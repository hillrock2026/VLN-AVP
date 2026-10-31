"""Deterministic low-speed control law for one Alignment phase.

This is the same kind of proportional heading controller used by the validated
in-bay parking corrector, isolated here so it can be unit-tested without
CARLA. It never receives a model value: the target heading and the staging
point come from :class:`~vln.parking.alignment.AlignmentTarget`.

Sign convention (matches the real charger in this scene):

* forward: positive yaw error -> positive (left) steer increases yaw;
* reverse: positive yaw error -> negative (right) steer, and reverse motion
  with negative steer decreases yaw.

The throttle/brake choices reproduce the measured low-speed behaviour of the
``vehicle.dodge.charger``: 0.45 throttle is needed to engage reverse from a
braked forward state, and a small brake caps the speed instead of a second
control mode.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from vln.parking.alignment import (
    AlignmentMeasurement,
    AlignmentPhase,
    AlignmentTarget,
)

__all__ = [
    "AlignmentCommand",
    "alignment_phase_command",
    "alignment_round_improved",
    "alignment_overall_improved",
]

HEADING_STOP_DEG = 0.3


@dataclass(frozen=True)
class AlignmentCommand:
    steer: float
    throttle: float
    brake: float
    reverse: bool
    done: bool
    done_reason: str
    heading_error_deg: float
    longitudinal_error_m: float

    def to_metadata(self) -> dict:
        return {
            "steer": round(self.steer, 4),
            "throttle": self.throttle,
            "brake": self.brake,
            "reverse": self.reverse,
            "done": self.done,
            "done_reason": self.done_reason,
            "heading_error_deg": round(self.heading_error_deg, 4),
            "longitudinal_error_m": round(self.longitudinal_error_m, 4),
        }


def _wrap(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi


def _heading_error_deg(target: AlignmentTarget, yaw: float) -> float:
    return math.degrees(_wrap(target.reference_heading_rad - yaw))


def _longitudinal_error_m(
    target: AlignmentTarget, x: float, y: float
) -> float:
    forward = target.forward
    return -(
        (x - target.reference_xy[0]) * forward[0]
        + (y - target.reference_xy[1]) * forward[1]
    )


def alignment_phase_command(
    target: AlignmentTarget,
    *,
    phase: str,
    x: float,
    y: float,
    yaw_rad: float,
    speed_mps: float,
    travelled_m: float,
    max_distance_m: float,
    sim_seconds: float,
    max_sim_seconds: float,
) -> AlignmentCommand:
    """Return the next bounded control command for one alignment phase."""

    if not isinstance(target, AlignmentTarget):
        raise TypeError("target must be an AlignmentTarget")
    if phase not in AlignmentPhase.ALL:
        raise ValueError(f"unknown alignment phase {phase!r}")
    for name, value in (
        ("x", x),
        ("y", y),
        ("yaw_rad", yaw_rad),
        ("speed_mps", speed_mps),
        ("travelled_m", travelled_m),
        ("max_distance_m", max_distance_m),
        ("sim_seconds", sim_seconds),
        ("max_sim_seconds", max_sim_seconds),
    ):
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
    if speed_mps < 0.0 or travelled_m < 0.0 or sim_seconds < 0.0:
        raise ValueError("speed/travel/time must be non-negative")
    if max_distance_m <= 0.0 or max_sim_seconds <= 0.0:
        raise ValueError("phase limits must be positive")

    heading_deg = _heading_error_deg(target, yaw_rad)
    heading_rad = math.radians(heading_deg)
    longitudinal = _longitudinal_error_m(target, x, y)

    if travelled_m >= max_distance_m:
        return AlignmentCommand(
            0.0, 0.0, 1.0, phase == AlignmentPhase.REVERSE_ALIGN, True,
            "distance_limit", heading_deg, longitudinal,
        )
    if sim_seconds >= max_sim_seconds:
        return AlignmentCommand(
            0.0, 0.0, 1.0, phase == AlignmentPhase.REVERSE_ALIGN, True,
            "time_limit", heading_deg, longitudinal,
        )

    if phase == AlignmentPhase.REVERSE_ALIGN:
        if abs(heading_deg) <= HEADING_STOP_DEG:
            return AlignmentCommand(
                0.0, 0.0, 1.0, True, True, "heading_aligned",
                heading_deg, longitudinal,
            )
        steer = max(-0.9, min(0.9, -10.0 * heading_rad))
        speed_cap = 0.15
        if speed_mps < speed_cap:
            throttle, brake = 0.45, 0.0
        else:
            throttle, brake = 0.0, 0.25
        return AlignmentCommand(
            steer, throttle, brake, True, False, "driving",
            heading_deg, longitudinal,
        )

    if longitudinal <= 0.02 and abs(heading_deg) <= 0.3:
        return AlignmentCommand(
            0.0, 0.0, 1.0, False, True, "staging_reached",
            heading_deg, longitudinal,
        )
    if longitudinal <= -0.04:
        return AlignmentCommand(
            0.0, 0.0, 1.0, False, True, "overshoot",
            heading_deg, longitudinal,
        )
    steer = max(-0.9, min(0.9, 10.0 * heading_rad))
    speed_cap = 0.12
    if speed_mps < speed_cap:
        throttle, brake = 0.40, 0.0
    else:
        throttle, brake = 0.0, 0.25
    return AlignmentCommand(
        steer, throttle, brake, False, False, "driving",
        heading_deg, longitudinal,
    )


def alignment_round_improved(
    target: AlignmentTarget,
    *,
    phase: str,
    before: AlignmentMeasurement,
    after: AlignmentMeasurement,
) -> tuple[bool, tuple[str, ...]]:
    """Check that one executed phase improved the intended error.

    A phase that leaves the vehicle outside the allowed region, inside the bay
    or below the boundary margin is always a failure, even if the target error
    nominally improved.
    """

    if not isinstance(target, AlignmentTarget):
        raise TypeError("target must be an AlignmentTarget")
    if phase not in AlignmentPhase.ALL:
        raise ValueError(f"unknown alignment phase {phase!r}")
    if not isinstance(before, AlignmentMeasurement) or not isinstance(
        after, AlignmentMeasurement
    ):
        raise TypeError("before/after must be AlignmentMeasurements")
    tol = target.tolerances
    reasons: list[str] = []
    if not after.inside_allowed_region:
        reasons.append("post_phase_outside_region")
    if after.reference_inside_bay:
        reasons.append("post_phase_reference_inside_bay")
    if (
        after.boundary_clearance_m is None
        or after.boundary_clearance_m < tol.boundary_clearance_m
    ):
        reasons.append("post_phase_boundary_clearance")
    if (
        after.obstacle_clearance_m is not None
        and after.obstacle_clearance_m < tol.obstacle_clearance_m
    ):
        reasons.append("post_phase_obstacle_clearance")
    # A phase may trade a few centimetres of lateral offset while correcting
    # the primary axis; only a lateral result outside the pre-declared
    # tolerance *and* worse than the phase start is a failure.
    if (
        abs(after.lateral_error_m) > tol.lateral_m
        and abs(after.lateral_error_m) > abs(before.lateral_error_m) + 0.02
    ):
        reasons.append("post_phase_lateral_worsened")
    heading_improved = abs(after.heading_error_deg) <= abs(
        before.heading_error_deg
    ) - 0.15
    heading_not_worse = abs(after.heading_error_deg) <= abs(
        before.heading_error_deg
    ) + 0.5
    longitudinal_improved = abs(after.longitudinal_error_m) <= abs(
        before.longitudinal_error_m
    ) - 0.005
    if phase == AlignmentPhase.REVERSE_ALIGN:
        if not heading_improved:
            reasons.append("reverse_phase_did_not_reduce_heading")
    else:
        if not heading_not_worse:
            reasons.append("forward_phase_heading_worsened")
        if not (
            longitudinal_improved
            or abs(after.longitudinal_error_m) <= tol.longitudinal_m
        ):
            reasons.append("forward_phase_did_not_reduce_longitudinal")
    return (not reasons, tuple(dict.fromkeys(reasons)))


def alignment_overall_improved(
    target: AlignmentTarget,
    *,
    initial: AlignmentMeasurement,
    final: AlignmentMeasurement,
) -> tuple[bool, tuple[str, ...]]:
    """Cumulative check across all rounds, separate from the verifier."""

    if not isinstance(target, AlignmentTarget):
        raise TypeError("target must be an AlignmentTarget")
    if not isinstance(initial, AlignmentMeasurement) or not isinstance(
        final, AlignmentMeasurement
    ):
        raise TypeError("initial/final must be AlignmentMeasurements")
    tol = target.tolerances
    reasons: list[str] = []
    if abs(final.heading_error_deg) > abs(initial.heading_error_deg) + 0.2:
        reasons.append("cumulative_heading_worsened")
    if abs(final.longitudinal_error_m) > abs(
        initial.longitudinal_error_m
    ) + 0.02:
        reasons.append("cumulative_longitudinal_worsened")
    if abs(final.lateral_error_m) > abs(initial.lateral_error_m) + 0.02:
        reasons.append("cumulative_lateral_worsened")
    if (
        final.boundary_clearance_m is None
        or final.boundary_clearance_m < tol.boundary_clearance_m
    ):
        reasons.append("cumulative_boundary_clearance")
    return (not reasons, tuple(reasons))
