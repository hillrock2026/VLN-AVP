#!/usr/bin/env python3
"""M1-VLN-AVP-CAP-08C-01: Session-centric end-to-end parking.

One Agent-Kernel Session is the only task lifecycle. This script is a session
driver, not a second runtime:

    user instruction + one Kernel Session
      -> real Taichu goal understanding through planner.plan
      -> parking-domain state written to the Kernel Context
      -> real Taichu target verification
      -> existing Entry / Pose Refinement / Final Verification / Completion Gate
      -> PARKING_COMPLETED

Parking-domain progress is carried in Context (``domain.parking``) and updated
through ``session.context.update`` (stage transitions), ``planner.plan`` and
``parking.move`` domain snapshots. There is no separate task lifecycle
object, task ID or second runtime.
"""

from __future__ import annotations

import argparse
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
import carla_cap07b05_refine as refine05  # noqa: E402
import carla_cap07b06_final_verify as final06  # noqa: E402
import carla_cap08b01_planner_navigation as bridge_runner  # noqa: E402
import carla_vln_bind_target as binder  # noqa: E402
import carla_vln_navigate as nav01e  # noqa: E402
from vln.carla.goal import GoalSpec, evaluate_goal  # noqa: E402
from vln.carla.image_annotate import annotate_candidates  # noqa: E402
from vln.carla.observation import write_rgb_png  # noqa: E402
from vln.carla.parking_entities import (  # noqa: E402
    assign_labels,
    bay_entity,
    project_bay,
)
from vln.carla.parking_verdict import BAY03_ID  # noqa: E402
from vln.ipc.envelope import Request  # noqa: E402
from vln.nav.binding_runtime import load_binding_artifact  # noqa: E402
from vln.parking.autonomous import (  # noqa: E402
    ApproachState,
    AutonomousParkingStage,
    VerificationObservation,
    approach_state_from_result,
    verify_target,
)
from vln.parking.session_decision import (  # noqa: E402
    GoalUnderstandingAction,
    GoalUnderstandingParseError,
    SessionDecisionParseError,
    build_goal_understanding_prompt,
    build_session_decision_prompt,
    evaluate_goal_understanding,
    evaluate_session_decision,
    parse_goal_understanding,
    parse_session_decision,
)
from vln.vlm.host_planner_client import (  # noqa: E402
    HostPlannerError,
    HostPlannerModelClient,
)

TASK_ID = "cap08c-01"
OUTPUT = REPO_ROOT / "docs/evidence/vln-carla-cap-08c-01"
KERNEL_HOST = Path(
    "/home/gaosong/workspace/Agentic_Program/m1-cap08b02-build/kernel_host"
)
BINDING_JSON = REPO_ROOT / "docs/evidence/cap07a/A/binding.json"
APPROACH_RESULT = REPO_ROOT / "docs/evidence/cap07b-01-w4-4096/result.json"
VERIFICATION_JSON = (
    REPO_ROOT / "docs/evidence/vln-carla-cap-07b-02/verification.json"
)
ENTRY_AUTHORIZATION = (
    REPO_ROOT / "docs/evidence/vln-carla-cap-07b-02/entry_authorization.json"
)
ALIGNMENT_RESULT = (
    REPO_ROOT / "docs/evidence/vln-carla-cap-07b-03/result.json"
)
ALIGNMENT_AUTHORIZATION = (
    REPO_ROOT / "docs/evidence/vln-carla-cap-07b-03/alignment_authorization.json"
)
GEOMETRY_PROBE = REPO_ROOT / "docs/evidence/carla-07a/geometry_probe.json"

DEFAULT_VIEWS = (
    ("view_a", (-5.0, -1.0, 1.6), -12.0, -25.0, 110.0),
    ("view_b", (-5.0, -0.2, 2.0), -20.0, -55.0, 110.0),
)
RECOVERY_VIEWS = (
    ("view_c", (-4.5, -1.8, 1.9), -15.0, -70.0, 110.0),
    ("view_d", (-6.0, 0.4, 2.2), -22.0, -10.0, 100.0),
)
GOAL_VIEWS = (
    ("goal_a", (0.0, 0.0, 2.0), -5.0, 0.0, 100.0),
    ("goal_b", (-4.0, 0.0, 2.0), -10.0, -20.0, 100.0),
)
MAX_VERIFICATION_ATTEMPTS = 2
STOP_SPEED_MPS = 0.25


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_clean(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=list))


def _context_payload(state: dict) -> dict:
    """Compact parking-domain state for Kernel Context (not raw evidence)."""

    stage_status = {}
    for name, result in (state.get("stage_results") or {}).items():
        if isinstance(result, dict):
            stage_status[name] = {
                "ok": bool(result.get("ok")),
                "reason": result.get("reason") or result.get("source"),
            }
    goal = state.get("goal_understanding") or {}
    verification = state.get("target_verification") or {}
    final = state.get("final_verification") or {}
    gate = state.get("completion_gate") or {}
    last = state.get("last_execution") or {}
    last_state = last.get("final_state") or {}
    payload = {
        "session_id": state.get("session_id"),
        "instruction": state.get("instruction"),
        "target": state.get("target"),
        "current_stage": state.get("current_stage"),
        "completed_stages": list(state.get("completed_stages") or ()),
        "stage_status": stage_status,
        "goal_understanding": {
            key: goal.get(key)
            for key in ("task_type", "target", "identity_clear", "decision")
            if key in goal
        },
        "target_verification": {
            key: verification.get(key)
            for key in (
                "stage",
                "identity_verified",
                "occupancy_verified",
                "evidence_sufficient",
                "target_confirmed",
                "reasons",
            )
            if key in verification
        },
        "recovery_state": state.get("recovery_state"),
        "last_execution": {
            "stage": last.get("stage"),
            "final_state": {
                key: last_state.get(key)
                for key in ("x", "y", "yaw_deg", "yaw_rad", "speed")
                if key in last_state
            },
            "kernel_correlation_count": len(
                last.get("kernel_correlations") or ()
            ),
        },
        "final_verification": (
            {
                key: final.get(key)
                for key in (
                    "decision",
                    "verification_passed",
                    "checks_passed",
                    "checks_total",
                    "reasons",
                )
                if key in final
            }
            or None
        ),
        "completion_gate": (
            {
                key: gate.get(key)
                for key in (
                    "decision",
                    "gate_decision",
                    "parking_completed",
                    "decision_id",
                    "verifier_result_sha256",
                )
                if key in gate
            }
            or None
        ),
    }
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def _sha256_file(path: str | Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _host_evidence(path: Path) -> dict:
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "size": path.stat().st_size,
        "mtime": datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
        "build_dir": str(path.parent),
    }


