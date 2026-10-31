"""Offline tests for the low-speed parking path and goal helpers."""

from __future__ import annotations

import math

import pytest

from vln.carla import (
    Footprint,
    build_forward_right_arc,
    cumulative_lengths,
    footprint_polygon_clearance,
    parking_command,
    path_curvature_at_s,
    parking_goal_evaluation,
    turn_metrics,
)
from vln.carla.parking_control import parking_continuation_target_index


def test_forward_arc_starts_south_and_ends_at_the_slot() -> None:
    path = build_forward_right_arc(
        -4.0,
        -17.6,
        3.5,
        final_x=-9.5,
        step_deg=2.5,
    )
    assert path[0] == pytest.approx((-4.0, -17.6))
    assert path[-1] == pytest.approx((-9.5, -21.1))
    assert len(path) > 20
    cumulative = cumulative_lengths(path)
    assert cumulative[-1] == pytest.approx(7.497, abs=0.01)
    metrics = turn_metrics(path)
    assert metrics["kinematically_feasible"] is True
    assert metrics["min_radius_m"] == pytest.approx(3.5, abs=0.01)
    assert metrics["max_required_steer_deg"] == pytest.approx(40.6, abs=0.1)


def test_forward_arc_rejects_a_final_point_east_of_the_arc_end() -> None:
    with pytest.raises(ValueError):
        build_forward_right_arc(-4.0, -17.6, 3.5, final_x=-6.0)
    with pytest.raises(ValueError):
        build_forward_right_arc(-4.0, -17.6, 0.0, final_x=-9.5)


def _goal(**overrides):
    values = dict(
        x=-9.5,
        y=-21.1,
        yaw_rad=math.pi,
        speed_mps=0.0,
        stopped=True,
        slot_x=-9.5,
        slot_y=-21.1,
        slot_heading_rad=math.pi,
    )
    values.update(overrides)
    return parking_goal_evaluation(**values)


def test_parking_goal_accepts_exact_pose_and_stop() -> None:
    result = _goal()
    assert result["ok"] is True
    assert result["reasons"] == []
    assert result["distance_m"] == 0.0
    assert result["heading_error_deg"] == 0.0


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"x": -9.0}, "position_outside_tolerance"),
        ({"yaw_rad": math.pi + math.radians(10.0)}, "heading_outside_tolerance"),
        ({"speed_mps": 0.1}, "speed_not_stopped"),
        ({"stopped": False}, "not_confirmed_stopped"),
    ],
)
def test_parking_goal_rejects_each_failure(overrides, reason) -> None:
    result = _goal(**overrides)
    assert result["ok"] is False
    assert reason in result["reasons"]


def test_parking_goal_wraps_heading_around_pi() -> None:
    result = _goal(
        yaw_rad=math.radians(179.0),
        slot_heading_rad=math.radians(-179.0),
    )
    assert result["ok"] is True
    assert abs(result["heading_error_deg"]) <= 2.0 + 1e-6


def test_path_curvature_is_negative_on_the_right_turn() -> None:
    path = build_forward_right_arc(-4.0, -17.6, 3.5, final_x=-9.5)
    cumulative = cumulative_lengths(path)
    curvature = path_curvature_at_s(path, cumulative, 3.0)
    assert curvature < 0.0
    assert curvature == pytest.approx(-1.0 / 3.5, abs=0.02)
    assert abs(path_curvature_at_s(path, cumulative, cumulative[-1])) < 0.02


def test_parking_command_feedforward_increases_the_turn() -> None:
    # State recorded at the collision approach in the 07B run.
    path = build_forward_right_arc(-4.0, -17.6, 3.5, final_x=-9.5)
    cumulative = cumulative_lengths(path)
    base, _ = parking_command(
        x=-6.471,
        y=-20.336,
        yaw_rad=math.radians(-139.187),
        speed_mps=0.603,
        points=path,
        cumulative=cumulative,
        s=4.232,
        distance_to_slot_m=3.124,
        speed_cap_mps=0.45,
        feedforward_gain=0.0,
    )
    assisted, _ = parking_command(
        x=-6.471,
        y=-20.336,
        yaw_rad=math.radians(-139.187),
        speed_mps=0.603,
        points=path,
        cumulative=cumulative,
        s=4.232,
        distance_to_slot_m=3.124,
        speed_cap_mps=0.45,
        feedforward_gain=0.2,
    )
    assert base.steer == pytest.approx(-0.831, abs=0.01)
    assert assisted.steer < base.steer
    assert assisted.steer >= -0.9


