#!/usr/bin/env python3
"""M1-VLN-CARLA-CAP-07B-05: in-bay Parking Pose Refinement.

The runner re-establishes a real Entry state in the same CARLA process (from
the accepted CAP-07B-03 Alignment artifact, using the CAP-07B-04 Entry
execution chain), then evaluates whether a safer in-bay pose exists. It
executes at most one bounded reverse + forward refinement, each through the
existing Agent-Kernel parking.move single-use permit.

Outcomes:
  PASS — PARKING_POSE_READY
  PASS — NO_SAFE_REFINEMENT (current pose preserved safely)
  PARTIAL — SAFE_STOP / REFINEMENT_FAILED
It never produces PARKING_COMPLETED.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
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

import carla_cap07b04_entry as entry04  # noqa: E402
import carla_vln_navigate as nav01e  # noqa: E402
from vln.carla.entry_terminal import TerminalPhase  # noqa: E402
from vln.carla.parking_verdict import (  # noqa: E402
    BAY03_CENTER,
    BAY03_POLYGON,
    PARKING_FOOTPRINT,
)
from vln.carla.refinement_plan import (  # noqa: E402
    build_refinement_phase_plan,
    plan_refinement_path,
)
from vln.client import build_request  # noqa: E402
from vln.intent import AgentIntent, Target  # noqa: E402
from vln.nav.binding_runtime import load_binding_artifact  # noqa: E402
from vln.parking.refinement import (  # noqa: E402
    RefinementBudget,
    RefinementStage,
    RefinementTolerances,
    RefinementStability,
    authorize_refinement,
    compute_entry_completion_id,
    consume_refinement_authorization,
    generate_candidates,
    measure_refinement,
    measure_stability,
    no_safe_refinement_result,
    refinement_phase_improved,
    revoke_refinement_authorization,
    verify_refinement,
)

TASK_ID = "cap07b-05"
SKILL_ID = "vln.parking.refinement"
HISTORICAL_ENTRY_RESULT = (
    REPO_ROOT / "docs" / "evidence" / "vln-carla-cap-07b-04" / "result.json"
)
HISTORICAL_ENTRY_AUTH = (
    REPO_ROOT
    / "docs"
    / "evidence"
    / "vln-carla-cap-07b-04"
    / "entry_authorization.json"
)
GEOMETRY_PROBE = REPO_ROOT / "docs" / "evidence" / "carla-07a" / "geometry_probe.json"
BINDING_JSON = REPO_ROOT / "docs" / "evidence" / "cap07a" / "A" / "binding.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
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


def _load_obstacles() -> tuple[tuple[float, float], ...]:
    payload = json.loads(GEOMETRY_PROBE.read_text(encoding="utf-8"))
    return tuple(
        (float(p[0]), float(p[1])) for p in payload["obstacle_points"]
    )


def _measure(session, ego, *, collision_count: int):
    samples, state = entry04._hold_and_sample(session, ego, 5)
    tolerances = RefinementTolerances()
    stability = measure_stability(samples, tolerances)
    measurement = measure_refinement(
        x=state["x"],
        y=state["y"],
        yaw_rad=state["yaw_rad"],
        speed_mps=state["speed"],
        stopped=state["speed"] < tolerances.stop_speed_mps,
        center=(float(BAY03_CENTER[0]), float(BAY03_CENTER[1])),
        bay_heading_rad=math.pi,
        bay_polygon=tuple((float(x), float(y)) for x, y in BAY03_POLYGON),
        footprint=PARKING_FOOTPRINT,
        obstacle_points=OBSTACLES,
        stability=stability,
        collision_count=collision_count,
    )
    return measurement, state, samples, stability


OBSTACLES: tuple[tuple[float, float], ...] = ()


def _run_phase(
    *,
    session,
    ego,
    route,
    plan,
    config,
    entry_budget,
    bridge,
    host_client,
    phase_label: str,
    round_index: int,
    baseline_collisions: int,
    collision_events: list[dict],
    boundary_floor: float,
) -> dict:
    pre = entry04._state(session, ego)
    intent_id = f"{TASK_ID}-r{round_index:02d}-{pre['frame']}"
    intent = AgentIntent(
        intent_id=intent_id,
        target=Target(x=plan.target_x, y=plan.target_y, heading=plan.target_heading_rad),
    )
    request_id = f"{TASK_ID}-r{round_index:02d}-req-{pre['frame']}"
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
            "budget": entry_budget,
            "baseline_collisions": baseline_collisions,
            "collision_events": collision_events,
            "min_boundary_clearance": boundary_floor,
            "phase_label": phase_label,
        },
    )
    kernel = {
        "called": True,
        "capability_id": request.capability_id,
        "request_id": request_id,
        "intent_id": intent.intent_id,
        "target": intent.target.to_object(),
        "authorization": (
            "IssueRuntimeExecutionAuthority -> Port().Submit/Observe -> "
            "Runtime::Run -> registered parking.move invoker"
        ),
        "phase_label": phase_label,
        "single_use_permit": True,
    }
    started = time.monotonic()
    try:
        response = host_client.send(request)
        transaction = bridge.get_transaction(request_id)
        error, output = nav01e._validate_kernel_correlation(
            response, request, intent, transaction
        )
        kernel.update(
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
            return {"ok": False, "error": error, "kernel": kernel}
        execution = transaction.get("vehicle") if isinstance(transaction, dict) else None
        return {
            "ok": True,
            "phase_success": bool(execution and execution.get("phase_success")),
            "execution": execution,
            "kernel": kernel,
        }
    except Exception as error:
        kernel.update(
            {
                "request_ok": False,
                "error": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(),
            }
        )
        return {"ok": False, "error": f"{type(error).__name__}: {error}", "kernel": kernel}


def _historical_entry_check(binding) -> dict:
    result = json.loads(HISTORICAL_ENTRY_RESULT.read_text(encoding="utf-8"))
    auth = json.loads(HISTORICAL_ENTRY_AUTH.read_text(encoding="utf-8"))
    if result.get("status") != "PASS" or result.get("decision") != "ENTRY_COMPLETED":
        raise ValueError("historical CAP-07B-04 result is not ENTRY_COMPLETED")
    if result.get("entry_completed") is not True or result.get("parking_completed") is not False:
        raise ValueError("historical CAP-07B-04 flags are inconsistent")
    final = result.get("final_state") or {}
    if auth.get("decision") != "ENTRY_AUTHORIZED" or not auth.get("consumed_at"):
        raise ValueError("historical CAP-07B-04 entry authorization is not consumed")
    if auth.get("bay_id") != getattr(binding, "bay_id", None) or auth.get("slot_node_id") != getattr(binding, "slot_node_id", None):
        raise ValueError("historical entry authorization identity mismatch")
    return {
        "result": result,
        "authorization": auth,
        "result_sha256": _sha256_file(HISTORICAL_ENTRY_RESULT),
        "authorization_sha256": _sha256_file(HISTORICAL_ENTRY_AUTH),
        "final_pose": {
            "x": float(final["x"]),
            "y": float(final["y"]),
            "yaw_rad": float(final["yaw_rad"]),
        },
    }


def _snapshot_bridge(out_dir: Path, bridge) -> None:
    try:
        with (out_dir / "kernel_bridge_transactions.jsonl").open("w", encoding="utf-8") as handle:
            for transaction in bridge.transactions:
                handle.write(json.dumps(transaction, ensure_ascii=False) + "\n")
    except Exception as error:
        print(f"bridge snapshot error: {type(error).__name__}: {error}", file=sys.stderr)


def _write_geometry(out_dir: Path, initial, final, plan, rounds) -> None:
    payload = {
        "initial_measurement": initial.to_metadata(),
        "final_measurement": final.to_metadata(),
        "path_plan": None if plan is None else {
            "ok": plan.ok,
            "reasons": list(plan.reasons),
            "min_boundary_clearance_m": plan.min_boundary_clearance_m,
            "min_obstacle_clearance_m": plan.min_obstacle_clearance_m,
            "simulated_pose_count": len(plan.simulated_poses),
            "predicted_final": None if plan.predicted_final is None else plan.predicted_final.to_metadata(),
        },
        "rounds": [
            {
                "round": r.get("round"),
                "phase": r.get("phase"),
                "pre_measurement": r.get("pre_measurement"),
                "post_measurement": r.get("post_measurement"),
                "improvement": r.get("improvement"),
            }
            for r in rounds
        ],
    }
    _write_json(out_dir / "geometry_audit.json", payload)


def _callback(
    *,
    session,
    ego,
    route,
    completion,
    entry_authorization,
    final_state,
    final_measurement,
    final_verification,
    collision_events,
    budget,
    round_records,
    out_dir,
    bridge,
    host_client,
    binding,
    collision_monitor=None,
) -> dict:
    out_dir = Path(out_dir)
    started = _utc_now()
    tolerances = RefinementTolerances()
    base = {
        "schema": "vln.cap07b05.result.v1",
        "skill": SKILL_ID,
        "task_id": TASK_ID,
        "started_utc": started,
        "entry_reestablished": {
            "task_id": "cap07b-04",
            "decision": getattr(final_verification, "stage", None),
            "completed": bool(getattr(final_verification, "completed", False)),
            "final_state": final_state,
            "final_measurement": final_measurement.to_metadata(),
            "final_verification": final_verification.to_metadata(),
            "entry_authorization": entry_authorization.to_metadata(),
            "entry_first_motion_frame": (
                int(round_records[0]["pre_state"]["frame"])
                if round_records
                and isinstance(round_records[0], dict)
                and isinstance(round_records[0].get("pre_state"), dict)
                and type(round_records[0]["pre_state"].get("frame")) is int
                else None
            ),
        },
        "parking_completed": False,
        "parking_pose_ready": False,
        "no_safe_refinement": False,
        "collision_monitor": collision_monitor,
        "rounds": [],
        "kernel_executions": 0,
        "model": {"calls": 0, "reason": "refinement is deterministic geometry/controller work"},
    }
    outcome = {"code": 3, "status": "PARTIAL", "decision": RefinementStage.FAILED}
    try:
        if not getattr(final_verification, "completed", False):
            raise RuntimeError("the in-process Entry did not complete")
        if final_state.get("speed", 1.0) >= tolerances.stop_speed_mps:
            raise RuntimeError("the Entry final state is not stopped")
        measurements = _measure(
            session, ego, collision_count=len(collision_events)
        )
        current, current_state, current_samples, current_stability = measurements
        if not current.footprint_inside_bay:
            raise RuntimeError("Entry final footprint is not inside bay03")
        if current.speed_mps >= tolerances.stop_speed_mps:
            raise RuntimeError("Entry final state is moving")
        if current.collision_count:
            raise RuntimeError("Entry final state has a collision")
        extent = ego.bounding_box.extent
        base["vehicle"] = {
            "actor_id": int(ego.id),
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
            raise RuntimeError("vehicle bounding box differs from the configured footprint")
        # Compare the current real pose to the in-process Entry final and the
        # historical accepted CAP-07B-04 final.
        pose_gap = math.hypot(
            current.x - final_measurement.x, current.y - final_measurement.y
        )
        historical = _historical_entry_check(binding)
        historical_gap = math.hypot(
            current.x - historical["final_pose"]["x"],
            current.y - historical["final_pose"]["y"],
        )
        historical_heading_gap = abs(
            (math.degrees(current.yaw_rad - historical["final_pose"]["yaw_rad"]) + 180.0)
            % 360.0
            - 180.0
        )
        base["entry_reestablished"].update(
            {
                "pose_gap_m": round(pose_gap, 4),
                "historical_entry": historical,
                "historical_pose_gap_m": round(historical_gap, 4),
                "historical_heading_gap_deg": round(historical_heading_gap, 4),
            }
        )
        if pose_gap > 0.10 or historical_gap > 0.15 or historical_heading_gap > 2.0:
            raise RuntimeError(
                "current pose does not match the Entry completion evidence"
            )
        base["initial_state"] = current_state
        base["initial_samples"] = current_samples
        base["initial_measurement"] = current.to_metadata()
        _write_json(
            out_dir / "refinement_initial.json",
            {
                "state": current_state,
                "stability_samples": current_samples,
                "measurement": current.to_metadata(),
                "entry_historical": historical,
            },
        )
        selection = generate_candidates(
            current_x=current.x,
            current_y=current.y,
            current_heading_rad=current.yaw_rad,
            center=(float(BAY03_CENTER[0]), float(BAY03_CENTER[1])),
            bay_heading_rad=math.pi,
            bay_polygon=tuple((float(x), float(y)) for x, y in BAY03_POLYGON),
            footprint=PARKING_FOOTPRINT,
            obstacle_points=OBSTACLES,
            tolerances=tolerances,
        )
        base["candidate_selection"] = selection.to_metadata()
        _write_json(out_dir / "refinement_candidates.json", selection.to_metadata())
        plan = None
        if selection.ok:
            plan = plan_refinement_path(
                current,
                selection.selected,
                bay_polygon=tuple((float(x), float(y)) for x, y in BAY03_POLYGON),
                bay_center=(float(BAY03_CENTER[0]), float(BAY03_CENTER[1])),
                footprint=PARKING_FOOTPRINT,
                obstacle_points=OBSTACLES,
                tolerances=tolerances,
            )
            base["path_plan"] = plan.to_metadata()
            _write_json(out_dir / "refinement_route.json", plan.to_metadata())
        reasons = list(selection.reasons)
        if plan is not None and not plan.ok:
            reasons.extend(plan.reasons)
        if plan is None or not plan.ok:
            no_safe_completion_id = compute_entry_completion_id(
                entry_task_id="cap07b-04",
                entry_authorization_id=entry_authorization.authorization_id,
                entry_route_hash=route.route_hash,
                final_pose=(current.x, current.y, current.yaw_rad),
                final_verification_stage="ENTRY_COMPLETED",
                final_boundary_clearance_m=current.boundary_clearance_m,
                final_heading_error_deg=current.heading_error_deg,
            )
            base["entry_reestablished"]["entry_completion_inputs"] = {
                "entry_task_id": "cap07b-04",
                "entry_authorization_id": entry_authorization.authorization_id,
                "entry_route_hash": route.route_hash,
                "final_pose": [
                    float(current.x),
                    float(current.y),
                    float(current.yaw_rad),
                ],
                "final_verification_stage": "ENTRY_COMPLETED",
                "final_boundary_clearance_m": current.boundary_clearance_m,
                "final_heading_error_deg": current.heading_error_deg,
                "entry_completion_id": no_safe_completion_id,
            }
            result = no_safe_refinement_result(
                task_id=TASK_ID,
                bay_id="bay03",
                slot_node_id="park_slot",
                entry_completion_id=no_safe_completion_id,
                current=current,
                reasons=reasons or ("no_safe_refinement_path",),
                tolerances=tolerances,
            )
            base.update(
                {
                    "status": "PASS" if result.stage == RefinementStage.NO_SAFE else "PARTIAL",
                    "decision": result.stage,
                    "no_safe_refinement": result.stage == RefinementStage.NO_SAFE,
                    "refinement_verification": result.to_metadata(),
                    "error": None if result.stage == RefinementStage.NO_SAFE else ", ".join(result.reasons),
                    "final_state": current_state,
                    "final_measurement": current.to_metadata(),
                    "finished_utc": _utc_now(),
                }
            )
            _write_json(out_dir / "refinement_verification.json", result.to_metadata())
            _write_json(out_dir / "refinement_final.json", {"state": current_state, "measurement": current.to_metadata(), "verification": result.to_metadata()})
            _write_json(out_dir / "refinement_rounds.json", {"rounds": []})
            _write_geometry(out_dir, current, current, plan, base["rounds"])
            _snapshot_bridge(out_dir, bridge)
            _write_json(out_dir / "result.json", base)
            outcome.update(
                {
                    "code": 0 if result.stage == RefinementStage.NO_SAFE else 3,
                    "status": base["status"],
                    "decision": result.stage,
                    "result": base,
                }
            )
            return outcome

        entry_completion_id = compute_entry_completion_id(
            entry_task_id="cap07b-04",
            entry_authorization_id=entry_authorization.authorization_id,
            entry_route_hash=route.route_hash,
            final_pose=(current.x, current.y, current.yaw_rad),
            final_verification_stage="ENTRY_COMPLETED",
            final_boundary_clearance_m=current.boundary_clearance_m,
            final_heading_error_deg=current.heading_error_deg,
        )
        base["entry_reestablished"]["entry_completion_inputs"] = {
            "entry_task_id": "cap07b-04",
            "entry_authorization_id": entry_authorization.authorization_id,
            "entry_route_hash": route.route_hash,
            "final_pose": [
                float(current.x),
                float(current.y),
                float(current.yaw_rad),
            ],
            "final_verification_stage": "ENTRY_COMPLETED",
            "final_boundary_clearance_m": current.boundary_clearance_m,
            "final_heading_error_deg": current.heading_error_deg,
            "entry_completion_id": entry_completion_id,
        }
        refinement_budget = RefinementBudget()
        authorization = authorize_refinement(
            task_id=TASK_ID,
            bay_id="bay03",
            slot_node_id="park_slot",
            entry_completion_id=entry_completion_id,
            entry_authorization_id=entry_authorization.authorization_id,
            start_pose=(current.x, current.y, current.yaw_rad),
            target_pose=(selection.selected.x, selection.selected.y, selection.selected.heading_rad),
            plan_hash=plan.plan_hash,
            tolerances=tolerances,
            budget=refinement_budget,
            evidence={
                "entry_route_hash": route.route_hash,
                "entry_completion": base["entry_reestablished"],
                "candidate": selection.selected.to_metadata(),
                "path_plan": plan.to_metadata(),
            },
        )
        authorization = consume_refinement_authorization(
            authorization,
            task_id=TASK_ID,
            bay_id="bay03",
            slot_node_id="park_slot",
            entry_completion_id=entry_completion_id,
            plan_hash=plan.plan_hash,
        )
        base["refinement_authorization"] = authorization.to_metadata()
        _write_json(out_dir / "refinement_authorization.json", authorization.to_metadata())
        base["entry_completion_id"] = entry_completion_id
        budget_ref = refinement_budget
        measurement = current
        initial_boundary_floor = current.boundary_clearance_m or 0.05
        stop_reason = None
        phases = [
            (TerminalPhase.REVERSE_ALIGN, "reverse_align"),
            (TerminalPhase.FORWARD_RETURN, "forward_return"),
        ]
        for round_index, (phase, label) in enumerate(phases, start=1):
            if not authorization.is_active(
                task_id=TASK_ID,
                bay_id="bay03",
                slot_node_id="park_slot",
                entry_completion_id=entry_completion_id,
                plan_hash=plan.plan_hash,
            ):
                stop_reason = "refinement_authorization_inactive"
                break
            if not budget_ref.can_start_segment:
                stop_reason = "refinement_budget_exhausted"
                break
            phase_plan = build_refinement_phase_plan(
                measurement, selection.selected, phase, tolerances=tolerances
            )
            preflight = entry04._terminal_preflight(
                session, ego, route, phase_plan, plan.config, len(collision_events)
            )
            cb = preflight.get("current_measurement", {})
            floor = initial_boundary_floor
            round_record = {
                "round": round_index,
                "phase": phase,
                "phase_label": label,
                "plan": phase_plan.to_metadata(),
                "preflight": preflight,
                "pre_state": entry04._state(session, ego),
                "pre_measurement": measurement.to_metadata(),
                "kernel": None,
                "post_state": None,
                "post_measurement": None,
                "post_verification": None,
                "improvement": None,
                "budget_before": budget_ref.to_metadata(),
            }
            base["rounds"].append(round_record)
            if not preflight["ok"]:
                stop_reason = "preflight: " + ", ".join(preflight["reasons"])
                break
            if (
                cb.get("boundary_clearance_m") is not None
                and cb["boundary_clearance_m"] < floor - 1e-9
            ):
                stop_reason = "preflight_boundary_below_current"
                break
            kernel_result = _run_phase(
                session=session,
                ego=ego,
                route=route,
                plan=phase_plan,
                config=plan.config,
                entry_budget=budget,
                bridge=bridge,
                host_client=host_client,
                phase_label=label,
                round_index=round_index,
                baseline_collisions=len(collision_events),
                collision_events=collision_events,
                boundary_floor=floor,
            )
            base["kernel_executions"] += 1
            round_record["kernel"] = kernel_result["kernel"]
            if not kernel_result["ok"]:
                stop_reason = "kernel_failed: " + str(kernel_result["error"])
                break
            post, post_state, post_samples, post_stability = _measure(
                session, ego, collision_count=len(collision_events)
            )
            improved, improvement_reasons = refinement_phase_improved(
                phase,
                before=measurement,
                after=post,
                boundary_floor_m=floor,
                route_or_none=route,
                tolerances=tolerances,
            )
            execution = kernel_result["execution"] or {}
            travelled = float(execution.get("travelled_m") or execution.get("moved_m") or 0.0)
            sim_seconds = float(execution.get("sim_seconds") or 0.0)
            round_record.update(
                {
                    "post_state": post_state,
                    "post_samples": post_samples,
                    "post_measurement": post.to_metadata(),
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
                    "improvement": {
                        "ok": improved,
                        "reasons": list(improvement_reasons),
                    },
                }
            )
            budget_ref = budget_ref.record_segment(travelled, sim_seconds)
            round_record["budget_after"] = budget_ref.to_metadata()
            _write_json(out_dir / "refinement_rounds.json", {"rounds": base["rounds"]})
            if not improved:
                stop_reason = "phase_did_not_improve: " + ", ".join(improvement_reasons)
                break
            if not kernel_result["phase_success"]:
                stop_reason = "phase_incomplete"
                break
            measurement = post
            final_check = verify_refinement(
                task_id=TASK_ID,
                bay_id="bay03",
                slot_node_id="park_slot",
                entry_completion_id=entry_completion_id,
                plan_hash=plan.plan_hash,
                authorization=authorization,
                measurement=measurement,
                tolerances=tolerances,
            )
            round_record["post_verification"] = final_check.to_metadata()
            if final_check.ready:
                break
            if final_check.stage == RefinementStage.SAFE_STOP:
                stop_reason = "post_verification_safe_stop: " + ", ".join(final_check.reasons)
                break
        session.brake_to_stop(ego, max_ticks=120)
        final_measurement, final_state, final_samples, _stability = _measure(
            session, ego, collision_count=len(collision_events)
        )
        final_result = verify_refinement(
            task_id=TASK_ID,
            bay_id="bay03",
            slot_node_id="park_slot",
            entry_completion_id=entry_completion_id,
            plan_hash=plan.plan_hash,
            authorization=authorization,
            measurement=final_measurement,
            tolerances=tolerances,
        )
        success = final_result.ready and not collision_events and stop_reason is None
        base["status"] = "PASS" if success else "PARTIAL"
        base["decision"] = final_result.stage
        base["parking_pose_ready"] = final_result.ready
        base["no_safe_refinement"] = False
        base["final_state"] = final_state
        base["final_samples"] = final_samples
        base["final_measurement"] = final_measurement.to_metadata()
        base["refinement_verification"] = final_result.to_metadata()
        base["budget"] = budget_ref.to_metadata()
        base["collision_events"] = list(collision_events)
        base["stop_reason"] = stop_reason
        base["finished_utc"] = _utc_now()
        if not success:
            base["error"] = stop_reason or "final refinement: " + ", ".join(final_result.reasons)
            try:
                base["refinement_authorization"] = revoke_refinement_authorization(
                    authorization, base["error"]
                ).to_metadata()
                _write_json(out_dir / "refinement_authorization.json", base["refinement_authorization"])
            except Exception:
                pass
        _write_json(out_dir / "refinement_verification.json", final_result.to_metadata())
        _write_json(out_dir / "refinement_final.json", {"state": final_state, "samples": final_samples, "measurement": final_measurement.to_metadata(), "verification": final_result.to_metadata()})
        _write_json(out_dir / "refinement_rounds.json", {"rounds": base["rounds"]})
        _write_geometry(out_dir, current, final_measurement, plan, base["rounds"])
        _snapshot_bridge(out_dir, bridge)
        _write_json(out_dir / "result.json", base)
        outcome.update(
            {
                "code": 0 if success else 3,
                "status": base["status"],
                "decision": final_result.stage,
                "result": base,
            }
        )
        return outcome
    except Exception as error:
        base["status"] = "PARTIAL"
        base["decision"] = RefinementStage.FAILED
        base["error"] = f"{type(error).__name__}: {error}"
        base["traceback"] = traceback.format_exc()
        base["finished_utc"] = _utc_now()
        try:
            _snapshot_bridge(out_dir, bridge)
        except Exception:
            pass
        _write_json(out_dir / "result.json", base)
        outcome.update({"code": 3, "status": "PARTIAL", "decision": RefinementStage.FAILED, "result": base})
        return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "docs" / "evidence" / "vln-carla-cap-07b-05"))
    parser.add_argument("--kernel-host", default=entry04.DEFAULT_KERNEL_HOST)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    args = parser.parse_args(argv)
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    global OBSTACLES
    OBSTACLES = _load_obstacles()
    entry_dir = root / "entry_reestablish_inprocess"
    entry_dir.mkdir(parents=True, exist_ok=True)
    outcome: dict = {}
    started = _utc_now()

    def _after(**kwargs):
        kwargs.pop("out_dir", None)
        outcome.update(_callback(out_dir=root, **kwargs))

    entry_args = [
        "--host", args.host,
        "--port", str(args.port),
        "--kernel-host", args.kernel_host,
        "--output-dir", str(entry_dir),
        "--alignment-result", str(REPO_ROOT / "docs/evidence/vln-carla-cap-07b-03/result.json"),
        "--alignment-authorization", str(REPO_ROOT / "docs/evidence/vln-carla-cap-07b-03/alignment_authorization.json"),
        "--binding-json", str(BINDING_JSON),
        "--geometry-probe", str(GEOMETRY_PROBE),
    ]
    entry_code = entry04.main(entry_args, after_entry=_after)
    if not outcome:
        result = {
            "schema": "vln.cap07b05.result.v1",
            "skill": SKILL_ID,
            "task_id": TASK_ID,
            "started_utc": started,
            "status": "FAIL",
            "decision": "ENTRY_REESTABLISH_FAILED",
            "parking_completed": False,
            "entry_exit_code": entry_code,
            "error": "in-process Entry did not complete; refinement was not attempted",
            "finished_utc": _utc_now(),
        }
        _write_json(root / "result.json", result)
        return 4
    result = outcome.get("result", {})
    result["entry_exit_code"] = entry_code
    result["finished_utc"] = _utc_now()
    _write_json(root / "result.json", result)
    _write_json(
        root / "run.log",
        {
            "started_utc": started,
            "finished_utc": _utc_now(),
            "status": result.get("status"),
            "decision": result.get("decision"),
            "entry_exit_code": entry_code,
            "parking_completed": False,
            "error": result.get("error"),
        },
    )
    print(
        json.dumps(
            {
                "status": result.get("status"),
                "decision": result.get("decision"),
                "certification": result.get("certification"),
                "parking_completed": False,
                "parking_pose_ready": result.get("parking_pose_ready"),
                "no_safe_refinement": result.get("no_safe_refinement"),
                "initial": result.get("initial_measurement"),
                "final": result.get("final_measurement"),
                "rounds": len(result.get("rounds", [])),
                "kernel_executions": result.get("kernel_executions"),
                "collisions": len(result.get("collision_events", [])),
                "error": result.get("error"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return int(outcome.get("code", 3))


if __name__ == "__main__":
    sys.exit(main())