def _capture_view(
    session,
    ego,
    out_dir: Path,
    *,
    observation_id: str,
    view_name: str,
    offset: tuple[float, float, float],
    pitch: float,
    yaw: float,
    fov: float,
    overlay: bool,
    label: str = "A",
) -> dict:
    (
        frame,
        raw_path,
        camera_meta,
        ego_meta,
        camera_pose,
        ego_pose,
    ) = binder.capture_binding_frame(
        session,
        ego,
        out_dir,
        name=observation_id,
        fov=fov,
        camera_offset=offset,
        camera_pitch=pitch,
        camera_yaw=yaw,
    )
    record = {
        "observation_id": observation_id,
        "view": view_name,
        "frame_id": frame.frame_id,
        "raw_image": raw_path,
        "raw_image_sha256": _sha256_file(raw_path),
        "camera": camera_meta,
        "ego": ego_meta,
        "camera_offset": list(offset),
        "camera_pitch": pitch,
        "camera_yaw": yaw,
        "fov": fov,
        "overlay_image": None,
        "overlay_image_sha256": None,
        "projection": None,
        "view_signature": json.dumps(
            {
                "x": round(camera_pose.x, 3),
                "y": round(camera_pose.y, 3),
                "z": round(camera_pose.z, 3),
                "yaw": round(camera_pose.yaw_deg, 3),
                "pitch": round(camera_pose.pitch_deg, 3),
                "offset": list(offset),
            },
            sort_keys=True,
        ),
    }
    if not overlay:
        return record

    projected = project_bay(
        bay_entity(BAY03_ID),
        camera_pose,
        fov_deg=fov,
        width=binder.CAM_W,
        height=binder.CAM_H,
        floor_z=binder.FLOOR_Z,
        ego=ego_pose,
    )
    record["projection"] = {
        "bay_id": projected.entity.bay_id,
        "slot_node_id": projected.entity.slot_node_id,
        "all_in_frame": projected.all_in_frame,
        "visible_corners": projected.visible_corners,
        "corners": [
            [
                round(float(u), 3) if math.isfinite(float(u)) else None,
                round(float(v), 3) if math.isfinite(float(v)) else None,
            ]
            for u, v in projected.corners
        ],
    }
    if not projected.all_in_frame:
        record["reasons"] = ["target_not_fully_visible"]
        return record

    labelled = assign_labels([projected])
    buffer = bytearray(frame.rgb)
    annotate_candidates(buffer, frame.width, frame.height, labelled)
    overlay_path = out_dir / f"{observation_id}_overlay_{frame.frame_id}.png"
    write_rgb_png(
        str(overlay_path), bytes(buffer), frame.width, frame.height
    )
    record["overlay_image"] = str(overlay_path)
    record["overlay_image_sha256"] = _sha256_file(overlay_path)
    record["reasons"] = []
    return record


def _verification_observation(
    record: dict,
    *,
    binding,
    decision=None,
    parse_ok: bool,
    request_ok: bool,
    model_request_id: str,
    server_response_id: str | None,
    model_text: str,
    reasons: tuple[str, ...] = (),
) -> VerificationObservation:
    verification = None if decision is None else decision.verification
    entity_bay_id = record["projection"]["bay_id"]
    return VerificationObservation(
        observation_id=record["observation_id"],
        entity_bay_id=entity_bay_id,
        image_path=record["overlay_image"] or record["raw_image"],
        image_sha256=(
            record["overlay_image_sha256"] or record["raw_image_sha256"]
        ),
        raw_image_path=record["raw_image"],
        raw_image_sha256=record["raw_image_sha256"],
        frame_id=int(record["frame_id"]),
        captured_at=_utc_now(),
        pose={
            "x": float(record["ego"]["x"]),
            "y": float(record["ego"]["y"]),
            "yaw": float(record["ego"]["yaw"]),
        },
        camera={
            "x": float(record["camera"]["world_transform"]["x"]),
            "y": float(record["camera"]["world_transform"]["y"]),
            "z": float(record["camera"]["world_transform"]["z"]),
            "yaw": float(record["camera"]["world_transform"]["yaw"]),
            "pitch": float(record["camera"]["world_transform"]["pitch"]),
        },
        view_signature=record["view_signature"],
        model_request_id=model_request_id,
        server_response_id=server_response_id,
        model_text=model_text,
        occupancy=(
            "unknown" if verification is None else verification.occupancy
        ),
        boundary_clear=bool(
            verification is not None and verification.boundary_clear
        ),
        occluded=bool(verification is not None and verification.occluded),
        evidence_sufficient=bool(
            verification is not None and verification.evidence_sufficient
        ),
        identity_verified=bool(
            request_ok
            and parse_ok
            and entity_bay_id == binding.bay_id
            and record["projection"]["all_in_frame"]
        ),
        identity_mismatch=bool(
            record["projection"]["all_in_frame"]
            and entity_bay_id != binding.bay_id
        ),
        parse_ok=parse_ok,
        request_ok=request_ok,
        reasons=tuple(reasons),
    )


