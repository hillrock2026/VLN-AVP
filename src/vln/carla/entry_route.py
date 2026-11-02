"""Segmenting and geometric validation for the Entry route.

The route itself is built from the validated parking graph by
:mod:`vln.carla.entry_scene`. This module only answers geometric questions:

* split a route into bounded segments that each carry a target pose;
* check steering feasibility;
* sweep the rotated vehicle footprint along the route and check static
  obstacle clearance and the approved Entry corridor;
* check that the terminal footprint is fully inside the painted bay polygon.

It is pure and imports no CARLA package.
"""

from __future__ import annotations

import math
from typing import Sequence

from vln.carla.parking_geometry import (
    Footprint,
    footprint_clearance,
    footprint_polygon_clearance,
    turn_metrics,
)
from vln.parking.entry import (
    EntryGeometryError,
    EntryRoute,
    EntryRouteSegment,
    EntryTolerances,
    entry_route_hash,
)

__all__ = [
    "build_segments",
    "validate_entry_route",
    "route_geometry_audit",
    "ENTRY_STEP_M",
]

ENTRY_STEP_M = 0.05


def _tangent_at(
    points: Sequence[Sequence[float]],
    cumulative: Sequence[float],
    s: float,
    target_heading_rad: float,
) -> float:
    if s >= float(cumulative[-1]) - 1e-9:
        return target_heading_rad
    s = max(0.0, min(float(cumulative[-1]), float(s)))
    for index in range(1, len(cumulative)):
        if s <= cumulative[index]:
            p0 = points[index - 1]
            p1 = points[index]
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            if math.hypot(dx, dy) <= 1e-9:
                continue
            return math.atan2(dy, dx)
    return target_heading_rad


def build_segments(
    points: Sequence[Sequence[float]],
    cumulative: Sequence[float],
    *,
    max_segment_distance_m: float,
    target_heading_rad: float,
) -> tuple[EntryRouteSegment, ...]:
    """Split a route into contiguous bounded segments ending on route poses."""

    if len(points) < 2 or len(cumulative) != len(points):
        raise EntryGeometryError("route points/cumulative are inconsistent")
    if max_segment_distance_m <= 0.0:
        raise ValueError("max_segment_distance_m must be positive")
    total = float(cumulative[-1])
    if total <= 0.0:
        raise EntryGeometryError("route has zero length")
    segments: list[EntryRouteSegment] = []
    start = 0.0
    index = 1
    while start < total - 1e-9:
        end = min(total, start + max_segment_distance_m)
        if total - end < 0.10:
            end = total
        # target point
        for i in range(1, len(cumulative)):
            if end <= cumulative[i] + 1e-9:
                span = cumulative[i] - cumulative[i - 1]
                t = 0.0 if span <= 1e-9 else (end - cumulative[i - 1]) / span
                a = points[i - 1]
                b = points[i]
                target_x = a[0] + (b[0] - a[0]) * t
                target_y = a[1] + (b[1] - a[1]) * t
                break
        else:
            target_x, target_y = points[-1]
        heading = _tangent_at(
            points, cumulative, end, target_heading_rad
        )
        segments.append(
            EntryRouteSegment(
                index=index,
                start_s=start,
                end_s=end,
                length_m=end - start,
                target_x=target_x,
                target_y=target_y,
                target_heading_rad=heading,
                phase="ARC_ENTRY" if end <= total - 1.95 else "FINAL_STRAIGHT",
            )
        )
        start = end
        index += 1
    return tuple(segments)


def _pose_at(
    points: Sequence[Sequence[float]],
    cumulative: Sequence[float],
    s: float,
    target_heading_rad: float,
) -> tuple[float, float, float]:
    s = max(0.0, min(float(cumulative[-1]), float(s)))
    for index in range(1, len(cumulative)):
        if s <= cumulative[index]:
            span = cumulative[index] - cumulative[index - 1]
            t = 0.0 if span <= 1e-9 else (s - cumulative[index - 1]) / span
            a = points[index - 1]
            b = points[index]
            return (
                a[0] + (b[0] - a[0]) * t,
                a[1] + (b[1] - a[1]) * t,
                _tangent_at(points, cumulative, s, target_heading_rad),
            )
    return (points[-1][0], points[-1][1], target_heading_rad)


