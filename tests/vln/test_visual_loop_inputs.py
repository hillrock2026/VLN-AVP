"""NAV-11A offline tests: image + instruction + previous-response feedback.

Everything here is deterministic and offline: the image backend is a test
double (it records the image path and instruction but sends no HTTP) and the
Host is a test double returning constructed ``Response`` objects. The NAV-09
layers and the NAV-10 execution half are the real implementations. These tests
prove input composition and feedback propagation, not real inference, real
image transport or a real Host execution.
"""

from __future__ import annotations

import json

import pytest

from vln.intent import AgentIntent
from vln.ipc.envelope import (
    ErrorCode,
    HostKind,
    ObservationStatus,
    Request,
    Response,
    SubmissionStatus,
)
from vln.ipc.errors import HostTerminatedError
from vln.nav import VehiclePose
from vln.nav_execution import NavigationExecutionError
from vln.observation import (
    CompositeObservationEncoder,
    FeedbackEncodingError,
    ResponseFeedbackEncoder,
)
from vln.pipeline import LoopStopReason
from vln.stm import FactStatus, NavigationTaskMemory, RoundOutcome
from vln.visual_loop import (
    MissingRoundObservationError,
    VisualLoopModelClient,
    run_visual_parking_loop,
)
from vln.vlm import (
    ModelCallError,
    UnsupportedObservationError,
    UnsupportedServerInputError,
)
from vln.vlm.image_path_client import (
    FEEDBACK_SECTION_HEADER,
    STM_SECTION_HEADER,
    ServerImageModelClient,
)

#: Explicitly simulated/test-only; no localisation exists in this project.
SIMULATED_TEST_POSE = VehiclePose(x=12.5, y=-4.0, heading=0.25)

_IMAGE_PATH = "frame.png"
_INSTRUCTION = "park at D50"

_BLOCK = (
    "第五步 输出结论块：\n"
    "Target: D50\n"
    "Identified as: D50\n"
    "Visible: 是\n"
    "Relative position: LEFT\n"
    "Next direction: LEFT\n"
    "Evidence: 地面白色编号 D50\n"
)


def _response(
    *,
    request_id: str = "req-1",
    accepted=True,
    submission_status=SubmissionStatus.COMPLETED,
    observation_status=ObservationStatus.SUCCESS,
    execution_status="completed",
    output: str | None = '{"target":{"x":1.0}}',
    error=None,
) -> Response:
    return Response(
        request_id=request_id,
        host_kind=HostKind.KERNEL,
        accepted=accepted,
        submission_status=submission_status,
        observation_status=observation_status,
        execution_status=execution_status,
        output=output,
        error=error,
    )


class _FakeImageBackend:
    """Test double for the existing server image entry; records its calls."""

    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.calls: list[tuple[str, str]] = []

    def generate_image(self, image_path: str, instruction: str) -> str:
        self.calls.append((image_path, instruction))
        if not self._outputs:
            return ""
        if len(self._outputs) == 1:
            return self._outputs[0]
        return self._outputs.pop(0)


def _image_model(backend: _FakeImageBackend) -> VisualLoopModelClient:
    return VisualLoopModelClient(
        image_path=_IMAGE_PATH,
        image_client=ServerImageModelClient(backend=backend),
    )


class _FailingModel:
    """A model double that fails before any image/backend work."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, observation: object, instruction: str) -> str:
        self.calls += 1
        raise ModelCallError("model unavailable")


class _FailsOnFeedbackModel:
    """Succeeds on round 0, then fails when the loop hands back a Response."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, observation: object, instruction: str) -> str:
        self.calls += 1
        if isinstance(observation, Response):
            raise ModelCallError("feedback model unavailable")
        return _BLOCK


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


def _success_response(request: Request, *, accepted=True) -> Response:
    return Response(
        request_id=request.request_id,
        host_kind=HostKind.KERNEL,
        accepted=accepted,
        submission_status=SubmissionStatus.COMPLETED,
        observation_status=ObservationStatus.SUCCESS,
        execution_status="completed",
        output=json.dumps(_stub_output(request)),
        error=None,
    )


def _failure_response(
    request: Request,
    *,
    accepted=True,
    submission_status=SubmissionStatus.FAILED,
    execution_status="failed",
    code=ErrorCode.CAPABILITY_INVOCATION_FAILED,
) -> Response:
    return Response(
        request_id=request.request_id,
        host_kind=HostKind.KERNEL,
        accepted=accepted,
        submission_status=submission_status,
        observation_status=ObservationStatus.FAILURE,
        execution_status=execution_status,
        output=None,
        error={"code": code, "message": "not executed"},
    )


class _FakeHost:
    """Offline HostClient stand-in; not evidence of Kernel execution."""

    def __init__(self, responder=None) -> None:
        self.builds = 0
        self.sends = 0
        self.requests: list[Request] = []
        self.responses: list[Response] = []
        self._responder = responder or (lambda request: _success_response(request))

    def factory(self) -> "_FakeHost":
        self.builds += 1
        return self

    def __enter__(self) -> "_FakeHost":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def send(self, request: Request) -> Response:
        self.sends += 1
        response = self._responder(request)
        self.requests.append(request)
        self.responses.append(response)
        return response


