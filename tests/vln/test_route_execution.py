"""NAV-19 unit tests: selected route -> AgentIntent -> execution boundaries.

The injected-host success case is explicitly a mock of the host boundary, not
evidence of real Agent-Kernel execution. Real Host integration is covered by
tests/integration/test_nav19_host_execution.py when VLN_KERNEL_HOST_EXE is set.
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from vln.intent import AgentIntent
from vln.ipc.envelope import Response
from vln.ipc.errors import UncertainOutcomeError
from vln.nav import RouteIntentMappingError, VehiclePose
from vln.nav.offline_e2e import (
    DEMO_AS_OF,
    DEMO_POSE,
    OfflineEndToEndStatus,
    demo_cases,
    run_offline_decision,
)
from vln.nav.route_execution import (
    RouteExecutionStatus,
    execute_selected_route,
    map_selected_route_to_agent_intent,
)


def _case(name: str):
    return next(item for item in demo_cases() if item.name == name)


def _plan(name: str):
    case = _case(name)
    return (
        case.scene,
        run_offline_decision(
            case.scene, case.decision_input, pose=DEMO_POSE, as_of=DEMO_AS_OF
        ),
    )


class _FakeHostClient:
    """A host-boundary double; never represents real Kernel execution."""

    def __init__(self, *, response: Response | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.requests = []

    def __enter__(self) -> "_FakeHostClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def send(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _factory(host: _FakeHostClient):
    calls: list[_FakeHostClient] = []

    def make() -> _FakeHostClient:
        calls.append(host)
        return host

    return make, calls


def _success_response(mapping, request_id: str = "req-test") -> Response:
    output = {
        "output_version": "1",
        "status": "stub_completed",
        "execution_mode": "simulation",
        "action": mapping.intent.action,
        "intent_id": mapping.intent.intent_id,
        "target": mapping.intent.target.to_object(),
    }
    return Response(
        request_id=request_id,
        host_kind="kernel",
        accepted=True,
        submission_status="completed",
        observation_status="success",
        execution_status="completed",
        output=json.dumps(output),
        error=None,
    )


def _failure_response(request_id: str = "req-test") -> Response:
    return Response(
        request_id=request_id,
        host_kind="kernel",
        accepted=True,
        submission_status="failed",
        observation_status="failure",
        execution_status=None,
        output=None,
        error={"code": "capability-not-found", "message": "no such capability"},
    )


class _BrokenFeedbackEncoder:
    def encode(self, observation: object) -> Any:
        raise RuntimeError("feedback encoder exploded")


# ----------------------------------------------------------------------
# Route -> AgentIntent mapping
# ----------------------------------------------------------------------


def test_left_mapping_uses_the_selected_route_next_node() -> None:
    scene, plan = _plan("left")
    assert plan.status == OfflineEndToEndStatus.SELECTED

    mapping = map_selected_route_to_agent_intent(
        scene, plan, pose=DEMO_POSE, intent_id="nav19-intent-left"
    )

    assert mapping.candidate_id == "cand-NAV18-DIRECTION-02"
    assert mapping.candidate_id == plan.selected_candidate_id
    assert mapping.route_key == "S>B>M>T"
    assert mapping.next_node_id == "B"
    assert mapping.target.x == 0.0
    assert mapping.target.y == 10.0
    assert mapping.target.heading == pytest.approx(math.pi / 2.0)
    assert mapping.turn_delta_rad == pytest.approx(math.pi / 2.0)
    assert mapping.navigation_direction == "LEFT"
    assert mapping.coordinate_frame == "synthetic-topology-local"
    assert mapping.source == "synthetic-simulation"

    # The generated intent is the authoritative v1 object and round-trips.
    assert AgentIntent.from_payload(mapping.intent.to_payload()).to_object() == (
        mapping.intent.to_object()
    )


def test_straight_mapping_uses_the_selected_route_next_node() -> None:
    scene, plan = _plan("straight")
    mapping = map_selected_route_to_agent_intent(
        scene, plan, pose=DEMO_POSE, intent_id="nav19-intent-straight"
    )

    assert mapping.candidate_id == "cand-NAV18-DIRECTION-01"
    assert mapping.route_key == "S>A>A2>M>T"
    assert mapping.next_node_id == "A"
    assert mapping.target.x == 5.0
    assert mapping.target.y == 0.0
    assert mapping.target.heading == 0.0


def test_explicit_pose_position_changes_the_target_heading() -> None:
    scene, plan = _plan("left")
    pose = VehiclePose(x=5.0, y=0.0, heading=0.5)
    mapping = map_selected_route_to_agent_intent(
        scene, plan, pose=pose, intent_id="nav19-intent-pose"
    )

    expected = math.atan2(10.0 - 0.0, 0.0 - 5.0)  # bearing to B=(0,10)
    assert mapping.target.heading == pytest.approx(expected)
    assert mapping.turn_delta_rad == pytest.approx(
        (expected - pose.heading + math.pi) % (2.0 * math.pi) - math.pi
    )


def test_target_uses_topology_coordinates_not_the_node_id() -> None:
    scene, plan = _plan("left")
    mapping = map_selected_route_to_agent_intent(
        scene, plan, pose=DEMO_POSE, intent_id="nav19-intent-coords"
    )
    assert mapping.next_node_id == "B"
    assert isinstance(mapping.target.x, float)
    assert isinstance(mapping.target.y, float)
    assert mapping.target.x != mapping.next_node_id
    assert mapping.target.y != mapping.next_node_id


def test_mapping_fails_when_planning_did_not_select_a_route() -> None:
    scene, plan = _plan("conflict")
    assert plan.status == OfflineEndToEndStatus.CONSTRAINT_CONFLICT
    with pytest.raises(RouteIntentMappingError):
        map_selected_route_to_agent_intent(
            scene, plan, pose=DEMO_POSE, intent_id="nav19-intent-none"
        )


def test_mapping_fails_when_pose_coincides_with_the_next_node() -> None:
    scene, plan = _plan("left")
    # Next node for LEFT is B=(0,10); zero distance means no finite heading.
    with pytest.raises(RouteIntentMappingError, match="coincides"):
        map_selected_route_to_agent_intent(
            scene,
            plan,
            pose=VehiclePose(0.0, 10.0, 0.0),
            intent_id="nav19-intent-zero",
        )


# ----------------------------------------------------------------------
# Fail-closed boundaries: no host call
# ----------------------------------------------------------------------


def test_planning_failure_does_not_call_the_host() -> None:
    scene, plan = _plan("conflict")
    host = _FakeHostClient(response=_failure_response())
    factory, calls = _factory(host)

    result = execute_selected_route(
        scene,
        plan,
        pose=DEMO_POSE,
        intent_id="nav19-intent-planning-fail",
        request_id="req-planning-fail",
        host_client_factory=factory,
    )

    assert result.status == RouteExecutionStatus.PLANNING_FAILED
    assert result.ok is False
    assert result.mapping is None
    assert result.intent is None
    assert result.request is None
    assert result.response is None
    assert result.host_called is False
    assert result.feedback_text is None
    assert calls == []
    assert result.stages["intent_mapping"] is False


def test_invalid_decision_does_not_call_the_host() -> None:
    scene, plan = _plan("invalid")
    assert plan.status == OfflineEndToEndStatus.DECISION_INVALID
    host = _FakeHostClient(response=_failure_response())
    factory, calls = _factory(host)

    result = execute_selected_route(
        scene,
        plan,
        pose=DEMO_POSE,
        intent_id="nav19-intent-invalid-decision",
        request_id="req-invalid-decision",
        host_client_factory=factory,
    )

    assert result.status == RouteExecutionStatus.PLANNING_FAILED
    assert result.ok is False
    assert result.mapping is None
    assert result.request is None
    assert result.response is None
    assert result.host_called is False
    assert calls == []


def test_mapping_failure_does_not_call_the_host() -> None:
    scene, plan = _plan("left")
    host = _FakeHostClient(response=_failure_response())
    factory, calls = _factory(host)

    result = execute_selected_route(
        scene,
        plan,
        pose=VehiclePose(0.0, 10.0, 0.0),  # coincides with next node B
        intent_id="nav19-intent-mapping-fail",
        request_id="req-mapping-fail",
        host_client_factory=factory,
    )

    assert result.status == RouteExecutionStatus.MAPPING_FAILED
    assert result.ok is False
    assert result.mapping is None
    assert result.request is None
    assert result.host_called is False
    assert result.error_type == "RouteIntentMappingError"
    assert calls == []


def test_request_failure_does_not_call_the_host() -> None:
    scene, plan = _plan("left")
    host = _FakeHostClient(response=_failure_response())
    factory, calls = _factory(host)

    def broken_builder(intent, *, request_id: str):
        raise TypeError("request builder refused the intent")

    result = execute_selected_route(
        scene,
        plan,
        pose=DEMO_POSE,
        intent_id="nav19-intent-request-fail",
        request_id="req-request-fail",
        host_client_factory=factory,
        request_builder=broken_builder,
    )

    assert result.status == RouteExecutionStatus.REQUEST_FAILED
    assert result.ok is False
    assert result.mapping is not None
    assert result.request is None
    assert result.host_called is False
    assert result.error_type == "TypeError"
    assert calls == []


def test_host_unavailable_is_explicit_and_does_not_claim_execution() -> None:
    scene, plan = _plan("left")
    calls: list[int] = []

    def factory():
        calls.append(1)
        raise FileNotFoundError("kernel_host not found")

    result = execute_selected_route(
        scene,
        plan,
        pose=DEMO_POSE,
        intent_id="nav19-intent-host-missing",
        request_id="req-host-missing",
        host_client_factory=factory,
    )

    assert result.status == RouteExecutionStatus.HOST_UNAVAILABLE
    assert result.ok is False
    assert result.host_called is False
    assert result.request is not None
    assert result.response is None
    assert result.error_type == "FileNotFoundError"
    assert calls == [1]


def test_uncertain_host_outcome_is_not_success_and_is_not_retried() -> None:
    scene, plan = _plan("left")
    mapping = map_selected_route_to_agent_intent(
        scene, plan, pose=DEMO_POSE, intent_id="nav19-intent-uncertain"
    )
    host = _FakeHostClient(error=UncertainOutcomeError("request may have executed"))
    factory, calls = _factory(host)

    result = execute_selected_route(
        scene,
        plan,
        pose=DEMO_POSE,
        intent_id="nav19-intent-uncertain",
        request_id="req-uncertain",
        host_client_factory=factory,
    )

    assert result.status == RouteExecutionStatus.EXECUTION_UNCERTAIN
    assert result.ok is False
    assert result.host_called is True
    assert result.request is not None
    assert result.response is None
    assert result.feedback_text is None
    assert result.error_type == "UncertainOutcomeError"
    assert len(host.requests) == 1  # no retry
    assert calls == [host]
    assert result.mapping is not None
    assert result.mapping.route_key == mapping.route_key


# ----------------------------------------------------------------------
# Host response handling (injected host boundary)
# ----------------------------------------------------------------------


def test_injected_success_is_classified_and_feedback_is_encoded() -> None:
    scene, plan = _plan("left")
    mapping = map_selected_route_to_agent_intent(
        scene, plan, pose=DEMO_POSE, intent_id="nav19-intent-mock-success"
    )
    host = _FakeHostClient(
        response=_success_response(mapping, request_id="req-mock-success")
    )
    factory, calls = _factory(host)

    result = execute_selected_route(
        scene,
        plan,
        pose=DEMO_POSE,
        intent_id="nav19-intent-mock-success",
        request_id="req-mock-success",
        host_client_factory=factory,
    )

    assert result.status == RouteExecutionStatus.SIMULATED_COMPLETED
    assert result.ok is True
    assert result.host_called is True
    assert result.response is not None
    assert result.response.request_id == "req-mock-success"
    assert result.outcome == "software-succeeded"
    assert result.stub_execution_mode == "simulation"
    assert result.physical_arrival == "unknown"
    assert result.feedback_text is not None
    assert result.feedback_error is None
    assert calls == [host]
    assert len(host.requests) == 1

    feedback = json.loads(result.feedback_text)
    assert feedback["request_id"] == "req-mock-success"
    assert feedback["host_kind"] == "kernel"
    assert feedback["ok"] is True
    assert feedback["output"] == result.response.output
    assert feedback["truncated"] == {}

    stages = result.stages
    assert stages["intent_mapping"] is True
    assert stages["request_built"] is True
    assert stages["host_called"] is True
    assert stages["stub_simulated_completed"] is True
    assert stages["feedback_encoded"] is True
    assert stages["physical_arrival"] == "unknown"


def test_failed_response_is_not_success_but_feedback_is_still_encoded() -> None:
    scene, plan = _plan("left")
    host = _FakeHostClient(response=_failure_response("req-failed"))
    factory, calls = _factory(host)

    result = execute_selected_route(
        scene,
        plan,
        pose=DEMO_POSE,
        intent_id="nav19-intent-failed-response",
        request_id="req-failed",
        host_client_factory=factory,
    )

    assert result.status == RouteExecutionStatus.EXECUTION_FAILED
    assert result.ok is False
    assert result.host_called is True
    assert result.response is not None
    assert result.outcome == "failed-before-execution"
    assert result.response.error is not None
    assert result.response.error["code"] == "capability-not-found"
    assert result.feedback_text is not None
    assert result.feedback_error is None
    assert calls == [host]


def test_feedback_encoding_failure_is_explicit_and_not_full_success() -> None:
    scene, plan = _plan("left")
    mapping = map_selected_route_to_agent_intent(
        scene, plan, pose=DEMO_POSE, intent_id="nav19-intent-feedback-fail"
    )
    host = _FakeHostClient(
        response=_success_response(mapping, request_id="req-feedback-fail")
    )
    factory, _ = _factory(host)

    result = execute_selected_route(
        scene,
        plan,
        pose=DEMO_POSE,
        intent_id="nav19-intent-feedback-fail",
        request_id="req-feedback-fail",
        host_client_factory=factory,
        feedback_encoder=_BrokenFeedbackEncoder(),
    )

    assert result.status == RouteExecutionStatus.SIMULATED_COMPLETED
    assert result.ok is False  # feedback failure prevents a full-loop claim
    assert result.feedback_text is None
    assert result.feedback_error is not None
    assert "RuntimeError" in result.feedback_error
    assert result.stages["stub_simulated_completed"] is True
    assert result.stages["feedback_encoded"] is False


def test_success_response_with_wrong_stub_target_is_uncertain() -> None:
    scene, plan = _plan("left")
    mapping = map_selected_route_to_agent_intent(
        scene, plan, pose=DEMO_POSE, intent_id="nav19-intent-bad-stub"
    )
    response = _success_response(mapping, request_id="req-bad-stub")
    output = json.loads(response.output or "{}")
    output["target"] = {"x": 999.0, "y": 999.0, "heading": 0.0}
    response = Response(
        request_id=response.request_id,
        host_kind=response.host_kind,
        accepted=response.accepted,
        submission_status=response.submission_status,
        observation_status=response.observation_status,
        execution_status=response.execution_status,
        output=json.dumps(output),
        error=None,
    )
    host = _FakeHostClient(response=response)
    factory, _ = _factory(host)

    result = execute_selected_route(
        scene,
        plan,
        pose=DEMO_POSE,
        intent_id="nav19-intent-bad-stub",
        request_id="req-bad-stub",
        host_client_factory=factory,
    )

    assert result.status == RouteExecutionStatus.EXECUTION_UNCERTAIN
    assert result.ok is False
    assert "does not match" in result.reason
    assert result.feedback_text is not None  # real response still transcribed
