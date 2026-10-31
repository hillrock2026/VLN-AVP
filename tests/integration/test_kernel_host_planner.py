"""Kernel Host planner.plan integration tests (fake model bridge).

These tests exercise the compiled Host's real composition:

    planner.plan -> ak::planner::Planner -> TaichuPlanningEngine
        -> loopback bridge -> fake backend -> PlanningArtifact -> Context

The planner bridge and backend are deterministic fakes. No model inference,
no CARLA execution and no GPU is involved. The real model is exercised only by
the separate real CARLA run and its evidence.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
import threading
from pathlib import Path
from typing import Any, Iterator

import pytest

from vln.carla.kernel_bridge import CarlaExecutionBridge
from vln.client import HostClient, build_request
from vln.intent import AgentIntent, Target
from vln.ipc.envelope import Request

pytestmark = pytest.mark.integration

_EXE_ENV = "VLN_KERNEL_HOST_EXE"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BRIDGE_PATH = _REPO_ROOT / "scripts" / "taichu_planner_bridge.py"
_TOKEN = "planner-test-token"


def _host_exe() -> str:
    exe = os.environ.get(_EXE_ENV)
    if not exe:
        pytest.skip(f"{_EXE_ENV} is not set; build kernel_host first")
    path = Path(exe)
    if not path.is_file():
        pytest.skip(f"{_EXE_ENV} points to a missing file: {exe}")
    return str(path)


def _bridge_module():
    spec = importlib.util.spec_from_file_location(
        "taichu_planner_bridge_integration", _BRIDGE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeBackend:
    endpoint = "fake://zdt-taichu"
    max_new_tokens = 64
    temperature = 0.0
    enable_thinking = False
    model_name = "fake-taichu"

    def __init__(self, outputs: list[Any]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    def generate_image_with_metadata(self, image_path: str, instruction: str):
        self.calls.append({"image_path": image_path, "instruction": instruction})
        if not self.outputs:
            raise AssertionError("unexpected model call")
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output, {
            "server_response_id": f"resp-{len(self.calls)}",
            "response_model": "fake-taichu-9b",
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        }


@contextlib.contextmanager
def _fake_planner_bridge(outputs: list[Any]) -> Iterator[tuple[str, _FakeBackend]]:
    module = _bridge_module()
    backend = _FakeBackend(outputs)
    server = module._Server(
        ("127.0.0.1", 0), module._Handler,
        expected_token=_TOKEN, backend=backend,
    )
    stop = threading.Event()

    def _serve() -> None:
        while not stop.is_set():
            try:
                server.handle_request()
            except OSError:
                break

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    try:
        yield f"{host}:{port}", backend
    finally:
        stop.set()
        server.server_close()
        thread.join(timeout=2.0)


def _host_env(
    planner_endpoint: str | None,
    *,
    token: str = _TOKEN,
    carla_bridge: CarlaExecutionBridge | None = None,
) -> dict:
    env = os.environ.copy()
    env.pop("VLN_TAICHU_PLANNER_BRIDGE", None)
    env.pop("VLN_TAICHU_PLANNER_TOKEN", None)
    env.pop("VLN_CARLA_EXEC_BRIDGE", None)
    env.pop("VLN_CARLA_EXEC_TOKEN", None)
    if planner_endpoint is not None:
        env["VLN_TAICHU_PLANNER_BRIDGE"] = planner_endpoint
        env["VLN_TAICHU_PLANNER_TOKEN"] = token
        env["VLN_TAICHU_PLANNER_TIMEOUT_MS"] = "15000"
    if carla_bridge is not None:
        env["VLN_CARLA_EXEC_BRIDGE"] = carla_bridge.endpoint
        env["VLN_CARLA_EXEC_TOKEN"] = carla_bridge.token
        env["VLN_CARLA_EXEC_TIMEOUT_MS"] = "15000"
    return env


def _control(
    client: HostClient,
    request_id: str,
    capability: str,
    payload: dict,
):
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
    instruction: str = "go to the red car, then the blue car",
    domain: dict | None = None,
):
    payload = {"image_path": image_path, "instruction": instruction}
    if domain is not None:
        payload["domain"] = domain
    return client.send(
        Request(
            request_id=request_id,
            capability_id="planner.plan",
            payload=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            session_id=session_id,
            expected_context_revision=revision,
            domain=domain,
        )
    )


@pytest.fixture()
def image_path(tmp_path: Path) -> str:
    path = tmp_path / "round_frame.png"
    path.write_bytes(b"real-frame-placeholder-for-bridge-tests")
    return str(path)


def test_planner_context_continuity_and_candidate_output(image_path: str) -> None:
    with _fake_planner_bridge(["RAW-ONE", "RAW-TWO"]) as (endpoint, backend):
        with HostClient([_host_exe()], env=_host_env(endpoint)) as client:
            created = _control(
                client, "ctl-create", "session.create", {"session_id": "p-s1"}
            )
            assert created.ok is True
            assert created.context_revision == 0

            first = _plan(
                client,
                request_id="plan-r1",
                session_id="p-s1",
                revision=0,
                image_path=image_path,
                domain={"round": 1},
            )
            assert first.ok is True
            assert first.session_id == "p-s1"
            assert first.context_revision == 1
            assert first.turn == 1
            output1 = json.loads(first.output)
            assert output1["status"] == "candidate"
            assert output1["is_execution_permit"] is False
            assert output1["raw_output"] == "RAW-ONE"
            assert output1["planner_session_id"] == "1"
            assert output1["planner_request_id"] == "1"
            assert output1["planning_result_id"]
            assert output1["planning_artifact_id"]
            assert output1["strategy"] == "taichu"
            assert output1["server_response"]["server_response_id"] == "resp-1"
            expected_image_sha = hashlib.sha256(
                Path(image_path).read_bytes()
            ).hexdigest()
            assert output1["image_sha256"] == expected_image_sha
            assert output1["prompt"]
            assert output1["prompt_sha256"]
            assert output1["context_selection"]["source"] == (
                "kernel.session.context.history"
            )
            assert first.context_after["phase"] == "planning"
            assert first.context_after["status"] == "planned"
            assert first.context_after["raw_output_preview"] == "RAW-ONE"
            assert len(first.context_after["history"]) == 1
            assert first.context_after["history"][0]["kind"] == "planning"

            second = _plan(
                client,
                request_id="plan-r2",
                session_id="p-s1",
                revision=1,
                image_path=image_path,
                domain={"round": 2},
            )
            assert second.ok is True
            assert second.context_revision == 2
            assert second.turn == 2
            assert second.context_before["turn"] == 1
            assert second.context_before["history"][0]["raw_output_preview"] == (
                "RAW-ONE"
            )
            output2 = json.loads(second.output)
            assert output2["raw_output"] == "RAW-TWO"
            assert output2["planner_request_id"] == "2"
            assert len(second.context_after["history"]) == 2

            # Kernel Context -> bridge -> final model prompt, end to end.
            assert "Kernel 持久上下文" in backend.calls[0]["instruction"]
            assert backend.calls[1]["instruction"].startswith(
                "go to the red car, then the blue car"
            )
            assert "RAW-ONE" in backend.calls[1]["instruction"]
            assert output2["prompt"] == backend.calls[1]["instruction"]
            assert "RAW-ONE" in output2["prompt"]
            assert output2["prompt_sha256"]
            assert output2["context_selection"]["selected_count"] >= 1
            assert output2["context_selection"]["source"] == (
                "kernel.session.context.history"
            )

            calls_before = len(backend.calls)
            mismatch = _plan(
                client,
                request_id="plan-wrong-revision",
                session_id="p-s1",
                revision=0,
                image_path=image_path,
            )
            assert mismatch.ok is False
            assert mismatch.error["code"] == "context-revision-mismatch"
            assert mismatch.context_revision == 2
            assert len(backend.calls) == calls_before

            got = _control(client, "ctl-get", "session.get", {"session_id": "p-s1"})
            assert got.ok is True
            assert got.context_revision == 2
            assert got.turn == 2
            info = json.loads(got.output)
            assert len(info["context"]["history"]) == 2

            closed = _control(
                client, "ctl-close", "session.close", {"session_id": "p-s1"}
            )
            assert closed.ok is True
            assert closed.session_state == "DESTROYED"

            after_close = _plan(
                client,
                request_id="plan-after-close",
                session_id="p-s1",
                revision=2,
                image_path=image_path,
            )
            assert after_close.ok is False
            assert after_close.error["code"] == "session-closed"
            assert len(backend.calls) == calls_before


def test_planner_failures_are_context_failures_and_token_fails_closed(
    image_path: str,
) -> None:
    with _fake_planner_bridge(
        [RuntimeError("model service down"), ""]
    ) as (endpoint, backend):
        with HostClient([_host_exe()], env=_host_env(endpoint)) as client:
            _control(client, "ctl-create", "session.create", {"session_id": "p-f1"})

            failed = _plan(
                client,
                request_id="plan-model-error",
                session_id="p-f1",
                revision=0,
                image_path=image_path,
            )
            assert failed.ok is False
            assert failed.accepted is True
            assert failed.submission_status == "completed"
            assert failed.observation_status == "failure"
            assert failed.error["code"] == "planner-failed"
            assert "model service down" in failed.error["message"]
            assert failed.context_updated is True
            assert failed.context_revision == 1
            assert failed.context_after["status"] == "failed"
            assert failed.context_after["history"][0]["status"] == "failed"

            empty = _plan(
                client,
                request_id="plan-empty-output",
                session_id="p-f1",
                revision=1,
                image_path=image_path,
            )
            assert empty.ok is False
            assert empty.error["code"] == "planner-failed"
            assert "empty" in empty.error["message"]
            assert empty.context_revision == 2

            no_session = _plan(
                client,
                request_id="plan-no-session",
                session_id=None,
                revision=None,
                image_path=image_path,
            )
            assert no_session.ok is False
            assert no_session.error["code"] == "planner-unavailable"
            assert len(backend.calls) == 2

            calls_before = len(backend.calls)
            with HostClient(
                [_host_exe()],
                env=_host_env(endpoint, token="wrong-token"),
            ) as wrong_token_client:
                _control(
                    wrong_token_client,
                    "ctl-wrong-create",
                    "session.create",
                    {"session_id": "p-f2"},
                )
                unauthorized = _plan(
                    wrong_token_client,
                    request_id="plan-wrong-token",
                    session_id="p-f2",
                    revision=0,
                    image_path=image_path,
                )
                assert unauthorized.ok is False
                assert unauthorized.error["code"] == "planner-failed"
                assert "invalid planner bridge token" in unauthorized.error["message"]
                assert unauthorized.context_revision == 1
            assert len(backend.calls) == calls_before

        with HostClient([_host_exe()], env=_host_env(None)) as unconfigured:
            _control(
                unconfigured, "ctl-nobridge-create", "session.create",
                {"session_id": "p-f3"},
            )
            unavailable = _plan(
                unconfigured,
                request_id="plan-no-bridge",
                session_id="p-f3",
                revision=0,
                image_path=image_path,
            )
            assert unavailable.ok is False
            assert unavailable.error["code"] == "planner-unavailable"


class _CarlaState:
    def __init__(self) -> None:
        self.x = 0.0
        self.calls: list[str] = []

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
        self.calls.append(permit.request_id)
        return {
            "status": "completed",
            "stop_reason": "success",
            "pre_state": pre,
            "post_state": post,
            "stopped": True,
            "segment_success": True,
        }


def test_planner_and_execution_share_one_session_revision(image_path: str) -> None:
    carla_state = _CarlaState()
    carla_bridge = CarlaExecutionBridge(
        carla_state.handler, request_timeout_s=10.0
    ).start()
    try:
        with _fake_planner_bridge(["RAW-PLAN-FOR-EXECUTION"]) as (
            endpoint,
            backend,
        ):
            with HostClient(
                [_host_exe()],
                env=_host_env(endpoint, carla_bridge=carla_bridge),
            ) as client:
                _control(
                    client, "ctl-shared-create", "session.create",
                    {"session_id": "p-shared"},
                )
                planned = _plan(
                    client,
                    request_id="plan-shared",
                    session_id="p-shared",
                    revision=0,
                    image_path=image_path,
                )
                assert planned.ok is True
                assert planned.context_revision == 1
                assert len(backend.calls) == 1

                intent = AgentIntent(
                    intent_id="intent-shared-exec",
                    target=Target(x=1.5, y=0.0, heading=0.0),
                )
                carla_bridge.register_permit(
                    request_id="exec-shared",
                    intent_id=intent.intent_id,
                    target=intent.target.to_object(),
                    payload=intent.to_payload(),
                )
                execution = client.send(
                    build_request(
                        intent,
                        request_id="exec-shared",
                        session_id="p-shared",
                        expected_context_revision=1,
                        domain={"capability": "parking.move", "round": 1},
                    )
                )
                assert execution.ok is True
                assert execution.context_revision == 2
                assert execution.turn == 2
                assert execution.task_id and execution.workflow_id
                assert execution.context_before["phase"] == "planning"
                assert execution.context_after["phase"] == "execution"
                assert execution.context_after["status"] == "completed"
                assert execution.context_after["real_carla_execution"] is True
                history = execution.context_after["history"]
                assert [entry["kind"] for entry in history] == [
                    "planning",
                    "execution",
                ]
                assert len(carla_state.calls) == 1

                got = _control(
                    client, "ctl-shared-get", "session.get",
                    {"session_id": "p-shared"},
                )
                info = json.loads(got.output)
                assert got.context_revision == 2
                assert info["workflow_count"] == 1
                assert info["task_count"] == 1
    finally:
        carla_bridge.close()
