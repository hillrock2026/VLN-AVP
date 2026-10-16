"""Tests for the orchestration seam (:mod:`vln.pipeline`).

These are pure Python unit tests with a fake host client and spy
builder/factory, so the exact call order and call counts are observable. The
parser under test is the REAL :func:`vln.intent.parse_model_output`; only the
model and the host are fakes. No host process and no real model are used here.
"""

from __future__ import annotations

import json

import pytest

from vln.client import build_request
from vln.intent import (
    AgentIntent,
    ModelOutputParseError,
    ModelOutputShapeError,
    ModelOutputValidationError,
    parse_model_output,
)
from vln.ipc.envelope import (
    ErrorCode,
    HostKind,
    ObservationStatus,
    Request,
    Response,
    SubmissionStatus,
)
from vln.ipc.errors import TransportError
from vln.pipeline import (
    DEFAULT_MAX_ROUNDS,
    LoopStopReason,
    ParkingLoopResult,
    run_parking_intent,
    run_parking_loop,
)
from vln.observation import CompositeObservationEncoder, ResponseFeedbackEncoder
from vln.vlm import (
    MockModelClient,
    ModelCallError,
    PreparedObservation,
    ZDTaichuModelClient,
)

_VALID_TEXT = (
    '{"contract_version":"1","intent_id":"intent-1","action":"parking.move",'
    '"target":{"x":1.0,"y":2.0,"heading":0.5}}'
)


# ----------------------------------------------------------------------
# Test doubles (spies/fakes) - no real host, no real model
# ----------------------------------------------------------------------


class _RecordingModel:
    """A model spy: appends 'generate', returns a fixed string or raises."""

    def __init__(self, output: str | None, events: list[str], *, error: Exception | None = None):
        self.output = output
        self.events = events
        self.error = error
        self.call_count = 0

    def generate(self, observation: object, instruction: str) -> str:
        self.call_count += 1
        self.events.append("generate")
        if self.error is not None:
            raise self.error
        assert self.output is not None
        return self.output


class _BuilderSpy:
    """A request-builder spy: appends 'build' and delegates to the real bridge."""

    def __init__(self, events: list[str]):
        self.events = events
        self.count = 0
        self.last_request: Request | None = None

    def __call__(self, intent, *, request_id: str) -> Request:
        self.count += 1
        self.events.append("build")
        self.last_request = build_request(intent, request_id=request_id)
        return self.last_request


class _FakeHostClient:
    """A fake HostClient: context manager that records send() calls."""

    def __init__(self, events: list[str], *, response: Response | None = None, error: Exception | None = None):
        self.events = events
        self.response = response
        self.error = error
        self.send_count = 0
        self.sent: list[Request] = []
        self.entered = 0
        self.exited = 0

    def __enter__(self) -> "_FakeHostClient":
        self.entered += 1
        return self

    def __exit__(self, *exc) -> bool:
        self.exited += 1
        return False

    def send(self, request: Request) -> Response:
        self.events.append("send")
        self.send_count += 1
        self.sent.append(request)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class _FactorySpy:
    """A host-client factory spy: counts calls and appends 'factory'."""

    def __init__(self, events: list[str], client: _FakeHostClient):
        self.events = events
        self.count = 0
        self._client = client

    def __call__(self) -> _FakeHostClient:
        self.count += 1
        self.events.append("factory")
        return self._client


def _ok_response(request_id: str) -> Response:
    return Response(
        request_id=request_id,
        host_kind=HostKind.STUB,
        accepted=True,
        submission_status=SubmissionStatus.COMPLETED,
        observation_status=ObservationStatus.SUCCESS,
        execution_status=None,
        output="[stub-echo]:x",
        error=None,
    )


def _wire(*, output: str | None, response: Response | None = None, model_error: Exception | None = None, send_error: Exception | None = None):
    events: list[str] = []
    model = _RecordingModel(output, events, error=model_error)
    builder = _BuilderSpy(events)
    client = _FakeHostClient(events, response=response, error=send_error)
    factory = _FactorySpy(events, client)
    return events, model, builder, client, factory