def _session_control(
    host_client,
    capability: str,
    payload: dict,
    request_id: str,
    *,
    session_id: str | None = None,
    expected_revision: int | None = None,
) -> dict:
    response = host_client.send(
        Request(
            request_id=request_id,
            capability_id=capability,
            payload=json.dumps(payload, separators=(",", ":")),
            session_id=session_id,
            expected_context_revision=expected_revision,
        )
    )
    output = None
    if isinstance(response.output, str):
        try:
            output = json.loads(response.output)
        except json.JSONDecodeError:
            output = None
    return {
        "request_id": request_id,
        "capability_id": capability,
        "accepted": response.accepted,
        "submission_status": response.submission_status,
        "observation_status": response.observation_status,
        "session_id": response.session_id,
        "session_state": response.session_state,
        "context_revision": response.context_revision,
        "turn": response.turn,
        "context_before": response.context_before,
        "context_after": response.context_after,
        "error": None if response.error is None else dict(response.error),
        "output": output,
    }


def _write_context_state(
    host_client,
    session_id: str,
    state: dict,
    *,
    status: str,
    request_id: str,
) -> dict:
    """Write the parking-domain snapshot to Context with a revision guard."""

    parking_payload = _json_clean(_context_payload(state))
    response = _session_control(
        host_client,
        "session.context.update",
        {
            "parking": parking_payload,
            "kind": "stage_transition",
            "status": status,
        },
        request_id,
        session_id=session_id,
        expected_revision=entry04.CONTEXT_REVISION,
    )
    if (
        not response["accepted"]
        or response["observation_status"] != "success"
    ):
        raise RuntimeError(
            "session.context.update failed: "
            f"{response.get('error')}"
        )
    context_after = response.get("context_after") or {}
    parked = ((context_after.get("domain") or {}).get("parking"))
    if _json_clean(parked) != parking_payload:
        raise RuntimeError(
            "Context parking state does not match the written domain state"
        )
    if isinstance(response.get("context_revision"), int):
        entry04.CONTEXT_REVISION = response["context_revision"]
    return response


def _run_goal_understanding(
    *,
    session,
    ego,
    out_dir: Path,
    host_client,
    session_id: str,
    binding,
    vehicle_state: str,
    state: dict,
) -> dict:
    """Real Taichu goal understanding, before any vehicle motion."""

    out_dir.mkdir(parents=True, exist_ok=True)
    attempts = []
    for attempt_index, (name, offset, pitch, yaw, fov) in enumerate(
        GOAL_VIEWS, start=1
    ):
        observation_id = f"goal_{attempt_index:02d}_{name}"
        record = _capture_view(
            session,
            ego,
            out_dir,
            observation_id=observation_id,
            view_name=name,
            offset=offset,
            pitch=pitch,
            yaw=yaw,
            fov=fov,
            overlay=False,
        )
        prompt = build_goal_understanding_prompt(
            instruction=binding.instruction,
            target_bay=binding.bay_id,
            target_slot=binding.slot_node_id,
            binding_status=binding.status,
            vehicle_state=vehicle_state,
            stage=state["current_stage"],
        )
        client = HostPlannerModelClient(
            host_client,
            session_id=session_id,
            context_revision=entry04.CONTEXT_REVISION,
            request_id_prefix=f"cap08c-goal-a{attempt_index}",
            domain={
                "capability": "planner.plan",
                "stage": state["current_stage"],
                "skill": "vln.parking.goal_understanding",
                "attempt": attempt_index,
                "observation_id": observation_id,
                "target": binding.bay_id,
                "target_kind": "车位",
                "route_goal_node_id": binding.slot_node_id,
                "frame_id": record["frame_id"],
                "image_sha256": record["raw_image_sha256"],
                "view": name,
                "parking": _json_clean(_context_payload(state)),
            },
        )
        request_record = {
            "observation_id": observation_id,
            "prompt": prompt,
            "raw_image": record["raw_image"],
            "raw_image_sha256": record["raw_image_sha256"],
            "attempt": attempt_index,
        }
        try:
            raw = client.generate(record["raw_image"], prompt)
            understanding = parse_goal_understanding(raw)
            evaluated = evaluate_goal_understanding(
                understanding,
                expected_bay=binding.bay_id,
                expected_slot=binding.slot_node_id,
            )
            if isinstance(client.context_revision_after, int):
                entry04.CONTEXT_REVISION = client.context_revision_after
            exchange = client.last_exchange
            if exchange is not None:
                output = exchange.output or {}
                server = output.get("server_response") or {}
                request_record.update(
                    {
                        "request_id": exchange.request_id,
                        "planner_request_id": exchange.planner_request_id,
                        "planning_artifact_id": exchange.planning_artifact_id,
                        "context_revision": exchange.context_revision,
                        "final_prompt": output.get("prompt"),
                        "final_prompt_sha256": output.get("prompt_sha256"),
                        "context_selection": output.get("context_selection"),
                        "server_response": server,
                        "model": output.get("model"),
                    }
                )
                server_response_id = server.get("server_response_id")
            else:
                server_response_id = None
            attempt = {
                "attempt": attempt_index,
                "observation": record,
                "request": request_record,
                "raw_output": raw,
                "server_response_id": server_response_id,
                "parsed": understanding.to_metadata(),
                "evaluated": evaluated,
            }
            attempts.append(attempt)
            if evaluated.get("start_session"):
                return {
                    "ok": True,
                    "understanding": understanding.to_metadata(),
                    "evaluated": evaluated,
                    "attempts": attempts,
                    "server_response_id": server_response_id,
                }
            if evaluated.get("safe_stop"):
                return {
                    "ok": False,
                    "safe_stop": True,
                    "understanding": understanding.to_metadata(),
                    "evaluated": evaluated,
                    "attempts": attempts,
                    "reasons": ["goal_understanding_safe_stop"],
                }
            # REQUEST_OBSERVATION: try the next view once.
        except GoalUnderstandingParseError as error:
            request_record["parse_error"] = str(error)
            attempts.append(
                {
                    "attempt": attempt_index,
                    "observation": record,
                    "request": request_record,
                    "error": f"GoalUnderstandingParseError: {error}",
                }
            )
        except HostPlannerError as error:
            request_record["model_error"] = str(error)
            attempts.append(
                {
                    "attempt": attempt_index,
                    "observation": record,
                    "request": request_record,
                    "error": f"HostPlannerError: {error}",
                }
            )
        except Exception as error:
            request_record["error"] = (
                f"{type(error).__name__}: {error}"
            )
            attempts.append(
                {
                    "attempt": attempt_index,
                    "observation": record,
                    "request": request_record,
                    "error": request_record["error"],
                    "traceback": traceback.format_exc(),
                }
            )
    return {
        "ok": False,
        "understanding": None,
        "evaluated": None,
        "attempts": attempts,
        "reasons": ["goal_understanding_not_started"],
    }


