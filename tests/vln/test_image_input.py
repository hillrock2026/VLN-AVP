"""Offline tests for the local-image -> wire-image-part boundary.

Nothing here contacts the inference server, opens a socket or imports Pillow:
the subject is a pure file-to-value conversion. The magic-byte cases use real
prefixes (and one genuinely valid 1x1 PNG), because the property under test is
that the media type comes from the file's **content**, never from its name.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from vln.vlm import image_input as image_input_module
from vln.vlm.image_input import (
    MAX_IMAGE_BYTES,
    SUPPORTED_MEDIA_TYPES,
    ImageInputError,
    ImagePart,
    UnsupportedImageFormatError,
    detect_media_type,
    load_image_part,
)
from vln.vlm.model_client import ModelCallError
from vln.vlm.server_client import UnsupportedServerInputError, build_image_messages

#: A genuinely valid 1x1 PNG, so the round-trip assertion below is meaningful.
_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)
_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
_GIF_BYTES = b"GIF89a" + b"\x00" * 16
_WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 16


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


# ----------------------------------------------------------------------
# Media-type detection is by content
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "data, expected",
    [
        (_ONE_PIXEL_PNG, "image/png"),
        (_JPEG_BYTES, "image/jpeg"),
        (_GIF_BYTES, "image/gif"),
        (_WEBP_BYTES, "image/webp"),
        (b"not an image at all", None),
        (b"", None),
    ],
)
def test_media_type_is_detected_from_magic_bytes(data: bytes, expected) -> None:
    assert detect_media_type(data[:16]) == expected


def test_supported_media_types_are_the_documented_ones() -> None:
    assert SUPPORTED_MEDIA_TYPES == ("image/png", "image/jpeg", "image/webp", "image/gif")


def test_the_file_extension_is_never_consulted(tmp_path: Path) -> None:
    """A PNG named ``.txt`` is a PNG; a text file named ``.png`` is not an image."""

    disguised_png = _write(tmp_path, "frame.txt", _ONE_PIXEL_PNG)
    assert load_image_part(disguised_png).media_type == "image/png"

    disguised_text = _write(tmp_path, "frame.png", b"just some text")
    with pytest.raises(UnsupportedImageFormatError):
        load_image_part(disguised_text)


# ----------------------------------------------------------------------
# The encoded part
# ----------------------------------------------------------------------


def test_loaded_part_encodes_the_exact_file_bytes(tmp_path: Path) -> None:
    path = _write(tmp_path, "one-pixel.png", _ONE_PIXEL_PNG)
    part = load_image_part(path)

    assert isinstance(part, ImagePart)
    assert part.media_type == "image/png"
    assert part.size_bytes == len(_ONE_PIXEL_PNG)
    assert part.sha256 == hashlib.sha256(_ONE_PIXEL_PNG).hexdigest()
    assert part.path == str(path.resolve())

    prefix = "data:image/png;base64,"
    assert part.data_uri.startswith(prefix)
    assert base64.b64decode(part.data_uri[len(prefix):]) == _ONE_PIXEL_PNG


def test_content_part_is_the_openai_image_url_shape(tmp_path: Path) -> None:
    part = load_image_part(_write(tmp_path, "one-pixel.png", _ONE_PIXEL_PNG))
    assert part.content_part() == {
        "type": "image_url",
        "image_url": {"url": part.data_uri},
    }


def test_evidence_description_carries_no_payload(tmp_path: Path) -> None:
    part = load_image_part(_write(tmp_path, "one-pixel.png", _ONE_PIXEL_PNG))
    description = part.safe_description()

    assert set(description) == {
        "path",
        "media_type",
        "size_bytes",
        "sha256",
        "content_part_type",
        "encoded_chars",
    }
    assert description["encoded_chars"] == len(part.data_uri)
    rendered = json.dumps(description)
    assert base64.b64encode(_ONE_PIXEL_PNG).decode() not in rendered
    assert "data:" not in rendered


def test_part_repr_hides_the_payload(tmp_path: Path) -> None:
    part = load_image_part(_write(tmp_path, "one-pixel.png", _ONE_PIXEL_PNG))
    assert "base64" not in repr(part)


def test_existing_repository_image_summary() -> None:
    """The four owner-supplied PNGs: real files, PNG, hashed, under the cap."""

    images = sorted((Path(__file__).resolve().parents[2] / "images").glob("*.png"))
    assert len(images) == 4
    for path in images:
        part = load_image_part(path)
        assert part.media_type == "image/png"
        assert part.size_bytes > 0 and part.size_bytes <= MAX_IMAGE_BYTES
        assert len(part.sha256) == 64


# ----------------------------------------------------------------------
# Fail closed on unusable input
# ----------------------------------------------------------------------


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ImageInputError, match="does not exist"):
        load_image_part(tmp_path / "absent.png")


def test_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ImageInputError, match="directory"):
        load_image_part(tmp_path)


def test_remote_url_is_rejected(tmp_path: Path) -> None:
    """The server would fetch a URL; this client refuses to hand it one."""

    with pytest.raises(ImageInputError, match="remote URL"):
        load_image_part("https://example.invalid/a.png")


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_path_is_rejected(value: str) -> None:
    with pytest.raises(ImageInputError, match="blank"):
        load_image_part(value)


@pytest.mark.parametrize("value", [None, 42, b"frame.png", ["frame.png"]])
def test_non_path_values_are_rejected(value: object) -> None:
    with pytest.raises(ImageInputError, match="must be a str or os.PathLike"):
        load_image_part(value)  # type: ignore[arg-type]


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ImageInputError, match="empty"):
        load_image_part(_write(tmp_path, "empty.png", b""))


def test_oversized_file_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(image_input_module, "MAX_IMAGE_BYTES", 8)
    with pytest.raises(ImageInputError, match="over the"):
        load_image_part(_write(tmp_path, "big.png", _ONE_PIXEL_PNG))


def test_unreadable_file_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "one-pixel.png", _ONE_PIXEL_PNG)
    path.chmod(0o000)
    try:
        readable = True
        try:
            path.read_bytes()
        except PermissionError:
            readable = False
        if readable:
            pytest.skip("this user can read a 0o000 file, so nothing is refused")
        with pytest.raises(ImageInputError, match="could not be read"):
            load_image_part(path)
    finally:
        path.chmod(0o644)


def test_every_failure_is_a_model_call_error(tmp_path: Path) -> None:
    """The pipeline's existing fail-closed handling must catch these too."""

    for bad in (tmp_path / "absent.png", tmp_path, "https://example.invalid/a.png"):
        with pytest.raises(ModelCallError):
            load_image_part(bad)


