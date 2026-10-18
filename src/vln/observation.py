"""Host-feedback observation encoding: a real ``Response`` -> model-ready input.

:func:`~vln.pipeline.run_parking_loop` hands the *previous* round's real
:class:`~vln.ipc.envelope.Response` to the next round as its ``observation``.
A real model client still has to turn that object into model input. The default
ZDTaichu encoder deliberately refuses anything that is not a ``str`` or a PIL
image, so the feedback object needs an explicit, deterministic encoding path -
not an implicit stringification of its ``repr``.

This module provides exactly that, and nothing more:

* :class:`ResponseFeedbackEncoder` - encodes a real ``Response`` into a
  deterministic compact-JSON *text* part, and never into an image. Every value
  comes from the response itself: no parking outcome, vehicle pose or new
  camera frame is invented. Free-text fields (``output`` and ``error.message``)
  are truncated at :data:`MAX_FEEDBACK_TEXT_CHARS` with an explicit
  ``truncated`` annotation that keeps the original character count; every other
  field is never truncated.
* :class:`CompositeObservationEncoder` - explicit dispatch: a ``Response`` goes
  to the feedback encoder, everything else is delegated to the existing
  :class:`~vln.vlm.DefaultObservationEncoder`. So ``str`` and PIL images keep
  their exact current behaviour, and every other type still fails through the
  existing :class:`~vln.vlm.UnsupportedObservationError` path. There is no
  catch-and-retry and no silent fallback.

Why this module lives outside :mod:`vln.vlm`: ``vln.vlm`` deliberately has no
dependency on the IPC layer (it defines a model seam, not a host seam). The
feedback encoder needs the ``Response`` type, so it belongs above ``vln.vlm``;
``vln.observation`` imports ``vln.vlm`` (never the reverse), so there is no
import cycle and the adapter's "no IPC import" property is preserved.

The encoding is a *contract*, not a claim: a successful encode is only a
faithful transcription of software feedback. It is neither evidence that a
vehicle parked nor a substitute for real inference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Mapping, Optional

from vln.ipc.envelope import Response
from vln.vlm import (
    DefaultObservationEncoder,
    ModelCallError,
    ObservationEncoder,
    PreparedObservation,
    UnsupportedObservationError,
)

__all__ = [
    "MAX_FEEDBACK_TEXT_CHARS",
    "FeedbackEncodingError",
    "ResponseFeedbackEncoder",
    "CompositeObservationEncoder",
]


class FeedbackEncodingError(ModelCallError):
    """A real ``Response`` could not be encoded into next-round model input.

    Raised by the feedback-aware model client when the production encoder
    refuses the previous round's response. It is a :class:`ModelCallError`
    subclass, so existing fail-closed callers still catch it, but it is
    distinguishable from an inference/service failure: no second model request
    was attempted, and the original encoder failure is chained as
    ``__cause__``. The loop does not fabricate empty or stale feedback.
    """

#: Maximum length, in characters, of a *free-text* feedback field (``output``
#: and ``error.message``). Status, identifier and boolean fields are never
#: truncated. Owner-approved value for M1-VLN-FUNCTION-04.
MAX_FEEDBACK_TEXT_CHARS = 4096

#: Emitted field order, frozen. It is the ``Response``'s own field order plus
#: the derived ``ok`` flag and the truncation annotation; no field is invented
#: and no field is dropped.
_FEEDBACK_FIELDS = (
    "protocol_version",
    "request_id",
    "host_kind",
    "accepted",
    "submission_status",
    "observation_status",
    "execution_status",
    "ok",
    "output",
    "error",
    "truncated",
)

#: ``Response`` attributes re-emitted as-is; each must be a string or ``None``.
_STRING_FIELDS = (
    "protocol_version",
    "request_id",
    "host_kind",
    "submission_status",
    "observation_status",
    "execution_status",
)


def _truncate(text: str, limit: int) -> tuple[str, Optional[int]]:
    """Return ``(value, original_chars)``.

    ``original_chars`` is ``None`` when the text fits; otherwise it is the
    original character count and ``value`` is the exact ``limit``-character
    prefix (no marker characters are injected, so the value stays a faithful
    prefix of the real field).
    """

    if len(text) <= limit:
        return text, None
    return text[:limit], len(text)


@dataclass
class ResponseFeedbackEncoder:
    """Encode a real :class:`Response` into a deterministic text observation.

    It accepts only a ``Response``; anything else is refused with
    :class:`~vln.vlm.UnsupportedObservationError` (a
    :class:`~vln.vlm.ModelCallError`), so an unsupported input can never
    produce a fabricated "successful" feedback.
    """

    max_text_chars: int = MAX_FEEDBACK_TEXT_CHARS

    def encode(self, observation: object) -> PreparedObservation:
        if not isinstance(observation, Response):
            raise UnsupportedObservationError(type(observation).__name__)

        for name in _STRING_FIELDS:
            value = getattr(observation, name)
            if value is not None and not isinstance(value, str):
                raise ModelCallError(
                    f"feedback {name} must be a string or None, "
                    f"got {type(value).__name__}"
                )
        if type(observation.accepted) is not bool:
            raise ModelCallError(
                f"feedback accepted must be a boolean, "
                f"got {type(observation.accepted).__name__}"
            )

        truncated: dict[str, int] = {}

        # Free text: `output`.
        output = observation.output
        if output is not None and not isinstance(output, str):
            raise ModelCallError(
                f"feedback output must be a string or None, "
                f"got {type(output).__name__}"
            )
        if output is None:
            output_value = None
        else:
            output_value, output_cut = _truncate(output, self.max_text_chars)
            if output_cut is not None:
                truncated["output"] = output_cut

        # Free text: `error.message`. `error.code` is a machine code, not free
        # text, so it is carried verbatim and never truncated.
        error = observation.error
        if error is None:
            error_value = None
        elif isinstance(error, Mapping):
            code = error.get("code")
            message = error.get("message")
            if not isinstance(code, str) or not isinstance(message, str):
                raise ModelCallError(
                    "feedback error must be {code: str, message: str}"
                )
            message_value, message_cut = _truncate(message, self.max_text_chars)
            if message_cut is not None:
                truncated["error.message"] = message_cut
            error_value = {"code": code, "message": message_value}
        else:
            raise ModelCallError(
                f"feedback error must be a mapping or None, "
                f"got {type(error).__name__}"
            )

        payload = {
            "protocol_version": observation.protocol_version,
            "request_id": observation.request_id,
            "host_kind": observation.host_kind,
            "accepted": observation.accepted,
            "submission_status": observation.submission_status,
            "observation_status": observation.observation_status,
            "execution_status": observation.execution_status,
            # `Response.ok` is the same software-outcome flag the loop itself
            # uses to decide whether to stop; it is not a navigation claim.
            "ok": observation.ok,
            "output": output_value,
            "error": error_value,
            # Explicit truncation annotation: field -> original character count.
            # Empty when nothing was truncated. Never silently drops feedback.
            "truncated": truncated,
        }

        # A fixed order is guaranteed by building the dict above in order and by
        # not sorting keys; `ensure_ascii=False` is the fixed escaping policy.
        assert tuple(payload) == _FEEDBACK_FIELDS
        try:
            text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise ModelCallError(f"feedback encoding failed: {exc}") from exc

        return PreparedObservation(text=text)


@dataclass
class CompositeObservationEncoder:
    """Explicit type dispatch over the observation boundary.

    * a real :class:`Response` -> the feedback encoder;
    * anything else -> the existing :class:`~vln.vlm.DefaultObservationEncoder`
      (``str`` and PIL images behave exactly as before; every other type still
      raises the existing :class:`~vln.vlm.UnsupportedObservationError`).

    Dispatch is by declared type, not by "try each encoder and fall back": no
    exception is caught here and no unsupported input is silently substituted.
    """

    feedback_encoder: ObservationEncoder = field(
        default_factory=ResponseFeedbackEncoder
    )
    default_encoder: ObservationEncoder = field(
        default_factory=DefaultObservationEncoder
    )

    def encode(self, observation: object) -> PreparedObservation:
        if isinstance(observation, Response):
            return self.feedback_encoder.encode(observation)
        return self.default_encoder.encode(observation)
