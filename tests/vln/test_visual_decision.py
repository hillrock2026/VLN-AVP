"""Offline tests for the visual-judgement parse and verification layers.

No model, no network and no image: every input here is text. The subject is the
boundary that decides whether a model's written judgement may drive a
navigation intent at all.

Module under test: :mod:`vln.nav.visual_decision`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vln.intent.agent_intent import AgentIntentError
from vln.nav import (
    DECISION_FIELDS,
    POSITION_TO_DIRECTION,
    EvidenceInsufficientError,
    NavigationDirective,
    VisualDecisionParseError,
    VisualDecisionValidationError,
    TargetIdentityMismatchError,
    TargetNotVisibleError,
    evidence_is_insufficient,
    identity_matches,
    parse_visual_decision,
    verify_visual_decision,
)
from vln.vlm.nav_prompt import (
    DIRECTION_ANSWERS,
    IDENTITY_FIELD,
    POSITION_ANSWERS,
    UNKNOWN_ANSWER,
    Variant,
    build_nav_prompt,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RAW_08A = _REPO_ROOT / "docs" / "M1-VLN-NAV-08A-RAW.jsonl"


def _block(
    *,
    target: str = "D50",
    identified: str = "D50",
    visible: str = "是",
    position: str = "LEFT",
    direction: str = "LEFT",
    evidence: str = "左上角地面白色编号",
) -> str:
    """A conclusion block in the exact shape the prompt asks for."""

    return (
        f"Target: {target}\n"
        f"{IDENTITY_FIELD}: {identified}\n"
        f"Visible: {visible}\n"
        f"Relative position: {position}\n"
        f"Next direction: {direction}\n"
        f"Evidence: {evidence}\n"
    )


def _real_08a_record(scene_id: str) -> str:
    """The verbatim raw model output for ``scene_id`` from the 08A evidence file.

    Reading the recorded artifact rather than transcribing it means the parser is
    tested against what the real model actually emitted, with no copy error.
    """

    assert _RAW_08A.is_file(), f"the 08A raw evidence file is missing: {_RAW_08A}"
    for line in _RAW_08A.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("scene_id") == scene_id and "scored" in record:
            return record["raw"]
    raise AssertionError(f"no 08A record for {scene_id!r}")


# ----------------------------------------------------------------------
# The parser and the prompt tell the same story
# ----------------------------------------------------------------------


@pytest.mark.parametrize("label", DECISION_FIELDS)
def test_every_parsed_field_label_really_appears_in_the_prompt(label: str) -> None:
    """The parser must not parse a block the prompt never asks for."""

    text = build_nav_prompt(
        Variant.TARGET_DIRECTION, target="D50", require_identity=True
    )
    assert f"{label}:" in text


def test_the_block_shape_matches_the_prompt_field_order() -> None:
    text = build_nav_prompt(
        Variant.TARGET_DIRECTION, target="D50", require_identity=True
    )
    positions = [text.index(f"{label}:") for label in DECISION_FIELDS]
    assert positions == sorted(positions)


# ----------------------------------------------------------------------
# Layer 1: parsing (structure)
# ----------------------------------------------------------------------


def test_a_well_formed_block_parses_into_its_fields() -> None:
    decision = parse_visual_decision(_block())
    assert decision.target_field == "D50"
    assert decision.identified_as == "D50"
    assert decision.visible == "是"
    assert decision.position == "LEFT"
    assert decision.direction == "LEFT"
    assert decision.evidence == "左上角地面白色编号"


def test_the_real_recorded_model_answer_parses() -> None:
    """08A's certified positive, verbatim from the raw evidence file."""

    decision = parse_visual_decision(_real_08a_record("U-EXIT-LEFT"))
    assert decision.visible == "是"
    assert decision.position == "LEFT"
    assert decision.direction == "LEFT"
    assert identity_matches(decision.identified_as, "出口")


