"""Bounded local route and low-speed control tests (CAP-07B-03)."""

from __future__ import annotations

import math

import pytest

from vln.carla.alignment_control import (
    alignment_overall_improved,
    alignment_phase_command,
    alignment_round_improved,
)
from vln.carla.alignment_route import (
    AlignmentRouteStatus,
    plan_alignment_round,
    validate_alignment_poses,
)
from vln.carla.alignment_scene import bay03_alignment_target
from vln.parking.alignment import (
    AlignmentBudget,
    AlignmentPhase,
    AlignmentStability,
    AlignmentStage,
    measure_alignment,
    verify_alignment,
)


class _Binding:
    status = "bound"
    bay_id = "bay03"
    slot_node_id = "park_slot"


START = (-3.8943, -17.1788, math.radians(-86.3512))


def _target():
    return bay03_alignment_target(task_id="cap07b-03")


def _measure(target, x, y, yaw, *, stable=True, speed=0.0, stopped=True):
    return measure_alignment(
        target,
        x=x,
        y=y,
        yaw_rad=yaw,
        speed_mps=speed,
        stopped=stopped,
        stability=AlignmentStability(3, 0.0, 0.0, stable),
    )


def _simulate_phase(target, plan, pose):
    """Kinematic stand-in for the bounded CARLA phase; no CARLA import."""

    x, y, yaw = pose
    travelled = 0.0
    sim_time = 0.0
    speed = 0.0
    records = []
    for _ in range(4000):
        command = alignment_phase_command(
            target,
            phase=plan.phase,
            x=x,
            y=y,
            yaw_rad=yaw,
            speed_mps=speed,
            travelled_m=travelled,
            max_distance_m=plan.max_distance_m,
            sim_seconds=sim_time,
            max_sim_seconds=plan.max_sim_seconds,
        )
        if command.done:
            break
        if command.throttle > 0.0:
            speed = min(plan.speed_cap_mps, speed + 0.12 * 0.05)
        else:
            speed = max(0.0, speed - 0.5 * 0.05)
        if speed < 0.01:
            speed = plan.speed_cap_mps
        sign = -1.0 if command.reverse else 1.0
        yaw += (math.tan(command.steer) / 3.0) * sign * speed * 0.05
        x += math.cos(yaw) * sign * speed * 0.05
        y += math.sin(yaw) * sign * speed * 0.05
        travelled += speed * 0.05
        sim_time += 0.05
        records.append((x, y, yaw))
    return (x, y, yaw), travelled, records


def test_initial_pose_produces_a_bounded_reverse_plan() -> None:
    target = _target()
    measurement = _measure(target, *START)
    assert abs(measurement.heading_error_deg) > target.tolerances.heading_deg
    result = plan_alignment_round(
        target,
        measurement,
        budget=AlignmentBudget(),
        round_index=1,
    )
    assert result.status == AlignmentRouteStatus.SELECTED
    plan = result.plan
    assert plan.phase == AlignmentPhase.REVERSE_ALIGN
    assert plan.reverse
    assert 0.15 <= plan.length_m <= 1.30
    assert plan.end_pose[1] > START[1]  # reverse moves north
    assert abs(plan.checks["heading_after_deg"]) < abs(
        measurement.heading_error_deg
    )
    assert plan.checks["stays_north_of_staging_line"]
    assert plan.checks["boundary_clearance_min_m"] >= 0.10


def test_two_phase_kinematic_cycle_completes_alignment() -> None:
    target = _target()
    pose = START
    budget = AlignmentBudget()
    measurement = _measure(target, *pose)
    for round_index in (1, 2):
        result = plan_alignment_round(
            target, measurement, budget=budget, round_index=round_index
        )
        assert result.ok, result.reason
        plan = result.plan
        before = measurement
        pose, travelled, records = _simulate_phase(target, plan, pose)
        measurement = _measure(target, *pose)
        improved, reasons = alignment_round_improved(
            target, phase=plan.phase, before=before, after=measurement
        )
        assert improved, reasons
        assert not validate_alignment_poses(target, records)
        budget = budget.record_round(travelled)
    verification = verify_alignment(
        target, binding=_Binding(), measurement=measurement
    )
    assert verification.stage == AlignmentStage.COMPLETED
    assert abs(measurement.heading_error_deg) <= 2.0
    assert abs(measurement.lateral_error_m) <= 0.15
    assert abs(measurement.longitudinal_error_m) <= 0.08


def test_plan_never_crosses_the_staging_line_or_bay() -> None:
    target = _target()
    measurement = _measure(target, *START)
    result = plan_alignment_round(
        target, measurement, budget=AlignmentBudget(), round_index=1
    )
    assert result.ok
    assert not validate_alignment_poses(target, result.plan.poses)
    for x, y, _ in result.plan.poses:
        assert y >= target.reference_xy[1] - 0.10
        assert target.region_contains(x, y)


