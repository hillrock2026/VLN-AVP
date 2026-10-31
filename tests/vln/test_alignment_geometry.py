"""Deterministic Alignment geometry and verifier tests (CAP-07B-03)."""

from __future__ import annotations

import math

import pytest

from vln.carla.alignment_scene import bay03_alignment_target
from vln.parking.alignment import (
    AlignmentGeometryError,
    AlignmentStage,
    AlignmentStability,
    AlignmentTarget,
    AlignmentTolerances,
    measure_alignment,
    measure_stability,
    verify_alignment,
)


class _Binding:
    status = "bound"
    bay_id = "bay03"
    slot_node_id = "park_slot"


def _target() -> AlignmentTarget:
    return bay03_alignment_target(task_id="cap07b-03")


def _measure(
    target: AlignmentTarget,
    *,
    x: float = -4.0,
    y: float = -17.19,
    yaw_deg: float = -90.0,
    speed: float = 0.0,
    stopped: bool = True,
    stable: bool = True,
):
    stability = AlignmentStability(3, 0.0, 0.0, stable)
    return measure_alignment(
        target,
        x=x,
        y=y,
        yaw_rad=math.radians(yaw_deg),
        speed_mps=speed,
        stopped=stopped,
        stability=stability,
    )


def _verify(target, measurement, **kwargs):
    return verify_alignment(
        target,
        binding=_Binding(),
        measurement=measurement,
        **kwargs,
    )


def test_fully_aligned_stable_pose_completes() -> None:
    target = _target()
    measurement = _measure(target)
    result = _verify(target, measurement)
    assert result.stage == AlignmentStage.COMPLETED
    assert result.completed
    assert result.alignment_valid
    assert result.reasons == ()
    assert abs(measurement.lateral_error_m) < 1e-9
    assert abs(measurement.heading_error_deg) < 1e-9
    assert abs(measurement.longitudinal_error_m) < 1e-9
    assert measurement.boundary_clearance_m == pytest.approx(0.197, abs=1e-3)
    assert not measurement.reference_inside_bay


def test_lateral_offset_is_reported_and_pending() -> None:
    target = _target()
    measurement = _measure(target, x=-3.70)
    assert measurement.lateral_error_m == pytest.approx(0.30, abs=1e-9)
    result = _verify(target, measurement)
    assert result.stage == AlignmentStage.PENDING
    assert result.checks["lateral_within_tolerance"] is False
    assert "lateral_within_tolerance" in result.reasons


def test_heading_error_sign_and_pending() -> None:
    target = _target()
    measurement = _measure(target, yaw_deg=-86.0)
    assert measurement.heading_error_deg == pytest.approx(4.0, abs=1e-9)
    result = _verify(target, measurement)
    assert result.stage == AlignmentStage.PENDING
    assert result.checks["heading_within_tolerance"] is False


def test_longitudinal_offset_north_is_pending() -> None:
    target = _target()
    measurement = _measure(target, y=-17.05)
    assert measurement.longitudinal_error_m == pytest.approx(0.14, abs=1e-9)
    result = _verify(target, measurement)
    assert result.stage == AlignmentStage.PENDING
    assert result.checks["longitudinal_within_tolerance"] is False


def test_boundary_clearance_failure_is_safe_stop() -> None:
    target = _target()
    measurement = _measure(target, y=-18.20)
    assert measurement.boundary_clearance_m < target.tolerances.boundary_clearance_m
    result = _verify(target, measurement)
    assert result.stage == AlignmentStage.SAFE_STOP
    assert "boundary_clearance" in result.reasons


def test_reference_inside_bay_is_safe_stop() -> None:
    target = _target()
    measurement = _measure(target, x=-8.0, y=-21.0)
    assert measurement.reference_inside_bay
    result = _verify(target, measurement)
    assert result.stage == AlignmentStage.SAFE_STOP
    assert "reference_not_inside_bay" in result.reasons


def test_unstable_stop_is_valid_not_completed() -> None:
    target = _target()
    stability = AlignmentStability(3, 0.0, 0.0, False)
    measurement = measure_alignment(
        target, x=-4.0, y=-17.19, yaw_rad=-math.pi / 2, speed_mps=0.0,
        stopped=True, stability=stability,
    )
    result = _verify(target, measurement)
    assert result.stage == AlignmentStage.VALID
    assert result.reasons == ("stop_stable_not_confirmed",)
    assert not result.completed


def test_not_stopped_is_safe_stop() -> None:
    target = _target()
    measurement = _measure(target, speed=0.4, stopped=False)
    result = _verify(target, measurement)
    assert result.stage == AlignmentStage.SAFE_STOP
    assert "stopped" in result.reasons


