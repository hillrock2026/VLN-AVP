"""NAV-10 offline unit tests: the orchestration and its fail-closed boundary.

The model and the host are both test doubles here. This file proves *ordering,
validation and correlation* only: it is not evidence that a real model
produced the judgement, that a real host ran, or that a vehicle moved. The
real Host path lives in ``tests/integration/test_vln_nav_10.py``; the real
model path is gated there too.
"""

from __future__ import annotations

import inspect
import json
import math

import pytest

from vln.client import build_request
from vln.intent import AgentIntent, AgentIntentValidationError
from vln.ipc import envelope
from vln.ipc.envelope import HostKind, Request, Response
from vln.ipc.errors import HostTerminatedError
from vln.nav import (
    EvidenceInsufficientError,
    NavigationMappingError,
    TargetIdentityMismatchError,
    TargetNotVisibleError,
    VehiclePose,
    VisualDecisionParseError,
    VisualDecisionValidationError,
    parse_visual_decision,
    to_agent_intent,
    verify_visual_decision,
)
from vln.nav_execution import (
    NavigationExecutionError,
    run_visual_parking_intent,
)
from vln.vlm import MockModelClient, ModelCallError

#: The pose is supplied explicitly by the caller. This project has no
#: localisation, odometry or simulator, so the value below is a SIMULATED/TEST
#: carrier for the heading delta - not a measured vehicle position.
SIMULATED_TEST_POSE = VehiclePose(x=12.5, y=-4.0, heading=0.25)

_BLOCK_TEMPLATE = (
    "第五步 输出结论块：\n"
    "Target: {target}\n"
    "Identified as: {identified}\n"
    "Visible: {visible}\n"
    "Relative position: {position}\n"
    "Next direction: {direction}\n"
    "Evidence: {evidence}\n"
)


def _block(
    *,
    target: str = "D50",
    identified: str = "D50",
    visible: str = "是",
    position: str = "LEFT",
    direction: str = "LEFT",
    evidence: str = "地面白色编号 D50",
) -> str:
    return _BLOCK_TEMPLATE.format(
        target=target,
        identified=identified,
        visible=visible,
        position=position,
        direction=direction,
        evidence=evidence,
    )


# ----------------------------------------------------------------------
# Test doubles (explicitly not a host and not evidence of execution)
# ----------------------------------------------------------------------


class _FakeHost:
    """An offline ``HostClient`` stand-in; counts calls and returns a Response."""

    def __init__(self, responder=None) -> None:
        self.builds = 0
        self.sends = 0
        self.requests: list[Request] = []
        self.responses: list[Response] = []
        self._responder = responder

    def factory(self) -> "_FakeHost":
        self.builds += 1
        return self

    def __enter__(self) -> "_FakeHost":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def send(self, request: Request) -> Response:
        self.sends += 1
        self.requests.append(request)
        if self._responder is not None:
            response = self._responder(request)
        else:
            response = _success_response(request)
        self.responses.append(response)
        return response


class _UntouchedHost:
    """A factory that fails loudly if the orchestrator ever constructs a host."""

    def __init__(self) -> None:
        self.builds = 0

    def factory(self):
        self.builds += 1
        raise AssertionError("the host client must not be constructed")


class _CountingBuilder:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.intents: list[AgentIntent] = []
        self._error = error

    def __call__(self, intent: AgentIntent, *, request_id: str) -> Request:
        self.calls += 1
        self.intents.append(intent)
        if self._error is not None:
            raise self._error
        return build_request(intent, request_id=request_id)


def _stub_output(request: Request) -> dict:
    intent = json.loads(request.payload)
    return {
        "output_version": "1",
        "status": "stub_completed",
        "execution_mode": "simulation",
        "action": "parking.move",
        "intent_id": intent["intent_id"],
        "target": intent["target"],
    }


def _success_response(
    request: Request,
    *,
    response_request_id: str | None = None,
    host_kind: str = HostKind.KERNEL,
    output: str | None = None,
) -> Response:
    if output is None:
        output = json.dumps(_stub_output(request))
    obj = envelope.build_response(
        request_id=response_request_id
        if response_request_id is not None
        else request.request_id,
        accepted=True,
        submission_status=envelope.SubmissionStatus.COMPLETED,
        observation_status=envelope.ObservationStatus.SUCCESS,
        execution_status="completed",
        output=output,
        host_kind=host_kind,
    )
    return envelope.parse_response_line(json.dumps(obj))


