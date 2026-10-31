"""Bounded terminal Entry correction tests (CAP-07B-04)."""

from __future__ import annotations

import math

import pytest

from vln.carla.entry_scene import bay03_entry_route
from vln.carla.entry_terminal import (
    BoundaryFloorGuard,
    TerminalCorrectionConfig,
    TerminalPhase,
    boundary_floor_guard,
    terminal_footprint_in_buffer,
    terminal_phase_command,
    terminal_phase_improved,
    terminal_phase_plan,
    terminal_reference_in_box,
)
from vln.parking.entry import (
    EntryStability,
    measure_entry,
)

START = (-3.9959, -17.1843, math.radians(-89.5386))
BAY = (
    (-4.0, -19.89),
    (-14.4, -19.89),
    (-14.4, -22.39),
    (-4.0, -22.39),
)


def _route():
    route, _ = bay03_entry_route(
        task_id="cap07b-04", actual_pose=START, obstacle_points=()
    )
    return route


def _measure(route, x, y, yaw, *, speed=0.0, stopped=True, collision=0):
    return measure_entry(
        route,
        x=x,
        y=y,
        yaw_rad=yaw,
        speed_mps=speed,
        stopped=stopped,
        route_s=route.length_m,
        cross_track_m=0.0,
        stability=EntryStability(3, 0.0, 0.0, True),
        collision_count=collision,
    )


def test_reverse_plan_targets_heading_west_and_moves_behind() -> None:
    route = _route()
    measurement = _measure(
        route, -9.475, -21.5435, math.radians(-169.2638)
    )
    plan = terminal_phase_plan(
        route, measurement, TerminalPhase.REVERSE_ALIGN
    )
    assert plan.reverse
    assert plan.target_heading_rad == pytest.approx(math.pi)
    assert plan.max_distance_m == pytest.approx(2.4)
    assert plan.points[1][1] > plan.points[0][1]  # reverse moves north


def test_forward_plan_targets_slot() -> None:
    route = _route()
    measurement = _measure(
        route, -9.2, -20.6, math.radians(-178.0)
    )
    plan = terminal_phase_plan(
        route, measurement, TerminalPhase.FORWARD_RETURN
    )
    assert not plan.reverse
    assert plan.target_x == pytest.approx(route.target_pose[0])
    assert plan.target_y == pytest.approx(route.target_pose[1])
    assert plan.target_heading_rad == pytest.approx(math.pi)


def test_reverse_command_steers_to_correct_heading_and_caps_speed() -> None:
    route = _route()
    measurement = _measure(
        route, -9.475, -21.5435, math.radians(-169.2638)
    )
    plan = terminal_phase_plan(
        route, measurement, TerminalPhase.REVERSE_ALIGN
    )
    command = terminal_phase_command(
        plan,
        x=measurement.x,
        y=measurement.y,
        yaw_rad=measurement.yaw_rad,
        speed_mps=0.0,
        travelled_m=0.0,
        sim_seconds=0.0,
    )
    assert command.reverse
    assert command.command.throttle == pytest.approx(0.45)
    assert command.command.steer > 0.0
    assert not command.done
    fast = terminal_phase_command(
        plan,
        x=measurement.x,
        y=measurement.y,
        yaw_rad=measurement.yaw_rad,
        speed_mps=0.16,
        travelled_m=0.0,
        sim_seconds=0.0,
    )
    assert fast.command.throttle == 0.0
    assert fast.command.brake == pytest.approx(0.25)


def test_terminal_command_stops_at_heading_or_limits() -> None:
    route = _route()
    measurement = _measure(route, -9.5, -20.5, math.pi)
    plan = terminal_phase_plan(
        route, measurement, TerminalPhase.REVERSE_ALIGN
    )
    aligned = terminal_phase_command(
        plan,
        x=-9.5,
        y=-20.5,
        yaw_rad=math.pi,
        speed_mps=0.05,
        travelled_m=0.4,
        sim_seconds=2.0,
    )
    assert aligned.done and aligned.done_reason == "heading_aligned"
    distance = terminal_phase_command(
        plan,
        x=-9.5,
        y=-20.5,
        yaw_rad=math.radians(-170.0),
        speed_mps=0.05,
        travelled_m=plan.max_distance_m,
        sim_seconds=2.0,
    )
    assert distance.done and distance.done_reason == "distance_limit"


def test_terminal_box_and_buffer() -> None:
    route = _route()
    config = TerminalCorrectionConfig()
    assert terminal_reference_in_box(-9.5, -21.3, config)
    assert not terminal_reference_in_box(-4.0, -17.0, config)
    assert terminal_footprint_in_buffer(
        route.footprint.corners(-9.5, -21.3, math.pi), route, config
    )
    assert not terminal_footprint_in_buffer(
        route.footprint.corners(-3.0, -16.0, math.pi), route, config
    )


def test_terminal_improvement_reverse() -> None:
    route = _route()
    config = TerminalCorrectionConfig()
    before = _measure(
        route, -9.475, -21.5435, math.radians(-169.2638)
    )
    after = _measure(
        route, -9.4, -21.3, math.radians(-177.0)
    )
    ok, reasons = terminal_phase_improved(
        TerminalPhase.REVERSE_ALIGN,
        before=before,
        after=after,
        route=route,
        config=config,
    )
    assert ok, reasons


