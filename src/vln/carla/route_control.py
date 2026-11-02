"""Pure-Python route following, safety verdicts and bounded-segment monitoring.

These are the control rules 01B validated on the real map. They are kept free
of the ``carla`` Python package so they can be unit-tested and so 01B and 01D
cannot drift into two slightly different controllers:

* :func:`pure_pursuit_command` is the exact geometric controller from 01B
  (same lookahead, effective steering limit, speed caps and throttle/brake
  law), returning plain numbers instead of a ``carla.VehicleControl``;
* :func:`forward_safety_verdict` is 01B's forward-ray + floor-probe decision;
* :class:`SegmentMonitor` is 01B's arrival / obstacle / off-route / stuck /
  timeout state machine, with an explicit, testable ``update`` method.

The model never produces any value in this module. A selected route is the
only input that changes, and throttle/brake/steer always come from the
controller below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

__all__ = [
    "STOP_SUCCESS",
    "STOP_OBSTACLE",
    "STOP_STUCK",
    "STOP_OFF_ROUTE",
    "STOP_TIMEOUT",
    "ControlCommand",
    "PurePursuitInfo",
    "SafetyVerdict",
    "SegmentMonitor",
    "clamp",
    "wrap_angle",
    "cumulative_lengths",
    "point_at_s",
    "project_to_path",
    "forward_stop_threshold",
    "forward_safety_verdict",
    "safety_stop_detail",
    "build_stop_diagnostics",
    "pure_pursuit_command",
    "classify_relative_turn",
]

STOP_SUCCESS = "success"
STOP_OBSTACLE = "obstacle"
STOP_STUCK = "stuck"
STOP_OFF_ROUTE = "off_route"
STOP_TIMEOUT = "timeout"

#: Defaults calibrated in 01B for this map and vehicle.
WHEELBASE = 3.0
MAX_STEER_EFF = math.radians(45.0)
LOOKAHEAD_BASE = 2.5
LOOKAHEAD_GAIN = 0.5
LOOKAHEAD_MIN = 3.0
LOOKAHEAD_MAX = 5.5
MAX_GROUND_Z = 5.95


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def wrap_angle(angle: float) -> float:
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def _checked_points(points: Sequence[Sequence[float]]) -> tuple[tuple[float, float], ...]:
    checked: list[tuple[float, float]] = []
    for point in points:
        if len(point) != 2:
            raise ValueError("each path point must be an (x, y) pair")
        x, y = point
        if type(x) is not int and type(x) is not float:
            raise ValueError("path x must be a number")
        if type(y) is not int and type(y) is not float:
            raise ValueError("path y must be a number")
        if not math.isfinite(float(x)) or not math.isfinite(float(y)):
            raise ValueError("path coordinates must be finite")
        checked.append((float(x), float(y)))
    if len(checked) < 2:
        raise ValueError("a path needs at least two points")
    return tuple(checked)


def cumulative_lengths(points: Sequence[Sequence[float]]) -> list[float]:
    checked = _checked_points(points)
    cumulative = [0.0]
    for index in range(1, len(checked)):
        cumulative.append(
            cumulative[-1]
            + math.hypot(
                checked[index][0] - checked[index - 1][0],
                checked[index][1] - checked[index - 1][1],
            )
        )
    return cumulative


def point_at_s(
    points: Sequence[Sequence[float]], cumulative: Sequence[float], s: float
) -> tuple[float, float]:
    checked = _checked_points(points)
    if len(cumulative) != len(checked):
        raise ValueError("cumulative lengths do not match the path")
    s = clamp(float(s), 0.0, float(cumulative[-1]))
    for index in range(1, len(cumulative)):
        if s <= cumulative[index]:
            segment = cumulative[index] - cumulative[index - 1]
            t = 0.0 if segment <= 1e-9 else (s - cumulative[index - 1]) / segment
            return (
                checked[index - 1][0] + (checked[index][0] - checked[index - 1][0]) * t,
                checked[index - 1][1] + (checked[index][1] - checked[index - 1][1]) * t,
            )
    return checked[-1]


def project_to_path(
    points: Sequence[Sequence[float]],
    cumulative: Sequence[float],
    x: float,
    y: float,
    s_min: float = 0.0,
    *,
    window_m: float | None = None,
) -> tuple[float, float, float, float]:
    """Closest path point with arc length >= ``s_min``.

    Returns ``(s, px, py, distance)``. The projection is monotonic while the
    vehicle makes forward progress, so a temporary backward excursion cannot
    rewind the controller onto an earlier part of the route.

    ``window_m`` bounds the search to ``[s_min - 1, s_min + window_m]``. This
    is required for routes that return near their own start (for example a
    loop): without a window the globally closest point can be on the return
    leg, which makes the controller follow the wrong remaining path. Callers
    that start a fresh route pass ``s_min=0`` and a window; in-loop callers
    pass their previous progress. ``None`` keeps the previous global search.
    """

    checked = _checked_points(points)
    if len(cumulative) != len(checked):
        raise ValueError("cumulative lengths do not match the path")
    for value in (x, y, s_min):
        if type(value) is not int and type(value) is not float:
            raise ValueError("position and s_min must be numbers")
        if not math.isfinite(float(value)):
            raise ValueError("position and s_min must be finite")
    if window_m is not None:
        if type(window_m) not in (int, float):
            raise ValueError("window_m must be a number or None")
        if not math.isfinite(float(window_m)) or window_m <= 0:
            raise ValueError("window_m must be finite and positive")
    best: tuple[float, float, float, float] | None = None
    for index in range(1, len(checked)):
        ax, ay = checked[index - 1]
        bx, by = checked[index]
        dx, dy = bx - ax, by - ay
        segment_sq = dx * dx + dy * dy
        if segment_sq <= 1e-9:
            continue
        t = clamp(((x - ax) * dx + (y - ay) * dy) / segment_sq, 0.0, 1.0)
        px, py = ax + t * dx, ay + t * dy
        s = cumulative[index - 1] + t * math.sqrt(segment_sq)
        if s < s_min - 1.0:
            continue
        if window_m is not None and s > s_min + float(window_m):
            continue
        distance = math.hypot(x - px, y - py)
        if best is None or distance < best[3]:
            best = (s, px, py, distance)
    if best is None and window_m is not None:
        # Do not jump to the end of the path when the local window has no
        # candidate; report the current progress so the caller can stop.
        s = clamp(float(s_min), 0.0, float(cumulative[-1]))
        px, py = point_at_s(checked, cumulative, s)
        return (s, px, py, math.hypot(x - px, y - py))
    if best is None:
        return (
            float(cumulative[-1]),
            checked[-1][0],
            checked[-1][1],
            math.hypot(x - checked[-1][0], y - checked[-1][1]),
        )
    return best


def classify_relative_turn(
    relative_rad: float,
    *,
    straight_tolerance_deg: float = 15.0,
    turn_limit_deg: float = 150.0,
) -> str:
    """Classify a heading delta into STRAIGHT / LEFT / RIGHT / BEHIND.

    The deadband is symmetric and configuration-driven. A delta beyond
    ``turn_limit_deg`` is treated as BEHIND: the model vocabulary has no
    U-turn, and a reverse edge must never be selected by a lateral direction.
    """

    if type(relative_rad) is not int and type(relative_rad) is not float:
        raise ValueError("relative_rad must be a number")
    if not math.isfinite(float(relative_rad)):
        raise ValueError("relative_rad must be finite")
    straight = math.radians(float(straight_tolerance_deg))
    limit = math.radians(float(turn_limit_deg))
    if straight < 0 or limit <= straight or limit > math.pi:
        raise ValueError("turn thresholds are out of range")
    angle = wrap_angle(float(relative_rad))
    magnitude = abs(angle)
    if magnitude <= straight:
        return "STRAIGHT"
    if magnitude > limit:
        return "BEHIND"
    return "LEFT" if angle > 0 else "RIGHT"


def forward_stop_threshold(speed_mps: float) -> float:
    """01B's speed-dependent forward stop distance, capped at 8 m."""

    if type(speed_mps) is not int and type(speed_mps) is not float:
        raise ValueError("speed_mps must be a number")
    if not math.isfinite(float(speed_mps)) or speed_mps < 0:
        raise ValueError("speed_mps must be a finite non-negative number")
    return min(8.0, 3.0 + float(speed_mps))


