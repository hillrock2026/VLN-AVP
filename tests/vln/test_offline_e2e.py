"""NAV-18 offline end-to-end tests.

Data provenance used here:

* ``frozen-replay`` - the exact raw model text preserved in
  ``docs/M1-VLN-NAV-15-RAW.jsonl``; replayed offline, no new inference;
* ``synthetic`` - constructed decision text/topologies for deterministic tests.

No test in this module calls a model, host, kernel or executor.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from vln.nav import ConstraintSource, VehiclePose
from vln.nav.offline_e2e import (
    DEMO_AS_OF,
    DEMO_POSE,
    DecisionSource,
    OfflineEndToEndStatus,
    VisualDecisionInput,
    build_demo,
    demo_cases,
    direction_scene,
    frozen_nav15_decision,
    main,
    run_offline_decision,
    synthetic_left_decision,
)
from vln.planning_ltm import (
    EvidenceLevel,
    LongTermMemoryStore,
    MemoryEffect,
    MemoryKind,
    MODE_BASE,
    MODE_LTM,
    ViolationCode,
    plan,
)

_REPO = Path(__file__).resolve().parents[2]


def _case(name: str):
    return next(item for item in demo_cases() if item.name == name)


def _evaluation(result, route_key: str):
    return next(
        evaluation
        for evaluation in result.planning.planning.selection.evaluations
        if evaluation.candidate.route_key == route_key
    )


def _codes(evaluation) -> set[str]:
    return {violation.code for violation in evaluation.violations}


# ----------------------------------------------------------------------
# LEFT / STRAIGHT / conflict
# ----------------------------------------------------------------------


def test_left_frozen_replay_reaches_planner_and_selects_left_route() -> None:
    case = _case("left")
    result = run_offline_decision(
        case.scene, case.decision_input, pose=DEMO_POSE, as_of=DEMO_AS_OF
    )

    assert result.status == OfflineEndToEndStatus.SELECTED
    assert result.ok is True
    assert result.decision_input.source == DecisionSource.FROZEN_REPLAY

    # The text went through the real parser/verifier.
    assert result.decision is not None and result.decision.direction == "LEFT"
    assert result.directive is not None and result.directive.direction == "LEFT"

    # The verified directive became a hard planner constraint.
    assert result.constraint is not None
    assert result.constraint.direction == "LEFT"
    assert result.constraint.source == ConstraintSource.VERIFIED_DIRECTIVE
    assert result.constraint.HARD is True

    assert result.selected_candidate_id == "cand-NAV18-DIRECTION-02"
    east = _evaluation(result, "S>A>A2>M>T")
    assert east.feasible is False
    assert east.cost is None
    assert ViolationCode.NAVIGATION_DIRECTION_MISMATCH in _codes(east)

    payload = result.to_dict()
    assert payload["planning_only"] is True
    assert payload["executed"] is False
    assert payload["physical_arrival"] == "not-evaluated"
    assert payload["constraint"]["source"] == ConstraintSource.VERIFIED_DIRECTIVE


def test_straight_frozen_replay_changes_selection_vs_unconstrained_plan() -> None:
    scene = direction_scene()
    base = plan(scene, mode=MODE_BASE, as_of=DEMO_AS_OF)
    # Unconstrained: north route is cheaper (34.0 vs 35.0).
    assert base.selection.selected_candidate_id == "cand-NAV18-DIRECTION-02"

    case = _case("straight")
    result = run_offline_decision(
        case.scene, case.decision_input, pose=DEMO_POSE, as_of=DEMO_AS_OF
    )

    assert result.status == OfflineEndToEndStatus.SELECTED
    assert result.decision is not None and result.decision.direction == "STRAIGHT"
    assert result.constraint is not None
    assert result.constraint.direction == "STRAIGHT"
    assert result.selected_candidate_id == "cand-NAV18-DIRECTION-01"
    assert result.selected_candidate_id != base.selection.selected_candidate_id

    north = _evaluation(result, "S>B>M>T")
    assert north.feasible is False
    assert ViolationCode.NAVIGATION_DIRECTION_MISMATCH in _codes(north)
    assert north.cost is None


def test_conflict_returns_explicit_failure_without_violating_fallback() -> None:
    case = _case("conflict")
    result = run_offline_decision(
        case.scene, case.decision_input, pose=DEMO_POSE, as_of=DEMO_AS_OF
    )

    assert result.status == OfflineEndToEndStatus.CONSTRAINT_CONFLICT
    assert result.ok is False
    assert result.selected_candidate_id is None
    assert result.planning is not None
    assert result.planning.constraint_conflict is True
    assert result.planning.satisfying_candidate_ids == ()
    assert result.planning.violating_candidate_ids == ("cand-NAV18-CONFLICT-01",)
    assert "no violating fallback" in result.reason

    selection = result.planning.planning.selection
    assert selection.selected_candidate_id is None
    assert len(selection.evaluations) == 1
    only = selection.evaluations[0]
    assert only.feasible is False
    assert only.cost is None
    assert ViolationCode.NAVIGATION_DIRECTION_MISMATCH in _codes(only)


# ----------------------------------------------------------------------
# Invalid decision inputs
# ----------------------------------------------------------------------


def test_malformed_decision_stops_before_planning() -> None:
    case = _case("invalid")
    result = run_offline_decision(
        case.scene, case.decision_input, pose=DEMO_POSE, as_of=DEMO_AS_OF
    )

    assert result.status == OfflineEndToEndStatus.DECISION_INVALID
    assert result.ok is False
    assert result.decision is None
    assert result.directive is None
    assert result.constraint is None
    assert result.planning is None
    assert result.error_type == "VisualDecisionParseError"
    assert "Relative position" in (result.error_message or "")


def test_failed_verification_stops_before_planning() -> None:
    raw = (
        "Target: 出口\n"
        "Identified as: 出口\n"
        "Visible: 否\n"
        "Relative position: LEFT\n"
        "Next direction: LEFT\n"
        "Evidence: 合成测试文本，并非模型输出。\n"
    )
    decision_input = VisualDecisionInput(
        raw_text=raw,
        expected_identity="出口",
        source=DecisionSource.SYNTHETIC,
        source_ref="nav18-not-visible-fixture",
        note="Synthetic verification-failure input.",
    )
    result = run_offline_decision(
        direction_scene(), decision_input, pose=DEMO_POSE, as_of=DEMO_AS_OF
    )

    assert result.status == OfflineEndToEndStatus.DECISION_INVALID
    # Parsing succeeded, verification did not.
    assert result.decision is not None
    assert result.decision.direction == "LEFT"
    assert result.directive is None
    assert result.constraint is None
    assert result.planning is None
    assert result.error_type == "TargetNotVisibleError"


# ----------------------------------------------------------------------
# LTM and explicit pose
# ----------------------------------------------------------------------


def test_ltm_cannot_override_the_end_to_end_hard_constraint(tmp_path: Path) -> None:
    case = _case("straight")
    store = LongTermMemoryStore.create(tmp_path / "ltm.json")
    memory = store.add(
        kind=MemoryKind.CONFIRMED_FACT,
        statement="synthetic preference for the north route",
        source="nav18-test",
        confidence=1.0,
        evidence_level=EvidenceLevel.CONFIRMED,
        effect=MemoryEffect.PREFER,
        scene_id=case.scene.scene_id,
        target_id=case.scene.target_id,
        route_key="S>B>M>T",
        node_ids=("S", "B", "M", "T"),
        created_at=DEMO_AS_OF,
    )

    # Without the visual constraint, LTM selects the preferred north route.
    unconstrained = plan(
        case.scene, mode=MODE_LTM, ltm_store=store, as_of=DEMO_AS_OF
    )
    assert unconstrained.selection.selected_candidate_id == "cand-NAV18-DIRECTION-02"

    result = run_offline_decision(
        case.scene,
        case.decision_input,
        pose=DEMO_POSE,
        mode=MODE_LTM,
        ltm_store=store,
        as_of=DEMO_AS_OF,
    )

    assert result.status == OfflineEndToEndStatus.SELECTED
    assert result.selected_candidate_id == "cand-NAV18-DIRECTION-01"
    north = _evaluation(result, "S>B>M>T")
    assert north.feasible is False
    assert north.ltm_applications == ()
    assert any(
        item.memory_id == memory.memory_id and item.reason == "candidate-infeasible"
        for item in result.planning.planning.selection.ignored_memories
    )


def test_explicit_pose_changes_the_relative_direction_result() -> None:
    # Heading -90° makes LEFT point east (+X), so the east route satisfies it.
    pose = VehiclePose(x=0.0, y=0.0, heading=-math.pi / 2.0)
    result = run_offline_decision(
        direction_scene(),
        frozen_nav15_decision(0),  # LEFT
        pose=pose,
        as_of=DEMO_AS_OF,
    )

    assert result.status == OfflineEndToEndStatus.SELECTED
    assert result.selected_candidate_id == "cand-NAV18-DIRECTION-01"
    assert result.to_dict()["pose"]["heading"] == pytest.approx(-math.pi / 2.0)
    north = _evaluation(result, "S>B>M>T")
    assert north.feasible is False
    assert ViolationCode.NAVIGATION_DIRECTION_MISMATCH in _codes(north)


# ----------------------------------------------------------------------
# Provenance and determinism
# ----------------------------------------------------------------------


def test_frozen_replay_matches_nav15_raw_and_is_not_live_model() -> None:
    raw_path = _REPO / "docs" / "M1-VLN-NAV-15-RAW.jsonl"
    if not raw_path.is_file():
        pytest.skip("NAV-15 RAW evidence is not present")

    rounds: dict[int, str] = {}
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("event") == "round":
            rounds[record["round_index"]] = record["raw_model_output"]
    if 0 not in rounds or 1 not in rounds:
        pytest.skip("NAV-15 RAW evidence does not contain both rounds")

    round_0 = frozen_nav15_decision(0)
    round_1 = frozen_nav15_decision(1)
    assert round_0.raw_text == rounds[0]
    assert round_1.raw_text == rounds[1]
    assert round_0.source == DecisionSource.FROZEN_REPLAY
    assert "NAV-15-RAW.jsonl#round=0" in round_0.source_ref
    assert round_0.model == "ZDTaichu5.0-9B"

    # The offline module must never label a replay as a new live inference.
    assert all(
        item.decision_input.source != DecisionSource.LIVE_MODEL
        for item in demo_cases()
    )


def test_synthetic_decision_remains_labeled_synthetic() -> None:
    decision_input = synthetic_left_decision()
    result = run_offline_decision(
        direction_scene(), decision_input, pose=DEMO_POSE, as_of=DEMO_AS_OF
    )

    assert result.status == OfflineEndToEndStatus.SELECTED
    assert result.decision_input.source == DecisionSource.SYNTHETIC
    # Type-level provenance of the constraint factory remains distinct.
    assert result.constraint is not None
    assert result.constraint.source == ConstraintSource.VERIFIED_DIRECTIVE
    assert result.to_dict()["decision_input"]["source"] == "synthetic"


def test_same_input_replays_deterministically() -> None:
    case = _case("straight")
    first = run_offline_decision(
        case.scene, case.decision_input, pose=DEMO_POSE, as_of=DEMO_AS_OF
    )
    second = run_offline_decision(
        case.scene, case.decision_input, pose=DEMO_POSE, as_of=DEMO_AS_OF
    )
    assert first.to_dict() == second.to_dict()


# ----------------------------------------------------------------------
# Demo / CLI
# ----------------------------------------------------------------------


def test_demo_runs_all_four_cases() -> None:
    payload = build_demo()
    statuses = {
        item["case"]: item["result"]["status"] for item in payload["cases"]
    }
    assert statuses == {
        "left": OfflineEndToEndStatus.SELECTED,
        "straight": OfflineEndToEndStatus.SELECTED,
        "conflict": OfflineEndToEndStatus.CONSTRAINT_CONFLICT,
        "invalid": OfflineEndToEndStatus.DECISION_INVALID,
    }
    assert payload["simulation_only"] is True
    assert payload["planning_only"] is True
    assert payload["executed"] is False
    assert set(payload["data_sources"]) == {
        DecisionSource.FROZEN_REPLAY,
        DecisionSource.SYNTHETIC,
    }


def test_cli_prints_a_single_case_as_json(capsys: object) -> None:
    exit_code = main(["--case", "left", "--indent", "0"])
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert len(payload["cases"]) == 1
    result = payload["cases"][0]["result"]
    assert result["status"] == OfflineEndToEndStatus.SELECTED
    assert result["selected_candidate_id"] == "cand-NAV18-DIRECTION-02"
    assert result["directive"]["direction"] == "LEFT"
