"""Local image file -> the image part the confirmed server protocol accepts.

Why this exists: :mod:`vln.vlm.server_client` speaks to the *already running*
``taichu_server``, whose ``load_image`` (``taichu_server/server.py``) accepts
exactly three forms - a ``data:`` URI, an ``http(s)://`` URL, or a local path.
The URL form makes the **server** issue ``requests.get`` to an address this
repository never vetted, so it is refused here. Between the remaining two, the
``data:`` URI is chosen because it keeps the request self-contained and adds no
filesystem assumption on the server side; the format is confirmed by that
module's own source, not inferred from the endpoint name.

Only the syntax of the wire part is decided here. Nothing in this module knows
about ``AgentIntent``, the host client, IPC, or model output.

Safety boundaries (all fail closed, all before any network send):

* **Files only.** ``path`` must name an existing regular file that can be read.
  A ``http(s)://`` string, a directory, a device, a missing path, an empty file
  and a file over :data:`MAX_IMAGE_BYTES` are each refused with a distinct
  :class:`ImageInputError`.
* **Verified media type.** The MIME type is sniffed from the file's own magic
  bytes, never from its extension, so a mislabelled file cannot select a parser
  it does not match. Only the formats Pillow (which the server uses to decode)
  reliably supports *and* that this sniffer identifies unambiguously are
  accepted.
* **No secret in the clear.** :meth:`ImagePart.safe_description` reports the
  path, media type, byte count, SHA-256 and encoded length - the evidence a
  record needs - without any base64 payload.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from .model_client import ModelCallError

__all__ = [
    "MAX_IMAGE_BYTES",
    "SUPPORTED_MEDIA_TYPES",
    "ImagePart",
    "ImageInputError",
    "UnsupportedImageFormatError",
    "load_image_part",
    "detect_media_type",
]

#: Upper bound on an encoded image, in bytes. A parking-lot frame is a few
#: hundred kilobytes; this is a guard against handing the service an arbitrary
#: blob, not a quality target.
MAX_IMAGE_BYTES = 16 * 1024 * 1024

#: The media types this module will name, in the order it checks them. Each is
#: identified by a fixed magic prefix and decoded to RGB by the server's
#: ``Image.open(...).convert("RGB")``.
SUPPORTED_MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_GIF_MAGICS = (b"GIF87a", b"GIF89a")
_RIFF_MAGIC = b"RIFF"
_WEBP_TAG = b"WEBP"


class ImageInputError(ModelCallError):
    """A local image could not be turned into a wire image part.

    Subclasses :class:`~vln.vlm.model_client.ModelCallError`, so the pipeline's
    existing fail-closed handling applies unchanged: an unusable image is a
    model-boundary failure, never a request with a substituted or empty image.
    """


class UnsupportedImageFormatError(ImageInputError):
    """The file's magic bytes are not one of :data:`SUPPORTED_MEDIA_TYPES`."""


def detect_media_type(head: bytes) -> str | None:
    """Return the media type named by ``head``'s magic bytes, or ``None``.

    ``head`` needs only the first few bytes of the file. Detection is by
    content, so the file's name and extension are never consulted.
    """

    if head.startswith(_PNG_MAGIC):
        return "image/png"
    if head.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if head.startswith(_GIF_MAGICS):
        return "image/gif"
    if head.startswith(_RIFF_MAGIC) and head[8:12] == _WEBP_TAG:
        return "image/webp"
    return None


@dataclass(frozen=True)
class ImagePart:
    """One validated local image, ready to be placed in a request body.

    ``data_uri`` is the exact string the server's ``load_image`` decodes; it is
    excluded from ``repr`` so an accidental log line cannot dump a whole frame.
    """

    path: str
    media_type: str
    size_bytes: int
    sha256: str
    data_uri: str = field(repr=False)

    def content_part(self) -> dict:
        """Return the OpenAI-style content part for this image."""

        return {"type": "image_url", "image_url": {"url": self.data_uri}}

    def safe_description(self) -> dict:
        """Return the request evidence for this image, without the payload."""

        return {
            "path": self.path,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "content_part_type": "image_url",
            "encoded_chars": len(self.data_uri),
        }


def _reject_non_file(path: Path, raw: str) -> None:
    """Refuse anything that is not an existing, readable, regular file."""

    lowered = raw.strip().lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        raise ImageInputError(
            "image path is a remote URL; the server would fetch it over the "
            "network, which this client refuses - pass a local file"
        )
    if not path.exists():
        raise ImageInputError(f"image file does not exist: {path}")
    if path.is_dir():
        raise ImageInputError(f"image path is a directory, not a file: {path}")
    if not path.is_file():
        raise ImageInputError(f"image path is not a regular file: {path}")


def load_image_part(path: str | os.PathLike[str]) -> ImagePart:
    """Read ``path`` and return it as a validated :class:`ImagePart`.

    Every failure - a non-string path, a blank path, a URL, a missing or
    unreadable file, an empty or oversized file, an unsupported format - raises
    an :class:`ImageInputError` (or its
    :class:`UnsupportedImageFormatError` subclass) and no part is produced.
    """

    if isinstance(path, os.PathLike):
        path = os.fspath(path)
    if type(path) is not str:
        raise ImageInputError(
            f"image path must be a str or os.PathLike, got {type(path).__name__}"
        )
    if path.strip() == "":
        raise ImageInputError("image path is blank")

    candidate = Path(path)
    _reject_non_file(candidate, path)

    try:
        resolved = candidate.resolve()
        size = candidate.stat().st_size
    except OSError as exc:
        raise ImageInputError(
            f"image file could not be inspected: {type(exc).__name__}"
        ) from None
    if size == 0:
        raise ImageInputError(f"image file is empty: {resolved}")
    if size > MAX_IMAGE_BYTES:
        raise ImageInputError(
            f"image file is {size} bytes, over the {MAX_IMAGE_BYTES}-byte cap: "
            f"{resolved}"
        )

    try:
        data = candidate.read_bytes()
    except OSError as exc:
        raise ImageInputError(
            f"image file could not be read: {type(exc).__name__}"
        ) from None

    media_type = detect_media_type(data[:16])
    if media_type is None:
        raise UnsupportedImageFormatError(
            "image file is not a supported format (checked by content, not by "
            f"extension); supported: {list(SUPPORTED_MEDIA_TYPES)}: {resolved}"
        )

    encoded = base64.b64encode(data).decode("ascii")
    return ImagePart(
        path=str(resolved),
        media_type=media_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data_uri=f"data:{media_type};base64,{encoded}",
    )