def _rejected_response(request: Request) -> Response:
    obj = envelope.build_response(
        request_id=request.request_id,
        accepted=False,
        submission_status=envelope.SubmissionStatus.REJECTED,
        observation_status=envelope.ObservationStatus.FAILURE,
        execution_status=None,
        output=None,
        error={"code": envelope.ErrorCode.CAPABILITY_NOT_FOUND, "message": "no"},
        host_kind=HostKind.KERNEL,
    )
    return envelope.parse_response_line(json.dumps(obj))


def _run(
    *,
    model,
    host,
    builder=None,
    expected_identity: str = "D50",
    pose=SIMULATED_TEST_POSE,
    intent_id: str = "nav10-intent-1",
    request_id: str = "nav10-req-1",
    instruction: str = "park at D50",
    observation: object = "a parking-lot frame",
):
    return run_visual_parking_intent(
        model=model,
        observation=observation,
        instruction=instruction,
        expected_identity=expected_identity,
        pose=pose,
        intent_id=intent_id,
        request_id=request_id,
        host_client_factory=host.factory,
        request_builder=build_request if builder is None else builder,
    )


def _expected_intent(raw: str, *, intent_id: str = "nav10-intent-1") -> AgentIntent:
    """The NAV-09 chain's own result, computed independently in the test."""

    decision = parse_visual_decision(raw)
    directive = verify_visual_decision(decision, expected_identity="D50")
    return to_agent_intent(directive, pose=SIMULATED_TEST_POSE, intent_id=intent_id)


# ----------------------------------------------------------------------
# A. Normal decision and execution
# ----------------------------------------------------------------------


def test_the_nav09_intent_is_what_the_request_builder_receives() -> None:
    raw = _block()
    host = _FakeHost()
    builder = _CountingBuilder()

    result = _run(model=MockModelClient(raw), host=host, builder=builder)

    expected = _expected_intent(raw)
    assert builder.calls == 1
    assert builder.intents == [expected]
    assert result.intent == expected
    # The request carries exactly that validated intent, on the existing route.
    assert result.request is host.requests[0]
    assert result.request.request_id == "nav10-req-1"
    assert result.request.capability_id == expected.action == "parking.move"
    assert result.request.payload == expected.to_payload()
    assert host.builds == 1
    assert host.sends == 1


def test_the_intermediate_layers_are_the_nav09_objects() -> None:
    raw = _block()
    result = _run(model=MockModelClient(raw), host=_FakeHost())

    assert result.raw_model_output == raw
    assert result.decision == parse_visual_decision(raw)
    assert result.directive == verify_visual_decision(
        result.decision, expected_identity="D50"
    )


def test_success_records_the_real_response_and_both_correlations() -> None:
    host = _FakeHost()
    result = _run(model=MockModelClient(_block()), host=host)

    assert result.response is host.responses[0]
    assert result.response.request_id == result.request.request_id == "nav10-req-1"
    assert result.response.host_kind == HostKind.KERNEL
    assert result.response.ok is True
    assert result.ok is True

    assert result.stub_output is not None
    assert set(result.stub_output) == {
        "output_version",
        "status",
        "execution_mode",
        "action",
        "intent_id",
        "target",
    }
    assert result.stub_output["status"] == "stub_completed"
    assert result.stub_output["execution_mode"] == "simulation"
    assert result.stub_output["intent_id"] == result.intent.intent_id
    assert result.stub_output["target"] == result.intent.target.to_object()


@pytest.mark.parametrize(
    "position,direction,delta",
    [
        ("LEFT", "LEFT", math.pi / 2.0),
        ("RIGHT", "RIGHT", -math.pi / 2.0),
        ("AHEAD", "STRAIGHT", 0.0),
    ],
)
def test_the_existing_heading_mapping_is_what_is_submitted(
    position: str, direction: str, delta: float
) -> None:
    result = _run(
        model=MockModelClient(_block(position=position, direction=direction)),
        host=_FakeHost(),
    )

    assert result.intent.target.x == SIMULATED_TEST_POSE.x
    assert result.intent.target.y == SIMULATED_TEST_POSE.y
    expected_heading = ((SIMULATED_TEST_POSE.heading + delta + math.pi) % (2 * math.pi)) - math.pi
    assert result.intent.target.heading == pytest.approx(expected_heading)


def test_pose_has_no_hidden_default() -> None:
    parameters = inspect.signature(run_visual_parking_intent).parameters
    assert parameters["pose"].default is inspect.Parameter.empty
    assert parameters["expected_identity"].default is inspect.Parameter.empty