def test_terminal_improvement_rejects_heading_worsening() -> None:
    route = _route()
    config = TerminalCorrectionConfig()
    before = _measure(
        route, -9.475, -21.5435, math.radians(-169.2638)
    )
    after = _measure(
        route, -9.3, -21.2, math.radians(-155.0)
    )
    ok, reasons = terminal_phase_improved(
        TerminalPhase.REVERSE_ALIGN,
        before=before,
        after=after,
        route=route,
        config=config,
    )
    assert not ok
    assert "terminal_reverse_did_not_reduce_heading" in reasons


def test_terminal_improvement_rejects_outside_box() -> None:
    route = _route()
    config = TerminalCorrectionConfig()
    before = _measure(
        route, -9.475, -21.5435, math.radians(-169.2638)
    )
    after = _measure(
        route, -3.0, -16.0, math.radians(-170.0)
    )
    ok, reasons = terminal_phase_improved(
        TerminalPhase.REVERSE_ALIGN,
        before=before,
        after=after,
        route=route,
        config=config,
    )
    assert not ok
    assert "terminal_reference_outside_box" in reasons


# --- CAP-07B-06: per-tick boundary floor guard -----------------------------

POSE = {
    "x": -9.4816,
    "y": -21.1966,
    "yaw_rad": -3.104287,
    "frame": 12345,
    "half_length": 2.503,
    "half_width": 0.9405,
}


def _guard(floor, **overrides):
    polygon = overrides.pop("bay_polygon", BAY)
    values = {**POSE, **overrides}
    yaw = values.pop("yaw_rad")
    return boundary_floor_guard(
        floor_m=floor,
        yaw_rad=yaw,
        bay_polygon=polygon,
        **values,
    )


def test_boundary_floor_guard_passes_above_floor() -> None:
    guard = _guard(0.10)
    assert not guard.triggered
    assert guard.reason == "ok"
    assert guard.footprint_inside_bay is True
    assert guard.clearance_m == pytest.approx(0.1605, abs=0.001)
    assert guard.frame == 12345
    assert len(guard.footprint_corners) == 4
    assert guard.to_metadata()["triggered"] is False


def test_boundary_floor_guard_accepts_exact_floor() -> None:
    measured = _guard(0.0).clearance_m
    guard = _guard(measured)
    assert not guard.triggered
    assert guard.clearance_m == pytest.approx(measured)


def test_boundary_floor_guard_stops_below_floor() -> None:
    measured = _guard(0.0).clearance_m
    guard = _guard(measured + 1e-4)
    assert guard.triggered
    assert guard.reason == "boundary_below_floor"
    assert guard.clearance_m == pytest.approx(measured)
    assert guard.footprint_inside_bay is True


def test_boundary_floor_guard_stops_when_footprint_leaves_bay() -> None:
    guard = _guard(0.0, x=-3.0)
    assert guard.triggered
    assert guard.reason == "boundary_footprint_outside_bay"
    assert guard.footprint_inside_bay is False


def test_boundary_floor_guard_fails_closed_on_unreadable_state() -> None:
    for field in ("x", "y", "yaw_rad", "half_length", "half_width"):
        guard = _guard(0.10, **{field: float("nan")})
        assert guard.triggered, field
        assert guard.reason == "boundary_state_unreadable", field
    guard = _guard(0.10, frame=None)
    assert guard.triggered
    assert guard.reason == "boundary_state_unreadable"
    guard = _guard(0.10, half_width=0.0)
    assert guard.reason == "boundary_state_unreadable"


def test_boundary_floor_guard_fails_closed_on_invalid_floor() -> None:
    for floor in (-0.1, float("nan"), float("inf"), None, "0.1"):
        guard = boundary_floor_guard(
            floor_m=floor,
            bay_polygon=BAY,
            **POSE,
        )
        assert guard.triggered
        assert guard.reason in ("boundary_floor_invalid", "boundary_state_unreadable")


def test_boundary_floor_guard_fails_closed_on_invalid_geometry() -> None:
    guard = _guard(0.10, bay_polygon=((-4.0, -19.89), (-14.4, -19.89)))
    assert guard.triggered
    assert guard.reason == "boundary_geometry_invalid"
    assert guard.error

    # A rectangle with a non-finite vertex cannot be used for a clearance.
    guard = _guard(
        0.10,
        bay_polygon=(
            (-4.0, -19.89),
            (-14.4, -19.89),
            (-14.4, float("nan")),
            (-4.0, -22.39),
        ),
    )
    assert guard.triggered
    assert guard.reason == "boundary_geometry_invalid"


def test_boundary_floor_guard_applies_bbox_center_offset() -> None:
    centered = _guard(0.0)
    shifted = _guard(0.0, bbox_offset_y=0.05)
    assert not shifted.triggered
    assert shifted.clearance_m == pytest.approx(
        centered.clearance_m - 0.05, abs=1e-6
    )
    # The offset rotates with the actor: at yaw pi a +Y body offset is -Y world.
    assert shifted.transform is not None
    assert shifted.bounding_box["offset_y"] == pytest.approx(0.05)


def test_boundary_floor_guard_is_a_frozen_failure_record() -> None:
    guard = _guard(1.0)
    assert isinstance(guard, BoundaryFloorGuard)
    metadata = guard.to_metadata()
    assert metadata["floor_m"] == pytest.approx(1.0)
    assert metadata["frame"] == 12345
    assert metadata["bounding_box"]["half_length"] == pytest.approx(2.503)
