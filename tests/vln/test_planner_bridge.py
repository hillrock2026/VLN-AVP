"""NAV-17 bridge tests (T1-T7).

The direction constraints used here are explicitly marked as synthetic offline
data. The one verified-directive test parses a frozen text fixture through the
real parser/verifier; it is **not** a live model call and is not presented as
real model output.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from vln.intent.agent_intent import AgentIntent, Target
from vln.nav import (
    ConstraintBuildStatus,
    ConstraintSource,
    NavigationConstraint,
    NavigationConstraintError,
    NavigationPlanningStatus,
    VehiclePose,
    constraint_from_agent_intent,
    constraint_from_directive,
    parse_visual_decision,
    plan_with_navigation_constraint,
    synthetic_navigation_constraint,
    verify_visual_decision,
)
from vln.planning_ltm import (
    EvidenceLevel,
    LongTermMemoryStore,
    MemoryEffect,
    MemoryKind,
    ParkingScene,
    ParkingTopology,
    TopologyEdge,
    TopologyNode,
    ViolationCode,
    plan,
    MODE_BASE,
    MODE_LTM,
)

_AS_OF = "2026-10-17T00:00:00Z"


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _direction_scene(scene_id: str = "NAV17-DIRECTION") -> ParkingScene:
    """Two routes from S to T.

    East route:  S>A>A2>M>T, first heading 0°, 1 turn, risk 3 -> cost 35.
    North route: S>B>M>T,   first heading 90°, 2 turns, risk 0 -> cost 34.

    The north route is therefore cheaper; the base planner selects it. This
    makes a STRAIGHT hard constraint observably change the selection.
    """

    nodes = (
        TopologyNode("S", 0.0, 0.0, kind="entrance"),
        TopologyNode("A", 5.0, 0.0),
        TopologyNode("A2", 10.0, 0.0),
        TopologyNode("B", 0.0, 10.0),
        TopologyNode("M", 10.0, 10.0),
        TopologyNode("T", 10.0, 20.0, kind="parking", target_id="T"),
    )
    edges = (
        TopologyEdge("E-S-A", "S", "A", risk=1.0),
        TopologyEdge("E-A-A2", "A", "A2", risk=1.0),
        TopologyEdge("E-A2-M", "A2", "M", risk=1.0),
        TopologyEdge("E-M-T", "M", "T", risk=0.0),
        TopologyEdge("E-S-B", "S", "B", risk=0.0),
        TopologyEdge("E-B-M", "B", "M", risk=0.0),
    )
    return ParkingScene(
        scene_id=scene_id,
        topology=ParkingTopology(nodes=nodes, edges=edges),
        start_node_id="S",
        target_node_id="T",
        target_id="T",
    )


def _multi_satisfying_scene() -> ParkingScene:
    """Two routes whose first segment is north (LEFT); both satisfy LEFT."""

    nodes = (
        TopologyNode("S", 0.0, 0.0, kind="entrance"),
        TopologyNode("B", 0.0, 10.0),
        TopologyNode("C", 0.0, 20.0),
        TopologyNode("M", 10.0, 10.0),
        TopologyNode("T", 10.0, 20.0, kind="parking", target_id="T"),
    )
    edges = (
        TopologyEdge("E-S-B", "S", "B"),
        TopologyEdge("E-B-C", "B", "C"),
        TopologyEdge("E-C-T", "C", "T"),
        TopologyEdge("E-B-M", "B", "M"),
        TopologyEdge("E-M-T", "M", "T"),
    )
    return ParkingScene(
        scene_id="NAV17-MULTI",
        topology=ParkingTopology(nodes=nodes, edges=edges),
        start_node_id="S",
        target_node_id="T",
        target_id="T",
    )


def _offline_verified_directive(direction: str):
    """A directive from frozen offline text parsed/verified by the real layers."""

    position = {"LEFT": "LEFT", "RIGHT": "RIGHT", "STRAIGHT": "AHEAD"}[direction]
    raw = (
        "Target: T\n"
        "Identified as: T\n"
        "Visible: 是\n"
        f"Relative position: {position}\n"
        f"Next direction: {direction}\n"
        "Evidence: 离线固化测试文本，并非实时模型输出\n"
    )
    return verify_visual_decision(
        parse_visual_decision(raw), expected_identity="T"
    )


def _evaluation(result, route_key: str):
    return next(
        evaluation
        for evaluation in result.planning.selection.evaluations
        if evaluation.candidate.route_key == route_key
    )


def _codes(evaluation) -> set[str]:
    return {violation.code for violation in evaluation.violations}


# ----------------------------------------------------------------------
# T1: LEFT hard constraint
# ----------------------------------------------------------------------


def test_t1_left_constraint_rejects_straight_route_and_selects_left_route() -> None:
    scene = _direction_scene()
    base = plan(scene, mode=MODE_BASE, as_of=_AS_OF)
    # Both routes are feasible; north is cheaper than east.
    assert base.selection.selected_candidate_id == "cand-NAV17-DIRECTION-02"

    constraint = synthetic_navigation_constraint("LEFT")
    assert constraint.source == ConstraintSource.SYNTHETIC_OFFLINE
    assert constraint.required_heading == pytest.approx(math.pi / 2.0)

    result = plan_with_navigation_constraint(scene, constraint, as_of=_AS_OF)

    assert result.status == NavigationPlanningStatus.SELECTED
    assert result.selected_candidate_id == "cand-NAV17-DIRECTION-02"
    assert result.selected_route_satisfies_constraint is True
    assert result.satisfying_candidate_ids == ("cand-NAV17-DIRECTION-02",)

    straight = _evaluation(result, "S>A>A2>M>T")
    assert straight.feasible is False
    assert straight.cost is None
    assert ViolationCode.NAVIGATION_DIRECTION_MISMATCH in _codes(straight)
    assert "LEFT" in (straight.rejection_reason or "")


# ----------------------------------------------------------------------
# T2: STRAIGHT hard constraint changes the selection
# ----------------------------------------------------------------------


def test_t2_straight_constraint_filters_out_the_cheaper_north_route() -> None:
    scene = _direction_scene()
    base = plan(scene, mode=MODE_BASE, as_of=_AS_OF)
    assert base.selection.selected_candidate_id == "cand-NAV17-DIRECTION-02"

    constraint = synthetic_navigation_constraint("STRAIGHT")
    result = plan_with_navigation_constraint(scene, constraint, as_of=_AS_OF)

    assert result.status == NavigationPlanningStatus.SELECTED
    assert result.selected_candidate_id == "cand-NAV17-DIRECTION-01"
    assert result.selected_candidate_id != base.selection.selected_candidate_id

    north = _evaluation(result, "S>B>M>T")
    assert north.feasible is False
    assert ViolationCode.NAVIGATION_DIRECTION_MISMATCH in _codes(north)
    straight = _evaluation(result, "S>A>A2>M>T")
    assert straight.feasible is True


# ----------------------------------------------------------------------
# T3: constraint / topology conflict
# ----------------------------------------------------------------------


def test_t3_no_route_satisfies_right_constraint_and_no_fallback_is_selected() -> None:
    scene = _direction_scene()
    constraint = synthetic_navigation_constraint("RIGHT")
    result = plan_with_navigation_constraint(scene, constraint, as_of=_AS_OF)

    assert result.status == NavigationPlanningStatus.CONSTRAINT_CONFLICT
    assert result.constraint_conflict is True
    assert result.selected_candidate_id is None
    assert result.satisfying_candidate_ids == ()
    assert len(result.violating_candidate_ids) == 2
    assert "no violating fallback" in result.reason

    plan_result = result.planning.selection
    assert plan_result.selected_candidate_id is None
    assert all(not evaluation.feasible for evaluation in plan_result.evaluations)
    assert all(evaluation.cost is None for evaluation in plan_result.evaluations)


# ----------------------------------------------------------------------
# T4: multiple satisfying routes -> NAV-16 still ranks them
# ----------------------------------------------------------------------


def test_t4_multiple_satisfying_routes_are_still_ranked_by_nav16_cost() -> None:
    scene = _multi_satisfying_scene()
    constraint = synthetic_navigation_constraint("LEFT")
    result = plan_with_navigation_constraint(scene, constraint, as_of=_AS_OF)

    assert result.status == NavigationPlanningStatus.SELECTED
    assert set(result.satisfying_candidate_ids) == {
        "cand-NAV17-MULTI-01",
        "cand-NAV17-MULTI-02",
    }
    assert result.violating_candidate_ids == ()

    selected = result.selected_evaluation
    assert selected is not None
    assert selected.candidate.route_key == "S>B>C>T"
    assert selected.cost is not None
    assert selected.cost.total == pytest.approx(32.0)

    other = _evaluation(result, "S>B>M>T")
    assert other.feasible is True
    assert other.cost is not None
    assert other.cost.total == pytest.approx(34.0)

    # The bridge did not re-rank: NAV-16's own base choice is the same route.
    base = plan(scene, mode=MODE_BASE, as_of=_AS_OF)
    assert result.selected_candidate_id == base.selection.selected_candidate_id


# ----------------------------------------------------------------------
# T5: LTM cannot override the hard constraint
# ----------------------------------------------------------------------


def test_t5_ltm_cannot_resurrect_a_route_violating_the_hard_constraint(
    tmp_path: Path,
) -> None:
    scene = _direction_scene()
    store = LongTermMemoryStore.create(tmp_path / "ltm.json")
    memory = store.add(
        kind=MemoryKind.CONFIRMED_FACT,
        statement="synthetic preference for the north route",
        source="nav17-test",
        confidence=1.0,
        evidence_level=EvidenceLevel.CONFIRMED,
        effect=MemoryEffect.PREFER,
        scene_id=scene.scene_id,
        target_id=scene.target_id,
        route_key="S>B>M>T",
        node_ids=("S", "B", "M", "T"),
        created_at=_AS_OF,
    )

    # Without the direction constraint, LTM keeps/strengthens the north choice.
    ltm_plan = plan(scene, mode=MODE_LTM, ltm_store=store, as_of=_AS_OF)
    assert ltm_plan.selection.selected_candidate_id == "cand-NAV17-DIRECTION-02"

    constraint = synthetic_navigation_constraint("STRAIGHT")
    result = plan_with_navigation_constraint(
        scene,
        constraint,
        mode=MODE_LTM,
        ltm_store=store,
        as_of=_AS_OF,
    )

    assert result.status == NavigationPlanningStatus.SELECTED
    assert result.selected_candidate_id == "cand-NAV17-DIRECTION-01"
    north = _evaluation(result, "S>B>M>T")
    assert north.feasible is False
    assert north.ltm_applications == ()
    assert ViolationCode.NAVIGATION_DIRECTION_MISMATCH in _codes(north)
    assert any(
        item.memory_id == memory.memory_id and item.reason == "candidate-infeasible"
        for item in result.planning.selection.ignored_memories
    )
    assert all(
        application.candidate_id != "cand-NAV17-DIRECTION-02"
        for application in result.planning.selection.applied_memories
    )


# ----------------------------------------------------------------------
# T6: invalid or insufficient inputs fail explicitly
# ----------------------------------------------------------------------


def test_t6_invalid_constraint_inputs_fail_explicitly() -> None:
    scene = _direction_scene()

    with pytest.raises(NavigationConstraintError):
        NavigationConstraint(
            direction="UP",
            reference_heading=0.0,
            source=ConstraintSource.SYNTHETIC_OFFLINE,
        )
    with pytest.raises(NavigationConstraintError):
        NavigationConstraint(
            direction="LEFT",
            reference_heading=float("nan"),
            source=ConstraintSource.SYNTHETIC_OFFLINE,
        )
    with pytest.raises(NavigationConstraintError):
        NavigationConstraint(
            direction="LEFT",
            reference_heading=0.0,
            source="manual-unmarked",
        )
    with pytest.raises(NavigationConstraintError):
        NavigationConstraint(
            direction="LEFT",
            reference_heading=0.0,
            source=ConstraintSource.SYNTHETIC_OFFLINE,
            tolerance_rad=math.pi / 2.0,
        )
    with pytest.raises(NavigationConstraintError):
        constraint_from_directive(object(), pose=VehiclePose(0.0, 0.0, 0.0))
    with pytest.raises(NavigationConstraintError):
        constraint_from_directive(
            _offline_verified_directive("LEFT"), pose=object()  # type: ignore[arg-type]
        )
    with pytest.raises(NavigationConstraintError):
        plan_with_navigation_constraint(scene, None)
    with pytest.raises(NavigationConstraintError):
        plan_with_navigation_constraint(scene, "LEFT")  # type: ignore[arg-type]


def test_t6_agent_intent_is_explicitly_insufficient_for_a_direction_constraint() -> None:
    intent = AgentIntent(
        intent_id="nav17-intent-0",
        target=Target(x=1.0, y=2.0, heading=0.5),
    )
    result = constraint_from_agent_intent(
        intent, pose=VehiclePose(0.0, 0.0, 0.0)
    )

    # The frozen v1 object really has no direction field to read.
    assert set(intent.to_object()) == {
        "contract_version",
        "intent_id",
        "action",
        "target",
    }
    assert result.status == ConstraintBuildStatus.INSUFFICIENT
    assert result.ok is False
    assert result.constraint is None
    assert result.intent_id == "nav17-intent-0"
    assert "no direction" in result.reason

    invalid = constraint_from_agent_intent(object())
    assert invalid.status == ConstraintBuildStatus.INVALID
    assert invalid.constraint is None


# ----------------------------------------------------------------------
# T7: determinism and provenance
# ----------------------------------------------------------------------


def test_t7_same_input_and_ltm_state_replay_identically(tmp_path: Path) -> None:
    scene = _direction_scene()
    store = LongTermMemoryStore.create(tmp_path / "ltm.json")
    store.add(
        kind=MemoryKind.CONFIRMED_FACT,
        statement="synthetic preference for the north route",
        source="nav17-test",
        confidence=0.9,
        evidence_level=EvidenceLevel.CONFIRMED,
        effect=MemoryEffect.PREFER,
        scene_id=scene.scene_id,
        target_id=scene.target_id,
        route_key="S>B>M>T",
        node_ids=("S", "B", "M", "T"),
        created_at=_AS_OF,
    )
    constraint = synthetic_navigation_constraint("STRAIGHT")

    first = plan_with_navigation_constraint(
        scene, constraint, mode=MODE_LTM, ltm_store=store, as_of=_AS_OF
    )
    second = plan_with_navigation_constraint(
        scene, constraint, mode=MODE_LTM, ltm_store=store, as_of=_AS_OF
    )

    assert first.to_dict() == second.to_dict()
    assert first.selected_candidate_id == second.selected_candidate_id


def test_t7_verified_directive_and_synthetic_constraint_keep_distinct_provenance() -> None:
    directive = _offline_verified_directive("LEFT")
    verified = constraint_from_directive(
        directive, pose=VehiclePose(x=12.5, y=-4.0, heading=0.25)
    )
    assert verified.source == ConstraintSource.VERIFIED_DIRECTIVE
    assert verified.identified_as == "T"
    assert "离线固化测试文本" in verified.evidence
    assert verified.required_heading == pytest.approx(0.25 + math.pi / 2.0)

    synthetic = synthetic_navigation_constraint("LEFT")
    assert synthetic.source == ConstraintSource.SYNTHETIC_OFFLINE
    assert synthetic.source != verified.source


def test_pose_heading_makes_direction_relative() -> None:
    # Heading -90° means LEFT points to +X (east); the east route satisfies it.
    scene = _direction_scene()
    constraint = constraint_from_directive(
        _offline_verified_directive("LEFT"),
        pose=VehiclePose(x=0.0, y=0.0, heading=-math.pi / 2.0),
    )
    result = plan_with_navigation_constraint(scene, constraint, as_of=_AS_OF)

    assert result.selected_evaluation is not None
    assert result.selected_evaluation.candidate.route_key == "S>A>A2>M>T"
    north = _evaluation(result, "S>B>M>T")
    assert north.feasible is False
    assert ViolationCode.NAVIGATION_DIRECTION_MISMATCH in _codes(north)
