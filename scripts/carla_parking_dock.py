#!/usr/bin/env python3
"""M1-VLN-CARLA-07C: controlled low-speed bay-03 multi-segment/reverse parking run.

Default mode is geometry-only: it reads the 07A probe JSON, builds the 3.5 m
forward arc and evaluates steering/clearance. It does not connect to CARLA or
move a vehicle.

The motion mode requires ``--execute`` and an explicit user authorization in
the surrounding task. It spawns the ego once at the measured staging pose,
submits one ``parking.move`` request through the real Kernel Host, uses the
existing CARLA safety checks on every control step, and never retries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import carla  # noqa: E402
import carla_parking_nav as nav01b  # noqa: E402

from vln.carla import (  # noqa: E402
    STOP_OBSTACLE,
    STOP_OFF_ROUTE,
    STOP_STUCK,
    STOP_SUCCESS,
    STOP_TIMEOUT,
    build_stop_diagnostics,
    cumulative_lengths,
    forward_safety_verdict,
    point_at_s,
    project_to_path,
)
from vln.carla.kernel_bridge import CarlaExecutionBridge  # noqa: E402
from vln.carla.parking_control import (  # noqa: E402
    PARKING_SPEED_CAP_MPS,
    build_forward_right_arc,
    parking_command,
    parking_goal_evaluation,
    parking_track_command,
)
from vln.carla.parking_geometry import (  # noqa: E402
    Footprint,
    evaluate_path,
    footprint_clearance,
    footprint_polygon_clearance,
    path_clearance,
)
from vln.client import HostClient, build_request  # noqa: E402
from vln.intent import AgentIntent, Target  # noqa: E402
from vln.carla.session import cleanup_session  # noqa: E402

DEFAULT_PROBE = REPO_ROOT / "docs" / "evidence" / "carla-07a" / "geometry_probe.json"
DEFAULT_KERNEL_HOST = "/home/gaosong/workspace/Agentic_Program/m1-vln-carla-02-build/kernel_host"
MAP_NAME = "UndergroundCarPark"
EGO_ROLE = "vln_ego_07b"
COLLISION_ROLE = "vln_collision_07b"
FLOOR_PROBE_Z = 7.0
SAFETY_RAY_Z_OFFSET = 0.35
FIXED_DT = 0.05
PROJECTION_WINDOW_M = 5.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _state(session, ego) -> dict:
    state = nav01b.state_of(ego, session)
    state["heading_rad"] = round(math.radians(state["yaw"]), 6)
    state["snapshot_frame"] = session.world.get_snapshot().frame
    return state


def _projection_metadata(points, cumulative, s) -> dict:
    p0 = point_at_s(points, cumulative, s)
    p1 = point_at_s(points, cumulative, min(cumulative[-1], s + 1.0))
    if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < 1e-3:
        p0, p1 = points[-2], points[-1]
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    return {
        "s": round(s, 3),
        "path_length_m": round(cumulative[-1], 3),
        "point": {"x": round(p0[0], 3), "y": round(p0[1], 3)},
        "point_at_s_plus_1": {"x": round(p1[0], 3), "y": round(p1[1], 3)},
        "tangent": {
            "dx": round((p1[0] - p0[0]) / length, 6),
            "dy": round((p1[1] - p0[1]) / length, 6),
        },
    }


def _safety_summary(details: dict) -> dict:
    rays = []
    for record in details.get("rays", []):
        hit = record.get("hit")
        rays.append(
            {
                "source": record.get("source"),
                "height_m": record.get("height_m"),
                "lateral_offset_m": record.get("lateral_offset_m"),
                "origin_s": record.get("origin_s"),
                "hit": (
                    None
                    if not isinstance(hit, dict)
                    else {
                        "distance_from_origin_m": hit.get("distance_from_origin_m"),
                        "label": hit.get("label"),
                        "location": hit.get("location"),
                    }
                ),
            }
        )
    probes = []
    for probe in details.get("ground_probes", []):
        probes.append(
            {
                "s": probe.get("s"),
                "point": probe.get("point"),
                "floor_z": probe.get("floor_z"),
                "inside_ego_footprint": probe.get("inside_ego_footprint"),
            }
        )
    verdict = details.get("verdict") or {}
    return {
        "blocked": verdict.get("blocked"),
        "obstacle_hit": verdict.get("obstacle_hit"),
        "ground_bad": verdict.get("ground_bad"),
        "min_hit_m": verdict.get("min_hit_m"),
        "ground_z": verdict.get("ground_z"),
        "stop_distance_m": verdict.get("stop_distance_m"),
        "ground_probe_inside_ego": details.get("ground_probe_inside_ego"),
        "reverse": details.get("reverse"),
        "probe_origin": details.get("probe_origin"),
        "rays": rays,
        "ground_probes": probes,
    }


def _stop_diagnostics(
    *,
    step,
    state,
    target,
    s,
    cross_track_m,
    points,
    cumulative,
    safety_details,
    min_hit,
    ground,
    monitor_metadata,
    monitor_reason,
    ego,
    last_command,
    max_steps=False,
):
    verdict = forward_safety_verdict(
        min_hit_m=min_hit,
        speed_mps=float(state["speed"]),
        ground_z=ground,
    )
    projection = _projection_metadata(points, cumulative, s)
    projection["cross_track_m"] = round(cross_track_m, 3)
    try:
        extent = ego.bounding_box.extent
        footprint = {
            "half_length_m": round(float(extent.x), 3),
            "half_width_m": round(float(extent.y), 3),
            "length_m": round(2.0 * float(extent.x), 3),
            "width_m": round(2.0 * float(extent.y), 3),
            "front_margin_m": round(float(nav01b.FRONT_MARGIN), 3),
        }
    except Exception:
        footprint = None
    return build_stop_diagnostics(
        step=step,
        state=state,
        target=target,
        projection=projection,
        safety=safety_details or {},
        monitor=monitor_metadata,
        verdict=verdict,
        monitor_reason=monitor_reason,
        max_steps=max_steps,
        ground_inside_ego=bool(
            (safety_details or {}).get("ground_probe_inside_ego", False)
        ),
        footprint=footprint,
        route={"length_m": round(cumulative[-1], 3)},
        last_command=last_command,
    )


def _capture_final_photo(session, out_dir: Path, *, fov=90.0) -> dict:
    library = session.world.get_blueprint_library()
    bp = library.find("sensor.camera.rgb")
    bp.set_attribute("image_size_x", "1280")
    bp.set_attribute("image_size_y", "720")
    bp.set_attribute("fov", str(fov))
    bp.set_attribute("sensor_tick", "0.0")
    bp.set_attribute("role_name", "vln_final_photo_07b")
    transform = carla.Transform(
        carla.Location(x=-4.0, y=-21.0, z=7.2),
        carla.Rotation(pitch=0.0, yaw=180.0),
    )
    camera = session.world.spawn_actor(bp, transform)
    latest = nav01b.LatestImage()
    camera.listen(latest)
    try:
        session.tick(25)
        image = None
        for _ in range(30):
            snapshot = session.world.get_snapshot()
            candidate = latest.image
            if candidate is not None and 0 <= snapshot.frame - candidate.frame <= 2:
                image = candidate
                break
            session.tick()
        if image is None:
            raise RuntimeError("final photo camera produced no fresh frame")
        path = out_dir / f"final_parking_{image.frame}.png"
        image.save_to_disk(str(path))
        return {
            "path": str(path),
            "frame": image.frame,
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
            "fov": float(fov),
            "transform": {
                "x": transform.location.x,
                "y": transform.location.y,
                "z": transform.location.z,
                "pitch": transform.rotation.pitch,
                "yaw": transform.rotation.yaw,
            },
        }
    finally:
        camera.stop()
        camera.destroy()


def _load_probe(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "obstacle_points" not in data:
        raise ValueError(f"probe JSON is missing obstacle_points: {path}")
    return data


_MOTION_ARGS = (
    "maneuver",
    "staging_x",
    "staging_y",
    "staging_yaw_deg",
    "spawn_z",
    "slot_x",
    "slot_y",
    "slot_heading_deg",
    "arc_radius",
    "path_step_deg",
    "speed_cap",
    "position_tolerance_m",
    "heading_tolerance_deg",
    "final_distance_m",
    "required_clearance_m",
    "collision_margin_m",
    "off_route_lateral_m",
    "off_route_seconds",
    "stuck_speed_mps",
    "stuck_seconds",
    "max_steps",
    "max_sim_seconds",
    "request_timeout",
    "kernel_host",
    "bay_boundary_json",
)


def _validate_motion_args(args) -> None:
    missing = [name for name in _MOTION_ARGS if not hasattr(args, name)]
    if missing:
        raise ValueError(f"missing motion arguments: {missing}")
    for name in (
        "arc_radius",
        "path_step_deg",
        "speed_cap",
        "position_tolerance_m",
        "heading_tolerance_deg",
        "final_distance_m",
        "required_clearance_m",
        "collision_margin_m",
        "off_route_lateral_m",
        "off_route_seconds",
        "stuck_speed_mps",
        "stuck_seconds",
        "max_sim_seconds",
        "request_timeout",
    ):
        value = getattr(args, name)
        if type(value) not in (int, float) or not math.isfinite(float(value)) or value <= 0:
            raise ValueError(f"{name} must be a finite positive number")
    if args.maneuver not in {"forward_arc", "reverse_straight"}:
        raise ValueError("maneuver must be forward_arc or reverse_straight")
    if type(args.max_steps) is not int or args.max_steps <= 0:
        raise ValueError("max_steps must be a positive int")


def _load_boundary(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    points = data.get("points")
    guard_points = data.get("guard_points", points)
    if not isinstance(points, list) or len(points) < 3:
        raise ValueError("bay boundary JSON must contain at least three points")
    if not isinstance(guard_points, list) or not guard_points:
        raise ValueError("bay boundary JSON must contain guard_points or points")
    return {
        "path": str(path),
        "points": points,
        "guard_points": guard_points,
        "slot_center": data.get("slot_center"),
        "slot_heading_deg": data.get("slot_heading_deg"),
        "visual_width_estimate_m": data.get("visual_width_estimate_m"),
        "conservative_width_m": data.get("conservative_width_m"),
        "uncertainty_m": data.get("uncertainty_m"),
        "method": data.get("method"),
        "notes": data.get("notes", []),
    }


def _build_geometry(args, probe: dict) -> dict:
    boundary = (
        None
        if not args.bay_boundary_json
        else _load_boundary(Path(args.bay_boundary_json))
    )
    if boundary is not None:
        center = boundary.get("slot_center")
        if not isinstance(center, list) or len(center) != 2:
            raise ValueError("bay boundary slot_center must be [x, y]")
        if (
            abs(float(center[0]) - args.slot_x) > 0.10
            or abs(float(center[1]) - args.slot_y) > 0.10
        ):
            raise ValueError(
                "bay boundary slot_center does not match --slot-x/--slot-y"
            )
        if boundary.get("slot_heading_deg") is not None and abs(
            math.radians(float(boundary["slot_heading_deg"]))
            - math.radians(args.slot_heading_deg)
        ) > math.radians(5.0):
            raise ValueError("bay boundary slot_heading_deg does not match")

    reverse = args.maneuver == "reverse_straight"
    if reverse:
        path = ((args.staging_x, args.staging_y), (args.slot_x, args.slot_y))
        if abs(args.staging_y - args.slot_y) > 0.05:
            raise ValueError("reverse_straight requires staging_y == slot_y")
        if args.staging_x <= args.slot_x + 0.05:
            raise ValueError("reverse_straight requires staging_x east of slot_x")
        if not (-4.30 <= args.staging_x <= -2.60) or not (
            -23.0 <= args.staging_y <= -19.5
        ):
            raise ValueError(
                "reverse staging pose is not on the measured bay-entry aisle: "
                f"({args.staging_x:.3f},{args.staging_y:.3f})"
            )
        if abs(math.atan2(
            math.sin(math.radians(args.staging_yaw_deg)),
            math.cos(math.radians(args.staging_yaw_deg)),
        )) > math.radians(10.0):
            raise ValueError("reverse staging yaw must be near 0 degrees")
        if abs(math.atan2(
            math.sin(math.radians(args.slot_heading_deg)),
            math.cos(math.radians(args.slot_heading_deg)),
        )) > math.radians(10.0):
            raise ValueError("reverse slot heading must be near 0 degrees")
    else:
        path = build_forward_right_arc(
            args.staging_x,
            args.staging_y,
            args.arc_radius,
            final_x=args.slot_x,
            step_deg=args.path_step_deg,
        )
        if abs((args.staging_y - args.arc_radius) - args.slot_y) > 0.05:
            raise ValueError(
                "arc endpoint y does not match slot y: "
                f"{args.staging_y - args.arc_radius:.3f} vs {args.slot_y:.3f}"
            )
        if abs(args.staging_x - (-4.0)) > 0.30 or not (
            -18.0 <= args.staging_y <= -14.0
        ):
            raise ValueError(
                "staging pose is not on the measured w8->w9 aisle segment: "
                f"({args.staging_x:.3f},{args.staging_y:.3f})"
            )

    footprint_meta = probe.get("footprint", {})
    footprint = Footprint(
        float(footprint_meta.get("half_length_m", 2.503)),
        float(footprint_meta.get("half_width_m", 0.94)),
        float(footprint_meta.get("front_margin_m", nav01b.FRONT_MARGIN)),
    )
    obstacles = probe.get("obstacle_points", [])
    guard_points = [] if boundary is None else boundary["guard_points"]
    combined = list(obstacles) + list(guard_points)
    evaluation = evaluate_path(
        path,
        footprint,
        combined,
        required_clearance_m=args.required_clearance_m,
        sample_step_m=0.10,
    )
    boundary_eval = None
    if boundary is not None:
        boundary_eval = footprint_polygon_clearance(
            args.slot_x,
            args.slot_y,
            math.radians(args.slot_heading_deg),
            footprint,
            boundary["points"],
        )
    return {
        "path": path,
        "cumulative": cumulative_lengths(path),
        "footprint": footprint,
        "evaluation": evaluation,
        "obstacles": obstacles,
        "guard_points": guard_points,
        "boundary": boundary,
        "boundary_eval": boundary_eval,
        "maneuver": args.maneuver,
        "reverse": reverse,
    }


def _execute_parking(
    *,
    session,
    ego,
    path,
    cumulative,
    args,
    collision_events,
    collision_lock,
    run_id,
    obstacles,
    collision_margin_m,
):
    slot_heading = math.radians(args.slot_heading_deg)
    slot_target = {
        "x": args.slot_x,
        "y": args.slot_y,
        "heading": slot_heading,
    }
    reverse = args.maneuver == "reverse_straight"
    ego_footprint = Footprint(
        ego.bounding_box.extent.x,
        ego.bounding_box.extent.y,
        nav01b.FRONT_MARGIN,
    )
    pre_state = _state(session, ego)
    start_s = 0.0
    last_progress_s = start_s
    last_progress_t = pre_state["t"]
    off_route_since = None
    last_command = None
    records = []
    steps = 0
    stop_reason = None
    safety_details = {}
    min_hit = None
    ground = []
    state = pre_state
    s = start_s
    cross = 0.0
    collision_count = 0
    distance_slot = math.hypot(pre_state["x"] - args.slot_x, pre_state["y"] - args.slot_y)
    heading_error = math.atan2(
        math.sin(pre_state["heading_rad"] - slot_heading),
        math.cos(pre_state["heading_rad"] - slot_heading),
    )
    while steps < args.max_steps:
        state = _state(session, ego)
        s, px, py, cross = project_to_path(
            path,
            cumulative,
            state["x"],
            state["y"],
            last_progress_s,
            window_m=PROJECTION_WINDOW_M,
        )
        tang0 = point_at_s(path, cumulative, s)
        tang1 = point_at_s(
            path, cumulative, min(cumulative[-1], s + 0.5)
        )
        if math.hypot(tang1[0] - tang0[0], tang1[1] - tang0[1]) < 1e-6:
            tang0, tang1 = path[-2], path[-1]
        tang_len = math.hypot(tang1[0] - tang0[0], tang1[1] - tang0[1])
        tang_x = (tang1[0] - tang0[0]) / tang_len
        tang_y = (tang1[1] - tang0[1]) / tang_len
        signed_lateral = -(
            (state["x"] - px) * tang_y - (state["y"] - py) * tang_x
        )
        distance_slot = math.hypot(state["x"] - args.slot_x, state["y"] - args.slot_y)
        heading_error = math.atan2(
            math.sin(state["heading_rad"] - slot_heading),
            math.cos(state["heading_rad"] - slot_heading),
        )
        safety_details = {}
        blocked, min_hit, ground = nav01b.safety_check(
            session,
            ego,
            path,
            cumulative,
            s,
            floor_probe_z=FLOOR_PROBE_Z,
            ray_z_offset=SAFETY_RAY_Z_OFFSET,
            reverse=reverse,
            stop_distance_m=1.0,
            details_out=safety_details,
        )
        with collision_lock:
            collision_count = len(collision_events)
        if collision_count:
            stop_reason = "collision"
            break
        static_clearance = footprint_clearance(
            state["x"],
            state["y"],
            state["heading_rad"],
            ego_footprint,
            obstacles,
        )
        if (
            static_clearance.get("min_clearance_m") is not None
            and static_clearance["min_clearance_m"] < collision_margin_m
        ):
            stop_reason = "clearance_margin"
            break
        if blocked:
            stop_reason = STOP_OBSTACLE
            break
        if (
            state["speed"] < 0.05
            and distance_slot <= args.position_tolerance_m
            and abs(math.degrees(heading_error)) <= args.heading_tolerance_deg
        ):
            stop_reason = STOP_SUCCESS
            break
        if distance_slot <= args.final_distance_m and state["speed"] < 0.05:
            stop_reason = STOP_SUCCESS
            break
        if s - last_progress_s > 0.2:
            last_progress_s = s
            last_progress_t = state["t"]
        if cross > args.off_route_lateral_m:
            if off_route_since is None:
                off_route_since = state["t"]
            elif state["t"] - off_route_since > args.off_route_seconds:
                stop_reason = STOP_OFF_ROUTE
                break
        else:
            off_route_since = None
        if (
            state["t"] - last_progress_t > args.stuck_seconds
            and state["speed"] < args.stuck_speed_mps
        ):
            stop_reason = STOP_STUCK
            break
        if state["t"] - pre_state["t"] > args.max_sim_seconds:
            stop_reason = STOP_TIMEOUT
            break

        if distance_slot <= args.final_distance_m:
            command = None
            info = None
            speed_cap = None
            control = carla.VehicleControl(
                throttle=0.0, brake=1.0, steer=0.0, reverse=reverse
            )
        elif reverse:
            command = None
            info = None
            speed_cap = min(
                args.speed_cap,
                max(0.15, 0.45 * float(distance_slot)),
            )
            if state["speed"] < 0.05:
                throttle = 0.40
                brake = 0.0
            elif state["speed"] > speed_cap + 0.10:
                throttle = 0.0
                brake = 0.30
            else:
                throttle = max(
                    0.0,
                    min(0.35, 0.10 + 0.30 * (speed_cap - state["speed"])),
                )
                brake = 0.0
            control = carla.VehicleControl(
                throttle=throttle,
                steer=0.0,
                brake=brake,
                reverse=True,
            )
        else:
            speed_cap = min(
                args.speed_cap,
                max(0.10, 0.45 * float(distance_slot)),
            )
            final_leg = s >= cumulative[-1] - 2.0
            command, info = parking_track_command(
                x=state["x"],
                y=state["y"],
                yaw_rad=state["heading_rad"],
                speed_mps=state["speed"],
                points=path,
                cumulative=cumulative,
                s=s,
                distance_to_slot_m=distance_slot,
                signed_lateral_m=signed_lateral,
                speed_cap_mps=speed_cap,
                cross_gain=2.5 if final_leg else 1.5,
                heading_gain=0.3 if final_leg else 0.1,
            )
            control = carla.VehicleControl(
                throttle=command.throttle,
                steer=command.steer,
                brake=command.brake,
                reverse=False,
            )
        ego.apply_control(control)
        last_command = {
            "throttle": round(float(control.throttle), 3),
            "brake": round(float(control.brake), 3),
            "steer": round(float(control.steer), 3),
            "reverse": bool(control.reverse),
        }
        records.append(
            {
                "step": steps,
                "frame": state.get("snapshot_frame"),
                "t": state["t"],
                "x": state["x"],
                "y": state["y"],
                "z": state["z"],
                "yaw": state["yaw"],
                "speed": state["speed"],
                "progress_m": round(s, 3),
                "cross_track_m": round(cross, 3),
                "signed_lateral_m": round(signed_lateral, 3),
                "distance_to_slot_m": round(distance_slot, 3),
                "heading_error_deg": round(math.degrees(heading_error), 3),
                "control": last_command,
                "speed_cap_mps": (
                    None if speed_cap is None else round(speed_cap, 3)
                ),
                "lookahead_m": None if info is None else info.lookahead_m,
                "v_target_mps": None if info is None else info.v_target,
                "static_clearance_m": static_clearance.get("min_clearance_m"),
                "static_clearance": static_clearance,
                "safety": _safety_summary(safety_details),
            }
        )
        session.tick()
        steps += 1

    if stop_reason is None:
        stop_reason = "max_steps"
        max_steps = True
    else:
        max_steps = False

    session.brake_to_stop(ego, max_ticks=120)
    post_state = _state(session, ego)
    session.tick(10)
    stable_state = _state(session, ego)
    stopped = stable_state["speed"] < 0.05 and post_state["speed"] < 0.05
    monitor_metadata = {
        "stop_reason": (
            stop_reason
            if stop_reason
            in {STOP_OBSTACLE, STOP_OFF_ROUTE, STOP_STUCK, STOP_TIMEOUT, STOP_SUCCESS}
            else stop_reason
        ),
        "distance_to_slot_m": round(
            math.hypot(post_state["x"] - args.slot_x, post_state["y"] - args.slot_y), 3
        ),
        "steps": steps,
    }
    final_goal = parking_goal_evaluation(
        x=post_state["x"],
        y=post_state["y"],
        yaw_rad=post_state["heading_rad"],
        speed_mps=post_state["speed"],
        stopped=stopped,
        slot_x=args.slot_x,
        slot_y=args.slot_y,
        slot_heading_rad=slot_heading,
        position_tolerance_m=args.position_tolerance_m,
        heading_tolerance_deg=args.heading_tolerance_deg,
        stop_speed_mps=0.05,
    )
    diagnostics = _stop_diagnostics(
        step=max(0, steps - 1),
        state=state,
        target={
            "node_id": "park_slot",
            "x": round(args.slot_x, 3),
            "y": round(args.slot_y, 3),
            "heading_deg": round(args.slot_heading_deg, 3),
        },
        s=s,
        cross_track_m=cross,
        points=path,
        cumulative=cumulative,
        safety_details=safety_details,
        min_hit=min_hit,
        ground=ground,
        monitor_metadata=monitor_metadata,
        monitor_reason=stop_reason,
        ego=ego,
        last_command=last_command,
        max_steps=max_steps,
    )
    if stop_reason not in {
        STOP_OBSTACLE,
        STOP_OFF_ROUTE,
        STOP_STUCK,
        STOP_TIMEOUT,
        STOP_SUCCESS,
    }:
        diagnostics["stop_detail"] = stop_reason

    success = (
        final_goal["ok"]
        and stopped
        and not collision_count
        and stop_reason == STOP_SUCCESS
    )
    status = "completed" if success else ("failed" if stop_reason == "controller_exception" else "stopped")
    moved_m = round(
        math.hypot(post_state["x"] - pre_state["x"], post_state["y"] - pre_state["y"]),
        3,
    )
    return {
        "status": status,
        "stop_reason": stop_reason,
        "stop_detail": diagnostics.get("stop_detail"),
        "pre_state": pre_state,
        "post_state": post_state,
        "stable_state": stable_state,
        "stopped": stopped,
        "moved_m": moved_m,
        "motion_executed": moved_m > 0.05,
        "target": slot_target,
        "path_length_m": round(cumulative[-1], 3),
        "steps": steps,
        "records": records,
        "final_goal": final_goal,
        "stop_diagnostics": diagnostics,
        "collision_events": list(collision_events),
    }


def _run_geometry(args, probe: dict) -> tuple[int, dict]:
    geometry = _build_geometry(args, probe)
    evaluation = geometry["evaluation"]
    result = {
        "task": "M1-VLN-CARLA-07C-EXEC",
        "phase": "geometry_only",
        "maneuver": geometry["maneuver"],
        "reverse": geometry["reverse"],
        "generated_utc": _utc_now(),
        "motion_executed": False,
        "probe_json": str(args.probe_json),
        "staging_pose": {
            "x": args.staging_x,
            "y": args.staging_y,
            "yaw_deg": args.staging_yaw_deg,
        },
        "slot_pose": {
            "x": args.slot_x,
            "y": args.slot_y,
            "heading_deg": args.slot_heading_deg,
        },
        "arc_radius_m": args.arc_radius,
        "path": [[round(x, 3), round(y, 3)] for x, y in geometry["path"]],
        "path_length_m": round(geometry["cumulative"][-1], 3),
        "footprint": geometry["footprint"].to_metadata(),
        "geometry_evaluation": evaluation,
        "bay_boundary": geometry["boundary"],
        "boundary_evaluation": geometry["boundary_eval"],
        "boundary_clearance_verified": bool(
            geometry["boundary"] is not None
            and geometry["boundary_eval"] is not None
            and geometry["boundary_eval"].get("min_clearance_m") is not None
            and geometry["boundary_eval"]["min_clearance_m"]
            >= args.required_clearance_m
        ),
        "reason": (
            "geometry-only check; no CARLA connection, no actor spawn, no motion. "
            "Bay boundary is a calibrated visual estimate with recorded uncertainty."
        ),
    }
    status = "BLOCKED_BY_GEOMETRY" if not evaluation["feasible"] else "PARTIAL"
    result["status"] = status
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "geometry_check.json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    return (2 if status == "BLOCKED_BY_GEOMETRY" else 0), result


def _run_motion(args, probe: dict) -> tuple[int, dict]:
    if not args.execute:
        raise ValueError("_run_motion called without --execute")
    _validate_motion_args(args)
    geometry = _build_geometry(args, probe)
    boundary_info = geometry["boundary"]
    boundary_points = None if boundary_info is None else boundary_info["points"]
    guard_points = [] if boundary_info is None else boundary_info["guard_points"]
    combined_obstacles = list(probe["obstacle_points"]) + list(guard_points)
    if not geometry["evaluation"]["feasible"]:
        return 2, {
            "task": "M1-VLN-CARLA-07C-EXEC",
            "status": "BLOCKED_BY_GEOMETRY",
            "motion_executed": False,
            "geometry_evaluation": geometry["evaluation"],
            "reason": "candidate path did not pass the steering/clearance check",
        }

    kernel_exe = args.kernel_host
    if not (os.path.isfile(kernel_exe) and os.access(kernel_exe, os.X_OK)):
        raise ValueError(f"Kernel Host is not executable: {kernel_exe}")

    client = carla.Client(args.host, args.port)
    client.set_timeout(20.0)
    world = client.get_world()
    if not world.get_map().name.endswith(MAP_NAME):
        raise RuntimeError(
            f"expected {MAP_NAME}, got {world.get_map().name}; refusing to reconfigure the map"
        )

    run_id = f"carla-07c-parking-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out_dir = Path(args.out_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    session = None
    host_client = None
    bridge = None
    result = {
        "task": "M1-VLN-CARLA-07C-EXEC",
        "run_id": run_id,
        "phase": "motion",
        "maneuver": geometry["maneuver"],
        "reverse": geometry["reverse"],
        "generated_utc": _utc_now(),
        "motion_executed": False,
        "probe_json": str(args.probe_json),
        "staging_pose": {
            "x": args.staging_x,
            "y": args.staging_y,
            "yaw_deg": args.staging_yaw_deg,
        },
        "slot_pose": {
            "x": args.slot_x,
            "y": args.slot_y,
            "heading_deg": args.slot_heading_deg,
        },
        "arc_radius_m": args.arc_radius,
        "path": [[round(x, 3), round(y, 3)] for x, y in geometry["path"]],
        "path_length_m": round(geometry["cumulative"][-1], 3),
        "footprint": geometry["footprint"].to_metadata(),
        "geometry_evaluation": geometry["evaluation"],
        "bay_boundary": {
            "path": None if boundary_info is None else boundary_info["path"],
            "points": boundary_points,
            "guard_point_count": len(guard_points),
            "verified": boundary_info is not None,
            "visual_width_estimate_m": (
                None if boundary_info is None else boundary_info.get("visual_width_estimate_m")
            ),
            "conservative_width_m": (
                None if boundary_info is None else boundary_info.get("conservative_width_m")
            ),
            "uncertainty_m": (
                None if boundary_info is None else boundary_info.get("uncertainty_m")
            ),
            "method": None if boundary_info is None else boundary_info.get("method"),
        },
        "status": "PARTIAL",
    }
    collision_events = []
    collision_lock = threading.Lock()
    try:
        session = nav01b.Session(args.host, args.port, str(out_dir), map_name=MAP_NAME)
        result["carla"] = {
            "server_version": client.get_server_version(),
            "map": session.world.get_map().name,
            "settings_before": dict(session.original),
        }
        session.destroy_leftovers()
        ego = session.spawn_vehicle(
            EGO_ROLE,
            args.staging_x,
            args.staging_y,
            args.spawn_z,
            args.staging_yaw_deg,
        )
        collision_bp = session.world.get_blueprint_library().find(
            "sensor.other.collision"
        )
        collision_bp.set_attribute("role_name", COLLISION_ROLE)
        collision = session.world.spawn_actor(collision_bp, carla.Transform(), attach_to=ego)
        session.actors.append(collision)

        def _on_collision(event):
            other = getattr(event, "other_actor", None)
            with collision_lock:
                collision_events.append(
                    {
                        "frame": getattr(event, "frame", None),
                        "other_actor_id": getattr(other, "id", None),
                        "other_actor_type": getattr(other, "type_id", None),
                        "normal_impulse": {
                            "x": round(float(event.normal_impulse.x), 4),
                            "y": round(float(event.normal_impulse.y), 4),
                            "z": round(float(event.normal_impulse.z), 4),
                        },
                    }
                )

        collision.listen(_on_collision)
        session.tick(40)
        spawn_state = _state(session, ego)
        result["spawn_state"] = spawn_state
        result["vehicle_spawned"] = True
        start_distance = math.hypot(
            spawn_state["x"] - args.staging_x, spawn_state["y"] - args.staging_y
        )
        with collision_lock:
            initial_collisions = list(collision_events)
        if start_distance > 0.5 or spawn_state["speed"] > 0.1:
            raise RuntimeError(
                "spawn did not settle at the staging pose: "
                f"distance={start_distance:.3f}, speed={spawn_state['speed']:.3f}"
            )
        if initial_collisions:
            raise RuntimeError(f"collision at spawn: {initial_collisions}")

        def handler(permit):
            return _execute_parking(
                session=session,
                ego=ego,
                path=geometry["path"],
                cumulative=geometry["cumulative"],
                args=args,
                collision_events=collision_events,
                collision_lock=collision_lock,
                run_id=run_id,
                obstacles=combined_obstacles,
                collision_margin_m=args.collision_margin_m,
            )

        bridge = CarlaExecutionBridge(
            handler, request_timeout_s=max(30.0, args.request_timeout)
        )
        bridge.start()
        host_env = os.environ.copy()
        host_env["VLN_CARLA_EXEC_BRIDGE"] = bridge.endpoint
        host_env["VLN_CARLA_EXEC_TOKEN"] = bridge.token
        host_env["VLN_CARLA_EXEC_TIMEOUT_MS"] = str(
            min(600000, max(30000, int(args.request_timeout * 1000)))
        )
        host_client = HostClient([kernel_exe], env=host_env)

        intent = AgentIntent(
            intent_id=f"{run_id}-intent",
            target=Target(
                x=args.slot_x,
                y=args.slot_y,
                heading=math.radians(args.slot_heading_deg),
            ),
        )
        payload = intent.to_payload()
        request_id = f"{run_id}-request"
        bridge.register_permit(
            request_id=request_id,
            intent_id=intent.intent_id,
            target=intent.target.to_object(),
            payload=payload,
            context={
                "run_id": run_id,
                "path_length_m": round(geometry["cumulative"][-1], 3),
            },
        )
        request = build_request(intent, request_id=request_id)
        result["kernel_request"] = {
            "request_id": request_id,
            "intent_id": intent.intent_id,
            "intent_payload": payload,
            "capability_id": request.capability_id,
        }
        started = time.monotonic()
        response = host_client.send(request)
        elapsed = round(time.monotonic() - started, 3)
        transaction = bridge.get_transaction(request_id)
        result["kernel"] = {
            "request_id": request_id,
            "intent_id": intent.intent_id,
            "intent_payload": payload,
            "elapsed_s": elapsed,
            "response": {
                "request_id": response.request_id,
                "host_kind": response.host_kind,
                "accepted": response.accepted,
                "submission_status": response.submission_status,
                "observation_status": response.observation_status,
                "execution_status": response.execution_status,
                "error": None if response.error is None else dict(response.error),
                "output": response.output,
            },
            "bridge_transaction": transaction,
            "host_stderr_tail": host_client.stderr_lines[-40:],
        }

        final_state = _state(session, ego)
        result["final_state"] = final_state
        result["motion_executed"] = (
            math.hypot(
                final_state["x"] - spawn_state["x"],
                final_state["y"] - spawn_state["y"],
            )
            > 0.05
        )
        result["final_goal"] = parking_goal_evaluation(
            x=final_state["x"],
            y=final_state["y"],
            yaw_rad=final_state["heading_rad"],
            speed_mps=final_state["speed"],
            stopped=final_state["speed"] < 0.05,
            slot_x=args.slot_x,
            slot_y=args.slot_y,
            slot_heading_rad=math.radians(args.slot_heading_deg),
            position_tolerance_m=args.position_tolerance_m,
            heading_tolerance_deg=args.heading_tolerance_deg,
            stop_speed_mps=0.05,
        )
        vehicle = transaction.get("vehicle") if isinstance(transaction, dict) else None
        if isinstance(vehicle, dict):
            result["execution"] = {
                "status": vehicle.get("status"),
                "stop_reason": vehicle.get("stop_reason"),
                "stop_detail": vehicle.get("stop_detail"),
                "pre_state": vehicle.get("pre_state"),
                "post_state": vehicle.get("post_state"),
                "steps": vehicle.get("steps"),
                "records": vehicle.get("records"),
                "final_goal": vehicle.get("final_goal"),
                "stop_diagnostics": vehicle.get("stop_diagnostics"),
                "collision_events": vehicle.get("collision_events"),
            }
            result["motion_executed"] = bool(
                vehicle.get("motion_executed", result["motion_executed"])
            )
        result["collision_events"] = list(collision_events)

        final_footprint = Footprint(
            float(ego.bounding_box.extent.x),
            float(ego.bounding_box.extent.y),
            float(nav01b.FRONT_MARGIN),
        )
        trajectory = [
            (record["x"], record["y"]) for record in (vehicle or {}).get("records", [])
        ]
        if trajectory:
            trajectory.append((final_state["x"], final_state["y"]))
            result["trajectory_clearance"] = path_clearance(
                trajectory, final_footprint, combined_obstacles
            )
        else:
            result["trajectory_clearance"] = {
                "min_clearance_m": None,
                "obstacle_count": len(combined_obstacles),
            }
        result["final_clearance"] = footprint_clearance(
            final_state["x"],
            final_state["y"],
            final_state["heading_rad"],
            final_footprint,
            combined_obstacles,
        )
        if boundary_points is not None:
            result["boundary_clearance"] = footprint_polygon_clearance(
                final_state["x"],
                final_state["y"],
                final_state["heading_rad"],
                final_footprint,
                boundary_points,
            )
        else:
            result["boundary_clearance"] = {
                "min_clearance_m": None,
                "obstacle_count": 0,
                "reason": "no measured painted bay boundary was supplied",
            }
        result["final_photo"] = _capture_final_photo(session, out_dir)

        kernel_ok = (
            response.execution_status == "completed"
            and isinstance(vehicle, dict)
            and vehicle.get("status") == "completed"
            and vehicle.get("stop_reason") == STOP_SUCCESS
        )
        collision_ok = not collision_events
        trajectory_ok = (
            result["trajectory_clearance"].get("min_clearance_m") is not None
            and result["trajectory_clearance"]["min_clearance_m"]
            >= args.required_clearance_m
        )
        final_clearance_ok = (
            result["final_clearance"].get("min_clearance_m") is not None
            and result["final_clearance"]["min_clearance_m"]
            >= args.required_clearance_m
        )
        boundary_ok = (
            boundary_points is not None
            and result["boundary_clearance"].get("min_clearance_m") is not None
            and result["boundary_clearance"]["min_clearance_m"]
            >= args.required_clearance_m
        )
        clearance_ok = trajectory_ok and final_clearance_ok and boundary_ok
        goal_ok = bool(result["final_goal"].get("ok"))
        result["checks"] = {
            "motion_executed": bool(result["motion_executed"]),
            "kernel_completed": kernel_ok,
            "goal_position_heading_speed": goal_ok,
            "no_collision": collision_ok,
            "trajectory_clearance": trajectory_ok,
            "final_clearance": final_clearance_ok,
            "boundary_clearance_verified": boundary_ok,
            "trajectory_and_final_clearance": clearance_ok,
        }
        result["status"] = (
            "PARKING_PASS"
            if all(result["checks"].values())
            else "PARTIAL"
        )
        return (0 if result["status"] == "PARKING_PASS" else 2), result
    except Exception as exc:
        result["status"] = "PARTIAL"
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        result["collision_events"] = list(collision_events)
        return 5, result
    finally:
        try:
            if host_client is not None:
                result.setdefault("kernel", {})["host_stderr_tail"] = (
                    host_client.stderr_lines[-60:]
                )
                host_client.close()
        except Exception as exc:
            result.setdefault("cleanup_errors", []).append(
                f"host_client: {type(exc).__name__}: {exc}"
            )
        try:
            if bridge is not None:
                bridge.close()
        except Exception as exc:
            result.setdefault("cleanup_errors", []).append(
                f"bridge: {type(exc).__name__}: {exc}"
            )
        try:
            if session is not None:
                cleanup = cleanup_session(
                    session.world, session.actors, session.original
                )
                result["cleanup"] = cleanup
                result["leftover_vln_actors"] = cleanup["leftover_vln_actors"]
                result["settings_after"] = cleanup["settings_after"]
                result["settings_restored"] = cleanup["settings_restored"]
                session.actors = []
        except Exception as exc:
            result.setdefault("cleanup_errors", []).append(
                f"session: {type(exc).__name__}: {exc}"
            )
        result_path = out_dir / "result.json"
        result_path.write_text(
            json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "docs" / "evidence" / "carla-07c"))
    parser.add_argument("--probe-json", default=str(DEFAULT_PROBE))
    parser.add_argument(
        "--maneuver", choices=("forward_arc", "reverse_straight"), default="reverse_straight"
    )
    parser.add_argument("--staging-x", type=float, default=-2.8)
    parser.add_argument("--staging-y", type=float, default=-21.14)
    parser.add_argument("--staging-yaw-deg", type=float, default=0.0)
    parser.add_argument("--spawn-z", type=float, default=6.7)
    parser.add_argument("--slot-x", type=float, default=-9.5)
    parser.add_argument("--slot-y", type=float, default=-21.14)
    parser.add_argument("--slot-heading-deg", type=float, default=0.0)
    parser.add_argument("--arc-radius", type=float, default=3.5)
    parser.add_argument("--path-step-deg", type=float, default=2.5)
    parser.add_argument("--speed-cap", type=float, default=0.35)
    parser.add_argument("--position-tolerance-m", type=float, default=0.25)
    parser.add_argument("--heading-tolerance-deg", type=float, default=5.0)
    parser.add_argument("--final-distance-m", type=float, default=0.12)
    parser.add_argument("--required-clearance-m", type=float, default=0.2)
    parser.add_argument("--collision-margin-m", type=float, default=0.2)
    parser.add_argument("--off-route-lateral-m", type=float, default=0.6)
    parser.add_argument("--off-route-seconds", type=float, default=0.5)
    parser.add_argument("--stuck-speed-mps", type=float, default=0.15)
    parser.add_argument("--stuck-seconds", type=float, default=5.0)
    parser.add_argument("--max-steps", type=int, default=800)
    parser.add_argument("--max-sim-seconds", type=float, default=60.0)
    parser.add_argument("--request-timeout", type=float, default=180.0)
    parser.add_argument("--kernel-host", default=os.environ.get("VLN_KERNEL_HOST_EXE", DEFAULT_KERNEL_HOST))
    parser.add_argument(
        "--bay-boundary-json",
        default=str(
            REPO_ROOT
            / "docs"
            / "evidence"
            / "carla-07c"
            / "bay03_boundary_estimate.json"
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="require an explicit user authorization before moving the vehicle",
    )
    args = parser.parse_args()

    probe = _load_probe(Path(args.probe_json))
    if not args.execute:
        exit_code, result = _run_geometry(args, probe)
    else:
        exit_code, result = _run_motion(args, probe)
    print(json.dumps({k: result.get(k) for k in ("status", "phase", "motion_executed", "reason")}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
