"""Offline tests for the real ZDTaichu backend (:mod:`vln.vlm.zdtaichu_backend`).

Every test injects a *fake* runtime (processor + model) through the backend's
own seam, so no weights, no ``torch``/``transformers``, no network and no GPU are
involved. The point under test is the **call contract and its boundaries** -
lazy load, message construction, ``from_messages`` / ``generate`` / decode
arguments, prompt-token stripping, the network-input guard, error mapping and
the fail-closed output boundary - not inference quality.

The parser exercised downstream is the REAL :func:`vln.intent.parse_model_output`
and the loop is the REAL :func:`vln.pipeline.run_parking_intent`; only the
processor/model and the host are fakes. A passing run here is NOT a claim that
ZDTaichu5.0-9B runs.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from vln.intent import AgentIntent, ModelOutputParseError, parse_model_output
from vln.ipc.envelope import (
    HostKind,
    ObservationStatus,
    Request,
    Response,
    SubmissionStatus,
)
from vln.pipeline import run_parking_intent
from vln.vlm import (
    InferenceBackend,
    ModelCallError,
    PreparedObservation,
    UntrustedImageInputError,
    ZDTaichuBackend,
    ZDTaichuModelClient,
    ZDTaichuRuntime,
)
from vln.vlm.zdtaichu_backend import _default_inference_context

_VALID_TEXT = (
    '{"contract_version":"1","intent_id":"intent-zd","action":"parking.move",'
    '"target":{"x":1.5,"y":-2.25,"heading":0.5}}'
)

# The pinned revision must never be a movable branch name.
_PINNED_REVISION = "bc125a9819a421755f4dcebe498eb81c139b65a3"


# ----------------------------------------------------------------------
# Fakes: a processor + model pair injected through the backend's seam
# ----------------------------------------------------------------------


class _Shape:
    """Minimal multi-dim shape supporting ``shape[1]``."""

    def __init__(self, dims: tuple) -> None:
        self._dims = tuple(dims)

    def __getitem__(self, index: int) -> int:
        return self._dims[index]

    def __len__(self) -> int:
        return len(self._dims)


class _Tensor:
    def __init__(self, shape: tuple) -> None:
        self.shape = _Shape(shape)


class _Generated:
    """The result of stripping the prompt tokens."""

    def __init__(self, n_new: int) -> None:
        self.shape = _Shape((1, n_new))


class _OutputIds:
    """Fake ``output_ids`` that records the slice it is asked for."""

    def __init__(self, n_new: int = 3, *, slice_error: Exception | None = None) -> None:
        self._n_new = n_new
        self.slice_keys: list = []
        self._slice_error = slice_error

    def __getitem__(self, key):
        self.slice_keys.append(key)
        if self._slice_error is not None:
            raise self._slice_error
        return _Generated(self._n_new)


class _Inputs:
    """Fake ``BatchFeature``: ``**`` unpacking, ``["input_ids"]`` and ``.to()``."""

    def __init__(
        self,
        prompt_len: int = 7,
        *,
        has_input_ids: bool = True,
        to_error: Exception | None = None,
    ) -> None:
        self._data: dict = {
            "input_ids": _Tensor((1, prompt_len)),
            "attention_mask": _Tensor((1, prompt_len)),
        }
        if not has_input_ids:
            self._data.pop("input_ids")
        self.move_calls: list = []
        self._to_error = to_error

    def __getitem__(self, key):
        return self._data[key]

    def keys(self):
        return self._data.keys()

    def __iter__(self):
        return iter(self._data)

    def to(self, device):
        self.move_calls.append(device)
        if self._to_error is not None:
            raise self._to_error
        return self


class _Processor:
    def __init__(self, decoded, inputs: _Inputs) -> None:
        self.decoded = decoded
        self._inputs = inputs
        self.from_messages_calls: list = []
        self.decode_calls: list = []
        self.from_messages_error: Exception | None = None

    def from_messages(self, messages, return_tensors=None, **kwargs):
        self.from_messages_calls.append(
            {"messages": messages, "return_tensors": return_tensors, "kwargs": kwargs}
        )
        if self.from_messages_error is not None:
            raise self.from_messages_error
        return self._inputs

    def batch_decode(self, sequences, skip_special_tokens=False, **kwargs):
        self.decode_calls.append(
            {"sequences": sequences, "skip_special_tokens": skip_special_tokens}
        )
        if isinstance(self.decoded, Exception):
            raise self.decoded
        return self.decoded


class _Model:
    def __init__(self, output_ids, *, device: str = "cpu") -> None:
        self.device = device
        self._output_ids = output_ids
        self.generate_calls: list = []
        self.generate_error: Exception | None = None

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        if self.generate_error is not None:
            raise self.generate_error
        return self._output_ids


class _Factory:
    """Backend runtime factory that counts calls, to prove lazy loading."""

    def __init__(self, runtime=None, *, error: Exception | None = None, returns=None) -> None:
        self._runtime = runtime
        self._error = error
        self._returns = returns
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self._error is not None:
            raise self._error
        if self._returns is not None:
            return self._returns
        return self._runtime


@dataclass
class _Harness:
    backend: ZDTaichuBackend
    factory: _Factory
    processor: _Processor
    model: _Model
    inputs: _Inputs
    runtime: ZDTaichuRuntime
    output_ids: _OutputIds


def _harness(
    decoded=None,
    *,
    prompt_len: int = 7,
    n_new: int = 3,
    has_input_ids: bool = True,
    to_error: Exception | None = None,
    output_ids=None,
    device: str = "cpu",
    **backend_kwargs,
) -> _Harness:
    if decoded is None:
        decoded = [_VALID_TEXT]
    inputs = _Inputs(prompt_len, has_input_ids=has_input_ids, to_error=to_error)
    processor = _Processor(decoded, inputs)
    od = output_ids if output_ids is not None else _OutputIds(n_new)
    model = _Model(od, device=device)
    runtime = ZDTaichuRuntime(processor=processor, model=model)
    factory = _Factory(runtime)
    backend_kwargs.setdefault("inference_context", contextlib.nullcontext)
    backend = ZDTaichuBackend(runtime_factory=factory, **backend_kwargs)
    return _Harness(backend, factory, processor, model, inputs, runtime, od)


# ----------------------------------------------------------------------
# T1. Lazy initialisation and dependency injection
# ----------------------------------------------------------------------


def test_constructing_a_backend_loads_no_runtime() -> None:
    h = _harness()
    assert h.factory.calls == 0
    assert h.processor.from_messages_calls == []
    assert h.model.generate_calls == []


def test_backend_satisfies_the_inference_backend_protocol() -> None:
    assert isinstance(_harness().backend, InferenceBackend)


def test_runtime_is_loaded_once_and_cached_across_calls() -> None:
    h = _harness()
    h.backend.generate(PreparedObservation(text="scene"), "park")
    h.backend.generate(PreparedObservation(text="scene"), "park")
    assert h.factory.calls == 1  # loaded exactly once, then cached
    assert len(h.processor.from_messages_calls) == 2


def test_load_failure_is_a_model_call_error_and_the_next_call_retries() -> None:
    factory = _Factory(error=RuntimeError("weights missing"))
    backend = ZDTaichuBackend(runtime_factory=factory)

    with pytest.raises(ModelCallError) as exc:
        backend.generate(PreparedObservation(text="scene"), "park")
    assert isinstance(exc.value.__cause__, RuntimeError)
    assert factory.calls == 1

    # Mirrors ZDTaichuModelClient: nothing is cached on failure, so the next
    # call retries rather than silently reusing a broken load.
    with pytest.raises(ModelCallError):
        backend.generate(PreparedObservation(text="scene"), "park")
    assert factory.calls == 2


def test_factory_returning_a_non_runtime_is_rejected() -> None:
    backend = ZDTaichuBackend(runtime_factory=_Factory(returns=object()))
    with pytest.raises(ModelCallError):
        backend.generate(PreparedObservation(text="scene"), "park")


def test_factory_returning_none_is_rejected() -> None:
    backend = ZDTaichuBackend(runtime_factory=_Factory(returns=None))
    with pytest.raises(ModelCallError):
        backend.generate(PreparedObservation(text="scene"), "park")


# ----------------------------------------------------------------------
# T2. Input construction
# ----------------------------------------------------------------------


def test_text_observation_and_instruction_become_one_user_message() -> None:
    h = _harness()
    h.backend.generate(PreparedObservation(text="a parking-lot scene"), "park at the target")
    (call,) = h.processor.from_messages_calls
    assert call["return_tensors"] == "pt"
    assert call["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "a parking-lot scene\npark at the target"}
            ],
        }
    ]


def test_image_observation_is_forwarded_as_an_image_content_item() -> None:
    h = _harness()
    image = object()
    h.backend.generate(PreparedObservation(images=(image,)), "park")
    (call,) = h.processor.from_messages_calls
    content = call["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["image"] is image  # forwarded unchanged, not copied/encoded
    assert content[1]["type"] == "text"
    assert content[1]["text"] == "park"


def test_image_and_text_keep_their_order() -> None:
    h = _harness()
    a, b = object(), object()
    h.backend.generate(PreparedObservation(text="scene", images=(a, b)), "park")
    (call,) = h.processor.from_messages_calls
    content = call["messages"][0]["content"]
    assert [item["type"] for item in content] == ["image", "image", "text"]
    assert [item["image"] for item in content[:2]] == [a, b]


def test_blank_input_is_rejected_before_any_load_or_processor_call() -> None:
    h = _harness()
    with pytest.raises(ModelCallError):
        h.backend.generate(PreparedObservation(), "")
    assert h.factory.calls == 0
    assert h.processor.from_messages_calls == []


def test_non_prepared_observation_is_rejected() -> None:
    h = _harness()
    with pytest.raises(ModelCallError):
        h.backend.generate({"text": "scene"}, "park")  # type: ignore[arg-type]
    assert h.processor.from_messages_calls == []


def test_non_str_observation_text_is_rejected() -> None:
    h = _harness()
    with pytest.raises(ModelCallError):
        h.backend.generate(PreparedObservation(text=123), "park")  # type: ignore[arg-type]


def test_non_sequence_images_is_rejected() -> None:
    h = _harness()
    with pytest.raises(ModelCallError):
        h.backend.generate(PreparedObservation(text="scene", images="not-a-tuple"), "park")  # type: ignore[arg-type]


def test_non_str_instruction_is_rejected() -> None:
    h = _harness()
    with pytest.raises(ModelCallError):
        h.backend.generate(PreparedObservation(text="scene"), 123)  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# T3. Processor invocation
# ----------------------------------------------------------------------


def test_processor_receives_the_built_messages_and_return_tensors() -> None:
    h = _harness()
    h.backend.generate(PreparedObservation(text="scene"), "park")
    (call,) = h.processor.from_messages_calls
    assert call["return_tensors"] == "pt"
    assert call["kwargs"] == {}
    assert call["messages"][0]["role"] == "user"


def test_processor_output_is_moved_to_the_model_device_then_forwarded() -> None:
    h = _harness(device="cuda:0")
    h.backend.generate(PreparedObservation(text="scene"), "park")
    assert h.inputs.move_calls == ["cuda:0"]
    (gen_call,) = h.model.generate_calls
    # Nothing the processor produced is dropped: every field is forwarded.
    assert gen_call["input_ids"] is h.inputs["input_ids"]
    assert gen_call["attention_mask"] is h.inputs["attention_mask"]


def test_processor_without_a_device_move_is_still_forwarded() -> None:
    # A runtime whose model exposes no device: inputs pass through unchanged.
    inputs = _Inputs(7)
    processor = _Processor([_VALID_TEXT], inputs)
    model = _Model(_OutputIds(3))
    del model.device  # type: ignore[attr-defined]
    backend = ZDTaichuBackend(
        runtime_factory=lambda: ZDTaichuRuntime(processor=processor, model=model),
        inference_context=contextlib.nullcontext,
    )
    backend.generate(PreparedObservation(text="scene"), "park")
    assert inputs.move_calls == []
    (gen_call,) = model.generate_calls
    assert gen_call["input_ids"] is inputs["input_ids"]


# ----------------------------------------------------------------------
# T4. Generate invocation
# ----------------------------------------------------------------------


def test_generate_receives_the_confirmed_default_parameters() -> None:
    h = _harness()
    h.backend.generate(PreparedObservation(text="scene"), "park")
    (gen_call,) = h.model.generate_calls
    assert gen_call["max_new_tokens"] == 1024
    assert gen_call["do_sample"] is False


def test_generate_parameters_are_configurable() -> None:
    h = _harness(max_new_tokens=64, do_sample=True)
    h.backend.generate(PreparedObservation(text="scene"), "park")
    (gen_call,) = h.model.generate_calls
    assert gen_call["max_new_tokens"] == 64
    assert gen_call["do_sample"] is True


def test_runtime_is_not_loaded_when_input_construction_fails() -> None:
    h = _harness()
    with pytest.raises(ModelCallError):
        h.backend.generate(PreparedObservation(images=("http://x/y.png",)), "park")
    assert h.factory.calls == 0
    assert h.model.generate_calls == []


# ----------------------------------------------------------------------
# T5. Prompt-token stripping and decoding
# ----------------------------------------------------------------------


def test_prompt_tokens_are_stripped_and_decode_uses_skip_special_tokens() -> None:
    h = _harness(prompt_len=7, n_new=4)
    text = h.backend.generate(PreparedObservation(text="scene"), "park")

    assert h.output_ids.slice_keys == [(slice(None), slice(7, None))]
    (decode_call,) = h.processor.decode_calls
    assert isinstance(decode_call["sequences"], _Generated)
    assert decode_call["skip_special_tokens"] is True
    assert text == _VALID_TEXT


def test_a_different_prompt_length_yields_a_different_slice() -> None:
    h = _harness(prompt_len=13)
    h.backend.generate(PreparedObservation(text="scene"), "park")
    assert h.output_ids.slice_keys == [(slice(None), slice(13, None))]


def test_empty_decoded_text_is_returned_verbatim_as_the_stop_signal() -> None:
    # An empty string is the loop's explicit "model stopped" signal, so it is
    # passed through rather than turned into an error or a fabricated value.
    h = _harness(decoded=[""])
    assert h.backend.generate(PreparedObservation(text="scene"), "park") == ""


# ----------------------------------------------------------------------
# T6. Error handling (nothing is swallowed or disguised as success)
# ----------------------------------------------------------------------


def test_from_messages_failure_becomes_a_model_call_error() -> None:
    h = _harness()
    h.processor.from_messages_error = RuntimeError("bad processor")
    with pytest.raises(ModelCallError) as exc:
        h.backend.generate(PreparedObservation(text="scene"), "park")
    assert isinstance(exc.value.__cause__, RuntimeError)
    assert h.model.generate_calls == []


def test_generate_failure_becomes_a_model_call_error() -> None:
    h = _harness()
    h.model.generate_error = RuntimeError("cuda oom")
    with pytest.raises(ModelCallError) as exc:
        h.backend.generate(PreparedObservation(text="scene"), "park")
    assert isinstance(exc.value.__cause__, RuntimeError)
    assert h.processor.decode_calls == []


def test_device_move_failure_becomes_a_model_call_error() -> None:
    h = _harness(to_error=RuntimeError("device move failed"))
    with pytest.raises(ModelCallError) as exc:
        h.backend.generate(PreparedObservation(text="scene"), "park")
    assert isinstance(exc.value.__cause__, RuntimeError)
    assert h.model.generate_calls == []


def test_processor_output_without_input_ids_is_rejected() -> None:
    h = _harness(has_input_ids=False)
    with pytest.raises(ModelCallError):
        h.backend.generate(PreparedObservation(text="scene"), "park")
    assert h.processor.decode_calls == []


def test_unsliceable_model_output_is_rejected() -> None:
    h = _harness(output_ids=_OutputIds(slice_error=TypeError("not sliceable")))
    with pytest.raises(ModelCallError) as exc:
        h.backend.generate(PreparedObservation(text="scene"), "park")
    assert isinstance(exc.value.__cause__, TypeError)


def test_empty_decode_result_is_rejected() -> None:
    h = _harness(decoded=[])
    with pytest.raises(ModelCallError):
        h.backend.generate(PreparedObservation(text="scene"), "park")


def test_non_str_decoded_element_is_rejected() -> None:
    h = _harness(decoded=[123])
    with pytest.raises(ModelCallError):
        h.backend.generate(PreparedObservation(text="scene"), "park")


def test_bare_str_decode_result_is_rejected() -> None:
    h = _harness(decoded="not-a-sequence")
    with pytest.raises(ModelCallError):
        h.backend.generate(PreparedObservation(text="scene"), "park")


def test_batch_decode_failure_becomes_a_model_call_error() -> None:
    h = _harness(decoded=RuntimeError("decode blew up"))
    with pytest.raises(ModelCallError) as exc:
        h.backend.generate(PreparedObservation(text="scene"), "park")
    assert isinstance(exc.value.__cause__, RuntimeError)


def test_a_failure_never_yields_fabricated_json() -> None:
    h = _harness(decoded=RuntimeError("boom"))
    with pytest.raises(ModelCallError) as exc:
        h.backend.generate(PreparedObservation(text="scene"), "park")
    assert "{" not in str(exc.value)


# ----------------------------------------------------------------------
# T7. Network-input restriction
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/a.jpg",
        "https://example.com/a.jpg",
        "HTTPS://EXAMPLE.COM/a.JPG",
        "  https://example.com/a.jpg  ",
    ],
)
def test_remote_url_image_is_refused_before_the_processor(url: str) -> None:
    h = _harness()
    with pytest.raises(UntrustedImageInputError):
        h.backend.generate(PreparedObservation(images=(url,)), "park")
    # The guard fires before the runtime is loaded and before any processor or
    # network call could happen.
    assert h.factory.calls == 0
    assert h.processor.from_messages_calls == []


def test_local_path_string_image_is_refused() -> None:
    h = _harness()
    with pytest.raises(UntrustedImageInputError):
        h.backend.generate(PreparedObservation(images=("/tmp/scene.png",)), "park")
    assert h.processor.from_messages_calls == []


def test_raw_bytes_image_is_refused() -> None:
    h = _harness()
    with pytest.raises(UntrustedImageInputError):
        h.backend.generate(PreparedObservation(images=(b"\x89PNG\r\n",)), "park")
    assert h.processor.from_messages_calls == []


def test_untrusted_image_error_is_a_model_call_error() -> None:
    assert issubclass(UntrustedImageInputError, ModelCallError)


def test_a_single_bad_image_blocks_the_whole_call() -> None:
    h = _harness()
    with pytest.raises(UntrustedImageInputError):
        h.backend.generate(
            PreparedObservation(images=(object(), "http://x/y.png")), "park"
        )
    assert h.processor.from_messages_calls == []


def test_untrusted_image_error_does_not_leak_the_value() -> None:
    h = _harness()
    with pytest.raises(UntrustedImageInputError) as exc:
        h.backend.generate(
            PreparedObservation(images=("https://user:secret@host/x.png",)), "park"
        )
    assert "secret" not in str(exc.value)


# ----------------------------------------------------------------------
# T8. Output boundary and fail-closed hand-off
# ----------------------------------------------------------------------

_THINKING_TEXT = "<think>\nreason about the lot\n</think>\n\n" + _VALID_TEXT


class _RecordingHostClient:
    def __init__(self, response: Response, requests: list) -> None:
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


def _client(h: _Harness) -> ZDTaichuModelClient:
    return ZDTaichuModelClient(backend_factory=lambda: h.backend)


def test_raw_output_is_returned_verbatim_without_think_stripping() -> None:
    h = _harness(decoded=[_THINKING_TEXT])
    assert h.backend.generate(PreparedObservation(text="scene"), "park") == _THINKING_TEXT


def test_thinking_prefixed_output_is_rejected_by_the_strict_parser() -> None:
    h = _harness(decoded=[_THINKING_TEXT])
    raw = h.backend.generate(PreparedObservation(text="scene"), "park")
    with pytest.raises(ModelOutputParseError):
        parse_model_output(raw)


def test_valid_output_parses_into_an_agent_intent() -> None:
    h = _harness(decoded=[_VALID_TEXT])
    raw = h.backend.generate(PreparedObservation(text="scene"), "park")
    intent = parse_model_output(raw)
    assert isinstance(intent, AgentIntent)
    assert intent.intent_id == "intent-zd"
    assert intent.target.x == 1.5


def test_invalid_model_output_never_reaches_the_host() -> None:
    requests: list = []
    h = _harness(decoded=[_THINKING_TEXT])
    with pytest.raises(ModelOutputParseError):
        run_parking_intent(
            model=_client(h),
            observation="a parking-lot scene",
            instruction="park",
            request_id="req-1",
            host_client_factory=lambda: _RecordingHostClient(_ok_response("req-1"), requests),
        )
    assert requests == []  # fail-closed: nothing reached the host


def test_valid_output_drives_the_real_pipeline_without_bypassing_it() -> None:
    requests: list = []
    h = _harness(decoded=[_VALID_TEXT])
    response = run_parking_intent(
        model=_client(h),
        observation="a parking-lot scene",
        instruction="park",
        request_id="req-1",
        host_client_factory=lambda: _RecordingHostClient(_ok_response("req-1"), requests),
    )
    assert response.ok is True
    (request,) = requests
    assert request.capability_id == "parking.move"
    assert AgentIntent.from_payload(request.payload).target.x == 1.5


# ----------------------------------------------------------------------
# Structural and contract-invariant checks
# ----------------------------------------------------------------------


def test_revision_is_pinned_to_an_immutable_sha_not_a_branch() -> None:
    from vln.vlm import MODEL_ID, MODEL_REVISION

    assert MODEL_ID == "TaichuAI/ZDTaichu5.0-9B"
    assert MODEL_REVISION == _PINNED_REVISION
    assert MODEL_REVISION not in ("main", "master")
    assert len(MODEL_REVISION) == 40
    int(MODEL_REVISION, 16)  # a hex commit SHA, not a label


def test_default_inference_context_is_a_usable_context_manager() -> None:
    with _default_inference_context():
        pass


def test_backend_module_pulls_in_no_inference_stack_host_or_pil() -> None:
    """Structural proof: importing the backend loads no model stack, host or Pillow."""

    src_root = Path(__file__).resolve().parents[2] / "src"
    code = (
        "import sys, vln.vlm.zdtaichu_backend as m;"
        "forbidden = [x for x in ('torch', 'transformers') if x in sys.modules];"
        "assert not forbidden, f'inference deps imported: {forbidden}';"
        "assert 'PIL' not in sys.modules, 'Pillow imported at module import';"
        "assert 'vln.client' not in sys.modules, 'backend imports vln.client';"
        "assert 'vln.ipc' not in sys.modules, 'backend imports vln.ipc';"
        "assert callable(getattr(m, 'ZDTaichuBackend'));"
        "assert callable(getattr(m, 'load_zdtaichu_runtime'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(src_root)},
    )
    assert result.returncode == 0, result.stderr