def _feedback_section(text: str) -> dict:
    """Parse the feedback JSON after the labelled section header."""

    _, _, payload = text.partition(FEEDBACK_SECTION_HEADER + "\n")
    assert payload, "the combined text has no feedback section"
    return json.loads(payload)


# ----------------------------------------------------------------------
# Test 1: round 0 has no fabricated history and keeps the image path
# ----------------------------------------------------------------------


def test_first_round_sends_only_the_image_and_current_instruction() -> None:
    backend = _FakeImageBackend([_BLOCK])
    model = _image_model(backend)

    raw = model.generate(_IMAGE_PATH, _INSTRUCTION)

    assert raw == _BLOCK
    assert backend.calls == [(_IMAGE_PATH, _INSTRUCTION)]
    assert FEEDBACK_SECTION_HEADER not in backend.calls[0][1]
    assert "上一轮" not in backend.calls[0][1]


# ----------------------------------------------------------------------
# Test 2: round 1+ receives the real previous Response as feedback
# ----------------------------------------------------------------------


def test_second_round_adds_feedback_after_the_current_instruction() -> None:
    backend = _FakeImageBackend([_BLOCK])
    model = _image_model(backend)
    previous = _response(request_id="req-previous")

    model.generate(previous, _INSTRUCTION)

    image_path, combined = backend.calls[0]
    expected_feedback = CompositeObservationEncoder().encode(previous).text

    assert image_path == _IMAGE_PATH
    assert combined.startswith(_INSTRUCTION)
    assert FEEDBACK_SECTION_HEADER in combined
    assert expected_feedback in combined
    assert (
        combined.index(_INSTRUCTION)
        < combined.index(FEEDBACK_SECTION_HEADER)
        < combined.index(expected_feedback)
    )
    # The image is still the separate image input, not text in the prompt.
    assert _IMAGE_PATH not in combined

    feedback = _feedback_section(combined)
    assert feedback["request_id"] == "req-previous"
    assert feedback["host_kind"] == "kernel"
    assert feedback["accepted"] is True
    assert feedback["submission_status"] == "completed"
    assert feedback["observation_status"] == "success"
    assert feedback["execution_status"] == "completed"
    assert feedback["ok"] is True


# ----------------------------------------------------------------------
# Test 3: success and failure statuses are preserved, never flattened
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "response, expected",
    [
        (
            _response(),
            {
                "accepted": True,
                "submission_status": "completed",
                "observation_status": "success",
                "execution_status": "completed",
                "ok": True,
                "error": None,
            },
        ),
        (
            _response(
                accepted=False,
                submission_status=SubmissionStatus.REJECTED,
                observation_status=ObservationStatus.FAILURE,
                execution_status=None,
                output=None,
                error={"code": ErrorCode.CAPABILITY_NOT_FOUND, "message": "no"},
            ),
            {
                "accepted": False,
                "submission_status": "rejected",
                "observation_status": "failure",
                "execution_status": None,
                "ok": False,
                "error": {"code": "capability-not-found", "message": "no"},
            },
        ),
        (
            _response(
                accepted=True,
                submission_status=SubmissionStatus.COMPLETED,
                observation_status=ObservationStatus.FAILURE,
                execution_status="failed",
                output=None,
                error={
                    "code": ErrorCode.CAPABILITY_INVOCATION_FAILED,
                    "message": "stub failed",
                },
            ),
            {
                "accepted": True,
                "submission_status": "completed",
                "observation_status": "failure",
                "execution_status": "failed",
                "ok": False,
                "error": {
                    "code": "capability-invocation-failed",
                    "message": "stub failed",
                },
            },
        ),
    ],
)
def test_feedback_preserves_response_status(response: Response, expected: dict) -> None:
    encoded = json.loads(CompositeObservationEncoder().encode(response).text)
    for name, value in expected.items():
        assert encoded[name] == value, name


def test_a_rejected_response_is_not_rendered_as_success() -> None:
    backend = _FakeImageBackend([_BLOCK])
    model = _image_model(backend)
    rejected = _response(
        accepted=False,
        submission_status=SubmissionStatus.REJECTED,
        observation_status=ObservationStatus.FAILURE,
        execution_status=None,
        output=None,
        error={"code": ErrorCode.CAPABILITY_NOT_FOUND, "message": "no"},
    )

    model.generate(rejected, _INSTRUCTION)

    feedback = _feedback_section(backend.calls[0][1])
    assert feedback["accepted"] is False
    assert feedback["submission_status"] == "rejected"
    assert feedback["observation_status"] == "failure"
    assert feedback["ok"] is False
    assert feedback["error"]["code"] == "capability-not-found"


# ----------------------------------------------------------------------
# Test 4: existing two-argument image client behaviour is unchanged
# ----------------------------------------------------------------------


def test_two_argument_generate_and_none_feedback_are_identical() -> None:
    backend = _FakeImageBackend(["first", "second"])
    client = ServerImageModelClient(backend=backend)

    assert client.generate("image.png", "instruction") == "first"
    assert client.generate_with_feedback("image.png", "instruction", None) == "second"

    assert backend.calls == [
        ("image.png", "instruction"),
        ("image.png", "instruction"),
    ]


def test_image_client_still_rejects_a_response_as_an_observation() -> None:
    client = ServerImageModelClient(backend=_FakeImageBackend(["x"]))

    with pytest.raises(UnsupportedObservationError):
        client.generate(_response(), "instruction")


