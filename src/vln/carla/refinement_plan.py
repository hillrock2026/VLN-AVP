"""Feasibility simulation for the bounded in-bay refinement path.

The planner uses the same validated terminal controller law as the Entry
terminal phases, but it simulates a two-phase reverse/forward correction to a
bay-centred target with the measured low-speed yaw response factor. Every
simulated pose is checked with the rotated footprint, the bay polygon and the
measured obstacle points. If any pose loses the current boundary clearance or
leaves the bay, the plan is refused; the runner then reports
``NO_SAFE_REFINEMENT`` and leaves the vehicle untouched.

This is a pre-execution feasibility check, not a claim that the real controller
will follow the simulated path. The real run still checks every CARLA tick and
stops on the first safety violation.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

from vln.carla.entry_terminal import (
    TerminalCorrectionConfig,
    TerminalPhase,
    TerminalPhasePlan,
    terminal_phase_command,
    terminal_reference_in_box,
)
from vln.carla.parking_geometry import (
    Footprint,
    footprint_clearance,
    footprint_polygon_clearance,
)
from vln.parking.refinement import (
    CandidatePose,
    RefinementMeasurement,
    RefinementStability,
    RefinementTolerances,
    measure_refinement,
)

__all__ = [
    "RefinementPathPlan",
    "plan_refinement_path",
    "build_refinement_phase_plan",
    "STEP_S",
]


STEP_S = 0.05


@dataclass(frozen=True)
class RefinementPathPlan:
    ok: bool
    reasons: tuple[str, ...]
    target: CandidatePose
    phases: tuple[TerminalPhasePlan, ...]
    config: TerminalCorrectionConfig
    simulated_poses: tuple[tuple[float, float, float], ...]
    min_boundary_clearance_m: float | None
    min_obstacle_clearance_m: float | None
    final_pose: tuple[float, float, float]
    predicted_final: RefinementMeasurement | None
    plan_hash: str
    yaw_response_factor: float

    def to_metadata(self) -> dict:
        return {
            "schema": "vln.parking.refinement_path.v1",
            "ok": self.ok,
            "reasons": list(self.reasons),
            "target": self.target.to_metadata(),
            "phases": [phase.to_metadata() for phase in self.phases],
            "terminal_config": self.config.to_metadata(),
            "plan_hash": self.plan_hash,
            "yaw_response_factor": self.yaw_response_factor,
            "simulated_pose_count": len(self.simulated_poses),
            "simulated_poses": [
                [round(x, 4), round(y, 4), round(math.degrees(yaw), 4)]
                for x, y, yaw in self.simulated_poses
            ],
            "min_boundary_clearance_m": None
            if self.min_boundary_clearance_m is None
            else round(self.min_boundary_clearance_m, 4),
            "min_obstacle_clearance_m": None
            if self.min_obstacle_clearance_m is None
            else round(self.min_obstacle_clearance_m, 4),
            "final_pose": {
                "x": round(self.final_pose[0], 4),
                "y": round(self.final_pose[1], 4),
                "yaw_deg": round(math.degrees(self.final_pose[2]), 4),
            },
            "predicted_final": (
                None
                if self.predicted_final is None
                else self.predicted_final.to_metadata()
            ),
        }


def _sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _config(tolerances: RefinementTolerances) -> TerminalCorrectionConfig:
    return TerminalCorrectionConfig(
        reverse_max_distance_m=tolerances.reverse_max_distance_m,
        reverse_speed_cap_mps=tolerances.reverse_speed_cap_mps,
        reverse_max_sim_seconds=tolerances.reverse_max_sim_seconds,
        reverse_stop_heading_deg=0.5,
        forward_max_distance_m=tolerances.forward_max_distance_m,
        forward_speed_cap_mps=tolerances.forward_speed_cap_mps,
        forward_max_sim_seconds=tolerances.forward_max_sim_seconds,
        forward_stop_heading_deg=1.0,
        forward_stop_distance_m=0.05,
        terminal_box_x_min=-10.8,
        terminal_box_x_max=-6.8,
        terminal_box_y_min=-22.3,
        terminal_box_y_max=-19.6,
        terminal_buffer_margin_m=1.0,
        obstacle_clearance_m=tolerances.target_obstacle_clearance_m,
    )


def _phase_plans(
    current: RefinementMeasurement,
    target: CandidatePose,
    tolerances: RefinementTolerances,
) -> tuple[TerminalPhasePlan, ...]:
    x, y, yaw = current.x, current.y, current.yaw_rad
    reverse = TerminalPhasePlan(
        phase=TerminalPhase.REVERSE_ALIGN,
        target_x=x - 0.6 * math.cos(yaw),
        target_y=y - 0.6 * math.sin(yaw),
        target_heading_rad=target.heading_rad,
        max_distance_m=tolerances.reverse_max_distance_m,
        speed_cap_mps=tolerances.reverse_speed_cap_mps,
        max_sim_seconds=tolerances.reverse_max_sim_seconds,
        reverse=True,
        start_pose=(x, y, yaw),
        points=(
            (x, y),
            (
                x - tolerances.reverse_max_distance_m * math.cos(yaw),
                y - tolerances.reverse_max_distance_m * math.sin(yaw),
            ),
        ),
    )
    forward_distance = max(
        math.hypot(target.x - x, target.y - y), 0.5
    )
    forward = TerminalPhasePlan(
        phase=TerminalPhase.FORWARD_RETURN,
        target_x=target.x,
        target_y=target.y,
        target_heading_rad=target.heading_rad,
        max_distance_m=tolerances.forward_max_distance_m,
        speed_cap_mps=tolerances.forward_speed_cap_mps,
        max_sim_seconds=tolerances.forward_max_sim_seconds,
        reverse=False,
        start_pose=(x, y, yaw),
        points=(
            (x, y),
            (
                x + forward_distance * math.cos(yaw),
                y + forward_distance * math.sin(yaw),
            ),
        ),
    )
    return (reverse, forward)


def _point_in_polygon(x: float, y: float, polygon) -> bool:
    inside = False
    count = len(polygon)
    for index in range(count):
        x0, y0 = polygon[index]
        x1, y1 = polygon[(index + 1) % count]
        if (y0 > y) != (y1 > y):
            x_cross = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < x_cross:
                inside = not inside
    return inside


def build_refinement_phase_plan(
    current: RefinementMeasurement,
    target: CandidatePose,
    phase: str,
    *,
    tolerances: RefinementTolerances | None = None,
) -> TerminalPhasePlan:
    """Build the concrete reverse or forward phase from the actual state."""

    if phase not in TerminalPhase.ALL:
        raise ValueError(f"unknown terminal phase {phase!r}")
    tolerances = tolerances or RefinementTolerances()
    x, y, yaw = current.x, current.y, current.yaw_rad
    if phase == TerminalPhase.REVERSE_ALIGN:
        return TerminalPhasePlan(
            phase=phase,
            target_x=x - 0.6 * math.cos(yaw),
            target_y=y - 0.6 * math.sin(yaw),
            target_heading_rad=target.heading_rad,
            max_distance_m=tolerances.reverse_max_distance_m,
            speed_cap_mps=tolerances.reverse_speed_cap_mps,
            max_sim_seconds=tolerances.reverse_max_sim_seconds,
            reverse=True,
            start_pose=(x, y, yaw),
            points=(
                (x, y),
                (
                    x - tolerances.reverse_max_distance_m * math.cos(yaw),
                    y - tolerances.reverse_max_distance_m * math.sin(yaw),
                ),
            ),
        )
    distance = max(math.hypot(target.x - x, target.y - y), 0.30)
    return TerminalPhasePlan(
        phase=phase,
        target_x=target.x,
        target_y=target.y,
        target_heading_rad=target.heading_rad,
        max_distance_m=tolerances.forward_max_distance_m,
        speed_cap_mps=tolerances.forward_speed_cap_mps,
        max_sim_seconds=tolerances.forward_max_sim_seconds,
        reverse=False,
        start_pose=(x, y, yaw),
        points=(
            (x, y),
            (x + distance * math.cos(yaw), y + distance * math.sin(yaw)),
        ),
    )


def plan_refinement_path(
    current: RefinementMeasurement,
    target: CandidatePose,
    *,
    bay_polygon,
    bay_center: tuple[float, float],
    footprint: Footprint,
    obstacle_points,
    tolerances: RefinementTolerances | None = None,
) -> RefinementPathPlan:
    """Simulate and validate the bounded reverse/forward refinement path."""

    if not isinstance(current, RefinementMeasurement):
        raise TypeError("current must be a RefinementMeasurement")
    if not isinstance(target, CandidatePose):
        raise TypeError("target must be a CandidatePose")
    tolerances = tolerances or RefinementTolerances()
    config = _config(tolerances)
    phases = _phase_plans(current, target, tolerances)
    # The current boundary clearance is the no-regression floor.
    boundary_floor = (
        current.boundary_clearance_m
        if current.boundary_clearance_m is not None
        else 0.05
    )
    x, y, yaw = current.x, current.y, current.yaw_rad
    speed = 0.0
    simulated: list[tuple[float, float, float]] = [(x, y, yaw)]
    min_boundary = current.boundary_clearance_m
    min_obstacle = current.obstacle_clearance_m
    reasons: list[str] = []

    def _check_pose(px, py, pyaw, phase) -> bool:
        nonlocal min_boundary, min_obstacle
        if not terminal_reference_in_box(px, py, config):
            reasons.append(f"{phase}_reference_outside_terminal_box")
            return False
        corners = footprint.corners(px, py, pyaw)
        inside = all(_point_in_polygon(cx, cy, bay_polygon) for cx, cy in corners)
        if not inside:
            reasons.append(f"{phase}_footprint_outside_bay")
            return False
        boundary = footprint_polygon_clearance(
            px, py, pyaw, footprint, bay_polygon
        )["min_clearance_m"]
        if boundary is None or boundary < max(boundary_floor, 0.05) - 1e-9:
            reasons.append(f"{phase}_boundary_clearance={boundary}")
            return False
        if obstacle_points:
            obstacle = footprint_clearance(
                px, py, pyaw, footprint, obstacle_points
            )["min_clearance_m"]
            if obstacle is not None and obstacle < tolerances.target_obstacle_clearance_m:
                reasons.append(f"{phase}_obstacle_clearance={obstacle}")
                return False
            if obstacle is not None and (
                min_obstacle is None or obstacle < min_obstacle
            ):
                min_obstacle = obstacle
        if min_boundary is None or boundary < min_boundary:
            min_boundary = boundary
        return True

    for phase in phases:
        speed = 0.0
        travelled = 0.0
        sim_time = 0.0
        max_steps = int(round(phase.max_sim_seconds / STEP_S)) + 10
        for _ in range(max_steps):
            command = terminal_phase_command(
                phase,
                x=x,
                y=y,
                yaw_rad=yaw,
                speed_mps=speed,
                travelled_m=travelled,
                sim_seconds=sim_time,
                config=config,
            )
            if command.done:
                break
            if command.command.throttle > 0.0:
                speed = min(phase.speed_cap_mps, speed + 0.12 * STEP_S)
            else:
                speed = max(0.0, speed - 0.5 * STEP_S)
            if speed < 0.01:
                speed = phase.speed_cap_mps
            sign = -1.0 if phase.reverse else 1.0
            yaw += (
                tolerances.yaw_response_factor
                * (math.tan(command.command.steer) / 3.0)
                * sign
                * speed
                * STEP_S
            )
            x += math.cos(yaw) * sign * speed * STEP_S
            y += math.sin(yaw) * sign * speed * STEP_S
            travelled += speed * STEP_S
            sim_time += STEP_S
            simulated.append((x, y, yaw))
            if not _check_pose(x, y, yaw, phase.phase):
                break
        # brake between phases
        speed = 0.0

    final_pose = (x, y, yaw)
    predicted = measure_refinement(
        x=x,
        y=y,
        yaw_rad=yaw,
        speed_mps=0.0,
        stopped=True,
        center=(float(bay_center[0]), float(bay_center[1])),
        bay_heading_rad=target.heading_rad,
        bay_polygon=bay_polygon,
        footprint=footprint,
        obstacle_points=obstacle_points,
        stability=RefinementStability(3, 0.0, 0.0, True),
        collision_count=0,
    )
    if reasons:
        return RefinementPathPlan(
            ok=False,
            reasons=tuple(dict.fromkeys(reasons)),
            target=target,
            phases=phases,
            config=config,
            simulated_poses=tuple(simulated),
            min_boundary_clearance_m=min_boundary,
            min_obstacle_clearance_m=min_obstacle,
            final_pose=final_pose,
            predicted_final=predicted,
            plan_hash=_sha256(
                {
                    "current": [round(current.x, 6), round(current.y, 6), round(current.yaw_rad, 9)],
                    "target": target.to_metadata(),
                    "policy": {
                        "reverse_max_distance_m": tolerances.reverse_max_distance_m,
                        "reverse_speed_cap_mps": tolerances.reverse_speed_cap_mps,
                        "reverse_max_sim_seconds": tolerances.reverse_max_sim_seconds,
                        "forward_max_distance_m": tolerances.forward_max_distance_m,
                        "forward_speed_cap_mps": tolerances.forward_speed_cap_mps,
                        "forward_max_sim_seconds": tolerances.forward_max_sim_seconds,
                        "yaw_response_factor": tolerances.yaw_response_factor,
                    },
                    "tolerances": tolerances.to_metadata(),
                }
            ),
            yaw_response_factor=tolerances.yaw_response_factor,
        )
    checks = [
        predicted.footprint_inside_bay,
        predicted.boundary_clearance_m is not None
        and predicted.boundary_clearance_m >= tolerances.target_boundary_clearance_m,
        abs(predicted.heading_error_deg) <= tolerances.target_heading_deg,
        predicted.distance_to_center_m <= tolerances.target_position_m,
        predicted.obstacle_clearance_m is None
        or predicted.obstacle_clearance_m >= tolerances.target_obstacle_clearance_m,
    ]
    if not all(checks):
        if not checks[0]:
            reasons.append("predicted_final_footprint")
        if not checks[1]:
            reasons.append("predicted_final_boundary")
        if not checks[2]:
            reasons.append("predicted_final_heading")
        if not checks[3]:
            reasons.append("predicted_final_position")
        if not checks[4]:
            reasons.append("predicted_final_obstacle")
    plan_hash = _sha256(
        {
            "current": [round(current.x, 6), round(current.y, 6), round(current.yaw_rad, 9)],
            "target": target.to_metadata(),
            "policy": {
                "reverse_max_distance_m": tolerances.reverse_max_distance_m,
                "reverse_speed_cap_mps": tolerances.reverse_speed_cap_mps,
                "reverse_max_sim_seconds": tolerances.reverse_max_sim_seconds,
                "forward_max_distance_m": tolerances.forward_max_distance_m,
                "forward_speed_cap_mps": tolerances.forward_speed_cap_mps,
                "forward_max_sim_seconds": tolerances.forward_max_sim_seconds,
                "yaw_response_factor": tolerances.yaw_response_factor,
            },
            "tolerances": tolerances.to_metadata(),
        }
    )
    return RefinementPathPlan(
        ok=not reasons,
        reasons=tuple(dict.fromkeys(reason for reason in reasons if reason)),
        target=target,
        phases=phases,
        config=config,
        simulated_poses=tuple(simulated),
        min_boundary_clearance_m=min_boundary,
        min_obstacle_clearance_m=min_obstacle,
        final_pose=final_pose,
        predicted_final=predicted,
        plan_hash=plan_hash,
        yaw_response_factor=tolerances.yaw_response_factor,
    )
