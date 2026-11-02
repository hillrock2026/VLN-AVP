"""Entry route, budget and low-speed segment tests (CAP-07B-04)."""

from __future__ import annotations

import math

import pytest

from vln.carla.entry_control import entry_segment_command
from vln.carla.entry_route import build_segments, route_geometry_audit
from vln.carla.entry_scene import bay03_entry_route
from vln.parking.entry import (
    EntryBudget,
    EntryGeometryError,
    EntryRoute,
    EntryStage,
    EntryStability,
    EntryTolerances,
    entry_round_improved,
    measure_entry,
    verify_entry,
)

START = (-3.9959, -17.1843, math.radians(-89.5386))


def _route(**kwargs):
    route, audit = bay03_entry_route(
        task_id="cap07b-04",
        actual_pose=START,
        obstacle_points=(),
        **kwargs,
    )
    return route, audit


def _pose_at(route: EntryRoute, s: float) -> tuple[float, float, float]:
    x, y = route.point_at_s(s)
    return (x, y, route.tangent_at_s(s))


def _measure(route, x, y, yaw, *, s, speed=0.0, stopped=True, stable=True,
             cross=0.0, collision=0, obstacle_points=None):
    stability = EntryStability(3, 0.0, 0.0, stable)
    if obstacle_points is not None:
        route = EntryRoute(
            **{
                **route.__dict__,
                "obstacle_points": tuple(obstacle_points),
            }
        )
    return measure_entry(
        route,
        x=x,
        y=y,
        yaw_rad=yaw,
        speed_mps=speed,
        stopped=stopped,
        route_s=s,
        cross_track_m=cross,
        stability=stability,
        collision_count=collision,
    )


def test_route_is_measured_validated_and_segmented() -> None:
    route, audit = _route()
    assert route.task_id == "cap07b-04"
    assert route.bay_id == "bay03"
    assert route.slot_node_id == "park_slot"
    assert route.length_m == pytest.approx(8.087, abs=0.01)
    assert len(route.segments) == 2
    assert route.target_pose == (-9.5, -21.3)
    assert route.target_heading_rad == pytest.approx(math.pi)
    assert route.route_id.startswith("bay03-entry-")
    assert audit["ok"], audit["reasons"]
    assert audit["min_obstacle_clearance_m"] is None
    assert audit["terminal_footprint_inside_bay"]
    assert audit["terminal_boundary_clearance_m"] >= 0.05
    assert audit["corridor_violations"] == 0
    assert audit["turn"]["kinematically_feasible"]
    assert audit["turn"]["min_radius_m"] == pytest.approx(3.56, abs=0.01)


def test_segments_are_contiguous_and_cover_the_route() -> None:
    route, _ = _route()
    assert route.segments[0].start_s == 0.0
    assert route.segments[-1].end_s == pytest.approx(route.length_m)
    for left, right in zip(route.segments, route.segments[1:]):
        assert left.end_s == pytest.approx(right.start_s)
    assert route.segments[0].target_heading_rad < 0.0  # still on the arc
    assert abs(route.segments[-1].target_heading_rad) == pytest.approx(math.pi)


def test_route_hash_is_bound_to_geometry() -> None:
    route, _ = _route()
    tampered = route.__dict__.copy()
    tampered["route_hash"] = "0" * 64
    with pytest.raises(EntryGeometryError):
        EntryRoute(**tampered)


def test_route_with_obstacles_reports_clearance() -> None:
    import json
    from pathlib import Path

    probe = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "tests/fixtures/carla_07a_geometry_probe.json"
        ).read_text()
    )
    route, audit = bay03_entry_route(
        task_id="cap07b-04",
        actual_pose=START,
        obstacle_points=tuple(
            (float(p[0]), float(p[1])) for p in probe["obstacle_points"]
        ),
    )
    assert audit["ok"], audit["reasons"]
    assert audit["min_obstacle_clearance_m"] >= 0.20
    assert route.obstacle_points


def test_terminal_footprint_is_fully_inside_bay() -> None:
    route, audit = _route()
    measurement = _measure(
        route, x=-9.5, y=-21.3, yaw=math.pi, s=route.length_m
    )
    assert measurement.footprint_inside_bay
    assert measurement.boundary_clearance_m >= 0.05
    assert measurement.distance_to_target_m == pytest.approx(0.0)
    assert measurement.heading_error_deg == pytest.approx(0.0)