def test_a_blank_instruction_is_refused_even_with_feedback() -> None:
    client = ServerImageModelClient(backend=_FakeImageBackend(["x"]))

    with pytest.raises(UnsupportedServerInputError):
        client.generate_with_feedback("image.png", "   ", '{"ok":true}')


def test_blank_feedback_is_refused_rather_than_dropped() -> None:
    client = ServerImageModelClient(backend=_FakeImageBackend(["x"]))

    with pytest.raises(ModelCallError):
        client.generate_with_feedback("image.png", "instruction", "   ")


# ----------------------------------------------------------------------
# Test 5: the existing loop, fed by the image/feedback model, wires rounds
# ----------------------------------------------------------------------


def _intent_id(round_index: int) -> str:
    return f"nav11a-intent-{round_index}"


def _request_id(round_index: int) -> str:
    return f"nav11a-req-{round_index}"


def test_the_existing_loop_carries_image_and_real_response_feedback() -> None:
    backend = _FakeImageBackend([_BLOCK, _BLOCK, ""])
    host = _FakeHost()
    model = _image_model(backend)

    result = run_visual_parking_loop(
        model=model,
        image_path=_IMAGE_PATH,
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=host.factory,
        intent_id_factory=_intent_id,
        request_id_factory=_request_id,
        max_rounds=3,
    )

    assert result.stop_reason == LoopStopReason.MODEL_STOP
    assert len(result.responses) == 2
    assert host.builds == 2
    assert len(host.requests) == 2

    # The first model call is the unchanged image-only call.
    assert backend.calls[0] == (_IMAGE_PATH, _INSTRUCTION)
    assert FEEDBACK_SECTION_HEADER not in backend.calls[0][1]

    # The second and third calls combine the current instruction with the
    # actual previous Response - not a fabricated status.
    for call_index, response in enumerate(result.responses, start=1):
        image_path, combined = backend.calls[call_index]
        assert image_path == _IMAGE_PATH
        assert combined.startswith(_INSTRUCTION)
        assert _IMAGE_PATH not in combined
        assert _feedback_section(combined) == json.loads(
            ResponseFeedbackEncoder().encode(response).text
        )

    # Round 2 saw exactly the response object returned by round 1 (and the
    # loop's result retains those same objects).
    assert result.responses[0] is host.responses[0]
    assert result.responses[1] is host.responses[1]

    # Every submitted request is a NAV-09-produced AgentIntent on the existing
    # parking.move route, with the caller's IDs.
    first = AgentIntent.from_payload(host.requests[0].payload)
    second = AgentIntent.from_payload(host.requests[1].payload)
    assert (first.intent_id, second.intent_id) == (
        "nav11a-intent-0",
        "nav11a-intent-1",
    )
    assert (host.requests[0].request_id, host.requests[1].request_id) == (
        "nav11a-req-0",
        "nav11a-req-1",
    )
    assert first.action == second.action == "parking.move"
    assert first.target.x == second.target.x == SIMULATED_TEST_POSE.x
    assert first.target.y == second.target.y == SIMULATED_TEST_POSE.y
    assert first.target.heading != SIMULATED_TEST_POSE.heading  # LEFT delta


@pytest.mark.parametrize(
    "failure",
    [
        {
            "accepted": False,
            "submission_status": SubmissionStatus.REJECTED,
            "execution_status": None,
            "code": ErrorCode.CAPABILITY_NOT_FOUND,
        },
        {
            "accepted": True,
            "submission_status": SubmissionStatus.FAILED,
            "execution_status": "failed",
            "code": ErrorCode.CAPABILITY_INVOCATION_FAILED,
        },
    ],
    ids=["rejected", "execution-failed"],
)
def test_execution_failure_stops_without_another_model_or_host_call(
    failure: dict,
) -> None:
    def _responder(request: Request) -> Response:
        return _failure_response(request, **failure)

    backend = _FakeImageBackend([_BLOCK])
    host = _FakeHost(_responder)

    result = run_visual_parking_loop(
        model=_image_model(backend),
        image_path=_IMAGE_PATH,
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=host.factory,
        intent_id_factory=_intent_id,
        request_id_factory=_request_id,
        max_rounds=3,
    )

    assert result.stop_reason == LoopStopReason.EXECUTION_FAILED
    assert result.stopped_by_model is False
    assert len(result.responses) == 1
    assert result.responses[0].ok is False
    assert result.responses[0].error["code"] == failure["code"]
    # One action, then stop: no second model call and no second Host call.
    assert host.builds == 1
    assert len(host.requests) == 1
    assert backend.calls == [(_IMAGE_PATH, _INSTRUCTION)]


