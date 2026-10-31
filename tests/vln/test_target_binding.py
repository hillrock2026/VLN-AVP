"""Offline tests for the parking-target binding decision layer.

No model, no image and no CARLA: the subject is the boundary that turns a
temporary candidate letter into a real bay identity, or refuses.

Module under test: :mod:`vln.nav.target_binding`.
"""

from __future__ import annotations

import json

import pytest

from vln.nav.parking_request import parse_parking_instruction
from vln.nav.target_binding import (
    BindingArtifact,
    BindingDecisionParseError,
    BindingNotExecutableError,
    BindingStatus,
    CandidateObservation,
    INTERNAL_OCCUPIED,
    INTERNAL_UNKNOWN,
    INTERNAL_VACANT,
    TargetBinding,
    binding_goal_node,
    parse_binding_artifact,
    parse_binding_decision,
    resolve_target_binding,
)
from vln.vlm.binding_prompt import build_binding_prompt


def _candidate(
    label: str,
    bay_id: str,
    slot_node_id: str,
    occupancy: str,
    *,
    visible: bool = True,
    side: str = "LEFT",
) -> CandidateObservation:
    return CandidateObservation(
        label=label,
        bay_id=bay_id,
        slot_node_id=slot_node_id,
        occupancy=occupancy,
        visible=visible,
        side=side,
        bearing_deg=-50.0,
        distance_m=6.0,
        image_bbox=(10.0, 20.0, 110.0, 90.0),
    )


def _two_candidates(
    *, occupancy_a: str = INTERNAL_VACANT, occupancy_b: str = INTERNAL_VACANT
) -> tuple[CandidateObservation, CandidateObservation]:
    return (
        _candidate("A", "bay11", "bay11_slot", occupancy_a),
        _candidate("B", "bay03", "park_slot", occupancy_b),
    )


def test_prompt_has_only_labels_and_no_coordinates() -> None:
    prompt = build_binding_prompt(("A", "B"), "请将车辆停入左侧的空闲车位")
    assert "A、B" in prompt
    assert "Selected" in prompt
    for forbidden in ("bay03", "bay11", "park_slot", "heading"):
        assert forbidden not in prompt.lower()
    with pytest.raises(ValueError):
        build_binding_prompt((), "停入空位")
    with pytest.raises(ValueError):
        build_binding_prompt(("A", "A"), "停入空位")
    with pytest.raises(ValueError):
        build_binding_prompt(("A", "Z"), "停入空位")


def test_parse_valid_block() -> None:
    decision = parse_binding_decision(
        "A: 空闲\nB: 占用\nSelected: A", ("A", "B")
    )
    assert decision.occupancies == {"A": INTERNAL_VACANT, "B": INTERNAL_OCCUPIED}
    assert decision.selected == "A"


def test_parse_chinese_colon_and_decoration() -> None:
    decision = parse_binding_decision(
        "**A：无法确定**\n- B: 空闲\n`Selected`: B", ("A", "B")
    )
    assert decision.occupancies == {"A": INTERNAL_UNKNOWN, "B": INTERNAL_VACANT}
    assert decision.selected == "B"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "A: 空闲\nSelected: A",  # missing B
        "A: 空闲\nB: 空闲\nB: 占用\nSelected: A",  # duplicate B
        "A: 空着\nB: 空闲\nSelected: A",  # off vocabulary
        "A: 空闲\nB: 占用",  # missing Selected
        "A: 空闲\nB: 占用\nSelected: A\nSelected: B",  # duplicate Selected
        "A: 空闲\nB: 占用\nSelected: C",  # invented candidate
        "A: 空闲\nB: 占用\nC: 空闲\nSelected: A",  # unexpected label
        "A: \nB: 占用\nSelected: A",  # empty value
    ],
)
def test_parse_refusals(text: str) -> None:
    with pytest.raises(BindingDecisionParseError):
        parse_binding_decision(text, ("A", "B"))


