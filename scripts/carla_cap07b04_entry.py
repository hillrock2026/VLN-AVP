#!/usr/bin/env python3
"""M1-VLN-CARLA-CAP-07B-04: bounded Entry into bound bay03.

The run starts from the accepted CAP-07B-03 `ALIGNMENT_COMPLETED` evidence,
re-reads the real CARLA pose, validates it against the alignment final pose,
builds the measured Entry route (connector -> validated 3.56 m arc -> final
straight), issues and consumes an Entry-only permission, and executes at most
one bounded segment per Kernel request.

Every segment:

    real state -> Entry authorization check -> route/preflight geometry
      -> Agent-Kernel parking.move single-use permit -> CARLA bridge
      -> bounded parking controller -> brake -> real post state
      -> independent entry verification

The run finishes with `ENTRY_COMPLETED` only when the independent verifier
accepts the terminal state. It never creates `PARKING_COMPLETED`, never runs a
parking verdict and never performs a parking manoeuvre beyond the declared
Entry route.

Exit codes: 0 ENTRY_COMPLETED, 2 rejected, 3 SAFE_STOP/partial, 4 setup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import carla  # noqa: E402

import carla_parking_nav as nav01b  # noqa: E402
import carla_vln_navigate as nav01e  # noqa: E402
from vln.carla.entry_control import entry_segment_command  # noqa: E402
from vln.carla.entry_route import route_geometry_audit  # noqa: E402
from vln.carla.entry_terminal import (  # noqa: E402
    BoundaryFloorGuard,
    TerminalCorrectionConfig,
    TerminalPhase,
    boundary_floor_guard,
    terminal_footprint_in_buffer,
    terminal_phase_command,
    terminal_phase_improved,
    terminal_phase_plan,
    terminal_reference_in_box,
)
from vln.carla.entry_scene import bay03_entry_route  # noqa: E402
from vln.carla.kernel_bridge import CarlaExecutionBridge  # noqa: E402
from vln.carla.parking_geometry import (  # noqa: E402
    footprint_clearance,
    footprint_polygon_clearance,
)
from vln.carla.parking_verdict import (  # noqa: E402
    BAY03_POLYGON,
    PARKING_FOOTPRINT,
)
from vln.carla.route_control import (  # noqa: E402
    cumulative_lengths,
    point_at_s,
    project_to_path,
)
from vln.carla.session import cleanup_session, leftover_actors  # noqa: E402
from vln.client import HostClient, build_request  # noqa: E402
from vln.intent import AgentIntent, Target  # noqa: E402
from vln.nav.binding_runtime import load_binding_artifact  # noqa: E402
from vln.parking.entry import (  # noqa: E402
    ALIGNMENT_COMPLETED_STAGE,
    AlignmentCompletion,
    EntryBudget,
    EntryStage,
    EntryStability,
    EntryTolerances,
    authorize_entry,
    compute_alignment_completion_id,
    consume_entry_authorization,
    entry_round_improved,
    measure_entry,
    measure_stability,
    revoke_entry_authorization,
    verify_entry,
)

TASK_ID = "cap07b-04"
SKILL_ID = "vln.parking.entry"
EGO_ROLE = "vln_cap07b04_ego"
COLLISION_ROLE = "vln_cap07b04_collision"
FIXED_DT = 0.05
STOP_SPEED_MPS = 0.05
DEFAULT_KERNEL_HOST = (
    "/home/gaosong/workspace/Agentic_Program/m1-vln-carla-02-build/kernel_host"
)
PROJECTION_WINDOW_M = 30.0
FLOOR_PROBE_Z = 7.0
SAFETY_RAY_Z_OFFSET = 0.35
PARKING_STOP_DISTANCE_M = 1.0
PARKING_STATIC_CLEARANCE_M = 0.20


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def _git_state() -> dict:
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, timeout=10
        ).strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            timeout=10,
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--short"], cwd=REPO_ROOT, text=True, timeout=10
        )
        lines = status.splitlines()
        return {
            "head": head,
            "branch": branch,
            "worktree_clean": not lines,
            "status_short_count": len(lines),
            "status_short": lines[:200],
        }
    except Exception as error:
        return {"error": f"{type(error).__name__}: {error}"}


def _settings_dict(settings) -> dict:
    return {
        "synchronous_mode": settings.synchronous_mode,
        "no_rendering_mode": settings.no_rendering_mode,
        "fixed_delta_seconds": settings.fixed_delta_seconds,
        "substepping": settings.substepping,
        "max_substeps": settings.max_substeps,
        "max_substep_delta_time": settings.max_substep_delta_time,
    }


def _state(session, ego) -> dict:
    transform = ego.get_transform()
    velocity = ego.get_velocity()
    return {
        "x": round(transform.location.x, 4),
        "y": round(transform.location.y, 4),
        "z": round(transform.location.z, 4),
        "yaw_deg": round(transform.rotation.yaw, 4),
        "yaw_rad": round(math.radians(transform.rotation.yaw), 6),
        "pitch": round(transform.rotation.pitch, 4),
        "roll": round(transform.rotation.roll, 4),
        "speed": round(math.hypot(velocity.x, velocity.y), 4),
        "frame": int(session.world.get_snapshot().frame),
        "sim_time": round(session.sim_time(), 4),
    }


def _hold_and_sample(session, ego, ticks: int = 5) -> tuple[list[dict], dict]:
    samples: list[dict] = []
    for _ in range(ticks):
        ego.apply_control(
            carla.VehicleControl(throttle=0.0, brake=1.0, steer=0.0)
        )
        session.tick()
        state = _state(session, ego)
        samples.append({"x": state["x"], "y": state["y"], "speed": state["speed"]})
    return samples, _state(session, ego)


def _project(route, x: float, y: float, last_s: float):
    return project_to_path(
        list(route.points),
        list(route.cumulative),
        x,
        y,
        last_s,
        window_m=PROJECTION_WINDOW_M,
    )


def _measure_route(
    session,
    ego,
    route,
    *,
    last_s: float,
    collision_count: int,
    ticks: int = 5,
):
    samples, state = _hold_and_sample(session, ego, ticks)
    stability = measure_stability(samples, route.tolerances)
    s, _px, _py, cross = _project(route, state["x"], state["y"], last_s)
    measurement = measure_entry(
        route,
        x=state["x"],
        y=state["y"],
        yaw_rad=state["yaw_rad"],
        speed_mps=state["speed"],
        stopped=state["speed"] < route.tolerances.stop_speed_mps,
        route_s=s,
        cross_track_m=cross,
        stability=stability,
        collision_count=collision_count,
    )
    return measurement, state, samples, s


def _load_obstacles(path: Path) -> tuple[tuple[float, float], ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return tuple(
            (float(point[0]), float(point[1]))
            for point in payload["obstacle_points"]
        )
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def _load_alignment_completion(
    result_path: Path,
    authorization_path: Path,
    binding,
) -> tuple[AlignmentCompletion, dict]:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    auth = json.loads(authorization_path.read_text(encoding="utf-8"))
    if result.get("status") != "PASS":
        raise ValueError("alignment result is not PASS")
    if result.get("decision") != ALIGNMENT_COMPLETED_STAGE:
        raise ValueError("alignment result decision is not ALIGNMENT_COMPLETED")
    if result.get("task_id") != "cap07b-03":
        raise ValueError("alignment result task is not cap07b-03")
    final_verification = result.get("final_verification")
    if not isinstance(final_verification, dict):
        raise ValueError("alignment result has no final verification")
    if final_verification.get("stage") != ALIGNMENT_COMPLETED_STAGE:
        raise ValueError("alignment final verification is not completed")
    if final_verification.get("completed") is not True:
        raise ValueError("alignment final verification did not complete")
    if final_verification.get("identity_verified") is not True:
        raise ValueError("alignment identity was not verified")
    if result.get("collision_events"):
        raise ValueError("alignment completion has collision events")
    final_state = result.get("final_state")
    final_measurement = result.get("final_measurement")
    if not isinstance(final_state, dict) or not isinstance(final_measurement, dict):
        raise ValueError("alignment result has no final state/measurement")
    if getattr(binding, "status", None) != "bound":
        raise ValueError("binding is not bound")
    if getattr(binding, "bay_id", None) != "bay03" or getattr(
        binding, "slot_node_id", None
    ) != "park_slot":
        raise ValueError("binding is not bay03/park_slot")
    if auth.get("decision") != "ALIGNMENT_AUTHORIZED":
        raise ValueError("alignment authorization is not ALIGNMENT_AUTHORIZED")
    if auth.get("permits_alignment") is not True:
        raise ValueError("alignment authorization does not permit alignment")
    if auth.get("permits_entry") not in (False, None):
        raise ValueError("alignment authorization claims Entry permission")
    if auth.get("revoked") is not False:
        raise ValueError("alignment authorization is revoked")
    if not auth.get("consumed_at"):
        raise ValueError("alignment authorization was not consumed")
    if auth.get("task_id") != "cap07b-03":
        raise ValueError("alignment authorization task mismatch")
    if auth.get("bay_id") != "bay03" or auth.get("slot_node_id") != "park_slot":
        raise ValueError("alignment authorization identity mismatch")
    if auth.get("approach_node_id") != "park_entry":
        raise ValueError("alignment authorization approach mismatch")
    alignment_authorization_id = auth.get("authorization_id")
    if type(alignment_authorization_id) is not str or not alignment_authorization_id:
        raise ValueError("alignment authorization id is missing")
    result_sha = _sha256_file(result_path)
    auth_sha = _sha256_file(authorization_path)
    created_at = result.get("finished_utc") or auth.get("created_at")
    final_pose = (
        float(final_state["x"]),
        float(final_state["y"]),
        float(final_state["yaw_rad"]),
    )
    completion_id = compute_alignment_completion_id(
        task_id="cap07b-03",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        final_pose={"x": final_pose[0], "y": final_pose[1], "yaw": final_pose[2]},
        final_speed_mps=float(final_state.get("speed", 0.0)),
        verification_stage=ALIGNMENT_COMPLETED_STAGE,
        alignment_authorization_id=alignment_authorization_id,
        alignment_result_sha256=result_sha,
        alignment_authorization_sha256=auth_sha,
    )
    completion = AlignmentCompletion(
        task_id="cap07b-03",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        final_pose=final_pose,
        final_speed_mps=float(final_state.get("speed", 0.0)),
        verification_stage=ALIGNMENT_COMPLETED_STAGE,
        alignment_authorization_id=alignment_authorization_id,
        alignment_result_sha256=result_sha,
        alignment_authorization_sha256=auth_sha,
        completion_id=completion_id,
        created_at=created_at,
    )
    return completion, {
        "result": result,
        "authorization": auth,
        "result_sha256": result_sha,
        "authorization_sha256": auth_sha,
    }


def _check_alignment_pose(completion: AlignmentCompletion, actual: dict) -> dict:
    distance = math.hypot(
        actual["x"] - completion.final_pose[0],
        actual["y"] - completion.final_pose[1],
    )
    heading_error = abs(
        (math.degrees(actual["yaw_rad"] - completion.final_pose[2]) + 180.0)
        % 360.0
        - 180.0
    )
    reasons = []
    if distance > 0.15:
        reasons.append(f"alignment_pose_distance={distance:.3f}")
    if heading_error > 2.0:
        reasons.append(f"alignment_pose_heading={heading_error:.3f}")
    if actual["speed"] >= STOP_SPEED_MPS:
        reasons.append(f"alignment_pose_speed={actual['speed']:.3f}")
    return {
        "ok": not reasons,
        "distance_m": round(distance, 4),
        "heading_error_deg": round(heading_error, 4),
        "speed_mps": actual["speed"],
        "reasons": reasons,
    }


def _preflight(session, ego, route, segment, start_s: float) -> dict:
    origins = []
    origin = start_s + PARKING_FOOTPRINT.half_length + PARKING_FOOTPRINT.front_margin
    while origin <= segment.end_s + 1e-6:
        origins.append(round(origin, 3))
        origin += 1.0
    details: dict = {}
    blocked, min_hit, ground = nav01b.safety_check(
        session,
        ego,
        list(route.points),
        list(route.cumulative),
        start_s,
        floor_probe_z=FLOOR_PROBE_Z,
        ray_z_offset=SAFETY_RAY_Z_OFFSET,
        path_origin_s=tuple(origins) if origins else None,
        stop_distance_m=PARKING_STOP_DISTANCE_M,
        min_probe_distance_m=7.0,
        details_out=details,
    )
    state = _state(session, ego)
    s, _px, _py, cross = _project(route, state["x"], state["y"], start_s)
    measurement = measure_entry(
        route,
        x=state["x"],
        y=state["y"],
        yaw_rad=state["yaw_rad"],
        speed_mps=state["speed"],
        stopped=state["speed"] < route.tolerances.stop_speed_mps,
        route_s=s,
        cross_track_m=cross,
        stability=EntryStability(0, state["speed"], 0.0, False),
    )
    reasons = []
    if blocked:
        reasons.append("safety_ray_or_floor_blocked")
    if cross > route.tolerances.route_deviation_m:
        reasons.append("current_route_deviation")
    if (
        measurement.obstacle_clearance_m is not None
        and measurement.obstacle_clearance_m < route.tolerances.obstacle_clearance_m
    ):
        reasons.append("current_obstacle_clearance")
    if not measurement.footprint_corners_inside_corridor:
        reasons.append("current_outside_entry_corridor")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "blocked": bool(blocked),
        "min_hit_m": None if min_hit is None else round(min_hit, 4),
        "ground_z": ground,
        "origins": list(origins),
        "details": details,
        "start_s": round(start_s, 4),
        "segment_end_s": round(segment.end_s, 4),
        "current_pose": state,
        "current_measurement": measurement.to_metadata(),
    }


def _drive_entry_segment(
    session,
    ego,
    route,
    segment,
    *,
    start_s: float,
    budget: EntryBudget,
    baseline_collisions: int,
    collision_events: list[dict],
) -> dict:
    pre = _state(session, ego)
    records: list[dict] = []
    last_s = start_s
    travelled = 0.0
    started_sim = pre["sim_time"]
    started_wall = time.monotonic()
    stop_reason = "step_limit"
    safety_stop = False
    max_steps = int(round(budget.max_segment_sim_seconds / FIXED_DT)) + 100
    max_distance = segment.length_m + 0.60
    try:
        for step in range(max_steps):
            state = _state(session, ego)
            s, _px, _py, cross = _project(
                route, state["x"], state["y"], last_s
            )
            last_s = s
            measurement = measure_entry(
                route,
                x=state["x"],
                y=state["y"],
                yaw_rad=state["yaw_rad"],
                speed_mps=state["speed"],
                stopped=False,
                route_s=s,
                cross_track_m=cross,
                stability=EntryStability(0, state["speed"], 0.0, False),
                collision_count=len(collision_events) - baseline_collisions,
            )
            if len(collision_events) > baseline_collisions:
                stop_reason = "collision"
                safety_stop = True
                break
            if cross > route.tolerances.route_deviation_m:
                stop_reason = "route_deviation"
                safety_stop = True
                break
            if (
                measurement.obstacle_clearance_m is not None
                and measurement.obstacle_clearance_m
                < route.tolerances.obstacle_clearance_m
            ):
                stop_reason = "obstacle_clearance"
                safety_stop = True
                break
            if not measurement.footprint_corners_inside_corridor:
                stop_reason = "outside_entry_corridor"
                safety_stop = True
                break
            safety_blocked, safety_min, safety_ground = nav01b.safety_check(
                session,
                ego,
                list(route.points),
                list(route.cumulative),
                s,
                floor_probe_z=FLOOR_PROBE_Z,
                ray_z_offset=SAFETY_RAY_Z_OFFSET,
                stop_distance_m=PARKING_STOP_DISTANCE_M,
                min_probe_distance_m=7.0,
            )
            if safety_blocked:
                stop_reason = "safety_obstacle"
                safety_stop = True
                break
            distance_to_slot = math.hypot(
                route.target_pose[0] - state["x"],
                route.target_pose[1] - state["y"],
            )
            if s >= segment.end_s - 0.03:
                stop_reason = "segment_end"
                break
            if segment.index == len(route.segments) and distance_to_slot <= 0.08:
                stop_reason = "slot_reached"
                break
            if travelled > max_distance:
                stop_reason = "distance_overshoot"
                safety_stop = True
                break
            if state["sim_time"] - started_sim > budget.max_segment_sim_seconds:
                stop_reason = "time_limit"
                break
            command = entry_segment_command(
                route,
                segment,
                x=state["x"],
                y=state["y"],
                yaw_rad=state["yaw_rad"],
                speed_mps=state["speed"],
                s=s,
                cross_track_m=cross,
                speed_cap_mps=budget.speed_cap_mps,
            )
            ego.apply_control(
                carla.VehicleControl(
                    throttle=float(command.command.throttle),
                    steer=float(command.command.steer),
                    brake=float(command.command.brake),
                )
            )
            session.tick()
            nxt = _state(session, ego)
            travelled = max(travelled, s - start_s)
            records.append(
                {
                    "step": step,
                    "t": nxt["sim_time"],
                    "x": nxt["x"],
                    "y": nxt["y"],
                    "yaw_deg": nxt["yaw_deg"],
                    "speed": nxt["speed"],
                    "route_s": round(s, 4),
                    "cross_track_m": round(cross, 4),
                    "distance_to_slot_m": round(distance_to_slot, 4),
                    "boundary_clearance_m": measurement.boundary_clearance_m,
                    "obstacle_clearance_m": measurement.obstacle_clearance_m,
                    "footprint_inside_bay": measurement.footprint_inside_bay,
                    "corridor_ok": measurement.footprint_corners_inside_corridor,
                    "safety_min_hit_m": None
                    if safety_min is None
                    else round(safety_min, 4),
                    "command": command.to_metadata(),
                    "travelled_m": round(travelled, 4),
                }
            )
    except Exception as error:
        ego.apply_control(
            carla.VehicleControl(throttle=0.0, brake=1.0, steer=0.0)
        )
        return {
            "status": "failed",
            "stop_reason": "controller_exception",
            "error": {"type": type(error).__name__, "message": str(error)},
            "safety_stop": True,
            "phase_success": False,
            "pre_state": {"x": pre["x"], "y": pre["y"], "speed": pre["speed"]},
            "post_state": {"x": pre["x"], "y": pre["y"], "speed": pre["speed"]},
            "stopped": False,
            "moved_m": 0.0,
            "travelled_m": round(travelled, 4),
            "records": records,
        }

    ego.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0, steer=0.0))
    for _ in range(120):
        session.tick()
        if _state(session, ego)["speed"] < 0.03:
            break
    post = _state(session, ego)
    moved = math.hypot(post["x"] - pre["x"], post["y"] - pre["y"])
    return {
        "status": "completed",
        "phase": segment.phase,
        "segment_index": segment.index,
        "stop_reason": stop_reason,
        "safety_stop": safety_stop,
        "phase_success": stop_reason
        in ("segment_end", "slot_reached")
        and not safety_stop,
        "pre_state": {"x": pre["x"], "y": pre["y"], "speed": pre["speed"]},
        "post_state": {"x": post["x"], "y": post["y"], "speed": post["speed"]},
        "pre_full": pre,
        "post_full": post,
        "stopped": post["speed"] < 0.03,
        "moved_m": round(moved, 4),
        "travelled_m": round(travelled, 4),
        "wall_seconds": round(time.monotonic() - started_wall, 3),
        "sim_seconds": round(post["sim_time"] - started_sim, 3),
        "collision_count": len(collision_events) - baseline_collisions,
        "records": records,
    }


def _terminal_preflight(session, ego, route, plan, config, collision_count: int) -> dict:
    points = list(plan.points)
    cumulative = list(cumulative_lengths(points))
    details: dict = {}
    blocked, min_hit, ground = nav01b.safety_check(
        session,
        ego,
        points,
        cumulative,
        0.0,
        floor_probe_z=FLOOR_PROBE_Z,
        ray_z_offset=SAFETY_RAY_Z_OFFSET,
        reverse=plan.reverse,
        stop_distance_m=PARKING_STOP_DISTANCE_M,
        min_probe_distance_m=7.0,
        details_out=details,
    )
    state = _state(session, ego)
    s, _px, _py, cross = _project(route, state["x"], state["y"], 0.0)
    measurement = measure_entry(
        route,
        x=state["x"],
        y=state["y"],
        yaw_rad=state["yaw_rad"],
        speed_mps=state["speed"],
        stopped=state["speed"] < route.tolerances.stop_speed_mps,
        route_s=s,
        cross_track_m=cross,
        stability=EntryStability(0, state["speed"], 0.0, False),
        collision_count=collision_count,
    )
    reasons = []
    if blocked:
        reasons.append("terminal_safety_ray_or_floor_blocked")
    if not terminal_reference_in_box(state["x"], state["y"], config):
        reasons.append("terminal_reference_outside_box")
    if not terminal_footprint_in_buffer(measurement.footprint_corners, route, config):
        reasons.append("terminal_footprint_outside_buffer")
    if (
        measurement.obstacle_clearance_m is not None
        and measurement.obstacle_clearance_m < config.obstacle_clearance_m
    ):
        reasons.append("terminal_obstacle_clearance")
    if collision_count:
        reasons.append("terminal_collision")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "blocked": bool(blocked),
        "min_hit_m": None if min_hit is None else round(min_hit, 4),
        "ground_z": ground,
        "details": details,
        "plan": plan.to_metadata(),
        "current_pose": state,
        "current_measurement": measurement.to_metadata(),
    }


def _drive_terminal_phase(
    session,
    ego,
    route,
    plan,
    *,
    config,
    budget,
    baseline_collisions: int,
    collision_events: list[dict],
    min_boundary_clearance: float | None = None,
) -> dict:
    pre = _state(session, ego)
    records: list[dict] = []
    travelled = 0.0
    started_sim = pre["sim_time"]
    started_wall = time.monotonic()
    stop_reason = "step_limit"
    safety_stop = False
    boundary_floor_enabled = min_boundary_clearance is not None
    boundary_min_seen = None
    boundary_trigger = None
    last_s = _project(route, pre["x"], pre["y"], 0.0)[0]
    max_steps = int(round(plan.max_sim_seconds / FIXED_DT)) + 100
    try:
        for step in range(max_steps):
            state = _state(session, ego)
            s, _px, _py, cross = _project(
                route, state["x"], state["y"], last_s
            )
            last_s = s
            measurement = measure_entry(
                route,
                x=state["x"],
                y=state["y"],
                yaw_rad=state["yaw_rad"],
                speed_mps=state["speed"],
                stopped=False,
                route_s=s,
                cross_track_m=cross,
                stability=EntryStability(0, state["speed"], 0.0, False),
                collision_count=len(collision_events) - baseline_collisions,
            )
            guard = None
            if boundary_floor_enabled:
                # Read the real bounding box on this tick. A sensor/actor
                # read failure must stop motion instead of reusing old state.
                try:
                    bounding_box = ego.bounding_box
                    guard = boundary_floor_guard(
                        floor_m=min_boundary_clearance,
                        x=state["x"],
                        y=state["y"],
                        yaw_rad=state["yaw_rad"],
                        frame=state["frame"],
                        half_length=float(bounding_box.extent.x),
                        half_width=float(bounding_box.extent.y),
                        bbox_offset_x=float(bounding_box.location.x),
                        bbox_offset_y=float(bounding_box.location.y),
                        bay_polygon=route.bay_polygon,
                    )
                except Exception as error:
                    guard = BoundaryFloorGuard.fail(
                        "boundary_state_unreadable",
                        float(min_boundary_clearance),
                        error=f"{type(error).__name__}: {error}",
                        frame=state["frame"],
                    )
                if (
                    guard.clearance_m is not None
                    and (
                        boundary_min_seen is None
                        or guard.clearance_m < boundary_min_seen
                    )
                ):
                    boundary_min_seen = guard.clearance_m
                if guard.triggered:
                    boundary_trigger = guard.to_metadata()
                    stop_reason = guard.reason
                    safety_stop = True
                    records.append(
                        {
                            "step": step,
                            "t": state["sim_time"],
                            "x": state["x"],
                            "y": state["y"],
                            "yaw_deg": state["yaw_deg"],
                            "speed": state["speed"],
                            "boundary_floor_trigger": boundary_trigger,
                            "travelled_m": round(travelled, 4),
                        }
                    )
                    break
            if len(collision_events) > baseline_collisions:
                stop_reason = "collision"
                safety_stop = True
                break
            if not terminal_reference_in_box(state["x"], state["y"], config):
                stop_reason = "terminal_reference_outside_box"
                safety_stop = True
                break
            if not terminal_footprint_in_buffer(
                measurement.footprint_corners, route, config
            ):
                stop_reason = "terminal_footprint_outside_buffer"
                safety_stop = True
                break
            if (
                measurement.obstacle_clearance_m is not None
                and measurement.obstacle_clearance_m < config.obstacle_clearance_m
            ):
                stop_reason = "terminal_obstacle_clearance"
                safety_stop = True
                break
            sign = -1.0 if plan.reverse else 1.0
            probe_path = [
                (state["x"], state["y"]),
                (
                    state["x"] + sign * math.cos(state["yaw_rad"]),
                    state["y"] + sign * math.sin(state["yaw_rad"]),
                ),
            ]
            safety_blocked, safety_min, safety_ground = nav01b.safety_check(
                session,
                ego,
                probe_path,
                cumulative_lengths(probe_path),
                0.0,
                floor_probe_z=FLOOR_PROBE_Z,
                ray_z_offset=SAFETY_RAY_Z_OFFSET,
                reverse=plan.reverse,
                stop_distance_m=PARKING_STOP_DISTANCE_M,
                min_probe_distance_m=7.0,
            )
            if safety_blocked:
                stop_reason = "terminal_safety_obstacle"
                safety_stop = True
                break
            command = terminal_phase_command(
                plan,
                x=state["x"],
                y=state["y"],
                yaw_rad=state["yaw_rad"],
                speed_mps=state["speed"],
                travelled_m=travelled,
                sim_seconds=max(0.0, state["sim_time"] - started_sim),
                config=config,
            )
            if command.done:
                stop_reason = command.done_reason
                break
            ego.apply_control(
                carla.VehicleControl(
                    throttle=float(command.command.throttle),
                    steer=float(command.command.steer),
                    brake=float(command.command.brake),
                    reverse=bool(command.reverse),
                )
            )
            session.tick()
            nxt = _state(session, ego)
            travelled += math.hypot(nxt["x"] - state["x"], nxt["y"] - state["y"])
            records.append(
                {
                    "step": step,
                    "t": nxt["sim_time"],
                    "x": nxt["x"],
                    "y": nxt["y"],
                    "yaw_deg": nxt["yaw_deg"],
                    "speed": nxt["speed"],
                    "route_s": round(s, 4),
                    "distance_to_slot_m": round(command.distance_to_slot_m, 4),
                    "heading_error_deg": round(command.heading_error_deg, 4),
                    "boundary_clearance_m": measurement.boundary_clearance_m,
                    "obstacle_clearance_m": measurement.obstacle_clearance_m,
                    "footprint_inside_bay": measurement.footprint_inside_bay,
                    "safety_min_hit_m": None
                    if safety_min is None
                    else round(safety_min, 4),
                    "boundary_floor_guard": None
                    if guard is None
                    else guard.to_metadata(),
                    "command": command.to_metadata(),
                    "travelled_m": round(travelled, 4),
                }
            )
            if travelled > plan.max_distance_m + 0.10:
                stop_reason = "terminal_distance_overshoot"
                safety_stop = True
                break
            if state["sim_time"] - started_sim > plan.max_sim_seconds:
                stop_reason = "terminal_time_limit"
                break
    except Exception as error:
        ego.apply_control(
            carla.VehicleControl(throttle=0.0, brake=1.0, steer=0.0)
        )
        return {
            "status": "failed",
            "stop_reason": "terminal_controller_exception",
            "error": {"type": type(error).__name__, "message": str(error)},
            "safety_stop": True,
            "phase_success": False,
            "pre_state": {"x": pre["x"], "y": pre["y"], "speed": pre["speed"]},
            "post_state": {"x": pre["x"], "y": pre["y"], "speed": pre["speed"]},
            "stopped": False,
            "moved_m": 0.0,
            "travelled_m": round(travelled, 4),
            "boundary_floor": {
                "enabled": boundary_floor_enabled,
                "floor_m": min_boundary_clearance,
                "min_clearance_m": boundary_min_seen,
                "triggered": boundary_trigger is not None,
                "trigger": boundary_trigger,
            },
            "records": records,
        }
    ego.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0, steer=0.0))
    for _ in range(120):
        session.tick()
        if _state(session, ego)["speed"] < 0.03:
            break
    post = _state(session, ego)
    moved = math.hypot(post["x"] - pre["x"], post["y"] - pre["y"])
    return {
        "status": "completed",
        "phase": plan.phase,
        "stop_reason": stop_reason,
        "safety_stop": safety_stop,
        "phase_success": stop_reason
        in (
            "heading_aligned",
            "slot_aligned",
            "slot_x_reached",
            "distance_limit",
            "time_limit",
        )
        and not safety_stop,
        "pre_state": {"x": pre["x"], "y": pre["y"], "speed": pre["speed"]},
        "post_state": {"x": post["x"], "y": post["y"], "speed": post["speed"]},
        "pre_full": pre,
        "post_full": post,
        "stopped": post["speed"] < 0.03,
        "moved_m": round(moved, 4),
        "travelled_m": round(travelled, 4),
        "wall_seconds": round(time.monotonic() - started_wall, 3),
        "sim_seconds": round(post["sim_time"] - started_sim, 3),
        "collision_count": len(collision_events) - baseline_collisions,
        "boundary_floor": {
            "enabled": boundary_floor_enabled,
            "floor_m": min_boundary_clearance,
            "min_clearance_m": boundary_min_seen,
            "triggered": boundary_trigger is not None,
            "trigger": boundary_trigger,
        },
        "records": records,
    }


def _run_terminal_phase_via_kernel(
    *,
    session,
    ego,
    route,
    plan,
    config,
    budget,
    host_client,
    bridge,
    round_index,
    baseline_collisions,
    collision_events,
) -> dict:
    pre = _state(session, ego)
    intent_id = f"{TASK_ID}-t{round_index:02d}-{pre['frame']}"
    intent = AgentIntent(
        intent_id=intent_id,
        target=Target(
            x=plan.target_x,
            y=plan.target_y,
            heading=plan.target_heading_rad,
        ),
    )
    request_id = f"{TASK_ID}-t{round_index:02d}-req-{pre['frame']}"
    request = build_request(intent, request_id=request_id)
    bridge.register_permit(
        request_id=request_id,
        intent_id=intent.intent_id,
        target=intent.target.to_object(),
        payload=intent.to_payload(),
        context={
            "kind": "terminal",
            "route": route,
            "plan": plan,
            "config": config,
            "budget": budget,
            "baseline_collisions": baseline_collisions,
            "collision_events": collision_events,
            "pre_state": pre,
        },
    )
    kernel_record = {
        "called": True,
        "capability_id": request.capability_id,
        "request_id": request_id,
        "intent_id": intent.intent_id,
        "intent_payload": intent.to_payload(),
        "target": intent.target.to_object(),
        "authorization": (
            "IssueRuntimeExecutionAuthority -> Port().Submit/Observe -> "
            "Runtime::Run -> registered parking.move invoker"
        ),
        "terminal_phase": plan.phase,
        "single_use_permit": True,
    }
    started = time.monotonic()
    try:
        response = host_client.send(request)
        transaction = bridge.get_transaction(request_id)
        error, output = nav01e._validate_kernel_correlation(
            response, request, intent, transaction
        )
        kernel_record.update(
            {
                "request_ok": error is None,
                "error": error,
                "execution_status": response.execution_status,
                "output": output,
                "transaction": transaction,
                "wall_seconds": round(time.monotonic() - started, 3),
            }
        )
        if error is not None:
            return {"ok": False, "error": error, "kernel": kernel_record}
        execution = (
            transaction.get("vehicle")
            if isinstance(transaction, dict)
            else None
        )
        return {
            "ok": True,
            "phase_success": bool(execution and execution.get("phase_success")),
            "execution": execution,
            "kernel": kernel_record,
        }
    except Exception as error:
        kernel_record.update(
            {
                "request_ok": False,
                "error": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(),
            }
        )
        return {
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
            "kernel": kernel_record,
        }


def _run_segment_via_kernel(
    *,
    session,
    ego,
    route,
    segment,
    start_s,
    budget,
    host_client,
    bridge,
    round_index,
    baseline_collisions,
    collision_events,
) -> dict:
    pre = _state(session, ego)
    intent_id = f"{TASK_ID}-s{segment.index:02d}-{pre['frame']}"
    intent = AgentIntent(
        intent_id=intent_id,
        target=Target(
            x=segment.target_x,
            y=segment.target_y,
            heading=segment.target_heading_rad,
        ),
    )
    request_id = f"{TASK_ID}-s{segment.index:02d}-req-{pre['frame']}"
    request = build_request(intent, request_id=request_id)
    bridge.register_permit(
        request_id=request_id,
        intent_id=intent.intent_id,
        target=intent.target.to_object(),
        payload=intent.to_payload(),
        context={
            "route": route,
            "segment": segment,
            "start_s": start_s,
            "budget": budget,
            "baseline_collisions": baseline_collisions,
            "collision_events": collision_events,
            "pre_state": pre,
        },
    )
    kernel_record = {
        "called": True,
        "capability_id": request.capability_id,
        "request_id": request_id,
        "intent_id": intent.intent_id,
        "intent_payload": intent.to_payload(),
        "target": intent.target.to_object(),
        "authorization": (
            "IssueRuntimeExecutionAuthority -> Port().Submit/Observe -> "
            "Runtime::Run -> registered parking.move invoker"
        ),
        "segment_index": segment.index,
        "segment_phase": segment.phase,
        "single_use_permit": True,
    }
    started = time.monotonic()
    try:
        response = host_client.send(request)
        transaction = bridge.get_transaction(request_id)
        error, output = nav01e._validate_kernel_correlation(
            response, request, intent, transaction
        )
        kernel_record.update(
            {
                "request_ok": error is None,
                "error": error,
                "execution_status": response.execution_status,
                "output": output,
                "transaction": transaction,
                "wall_seconds": round(time.monotonic() - started, 3),
            }
        )
        if error is not None:
            return {"ok": False, "error": error, "kernel": kernel_record}
        execution = (
            transaction.get("vehicle")
            if isinstance(transaction, dict)
            else None
        )
        return {
            "ok": True,
            "phase_success": bool(execution and execution.get("phase_success")),
            "execution": execution,
            "kernel": kernel_record,
        }
    except Exception as error:
        kernel_record.update(
            {
                "request_ok": False,
                "error": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(),
            }
        )
        return {
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
            "kernel": kernel_record,
        }


def _refusal(
    *,
    route,
    decision: str,
    reason: str,
    out_dir: Path,
    base: dict,
    exit_code: int,
    completion_id: str = "none",
    alignment_authorization_id: str = "none",
) -> int:
    base.update(
        {
            "status": "SAFE_STOP" if decision == "SAFE_STOP" else decision,
            "decision": decision,
            "error": reason,
            "entry_completed": False,
            "parking_completed": False,
            "finished_utc": _utc_now(),
        }
    )
    if route is not None:
        try:
            from vln.parking.entry import entry_refusal_authorization

            artifact = entry_refusal_authorization(
                route,
                decision,
                reason,
                task_id=TASK_ID,
                completion_id=completion_id,
                alignment_authorization_id=alignment_authorization_id,
            )
            base["entry_authorization"] = artifact.to_metadata()
            _write_json(out_dir / "entry_authorization.json", artifact.to_metadata())
        except Exception as error:
            base["entry_authorization"] = {"error": f"{type(error).__name__}: {error}"}
    _write_json(out_dir / "result.json", base)
    print(json.dumps(base, ensure_ascii=False, indent=2)[:6000])
    return exit_code


def main(argv: list[str] | None = None, *, after_entry=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument(
        "--alignment-result",
        default=str(REPO_ROOT / "docs/evidence/vln-carla-cap-07b-03/result.json"),
    )
    parser.add_argument(
        "--alignment-authorization",
        default=str(
            REPO_ROOT
            / "docs/evidence/vln-carla-cap-07b-03/alignment_authorization.json"
        ),
    )
    parser.add_argument(
        "--binding-json",
        default=str(REPO_ROOT / "docs/evidence/cap07a/A/binding.json"),
    )
    parser.add_argument(
        "--geometry-probe",
        default=str(REPO_ROOT / "docs/evidence/carla-07a/geometry_probe.json"),
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "docs/evidence/vln-carla-cap-07b-04"),
    )
    parser.add_argument("--spawn-z", type=float, default=6.7)
    parser.add_argument("--kernel-host", default=DEFAULT_KERNEL_HOST)
    parser.add_argument("--kernel-exec-timeout-ms", type=int, default=180000)
    parser.add_argument("--max-segments", type=int, default=8)
    parser.add_argument("--ttl-s", type=float, default=600.0)
    parser.add_argument(
        "--keep-vehicle",
        action="store_true",
        help=(
            "hand off a successful Entry to a following stage: keep the ego "
            "actor alive, destroy other run actors, leave world settings as-is "
            "and write a handoff record"
        ),
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = _utc_now()
    base: dict = {
        "schema": "vln.cap07b04.result.v1",
        "skill": SKILL_ID,
        "task_id": TASK_ID,
        "started_utc": started,
        "git": _git_state(),
        "model": {
            "calls": 0,
            "reason": "Entry executes the already verified route deterministically; no new Taichu call is needed",
        },
        "entry_completed": False,
        "parking_completed": False,
        "rounds": [],
        "kernel_executions": 0,
    }

    completion = None
    alignment_evidence = None
    route = None
    route_audit = None
    ego = None
    budget = EntryBudget(max_segments=args.max_segments)
    try:
        binding = load_binding_artifact(args.binding_json)
        completion, alignment_evidence = _load_alignment_completion(
            Path(args.alignment_result),
            Path(args.alignment_authorization),
            binding,
        )
        base["alignment_completion"] = completion.to_metadata()
        base["alignment_evidence"] = {
            "result": alignment_evidence["result"],
            "authorization": alignment_evidence["authorization"],
            "result_sha256": alignment_evidence["result_sha256"],
            "authorization_sha256": alignment_evidence["authorization_sha256"],
        }
        base["binding"] = binding.to_metadata()
        obstacles = _load_obstacles(Path(args.geometry_probe))
        base["obstacle_point_count"] = len(obstacles)
        base["obstacles"] = [list(point) for point in obstacles]
        terminal_config = TerminalCorrectionConfig()
        base["terminal_correction_policy"] = terminal_config.to_metadata()
    except Exception as error:
        base["status"] = "ENTRY_REJECTED"
        base["decision"] = EntryStage.REJECTED
        base["error"] = f"precondition failed: {type(error).__name__}: {error}"
        base["finished_utc"] = _utc_now()
        _write_json(out_dir / "result.json", base)
        print(json.dumps(base, ensure_ascii=False, indent=2)[:6000])
        return 4

    session = None
    bridge = None
    host_client = None
    collision_events: list[dict] = []
    collision_lock = threading.Lock()
    round_records: list[dict] = []
    all_trace_poses: list[tuple[float, float, float]] = []
    initial_measurement = None
    final_measurement = None
    final_verification = None
    last_s = 0.0
    authorization = None
    try:
        session = nav01b.Session(
            args.host, args.port, str(out_dir), map_name="UndergroundCarPark"
        )
        base["carla"] = {
            "server_version": session.client.get_server_version(),
            "map": session.world.get_map().name,
            "synchronous_mode": session.world.get_settings().synchronous_mode,
        }
        leftovers = leftover_actors(session.world)
        if leftovers:
            raise RuntimeError(
                "world already contains vln_ actors; refusing to run Entry on an unknown scene"
            )
        ego = session.spawn_vehicle(
            EGO_ROLE,
            completion.final_pose[0],
            completion.final_pose[1],
            args.spawn_z,
            math.degrees(completion.final_pose[2]),
        )
        session.tick(40)
        ego.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))
        session.tick(10)
        actual = _state(session, ego)
        base["restored_pose"] = actual
        base["alignment_expected_pose"] = {
            "x": round(completion.final_pose[0], 4),
            "y": round(completion.final_pose[1], 4),
            "yaw_deg": round(math.degrees(completion.final_pose[2]), 4),
        }
        extent = ego.bounding_box.extent
        base["vehicle"] = {
            "type_id": ego.type_id,
            "half_extent": {
                "x": round(float(extent.x), 4),
                "y": round(float(extent.y), 4),
                "z": round(float(extent.z), 4),
            },
            "footprint_config": PARKING_FOOTPRINT.to_metadata(),
        }
        if abs(float(extent.x) - PARKING_FOOTPRINT.half_length) > 0.05 or abs(
            float(extent.y) - PARKING_FOOTPRINT.half_width
        ) > 0.05:
            raise RuntimeError(
                "vehicle bounding box differs from the measured footprint"
            )
        pose_gate = _check_alignment_pose(completion, actual)
        base["alignment_pose_gate"] = pose_gate
        if not pose_gate["ok"]:
            return _refusal(
                route=None,
                decision=EntryStage.REJECTED,
                reason="restored pose is not the alignment final pose: "
                + ", ".join(pose_gate["reasons"]),
                out_dir=out_dir,
                base=base,
                exit_code=2,
                completion_id=completion.completion_id,
                alignment_authorization_id=completion.alignment_authorization_id,
            )
        try:
            route, route_audit = bay03_entry_route(
                task_id=TASK_ID,
                actual_pose=(actual["x"], actual["y"], actual["yaw_rad"]),
                obstacle_points=obstacles,
                budget=budget,
            )
        except Exception as error:
            return _refusal(
                route=None,
                decision=EntryStage.REJECTED,
                reason=f"entry route geometry failed: {type(error).__name__}: {error}",
                out_dir=out_dir,
                base=base,
                exit_code=2,
                completion_id=completion.completion_id,
                alignment_authorization_id=completion.alignment_authorization_id,
            )
        base["route"] = route.to_metadata()
        base["route_geometry_audit"] = route_audit
        _write_json(out_dir / "entry_route.json", route.to_metadata())
        try:
            authorization = authorize_entry(
                completion,
                route,
                binding=binding,
                task_id=TASK_ID,
                ttl_s=args.ttl_s,
                budget=budget,
                actual_pose=(actual["x"], actual["y"], actual["yaw_rad"]),
                terminal_correction_policy=terminal_config.to_metadata(),
            )
        except Exception as error:
            return _refusal(
                route=route,
                decision=EntryStage.REJECTED,
                reason=f"entry authorization failed: {type(error).__name__}: {error}",
                out_dir=out_dir,
                base=base,
                exit_code=2,
                completion_id=completion.completion_id,
                alignment_authorization_id=completion.alignment_authorization_id,
            )
        authorization = consume_entry_authorization(
            authorization,
            task_id=TASK_ID,
            bay_id=route.bay_id,
            slot_node_id=route.slot_node_id,
            approach_node_id=route.approach_node_id,
            route_id=route.route_id,
            route_hash=route.route_hash,
        )
        base["entry_authorization"] = authorization.to_metadata()
        _write_json(out_dir / "entry_authorization.json", authorization.to_metadata())

        collision_bp = session.world.get_blueprint_library().find(
            "sensor.other.collision"
        )
        collision_bp.set_attribute("role_name", COLLISION_ROLE)
        collision_sensor = session.world.spawn_actor(
            collision_bp, carla.Transform(), attach_to=ego
        )
        session.actors.append(collision_sensor)

        def _on_collision(event):
            try:
                record = {
                    "frame": int(session.world.get_snapshot().frame),
                    "other_actor_id": int(event.other_actor.id),
                    "other_actor_type": event.other_actor.type_id,
                    "normal_impulse": {
                        "x": round(float(event.normal_impulse.x), 4),
                        "y": round(float(event.normal_impulse.y), 4),
                        "z": round(float(event.normal_impulse.z), 4),
                    },
                }
            except Exception as error:
                record = {"error": f"{type(error).__name__}: {error}"}
            with collision_lock:
                collision_events.append(record)

        collision_sensor.listen(_on_collision)
        collision_monitor = {
            "sensor_role": COLLISION_ROLE,
            "sensor_id": int(collision_sensor.id),
            "started_frame": int(session.world.get_snapshot().frame),
            "started_utc": _utc_now(),
        }

        initial_measurement, initial_state, initial_samples, last_s = _measure_route(
            session,
            ego,
            route,
            last_s=0.0,
            collision_count=len(collision_events),
        )
        initial_verification = verify_entry(
            route,
            completion,
            authorization,
            binding=binding,
            measurement=initial_measurement,
            collision_count=len(collision_events),
        )
        base["initial_state"] = initial_state
        base["initial_stability_samples"] = initial_samples
        base["initial_measurement"] = initial_measurement.to_metadata()
        base["initial_verification"] = initial_verification.to_metadata()
        _write_json(
            out_dir / "entry_state_initial.json",
            {
                "state": initial_state,
                "stability_samples": initial_samples,
                "measurement": initial_measurement.to_metadata(),
                "verification": initial_verification.to_metadata(),
            },
        )
        all_trace_poses.append(
            (initial_state["x"], initial_state["y"], initial_state["yaw_rad"])
        )
        if initial_verification.stage in (
            EntryStage.REJECTED,
            EntryStage.SAFE_STOP,
        ):
            return _refusal(
                route=route,
                decision=initial_verification.stage,
                reason="initial verification: "
                + ", ".join(initial_verification.reasons),
                out_dir=out_dir,
                base=base,
                exit_code=3
                if initial_verification.stage == EntryStage.SAFE_STOP
                else 2,
                completion_id=completion.completion_id,
                alignment_authorization_id=completion.alignment_authorization_id,
            )
        if initial_verification.completed:
            base["status"] = "PASS"
            base["decision"] = EntryStage.COMPLETED
            base["entry_completed"] = True
            base["zero_motion_reason"] = (
                "the restored real pose already satisfied the Entry terminal "
                "conditions; no motion was needed"
            )
            _write_final(base, out_dir, route, completion, authorization, initial_state,
                         initial_measurement, initial_verification, collision_events,
                         all_trace_poses, budget, round_records, final_samples=initial_samples)
            return 0

        def _handle_kernel_execution(permit):
            context = permit.context
            if context.get("kind") == "terminal":
                return _drive_terminal_phase(
                    session,
                    ego,
                    context["route"],
                    context["plan"],
                    config=context["config"],
                    budget=context["budget"],
                    baseline_collisions=context["baseline_collisions"],
                    collision_events=context["collision_events"],
                    min_boundary_clearance=context.get("min_boundary_clearance"),
                )
            return _drive_entry_segment(
                session,
                ego,
                context["route"],
                context["segment"],
                start_s=context["start_s"],
                budget=context["budget"],
                baseline_collisions=context["baseline_collisions"],
                collision_events=context["collision_events"],
            )

        bridge = CarlaExecutionBridge(
            _handle_kernel_execution, request_timeout_s=180.0
        )
        bridge.start()
        host_env = {
            **os.environ.copy(),
            "VLN_CARLA_EXEC_BRIDGE": bridge.endpoint,
            "VLN_CARLA_EXEC_TOKEN": bridge.token,
            "VLN_CARLA_EXEC_TIMEOUT_MS": str(args.kernel_exec_timeout_ms),
        }
        host_client = HostClient([args.kernel_host], env=host_env)
        base["agent_kernel"] = {
            "host_exe": args.kernel_host,
            "bridge_endpoint": bridge.endpoint,
            "capability_id": "parking.move",
            "capability_provider": "vln.parking.carla",
            "single_use_permits": True,
            "token_recorded": False,
            "execution_timeout_ms": args.kernel_exec_timeout_ms,
        }

        measurement = initial_measurement
        state = initial_state
        stop_reason = None
        main_route_done = False
        terminal_trace_poses: list[tuple[float, float, float]] = []
        for round_index in range(1, budget.max_segments + 1):
            if not authorization.is_active(
                task_id=TASK_ID,
                bay_id=route.bay_id,
                slot_node_id=route.slot_node_id,
                approach_node_id=route.approach_node_id,
                route_id=route.route_id,
                route_hash=route.route_hash,
            ):
                stop_reason = "entry_authorization_inactive"
                break
            if not budget.can_start_segment:
                stop_reason = "entry_budget_exhausted"
                break
            current_verification = verify_entry(
                route,
                completion,
                authorization,
                binding=binding,
                measurement=measurement,
                collision_count=len(collision_events),
            )
            if current_verification.completed:
                break
            if current_verification.stage in (
                EntryStage.REJECTED,
                EntryStage.SAFE_STOP,
            ):
                stop_reason = "verification_" + current_verification.stage
                break
            segment = route.segment_for_s(last_s)
            if last_s >= segment.end_s - 0.05 and segment.index < len(route.segments):
                segment = route.segments[segment.index]
            before = measurement
            preflight = _preflight(session, ego, route, segment, last_s)
            round_record = {
                "round": round_index,
                "segment": segment.to_metadata(),
                "pre_state": state,
                "pre_measurement": measurement.to_metadata(),
                "pre_verification": current_verification.to_metadata(),
                "safety_preflight": preflight,
                "kernel": None,
                "post_state": None,
                "post_measurement": None,
                "post_verification": None,
                "improvement": None,
                "budget_before": budget.to_metadata(),
            }
            round_records.append(round_record)
            if not preflight["ok"]:
                stop_reason = "safety_preflight: " + ", ".join(preflight["reasons"])
                break
            kernel_result = _run_segment_via_kernel(
                session=session,
                ego=ego,
                route=route,
                segment=segment,
                start_s=last_s,
                budget=budget,
                host_client=host_client,
                bridge=bridge,
                round_index=round_index,
                baseline_collisions=len(collision_events),
                collision_events=collision_events,
            )
            base["kernel_executions"] += 1
            round_record["kernel"] = kernel_result["kernel"]
            if not kernel_result["ok"]:
                stop_reason = "kernel_execution_failed: " + str(kernel_result["error"])
                break
            measurement, state, post_samples, last_s = _measure_route(
                session,
                ego,
                route,
                last_s=last_s,
                collision_count=len(collision_events),
            )
            post_verification = verify_entry(
                route,
                completion,
                authorization,
                binding=binding,
                measurement=measurement,
                collision_count=len(collision_events),
            )
            execution = kernel_result["execution"] or {}
            travelled = float(
                execution.get("travelled_m") or execution.get("moved_m") or 0.0
            )
            sim_seconds = float(execution.get("sim_seconds") or 0.0)
            round_record.update(
                {
                    "post_state": state,
                    "post_stability_samples": post_samples,
                    "post_measurement": measurement.to_metadata(),
                    "post_verification": post_verification.to_metadata(),
                    "execution": {
                        key: execution.get(key)
                        for key in (
                            "status",
                            "phase",
                            "segment_index",
                            "stop_reason",
                            "safety_stop",
                            "phase_success",
                            "stopped",
                            "moved_m",
                            "travelled_m",
                            "wall_seconds",
                            "sim_seconds",
                            "collision_count",
                        )
                    },
                }
            )
            for record in execution.get("records", []) or []:
                all_trace_poses.append(
                    (
                        float(record["x"]),
                        float(record["y"]),
                        math.radians(float(record["yaw_deg"])),
                    )
                )
            all_trace_poses.append((state["x"], state["y"], state["yaw_rad"]))
            improved, improvement_reasons = entry_round_improved(
                route, before=before, after=measurement, segment=segment
            )
            round_record["improvement"] = {
                "ok": improved,
                "reasons": list(improvement_reasons),
                "before": before.to_metadata(),
                "after": measurement.to_metadata(),
            }
            budget = budget.record_segment(travelled, sim_seconds)
            round_record["budget_after"] = budget.to_metadata()
            _write_json(out_dir / "entry_rounds.json", {"rounds": round_records})
            if not improved:
                stop_reason = "segment_did_not_improve: " + ", ".join(
                    improvement_reasons
                )
                break
            if not kernel_result["phase_success"]:
                stop_reason = "segment_execution_incomplete"
                break
            if post_verification.stage in (
                EntryStage.REJECTED,
                EntryStage.SAFE_STOP,
            ):
                stop_reason = "post_verification_" + post_verification.stage
                break
            if post_verification.completed:
                break
            if last_s >= route.length_m - 0.40:
                main_route_done = True
                break

        # Bounded Entry terminal alignment: the validated charger understeers
        # on the 3.56 m arc, so the historical parking pipeline used a short
        # reverse arc + forward straight inside the bay. CAP-07B-04 reuses the
        # same bounded geometry as two separately authorized Entry segments.
        correction_round = len(round_records)
        if stop_reason is None:
            main_verification = verify_entry(
                route,
                completion,
                authorization,
                binding=binding,
                measurement=measurement,
                collision_count=len(collision_events),
            )
            eligible = (
                not main_verification.completed
                and measurement.distance_to_target_m <= 0.60
                and abs(measurement.heading_error_deg) <= 20.0
                and terminal_reference_in_box(
                    measurement.x, measurement.y, terminal_config
                )
                and (
                    measurement.obstacle_clearance_m is None
                    or measurement.obstacle_clearance_m
                    >= terminal_config.obstacle_clearance_m
                )
                and not collision_events
                and budget.can_start_segment
            )
            if eligible:
                for phase in (
                    TerminalPhase.REVERSE_ALIGN,
                    TerminalPhase.FORWARD_RETURN,
                ):
                    if not authorization.is_active(
                        task_id=TASK_ID,
                        bay_id=route.bay_id,
                        slot_node_id=route.slot_node_id,
                        approach_node_id=route.approach_node_id,
                        route_id=route.route_id,
                        route_hash=route.route_hash,
                    ):
                        stop_reason = "entry_authorization_inactive"
                        break
                    if not budget.can_start_segment:
                        stop_reason = "entry_budget_exhausted"
                        break
                    plan = terminal_phase_plan(
                        route, measurement, phase, config=terminal_config
                    )
                    preflight = _terminal_preflight(
                        session,
                        ego,
                        route,
                        plan,
                        terminal_config,
                        len(collision_events),
                    )
                    correction_round += 1
                    correction_record = {
                        "round": correction_round,
                        "kind": "terminal_correction",
                        "terminal_phase": phase,
                        "plan": plan.to_metadata(),
                        "pre_state": _state(session, ego),
                        "pre_measurement": measurement.to_metadata(),
                        "safety_preflight": preflight,
                        "kernel": None,
                        "post_state": None,
                        "post_measurement": None,
                        "post_verification": None,
                        "improvement": None,
                        "budget_before": budget.to_metadata(),
                    }
                    round_records.append(correction_record)
                    if not preflight["ok"]:
                        stop_reason = "terminal_preflight: " + ", ".join(
                            preflight["reasons"]
                        )
                        break
                    before = measurement
                    kernel_result = _run_terminal_phase_via_kernel(
                        session=session,
                        ego=ego,
                        route=route,
                        plan=plan,
                        config=terminal_config,
                        budget=budget,
                        host_client=host_client,
                        bridge=bridge,
                        round_index=correction_round,
                        baseline_collisions=len(collision_events),
                        collision_events=collision_events,
                    )
                    base["kernel_executions"] += 1
                    correction_record["kernel"] = kernel_result["kernel"]
                    if not kernel_result["ok"]:
                        stop_reason = "terminal_kernel_failed: " + str(
                            kernel_result["error"]
                        )
                        break
                    measurement, state, post_samples, last_s = _measure_route(
                        session,
                        ego,
                        route,
                        last_s=last_s,
                        collision_count=len(collision_events),
                    )
                    post_verification = verify_entry(
                        route,
                        completion,
                        authorization,
                        binding=binding,
                        measurement=measurement,
                        collision_count=len(collision_events),
                    )
                    execution = kernel_result["execution"] or {}
                    travelled = float(
                        execution.get("travelled_m")
                        or execution.get("moved_m")
                        or 0.0
                    )
                    sim_seconds = float(execution.get("sim_seconds") or 0.0)
                    correction_record.update(
                        {
                            "post_state": state,
                            "post_stability_samples": post_samples,
                            "post_measurement": measurement.to_metadata(),
                            "post_verification": post_verification.to_metadata(),
                            "execution": {
                                key: execution.get(key)
                                for key in (
                                    "status",
                                    "phase",
                                    "stop_reason",
                                    "safety_stop",
                                    "phase_success",
                                    "stopped",
                                    "moved_m",
                                    "travelled_m",
                                    "wall_seconds",
                                    "sim_seconds",
                                    "collision_count",
                                )
                            },
                        }
                    )
                    for record in execution.get("records", []) or []:
                        terminal_trace_poses.append(
                            (
                                float(record["x"]),
                                float(record["y"]),
                                math.radians(float(record["yaw_deg"])),
                            )
                        )
                    terminal_trace_poses.append(
                        (state["x"], state["y"], state["yaw_rad"])
                    )
                    improved, improvement_reasons = terminal_phase_improved(
                        phase,
                        before=before,
                        after=measurement,
                        route=route,
                        config=terminal_config,
                    )
                    correction_record["improvement"] = {
                        "ok": improved,
                        "reasons": list(improvement_reasons),
                        "before": before.to_metadata(),
                        "after": measurement.to_metadata(),
                    }
                    budget = budget.record_segment(travelled, sim_seconds)
                    correction_record["budget_after"] = budget.to_metadata()
                    _write_json(
                        out_dir / "entry_rounds.json",
                        {"rounds": round_records},
                    )
                    if not improved:
                        stop_reason = "terminal_phase_did_not_improve: " + ", ".join(
                            improvement_reasons
                        )
                        break
                    if not kernel_result["phase_success"]:
                        stop_reason = "terminal_phase_incomplete"
                        break
                    if post_verification.completed:
                        break
                    # The reverse terminal segment intentionally leaves the
                    # forward route; the main-route deviation/corridor checks
                    # only apply after the forward return.
                    if phase == TerminalPhase.FORWARD_RETURN and post_verification.stage in (
                        EntryStage.REJECTED,
                        EntryStage.SAFE_STOP,
                    ):
                        stop_reason = "terminal_post_verification_" + post_verification.stage
                        break

        session.brake_to_stop(ego, max_ticks=120)
        final_measurement, final_state, final_samples, _final_s = _measure_route(
            session,
            ego,
            route,
            last_s=last_s,
            collision_count=len(collision_events),
            ticks=5,
        )
        final_verification = verify_entry(
            route,
            completion,
            authorization,
            binding=binding,
            measurement=final_measurement,
            collision_count=len(collision_events),
        )
        trace_audit = _trace_geometry_audit(route, all_trace_poses)
        terminal_audit = _terminal_trace_audit(
            route,
            terminal_config,
            terminal_trace_poses,
            final_measurement,
            len(collision_events),
        )
        success = (
            final_verification.completed
            and stop_reason is None
            and not collision_events
            and trace_audit["ok"]
            and terminal_audit["ok"]
            and final_state["speed"] < route.tolerances.stop_speed_mps
            and final_measurement.stability.stable
            and budget.distance_used_m <= budget.max_total_distance_m
        )
        base["status"] = "PASS" if success else "PARTIAL"
        base["decision"] = final_verification.stage
        base["entry_completed"] = final_verification.completed
        base["parking_completed"] = False
        base["stop_reason"] = stop_reason
        base["finished_utc"] = _utc_now()
        if not success:
            base["error"] = stop_reason or "final verification: " + ", ".join(
                final_verification.reasons
            )
            try:
                revoked = revoke_entry_authorization(
                    authorization, base["error"]
                )
                base["entry_authorization"] = revoked.to_metadata()
                _write_json(
                    out_dir / "entry_authorization.json", revoked.to_metadata()
                )
            except Exception:
                pass
        _write_final(
            base,
            out_dir,
            route,
            completion,
            authorization,
            final_state,
            final_measurement,
            final_verification,
            collision_events,
            all_trace_poses,
            budget,
            round_records,
            final_samples=final_samples,
            trace_audit=trace_audit,
            terminal_trace_audit=terminal_audit,
        )
        if after_entry is not None and final_verification.completed:
            try:
                after_entry(
                    session=session,
                    ego=ego,
                    route=route,
                    completion=completion,
                    entry_authorization=authorization,
                    final_state=final_state,
                    final_measurement=final_measurement,
                    final_verification=final_verification,
                    collision_events=collision_events,
                    collision_monitor=collision_monitor,
                    budget=budget,
                    round_records=round_records,
                    out_dir=out_dir,
                    bridge=bridge,
                    host_client=host_client,
                    binding=binding,
                )
                base["after_entry"] = {"called": True, "ok": True}
            except Exception as error:
                base["after_entry"] = {
                    "called": True,
                    "ok": False,
                    "error": f"{type(error).__name__}: {error}",
                    "traceback": traceback.format_exc(),
                }
                _write_json(out_dir / "result.json", base)
        print(
            json.dumps(
                {
                    "status": base["status"],
                    "decision": base["decision"],
                    "bay_id": route.bay_id,
                    "initial": {
                        "x": initial_state["x"],
                        "y": initial_state["y"],
                        "yaw_deg": initial_state["yaw_deg"],
                    },
                    "final": {
                        "x": final_state["x"],
                        "y": final_state["y"],
                        "yaw_deg": final_state["yaw_deg"],
                        "distance_to_slot_m": round(
                            final_measurement.distance_to_target_m, 4
                        ),
                        "heading_error_deg": round(
                            final_measurement.heading_error_deg, 4
                        ),
                        "boundary_clearance_m": final_measurement.boundary_clearance_m,
                        "obstacle_clearance_m": final_measurement.obstacle_clearance_m,
                        "footprint_inside_bay": final_measurement.footprint_inside_bay,
                    },
                    "rounds": len(round_records),
                    "collisions": len(collision_events),
                    "final_speed": final_state["speed"],
                    "entry_completed": final_verification.completed,
                    "parking_completed": False,
                    "reason": base.get("error"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if success else 3
    except Exception as error:
        base["status"] = "SAFE_STOP"
        base["decision"] = EntryStage.SAFE_STOP
        base["error"] = f"{type(error).__name__}: {error}"
        base["traceback"] = traceback.format_exc()
        base["finished_utc"] = _utc_now()
        base["collision_events"] = list(collision_events)
        try:
            if authorization is not None:
                revoked = revoke_entry_authorization(authorization, base["error"])
                base["entry_authorization"] = revoked.to_metadata()
                _write_json(
                    out_dir / "entry_authorization.json", revoked.to_metadata()
                )
        except Exception:
            pass
        _write_json(out_dir / "result.json", base)
        print(json.dumps(base, ensure_ascii=False, indent=2)[:6000])
        return 3
    finally:
        if bridge is not None:
            try:
                transactions = bridge.transactions
                with (out_dir / "kernel_bridge_transactions.jsonl").open(
                    "w", encoding="utf-8"
                ) as handle:
                    for transaction in transactions:
                        handle.write(json.dumps(transaction, ensure_ascii=False) + "\n")
            except Exception as error:
                print(f"bridge evidence error: {type(error).__name__}: {error}", file=sys.stderr)
        if host_client is not None:
            try:
                (out_dir / "kernel_host_stderr.log").write_text(
                    "".join(host_client.stderr_lines), encoding="utf-8"
                )
                host_client.close()
            except Exception as error:
                print(f"host cleanup error: {type(error).__name__}: {error}", file=sys.stderr)
        if bridge is not None:
            try:
                bridge.close()
            except Exception as error:
                print(f"bridge cleanup error: {type(error).__name__}: {error}", file=sys.stderr)
        if session is not None:
            keep_handoff = bool(
                args.keep_vehicle
                and ego is not None
                and getattr(ego, "is_alive", False)
                and base.get("status") == "PASS"
            )
            if keep_handoff:
                destroy_errors = []
                for actor in reversed(list(session.actors)):
                    if actor is ego:
                        continue
                    try:
                        if getattr(actor, "is_alive", True):
                            actor.destroy()
                    except Exception as error:
                        destroy_errors.append(f"{type(error).__name__}: {error}")
                session.actors = [ego]
                handoff_state = _state(session, ego)
                base["handoff"] = {
                    "kept_vehicle_actor_id": int(ego.id),
                    "role_name": EGO_ROLE,
                    "type_id": ego.type_id,
                    "pose": handoff_state,
                    "destroy_errors": destroy_errors,
                    "settings": _settings_dict(session.world.get_settings()),
                    "settings_restored": False,
                    "note": (
                        "world settings are intentionally left in the Entry "
                        "synchronous mode for the following stage; the next "
                        "session snapshots and restores them"
                    ),
                }
                _write_json(out_dir / "result.json", base)
            else:
                try:
                    cleanup = cleanup_session(session.world, session.actors, session.original)
                    session.actors = []
                    base["cleanup"] = {
                        "destroy_errors": cleanup["destroy_errors"],
                        "leftover_vln_actors": cleanup["leftover_vln_actors"],
                    }
                    base["settings"] = {
                        "before": session.original,
                        "after": cleanup["settings_after"],
                        "restored": cleanup["settings_restored"],
                    }
                    _write_json(out_dir / "result.json", base)
                except Exception as error:
                    print(f"cleanup error: {type(error).__name__}: {error}", file=sys.stderr)
        try:
            (out_dir / "run.log").write_text(
                json.dumps(
                    {
                        "started_utc": started,
                        "finished_utc": _utc_now(),
                        "status": base.get("status"),
                        "decision": base.get("decision"),
                        "entry_completed": base.get("entry_completed"),
                        "parking_completed": base.get("parking_completed"),
                        "error": base.get("error"),
                        "rounds": len(round_records),
                        "kernel_executions": base.get("kernel_executions"),
                        "collision_events": len(collision_events),
                        "budget": base.get("budget"),
                        "cleanup": base.get("cleanup"),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except Exception as error:
            print(f"run.log error: {type(error).__name__}: {error}", file=sys.stderr)


def _trace_geometry_audit(route, poses) -> dict:
    """Aggregate the real trajectory against the route/bay/obstacle guards."""

    reasons: list[str] = []
    min_boundary = None
    min_obstacle = None
    max_deviation = 0.0
    corridor_violations = 0
    last_s = 0.0
    for index, (x, y, yaw) in enumerate(poses):
        s, _px, _py, cross = _project(route, x, y, last_s)
        last_s = s
        max_deviation = max(max_deviation, cross)
        if cross > route.tolerances.route_deviation_m:
            reasons.append(f"pose_{index}_route_deviation={cross:.3f}")
        corners = route.footprint.corners(x, y, yaw)
        inside = all(
            -14.4 <= cx <= -4.0 and -22.39 <= cy <= -19.89 for cx, cy in corners
        )
        if not inside:
            if not all(
                route.distance_to_route(cx, cy) <= route.tolerances.corridor_half_width_m
                or route.point_in_start_cap(cx, cy)
                for cx, cy in corners
            ):
                corridor_violations += 1
        clearance = footprint_polygon_clearance(
            x, y, yaw, route.footprint, route.bay_polygon
        )["min_clearance_m"]
        if clearance is not None and (min_boundary is None or clearance < min_boundary):
            min_boundary = clearance
        if route.obstacle_points:
            obstacle = footprint_clearance(
                x, y, yaw, route.footprint, route.obstacle_points
            )["min_clearance_m"]
            if obstacle is not None and (
                min_obstacle is None or obstacle < min_obstacle
            ):
                min_obstacle = obstacle
            if obstacle is not None and obstacle < route.tolerances.obstacle_clearance_m:
                reasons.append(f"pose_{index}_obstacle_clearance={obstacle:.3f}")
    if corridor_violations:
        reasons.append(f"corridor_violations={corridor_violations}")
    return {
        "ok": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "pose_count": len(poses),
        "max_route_deviation_m": round(max_deviation, 4),
        "min_footprint_to_bay_clearance_m": None
        if min_boundary is None
        else round(min_boundary, 4),
        "min_obstacle_clearance_m": None
        if min_obstacle is None
        else round(min_obstacle, 4),
        "corridor_violations": corridor_violations,
        "final_footprint_inside_bay": all(
            -14.4 <= cx <= -4.0 and -22.39 <= cy <= -19.89
            for cx, cy in route.footprint.corners(*poses[-1])
        )
        if poses
        else False,
    }


def _terminal_trace_audit(
    route,
    config,
    poses,
    final_measurement,
    collision_count: int,
) -> dict:
    reasons: list[str] = []
    min_obstacle = None
    min_boundary = None
    for index, (x, y, yaw) in enumerate(poses):
        if not terminal_reference_in_box(x, y, config):
            reasons.append(f"terminal_pose_{index}_outside_box")
        corners = route.footprint.corners(x, y, yaw)
        if not terminal_footprint_in_buffer(corners, route, config):
            reasons.append(f"terminal_pose_{index}_outside_buffer")
        if route.obstacle_points:
            obstacle = footprint_clearance(
                x, y, yaw, route.footprint, route.obstacle_points
            )["min_clearance_m"]
            if obstacle is not None and (
                min_obstacle is None or obstacle < min_obstacle
            ):
                min_obstacle = obstacle
            if obstacle is not None and obstacle < config.obstacle_clearance_m:
                reasons.append(f"terminal_pose_{index}_obstacle_clearance")
        boundary = footprint_polygon_clearance(
            x, y, yaw, route.footprint, route.bay_polygon
        )["min_clearance_m"]
        if boundary is not None and (min_boundary is None or boundary < min_boundary):
            min_boundary = boundary
    if collision_count:
        reasons.append("terminal_collision")
    if final_measurement is not None:
        if not final_measurement.footprint_inside_bay:
            reasons.append("final_footprint_not_inside_bay")
        if (
            final_measurement.boundary_clearance_m is None
            or final_measurement.boundary_clearance_m
            < route.tolerances.boundary_clearance_m
        ):
            reasons.append("final_boundary_clearance")
        if abs(final_measurement.heading_error_deg) > route.tolerances.heading_deg:
            reasons.append("final_heading")
        if final_measurement.distance_to_target_m > route.tolerances.position_m:
            reasons.append("final_position")
        if not final_measurement.stopped:
            reasons.append("final_not_stopped")
    return {
        "ok": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "pose_count": len(poses),
        "min_obstacle_clearance_m": None
        if min_obstacle is None
        else round(min_obstacle, 4),
        "min_footprint_to_bay_clearance_m": None
        if min_boundary is None
        else round(min_boundary, 4),
    }


def _write_final(
    base,
    out_dir,
    route,
    completion,
    authorization,
    final_state,
    final_measurement,
    final_verification,
    collision_events,
    all_trace_poses,
    budget,
    round_records,
    *,
    final_samples,
    trace_audit=None,
    terminal_trace_audit=None,
):
    trace_audit = trace_audit or _trace_geometry_audit(route, all_trace_poses)
    base["final_state"] = final_state
    base["final_stability_samples"] = final_samples
    base["final_measurement"] = final_measurement.to_metadata()
    base["final_verification"] = final_verification.to_metadata()
    base["trajectory_audit"] = trace_audit
    base["terminal_trajectory_audit"] = terminal_trace_audit
    base["trajectory_pose_count"] = len(all_trace_poses)
    base["budget"] = budget.to_metadata()
    base["collision_events"] = list(collision_events)
    base["rounds"] = round_records
    base["entry_completed"] = final_verification.completed
    base["parking_completed"] = False
    _write_json(
        out_dir / "entry_state_final.json",
        {
            "state": final_state,
            "stability_samples": final_samples,
            "measurement": final_measurement.to_metadata(),
            "verification": final_verification.to_metadata(),
        },
    )
    _write_json(
        out_dir / "entry_verification.json", final_verification.to_metadata()
    )
    _write_json(out_dir / "entry_rounds.json", {"rounds": round_records})
    _write_json(
        out_dir / "geometry_audit.json",
        {
            "route_id": route.route_id,
            "route_hash": route.route_hash,
            "bay_polygon": [list(point) for point in route.bay_polygon],
            "footprint": route.footprint.to_metadata(),
            "route_audit": route_geometry_audit(route),
            "trajectory_audit": trace_audit,
            "terminal_trajectory_audit": terminal_trace_audit,
        },
    )
    _write_json(out_dir / "result.json", base)


if __name__ == "__main__":
    sys.exit(main())