def test_a_second_round_execution_failure_keeps_round_one_and_stops() -> None:
    """A later failure preserves the real prior response and adds no round."""

    sends = {"count": 0}

    def _responder(request: Request) -> Response:
        sends["count"] += 1
        if sends["count"] == 1:
            return _success_response(request)
        return _failure_response(request)

    backend = _FakeImageBackend([_BLOCK, _BLOCK])
    host = _FakeHost(_responder)

    result = run_visual_parking_loop(
        model=_image_model(backend),
        image_path=_IMAGE_PATH,
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=host.factory,
        intent_id_factory=_intent_id,
        request_id_factory=_request_id,
        max_rounds=3,
    )

    assert result.stop_reason == LoopStopReason.EXECUTION_FAILED
    assert len(result.responses) == 2
    assert result.responses[0].ok is True       # round 0 is still real success
    assert result.responses[1].ok is False      # round 1 is not disguised as success
    assert result.responses[0] is host.responses[0]
    assert result.responses[1] is host.responses[1]

    # Exactly two attempts with distinct round IDs; no duplicate of round 0.
    assert host.builds == 2
    assert host.sends == 2
    assert [request.request_id for request in host.requests] == [
        "nav11a-req-0",
        "nav11a-req-1",
    ]
    assert [
        AgentIntent.from_payload(request.payload).intent_id
        for request in host.requests
    ] == ["nav11a-intent-0", "nav11a-intent-1"]

    # Round 1 saw round 0's feedback, then the loop stopped: no third model call
    # and therefore no attempt to feed the failed response into round 2.
    assert len(backend.calls) == 2
    assert FEEDBACK_SECTION_HEADER in backend.calls[1][1]
    feedback = _feedback_section(backend.calls[1][1])
    assert feedback["request_id"] == "nav11a-req-0"
    assert feedback["ok"] is True


def test_a_second_round_host_transport_error_stops_without_retry() -> None:
    """A failure on a later round never causes a resend or a later round."""

    sends = {"count": 0}

    def _responder(request: Request) -> Response:
        sends["count"] += 1
        if sends["count"] == 1:
            return _success_response(request)
        raise HostTerminatedError("host terminated before responding")

    backend = _FakeImageBackend([_BLOCK, _BLOCK])
    host = _FakeHost(_responder)

    with pytest.raises(HostTerminatedError):
        run_visual_parking_loop(
            model=_image_model(backend),
            image_path=_IMAGE_PATH,
            instruction=_INSTRUCTION,
            expected_identity="D50",
            pose=SIMULATED_TEST_POSE,
            host_client_factory=host.factory,
            intent_id_factory=_intent_id,
            request_id_factory=_request_id,
            max_rounds=3,
        )

    # Round 0 succeeded; round 1 was attempted once and failed in transport.
    # No retry and no third model call.
    assert host.builds == 2
    assert host.sends == 2
    assert len(host.responses) == 1
    assert len(host.requests) == 1
    assert len(backend.calls) == 2
    assert host.requests[0].request_id == "nav11a-req-0"


def test_an_invalid_second_decision_stops_without_a_third_model_call() -> None:
    backend = _FakeImageBackend([_BLOCK, "not a conclusion block"])
    host = _FakeHost()

    result = run_visual_parking_loop(
        model=_image_model(backend),
        image_path=_IMAGE_PATH,
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=host.factory,
        intent_id_factory=_intent_id,
        request_id_factory=_request_id,
        max_rounds=3,
    )

    assert result.stop_reason == LoopStopReason.INVALID_OUTPUT
    assert len(result.responses) == 1
    assert result.responses[0].ok is True
    # Round 0 executed; round 1 was refused before Host work; no round 2.
    assert host.builds == 1
    assert len(host.requests) == 1
    assert len(backend.calls) == 2
    assert FEEDBACK_SECTION_HEADER in backend.calls[1][1]


def test_a_model_call_failure_propagates_without_any_host_call() -> None:
    host = _FakeHost()
    model = _FailingModel()

    with pytest.raises(ModelCallError):
        run_visual_parking_loop(
            model=model,
            image_path=_IMAGE_PATH,
            instruction=_INSTRUCTION,
            expected_identity="D50",
            pose=SIMULATED_TEST_POSE,
            host_client_factory=host.factory,
            intent_id_factory=_intent_id,
            request_id_factory=_request_id,
            max_rounds=2,
        )

    assert model.calls == 1
    assert host.builds == 0
    assert host.requests == []


def test_a_model_failure_on_the_feedback_round_does_not_execute_again() -> None:
    host = _FakeHost()
    model = _FailsOnFeedbackModel()

    with pytest.raises(ModelCallError):
        run_visual_parking_loop(
            model=model,
            image_path=_IMAGE_PATH,
            instruction=_INSTRUCTION,
            expected_identity="D50",
            pose=SIMULATED_TEST_POSE,
            host_client_factory=host.factory,
            intent_id_factory=_intent_id,
            request_id_factory=_request_id,
            max_rounds=3,
        )

    # Round 0 executed once; the failed feedback-round model call must not
    # produce a second Host request.
    assert model.calls == 2
    assert host.builds == 1
    assert len(host.requests) == 1
    assert host.responses[0].ok is True


def test_a_request_builder_failure_stops_before_the_host() -> None:
    backend = _FakeImageBackend([_BLOCK])
    host = _FakeHost()

    def _exploding_builder(intent: AgentIntent, *, request_id: str):
        raise RuntimeError("builder failed")

    with pytest.raises(RuntimeError):
        run_visual_parking_loop(
            model=_image_model(backend),
            image_path=_IMAGE_PATH,
            instruction=_INSTRUCTION,
            expected_identity="D50",
            pose=SIMULATED_TEST_POSE,
            host_client_factory=host.factory,
            intent_id_factory=_intent_id,
            request_id_factory=_request_id,
            max_rounds=2,
            request_builder=_exploding_builder,
        )

    assert host.builds == 0
    assert host.requests == []
    assert backend.calls == [(_IMAGE_PATH, _INSTRUCTION)]