def test_parse_non_string_is_refused() -> None:
    with pytest.raises(BindingDecisionParseError):
        parse_binding_decision(None, ("A", "B"))  # type: ignore[arg-type]


def test_two_vacant_candidates_are_ambiguous_even_if_model_chooses() -> None:
    request = parse_parking_instruction("停入左侧的空闲车位")
    candidates = _two_candidates()
    decision = parse_binding_decision("A: 空闲\nB: 空闲\nSelected: A", ("A", "B"))
    binding = resolve_target_binding(request, candidates, decision)

    assert binding.status == BindingStatus.AMBIGUOUS
    assert binding.bay_id is None
    assert not binding.executable


def test_unique_vacant_candidate_binds_after_model_selects_it() -> None:
    request = parse_parking_instruction("停入左侧的空闲车位")
    candidates = _two_candidates(occupancy_a=INTERNAL_OCCUPIED)
    decision = parse_binding_decision("A: 占用\nB: 空闲\nSelected: B", ("A", "B"))
    binding = resolve_target_binding(request, candidates, decision)

    assert binding.status == BindingStatus.BOUND
    assert binding.bay_id == "bay03"
    assert binding.slot_node_id == "park_slot"
    assert binding.selected_label == "B"
    assert binding.executable


def test_model_choice_outside_system_constraints_is_refused() -> None:
    request = parse_parking_instruction("停入左侧的空闲车位")
    candidates = _two_candidates(occupancy_a=INTERNAL_OCCUPIED)
    decision = parse_binding_decision("A: 占用\nB: 空闲\nSelected: A", ("A", "B"))
    binding = resolve_target_binding(request, candidates, decision)

    assert binding.status == BindingStatus.REFUSED
    assert binding.bay_id is None


def test_unknown_occupancy_is_never_vacant() -> None:
    request = parse_parking_instruction("停入左侧的空闲车位")
    candidates = _two_candidates(
        occupancy_a=INTERNAL_UNKNOWN, occupancy_b=INTERNAL_UNKNOWN
    )
    decision = parse_binding_decision(
        "A: 无法确定\nB: 无法确定\nSelected: 无法确定", ("A", "B")
    )
    binding = resolve_target_binding(request, candidates, decision)
    assert binding.status == BindingStatus.UNVERIFIED
    assert binding.bay_id is None

    mixed = _two_candidates(
        occupancy_a=INTERNAL_OCCUPIED, occupancy_b=INTERNAL_UNKNOWN
    )
    decision = parse_binding_decision(
        "A: 占用\nB: 无法确定\nSelected: B", ("A", "B")
    )
    binding = resolve_target_binding(request, mixed, decision)
    assert binding.status == BindingStatus.REFUSED


def test_side_filter_uses_measured_side_not_model_text() -> None:
    request = parse_parking_instruction("停入右侧的空闲车位")
    candidates = _two_candidates()
    decision = parse_binding_decision("A: 空闲\nB: 空闲\nSelected: A", ("A", "B"))
    binding = resolve_target_binding(request, candidates, decision)
    assert binding.status == BindingStatus.REFUSED
    assert binding.bay_id is None


def test_no_visible_candidate_is_temporarily_not_visible() -> None:
    request = parse_parking_instruction("停入左侧的空闲车位")
    candidates = (
        _candidate("", "bay11", "bay11_slot", INTERNAL_UNKNOWN, visible=False),
        _candidate("", "bay03", "park_slot", INTERNAL_UNKNOWN, visible=False),
    )
    binding = resolve_target_binding(request, candidates, None)
    assert binding.status == BindingStatus.TEMPORARILY_NOT_VISIBLE
    assert binding.bay_id is None


