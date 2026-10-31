"""Bounded local route planning for the Alignment stage.

The general graph arbiter answers "which waypoint edge may be driven". At the
CAP-07B-01 approach pose the only graph continuation is the validated parking
arc into the bay, and Alignment is explicitly forbidden to drive that arc.
This module therefore arbitrates the *alignment-local* corridor instead:

* only a short reverse arc (to remove heading error while gaining north
  clearance) or a short forward return to the staging line is allowed;
* every sampled pose must stay inside the declared alignment region, outside
  the painted bay polygon, and clear of the measured static obstacles;
* no path may move south of the staging line, so it can never become an entry
  path by accident.

It returns a typed result. Only ``SELECTED`` carries a plan; every other status
is a refusal. It is pure and imports no CARLA package.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from vln.carla.parking_geometry import (
    Footprint,
    footprint_clearance,
    footprint_polygon_clearance,
)
from vln.parking.alignment import (
    AlignmentBudget,
    AlignmentMeasurement,
    AlignmentPhase,
    AlignmentTarget,
)

__all__ = [
    "AlignmentRouteStatus",
    "AlignmentPlan",
    "AlignmentRouteResult",
    "plan_alignment_round",
    "validate_alignment_poses",
    "ALIGNMENT_STEP_M",
]

ALIGNMENT_STEP_M = 0.05
WHEELBASE_M = 3.0


class AlignmentRouteStatus:
    SELECTED = "selected"
    ALREADY_ALIGNED = "already_aligned"
    REFUSED_NO_PHASE = "refused_no_phase"
    REFUSED_REGION = "refused_region"
    REFUSED_CLEARANCE = "refused_clearance"
    REFUSED_BUDGET = "refused_budget"
    REFUSED_NO_IMPROVEMENT = "refused_no_improvement"

    ALL = frozenset(
        {
            SELECTED,
            ALREADY_ALIGNED,
            REFUSED_NO_PHASE,
            REFUSED_REGION,
            REFUSED_CLEARANCE,
            REFUSED_BUDGET,
            REFUSED_NO_IMPROVEMENT,
        }
    )
    REFUSED = frozenset(ALL - {SELECTED, ALREADY_ALIGNED})


def _wrap(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _heading_error_rad(target: AlignmentTarget, yaw: float) -> float:
    return _wrap(target.reference_heading_rad - yaw)


def _longitudinal_error_m(
    target: AlignmentTarget, x: float, y: float
) -> float:
    forward = target.forward
    return -(
        (x - target.reference_xy[0]) * forward[0]
        + (y - target.reference_xy[1]) * forward[1]
    )


@dataclass(frozen=True)
class AlignmentPlan:
    """One bounded alignment phase, already checked against the scene."""

    phase: str
    round_index: int
    reverse: bool
    points: tuple[tuple[float, float], ...]
    poses: tuple[tuple[float, float, float], ...]
    length_m: float
    start_pose: tuple[float, float, float]
    end_pose: tuple[float, float, float]
    heading_target_rad: float
    speed_cap_mps: float
    max_sim_seconds: float
    max_distance_m: float
    heading_before_deg: float
    longitudinal_before_m: float
    lateral_before_m: float
    checks: dict

    def __post_init__(self) -> None:
        if self.phase not in AlignmentPhase.ALL:
            raise ValueError(f"unknown alignment phase {self.phase!r}")
        if type(self.reverse) is not bool:
            raise ValueError("reverse must be a bool")
        if self.reverse != (self.phase == AlignmentPhase.REVERSE_ALIGN):
            raise ValueError("phase and reverse flag disagree")
        if len(self.points) < 2 or len(self.poses) != len(self.points):
            raise ValueError("a plan needs at least two points and matching poses")
        if not (0.0 < self.length_m <= self.max_distance_m + 1e-6):
            raise ValueError("plan length exceeds its distance limit")

    def to_metadata(self) -> dict:
        return {
            "phase": self.phase,
            "round_index": self.round_index,
            "reverse": self.reverse,
            "length_m": round(self.length_m, 4),
            "start_pose": {
                "x": round(self.start_pose[0], 4),
                "y": round(self.start_pose[1], 4),
                "yaw_deg": round(math.degrees(self.start_pose[2]), 4),
            },
            "end_pose": {
                "x": round(self.end_pose[0], 4),
                "y": round(self.end_pose[1], 4),
                "yaw_deg": round(math.degrees(self.end_pose[2]), 4),
            },
            "heading_target_deg": round(
                math.degrees(self.heading_target_rad), 4
            ),
            "speed_cap_mps": self.speed_cap_mps,
            "max_sim_seconds": self.max_sim_seconds,
            "max_distance_m": self.max_distance_m,
            "heading_before_deg": round(self.heading_before_deg, 4),
            "longitudinal_before_m": round(self.longitudinal_before_m, 4),
            "lateral_before_m": round(self.lateral_before_m, 4),
            "checks": dict(self.checks),
            "points": [[round(x, 4), round(y, 4)] for x, y in self.points],
        }


@dataclass(frozen=True)
class AlignmentRouteResult:
    status: str
    reason: str
    plan: AlignmentPlan | None

    def __post_init__(self) -> None:
        if self.status not in AlignmentRouteStatus.ALL:
            raise ValueError(f"unknown alignment route status {self.status!r}")
        if (self.status == AlignmentRouteStatus.SELECTED) != (self.plan is not None):
            raise ValueError("only a selected route carries a plan")
        if self.status == AlignmentRouteStatus.SELECTED and self.reason:
            raise ValueError("a selected route cannot carry a refusal reason")
        if self.status in AlignmentRouteStatus.REFUSED and not self.reason:
            raise ValueError("a refused route needs a refusal reason")

    @property
    def ok(self) -> bool:
        return self.status == AlignmentRouteStatus.SELECTED

    def to_metadata(self) -> dict:
        return {
            "status": self.status,
            "ok": self.ok,
            "reason": self.reason,
            "plan": None if self.plan is None else self.plan.to_metadata(),
        }


def validate_alignment_poses(
    target: AlignmentTarget,
    poses: Sequence[Sequence[float]],
    *,
    footprint: Footprint | None = None,
) -> tuple[str, ...]:
    """Return every geometric violation in a sequence of ``(x, y, yaw)`` poses.

    This is the independent audit used for both the planned path and the real
    trajectory the controller actually produced.
    """

    if not isinstance(target, AlignmentTarget):
        raise TypeError("target must be an AlignmentTarget")
    footprint = footprint or target.footprint
    tolerance = target.tolerances
    reasons: list[str] = []
    south_limit = target.reference_xy[1] - 0.10
    for index, pose in enumerate(poses):
        if not isinstance(pose, (tuple, list)) or len(pose) != 3:
            reasons.append(f"pose_{index}_not_xyz")
            continue
        x, y, yaw = float(pose[0]), float(pose[1]), float(pose[2])
        if not all(math.isfinite(value) for value in (x, y, yaw)):
            reasons.append(f"pose_{index}_not_finite")
            continue
        if not target.region_contains(x, y):
            reasons.append(f"pose_{index}_outside_region")
        if y < south_limit:
            reasons.append(f"pose_{index}_south_of_staging_line")
        clearance = footprint_polygon_clearance(
            x, y, yaw, footprint, target.bay_polygon
        )
        if clearance["min_clearance_m"] is None:
            reasons.append(f"pose_{index}_clearance_unmeasured")
        elif clearance["min_clearance_m"] < tolerance.boundary_clearance_m:
            reasons.append(f"pose_{index}_boundary_clearance")
        if target.obstacle_points:
            obstacle = footprint_clearance(
                x, y, yaw, footprint, target.obstacle_points
            )
            measured = obstacle["min_clearance_m"]
            if measured is not None and measured < tolerance.obstacle_clearance_m:
                reasons.append(f"pose_{index}_obstacle_clearance")
    return tuple(dict.fromkeys(reasons))


def _integrate_reverse(
    target: AlignmentTarget,
    start: tuple[float, float, float],
    *,
    max_distance_m: float,
    max_sim_seconds: float,
) -> tuple[list[tuple[float, float]], list[tuple[float, float, float]], float]:
    x, y, yaw = start
    points = [(x, y)]
    poses = [(x, y, yaw)]
    travelled = 0.0
    north_limit = target.region_y_max - 0.02
    while travelled < max_distance_m - 1e-9:
        heading_error = _heading_error_rad(target, yaw)
        steer = _clamp(-10.0 * heading_error, -0.9, 0.9)
        step = min(ALIGNMENT_STEP_M, max_distance_m - travelled)
        yaw_next = yaw + (math.tan(steer) / WHEELBASE_M) * (-step)
        mid = 0.5 * (yaw + yaw_next)
        x_next = x + math.cos(mid) * (-step)
        y_next = y + math.sin(mid) * (-step)
        if y_next > north_limit:
            break
        points.append((x_next, y_next))
        poses.append((x_next, y_next, yaw_next))
        travelled += step
        x, y, yaw = x_next, y_next, yaw_next
    return points, poses, travelled


def _integrate_forward(
    target: AlignmentTarget,
    start: tuple[float, float, float],
    *,
    max_distance_m: float,
    max_sim_seconds: float,
) -> tuple[list[tuple[float, float]], list[tuple[float, float, float]], float]:
    x, y, yaw = start
    points = [(x, y)]
    poses = [(x, y, yaw)]
    travelled = 0.0
    south_limit = target.reference_xy[1] - 0.04
    while travelled < max_distance_m - 1e-9:
        heading_error = _heading_error_rad(target, yaw)
        steer = _clamp(10.0 * heading_error, -0.9, 0.9)
        step = min(ALIGNMENT_STEP_M, max_distance_m - travelled)
        yaw_next = yaw + (math.tan(steer) / WHEELBASE_M) * step
        mid = 0.5 * (yaw + yaw_next)
        x_next = x + math.cos(mid) * step
        y_next = y + math.sin(mid) * step
        if y_next < south_limit:
            break
        points.append((x_next, y_next))
        poses.append((x_next, y_next, yaw_next))
        travelled += step
        x, y, yaw = x_next, y_next, yaw_next
        if abs(_longitudinal_error_m(target, x, y)) <= 0.02:
            break
    return points, poses, travelled


def _plan(
    target: AlignmentTarget,
    measurement: AlignmentMeasurement,
    *,
    phase: str,
    round_index: int,
    budget: AlignmentBudget,
) -> AlignmentRouteResult:
    max_distance = min(
        budget.max_phase_distance_m, budget.remaining_distance_m()
    )
    if max_distance < 0.15:
        return AlignmentRouteResult(
            AlignmentRouteStatus.REFUSED_BUDGET,
            "no phase distance remains in the alignment budget",
            None,
        )
    start = (measurement.x, measurement.y, measurement.yaw_rad)
    if phase == AlignmentPhase.REVERSE_ALIGN:
        points, poses, length = _integrate_reverse(
            target,
            start,
            max_distance_m=max_distance,
            max_sim_seconds=budget.max_phase_sim_seconds,
        )
        speed_cap = budget.reverse_speed_cap_mps
    else:
        points, poses, length = _integrate_forward(
            target,
            start,
            max_distance_m=max_distance,
            max_sim_seconds=budget.max_phase_sim_seconds,
        )
        speed_cap = budget.forward_speed_cap_mps
    if length < 0.15:
        return AlignmentRouteResult(
            AlignmentRouteStatus.REFUSED_NO_PHASE,
            f"{phase} produced no usable displacement",
            None,
        )

    violations = validate_alignment_poses(target, poses)
    if violations:
        status = (
            AlignmentRouteStatus.REFUSED_REGION
            if any("region" in reason or "staging_line" in reason for reason in violations)
            else AlignmentRouteStatus.REFUSED_CLEARANCE
        )
        return AlignmentRouteResult(status, "; ".join(violations[:6]), None)

    end = poses[-1]
    heading_after_deg = math.degrees(_heading_error_rad(target, end[2]))
    longitudinal_after = _longitudinal_error_m(target, end[0], end[1])
    improved = (
        abs(heading_after_deg) < abs(measurement.heading_error_deg) - 0.2
        if phase == AlignmentPhase.REVERSE_ALIGN
        else (
            abs(longitudinal_after)
            < abs(measurement.longitudinal_error_m) - 0.005
            or abs(heading_after_deg)
            < abs(measurement.heading_error_deg) - 0.2
        )
    )
    if not improved:
        return AlignmentRouteResult(
            AlignmentRouteStatus.REFUSED_NO_IMPROVEMENT,
            f"{phase} would not reduce the measured error",
            None,
        )

    plan = AlignmentPlan(
        phase=phase,
        round_index=round_index,
        reverse=phase == AlignmentPhase.REVERSE_ALIGN,
        points=tuple(points),
        poses=tuple(poses),
        length_m=length,
        start_pose=start,
        end_pose=end,
        heading_target_rad=target.reference_heading_rad,
        speed_cap_mps=speed_cap,
        max_sim_seconds=budget.max_phase_sim_seconds,
        max_distance_m=max_distance,
        heading_before_deg=measurement.heading_error_deg,
        longitudinal_before_m=measurement.longitudinal_error_m,
        lateral_before_m=measurement.lateral_error_m,
        checks={
            "poses_checked": len(poses),
            "boundary_clearance_min_m": min(
                footprint_polygon_clearance(
                    x, y, yaw, target.footprint, target.bay_polygon
                )["min_clearance_m"]
                for x, y, yaw in poses
            ),
            "heading_after_deg": round(heading_after_deg, 4),
            "longitudinal_after_m": round(longitudinal_after, 4),
            "stays_north_of_staging_line": all(
                y >= target.reference_xy[1] - 0.10 for x, y, _ in poses
            ),
            "ends_north_of_staging_line": end[1]
            >= target.reference_xy[1] - 0.06,
        },
    )
    return AlignmentRouteResult(
        AlignmentRouteStatus.SELECTED, "", plan
    )


def plan_alignment_round(
    target: AlignmentTarget,
    measurement: AlignmentMeasurement,
    *,
    budget: AlignmentBudget,
    round_index: int,
) -> AlignmentRouteResult:
    """Choose and validate exactly one bounded alignment phase."""

    if not isinstance(target, AlignmentTarget):
        raise TypeError("target must be an AlignmentTarget")
    if not isinstance(measurement, AlignmentMeasurement):
        raise TypeError("measurement must be an AlignmentMeasurement")
    if not isinstance(budget, AlignmentBudget):
        raise TypeError("budget must be an AlignmentBudget")
    if type(round_index) is not int or round_index < 1:
        raise ValueError("round_index must be a positive int")
    if not budget.can_start_round:
        return AlignmentRouteResult(
            AlignmentRouteStatus.REFUSED_BUDGET,
            "alignment round or distance budget is exhausted",
            None,
        )

    tol = target.tolerances
    heading_abs = abs(measurement.heading_error_deg)
    longitudinal_abs = abs(measurement.longitudinal_error_m)
    lateral_abs = abs(measurement.lateral_error_m)
    if (
        heading_abs <= tol.heading_deg
        and longitudinal_abs <= tol.longitudinal_m
        and lateral_abs <= tol.lateral_m
    ):
        return AlignmentRouteResult(
            AlignmentRouteStatus.ALREADY_ALIGNED,
            "",
            None,
        )

    north_room = target.region_y_max - measurement.y
    if heading_abs > 0.6 and north_room >= 0.35:
        return _plan(
            target,
            measurement,
            phase=AlignmentPhase.REVERSE_ALIGN,
            round_index=round_index,
            budget=budget,
        )
    if longitudinal_abs > 0.03 or heading_abs > 0.6:
        return _plan(
            target,
            measurement,
            phase=AlignmentPhase.FORWARD_TO_STAGING,
            round_index=round_index,
            budget=budget,
        )
    return AlignmentRouteResult(
        AlignmentRouteStatus.REFUSED_NO_PHASE,
        "only the lateral error is outside tolerance; no bounded phase can "
        "correct it without entering the bay",
        None,
    )
