"""NAV-19 real Host/Agent-Kernel integration tests.

Requires ``VLN_KERNEL_HOST_EXE`` pointing at an existing compiled kernel_host.
These tests never rebuild the host, never call a model and never execute a real
vehicle. The ``parking.move`` capability is a simulation stub.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from vln.client import HostClient
from vln.ipc.envelope import (
    HostKind,
    ObservationStatus,
    Request,
    SubmissionStatus,
)
from vln.nav.offline_e2e import (
    DEMO_AS_OF,
    DEMO_POSE,
    demo_cases,
    run_offline_decision,
)
from vln.nav.route_execution import (
    RouteExecutionStatus,
    execute_selected_route,
)

pytestmark = pytest.mark.integration

_EXE_ENV = "VLN_KERNEL_HOST_EXE"


def _host_exe() -> str:
    exe = os.environ.get(_EXE_ENV)
    if not exe:
        pytest.skip(f"{_EXE_ENV} is not set")
    path = Path(exe)
    if not path.is_file():
        pytest.skip(f"{_EXE_ENV} points to a missing file: {exe}")
    return str(path)


def _straight_plan():
    case = next(item for item in demo_cases() if item.name == "straight")
    plan = run_offline_decision(
        case.scene, case.decision_input, pose=DEMO_POSE, as_of=DEMO_AS_OF
    )
    assert plan.status == "selected"
    return case.scene, plan


def test_real_kernel_host_executes_planned_route_and_returns_feedback() -> None:
    exe = _host_exe()
    scene, plan = _straight_plan()

    result = execute_selected_route(
        scene,
        plan,
        pose=DEMO_POSE,
        intent_id="nav19-real-intent-straight",
        request_id="nav19-real-req-straight",
        host_client_factory=lambda: HostClient([exe]),
    )

    assert result.status == RouteExecutionStatus.SIMULATED_COMPLETED
    assert result.ok is True
    assert result.host_called is True
    assert result.physical_arrival == "unknown"

    # The target is the selected route's next topology node, not a node-id.
    assert result.mapping is not None
    assert result.mapping.candidate_id == "cand-NAV18-DIRECTION-01"
    assert result.mapping.route_key == "S>A>A2>M>T"
    assert result.mapping.next_node_id == "A"
    assert result.mapping.target.x == 5.0
    assert result.mapping.target.y == 0.0
    assert result.mapping.target.heading == 0.0
    assert result.intent is not None
    assert result.intent.intent_id == "nav19-real-intent-straight"

    # The request/reply are the real IPC and Kernel objects.
    assert result.request is not None
    assert result.request.request_id == "nav19-real-req-straight"
    assert result.request.capability_id == "parking.move"
    assert result.response is not None
    assert result.response.request_id == "nav19-real-req-straight"
    assert result.response.host_kind == HostKind.KERNEL
    assert result.response.accepted is True
    assert result.response.submission_status == SubmissionStatus.COMPLETED
    assert result.response.observation_status == ObservationStatus.SUCCESS
    assert result.response.execution_status == "completed"
    assert result.response.ok is True
    assert result.response.error is None

    # The parking.move stub output is simulation-only and echoed the intent.
    assert result.stub_output is not None
    assert result.stub_output["status"] == "stub_completed"
    assert result.stub_output["execution_mode"] == "simulation"
    assert result.stub_output["action"] == "parking.move"
    assert result.stub_output["intent_id"] == "nav19-real-intent-straight"
    assert result.stub_output["target"] == {
        "x": 5.0,
        "y": 0.0,
        "heading": 0.0,
    }
    assert result.stub_execution_mode == "simulation"
    assert not any(
        key in result.stub_output
        for key in ("arrived", "parked", "pose", "physical_arrival")
    )

    # The real Response is transcribed by the existing feedback encoder.
    assert result.feedback_text is not None
    feedback = json.loads(result.feedback_text)
    assert feedback["request_id"] == "nav19-real-req-straight"
    assert feedback["host_kind"] == "kernel"
    assert feedback["ok"] is True
    assert feedback["truncated"] == {}
    assert feedback["output"] == result.response.output
    assert json.loads(feedback["output"])["status"] == "stub_completed"

    stages = result.stages
    assert stages == {
        "nav18_planning_status": "selected",
        "intent_mapping": True,
        "request_built": True,
        "host_called": True,
        "host_response_received": True,
        "host_response_ok": True,
        "stub_simulated_completed": True,
        "feedback_encoded": True,
        "physical_arrival": "unknown",
    }


def test_real_kernel_host_rejection_is_not_reported_as_success() -> None:
    exe = _host_exe()
    scene, plan = _straight_plan()

    def unregistered_capability(intent, *, request_id: str) -> Request:
        return Request(
            request_id=request_id,
            capability_id="parking.stop",
            payload=intent.to_payload(),
        )

    result = execute_selected_route(
        scene,
        plan,
        pose=DEMO_POSE,
        intent_id="nav19-real-intent-failure",
        request_id="nav19-real-req-failure",
        host_client_factory=lambda: HostClient([exe]),
        request_builder=unregistered_capability,
    )

    assert result.status == RouteExecutionStatus.EXECUTION_FAILED
    assert result.ok is False
    assert result.host_called is True
    assert result.response is not None
    assert result.response.host_kind == HostKind.KERNEL
    assert result.response.accepted is True
    assert result.response.submission_status == SubmissionStatus.FAILED
    assert result.response.observation_status == ObservationStatus.FAILURE
    assert result.response.error is not None
    assert result.response.error["code"] == "capability-not-found"
    assert result.feedback_text is not None
    assert json.loads(result.feedback_text)["ok"] is False
    assert result.physical_arrival == "unknown"
