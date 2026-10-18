"""Skip-gated 07B experiment: does the model find a *visible* target bay and say
which way to go?

07A established that the model perceives these images (it reads the column
letters) and that the prompt, not the image path, caused 06A's template echo.
What 07A could not test is target detection, because none of the four frames
contains the ``P07`` the prompt asked for. 07B therefore targets bay identifiers
that are **actually painted on the deck in the owner's existing four frames**,
with ground truth read from zoomed crops of the pixels.

Scenes (all from `images/`, no new or generated image is introduced):

  * ``TV-01`` IMG-02, target ``D50`` - bay id on the deck at x 5.7-15.2% of the
    frame, i.e. clearly LEFT.
  * ``TV-02`` IMG-04, target ``316`` - bay id at x 66.3-76.7%, clearly RIGHT.
  * ``TV-03`` IMG-02, target ``D65`` - bay id at x 48.0-57.5%, just right of
    centre; the same image as TV-01, so a LEFT/RIGHT difference between TV-01 and
    TV-03 cannot come from the image alone.
  * ``TV-04`` IMG-04, target ``C64`` - bay id at x 18.6-29.1% on the bottom edge
    with the glyphs clipped by the frame: a hard sample, not primary evidence.
  * ``NEG-01`` IMG-01, target ``P07`` - no bay identifier is legible anywhere, so
    "not visible" is the only correct answer.
  * ``NEG-02`` IMG-03, target ``P07`` - the right-hand row shows partially legible
    ``D0x`` markings; there is no ``P07``.

Two controls guard against reading a coincidence as a result: a text-only round of
the same prompt (does the answer depend on the image at all?) and a repeat of
TV-01 (is the answer stable at temperature 0?).

The judgement is recorded, never asserted: a wrong or refused answer is a real
finding about the model, and nothing here relaxes a contract or touches the
Kernel. The one structural assertion is that the image bytes really went out on
the wire, checked by decoding the recorded request body and comparing its SHA-256
with the file's.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path

import pytest

from vln.vlm import server_client as server_client_module
from vln.vlm.image_input import load_image_part
from vln.vlm.nav_prompt import (
    DIRECTION_ANSWERS,
    POSITION_ANSWERS,
    UNKNOWN_ANSWER,
    VISIBLE_ANSWERS,
    Variant,
    build_nav_prompt,
)
from vln.vlm.server_client import ZDTaichuServerBackend
from vln.vlm.zdtaichu_client import PreparedObservation

pytestmark = pytest.mark.integration

_EXPERIMENT_ENV = "VLN_ZDTAICHU_NAV_07B"
_ONLY_ENV = "VLN_ZDTAICHU_NAV_07B_ONLY"
_IMAGES_DIR = Path(__file__).resolve().parents[2] / "images"

#: ``gt_position`` is where the target sits in the frame the model is given, read
#: from the pixels. ``acceptable`` lists answers that are also defensible for that
#: framing (a bay just right of centre can legitimately be called AHEAD).
SCENES = (
    {
        "id": "TV-01",
        "file": "7328a8047ee41f088cceadaa7daa9b6d.png",
        "target": "D50",
        "gt_visible": True,
        "gt_position": "LEFT",
        "acceptable": ("LEFT",),
        "evidence": "bay id 'D50' painted on the deck, frame x 5.7-15.2%, lower-left",
        "known_bay_ids": ("D50", "D65"),
        "hard": False,
    },
    {
        "id": "TV-02",
        "file": "9a6908511ef1211af2ae8483c103bb63.png",
        "target": "316",
        "gt_visible": True,
        "gt_position": "RIGHT",
        "acceptable": ("RIGHT",),
        "evidence": "bay id '316' painted on the deck, frame x 66.3-76.7%, right",
        "known_bay_ids": ("316", "283", "C64"),
        "hard": False,
    },
    {
        "id": "TV-03",
        "file": "7328a8047ee41f088cceadaa7daa9b6d.png",
        "target": "D65",
        "gt_visible": True,
        "gt_position": "RIGHT",
        "acceptable": ("RIGHT", "AHEAD"),
        "evidence": "bay id 'D65' painted on the deck, frame x 48.0-57.5%, just right of centre",
        "known_bay_ids": ("D50", "D65"),
        "hard": False,
    },
    {
        "id": "TV-04",
        "file": "9a6908511ef1211af2ae8483c103bb63.png",
        "target": "C64",
        "gt_visible": True,
        "gt_position": "LEFT",
        "acceptable": ("LEFT",),
        "evidence": "bay id 'C64' at frame x 18.6-29.1% on the bottom edge, glyphs clipped",
        "known_bay_ids": ("316", "283", "C64"),
        "hard": True,
    },
    {
        "id": "NEG-01",
        "file": "17931c01d3fda4038c76944a334b3aef.png",
        "target": "P07",
        "gt_visible": False,
        "gt_position": UNKNOWN_ANSWER,
        "acceptable": (UNKNOWN_ANSWER,),
        "evidence": "no bay identifier is legible; the only letters are the column marker 'C'",
        "known_bay_ids": (),
        "hard": False,
    },
    {
        "id": "NEG-02",
        "file": "7ea84b439661950fcb5ec85d81011bfd.png",
        "target": "P07",
        "gt_visible": False,
        "gt_position": UNKNOWN_ANSWER,
        "acceptable": (UNKNOWN_ANSWER,),
        "evidence": "right-hand row shows partially legible 'D0x' markings; no 'P07'",
        "known_bay_ids": (),
        "hard": False,
    },
)

_FIELDS = ("Target", "Visible", "Relative position", "Next direction", "Evidence")
_FIELD_RE = re.compile(
    r"^\s*[*`#\-\s]*(Target|Visible|Relative position|Next direction|Evidence)\s*[:：]\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
#: A bay-id-shaped token: a letter+digits or a 3-digit number.
_BAY_TOKEN_RE = re.compile(r"\b(?:[A-Za-z]\d{2}|[1-9]\d{2})\b")


class _RecordingResponse:
    """Tee ``read`` off the real response so the wire body can be recorded."""

    def __init__(self, response, sink: dict) -> None:
        self._response = response
        self._sink = sink

    def read(self, limit: int | None = None) -> bytes:
        data = self._response.read(limit)
        self._sink["response_body"] = data
        return data

    def __enter__(self) -> "_RecordingResponse":
        self._response.__enter__()
        return self

    def __exit__(self, *exc: object) -> object:
        return self._response.__exit__(*exc)

    def __getattr__(self, name: str) -> object:
        return getattr(self._response, name)


def _install_recorder():
    original = server_client_module._OPENER.open
    calls: list = []

    def _open(request, timeout=None):
        calls.append({"body": request.data, "authorization": request.get_header("Authorization")})
        return _RecordingResponse(original(request, timeout=timeout), calls[-1])

    server_client_module._OPENER.open = _open
    return calls, original


def _gate() -> None:
    if os.environ.get(_EXPERIMENT_ENV) != "1":
        pytest.skip(
            f"{_EXPERIMENT_ENV} is not set to 1; this sends real multimodal "
            "requests to the local inference service"
        )
    if not _IMAGES_DIR.is_dir():
        pytest.skip(f"image directory not found: {_IMAGES_DIR}")


def _wanted() -> list:
    only = os.environ.get(_ONLY_ENV, "").strip().upper()
    if not only:
        return list(SCENES)
    tokens = {token.strip() for token in only.split(",") if token.strip()}
    selected = [scene for scene in SCENES if scene["id"].upper() in tokens]
    if not selected:
        pytest.fail(f"${_ONLY_ENV}={only!r} matched no scene")
    return selected


def _parse_block(raw: str) -> dict:
    """Pull the five declared fields out of the answer, as written."""

    found: dict = {}
    for name, value in _FIELD_RE.findall(raw):
        key = name.strip().lower()
        if key not in found:  # first occurrence wins; later ones are not merged
            found[key] = value.strip().strip("`*\"'。 ")
    return {field: found.get(field.lower()) for field in _FIELDS}


def _one_round(scene: dict, *, thinking: bool = False, max_new_tokens: int = 400):
    """Send exactly one image round for ``scene`` and return its record."""

    image_path = _IMAGES_DIR / scene["file"]
    if not image_path.is_file():
        pytest.skip(f"scene image missing: {image_path}")

    prompt = build_nav_prompt(Variant.TARGET_DIRECTION, target=scene["target"])
    part = load_image_part(image_path)
    backend = ZDTaichuServerBackend(
        max_new_tokens=max_new_tokens,
        temperature=0.0,
        enable_thinking=thinking,
        timeout=180.0,
    )

    calls, original = _install_recorder()
    try:
        raw = backend.generate_image(str(image_path), prompt)
    finally:
        server_client_module._OPENER.open = original

    assert type(raw) is str
    assert len(calls) == 1, "one round must be exactly one POST"

    payload = json.loads(calls[0]["body"].decode("utf-8"))
    (message,) = payload["messages"]
    encoded = message["content"][0]["image_url"]["url"].partition(";base64,")[2]
    response = json.loads(calls[0]["response_body"].decode("utf-8"))
    choice = response["choices"][0]

    return {
        "scene_id": scene["id"],
        "target": scene["target"],
        "thinking": thinking,
        "temperature": 0.0,
        "image": part.safe_description(),
        "wire_image_matches_file": hashlib.sha256(base64.b64decode(encoded)).hexdigest()
        == part.sha256,
        "content_part_types": [item["type"] for item in message["content"]],
        "authorization_header_present": calls[0]["authorization"] is not None,
        "prompt_chars": len(prompt),
        "usage": response.get("usage"),
        "finish_reason": choice.get("finish_reason"),
        "reasoning_content_chars": len(choice["message"].get("reasoning_content") or ""),
        "raw": raw,
        "block": _parse_block(raw),
    }


#: Chinese renderings of the allowed English answer tokens. The model sometimes
#: answers 右侧 for RIGHT; the semantics are unambiguous, so the value is mapped and
#: the deviation is recorded as a vocabulary-compliance miss rather than treated as
#: a missing answer.
_ANSWER_ALIASES = {
    "左侧": "LEFT",
    "右边": "RIGHT",
    "右侧": "RIGHT",
    "左边": "LEFT",
    "前方": "AHEAD",
    "正前方": "AHEAD",
    "直行": "STRAIGHT",
    "向前": "STRAIGHT",
}


def _normalize_visible(value: str | None) -> str | None:
    """Map the visibility answer onto the closed vocabulary ``{是, 否}``."""

    if value is None:
        return None
    token = value.strip().strip("`*\"'。 ").lower()
    if token in ("是", "yes", "true"):
        return "是"
    if token in ("否", "no", "false"):
        return "否"
    return None


def _normalize_answer(value: str | None, vocabulary: tuple) -> str | None:
    """Map a position/direction answer onto ``vocabulary``, via the aliases."""

    if value is None:
        return None
    token = value.strip().strip("`*\"'。 ")
    upper = token.upper()
    if upper in vocabulary:
        return upper
    return _ANSWER_ALIASES.get(token)


def _score(scene: dict, record: dict) -> dict:
    """Score one round against the ground truth, and record rather than assert."""

    raw = record["raw"]
    block = record["block"]
    upper = raw.upper()

    visible_raw = block["Visible"]
    visible = _normalize_visible(visible_raw)
    position = _normalize_answer(block["Relative position"], POSITION_ANSWERS)
    direction = _normalize_answer(block["Next direction"], DIRECTION_ANSWERS)
    target_field = block["Target"]

    # A bay-id token that is not in this image is a fabricated identifier.
    tokens = {token.upper() for token in _BAY_TOKEN_RE.findall(raw)}
    foreign = sorted(
        token
        for token in tokens
        if token not in {known.upper() for known in scene["known_bay_ids"]}
        and token != scene["target"].upper()
        and not (scene["target"].startswith("P") and token == "P07")
    )

    visibility_correct = (
        None
        if visible not in VISIBLE_ANSWERS
        else (visible == VISIBLE_ANSWERS[0]) == bool(scene["gt_visible"])
    )
    position_correct = (
        None if position is None or position not in POSITION_ANSWERS
        else (
            (position == UNKNOWN_ANSWER) if not scene["gt_visible"]
            else position in scene["acceptable"]
        )
    )
    direction_correct = (
        None if direction is None or direction not in DIRECTION_ANSWERS
        else (
            (direction == UNKNOWN_ANSWER) if not scene["gt_visible"]
            else direction in tuple(
                "STRAIGHT" if answer == "AHEAD" else answer for answer in scene["acceptable"]
            )
        )
    )
    claimed_visible = visible == VISIBLE_ANSWERS[0]
    return {
        "ground_truth": {
            "target_visible": scene["gt_visible"],
            "position": scene["gt_position"],
            "acceptable_answers": list(scene["acceptable"]),
            "pixel_evidence": scene["evidence"],
            "hard_sample": scene["hard"],
        },
        "block_parsed": {name: block[name] for name in _FIELDS},
        "block_complete": all(block[name] is not None for name in _FIELDS),
        "vocabulary_compliance": {
            # Checked against what the model actually wrote, before normalisation:
            # ``右侧`` and ``no`` are deviations even though their meaning is clear.
            "visible_used_the_allowed_token": (visible_raw or "").strip() in VISIBLE_ANSWERS,
            "position_used_an_allowed_token": (block["Relative position"] or "").strip()
            in POSITION_ANSWERS,
            "direction_used_an_allowed_token": (block["Next direction"] or "").strip()
            in DIRECTION_ANSWERS,
        },
        "target_field_echoes_the_request": (target_field or "").upper()
        == scene["target"].upper(),
        "visibility_correct": visibility_correct,
        "position_correct": position_correct,
        "direction_correct": direction_correct,
        "fabricated_visibility_claim": claimed_visible and not scene["gt_visible"],
        "missed_a_visible_target": (not claimed_visible) and bool(scene["gt_visible"]),
        "foreign_bay_tokens": foreign,
        "cites_any_real_bay_id": any(
            known.upper() in upper for known in scene["known_bay_ids"]
        )
        or scene["target"].upper() in upper,
        "cites_the_column_letters": "立柱" in raw and re.search(r"[ABC]", raw) is not None,
        "mentions_exit_or_arrow": ("EXIT" in upper) or ("出口" in raw) or ("箭头" in raw),
        "mentions_lane_or_aisle": ("通道" in raw) or ("车道" in raw),
    }


def _emit(record: dict) -> None:
    print("NAV07B " + json.dumps(record, ensure_ascii=False))


def _deliver(scene: dict, *, thinking: bool = False, max_new_tokens: int = 400) -> None:
    record = _one_round(scene, thinking=thinking, max_new_tokens=max_new_tokens)
    assert record["wire_image_matches_file"], "the wire image was not the file's bytes"
    _emit({**record, "scored": _score(scene, record)})


@pytest.mark.parametrize("scene", _wanted(), ids=[scene["id"] for scene in _wanted()])
def test_target_direction_round(scene: dict) -> None:
    _gate()
    _deliver(scene)


def test_repeat_stability_on_tv01() -> None:
    """Temperature 0, same request twice: is the answer stable?"""

    _gate()
    scene = next(entry for entry in SCENES if entry["id"] == "TV-01")
    first = _one_round(scene)
    second = _one_round(scene)
    _emit(
        {
            "phase": "repeat-stability",
            "scene_id": "TV-01",
            "raw_first": first["raw"],
            "raw_second": second["raw"],
            "identical": first["raw"] == second["raw"],
        }
    )


#: Derived frames: a tight crop around a target bay id, so the requested number is
#: several times larger than in the full frame. This separates "the model cannot
#: read a small rotated deck marking" from "the model cannot detect a target at
#: all". The pixels are the owner's own render - only the framing changes - and the
#: source file, crop box and derived SHA-256 are recorded with the result.
FOCUS_CROPS = (
    {
        "id": "TVF-01",
        "file": "7328a8047ee41f088cceadaa7daa9b6d.png",
        "box": (120, 900, 520, 1100),
        "target": "D50",
        "gt_visible": True,
        "gt_position": "LEFT",
        "acceptable": ("LEFT",),
        "evidence": "crop around the 'D50' deck marking; the id sits at ~20% of the crop width",
        "known_bay_ids": ("D50", "D65", "D66", "D67"),
        "hard": False,
    },
    {
        "id": "TVF-02",
        "file": "9a6908511ef1211af2ae8483c103bb63.png",
        "box": (1150, 850, 1650, 1150),
        "target": "316",
        "gt_visible": True,
        "gt_position": "RIGHT",
        "acceptable": ("RIGHT",),
        "evidence": "crop around the '316' deck marking; the id sits at ~70% of the crop width",
        "known_bay_ids": ("316",),
        "hard": False,
    },
)


def test_text_only_control() -> None:
    """The same prompt with no image: how much of the answer is the image?"""

    _gate()
    scene = next(entry for entry in SCENES if entry["id"] == "TV-01")
    prompt = build_nav_prompt(Variant.TARGET_DIRECTION, target=scene["target"])
    backend = ZDTaichuServerBackend(
        max_new_tokens=400, temperature=0.0, enable_thinking=False, timeout=180.0
    )

    calls, original = _install_recorder()
    try:
        raw = backend.generate(PreparedObservation(text=prompt), "")
    finally:
        server_client_module._OPENER.open = original
    assert len(calls) == 1

    payload = json.loads(calls[0]["body"].decode("utf-8"))
    content = payload["messages"][0]["content"]
    _emit(
        {
            "phase": "text-only-control",
            "target": scene["target"],
            "note": "no image part in this request",
            "content_part_types": [
                item["type"] if isinstance(item, dict) else type(item).__name__
                for item in (content if isinstance(content, list) else [content])
            ],
            "raw": raw,
            "block": _parse_block(raw),
        }
    )


@pytest.mark.parametrize("scene", FOCUS_CROPS, ids=[scene["id"] for scene in FOCUS_CROPS])
def test_focus_crop_target_is_detectable(scene: dict, tmp_path) -> None:
    """Re-ask with the target bay id magnified: small-text OCR, or no detection?

    The crop is generated at run time with Pillow, so nothing binary is added to
    the repository and the experiment stays reproducible wherever Pillow exists.
    """

    _gate()
    pytest.importorskip("PIL.Image", reason="generating the derived crop needs Pillow")

    from PIL import Image

    source = _IMAGES_DIR / scene["file"]
    if not source.is_file():
        pytest.skip(f"source image missing: {source}")

    with Image.open(source) as full:
        cropped = full.crop(scene["box"])
        derived = tmp_path / f"{scene['id']}-{scene['target']}.png"
        cropped.save(derived)

    part = load_image_part(derived)
    record = _one_round({**scene, "file": str(derived)})
    record["derived_from"] = {
        "source_file": scene["file"],
        "source_sha256": load_image_part(source).sha256,
        "crop_box": list(scene["box"]),
        "target_scale_up": round(
            Image.open(source).width / (scene["box"][2] - scene["box"][0]), 2
        ),
        "derived_sha256": part.sha256,
    }
    assert record["wire_image_matches_file"], "the wire image was not the crop's bytes"
    _emit({**record, "scored": _score(scene, record)})
