"""ZDTaichu5.0-9B adapter: the minimal, offline-verifiable model seam.

This module implements the existing :class:`~vln.vlm.model_client.ModelClient`
protocol over a ZDTaichu5.0-9B backend. It is the *only* new place the model is
invoked, and it stays inside the same boundary as :mod:`vln.vlm.model_client`:
it turns an observation plus an instruction into the model's **raw text** and
nothing else. It does **not** parse AgentIntent JSON, does **not** repair it,
builds **no** request and never touches the host or the IPC layer.

Two things are deliberately kept apart, because neither has a *verified*
contract in this phase (see ``docs/MODEL_OUTPUT_CONTRACT.md`` §6 and
``docs/M1-05C3A_READ_ONLY_REPORT.txt``):

* the **observation boundary** (:class:`ObservationEncoder`) - how an opaque
  ``observation`` becomes model input. The default encoder is conservative and
  handles only what the current evidence supports; it never guesses and never
  silently drops an input it cannot represent.
* the **backend** (:class:`InferenceBackend`) - the real ``AutoProcessor`` /
  ``AutoModel`` / ``model.generate`` pipeline. It is injected and loaded
  **lazily**, so constructing a client never loads a large model, and the
  offline tests need neither weights, nor ``torch``/``transformers``, nor a GPU.

No real model, weights, network, processor or GPU is used here. A failure to
obtain raw text becomes a :class:`~vln.vlm.model_client.ModelCallError`; raw
text is never fabricated, and an unsupported observation is an explicit
:class:`UnsupportedObservationError` rather than a silent substitution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol, runtime_checkable

from .model_client import ModelCallError

__all__ = [
    "PreparedObservation",
    "ObservationEncoder",
    "DefaultObservationEncoder",
    "InferenceBackend",
    "UnsupportedObservationError",
    "ZDTaichuModelClient",
]


class UnsupportedObservationError(ModelCallError):
    """The observation could not be turned into model input without guessing.

    Subclasses :class:`~vln.vlm.model_client.ModelCallError`, so the existing
    pipeline's fail-closed rule applies unchanged: an unsupported observation is
    a model-boundary failure, never a fabricated success and never a silent
    drop. ``observation_type`` is the offending type's *name* only; the object's
    ``repr`` is never embedded (a host ``Response`` must not be stringified into
    a prompt or mistaken for a frame).
    """

    def __init__(self, observation_type: str) -> None:
        super().__init__(
            "unsupported observation for ZDTaichu input: "
            f"{observation_type}; expected str or a PIL image, or supply an "
            "ObservationEncoder that handles this type"
        )
        self.observation_type = observation_type


@dataclass(frozen=True)
class PreparedObservation:
    """Backend-facing observation: a text part plus zero or more image parts.

    This is deliberately structural: it records *what kind of input* reached the
    model (text and/or images) and nothing about *how* a processor must encode
    it. The ZDTaichu chat template, image resize/normalization and token layout
    are **not** frozen here - a real :class:`InferenceBackend` owns all of that.
    """

    text: str = ""
    images: tuple[object, ...] = ()


@runtime_checkable
class ObservationEncoder(Protocol):
    """Observation -> :class:`PreparedObservation`. The uncertain boundary.

    It is a Protocol so a caller who has *verified* a real image or
    host-feedback conversion contract can supply it, without this module
    claiming a contract it cannot evidence.
    """

    def encode(self, observation: object) -> PreparedObservation:
        """Encode ``observation`` into model input, or raise."""

        ...


def _pil_image_type() -> Optional[type]:
    """Return ``PIL.Image.Image`` if Pillow is importable, else ``None``.

    Pillow is not a declared dependency of this package (``dependencies = []``),
    so the import is deferred: its absence simply means "no image support", and
    importing this module never pulls Pillow in.
    """

    try:
        from PIL.Image import Image  # type: ignore[import-not-found]
    except Exception:
        return None
    return Image


class DefaultObservationEncoder:
    """A conservative encoder with an explicit, closed observation vocabulary.

    Supported, and only these:

    * ``str`` - a text/status observation, carried through verbatim as the text
      part. It is never parsed and never treated as an image.
    * a Pillow ``PIL.Image.Image`` - carried through as the single image part.

    Everything else is rejected with :class:`UnsupportedObservationError` rather
    than guessed at, silently dropped, or stringified. This explicitly includes
    a host ``Response`` (the multi-round feedback object): until its encoding is
    *verified*, the safe action is to refuse, not to invent a prompt from it.
    Image ``bytes`` are likewise not auto-detected on purpose - an arbitrary
    ``bytes`` value is not evidence of an image, and misclassifying it would
    inject non-visual data as a frame.
    """

    def encode(self, observation: object) -> PreparedObservation:
        if type(observation) is str:
            return PreparedObservation(text=observation)
        image_type = _pil_image_type()
        if image_type is not None and isinstance(observation, image_type):
            return PreparedObservation(images=(observation,))
        raise UnsupportedObservationError(type(observation).__name__)


@runtime_checkable
class InferenceBackend(Protocol):
    """The model itself, behind the processing boundary.

    ``generate`` receives the already-encoded observation plus the instruction
    and returns the model's *raw* text. A real implementation (not built in this
    phase) owns ``AutoProcessor`` / ``AutoModel``, the chat template
    (``processor.from_messages``) and ``model.generate``; nothing here calls it.
    """

    def generate(self, observation: PreparedObservation, instruction: str) -> str:
        """Return the model's raw text for ``observation`` + ``instruction``."""

        ...