def _point_in_polygon(x: float, y: float, polygon: Sequence[Sequence[float]]) -> bool:
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


def _distance_to_polyline(
    x: float, y: float, points: Sequence[Sequence[float]]
) -> float:
    from vln.carla.parking_geometry import point_to_segment_distance

    return min(
        point_to_segment_distance(
            x, y,
            points[index - 1][0], points[index - 1][1],
            points[index][0], points[index][1],
        )
        for index in range(1, len(points))
    )


def route_geometry_audit(route: EntryRoute) -> dict:
    """Sweep the rotated footprint along the route and report every check."""

    if not isinstance(route, EntryRoute):
        raise TypeError("route must be an EntryRoute")
    tol = route.tolerances
    turn = turn_metrics(
        route.points, wheelbase=3.0, max_steer_rad=math.radians(45.0)
    )
    reasons: list[str] = []
    if not turn["kinematically_feasible"]:
        reasons.append(
            f"required_steer_exceeds_limit:{turn['max_required_steer_deg']}"
        )
    min_obstacle = None
    min_boundary_at_terminal = None
    corridor_violations = 0
    samples = 0
    last_pose = None
    sample_positions = [
        min(route.length_m, step * ENTRY_STEP_M)
        for step in range(int(math.floor(route.length_m / ENTRY_STEP_M)) + 1)
    ]
    if sample_positions[-1] < route.length_m - 1e-9:
        sample_positions.append(route.length_m)
    for s in sample_positions:
        pose = _pose_at(
            route.points, route.cumulative, s, route.target_heading_rad
        )
        x, y, yaw = pose
        samples += 1
        last_pose = pose
        if route.obstacle_points:
            clearance = footprint_clearance(
                x, y, yaw, route.footprint, route.obstacle_points
            )["min_clearance_m"]
            if clearance is not None and (
                min_obstacle is None or clearance < min_obstacle
            ):
                min_obstacle = clearance
            if clearance is not None and clearance < tol.obstacle_clearance_m:
                reasons.append(f"obstacle_clearance_at_s={s:.2f}")
        corners = route.footprint.corners(x, y, yaw)
        for px, py in corners:
            if _point_in_polygon(px, py, route.bay_polygon):
                continue
            if (
                _distance_to_polyline(px, py, route.points)
                > tol.corridor_half_width_m
                and not route.point_in_start_cap(px, py)
            ):
                corridor_violations += 1
    end_x, end_y, end_yaw = last_pose
    end_corners = route.footprint.corners(end_x, end_y, end_yaw)
    terminal_inside = all(
        _point_in_polygon(px, py, route.bay_polygon) for px, py in end_corners
    )
    terminal_clearance = footprint_polygon_clearance(
        end_x, end_y, end_yaw, route.footprint, route.bay_polygon
    )["min_clearance_m"]
    min_boundary_at_terminal = terminal_clearance
    if not terminal_inside:
        reasons.append("terminal_footprint_not_inside_bay")
    if terminal_clearance is None or terminal_clearance < tol.boundary_clearance_m:
        reasons.append("terminal_boundary_clearance")
    if corridor_violations:
        reasons.append(f"corridor_violations={corridor_violations}")
    return {
        "ok": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "samples": samples,
        "route_length_m": round(route.length_m, 4),
        "turn": turn,
        "min_obstacle_clearance_m": None
        if min_obstacle is None
        else round(min_obstacle, 4),
        "terminal_pose": {
            "x": round(end_x, 4),
            "y": round(end_y, 4),
            "yaw_deg": round(math.degrees(end_yaw), 4),
        },
        "terminal_footprint_inside_bay": terminal_inside,
        "terminal_boundary_clearance_m": None
        if min_boundary_at_terminal is None
        else round(min_boundary_at_terminal, 4),
        "corridor_violations": corridor_violations,
        "corridor_half_width_m": tol.corridor_half_width_m,
        "obstacle_guard_m": tol.obstacle_clearance_m,
    }


def validate_entry_route(route: EntryRoute) -> None:
    """Raise :class:`EntryGeometryError` if the route cannot be accepted."""

    audit = route_geometry_audit(route)
    if not audit["ok"]:
        raise EntryGeometryError(
            "entry route rejected: " + ", ".join(audit["reasons"])
        )
