"""NAV-11A: one model-input boundary for image + instruction + feedback.

``run_parking_loop`` already hands the previous round's real
:class:`~vln.ipc.envelope.Response` to the next model call, but the image
client only accepted a local image path and therefore could not receive that
feedback. This module adds the missing composition without changing the loop's
iteration or stop rules:

* :class:`VisualLoopModelClient` implements the existing ``ModelClient``
  protocol. A path-like observation is the first round and takes the unchanged
  image-only path. A ``Response`` observation is a later round: it is encoded by
  the existing :class:`~vln.observation.CompositeObservationEncoder` (which
  delegates to :class:`~vln.observation.ResponseFeedbackEncoder`) and passed as
  text context to the existing image client, while the image itself still goes
  through the existing multimodal image field. If the encoder refuses the
  response, the model call fails with
  :class:`~vln.observation.FeedbackEncodingError` **before** any image request;
  no empty, stale or fabricated feedback is substituted.
* :func:`run_visual_parking_loop` composes that model with the existing
  :func:`~vln.pipeline.run_parking_loop` and the NAV-10 execution half
  (:func:`~vln.nav_execution.execute_visual_decision`), so every round uses the
  NAV-09 three layers and the existing IPC/Host path.

This is input wiring only. It does not add a new stop policy, retry, pose
source, persistence, threading or lifecycle framework. The caller supplies the
pose (simulated/test-only in this project) and both IDs. The image remains the
same current frame on feedback rounds; a future multi-camera/round-source task
must supply a new ``image_path`` per round.

STM-01 adds an optional, explicitly enabled short-term memory. When a
``NavigationTaskMemory`` is supplied, each completed round is recorded and the
bounded history summary is appended to the next round's model text as its own
section, after the real previous ``Response`` feedback. ``memory=None`` keeps
the pre-STM behavior exactly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from vln.client import HostClient, build_request
from vln.intent import AgentIntentError
from vln.ipc.envelope import Request, Response
from vln.nav import VehiclePose
from vln.nav_execution import NavigationExecutionError, execute_visual_decision
from vln.observation import CompositeObservationEncoder, FeedbackEncodingError
from vln.pipeline import DEFAULT_MAX_ROUNDS, ParkingLoopResult, run_parking_loop
from vln.stm import NavigationTaskMemory
from vln.vlm import ModelCallError, ModelClient, ObservationEncoder
from vln.vlm.image_path_client import ServerImageModelClient

__all__ = [
    "MissingRoundObservationError",
    "VisualLoopModelClient",
    "run_visual_parking_loop",
]


class MissingRoundObservationError(ModelCallError, ValueError):
    """No visual observation was supplied for the requested round.

    Raised instead of silently reusing the previous image. A missing per-round
    observation is a caller error, not a reason to fabricate continuity. It is a
    ``ModelCallError`` subclass so the existing fail-closed loop propagates it
    unchanged instead of wrapping it as an inference failure.
    """


@dataclass
class VisualLoopModelClient:
    """A ``ModelClient`` that keeps the image and adds previous-round feedback.

    Observation contract:

    * a path-like observation (round 0) -> the legacy image-only call;
    * a real :class:`Response` (round 1+) -> the response is encoded by the
      injected ``feedback_encoder`` and appended after the current instruction
      by the existing image client.

    With ``image_paths`` set, each model call consumes one entry in order, so
    round 0 can use image A and round 1 image B. A missing entry raises
    :class:`MissingRoundObservationError`; the previous image is never reused.
    With ``image_paths=None`` the pre-NAV-14 single-image behavior is preserved.

    The image path is never put into the text; the image bytes still travel via
    the server client's multimodal image field.
    """

    image_path: str
    image_client: ServerImageModelClient = field(
        default_factory=ServerImageModelClient
    )
    feedback_encoder: ObservationEncoder = field(
        default_factory=CompositeObservationEncoder
    )
    #: Optional per-round observations, in call order. ``None`` preserves the
    #: pre-NAV-14 single-image behavior: round 0 uses ``image_path`` and every
    #: feedback round reuses it. A non-empty sequence makes each model call
    #: consume exactly one entry; running past the end raises
    #: :class:`MissingRoundObservationError` instead of reusing the last image.
    image_paths: Optional[Sequence[str]] = None
    #: Optional application-level STM. ``None`` preserves the pre-STM input
    #: exactly: only the real previous Response feedback is appended.
    stm: Optional[NavigationTaskMemory] = None
    _call_index: int = field(default=0, init=False, repr=False)

    def reset_observations(self) -> None:
        """Start a new loop at the first per-round observation."""

        self._call_index = 0

    def _round_image(self, observation: object) -> object:
        """Return the image input for the next model call.

        With ``image_paths`` set, the call index is authoritative and a missing
        entry raises. Without it, the legacy rule is preserved: a path
        observation is used as-is; a feedback round uses ``image_path``.
        """

        if self.image_paths is None:
            return observation if not isinstance(observation, Response) else self.image_path

        if self._call_index >= len(self.image_paths):
            raise MissingRoundObservationError(
                f"no visual observation for round {self._call_index}: "
                f"image_paths has {len(self.image_paths)} entries"
            )
        image_path = self.image_paths[self._call_index]
        self._call_index += 1
        if not isinstance(image_path, (str, os.PathLike)):
            raise MissingRoundObservationError(
                f"image_paths[{self._call_index - 1}] is not a path-like value: "
                f"{type(image_path).__name__}"
            )
        path = os.fspath(image_path)
        if not isinstance(path, str) or path.strip() == "":
            raise MissingRoundObservationError(
                f"image_paths[{self._call_index - 1}] must be a non-blank path"
            )
        return path

    def generate(self, observation: object, instruction: str) -> str:
        """Return raw model text for this round's image/instruction/feedback."""

        if isinstance(observation, Response):
            try:
                prepared = self.feedback_encoder.encode(observation)
            except FeedbackEncodingError:
                raise
            except ModelCallError as exc:
                # The feedback encoder refused this real Response. Stop before
                # the image/HTTP call: never substitute empty or stale feedback.
                raise FeedbackEncodingError(
                    f"feedback encoding failed: {exc}"
                ) from exc
            context_text = None
            if self.stm is not None:
                context_text = self.stm.render_context()
            return self.image_client.generate_with_feedback(
                self._round_image(observation),
                instruction,
                prepared.text,
                context_text=context_text,
            )
        return self.image_client.generate(self._round_image(observation), instruction)