def test_markdown_decoration_around_labels_and_values_is_tolerated() -> None:
    raw = (
        "- **Target**: `D50`\n"
        "* **Identified as**: **D50**\n"
        "• Visible: 是\n"
        "Relative position: `LEFT`\n"
        "Next direction: LEFT\n"
        "Evidence: 地面白色编号\n"
    )
    decision = parse_visual_decision(raw)
    assert decision.identified_as == "D50"
    assert decision.position == "LEFT"
    assert decision.target_field == "D50"


def test_prose_around_the_block_does_not_break_the_parse() -> None:
    """The prompt asks for reasoning in steps 1-4, so other lines are expected."""

    raw = (
        "第一步 观察：画面中可见多根立柱，立柱上有橙色条纹。\n\n"
        "第二步 查找目标：画面中确实出现了「D50」标识。\n\n"
        "第五步 输出结论块：\n" + _block()
    )
    assert parse_visual_decision(raw).direction == "LEFT"


@pytest.mark.parametrize("label", DECISION_FIELDS)
def test_a_missing_required_field_is_refused(label: str) -> None:
    kept = [line for line in _block().splitlines() if not line.startswith(f"{label}:")]
    with pytest.raises(VisualDecisionParseError, match="missing required field"):
        parse_visual_decision("\n".join(kept))


@pytest.mark.parametrize("label", DECISION_FIELDS)
def test_a_duplicated_field_is_refused_not_silently_first_wins(label: str) -> None:
    line = next(
        entry for entry in _block().splitlines() if entry.startswith(f"{label}:")
    )
    with pytest.raises(VisualDecisionParseError, match="duplicate field"):
        parse_visual_decision(_block() + line + "\n")


def test_the_real_repeated_block_artifact_is_refused() -> None:
    """08A's U-ZONE-C emitted its block twice; the parser refuses it.

    Recorded real evidence, not a constructed case: see
    ``docs/M1-VLN-NAV-08A-RESULT.md`` §8 and the raw file.
    """

    with pytest.raises(VisualDecisionParseError, match="duplicate field"):
        parse_visual_decision(_real_08a_record("U-ZONE-C"))


@pytest.mark.parametrize("label", DECISION_FIELDS)
def test_a_present_but_empty_field_is_refused(label: str) -> None:
    broken = _block().replace(f"{label}: ", f"{label}: ")
    broken = "\n".join(
        f"{label}:" if line.startswith(f"{label}:") else line
        for line in broken.splitlines()
    )
    with pytest.raises(VisualDecisionParseError, match="present but empty"):
        parse_visual_decision(broken)


@pytest.mark.parametrize("raw", ["", "   \n  ", "no block here at all"])
def test_blank_or_blockless_text_is_refused(raw: str) -> None:
    with pytest.raises(VisualDecisionParseError):
        parse_visual_decision(raw)


@pytest.mark.parametrize("raw", [None, 17, b"Visible: \xe6\x98\xaf", ["a"]])
def test_a_non_string_response_is_refused(raw: object) -> None:
    with pytest.raises(VisualDecisionParseError, match="must be a string"):
        parse_visual_decision(raw)  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# Identity matching
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "identified,expected,matches",
    [
        ("D50", "D50", True),
        ("`D50`", "D50", True),
        ("D50 编号", "D50", True),
        ("050", "D50", False),  # the measured 180-degree misread
        ("D66", "D50", False),
        ("D50", "D65", False),
        ("316", "316", True),
        ("1316", "316", False),  # must not match inside a longer number
        ("3160", "316", False),  # ...nor as a prefix of a longer number
        ("D50ABC", "D50", False),  # a longer alphanumeric token is a different read
        ("D50A", "D50", False),  # a letter suffix is still a token boundary
        ("D50 (EXIT)", "D50", True),  # punctuation is a boundary, so decorated reads pass
        ("A", "A", True),
        ("A 区", "A", True),
        ("AB", "A", False),  # zone A must not match zone AB
        ("A1", "A", False),  # ...nor bay A1
        ("C", "A", False),
        ("出口 EXIT", "出口", True),
        ("EXIT", "出口", False),  # the caller owns aliasing, not this layer
        ("出口", "出口", True),
        (UNKNOWN_ANSWER, "D50", False),
        ("", "", False),
        ("D50", "", False),
        (None, "D50", False),  # type: ignore[arg-type]
        ("D50", None, False),  # type: ignore[arg-type]
    ],
)
def test_identity_matching_is_whole_token(
    identified: object, expected: object, matches: bool
) -> None:
    assert identity_matches(identified, expected) is matches  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# Layer 2: verification (executability)
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "position,direction", sorted(POSITION_TO_DIRECTION.items())
)
def test_each_approved_direction_pair_is_accepted(position: str, direction: str) -> None:
    decision = parse_visual_decision(
        _block(position=position, direction=direction, evidence="证据")
    )
    directive = verify_visual_decision(decision, expected_identity="D50")
    assert isinstance(directive, NavigationDirective)
    assert directive.direction == direction
    assert directive.position == position


