"""Low-speed parking path and goal helpers.

The aisle controller is intentionally left unchanged. This module provides a
small, pure parking layer:

* a forward right-turn arc from a staging pose into bay 03;
* a low-speed Pure Pursuit configuration that still uses the shared
  ``route_control.pure_pursuit_command`` law;
* a final pose/stop evaluation separate from the aisle arrival radius.

These helpers do not replace the runtime safety gate. The CARLA runnable script
still calls the existing forward-ray and floor probes on every control step.
"""

from __future__ import annotations

import math
from typing import Sequence

from .route_control import (
    MAX_STEER_EFF,
    WHEELBASE,
    ControlCommand,
    PurePursuitInfo,
    clamp,
    point_at_s,
    pure_pursuit_command,
    wrap_angle,
)
from .parking_geometry import path_curvature_at_s

__all__ = [
    "PARKING_LOOKAHEAD_BASE",
    "PARKING_LOOKAHEAD_GAIN",
    "PARKING_LOOKAHEAD_MIN",
    "PARKING_LOOKAHEAD_MAX",
    "PARKING_SPEED_CAP_MPS",
    "PARKING_GOAL_SPEED_MPS",
    "PARKING_GOAL_SLOWDOWN_M",
    "PARKING_FEEDFORWARD_GAIN",
    "PARKING_LAUNCH_THROTTLE",
    "PARKING_LAUNCH_SPEED_MPS",
    "PARKING_CROSS_TRACK_GAIN",
    "PARKING_HEADING_GAIN",
    "PARKING_BUDGET_TIME_FACTOR",
    "PARKING_BUDGET_MAX_STEPS",
    "PARKING_BUDGET_MAX_SIM_SECONDS",
    "PARKING_PRECHECK_BASE_ORIGIN_M",
    "build_forward_right_arc",
    "parking_execution_budget",
    "parking_continuation_target_index",
    "parking_precheck_origin_start",
    "parking_command",
    "parking_track_command",
    "parking_goal_evaluation",
]

PARKING_LOOKAHEAD_BASE = 1.5
PARKING_LOOKAHEAD_GAIN = 0.2
PARKING_LOOKAHEAD_MIN = 1.2
PARKING_LOOKAHEAD_MAX = 2.5
PARKING_SPEED_CAP_MPS = 0.45
PARKING_GOAL_SPEED_MPS = 0.4
PARKING_GOAL_SLOWDOWN_M = 1.0
# The 07B real run recorded the arc being cut ~0.6 m inside with gain 0.2: the
# existing Pure Pursuit law already commands the exact arc curvature, so the
# extra feed-forward saturated the steer at 45 deg (R=3.0 m instead of 3.5 m)
# and drove the footprint toward the north pillar. Keep the default at zero.
PARKING_FEEDFORWARD_GAIN = 0.0
PARKING_LAUNCH_THROTTLE = 0.40
PARKING_LAUNCH_SPEED_MPS = 0.05
# The 07B and DEMO-02 arc calibration both showed a stable Pure Pursuit
# inside-offset of ~0.5 m on the 3.56 m arc.  The direct law below commands the
# path curvature plus signed lateral and heading corrections; these gains are
# the offline-tuned starting values (kinematic simulation: max 0.15 m offset
# for a 0.4 s steer lag).
PARKING_CROSS_TRACK_GAIN = 1.5
PARKING_HEADING_GAIN = 0.1

# The validated 08A bay-03 loop execution completed in 1808 steps for a
# 27.891 m route (raw execution.steps; the 2632-entry records array is not a
# step count).  A fixed 1400-step budget cannot even cover that route at the
# 0.35 m/s parking cap (1594 steps), so the budget must scale with the selected
# route.  The 1.75 factor is a conservative margin over the observed
# 1808/1594 ~= 1.13; these caps preserve the validated upper bound and keep the
# stall/off-route/safety exits in control.
PARKING_BUDGET_TIME_FACTOR = 1.75
PARKING_BUDGET_MAX_STEPS = 4000
PARKING_BUDGET_MAX_SIM_SECONDS = 240.0

