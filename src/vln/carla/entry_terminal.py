"""Bounded terminal alignment phases for Entry.

The validated CARLA charger understeers on the 3.56 m Entry arc at low speed:
the main arc reaches the slot region with roughly 8-12 deg of residual heading.
The historical parking pipeline used a short reverse arc plus a forward
straight inside the bay to remove that residual. CAP-07B-04 reuses the same
bounded geometry as **two separate Entry terminal segments**, each with its own
Kernel permit, safety preflight, brake and real post-state check.

This is terminal positioning for the declared Entry route, not a parking
verdict and not `PARKING_COMPLETED`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from vln.carla.parking_geometry import (
    Footprint,
    footprint_polygon_clearance,
    point_in_polygon,
)
from vln.carla.route_control import ControlCommand, wrap_angle
from vln.parking.entry import EntryMeasurement, EntryRoute

__all__ = [
    "TerminalPhase",
    "TerminalCorrectionConfig",
    "TerminalPhasePlan",
    "TerminalCommand",
    "BoundaryFloorGuard",
    "terminal_phase_plan",
    "terminal_phase_command",
    "terminal_phase_improved",
    "terminal_reference_in_box",
    "terminal_footprint_in_buffer",
    "boundary_floor_guard",
]


class TerminalPhase:
    REVERSE_ALIGN = "TERMINAL_REVERSE_ALIGN"
    FORWARD_RETURN = "TERMINAL_FORWARD_RETURN"
    ALL = frozenset({REVERSE_ALIGN, FORWARD_RETURN})


@dataclass(frozen=True)
class TerminalCorrectionConfig:
    reverse_max_distance_m: float = 2.4
    reverse_speed_cap_mps: float = 0.16
    reverse_max_sim_seconds: float = 30.0
    reverse_stop_heading_deg: float = 1.5
    forward_max_distance_m: float = 3.2
    forward_speed_cap_mps: float = 0.14
    forward_max_sim_seconds: float = 40.0
    forward_stop_heading_deg: float = 3.0
    forward_stop_distance_m: float = 0.12
    terminal_box_x_min: float = -10.8
    terminal_box_x_max: float = -6.8
    terminal_box_y_min: float = -22.3
    terminal_box_y_max: float = -19.6
    terminal_buffer_margin_m: float = 1.0
    obstacle_clearance_m: float = 0.20

    def to_metadata(self) -> dict:
        return {
            "reverse_max_distance_m": self.reverse_max_distance_m,
            "reverse_speed_cap_mps": self.reverse_speed_cap_mps,
            "reverse_max_sim_seconds": self.reverse_max_sim_seconds,
            "reverse_stop_heading_deg": self.reverse_stop_heading_deg,
            "forward_max_distance_m": self.forward_max_distance_m,
            "forward_speed_cap_mps": self.forward_speed_cap_mps,
            "forward_max_sim_seconds": self.forward_max_sim_seconds,
            "forward_stop_heading_deg": self.forward_stop_heading_deg,
            "forward_stop_distance_m": self.forward_stop_distance_m,
            "terminal_box": {
                "x_min": self.terminal_box_x_min,
                "x_max": self.terminal_box_x_max,
                "y_min": self.terminal_box_y_min,
                "y_max": self.terminal_box_y_max,
            },
            "terminal_buffer_margin_m": self.terminal_buffer_margin_m,
            "obstacle_clearance_m": self.obstacle_clearance_m,
        }


@dataclass(frozen=True)
class TerminalPhasePlan:
    phase: str
    target_x: float
    target_y: float
    target_heading_rad: float
    max_distance_m: float
    speed_cap_mps: float
    max_sim_seconds: float
    reverse: bool
    start_pose: tuple[float, float, float]
    points: tuple[tuple[float, float], ...]

    def to_metadata(self) -> dict:
        return {
            "phase": self.phase,
            "target": {
                "x": round(self.target_x, 4),
                "y": round(self.target_y, 4),
                "heading_deg": round(math.degrees(self.target_heading_rad), 4),
            },
            "max_distance_m": self.max_distance_m,
            "speed_cap_mps": self.speed_cap_mps,
            "max_sim_seconds": self.max_sim_seconds,
            "reverse": self.reverse,
            "start_pose": {
                "x": round(self.start_pose[0], 4),
                "y": round(self.start_pose[1], 4),
                "yaw_deg": round(math.degrees(self.start_pose[2]), 4),
            },
            "points": [[round(x, 4), round(y, 4)] for x, y in self.points],
        }


@dataclass(frozen=True)
class TerminalCommand:
    command: ControlCommand
    reverse: bool
    done: bool
    done_reason: str
    heading_error_deg: float
    distance_to_slot_m: float

    def to_metadata(self) -> dict:
        return {
            "throttle": round(self.command.throttle, 4),
            "brake": round(self.command.brake, 4),
            "steer": round(self.command.steer, 4),
            "reverse": self.reverse,
            "done": self.done,
            "done_reason": self.done_reason,
            "heading_error_deg": round(self.heading_error_deg, 4),
            "distance_to_slot_m": round(self.distance_to_slot_m, 4),
        }


def terminal_reference_in_box(
    x: float, y: float, config: TerminalCorrectionConfig
) -> bool:
    return (
        config.terminal_box_x_min <= x <= config.terminal_box_x_max
        and config.terminal_box_y_min <= y <= config.terminal_box_y_max
    )


def terminal_footprint_in_buffer(
    corners,
    route: EntryRoute,
    config: TerminalCorrectionConfig,
) -> bool:
    margin = config.terminal_buffer_margin_m
    x_min = min(p[0] for p in route.bay_polygon) - margin
    x_max = max(p[0] for p in route.bay_polygon) + margin
    y_min = min(p[1] for p in route.bay_polygon) - margin
    y_max = max(p[1] for p in route.bay_polygon) + margin
    return all(x_min <= px <= x_max and y_min <= py <= y_max for px, py in corners)


@dataclass(frozen=True)
class BoundaryFloorGuard:
    """Per-tick result of the terminal boundary-clearance floor guard.

    ``triggered`` is true when the current real footprint is unreadable,
    outside the bay, or closer to the bay boundary than ``floor_m``. A trigger
    means the terminal controller must brake immediately and must not execute
    any remaining motion segment.
    """

    triggered: bool
    reason: str
    floor_m: float | None
    clearance_m: float | None
    footprint_inside_bay: bool | None
    footprint_corners: tuple[tuple[float, float], ...]
    frame: int | None
    transform: Mapping[str, object] | None
    bounding_box: Mapping[str, object] | None
    error: str | None = None

    @classmethod
    def fail(
        cls,
        reason: str,
        floor_m: float | None,
        *,
        error: str | None = None,
        frame: int | None = None,
        transform: Mapping[str, object] | None = None,
        bounding_box: Mapping[str, object] | None = None,
        clearance_m: float | None = None,
        footprint_inside_bay: bool | None = None,
        footprint_corners: tuple[tuple[float, float], ...] = (),
    ) -> "BoundaryFloorGuard":
        return cls(
            triggered=True,
            reason=reason,
            floor_m=floor_m,
            clearance_m=clearance_m,
            footprint_inside_bay=footprint_inside_bay,
            footprint_corners=footprint_corners,
            frame=frame,
            transform=transform,
            bounding_box=bounding_box,
            error=error,
        )

    def to_metadata(self) -> dict:
        return {
            "triggered": self.triggered,
            "reason": self.reason,
            "floor_m": None if self.floor_m is None else round(self.floor_m, 6),
            "clearance_m": None
            if self.clearance_m is None
            else round(self.clearance_m, 6),
            "footprint_inside_bay": self.footprint_inside_bay,
            "footprint_corners": [
                [round(px, 4), round(py, 4)] for px, py in self.footprint_corners
            ],
            "frame": self.frame,
            "transform": None if self.transform is None else dict(self.transform),
            "bounding_box": None
            if self.bounding_box is None
            else dict(self.bounding_box),
            "error": self.error,
        }


def _finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def boundary_floor_guard(
    *,
    floor_m: object,
    x: object,
    y: object,
    yaw_rad: object,
    frame: object,
    half_length: object,
    half_width: object,
    bay_polygon: Sequence[Sequence[float]],
    bbox_offset_x: object = 0.0,
    bbox_offset_y: object = 0.0,
    tolerance_m: object = 1e-9,
) -> BoundaryFloorGuard:
    """Evaluate the real footprint against the bay boundary on one tick.

    This function never raises. Missing, non-finite or invalid inputs and
    geometry errors return ``triggered=True`` so the caller fails closed and
    brakes instead of continuing on stale or unreadable state.

    Boundary points use the same even-odd rule as the final parking verdict.
    The bounding-box centre offset is applied in the actor frame; the CARLA
    ``bounding_box.location`` is not necessarily the actor origin.
    """

    if not _finite_number(floor_m) or float(floor_m) < 0.0:
        return BoundaryFloorGuard.fail("boundary_floor_invalid", None)
    floor_value = float(floor_m)
    if not _finite_number(tolerance_m) or float(tolerance_m) < 0.0:
        return BoundaryFloorGuard.fail(
            "boundary_guard_config_invalid", floor_value
        )
    tolerance = float(tolerance_m)
    transform = {
        "x": x,
        "y": y,
        "yaw_rad": yaw_rad,
        "frame": frame,
    }
    bbox = {
        "half_length": half_length,
        "half_width": half_width,
        "offset_x": bbox_offset_x,
        "offset_y": bbox_offset_y,
    }
    if (
        not _finite_number(x)
        or not _finite_number(y)
        or not _finite_number(yaw_rad)
        or type(frame) is not int
        or frame < 0
        or not _finite_number(half_length)
        or not _finite_number(half_width)
        or float(half_length) <= 0.0
        or float(half_width) <= 0.0
        or not _finite_number(bbox_offset_x)
        or not _finite_number(bbox_offset_y)
    ):
        return BoundaryFloorGuard.fail(
            "boundary_state_unreadable",
            floor_value,
            frame=frame if type(frame) is int else None,
            transform=transform,
            bounding_box=bbox,
        )
    try:
        polygon = tuple(
            (float(point[0]), float(point[1])) for point in bay_polygon
        )
    except (TypeError, ValueError, IndexError):
        return BoundaryFloorGuard.fail(
            "boundary_geometry_invalid",
            floor_value,
            error="bay polygon is not a sequence of (x, y) pairs",
            frame=frame,
            transform=transform,
            bounding_box=bbox,
        )
    if len(polygon) < 3 or any(
        not math.isfinite(px) or not math.isfinite(py) for px, py in polygon
    ):
        return BoundaryFloorGuard.fail(
            "boundary_geometry_invalid",
            floor_value,
            error="bay polygon needs at least three finite points",
            frame=frame,
            transform=transform,
            bounding_box=bbox,
        )
    try:
        yaw = float(yaw_rad)
        offset_x = float(bbox_offset_x)
        offset_y = float(bbox_offset_y)
        center_x = (
            float(x) + math.cos(yaw) * offset_x - math.sin(yaw) * offset_y
        )
        center_y = (
            float(y) + math.sin(yaw) * offset_x + math.cos(yaw) * offset_y
        )
        footprint = Footprint(
            half_length=float(half_length),
            half_width=float(half_width),
            front_margin=0.0,
        )
        corners = footprint.corners(center_x, center_y, yaw)
        if any(
            not math.isfinite(px) or not math.isfinite(py) for px, py in corners
        ):
            raise ValueError("footprint corners are not finite")
        inside = all(
            point_in_polygon(px, py, polygon) for px, py in corners
        )
        clearance = footprint_polygon_clearance(
            center_x, center_y, yaw, footprint, polygon
        )["min_clearance_m"]
        if clearance is None or not math.isfinite(float(clearance)):
            return BoundaryFloorGuard.fail(
                "boundary_clearance_invalid",
                floor_value,
                error="clearance is not finite",
                frame=frame,
                transform=transform,
                bounding_box=bbox,
                footprint_inside_bay=inside,
                footprint_corners=tuple(corners),
            )
    except Exception as error:
        return BoundaryFloorGuard.fail(
            "boundary_geometry_invalid",
            floor_value,
            error=f"{type(error).__name__}: {error}",
            frame=frame,
            transform=transform,
            bounding_box=bbox,
        )
    if not inside:
        return BoundaryFloorGuard.fail(
            "boundary_footprint_outside_bay",
            floor_value,
            frame=frame,
            transform=transform,
            bounding_box=bbox,
            clearance_m=float(clearance),
            footprint_inside_bay=False,
            footprint_corners=tuple(corners),
        )
    if float(clearance) + tolerance < floor_value:
        return BoundaryFloorGuard.fail(
            "boundary_below_floor",
            floor_value,
            frame=frame,
            transform=transform,
            bounding_box=bbox,
            clearance_m=float(clearance),
            footprint_inside_bay=True,
            footprint_corners=tuple(corners),
        )
    return BoundaryFloorGuard(
        triggered=False,
        reason="ok",
        floor_m=floor_value,
        clearance_m=float(clearance),
        footprint_inside_bay=True,
        footprint_corners=tuple(corners),
        frame=frame,
        transform=transform,
        bounding_box=bbox,
    )


def _straight_path(
    x: float, y: float, yaw: float, distance: float, *, reverse: bool
) -> tuple[tuple[float, float], ...]:
    sign = -1.0 if reverse else 1.0
    return (
        (x, y),
        (x + sign * distance * math.cos(yaw), y + sign * distance * math.sin(yaw)),
    )


def terminal_phase_plan(
    route: EntryRoute,
    measurement: EntryMeasurement,
    phase: str,
    *,
    config: TerminalCorrectionConfig | None = None,
) -> TerminalPhasePlan:
    if not isinstance(route, EntryRoute):
        raise TypeError("route must be an EntryRoute")
    if not isinstance(measurement, EntryMeasurement):
        raise TypeError("measurement must be an EntryMeasurement")
    if phase not in TerminalPhase.ALL:
        raise ValueError(f"unknown terminal phase {phase!r}")
    config = config or TerminalCorrectionConfig()
    target_heading = route.target_heading_rad
    slot_x, slot_y = route.target_pose
    x, y, yaw = measurement.x, measurement.y, measurement.yaw_rad
    if phase == TerminalPhase.REVERSE_ALIGN:
        max_distance = config.reverse_max_distance_m
        speed_cap = config.reverse_speed_cap_mps
        max_sim = config.reverse_max_sim_seconds
        reverse = True
        target_x = x - 0.6 * math.cos(yaw)
        target_y = y - 0.6 * math.sin(yaw)
    else:
        max_distance = config.forward_max_distance_m
        speed_cap = config.forward_speed_cap_mps
        max_sim = config.forward_max_sim_seconds
        reverse = False
        target_x = slot_x
        target_y = slot_y
    points = _straight_path(
        x, y, yaw, max_distance if phase == TerminalPhase.REVERSE_ALIGN else max(
            math.hypot(slot_x - x, slot_y - y), 0.30
        ),
        reverse=reverse,
    )
    return TerminalPhasePlan(
        phase=phase,
        target_x=target_x,
        target_y=target_y,
        target_heading_rad=target_heading,
        max_distance_m=max_distance,
        speed_cap_mps=speed_cap,
        max_sim_seconds=max_sim,
        reverse=reverse,
        start_pose=(x, y, yaw),
        points=points,
    )


def terminal_phase_command(
    plan: TerminalPhasePlan,
    *,
    x: float,
    y: float,
    yaw_rad: float,
    speed_mps: float,
    travelled_m: float,
    sim_seconds: float,
    config: TerminalCorrectionConfig | None = None,
) -> TerminalCommand:
    if not isinstance(plan, TerminalPhasePlan):
        raise TypeError("plan must be a TerminalPhasePlan")
    config = config or TerminalCorrectionConfig()
    for name, value in (
        ("x", x),
        ("y", y),
        ("yaw_rad", yaw_rad),
        ("speed_mps", speed_mps),
        ("travelled_m", travelled_m),
        ("sim_seconds", sim_seconds),
    ):
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
    if speed_mps < 0.0 or travelled_m < 0.0 or sim_seconds < 0.0:
        raise ValueError("speed/travel/time must be non-negative")
    heading_error = math.degrees(wrap_angle(yaw_rad - plan.target_heading_rad))
    distance_slot = math.hypot(x - plan.target_x, y - plan.target_y)
    if travelled_m >= plan.max_distance_m:
        return TerminalCommand(
            ControlCommand(0.0, 1.0, 0.0), plan.reverse, True,
            "distance_limit", heading_error, distance_slot,
        )
    if sim_seconds >= plan.max_sim_seconds:
        return TerminalCommand(
            ControlCommand(0.0, 1.0, 0.0), plan.reverse, True,
            "time_limit", heading_error, distance_slot,
        )
    if plan.phase == TerminalPhase.REVERSE_ALIGN:
        if abs(heading_error) <= config.reverse_stop_heading_deg:
            return TerminalCommand(
                ControlCommand(0.0, 1.0, 0.0), True, True,
                "heading_aligned", heading_error, distance_slot,
            )
        steer = max(-0.6, min(0.6, 3.0 * math.radians(heading_error)))
        if speed_mps < plan.speed_cap_mps:
            command = ControlCommand(0.45, 0.0, steer)
        else:
            command = ControlCommand(0.0, 0.25, steer)
        return TerminalCommand(
            command, True, False, "driving", heading_error, distance_slot
        )
    if (
        distance_slot <= config.forward_stop_distance_m
        and abs(heading_error) <= config.forward_stop_heading_deg
    ):
        return TerminalCommand(
            ControlCommand(0.0, 1.0, 0.0), False, True,
            "slot_aligned", heading_error, distance_slot,
        )
    if x <= plan.target_x + 0.02:
        return TerminalCommand(
            ControlCommand(0.0, 1.0, 0.0), False, True,
            "slot_x_reached", heading_error, distance_slot,
        )
    steer = max(-0.5, min(0.5, -2.0 * math.radians(heading_error)))
    if speed_mps < plan.speed_cap_mps:
        command = ControlCommand(0.45, 0.0, steer)
    else:
        command = ControlCommand(0.0, 0.25, steer)
    return TerminalCommand(
        command, False, False, "driving", heading_error, distance_slot
    )


def terminal_phase_improved(
    phase: str,
    *,
    before: EntryMeasurement,
    after: EntryMeasurement,
    route: EntryRoute,
    config: TerminalCorrectionConfig | None = None,
) -> tuple[bool, tuple[str, ...]]:
    if phase not in TerminalPhase.ALL:
        raise ValueError(f"unknown terminal phase {phase!r}")
    if not isinstance(before, EntryMeasurement) or not isinstance(after, EntryMeasurement):
        raise TypeError("before/after must be EntryMeasurements")
    config = config or TerminalCorrectionConfig()
    reasons: list[str] = []
    if not terminal_reference_in_box(after.x, after.y, config):
        reasons.append("terminal_reference_outside_box")
    if not terminal_footprint_in_buffer(after.footprint_corners, route, config):
        reasons.append("terminal_footprint_outside_buffer")
    if (
        after.obstacle_clearance_m is not None
        and after.obstacle_clearance_m < config.obstacle_clearance_m
    ):
        reasons.append("terminal_obstacle_clearance")
    if after.collision_count:
        reasons.append("terminal_collision")
    if not after.stopped or after.speed_mps >= route.tolerances.stop_speed_mps:
        reasons.append("terminal_not_stopped")
    if phase == TerminalPhase.REVERSE_ALIGN:
        if abs(after.heading_error_deg) > abs(before.heading_error_deg) - 0.2:
            reasons.append("terminal_reverse_did_not_reduce_heading")
    else:
        if abs(after.heading_error_deg) > abs(before.heading_error_deg) + 0.5:
            reasons.append("terminal_forward_heading_worsened")
        if (
            after.distance_to_target_m > before.distance_to_target_m - 0.005
            and after.distance_to_target_m > config.forward_stop_distance_m
        ):
            reasons.append("terminal_forward_did_not_reduce_distance")
    return (not reasons, tuple(reasons))
