#!/usr/bin/env python3
"""M1-VLN-CARLA-CAP-07B-03: bounded low-speed Alignment for bound bay03.

Flow (one round = one verified adjustment):

    restored approach pose + real CARLA state
      -> binding identity + CAP-07B-02 ENTRY_AUTHORIZED precondition
      -> deterministic alignment measurement
      -> if not aligned: bounded local route (reverse heading correction or
         forward return to the staging line)
      -> geometric route validation + forward/reverse safety precheck
      -> Agent-Kernel parking.move single-use permit
      -> CARLA bridge -> bounded low-speed control -> brake -> real post state
      -> re-measure, require improvement, re-verify
      -> ALIGNMENT_COMPLETED, or SAFE_STOP with no retry

The vehicle may only move inside the declared alignment region, north of the
staging line, with the whole footprint outside the painted bay polygon. It
never follows the parking arc, never enters the bay and never emits an Entry
execution permission. The stage permission is single-use, task-bound and
expires; every round also needs its own Kernel execution permit.

No Taichu call is made: Alignment is geometry-driven, and the model's verified
close-range judgement already exists in the CAP-07B-02 artifact consumed as a
precondition. This avoids presenting an old model output as a new call.

Exit codes: 0 ALIGNMENT_COMPLETED, 2 rejected, 3 SAFE_STOP/partial, 4 setup.
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
from vln.carla.alignment_control import (  # noqa: E402
    alignment_overall_improved,
    alignment_phase_command,
    alignment_round_improved,
)
from vln.carla.alignment_route import (  # noqa: E402
    AlignmentRouteStatus,
    plan_alignment_round,
    validate_alignment_poses,
)
from vln.carla.alignment_scene import bay03_alignment_target  # noqa: E402
from vln.carla.goal import GoalSpec, evaluate_goal  # noqa: E402
from vln.carla.kernel_bridge import CarlaExecutionBridge  # noqa: E402
from vln.carla.session import cleanup_session, leftover_actors  # noqa: E402
from vln.client import HostClient, build_request  # noqa: E402
from vln.intent import AgentIntent, Target  # noqa: E402
from vln.nav import VehiclePose  # noqa: E402
from vln.nav.binding_runtime import load_binding_artifact  # noqa: E402
from vln.parking.alignment import (  # noqa: E402
    AlignmentBudget,
    AlignmentPhase,
    AlignmentStability,
    AlignmentStage,
    alignment_refusal_authorization,
    authorize_alignment,
    consume_alignment_authorization,
    measure_alignment,
    measure_stability,
    revoke_alignment_authorization,
    verify_alignment,
)
from vln.parking.autonomous import (  # noqa: E402
    EntryAuthorization,
    approach_state_from_result,
    entry_authorization_from_metadata,
)

TASK_ID = "cap07b-03"
SKILL_ID = "vln.parking.alignment"
EGO_ROLE = "vln_cap07b03_ego"
COLLISION_ROLE = "vln_cap07b03_collision"
FIXED_DT = 0.05
STOP_SPEED_MPS = 0.05
DEFAULT_KERNEL_HOST = (
    "/home/gaosong/workspace/Agentic_Program/m1-vln-carla-02-build/kernel_host"
)


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
    except Exception as error:  # evidence must not fail the run
        return {"error": f"{type(error).__name__}: {error}"}


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


def _measure(session, ego, target, ticks: int = 5):
    samples, state = _hold_and_sample(session, ego, ticks)
    stability = measure_stability(samples, target.tolerances)
    measurement = measure_alignment(
        target,
        x=state["x"],
        y=state["y"],
        yaw_rad=state["yaw_rad"],
        speed_mps=state["speed"],
        stopped=state["speed"] < target.tolerances.stop_speed_mps,
        stability=stability,
    )
    return measurement, state, samples


def _load_obstacles(path: Path) -> tuple[tuple[float, float], ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        points = payload["obstacle_points"]
        return tuple((float(point[0]), float(point[1])) for point in points)
    except (OSError, ValueError, KeyError, TypeError):
        return ()


def _load_entry_precondition(
    entry_authorization_path: Path,
    verification_path: Path,
    binding,
) -> tuple[EntryAuthorization, dict]:
    """Load and cross-check the CAP-07B-02 permission and its evidence."""

    entry = entry_authorization_from_metadata(
        json.loads(entry_authorization_path.read_text(encoding="utf-8"))
    )
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    if entry.decision != "ENTRY_AUTHORIZED" or not entry.permits_entry:
        raise ValueError("entry authorization is not ENTRY_AUTHORIZED")
    if entry.executes_motion:
        raise ValueError("entry authorization must not execute motion")
    if entry.task_id != "cap07b-02" or verification.get("task_id") != "cap07b-02":
        raise ValueError("entry authorization and verification task mismatch")
    if verification.get("stage") != "TARGET_CONFIRMED":
        raise ValueError("target verification did not reach TARGET_CONFIRMED")
    if not verification.get("target_confirmed"):
        raise ValueError("target verification is not confirmed")
    hashes = verification.get("observation_image_hashes")
    if not isinstance(hashes, list) or len(set(hashes)) < 2:
        raise ValueError("verification evidence has fewer than two distinct images")
    if set(hashes) != set(entry.observation_image_hashes):
        raise ValueError(
            "entry authorization evidence is not the current verification evidence"
        )
    if (
        entry.bay_id != getattr(binding, "bay_id", None)
        or entry.slot_node_id != getattr(binding, "slot_node_id", None)
    ):
        raise ValueError("entry authorization identity does not match the binding")
    if not entry.is_usable_by(
        task_id=entry.task_id,
        target_id=entry.target_id,
        bay_id=entry.bay_id,
        slot_node_id=entry.slot_node_id,
        approach_node_id=entry.approach_node_id,
    ):
        raise ValueError("entry authorization is not usable for its own identity")
    if not entry.is_current(
        binding_status="bound",
        approach_stage="APPROACH_COMPLETED",
        observation_image_hashes=hashes,
    ):
        raise ValueError("entry authorization is no longer current")
    return entry, verification


def _preflight(session, ego, target, plan) -> dict:
    points = list(plan.points)
    cumulative = nav01b.cumulative_lengths(points)
    details: dict = {}
    blocked, min_hit, ground = nav01b.safety_check(
        session,
        ego,
        points,
        cumulative,
        0.0,
        floor_probe_z=nav01e.FLOOR_PROBE_Z,
        ray_z_offset=nav01e.SAFETY_RAY_Z_OFFSET,
        reverse=plan.reverse,
        stop_distance_m=nav01e.PARKING_STOP_DISTANCE_M,
        min_probe_distance_m=7.0,
        details_out=details,
    )
    violations = validate_alignment_poses(target, plan.poses)
    current = _state(session, ego)
    current_measurement = measure_alignment(
        target,
        x=current["x"],
        y=current["y"],
        yaw_rad=current["yaw_rad"],
        speed_mps=current["speed"],
        stopped=current["speed"] < target.tolerances.stop_speed_mps,
        stability=AlignmentStability(0, current["speed"], 0.0, False),
    )
    reasons: list[str] = []
    if blocked:
        reasons.append("safety_ray_or_floor_blocked")
    reasons.extend(violations)
    if not current_measurement.inside_allowed_region:
        reasons.append("current_pose_outside_region")
    if (
        current_measurement.boundary_clearance_m is None
        or current_measurement.boundary_clearance_m
        < target.tolerances.boundary_clearance_m
    ):
        reasons.append("current_boundary_clearance")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "blocked": bool(blocked),
        "min_hit_m": None if min_hit is None else round(min_hit, 4),
        "ground_z": ground,
        "details": details,
        "route_violations": list(violations),
        "current_pose": current,
        "current_measurement": current_measurement.to_metadata(),
        "route": plan.to_metadata(),
    }


def _drive_alignment_phase(
    session,
    ego,
    target,
    plan,
    *,
    baseline_collisions: int,
    collision_events: list[dict],
) -> dict:
    """Run one already-authorized bounded phase; always brake before return."""

    pre = _state(session, ego)
    records: list[dict] = []
    travelled = 0.0
    started = time.monotonic()
    started_sim = pre["sim_time"]
    stop_reason = "step_limit"
    safety_stop = False
    x, y, yaw = pre["x"], pre["y"], pre["yaw_rad"]
    max_steps = int(round(plan.max_sim_seconds / FIXED_DT)) + 100
    try:
        for step in range(max_steps):
            current = _state(session, ego)
            x, y, yaw = current["x"], current["y"], current["yaw_rad"]
            measurement = measure_alignment(
                target,
                x=x,
                y=y,
                yaw_rad=yaw,
                speed_mps=current["speed"],
                stopped=False,
                stability=AlignmentStability(0, current["speed"], 0.0, False),
            )
            if len(collision_events) > baseline_collisions:
                stop_reason = "collision"
                safety_stop = True
                break
            if not measurement.inside_allowed_region:
                stop_reason = "outside_alignment_region"
                safety_stop = True
                break
            if measurement.reference_inside_bay:
                stop_reason = "reference_inside_bay"
                safety_stop = True
                break
            if (
                measurement.boundary_clearance_m is None
                or measurement.boundary_clearance_m
                < target.tolerances.boundary_clearance_m
            ):
                stop_reason = "boundary_clearance"
                safety_stop = True
                break
            if (
                measurement.obstacle_clearance_m is not None
                and measurement.obstacle_clearance_m
                < target.tolerances.obstacle_clearance_m
            ):
                stop_reason = "obstacle_clearance"
                safety_stop = True
                break
            command = alignment_phase_command(
                target,
                phase=plan.phase,
                x=x,
                y=y,
                yaw_rad=yaw,
                speed_mps=current["speed"],
                travelled_m=travelled,
                max_distance_m=plan.max_distance_m,
                sim_seconds=max(0.0, current["sim_time"] - started_sim),
                max_sim_seconds=plan.max_sim_seconds,
            )
            if command.done:
                stop_reason = command.done_reason
                break
            control = carla.VehicleControl(
                throttle=float(command.throttle),
                steer=float(command.steer),
                brake=float(command.brake),
                reverse=bool(command.reverse),
            )
            ego.apply_control(control)
            session.tick()
            nxt = _state(session, ego)
            travelled += math.hypot(nxt["x"] - current["x"], nxt["y"] - current["y"])
            records.append(
                {
                    "step": step,
                    "t": nxt["sim_time"],
                    "x": nxt["x"],
                    "y": nxt["y"],
                    "yaw_deg": nxt["yaw_deg"],
                    "speed": nxt["speed"],
                    "command": command.to_metadata(),
                    "lateral_error_m": round(measurement.lateral_error_m, 4),
                    "heading_error_deg": round(
                        measurement.heading_error_deg, 4
                    ),
                    "longitudinal_error_m": round(
                        measurement.longitudinal_error_m, 4
                    ),
                    "boundary_clearance_m": measurement.boundary_clearance_m,
                    "travelled_m": round(travelled, 4),
                }
            )
            if travelled > plan.max_distance_m + 0.10:
                stop_reason = "distance_overshoot"
                safety_stop = True
                break
            if current["sim_time"] - started_sim > plan.max_sim_seconds:
                stop_reason = "time_limit"
                break
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
    for _ in range(100):
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
        in ("heading_aligned", "staging_reached", "distance_limit", "time_limit")
        and not safety_stop,
        "pre_state": {"x": pre["x"], "y": pre["y"], "speed": pre["speed"]},
        "post_state": {"x": post["x"], "y": post["y"], "speed": post["speed"]},
        "pre_full": pre,
        "post_full": post,
        "stopped": post["speed"] < 0.03,
        "moved_m": round(moved, 4),
        "travelled_m": round(travelled, 4),
        "wall_seconds": round(time.monotonic() - started, 3),
        "sim_seconds": round(post["sim_time"] - started_sim, 3),
        "collision_count": len(collision_events) - baseline_collisions,
        "records": records,
    }


def _run_round_via_kernel(
    *,
    session,
    ego,
    target,
    plan,
    host_client,
    bridge,
    round_index,
    baseline_collisions,
    collision_events,
) -> dict:
    pre = _state(session, ego)
    intent_id = f"{TASK_ID}-r{round_index:02d}-{pre['frame']}"
    intent = AgentIntent(
        intent_id=intent_id,
        target=Target(
            x=plan.end_pose[0],
            y=plan.end_pose[1],
            heading=plan.heading_target_rad,
        ),
    )
    request_id = f"{TASK_ID}-r{round_index:02d}-req-{pre['frame']}"
    request = build_request(intent, request_id=request_id)
    bridge.register_permit(
        request_id=request_id,
        intent_id=intent.intent_id,
        target=intent.target.to_object(),
        payload=intent.to_payload(),
        context={
            "plan": plan,
            "target": target,
            "round_index": round_index,
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
        "plan_phase": plan.phase,
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
        phase_success = bool(execution and execution.get("phase_success"))
        kernel_record["phase_success"] = phase_success
        return {
            "ok": True,
            "phase_success": phase_success,
            "moved_m": None
            if not isinstance(execution, dict)
            else execution.get("moved_m"),
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
    target,
    decision: str,
    reason: str,
    out_dir: Path,
    base: dict,
    exit_code: int,
    entry_authorization_id: str = "none",
) -> int:
    try:
        artifact = alignment_refusal_authorization(
            target,
            decision,
            reason,
            task_id=TASK_ID,
            entry_authorization_id=entry_authorization_id,
        )
        base["alignment_authorization"] = artifact.to_metadata()
        _write_json(
            out_dir / "alignment_authorization.json", artifact.to_metadata()
        )
    except Exception as error:
        base["alignment_authorization"] = {
            "error": f"{type(error).__name__}: {error}"
        }
    base.update(
        {
            "status": "SAFE_STOP" if decision == "SAFE_STOP" else decision,
            "decision": decision,
            "error": reason,
            "parking_executed": False,
            "entry_executed": False,
            "parking_arc_executed": False,
            "entry_execution_authorization_issued": False,
            "finished_utc": _utc_now(),
        }
    )
    _write_json(out_dir / "result.json", base)
    print(json.dumps(base, ensure_ascii=False, indent=2)[:6000])
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument(
        "--approach-result",
        default=str(
            REPO_ROOT / "docs" / "evidence" / "cap07b-01-w4-4096" / "result.json"
        ),
    )
    parser.add_argument(
        "--binding-json",
        default=str(REPO_ROOT / "docs" / "evidence" / "cap07a" / "A" / "binding.json"),
    )
    parser.add_argument(
        "--entry-authorization",
        default=str(
            REPO_ROOT
            / "docs"
            / "evidence"
            / "vln-carla-cap-07b-02"
            / "entry_authorization.json"
        ),
    )
    parser.add_argument(
        "--verification-json",
        default=str(
            REPO_ROOT
            / "docs"
            / "evidence"
            / "vln-carla-cap-07b-02"
            / "verification.json"
        ),
    )
    parser.add_argument(
        "--geometry-probe",
        default=str(
            REPO_ROOT / "docs" / "evidence" / "carla-07a" / "geometry_probe.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "docs" / "evidence" / "vln-carla-cap-07b-03"),
    )
    parser.add_argument("--spawn-z", type=float, default=6.7)
    parser.add_argument("--kernel-host", default=DEFAULT_KERNEL_HOST)
    parser.add_argument("--kernel-exec-timeout-ms", type=int, default=180000)
    parser.add_argument("--max-rounds", type=int, default=4)
    parser.add_argument("--ttl-s", type=float, default=600.0)
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = _utc_now()
    base: dict = {
        "schema": "vln.cap07b03.result.v1",
        "skill": SKILL_ID,
        "task_id": TASK_ID,
        "started_utc": started,
        "git": _git_state(),
        "model": {
            "calls": 0,
            "reason": (
                "Alignment is geometry-driven; the real Taichu two-observation "
                "verification is consumed as the CAP-07B-02 precondition artifact"
            ),
        },
        "entry_executed": False,
        "parking_arc_executed": False,
        "parking_executed": False,
        "entry_execution_authorization_issued": False,
        "motion": None,
        "rounds": [],
        "kernel_executions": 0,
    }

    try:
        approach_result = json.loads(
            Path(args.approach_result).read_text(encoding="utf-8")
        )
        binding = load_binding_artifact(args.binding_json)
        approach = approach_state_from_result(approach_result)
        if not approach.matches_binding(binding):
            raise ValueError("approach identity does not match the binding artifact")
        goal_spec = approach_result["goal_spec"]
        if goal_spec.get("node_id") != "park_entry":
            raise ValueError("approach goal_spec is not park_entry")
        entry_authorization, verification = _load_entry_precondition(
            Path(args.entry_authorization),
            Path(args.verification_json),
            binding,
        )
        obstacles = _load_obstacles(Path(args.geometry_probe))
        target = bay03_alignment_target(
            task_id=TASK_ID, obstacle_points=obstacles
        )
        base["target"] = target.to_metadata()
        base["binding"] = binding.to_metadata()
        base["entry_precondition"] = {
            "authorization": entry_authorization.to_metadata(),
            "verification": verification,
            "used_as": (
                "precondition only; its task identity and ENTRY scope are not "
                "modified and it is not consumed"
            ),
        }
        alignment_budget = AlignmentBudget(max_rounds=args.max_rounds)
        authorization = authorize_alignment(
            entry_authorization,
            target,
            binding=binding,
            verification_observation_hashes=verification[
                "observation_image_hashes"
            ],
            task_id=TASK_ID,
            ttl_s=args.ttl_s,
            budget=alignment_budget,
        )
        authorization = consume_alignment_authorization(
            authorization,
            task_id=TASK_ID,
            target_id=target.target_id,
            bay_id=target.bay_id,
            slot_node_id=target.slot_node_id,
            approach_node_id=target.approach_node_id,
        )
        base["alignment_authorization"] = authorization.to_metadata()
        _write_json(
            out_dir / "alignment_authorization.json",
            authorization.to_metadata(),
        )
    except Exception as error:
        base["status"] = "ALIGNMENT_REJECTED"
        base["error"] = f"setup/precondition failed: {type(error).__name__}: {error}"
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
                "world already contains vln_ actors; refusing to run alignment "
                "on an unknown scene"
            )
        ego = session.spawn_vehicle(
            EGO_ROLE,
            float(approach.pose["x"]),
            float(approach.pose["y"]),
            args.spawn_z,
            float(approach.pose["yaw"]),
        )
        session.tick(40)
        ego.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))
        session.tick(10)
        actual = _state(session, ego)
        base["restored_pose"] = actual
        base["approach_expected_pose"] = dict(approach.pose)
        extent = ego.bounding_box.extent
        base["vehicle"] = {
            "type_id": ego.type_id,
            "half_extent": {
                "x": round(float(extent.x), 4),
                "y": round(float(extent.y), 4),
                "z": round(float(extent.z), 4),
            },
            "footprint_config": target.footprint.to_metadata(),
        }
        if abs(float(extent.x) - target.footprint.half_length) > 0.05 or abs(
            float(extent.y) - target.footprint.half_width
        ) > 0.05:
            return _refusal(
                target=target,
                decision="SAFE_STOP",
                reason=(
                    "vehicle bounding box differs from the measured footprint: "
                    f"extent=({extent.x:.3f},{extent.y:.3f})"
                ),
                out_dir=out_dir,
                base=base,
                exit_code=3,
                entry_authorization_id=authorization.entry_authorization_id,
            )

        spec = GoalSpec(
            node_id="park_entry",
            x=float(goal_spec["x"]),
            y=float(goal_spec["y"]),
            heading_rad=float(goal_spec["heading_rad"]),
            distance_tolerance_m=1.5,
            heading_tolerance_rad=math.radians(30.0),
            stop_speed_mps=0.25,
        )
        goal_eval = evaluate_goal(
            spec,
            VehiclePose(
                x=actual["x"],
                y=actual["y"],
                heading=actual["yaw_rad"],
            ),
            speed_mps=actual["speed"],
            stopped=actual["speed"] < 0.25,
        )
        base["approach_gate"] = goal_eval.to_metadata()
        if not goal_eval.ok:
            return _refusal(
                target=target,
                decision="SAFE_STOP",
                reason="restored_pose_not_at_approach: "
                + ", ".join(goal_eval.reasons),
                out_dir=out_dir,
                base=base,
                exit_code=3,
                entry_authorization_id=authorization.entry_authorization_id,
            )
        if not target.region_contains(actual["x"], actual["y"]):
            return _refusal(
                target=target,
                decision="SAFE_STOP",
                reason="restored_pose_outside_alignment_region",
                out_dir=out_dir,
                base=base,
                exit_code=3,
                entry_authorization_id=authorization.entry_authorization_id,
            )

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

        initial_measurement, initial_state, initial_samples = _measure(
            session, ego, target
        )
        initial_verification = verify_alignment(
            target,
            binding=binding,
            measurement=initial_measurement,
            collision_count=len(collision_events),
        )
        base["initial_state"] = initial_state
        base["initial_stability_samples"] = initial_samples
        base["initial_measurement"] = initial_measurement.to_metadata()
        base["initial_verification"] = initial_verification.to_metadata()
        _write_json(
            out_dir / "alignment_state_initial.json",
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
            AlignmentStage.REJECTED,
            AlignmentStage.SAFE_STOP,
        ):
            return _refusal(
                target=target,
                decision=initial_verification.stage,
                reason="initial verification: "
                + ", ".join(initial_verification.reasons),
                out_dir=out_dir,
                base=base,
                exit_code=3
                if initial_verification.stage == AlignmentStage.SAFE_STOP
                else 2,
                entry_authorization_id=authorization.entry_authorization_id,
            )

        if initial_verification.completed:
            base["status"] = "PASS"
            base["decision"] = AlignmentStage.COMPLETED
            base["zero_motion_reason"] = (
                "the restored real pose already satisfied every pre-defined "
                "alignment threshold and the stable-stop check"
            )
            base["final_state"] = initial_state
            base["final_measurement"] = initial_measurement.to_metadata()
            base["final_verification"] = initial_verification.to_metadata()
            base["collision_events"] = list(collision_events)
            base["finished_utc"] = _utc_now()
            _write_json(
                out_dir / "alignment_state_final.json",
                {
                    "state": initial_state,
                    "measurement": initial_measurement.to_metadata(),
                    "verification": initial_verification.to_metadata(),
                    "zero_motion": True,
                },
            )
            _write_json(out_dir / "result.json", base)
            return 0

        def _handle_kernel_execution(permit):
            context = permit.context
            return _drive_alignment_phase(
                session,
                ego,
                context["target"],
                context["plan"],
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

        budget = alignment_budget
        measurement = initial_measurement
        stop_reason = None
        for round_index in range(1, args.max_rounds + 1):
            if not authorization.is_active(
                task_id=TASK_ID,
                target_id=target.target_id,
                bay_id=target.bay_id,
                slot_node_id=target.slot_node_id,
                approach_node_id=target.approach_node_id,
            ):
                stop_reason = "alignment_authorization_inactive"
                break
            if not budget.can_start_round:
                stop_reason = "alignment_budget_exhausted"
                break
            current_verification = verify_alignment(
                target,
                binding=binding,
                measurement=measurement,
                collision_count=len(collision_events),
            )
            if current_verification.completed:
                break
            if current_verification.stage in (
                AlignmentStage.REJECTED,
                AlignmentStage.SAFE_STOP,
            ):
                stop_reason = "verification_" + current_verification.stage
                break
            route = plan_alignment_round(
                target,
                measurement,
                budget=budget,
                round_index=round_index,
            )
            round_record = {
                "round": round_index,
                "pre_state": _state(session, ego),
                "pre_measurement": measurement.to_metadata(),
                "pre_verification": current_verification.to_metadata(),
                "route_arbitration": route.to_metadata(),
                "safety_preflight": None,
                "kernel": None,
                "post_state": None,
                "post_measurement": None,
                "post_verification": None,
                "improvement": None,
                "budget_before": budget.to_metadata(),
            }
            if route.status == AlignmentRouteStatus.ALREADY_ALIGNED:
                stop_reason = "already_aligned_but_not_stable"
                round_records.append(round_record)
                break
            if not route.ok:
                stop_reason = f"route_{route.status}: {route.reason}"
                round_records.append(round_record)
                break
            plan = route.plan
            preflight = _preflight(session, ego, target, plan)
            round_record["safety_preflight"] = preflight
            if not preflight["ok"]:
                stop_reason = "safety_preflight: " + ", ".join(preflight["reasons"])
                round_records.append(round_record)
                break

            before_round_state = _state(session, ego)
            before_round_measurement = measure_alignment(
                target,
                x=before_round_state["x"],
                y=before_round_state["y"],
                yaw_rad=before_round_state["yaw_rad"],
                speed_mps=before_round_state["speed"],
                stopped=before_round_state["speed"]
                < target.tolerances.stop_speed_mps,
                stability=measurement.stability,
            )
            kernel_result = _run_round_via_kernel(
                session=session,
                ego=ego,
                target=target,
                plan=plan,
                host_client=host_client,
                bridge=bridge,
                round_index=round_index,
                baseline_collisions=len(collision_events),
                collision_events=collision_events,
            )
            base["kernel_executions"] += 1
            round_record["kernel"] = kernel_result["kernel"]
            if not kernel_result["ok"]:
                stop_reason = "kernel_execution_failed: " + str(
                    kernel_result["error"]
                )
                round_records.append(round_record)
                break

            post_measurement, post_state, post_samples = _measure(
                session, ego, target
            )
            post_verification = verify_alignment(
                target,
                binding=binding,
                measurement=post_measurement,
                collision_count=len(collision_events),
            )
            execution = kernel_result["execution"] or {}
            moved = float(
                execution.get("travelled_m")
                or execution.get("moved_m")
                or 0.0
            )
            round_record.update(
                {
                    "post_state": post_state,
                    "post_stability_samples": post_samples,
                    "post_measurement": post_measurement.to_metadata(),
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
            all_trace_poses.append(
                (post_state["x"], post_state["y"], post_state["yaw_rad"])
            )
            for record in execution.get("records", []) or []:
                all_trace_poses.append(
                    (
                        float(record["x"]),
                        float(record["y"]),
                        math.radians(float(record["yaw_deg"])),
                    )
                )
            improved, improvement_reasons = alignment_round_improved(
                target,
                phase=plan.phase,
                before=before_round_measurement,
                after=post_measurement,
            )
            round_record["improvement"] = {
                "ok": improved,
                "reasons": list(improvement_reasons),
                "before": before_round_measurement.to_metadata(),
                "after": post_measurement.to_metadata(),
            }
            budget = budget.record_round(moved)
            round_record["budget_after"] = budget.to_metadata()
            round_records.append(round_record)
            _write_json(
                out_dir / "alignment_rounds.json",
                {"rounds": round_records},
            )
            if not improved:
                stop_reason = "phase_did_not_improve: " + ", ".join(
                    improvement_reasons
                )
                break
            if post_verification.stage in (
                AlignmentStage.REJECTED,
                AlignmentStage.SAFE_STOP,
            ):
                stop_reason = "post_verification_" + post_verification.stage
                break
            measurement = post_measurement
            if post_verification.completed:
                break

        session.brake_to_stop(ego, max_ticks=100)
        final_measurement, final_state, final_samples = _measure(
            session, ego, target
        )
        final_verification = verify_alignment(
            target,
            binding=binding,
            measurement=final_measurement,
            collision_count=len(collision_events),
        )
        overall_ok, overall_reasons = alignment_overall_improved(
            target,
            initial=initial_measurement,
            final=final_measurement,
        )
        trace_violations = validate_alignment_poses(target, all_trace_poses)
        base["final_state"] = final_state
        base["final_stability_samples"] = final_samples
        base["final_measurement"] = final_measurement.to_metadata()
        base["final_verification"] = final_verification.to_metadata()
        base["overall_improvement"] = {
            "ok": overall_ok,
            "reasons": list(overall_reasons),
        }
        base["trajectory_violations"] = list(trace_violations)
        base["trajectory_pose_count"] = len(all_trace_poses)
        base["budget"] = budget.to_metadata()
        base["collision_events"] = list(collision_events)
        base["stop_reason"] = stop_reason
        base["rounds"] = round_records
        _write_json(
            out_dir / "alignment_state_final.json",
            {
                "state": final_state,
                "stability_samples": final_samples,
                "measurement": final_measurement.to_metadata(),
                "verification": final_verification.to_metadata(),
                "overall_improvement": {
                    "ok": overall_ok,
                    "reasons": list(overall_reasons),
                },
                "trajectory_violations": list(trace_violations),
            },
        )
        _write_json(out_dir / "alignment_rounds.json", {"rounds": round_records})

        success = (
            final_verification.completed
            and overall_ok
            and not trace_violations
            and not collision_events
            and final_state["speed"] < target.tolerances.stop_speed_mps
            and final_measurement.stability.stable
        )
        base["status"] = "PASS" if success else "PARTIAL"
        base["decision"] = final_verification.stage
        base["finished_utc"] = _utc_now()
        if not success:
            base["error"] = (
                stop_reason
                or "final verification: "
                + ", ".join(final_verification.reasons)
            )
            # A permission that started motion and did not complete is revoked
            # so it cannot fund a later silent attempt.
            try:
                revoked = revoke_alignment_authorization(
                    authorization, base["error"]
                )
                base["alignment_authorization"] = revoked.to_metadata()
                _write_json(
                    out_dir / "alignment_authorization.json",
                    revoked.to_metadata(),
                )
            except Exception:
                pass
        _write_json(out_dir / "result.json", base)
        print(
            json.dumps(
                {
                    "status": base["status"],
                    "decision": base["decision"],
                    "bay_id": target.bay_id,
                    "initial": {
                        "lateral_m": round(
                            initial_measurement.lateral_error_m, 4
                        ),
                        "heading_deg": round(
                            initial_measurement.heading_error_deg, 4
                        ),
                        "longitudinal_m": round(
                            initial_measurement.longitudinal_error_m, 4
                        ),
                        "boundary_m": initial_measurement.boundary_clearance_m,
                    },
                    "final": {
                        "lateral_m": round(final_measurement.lateral_error_m, 4),
                        "heading_deg": round(
                            final_measurement.heading_error_deg, 4
                        ),
                        "longitudinal_m": round(
                            final_measurement.longitudinal_error_m, 4
                        ),
                        "boundary_m": final_measurement.boundary_clearance_m,
                    },
                    "rounds": len(round_records),
                    "collisions": len(collision_events),
                    "final_speed": final_state["speed"],
                    "entry_executed": False,
                    "parking_arc_executed": False,
                    "reason": base.get("error"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if success else 3
    except Exception as error:
        base["status"] = "SAFE_STOP"
        base["decision"] = AlignmentStage.SAFE_STOP
        base["error"] = f"{type(error).__name__}: {error}"
        base["traceback"] = traceback.format_exc()
        base["finished_utc"] = _utc_now()
        try:
            if initial_measurement is not None:
                base["final_measurement"] = initial_measurement.to_metadata()
            base["collision_events"] = list(collision_events)
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
                        handle.write(
                            json.dumps(transaction, ensure_ascii=False) + "\n"
                        )
            except Exception as error:
                print(
                    f"bridge evidence error: {type(error).__name__}: {error}",
                    file=sys.stderr,
                )
        if host_client is not None:
            try:
                stderr_lines = host_client.stderr_lines
                (out_dir / "kernel_host_stderr.log").write_text(
                    "".join(stderr_lines), encoding="utf-8"
                )
                host_client.close()
            except Exception as error:
                print(
                    f"host cleanup error: {type(error).__name__}: {error}",
                    file=sys.stderr,
                )
        if bridge is not None:
            try:
                bridge.close()
            except Exception as error:
                print(
                    f"bridge cleanup error: {type(error).__name__}: {error}",
                    file=sys.stderr,
                )
        if session is not None:
            try:
                cleanup = cleanup_session(
                    session.world, session.actors, session.original
                )
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
                print(
                    f"cleanup error: {type(error).__name__}: {error}",
                    file=sys.stderr,
                )
        try:
            log_payload = {
                "started_utc": started,
                "finished_utc": _utc_now(),
                "status": base.get("status"),
                "decision": base.get("decision"),
                "error": base.get("error"),
                "rounds": len(round_records),
                "collision_events": len(collision_events),
                "kernel_executions": base.get("kernel_executions"),
                "initial_measurement": base.get("initial_measurement"),
                "final_measurement": base.get("final_measurement"),
                "budget": base.get("budget"),
                "cleanup": base.get("cleanup"),
            }
            (out_dir / "run.log").write_text(
                json.dumps(log_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as error:
            print(f"run.log error: {type(error).__name__}: {error}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