#: For each approval state, a direction that cannot correspond to it.
_MISMATCHED_DIRECTION = {
    "LEFT": "RIGHT",
    "RIGHT": "LEFT",
    "AHEAD": "LEFT",
    UNKNOWN_ANSWER: "LEFT",
}


@pytest.mark.parametrize("position", POSITION_ANSWERS)
def test_an_unknown_position_or_a_mismatched_direction_is_refused(position: str) -> None:
    decision = parse_visual_decision(
        _block(position=position, direction=_MISMATCHED_DIRECTION[position])
    )
    with pytest.raises(VisualDecisionValidationError):
        verify_visual_decision(decision, expected_identity="D50")


@pytest.mark.parametrize("position", ["右侧", "left", "AHEAD-ish", "LEFTISH", "左"])
def test_an_off_vocabulary_position_is_refused(position: str) -> None:
    raw = _block().replace("Relative position: LEFT", f"Relative position: {position}")
    with pytest.raises(VisualDecisionValidationError):
        verify_visual_decision(parse_visual_decision(raw), expected_identity="D50")


def test_surrounding_whitespace_on_a_valid_token_is_not_an_offence() -> None:
    """The parser strips padding, so a padded approved token still passes."""

    raw = _block().replace("Relative position: LEFT", "Relative position:   LEFT  ")
    directive = verify_visual_decision(
        parse_visual_decision(raw), expected_identity="D50"
    )
    assert directive.position == "LEFT"


@pytest.mark.parametrize("direction", ["右侧", "right", UNKNOWN_ANSWER, "FORWARD"])
def test_an_off_vocabulary_or_unknown_direction_is_refused(direction: str) -> None:
    raw = _block().replace("Next direction: LEFT", f"Next direction: {direction}")
    with pytest.raises(VisualDecisionValidationError):
        verify_visual_decision(parse_visual_decision(raw), expected_identity="D50")


@pytest.mark.parametrize("position,direction", [("LEFT", "RIGHT"), ("RIGHT", "LEFT"), ("AHEAD", "LEFT")])
def test_a_self_contradictory_answer_is_refused(position: str, direction: str) -> None:
    decision = parse_visual_decision(_block(position=position, direction=direction))
    with pytest.raises(VisualDecisionValidationError, match="contradicts itself"):
        verify_visual_decision(decision, expected_identity="D50")


def test_an_invisible_target_is_refused_with_its_own_error() -> None:
    decision = parse_visual_decision(
        _block(visible="否", position=UNKNOWN_ANSWER, direction=UNKNOWN_ANSWER)
    )
    with pytest.raises(TargetNotVisibleError):
        verify_visual_decision(decision, expected_identity="D50")


def test_an_unapproved_visibility_token_is_not_reported_as_not_visible() -> None:
    """`no` is off-vocabulary, which is a different failure from the token `否`."""

    decision = parse_visual_decision(
        _block(visible="no", position=UNKNOWN_ANSWER, direction=UNKNOWN_ANSWER)
    )
    with pytest.raises(VisualDecisionValidationError) as excinfo:
        verify_visual_decision(decision, expected_identity="D50")
    assert not isinstance(excinfo.value, TargetNotVisibleError)


