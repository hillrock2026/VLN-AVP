"""Real ZDTaichu5.0-9B backend over the verified call contract.

This is the one place the real model is actually driven: it implements
:class:`~vln.vlm.zdtaichu_client.InferenceBackend` and turns a
:class:`~vln.vlm.zdtaichu_client.PreparedObservation` plus an instruction into
the model's **raw text**, and nothing else. It never builds an ``AgentIntent``,
never repairs JSON, never touches the host or IPC layer and never widens the
model-output contract.

The call chain is the one confirmed in ``M1-VLN-MODEL-06A`` for the pinned
revision ``bc125a98…``::

    messages -> processor.from_messages(..., return_tensors="pt")
             -> model.generate(**inputs, max_new_tokens=..., do_sample=...)
             -> output_ids[:, prompt_len:]        # drop the input tokens
             -> processor.batch_decode(..., skip_special_tokens=True)

``processor.from_messages`` has no channel to the Jinja renderer (its
``**kwargs`` go to the processor, not the template), so the ``enable_thinking``
switch cannot be reached through it. The opt-in ``ZDTaichuBackend.enable_thinking``
path renders the template via ``processor.apply_chat_template`` instead - see
:func:`_prepare_inputs_with_thinking`; ``None`` leaves the call chain above
unchanged.

``torch`` / ``transformers`` are imported **only** inside
:func:`load_zdtaichu_runtime`, so importing this module, constructing a backend
or collecting tests loads no model stack. The runtime is supplied through an
injected zero-argument factory and created lazily, at most once, on the first
:meth:`ZDTaichuBackend.generate` - mirroring :class:`ZDTaichuModelClient`.

Safety boundaries:

* **No implicit network input.** ``vision_utils.fetch_image`` issues
  ``requests.get`` for ``http(s)://`` image values, so this adapter refuses any
  ``str`` image part outright (URL *or* local path) and any raw ``bytes``; only
  in-memory image objects (for example a PIL image) reach the processor.
* **Fail closed.** Every load / processor / generate / slice / decode failure
  becomes a :class:`~vln.vlm.model_client.ModelCallError`; raw text is never
  fabricated, and an empty (EOS) decode is returned verbatim as the loop's
  explicit stop signal rather than being "repaired".
* **No output repair.** The decoded text is returned exactly as produced; the
  thinking-block / strict-JSON conflict is left to the owner's decision and is
  deliberately *not* worked around here.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from typing import Callable, Optional

from .model_client import ModelCallError
from .zdtaichu_client import PreparedObservation

__all__ = [
    "MODEL_ID",
    "MODEL_REVISION",
    "DEFAULT_MAX_NEW_TOKENS",
    "DEFAULT_DO_SAMPLE",
    "ZDTaichuRuntime",
    "UntrustedImageInputError",
    "ZDTaichuBackend",
    "load_zdtaichu_runtime",
]

#: The official model repository (weights + config + custom code).
MODEL_ID = "TaichuAI/ZDTaichu5.0-9B"

#: The immutable model-repository revision confirmed by M1-VLN-MODEL-06A. A
#: commit SHA is pinned deliberately: ``main``/``master`` are movable.
MODEL_REVISION = "bc125a9819a421755f4dcebe498eb81c139b65a3"

#: Generation defaults, taken from the official README example for the pinned
#: revision. ``generation_config.json`` ships ``do_sample=true`` instead; the
#: two differ and the runtime behaviour is unverified, so both are exposed as
#: plain constructor parameters rather than hidden defaults.
DEFAULT_MAX_NEW_TOKENS = 1024
DEFAULT_DO_SAMPLE = False


class UntrustedImageInputError(ModelCallError):
    """An image part was refused before it could reach the processor.

    Subclasses :class:`~vln.vlm.model_client.ModelCallError`, so the pipeline's
    existing fail-closed handling applies unchanged. Raised for a ``str`` image
    value (a remote URL would make ``vision_utils`` issue ``requests.get``, and
    a bare path is not part of the accepted input vocabulary) and for raw
    ``bytes`` (never auto-detected as an image).
    """


@dataclass
class ZDTaichuRuntime:
    """A loaded processor + model pair, as produced by :func:`load_zdtaichu_runtime`.

    Deliberately structural: this module never inspects or imports the concrete
    ``transformers`` types, so tests can inject any object pair with the same
    duck-typed surface.
    """

    processor: object
    model: object


def _default_inference_context() -> AbstractContextManager:
    """Return ``torch.inference_mode()`` for the real path.

    ``torch`` is imported here, not at module scope. If it is unavailable the
    caller cannot have produced a :class:`ZDTaichuRuntime` anyway, so a no-op
    context is returned instead of raising at construction time.
    """

    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return nullcontext()
    return torch.inference_mode()


def load_zdtaichu_runtime(
    model_id: str = MODEL_ID,
    revision: str = MODEL_REVISION,
    *,
    use_fast: bool = False,
    torch_dtype: str = "bfloat16",
    device_map: str = "auto",
    attn_implementation: str = "sdpa",
    trust_remote_code: bool = True,
) -> ZDTaichuRuntime:
    """Load the processor and model for the pinned revision.

    This is the **only** function in this module that imports the inference
    stack, and it is never called from module import, construction or test
    collection - only when a caller installs it as the backend's
    ``runtime_factory`` and a real :meth:`ZDTaichuBackend.generate` runs. It
    must not be invoked before dependency installation, asset acquisition and
    ``trust_remote_code`` execution are separately authorised.

    The keyword defaults mirror the official README example for the pinned
    revision (``torch_dtype=bfloat16``, ``device_map="auto"``,
    ``attn_implementation="sdpa"``); none of them has been runtime-verified.
    """

    import torch  # type: ignore[import-not-found]
    from transformers import AutoModel, AutoProcessor  # type: ignore[import-not-found]

    dtype = getattr(torch, torch_dtype)
    processor = AutoProcessor.from_pretrained(
        model_id,
        revision=revision,
        trust_remote_code=trust_remote_code,
        use_fast=use_fast,
    )
    model = AutoModel.from_pretrained(
        model_id,
        revision=revision,
        trust_remote_code=trust_remote_code,
        torch_dtype=dtype,
        device_map=device_map,
        attn_implementation=attn_implementation,
    ).eval()
    return ZDTaichuRuntime(processor=processor, model=model)


def _reject_untrusted_image(image: object, index: int) -> None:
    """Refuse any image part that could trigger a network fetch or type confusion."""

    if isinstance(image, str):
        stripped = image.strip().lower()
        if stripped.startswith("http://") or stripped.startswith("https://"):
            raise UntrustedImageInputError(
                f"image[{index}] is a remote URL; the ZDTaichu processor would "
                "fetch it over the network, which this adapter refuses"
            )
        raise UntrustedImageInputError(
            f"image[{index}] is a string path; only in-memory image objects "
            "(for example a PIL image) are accepted, so no path or URL reaches "
            "the processor"
        )
    if isinstance(image, (bytes, bytearray)):
        raise UntrustedImageInputError(
            f"image[{index}] is raw bytes; bytes are not auto-detected as an image"
        )


def _build_messages(observation: object, instruction: str) -> list:
    """Turn a ``PreparedObservation`` + instruction into Qwen-style messages."""

    messages, _images = _build_message_parts(observation, instruction)
    return messages


def _build_message_parts(observation: object, instruction: str) -> tuple:
    """Validate the input and return ``(messages, accepted_images)``.

    ``accepted_images`` holds only the image objects that survived
    :func:`_reject_untrusted_image`. The default path does not need them
    (``from_messages`` loads the images itself), but the explicit-thinking path
    calls the processor directly and so must pass them along.
    """

    text = getattr(observation, "text", None)
    images = getattr(observation, "images", None)
    if type(text) is not str:
        raise ModelCallError(
            "ZDTaichu backend expects PreparedObservation.text to be a str, got "
            f"{type(text).__name__}"
        )
    if not isinstance(images, (tuple, list)):
        raise ModelCallError(
            "ZDTaichu backend expects PreparedObservation.images to be a sequence, "
            f"got {type(images).__name__}"
        )
    if type(instruction) is not str:
        raise ModelCallError(
            f"instruction must be a str, got {type(instruction).__name__}"
        )

    content: list = []
    accepted: list = []
    for index, image in enumerate(images):
        _reject_untrusted_image(image, index)
        accepted.append(image)
        content.append({"type": "image", "image": image})

    parts = [part for part in (text, instruction) if part]
    if not parts and not content:
        raise ModelCallError("empty ZDTaichu input: no text and no images")
    content.append({"type": "text", "text": "\n".join(parts)})
    return [{"role": "user", "content": content}], accepted


def _prepare_inputs_with_thinking(
    processor: object, messages: list, images: list, enable_thinking: bool
):
    """Render the chat template with an explicit thinking switch, then process.

    ``processor.from_messages`` cannot carry ``enable_thinking``: the model's
    ``processing.py`` renders the template with
    ``tokenizer.apply_chat_template(messages, tokenize=False,
    add_generation_prompt=True, add_vision_id=...)`` and forwards its
    ``**kwargs`` to the processor instead of to the template, so the flag never
    reaches the Jinja renderer. ``ProcessorMixin.apply_chat_template`` *does*
    route unknown kwargs to it (transformers 5.3.0 ``processing_utils.py:1714``
    then ``:1799-1804``), which is the layer called here. The remaining steps
    mirror the model's own call shape (``processing.py:516-523``) so the batch
    keeps the same keys.
    """

    prompt = processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        add_vision_id=True,
        enable_thinking=enable_thinking,
    )
    if type(prompt) is not str or not prompt.strip():
        raise ModelCallError("chat template produced no prompt text")
    return processor(
        images=list(images),
        text=prompt,
        videos=None,
        return_tensors="pt",
        videos_kwargs={},
    )


def _move_to_model_device(inputs: object, model: object):
    """Move the processor output onto the model's device, if it supports ``.to``."""

    to = getattr(inputs, "to", None)
    device = getattr(model, "device", None)
    if device is None or not callable(to):
        return inputs
    return to(device)