# ----------------------------------------------------------------------
# B/C. Judgement refusals never build or execute
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,error",
    [
        ("", VisualDecisionParseError),
        ("I could not decide.", VisualDecisionParseError),
        (_block().replace("Next direction: LEFT\n", ""), VisualDecisionParseError),
        (_block() + _block(), VisualDecisionParseError),
        (_block(visible="否", position="无法确定", direction="无法确定"), TargetNotVisibleError),
        (_block(identified="050"), TargetIdentityMismatchError),
        (_block(identified="D50ABC"), TargetIdentityMismatchError),
        (_block(target="D66"), TargetIdentityMismatchError),
        (_block(identified="无法确定"), TargetIdentityMismatchError),
        (_block(evidence="无法确定"), EvidenceInsufficientError),
        (_block(evidence="证据不足，无法确定"), EvidenceInsufficientError),
        (_block(direction="无法确定"), VisualDecisionValidationError),
        (_block(position="右侧", direction="RIGHT"), VisualDecisionValidationError),
        (_block(position="AHEAD", direction="RIGHT"), VisualDecisionValidationError),
        (_block(visible="no", position="无法确定", direction="无法确定"),
         VisualDecisionValidationError),
    ],
)
def test_a_bad_judgement_never_reaches_the_builder_or_host(raw: str, error: type) -> None:
    host = _UntouchedHost()
    builder = _CountingBuilder()

    with pytest.raises(error):
        _run(model=MockModelClient(raw), host=host, builder=builder)

    assert builder.calls == 0
    assert host.builds == 0


def test_a_zone_label_prefix_is_not_accepted_as_the_requested_zone() -> None:
    """Zone ``A`` must not be authorised by a read of ``AB``.

    This is the host-boundary version of the identity whole-token rule: if the
    model reports a longer alphanumeric label, the refusal happens before the
    request builder and before any host client exists.
    """

    host = _UntouchedHost()
    builder = _CountingBuilder()
    raw = _block(
        target="A", identified="AB", position="LEFT", direction="LEFT"
    )

    with pytest.raises(TargetIdentityMismatchError):
        _run(
            model=MockModelClient(raw),
            host=host,
            builder=builder,
            expected_identity="A",
        )

    assert builder.calls == 0
    assert host.builds == 0


def test_evidence_insufficiency_is_refused_before_execution() -> None:
    """An explicit 'cannot determine' Evidence value cannot reach the Host."""

    host = _UntouchedHost()
    builder = _CountingBuilder()

    with pytest.raises(EvidenceInsufficientError):
        _run(
            model=MockModelClient(_block(evidence="证据不足，无法确定")),
            host=host,
            builder=builder,
        )

    assert builder.calls == 0
    assert host.builds == 0


def test_an_identity_mismatch_is_refused_before_execution() -> None:
    host = _UntouchedHost()
    builder = _CountingBuilder()

    with pytest.raises(TargetIdentityMismatchError):
        _run(
            model=MockModelClient(
                _block(target="316", identified="316", position="RIGHT", direction="RIGHT")
            ),
            host=host,
            builder=builder,
            expected_identity="283",
        )

    assert builder.calls == 0
    assert host.builds == 0


def test_a_model_failure_is_never_converted_into_a_judgement() -> None:
    host = _UntouchedHost()

    class _FailingModel:
        def generate(self, observation: object, instruction: str) -> str:
            raise ModelCallError("the service refused the request")

    with pytest.raises(ModelCallError):
        _run(model=_FailingModel(), host=host)

    assert host.builds == 0


def test_an_arbitrary_model_exception_is_wrapped_and_still_not_executed() -> None:
    host = _UntouchedHost()

    class _ExplodingModel:
        def generate(self, observation: object, instruction: str) -> str:
            raise RuntimeError("boom")

    with pytest.raises(ModelCallError, match="model client failed"):
        _run(model=_ExplodingModel(), host=host)

    assert host.builds == 0


# ----------------------------------------------------------------------
# D. Mapping and request-building failures
# ----------------------------------------------------------------------


def test_a_missing_pose_is_refused_before_execution() -> None:
    host = _UntouchedHost()
    builder = _CountingBuilder()

    with pytest.raises(NavigationMappingError):
        _run(model=MockModelClient(_block()), host=host, builder=builder, pose=None)

    assert builder.calls == 0
    assert host.builds == 0


def test_a_non_finite_pose_is_refused_by_the_nav09_type() -> None:
    with pytest.raises(NavigationMappingError):
        VehiclePose(x=float("nan"), y=0.0, heading=0.0)