#: Default corridor precheck origin along the route. A fixed value is only
#: safe when the segment starts at the route origin (projection s ~= 0).
PARKING_PRECHECK_BASE_ORIGIN_M = 3.0


def parking_precheck_origin_start(
    start_s: float,
    *,
    half_length_m: float,
    front_margin_m: float,
    base_origin_m: float = PARKING_PRECHECK_BASE_ORIGIN_M,
) -> float:
    """First along-route s where the corridor ray may leave the ego body.

    The precheck casts rays from points on the route at z = ego_z + 0.35. A
    point still inside the 5.006 m body hits the ego itself at distance 0.0 and
    a valid route is refused as ``precheck_obstacle_ray``. The segment does not
    always start at s = 0 (a spawn can sit ~1 m along its route), so the origin
    must follow the real projection instead of a fixed 3.0 m.
    """

    values = {
        "start_s": _finite(start_s, "start_s"),
        "half_length_m": _finite(half_length_m, "half_length_m"),
        "front_margin_m": _finite(front_margin_m, "front_margin_m"),
        "base_origin_m": _finite(base_origin_m, "base_origin_m"),
    }
    if values["start_s"] < 0.0:
        raise ValueError("start_s must be non-negative")
    if values["half_length_m"] <= 0.0:
        raise ValueError("half_length_m must be positive")
    if values["front_margin_m"] < 0.0:
        raise ValueError("front_margin_m must be non-negative")
    if values["base_origin_m"] < 0.0:
        raise ValueError("base_origin_m must be non-negative")
    return max(
        values["base_origin_m"],
        values["start_s"] + values["half_length_m"] + values["front_margin_m"],
    )


def parking_continuation_target_index(
    route_node_ids: Sequence[str],
    requested_nodes: int,
    *,
    entry_node_ids: Sequence[str] | frozenset[str],
    goal_node_ids: Sequence[str] | frozenset[str],
) -> int:
    """Return the execution target index for an already-approved route.

    A parking entry/turn node is an arc point, not a new high-level decision
    point. When the requested segment target is such a node and the route ends
    at a parking goal, the approved route continues to the parking goal in the
    same segment. This does not select a new direction or bypass arbitration;
    it only prevents a normal aisle stop at an arc point whose only forward
    continuation is the parking path.
    """

    if type(requested_nodes) is not int or requested_nodes < 1:
        raise ValueError("requested_nodes must be a positive int")
    if not route_node_ids:
        raise ValueError("route_node_ids must not be empty")
    entries = frozenset(entry_node_ids)
    goals = frozenset(goal_node_ids)
    target_index = min(requested_nodes, len(route_node_ids) - 1)
    if (
        route_node_ids[target_index] in entries
        and route_node_ids[-1] in goals
    ):
        return len(route_node_ids) - 1
    return target_index


