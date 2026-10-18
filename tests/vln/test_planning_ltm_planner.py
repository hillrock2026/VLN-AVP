"""Unit tests for candidate generation, hard constraints, costs and topology I/O."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from vln.planning_ltm import (
    Bounds,
    JsonTopologyStore,
    ParkingScene,
    ParkingTopology,
    RouteCandidate,
    StoreError,
    TopologyEdge,
    TopologyNode,
    ViolationCode,
    check_hard_constraints,
    generate_candidates,
    plan,
)
from vln.planning_ltm.scenarios import DEMO_AS_OF, scene_obstacle

_B_RESULT_LENGTH = 10.0 + 20.0 + (10.0**2 + 10.0**2) ** 0.5


def _codes(candidate: RouteCandidate, scene: ParkingScene = scene_obstacle()) -> set[str]:
    return {violation.code for violation in check_hard_constraints(scene, candidate)}


def test_scene_generates_three_distinct_candidates_deterministically() -> None:
    scene = scene_obstacle()
    first = generate_candidates(scene)
    second = generate_candidates(scene)

    assert first.to_dict() == second.to_dict()
    assert first.sufficient is True
    assert len(first.candidates) == 3
    assert len({candidate.route_key for candidate in first.candidates}) == 3
    assert len({candidate.candidate_id for candidate in first.candidates}) == 3
    for candidate in first.candidates:
        assert candidate.target_id == "P1"
        assert candidate.start_node_id == "S1"
        assert candidate.end_node_id == "P1"


def test_obstructed_route_is_retained_and_rejected_with_reason() -> None:
    scene = scene_obstacle()
    result = plan(scene, mode="base", as_of=DEMO_AS_OF)

    blocked = [
        evaluation
        for evaluation in result.selection.evaluations
        if "A2" in evaluation.candidate.node_ids
    ]
    assert len(blocked) == 1
    evaluation = blocked[0]
    assert evaluation.feasible is False
    assert evaluation.cost is None
    assert ViolationCode.BLOCKED_NODE in {
        violation.code for violation in evaluation.violations
    }
    assert "A2" in (evaluation.rejection_reason or "")
    assert result.selection.selected_candidate_id != evaluation.candidate_id
    # The candidate is retained, not silently removed.
    assert len(result.selection.evaluations) == 3


def test_target_mismatch_is_rejected_even_if_geometry_is_valid() -> None:
    scene = scene_obstacle()
    candidate = generate_candidates(scene).candidates[0]
    mismatch = RouteCandidate(
        candidate_id="target-mismatch",
        target_id="P2",
        node_ids=candidate.node_ids,
        edge_ids=candidate.edge_ids,
        length_m=candidate.length_m,
    )
    assert ViolationCode.TARGET_MISMATCH in _codes(mismatch, scene)


def test_route_that_does_not_end_at_target_is_rejected() -> None:
    scene = scene_obstacle()
    candidate = RouteCandidate(
        candidate_id="wrong-end",
        target_id="P1",
        node_ids=("S1", "B1", "B2"),
        edge_ids=("E-S1-B1", "E-B1-B2"),
        length_m=30.0,
    )
    assert ViolationCode.TARGET_NODE_MISMATCH in _codes(candidate, scene)


def test_disconnected_route_and_bad_edge_sequence_are_rejected() -> None:
    scene = scene_obstacle()
    disconnected = RouteCandidate(
        candidate_id="disconnected",
        target_id="P1",
        node_ids=("S1", "P1"),
        edge_ids=("E-S1-A1",),
        length_m=30.0,
    )
    assert ViolationCode.DISCONNECTED_ROUTE in _codes(disconnected, scene)

    bad_edges = RouteCandidate(
        candidate_id="bad-edges",
        target_id="P1",
        node_ids=("S1", "B1", "B2", "P1"),
        edge_ids=("E-S1-C1", "E-B1-B2", "E-B2-P1"),
        length_m=_B_RESULT_LENGTH,
    )
    codes = _codes(bad_edges, scene)
    assert ViolationCode.EDGE_SEQUENCE_MISMATCH in codes
    assert ViolationCode.BLOCKED_NODE not in codes


def test_no_feasible_candidate_returns_an_explicit_no_solution() -> None:
    scene = replace(
        scene_obstacle(),
        blocked_node_ids=frozenset({"A2", "B2", "C3"}),
    )
    result = plan(scene, mode="base", as_of=DEMO_AS_OF)

    assert len(result.selection.evaluations) == 3
    assert all(not evaluation.feasible for evaluation in result.selection.evaluations)
    assert all(evaluation.cost is None for evaluation in result.selection.evaluations)
    assert result.selection.selected_candidate_id is None
    assert result.selection.base_selected_candidate_id is None
    assert result.selection.no_solution_reason is not None
    assert "re-observed" in result.selection.no_solution_reason


def test_insufficient_candidates_are_reported_not_fabricated() -> None:
    topology = ParkingTopology(
        nodes=(
            TopologyNode("S", 0.0, 0.0, kind="entrance"),
            TopologyNode("T", 5.0, 0.0, kind="parking", target_id="T"),
        ),
        edges=(TopologyEdge("E-S-T", "S", "T"),),
    )
    scene = ParkingScene(
        scene_id="SYN-SINGLE-ROUTE",
        topology=topology,
        start_node_id="S",
        target_node_id="T",
        target_id="T",
    )
    candidate_set = generate_candidates(scene, max_candidates=3)

    assert len(candidate_set.candidates) == 1
    assert candidate_set.sufficient is False
    assert candidate_set.insufficient_reason is not None
    assert "no alternative routes were fabricated" in candidate_set.insufficient_reason

    result = plan(scene, mode="base", as_of=DEMO_AS_OF)
    assert len(result.selection.evaluations) == 1
    assert result.selection.selected_candidate_id == candidate_set.candidates[0].candidate_id


def test_disconnected_scene_reports_zero_candidates_without_fabrication() -> None:
    topology = ParkingTopology(
        nodes=(
            TopologyNode("S", 0.0, 0.0, kind="entrance"),
            TopologyNode("T", 5.0, 0.0, kind="parking", target_id="T"),
        ),
        edges=(),
    )
    scene = ParkingScene(
        scene_id="SYN-NO-ROUTE",
        topology=topology,
        start_node_id="S",
        target_node_id="T",
        target_id="T",
    )
    candidate_set = generate_candidates(scene)
    assert candidate_set.candidates == ()
    assert candidate_set.sufficient is False

    result = plan(scene, mode="base", as_of=DEMO_AS_OF)
    assert result.selection.selected_candidate_id is None
    assert result.selection.no_solution_reason is not None


def test_length_limit_rejects_all_remaining_routes() -> None:
    scene = replace(scene_obstacle(), max_length_m=35.0)
    result = plan(scene, mode="base", as_of=DEMO_AS_OF)
    codes = {
        violation.code
        for evaluation in result.selection.evaluations
        for violation in evaluation.violations
    }
    assert ViolationCode.LENGTH_LIMIT in codes
    assert result.selection.selected_candidate_id is None


def test_turn_limit_rejects_candidates_with_too_many_turns() -> None:
    scene = replace(scene_obstacle(), max_turn_count=1)
    result = plan(scene, mode="base", as_of=DEMO_AS_OF)
    codes = {
        violation.code
        for evaluation in result.selection.evaluations
        for violation in evaluation.violations
    }
    assert ViolationCode.TURN_LIMIT in codes
    assert result.selection.selected_candidate_id is None


def test_allowed_area_rejects_nodes_outside_the_declared_bounds() -> None:
    scene = replace(scene_obstacle(), allowed_bounds=Bounds(0.0, 0.0, 25.0, 5.0))
    result = plan(scene, mode="base", as_of=DEMO_AS_OF)
    codes = {
        violation.code
        for evaluation in result.selection.evaluations
        for violation in evaluation.violations
    }
    assert ViolationCode.OUTSIDE_ALLOWED_AREA in codes
    assert result.selection.selected_candidate_id is None


def test_cost_components_are_explainable_and_deterministic() -> None:
    scene = scene_obstacle()
    first = plan(scene, mode="base", as_of=DEMO_AS_OF)
    second = plan(scene, mode="base", as_of=DEMO_AS_OF)
    assert first.selection.to_dict() == second.selection.to_dict()

    b_route = next(
        evaluation
        for evaluation in first.selection.evaluations
        if evaluation.candidate.route_key == "S1>B1>B2>P1"
    )
    assert b_route.cost is not None
    assert b_route.cost.length_component == pytest.approx(_B_RESULT_LENGTH)
    assert b_route.cost.turn_count == 2
    assert b_route.cost.turn_component == pytest.approx(4.0)
    assert b_route.cost.risk_component == 0.0
    assert b_route.cost.ltm_component == 0.0
    assert b_route.cost.base_total == pytest.approx(_B_RESULT_LENGTH + 4.0)
    assert b_route.cost.total == pytest.approx(b_route.cost.base_total)


def test_topology_store_round_trip_and_queries(tmp_path: Path) -> None:
    path = tmp_path / "topology.json"
    store = JsonTopologyStore.create(path, scene_obstacle().topology)
    loaded = store.load()

    assert loaded.node("S1").kind == "entrance"
    assert loaded.target_node("P1").node_id == "P1"
    assert loaded.edge_between("A1", "S1").edge_id == "E-S1-A1"
    assert loaded.neighbors("S1") == (
        ("A1", "E-S1-A1"),
        ("B1", "E-S1-B1"),
        ("C1", "E-S1-C1"),
    )
    assert loaded.route_length(("S1", "B1", "B2", "P1")) == pytest.approx(
        _B_RESULT_LENGTH
    )
    with pytest.raises(StoreError):
        JsonTopologyStore.create(path, scene_obstacle().topology)