@dataclass(frozen=True)
class SafetyVerdict:
    blocked: bool
    obstacle_hit: bool
    ground_bad: bool
    stop_distance_m: float
    min_hit_m: float | None
    ground_z: tuple[float | None, ...]

    def to_metadata(self) -> dict:
        return {
            "blocked": self.blocked,
            "obstacle_hit": self.obstacle_hit,
            "ground_bad": self.ground_bad,
            "stop_distance_m": round(self.stop_distance_m, 3),
            "min_hit_m": self.min_hit_m,
            "ground_z": list(self.ground_z),
        }


def forward_safety_verdict(
    *,
    min_hit_m: float | None,
    speed_mps: float,
    ground_z: Sequence[float | None],
    max_ground_z: float = MAX_GROUND_Z,
    stop_distance_m: float | None = None,
) -> SafetyVerdict:
    """Decide whether the measured forward corridor is unsafe to continue.

    ``min_hit_m`` is the nearest forward-ray hit, or ``None`` when clear.
    ``ground_z`` is the floor height at the 3/4/5 m probes; ``None`` means the
    ray hit nothing (a hole) and is unsafe. This is exactly 01B's rule.
    """

    if min_hit_m is not None:
        if type(min_hit_m) is not int and type(min_hit_m) is not float:
            raise ValueError("min_hit_m must be a number or None")
        if not math.isfinite(float(min_hit_m)) or min_hit_m < 0:
            raise ValueError("min_hit_m must be finite and non-negative")
    if stop_distance_m is None:
        stop_distance = forward_stop_threshold(speed_mps)
    else:
        if (
            type(stop_distance_m) not in (int, float)
            or not math.isfinite(float(stop_distance_m))
            or stop_distance_m <= 0
        ):
            raise ValueError(
                "stop_distance_m must be a finite positive number or None"
            )
        stop_distance = float(stop_distance_m)
    obstacle_hit = min_hit_m is not None and min_hit_m < stop_distance
    ground_bad = any(z is None or z > max_ground_z for z in ground_z)
    return SafetyVerdict(
        blocked=obstacle_hit or ground_bad,
        obstacle_hit=obstacle_hit,
        ground_bad=ground_bad,
        stop_distance_m=stop_distance,
        min_hit_m=None if min_hit_m is None else round(float(min_hit_m), 3),
        ground_z=tuple(ground_z),
    )


