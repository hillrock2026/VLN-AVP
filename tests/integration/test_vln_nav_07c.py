"""Skip-gated 07C: natively legible targets, and where the size limit actually is.

07B left one question open: none of the four frames contains a *natively* large
target bay number, so it could only show that native small deck markings are not
read. 07C therefore looks for targets that are large enough to read **without any
magnification**, and measures the size limit directly instead of guessing at it.

What the frames actually contain (found by colour-thresholding the blue signage and
measuring each blob, then confirming by eye at 4-8x; no crop is used as an input
here):

  * ``NL-01`` IMG-01 target ``出口`` - the blue 出口/EXIT sign, 153x132 px, frame
    x 0-7%: the only genuinely large identifier in the whole set -> LEFT.
  * ``NL-02`` IMG-04 target ``出口`` - the same sign in the centre distance, only
    89x31 px -> AHEAD. Same target semantics as NL-01 at ~4x less area, so the pair
    separates "cannot find the target" from "cannot resolve the pixels".
  * ``NB-01`` IMG-04 target ``316`` -> RIGHT, ``NB-02`` IMG-02 target ``D50`` ->
    LEFT: native bay numbers, measured at ~45 px tall in 07B.
  * ``NH-01`` IMG-01 target ``P07`` and ``NH-02`` IMG-03 target ``P07``: the
    target-hidden controls. NH-01 matters most - it is the **same image** as NL-01,
    where the model just reported the EXIT sign, so it shows whether "not visible"
    is a real reading of that frame or a target-independent default.
  * text-only control: same prompt, no image.
  * ``test_glyph_height_ladder``: a synthetic diagnostic, *not* a parking scene and
    not part of the primary result, that finds the glyph height at which the
    pipeline starts reading rotated white-on-dark text. It exists to turn the
    blocker into a number for the next capture request.

The prompt is ``Variant.TARGET_DIRECTION`` unmodified; it was probed once on the
landmark target before this file was written and needed no change.

Scoring, the wire-SHA-256 check and the block parser are imported from the 07B
runner so both experiments classify identically; that module is not modified.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_vln_nav_07b import (  # noqa: E402
    _install_recorder,
    _parse_block,
    _score,
    server_client_module,
)

from vln.vlm.image_input import load_image_part  # noqa: E402
from vln.vlm.nav_prompt import Variant, build_nav_prompt  # noqa: E402
from vln.vlm.server_client import ZDTaichuServerBackend  # noqa: E402
from vln.vlm.zdtaichu_client import PreparedObservation  # noqa: E402

pytestmark = pytest.mark.integration

_EXPERIMENT_ENV = "VLN_ZDTAICHU_NAV_07C"
_ONLY_ENV = "VLN_ZDTAICHU_NAV_07C_ONLY"
_IMAGES_DIR = Path(__file__).resolve().parents[2] / "images"

_IMG01 = "17931c01d3fda4038c76944a334b3aef.png"
_IMG02 = "7328a8047ee41f088cceadaa7daa9b6d.png"
_IMG03 = "7ea84b439661950fcb5ec85d81011bfd.png"
_IMG04 = "9a6908511ef1211af2ae8483c103bb63.png"

#: ``gt_position`` is where the target sits in the frame, measured from the pixels.
SCENES = (
    {
        "id": "NL-01",
        "file": _IMG01,
        "target": "出口",
        "target_kind": "目标标识",
        "kind": "landmark: blue 出口/EXIT sign",
        "gt_visible": True,
        "gt_position": "LEFT",
        "acceptable": ("LEFT",),
        "evidence": "blue 出口/EXIT sign, 153x132 px, frame x 0-7%, upper-left wall",
        "known_bay_ids": (),
        "hard": False,
    },
    {
        "id": "NL-02",
        "file": _IMG04,
        "target": "出口",
        "target_kind": "目标标识",
        "kind": "landmark: blue 出口/EXIT sign",
        "gt_visible": True,
        "gt_position": "AHEAD",
        "acceptable": ("AHEAD",),
        "evidence": "blue 出口/EXIT sign, 89x31 px, frame x 51-55%, centre distance",
        "known_bay_ids": ("316", "283", "C64"),
        "hard": False,
    },
    {
        "id": "NB-01",
        "file": _IMG04,
        "target": "316",
        "target_kind": "车位编号",
        "kind": "native bay number",
        "gt_visible": True,
        "gt_position": "RIGHT",
        "acceptable": ("RIGHT",),
        "evidence": "bay id '316' painted on the deck, frame x 66.3-76.7%, ~45 px tall",
        "known_bay_ids": ("316", "283", "C64"),
        "hard": False,
    },
    {
        "id": "NB-02",
        "file": _IMG02,
        "target": "D50",
        "target_kind": "车位编号",
        "kind": "native bay number",
        "gt_visible": True,
        "gt_position": "LEFT",
        "acceptable": ("LEFT",),
        "evidence": "bay id 'D50' painted on the deck, frame x 5.7-15.2%, ~45 px tall",
        "known_bay_ids": ("D50", "D65"),
        "hard": False,
    },
    {
        "id": "NH-01",
        "file": _IMG01,
        "target": "P07",
        "target_kind": "车位编号",
        "kind": "target-hidden (same image as NL-01)",
        "gt_visible": False,
        "gt_position": "无法确定",
        "acceptable": ("无法确定",),
        "evidence": "no 'P07' anywhere; the same frame does carry the 出口/EXIT sign",
        "known_bay_ids": (),
        "hard": False,
    },
    {
        "id": "NH-02",
        "file": _IMG03,
        "target": "P07",
        "target_kind": "车位编号",
        "kind": "target-hidden",
        "gt_visible": False,
        "gt_position": "无法确定",
        "acceptable": ("无法确定",),
        "evidence": "no 'P07'; right-hand row shows partially legible 'D0x'",
        "known_bay_ids": (),
        "hard": False,
    },
)

#: Key positive samples repeated at temperature 0 to see whether the answer is stable.
_REPEAT_IDS = ("NL-01", "NL-02")

#: (glyph height in px, rotation in degrees) for the synthetic legibility ladder.
#: 180 degrees is the deck paint's orientation in the garage; 0 is the upright
#: control that separates "too small to read" from "does not undo the rotation".
_LADDER_CASES = ((30, 180), (60, 180), (120, 180), (240, 180), (60, 0), (240, 0))
_LADDER_FRAME = (2100, 1180)


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


def _emit(record: dict) -> None:
    print("NAV07C " + json.dumps(record, ensure_ascii=False))


def _round(
    scene: dict, *, thinking: bool = False, max_new_tokens: int = 400, target_note: str = ""
) -> dict:
    """One image round whose prompt follows this scene's target *and* target kind.

    07B's ``_one_round`` hard-codes the bay-number wording, and NL-02 showed the
    model rejecting a visible sign as "not a bay number", so 07C has to build the
    prompt itself. The recorder, the block parser and the scorer are still 07B's,
    so both experiments classify identically.
    """

    image_path = _IMAGES_DIR / scene["file"]
    if not image_path.is_file():
        pytest.skip(f"scene image missing: {image_path}")

    prompt = build_nav_prompt(
        Variant.TARGET_DIRECTION,
        target=scene["target"],
        target_kind=scene["target_kind"],
        target_note=target_note,
    )
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
        "target_kind": scene["target_kind"],
        "thinking": thinking,
        "temperature": 0.0,
        "prompt_chars": len(prompt),
        "image": part.safe_description(),
        "wire_image_matches_file": hashlib.sha256(base64.b64decode(encoded)).hexdigest()
        == part.sha256,
        "content_part_types": [item["type"] for item in message["content"]],
        "usage": response.get("usage"),
        "finish_reason": choice.get("finish_reason"),
        "reasoning_content_chars": len(choice["message"].get("reasoning_content") or ""),
        "raw": raw,
        "block": _parse_block(raw),
    }


def _deliver(scene: dict, *, thinking: bool = False) -> None:
    record = _round(scene, thinking=thinking)
    assert record["wire_image_matches_file"], "the wire image was not the file's bytes"
    scored = _score(scene, record)
    scored["kind"] = scene["kind"]
    _emit({**record, "scored": scored})


@pytest.mark.parametrize("scene", _wanted(), ids=[scene["id"] for scene in _wanted()])
def test_native_target_round(scene: dict) -> None:
    _gate()
    _deliver(scene)


@pytest.mark.parametrize("scene_id", _REPEAT_IDS)
def test_repeat_stability(scene_id: str) -> None:
    """Two extra samples of a key positive scene, same image, same target."""

    _gate()
    scene = next(entry for entry in SCENES if entry["id"] == scene_id)
    samples = [_round(scene) for _ in range(2)]
    raws = [sample["raw"] for sample in samples]
    _emit(
        {
            "phase": "repeat-stability",
            "scene_id": scene_id,
            "target": scene["target"],
            "raw_1": raws[0],
            "raw_2": raws[1],
            "identical": raws[0] == raws[1],
            "blocks": [sample["block"] for sample in samples],
        }
    )


def test_text_only_control() -> None:
    """The same landmark prompt with no image: is 'Visible: 否' the default?"""

    _gate()
    prompt = build_nav_prompt(
        Variant.TARGET_DIRECTION, target="出口", target_kind="目标标识"
    )
    backend = ZDTaichuServerBackend(
        max_new_tokens=400, temperature=0.0, enable_thinking=False, timeout=180.0
    )
    calls, original = _install_recorder()
    try:
        raw = backend.generate(PreparedObservation(text=prompt), "")
    finally:
        server_client_module._OPENER.open = original
    assert len(calls) == 1
    _emit(
        {
            "phase": "text-only-control",
            "target": "出口",
            "note": "no image part in this request",
            "raw": raw,
            "block": _parse_block(raw),
        }
    )


@pytest.mark.parametrize("height,rotation", _LADDER_CASES)
def test_glyph_height_ladder(height: int, rotation: int, tmp_path) -> None:
    """SYNTHETIC DIAGNOSTIC (not a parking scene, not a 07C primary result).

    Finds the glyph height at which the pipeline starts reading rotated
    white-on-dark text at the frame size of the real captures, so the next capture
    request can specify a target size instead of a guess.
    """

    _gate()
    pytest.importorskip("PIL.Image", reason="generating the ladder needs Pillow")

    from PIL import Image, ImageDraw, ImageFont

    frame = Image.new("RGB", _LADDER_FRAME, (24, 26, 28))
    draw = ImageDraw.Draw(frame)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", height
        )
    except Exception:  # pragma: no cover - font missing
        pytest.skip("no scalable font available for the ladder")

    label = "D50"
    box = draw.textbbox((0, 0), label, font=font)
    strip = Image.new("RGB", (box[2] - box[0] + 20, box[3] - box[1] + 20), (24, 26, 28))
    ImageDraw.Draw(strip).text((10, 10 - box[1]), label, font=font, fill=(196, 198, 200))
    strip = strip.rotate(rotation)  # 180 matches the deck paint orientation
    frame.paste(
        strip,
        (_LADDER_FRAME[0] // 2 - strip.width // 2, _LADDER_FRAME[1] // 2 - strip.height // 2),
    )
    path = tmp_path / f"ladder-{height}px-rot{rotation}.png"
    frame.save(path)

    prompt = "图中有一处白色数字标识，请只回答该数字本身，不要解释。"
    backend = ZDTaichuServerBackend(
        max_new_tokens=32, temperature=0.0, enable_thinking=False, timeout=180.0
    )
    calls, original = _install_recorder()
    try:
        raw = backend.generate_image(str(path), prompt)
    finally:
        server_client_module._OPENER.open = original

    _emit(
        {
            "phase": "glyph-height-ladder",
            "note": "synthetic diagnostic; not a parking scene",
            "glyph_height_px": height,
            "rotation_degrees": rotation,
            "rendered_number": label,
            "frame": list(_LADDER_FRAME),
            "raw": raw,
            "read_correctly": raw.strip().strip("`*\"'。 ") == label,
        }
    )


#: Supplementary, and *not* part of the primary matrix: the same two native bay
#: numbers, but with one extra sentence telling the model the deck paint is
#: inverted. The ladder in this file shows the failure is orientation rather than
#: size, so this probe asks whether a rotation hint is enough to recover the read.
_ROTATION_HINT = "注意：地面上的车位编号在画面里是倒置的（旋转了 180 度），请先把它转正再读。"


@pytest.mark.parametrize("scene_id", ("NB-01", "NB-02"))
def test_supplementary_rotation_hint_probe(scene_id: str) -> None:
    """Supplementary probe with a modified prompt - labelled, not a primary result."""

    _gate()
    scene = next(entry for entry in SCENES if entry["id"] == scene_id)
    record = _round(scene, target_note=_ROTATION_HINT)
    assert record["wire_image_matches_file"], "the wire image was not the file's bytes"
    _emit(
        {
            **record,
            "phase": "supplementary-rotation-hint",
            "note": "primary matrix prompt plus one rotation-hint sentence",
            "scored": {**_score(scene, record), "kind": scene["kind"]},
        }
    )