@pytest.mark.parametrize(
    "identified,expected",
    [
        ("050", "D50"),  # the rotated misread
        ("D65", "D50"),  # a real neighbour, wrong target
        (UNKNOWN_ANSWER, "D50"),  # the model could not read it
        ("283", "316"),  # 08A's anchoring case, other way round
    ],
)
def test_an_identity_mismatch_is_refused_with_its_own_error(
    identified: str, expected: str
) -> None:
    decision = parse_visual_decision(_block(identified=identified))
    with pytest.raises(TargetIdentityMismatchError):
        verify_visual_decision(decision, expected_identity=expected)


def test_an_anchored_identity_claim_does_not_pass_for_a_different_target() -> None:
    """The 08A lesson, as a boundary: a claimed identity is checked, not trusted."""

    decision = parse_visual_decision(
        _block(target="316", identified="316", position="RIGHT", direction="RIGHT")
    )
    directive = verify_visual_decision(decision, expected_identity="316")
    assert directive.direction == "RIGHT"
    with pytest.raises(TargetIdentityMismatchError):
        verify_visual_decision(decision, expected_identity="283")


def test_a_target_echo_that_names_a_different_label_is_refused() -> None:
    """The two identity fields may not contradict each other.

    ``Target`` is not evidence of a read, but the prompt defines it as a copy of
    the requested label; a block that echoes a different target is answering a
    different task even when ``Identified as`` happens to match.
    """

    decision = parse_visual_decision(_block(target="D66", identified="D50"))
    with pytest.raises(TargetIdentityMismatchError, match="Target field"):
        verify_visual_decision(decision, expected_identity="D50")


@pytest.mark.parametrize("target", ["D50", "D50 编号", "D50号", "D50 (EXIT)"])
def test_a_target_echo_that_contains_the_request_is_accepted(target: str) -> None:
    """Whole-token containment, not byte equality: decoration is tolerated."""

    decision = parse_visual_decision(_block(target=target, identified="D50"))
    directive = verify_visual_decision(decision, expected_identity="D50")
    assert directive.direction == "LEFT"


def test_an_extra_field_cannot_override_the_required_direction() -> None:
    """The text-block contract does not close the field set.

    An unrecognised line is ignored, so it cannot authorise a direction. (The
    separate JSON model-output contract, which is not on the NAV-09 path, does
    reject unknown fields - see ``tests/vln/test_model_output.py``.)
    """

    raw = _block() + "Direction: RIGHT\nConfidence: high\n"
    directive = verify_visual_decision(
        parse_visual_decision(raw), expected_identity="D50"
    )
    assert directive.direction == "LEFT"


@pytest.mark.parametrize("expected", ["", "   ", None, 7])
def test_a_blank_or_non_string_expected_identity_is_refused(expected: object) -> None:
    with pytest.raises(VisualDecisionValidationError):
        verify_visual_decision(
            parse_visual_decision(_block()), expected_identity=expected  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("decision", [_block(), None, "Visible: 是"])
def test_a_non_decision_object_cannot_be_verified(decision: object) -> None:
    with pytest.raises(VisualDecisionValidationError):
        verify_visual_decision(decision, expected_identity="D50")  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# NAV-12B: the Evidence field and explicit uncertainty
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "evidence",
    ["无法确定", "证据不足", "证据不足，无法确定", "无法判断", "不确定",
     "不能确定", "看不清", "不可见", "「无法确定」", "（证据不足）",
     "无法确定方向", "证据不足，无法判断位置"],
)
def test_evidence_that_is_only_uncertainty_is_refused(evidence: str) -> None:
    """A concrete Visible/direction pair is not executable without evidence."""

    decision = parse_visual_decision(_block(evidence=evidence))
    with pytest.raises(EvidenceInsufficientError, match="cannot be supported"):
        verify_visual_decision(decision, expected_identity="D50")


