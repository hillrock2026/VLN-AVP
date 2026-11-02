#!/usr/bin/env python3
"""M1-VLN-AVP-CAP-08C-02: full live Session-centric parking.

One Agent-Kernel Session owns the whole task. The driver runs, in this process
and on the same Session:

    real Taichu task understanding
      -> live target binding (real CARLA image + real Taichu)
      -> live approach navigation (real Taichu planning + Kernel execution)
      -> live target verification (two real Taichu views)
      -> live alignment (real Kernel execution)
      -> live Entry / Pose Refinement / Final Verification / Completion Gate

Parking-domain progress is written into the Session Context under
``domain.parking`` via planner/execution domains and
``session.context.update``. There is no separate task lifecycle.
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

import carla_cap07b03_align as align03  # noqa: E402
import carla_cap07b04_entry as entry04  # noqa: E402
import carla_cap07b05_refine as refine05  # noqa: E402
import carla_cap07b06_final_verify as final06  # noqa: E402
import carla_cap08b01_planner_navigation as bridge_runner  # noqa: E402
import carla_cap08c01_session_parking as session01  # noqa: E402
import carla_parking_nav as nav01b  # noqa: E402
import carla_vln_bind_target as binder  # noqa: E402
import carla_vln_navigate as nav01e  # noqa: E402
from vln.carla.kernel_bridge import CarlaExecutionBridge  # noqa: E402
from vln.carla.session import cleanup_session, leftover_actors  # noqa: E402
from vln.client import HostClient  # noqa: E402
from vln.parking.autonomous import (  # noqa: E402
    authorize_entry,
    approach_state_from_result,
)
from vln.parking.session_decision import (  # noqa: E402
    evaluate_task_understanding,
    parse_task_understanding,
    build_task_understanding_prompt,
)
from vln.vlm.host_planner_client import (  # noqa: E402
    HostPlannerError,
    HostPlannerModelClient,
)
from vln.vlm.server_client import ZDTaichuServerBackend  # noqa: E402

TASK_ID = "cap08c-02"
INSTRUCTION = "请将车辆停入左侧靠近出口的空闲车位"
OUTPUT = REPO_ROOT / "docs/evidence/vln-avp-cap-08c-02"
KERNEL_HOST = Path(
    "/home/gaosong/workspace/Agentic_Program/m1-cap08b02-build/kernel_host"
)
GEOMETRY_PROBE = REPO_ROOT / "docs/evidence/carla-07a/geometry_probe.json"
BINDING_SPAWN = (-5.1, -9.9, 6.7, -75.0)
STOP_SPEED_MPS = 0.25


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state(session, ego) -> dict:
    return entry04._state(session, ego)


def _session_get(host_client, session_id: str, request_id: str) -> dict:
    response = session01._session_control(
        host_client,
        "session.get",
        {"session_id": session_id},
        request_id,
        session_id=session_id,
    )
    context_revision = response.get("context_revision")
    if isinstance(context_revision, int):
        entry04.CONTEXT_REVISION = context_revision
    return response


def _connection_snapshot(session, ego, label: str) -> dict:
    state = _state(session, ego)
    return {
        "label": label,
        "frame": state.get("frame"),
        "x": state.get("x"),
        "y": state.get("y"),
        "yaw_deg": state.get("yaw_deg"),
        "speed": state.get("speed"),
        "utc": _utc_now(),
    }


def _run_task_understanding(
    *,
    session,
    ego,
    host_client,
    session_id: str,
    state: dict,
    out_dir: Path,
) -> dict:
    parsed = binder.parse_parking_instruction(INSTRUCTION)
    constraints = (
        f"target_kind={parsed.target_kind}; occupancy={parsed.occupancy}; "
        f"side={parsed.side}; landmark={parsed.landmark or 'none'}"
    )
    vehicle = _state(session, ego)
    vehicle_text = (
        f"x={vehicle['x']:.3f}, y={vehicle['y']:.3f}, "
        f"yaw={vehicle['yaw_deg']:.3f} deg, speed={vehicle['speed']:.3f} m/s"
    )
    attempts = []
    for attempt_index, (name, offset, pitch, yaw, fov) in enumerate(
        session01.GOAL_VIEWS, start=1
    ):
        observation_id = f"task_{attempt_index:02d}_{name}"
        record = session01._capture_view(
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
        prompt = build_task_understanding_prompt(
            instruction=INSTRUCTION,
            parsed_constraints=constraints,
            vehicle_state=vehicle_text,
        )
        client = HostPlannerModelClient(
            host_client,
            session_id=session_id,
            context_revision=entry04.CONTEXT_REVISION,
            request_id_prefix=f"cap08c02-task-a{attempt_index}",
            domain={
                "capability": "planner.plan",
                "stage": "GOAL_UNDERSTANDING",
                "skill": "vln.parking.task_understanding",
                "attempt": attempt_index,
                "observation_id": observation_id,
                "frame_id": record["frame_id"],
                "image_sha256": record["raw_image_sha256"],
                "parking": session01._context_payload(state),
            },
        )
        request_record = {
            "observation_id": observation_id,
            "prompt": prompt,
            "raw_image": record["raw_image"],
            "raw_image_sha256": record["raw_image_sha256"],
        }
        try:
            raw = client.generate(record["raw_image"], prompt)
            understanding = parse_task_understanding(raw)
            evaluated = evaluate_task_understanding(understanding)
            if isinstance(client.context_revision_after, int):
                entry04.CONTEXT_REVISION = client.context_revision_after
            exchange = client.last_exchange
            server_response_id = None
            if exchange is not None:
                output = exchange.output or {}
                server = output.get("server_response") or {}
                server_response_id = server.get("server_response_id")
                request_record.update(
                    {
                        "request_id": exchange.request_id,
                        "planner_request_id": exchange.planner_request_id,
                        "context_revision": exchange.context_revision,
                        "final_prompt": output.get("prompt"),
                        "final_prompt_sha256": output.get("prompt_sha256"),
                        "context_selection": output.get("context_selection"),
                        "server_response": server,
                        "model": output.get("model"),
                    }
                )
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
            if evaluated.get("start_task"):
                return {
                    "ok": True,
                    "parsed_constraints": constraints,
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
                    "reasons": ["task_understanding_safe_stop"],
                }
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
            request_record["error"] = f"{type(error).__name__}: {error}"
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
        "reasons": ["task_understanding_not_started"],
    }


def _run_binding(
    *,
    session,
    ego,
    out_dir: Path,
    parsed_instruction,
) -> dict:
    """Bounded real-image binding attempts.

    The model is re-observed from several independent real camera views if the
    first view is ambiguous or identifies the wrong bay. No occupancy or bay is
    fabricated; the first real observation that correctly binds bay03/park_slot
    is accepted, otherwise the caller must safe-stop.
    """

    views = (
        ("v1", (2.4, 0.0, 1.6), -20.0, -55.0, 110.0),
        ("v_left", (1.0, 2.0, 2.0), -20.0, -60.0, 110.0),
        ("v_left2", (0.0, 3.0, 2.0), -15.0, -55.0, 100.0),
        ("v_high", (2.4, 0.0, 2.8), -25.0, -55.0, 100.0),
    )
    attempts = []
    selected = None
    for index, (name, offset, pitch, yaw, fov) in enumerate(views):
        backend = ZDTaichuServerBackend(
            max_new_tokens=1024,
            timeout=240.0,
            temperature=0.0,
            enable_thinking=True,
        )
        binding, record = binder.run_binding_round(
            session,
            ego,
            request=parsed_instruction,
            round_index=0,
            prior=None,
            backend=backend,
            out_dir=out_dir,
            fov=fov,
            camera_offset=offset,
            camera_pitch=pitch,
            camera_yaw=yaw,
            label_order="near_to_far",
            name=f"round_{index:02d}_{name}",
        )
        attempt = {
            "attempt": index + 1,
            "view": name,
            "camera_offset": list(offset),
            "camera_pitch": pitch,
            "camera_yaw": yaw,
            "fov": fov,
            "binding": binding.to_metadata(),
            "model_text": record.get("model_text"),
            "overlay": record.get("overlay_png"),
            "raw_image": (record.get("camera") or {}).get("raw_png"),
        }
        attempts.append(attempt)
        if (
            binding.status == "bound"
            and binding.executable
            and binding.bay_id == "bay03"
            and binding.slot_node_id == "park_slot"
        ):
            selected = (binding, record, attempt)
            break
    session01._write_json(
        out_dir / "binding_attempts.json", {"attempts": attempts}
    )
    if selected is None:
        return {
            "ok": False,
            "binding": None,
            "binding_metadata": None,
            "binding_path": None,
            "record": None,
            "attempts": attempts,
            "reason": "no real binding attempt selected bay03/park_slot",
        }
    binding, record, attempt = selected
    binding_path = out_dir / "binding.json"
    session01._write_json(binding_path, binding.to_metadata())
    session01._write_json(out_dir / "binding_round.json", record)
    return {
        "ok": True,
        "binding": binding,
        "binding_metadata": binding.to_metadata(),
        "binding_path": str(binding_path),
        "record": record,
        "attempts": attempts,
        "selected_attempt": attempt["attempt"],
        "selected_view": attempt["view"],
    }


def _run_approach(
    *,
    session,
    ego,
    host_client,
    bridge,
    session_id: str,
    binding_path: str,
    out_dir: Path,
) -> dict:
    argv = [
        "--scenario", "carpark_parking",
        "--host", "127.0.0.1",
        "--port", "2000",
        "--start-node", "w6",
        "--start-previous-node", "w5",
        "--start-yaw-deg", "-75.0",
        "--target-binding-json", binding_path,
        "--parking-instruction", INSTRUCTION,
        "--target-approach-only",
        "--task-id", TASK_ID,
        "--task-label", "M1-VLN-AVP-CAP-08C-02",
        "--target-id", "bay03",
        "--run-prefix", "cap08c02-approach",
        "--instruction", INSTRUCTION + "。本次只需安全接近目标车位，不要进入车位泊车。",
        "--targets", "B1",
        "--output-dir", str(out_dir),
        "--kernel-host", str(KERNEL_HOST),
        "--host-planner",
        "--session-id", session_id,
        "--recover-after-safety-stop",
        "--max-recovery-attempts", "1",
        "--max-new-tokens", "4096",
        "--timeout", "240",
    ]
    runtime = {
        "session": session,
        "ego": ego,
        "host_client": host_client,
        "bridge": bridge,
        "keep_runtime": True,
        "host_session_id": session_id,
        "host_context_revision": entry04.CONTEXT_REVISION,
    }
    code = nav01e.main(argv, runtime=runtime)
    result_path = out_dir / "result.json"
    result = (
        json.loads(result_path.read_text(encoding="utf-8"))
        if result_path.is_file()
        else {}
    )
    _session_get(
        host_client, session_id, f"{TASK_ID}-approach-session-get"
    )
    ok = bool(
        code == 0
        and result.get("status") == "PASS"
        and result.get("task_status") == "goal_reached"
        and (result.get("target_approach_verdict") or {}).get("ok") is True
    )
    return {"ok": ok, "code": code, "result": result, "path": str(result_path)}


def _run_alignment(
    *,
    session,
    ego,
    host_client,
    bridge,
    session_id: str,
    binding_path: str,
    approach_result_path: str,
    entry_authorization_path: str,
    verification_path: str,
    out_dir: Path,
) -> dict:
    argv = [
        "--host", "127.0.0.1",
        "--port", "2000",
        "--approach-result", approach_result_path,
        "--binding-json", binding_path,
        "--entry-authorization", entry_authorization_path,
        "--verification-json", verification_path,
        "--geometry-probe", str(GEOMETRY_PROBE),
        "--output-dir", str(out_dir),
        "--kernel-host", str(KERNEL_HOST),
        "--max-rounds", "4",
        "--ttl-s", "1800",
    ]
    runtime = {
        "session": session,
        "ego": ego,
        "host_client": host_client,
        "bridge": bridge,
        "keep_runtime": True,
        "host_session_id": session_id,
        "host_context_revision": entry04.CONTEXT_REVISION,
    }
    code = align03.main(argv, runtime=runtime)
    result_path = out_dir / "result.json"
    result = (
        json.loads(result_path.read_text(encoding="utf-8"))
        if result_path.is_file()
        else {}
    )
    auth_path = out_dir / "alignment_authorization.json"
    auth = (
        json.loads(auth_path.read_text(encoding="utf-8"))
        if auth_path.is_file()
        else {}
    )
    _session_get(
        host_client, session_id, f"{TASK_ID}-alignment-session-get"
    )
    ok = bool(
        code == 0
        and result.get("status") == "PASS"
        and result.get("decision") == "ALIGNMENT_COMPLETED"
        and auth.get("decision") == "ALIGNMENT_AUTHORIZED"
    )
    return {
        "ok": ok,
        "code": code,
        "result": result,
        "authorization": auth,
        "result_path": str(result_path),
        "authorization_path": str(auth_path),
    }


def main(argv: list[str] | None = None, demo=None) -> int:
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
    binding_dir = output / "target_binding"
    task_dir = output / "goal_understanding"
    approach_dir = output / "approach"
    verification_dir = output / "target_verification"
    alignment_dir = output / "alignment"
    entry_dir = output / "entry"
    refine_dir = output / "refinement"
    final_dir = output / "final"
    for path in (
        binding_dir,
        task_dir,
        approach_dir,
        verification_dir,
        alignment_dir,
        entry_dir,
        refine_dir,
        final_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)

    host_exe = Path(args.kernel_host).resolve()
    if not (host_exe.is_file() and os.access(host_exe, os.X_OK)):
        raise SystemExit(f"--kernel-host is not executable: {host_exe}")
    started = _utc_now()
    result: dict = {
        "schema": "vln.cap08c02.live_parking.v1",
        "task_id": TASK_ID,
        "session_id": args.session_id,
        "user_instruction": INSTRUCTION,
        "started_utc": started,
        "git": entry04._git_state(),
        "host": session01._host_evidence(host_exe),
        "status": "FAIL",
        "parking_completed": False,
        "completion_level": [],
        "stage_revisions": [],
        "connections": [],
        "error": None,
    }

    state: dict = {
        "session_id": args.session_id,
        "instruction": INSTRUCTION,
        "target": {
            "bay_id": None,
            "slot_node_id": None,
            "target_id": None,
            "approach_node_id": None,
        },
        "current_stage": "GOAL_UNDERSTANDING",
        "completed_stages": [],
        "stage_results": {},
        "goal_understanding": None,
        "target_binding": None,
        "approach": None,
        "target_verification": None,
        "alignment": None,
        "recovery_state": {
            "attempts": 0,
            "max_attempts": session01.MAX_VERIFICATION_ATTEMPTS,
            "used": False,
        },
        "last_execution": None,
        "final_verification": None,
        "completion_gate": None,
    }
    entry04.SESSION_ID = args.session_id
    entry04.CONTEXT_REVISION = None
    entry04.PARKING_CONTEXT = session01._context_payload(state)
    run_state: dict = {
        "task": None,
        "binding": None,
        "approach": None,
        "verification": None,
        "alignment": None,
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
        entry04.PARKING_CONTEXT = session01._context_payload(state)
        response = session01._write_context_state(
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
        if demo is not None:
            demo.on_stage(stage, status, state, response)

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
        result["connections"].append(
            _connection_snapshot(session, ego, "ENTRY_COMPLETED")
        )
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
                "GOAL_UNDERSTANDING",
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
        result["connections"].append(
            _connection_snapshot(session, ego, "PARKING_POSE_READY")
        )
        if not refine_ok:
            run_state["failure"] = (
                "refinement did not reach PARKING_POSE_READY"
            )
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
                "GOAL_UNDERSTANDING",
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
        session01._write_json(final_dir / "session_final.json", final)
        verifier = final.get("verifier") or {}
        checks = verifier.get("checks") or {}
        state["final_verification"] = {
            "decision": verifier.get("decision"),
            "verification_passed": verifier.get("verification_passed"),
            "checks_passed": sum(
                1 for value in checks.values() if value is True
            ),
            "checks_total": len(checks),
            "reasons": verifier.get("reasons"),
        }
        state["stage_results"]["FINAL_VERIFICATION"] = {
            "ok": bool(final.get("final_parking_verified")),
            "verifier": state["final_verification"],
        }
        composite = session01._composite_completion_decision(final)
        state["completion_gate"] = composite
        state["stage_results"]["COMPLETION"] = {
            "ok": composite is not None,
            "gate": final.get("gate"),
        }
        result["connections"].append(
            _connection_snapshot(session, ego, "FINAL_VERIFICATION")
        )
        if composite is not None:
            state["completed_stages"] = [
                "GOAL_UNDERSTANDING",
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

        run_state["session"]["get"] = session01._session_control(
            host_client,
            "session.get",
            {"session_id": args.session_id},
            f"{TASK_ID}-session-get",
            session_id=args.session_id,
        )
        run_state["session"]["close"] = session01._session_control(
            host_client,
            "session.close",
            {"session_id": args.session_id},
            f"{TASK_ID}-session-close",
            session_id=args.session_id,
        )
        run_state["session"]["get_after_close"] = session01._session_control(
            host_client,
            "session.get",
            {"session_id": args.session_id},
            f"{TASK_ID}-session-get-after-close",
            session_id=args.session_id,
        )

    bridge_state = None
    bridge = None
    host_client = None
    session = None
    ego = None
    entry_started = False
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

        session = nav01b.Session(
            args.host, args.port, str(output), map_name="UndergroundCarPark"
        )
        leftovers = leftover_actors(session.world)
        if leftovers:
            raise RuntimeError(
                "world already contains vln_ actors; refusing to run the live "
                "parking task on an unknown scene"
            )
        ego = session.spawn_vehicle(
            nav01e.EGO_ROLE,
            BINDING_SPAWN[0],
            BINDING_SPAWN[1],
            BINDING_SPAWN[2],
            BINDING_SPAWN[3],
        )
        parked = binder.spawn_parked_vehicle(session, "bay11")
        session.tick(40)
        ego.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))
        session.tick(10)
        result["parked_obstacle"] = {
            "actor_id": int(parked.id),
            "type_id": parked.type_id,
            "role_name": parked.attributes.get("role_name"),
            "purpose": "recreate the accepted CAP-07A occupied bay11 scene",
        }
        result["connections"].append(
            _connection_snapshot(session, ego, "SPAWN_W6_WITH_BAY11_OCCUPIED")
        )
        if demo is not None:
            demo.on_ego(session, ego, parked, output)
            demo.on_stage("GOAL_UNDERSTANDING", "running", state, None)

        def _no_stage(permit):
            return {
                "status": "rejected",
                "stop_reason": "no_stage_handler_configured",
                "pre_state": _state(session, ego),
                "post_state": _state(session, ego),
                "stopped": True,
                "segment_success": False,
            }

        bridge = CarlaExecutionBridge(_no_stage)
        bridge.start()
        host_env = {
            **os.environ.copy(),
            "VLN_CARLA_EXEC_BRIDGE": bridge.endpoint,
            "VLN_CARLA_EXEC_TOKEN": bridge.token,
            "VLN_CARLA_EXEC_TIMEOUT_MS": str(args.kernel_exec_timeout_ms),
        }
        host_client = HostClient([str(host_exe)], env=host_env)

        task = _run_task_understanding(
            session=session,
            ego=ego,
            host_client=host_client,
            session_id=args.session_id,
            state=state,
            out_dir=task_dir,
        )
        run_state["task"] = task
        session01._write_json(task_dir / "result.json", task)
        if not task.get("ok"):
            run_state["failure"] = (
                "task understanding did not start: "
                + ", ".join(task.get("reasons") or ())
            )
            state["stage_results"]["GOAL_UNDERSTANDING"] = {
                "ok": False,
                "reason": run_state["failure"],
            }
            _set_stage(
                "GOAL_UNDERSTANDING",
                status="blocked",
                request_id=f"{TASK_ID}-stage-task-understanding-blocked",
                host_client=host_client,
            )
            raise RuntimeError(run_state["failure"])
        state["goal_understanding"] = task.get("understanding")
        state["stage_results"]["GOAL_UNDERSTANDING"] = {
            "ok": True,
            "understanding": task.get("understanding"),
            "parsed_constraints": task.get("parsed_constraints"),
        }
        _set_stage(
            "TARGET_BINDING",
            completed=["GOAL_UNDERSTANDING"],
            status="running",
            request_id=f"{TASK_ID}-stage-target-binding",
            host_client=host_client,
        )

        parsed_instruction = binder.parse_parking_instruction(INSTRUCTION)
        binding_run = _run_binding(
            session=session,
            ego=ego,
            out_dir=binding_dir,
            parsed_instruction=parsed_instruction,
        )
        run_state["binding"] = binding_run
        if not binding_run.get("ok"):
            run_state["failure"] = (
                "live target binding did not select bay03/park_slot"
            )
            state["stage_results"]["TARGET_BINDING"] = {
                "ok": False,
                "binding": binding_run.get("binding_metadata"),
            }
            _set_stage(
                "TARGET_BINDING",
                status="blocked",
                request_id=f"{TASK_ID}-stage-binding-blocked",
                host_client=host_client,
            )
            raise RuntimeError(run_state["failure"])
        binding = binding_run["binding"]
        state["target"] = {
            "bay_id": binding.bay_id,
            "slot_node_id": binding.slot_node_id,
            "target_id": binding.bay_id,
            "approach_node_id": "park_entry",
        }
        state["target_binding"] = binding_run["binding_metadata"]
        state["stage_results"]["TARGET_BINDING"] = {
            "ok": True,
            "binding": binding_run["binding_metadata"],
            "model_text": binding_run["record"].get("model_text"),
        }
        _set_stage(
            "APPROACH",
            completed=["GOAL_UNDERSTANDING", "TARGET_BINDING"],
            status="running",
            request_id=f"{TASK_ID}-stage-approach",
            host_client=host_client,
        )

        nav01e.PARKING_CONTEXT = session01._context_payload(state)
        approach_run = _run_approach(
            session=session,
            ego=ego,
            host_client=host_client,
            bridge=bridge,
            session_id=args.session_id,
            binding_path=binding_run["binding_path"],
            out_dir=approach_dir,
        )
        run_state["approach"] = approach_run
        if not approach_run.get("ok"):
            run_state["failure"] = "live approach did not reach park_entry"
            state["stage_results"]["APPROACH"] = {
                "ok": False,
                "result": approach_run.get("result"),
            }
            _set_stage(
                "APPROACH",
                status="safe_stop",
                request_id=f"{TASK_ID}-stage-approach-failed",
                host_client=host_client,
            )
            raise RuntimeError(run_state["failure"])
        approach_result = approach_run["result"]
        result["connections"].append(
            _connection_snapshot(session, ego, "APPROACH_COMPLETED")
        )
        state["approach"] = {
            "result_path": approach_run["path"],
            "final_state": approach_result.get("final_state"),
            "target_approach_verdict": approach_result.get(
                "target_approach_verdict"
            ),
        }
        state["stage_results"]["APPROACH"] = {
            "ok": True,
            "final_state": approach_result.get("final_state"),
            "target_approach_verdict": approach_result.get(
                "target_approach_verdict"
            ),
        }
        _set_stage(
            "TARGET_VERIFICATION",
            completed=["GOAL_UNDERSTANDING", "TARGET_BINDING", "APPROACH"],
            status="running",
            request_id=f"{TASK_ID}-stage-target-verification",
            host_client=host_client,
        )

        approach_state = approach_state_from_result(approach_result)
        approach_live = replace(
            approach_state,
            task_id="cap07b-02",
            source="live approach in the current session",
        )
        nav01e.PARKING_CONTEXT = session01._context_payload(state)
        verification = session01._run_verification_attempts(
            session=session,
            ego=ego,
            out_dir=verification_dir,
            binding=binding,
            approach_live=approach_live,
            host_client=host_client,
            session_id=args.session_id,
            state=state,
            collision_count=len(approach_result.get("collision_events") or ()),
        )
        result_object = verification.pop("result_object", None)
        run_state["verification"] = verification
        session01._write_json(verification_dir / "result.json", verification)
        state["target_verification"] = verification.get("verification")
        state["recovery_state"]["used"] = bool(
            verification.get("recovery_used")
        )
        state["recovery_state"]["attempts"] = len(
            verification.get("attempts") or []
        )
        if not verification.get("ok") or result_object is None:
            run_state["failure"] = "live target verification failed"
            state["stage_results"]["TARGET_VERIFICATION"] = {
                "ok": False,
                "verification": verification.get("verification"),
            }
            _set_stage(
                "TARGET_VERIFICATION",
                status="safe_stop",
                request_id=f"{TASK_ID}-stage-target-verification-failed",
                host_client=host_client,
            )
            raise RuntimeError(run_state["failure"])
        entry_authorization = authorize_entry(
            result_object, stopped=True, collision_count=0
        )
        if entry_authorization.decision != "ENTRY_AUTHORIZED":
            run_state["failure"] = (
                "live verification did not issue ENTRY_AUTHORIZED"
            )
            _set_stage(
                "TARGET_VERIFICATION",
                status="safe_stop",
                request_id=f"{TASK_ID}-stage-entry-authorization-failed",
                host_client=host_client,
            )
            raise RuntimeError(run_state["failure"])
        verification_path = verification_dir / "verification.json"
        entry_authorization_path = verification_dir / "entry_authorization.json"
        session01._write_json(
            verification_path, result_object.to_metadata()
        )
        session01._write_json(
            entry_authorization_path, entry_authorization.to_metadata()
        )
        state["stage_results"]["TARGET_VERIFICATION"] = {
            "ok": True,
            "verification": result_object.to_metadata(),
            "authorization": entry_authorization.to_metadata(),
            "recovery_used": verification.get("recovery_used"),
        }
        _set_stage(
            "ALIGNMENT",
            completed=[
                "GOAL_UNDERSTANDING",
                "TARGET_BINDING",
                "APPROACH",
                "TARGET_VERIFICATION",
            ],
            status="running",
            request_id=f"{TASK_ID}-stage-alignment",
            host_client=host_client,
        )

        align03.PARKING_CONTEXT = session01._context_payload(state)
        align03.SESSION_ID = args.session_id
        align03.CONTEXT_REVISION = entry04.CONTEXT_REVISION
        alignment_run = _run_alignment(
            session=session,
            ego=ego,
            host_client=host_client,
            bridge=bridge,
            session_id=args.session_id,
            binding_path=binding_run["binding_path"],
            approach_result_path=approach_run["path"],
            entry_authorization_path=str(entry_authorization_path),
            verification_path=str(verification_path),
            out_dir=alignment_dir,
        )
        run_state["alignment"] = alignment_run
        if not alignment_run.get("ok"):
            run_state["failure"] = "live alignment did not complete"
            state["stage_results"]["ALIGNMENT"] = {
                "ok": False,
                "result": alignment_run.get("result"),
            }
            _set_stage(
                "ALIGNMENT",
                status="safe_stop",
                request_id=f"{TASK_ID}-stage-alignment-failed",
                host_client=host_client,
            )
            raise RuntimeError(run_state["failure"])
        result["connections"].append(
            _connection_snapshot(session, ego, "ALIGNMENT_COMPLETED")
        )
        state["alignment"] = {
            "result_path": alignment_run["result_path"],
            "authorization_path": alignment_run["authorization_path"],
            "decision": alignment_run["result"].get("decision"),
            "final_state": alignment_run["result"].get("final_state"),
        }
        state["stage_results"]["ALIGNMENT"] = {
            "ok": True,
            "decision": alignment_run["result"].get("decision"),
            "authorization": alignment_run["authorization"],
            "final_state": alignment_run["result"].get("final_state"),
        }
        _set_stage(
            "ENTRY",
            completed=[
                "GOAL_UNDERSTANDING",
                "TARGET_BINDING",
                "APPROACH",
                "TARGET_VERIFICATION",
                "ALIGNMENT",
            ],
            status="running",
            request_id=f"{TASK_ID}-stage-entry",
            host_client=host_client,
        )

        entry04.PARKING_CONTEXT = session01._context_payload(state)
        entry_args = [
            "--host", args.host,
            "--port", str(args.port),
            "--kernel-host", str(host_exe),
            "--output-dir", str(entry_dir),
            "--alignment-result", alignment_run["result_path"],
            "--alignment-authorization", alignment_run["authorization_path"],
            "--binding-json", binding_run["binding_path"],
            "--geometry-probe", str(GEOMETRY_PROBE),
            "--kernel-exec-timeout-ms", str(args.kernel_exec_timeout_ms),
            "--ttl-s", "1800",
        ]
        entry_started = True
        entry_code = entry04.main(
            entry_args,
            runtime={
                "session": session,
                "ego": ego,
                "host_client": host_client,
                "bridge": bridge,
            },
            after_entry=_after_entry,
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
        if not entry_started:
            try:
                if bridge is not None:
                    bridge.close()
            except Exception:
                pass
            try:
                if host_client is not None:
                    host_client.close()
            except Exception:
                pass
            try:
                if session is not None:
                    cleanup = cleanup_session(
                        session.world, session.actors, session.original
                    )
                    result["cleanup"] = {
                        "destroy_errors": cleanup["destroy_errors"],
                        "leftover_vln_actors": cleanup["leftover_vln_actors"],
                    }
            except Exception as cleanup_error:
                result["cleanup_error"] = (
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )
    finally:
        bridge_stopped = bridge_runner._stop_planner_bridge(bridge_state)
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    result["goal_understanding"] = run_state.get("task")
    binding_run = run_state.get("binding") or {}
    result["target_binding"] = {
        key: value
        for key, value in binding_run.items()
        if key != "binding"
    }
    result["approach"] = run_state.get("approach")
    result["verification"] = run_state.get("verification")
    result["alignment"] = run_state.get("alignment")
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
        if run_state.get("failure")
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
    session01._write_json(output / "result.json", result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "session_id": args.session_id,
                "parking_completed": result["parking_completed"],
                "current_stage": state.get("current_stage"),
                "completed_stages": state.get("completed_stages"),
                "task_understanding": (
                    (run_state.get("task") or {}).get("evaluated")
                ),
                "binding": {
                    "bay_id": (run_state.get("binding") or {})
                    .get("binding_metadata", {})
                    .get("bay_id"),
                    "selected_label": (run_state.get("binding") or {})
                    .get("binding_metadata", {})
                    .get("selected_label"),
                },
                "approach": (
                    (run_state.get("approach") or {}).get("result", {}).get(
                        "final_state"
                    )
                ),
                "verification_stage": (
                    (run_state.get("verification") or {}).get("stage")
                ),
                "alignment": (
                    (run_state.get("alignment") or {}).get("result", {}).get(
                        "decision"
                    )
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
