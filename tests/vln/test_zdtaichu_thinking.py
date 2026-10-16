"""Offline checks for the explicit thinking switch and the input contract.

Two repair items from ``M1-VLN-REAL-MODEL-05A-R1`` are covered here, entirely
offline - no model, no weights, no ``torch``/``transformers``, no processor:

* **thinking parameter passing.** ``processor.from_messages`` forwards its
  ``**kwargs`` to the processor, not to the Jinja renderer, so ``enable_thinking``
  can never reach the template through it. ``ZDTaichuBackend.enable_thinking``
  therefore routes through ``processor.apply_chat_template``; these tests prove
  the flag arrives at *that* call and that the template renders the expected
  text for the on / off / unspecified cases.
* **smoke-test input contract.** The script proposed in 05A passed an empty
  observation and an empty instruction, which fails validation before any model
  is loaded. The first test pins that behaviour (fail-closed, factory never
  called) and the second pins the corrected, contract-valid form.

Everything here is a fake-runtime test except the template-render test, which
reads the local ``chat_template.jinja`` as a text file and renders it with
Jinja2 - it loads no model code and downloads nothing. Template rendering is
verified at the template level only; the end-to-end behaviour of the real
processor is ``NOT_EXECUTED``.
"""

from __future__ import annotations

import pathlib

import pytest

from vln.vlm.model_client import ModelCallError
from vln.vlm.zdtaichu_backend import (
    MODEL_ID,
    MODEL_REVISION,
    ZDTaichuBackend,
    ZDTaichuRuntime,
)
from vln.vlm.zdtaichu_client import PreparedObservation

_REAL_MODEL_DIR = pathlib.Path("/home/gaosong/models/ZDTaichu5.0-9B")
_TEMPLATE = _REAL_MODEL_DIR / "chat_template.jinja"

_VALID_TEXT = '{"contract_version":"1","intent_id":"i","action":"parking.move","target":{"x":0.0,"y":0.0,"heading":0.0}}'


class _InputIds:
    shape = (1, 5)


class _Inputs(dict):
    """Minimal stand-in for a ``BatchFeature``: indexable and ``.to``-able."""

    def __init__(self, prompt_len: int = 5) -> None:
        super().__init__({"input_ids": _InputIds()})
        self._prompt_len = prompt_len

    def to(self, device: object) -> "_Inputs":
        return self


class _OutputIds:
    """Stands in for the generated ids tensor; supports ``ids[:, k:]``."""

    def __init__(self, n_new: int = 2) -> None:
        self._n_new = n_new

    def __getitem__(self, item: object) -> list:
        _row, col = item  # type: ignore[misc]
        assert isinstance(col, slice)
        return [f"tok-{index}" for index in range(self._n_new)]


class _Processor:
    """Records how it was driven; never renders, tokenizes or loads anything."""

    def __init__(
        self,
        *,
        prompt: object = "<rendered prompt>",
        decoded: object = (_VALID_TEXT,),
    ) -> None:
        self._prompt = prompt
        self._decoded = decoded
        self._inputs = _Inputs()
        self.from_messages_calls: list = []
        self.template_calls: list = []
        self.call_calls: list = []
        self.decode_calls: list = []

    def from_messages(self, messages, return_tensors=None, **kwargs):
        self.from_messages_calls.append({"messages": messages, "return_tensors": return_tensors})
        return self._inputs

    def apply_chat_template(self, conversation, **kwargs):
        self.template_calls.append({"conversation": conversation, "kwargs": kwargs})
        return self._prompt

    def __call__(self, **kwargs):
        self.call_calls.append(kwargs)
        return self._inputs

    def batch_decode(self, sequences, skip_special_tokens=False, **kwargs):
        self.decode_calls.append({"sequences": sequences, "skip_special_tokens": skip_special_tokens})
        return self._decoded


class _Model:
    def __init__(self, device: str = "cpu") -> None:
        self.device = device
        self.generate_calls: list = []

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return _OutputIds()


class _Factory:
    def __init__(self, processor: _Processor, model: _Model) -> None:
        self._runtime = ZDTaichuRuntime(processor=processor, model=model)
        self.calls = 0

    def __call__(self) -> ZDTaichuRuntime:
        self.calls += 1
        return self._runtime


class _Harness:
    def __init__(self, **backend_kwargs) -> None:
        self.processor = _Processor()
        self.model = _Model()
        self.factory = _Factory(self.processor, self.model)
        self.backend = ZDTaichuBackend(runtime_factory=self.factory, **backend_kwargs)


# ----------------------------------------------------------------------
# Input contract (05A MAJOR-1)
# ----------------------------------------------------------------------


def test_empty_observation_and_instruction_fail_before_any_load() -> None:
    """The rejected 05A script input: fail-closed, and no model was loaded."""

    h = _Harness(enable_thinking=False)
    with pytest.raises(ModelCallError, match="empty ZDTaichu input"):
        h.backend.generate(PreparedObservation(text=""), "")
    assert h.factory.calls == 0
    assert h.processor.from_messages_calls == []
    assert h.processor.template_calls == []
    assert h.processor.call_calls == []


