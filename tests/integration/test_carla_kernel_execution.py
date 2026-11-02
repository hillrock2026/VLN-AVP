"""Kernel-to-CARLA adapter tests against the compiled Kernel host.

These tests use a fake bridge handler instead of CARLA. They prove the real
cross-process chain:

    AgentIntent -> IPC request -> C++ Host -> IssueRuntimeExecutionAuthority
      -> Runtime::Run -> registered parking.move invoker -> bridge -> result

and the fail-closed paths: missing authorization, intent/target mismatch,
capability execution failure and timeout. A passing test here is **not**
evidence that a CARLA vehicle moved; that requires the real end-to-end run.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from vln.carla.kernel_bridge import CarlaExecutionBridge
from vln.client import HostClient, build_request
from vln.intent import AgentIntent, Target
from vln.ipc.envelope import ErrorCode, HostKind, SubmissionStatus

pytestmark = pytest.mark.integration

_EXE_ENV = "VLN_KERNEL_HOST_EXE"


def _host_exe() -> str:
    exe = os.environ.get(_EXE_ENV)
    if not exe:
        pytest.skip(f"{_EXE_ENV} is not set; build kernel_host first")
    path = Path(exe)
    if not path.is_file():
        pytest.skip(f"{_EXE_ENV} points to a missing file: {exe}")
    return str(path)


def _intent(intent_id: str = "intent-carla-1") -> AgentIntent:
    return AgentIntent(
        intent_id=intent_id,
        target=Target(x=1.0, y=2.0, heading=0.0),
    )


def _fake_result(*, status: str = "completed", stopped: bool = True) -> dict:
    return {
        "status": status,
        "stop_reason": "success" if status == "completed" else "safety_stop",
        "pre_state": {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "speed": 0.0},
        "post_state": {
            "x": 1.5 if stopped else 3.0,
            "y": 0.0,
            "z": 0.0,
            "yaw": 0.0,
            "speed": 0.0 if stopped else 1.0,
        },
        "stopped": stopped,
        "segment_success": status == "completed",
        "steps": 12,
        "records": [{"step": 0, "x": 0.0, "y": 0.0, "speed": 0.0}],
    }


def _host_env(bridge: CarlaExecutionBridge, timeout_ms: int = 30000) -> dict:
    env = os.environ.copy()
    env["VLN_CARLA_EXEC_BRIDGE"] = bridge.endpoint
    env["VLN_CARLA_EXEC_TOKEN"] = bridge.token
    env["VLN_CARLA_EXEC_TIMEOUT_MS"] = str(timeout_ms)
    return env


def _register(bridge: CarlaExecutionBridge, intent: AgentIntent, request_id: str) -> None:
    bridge.register_permit(
        request_id=request_id,
        intent_id=intent.intent_id,
        target=intent.target.to_object(),
        payload=intent.to_payload(),
    )


def _run(
    handler,
    *,
    timeout_ms: int = 30000,
    authorize: bool = True,
    intent: AgentIntent | None = None,
    request_id: str = "req-carla-1",
):
    intent = intent or _intent()
    calls: list = []

    def wrapped(permit):
        calls.append(permit)
        return handler(permit)

    bridge = CarlaExecutionBridge(wrapped, request_timeout_s=10.0).start()
    try:
        if authorize:
            _register(bridge, intent, request_id)
        request = build_request(intent, request_id=request_id)
        with HostClient([_host_exe()], env=_host_env(bridge, timeout_ms)) as client:
            response = client.send(request)
        # A host timeout returns before the bridge thread records its terminal
        # transaction; wait for that record so the evidence is observable.
        deadline = time.monotonic() + 3.0
        transaction = bridge.get_transaction(request_id)
        while transaction is None and time.monotonic() < deadline:
            time.sleep(0.05)
            transaction = bridge.get_transaction(request_id)
        return response, transaction, calls, intent, request
    finally:
        bridge.close()


# -- success path -----------------------------------------------------------


def test_agent_intent_reaches_carla_bridge_through_real_kernel() -> None:
    response, transaction, calls, intent, _ = _run(lambda permit: _fake_result())

    assert response.request_id == "req-carla-1"
    assert response.host_kind == HostKind.KERNEL
    assert response.accepted is True
    assert response.submission_status == SubmissionStatus.COMPLETED
    assert response.execution_status == "completed"
    assert response.ok is True
    assert response.error is None

    output = json.loads(response.output)
    assert output["output_version"] == "2"
    assert output["status"] == "carla_completed"
    assert output["execution_mode"] == "carla"
    assert output["action"] == "parking.move"
    assert output["intent_id"] == intent.intent_id
    assert output["request_id"] == "req-carla-1"
    assert output["target"] == intent.target.to_object()
    assert output["vehicle"]["moved_m"] == pytest.approx(1.5)
    assert output["vehicle"]["stopped"] is True
    assert output["vehicle"]["records"] == [{"step": 0, "x": 0.0, "y": 0.0, "speed": 0.0}]

    assert len(calls) == 1
    assert transaction is not None
    assert transaction["authorized"] is True
    assert transaction["handler_started"] is True
    assert transaction["handler_finished"] is True
    assert transaction["status"] == "completed"
    # The intent id and IPC request id remain independent identities.
    assert output["intent_id"] != output["request_id"]


# -- authorization / validation failures -----------------------------------


def test_missing_permit_keeps_the_kernel_path_failed_and_runs_no_handler() -> None:
    response, transaction, calls, _, _ = _run(
        lambda permit: _fake_result(), authorize=False
    )

    assert response.host_kind == HostKind.KERNEL
    assert response.accepted is True
    assert response.submission_status == SubmissionStatus.FAILED
    assert response.execution_status == "failed"
    assert response.ok is False
    assert response.output is None
    assert response.error is not None
    assert response.error["code"] == ErrorCode.CAPABILITY_INVOCATION_FAILED
    assert calls == []
    assert transaction["authorized"] is False
    assert transaction["handler_started"] is False


def test_target_mismatch_is_rejected_before_the_handler() -> None:
    permitted = _intent()
    forged = AgentIntent(
        intent_id=permitted.intent_id,
        target=Target(x=9.0, y=2.0, heading=0.0),
    )
    calls: list = []

    def handler(permit):
        calls.append(permit)
        return _fake_result()

    bridge = CarlaExecutionBridge(handler, request_timeout_s=10.0).start()
    try:
        _register(bridge, permitted, "req-carla-mismatch")
        request = build_request(forged, request_id="req-carla-mismatch")
        with HostClient([_host_exe()], env=_host_env(bridge)) as client:
            response = client.send(request)
        transaction = bridge.get_transaction("req-carla-mismatch")
    finally:
        bridge.close()

    assert response.ok is False
    assert response.execution_status == "failed"
    assert calls == []
    assert transaction["authorized"] is False
    assert "target_mismatch" in transaction["reason"]


def test_wrong_token_never_reaches_the_handler() -> None:
    original = _intent()
    bridge = CarlaExecutionBridge(lambda permit: _fake_result()).start()
    try:
        _register(bridge, original, "req-carla-token")
        request = build_request(original, request_id="req-carla-token")
        env = _host_env(bridge)
        env["VLN_CARLA_EXEC_TOKEN"] = "not-the-token"
        with HostClient([_host_exe()], env=env) as client:
            response = client.send(request)
        transaction = bridge.get_transaction("req-carla-token")
    finally:
        bridge.close()

    assert response.ok is False
    assert response.execution_status == "failed"
    assert transaction["authorized"] is False


def test_invalid_bridge_configuration_fails_closed_at_startup() -> None:
    env = os.environ.copy()
    env["VLN_CARLA_EXEC_BRIDGE"] = "not-a-host-port"
    env.pop("VLN_CARLA_EXEC_TOKEN", None)
    completed = subprocess.run(
        [_host_exe()],
        input=b"",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=10,
    )
    assert completed.returncode == 3
    assert b"fatal: invalid CARLA execution bridge configuration" in completed.stderr


# -- execution failure and timeout -----------------------------------------


def test_capability_execution_failure_is_not_reported_as_success() -> None:
    response, transaction, calls, _, _ = _run(
        lambda permit: _fake_result(status="failed", stopped=True)
    )

    assert response.ok is False
    assert response.execution_status == "failed"
    assert response.output is None
    assert response.error is not None
    assert response.error["code"] == ErrorCode.CAPABILITY_INVOCATION_FAILED
    assert len(calls) == 1
    assert transaction["authorized"] is True
    assert transaction["handler_finished"] is True
    assert transaction["status"] == "failed"
    assert transaction["vehicle"]["stopped"] is True


def test_handler_exception_is_correlated_and_fails_the_kernel_execution() -> None:
    def handler(permit):
        raise RuntimeError("simulated controller failure")

    response, transaction, calls, _, _ = _run(handler)

    assert response.ok is False
    assert response.execution_status == "failed"
    assert response.error["code"] == ErrorCode.CAPABILITY_INVOCATION_FAILED
    assert len(calls) == 1
    assert transaction["authorized"] is True
    assert transaction["handler_started"] is True
    assert transaction["handler_finished"] is False
    assert transaction["error"]["type"] == "RuntimeError"


def test_kernel_execution_timeout_is_reported_as_failure() -> None:
    started = threading.Event()

    def handler(permit):
        started.set()
        time.sleep(1.0)
        return _fake_result()

    response, transaction, calls, _, _ = _run(handler, timeout_ms=300)

    assert response.ok is False
    assert response.execution_status == "failed"
    assert response.error["code"] == ErrorCode.CAPABILITY_INVOCATION_FAILED
    assert started.wait(2.0) is True
    assert len(calls) == 1
    assert transaction["handler_started"] is True


# -- no-bridge regression ---------------------------------------------------


def test_simulation_stub_is_unchanged_when_no_bridge_is_configured() -> None:
    intent = _intent("intent-stub-regression")
    env = os.environ.copy()
    env.pop("VLN_CARLA_EXEC_BRIDGE", None)
    env.pop("VLN_CARLA_EXEC_TOKEN", None)
    request = build_request(intent, request_id="req-stub-regression")
    with HostClient([_host_exe()], env=env) as client:
        response = client.send(request)

    assert response.ok is True
    output = json.loads(response.output)
    assert output == {
        "output_version": "1",
        "status": "stub_completed",
        "execution_mode": "simulation",
        "action": "parking.move",
        "intent_id": "intent-stub-regression",
        "target": {"x": 1.0, "y": 2.0, "heading": 0.0},
    }