def test_an_invalid_intent_id_surfaces_as_the_v1_error_before_execution() -> None:
    host = _UntouchedHost()
    builder = _CountingBuilder()

    with pytest.raises(AgentIntentValidationError):
        _run(model=MockModelClient(_block()), host=host, builder=builder, intent_id="   ")

    assert builder.calls == 0
    assert host.builds == 0


def test_a_request_builder_failure_propagates_and_starts_no_host() -> None:
    host = _UntouchedHost()
    error = RuntimeError("builder exploded")
    builder = _CountingBuilder(error=error)

    with pytest.raises(RuntimeError) as raised:
        _run(model=MockModelClient(_block()), host=host, builder=builder)

    assert raised.value is error
    assert builder.calls == 1
    assert host.builds == 0


# ----------------------------------------------------------------------
# E. Host / Kernel failures
# ----------------------------------------------------------------------


def test_a_transport_failure_propagates_without_retry_or_fake_success() -> None:
    def _terminate(request: Request) -> Response:
        raise HostTerminatedError("host terminated before responding")

    host = _FakeHost(_terminate)

    with pytest.raises(HostTerminatedError):
        _run(model=MockModelClient(_block()), host=host)

    assert host.builds == 1
    assert host.sends == 1  # one attempt, no transparent retry


def test_an_unavailable_host_propagates_as_a_failure() -> None:
    class _UnavailableHost:
        def factory(self):
            raise OSError("host executable is not available")

    with pytest.raises(OSError):
        _run(model=MockModelClient(_block()), host=_UnavailableHost())


def test_a_rejected_response_is_returned_as_failure_not_success() -> None:
    result = _run(model=MockModelClient(_block()), host=_FakeHost(_rejected_response))

    assert result.ok is False
    assert result.stub_output is None
    assert result.response.ok is False
    assert result.response.request_id == result.request.request_id
    assert result.response.error is not None
    assert result.response.error["code"] == envelope.ErrorCode.CAPABILITY_NOT_FOUND


# ----------------------------------------------------------------------
# F. Response structure and correlation
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "responder,message",
    [
        (
            lambda request: _success_response(
                request, response_request_id="a-different-request"
            ),
            "request_id does not match",
        ),
        (
            lambda request: _success_response(request, host_kind=HostKind.STUB),
            "not the Agent-Kernel host",
        ),
        (
            lambda request: _success_response(request, output="{not json"),
            "not valid JSON",
        ),
        (
            lambda request: _success_response(
                request,
                output=json.dumps(
                    {
                        key: value
                        for key, value in _stub_output(request).items()
                        if key != "execution_mode"
                    }
                ),
            ),
            "unexpected field set",
        ),
        (
            lambda request: _success_response(
                request,
                output=json.dumps({**_stub_output(request), "intent_id": "someone-else"}),
            ),
            "intent_id does not match",
        ),
        (
            lambda request: _success_response(
                request,
                output=json.dumps(
                    {**_stub_output(request), "target": {"x": 0.0, "y": 0.0, "heading": 0.0}}
                ),
            ),
            "target does not match",
        ),
        (
            lambda request: _success_response(
                request,
                output=json.dumps({**_stub_output(request), "status": "completed"}),
            ),
            "status must be",
        ),
        (
            lambda request: _success_response(
                request,
                output=json.dumps(
                    {**_stub_output(request), "action": "parking.stop"}
                ),
            ),
            "action does not match",
        ),
    ],
)
def test_an_untrustworthy_success_response_is_refused(responder, message: str) -> None:
    with pytest.raises(NavigationExecutionError, match=message) as raised:
        _run(model=MockModelClient(_block()), host=_FakeHost(responder))

    assert raised.value.request is not None
    assert raised.value.response is not None
    assert raised.value.response.ok is True


def test_a_success_response_without_output_is_refused() -> None:
    def _no_output(request: Request) -> Response:
        obj = envelope.build_response(
            request_id=request.request_id,
            accepted=True,
            submission_status=envelope.SubmissionStatus.COMPLETED,
            observation_status=envelope.ObservationStatus.SUCCESS,
            execution_status="completed",
            output=None,
            host_kind=HostKind.KERNEL,
        )
        return envelope.parse_response_line(json.dumps(obj))

    with pytest.raises(NavigationExecutionError, match="no parking.move output"):
        _run(model=MockModelClient(_block()), host=_FakeHost(_no_output))
