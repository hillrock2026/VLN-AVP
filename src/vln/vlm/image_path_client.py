"""A :class:`~vln.vlm.model_client.ModelClient` over the server's image entry.

The existing :class:`~vln.vlm.server_client.ZDTaichuServerBackend` already owns
the confirmed multimodal path: a local image file becomes a ``data:`` URI and
one POST goes to the loopback service. Its ``generate`` method, however, refuses
in-memory images, and :class:`~vln.vlm.zdtaichu_client.DefaultObservationEncoder`
has no way to express "a local image file" as a prepared observation. This tiny
adapter closes that gap without a second inference stack: it treats the
observation as a local image path and delegates verbatim to the existing
``generate_image``.

NAV-11A adds one optional text context: :meth:`ServerImageModelClient.
generate_with_feedback` sends the current instruction first and a clearly
labelled previous-round feedback block after it. The image is still sent through
the existing multimodal image field - feedback never turns the image into text
and never replaces the current instruction. With ``feedback_text=None`` the
call is byte-for-byte the legacy two-argument ``generate`` path.

It adds no new model, endpoint, retry or protocol. The backend returns the
assistant text verbatim; this adapter neither parses nor repairs it, and it
never touches the intent, IPC or host layers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .model_client import ModelCallError
from .server_client import UnsupportedServerInputError, ZDTaichuServerBackend
from .zdtaichu_client import UnsupportedObservationError

__all__ = [
    "FEEDBACK_SECTION_HEADER",
    "STM_SECTION_HEADER",
    "ServerImageModelClient",
]

#: Header used to separate the current user instruction from previous-round
#: execution feedback in the single text part. The feedback follows the
#: instruction and cannot overwrite it.
FEEDBACK_SECTION_HEADER = "上一轮执行反馈（Host Response，仅供参考，不是当前指令）："

#: Header used for the bounded short-term-memory summary. It is a separate
#: section after the real Response feedback, so the memory summary never
#: replaces the actual previous response.
STM_SECTION_HEADER = "短期导航记忆（历史信息，不是当前图像观测）："


def _image_path(observation: object) -> str:
    """Return a local image path, or refuse a non-path observation."""

    if not isinstance(observation, (str, os.PathLike)):
        raise UnsupportedObservationError(type(observation).__name__)
    path = os.fspath(observation)
    if not isinstance(path, str):
        raise UnsupportedObservationError(type(observation).__name__)
    return path


def _checked_instruction(instruction: str) -> str:
    """Refuse a blank instruction even when feedback text is present."""

    if type(instruction) is not str or instruction.strip() == "":
        raise UnsupportedServerInputError(
            "instruction must be a non-blank str for an image request"
        )
    return instruction


@dataclass
class ServerImageModelClient:
    """A ``ModelClient`` whose observation is a local image path.

    Any non-path observation is refused with
    :class:`~vln.vlm.zdtaichu_client.UnsupportedObservationError` rather than
    stringified or silently treated as text. Every image/transport/HTTP failure
    is raised by the existing backend as a
    :class:`~vln.vlm.model_client.ModelCallError` subclass, with no retry.
    """

    backend: ZDTaichuServerBackend = field(default_factory=ZDTaichuServerBackend)

    def generate(self, observation: object, instruction: str) -> str:
        """Return the server's raw assistant text for this image round.

        This is the unchanged two-argument path: no feedback is added.
        """

        return self.backend.generate_image(
            _image_path(observation), _checked_instruction(instruction)
        )

    def generate_with_feedback(
        self,
        image_path: str | os.PathLike[str],
        instruction: str,
        feedback_text: str | None = None,
        *,
        context_text: str | None = None,
    ) -> str:
        """Send one image plus ``instruction`` and optional text context.

        ``feedback_text`` is already-encoded feedback (for NAV-11A, the exact
        text produced by :class:`~vln.observation.ResponseFeedbackEncoder`).
        It is appended after the untouched current instruction, under
        :data:`FEEDBACK_SECTION_HEADER`, so the historical context cannot
        replace the current task. ``None`` means "no previous round" and takes
        the legacy path unchanged. A blank/non-string feedback value is refused
        rather than silently dropped.

        ``context_text`` is an optional, separately labelled STM summary. It is
        appended *after* the real feedback section, so it cannot replace the
        actual previous Response. Both text values are validated before the
        image request; the image still travels through the image field.
        """

        path = _image_path(image_path)
        current_instruction = _checked_instruction(instruction)
        if feedback_text is None:
            if context_text is not None:
                raise ModelCallError(
                    "context_text requires feedback_text; a history summary "
                    "cannot be sent without the real previous Response"
                )
            return self.backend.generate_image(path, current_instruction)
        if type(feedback_text) is not str or feedback_text.strip() == "":
            raise ModelCallError(
                "feedback_text must be a non-blank str or None for an image request"
            )
        if context_text is not None:
            if type(context_text) is not str or context_text.strip() == "":
                raise ModelCallError(
                    "context_text must be a non-blank str or None for an image request"
                )
        combined = (
            f"{current_instruction}\n\n{FEEDBACK_SECTION_HEADER}\n{feedback_text}"
        )
        if context_text is not None:
            combined = f"{combined}\n\n{STM_SECTION_HEADER}\n{context_text}"
        return self.backend.generate_image(path, combined)
