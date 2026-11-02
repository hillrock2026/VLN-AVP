"""Pure parking-path geometry checks.

These helpers answer a narrow question before a parking controller is written:
does a candidate centreline fit the vehicle's steering limit, and does its
swept footprint stay clear of measured static collision points? They are
analysis tools, not a safety certification and not a runtime replacement for
the existing forward/floor safety gate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .route_control import point_at_s

__all__ = [
    "Footprint",
    "point_in_polygon",
    "turn_metrics",
    "path_curvature_at_s",
    "point_to_segment_distance",
    "path_clearance",
    "footprint_clearance",
    "footprint_polygon_clearance",
    "evaluate_path",
]


def _finite(value: object, name: str) -> float:
    if type(value) is not int and type(value) is not float:
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
    return float(value)


def _points(points: Sequence[Sequence[float]], name: str) -> tuple[tuple[float, float], ...]:
    try:
        raw = tuple(points)
    except TypeError:
        raise TypeError(f"{name} must be an iterable of (x, y) pairs") from None
    if len(raw) < 2:
        raise ValueError(f"{name} needs at least two points")
    checked: list[tuple[float, float]] = []
    for point in raw:
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            raise ValueError(f"each {name} point must be an (x, y) pair")
        checked.append((_finite(point[0], f"{name} x"), _finite(point[1], f"{name} y")))
    return tuple(checked)


def _wrap(angle: float) -> float:
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def point_in_polygon(x: float, y: float, polygon: Sequence[Sequence[float]]) -> bool:
    """Even-odd rule test; boundary points are not guaranteed to be inside."""

    x = _finite(x, "x")
    y = _finite(y, "y")
    points = _points(polygon, "polygon")
    inside = False
    count = len(points)
    for index in range(count):
        x0, y0 = points[index]
        x1, y1 = points[(index + 1) % count]
        if (y0 > y) != (y1 > y):
            x_cross = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < x_cross:
                inside = not inside
    return inside


@dataclass(frozen=True)
class Footprint:
    """Axis-aligned body half-extents plus the front safety margin."""

    half_length: float
    half_width: float
    front_margin: float = 0.3

    def __post_init__(self) -> None:
        object.__setattr__(self, "half_length", _finite(self.half_length, "half_length"))
        object.__setattr__(self, "half_width", _finite(self.half_width, "half_width"))
        object.__setattr__(self, "front_margin", _finite(self.front_margin, "front_margin"))
        if self.half_length <= 0.0 or self.half_width <= 0.0:
            raise ValueError("footprint half-extents must be positive")
        if self.front_margin < 0.0:
            raise ValueError("front_margin must be non-negative")

    @property
    def length(self) -> float:
        return 2.0 * self.half_length

    @property
    def width(self) -> float:
        return 2.0 * self.half_width

    def corners(self, x: float, y: float, yaw_rad: float) -> tuple[tuple[float, float], ...]:
        x = _finite(x, "x")
        y = _finite(y, "y")
        yaw = _finite(yaw_rad, "yaw_rad")
        c, s = math.cos(yaw), math.sin(yaw)
        local = (
            (self.half_length, self.half_width),
            (self.half_length, -self.half_width),
            (-self.half_length, -self.half_width),
            (-self.half_length, self.half_width),
        )
        return tuple((x + lx * c - ly * s, y + lx * s + ly * c) for lx, ly in local)

    def front_center(self, x: float, y: float, yaw_rad: float) -> tuple[float, float]:
        x = _finite(x, "x")
        y = _finite(y, "y")
        yaw = _finite(yaw_rad, "yaw_rad")
        reach = self.half_length + self.front_margin
        return (x + reach * math.cos(yaw), y + reach * math.sin(yaw))

    def local_point(
        self, x: float, y: float, yaw_rad: float, px: float, py: float
    ) -> tuple[float, float]:
        """Return a world point in the body frame (forward, left)."""

        x = _finite(x, "x")
        y = _finite(y, "y")
        yaw = _finite(yaw_rad, "yaw_rad")
        px = _finite(px, "px")
        py = _finite(py, "py")
        dx, dy = px - x, py - y
        c, s = math.cos(yaw), math.sin(yaw)
        return (dx * c + dy * s, -dx * s + dy * c)

    def contains(
        self, x: float, y: float, yaw_rad: float, px: float, py: float
    ) -> bool:
        local_x, local_y = self.local_point(x, y, yaw_rad, px, py)
        return abs(local_x) <= self.half_length and abs(local_y) <= self.half_width

    def to_metadata(self) -> dict:
        return {
            "half_length_m": round(self.half_length, 3),
            "half_width_m": round(self.half_width, 3),
            "length_m": round(self.length, 3),
            "width_m": round(self.width, 3),
            "front_margin_m": round(self.front_margin, 3),
        }


def _circumradius(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    ax, ay = a
    bx, by = b
    cx, cy = c
    denominator = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(denominator) < 1e-12:
        return float("inf")
    ux = (
        (ax * ax + ay * ay) * (by - cy)
        + (bx * bx + by * by) * (cy - ay)
        + (cx * cx + cy * cy) * (ay - by)
    ) / denominator
    uy = (
        (ax * ax + ay * ay) * (cx - bx)
        + (bx * bx + by * by) * (ax - cx)
        + (cx * cx + cy * cy) * (bx - ax)
    ) / denominator
    return math.hypot(ax - ux, ay - uy)


def turn_metrics(
    points: Sequence[Sequence[float]],
    *,
    wheelbase: float = 3.0,
    max_steer_rad: float = math.radians(45.0),
) -> dict:
    """Return the tightest circumradius and the steering it would require.

    The radius is computed at each interior polyline vertex from the three
    adjacent samples. This is a conservative, resolution-dependent check: a
    densely sampled smooth arc gives a smaller radius than a coarse chord.
    """

    wheelbase = _finite(wheelbase, "wheelbase")
    max_steer_rad = _finite(max_steer_rad, "max_steer_rad")
    if wheelbase <= 0.0:
        raise ValueError("wheelbase must be positive")
    if not 0.0 < max_steer_rad < math.pi / 2.0:
        raise ValueError("max_steer_rad must be in (0, pi/2)")
    path = _points(points, "path")
    min_radius = float("inf")
    max_required = 0.0
    max_turn_deg = 0.0
    vertices = []
    for index in range(1, len(path) - 1):
        previous, current, following = path[index - 1], path[index], path[index + 1]
        incoming = math.atan2(current[1] - previous[1], current[0] - previous[0])
        outgoing = math.atan2(following[1] - current[1], following[0] - current[0])
        turn = abs(_wrap(outgoing - incoming))
        radius = _circumradius(previous, current, following)
        required = 0.0 if math.isinf(radius) else math.atan(wheelbase / radius)
        if math.isfinite(radius):
            min_radius = min(min_radius, radius)
        max_required = max(max_required, required)
        max_turn_deg = max(max_turn_deg, math.degrees(turn))
        vertices.append(
            {
                "index": index,
                "x": round(current[0], 3),
                "y": round(current[1], 3),
                "turn_deg": round(math.degrees(turn), 3),
                "radius_m": None if math.isinf(radius) else round(radius, 3),
                "required_steer_deg": round(math.degrees(required), 3),
            }
        )
    limit_radius = wheelbase / math.tan(max_steer_rad)
    return {
        "wheelbase_m": round(wheelbase, 3),
        "max_steer_deg": round(math.degrees(max_steer_rad), 3),
        "limit_radius_m": round(limit_radius, 3),
        "min_radius_m": None if math.isinf(min_radius) else round(min_radius, 3),
        "max_required_steer_deg": round(math.degrees(max_required), 3),
        "max_turn_deg": round(max_turn_deg, 3),
        "kinematically_feasible": max_required <= max_steer_rad + 1e-9,
        "vertices": vertices,
    }


def path_curvature_at_s(
    points: Sequence[Sequence[float]],
    cumulative: Sequence[float],
    s: float,
    *,
    delta_m: float = 0.5,
) -> float:
    """Signed curvature at an arc-length position (right turn is negative)."""

    path = _points(points, "path")
    if len(cumulative) != len(path):
        raise ValueError("cumulative lengths do not match the path")
    s = _finite(s, "s")
    delta_m = _finite(delta_m, "delta_m")
    if delta_m <= 0.0:
        raise ValueError("delta_m must be positive")
    s = max(0.0, min(float(cumulative[-1]), s))
    p0 = point_at_s(path, cumulative, max(0.0, s - delta_m))
    p1 = point_at_s(path, cumulative, s)
    p2 = point_at_s(path, cumulative, min(float(cumulative[-1]), s + delta_m))
    a = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    b = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if a <= 1e-9 or a < 0.5 * delta_m:
        # Near the path start the backward sample is too short (or collapses
        # onto s), which makes the circumradius ill-conditioned. Use a forward
        # window so the first control steps see the real curvature.
        p0 = point_at_s(path, cumulative, s)
        p1 = point_at_s(
            path, cumulative, min(float(cumulative[-1]), s + delta_m)
        )
        p2 = point_at_s(
            path, cumulative, min(float(cumulative[-1]), s + 2.0 * delta_m)
        )
        a = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        b = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if a <= 1e-9 or b <= 1e-9:
        return 0.0
    h1 = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    h2 = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    turn = _wrap(h2 - h1)
    if abs(turn) <= 1e-9:
        return 0.0
    radius = _circumradius(p0, p1, p2)
    if not math.isfinite(radius) or radius <= 1e-9:
        return 0.0
    return math.copysign(1.0 / radius, turn)


def point_to_segment_distance(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    px = _finite(px, "px")
    py = _finite(py, "py")
    ax = _finite(ax, "ax")
    ay = _finite(ay, "ay")
    bx = _finite(bx, "bx")
    by = _finite(by, "by")
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _obstacles(points: Sequence[Sequence[float]]) -> tuple[tuple[float, float], ...]:
    try:
        raw = tuple(points)
    except TypeError:
        raise TypeError("obstacle points must be an iterable of (x, y) pairs") from None
    checked: list[tuple[float, float]] = []
    for point in raw:
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            raise ValueError("each obstacle point must be an (x, y) pair")
        checked.append((_finite(point[0], "obstacle x"), _finite(point[1], "obstacle y")))
    return tuple(checked)


def path_clearance(
    points: Sequence[Sequence[float]],
    footprint: Footprint,
    obstacle_points: Sequence[Sequence[float]],
    *,
    sample_step_m: float = 0.25,
) -> dict:
    """Minimum obstacle-to-footprint-edge distance over sampled path poses.

    Obstacles are treated as points. The result is only as good as the
    obstacle sample set; it is not a substitute for a full swept-volume check.
    """

    if not isinstance(footprint, Footprint):
        raise TypeError("footprint must be a Footprint")
    sample_step_m = _finite(sample_step_m, "sample_step_m")
    if sample_step_m <= 0.0:
        raise ValueError("sample_step_m must be positive")
    path = _points(points, "path")
    obstacles = _obstacles(obstacle_points)
    if not obstacles:
        return {
            "min_clearance_m": None,
            "worst_pose": None,
            "sample_count": 0,
            "obstacle_count": 0,
            "sample_step_m": round(sample_step_m, 3),
        }
    best = float("inf")
    worst = None
    samples = 0
    for index in range(1, len(path)):
        ax, ay = path[index - 1]
        bx, by = path[index]
        heading = math.atan2(by - ay, bx - ax)
        segment_length = math.hypot(bx - ax, by - ay)
        count = max(1, int(math.ceil(segment_length / sample_step_m)))
        for step in range(count + 1):
            t = step / count
            x = ax + (bx - ax) * t
            y = ay + (by - ay) * t
            corners = footprint.corners(x, y, heading)
            samples += 1
            for ox, oy in obstacles:
                for edge in range(4):
                    a = corners[edge]
                    b = corners[(edge + 1) % 4]
                    distance = point_to_segment_distance(ox, oy, a[0], a[1], b[0], b[1])
                    if distance < best:
                        best = distance
                        worst = {
                            "x": round(x, 3),
                            "y": round(y, 3),
                            "yaw_deg": round(math.degrees(heading), 3),
                            "segment_index": index,
                            "t": round(t, 3),
                            "obstacle": [round(ox, 3), round(oy, 3)],
                        }
    return {
        "min_clearance_m": round(best, 3),
        "worst_pose": worst,
        "sample_count": samples,
        "obstacle_count": len(obstacles),
        "sample_step_m": round(sample_step_m, 3),
    }


def footprint_clearance(
    x: float,
    y: float,
    yaw_rad: float,
    footprint: Footprint,
    obstacle_points: Sequence[Sequence[float]],
) -> dict:
    """Minimum obstacle-to-footprint-edge distance at one pose."""

    if not isinstance(footprint, Footprint):
        raise TypeError("footprint must be a Footprint")
    corners = footprint.corners(x, y, yaw_rad)
    obstacles = _obstacles(obstacle_points)
    if not obstacles:
        return {"min_clearance_m": None, "obstacle_count": 0, "pose": None}
    best = float("inf")
    worst = None
    for ox, oy in obstacles:
        for edge in range(4):
            a = corners[edge]
            b = corners[(edge + 1) % 4]
            distance = point_to_segment_distance(ox, oy, a[0], a[1], b[0], b[1])
            if distance < best:
                best = distance
                worst = [round(ox, 3), round(oy, 3)]
    return {
        "min_clearance_m": round(best, 3),
        "obstacle_count": len(obstacles),
        "pose": {
            "x": round(float(x), 3),
            "y": round(float(y), 3),
            "yaw_deg": round(math.degrees(float(yaw_rad)), 3),
        },
        "worst_obstacle": worst,
    }


def _orientation(
    ax: float, ay: float, bx: float, by: float, cx: float, cy: float
) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _segments_intersect(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
) -> bool:
    o1 = _orientation(ax, ay, bx, by, cx, cy)
    o2 = _orientation(ax, ay, bx, by, dx, dy)
    o3 = _orientation(cx, cy, dx, dy, ax, ay)
    o4 = _orientation(cx, cy, dx, dy, bx, by)
    return (o1 * o2 < 0.0) and (o3 * o4 < 0.0)


def segment_to_segment_distance(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
) -> float:
    if _segments_intersect(ax, ay, bx, by, cx, cy, dx, dy):
        return 0.0
    return min(
        point_to_segment_distance(ax, ay, cx, cy, dx, dy),
        point_to_segment_distance(bx, by, cx, cy, dx, dy),
        point_to_segment_distance(cx, cy, ax, ay, bx, by),
        point_to_segment_distance(dx, dy, ax, ay, bx, by),
    )


def footprint_polygon_clearance(
    x: float,
    y: float,
    yaw_rad: float,
    footprint: Footprint,
    polygon_points: Sequence[Sequence[float]],
) -> dict:
    """Minimum edge-to-edge distance between the footprint and a boundary.

    This is the correct check for a closed painted bay boundary, unlike
    ``footprint_clearance`` which treats the boundary as point obstacles.
    """

    if not isinstance(footprint, Footprint):
        raise TypeError("footprint must be a Footprint")
    polygon = _obstacles(polygon_points)
    if len(polygon) < 3:
        raise ValueError("boundary polygon needs at least three points")
    if polygon[0] != polygon[-1]:
        polygon = polygon + (polygon[0],)
    corners = footprint.corners(x, y, yaw_rad)
    best = float("inf")
    worst = None
    for edge in range(4):
        a = corners[edge]
        b = corners[(edge + 1) % 4]
        for index in range(1, len(polygon)):
            c = polygon[index - 1]
            d = polygon[index]
            distance = segment_to_segment_distance(
                a[0], a[1], b[0], b[1], c[0], c[1], d[0], d[1]
            )
            if distance < best:
                best = distance
                worst = {
                    "footprint_edge": edge,
                    "boundary_edge": index - 1,
                    "boundary_points": [list(c), list(d)],
                }
    return {
        "min_clearance_m": round(best, 3),
        "pose": {
            "x": round(float(x), 3),
            "y": round(float(y), 3),
            "yaw_deg": round(math.degrees(float(yaw_rad)), 3),
        },
        "worst": worst,
    }


def evaluate_path(
    points: Sequence[Sequence[float]],
    footprint: Footprint,
    obstacle_points: Sequence[Sequence[float]],
    *,
    wheelbase: float = 3.0,
    max_steer_rad: float = math.radians(45.0),
    required_clearance_m: float = 0.2,
    sample_step_m: float = 0.25,
) -> dict:
    """Combine steering-limit and sampled-clearance checks for one path."""

    required_clearance_m = _finite(required_clearance_m, "required_clearance_m")
    if required_clearance_m < 0.0:
        raise ValueError("required_clearance_m must be non-negative")
    turn = turn_metrics(points, wheelbase=wheelbase, max_steer_rad=max_steer_rad)
    clearance = path_clearance(
        points, footprint, obstacle_points, sample_step_m=sample_step_m
    )
    reasons = []
    if not turn["kinematically_feasible"]:
        reasons.append(
            "required_steer_exceeds_limit: "
            f"{turn['max_required_steer_deg']} deg > {turn['max_steer_deg']} deg"
        )
    minimum = clearance["min_clearance_m"]
    if minimum is None:
        reasons.append("clearance_not_measured: no obstacle points")
    elif minimum < required_clearance_m:
        reasons.append(
            f"clearance_below_required: {minimum} m < {required_clearance_m} m"
        )
    return {
        "feasible": not reasons,
        "reasons": reasons,
        "required_clearance_m": round(required_clearance_m, 3),
        "turn": turn,
        "clearance": clearance,
        "footprint": footprint.to_metadata(),
    }