def _strip_prompt_tokens(output_ids: object, inputs: object):
    """Drop the prompt tokens: ``output_ids[:, prompt_len:]``."""

    try:
        input_ids = inputs["input_ids"]
    except Exception as exc:
        raise ModelCallError(
            "processor output has no 'input_ids'; cannot locate the prompt boundary"
        ) from exc

    shape = getattr(input_ids, "shape", None)
    if shape is None or len(shape) < 2:
        raise ModelCallError(
            "processor 'input_ids' has no 2-D shape; cannot locate the prompt boundary"
        )
    prompt_len = shape[1]
    if not isinstance(prompt_len, int) or prompt_len < 0:
        raise ModelCallError(
            f"processor prompt length is not a non-negative int: {prompt_len!r}"
        )

    try:
        generated = output_ids[:, prompt_len:]
    except Exception as exc:
        raise ModelCallError(
            "model output is not sliceable; cannot strip the prompt tokens"
        ) from exc
    if generated is None:
        raise ModelCallError("stripping the prompt tokens produced no token sequence")
    return generated


def _first_decoded_text(texts: object) -> str:
    """Return ``texts[0]`` after checking ``batch_decode`` returned decoded strings."""

    if texts is None or not isinstance(texts, (list, tuple)) or len(texts) == 0:
        raise ModelCallError(
            "processor.batch_decode returned no decoded text "
            f"({type(texts).__name__})"
        )
    first = texts[0]
    if type(first) is not str:
        raise ModelCallError(
            f"decoded text is {type(first).__name__}, expected str"
        )
    return first


