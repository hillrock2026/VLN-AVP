"""Tests for the independent bay-03 parking verdict."""

from __future__ import annotations

import math

import pytest

from vln.carla import (
    BAY11_CENTER,
    BAY11_POLYGON,
    BAY11_SLOT_NODE_ID,
    evaluate_parking_verdict,
)


def _verdict(**overrides):
    values = dict(
        target_node_id="park_slot",
        target_bay_id="bay03",
        x=-9.5,
        y=-21.1,
        yaw_rad=math.pi,
        speed_mps=0.0,
        stop_stable=True,
        stable_position_drift_m=0.0,
        collision_count=0,
        safety_stop_reason="success",
        kernel_execution_status="completed",
    )
    values.update(overrides)
    return evaluate_parking_verdict(**values)


def test_exact_final_pose_passes_every_independent_check() -> None:
    verdict = _verdict()
    assert verdict.ok is True
    assert verdict.reasons == []
    assert verdict.measurements["boundary_clearance_m"] >= 0.2
    assert verdict.measurements["heading_error_deg"] == pytest.approx(0.0)
    assert verdict.measurements["corners_inside_polygon"] is True


def test_heading_wraps_around_pi() -> None:
    verdict = _verdict(yaw_rad=-math.pi + math.radians(2.0))
    assert verdict.ok is True
    assert abs(verdict.measurements["heading_error_deg"]) <= 2.0 + 1e-6


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"x": -9.0}, "position_inside_tolerance"),
        ({"yaw_rad": math.pi + math.radians(10.0)}, "heading_aligned"),
        ({"speed_mps": 0.10}, "stopped"),
        ({"stop_stable": False}, "stop_stable"),
        ({"stable_position_drift_m": 0.05}, "stop_stable"),
        ({"collision_count": 1}, "no_collision"),
        ({"safety_stop_reason": "obstacle"}, "no_unresolved_safety_stop"),
        ({"kernel_execution_status": "failed"}, "kernel_execution_completed"),
        ({"target_node_id": "goal"}, "target_identity"),
        ({"target_bay_id": "bay02"}, "target_identity"),
    ],
)
def test_each_independent_failure_is_reported(overrides, reason) -> None:
    verdict = _verdict(**overrides)
    assert verdict.ok is False
    assert reason in verdict.reasons


def test_footprint_crossing_the_painted_south_line_fails() -> None:
    # Car half-width 0.94 m; y=-21.9 puts the south side at -22.84, outside the
    # measured south line y=-22.39 even though the centre is near the bay.
    verdict = _verdict(y=-21.9)
    assert verdict.ok is False
    assert "footprint_inside_bay" in verdict.reasons
    assert verdict.measurements["corners_inside_polygon"] is False


def test_heading_within_five_degrees_keeps_every_corner_inside() -> None:
    verdict = _verdict(yaw_rad=math.pi - math.radians(4.0))
    assert verdict.ok is True
    assert verdict.measurements["boundary_clearance_m"] >= 0.05


def test_a_six_degree_heading_break_is_rejected() -> None:
    verdict = _verdict(yaw_rad=math.pi - math.radians(6.0))
    assert verdict.ok is False
    assert "heading_aligned" in verdict.reasons


def test_bay11_target_uses_its_own_slot_and_polygon() -> None:
    verdict = _verdict(
        target_node_id=BAY11_SLOT_NODE_ID,
        target_bay_id="bay11",
        slot_node_id=BAY11_SLOT_NODE_ID,
        bay_id="bay11",
        bay_polygon=BAY11_POLYGON,
        bay_center=BAY11_CENTER,
        x=-9.5,
        y=-16.14,
    )
    assert verdict.ok is True
    assert verdict.bay_id == "bay11"
    assert verdict.bay_center == BAY11_CENTER
    assert verdict.measurements["distance_to_bay_center_m"] <= 0.25

    wrong_bay = _verdict(
        target_node_id=BAY11_SLOT_NODE_ID,
        target_bay_id="bay11",
        slot_node_id=BAY11_SLOT_NODE_ID,
        bay_id="bay11",
        bay_polygon=BAY11_POLYGON,
        bay_center=BAY11_CENTER,
        x=-9.5,
        y=-21.14,
    )
    assert wrong_bay.ok is False
    assert "position_inside_tolerance" in wrong_bay.reasons

    wrong_identity = _verdict(
        target_node_id="park_slot",
        target_bay_id="bay11",
        slot_node_id=BAY11_SLOT_NODE_ID,
        bay_id="bay11",
        bay_polygon=BAY11_POLYGON,
        bay_center=BAY11_CENTER,
        x=-9.5,
        y=-16.14,
    )
    assert wrong_identity.ok is False
    assert "target_identity" in wrong_identity.reasons
