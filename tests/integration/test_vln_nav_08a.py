"""Skip-gated 08A: can a target parking-space *identity*, expressed in a visual
form the model has proven it can read, enter the real navigation chain?

The question 07C left open is narrow and concrete. 07C measured that native
ground-painted bay numbers are painted 180 degrees rotated and are misread at
every glyph height tested, while **upright** identifiers are found with the
correct position and direction. 08A therefore asks only this: when the target
identity is carried by an upright, natively legible marking, does the model
return *both* the right identity *and* the right discrete direction, at native
framing, stably?

What the four owner frames actually contain, established by eye at 5-8x on
crops and by a hue-masked blue-signage blob inventory (the 07C method):

  * **upright and natively legible.** (a) the blue 出口/EXIT signs - 153x132 px
    at frame x 0-7% in IMG-01, 89x31 px at x 51-55% in IMG-04; (b) the pillar
    zone letters - orange ``C`` in IMG-01 and IMG-04, teal ``A`` in IMG-02,
    navy ``B`` in IMG-03, every one of them upright and large.
  * **rotated 180 degrees.** *every* bay number painted on the deck: ``D50``,
    ``D65``, ``D63``, ``D64``, ``316``, ``283``, ``364``, ``C60``/``196``.
  * **absent.** any wall-mounted bay number, any hanging bay sign, and any
    upright bay *number* of any kind. IMG-01's pillars and wall signs all read
    ``C``; there is no ``A`` anywhere in it.

So there is no upright **bay number** in this dataset, and 08A must not
manufacture one (no rotation, no crop, no pasting a number onto a wall). What
does exist is an upright *parking-space* identity - the zone letter the garage
itself paints on every pillar - which is the closest thing in these pixels to a
bay identity the model can actually read. It is used here, labelled for exactly
what it is, and never presented as a bay number.

Scoring separates the two things the earlier tasks conflated (the task requires
this explicitly): **identity** - did the model read the marking it was asked
for - and **direction** - did it say which way, *counted only where the identity
was right*. ``Variant.TARGET_DIRECTION`` was given one additive field for this
(``Identified as``): the ``Target`` field is by design a copy of the requested
label, so without it a correct-looking answer could not be told apart from
target-name anchoring.

Direction ground truth is the 07B convention - the target's position in the
frame - and for the zone letters it is **not well posed** (the same letter sits
on pillars left and right), so those cases score identity only and are flagged
``direction_well_posed: False`` rather than being quietly scored as failures.

The block parser, the wire-SHA-256 image check and the shared visibility /
position / direction / fabrication scoring are imported from the 07B runner, so
all three experiments classify identically; that module is not modified. Raw
model output is kept for every case (console plus ``VLN_ZDTAICHU_NAV_08A_OUT``
if set) because the follow-up review has to judge anchoring and guesswork, and
a PASS/FAIL alone cannot show either.

Nothing here changes ``AgentIntent``, ``parse_model_output``, any contract, the
Kernel, ``parking.move``, the Runtime or the service. The one code change is the
opt-in prompt field, off by default, so the 07B and 07C prompts stay
byte-identical.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
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
from vln.vlm.nav_prompt import (  # noqa: E402
    IDENTITY_FIELD,
    UNKNOWN_ANSWER,
    Variant,
    build_nav_prompt,
)
from vln.vlm.server_client import ZDTaichuServerBackend  # noqa: E402
from vln.vlm.zdtaichu_client import PreparedObservation  # noqa: E402

pytestmark = pytest.mark.integration

_EXPERIMENT_ENV = "VLN_ZDTAICHU_NAV_08A"
_ONLY_ENV = "VLN_ZDTAICHU_NAV_08A_ONLY"
_REPEAT_ONLY_ENV = "VLN_ZDTAICHU_NAV_08A_REPEAT_ONLY"
_OUT_ENV = "VLN_ZDTAICHU_NAV_08A_OUT"
_IMAGES_DIR = Path(__file__).resolve().parents[2] / "images"

_IMG01 = "17931c01d3fda4038c76944a334b3aef.png"
_IMG02 = "7328a8047ee41f088cceadaa7daa9b6d.png"
_IMG03 = "7ea84b439661950fcb5ec85d81011bfd.png"
_IMG04 = "9a6908511ef1211af2ae8483c103bb63.png"

#: Every entry carries the keys 07B's ``_score`` reads (``target``,
#: ``gt_visible``, ``gt_position``, ``acceptable``, ``evidence``,
#: ``known_bay_ids``, ``hard``) plus 08A's ``gt_identity``, ``category`` and
#: ``direction_well_posed``. ``gt_identity`` is what the pixels really show at
#: the requested target; ``None`` on a hidden control, where the correct
#: identity answer is "not the requested one".
SCENES = (
    {
        "id": "U-EXIT-LEFT",
        "file": _IMG01,
        "target": "出口",
        "target_kind": "目标标识",
        "category": "upright-identity",
        "gt_visible": True,
        "gt_identity": "出口",
        "gt_position": "LEFT",
        "acceptable": ("LEFT",),
        "direction_well_posed": True,
        "evidence": "blue 出口/EXIT sign, 153x132 px, frame x 0-7% y 31-41%, upper-left wall",
        "known_bay_ids": (),
        "hard": False,
    },
    {
        "id": "U-EXIT-AHEAD",
        "file": _IMG04,
        "target": "出口",
        "target_kind": "目标标识",
        "category": "upright-identity",
        "gt_visible": True,
        "gt_identity": "出口",
        "gt_position": "AHEAD",
        "acceptable": ("AHEAD",),
        "direction_well_posed": True,
        "evidence": "blue 出口/EXIT sign, 89x31 px, frame x 51-55% y 44-47%, centre distance",
        "known_bay_ids": ("316", "283", "364"),
        "hard": False,
    },
    {
        "id": "U-ZONE-A",
        "file": _IMG02,
        "target": "A",
        "target_kind": "立柱分区字母",
        "category": "upright-identity",
        "gt_visible": True,
        "gt_identity": "A",
        "gt_position": "RIGHT",
        "acceptable": ("RIGHT",),
        # The same letter sits on the near-right pillar and on smaller pillars to
        # the left, so "which way" has no single right answer: identity is scored,
        # direction is recorded and excluded from the direction statistic.
        "direction_well_posed": False,
        "evidence": (
            "upright white 'A' on the teal pillar band; nearest instance frame "
            "x 69-77% y 66-81% (RIGHT), smaller ones at x 27% y 57% and in the left distance"
        ),
        "known_bay_ids": ("D50", "D65", "D63", "D64"),
        "hard": False,
    },
    {
        "id": "U-ZONE-C",
        "file": _IMG04,
        "target": "C",
        "target_kind": "立柱分区字母",
        "category": "upright-identity",
        "gt_visible": True,
        "gt_identity": "C",
        "gt_position": "RIGHT",
        "acceptable": ("RIGHT",),
        "direction_well_posed": False,
        "evidence": (
            "upright white 'C' on the orange pillar bands; nearest instance frame "
            "x 63-72% y 55-75% (RIGHT), smaller ones at x 8% and in the distance"
        ),
        "known_bay_ids": ("316", "283", "364"),
        "hard": False,
    },
    {
        "id": "B-D50",
        "file": _IMG02,
        "target": "D50",
        "target_kind": "车位编号",
        "category": "rotated-bay-number",
        "gt_visible": True,
        "gt_identity": "D50",
        "gt_position": "LEFT",
        "acceptable": ("LEFT",),
        "direction_well_posed": True,
        "evidence": "bay id 'D50' painted on the deck, frame x 5.7-15.2%, rotated 180 deg",
        "known_bay_ids": ("D50", "D65", "D63", "D64"),
        "hard": False,
    },
    {
        "id": "B-316",
        "file": _IMG04,
        "target": "316",
        "target_kind": "车位编号",
        "category": "rotated-bay-number",
        "gt_visible": True,
        "gt_identity": "316",
        "gt_position": "RIGHT",
        "acceptable": ("RIGHT",),
        "direction_well_posed": True,
        "evidence": "bay id '316' painted on the deck, frame x 78-100% y 86-100%, rotated 180 deg",
        "known_bay_ids": ("316", "283", "364"),
        "hard": False,
    },
    {
        "id": "N-P07-IMG01",
        "file": _IMG01,
        "target": "P07",
        "target_kind": "车位编号",
        "category": "hidden-control",
        "gt_visible": False,
        "gt_identity": None,
        "gt_position": UNKNOWN_ANSWER,
        "acceptable": (UNKNOWN_ANSWER,),
        "direction_well_posed": False,
        "evidence": "no legible bay number anywhere; the only upright letters are the zone 'C'",
        "known_bay_ids": (),
        "hard": False,
    },
    {
        "id": "N-P07-IMG03",
        "file": _IMG03,
        "target": "P07",
        "target_kind": "车位编号",
        "category": "hidden-control",
        "gt_visible": False,
        "gt_identity": None,
        "gt_position": UNKNOWN_ANSWER,
        "acceptable": (UNKNOWN_ANSWER,),
        "direction_well_posed": False,
        "evidence": "no 'P07'; the upright letters are the zone 'B'",
        "known_bay_ids": (),
        "hard": False,
    },
    {
        "id": "N-ZONE-A-IMG01",
        "file": _IMG01,
        "target": "A",
        "target_kind": "立柱分区字母",
        "category": "hidden-control",
        "gt_visible": False,
        "gt_identity": None,
        "gt_position": UNKNOWN_ANSWER,
        "acceptable": (UNKNOWN_ANSWER,),
        "direction_well_posed": False,
        # Verified by scanning both halves of the frame at 2x: every pillar and
        # wall sign in IMG-01 reads 'C'; there is no 'A' zone letter.
        "evidence": "IMG-01's pillars and wall signs all read 'C'; no 'A' zone letter",
        "known_bay_ids": (),
        "hard": False,
    },
    # --- anchoring controls on the one rotated number that was claimed --------
    # B-316 came back ``Identified as: 316`` at the right position, where 07B and
    # 07C (same image, same target, older prompt) had denied it. The claim has to
    # be separated from target-name anchoring before it can count, so the same
    # frame is asked for (a) a different rotated number that is really painted on
    # it, and (b) two numbers that are not in it at all. ``D50`` is the stronger
    # of the two negatives: it is a real bay number of this dataset, painted in
    # IMG-02.
    {
        "id": "X-283-IMG04",
        "file": _IMG04,
        "target": "283",
        "target_kind": "车位编号",
        "category": "rotated-bay-number",
        "gt_visible": True,
        "gt_identity": "283",
        "gt_position": "LEFT",
        "acceptable": ("LEFT",),
        "direction_well_posed": True,
        "evidence": "bay id '283' painted on the deck, frame x 29-35% y 83-86%, rotated 180 deg",
        "known_bay_ids": ("316", "283", "364"),
        "hard": False,
    },
    {
        "id": "X-D50-ABSENT-IMG04",
        "file": _IMG04,
        "target": "D50",
        "target_kind": "车位编号",
        "category": "anchoring-control",
        "gt_visible": False,
        "gt_identity": None,
        "gt_position": UNKNOWN_ANSWER,
        "acceptable": (UNKNOWN_ANSWER,),
        "direction_well_posed": False,
        "evidence": "'D50' is painted in IMG-02, not IMG-04; absent from this frame",
        "known_bay_ids": ("316", "283", "364"),
        "hard": False,
    },
    {
        "id": "X-999-ABSENT-IMG04",
        "file": _IMG04,
        "target": "999",
        "target_kind": "车位编号",
        "category": "anchoring-control",
        "gt_visible": False,
        "gt_identity": None,
        "gt_position": UNKNOWN_ANSWER,
        "acceptable": (UNKNOWN_ANSWER,),
        "direction_well_posed": False,
        "evidence": "no bay number '999' anywhere in the frame",
        "known_bay_ids": ("316", "283", "364"),
        "hard": False,
    },
)

#: Key positive cases repeated twice more at temperature 0 (three samples each).
#: ``B-316`` is repeated because its identity claim is the one new positive that
#: the anchoring controls have to adjudicate.
_REPEAT_IDS = ("U-EXIT-LEFT", "U-EXIT-AHEAD", "U-ZONE-A", "B-316")

#: 08A's extra field. Kept next to the 07B parser rather than replacing it: the
#: 5-field parser stays untouched so 07B/07C keep classifying identically.
_IDENTITY_FIELD_RE = re.compile(
    r"^\s*[*`#\-\s]*(Identified as|识别为)\s*[:：]\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

#: Accepted readings for an identity that is not a Latin alphanumeric token.
_IDENTITY_ALIASES = {"出口": ("EXIT",)}

_STRIP_RE = re.compile(r"[\s`*\"'。.,;:：]")
#: A Latin/digit character, used to stop ``316`` from matching inside ``1316``.
_ALNUM = "A-Z0-9"


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


def _repeat_ids() -> tuple:
    only = os.environ.get(_REPEAT_ONLY_ENV, "").strip().upper()
    if not only:
        return _REPEAT_IDS
    tokens = {token.strip() for token in only.split(",") if token.strip()}
    selected = tuple(scene_id for scene_id in _REPEAT_IDS if scene_id.upper() in tokens)
    if not selected:
        pytest.fail(f"${_REPEAT_ONLY_ENV}={only!r} matched no repeat scene")
    return selected


def _compact(value: str) -> str:
    return _STRIP_RE.sub("", value).upper()


def _identity_matches(identified: str | None, expected: str) -> bool:
    """Does the model's stated reading contain ``expected`` as a whole token?

    Whole-token rather than substring so the measured failure mode is caught: a
    180-degree-rotated ``D50`` is read as ``050``, and ``050`` must not pass as
    ``D50``. ``1316`` must not pass as ``316`` either.
    """

    if not identified:
        return False
    compact = _compact(identified)
    for candidate in (expected, *_IDENTITY_ALIASES.get(expected, ())):
        token = _compact(candidate)
        if re.search(rf"(?<![{_ALNUM}]){re.escape(token)}(?![0-9])", compact):
            return True
    return False


def _parse_identity_field(raw: str) -> str | None:
    match = _IDENTITY_FIELD_RE.search(raw)
    return match.group(2).strip().strip("`*\"'。 ") if match else None


def _expected_direction(scene: dict) -> str:
    if not scene["gt_visible"]:
        return UNKNOWN_ANSWER
    return " 或 ".join(
        "STRAIGHT" if answer == "AHEAD" else answer for answer in scene["acceptable"]
    )


def _score_08a(scene: dict, record: dict) -> dict:
    """Score one round and record rather than assert.

    ``identity_correct`` means: for a present target, the model read *that*
    marking; for a hidden control, the model did **not** claim the requested
    marking (so reading the frame's real letter, or abstaining, both pass).
    """

    base = _score(scene, record)
    identified = record["identity_field_raw"]

    if scene["gt_visible"]:
        identity_correct = _identity_matches(identified, scene["gt_identity"])
        expected_identity = scene["gt_identity"]
    else:
        identity_correct = not _identity_matches(identified, scene["target"])
        expected_identity = f"anything but {scene['target']}"

    direction_correct = base["direction_correct"]
    end_to_end = None
    if scene["gt_visible"] and scene["direction_well_posed"]:
        end_to_end = bool(identity_correct and direction_correct is True)

    return {
        **base,
        "identity": {
            "field_present": identified is not None,
            "identified_as_raw": identified,
            "expected": expected_identity,
            "correct": identity_correct,
        },
        "requested_target": scene["target"],
        "target_kind": scene["target_kind"],
        "category": scene["category"],
        "expected_identity": expected_identity,
        "expected_direction": _expected_direction(scene),
        "direction_well_posed": scene["direction_well_posed"],
        "pass_identity": identity_correct,
        "pass_direction": direction_correct,
        "pass_end_to_end": end_to_end,
    }


def _summarize(records: list) -> dict:
    """The three numbers the task requires, kept apart on purpose."""

    scored = [record["scored"] for record in records]
    identity = [entry for entry in scored if entry["pass_identity"] is not None]
    present = [entry for entry in identity if entry["identity"]["expected"] is not None
               and not entry["expected_identity"].startswith("anything")]
    direction_pool = [
        entry
        for entry in identity
        if entry["pass_identity"] and entry["direction_well_posed"]
    ]
    end_to_end = [entry for entry in identity if entry["pass_end_to_end"] is not None]
    return {
        "identity_scored": len(identity),
        "identity_correct": sum(1 for entry in identity if entry["pass_identity"]),
        "identity_accuracy": (
            round(sum(1 for entry in identity if entry["pass_identity"]) / len(identity), 3)
            if identity
            else None
        ),
        "present_targets": len(present),
        "present_targets_identified": sum(
            1 for entry in present if entry["pass_identity"]
        ),
        "direction_scored_on_identity_correct": len(direction_pool),
        "direction_correct_on_identity_correct": sum(
            1 for entry in direction_pool if entry["pass_direction"]
        ),
        "end_to_end_scored": len(end_to_end),
        "end_to_end_success": sum(
            1 for entry in end_to_end if entry["pass_end_to_end"]
        ),
    }


def _emit(record: dict) -> None:
    line = json.dumps(record, ensure_ascii=False)
    print("NAV08A " + line)
    path = os.environ.get(_OUT_ENV, "").strip()
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _round(scene: dict, *, thinking: bool = False, max_new_tokens: int = 400) -> dict:
    """One image round with 08A's identity-bearing prompt, for ``scene``.

    07B's ``_one_round`` hard-codes the bay-number wording and 07C's ``_round``
    stops at the target kind, so 08A has to build its own prompt; the recorder,
    the block parser and the shared scorer are still 07B's, so all three
    experiments classify identically.
    """

    image_path = _IMAGES_DIR / scene["file"]
    if not image_path.is_file():
        pytest.skip(f"scene image missing: {image_path}")

    prompt = build_nav_prompt(
        Variant.TARGET_DIRECTION,
        target=scene["target"],
        target_kind=scene["target_kind"],
        require_identity=True,
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
        "category": scene["category"],
        "thinking": thinking,
        "temperature": 0.0,
        "prompt_chars": len(prompt),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "image": part.safe_description(),
        "wire_image_matches_file": hashlib.sha256(base64.b64decode(encoded)).hexdigest()
        == part.sha256,
        "content_part_types": [item["type"] for item in message["content"]],
        "authorization_header_present": calls[0]["authorization"] is not None,
        "usage": response.get("usage"),
        "finish_reason": choice.get("finish_reason"),
        "reasoning_content_chars": len(choice["message"].get("reasoning_content") or ""),
        "raw": raw,
        "block": _parse_block(raw),
        "identity_field_raw": _parse_identity_field(raw),
    }


def _deliver(scene: dict, *, thinking: bool = False) -> dict:
    record = _round(scene, thinking=thinking)
    assert record["wire_image_matches_file"], "the wire image was not the file's bytes"
    _emit({**record, "scored": _score_08a(scene, record)})
    return record


@pytest.mark.parametrize("scene", _wanted(), ids=[scene["id"] for scene in _wanted()])
def test_identity_and_direction_round(scene: dict) -> None:
    _gate()
    _deliver(scene)


@pytest.mark.parametrize("scene_id", _repeat_ids())
def test_repeat_stability(scene_id: str) -> None:
    """Two extra samples of a key positive, same image, same target."""

    _gate()
    scene = next(entry for entry in SCENES if entry["id"] == scene_id)
    samples = [_round(scene) for _ in range(2)]
    for sample in samples:
        # The same on-the-wire check as the primary rounds: a repeated raw string
        # only means something if the same image really went out again.
        assert sample["wire_image_matches_file"], "the wire image was not the file's bytes"
    raws = [sample["raw"] for sample in samples]
    _emit(
        {
            "phase": "repeat-stability",
            "scene_id": scene_id,
            "target": scene["target"],
            "target_kind": scene["target_kind"],
            "raw_1": raws[0],
            "raw_2": raws[1],
            "identical": raws[0] == raws[1],
            "identity_1": samples[0]["identity_field_raw"],
            "identity_2": samples[1]["identity_field_raw"],
            "wire_image_matches_file_1": samples[0]["wire_image_matches_file"],
            "wire_image_matches_file_2": samples[1]["wire_image_matches_file"],
            "images": [sample["image"] for sample in samples],
            "scored": [_score_08a(scene, sample) for sample in samples],
        }
    )


def test_text_only_control() -> None:
    """The same prompt with no image: how much of the answer is the image?"""

    _gate()
    prompt = build_nav_prompt(
        Variant.TARGET_DIRECTION,
        target="出口",
        target_kind="目标标识",
        require_identity=True,
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
            "identity_field_raw": _parse_identity_field(raw),
            "raw": raw,
            "block": _parse_block(raw),
        }
    )


# ----------------------------------------------------------------------
# Supplementary (labelled, not part of the primary matrix)
# ----------------------------------------------------------------------

#: An open-ended read of the deck numbers, with **no target named**. It exists for
#: one reason: ``B-316`` and ``X-283-IMG04`` came back with the correct identity
#: and the correct position, yet the same answers misread a real neighbouring
#: number (the rotated ``364`` came back as ``36``). A correct identity on a
#: named target cannot be separated from naming luck, but a correct identity
#: produced with nothing to echo can. This is a diagnostic prompt, not a new
#: capability and not a contract: nothing parses its output.
_OPEN_READ_PROMPT = (
    "请只观察这张停车场图像的地面。\n"
    "把画面中你能够辨认出的车位编号文字逐个原样抄写出来，每个编号单独一行，用「编号: 」开头。\n"
    "只写你确实能从画面像素中辨认出的字符；辨认不清的写「看不清」。\n"
    "不要推测，不要解释，不要输出其他内容。"
)

_OPEN_READ_CASES = (
    {
        "id": "OPEN-IMG04",
        "file": _IMG04,
        "real_deck_numbers": ("316", "283", "364"),
    },
    {
        "id": "OPEN-IMG02",
        "file": _IMG02,
        "real_deck_numbers": ("D50", "D63", "D64", "D65"),
    },
)


@pytest.mark.parametrize("case", _OPEN_READ_CASES, ids=[c["id"] for c in _OPEN_READ_CASES])
def test_supplementary_open_deck_read(case: dict) -> None:
    """Supplementary diagnostic: what deck numbers come back when none is named?"""

    _gate()
    image_path = _IMAGES_DIR / case["file"]
    if not image_path.is_file():
        pytest.skip(f"image missing: {image_path}")

    part = load_image_part(image_path)
    backend = ZDTaichuServerBackend(
        max_new_tokens=300, temperature=0.0, enable_thinking=False, timeout=180.0
    )
    calls, original = _install_recorder()
    try:
        raw = backend.generate_image(str(image_path), _OPEN_READ_PROMPT)
    finally:
        server_client_module._OPENER.open = original
    assert len(calls) == 1

    payload = json.loads(calls[0]["body"].decode("utf-8"))
    (message,) = payload["messages"]
    encoded = message["content"][0]["image_url"]["url"].partition(";base64,")[2]
    upper = raw.upper()
    _emit(
        {
            "phase": "supplementary-open-deck-read",
            "scene_id": case["id"],
            "note": "no target named in this prompt; nothing can be echoed",
            "prompt_chars": len(_OPEN_READ_PROMPT),
            "image": part.safe_description(),
            "wire_image_matches_file": hashlib.sha256(
                base64.b64decode(encoded)
            ).hexdigest()
            == part.sha256,
            "content_part_types": [item["type"] for item in message["content"]],
            "real_deck_numbers": list(case["real_deck_numbers"]),
            "real_numbers_reproduced": [
                number for number in case["real_deck_numbers"] if number in upper
            ],
            "raw": raw,
        }
    )


# ----------------------------------------------------------------------
# Offline: the identity/direction scoring rules, with no model and no socket.
# ----------------------------------------------------------------------


def _fake_record(identity: str | None, direction: str, visible: str = "是") -> dict:
    raw = (
        f"Target: X\n{IDENTITY_FIELD}: {identity}\nVisible: {visible}\n"
        f"Relative position: LEFT\nNext direction: {direction}\nEvidence: none\n"
    )
    return {
        "raw": raw,
        "block": _parse_block(raw),
        "identity_field_raw": _parse_identity_field(raw),
    }


def test_the_identity_field_is_parsed_out_of_the_answer_block() -> None:
    assert _parse_identity_field(_fake_record("D50", "LEFT")["raw"]) == "D50"


@pytest.mark.parametrize(
    "identified,expected,correct",
    [
        ("D50", "D50", True),
        ("`D50`", "D50", True),
        ("050", "D50", False),  # the measured 180-degree misread
        ("D50", "D65", False),
        ("316", "316", True),
        ("1316", "316", False),  # must not match inside a longer number
        ("A", "A", True),
        ("A区", "A", True),
        ("C", "A", False),
        ("出口", "出口", True),
        ("EXIT", "出口", True),
        (UNKNOWN_ANSWER, "D50", False),
        (None, "D50", False),
    ],
)
def test_identity_matching_is_whole_token_and_alias_aware(
    identified: str | None, expected: str, correct: bool
) -> None:
    assert _identity_matches(identified, expected) is correct


def test_a_guessed_direction_does_not_score_when_the_identity_is_wrong() -> None:
    """The failure mode the task calls out: right direction, wrong identity."""

    scene = next(entry for entry in SCENES if entry["id"] == "B-D50")
    scored = _score_08a(scene, _fake_record("050", "LEFT"))
    assert scored["pass_identity"] is False
    assert scored["pass_end_to_end"] is False


def test_a_hidden_control_passes_when_the_target_is_not_claimed() -> None:
    scene = next(entry for entry in SCENES if entry["id"] == "N-ZONE-A-IMG01")
    assert _score_08a(scene, _fake_record("C", UNKNOWN_ANSWER, visible="否"))["pass_identity"]
    assert not _score_08a(
        scene, _fake_record("A", "RIGHT", visible="是")
    )["pass_identity"]


def test_direction_accuracy_is_counted_only_over_correct_identities() -> None:
    """06A/07B's trap: a wrong identity with a lucky direction must not count."""

    scene = next(entry for entry in SCENES if entry["id"] == "B-D50")
    records = [
        {"scored": _score_08a(scene, _fake_record("D50", "LEFT"))},  # both right
        {"scored": _score_08a(scene, _fake_record("050", "LEFT"))},  # lucky direction
    ]
    summary = _summarize(records)
    assert summary["identity_scored"] == 2
    assert summary["identity_correct"] == 1
    assert summary["direction_scored_on_identity_correct"] == 1
    assert summary["direction_correct_on_identity_correct"] == 1
    assert summary["end_to_end_success"] == 1


def test_an_ill_posed_direction_is_excluded_from_the_direction_statistic() -> None:
    scene = next(entry for entry in SCENES if entry["id"] == "U-ZONE-A")
    records = [{"scored": _score_08a(scene, _fake_record("A", "LEFT"))}]
    summary = _summarize(records)
    assert summary["identity_correct"] == 1
    assert summary["direction_scored_on_identity_correct"] == 0
    assert summary["end_to_end_success"] == 0