@dataclass(frozen=True)
class ControlCommand:
    """Throttle/brake/steer generated by the geometric controller."""

    throttle: float
    brake: float
    steer: float

    def to_metadata(self) -> dict:
        return {
            "throttle": round(self.throttle, 3),
            "brake": round(self.brake, 3),
            "steer": round(self.steer, 3),
            "source": "pure_pursuit_01b",
        }


@dataclass(frozen=True)
class PurePursuitInfo:
    lookahead_m: float
    target_x: float
    target_y: float
    alpha_deg: float
    steer: float
    v_target: float

    def to_metadata(self) -> dict:
        return {
            "lookahead_m": round(self.lookahead_m, 2),
            "target_x": round(self.target_x, 2),
            "target_y": round(self.target_y, 2),
            "alpha_deg": round(self.alpha_deg, 2),
            "steer": round(self.steer, 3),
            "v_target": round(self.v_target, 2),
        }


def pure_pursuit_command(
    *,
    x: float,
    y: float,
    yaw_rad: float,
    speed_mps: float,
    points: Sequence[Sequence[float]],
    cumulative: Sequence[float],
    s: float,
    distance_to_goal_m: float,
    wheelbase: float = WHEELBASE,
    max_steer_rad: float = MAX_STEER_EFF,
    lookahead_base: float = LOOKAHEAD_BASE,
    lookahead_gain: float = LOOKAHEAD_GAIN,
    lookahead_min: float = LOOKAHEAD_MIN,
    lookahead_max: float = LOOKAHEAD_MAX,
    goal_slowdown_distance_m: float = 6.0,
    goal_speed_mps: float = 1.8,
    speed_cap_mps: float | None = None,
) -> tuple[ControlCommand, PurePursuitInfo]:
    """01B's Pure Pursuit law over a route, returning plain numbers.

    The lookahead point, geometric steering, effective steering limit, speed
    schedule and throttle/brake law are reproduced exactly. ``yaw_rad`` is the
    CARLA yaw converted to radians; the returned ``steer`` is a normalized
    CARLA control value in ``[-0.9, 0.9]``. ``speed_cap_mps`` is an optional
    additional low-speed cap used by the parking controller; ``None`` keeps
    the original 01B behaviour.
    """

    for name, value in (
        ("x", x),
        ("y", y),
        ("yaw_rad", yaw_rad),
        ("speed_mps", speed_mps),
        ("s", s),
        ("distance_to_goal_m", distance_to_goal_m),
    ):
        if type(value) is not int and type(value) is not float:
            raise ValueError(f"{name} must be a number")
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
    if speed_mps < 0 or distance_to_goal_m < 0:
        raise ValueError("speed and distance_to_goal must be non-negative")
    if not wheelbase > 0 or not lookahead_max > 0 or not max_steer_rad > 0:
        raise ValueError("controller geometry must be positive")
    if speed_cap_mps is not None:
        if type(speed_cap_mps) is not int and type(speed_cap_mps) is not float:
            raise ValueError("speed_cap_mps must be a number or None")
        if not math.isfinite(float(speed_cap_mps)) or speed_cap_mps <= 0:
            raise ValueError("speed_cap_mps must be finite and positive")

    checked = _checked_points(points)
    if len(cumulative) != len(checked):
        raise ValueError("cumulative lengths do not match the path")
    speed = float(speed_mps)
    lookahead = clamp(
        lookahead_base + lookahead_gain * speed, lookahead_min, lookahead_max
    )
    target = point_at_s(checked, cumulative, min(float(cumulative[-1]), s + lookahead))
    dx, dy = target[0] - float(x), target[1] - float(y)
    alpha = wrap_angle(math.atan2(dy, dx) - float(yaw_rad))
    delta = math.atan2(2.0 * wheelbase * math.sin(alpha), lookahead)
    steer = clamp(delta / max_steer_rad, -0.9, 0.9)
    v_target = 4.0 if abs(alpha) < 0.25 else 2.6
    if abs(steer) > 0.45:
        v_target = min(v_target, 2.2)
    if distance_to_goal_m < goal_slowdown_distance_m:
        v_target = min(v_target, goal_speed_mps)
    if speed_cap_mps is not None:
        v_target = min(v_target, float(speed_cap_mps))
    error = v_target - speed
    if error > 0.0:
        throttle = clamp(0.12 + 0.35 * error, 0.0, 0.55)
        brake = 0.0
    else:
        throttle = 0.0
        brake = clamp(-0.6 * error, 0.0, 0.8)
    command = ControlCommand(throttle=throttle, brake=brake, steer=steer)
    info = PurePursuitInfo(
        lookahead_m=lookahead,
        target_x=target[0],
        target_y=target[1],
        alpha_deg=math.degrees(alpha),
        steer=steer,
        v_target=v_target,
    )
    return command, info