def test_a_post_host_response_contract_error_propagates_without_retry() -> None:
    """NAV-10's response-contract error is not swallowed by the loop."""

    def _bad_success(request: Request) -> Response:
        return Response(
            request_id=request.request_id,
            host_kind=HostKind.KERNEL,
            accepted=True,
            submission_status=SubmissionStatus.COMPLETED,
            observation_status=ObservationStatus.SUCCESS,
            execution_status="completed",
            output='{"unexpected":true}',
            error=None,
        )

    backend = _FakeImageBackend([_BLOCK])
    host = _FakeHost(_bad_success)

    with pytest.raises(NavigationExecutionError):
        run_visual_parking_loop(
            model=_image_model(backend),
            image_path=_IMAGE_PATH,
            instruction=_INSTRUCTION,
            expected_identity="D50",
            pose=SIMULATED_TEST_POSE,
            host_client_factory=host.factory,
            intent_id_factory=_intent_id,
            request_id_factory=_request_id,
            max_rounds=3,
        )

    # One model call and one Host attempt; no retry and no next round.
    assert backend.calls == [(_IMAGE_PATH, _INSTRUCTION)]
    assert host.builds == 1
    assert len(host.requests) == 1


def test_a_host_transport_error_propagates_without_retry_or_response() -> None:
    def _terminate(request: Request) -> Response:
        raise HostTerminatedError("host terminated before responding")

    backend = _FakeImageBackend([_BLOCK])
    host = _FakeHost(_terminate)

    with pytest.raises(HostTerminatedError):
        run_visual_parking_loop(
            model=_image_model(backend),
            image_path=_IMAGE_PATH,
            instruction=_INSTRUCTION,
            expected_identity="D50",
            pose=SIMULATED_TEST_POSE,
            host_client_factory=host.factory,
            intent_id_factory=_intent_id,
            request_id_factory=_request_id,
            max_rounds=2,
        )

    assert backend.calls == [(_IMAGE_PATH, _INSTRUCTION)]
    assert host.builds == 1
    assert host.sends == 1  # one attempt; the responder raised before a Response
    assert host.responses == []


@pytest.mark.parametrize("max_rounds", [1, 2])
def test_max_rounds_is_an_exact_cap_without_extra_calls(max_rounds: int) -> None:
    backend = _FakeImageBackend([_BLOCK])  # never stops by itself
    host = _FakeHost()

    result = run_visual_parking_loop(
        model=_image_model(backend),
        image_path=_IMAGE_PATH,
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=host.factory,
        intent_id_factory=_intent_id,
        request_id_factory=_request_id,
        max_rounds=max_rounds,
    )

    assert result.stop_reason == LoopStopReason.MAX_ROUNDS
    assert result.stopped_by_model is False
    assert len(result.responses) == max_rounds
    assert host.builds == max_rounds
    assert len(host.requests) == max_rounds
    assert len(backend.calls) == max_rounds
    assert [
        (request.request_id, AgentIntent.from_payload(request.payload).intent_id)
        for request in host.requests
    ] == [
        (f"nav11a-req-{index}", f"nav11a-intent-{index}")
        for index in range(max_rounds)
    ]


def test_a_mismatched_model_image_path_is_refused_before_any_call() -> None:
    backend = _FakeImageBackend([_BLOCK])
    host = _FakeHost()
    model = VisualLoopModelClient(
        image_path="another-frame.png",
        image_client=ServerImageModelClient(backend=backend),
    )

    with pytest.raises(ValueError):
        run_visual_parking_loop(
            model=model,
            image_path=_IMAGE_PATH,
            instruction=_INSTRUCTION,
            expected_identity="D50",
            pose=SIMULATED_TEST_POSE,
            host_client_factory=host.factory,
            intent_id_factory=_intent_id,
            request_id_factory=_request_id,
            max_rounds=2,
        )

    assert backend.calls == []
    assert host.builds == 0


def test_a_refused_decision_stops_without_starting_a_host() -> None:
    backend = _FakeImageBackend(["not a conclusion block"])
    host = _FakeHost()
    model = _image_model(backend)

    result = run_visual_parking_loop(
        model=model,
        image_path=_IMAGE_PATH,
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=host.factory,
        intent_id_factory=_intent_id,
        request_id_factory=_request_id,
        max_rounds=2,
    )

    assert result.stop_reason == LoopStopReason.INVALID_OUTPUT
    assert result.responses == ()
    assert host.builds == 0
    assert host.requests == []
    assert len(backend.calls) == 1  # no retry / no next-round model call


def test_a_target_echo_contradiction_stops_the_loop_before_the_host() -> None:
    """The new identity consistency refusal also fails closed inside the loop."""

    contradictory = _BLOCK.replace("Target: D50", "Target: D66")
    backend = _FakeImageBackend([contradictory])
    host = _FakeHost()

    result = run_visual_parking_loop(
        model=_image_model(backend),
        image_path=_IMAGE_PATH,
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=host.factory,
        intent_id_factory=_intent_id,
        request_id_factory=_request_id,
        max_rounds=2,
    )

    assert result.stop_reason == LoopStopReason.INVALID_OUTPUT
    assert result.responses == ()
    assert host.builds == 0
    assert host.requests == []
    assert len(backend.calls) == 1  # no retry / no next-round model call