def test_historical_parking_terminal_pose_is_a_valid_entry_terminal() -> None:
    route, _ = _route()
    # DEMO-05B real parked pose, not the graph slot exactly.
    measurement = _measure(
        route,
        x=-9.488,
        y=-21.218,
        yaw=math.radians(-176.458),
        s=route.length_m - 0.05,
    )
    assert measurement.distance_to_target_m <= 0.25
    assert abs(measurement.heading_error_deg) <= 5.0
    assert measurement.footprint_inside_bay
    assert measurement.boundary_clearance_m >= 0.05


def test_start_is_entry_pending_and_safe() -> None:
    route, _ = _route()
    measurement = _measure(route, *START, s=0.0)
    assert measurement.route_s == 0.0
    assert not measurement.footprint_inside_bay
    assert measurement.footprint_corners_inside_corridor


def test_mid_route_pose_is_pending() -> None:
    route, _ = _route()
    pose = _pose_at(route, 4.0)
    measurement = _measure(route, *pose, s=4.0)
    assert measurement.route_s == 4.0
    assert not measurement.footprint_inside_bay or measurement.distance_to_target_m > 0.25


def test_segment_command_uses_the_shared_parking_law_and_slows_at_the_end() -> None:
    route, _ = _route()
    segment = route.segments[0]
    pose = _pose_at(route, 0.2)
    command = entry_segment_command(
        route,
        segment,
        x=pose[0],
        y=pose[1],
        yaw_rad=pose[2],
        speed_mps=0.0,
        s=0.2,
        cross_track_m=0.0,
    )
    assert command.command.throttle > 0.0
    assert abs(command.command.steer) <= 0.9
    assert not command.final_leg
    near_end = entry_segment_command(
        route,
        segment,
        x=pose[0],
        y=pose[1],
        yaw_rad=pose[2],
        speed_mps=0.20,
        s=segment.end_s - 0.10,
        cross_track_m=0.0,
    )
    assert near_end.speed_cap_mps <= 0.20


def test_final_segment_command_marks_final_leg() -> None:
    route, _ = _route()
    segment = route.segments[-1]
    pose = _pose_at(route, route.length_m - 0.30)
    command = entry_segment_command(
        route,
        segment,
        x=pose[0],
        y=pose[1],
        yaw_rad=pose[2],
        speed_mps=0.10,
        s=route.length_m - 0.30,
        cross_track_m=0.0,
    )
    assert command.final_leg
    assert command.distance_to_slot_m <= 0.35
    assert command.speed_cap_mps <= 0.35


def test_budget_records_segments_and_exhausts() -> None:
    budget = EntryBudget(max_segments=2, max_total_distance_m=3.0)
    assert budget.can_start_segment
    after_one = budget.record_segment(2.0, 10.0)
    assert after_one.segments_used == 1
    after_two = after_one.record_segment(1.0, 5.0)
    assert not after_two.can_start_segment
    with pytest.raises(ValueError):
        after_two.record_segment(0.1, 0.1)


def test_round_improvement_requires_progress_and_stop() -> None:
    route, _ = _route()
    before = _measure(route, *_pose_at(route, 1.0), s=1.0)
    after = _measure(
        route, *_pose_at(route, 2.0), s=2.0, speed=0.2, stopped=False
    )
    ok, reasons = entry_round_improved(
        route, before=before, after=after, segment=route.segments[0]
    )
    assert not ok  # after is a moving measurement, not stopped
    assert "segment_not_stopped" in reasons
    stopped = _measure(route, *_pose_at(route, 2.0), s=2.0, stopped=True)
    ok, reasons = entry_round_improved(
        route, before=before, after=stopped, segment=route.segments[0]
    )
    assert ok, reasons


def test_round_improvement_rejects_no_progress_and_deviation() -> None:
    route, _ = _route()
    before = _measure(route, *_pose_at(route, 1.0), s=1.0)
    same = _measure(route, *_pose_at(route, 1.0), s=1.0)
    ok, reasons = entry_round_improved(
        route, before=before, after=same, segment=route.segments[0]
    )
    assert not ok
    assert "segment_no_progress" in reasons
    deviated = _measure(route, *_pose_at(route, 2.0), s=2.0, cross=0.80)
    ok, reasons = entry_round_improved(
        route, before=before, after=deviated, segment=route.segments[0]
    )
    assert not ok
    assert "segment_route_deviation" in reasons
