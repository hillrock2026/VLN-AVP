#!/usr/bin/env python3
"""M1-VLN-CARLA-CAP-08B-01: real Taichu planning through Agent-Kernel.

This runner starts one real loopback planner bridge (which calls the existing
ZDTaichu5.0-9B service through ``ZDTaichuServerBackend``), configures the
Town10HD_Opt multipoint targets, and runs the existing navigation runner with
``--host-planner``. Every model call therefore traverses:

    navigation runner -> Host planner.plan -> ak::planner::Planner
        -> TaichuPlanningEngine -> planner bridge -> real model service

The model output remains a candidate: the existing parse/verify/arbitration/
safety gates and the Kernel authorization path are unchanged. A passing run
still requires real CARLA movement; a model failure stops before execution.

Evidence is written under ``docs/evidence/cap-08b-01``. The runner never
commits, pushes, resets or cleans the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import secrets
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from vln.client import HostClient  # noqa: E402
from vln.ipc.envelope import Request  # noqa: E402

TASK_ID = "cap08b-01"
DEFAULT_HOST = Path(
    "/home/gaosong/workspace/Agentic_Program/m1-cap08b01-build/kernel_host"
)
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "evidence" / "cap-08b-01"
PLANNER_BRIDGE = REPO_ROOT / "scripts" / "taichu_planner_bridge.py"
TARGET_SETUP = REPO_ROOT / "scripts" / "setup_town10_multipoint_targets.py"
NAVIGATION = REPO_ROOT / "scripts" / "carla_vln_navigate.py"

INSTRUCTION = (
    "请先沿画面中红色车辆所在的道路前进到路口；到达下一个路口后，驶向蓝色车辆"
    "并沿其道路继续，到达蓝色车辆附近后停止。"
)
TARGET_NOTE = (
    "若画面中出现多辆车，请只以 {target} 为目标，不要以其他车辆或道路结构代替目标判断。"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
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


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _ensure_town10_map(host: str, port: int) -> dict:
    import carla  # the CARLA venv is the runner's interpreter

    client = carla.Client(host, port)
    client.set_timeout(60.0)
    before = client.get_world().get_map().name
    if before.endswith("Town10HD_Opt"):
        return {"map_before": before, "map_after": before, "loaded": False}
    world = client.load_world("Town10HD_Opt")
    after = world.get_map().name
    if not after.endswith("Town10HD_Opt"):
        raise RuntimeError(f"map load returned {after!r}, expected Town10HD_Opt")
    return {"map_before": before, "map_after": after, "loaded": True}


def _warmup_world(host: str, port: int, ticks: int = 5) -> dict:
    """Advance physics before the navigation runner validates floor rays.

    A freshly reloaded CARLA world can answer the first synchronous ray query
    from a stale physics frame. The navigation runner sets synchronous mode and
    validates waypoints immediately, so the runner advances a few ticks first
    and leaves the world asynchronous (the runner re-enables sync itself).
    """

    import carla

    client = carla.Client(host, port)
    client.set_timeout(60.0)
    world = client.get_world()
    settings = world.get_settings()
    before = {
        "synchronous_mode": settings.synchronous_mode,
        "fixed_delta_seconds": settings.fixed_delta_seconds,
    }
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05
    world.apply_settings(settings)
    for _ in range(int(ticks)):
        world.tick()
    settings = world.get_settings()
    settings.synchronous_mode = False
    settings.fixed_delta_seconds = None
    world.apply_settings(settings)
    return {"ticks": int(ticks), "before": before, "after": {"synchronous_mode": False}}


def _host_evidence(path: Path) -> dict:
    cache = {}
    cache_path = path.parent / "CMakeCache.txt"
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith(
                (
                    "CMAKE_HOME_DIRECTORY:",
                    "AGENT_KERNEL_SOURCE_DIR:",
                    "CMAKE_BUILD_TYPE:",
                    "CMAKE_CXX_COMPILER:",
                )
            ):
                key, _, value = line.partition("=")
                cache[key.split(":", 1)[0]] = value
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
        "mtime": datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
        "build_dir": str(path.parent),
        "cmake_cache": cache,
    }


def _control(client: HostClient, request_id: str, capability: str, payload: dict):
    return client.send(
        Request(
            request_id=request_id,
            capability_id=capability,
            payload=json.dumps(payload, separators=(",", ":")),
        )
    )


def _plan(
    client: HostClient,
    *,
    request_id: str,
    session_id: str | None,
    revision: int | None,
    image_path: str,
    instruction: str = "planning guard",
):
    return client.send(
        Request(
            request_id=request_id,
            capability_id="planner.plan",
            payload=json.dumps(
                {"image_path": image_path, "instruction": instruction},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            session_id=session_id,
            expected_context_revision=revision,
        )
    )


def _response_summary(response) -> dict:
    output = None
    if isinstance(response.output, str):
        try:
            output = json.loads(response.output)
        except json.JSONDecodeError:
            output = {"raw": response.output}
    return {
        "ok": response.ok,
        "accepted": response.accepted,
        "submission_status": response.submission_status,
        "observation_status": response.observation_status,
        "error": None if response.error is None else dict(response.error),
        "session_id": response.session_id,
        "session_state": response.session_state,
        "context_revision": response.context_revision,
        "turn": response.turn,
        "context_updated": response.context_updated,
        "output": output,
    }


def _start_planner_bridge(
    python: str,
    *,
    max_new_tokens: int,
    model_timeout: float,
    enable_thinking: bool,
    log_path: Path,
    cwd: Path,
) -> dict:
    port = _free_port()
    token = secrets.token_hex(24)
    command = [
        python,
        str(PLANNER_BRIDGE),
        "--host", "127.0.0.1",
        "--port", str(port),
        "--max-new-tokens", str(max_new_tokens),
        "--timeout", str(model_timeout),
    ]
    if enable_thinking:
        command.append("--enable-thinking")
    env = os.environ.copy()
    env["VLN_TAICHU_PLANNER_TOKEN"] = token
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_handle = open(log_path, "w", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=stderr_handle,
        text=True,
    )
    assert process.stdout is not None
    ready_queue: queue.Queue = queue.Queue()

    def _read_ready() -> None:
        ready_queue.put(process.stdout.readline())

    threading.Thread(target=_read_ready, daemon=True).start()
    try:
        line = ready_queue.get(timeout=30.0)
    except queue.Empty:
        process.kill()
        stderr_handle.close()
        raise RuntimeError(
            f"planner bridge did not become ready; see {log_path}"
        )
    if not line:
        process.kill()
        stderr_handle.close()
        raise RuntimeError(f"planner bridge exited; see {log_path}")
    try:
        ready = json.loads(line)
    except json.JSONDecodeError as error:
        process.kill()
        stderr_handle.close()
        raise RuntimeError(f"planner bridge ready line is not JSON: {error}") from error
    if ready.get("status") != "ready":
        process.terminate()
        stderr_handle.close()
        raise RuntimeError(f"planner bridge is not ready: {ready}")
    expected_endpoint = f"127.0.0.1:{port}"
    if ready.get("endpoint") != expected_endpoint:
        process.terminate()
        stderr_handle.close()
        raise RuntimeError(
            f"planner bridge endpoint mismatch: {ready.get('endpoint')!r} != "
            f"{expected_endpoint!r}"
        )
    return {
        "process": process,
        "stderr_handle": stderr_handle,
        "endpoint": expected_endpoint,
        "port": port,
        "token": token,
        "ready": ready,
        "command_without_token": command,
        "log_path": str(log_path),
    }


def _stop_planner_bridge(state: dict | None) -> dict | None:
    if state is None:
        return None
    process = state["process"]
    stopped = {}
    try:
        process.terminate()
        try:
            process.wait(timeout=8.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)
        stopped["returncode"] = process.returncode
    finally:
        try:
            state["stderr_handle"].close()
        except Exception:
            pass
    return stopped


def _planner_env(state: dict, *, timeout_ms: int = 300000) -> dict:
    env = os.environ.copy()
    env["VLN_TAICHU_PLANNER_BRIDGE"] = state["endpoint"]
    env["VLN_TAICHU_PLANNER_TOKEN"] = state["token"]
    env["VLN_TAICHU_PLANNER_TIMEOUT_MS"] = str(timeout_ms)
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    return env


def _session_guard(host_exe: str, env: dict, output: Path) -> tuple[bool, dict]:
    session_id = f"{TASK_ID}-guard-{int(time.time())}"
    started = _utc_now()
    record: dict = {"session_id": session_id, "started_utc": started}
    try:
        with HostClient([host_exe], env=env) as client:
            created = _control(
                client, f"{TASK_ID}-guard-create", "session.create",
                {"session_id": session_id},
            )
            record["create"] = _response_summary(created)
            mismatch = _plan(
                client,
                request_id=f"{TASK_ID}-guard-mismatch",
                session_id=session_id,
                revision=999,
                image_path="guard-does-not-need-to-exist.png",
            )
            record["revision_mismatch"] = _response_summary(mismatch)
            no_session = _plan(
                client,
                request_id=f"{TASK_ID}-guard-no-session",
                session_id=None,
                revision=None,
                image_path="guard-does-not-need-to-exist.png",
            )
            record["missing_session"] = _response_summary(no_session)
            got = _control(
                client, f"{TASK_ID}-guard-get", "session.get",
                {"session_id": session_id},
            )
            record["get"] = _response_summary(got)
            closed = _control(
                client, f"{TASK_ID}-guard-close", "session.close",
                {"session_id": session_id},
            )
            record["close"] = _response_summary(closed)
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
    record["finished_utc"] = _utc_now()
    mismatch = record.get("revision_mismatch") or {}
    no_session = record.get("missing_session") or {}
    get = record.get("get") or {}
    close = record.get("close") or {}
    ok = bool(
        mismatch.get("ok") is False
        and (mismatch.get("error") or {}).get("code") == "context-revision-mismatch"
        and mismatch.get("context_updated") is False
        and mismatch.get("context_revision") == 0
        and no_session.get("ok") is False
        and (no_session.get("error") or {}).get("code") == "planner-unavailable"
        and get.get("context_revision") == 0
        and close.get("session_state") == "DESTROYED"
    )
    record["ok"] = ok
    _write_json(output / "session_guard.json", record)
    return ok, record


def _bridge_failure_guard(
    host_exe: str, env: dict, output: Path
) -> tuple[bool, dict]:
    closed_port = _free_port()
    guard_env = dict(env)
    guard_env["VLN_TAICHU_PLANNER_BRIDGE"] = f"127.0.0.1:{closed_port}"
    guard_env["VLN_TAICHU_PLANNER_TIMEOUT_MS"] = "5000"
    session_id = f"{TASK_ID}-bridgefail-{int(time.time())}"
    record: dict = {
        "session_id": session_id,
        "closed_endpoint": f"127.0.0.1:{closed_port}",
        "started_utc": _utc_now(),
    }
    try:
        with HostClient([host_exe], env=guard_env) as client:
            _control(
                client, f"{TASK_ID}-bridgefail-create", "session.create",
                {"session_id": session_id},
            )
            planned = _plan(
                client,
                request_id=f"{TASK_ID}-bridgefail-plan",
                session_id=session_id,
                revision=0,
                image_path="bridge-less-guard.png",
            )
            record["plan"] = _response_summary(planned)
            got = _control(
                client, f"{TASK_ID}-bridgefail-get", "session.get",
                {"session_id": session_id},
            )
            record["get"] = _response_summary(got)
            _control(
                client, f"{TASK_ID}-bridgefail-close", "session.close",
                {"session_id": session_id},
            )
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
    record["finished_utc"] = _utc_now()
    planned = record.get("plan") or {}
    output_json = planned.get("output") or {}
    got = record.get("get") or {}
    ok = bool(
        planned.get("ok") is False
        and planned.get("accepted") is True
        and planned.get("submission_status") == "completed"
        and planned.get("observation_status") == "failure"
        and (planned.get("error") or {}).get("code") == "planner-failed"
        and planned.get("context_updated") is True
        and planned.get("context_revision") == 1
        and output_json.get("status") == "failed"
        and (got.get("output") or {}).get("context", {}).get("status") == "failed"
    )
    record["ok"] = ok
    _write_json(output / "bridge_failure_guard.json", record)
    return ok, record


def _collect_run_evidence(nav_result: dict) -> dict:
    planner_calls: list[dict] = []
    context_events: list[dict] = []
    movements: list[dict] = []
    decisions: list[dict] = []
    recovery_attempts: list[dict] = []
    for round_result in nav_result.get("rounds") or []:
        round_index = round_result.get("round")
        seen_requests: set = set()

        def _add_planner(entry, phase: str) -> None:
            if not isinstance(entry, dict):
                return
            request_id = entry.get("request_id")
            if request_id is not None:
                if request_id in seen_requests:
                    return
                seen_requests.add(request_id)
            output = entry.get("output") or {}
            model = entry.get("model") or {}
            server = output.get("server_response") or {}
            selection = output.get("context_selection") or {}
            planner_calls.append(
                {
                    "round": round_index,
                    "phase": phase,
                    "request_id": entry.get("request_id"),
                    "planner_session_id": entry.get("planner_session_id"),
                    "planner_request_id": entry.get("planner_request_id"),
                    "planning_result_id": entry.get("planning_result_id"),
                    "planning_artifact_id": entry.get("planning_artifact_id"),
                    "context_revision": entry.get("context_revision"),
                    "status": output.get("status"),
                    "is_execution_permit": output.get("is_execution_permit"),
                    "raw_output_chars": entry.get("raw_output_chars"),
                    "raw_output_sha256": entry.get("raw_output_sha256"),
                    "prompt_sha256": output.get("prompt_sha256"),
                    "prompt_chars": output.get("prompt_chars"),
                    "context_selected_count": selection.get("selected_count"),
                    "context_stale_count": selection.get("stale_count"),
                    "context_truncated": selection.get("truncated"),
                    "model": model,
                    "server_response_id": server.get("server_response_id"),
                    "response_model": server.get("response_model"),
                }
            )
            if entry.get("context_after") is not None:
                context_events.append(
                    {
                        "round": round_index,
                        "kind": "planning",
                        "phase": phase,
                        "request_id": entry.get("request_id"),
                        "planner_request_id": entry.get("planner_request_id"),
                        "session_id": entry.get("session_id"),
                        "revision": entry.get("context_revision"),
                        "turn": entry.get("turn"),
                        "before": entry.get("context_before"),
                        "after": entry.get("context_after"),
                    }
                )

        recovery = round_result.get("visual_recovery") or {}
        for attempt in recovery.get("attempts") or []:
            if not isinstance(attempt, dict):
                continue
            attempt_number = attempt.get("attempt")
            _add_planner(
                attempt.get("planner"),
                f"visual_recovery_{attempt_number}",
            )
            decision = attempt.get("decision") or {}
            decided = decision.get("decision") or {}
            parsed = attempt.get("parsed") or {}
            observation = attempt.get("observation") or {}
            planner = attempt.get("planner") or {}
            planner_output = planner.get("output") or {}
            server = planner_output.get("server_response") or {}
            recovery_attempts.append(
                {
                    "round": round_index,
                    "attempt": attempt_number,
                    "phase": attempt.get("phase"),
                    "uncertainty_type": attempt.get("uncertainty_type"),
                    "frame_id": (observation.get("frame") or {}).get("frame_id"),
                    "image_sha256": observation.get("image_sha256"),
                    "context_revision": attempt.get("context_revision"),
                    "revision_advanced": attempt.get("revision_advanced"),
                    "decision_status": decision.get("status"),
                    "identified_as": decided.get("identified_as")
                    or parsed.get("identified_as"),
                    "visible": decided.get("visible") or parsed.get("visible"),
                    "error_type": decision.get("error_type"),
                    "error_message": decision.get("error_message"),
                    "server_response_id": server.get("server_response_id"),
                    "status": planner_output.get("status"),
                    "recovered": bool(recovery.get("recovered"))
                    and attempt_number == recovery.get("attempt_count"),
                }
            )
        _add_planner(round_result.get("planner"), "normal")
        redecision = round_result.get("redecision") or {}
        _add_planner(redecision.get("planner"), "redecision")

        execution = round_result.get("execution") or {}
        kernel = execution.get("kernel") or {}
        kernel_response = kernel.get("response") or {}
        if kernel.get("context_after") is not None:
            context_events.append(
                {
                    "round": round_index,
                    "kind": "execution",
                    "phase": "execution",
                    "request_id": kernel.get("request_id"),
                    "session_id": kernel_response.get("session_id"),
                    "revision": kernel_response.get("context_revision"),
                    "turn": kernel_response.get("turn"),
                    "before": kernel.get("context_before"),
                    "after": kernel.get("context_after"),
                }
            )
        moved = execution.get("moved_m")
        if (
            execution.get("executed") is True
            and execution.get("segment_success") is True
            and isinstance(moved, (int, float))
            and float(moved) > 0.05
        ):
            movements.append(
                {
                    "round": round_index,
                    "moved_m": moved,
                    "target_node_id": execution.get("target_node_id"),
                    "route_node_ids": execution.get("route_node_ids"),
                    "session_id": kernel_response.get("session_id"),
                    "context_revision": kernel_response.get("context_revision"),
                    "execution_status": kernel_response.get("execution_status"),
                }
            )
        arbitration = round_result.get("arbitration") or {}
        if arbitration.get("ok") is True and execution.get("executed") is True:
            decisions.append(
                {
                    "round": round_index,
                    "decision_node": arbitration.get("matched_node_id"),
                    "model_direction": arbitration.get("model_direction"),
                    "selected_edge": arbitration.get("selected_edge"),
                    "selected_route_node_ids": arbitration.get(
                        "selected_route_node_ids"
                    ),
                    "execution_target_node_id": execution.get("target_node_id"),
                    "moved_m": moved,
                }
            )
    return {
        "planner_calls": planner_calls,
        "context_events": context_events,
        "movements": movements,
        "route_decisions": decisions,
        "visual_recovery_attempts": recovery_attempts,
    }


def _context_continuity(events: list[dict]) -> tuple[bool, dict]:
    if len(events) < 2:
        return False, {"reason": "fewer than two Context events"}
    transitions = []
    ok = True
    for index in range(1, len(events)):
        previous = events[index - 1]
        current = events[index]
        previous_after = previous.get("after") or {}
        current_before = current.get("before") or {}
        previous_history = previous_after.get("history") or []
        current_history = (current.get("after") or {}).get("history") or []
        revision_ok = (
            isinstance(previous.get("revision"), int)
            and isinstance(current.get("revision"), int)
            and current["revision"] == previous["revision"] + 1
        )
        turn_ok = current_before.get("turn") == previous_after.get("turn")
        history_ok = len(current_history) == len(previous_history) + 1
        session_ok = (
            previous.get("session_id") is not None
            and current.get("session_id") == previous.get("session_id")
        )
        transition = {
            "from": {
                "round": previous.get("round"),
                "kind": previous.get("kind"),
                "revision": previous.get("revision"),
                "after_turn": previous_after.get("turn"),
                "history_len": len(previous_history),
            },
            "to": {
                "round": current.get("round"),
                "kind": current.get("kind"),
                "revision": current.get("revision"),
                "before_turn": current_before.get("turn"),
                "history_len": len(current_history),
            },
            "revision_incremented": revision_ok,
            "turn_continued": turn_ok,
            "history_appended": history_ok,
            "same_session": session_ok,
        }
        transitions.append(transition)
        ok = ok and revision_ok and turn_ok and history_ok and session_ok
    return ok, {"events": len(events), "transitions": transitions}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--kernel-host", default=str(DEFAULT_HOST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python used for the planner bridge, target setup and navigation",
    )
    parser.add_argument("--max-new-tokens", type=int, default=4096)
    parser.add_argument("--model-timeout", type=float, default=240.0)
    parser.add_argument("--enable-thinking", action="store_true", default=True)
    parser.add_argument("--kernel-exec-timeout-ms", type=int, default=180000)
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--max-total-wall-seconds", type=float, default=1500.0)
    parser.add_argument("--task-id", default=TASK_ID)
    parser.add_argument("--schema", default="vln.cap08b01.result.v1")
    parser.add_argument(
        "--task-label",
        default="M1-VLN-CARLA-CAP-08B-01",
    )
    parser.add_argument("--run-prefix", default="cap08b-01")
    parser.add_argument(
        "--max-visual-recovery-attempts",
        type=int,
        default=3,
    )
    parser.add_argument(
        "--max-visual-recovery-per-type",
        type=int,
        default=2,
    )
    parser.add_argument("--no-visual-recovery", action="store_true")
    parser.add_argument(
        "--session-id",
        default=None,
    )
    parser.add_argument("--skip-target-setup", action="store_true")
    parser.add_argument("--skip-safety-guards", action="store_true")
    args = parser.parse_args(argv)
    if args.session_id is None:
        args.session_id = f"{args.task_id}-s1-{int(time.time())}"
    if args.max_visual_recovery_attempts < 0:
        raise SystemExit("--max-visual-recovery-attempts must be non-negative")
    if args.max_visual_recovery_per_type < 0:
        raise SystemExit("--max-visual-recovery-per-type must be non-negative")

    host_exe = os.path.abspath(args.kernel_host)
    if not (os.path.isfile(host_exe) and os.access(host_exe, os.X_OK)):
        raise SystemExit(f"--kernel-host is not executable: {host_exe}")
    if not _port_open(args.port):
        raise SystemExit(
            f"CARLA is not listening on {args.host}:{args.port}; refusing to run"
        )

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    nav_output = output / "navigation"
    nav_output.mkdir(parents=True, exist_ok=True)
    started = _utc_now()

    host_evidence = _host_evidence(Path(host_exe))
    _write_json(output / "host.json", host_evidence)

    result: dict = {
        "schema": args.schema,
        "task_id": args.task_id,
        "started_utc": started,
        "session_id": args.session_id,
        "host": host_evidence,
        "status": "FAIL",
        "checks": {},
        "error": None,
    }

    bridge_state = None
    bridge_stopped = None
    try:
        bridge_state = _start_planner_bridge(
            args.python,
            max_new_tokens=args.max_new_tokens,
            model_timeout=args.model_timeout,
            enable_thinking=bool(args.enable_thinking),
            log_path=output / "planner_bridge_stderr.log",
            cwd=REPO_ROOT,
        )
        bridge_evidence = {
            "script": str(PLANNER_BRIDGE),
            "script_sha256": _sha256(PLANNER_BRIDGE),
            "endpoint": bridge_state["endpoint"],
            "ready": bridge_state["ready"],
            "command_without_token": bridge_state["command_without_token"],
            "token_recorded": False,
            "stderr_log": bridge_state["log_path"],
        }
        _write_json(output / "planner_bridge.json", bridge_evidence)
        result["planner_bridge"] = bridge_evidence
        env = _planner_env(bridge_state)

        if not args.skip_target_setup:
            map_setup = _ensure_town10_map(args.host, args.port)
            _write_json(output / "map_setup.json", map_setup)
            result["map_setup"] = map_setup
            warmup = _warmup_world(args.host, args.port)
            _write_json(output / "world_warmup.json", warmup)
            result["world_warmup"] = warmup
            setup_log = output / "targets_setup.log"
            setup = subprocess.run(
                [args.python, str(TARGET_SETUP)],
                cwd=str(REPO_ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=300.0,
            )
            setup_log.write_text(setup.stdout or "", encoding="utf-8")
            result["target_setup"] = {
                "command": [args.python, str(TARGET_SETUP)],
                "returncode": setup.returncode,
                "log": str(setup_log),
            }
            if setup.returncode != 0:
                result["status"] = "BLOCKED"
                result["error"] = "Town10 multipoint target setup failed"
                result["finished_utc"] = _utc_now()
                _write_json(output / "result.json", result)
                return 2

        if not args.skip_safety_guards:
            guard_ok, guard_record = _session_guard(host_exe, env, output)
            failure_ok, failure_record = _bridge_failure_guard(
                host_exe, env, output
            )
            result["safety_guards"] = {
                "session_guard_ok": guard_ok,
                "session_guard": guard_record,
                "bridge_failure_ok": failure_ok,
                "bridge_failure": failure_record,
            }
        else:
            guard_ok = failure_ok = True

        nav_command = [
            args.python,
            str(NAVIGATION),
            "--scenario", "town10_multipoint",
            "--kernel-host", host_exe,
            "--host-planner",
            "--session-id", args.session_id,
            "--output-dir", str(nav_output),
            "--task-label", args.task_label,
            "--run-prefix", args.run_prefix,
            "--start-node", "fork",
            "--goal-node", "c_goal",
            "--start-yaw-deg", "-89.3578",
            "--spawn-z", "0.5",
            "--round-fovs", "100,70,70,70",
            "--segment-nodes", "1",
            "--rounds", str(args.rounds),
            # mid-obstacle injection is disabled (round 0), but the runner
            # validates the edge name unconditionally; name a real multipoint
            # edge instead of the carpark-only default.
            "--mid-obstacle-edge", "fork,b_mid",
            "--mid-obstacle-round", "0",
            "--targets", "red car,blue car,blue car,blue car",
            "--target-kind", "车辆",
            "--instruction", INSTRUCTION,
            "--target-note", TARGET_NOTE,
            "--max-new-tokens", str(args.max_new_tokens),
            "--timeout", str(args.model_timeout),
            "--kernel-exec-timeout-ms", str(args.kernel_exec_timeout_ms),
            "--max-total-wall-seconds", str(args.max_total_wall_seconds),
            "--max-visual-recovery-attempts",
            str(args.max_visual_recovery_attempts),
            "--max-visual-recovery-per-type",
            str(args.max_visual_recovery_per_type),
        ]
        if args.no_visual_recovery:
            nav_command.append("--no-visual-recovery")
        nav_log_path = output / "navigation_stdout.log"
        with open(nav_log_path, "w", encoding="utf-8") as nav_log:
            nav = subprocess.run(
                nav_command,
                cwd=str(REPO_ROOT),
                env=env,
                stdout=nav_log,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=args.max_total_wall_seconds + 300.0,
            )
        result["navigation"] = {
            "command": nav_command,
            "returncode": nav.returncode,
            "log": str(nav_log_path),
            "output_dir": str(nav_output),
        }
        try:
            nav_result = _read_json(nav_output / "result.json")
        except Exception as error:
            result["error"] = f"navigation result.json is unavailable: {error}"
            result["finished_utc"] = _utc_now()
            _write_json(output / "result.json", result)
            return 3
        result["navigation_status"] = nav_result.get("status")
        result["navigation_task_status"] = nav_result.get("task_status")
        result["navigation_summary"] = nav_result.get("summary")
        result["navigation_stop"] = nav_result.get("stop")

        evidence = _collect_run_evidence(nav_result)
        continuity_ok, continuity = _context_continuity(
            evidence["context_events"]
        )
        planner_calls = evidence["planner_calls"]
        recovery_attempts = evidence["visual_recovery_attempts"]
        recovery_rounds = [
            {
                "round": round_result.get("round"),
                "state": (round_result.get("visual_recovery") or {}).get("state"),
                "attempt_count": (
                    round_result.get("visual_recovery") or {}
                ).get("attempt_count"),
                "recovered": (round_result.get("visual_recovery") or {}).get(
                    "recovered"
                ),
                "last_uncertainty": (
                    round_result.get("visual_recovery") or {}
                ).get("last_uncertainty"),
            }
            for round_result in nav_result.get("rounds") or []
            if round_result.get("visual_recovery")
        ]
        per_type_counts: dict[str, int] = {}
        for attempt in recovery_attempts:
            if attempt.get("phase") != "reobservation":
                continue
            kind = attempt.get("uncertainty_type")
            per_type_counts[kind] = per_type_counts.get(kind, 0) + 1
        recovery_bounded = all(
            count <= args.max_visual_recovery_per_type
            for count in per_type_counts.values()
        ) and len(
            [
                attempt
                for attempt in recovery_attempts
                if attempt.get("phase") == "reobservation"
            ]
        ) <= args.max_visual_recovery_attempts
        candidate_calls = [
            call
            for call in planner_calls
            if call.get("status") == "candidate"
            and isinstance(call.get("raw_output_chars"), int)
            and call["raw_output_chars"] > 0
        ]
        real_backend_ok = bool(candidate_calls) and all(
            (call.get("model") or {}).get("backend") == "zdt-taichu-server"
            and call.get("response_model") is not None
            for call in candidate_calls
        )
        context_prompt_injected = bool(candidate_calls) and all(
            bool(call.get("prompt_sha256"))
            and call.get("context_selected_count") is not None
            for call in candidate_calls
        )
        planner_boundary_ok = bool(candidate_calls) and all(
            call.get("is_execution_permit") is False
            and call.get("planner_request_id")
            and call.get("planning_artifact_id")
            and call.get("planner_session_id") == "1"
            for call in candidate_calls
        )
        sessions = {
            call.get("request_id")
            for call in planner_calls
            if call.get("request_id")
        }
        planner_session_ids = {
            event.get("session_id")
            for event in evidence["context_events"]
            if event.get("session_id")
        }
        same_session = planner_session_ids == {args.session_id}
        decision_nodes = {
            decision.get("decision_node")
            for decision in evidence["route_decisions"]
            if decision.get("decision_node")
        }
        meta = nav_result.get("meta") or {}
        host_session = meta.get("host_session") or {}
        final_get = host_session.get("final_get") or {}
        close = host_session.get("close") or {}
        get_after_close = host_session.get("get_after_close") or {}
        session_finalized = bool(
            final_get.get("accepted") is True
            and close.get("accepted") is True
            and close.get("session_state") == "DESTROYED"
            and (get_after_close.get("error") or {}).get("code")
            == "session-closed"
        )
        kernel_path_ok = bool(
            meta.get("execution_mode") == "kernel"
            and (meta.get("host_planner") or {}).get("enabled") is True
            and ((meta.get("agent_kernel") or {}).get("capability_provider")
                 == "vln.parking.carla")
        )
        executed_kernel_rounds = [
            round_result
            for round_result in nav_result.get("rounds") or []
            if (
                ((round_result.get("execution") or {}).get("kernel") or {}).get(
                    "response"
                )
                or {}
            ).get("execution_status")
            == "completed"
        ]
        no_collisions = not (nav_result.get("collision_events") or [])

        checks = {
            "navigation_pass": nav_result.get("status") == "PASS",
            "goal_reached": nav_result.get("task_status") == "goal_reached",
            "at_least_3_real_model_calls": len(candidate_calls) >= 3,
            "at_least_2_route_decisions": len(decision_nodes) >= 2,
            "at_least_2_real_movements": len(evidence["movements"]) >= 2,
            "same_persistent_session": same_session,
            "context_continuity": continuity_ok,
            "planner_candidate_only": planner_boundary_ok,
            "real_taichu_backend": real_backend_ok,
            "context_prompt_injected": context_prompt_injected,
            "visual_recovery_bounded": recovery_bounded,
            "kernel_authorization_path": kernel_path_ok,
            "kernel_executed_rounds_match": len(executed_kernel_rounds)
            == len(evidence["movements"]),
            "no_collisions": no_collisions,
            "session_finalized": session_finalized,
            "session_guard_ok": guard_ok,
            "bridge_failure_fail_closed": failure_ok,
        }
        core_ok = all(checks.values())
        result.update(
            {
                "checks": checks,
                "planner_calls": planner_calls,
                "candidate_call_count": len(candidate_calls),
                "route_decisions": evidence["route_decisions"],
                "decision_nodes": sorted(decision_nodes),
                "movements": evidence["movements"],
                "visual_recovery_attempts": recovery_attempts,
                "visual_recovery_rounds": recovery_rounds,
                "visual_recovery": {
                    "attempt_count": len(
                        [
                            attempt
                            for attempt in recovery_attempts
                            if attempt.get("phase") == "reobservation"
                        ]
                    ),
                    "attempts_by_type": per_type_counts,
                    "bounded": recovery_bounded,
                },
                "context_events": evidence["context_events"],
                "context_continuity": continuity,
                "session_ids": sorted(sessions),
                "persistent_session_ids": sorted(planner_session_ids),
                "final_session": {
                    "final_get": final_get,
                    "close": close,
                    "get_after_close": get_after_close,
                },
                "collision_events": nav_result.get("collision_events"),
                "final_state": nav_result.get("final_state"),
                "status": "PASS" if core_ok and nav.returncode == 0 else "PARTIAL",
                "error": (
                    None
                    if core_ok and nav.returncode == 0
                    else "CAP-08B-01 core conditions not all proven"
                ),
                "finished_utc": _utc_now(),
            }
        )
        _write_json(output / "result.json", result)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "navigation_status": result.get("navigation_status"),
                    "candidate_calls": len(candidate_calls),
                    "decision_nodes": sorted(decision_nodes),
                    "movements": len(evidence["movements"]),
                    "context_continuity": continuity_ok,
                    "checks": checks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if result["status"] == "PASS" else 3
    finally:
        bridge_stopped = _stop_planner_bridge(bridge_state)
        if bridge_stopped is not None:
            result["planner_bridge_stopped"] = bridge_stopped
            try:
                _write_json(output / "bridge_stop.json", bridge_stopped)
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