def test_prior_binding_survives_label_permutation() -> None:
    request = parse_parking_instruction("停入左侧的空闲车位")
    prior = TargetBinding(
        status=BindingStatus.BOUND,
        instruction=request.raw,
        round_index=0,
        bay_id="bay03",
        slot_node_id="park_slot",
        selected_label="B",
        reason="unique",
    )
    # Round 2: the near/far order changed, so bay03 is now label A.
    candidates = (
        _candidate("A", "bay03", "park_slot", INTERNAL_VACANT),
        _candidate("B", "bay11", "bay11_slot", INTERNAL_OCCUPIED),
    )
    decision = parse_binding_decision("A: 空闲\nB: 占用\nSelected: A", ("A", "B"))
    binding = resolve_target_binding(
        request, candidates, decision, prior=prior, round_index=1
    )

    assert binding.status == BindingStatus.BOUND
    assert binding.bay_id == "bay03"
    assert binding.slot_node_id == "park_slot"
    assert binding.selected_label == "A"
    assert binding.prior_bay_id == "bay03"
    assert binding.round_index == 1


def test_prior_binding_is_not_rebound_to_another_bay() -> None:
    request = parse_parking_instruction("停入左侧的空闲车位")
    prior = TargetBinding(
        status=BindingStatus.BOUND,
        instruction=request.raw,
        round_index=0,
        bay_id="bay03",
        slot_node_id="park_slot",
        selected_label="B",
        reason="unique",
    )
    candidates = (
        _candidate("A", "bay03", "park_slot", INTERNAL_OCCUPIED),
        _candidate("B", "bay11", "bay11_slot", INTERNAL_VACANT),
    )
    decision = parse_binding_decision("A: 占用\nB: 空闲\nSelected: B", ("A", "B"))
    binding = resolve_target_binding(
        request, candidates, decision, prior=prior, round_index=1
    )

    assert binding.status == BindingStatus.INVALIDATED
    assert binding.bay_id == "bay03"
    assert binding.prior_bay_id == "bay03"
    assert not binding.executable


def test_prior_invalidated_stays_invalidated() -> None:
    request = parse_parking_instruction("停入左侧的空闲车位")
    prior = TargetBinding(
        status=BindingStatus.INVALIDATED,
        instruction=request.raw,
        round_index=1,
        bay_id="bay03",
        slot_node_id="park_slot",
        selected_label="B",
        reason="occupied",
    )
    candidates = _two_candidates(occupancy_a=INTERNAL_OCCUPIED)
    decision = parse_binding_decision("A: 占用\nB: 空闲\nSelected: B", ("A", "B"))
    binding = resolve_target_binding(
        request, candidates, decision, prior=prior, round_index=2
    )
    assert binding.status == BindingStatus.INVALIDATED
    assert binding.bay_id == "bay03"


def test_prior_binding_missing_from_view_is_temporarily_not_visible() -> None:
    request = parse_parking_instruction("停入左侧的空闲车位")
    prior = TargetBinding(
        status=BindingStatus.BOUND,
        instruction=request.raw,
        round_index=0,
        bay_id="bay03",
        slot_node_id="park_slot",
        selected_label="B",
        reason="unique",
    )
    candidates = (
        _candidate("A", "bay11", "bay11_slot", INTERNAL_VACANT),
        _candidate("", "bay03", "park_slot", INTERNAL_UNKNOWN, visible=False),
    )
    decision = parse_binding_decision("A: 空闲\nSelected: A", ("A",))
    binding = resolve_target_binding(
        request, candidates, decision, prior=prior, round_index=1
    )
    assert binding.status == BindingStatus.TEMPORARILY_NOT_VISIBLE
    assert binding.bay_id == "bay03"
    assert binding.prior_bay_id == "bay03"


def test_prior_binding_with_unknown_occupancy_is_unverified() -> None:
    request = parse_parking_instruction("停入左侧的空闲车位")
    prior = TargetBinding(
        status=BindingStatus.BOUND,
        instruction=request.raw,
        round_index=0,
        bay_id="bay03",
        slot_node_id="park_slot",
        selected_label="B",
        reason="unique",
    )
    candidates = (
        _candidate("A", "bay11", "bay11_slot", INTERNAL_OCCUPIED),
        _candidate("B", "bay03", "park_slot", INTERNAL_UNKNOWN),
    )
    decision = parse_binding_decision(
        "A: 占用\nB: 无法确定\nSelected: B", ("A", "B")
    )
    binding = resolve_target_binding(
        request, candidates, decision, prior=prior, round_index=1
    )
    assert binding.status == BindingStatus.UNVERIFIED
    assert binding.bay_id == "bay03"