def parking_execution_budget(
    route_length_m: float,
    speed_cap_mps: float,
    fixed_dt_s: float,
    requested_steps: int,
    requested_sim_seconds: float,
) -> dict:
    """Return a bounded parking budget derived from the selected route.

    The parking controller runs at a low speed cap, so a fixed step budget can
    time out on a long but valid bypass before the car reaches the goal.  The
    route length and cap provide a lower bound; a bounded time factor covers
    steering and launch losses.  Explicit CLI requests and hard caps remain
    upper bounds, and the loop's stall/off-route/safety exits are unchanged.
    """

    values = {
        "route_length_m": _finite(route_length_m, "route_length_m"),
        "speed_cap_mps": _finite(speed_cap_mps, "speed_cap_mps"),
        "fixed_dt_s": _finite(fixed_dt_s, "fixed_dt_s"),
        "requested_steps": int(requested_steps),
        "requested_sim_seconds": _finite(
            requested_sim_seconds, "requested_sim_seconds"
        ),
    }
    if values["route_length_m"] < 0:
        raise ValueError("route_length_m must be non-negative")
    if values["speed_cap_mps"] <= 0:
        raise ValueError("speed_cap_mps must be positive")
    if values["fixed_dt_s"] <= 0:
        raise ValueError("fixed_dt_s must be positive")
    if values["requested_steps"] <= 0:
        raise ValueError("requested_steps must be positive")
    if values["requested_sim_seconds"] <= 0:
        raise ValueError("requested_sim_seconds must be positive")

    ideal_steps = math.ceil(
        values["route_length_m"] / (values["speed_cap_mps"] * values["fixed_dt_s"])
    )
    route_steps = math.ceil(ideal_steps * PARKING_BUDGET_TIME_FACTOR)
    route_seconds = (
        values["route_length_m"] / values["speed_cap_mps"]
    ) * PARKING_BUDGET_TIME_FACTOR
    steps = min(
        PARKING_BUDGET_MAX_STEPS,
        max(values["requested_steps"], route_steps),
    )
    sim_seconds = min(
        PARKING_BUDGET_MAX_SIM_SECONDS,
        max(values["requested_sim_seconds"], route_seconds),
    )
    return {
        **values,
        "ideal_steps_at_speed_cap": ideal_steps,
        "route_scaled_steps": route_steps,
        "route_scaled_seconds": round(route_seconds, 3),
        "time_factor": PARKING_BUDGET_TIME_FACTOR,
        "steps": steps,
        "sim_seconds": round(sim_seconds, 3),
        "hard_cap_steps": PARKING_BUDGET_MAX_STEPS,
        "hard_cap_sim_seconds": PARKING_BUDGET_MAX_SIM_SECONDS,
    }


def _finite(value: object, name: str) -> float:
    if type(value) is not int and type(value) is not float:
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
    return float(value)


def build_forward_right_arc(
    start_x: float,
    start_y: float,
    radius: float,
    *,
    final_x: float,
    step_deg: float = 2.5,
) -> tuple[tuple[float, float], ...]:
    """Build a southbound-to-westbound right-turn arc plus a final straight.

    The ego starts at ``(start_x, start_y)`` heading south. The turn centre is
    ``radius`` metres west; the arc ends at ``(start_x - radius,
    start_y - radius)`` heading west. A final straight continues west to
    ``(final_x, start_y - radius)``.
    """

    start_x = _finite(start_x, "start_x")
    start_y = _finite(start_y, "start_y")
    radius = _finite(radius, "radius")
    final_x = _finite(final_x, "final_x")
    step_deg = _finite(step_deg, "step_deg")
    if radius <= 0.0:
        raise ValueError("radius must be positive")
    if not 0.0 < step_deg <= 30.0:
        raise ValueError("step_deg must be in (0, 30]")
    end_x = start_x - radius
    end_y = start_y - radius
    if final_x > end_x + 1e-9:
        raise ValueError("final_x must be west of or equal to the arc endpoint")

    centre_x = start_x - radius
    centre_y = start_y
    points: list[tuple[float, float]] = []
    degrees = 0.0
    while degrees >= -90.0 - 1e-9:
        angle = math.radians(degrees)
        points.append(
            (
                centre_x + radius * math.cos(angle),
                centre_y + radius * math.sin(angle),
            )
        )
        degrees -= step_deg
    last_x, last_y = points[-1]
    if abs(last_x - end_x) > 1e-6 or abs(last_y - end_y) > 1e-6:
        points.append((end_x, end_y))
    if abs(final_x - end_x) > 1e-9:
        points.append((final_x, end_y))
    return tuple(points)