def _run_verification_attempts(
    *,
    session,
    ego,
    out_dir: Path,
    binding,
    approach_live: ApproachState,
    host_client,
    session_id: str,
    state: dict,
    collision_count: int,
) -> dict:
    attempts: list[dict] = []
    last_result = None
    for attempt_index in range(1, MAX_VERIFICATION_ATTEMPTS + 1):
        views = DEFAULT_VIEWS if attempt_index == 1 else RECOVERY_VIEWS
        attempt_dir = out_dir / f"attempt_{attempt_index:02d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        observations = []
        requests = []
        actions = []
        stopped = entry04._state(session, ego)["speed"] < STOP_SPEED_MPS
        for view_index, (name, offset, pitch, yaw, fov) in enumerate(
            views, start=1
        ):
            observation_id = f"attempt{attempt_index:02d}_{view_index:02d}_{name}"
            record = _capture_view(
                session,
                ego,
                attempt_dir,
                observation_id=observation_id,
                view_name=name,
                offset=offset,
                pitch=pitch,
                yaw=yaw,
                fov=fov,
                overlay=True,
            )
            request_record = {"observation_id": observation_id}
            decision = None
            parse_ok = False
            request_ok = False
            model_text = ""
            server_response_id = None
            reasons: tuple[str, ...] = tuple(record.get("reasons") or ())
            prompt = None
            if record["overlay_image"] is not None:
                feedback = (
                    "goal understanding passed; no Entry motion has been "
                    "commanded yet"
                )
                if view_index > 1:
                    feedback += (
                        "；这是本轮第 2 个独立视角，必须只依据本帧独立判断，"
                        "不得照抄上一视角的结论"
                    )
                prompt = build_session_decision_prompt(
                    instruction=binding.instruction,
                    target_bay=binding.bay_id,
                    target_slot=binding.slot_node_id,
                    stage="TARGET_VERIFICATION",
                    completed_stages=tuple(
                        state.get("completed_stages") or ()
                    ),
                    recent_feedback=feedback,
                    label="A",
                )
                client = HostPlannerModelClient(
                    host_client,
                    session_id=session_id,
                    context_revision=entry04.CONTEXT_REVISION,
                    request_id_prefix=(
                        f"cap08c-verify-a{attempt_index}-o{view_index}"
                    ),
                    domain={
                        "capability": "planner.plan",
                        "stage": "TARGET_VERIFICATION",
                        "skill": "vln.parking.autonomous",
                        "attempt": attempt_index,
                        "observation_id": observation_id,
                        "target": binding.bay_id,
                        "target_kind": "车位",
                        "route_goal_node_id": binding.slot_node_id,
                        "frame_id": record["frame_id"],
                        "image_sha256": record["overlay_image_sha256"],
                        "view": name,
                        "parking": _json_clean(_context_payload(state)),
                    },
                )
                try:
                    model_text = client.generate(
                        record["overlay_image"], prompt
                    )
                    request_ok = True
                    if isinstance(client.context_revision_after, int):
                        entry04.CONTEXT_REVISION = (
                            client.context_revision_after
                        )
                    exchange = client.last_exchange
                    if exchange is not None:
                        output = exchange.output or {}
                        server = output.get("server_response") or {}
                        server_response_id = server.get("server_response_id")
                        request_record.update(
                            {
                                "request_id": exchange.request_id,
                                "planner_request_id": exchange.planner_request_id,
                                "planning_artifact_id": exchange.planning_artifact_id,
                                "context_revision": exchange.context_revision,
                                "final_prompt": output.get("prompt"),
                                "final_prompt_sha256": output.get("prompt_sha256"),
                                "context_selection": output.get(
                                    "context_selection"
                                ),
                                "server_response": server,
                                "model": output.get("model"),
                            }
                        )
                    decision = parse_session_decision(model_text, label="A")
                    parse_ok = True
                    action_eval = evaluate_session_decision(
                        decision,
                        expected_label="A",
                        expected_bay=binding.bay_id,
                        observed_bay=record["projection"]["bay_id"],
                    )
                    actions.append(action_eval)
                    record["session_action"] = action_eval
                except SessionDecisionParseError as error:
                    reasons = reasons + (f"parse_error:{error}",)
                    request_record["parse_error"] = str(error)
                except HostPlannerError as error:
                    reasons = reasons + (f"model_call_failed:{error}",)
                    request_record["model_error"] = str(error)
                except Exception as error:
                    reasons = reasons + (
                        f"verification_exception:{type(error).__name__}:{error}",
                    )
                    request_record["error"] = str(error)
                    request_record["traceback"] = traceback.format_exc()
                record["model_called"] = True
                record["model_text"] = model_text
                record["server_response_id"] = server_response_id
                record["parse_ok"] = parse_ok
                record["prompt"] = prompt
            else:
                reasons = reasons + ("target_not_fully_visible",)

            observation = _verification_observation(
                record,
                binding=binding,
                decision=decision,
                parse_ok=parse_ok,
                request_ok=request_ok,
                model_request_id=request_record.get("request_id")
                or observation_id,
                server_response_id=server_response_id,
                model_text=model_text or "",
                reasons=reasons,
            )
            record["verification"] = observation.to_metadata()
            request_record["reasons"] = list(reasons)
            request_record["verification"] = observation.to_metadata()
            requests.append(request_record)
            observations.append(observation)
            _write_json(attempt_dir / f"{observation_id}.json", record)

        result = verify_target(
            approach_live,
            observations,
            binding=binding,
            stopped=stopped,
            collision_count=collision_count,
        )
        last_result = result
        attempt_record = {
            "attempt": attempt_index,
            "views": [name for name, *_ in views],
            "observations": [item.to_metadata() for item in observations],
            "requests": requests,
            "actions": actions,
            "verification": result.to_metadata(),
            "stopped": stopped,
        }
        attempts.append(attempt_record)
        _write_json(attempt_dir / "verification.json", attempt_record)
        if result.stage == AutonomousParkingStage.TARGET_CONFIRMED:
            if actions and all(
                action.get("continue_session") is True for action in actions
            ):
                return {
                    "ok": True,
                    "stage": result.stage,
                    "verification": result.to_metadata(),
                    "result_object": result,
                    "attempts": attempts,
                    "recovery_used": attempt_index > 1,
                }
            if any(action.get("safe_stop") for action in actions):
                break
        if any(action.get("safe_stop") for action in actions):
            break
        if result.stage == AutonomousParkingStage.REJECTED:
            break
    return {
        "ok": False,
        "stage": None if last_result is None else last_result.stage,
        "verification": (
            None if last_result is None else last_result.to_metadata()
        ),
        "result_object": last_result,
        "attempts": attempts,
        "recovery_used": len(attempts) > 1,
    }


