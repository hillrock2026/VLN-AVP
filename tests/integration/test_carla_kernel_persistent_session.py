"""Persistent Kernel Session + Context tests against the compiled Host.

These tests use a fake bridge handler, not CARLA. They prove the real
cross-process chain for the CAP-08A-01 Kernel changes:

    session.create -> persistent ak::Session + ak::context::Context
    round 1 parking.move -> new Workflow/Task in S1 -> bridge -> Context update
    round 2 parking.move -> same S1 -> context revision check -> Context update
    session.get/close -> lifecycle + isolation + fail-closed rejection

A passing test here is not evidence that a CARLA vehicle moved; that requires
the separate real CARLA run.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from vln.carla.kernel_bridge import CarlaExecutionBridge
from vln.client import HostClient, build_request
from vln.intent import AgentIntent, Target
from vln.ipc.envelope import HostKind, Request

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


def _host_env(bridge: CarlaExecutionBridge, timeout_ms: int = 30000) -> dict:
    env = os.environ.copy()
    env["VLN_CARLA_EXEC_BRIDGE"] = bridge.endpoint
    env["VLN_CARLA_EXEC_TOKEN"] = bridge.token
    env["VLN_CARLA_EXEC_TIMEOUT_MS"] = str(timeout_ms)
    return env


def _intent(tag: str) -> AgentIntent:
    return AgentIntent(
        intent_id=f"intent-{tag}",
        target=Target(x=1.0, y=2.0, heading=0.0),
    )


def _result(pre: dict, post: dict, *, status: str = "completed") -> dict:
    return {
        "status": status,
        "stop_reason": "success" if status == "completed" else "safety_stop",
        "pre_state": pre,
        "post_state": post,
        "stopped": status == "completed",
        "segment_success": status == "completed",
    }


class _State:
    def __init__(self) -> None:
        self.x = 0.0
        self.calls: list[dict] = []

    def handler(self, permit):
        pre = {"x": self.x, "y": 0.0, "z": 0.0, "yaw": 0.0, "speed": 0.0}
        post = {
            "x": pre["x"] + 1.5,
            "y": 0.0,
            "z": 0.0,
            "yaw": 0.0,
            "speed": 0.0,
        }
        self.x = post["x"]
        self.calls.append(
            {
                "request_id": permit.request_id,
                "intent_id": permit.intent_id,
                "pre": pre,
                "post": post,
            }
        )
        return _result(pre, post)

    def failing_handler(self, permit):
        pre = {"x": self.x, "y": 0.0, "z": 0.0, "yaw": 0.0, "speed": 0.0}
        post = dict(pre)
        self.calls.append(
            {
                "request_id": permit.request_id,
                "intent_id": permit.intent_id,
                "pre": pre,
                "post": post,
            }
        )
        return _result(pre, post, status="failed")


def _register(bridge, intent: AgentIntent, request_id: str) -> None:
    bridge.register_permit(
        request_id=request_id,
        intent_id=intent.intent_id,
        target=intent.target.to_object(),
        payload=intent.to_payload(),
    )


def _control(client: HostClient, request_id: str, capability: str, payload: dict):
    return client.send(
        Request(
            request_id=request_id,
            capability_id=capability,
            payload=json.dumps(payload, separators=(",", ":")),
        )
    )


def _move(
    client: HostClient,
    *,
    bridge=None,
    register_permit: bool = True,
    session_id: str,
    request_id: str,
    expected_revision: int,
    tag: str,
    domain: dict | None = None,
):
    intent = _intent(tag)
    request = build_request(
        intent,
        request_id=request_id,
        session_id=session_id,
        expected_context_revision=expected_revision,
        domain=domain or {"parking_session_id": "cap08a01-test", "skill_execution_id": request_id},
    )
    if register_permit:
        if bridge is None:
            raise ValueError("bridge is required when register_permit is true")
        _register(bridge, intent, request_id)
    return client.send(request), intent


def test_two_rounds_share_one_session_and_context() -> None:
    state = _State()
    bridge = CarlaExecutionBridge(state.handler, request_timeout_s=10.0).start()
    try:
        with HostClient([_host_exe()], env=_host_env(bridge)) as client:
            created = _control(
                client, "ctl-create", "session.create", {"session_id": "s1"}
            )
            assert created.ok is True
            assert created.host_kind == HostKind.KERNEL
            assert created.session_id == "s1"
            assert created.session_state == "READY"
            assert created.context_revision == 0
            assert created.turn == 0
            assert created.context_after["turn"] == 0

            first, intent1 = _move(
                client,
                bridge=bridge,
                session_id="s1",
                request_id="req-r1",
                expected_revision=0,
                tag="r1",
            )
            assert first.ok is True
            assert first.session_id == "s1"
            assert first.context_revision == 1
            assert first.turn == 1
            assert first.task_id and first.workflow_id
            assert first.context_updated is True
            assert first.context_before["turn"] == 0
            assert first.context_after["turn"] == 1
            assert first.context_after["status"] == "completed"
            assert first.context_after["real_carla_execution"] is True
            assert first.context_after["vehicle"]["post_state"]["x"] == pytest.approx(1.5)
            assert first.context_after["task_id"] == first.task_id
            assert first.context_after["workflow_id"] == first.workflow_id

            second, intent2 = _move(
                client,
                bridge=bridge,
                session_id="s1",
                request_id="req-r2",
                expected_revision=1,
                tag="r2",
            )
            assert second.ok is True
            assert second.session_id == "s1"
            assert second.context_revision == 2
            assert second.turn == 2
            assert second.task_id and second.workflow_id
            assert second.task_id != first.task_id
            assert second.workflow_id != first.workflow_id
            assert second.context_before["turn"] == 1
            assert (
                second.context_before["vehicle"]["post_state"]["x"]
                == pytest.approx(1.5)
            )
            assert second.context_after["turn"] == 2
            assert second.context_after["vehicle"]["post_state"]["x"] == pytest.approx(3.0)
            assert second.context_after["observation_status"] == "success"

            got = _control(client, "ctl-get", "session.get", {"session_id": "s1"})
            assert got.ok is True
            assert got.session_id == "s1"
            assert got.session_state == "READY"
            assert got.context_revision == 2
            assert got.turn == 2
            info = json.loads(got.output)
            assert info["workflow_count"] == 2
            assert info["task_count"] == 2
            assert info["context"]["vehicle"]["post_state"]["x"] == pytest.approx(3.0)
            assert len({call["request_id"] for call in state.calls}) == 2
            assert {call["request_id"] for call in state.calls} == {"req-r1", "req-r2"}

            closed = _control(
                client, "ctl-close", "session.close", {"session_id": "s1"}
            )
            assert closed.ok is True
            assert closed.session_state == "DESTROYED"
            assert closed.session_id == "s1"

            # Closed session: no new execution and no Context access.
            calls_before = len(state.calls)
            after_close, _ = _move(
                client,
                register_permit=False,
                session_id="s1",
                request_id="req-after-close",
                expected_revision=2,
                tag="after-close",
            )
            assert after_close.ok is False
            assert after_close.error["code"] == "session-closed"
            assert len(state.calls) == calls_before
            get_closed = _control(
                client, "ctl-get-closed", "session.get", {"session_id": "s1"}
            )
            assert get_closed.ok is False
            assert get_closed.error["code"] == "session-closed"
    finally:
        bridge.close()


def test_sessions_are_isolated_and_wrong_revision_is_rejected() -> None:
    state = _State()
    bridge = CarlaExecutionBridge(state.handler, request_timeout_s=10.0).start()
    try:
        with HostClient([_host_exe()], env=_host_env(bridge)) as client:
            _control(client, "ctl-s1", "session.create", {"session_id": "iso-s1"})
            _control(client, "ctl-s2", "session.create", {"session_id": "iso-s2"})

            r1, _ = _move(
                client,
                bridge=bridge,
                session_id="iso-s1",
                request_id="req-iso-s1-1",
                expected_revision=0,
                tag="iso-s1-1",
            )
            assert r1.ok is True
            assert r1.context_revision == 1

            # S2 starts at revision 0; it cannot observe S1's turn/post-state.
            r2, _ = _move(
                client,
                bridge=bridge,
                session_id="iso-s2",
                request_id="req-iso-s2-1",
                expected_revision=0,
                tag="iso-s2-1",
            )
            assert r2.ok is True
            assert r2.session_id == "iso-s2"
            assert r2.context_revision == 1
            assert r2.context_before["turn"] == 0
            assert "vehicle" not in r2.context_before
            assert r2.context_after["turn"] == 1

            calls_before = len(state.calls)
            mismatch, _ = _move(
                client,
                register_permit=False,
                session_id="iso-s1",
                request_id="req-wrong-rev",
                expected_revision=0,
                tag="wrong-rev",
            )
            assert mismatch.ok is False
            assert mismatch.error["code"] == "context-revision-mismatch"
            assert mismatch.session_id == "iso-s1"
            assert mismatch.context_revision == 1
            assert len(state.calls) == calls_before

            s1_info = _control(
                client, "ctl-s1-get", "session.get", {"session_id": "iso-s1"}
            )
            assert s1_info.context_revision == 1
            assert s1_info.turn == 1
            s2_info = _control(
                client, "ctl-s2-get", "session.get", {"session_id": "iso-s2"}
            )
            assert s2_info.context_revision == 1
            assert s2_info.turn == 1
    finally:
        bridge.close()


def test_authorization_rejection_is_not_context_success() -> None:
    state = _State()
    bridge = CarlaExecutionBridge(state.handler, request_timeout_s=10.0).start()
    try:
        with HostClient([_host_exe()], env=_host_env(bridge)) as client:
            _control(client, "ctl-auth", "session.create", {"session_id": "auth-s1"})
            first, _ = _move(
                client,
                bridge=bridge,
                session_id="auth-s1",
                request_id="req-auth-1",
                expected_revision=0,
                tag="auth-1",
            )
            assert first.ok is True
            calls_before = len(state.calls)

            # No permit is registered: the Kernel path fails before the handler.
            rejected, _ = _move(
                client,
                register_permit=False,
                session_id="auth-s1",
                request_id="req-auth-missing-permit",
                expected_revision=1,
                tag="auth-missing-permit",
            )
            assert rejected.ok is False
            assert rejected.execution_status == "failed"
            assert rejected.context_updated is True
            assert rejected.context_revision == 2
            assert rejected.context_after["status"] == "failed"
            assert rejected.context_after["observation_status"] == "failure"
            assert rejected.context_after["real_carla_execution"] is False
            assert len(state.calls) == calls_before

            got = _control(
                client, "ctl-auth-get", "session.get", {"session_id": "auth-s1"}
            )
            assert got.ok is True
            assert got.context_revision == 2
            assert got.turn == 2
            info = json.loads(got.output)
            assert info["context"]["status"] == "failed"
            assert info["context"]["turn"] == 2
    finally:
        bridge.close()


def test_provider_failure_is_not_context_success() -> None:
    state = _State()
    bridge = CarlaExecutionBridge(
        state.failing_handler, request_timeout_s=10.0
    ).start()
    try:
        with HostClient([_host_exe()], env=_host_env(bridge)) as client:
            _control(client, "ctl-fail", "session.create", {"session_id": "fail-s1"})
            intent = _intent("provider-fail")
            _register(bridge, intent, "req-provider-fail")
            request = build_request(
                intent,
                request_id="req-provider-fail",
                session_id="fail-s1",
                expected_context_revision=0,
                domain={"parking_session_id": "cap08a01-test"},
            )
            response = client.send(request)
            assert response.ok is False
            assert response.execution_status == "failed"
            assert response.context_updated is True
            assert response.context_revision == 1
            assert response.context_after["status"] == "failed"
            assert response.context_after["observation_status"] == "failure"
            assert response.context_after["real_carla_execution"] is False

            got = _control(
                client, "ctl-fail-get", "session.get", {"session_id": "fail-s1"}
            )
            assert got.ok is True
            assert got.context_revision == 1
            assert got.turn == 1
            info = json.loads(got.output)
            assert info["context"]["status"] == "failed"
    finally:
        bridge.close()


def test_bridge_unavailable_is_context_failure() -> None:
    # Start a bridge to get a valid endpoint/token, then close it before the
    # Host attempts the connection.
    bridge = CarlaExecutionBridge(lambda permit: None, request_timeout_s=1.0).start()
    endpoint = bridge.endpoint
    token = bridge.token
    bridge.close()
    host, port = endpoint.rsplit(":", 1)
    env = os.environ.copy()
    env["VLN_CARLA_EXEC_BRIDGE"] = endpoint
    env["VLN_CARLA_EXEC_TOKEN"] = token
    env["VLN_CARLA_EXEC_TIMEOUT_MS"] = "3000"
    with HostClient([_host_exe()], env=env) as client:
        _control(client, "ctl-down", "session.create", {"session_id": "down-s1"})
        intent = _intent("bridge-down")
        request = build_request(
            intent,
            request_id="req-bridge-down",
            session_id="down-s1",
            expected_context_revision=0,
            domain={"parking_session_id": "cap08a01-test"},
        )
        response = client.send(request)
        assert response.ok is False
        assert response.execution_status == "failed"
        assert response.context_updated is True
        assert response.context_revision == 1
        assert response.context_after["status"] == "failed"
        assert response.context_after["real_carla_execution"] is False


def test_session_context_update_records_domain_state_and_guards_revision() -> None:
    state = _State()
    bridge = CarlaExecutionBridge(state.handler).start()
    try:
        with HostClient([_host_exe()], env=_host_env(bridge)) as client:
            created = _control(
                client, "ctx-create", "session.create", {"session_id": "ctx-s1"}
            )
            assert created.ok is True
            assert created.context_revision == 0

            updated = client.send(
                Request(
                    request_id="ctx-update-1",
                    capability_id="session.context.update",
                    payload=json.dumps(
                        {
                            "parking": {
                                "current_stage": "ENTRY",
                                "completed_stages": ["TARGET_BINDING"],
                            },
                            "kind": "stage_transition",
                            "status": "running",
                        },
                        separators=(",", ":"),
                    ),
                    session_id="ctx-s1",
                    expected_context_revision=0,
                )
            )
            assert updated.ok is True
            assert updated.observation_status == "success"
            assert updated.context_revision == 1
            assert updated.context_after["domain"]["parking"] == {
                "current_stage": "ENTRY",
                "completed_stages": ["TARGET_BINDING"],
            }

            mismatch = client.send(
                Request(
                    request_id="ctx-update-stale",
                    capability_id="session.context.update",
                    payload=json.dumps(
                        {"parking": {"current_stage": "X"}},
                        separators=(",", ":"),
                    ),
                    session_id="ctx-s1",
                    expected_context_revision=0,
                )
            )
            assert mismatch.ok is False
            assert mismatch.error["code"] == "context-revision-mismatch"
            assert mismatch.context_revision == 1
    finally:
        bridge.close()