def parking_command(
    *,
    x: float,
    y: float,
    yaw_rad: float,
    speed_mps: float,
    points: Sequence[Sequence[float]],
    cumulative: Sequence[float],
    s: float,
    distance_to_slot_m: float,
    speed_cap_mps: float = PARKING_SPEED_CAP_MPS,
    feedforward_gain: float = PARKING_FEEDFORWARD_GAIN,
) -> tuple[ControlCommand, PurePursuitInfo]:
    """Shared Pure Pursuit law with parking lookahead, cap and curvature feedforward.

    Pure Pursuit already gives the exact circular-arc steer when the lookahead
    point lies on the arc, so the default feedforward gain is zero.  The
    parameter is kept for calibration tests; an optional positive term is
    added to the existing steering command and clamped to the same
    [-0.9, 0.9] range. No safety threshold is changed.
    """

    feedforward_gain = _finite(feedforward_gain, "feedforward_gain")
    if not 0.0 <= feedforward_gain <= 1.0:
        raise ValueError("feedforward_gain must be in [0, 1]")
    command, info = pure_pursuit_command(
        x=x,
        y=y,
        yaw_rad=yaw_rad,
        speed_mps=speed_mps,
        points=points,
        cumulative=cumulative,
        s=s,
        distance_to_goal_m=distance_to_slot_m,
        lookahead_base=PARKING_LOOKAHEAD_BASE,
        lookahead_gain=PARKING_LOOKAHEAD_GAIN,
        lookahead_min=PARKING_LOOKAHEAD_MIN,
        lookahead_max=PARKING_LOOKAHEAD_MAX,
        goal_slowdown_distance_m=PARKING_GOAL_SLOWDOWN_M,
        goal_speed_mps=PARKING_GOAL_SPEED_MPS,
        speed_cap_mps=speed_cap_mps,
    )
    if feedforward_gain == 0.0:
        if speed_mps < PARKING_LAUNCH_SPEED_MPS and command.throttle > 0.0:
            command = ControlCommand(
                throttle=max(command.throttle, PARKING_LAUNCH_THROTTLE),
                brake=command.brake,
                steer=command.steer,
            )
        return command, info
    curvature = path_curvature_at_s(points, cumulative, s)
    feedforward = math.atan(WHEELBASE * curvature) / MAX_STEER_EFF
    steer = clamp(command.steer + feedforward_gain * feedforward, -0.9, 0.9)
    command = ControlCommand(
        throttle=command.throttle, brake=command.brake, steer=steer
    )
    if speed_mps < PARKING_LAUNCH_SPEED_MPS and command.throttle > 0.0:
        command = ControlCommand(
            throttle=max(command.throttle, PARKING_LAUNCH_THROTTLE),
            brake=command.brake,
            steer=command.steer,
        )
    info = PurePursuitInfo(
        lookahead_m=info.lookahead_m,
        target_x=info.target_x,
        target_y=info.target_y,
        alpha_deg=info.alpha_deg,
        steer=steer,
        v_target=info.v_target,
    )
    return command, info


def _path_tangent_angle(
    points: Sequence[Sequence[float]], cumulative: Sequence[float], s: float
) -> float:
    p0 = point_at_s(points, cumulative, s)
    p1 = point_at_s(points, cumulative, min(float(cumulative[-1]), s + 0.5))
    if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < 1e-6:
        p0, p1 = points[-2], points[-1]
    return math.atan2(p1[1] - p0[1], p1[0] - p0[0])