# ----------------------------------------------------------------------
# Success path
# ----------------------------------------------------------------------


def test_valid_output_runs_the_full_chain_in_order() -> None:
    events, model, builder, client, factory = _wire(
        output=_VALID_TEXT, response=_ok_response("req-1")
    )

    response = run_parking_intent(
        model=model,
        observation="obs",
        instruction="park at the target",
        request_id="req-1",
        host_client_factory=factory,
        request_builder=builder,
    )

    # Exact order: model -> parse(implicit) -> builder -> factory -> send.
    assert events == ["generate", "build", "factory", "send"]
    assert model.call_count == 1
    assert builder.count == 1
    assert factory.count == 1
    assert client.send_count == 1
    assert client.entered == 1 and client.exited == 1
    assert response is client.response


def test_success_sends_a_request_matching_the_intent() -> None:
    events, model, builder, client, factory = _wire(
        output=_VALID_TEXT, response=_ok_response("req-1")
    )
    run_parking_intent(
        model=model,
        observation=None,
        instruction="park",
        request_id="req-1",
        host_client_factory=factory,
        request_builder=builder,
    )
    request = client.sent[0]
    assert request.capability_id == "parking.move"
    assert request.request_id == "req-1"
    # payload is the bridge output for the parsed intent (verbatim serialization)
    assert request.payload == builder.last_request.payload
    assert '"intent_id":"intent-1"' in request.payload


def test_request_id_is_not_derived_from_intent_id() -> None:
    events, model, builder, client, factory = _wire(
        output=_VALID_TEXT, response=_ok_response("req-xyz")
    )
    run_parking_intent(
        model=model,
        observation=None,
        instruction="park",
        request_id="req-xyz",
        host_client_factory=factory,
        request_builder=builder,
    )
    assert client.sent[0].request_id == "req-xyz"
    assert '"intent_id":"intent-1"' in client.sent[0].payload
    assert client.sent[0].request_id != "intent-1"


def test_default_request_builder_is_used_when_not_injected() -> None:
    events, model, _builder, client, factory = _wire(
        output=_VALID_TEXT, response=_ok_response("req-1")
    )
    # No request_builder injected -> the pipeline uses the real build_request.
    run_parking_intent(
        model=model,
        observation=None,
        instruction="park",
        request_id="req-1",
        host_client_factory=factory,
    )
    assert client.sent[0].capability_id == "parking.move"
    assert client.sent[0].request_id == "req-1"


# ----------------------------------------------------------------------
# Failure path: nothing host-related may run before a valid intent exists
# ----------------------------------------------------------------------


_PARSE_FAILURES = [
    pytest.param("{not json", ModelOutputParseError, id="malformed-json"),
    pytest.param("", ModelOutputParseError, id="empty-text"),
    pytest.param(
        '{"contract_version":"1","intent_id":"i","action":"parking.move"}',
        ModelOutputShapeError,
        id="missing-top-level-field",
    ),
    pytest.param(
        '{"contract_version":"1","intent_id":"i","action":"parking.move",'
        '"target":{"x":1.0,"y":2.0,"heading":0.5},"confidence":0.9}',
        ModelOutputShapeError,
        id="unknown-top-level-field",
    ),
    pytest.param(
        '{"contract_version":"1","intent_id":"i","action":"parking.move",'
        '"target":{"x":1.0,"y":2.0}}',
        ModelOutputValidationError,
        id="target-missing-heading",
    ),
    pytest.param(
        '{"contract_version":"1","intent_id":"i","action":"parking.move",'
        '"target":{"x":"1.0","y":2.0,"heading":0.5}}',
        ModelOutputValidationError,
        id="x-is-string",
    ),
    pytest.param(
        '{"contract_version":"1","intent_id":"i","action":"parking.move",'
        '"target":{"x":true,"y":2.0,"heading":0.5}}',
        ModelOutputValidationError,
        id="x-is-bool",
    ),
    pytest.param(
        '{"contract_version":"1","intent_id":"i","action":"parking.stop",'
        '"target":{"x":1.0,"y":2.0,"heading":0.5}}',
        ModelOutputValidationError,
        id="wrong-action",
    ),
    pytest.param(
        '{"contract_version":"2","intent_id":"i","action":"parking.move",'
        '"target":{"x":1.0,"y":2.0,"heading":0.5}}',
        ModelOutputValidationError,
        id="wrong-contract-version",
    ),
    pytest.param(
        '{"contract_version":"1","intent_id":"   ","action":"parking.move",'
        '"target":{"x":1.0,"y":2.0,"heading":0.5}}',
        ModelOutputValidationError,
        id="blank-intent-id",
    ),
]


