"""Offline tests for the ZDTaichu adapter (:mod:`vln.vlm.zdtaichu_client`).

Every test here uses a *fake* backend and/or a *fake* encoder injected through
the adapter's own seams. No weights, no ``torch``/``transformers``, no network,
no GPU and no real model are involved: the point under test is the adapter's
*boundary behaviour* (lazy load, verbatim passthrough, error mapping, input
handling and its connection to the real parser) - not inference quality. A
passing run here is NOT a claim that ZDTaichu5.0-9B runs.

The parser exercised downstream is the REAL
:func:`vln.intent.parse_model_output`; only the model and the host are fakes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from vln.intent import (
    AgentIntent,
    ModelOutputParseError,
    ModelOutputShapeError,
    ModelOutputValidationError,
    parse_model_output,
)
from vln.ipc.envelope import (
    HostKind,
    ObservationStatus,
    Request,
    Response,
    SubmissionStatus,
)
from vln.pipeline import run_parking_intent
from vln.vlm import (
    DefaultObservationEncoder,
    ModelCallError,
    ModelClient,
    MockModelClient,
    PreparedObservation,
    UnsupportedObservationError,
    ZDTaichuModelClient,
)

_VALID_TEXT = (
    '{"contract_version":"1","intent_id":"intent-zd","action":"parking.move",'
    '"target":{"x":1.5,"y":-2.25,"heading":0.5}}'
)


# ----------------------------------------------------------------------
# Test doubles: a backend and a factory, both injected through the seams
# ----------------------------------------------------------------------


class _FakeBackend:
    """A fake :class:`InferenceBackend` recording its calls.

    ``outcome`` is either the string to return or an exception to raise; no
    inference is performed.
    """

    def __init__(self, outcome: str | Exception) -> None:
        self.outcome = outcome
        self.call_count = 0
        self.observations: list[PreparedObservation] = []
        self.instructions: list[str] = []

    def generate(self, observation: PreparedObservation, instruction: str) -> str:
        self.call_count += 1
        self.observations.append(observation)
        self.instructions.append(instruction)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _CountingFactory:
    """A backend factory that counts calls, to prove lazy loading."""

    def __init__(self, backend: object, *, error: Exception | None = None) -> None:
        self.backend = backend
        self.error = error
        self.calls = 0

    def __call__(self) -> object:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.backend


def _client(backend_outcome: str | Exception = _VALID_TEXT):
    """Build a client over a fake backend plus its factory, for assertions."""

    backend = _FakeBackend(backend_outcome)
    factory = _CountingFactory(backend)
    return ZDTaichuModelClient(backend_factory=factory), factory, backend


# ----------------------------------------------------------------------
# A. Lazy initialisation and verbatim output
# ----------------------------------------------------------------------


def test_constructing_a_client_loads_no_backend() -> None:
    client, factory, backend = _client()
    assert factory.calls == 0  # nothing was loaded merely by constructing
    assert backend.call_count == 0
    assert isinstance(client, ZDTaichuModelClient)


def test_client_satisfies_the_model_client_protocol() -> None:
    client, _factory, _backend = _client()
    assert isinstance(client, ModelClient)


def test_injected_backend_returns_its_text_through_generate() -> None:
    client, _factory, backend = _client(_VALID_TEXT)

    assert client.generate("a parked-lot scene", "park at the target") == _VALID_TEXT
    assert backend.call_count == 1
    assert backend.instructions == ["park at the target"]


def test_adapter_returns_backend_text_verbatim() -> None:
    # The adapter must not trim, reformat or "fix" the text - the parse layer
    # owns every judgement about it.
    raw = '  \n{"not": "the contract"} trailing  '
    client, _factory, _backend = _client(raw)
    assert client.generate("scene", "park") == raw


def test_backend_is_loaded_at_most_once_across_calls() -> None:
    client, factory, backend = _client(_VALID_TEXT)

    client.generate("scene-1", "park")
    client.generate("scene-2", "park")

    assert factory.calls == 1  # loaded exactly once, then cached
    assert backend.call_count == 2


# ----------------------------------------------------------------------
# B. Error mapping (never fabricated text)
# ----------------------------------------------------------------------


def test_backend_load_failure_becomes_a_model_call_error_on_first_use() -> None:
    factory = _CountingFactory(object(), error=RuntimeError("weights missing"))
    client = ZDTaichuModelClient(backend_factory=factory)

    # Construction must not raise: loading happens lazily, on first generate.
    with pytest.raises(ModelCallError) as exc:
        client.generate("scene", "park")
    assert isinstance(exc.value.__cause__, RuntimeError)
    assert factory.calls == 1


def test_inference_failure_becomes_a_model_call_error() -> None:
    client, _factory, _backend = _client(RuntimeError("cuda oom"))

    with pytest.raises(ModelCallError) as exc:
        client.generate("scene", "park")
    assert isinstance(exc.value.__cause__, RuntimeError)


def test_non_string_backend_output_is_rejected_not_fabricated() -> None:
    client, _factory, _backend = _client(123)  # type: ignore[arg-type]

    with pytest.raises(ModelCallError):
        client.generate("scene", "park")


def test_a_backend_failure_is_not_disguised_as_valid_json() -> None:
    # A failure must surface as a failure, never as JSON-looking text a parser
    # might accept.
    client, _factory, _backend = _client(ValueError("boom"))

    with pytest.raises(ModelCallError) as exc:
        client.generate("scene", "park")
    assert not isinstance(exc.value, ModelOutputParseError)
    assert "{" not in str(exc.value)  # no fabricated payload in the message


def test_encoder_failure_is_mapped_to_a_model_call_error() -> None:
    class _ExplodingEncoder:
        def encode(self, observation: object) -> PreparedObservation:
            raise ValueError("encoder bug")

    client = ZDTaichuModelClient(
        backend_factory=_CountingFactory(_FakeBackend(_VALID_TEXT)),
        encoder=_ExplodingEncoder(),
    )
    with pytest.raises(ModelCallError) as exc:
        client.generate("scene", "park")
    assert isinstance(exc.value.__cause__, ValueError)


# ----------------------------------------------------------------------
# C. Observation input boundary
# ----------------------------------------------------------------------


def test_unsupported_observation_type_is_rejected_explicitly() -> None:
    client, factory, backend = _client()

    with pytest.raises(UnsupportedObservationError) as exc:
        client.generate(observation={"scene": "structured"}, instruction="park")

    assert exc.value.observation_type == "dict"
    # The model was never loaded and never called: nothing was silently dropped
    # or substituted.
    assert factory.calls == 0
    assert backend.call_count == 0


def test_unsupported_observation_error_is_a_model_call_error() -> None:
    # So the existing pipeline's fail-closed handling applies unchanged.
    assert issubclass(UnsupportedObservationError, ModelCallError)


def test_str_observation_reaches_the_backend_as_text() -> None:
    client, _factory, backend = _client()

    client.generate("the vehicle is 2 m from the slot", "park")

    (prepared,) = backend.observations
    assert isinstance(prepared, PreparedObservation)
    assert prepared.text == "the vehicle is 2 m from the slot"
    assert prepared.images == ()  # a str is never turned into an image


def test_image_observation_reaches_the_backend_as_an_image() -> None:
    pil_image = pytest.importorskip("PIL.Image")

    client, _factory, backend = _client()
    frame = pil_image.new("RGB", (2, 2))

    client.generate(frame, "park")

    (prepared,) = backend.observations
    assert prepared.images == (frame,)
    assert prepared.text == ""


def test_a_previous_host_response_is_not_treated_as_visual_input() -> None:
    # The multi-round loop hands the previous round's REAL Response as the next
    # observation. Until its encoding is verified, the adapter must refuse it -
    # not stringify it into a prompt and not mistake it for a frame.
    response = Response(
        request_id="req-1",
        host_kind=HostKind.STUB,
        accepted=True,
        submission_status=SubmissionStatus.COMPLETED,
        observation_status=ObservationStatus.SUCCESS,
        execution_status=None,
        output="[stub-echo]:secret-frame-bytes",
        error=None,
    )
    client, factory, backend = _client()

    with pytest.raises(UnsupportedObservationError) as exc:
        client.generate(response, "park")

    assert exc.value.observation_type == "Response"
    # No repr leakage: the response's output must not appear in the message.
    assert "secret-frame-bytes" not in str(exc.value)
    assert factory.calls == 0
    assert backend.call_count == 0


def test_an_injected_encoder_owns_the_observation_boundary() -> None:
    # A caller who has verified a conversion (e.g. host feedback -> text) can
    # supply it; the adapter defers entirely to the encoder.
    class _FeedbackEncoder:
        def encode(self, observation: object) -> PreparedObservation:
            if isinstance(observation, Response):
                return PreparedObservation(text=f"execution: {observation.execution_status}")
            raise UnsupportedObservationError(type(observation).__name__)

    response = Response(
        request_id="req-1",
        host_kind=HostKind.KERNEL,
        accepted=True,
        submission_status=SubmissionStatus.COMPLETED,
        observation_status=ObservationStatus.SUCCESS,
        execution_status="completed",
        output=None,
        error=None,
    )
    client = ZDTaichuModelClient(
        backend_factory=_CountingFactory(_FakeBackend(_VALID_TEXT)),
        encoder=_FeedbackEncoder(),
    )
    backend = client.backend_factory.backend  # type: ignore[attr-defined]

    assert client.generate(response, "park") == _VALID_TEXT
    assert backend.observations[0].text == "execution: completed"


def test_default_encoder_is_injectable_and_used_by_default() -> None:
    assert isinstance(DefaultObservationEncoder(), object)
    client, _factory, _backend = _client()
    assert isinstance(client.encoder, DefaultObservationEncoder)


# ----------------------------------------------------------------------
# D. Output-contract connection: the adapter's text still meets the REAL parser
# ----------------------------------------------------------------------


def test_adapter_output_is_accepted_by_the_real_parser() -> None:
    client, _factory, _backend = _client(_VALID_TEXT)

    raw = client.generate("scene", "park")
    intent = parse_model_output(raw)

    assert isinstance(intent, AgentIntent)
    assert intent.intent_id == "intent-zd"
    assert intent.target.x == 1.5


def test_malformed_adapter_output_is_rejected_by_the_real_parser() -> None:
    client, _factory, _backend = _client("{not json")

    with pytest.raises(ModelOutputParseError):
        parse_model_output(client.generate("scene", "park"))


def test_unknown_field_in_adapter_output_is_rejected_by_the_real_parser() -> None:
    raw = (
        '{"contract_version":"1","intent_id":"i","action":"parking.move",'
        '"target":{"x":1.0,"y":2.0,"heading":0.5},"confidence":0.9}'
    )
    client, _factory, _backend = _client(raw)

    with pytest.raises(ModelOutputShapeError):
        parse_model_output(client.generate("scene", "park"))


def test_wrong_type_in_adapter_output_is_rejected_by_the_real_parser() -> None:
    raw = (
        '{"contract_version":"1","intent_id":"i","action":"parking.move",'
        '"target":{"x":"1.0","y":2.0,"heading":0.5}}'
    )
    client, _factory, _backend = _client(raw)

    with pytest.raises(ModelOutputValidationError):
        parse_model_output(client.generate("scene", "park"))


def test_adapter_does_not_strip_wrappers_to_pass_the_contract() -> None:
    # A fenced output is still invalid: the adapter must not "help" the parser.
    raw = "```json\n" + _VALID_TEXT + "\n```"
    client, _factory, _backend = _client(raw)

    with pytest.raises(ModelOutputParseError):
        parse_model_output(client.generate("scene", "park"))


# ----------------------------------------------------------------------
# E. Integration with the existing offline chain and protection of it
# ----------------------------------------------------------------------


class _RecordingHostClient:
    def __init__(self, response: Response, requests: list[Request]) -> None:
        self._response = response
        self._requests = requests

    def __enter__(self) -> "_RecordingHostClient":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def send(self, request: Request) -> Response:
        self._requests.append(request)
        return self._response


def _ok_response(request_id: str) -> Response:
    return Response(
        request_id=request_id,
        host_kind=HostKind.KERNEL,
        accepted=True,
        submission_status=SubmissionStatus.COMPLETED,
        observation_status=ObservationStatus.SUCCESS,
        execution_status="completed",
        output=json.dumps({"intent_id": "intent-zd"}, separators=(",", ":")),
        error=None,
    )


def test_new_adapter_drives_the_real_pipeline_without_bypassing_it() -> None:
    # The adapter's text must still flow through the authoritative parse and the
    # existing submit path - it does not authorize or submit anything itself.
    requests: list[Request] = []
    client, _factory, _backend = _client(_VALID_TEXT)

    response = run_parking_intent(
        model=client,
        observation="a parking-lot scene",
        instruction="park at the target",
        request_id="req-1",
        host_client_factory=lambda: _RecordingHostClient(
            _ok_response("req-1"), requests
        ),
    )

    assert response.ok is True
    (request,) = requests
    assert request.capability_id == "parking.move"
    assert request.request_id == "req-1"
    assert AgentIntent.from_payload(request.payload).intent_id == "intent-zd"


def test_invalid_adapter_output_blocks_the_host_in_the_real_pipeline() -> None:
    requests: list[Request] = []
    client, _factory, _backend = _client("{not a valid intent")

    with pytest.raises(ModelOutputParseError):
        run_parking_intent(
            model=client,
            observation="scene",
            instruction="park",
            request_id="req-1",
            host_client_factory=lambda: _RecordingHostClient(
                _ok_response("req-1"), requests
            ),
        )
    assert requests == []  # fail-closed: nothing reached the host


def test_existing_mock_model_client_is_unaffected() -> None:
    model = MockModelClient(_VALID_TEXT)
    assert isinstance(model, ModelClient)
    assert model.generate(None, "park") == _VALID_TEXT


def test_adapter_module_pulls_in_no_inference_stack_host_or_pil() -> None:
    """Structural proof: importing the adapter loads no model stack, host or Pillow."""

    src_root = Path(__file__).resolve().parents[2] / "src"
    code = (
        "import sys, vln.vlm.zdtaichu_client as m;"
        "forbidden = [x for x in ('torch', 'transformers') if x in sys.modules];"
        "assert not forbidden, f'inference deps imported: {forbidden}';"
        "assert 'PIL' not in sys.modules, 'Pillow imported at module import';"
        "assert 'vln.client' not in sys.modules, 'adapter imports vln.client';"
        "assert 'vln.ipc' not in sys.modules, 'adapter imports vln.ipc';"
        "assert callable(getattr(m, 'ZDTaichuModelClient'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(src_root)},
    )
    assert result.returncode == 0, result.stderr