class SegmentMonitor:
    """01B's bounded-segment stop conditions, in the original order.

    ``update`` is called once per control cycle. It returns a stop reason and
    freezes; later calls return the same reason. The caller remains responsible
    for actually braking the vehicle and re-reading its speed.
    """

    def __init__(
        self,
        *,
        goal_x: float,
        goal_y: float,
        start_t: float,
        start_progress_s: float = 0.0,
        arrival_radius_m: float = 1.2,
        max_sim_seconds: float = 90.0,
        off_route_lateral_m: float = 2.5,
        off_route_seconds: float = 1.0,
        stuck_after_seconds: float = 3.0,
        stuck_speed_mps: float = 0.5,
        stuck_progress_seconds: float = 5.0,
        progress_epsilon_m: float = 0.2,
    ) -> None:
        for name, value in (
            ("goal_x", goal_x),
            ("goal_y", goal_y),
            ("start_t", start_t),
            ("start_progress_s", start_progress_s),
            ("arrival_radius_m", arrival_radius_m),
            ("max_sim_seconds", max_sim_seconds),
            ("off_route_lateral_m", off_route_lateral_m),
            ("off_route_seconds", off_route_seconds),
            ("stuck_after_seconds", stuck_after_seconds),
            ("stuck_speed_mps", stuck_speed_mps),
            ("stuck_progress_seconds", stuck_progress_seconds),
            ("progress_epsilon_m", progress_epsilon_m),
        ):
            if type(value) is not int and type(value) is not float:
                raise ValueError(f"{name} must be a number")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if arrival_radius_m <= 0 or max_sim_seconds <= 0:
            raise ValueError("arrival radius and timeout must be positive")
        self.goal_x = float(goal_x)
        self.goal_y = float(goal_y)
        self.start_t = float(start_t)
        self.arrival_radius_m = float(arrival_radius_m)
        self.max_sim_seconds = float(max_sim_seconds)
        self.off_route_lateral_m = float(off_route_lateral_m)
        self.off_route_seconds = float(off_route_seconds)
        self.stuck_after_seconds = float(stuck_after_seconds)
        self.stuck_speed_mps = float(stuck_speed_mps)
        self.stuck_progress_seconds = float(stuck_progress_seconds)
        self.progress_epsilon_m = float(progress_epsilon_m)
        self.last_progress_s = float(start_progress_s)
        self.last_progress_t = float(start_t)
        self.off_route_since: float | None = None
        self.stop_reason: str | None = None
        self.stop_t: float | None = None
        self.distance_to_goal_m = float("inf")

    def update(
        self,
        *,
        t: float,
        x: float,
        y: float,
        speed_mps: float,
        progress_s: float,
        cross_track_m: float,
        blocked: bool,
    ) -> str | None:
        if self.stop_reason is not None:
            return self.stop_reason
        for name, value in (
            ("t", t),
            ("x", x),
            ("y", y),
            ("speed_mps", speed_mps),
            ("progress_s", progress_s),
        ):
            if type(value) is not int and type(value) is not float:
                raise ValueError(f"{name} must be a number")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if cross_track_m < 0:
            raise ValueError("cross_track_m must be non-negative")

        self.distance_to_goal_m = math.hypot(
            float(x) - self.goal_x, float(y) - self.goal_y
        )
        if progress_s - self.last_progress_s > self.progress_epsilon_m:
            self.last_progress_s = float(progress_s)
            self.last_progress_t = float(t)

        reason = None
        if self.distance_to_goal_m < self.arrival_radius_m:
            reason = STOP_SUCCESS
        elif blocked:
            reason = STOP_OBSTACLE
        elif cross_track_m > self.off_route_lateral_m:
            if self.off_route_since is None:
                self.off_route_since = float(t)
            elif t - self.off_route_since > self.off_route_seconds:
                reason = STOP_OFF_ROUTE
        else:
            self.off_route_since = None
        if reason is None and (
            t - self.start_t > self.stuck_after_seconds
            and speed_mps < self.stuck_speed_mps
            and t - self.last_progress_t > self.stuck_progress_seconds
        ):
            reason = STOP_STUCK
        if reason is None and t - self.start_t > self.max_sim_seconds:
            reason = STOP_TIMEOUT
        if reason is not None:
            self.stop_reason = reason
            self.stop_t = float(t)
        return reason

    def to_metadata(self) -> dict:
        return {
            "stop_reason": self.stop_reason,
            "distance_to_goal_m": round(self.distance_to_goal_m, 3),
            "last_progress_s": round(self.last_progress_s, 3),
            "elapsed_s": (
                None if self.stop_t is None else round(self.stop_t - self.start_t, 3)
            ),
        }