@pytest.mark.parametrize("raw, expected_error", _PARSE_FAILURES)
def test_parse_failure_blocks_all_host_work(raw: str, expected_error: type[Exception]) -> None:
    events, model, builder, client, factory = _wire(
        output=raw, response=_ok_response("req-1")
    )

    with pytest.raises(expected_error):
        run_parking_intent(
            model=model,
            observation="obs",
            instruction="park",
            request_id="req-1",
            host_client_factory=factory,
            request_builder=builder,
        )

    # Only the model ran; nothing host-related was constructed or called.
    assert events == ["generate"]
    assert builder.count == 0
    assert factory.count == 0
    assert client.send_count == 0
    assert client.entered == 0
    assert client.sent == []


def test_model_call_error_propagates_before_any_host_work() -> None:
    events, model, builder, client, factory = _wire(
        output=None, model_error=ModelCallError("backend unreachable")
    )
    with pytest.raises(ModelCallError):
        run_parking_intent(
            model=model,
            observation=None,
            instruction="park",
            request_id="req-1",
            host_client_factory=factory,
            request_builder=builder,
        )
    assert events == ["generate"]
    assert builder.count == 0
    assert factory.count == 0
    assert client.send_count == 0


def test_unexpected_model_exception_is_mapped_to_model_call_error() -> None:
    # A raw model/service bug must not leak as a non-model error, and must
    # never be turned into fabricated valid text.
    events, model, builder, client, factory = _wire(
        output=None, model_error=RuntimeError("boom")
    )
    with pytest.raises(ModelCallError) as exc:
        run_parking_intent(
            model=model,
            observation=None,
            instruction="park",
            request_id="req-1",
            host_client_factory=factory,
            request_builder=builder,
        )
    assert isinstance(exc.value.__cause__, RuntimeError)
    assert builder.count == 0
    assert factory.count == 0
    assert client.send_count == 0


def test_host_send_error_propagates_and_is_not_a_fake_success() -> None:
    events, model, builder, client, factory = _wire(
        output=_VALID_TEXT, send_error=TransportError("pipe broke")
    )
    with pytest.raises(TransportError):
        run_parking_intent(
            model=model,
            observation=None,
            instruction="park",
            request_id="req-1",
            host_client_factory=factory,
            request_builder=builder,
        )
    # The chain did reach the host, but the failure is surfaced, not swallowed.
    assert events == ["generate", "build", "factory", "send"]
    assert client.send_count == 1


def test_builder_failure_prevents_host_construction() -> None:
    # If the bridge itself fails, the host must not be constructed.
    events, model, _builder, client, factory = _wire(
        output=_VALID_TEXT, response=_ok_response("req-1")
    )

    def _exploding_builder(intent, *, request_id: str):
        events.append("build")
        raise RuntimeError("builder bug")

    with pytest.raises(RuntimeError):
        run_parking_intent(
            model=model,
            observation=None,
            instruction="park",
            request_id="req-1",
            host_client_factory=factory,
            request_builder=_exploding_builder,
        )
    assert events == ["generate", "build"]
    assert factory.count == 0
    assert client.send_count == 0