def test_instruction_change_does_not_reuse_prior_binding() -> None:
    prior = TargetBinding(
        status=BindingStatus.BOUND,
        instruction="停入左侧的空闲车位",
        round_index=0,
        bay_id="bay03",
        slot_node_id="park_slot",
        selected_label="B",
        reason="unique",
    )
    request = parse_parking_instruction("停入左侧靠近出口的空闲车位")
    candidates = _two_candidates(occupancy_a=INTERNAL_OCCUPIED)
    decision = parse_binding_decision("A: 占用\nB: 空闲\nSelected: B", ("A", "B"))
    binding = resolve_target_binding(
        request, candidates, decision, prior=prior, round_index=1
    )
    assert binding.status == BindingStatus.REFUSED
    assert "instruction changed" in binding.reason


def test_unverified_exit_landmark_is_recorded_not_used() -> None:
    request = parse_parking_instruction("停入左侧靠近出口的空闲车位")
    candidates = _two_candidates(occupancy_a=INTERNAL_OCCUPIED)
    decision = parse_binding_decision("A: 占用\nB: 空闲\nSelected: B", ("A", "B"))
    binding = resolve_target_binding(request, candidates, decision)
    assert binding.status == BindingStatus.BOUND
    assert binding.evidence["landmark_used"] is False
    assert binding.evidence["landmark_verified"] is False


def test_decision_labels_must_match_visible_candidates() -> None:
    request = parse_parking_instruction("停入左侧的空闲车位")
    candidates = _two_candidates()
    decision = parse_binding_decision("A: 空闲\nSelected: A", ("A",))
    with pytest.raises(ValueError):
        resolve_target_binding(request, candidates, decision)


def test_artifact_round_trip_and_goal_resolution() -> None:
    request = parse_parking_instruction("停入左侧的空闲车位")
    candidates = _two_candidates(occupancy_a=INTERNAL_OCCUPIED)
    decision = parse_binding_decision("A: 占用\nB: 空闲\nSelected: B", ("A", "B"))
    binding = resolve_target_binding(request, candidates, decision)
    metadata = binding.to_metadata()
    text = json.dumps(metadata, ensure_ascii=False, allow_nan=False)
    restored = parse_binding_artifact(json.loads(text))

    assert isinstance(restored, BindingArtifact)
    assert restored.status == BindingStatus.BOUND
    assert restored.bay_id == "bay03"
    assert binding_goal_node(restored) == "park_slot"
    assert restored.instruction == request.raw


def test_non_bound_artifact_is_not_executable() -> None:
    metadata = {
        "status": BindingStatus.AMBIGUOUS,
        "instruction": "停入左侧的空闲车位",
        "round_index": 0,
        "bay_id": None,
        "slot_node_id": None,
        "selected_label": "A",
        "reason": "two candidates",
    }
    artifact = parse_binding_artifact(metadata)
    with pytest.raises(BindingNotExecutableError):
        binding_goal_node(artifact)


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"status": "bound", "instruction": "x", "round_index": 0},
        {"status": "nope", "instruction": "x", "round_index": 0},
        {"status": "bound", "instruction": "", "round_index": 0, "bay_id": "b", "slot_node_id": "s"},
        {"status": "bound", "instruction": "x", "round_index": -1, "bay_id": "b", "slot_node_id": "s"},
        {"status": "bound", "instruction": "x", "round_index": 0, "bay_id": "b"},
    ],
)
def test_invalid_artifact_is_refused(metadata: dict) -> None:
    with pytest.raises(ValueError):
        parse_binding_artifact(metadata)