def test_evidence_insufficiency_stops_the_loop_before_the_host() -> None:
    """A concrete direction with an explicitly unsupported evidence is refused."""

    unsupported = _BLOCK.replace(
        "Evidence: 地面白色编号 D50", "Evidence: 证据不足，无法确定"
    )
    backend = _FakeImageBackend([unsupported])
    host = _FakeHost()

    result = run_visual_parking_loop(
        model=_image_model(backend),
        image_path=_IMAGE_PATH,
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=host.factory,
        intent_id_factory=_intent_id,
        request_id_factory=_request_id,
        max_rounds=2,
    )

    assert result.stop_reason == LoopStopReason.INVALID_OUTPUT
    assert result.responses == ()
    assert host.builds == 0
    assert host.requests == []
    assert len(backend.calls) == 1  # no retry / no next-round model call


def test_feedback_encoding_failure_stops_before_a_second_host_call() -> None:
    """A malformed Response cannot become fabricated feedback for round 2."""

    def _invalid_feedback_response(request: Request) -> Response:
        # Valid stub output, but `accepted` is not a boolean: the round-1
        # executor accepts the successful response, then the feedback encoder
        # refuses it at the round-2 model-input boundary.
        good = _success_response(request)
        return Response(
            request_id=good.request_id,
            host_kind=good.host_kind,
            accepted="yes",  # deliberately invalid for the encoder
            submission_status=good.submission_status,
            observation_status=good.observation_status,
            execution_status=good.execution_status,
            output=good.output,
            error=None,
        )

    backend = _FakeImageBackend([_BLOCK])
    host = _FakeHost(_invalid_feedback_response)
    model = _image_model(backend)

    with pytest.raises(FeedbackEncodingError) as excinfo:
        run_visual_parking_loop(
            model=model,
            image_path=_IMAGE_PATH,
            instruction=_INSTRUCTION,
            expected_identity="D50",
            pose=SIMULATED_TEST_POSE,
            host_client_factory=host.factory,
            intent_id_factory=_intent_id,
            request_id_factory=_request_id,
            max_rounds=2,
        )

    # The failure is distinguishable from an inference/service failure, and the
    # encoder's own cause survives for diagnosis.
    assert isinstance(excinfo.value, ModelCallError)
    assert isinstance(excinfo.value.__cause__, ModelCallError)
    assert "feedback encoding failed" in str(excinfo.value)
    assert host.builds == 1
    assert len(host.requests) == 1
    assert backend.calls == [(_IMAGE_PATH, _INSTRUCTION)]


# ----------------------------------------------------------------------
# STM-01: bounded history is actually injected into the next model input
# ----------------------------------------------------------------------


def _stm_section(text: str) -> dict:
    _, _, payload = text.partition(STM_SECTION_HEADER + "\n")
    assert payload, "the combined text has no STM section"
    return json.loads(payload)


def test_stm_context_reaches_the_next_model_input_and_rounds_are_linked() -> None:
    backend = _FakeImageBackend([_BLOCK, _BLOCK, ""])
    host = _FakeHost()
    image_b = "frame-b.png"
    image_c = "frame-c.png"
    memory = NavigationTaskMemory(
        task_id="task-stm-1", max_entries=4, max_facts=8, max_context_chars=2000
    )
    model = _image_model(backend)

    result = run_visual_parking_loop(
        model=model,
        image_path=_IMAGE_PATH,
        image_paths=[_IMAGE_PATH, image_b, image_c],
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=host.factory,
        intent_id_factory=_intent_id,
        request_id_factory=_request_id,
        max_rounds=3,
        memory=memory,
    )

    assert model.stm is memory

    assert result.stop_reason == LoopStopReason.MODEL_STOP
    assert len(result.responses) == 2
    assert len(memory.records) == 2

    # Task identity is stable; round indices increase; the ledger keeps the
    # exact real Response and its request_id.
    assert [record.task_id for record in memory.records] == ["task-stm-1", "task-stm-1"]
    assert [record.round_index for record in memory.records] == [0, 1]
    assert [record.intent_id for record in memory.records] == [
        "nav11a-intent-0",
        "nav11a-intent-1",
    ]
    assert [record.request_id for record in memory.records] == [
        "nav11a-req-0",
        "nav11a-req-1",
    ]
    assert [record.outcome for record in memory.records] == [
        RoundOutcome.SOFTWARE_SUCCEEDED,
        RoundOutcome.SOFTWARE_SUCCEEDED,
    ]
    for index, record in enumerate(memory.records):
        assert record.action == "parking.move"
        assert record.response is result.responses[index]
        assert record.response.request_id == record.request_id
    assert memory.stop_reason == LoopStopReason.MODEL_STOP
    assert memory.records[-1].stop_reason == LoopStopReason.MODEL_STOP

    # Round 0 uses image A, round 1 uses image B, and round 2 (the empty stop)
    # uses image C. Round 1 has both the real Response feedback and the
    # separate STM history section.
    assert [call[0] for call in backend.calls] == [_IMAGE_PATH, image_b, image_c]
    assert backend.calls[0] == (_IMAGE_PATH, _INSTRUCTION)
    second_text = backend.calls[1][1]
    assert second_text.startswith(_INSTRUCTION)
    assert FEEDBACK_SECTION_HEADER in second_text
    assert STM_SECTION_HEADER in second_text
    assert ResponseFeedbackEncoder().encode(result.responses[0]).text in second_text
    assert second_text.index(FEEDBACK_SECTION_HEADER) < second_text.index(
        STM_SECTION_HEADER
    )

    context = _stm_section(second_text)
    assert context["task_id"] == "task-stm-1"
    assert context["source"] == "history"
    assert context["physical_arrival"] == "unknown"
    assert context["rounds"][0]["round"] == 0
    assert context["rounds"][0]["request_id"] == "nav11a-req-0"
    assert context["rounds"][0]["outcome"] == RoundOutcome.SOFTWARE_SUCCEEDED
    assert any(
        fact["key"] == "target_identity"
        and fact["value"] == "D50"
        and fact["status"] == FactStatus.OBSERVED
        for fact in context["facts"]
    )
    assert "stub_completed does not mean arrival" in context["note"]

    # The STM summary did not replace the real previous Response: the exact
    # response encoder output is still present above the STM section.
    feedback_payload = (
        second_text.split(STM_SECTION_HEADER)[0]
        .partition(FEEDBACK_SECTION_HEADER + "\n")[2]
        .strip()
    )
    feedback = json.loads(feedback_payload)
    assert feedback["request_id"] == "nav11a-req-0"
    assert feedback["ok"] is True