# ----------------------------------------------------------------------
# M1-VLN-FUNCTION-01: whole chain in-process, with a controlled executor
# ----------------------------------------------------------------------
# The C++ `parking.move` stub lives in an out-of-repo binary and is only
# reachable through tests/integration/test_kernel_host.py (which skips when the
# binary is absent). These tests exercise the SAME chain - MockModel -> parse/
# validate -> bridge -> host/executor -> result - entirely in-process, with a
# controlled stand-in for the host+executor seam, so the executor's call count,
# input and result are assertable with no subprocess, no compiled host, no
# Kernel, no model weights and no network.


class _ControlledStubExecutor:
    """In-process controlled stand-in for the host + Kernel executor seam.

    It records the exact :class:`Request` it was handed and returns a
    caller-configured deterministic :class:`Response` (or raises a configured
    exception). This is the in-process analogue of the C++ ``parking.move``
    stub reached through the real host: it controls no vehicle and performs no
    inference.
    """

    def __init__(self, outcome: Response | Exception) -> None:
        self.outcome = outcome
        self.call_count = 0
        self.invocations: list[Request] = []

    def execute(self, request: Request) -> Response:
        self.call_count += 1
        self.invocations.append(request)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _ExecutorHostClient:
    """A fake HostClient whose ``send`` delegates to a controlled executor."""

    def __init__(self, executor: _ControlledStubExecutor) -> None:
        self.executor = executor
        self.entered = 0
        self.exited = 0

    def __enter__(self) -> "_ExecutorHostClient":
        self.entered += 1
        return self

    def __exit__(self, *exc) -> bool:
        self.exited += 1
        return False

    def send(self, request: Request) -> Response:
        return self.executor.execute(request)


#: The exact text the MockModel returns; parsed by the real parser.
_MOCK_TEXT = (
    '{"contract_version":"1","intent_id":"intent-mock","action":"parking.move",'
    '"target":{"x":1.5,"y":-2.25,"heading":0.5}}'
)


def _stub_success_response(request_id: str) -> Response:
    """A success envelope shaped like the real C++ stub's response."""

    output = json.dumps(
        {
            "output_version": "1",
            "status": "stub_completed",
            "execution_mode": "simulation",
            "action": "parking.move",
            "intent_id": "intent-mock",
            "target": {"x": 1.5, "y": -2.25, "heading": 0.5},
        },
        separators=(",", ":"),
    )
    return Response(
        request_id=request_id,
        host_kind=HostKind.KERNEL,
        accepted=True,
        submission_status=SubmissionStatus.COMPLETED,
        observation_status=ObservationStatus.SUCCESS,
        execution_status="completed",
        output=output,
        error=None,
    )


def _stub_failure_response(request_id: str) -> Response:
    """A failure envelope shaped like the real C++ stub's invocation failure."""

    return Response(
        request_id=request_id,
        host_kind=HostKind.KERNEL,
        accepted=True,
        submission_status=SubmissionStatus.FAILED,
        observation_status=ObservationStatus.FAILURE,
        execution_status="failed",
        output=None,
        error={
            "code": ErrorCode.CAPABILITY_INVOCATION_FAILED,
            "message": "capability-invocation-failed:parking.move",
        },
    )


def test_mock_model_output_reaches_a_controlled_executor_exactly_once() -> None:
    """Whole chain in-process: MockModel -> parse -> bridge -> controlled executor."""

    model = MockModelClient(_MOCK_TEXT)
    executor = _ControlledStubExecutor(_stub_success_response("req-1"))
    host = _ExecutorHostClient(executor)

    response = run_parking_intent(
        model=model,
        observation={"cam": "mock-frame"},
        instruction="park at the target",
        request_id="req-1",
        host_client_factory=lambda: host,
    )

    # Called exactly once, end to end.
    assert model.call_count == 1
    assert executor.call_count == 1
    assert host.entered == 1 and host.exited == 1

    # Exact input: the validated intent, bridged by the real build_request.
    (request,) = executor.invocations
    assert request.capability_id == "parking.move"
    assert request.request_id == "req-1"
    parsed_intent = parse_model_output(_MOCK_TEXT)
    assert request.request_id != parsed_intent.intent_id
    assert AgentIntent.from_payload(request.payload) == parsed_intent

    # Result surfaced verbatim (a real success), not fabricated.
    assert response is executor.outcome
    assert response.ok is True
    assert json.loads(response.output)["intent_id"] == parsed_intent.intent_id