@pytest.mark.parametrize(
    "evidence",
    [
        "可见左侧蓝色出口 EXIT 标识，但无法确定其距离。",
        "左侧上方指示牌清晰显示出口 EXIT，无法确定具体距离。",
        "地面白色编号 D50，位于左侧。",
    ],
)
def test_evidence_with_a_visual_basis_is_not_rejected_for_containing_a_keyword(
    evidence: str,
) -> None:
    """Whole-value composition, not keyword search: a real basis still passes."""

    directive = verify_visual_decision(
        parse_visual_decision(_block(evidence=evidence)), expected_identity="D50"
    )
    assert directive.direction == "LEFT"


@pytest.mark.parametrize(
    "evidence,insufficient",
    [
        ("无法确定", True),
        ("证据不足，无法确定", True),
        ("证据不足/无法判断", True),
        ("无法确定方向", True),
        ("可见出口，无法确定方向", False),
        ("可见出口，但无法确定距离", False),
        ("画面中未出现 D50，仅可见 D65", False),
        ("", False),
        (None, False),
    ],
)
def test_evidence_insufficiency_is_whole_value_composition(
    evidence: object, insufficient: bool
) -> None:
    assert evidence_is_insufficient(evidence) is insufficient  # type: ignore[arg-type]


def test_evidence_uncertainty_does_not_replace_the_not_visible_error() -> None:
    """A not-visible claim keeps its more specific refusal."""

    decision = parse_visual_decision(
        _block(
            visible="否",
            position=UNKNOWN_ANSWER,
            direction=UNKNOWN_ANSWER,
            evidence=UNKNOWN_ANSWER,
        )
    )
    with pytest.raises(TargetNotVisibleError):
        verify_visual_decision(decision, expected_identity="D50")


def test_verification_returns_a_plain_directive_and_not_an_intent() -> None:
    """Layer 2 stops at a directive; it never builds an ``AgentIntent``."""

    directive = verify_visual_decision(
        parse_visual_decision(_block()), expected_identity="D50"
    )
    assert not hasattr(directive, "to_payload")
    assert set(directive.__dataclass_fields__) == {
        "direction",
        "position",
        "identified_as",
        "evidence",
    }


# ----------------------------------------------------------------------
# Boundary invariants
# ----------------------------------------------------------------------


def test_the_unknown_token_is_last_in_both_vocabularies() -> None:
    """The code strips the unknown entry with ``[:-1]``; that must stay valid."""

    assert POSITION_ANSWERS[-1] == UNKNOWN_ANSWER == DIRECTION_ANSWERS[-1]
    assert UNKNOWN_ANSWER not in POSITION_ANSWERS[:-1]
    assert UNKNOWN_ANSWER not in DIRECTION_ANSWERS[:-1]


def test_the_visibility_vocabulary_keeps_yes_first() -> None:
    """``VISIBLE_ANSWERS[0]`` is treated as "visible"; the order is load-bearing."""

    from vln.vlm.nav_prompt import VISIBLE_ANSWERS

    assert VISIBLE_ANSWERS == ("是", "否")


@pytest.mark.parametrize(
    "error",
    [
        VisualDecisionParseError,
        VisualDecisionValidationError,
        TargetNotVisibleError,
        TargetIdentityMismatchError,
        EvidenceInsufficientError,
    ],
)
def test_every_refusal_is_catchable_at_the_intent_boundary(error: type) -> None:
    """One ``except AgentIntentError`` must catch every failure this layer raises."""

    assert issubclass(error, AgentIntentError)


def test_the_layer_imports_no_execution_stack() -> None:
    """Importing the layer must not reach a model, a host client or a process.

    ``socket`` does arrive transitively - ``vln.vlm.nav_prompt`` pulls in the
    server client, which imports ``urllib`` - so it is not asserted here. No
    connection is opened by importing, and the layer holds no client at all.
    """

    import subprocess
    import sys

    code = (
        "import sys, vln.nav;"
        "bad=[x for x in ('torch','transformers','subprocess',"
        "'vln.client','vln.pipeline','vln.app') if x in sys.modules];"
        "assert not bad, bad"
    )
    root = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT / "src"),
    )
    assert root.returncode == 0, root.stderr