def _blocked_detail(
    verdict: SafetyVerdict, *, ground_inside_ego: bool = False
) -> str:
    if verdict.obstacle_hit and verdict.ground_bad:
        return "obstacle_and_ground"
    if verdict.obstacle_hit:
        return "obstacle_ray"
    if verdict.ground_bad:
        return "ground_bad_inside_ego" if ground_inside_ego else "ground_bad"
    return "blocked_unknown"


def safety_stop_detail(
    verdict: SafetyVerdict,
    monitor_reason: str | None,
    *,
    max_steps: bool = False,
    ground_inside_ego: bool = False,
) -> str:
    """Classify a stop into a traceable cause.

    ``stop_reason="obstacle"`` is the monitor's coarse category; it covers
    both a forward-ray hit and a bad floor probe. This function keeps the two
    distinguishable in the saved evidence. When the only cause is a ground
    probe inside the ego footprint, it reports that separately: the vertical
    ray may have hit the ego body rather than the floor.
    """

    if not isinstance(verdict, SafetyVerdict):
        raise TypeError("verdict must be a SafetyVerdict")
    if monitor_reason is not None and type(monitor_reason) is not str:
        raise TypeError("monitor_reason must be a str or None")
    if type(ground_inside_ego) is not bool:
        raise TypeError("ground_inside_ego must be a bool")
    if max_steps:
        return "max_steps"
    if monitor_reason == "safety_precheck":
        return "precheck_" + _blocked_detail(
            verdict, ground_inside_ego=ground_inside_ego
        )
    if monitor_reason == STOP_OBSTACLE:
        return _blocked_detail(verdict, ground_inside_ego=ground_inside_ego)
    if monitor_reason == STOP_SUCCESS:
        return "arrival"
    if monitor_reason == STOP_OFF_ROUTE:
        return "off_route"
    if monitor_reason == STOP_STUCK:
        return "stuck"
    if monitor_reason == STOP_TIMEOUT:
        return "timeout"
    if monitor_reason is None:
        return "not_stopped"
    return "unknown"


