"""Offline tests for the bounded parking-path geometry checks."""

from __future__ import annotations

import math

import pytest

from vln.carla import (
    Footprint,
    evaluate_path,
    footprint_clearance,
    footprint_polygon_clearance,
    path_clearance,
    point_to_segment_distance,
    turn_metrics,
)


def test_footprint_metadata_uses_measured_extents() -> None:
    footprint = Footprint(2.503, 0.94, front_margin=0.30)
    assert footprint.length == pytest.approx(5.006)
    assert footprint.width == pytest.approx(1.88)
    assert footprint.to_metadata() == {
        "half_length_m": 2.503,
        "half_width_m": 0.94,
        "length_m": 5.006,
        "width_m": 1.88,
        "front_margin_m": 0.3,
    }


def test_current_goal_turn_exceeds_the_steering_limit() -> None:
    # The hand-defined route turns from southbound to westbound at goal.
    route = [
        (-3.9, -14.0),
        (-4.0, -18.0),
        (-4.0, -20.0),
        (-5.0, -20.5),
    ]
    metrics = turn_metrics(route)
    assert metrics["kinematically_feasible"] is False
    assert metrics["min_radius_m"] == pytest.approx(1.505, abs=0.01)
    assert metrics["max_required_steer_deg"] == pytest.approx(63.36, abs=0.1)
    assert metrics["limit_radius_m"] == pytest.approx(3.0)


def test_wide_arc_is_kinematically_feasible() -> None:
    radius = 3.5
    centre_x, centre_y = -7.5, -17.6
    arc = []
    for degrees in range(0, -91, -5):
        angle = math.radians(degrees)
        arc.append(
            (centre_x + radius * math.cos(angle), centre_y + radius * math.sin(angle))
        )
    arc.append((-9.5, -21.1))
    metrics = turn_metrics([(-3.9, -14.0)] + arc)
    assert metrics["kinematically_feasible"] is True
    assert metrics["min_radius_m"] == pytest.approx(3.5, abs=1e-6)
    assert metrics["max_required_steer_deg"] == pytest.approx(40.6, abs=0.1)


def test_evaluate_path_rejects_a_tight_turn_even_with_clear_space() -> None:
    route = [(-3.9, -14.0), (-4.0, -18.0), (-4.0, -20.0), (-5.0, -20.5)]
    result = evaluate_path(route, Footprint(2.503, 0.94), [(-20.0, -20.0)])
    assert result["feasible"] is False
    assert any("required_steer_exceeds_limit" in reason for reason in result["reasons"])


def test_path_clearance_rejects_an_obstacle_inside_the_footprint() -> None:
    result = path_clearance(
        [(0.0, 0.0), (10.0, 0.0)],
        Footprint(2.5, 0.94),
        [(5.0, 0.0)],
    )
    assert result["min_clearance_m"] == pytest.approx(0.0, abs=0.01)
    assert result["worst_pose"] is not None


def test_evaluate_path_accepts_a_clear_straight_path() -> None:
    result = evaluate_path(
        [(0.0, 0.0), (10.0, 0.0)],
        Footprint(2.5, 0.94),
        [(0.0, 5.0)],
        required_clearance_m=0.2,
    )
    assert result["feasible"] is True
    assert result["reasons"] == []
    assert result["clearance"]["min_clearance_m"] > 0.2


def test_clearance_is_not_measured_without_obstacle_points() -> None:
    result = evaluate_path([(0.0, 0.0), (10.0, 0.0)], Footprint(2.5, 0.94), [])
    assert result["feasible"] is False
    assert any("clearance_not_measured" in reason for reason in result["reasons"])


def test_point_to_segment_distance_handles_endpoints_and_interior() -> None:
    assert point_to_segment_distance(0.0, 1.0, 0.0, 0.0, 2.0, 0.0) == pytest.approx(1.0)
    assert point_to_segment_distance(-1.0, 0.0, 0.0, 0.0, 2.0, 0.0) == pytest.approx(1.0)
    assert point_to_segment_distance(1.0, 1.0, 0.0, 0.0, 2.0, 0.0) == pytest.approx(1.0)


def test_collinear_path_has_no_finite_turn_radius() -> None:
    metrics = turn_metrics([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)])
    assert metrics["min_radius_m"] is None
    assert metrics["kinematically_feasible"] is True


def test_run5_first_ground_probe_can_be_inside_the_ego_footprint() -> None:
    # run5 last saved state and the s+3 ground-probe point on the parking edge.
    footprint = Footprint(2.503, 0.94)
    x, y, yaw = -4.266, -18.527, math.radians(-99.623)
    first = (-5.393, -20.631)
    second = (-6.355, -20.922)
    local_first = footprint.local_point(x, y, yaw, *first)
    assert abs(local_first[0]) <= footprint.half_length
    assert abs(local_first[1]) <= footprint.half_width
    assert footprint.contains(x, y, yaw, *first) is True
    assert footprint.contains(x, y, yaw, *second) is False



def test_collision_state_is_below_the_static_clearance_guard() -> None:
    result = footprint_clearance(
        -6.471,
        -20.336,
        math.radians(-139.187),
        Footprint(2.503, 0.94),
        [(-7.0, -19.41)],
    )
    assert result["min_clearance_m"] is not None
    assert result["min_clearance_m"] < 0.2


def test_straight_reverse_candidate_has_side_and_back_clearance() -> None:
    footprint = Footprint(2.503, 0.94)
    north, south, west = -19.89, -22.39, -14.4
    guard = []
    x = -4.0
    while x >= west - 1e-9:
        guard.extend([(x, north), (x, south)])
        x -= 0.25
    y = north - 0.25
    while y >= south + 1e-9:
        guard.append((west, y))
        y -= 0.25
    path = [(-4.0, -21.14), (-9.5, -21.14)]
    result = evaluate_path(path, footprint, guard, required_clearance_m=0.2)
    assert result["feasible"] is True
    assert result["turn"]["max_required_steer_deg"] == 0.0
    assert result["clearance"]["min_clearance_m"] == pytest.approx(0.31, abs=0.01)
    final = footprint_polygon_clearance(
        -9.5,
        -21.14,
        0.0,
        footprint,
        [(-4.0, north), (west, north), (west, south), (-4.0, south)],
    )
    assert final["min_clearance_m"] == pytest.approx(0.31, abs=0.01)