def test_parking_command_applies_a_launch_throttle_floor() -> None:
    path = build_forward_right_arc(-4.0, -17.6, 3.5, final_x=-9.5)
    cumulative = cumulative_lengths(path)
    command, _ = parking_command(
        x=-4.0,
        y=-17.6,
        yaw_rad=math.radians(-90.0),
        speed_mps=0.0,
        points=path,
        cumulative=cumulative,
        s=0.0,
        distance_to_slot_m=cumulative[-1],
        speed_cap_mps=0.45,
    )
    assert command.throttle >= 0.40
    moving, _ = parking_command(
        x=-4.0,
        y=-17.6,
        yaw_rad=math.radians(-90.0),
        speed_mps=0.20,
        points=path,
        cumulative=cumulative,
        s=0.0,
        distance_to_slot_m=cumulative[-1],
        speed_cap_mps=0.45,
    )
    assert moving.throttle < 0.40


def test_parking_track_command_corrects_signed_lateral_error() -> None:
    from vln.carla import parking_track_command

    path = build_forward_right_arc(-4.0, -17.54, 3.56, final_x=-9.5)
    cumulative = cumulative_lengths(path)
    common = dict(
        x=-4.0,
        y=-17.54,
        yaw_rad=math.radians(-90.0),
        speed_mps=0.0,
        points=path,
        cumulative=cumulative,
        s=0.0,
        distance_to_slot_m=cumulative[-1],
        speed_cap_mps=0.35,
    )
    on_path, _ = parking_track_command(signed_lateral_m=0.0, **common)
    inside, _ = parking_track_command(signed_lateral_m=-0.5, **common)
    outside, _ = parking_track_command(signed_lateral_m=0.5, **common)
    # Right turn: the curvature feed-forward is at the -0.9 steering limit.
    assert on_path.steer == pytest.approx(-0.89, abs=0.02)
    # Negative lateral is right of the path (the observed inside offset), so
    # the correction must reduce the right steer.  A positive (left) offset
    # would ask for more right steer and saturates at the same -0.9 limit.
    assert inside.steer > on_path.steer + 0.1
    assert outside.steer == pytest.approx(-0.9, abs=0.01)
    assert -0.9 <= inside.steer <= 0.9
    assert -0.9 <= outside.steer <= 0.9
    assert on_path.throttle >= 0.40


def test_parking_command_uses_low_lookahead_and_speed_cap() -> None:
    path = build_forward_right_arc(-4.0, -17.6, 3.5, final_x=-9.5)
    cumulative = cumulative_lengths(path)
    command, info = parking_command(
        x=-4.0,
        y=-17.6,
        yaw_rad=math.radians(-90.0),
        speed_mps=0.0,
        points=path,
        cumulative=cumulative,
        s=0.0,
        distance_to_slot_m=cumulative[-1],
        speed_cap_mps=0.8,
    )
    assert info.v_target <= 0.8
    assert info.lookahead_m <= 2.5
    assert 0.0 <= command.throttle <= 0.55


def test_footprint_polygon_clearance_detects_an_enclosing_boundary() -> None:
    footprint = Footprint(2.5, 0.94)
    boundary = [
        (-12.3, -22.4),
        (-6.7, -22.4),
        (-6.7, -19.8),
        (-12.3, -19.8),
    ]
    result = footprint_polygon_clearance(-9.5, -21.1, math.pi, footprint, boundary)
    assert result["min_clearance_m"] == pytest.approx(0.3, abs=0.01)


def test_footprint_polygon_clearance_detects_intersection() -> None:
    footprint = Footprint(2.5, 0.94)
    boundary = [
        (-10.0, -22.0),
        (-9.0, -22.0),
        (-9.0, -20.0),
        (-10.0, -20.0),
    ]
    result = footprint_polygon_clearance(-9.5, -21.1, math.pi, footprint, boundary)
    assert result["min_clearance_m"] == 0.0