def test_in_band_execution_failure_is_not_reported_as_success() -> None:
    """A failing executor result is surfaced as failure, never as success."""

    model = MockModelClient(_MOCK_TEXT)
    executor = _ControlledStubExecutor(_stub_failure_response("req-1"))
    host = _ExecutorHostClient(executor)

    response = run_parking_intent(
        model=model,
        observation=None,
        instruction="park",
        request_id="req-1",
        host_client_factory=lambda: host,
    )

    assert model.call_count == 1
    assert executor.call_count == 1
    assert response is executor.outcome
    assert response.ok is False
    assert response.submission_status == SubmissionStatus.FAILED
    assert response.observation_status == ObservationStatus.FAILURE
    assert response.execution_status == "failed"
    assert response.output is None
    assert response.error is not None
    assert response.error["code"] == ErrorCode.CAPABILITY_INVOCATION_FAILED


# ----------------------------------------------------------------------
# M1-VLN-FUNCTION-03: minimal feedback closure (run_parking_loop)
# ----------------------------------------------------------------------
# These are pure-Python loop tests: the model is a scripted double and the
# "host" is an in-process stand-in, so the loop's feedback hand-off and its
# terminal conditions can be asserted exactly. The feedback under test is the
# loop's REAL Response object, and the scripting never sets the loop's outcome
# directly - the outcome is a function of how the model reads that response.


def _loop_intent_text(*, x: float, intent_id: str = "intent-loop") -> str:
    """A valid AgentIntent v1 payload string targeting the given x."""

    return json.dumps(
        {
            "contract_version": "1",
            "intent_id": intent_id,
            "action": "parking.move",
            "target": {"x": x, "y": -2.25, "heading": 0.5},
        },
        separators=(",", ":"),
    )


def _loop_success(
    request_id: str, *, x: float, intent_id: str = "intent-loop"
) -> Response:
    """A success Response shaped like the real stub's reply, echoing target x."""

    output = json.dumps(
        {
            "output_version": "1",
            "status": "stub_completed",
            "execution_mode": "simulation",
            "action": "parking.move",
            "intent_id": intent_id,
            "target": {"x": x, "y": -2.25, "heading": 0.5},
        },
        separators=(",", ":"),
    )
    return Response(
        request_id=request_id,
        host_kind=HostKind.KERNEL,
        accepted=True,
        submission_status=SubmissionStatus.COMPLETED,
        observation_status=ObservationStatus.SUCCESS,
        execution_status="completed",
        output=output,
        error=None,
    )


def _loop_failure(request_id: str) -> Response:
    """A failure Response shaped like the real stub's invocation failure."""

    return Response(
        request_id=request_id,
        host_kind=HostKind.KERNEL,
        accepted=True,
        submission_status=SubmissionStatus.FAILED,
        observation_status=ObservationStatus.FAILURE,
        execution_status="failed",
        output=None,
        error={
            "code": ErrorCode.CAPABILITY_INVOCATION_FAILED,
            "message": "capability-invocation-failed:parking.move",
        },
    )


class _OneResponseHost:
    """Context-manager host that answers every send with one scripted Response."""

    def __init__(self, response: Response, requests: list[Request]) -> None:
        self._response = response
        self._requests = requests

    def __enter__(self) -> "_OneResponseHost":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def send(self, request: Request) -> Response:
        self._requests.append(request)
        return self._response