@dataclass
class ZDTaichuBackend:
    """A real :class:`InferenceBackend` over an injected ZDTaichu runtime.

    ``runtime_factory`` is called at most once, on the first :meth:`generate`,
    and cached - so constructing a backend loads no model. If loading fails the
    cached slot stays empty and the next :meth:`generate` retries, matching
    :class:`~vln.vlm.zdtaichu_client.ZDTaichuModelClient`.

    ``inference_context`` isolates the one torch-specific concern
    (``torch.inference_mode()``) so tests can run without torch.

    ``enable_thinking`` is the explicit chat-template switch. ``None`` (the
    default) keeps the official ``from_messages`` path exactly as it was, in
    which the template's own default applies (the pinned template renders
    ``<think>\\n``, i.e. thinking on). ``False`` renders the empty thinking block
    and ``True`` renders it open; both go through
    :func:`_prepare_inputs_with_thinking`, because ``from_messages`` has no
    channel that reaches the template renderer.
    """

    runtime_factory: Callable[[], ZDTaichuRuntime]
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS
    do_sample: bool = DEFAULT_DO_SAMPLE
    enable_thinking: Optional[bool] = None
    inference_context: Callable[[], AbstractContextManager] = _default_inference_context
    _runtime: Optional[ZDTaichuRuntime] = field(
        default=None, init=False, repr=False, compare=False
    )

    def generate(self, observation: PreparedObservation, instruction: str) -> str:
        """Return the model's raw text for ``observation`` + ``instruction``."""

        messages, images = _build_message_parts(observation, instruction)
        runtime = self._load_runtime()
        processor, model = runtime.processor, runtime.model

        if self.enable_thinking is None:
            try:
                inputs = processor.from_messages(messages, return_tensors="pt")
            except ModelCallError:
                raise
            except Exception as exc:
                raise ModelCallError(
                    f"processor.from_messages failed: {exc}"
                ) from exc
        else:
            try:
                inputs = _prepare_inputs_with_thinking(
                    processor, messages, images, self.enable_thinking
                )
            except ModelCallError:
                raise
            except Exception as exc:
                raise ModelCallError(
                    f"explicit chat-template input preparation failed: {exc}"
                ) from exc

        try:
            inputs = _move_to_model_device(inputs, model)
        except ModelCallError:
            raise
        except Exception as exc:
            raise ModelCallError(f"moving inputs to the model device failed: {exc}") from exc

        try:
            with self.inference_context():
                output_ids = model.generate(
                    **inputs,
                    max_new_tokens=self.max_new_tokens,
                    do_sample=self.do_sample,
                )
        except ModelCallError:
            raise
        except Exception as exc:
            raise ModelCallError(f"model.generate failed: {exc}") from exc

        generated = _strip_prompt_tokens(output_ids, inputs)

        try:
            texts = processor.batch_decode(generated, skip_special_tokens=True)
        except ModelCallError:
            raise
        except Exception as exc:
            raise ModelCallError(f"processor.batch_decode failed: {exc}") from exc

        return _first_decoded_text(texts)

    def _load_runtime(self) -> ZDTaichuRuntime:
        """Return the cached runtime, loading it at most once on success."""

        if self._runtime is None:
            try:
                runtime = self.runtime_factory()
            except ModelCallError:
                raise
            except Exception as exc:
                raise ModelCallError(f"model runtime load failed: {exc}") from exc
            if runtime is None or not hasattr(runtime, "processor") or not hasattr(
                runtime, "model"
            ):
                raise ModelCallError(
                    "model runtime factory did not return a ZDTaichuRuntime "
                    f"(got {type(runtime).__name__})"
                )
            self._runtime = runtime
        return self._runtime
