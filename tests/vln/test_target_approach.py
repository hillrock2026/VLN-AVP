"""Offline tests for the bound-bay approach area and independent verdict.

Module under test: :mod:`vln.carla.target_approach`.
"""

from __future__ import annotations

import math

import pytest

from vln.carla.goal import GoalSpec, evaluate_goal
from vln.carla.parking_verdict import PARKING_SLOT_NODE_ID
from vln.carla.underground_carpark_parking import (
    BAY11_SLOT_NODE_ID,
    underground_carpark_parking_graph,
)
from vln.carla.target_approach import (
    APPROACH_NODE_BY_SLOT,
    approach_node_for_slot,
    evaluate_target_approach,
)
from vln.nav import VehiclePose
from vln.nav.target_binding import BindingArtifact


def _binding(status: str = "bound", bay_id: str = "bay03", slot: str = "park_slot"):
    return BindingArtifact(
        status=status,
        instruction="请将车辆停入左侧靠近出口的空闲车位",
        bay_id=bay_id,
        slot_node_id=slot,
        round_index=0,
        selected_label="B",
        reason="unique",
    )


def _goal_ok(
    node_id: str = "park_entry",
    *,
    x: float = -4.0,
    y: float = -17.74,
    pose_x: float | None = None,
    pose_y: float | None = None,
):
    spec = GoalSpec(
        node_id=node_id,
        x=x,
        y=y,
        heading_rad=-math.pi / 2.0,
        distance_tolerance_m=1.5,
        heading_tolerance_rad=math.radians(30.0),
        stop_speed_mps=0.25,
    )
    return evaluate_goal(
        spec,
        VehiclePose(
            x=x if pose_x is None else pose_x,
            y=y if pose_y is None else pose_y,
            heading=-math.pi / 2.0,
        ),
        speed_mps=0.0,
        stopped=True,
    )


def test_approach_nodes_are_real_graph_predecessors() -> None:
    graph = underground_carpark_parking_graph()
    assert approach_node_for_slot(PARKING_SLOT_NODE_ID) == "park_entry"
    assert approach_node_for_slot(BAY11_SLOT_NODE_ID) == "bay11_turn"
    for slot, approach in APPROACH_NODE_BY_SLOT.items():
        predecessors = {name for name, _ in graph.predecessors(slot)}
        assert approach in predecessors
        assert approach != slot
        assert graph.has_node(approach)
    with pytest.raises(KeyError):
        approach_node_for_slot("unknown_slot")
    with pytest.raises(ValueError):
        approach_node_for_slot("")


def test_valid_real_stop_is_accepted() -> None:
    verdict = evaluate_target_approach(
        task_id="cap07b-01",
        binding=_binding(),
        approach_node_id="park_entry",
        goal_evaluation=_goal_ok(),
        collision_count=0,
        kernel_execution_status="completed",
    )
    assert verdict.ok
    assert verdict.target_id == "bay03"
    assert verdict.bay_id == "bay03"
    assert verdict.slot_node_id == "park_slot"
    assert verdict.reasons == ()
    meta = verdict.to_metadata()
    assert meta["goal"]["ok"] is True
    assert meta["approach_node_id"] == "park_entry"


def test_target_identity_change_is_refused() -> None:
    verdict = evaluate_target_approach(
        task_id="cap07b-01",
        binding=_binding(),
        approach_node_id="park_entry",
        goal_evaluation=_goal_ok(),
        target_id="bay11",
    )
    assert not verdict.ok
    assert "target_id_changed_without_evidence" in verdict.reasons


def test_goal_failure_and_collision_are_refused() -> None:
    far_goal = evaluate_target_approach(
        task_id="cap07b-01",
        binding=_binding(),
        approach_node_id="park_entry",
        goal_evaluation=_goal_ok(pose_y=-10.0),
    )
    assert not far_goal.ok
    assert any(reason.startswith("approach_distance") for reason in far_goal.reasons)

    collision = evaluate_target_approach(
        task_id="cap07b-01",
        binding=_binding(),
        approach_node_id="park_entry",
        goal_evaluation=_goal_ok(),
        collision_count=1,
    )
    assert not collision.ok
    assert "collision_count=1" in collision.reasons


def test_kernel_status_is_checked() -> None:
    verdict = evaluate_target_approach(
        task_id="cap07b-01",
        binding=_binding(),
        approach_node_id="park_entry",
        goal_evaluation=_goal_ok(),
        kernel_execution_status="failed",
    )
    assert not verdict.ok
    assert "kernel_execution_status=failed" in verdict.reasons


def test_non_bound_binding_and_wrong_approach_are_refused() -> None:
    with pytest.raises(ValueError):
        evaluate_target_approach(
            task_id="cap07b-01",
            binding=_binding(status="invalidated"),
            approach_node_id="park_entry",
            goal_evaluation=_goal_ok(),
        )
    with pytest.raises(ValueError):
        evaluate_target_approach(
            task_id="cap07b-01",
            binding=_binding(),
            approach_node_id="bay11_turn",
            goal_evaluation=_goal_ok(node_id="bay11_turn", x=-7.61, y=-16.14),
        )