# ----------------------------------------------------------------------
# Message assembly
# ----------------------------------------------------------------------


def test_message_carries_the_image_first_and_the_instruction_second(
    tmp_path: Path,
) -> None:
    part = load_image_part(_write(tmp_path, "one-pixel.png", _ONE_PIXEL_PNG))
    messages = build_image_messages(part, "drive to slot P07")

    (message,) = messages
    assert message["role"] == "user"
    image_part, text_part = message["content"]
    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["url"] == part.data_uri
    assert text_part == {"type": "text", "text": "drive to slot P07"}


def test_message_keeps_the_instruction_verbatim(tmp_path: Path) -> None:
    """No templating or rewriting: the caller's instruction is passed through."""

    part = load_image_part(_write(tmp_path, "one-pixel.png", _ONE_PIXEL_PNG))
    instruction = "只返回 JSON。\nReturn exactly one object."
    (message,) = build_image_messages(part, instruction)
    assert message["content"][1]["text"] == instruction


@pytest.mark.parametrize("instruction", ["", "   ", "\n"])
def test_blank_instruction_is_refused(tmp_path: Path, instruction: str) -> None:
    part = load_image_part(_write(tmp_path, "one-pixel.png", _ONE_PIXEL_PNG))
    with pytest.raises(UnsupportedServerInputError, match="non-blank str"):
        build_image_messages(part, instruction)


@pytest.mark.parametrize("value", [None, 42, object()])
def test_non_image_part_is_refused(value: object) -> None:
    with pytest.raises(UnsupportedServerInputError, match="expected an ImagePart"):
        build_image_messages(value, "park")  # type: ignore[arg-type]