def test_collision_is_safe_stop() -> None:
    target = _target()
    measurement = _measure(target)
    result = _verify(target, measurement, collision_count=1)
    assert result.stage == AlignmentStage.SAFE_STOP
    assert "no_collision" in result.reasons


def test_missing_vehicle_state_is_rejected() -> None:
    result = verify_alignment(_target(), binding=_Binding(), measurement=None)
    assert result.stage == AlignmentStage.REJECTED
    assert result.reasons == ("vehicle_state_missing",)


def test_geometry_invalidation_during_execution_is_rejected() -> None:
    target = _target()
    result = verify_alignment(
        target,
        binding=_Binding(),
        measurement=_measure(target),
        geometry_error="bay_geometry_changed",
    )
    assert result.stage == AlignmentStage.REJECTED
    assert result.reasons == ("bay_geometry_changed",)


def test_missing_geometry_is_rejected() -> None:
    result = verify_alignment(
        None,
        binding=_Binding(),
        task_id="cap07b-03",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        geometry_error="target_not_visible",
    )
    assert result.stage == AlignmentStage.REJECTED
    assert result.reasons == ("target_not_visible",)
    assert result.measurement is None


def test_degenerate_bay_polygon_is_rejected_at_construction() -> None:
    base = _target()
    with pytest.raises(AlignmentGeometryError):
        AlignmentTarget(
            task_id=base.task_id,
            target_id=base.target_id,
            bay_id=base.bay_id,
            slot_node_id=base.slot_node_id,
            approach_node_id=base.approach_node_id,
            entry_node_id=base.entry_node_id,
            entry_xy=base.entry_xy,
            reference_xy=base.reference_xy,
            reference_heading_rad=base.reference_heading_rad,
            standoff_m=base.standoff_m,
            bay_polygon=((-4.0, -19.89), (-4.0, -19.89), (-4.0, -19.89)),
            bay_center=base.bay_center,
            footprint=base.footprint,
            region_x_min=base.region_x_min,
            region_x_max=base.region_x_max,
            region_y_min=base.region_y_min,
            region_y_max=base.region_y_max,
            tolerances=base.tolerances,
        )


def test_unknown_bay_has_no_scene_geometry() -> None:
    with pytest.raises(AlignmentGeometryError):
        bay03_alignment_target(task_id="cap07b-03", target_id="bay99")


def test_identity_mismatch_is_rejected() -> None:
    target = _target()
    result = verify_alignment(
        target,
        binding=_Binding(),
        task_id="another-task",
        measurement=_measure(target),
    )
    assert result.stage == AlignmentStage.REJECTED
    assert result.reasons == ("target_identity_mismatch",)
    assert not result.identity_verified


def test_binding_mismatch_is_rejected() -> None:
    class OtherBinding:
        status = "bound"
        bay_id = "bay11"
        slot_node_id = "bay11_slot"

    target = _target()
    result = verify_alignment(
        target, binding=OtherBinding(), measurement=_measure(target)
    )
    assert result.stage == AlignmentStage.REJECTED
    assert result.reasons == ("target_identity_mismatch",)


def test_heading_and_lateral_coordinate_signs() -> None:
    target = _target()
    east = _measure(target, x=-3.90)
    west = _measure(target, x=-4.10)
    assert east.lateral_error_m > 0.0
    assert west.lateral_error_m < 0.0
    # yaw -89 deg points slightly east of south -> positive heading error.
    assert _measure(target, yaw_deg=-89.0).heading_error_deg > 0.0
    assert _measure(target, yaw_deg=-91.0).heading_error_deg < 0.0


def test_stability_requires_three_samples_and_bounded_drift() -> None:
    tolerances = AlignmentTolerances()
    two = measure_stability(
        [{"x": -4.0, "y": -17.19, "speed": 0.0}] * 2, tolerances
    )
    assert not two.stable
    drifting = measure_stability(
        [
            {"x": -4.0, "y": -17.19, "speed": 0.0},
            {"x": -3.97, "y": -17.19, "speed": 0.0},
            {"x": -3.94, "y": -17.19, "speed": 0.0},
        ],
        tolerances,
    )
    assert drifting.position_drift_m == pytest.approx(0.06, abs=1e-9)
    assert not drifting.stable
    moving = measure_stability(
        [{"x": -4.0, "y": -17.19, "speed": 0.2}] * 3, tolerances
    )
    assert not moving.stable


def test_tolerance_window_is_the_predeclared_one() -> None:
    tol = AlignmentTolerances()
    assert tol.lateral_m == 0.15
    assert tol.heading_deg == 2.0
    assert tol.longitudinal_m == 0.08
    assert tol.boundary_clearance_m == 0.10
    assert tol.stable_samples == 3