def test_parking_budget_covers_the_validated_left_loop() -> None:
    from vln.carla.parking_control import parking_execution_budget

    # The PERF-03 left-loop route is 27.891 m; the validated 08A round-4
    # execution.steps value was 1808 (the 2632-entry records array is not a
    # step count).  A fixed 1400-step budget cannot cover it at 0.35 m/s.
    budget = parking_execution_budget(27.891, 0.35, 0.05, 1400, 90.0)
    assert budget["ideal_steps_at_speed_cap"] == 1594
    assert budget["steps"] >= 1808
    assert budget["steps"] <= budget["hard_cap_steps"] == 4000
    assert budget["sim_seconds"] >= 90.4
    assert budget["sim_seconds"] <= budget["hard_cap_sim_seconds"] == 240.0


def test_parking_budget_keeps_explicit_budget_for_a_short_route() -> None:
    from vln.carla.parking_control import parking_execution_budget

    budget = parking_execution_budget(13.124, 0.35, 0.05, 1400, 90.0)
    assert budget["steps"] == 1400
    assert budget["sim_seconds"] == 90.0


def test_parking_budget_is_hard_capped() -> None:
    from vln.carla.parking_control import parking_execution_budget

    budget = parking_execution_budget(1000.0, 0.35, 0.05, 10000, 10000.0)
    assert budget["steps"] == 4000
    assert budget["sim_seconds"] == 240.0


def test_parking_entry_target_continues_to_the_parking_goal() -> None:
    assert parking_continuation_target_index(
        ["w7", "bay11_turn", "bay11_slot"],
        1,
        entry_node_ids={"bay11_turn"},
        goal_node_ids={"bay11_slot"},
    ) == 2


def test_park_entry_target_continues_to_the_parking_goal() -> None:
    assert parking_continuation_target_index(
        ["w8", "park_entry", "park_slot"],
        1,
        entry_node_ids={"park_entry"},
        goal_node_ids={"park_slot"},
    ) == 2


def test_a_non_parking_target_keeps_the_requested_segment_boundary() -> None:
    assert parking_continuation_target_index(
        ["w6", "w7", "bay11_turn", "bay11_slot"],
        1,
        entry_node_ids={"bay11_turn"},
        goal_node_ids={"bay11_slot"},
    ) == 1


def test_parking_continuation_is_clamped_to_the_route_end() -> None:
    assert parking_continuation_target_index(
        ["w7", "bay11_turn", "bay11_slot"],
        99,
        entry_node_ids={"bay11_turn"},
        goal_node_ids={"bay11_slot"},
    ) == 2


@pytest.mark.parametrize("nodes", [0, -1, 1.5, True])
def test_parking_continuation_rejects_an_invalid_request(nodes) -> None:
    with pytest.raises(ValueError):
        parking_continuation_target_index(
            ["w7", "bay11_turn", "bay11_slot"],
            nodes,
            entry_node_ids={"bay11_turn"},
            goal_node_ids={"bay11_slot"},
        )


def test_parking_precheck_origin_never_starts_inside_the_ego() -> None:
    from vln.carla.parking_control import parking_precheck_origin_start

    # Segment starts at the route origin: the historical 3.0 m origin is
    # already outside the 5.006 m body and must stay unchanged.
    assert parking_precheck_origin_start(
        0.0, half_length_m=2.503, front_margin_m=0.3
    ) == 3.0
    # A spawn 0.987 m along its own route put the fixed 3.0 m origin inside
    # the body; the origin must follow the projection instead.
    origin = parking_precheck_origin_start(
        0.987, half_length_m=2.503, front_margin_m=0.3
    )
    assert origin == pytest.approx(3.79, abs=1e-9)
    assert origin - 0.987 >= 2.503 + 0.3 - 1e-9


def test_parking_precheck_origin_rejects_invalid_inputs() -> None:
    from vln.carla.parking_control import parking_precheck_origin_start

    with pytest.raises(ValueError, match="start_s"):
        parking_precheck_origin_start(-0.1, half_length_m=2.5, front_margin_m=0.3)
    with pytest.raises(ValueError, match="half_length_m"):
        parking_precheck_origin_start(0.0, half_length_m=0.0, front_margin_m=0.3)
    with pytest.raises(ValueError, match="front_margin_m"):
        parking_precheck_origin_start(0.0, half_length_m=2.5, front_margin_m=-0.1)