def parking_track_command(
    *,
    x: float,
    y: float,
    yaw_rad: float,
    speed_mps: float,
    points: Sequence[Sequence[float]],
    cumulative: Sequence[float],
    s: float,
    distance_to_slot_m: float,
    signed_lateral_m: float,
    speed_cap_mps: float = PARKING_SPEED_CAP_MPS,
    cross_gain: float = PARKING_CROSS_TRACK_GAIN,
    heading_gain: float = PARKING_HEADING_GAIN,
) -> tuple[ControlCommand, PurePursuitInfo]:
    """Curvature-feedforward parking law with explicit lateral correction.

    Pure Pursuit alone settled ~0.5 m inside the 3.56 m arc in the real 07B and
    DEMO-02 runs. This law commands the path curvature directly and adds a
    signed lateral term (positive is left of the path) and a heading term.
    Throttle/brake still come from the shared 01B speed law.
    """

    cross_gain = _finite(cross_gain, "cross_gain")
    heading_gain = _finite(heading_gain, "heading_gain")
    signed_lateral_m = _finite(signed_lateral_m, "signed_lateral_m")
    if not 0.0 <= cross_gain <= 4.0:
        raise ValueError("cross_gain must be in [0, 4]")
    if not 0.0 <= heading_gain <= 1.5:
        raise ValueError("heading_gain must be in [0, 1.5]")
    base, info = pure_pursuit_command(
        x=x,
        y=y,
        yaw_rad=yaw_rad,
        speed_mps=speed_mps,
        points=points,
        cumulative=cumulative,
        s=s,
        distance_to_goal_m=distance_to_slot_m,
        lookahead_base=PARKING_LOOKAHEAD_BASE,
        lookahead_gain=PARKING_LOOKAHEAD_GAIN,
        lookahead_min=PARKING_LOOKAHEAD_MIN,
        lookahead_max=PARKING_LOOKAHEAD_MAX,
        goal_slowdown_distance_m=PARKING_GOAL_SLOWDOWN_M,
        goal_speed_mps=PARKING_GOAL_SPEED_MPS,
        speed_cap_mps=speed_cap_mps,
    )
    curvature = path_curvature_at_s(points, cumulative, s)
    curvature_steer = math.atan(WHEELBASE * curvature) / MAX_STEER_EFF
    tangent = _path_tangent_angle(points, cumulative, s)
    heading_error = wrap_angle(tangent - yaw_rad)
    steer = clamp(
        curvature_steer - cross_gain * signed_lateral_m + heading_gain * heading_error,
        -0.9,
        0.9,
    )
    throttle = base.throttle
    if speed_mps < PARKING_LAUNCH_SPEED_MPS and throttle > 0.0:
        throttle = max(throttle, PARKING_LAUNCH_THROTTLE)
    command = ControlCommand(
        throttle=throttle,
        brake=base.brake,
        steer=steer,
    )
    info = PurePursuitInfo(
        lookahead_m=info.lookahead_m,
        target_x=info.target_x,
        target_y=info.target_y,
        alpha_deg=info.alpha_deg,
        steer=steer,
        v_target=info.v_target,
    )
    return command, info


def parking_goal_evaluation(
    *,
    x: float,
    y: float,
    yaw_rad: float,
    speed_mps: float,
    stopped: bool,
    slot_x: float,
    slot_y: float,
    slot_heading_rad: float,
    position_tolerance_m: float = 0.25,
    heading_tolerance_deg: float = 5.0,
    stop_speed_mps: float = 0.05,
) -> dict:
    """Evaluate the strict parking goal, independent of arrival radius."""

    x = _finite(x, "x")
    y = _finite(y, "y")
    yaw_rad = _finite(yaw_rad, "yaw_rad")
    speed_mps = _finite(speed_mps, "speed_mps")
    slot_x = _finite(slot_x, "slot_x")
    slot_y = _finite(slot_y, "slot_y")
    slot_heading_rad = _finite(slot_heading_rad, "slot_heading_rad")
    position_tolerance_m = _finite(position_tolerance_m, "position_tolerance_m")
    heading_tolerance_deg = _finite(heading_tolerance_deg, "heading_tolerance_deg")
    stop_speed_mps = _finite(stop_speed_mps, "stop_speed_mps")
    if speed_mps < 0.0 or stop_speed_mps < 0.0:
        raise ValueError("speeds must be non-negative")
    if position_tolerance_m <= 0.0 or heading_tolerance_deg <= 0.0:
        raise ValueError("tolerances must be positive")
    if type(stopped) is not bool:
        raise TypeError("stopped must be a bool")
    distance = math.hypot(x - slot_x, y - slot_y)
    heading_error = wrap_angle(yaw_rad - slot_heading_rad)
    reasons = []
    if distance > position_tolerance_m:
        reasons.append("position_outside_tolerance")
    if abs(math.degrees(heading_error)) > heading_tolerance_deg:
        reasons.append("heading_outside_tolerance")
    if speed_mps >= stop_speed_mps:
        reasons.append("speed_not_stopped")
    if not stopped:
        reasons.append("not_confirmed_stopped")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "distance_m": round(distance, 3),
        "heading_error_deg": round(math.degrees(heading_error), 3),
        "speed_mps": round(speed_mps, 3),
        "stopped": stopped,
        "position_tolerance_m": round(position_tolerance_m, 3),
        "heading_tolerance_deg": round(heading_tolerance_deg, 3),
        "stop_speed_mps": round(stop_speed_mps, 3),
    }