def test_outside_region_pose_is_refused() -> None:
    target = _target()
    measurement = _measure(target, 1.0, -17.0, -math.pi / 2)
    result = plan_alignment_round(
        target, measurement, budget=AlignmentBudget(), round_index=1
    )
    assert result.status in (
        AlignmentRouteStatus.REFUSED_REGION,
        AlignmentRouteStatus.REFUSED_CLEARANCE,
    )
    assert not result.ok


def test_lateral_only_error_has_no_safe_phase() -> None:
    target = _target()
    # x -3.70: lateral 0.30 m; heading and longitudinal are inside tolerance.
    measurement = _measure(target, -3.70, -17.19, -math.pi / 2)
    result = plan_alignment_round(
        target, measurement, budget=AlignmentBudget(), round_index=1
    )
    assert result.status == AlignmentRouteStatus.REFUSED_NO_PHASE
    assert not result.ok


def test_exhausted_budget_is_refused() -> None:
    target = _target()
    measurement = _measure(target, *START)
    budget = AlignmentBudget(max_rounds=1, rounds_used=1)
    result = plan_alignment_round(
        target, measurement, budget=budget, round_index=2
    )
    assert result.status == AlignmentRouteStatus.REFUSED_BUDGET


def test_reverse_command_rotates_the_right_way_and_caps_speed() -> None:
    target = _target()
    command = alignment_phase_command(
        target,
        phase=AlignmentPhase.REVERSE_ALIGN,
        x=START[0],
        y=START[1],
        yaw_rad=START[2],
        speed_mps=0.0,
        travelled_m=0.0,
        max_distance_m=1.3,
        sim_seconds=0.0,
        max_sim_seconds=25.0,
    )
    assert command.reverse
    assert command.throttle == 0.45
    assert command.steer > 0.0  # reverse with positive steer decreases yaw
    assert not command.done
    fast = alignment_phase_command(
        target,
        phase=AlignmentPhase.REVERSE_ALIGN,
        x=START[0],
        y=START[1],
        yaw_rad=START[2],
        speed_mps=0.15,
        travelled_m=0.0,
        max_distance_m=1.3,
        sim_seconds=0.0,
        max_sim_seconds=25.0,
    )
    assert fast.throttle == 0.0 and fast.brake == 0.25


def test_command_stops_at_limits_and_aligned_heading() -> None:
    target = _target()
    distance = alignment_phase_command(
        target,
        phase=AlignmentPhase.REVERSE_ALIGN,
        x=START[0],
        y=START[1],
        yaw_rad=START[2],
        speed_mps=0.15,
        travelled_m=1.3,
        max_distance_m=1.3,
        sim_seconds=0.0,
        max_sim_seconds=25.0,
    )
    assert distance.done and distance.done_reason == "distance_limit"
    tlimit = alignment_phase_command(
        target,
        phase=AlignmentPhase.REVERSE_ALIGN,
        x=START[0],
        y=START[1],
        yaw_rad=START[2],
        speed_mps=0.15,
        travelled_m=0.0,
        max_distance_m=1.3,
        sim_seconds=25.0,
        max_sim_seconds=25.0,
    )
    assert tlimit.done and tlimit.done_reason == "time_limit"
    aligned = alignment_phase_command(
        target,
        phase=AlignmentPhase.REVERSE_ALIGN,
        x=-4.0,
        y=-16.5,
        yaw_rad=-math.pi / 2,
        speed_mps=0.0,
        travelled_m=0.5,
        max_distance_m=1.3,
        sim_seconds=1.0,
        max_sim_seconds=25.0,
    )
    assert aligned.done and aligned.done_reason == "heading_aligned"


def test_round_improvement_rejects_heading_worsening() -> None:
    target = _target()
    before = _measure(target, *START)
    after = _measure(target, START[0], START[1] + 0.5, math.radians(-80.0))
    ok, reasons = alignment_round_improved(
        target, phase=AlignmentPhase.REVERSE_ALIGN, before=before, after=after
    )
    assert not ok
    assert "reverse_phase_did_not_reduce_heading" in reasons


def test_round_improvement_rejects_leaving_the_region() -> None:
    target = _target()
    before = _measure(target, *START)
    after = _measure(target, 1.0, -16.5, -math.pi / 2)
    ok, reasons = alignment_round_improved(
        target, phase=AlignmentPhase.REVERSE_ALIGN, before=before, after=after
    )
    assert not ok
    assert "post_phase_outside_region" in reasons


def test_cumulative_worsening_is_rejected() -> None:
    target = _target()
    initial = _measure(target, *START)
    final = _measure(target, -4.0, -17.19, math.radians(-85.0))
    ok, reasons = alignment_overall_improved(
        target, initial=initial, final=final
    )
    assert not ok
    assert "cumulative_heading_worsened" in reasons


def test_validate_real_pose_trajectory_flags_bay_entry() -> None:
    target = _target()
    bad = [(-4.0, -17.19, -math.pi / 2), (-8.0, -21.0, -math.pi / 2)]
    reasons = validate_alignment_poses(target, bad)
    assert "pose_1_outside_region" in reasons
    assert any("boundary_clearance" in reason for reason in reasons)