class _ScriptedHostFactory:
    """A host-client factory returning one scripted Response per round.

    ``calls`` counts rounds and ``requests`` records the exact Request sent each
    round. Calling the factory beyond the scripted list repeats the last entry
    (so an always-continuing model can reach the round cap).
    """

    def __init__(self, responses: list[Response]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.requests: list[Request] = []

    def __call__(self) -> _OneResponseHost:
        index = self.calls
        self.calls += 1
        response = self._responses[min(index, len(self._responses) - 1)]
        return _OneResponseHost(response, self.requests)


class _FeedbackDrivenModel:
    """A test model whose later decisions are computed from the real feedback.

    Round 0 (the observation is not a Response) targets ``start_x``. Every later
    round reads the loop-supplied previous Response and targets
    ``last target.x + 1`` until that reaches ``done_x``, at which point it
    explicitly stops (empty output). The loop's continuation is therefore a
    function of the REAL response, not of a preset result.
    """

    def __init__(self, *, start_x: float = 1.0, done_x: float = 2.0) -> None:
        self._start_x = start_x
        self._done_x = done_x
        self.observations: list[object] = []

    def generate(self, observation: object, instruction: str) -> str:
        self.observations.append(observation)
        if not isinstance(observation, Response):
            return _loop_intent_text(x=self._start_x)
        last_x = json.loads(observation.output)["target"]["x"]
        if last_x >= self._done_x:
            return ""  # model decides to stop
        return _loop_intent_text(x=last_x + 1.0)


class _FixedTextModel:
    """A model that always returns the same raw text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def generate(self, observation: object, instruction: str) -> str:
        self.calls += 1
        return self.text


def test_loop_hands_the_real_response_back_and_it_drives_the_next_decision() -> None:
    model = _FeedbackDrivenModel(start_x=1.0, done_x=2.0)
    factory = _ScriptedHostFactory(
        [_loop_success("req-1", x=1.0), _loop_success("req-2", x=2.0)]
    )

    result = run_parking_loop(
        model=model,
        observation={"scene": "mock; no camera in this phase"},
        instruction="park at the target",
        host_client_factory=factory,
        request_id_factory=lambda index: f"req-{index + 1}",
    )

    assert isinstance(result, ParkingLoopResult)
    assert result.stop_reason == LoopStopReason.MODEL_STOP
    assert result.stopped_by_model is True
    assert len(result.responses) == 2
    assert factory.calls == 2

    # Round 0's model input is the initial observation; round 1's model input is
    # the REAL round-0 Response object (feedback), not the initial observation.
    assert not isinstance(model.observations[0], Response)
    assert model.observations[1] is result.responses[0]

    # The feedback (round-0 target x=1.0) drove round 1's decision (target x=2.0).
    assert json.loads(factory.requests[1].payload)["target"]["x"] == 2.0
    assert factory.requests[1].request_id == "req-2"
    assert factory.requests[1].capability_id == "parking.move"


def test_loop_decision_changes_when_the_feedback_changes() -> None:
    # Same model; only the round-0 response differs -> different continuation.
    def run(first_x: float) -> ParkingLoopResult:
        model = _FeedbackDrivenModel(start_x=1.0, done_x=2.0)
        factory = _ScriptedHostFactory(
            [_loop_success("req-1", x=first_x), _loop_success("req-2", x=2.0)]
        )
        return run_parking_loop(
            model=model,
            observation=None,
            instruction="park",
            host_client_factory=factory,
            request_id_factory=lambda index: f"req-{index + 1}",
        )

    keeps_going = run(1.0)  # feedback below done_x -> one more round
    stops_now = run(2.0)  # feedback at done_x -> stop immediately

    assert len(keeps_going.responses) == 2
    assert len(stops_now.responses) == 1
    assert keeps_going.stop_reason == stops_now.stop_reason == LoopStopReason.MODEL_STOP


def test_loop_stops_on_execution_failure_without_another_action() -> None:
    model = _FeedbackDrivenModel(start_x=1.0, done_x=999.0)  # would keep going
    factory = _ScriptedHostFactory([_loop_failure("req-1")])

    result = run_parking_loop(
        model=model,
        observation=None,
        instruction="park",
        host_client_factory=factory,
        request_id_factory=lambda index: f"req-{index + 1}",
    )

    assert result.stop_reason == LoopStopReason.EXECUTION_FAILED
    assert result.stopped_by_model is False
    assert result.last_response is not None
    assert result.last_response.ok is False
    assert result.last_response.error["code"] == ErrorCode.CAPABILITY_INVOCATION_FAILED
    # No second action: the loop stopped on the failure.
    assert factory.calls == 1
    assert len(result.responses) == 1


def test_loop_rejects_invalid_model_output_before_any_host_call() -> None:
    model = _FixedTextModel("{not a valid intent")
    factory = _ScriptedHostFactory([_loop_success("req-1", x=1.0)])

    result = run_parking_loop(
        model=model,
        observation=None,
        instruction="park",
        host_client_factory=factory,
        request_id_factory=lambda index: f"req-{index + 1}",
    )

    assert result.stop_reason == LoopStopReason.INVALID_OUTPUT
    assert result.responses == ()
    assert result.last_response is None
    assert factory.calls == 0  # the host was never reached


def test_loop_stops_at_max_rounds_and_does_not_claim_completion() -> None:
    model = _FixedTextModel(_loop_intent_text(x=1.0))  # never stops
    factory = _ScriptedHostFactory([_loop_success("req-1", x=1.0)])

    result = run_parking_loop(
        model=model,
        observation=None,
        instruction="park",
        host_client_factory=factory,
        request_id_factory=lambda index: f"req-{index + 1}",
        max_rounds=3,
    )

    assert result.stop_reason == LoopStopReason.MAX_ROUNDS
    assert result.stopped_by_model is False  # the cap is not a model stop
    assert len(result.responses) == 3
    assert factory.calls == 3
    # Every round succeeded, yet reaching the cap is NOT a completion.
    assert all(response.ok for response in result.responses)


def test_loop_rejects_a_non_positive_max_rounds() -> None:
    for bad in (0, -1, True, 1.0):
        with pytest.raises(ValueError):
            run_parking_loop(
                model=_FixedTextModel(_loop_intent_text(x=1.0)),
                observation=None,
                instruction="park",
                host_client_factory=_ScriptedHostFactory(
                    [_loop_success("req-1", x=1.0)]
                ),
                request_id_factory=lambda index: f"req-{index + 1}",
                max_rounds=bad,  # type: ignore[arg-type]
            )


def test_default_max_rounds_is_a_small_positive_cap() -> None:
    assert isinstance(DEFAULT_MAX_ROUNDS, int)
    assert 1 <= DEFAULT_MAX_ROUNDS <= 10


# ----------------------------------------------------------------------
# M1-VLN-FUNCTION-04: real adapter + feedback encoder, end to end
# ----------------------------------------------------------------------
# Everything here is real except the model weights and the host: the loop, the
# ZDTaichuModelClient adapter, the Response object and the parser are the
# production ones; only the inference backend and the host are fakes. These
# tests prove the ENCODED feedback - not the raw Response - reaches the backend
# on round 2.


class _FeedbackReadingBackend:
    """A fake InferenceBackend whose later rounds read the encoded feedback.

    Round 0 returns an intent targeting ``start_x``. Every later round parses
    the feedback text it receives, reads the previous round's echoed target x,
    and continues to ``+1`` until it reaches ``done_x`` (then it stops with
    empty text). The continuation therefore depends on the REAL feedback.
    """

    def __init__(self, *, start_x: float = 1.0, done_x: float = 2.0) -> None:
        self._start_x = start_x
        self._done_x = done_x
        self.observations: list[object] = []

    def generate(self, observation: object, instruction: str) -> str:
        self.observations.append(observation)
        if len(self.observations) == 1:
            return _loop_intent_text(x=self._start_x)
        last_x = json.loads(json.loads(observation.text)["output"])["target"]["x"]
        if last_x >= self._done_x:
            return ""
        return _loop_intent_text(x=last_x + 1.0)


class _ConstantBackend:
    """A fake InferenceBackend that always returns the same raw text."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.observations: list[object] = []

    def generate(self, observation: object, instruction: str) -> str:
        self.observations.append(observation)
        return self._text


def _real_adapter(backend: object) -> ZDTaichuModelClient:
    """A real adapter over a fake backend, using the feedback-aware encoder."""

    return ZDTaichuModelClient(
        backend_factory=lambda: backend,
        encoder=CompositeObservationEncoder(),
    )


def test_loop_with_the_real_adapter_sends_encoded_feedback_not_the_response() -> None:
    backend = _FeedbackReadingBackend(start_x=1.0, done_x=2.0)
    factory = _ScriptedHostFactory(
        [_loop_success("req-1", x=1.0), _loop_success("req-2", x=2.0)]
    )

    result = run_parking_loop(
        model=_real_adapter(backend),
        observation="a parking-lot scene",
        instruction="park at the target",
        host_client_factory=factory,
        request_id_factory=lambda index: f"req-{index + 1}",
    )

    assert result.stop_reason == LoopStopReason.MODEL_STOP
    assert len(result.responses) == 2
    assert factory.calls == 2

    # Round 2 is the stop round: the model is called (and returns empty text) but
    # nothing is submitted, so there are 3 model observations for 2 responses.
    assert len(backend.observations) == 3
    first, second, third = backend.observations
    assert isinstance(first, PreparedObservation)
    assert first.text == "a parking-lot scene"  # round 0: the caller's str
    # round 1: the ENCODED feedback, not the Response object
    assert isinstance(second, PreparedObservation)
    assert not isinstance(second, Response)
    assert second.text == ResponseFeedbackEncoder().encode(result.responses[0]).text
    payload = json.loads(second.text)
    assert payload["ok"] is True
    assert json.loads(payload["output"])["target"]["x"] == 1.0
    assert payload["truncated"] == {}
    # round 2 reads the second real response's feedback and then stops
    assert isinstance(third, PreparedObservation)
    assert third.text == ResponseFeedbackEncoder().encode(result.responses[1]).text


def test_changing_the_execution_feedback_changes_the_next_round_input() -> None:
    def run(first_x: float) -> tuple[str, ParkingLoopResult]:
        backend = _FeedbackReadingBackend(start_x=1.0, done_x=2.0)
        factory = _ScriptedHostFactory(
            [_loop_success("req-1", x=first_x), _loop_success("req-2", x=2.0)]
        )
        result = run_parking_loop(
            model=_real_adapter(backend),
            observation="scene",
            instruction="park",
            host_client_factory=factory,
            request_id_factory=lambda index: f"req-{index + 1}",
        )
        assert isinstance(backend.observations[1], PreparedObservation)
        return backend.observations[1].text, result

    text_below, keeps_going = run(1.0)  # feedback below done_x -> one more round
    text_at, stops_now = run(2.0)  # feedback at done_x -> stop immediately

    assert len(keeps_going.responses) == 2
    assert len(stops_now.responses) == 1
    assert text_below != text_at  # the real feedback drove a different next input
    assert json.loads(text_below)["output"] != json.loads(text_at)["output"]


def test_unsupported_observation_fails_closed_and_never_reaches_the_host() -> None:
    backend = _FeedbackReadingBackend()
    factory = _ScriptedHostFactory([_loop_success("req-1", x=1.0)])

    with pytest.raises(ModelCallError):
        run_parking_loop(
            model=_real_adapter(backend),
            observation={"scene": "structured"},  # not str / image / Response
            instruction="park",
            host_client_factory=factory,
            request_id_factory=lambda index: f"req-{index + 1}",
        )

    assert factory.calls == 0  # no submission
    assert backend.observations == []  # the model was never called


def test_invalid_model_text_is_still_invalid_output_with_the_real_adapter() -> None:
    backend = _ConstantBackend("{not a valid intent")
    factory = _ScriptedHostFactory([_loop_success("req-1", x=1.0)])

    result = run_parking_loop(
        model=_real_adapter(backend),
        observation="scene",
        instruction="park",
        host_client_factory=factory,
        request_id_factory=lambda index: f"req-{index + 1}",
    )

    assert result.stop_reason == LoopStopReason.INVALID_OUTPUT
    assert result.responses == ()
    assert factory.calls == 0  # fail-closed: nothing was submitted