def test_stm_is_off_by_default_and_keeps_the_old_input_contract() -> None:
    backend = _FakeImageBackend([_BLOCK, _BLOCK, ""])
    host = _FakeHost()

    result = run_visual_parking_loop(
        model=_image_model(backend),
        image_path=_IMAGE_PATH,
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=host.factory,
        intent_id_factory=_intent_id,
        request_id_factory=_request_id,
        max_rounds=3,
    )

    assert result.stop_reason == LoopStopReason.MODEL_STOP
    assert len(result.responses) == 2
    assert backend.calls[0] == (_IMAGE_PATH, _INSTRUCTION)
    assert STM_SECTION_HEADER not in backend.calls[1][1]
    assert FEEDBACK_SECTION_HEADER in backend.calls[1][1]
    assert _feedback_section(backend.calls[1][1]) == json.loads(
        ResponseFeedbackEncoder().encode(result.responses[0]).text
    )


def test_invalid_visual_output_is_recorded_and_never_reaches_the_host() -> None:
    backend = _FakeImageBackend(["not a conclusion block"])
    host = _FakeHost()
    memory = NavigationTaskMemory(task_id="task-invalid")

    result = run_visual_parking_loop(
        model=_image_model(backend),
        image_path=_IMAGE_PATH,
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=host.factory,
        intent_id_factory=_intent_id,
        request_id_factory=_request_id,
        max_rounds=2,
        memory=memory,
    )

    assert result.stop_reason == LoopStopReason.INVALID_OUTPUT
    assert result.responses == ()
    assert host.builds == 0
    assert host.sends == 0
    assert len(memory.records) == 1
    record = memory.records[0]
    assert record.outcome == RoundOutcome.NOT_SUBMITTED
    assert record.request_id is None
    assert record.response is None
    assert record.error is not None
    assert record.stop_reason == LoopStopReason.INVALID_OUTPUT
    assert memory.active_fact("last_action") is None
    assert memory.unresolved


def test_stm_records_a_failed_response_without_calling_it_success() -> None:
    backend = _FakeImageBackend([_BLOCK])
    host = _FakeHost(lambda request: _failure_response(request))
    memory = NavigationTaskMemory(task_id="task-failed")

    result = run_visual_parking_loop(
        model=_image_model(backend),
        image_path=_IMAGE_PATH,
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=host.factory,
        intent_id_factory=_intent_id,
        request_id_factory=_request_id,
        max_rounds=2,
        memory=memory,
    )

    assert result.stop_reason == LoopStopReason.EXECUTION_FAILED
    assert len(result.responses) == 1
    assert len(memory.records) == 1
    record = memory.records[0]
    assert record.outcome == RoundOutcome.EXECUTION_FAILED
    assert record.request_id == result.responses[0].request_id
    assert record.response is result.responses[0]
    assert memory.active_fact("last_action").status != FactStatus.CONFIRMED
    assert memory.active_fact("last_action_outcome").value == RoundOutcome.EXECUTION_FAILED
    assert memory.active_fact("arrived") is None
    assert memory.unresolved


