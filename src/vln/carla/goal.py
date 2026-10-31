"""Explicit goal-region evaluation for multi-round navigation.

A graph node, a waypoint arrival, or one successful ``parking.move`` is not a
goal arrival. The caller defines a goal region once, and this module checks the
real stopped pose against all of it:

* distance from the named goal point;
* heading relative to the declared approach heading;
* real vehicle speed at the moment of evaluation.

The function is pure and CARLA-free. It returns a typed evaluation, not a
boolean, so a run can record *which* condition failed instead of collapsing
"not reached" into one opaque status.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from vln.nav import VehiclePose

from .route_control import wrap_angle

__all__ = [
    "GOAL_REACHED",
    "GOAL_NOT_REACHED",
    "GoalSpec",
    "GoalEvaluation",
    "evaluate_goal",
]

GOAL_REACHED = "goal_reached"
GOAL_NOT_REACHED = "not_reached"

#: Tolerances are inclusive; this only absorbs trigonometric round-off at the
#: exact boundary (for example -70.0 degrees against a 20-degree tolerance).
_BOUNDARY_EPSILON = 1e-9


def _finite(value: object, name: str) -> float:
    if type(value) is not int and type(value) is not float:
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
    return float(value)


@dataclass(frozen=True)
class GoalSpec:
    """The declared goal region, in the same world frame as the real pose."""

    node_id: str
    x: float
    y: float
    heading_rad: float
    distance_tolerance_m: float = 1.5
    heading_tolerance_rad: float = math.radians(30.0)
    stop_speed_mps: float = 0.25

    def __post_init__(self) -> None:
        if type(self.node_id) is not str or self.node_id.strip() == "":
            raise ValueError("node_id must be a non-blank str")
        object.__setattr__(self, "x", _finite(self.x, "goal.x"))
        object.__setattr__(self, "y", _finite(self.y, "goal.y"))
        object.__setattr__(
            self, "heading_rad", wrap_angle(_finite(self.heading_rad, "goal.heading"))
        )
        distance = _finite(self.distance_tolerance_m, "goal.distance_tolerance_m")
        if distance <= 0:
            raise ValueError("distance tolerance must be positive")
        heading = _finite(self.heading_tolerance_rad, "goal.heading_tolerance_rad")
        if heading < 0 or heading > math.pi:
            raise ValueError("heading tolerance must be in [0, pi]")
        speed = _finite(self.stop_speed_mps, "goal.stop_speed_mps")
        if speed < 0:
            raise ValueError("stop speed must be non-negative")
        object.__setattr__(self, "distance_tolerance_m", distance)
        object.__setattr__(self, "heading_tolerance_rad", heading)
        object.__setattr__(self, "stop_speed_mps", speed)

    def to_metadata(self) -> dict:
        return {
            "node_id": self.node_id,
            "x": self.x,
            "y": self.y,
            "heading_rad": self.heading_rad,
            "heading_deg": round(math.degrees(self.heading_rad), 3),
            "distance_tolerance_m": self.distance_tolerance_m,
            "heading_tolerance_deg": round(math.degrees(self.heading_tolerance_rad), 3),
            "stop_speed_mps": self.stop_speed_mps,
        }


@dataclass(frozen=True)
class GoalEvaluation:
    """Result of checking one real pose against a :class:`GoalSpec`."""

    status: str
    node_id: str
    distance_m: float
    heading_error_rad: float
    speed_mps: float
    stopped: bool
    reasons: tuple[str, ...]
    distance_tolerance_m: float
    heading_tolerance_rad: float
    stop_speed_mps: float

    def __post_init__(self) -> None:
        if self.status not in (GOAL_REACHED, GOAL_NOT_REACHED):
            raise ValueError(f"unknown goal status {self.status!r}")
        if self.status == GOAL_REACHED and self.reasons:
            raise ValueError("goal_reached cannot carry failure reasons")
        if self.status == GOAL_NOT_REACHED and not self.reasons:
            raise ValueError("not_reached must carry at least one reason")

    @property
    def ok(self) -> bool:
        return self.status == GOAL_REACHED

    def to_metadata(self) -> dict:
        return {
            "status": self.status,
            "ok": self.ok,
            "node_id": self.node_id,
            "distance_m": round(self.distance_m, 3),
            "heading_error_rad": round(self.heading_error_rad, 6),
            "heading_error_deg": round(math.degrees(self.heading_error_rad), 3),
            "speed_mps": round(self.speed_mps, 3),
            "stopped": self.stopped,
            "reasons": list(self.reasons),
            "distance_tolerance_m": self.distance_tolerance_m,
            "heading_tolerance_rad": self.heading_tolerance_rad,
            "heading_tolerance_deg": round(math.degrees(self.heading_tolerance_rad), 3),
            "stop_speed_mps": self.stop_speed_mps,
        }


def evaluate_goal(
    spec: GoalSpec,
    pose: VehiclePose,
    *,
    speed_mps: float,
    stopped: bool,
) -> GoalEvaluation:
    """Check the real stopped pose against every part of the goal region."""

    if not isinstance(spec, GoalSpec):
        raise TypeError("spec must be a GoalSpec")
    if not isinstance(pose, VehiclePose):
        raise TypeError("pose must be a VehiclePose")
    speed = _finite(speed_mps, "speed_mps")
    if speed < 0:
        raise ValueError("speed_mps must be non-negative")
    if type(stopped) is not bool:
        raise ValueError("stopped must be a bool")

    distance = math.hypot(pose.x - spec.x, pose.y - spec.y)
    heading_error = wrap_angle(pose.heading - spec.heading_rad)
    stopped_by_speed = speed < spec.stop_speed_mps
    reasons: list[str] = []
    if distance > spec.distance_tolerance_m + _BOUNDARY_EPSILON:
        reasons.append("distance_above_tolerance")
    if abs(heading_error) > spec.heading_tolerance_rad + _BOUNDARY_EPSILON:
        reasons.append("heading_outside_tolerance")
    if not stopped_by_speed:
        reasons.append("vehicle_not_stopped")
    if not stopped:
        reasons.append("stop_not_confirmed")

    return GoalEvaluation(
        status=GOAL_REACHED if not reasons else GOAL_NOT_REACHED,
        node_id=spec.node_id,
        distance_m=distance,
        heading_error_rad=heading_error,
        speed_mps=speed,
        stopped=stopped_by_speed and stopped,
        reasons=tuple(dict.fromkeys(reasons)),
        distance_tolerance_m=spec.distance_tolerance_m,
        heading_tolerance_rad=spec.heading_tolerance_rad,
        stop_speed_mps=spec.stop_speed_mps,
    )