def run_visual_parking_loop(
    *,
    model: ModelClient,
    image_path: Optional[str] = None,
    image_paths: Optional[Sequence[str]] = None,
    instruction: str,
    expected_identity: str,
    pose: VehiclePose,
    host_client_factory: Callable[[], HostClient],
    intent_id_factory: Callable[[int], str],
    request_id_factory: Callable[[int], str],
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    request_builder: Callable[..., Request] = build_request,
    memory: Optional[NavigationTaskMemory] = None,
) -> ParkingLoopResult:
    """Run the existing loop with per-round NAV-09 -> NAV-10 execution.

    Round 0's model observation is ``image_path``. Every later observation is
    the previous round's **real** Response, exactly as
    :func:`~vln.pipeline.run_parking_loop` already hands it over. The injected
    ``round_executor`` runs :func:`~vln.nav_execution.execute_visual_decision`
    (NAV-09 layers, existing request builder, existing HostClient) and returns
    that round's actual Response. The loop's existing stop rules are unchanged.

    ``intent_id_factory(round_index)`` and ``request_id_factory(round_index)``
    are caller-owned and independent. No retry is performed anywhere.

    ``image_paths`` is the optional per-round observation sequence. When it is
    supplied, round 0 uses ``image_paths[0]``, round 1 uses ``image_paths[1]``,
    and so on; a missing entry raises :class:`MissingRoundObservationError`.
    When it is omitted, the old single-image behavior is preserved exactly
    (``image_path`` for round 0 and every feedback round). ``image_path`` may be
    omitted only when ``image_paths`` supplies the first image.

    ``memory`` is the explicit STM switch. ``None`` keeps the pre-STM behavior
    exactly. When a :class:`~vln.stm.NavigationTaskMemory` is supplied, every
    executed/refused/uncertain round updates it, and the next round's model
    input reads its bounded history summary. STM injection requires a
    :class:`VisualLoopModelClient`, because that is the existing input seam
    where the labelled history section is appended.
    """

    if image_paths is None and isinstance(model, VisualLoopModelClient):
        # A model can own the per-round sequence directly.
        image_paths = model.image_paths
    if image_paths is not None:
        if not isinstance(model, VisualLoopModelClient):
            raise ValueError(
                "per-round image observations require a VisualLoopModelClient"
            )
        if isinstance(image_paths, (str, bytes)):
            raise ValueError("image_paths must be a sequence of paths, not a string")
        normalized = tuple(image_paths)
        if not normalized:
            raise ValueError("image_paths must contain at least one path")
        for index, path in enumerate(normalized):
            if not isinstance(path, (str, os.PathLike)):
                raise ValueError(
                    f"image_paths[{index}] must be a path-like value"
                )
            if not isinstance(os.fspath(path), str) or os.fspath(path).strip() == "":
                raise ValueError(f"image_paths[{index}] must be a non-blank path")
        if image_path is None:
            image_path = os.fspath(normalized[0])
        elif image_path != os.fspath(normalized[0]):
            raise ValueError(
                "image_path must equal image_paths[0] when both are supplied"
            )
        if model.image_paths is not None and tuple(model.image_paths) != normalized:
            raise ValueError(
                "model.image_paths and the loop's image_paths must match"
            )
        model.image_paths = normalized
        model.reset_observations()
    elif image_path is None:
        raise ValueError("image_path or image_paths is required")

    if isinstance(model, VisualLoopModelClient) and model.image_path != image_path:
        # Round 0 would use ``image_path`` while feedback rounds would use the
        # model's own path; refuse the silent image mismatch.
        raise ValueError(
            "VisualLoopModelClient.image_path must match the loop's image_path"
        )

    if memory is not None:
        if not isinstance(model, VisualLoopModelClient):
            raise ValueError(
                "STM requires a VisualLoopModelClient so the history summary "
                "can be added to the model input"
            )
        if model.stm is None:
            model.stm = memory
        elif model.stm is not memory:
            raise ValueError(
                "model.stm and the loop's memory must be the same "
                "NavigationTaskMemory object"
            )
    elif isinstance(model, VisualLoopModelClient):
        memory = model.stm

    def _round_executor(raw_text: str, round_index: int) -> Response:
        try:
            execution = execute_visual_decision(
                raw_text,
                expected_identity=expected_identity,
                pose=pose,
                intent_id=intent_id_factory(round_index),
                request_id=request_id_factory(round_index),
                host_client_factory=host_client_factory,
                request_builder=request_builder,
            )
        except AgentIntentError as exc:
            # The NAV-09/validation layers refused the model text before any
            # Host work. Record the refused round, then let the existing loop
            # map it to INVALID_OUTPUT.
            if memory is not None:
                memory.record_unsubmitted(round_index=round_index, error=exc)
            raise
        except NavigationExecutionError as exc:
            # A real Response existed but could not be trusted as this
            # request's execution. Keep that Response in the ledger.
            if memory is not None:
                request = exc.request
                memory.record_uncertain(
                    round_index=round_index,
                    request_id=(
                        request.request_id if request is not None else None
                    ),
                    response=exc.response,
                    error=exc,
                )
            raise
        except Exception as exc:
            # Transport/termination failures may have happened after the
            # request reached the host. Record the uncertainty; never mark it
            # as success.
            if memory is not None:
                memory.record_uncertain(
                    round_index=round_index,
                    request_id=None,
                    response=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            raise

        if memory is not None:
            memory.record_execution(execution, round_index=round_index)
        return execution.response

    try:
        result = run_parking_loop(
            model=model,
            observation=image_path,
            instruction=instruction,
            host_client_factory=host_client_factory,
            request_id_factory=request_id_factory,
            max_rounds=max_rounds,
            request_builder=request_builder,
            round_executor=_round_executor,
        )
    except Exception:
        if memory is not None:
            memory.mark_stopped("exception")
        raise
    if memory is not None:
        memory.mark_stopped(result.stop_reason)
    return result