def _composite_completion_decision(final: dict) -> dict | None:
    verifier = final.get("verifier") or {}
    gate = final.get("gate") or {}
    if not final.get("final_parking_verified"):
        return None
    if verifier.get("decision") != "FINAL_PARKING_VERIFIED":
        return None
    if gate.get("decision") != "PARKING_COMPLETED" or not gate.get(
        "parking_completed"
    ):
        return None
    return {
        **gate,
        "source": "final_parking_verifier",
        "decision": "FINAL_PARKING_VERIFIED",
        "gate_decision": gate.get("decision"),
        "parking_completed": True,
        "verifier_result_sha256": verifier.get("result_sha256")
        or gate.get("verifier_result_sha256"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--kernel-host", default=str(KERNEL_HOST))
    parser.add_argument("--output-dir", default=str(OUTPUT))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--max-new-tokens", type=int, default=4096)
    parser.add_argument("--model-timeout", type=float, default=240.0)
    parser.add_argument("--enable-thinking", action="store_true", default=True)
    parser.add_argument("--kernel-exec-timeout-ms", type=int, default=180000)
    parser.add_argument(
        "--session-id", default=f"{TASK_ID}-s1-{int(time.time())}"
    )
    args = parser.parse_args(argv)

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    entry_dir = output / "entry"
    refine_dir = output / "refinement"
    final_dir = output / "final"
    goal_dir = output / "goal_understanding"
    verification_dir = output / "target_verification"
    for path in (entry_dir, refine_dir, final_dir, goal_dir, verification_dir):
        path.mkdir(parents=True, exist_ok=True)
    started = _utc_now()
    host_exe = Path(args.kernel_host).resolve()
    if not (host_exe.is_file() and os.access(host_exe, os.X_OK)):
        raise SystemExit(f"--kernel-host is not executable: {host_exe}")

    result: dict = {
        "schema": "vln.cap08c01.session_parking.v1",
        "task_id": TASK_ID,
        "session_id": args.session_id,
        "started_utc": started,
        "git": entry04._git_state(),
        "host": _host_evidence(host_exe),
        "user_instruction": None,
        "status": "FAIL",
        "parking_completed": False,
        "completion_level": [],
        "stage_revisions": [],
        "error": None,
    }

    try:
        binding = load_binding_artifact(str(BINDING_JSON))
        if binding.bay_id != "bay03" or binding.slot_node_id != "park_slot":
            raise ValueError(
                f"binding identity is {binding.bay_id}/{binding.slot_node_id}, "
                "expected bay03/park_slot"
            )
        approach_result = json.loads(APPROACH_RESULT.read_text(encoding="utf-8"))
        approach_historical = approach_state_from_result(approach_result)
        if not approach_historical.matches_binding(binding):
            raise ValueError("accepted approach identity does not match binding")
        if approach_result.get("goal_spec", {}).get("node_id") != "park_entry":
            raise ValueError("accepted approach goal is not park_entry")
        alignment_result = json.loads(
            ALIGNMENT_RESULT.read_text(encoding="utf-8")
        )
        alignment_auth = json.loads(
            ALIGNMENT_AUTHORIZATION.read_text(encoding="utf-8")
        )
        if (
            alignment_result.get("status") != "PASS"
            or alignment_result.get("decision") != "ALIGNMENT_COMPLETED"
        ):
            raise ValueError("accepted alignment is not ALIGNMENT_COMPLETED")
        if alignment_auth.get("decision") != "ALIGNMENT_AUTHORIZED":
            raise ValueError("accepted alignment authorization is not valid")
    except Exception as error:
        result["status"] = "BLOCKED"
        result["error"] = f"preconditions: {type(error).__name__}: {error}"
        result["finished_utc"] = _utc_now()
        _write_json(output / "result.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2)[:5000])
        return 2

    result["user_instruction"] = binding.instruction
    result["binding"] = binding.to_metadata()
    result["approach_source"] = {
        "path": str(APPROACH_RESULT),
        "sha256": _sha256_file(APPROACH_RESULT),
        "approach": approach_historical.to_metadata(),
    }
    result["alignment_source"] = {
        "result_path": str(ALIGNMENT_RESULT),
        "result_sha256": _sha256_file(ALIGNMENT_RESULT),
        "authorization_path": str(ALIGNMENT_AUTHORIZATION),
        "authorization_sha256": _sha256_file(ALIGNMENT_AUTHORIZATION),
        "decision": alignment_result.get("decision"),
    }

    state: dict = {
        "session_id": args.session_id,
        "instruction": binding.instruction,
        "target": {
            "bay_id": binding.bay_id,
            "slot_node_id": binding.slot_node_id,
            "target_id": "bay03",
            "approach_node_id": "park_entry",
        },
        "current_stage": "TARGET_BINDING",
        "completed_stages": [],
        "stage_results": {},
        "goal_understanding": None,
        "target_verification": None,
        "recovery_state": {
            "attempts": 0,
            "max_attempts": MAX_VERIFICATION_ATTEMPTS,
            "used": False,
        },
        "last_execution": None,
        "final_verification": None,
        "completion_gate": None,
    }
    entry04.PARKING_CONTEXT = _context_payload(state)
    entry04.SESSION_ID = args.session_id
    entry04.CONTEXT_REVISION = None
    run_state: dict = {
        "goal": None,
        "verification": None,
        "entry": None,
        "refinement": None,
        "final": None,
        "session": {},
        "failure": None,
        "revisions": [],
    }

    def _set_stage(
        stage: str,
        *,
        completed: list[str] | None = None,
        status: str = "running",
        request_id: str,
        host_client,
    ) -> None:
        state["current_stage"] = stage
        if completed is not None:
            state["completed_stages"] = list(completed)
        entry04.PARKING_CONTEXT = _context_payload(state)
        response = _write_context_state(
            host_client,
            args.session_id,
            state,
            status=status,
            request_id=request_id,
        )
        run_state["revisions"].append(
            {
                "stage": stage,
                "status": status,
                "context_revision": response.get("context_revision"),
                "turn": response.get("turn"),
                "request_id": request_id,
            }
        )

    def _before_entry(**kwargs):
        session = kwargs["session"]
        ego = kwargs["ego"]
        initial_state = kwargs["initial_state"]
        collision_events = kwargs["collision_events"]
        host_client = kwargs["host_client"]

        live_gate = evaluate_goal(
            GoalSpec(
                node_id="park_entry",
                x=float(approach_result["goal_spec"]["x"]),
                y=float(approach_result["goal_spec"]["y"]),
                heading_rad=float(approach_result["goal_spec"]["heading_rad"]),
                distance_tolerance_m=1.5,
                heading_tolerance_rad=math.radians(30.0),
                stop_speed_mps=STOP_SPEED_MPS,
            ),
            nav01e.VehiclePose(
                x=float(initial_state["x"]),
                y=float(initial_state["y"]),
                heading=float(initial_state["yaw_rad"]),
            ),
            speed_mps=float(initial_state["speed"]),
            stopped=float(initial_state["speed"]) < STOP_SPEED_MPS,
        )
        if not live_gate.ok:
            run_state["failure"] = (
                "live pose is not at the accepted approach: "
                + ", ".join(live_gate.reasons)
            )
            _set_stage(
                "TARGET_VERIFICATION",
                status="safe_stop",
                request_id=f"{TASK_ID}-verification-approach-gate",
                host_client=host_client,
            )
            return {
                "ok": False,
                "decision": entry04.EntryStage.SAFE_STOP,
                "reasons": [run_state["failure"]],
            }

        vehicle_state = (
            f"x={initial_state['x']:.3f}, y={initial_state['y']:.3f}, "
            f"yaw={initial_state['yaw_deg']:.3f} deg, "
            f"speed={initial_state['speed']:.3f} m/s, stopped=true"
        )
        goal = _run_goal_understanding(
            session=session,
            ego=ego,
            out_dir=goal_dir,
            host_client=host_client,
            session_id=args.session_id,
            binding=binding,
            vehicle_state=vehicle_state,
            state=state,
        )
        run_state["goal"] = goal
        _write_json(goal_dir / "result.json", goal)
        if not goal.get("ok"):
            run_state["failure"] = (
                "goal understanding did not start the session: "
                + ", ".join(goal.get("reasons") or ())
            )
            state["stage_results"]["TARGET_BINDING"] = {
                "ok": False,
                "reason": run_state["failure"],
            }
            _set_stage(
                "TARGET_BINDING",
                status="blocked",
                request_id=f"{TASK_ID}-goal-understanding-blocked",
                host_client=host_client,
            )
            _session_control(
                host_client,
                "session.close",
                {"session_id": args.session_id},
                f"{TASK_ID}-session-close-goal-blocked",
            )
            return {
                "ok": False,
                "decision": entry04.EntryStage.SAFE_STOP,
                "reasons": [run_state["failure"]],
            }

        state["goal_understanding"] = goal.get("understanding")
        state["stage_results"]["TARGET_BINDING"] = {
            "ok": True,
            "source": "accepted CAP-07A binding",
            "evidence": binding.to_metadata(),
        }
        state["stage_results"]["APPROACH"] = {
            "ok": True,
            "source": "accepted CAP-07B-01 approach",
            "live_pose_gate": live_gate.to_metadata(),
        }
        _set_stage(
            "TARGET_VERIFICATION",
            completed=["TARGET_BINDING", "APPROACH"],
            status="running",
            request_id=f"{TASK_ID}-stage-target-verification",
            host_client=host_client,
        )

        live_pose = {
            "x": round(float(initial_state["x"]), 4),
            "y": round(float(initial_state["y"]), 4),
            "yaw": round(float(initial_state["yaw_deg"]), 4),
        }
        approach_live = replace(
            approach_historical,
            pose=live_pose,
            speed_mps=round(float(initial_state["speed"]), 4),
            source="live verification at restored approach pose",
        )
        verification = _run_verification_attempts(
            session=session,
            ego=ego,
            out_dir=verification_dir,
            binding=binding,
            approach_live=approach_live,
            host_client=host_client,
            session_id=args.session_id,
            state=state,
            collision_count=len(collision_events),
        )
        verification.pop("result_object", None)
        run_state["verification"] = verification
        _write_json(verification_dir / "result.json", verification)
        state["target_verification"] = verification.get("verification")
        state["recovery_state"]["used"] = bool(
            verification.get("recovery_used")
        )
        state["recovery_state"]["attempts"] = len(
            verification.get("attempts") or []
        )
        if verification.get("ok"):
            state["stage_results"]["TARGET_VERIFICATION"] = {
                "ok": True,
                "verification": verification.get("verification"),
                "recovery_used": verification.get("recovery_used"),
            }
            state["stage_results"]["ALIGNMENT"] = {
                "ok": True,
                "source": "accepted CAP-07B-03 alignment",
                "decision": alignment_result.get("decision"),
            }
            _set_stage(
                "ENTRY",
                completed=[
                    "TARGET_BINDING",
                    "APPROACH",
                    "TARGET_VERIFICATION",
                    "ALIGNMENT",
                ],
                status="running",
                request_id=f"{TASK_ID}-stage-entry",
                host_client=host_client,
            )
            return {
                "ok": True,
                "verification": verification.get("verification"),
                "recovery_used": verification.get("recovery_used"),
            }

        run_state["failure"] = "target verification failed"
        state["stage_results"]["TARGET_VERIFICATION"] = {
            "ok": False,
            "verification": verification.get("verification"),
            "attempts": verification.get("attempts"),
        }
        _set_stage(
            "TARGET_VERIFICATION",
            status="safe_stop",
            request_id=f"{TASK_ID}-stage-target-verification-failed",
            host_client=host_client,
        )
        _session_control(
            host_client,
            "session.close",
            {"session_id": args.session_id},
            f"{TASK_ID}-session-close-verification-failed",
        )
        return {
            "ok": False,
            "decision": entry04.EntryStage.SAFE_STOP,
            "reasons": [run_state["failure"]],
        }

    def _after_entry(**kwargs):
        session = kwargs["session"]
        ego = kwargs["ego"]
        host_client = kwargs["host_client"]
        final_verification = kwargs["final_verification"]
        collision_events = kwargs["collision_events"]
        entry_kernel = tuple(
            {
                "request_id": (record.get("kernel") or {}).get("request_id"),
                "intent_id": (record.get("kernel") or {}).get("intent_id"),
                "execution_status": (record.get("kernel") or {}).get(
                    "execution_status"
                ),
                "session_id": (record.get("kernel") or {}).get("session_id"),
                "context_revision": (record.get("kernel") or {}).get(
                    "context_revision"
                ),
            }
            for record in kwargs.get("round_records") or ()
            if (record.get("kernel") or {}).get("request_id")
        )
        run_state["entry"] = {
            "decision": final_verification.stage,
            "completed": final_verification.completed,
            "final_state": kwargs["final_state"],
            "final_measurement": kwargs["final_measurement"].to_metadata(),
            "final_verification": final_verification.to_metadata(),
            "kernel_correlations": list(entry_kernel),
        }
        if not final_verification.completed:
            run_state["failure"] = "Entry did not complete"
            state["stage_results"]["ENTRY"] = {
                "ok": False,
                "verification": final_verification.to_metadata(),
            }
            _set_stage(
                "ENTRY",
                status="safe_stop",
                request_id=f"{TASK_ID}-stage-entry-failed",
                host_client=host_client,
            )
            return
        state["stage_results"]["ENTRY"] = {
            "ok": True,
            "final_state": kwargs["final_state"],
            "final_measurement": kwargs["final_measurement"].to_metadata(),
            "kernel_correlations": list(entry_kernel),
        }
        state["last_execution"] = {
            "stage": "ENTRY",
            "final_state": kwargs["final_state"],
            "kernel_correlations": list(entry_kernel),
        }
        _set_stage(
            "POSE_REFINEMENT",
            completed=[
                "TARGET_BINDING",
                "APPROACH",
                "TARGET_VERIFICATION",
                "ALIGNMENT",
                "ENTRY",
            ],
            status="running",
            request_id=f"{TASK_ID}-stage-pose-refinement",
            host_client=host_client,
        )

        refine_kwargs = dict(kwargs)
        refine_kwargs.pop("out_dir", None)
        outcome = refine05._callback(out_dir=refine_dir, **refine_kwargs)
        refine_result = outcome.get("result") or {}
        run_state["refinement"] = outcome
        refine_ok = bool(
            outcome.get("status") == "PASS"
            and refine_result.get("parking_pose_ready") is True
        )
        state["stage_results"]["POSE_REFINEMENT"] = {
            "ok": refine_ok,
            "decision": outcome.get("decision"),
            "status": outcome.get("status"),
            "final_measurement": refine_result.get("final_measurement"),
            "rounds": refine_result.get("rounds"),
        }
        if not refine_ok:
            run_state["failure"] = "refinement did not reach PARKING_POSE_READY"
            _set_stage(
                "POSE_REFINEMENT",
                status="failed",
                request_id=f"{TASK_ID}-stage-pose-refinement-failed",
                host_client=host_client,
            )
            return
        state["last_execution"] = {
            "stage": "POSE_REFINEMENT",
            "final_state": refine_result.get("final_state"),
            "rounds": refine_result.get("rounds"),
        }
        _set_stage(
            "FINAL_VERIFICATION",
            completed=[
                "TARGET_BINDING",
                "APPROACH",
                "TARGET_VERIFICATION",
                "ALIGNMENT",
                "ENTRY",
                "POSE_REFINEMENT",
            ],
            status="running",
            request_id=f"{TASK_ID}-stage-final-verification",
            host_client=host_client,
        )

        final = final06._run_final_verification(kwargs, outcome, final_dir)
        run_state["final"] = final
        _write_json(final_dir / "session_final.json", final)
        verifier = final.get("verifier") or {}
        verifier_checks = verifier.get("checks") or {}
        state["final_verification"] = {
            "decision": verifier.get("decision"),
            "verification_passed": verifier.get("verification_passed"),
            "checks_passed": sum(
                1 for value in verifier_checks.values() if value is True
            ),
            "checks_total": len(verifier_checks),
            "reasons": verifier.get("reasons"),
        }
        state["stage_results"]["FINAL_VERIFICATION"] = {
            "ok": bool(final.get("final_parking_verified")),
            "verifier": final.get("verifier"),
        }
        composite = _composite_completion_decision(final)
        state["completion_gate"] = composite
        state["stage_results"]["COMPLETION"] = {
            "ok": composite is not None,
            "gate": final.get("gate"),
        }
        if composite is not None:
            state["completed_stages"] = [
                "TARGET_BINDING",
                "APPROACH",
                "TARGET_VERIFICATION",
                "ALIGNMENT",
                "ENTRY",
                "POSE_REFINEMENT",
                "FINAL_VERIFICATION",
                "COMPLETION",
            ]
            state["current_stage"] = "COMPLETED"
            _set_stage(
                "COMPLETED",
                completed=state["completed_stages"],
                status="completed",
                request_id=f"{TASK_ID}-stage-completed",
                host_client=host_client,
            )
        else:
            run_state["failure"] = (
                "final verification or completion gate did not complete"
            )
            _set_stage(
                "FINAL_VERIFICATION",
                status="failed",
                request_id=f"{TASK_ID}-stage-final-verification-failed",
                host_client=host_client,
            )

        run_state["session"]["get"] = _session_control(
            host_client,
            "session.get",
            {"session_id": args.session_id},
            f"{TASK_ID}-session-get",
        )
        run_state["session"]["close"] = _session_control(
            host_client,
            "session.close",
            {"session_id": args.session_id},
            f"{TASK_ID}-session-close",
        )
        run_state["session"]["get_after_close"] = _session_control(
            host_client,
            "session.get",
            {"session_id": args.session_id},
            f"{TASK_ID}-session-get-after-close",
        )

    bridge_state = None
    bridge_stopped = None
    old_env = {}
    try:
        bridge_state = bridge_runner._start_planner_bridge(
            args.python,
            max_new_tokens=args.max_new_tokens,
            model_timeout=args.model_timeout,
            enable_thinking=bool(args.enable_thinking),
            log_path=output / "planner_bridge_stderr.log",
            cwd=REPO_ROOT,
        )
        result["planner_bridge"] = {
            "endpoint": bridge_state["endpoint"],
            "ready": bridge_state["ready"],
            "command_without_token": bridge_state["command_without_token"],
            "token_recorded": False,
            "stderr_log": bridge_state["log_path"],
        }
        env = bridge_runner._planner_env(bridge_state)
        old_env = {
            key: os.environ.get(key)
            for key in (
                "VLN_TAICHU_PLANNER_BRIDGE",
                "VLN_TAICHU_PLANNER_TOKEN",
                "VLN_TAICHU_PLANNER_TIMEOUT_MS",
                "PYTHONPATH",
            )
        }
        os.environ.update(env)

        entry_args = [
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--kernel-host",
            str(host_exe),
            "--output-dir",
            str(entry_dir),
            "--alignment-result",
            str(ALIGNMENT_RESULT),
            "--alignment-authorization",
            str(ALIGNMENT_AUTHORIZATION),
            "--binding-json",
            str(BINDING_JSON),
            "--geometry-probe",
            str(GEOMETRY_PROBE),
            "--kernel-exec-timeout-ms",
            str(args.kernel_exec_timeout_ms),
            "--ttl-s",
            "1800",
        ]
        entry_code = entry04.main(
            entry_args, before_entry=_before_entry, after_entry=_after_entry
        )
        result["entry_exit_code"] = entry_code
        result["entry_result"] = (
            json.loads((entry_dir / "result.json").read_text(encoding="utf-8"))
            if (entry_dir / "result.json").is_file()
            else None
        )
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        result["traceback"] = traceback.format_exc()
    finally:
        bridge_stopped = bridge_runner._stop_planner_bridge(bridge_state)
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    result["goal_understanding"] = run_state.get("goal")
    result["verification"] = run_state.get("verification")
    result["entry"] = run_state.get("entry")
    result["refinement"] = run_state.get("refinement")
    result["final"] = run_state.get("final")
    result["session"] = run_state.get("session")
    result["parking_state"] = state
    result["stage_revisions"] = run_state.get("revisions")
    result["planner_bridge_stopped"] = bridge_stopped
    result["parking_completed"] = bool(
        state.get("current_stage") == "COMPLETED"
        and (state.get("completion_gate") or {}).get("parking_completed") is True
    )
    result["status"] = (
        "PASS"
        if result["parking_completed"]
        else "SAFE_STOP"
        if (state.get("current_stage") or "").endswith("STOP")
        else "FAIL"
    )
    if result["parking_completed"]:
        result["completion_level"] = [
            "IMPLEMENTED",
            "UNIT_TESTED",
            "INTEGRATED",
            "REAL_MODEL_VALIDATED",
            "CARLA_TASK_COMPLETED",
        ]
        if (run_state.get("verification") or {}).get("recovery_used"):
            result["completion_level"].append("RECOVERY_VALIDATED")
    result["error"] = result.get("error") or run_state.get("failure")
    result["finished_utc"] = _utc_now()
    _write_json(output / "result.json", result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "session_id": args.session_id,
                "parking_completed": result["parking_completed"],
                "current_stage": state.get("current_stage"),
                "completed_stages": state.get("completed_stages"),
                "goal_understanding": (
                    (run_state.get("goal") or {}).get("evaluated")
                ),
                "verification_stage": (
                    (run_state.get("verification") or {}).get("stage")
                ),
                "final": {
                    "verifier": (
                        (run_state.get("final") or {}).get("verifier") or {}
                    ).get("decision"),
                    "gate": (
                        (run_state.get("final") or {}).get("gate") or {}
                    ).get("decision"),
                },
                "session": {
                    "close": (
                        (run_state.get("session") or {}).get("close") or {}
                    ).get("session_state"),
                    "revision": (
                        (run_state.get("session") or {}).get("get") or {}
                    ).get("context_revision"),
                },
                "error": result["error"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["parking_completed"] else 3


if __name__ == "__main__":
    sys.exit(main())