def test_non_empty_observation_and_instruction_reach_the_processor() -> None:
    """The corrected form: a text observation plus a real instruction passes."""

    h = _Harness(enable_thinking=False)
    raw = h.backend.generate(
        PreparedObservation(text="a parking-lot scene: target slot ahead-left"),
        "park at the target",
    )
    assert raw == _VALID_TEXT
    assert h.factory.calls == 1
    (call,) = h.processor.template_calls
    content = call["conversation"][0]["content"]
    assert content[-1]["type"] == "text"
    assert content[-1]["text"] == (
        "a parking-lot scene: target slot ahead-left\npark at the target"
    )


def test_whitespace_only_observation_is_still_accepted_by_the_contract() -> None:
    """A blank-but-non-empty string is contract-valid; only *empty* input fails."""

    h = _Harness(enable_thinking=False)
    h.backend.generate(PreparedObservation(text=" "), "park")
    assert len(h.processor.template_calls) == 1


# ----------------------------------------------------------------------
# Thinking switch: the flag must reach the layer that renders the template
# ----------------------------------------------------------------------


def test_default_path_is_unchanged_and_never_calls_apply_chat_template() -> None:
    """``enable_thinking=None`` keeps the official ``from_messages`` path."""

    h = _Harness()
    raw = h.backend.generate(PreparedObservation(text="scene"), "park")
    assert raw == _VALID_TEXT
    assert len(h.processor.from_messages_calls) == 1
    assert h.processor.template_calls == []
    assert h.processor.call_calls == []


@pytest.mark.parametrize("value", [False, True])
def test_thinking_flag_is_passed_to_apply_chat_template(value: bool) -> None:
    h = _Harness(enable_thinking=value)
    h.backend.generate(PreparedObservation(text="scene"), "park")
    assert h.processor.from_messages_calls == []
    (call,) = h.processor.template_calls
    kwargs = call["kwargs"]
    assert kwargs["enable_thinking"] is value
    assert kwargs["tokenize"] is False
    assert kwargs["add_generation_prompt"] is True
    assert kwargs["add_vision_id"] is True


def test_processor_call_shape_mirrors_the_official_from_messages_call() -> None:
    """Compare with the model's ``processing.py`` final ``self(...)`` call."""

    h = _Harness(enable_thinking=False)
    h.backend.generate(PreparedObservation(text="scene"), "park")
    (call,) = h.processor.call_calls
    assert call["text"] == "<rendered prompt>"
    assert call["images"] == []
    assert call["videos"] is None
    assert call["return_tensors"] == "pt"
    assert call["videos_kwargs"] == {}


def test_accepted_images_are_forwarded_to_the_processor() -> None:
    class _FakeImage:
        pass

    h = _Harness(enable_thinking=False)
    image = _FakeImage()
    h.backend.generate(PreparedObservation(text="scene", images=(image,)), "park")
    (call,) = h.processor.call_calls
    assert call["images"] == [image]
    (template_call,) = h.processor.template_calls
    assert template_call["conversation"][0]["content"][0] == {
        "type": "image",
        "image": image,
    }


def test_blank_rendered_prompt_is_rejected_rather_than_generated_from() -> None:
    h = _Harness(enable_thinking=False)
    h.processor._prompt = "   "
    with pytest.raises(ModelCallError, match="chat template produced no prompt text"):
        h.backend.generate(PreparedObservation(text="scene"), "park")
    assert h.model.generate_calls == []


def test_template_rendering_failure_is_a_model_call_error() -> None:
    h = _Harness(enable_thinking=False)

    def _boom(*args, **kwargs):
        raise TypeError("template exploded")

    h.processor.apply_chat_template = _boom
    with pytest.raises(ModelCallError, match="explicit chat-template input preparation failed"):
        h.backend.generate(PreparedObservation(text="scene"), "park")


def test_thinking_field_defaults_to_none() -> None:
    from dataclasses import fields

    by_name = {f.name: f for f in fields(ZDTaichuBackend)}
    assert by_name["enable_thinking"].default is None


def test_pinned_model_identity_is_unchanged() -> None:
    assert MODEL_ID == "TaichuAI/ZDTaichu5.0-9B"
    assert MODEL_REVISION == "bc125a9819a421755f4dcebe498eb81c139b65a3"


# ----------------------------------------------------------------------
# Real template text: on / off / unspecified, rendered offline
# ----------------------------------------------------------------------


def _render_template(**extra: object) -> str:
    jinja2 = pytest.importorskip("jinja2")
    if not _TEMPLATE.is_file():
        pytest.skip(f"local chat template not present: {_TEMPLATE}")
    env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
    env.globals["raise_exception"] = lambda message: (_ for _ in ()).throw(
        ValueError(message)
    )
    template = env.from_string(_TEMPLATE.read_text(encoding="utf-8"))
    messages = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    return template.render(
        messages=messages, add_generation_prompt=True, add_vision_id=True, **extra
    )


def test_local_template_renders_an_empty_thinking_block_when_disabled() -> None:
    rendered = _render_template(enable_thinking=False)
    assert rendered.endswith("<think>\n\n</think>\n\n")
    assert not rendered.rstrip().endswith("<think>")


@pytest.mark.parametrize("extra", [{"enable_thinking": True}, {}])
def test_local_template_leaves_thinking_open_otherwise(extra: dict) -> None:
    rendered = _render_template(**extra)
    assert rendered.rstrip().endswith("<think>")