@dataclass
class ZDTaichuModelClient:
    """A :class:`~vln.vlm.model_client.ModelClient` over a ZDTaichu backend.

    The backend is supplied as a zero-argument ``backend_factory`` and is called
    at most once, on the first :meth:`generate`, then cached - so merely
    constructing a client loads no model. The observation boundary is the
    injected ``encoder`` (defaulting to :class:`DefaultObservationEncoder`).

    :meth:`generate` returns the backend's raw text **verbatim**: it does not
    parse or repair AgentIntent JSON, constructs no request, and cannot reach
    the host. Order of operations is fixed:

    1. encode the observation (a rejected observation raises here, before any
       model is loaded or called);
    2. lazily obtain the backend;
    3. call the backend and return its text, after checking it really is a
       ``str``.

    Every failure to obtain that text - load, encode or inference - surfaces as
    a :class:`ModelCallError` (or the more specific
    :class:`UnsupportedObservationError`), never as fabricated text.
    """

    backend_factory: Callable[[], InferenceBackend]
    encoder: ObservationEncoder = field(default_factory=DefaultObservationEncoder)
    _backend: Optional[InferenceBackend] = field(
        default=None, init=False, repr=False, compare=False
    )

    def generate(self, observation: object, instruction: str) -> str:
        """Return the backend's raw text for ``observation`` + ``instruction``."""

        try:
            prepared = self.encoder.encode(observation)
        except ModelCallError:
            raise
        except Exception as exc:  # the encoder is a replaceable boundary
            raise ModelCallError(f"observation encoding failed: {exc}") from exc

        backend = self._load_backend()

        try:
            raw_text = backend.generate(prepared, instruction)
        except ModelCallError:
            raise
        except Exception as exc:  # the model call is an untrusted boundary
            raise ModelCallError(f"model inference failed: {exc}") from exc

        if type(raw_text) is not str:
            raise ModelCallError(
                "model backend returned "
                f"{type(raw_text).__name__}, expected str"
            )
        return raw_text

    def _load_backend(self) -> InferenceBackend:
        """Return the cached backend, loading it at most once."""

        if self._backend is None:
            try:
                self._backend = self.backend_factory()
            except ModelCallError:
                raise
            except Exception as exc:  # an untrusted external boundary
                raise ModelCallError(f"model backend load failed: {exc}") from exc
        return self._backend