def _mapping(value: object, name: str) -> dict:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return dict(value)


def build_stop_diagnostics(
    *,
    step: int,
    state: Mapping,
    target: Mapping,
    projection: Mapping,
    safety: Mapping,
    monitor: Mapping | None,
    verdict: SafetyVerdict,
    monitor_reason: str | None,
    max_steps: bool = False,
    ground_inside_ego: bool = False,
    footprint: Mapping | None = None,
    route: Mapping | None = None,
    last_command: Mapping | None = None,
) -> dict:
    """Build one JSON-serialisable stop snapshot.

    The caller supplies the real stop-step values; this function does not
    invent a pose, ray hit or ground reading. ``safety`` should contain the
    detailed ray and ground-probe records collected at that step.
    """

    if type(step) is not int or step < 0:
        raise ValueError("step must be a non-negative int")
    if not isinstance(verdict, SafetyVerdict):
        raise TypeError("verdict must be a SafetyVerdict")
    if type(ground_inside_ego) is not bool:
        raise TypeError("ground_inside_ego must be a bool")
    safety_out = _mapping(safety, "safety")
    safety_out.update(verdict.to_metadata())
    return {
        "schema_version": "1",
        "stop_reason": monitor_reason,
        "stop_detail": safety_stop_detail(
            verdict,
            monitor_reason,
            max_steps=max_steps,
            ground_inside_ego=ground_inside_ego,
        ),
        "ground_inside_ego": ground_inside_ego,
        "step": step,
        "state": _mapping(state, "state"),
        "target": _mapping(target, "target"),
        "projection": _mapping(projection, "projection"),
        "safety": safety_out,
        "monitor": {} if monitor is None else _mapping(monitor, "monitor"),
        "footprint": None if footprint is None else _mapping(footprint, "footprint"),
        "route": None if route is None else _mapping(route, "route"),
        "last_command": (
            None if last_command is None else _mapping(last_command, "last_command")
        ),
    }