def test_stm_records_transport_uncertainty_and_stops_without_retry() -> None:
    sends = {"count": 0}

    def _responder(request: Request) -> Response:
        sends["count"] += 1
        if sends["count"] == 1:
            return _success_response(request)
        raise HostTerminatedError("host terminated before responding")

    backend = _FakeImageBackend([_BLOCK, _BLOCK])
    host = _FakeHost(_responder)
    memory = NavigationTaskMemory(task_id="task-transport")

    with pytest.raises(HostTerminatedError):
        run_visual_parking_loop(
            model=_image_model(backend),
            image_path=_IMAGE_PATH,
            instruction=_INSTRUCTION,
            expected_identity="D50",
            pose=SIMULATED_TEST_POSE,
            host_client_factory=host.factory,
            intent_id_factory=_intent_id,
            request_id_factory=_request_id,
            max_rounds=3,
            memory=memory,
        )

    assert host.builds == 2
    assert host.sends == 2
    assert len(memory.records) == 2
    assert memory.records[0].outcome == RoundOutcome.SOFTWARE_SUCCEEDED
    assert memory.records[1].outcome == RoundOutcome.UNCERTAIN
    assert memory.records[1].request_id is None
    assert memory.records[1].response is None
    assert memory.stop_reason == "exception"
    assert memory.active_fact("last_action_outcome").value == RoundOutcome.UNCERTAIN
    assert memory.active_fact("arrived") is None


def test_each_round_sends_its_own_image_to_the_model() -> None:
    image_b = "frame-b.png"
    image_c = "frame-c.png"
    backend = _FakeImageBackend([_BLOCK, _BLOCK, ""])
    host = _FakeHost()

    result = run_visual_parking_loop(
        model=_image_model(backend),
        image_paths=[_IMAGE_PATH, image_b, image_c],
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=host.factory,
        intent_id_factory=_intent_id,
        request_id_factory=_request_id,
        max_rounds=3,
    )

    assert result.stop_reason == LoopStopReason.MODEL_STOP
    assert len(result.responses) == 2
    assert [call[0] for call in backend.calls] == [_IMAGE_PATH, image_b, image_c]
    assert backend.calls[0] == (_IMAGE_PATH, _INSTRUCTION)
    assert backend.calls[1][0] == image_b
    assert backend.calls[2][0] == image_c
    assert backend.calls[1][0] != backend.calls[0][0]
    # The third call is the model's explicit empty stop, after seeing image C.
    assert host.builds == 2
    assert [request.request_id for request in host.requests] == [
        "nav11a-req-0",
        "nav11a-req-1",
    ]


def test_missing_round_observation_is_refused_not_reused() -> None:
    backend = _FakeImageBackend([_BLOCK, _BLOCK])
    host = _FakeHost()
    memory = NavigationTaskMemory(task_id="task-missing-image")

    with pytest.raises(MissingRoundObservationError):
        run_visual_parking_loop(
            model=_image_model(backend),
            image_paths=[_IMAGE_PATH],  # only round 0 is supplied
            instruction=_INSTRUCTION,
            expected_identity="D50",
            pose=SIMULATED_TEST_POSE,
            host_client_factory=host.factory,
            intent_id_factory=_intent_id,
            request_id_factory=_request_id,
            max_rounds=2,
            memory=memory,
        )

    # Round 0 used image A and executed. Round 1 failed before the backend call;
    # the loop did not silently reuse A.
    assert backend.calls == [(_IMAGE_PATH, _INSTRUCTION)]
    assert host.builds == 1
    assert host.sends == 1
    assert len(memory.records) == 1
    assert memory.records[0].round_index == 0
    assert memory.records[0].outcome == RoundOutcome.SOFTWARE_SUCCEEDED
    assert memory.stop_reason == "exception"


def test_single_image_path_is_still_reused_without_a_per_round_sequence() -> None:
    backend = _FakeImageBackend([_BLOCK, _BLOCK, ""])
    host = _FakeHost()

    result = run_visual_parking_loop(
        model=_image_model(backend),
        image_path=_IMAGE_PATH,
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=host.factory,
        intent_id_factory=_intent_id,
        request_id_factory=_request_id,
        max_rounds=3,
    )

    assert result.stop_reason == LoopStopReason.MODEL_STOP
    assert [call[0] for call in backend.calls] == [
        _IMAGE_PATH,
        _IMAGE_PATH,
        _IMAGE_PATH,
    ]
    assert FEEDBACK_SECTION_HEADER in backend.calls[1][1]
    assert STM_SECTION_HEADER not in backend.calls[1][1]


def test_navigation_execution_error_keeps_the_real_response_as_uncertain() -> None:
    def _responder(request: Request) -> Response:
        return Response(
            request_id=request.request_id,
            host_kind=HostKind.KERNEL,
            accepted=True,
            submission_status=SubmissionStatus.COMPLETED,
            observation_status=ObservationStatus.SUCCESS,
            execution_status="completed",
            output='{"status":"stub_completed"}',  # missing output-v1 fields
            error=None,
        )

    backend = _FakeImageBackend([_BLOCK])
    host = _FakeHost(_responder)
    memory = NavigationTaskMemory(task_id="task-contract-error")

    with pytest.raises(NavigationExecutionError):
        run_visual_parking_loop(
            model=_image_model(backend),
            image_path=_IMAGE_PATH,
            instruction=_INSTRUCTION,
            expected_identity="D50",
            pose=SIMULATED_TEST_POSE,
            host_client_factory=host.factory,
            intent_id_factory=_intent_id,
            request_id_factory=_request_id,
            max_rounds=2,
            memory=memory,
        )

    assert len(host.responses) == 1
    assert len(memory.records) == 1
    record = memory.records[0]
    assert record.outcome == RoundOutcome.UNCERTAIN
    assert record.request_id == "nav11a-req-0"
    assert record.response is host.responses[0]
    assert record.error is not None
    assert memory.stop_reason == "exception"
    assert memory.active_fact("arrived") is None
