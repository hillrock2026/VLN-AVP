"""Minimal Intelligence-side orchestration: model text -> intent -> Host -> Response.

One function wires the existing, independent layers together for a single
parking request:

    model.generate(observation, instruction)   # vln.vlm  -> raw text
      -> parse_model_output(raw_text)          # vln.intent -> validated AgentIntent
      -> build_request(intent, request_id=...) # vln.client -> IPC Request
      -> HostClient.send(request)              # vln.ipc   -> Response

Nothing here re-implements validation, re-parses raw text, or invents protocol
fields: each step delegates to the module that already owns it. The orchestrator
adds only *ordering* and the safety boundary below.

The single hard rule (fail-closed):

    Before :func:`~vln.intent.model_output.parse_model_output` returns a valid
    :class:`~vln.intent.agent_intent.AgentIntent`, this function must NOT build
    an IPC request, must NOT construct a host client, and must NOT call
    ``send``. A model error or a parse/validation error therefore cannot reach
    the host or the runtime.

The dependencies are injectable (``model``, ``host_client_factory`` and
``request_builder``) so a test can substitute a fake host client and a spy
builder and observe the exact call order and call counts, including the zero
counts on a failing parse.

No real model is called and no kernel/host capability beyond the existing
``parking.move`` simulation stub is involved.

:func:`run_parking_intent` above is exactly one round. :func:`run_parking_loop`
adds the minimal *feedback* closure for the same simulated task: it repeats the
round until the model explicitly stops, a round fails, the model output is
invalid, or a hard round cap is reached. The feedback handed to the next round
is the REAL :class:`~vln.ipc.envelope.Response` of the previous round - never a
fabricated value - and a successful software round is never a claim that a
vehicle reached the target (the capability is a simulation stub).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from vln.client import HostClient, build_request
from vln.intent import AgentIntent, AgentIntentError, parse_model_output
from vln.ipc.envelope import Request, Response
from vln.vlm import ModelCallError, ModelClient

__all__ = [
    "run_parking_intent",
    "run_parking_loop",
    "ParkingLoopResult",
    "LoopStopReason",
    "DEFAULT_MAX_ROUNDS",
]


def run_parking_intent(
    *,
    model: ModelClient,
    observation: object,
    instruction: str,
    request_id: str,
    host_client_factory: Callable[[], HostClient],
    request_builder: Callable[..., Request] = build_request,
) -> Response:
    """Run one model -> intent -> host exchange and return the host response.

    Steps (in this order, and no other):

    1. ``model.generate`` obtains the raw model text. A failure here is mapped
       to :class:`~vln.vlm.model_client.ModelCallError` (never fabricated text).
    2. :func:`parse_model_output` validates the raw text into an
       :class:`AgentIntent`. Any parse/shape/validation failure raises before
       any host work is done.
    3. ``request_builder`` maps the validated intent onto an IPC ``Request``.
    4. ``host_client_factory`` builds the host client and ``send`` submits the
       request. The client is used as a context manager (start/close).

    ``request_id`` is the IPC correlation id supplied by the caller; it is not
    derived from ``intent_id`` and carries no idempotency guarantee.
    """

    try:
        raw_text = model.generate(observation, instruction)
    except ModelCallError:
        raise
    except Exception as exc:  # the model call is an untrusted external boundary
        raise ModelCallError(f"model client failed: {exc}") from exc

    # Fail-closed boundary: from here the intent is authoritative or we raise.
    intent: AgentIntent = parse_model_output(raw_text)

    request = request_builder(intent, request_id=request_id)

    with host_client_factory() as client:
        return client.send(request)


# ----------------------------------------------------------------------
# Minimal feedback closure
# ----------------------------------------------------------------------

#: Hard iteration cap for :func:`run_parking_loop`. A small, explicit safety
#: bound so the loop can never run unbounded. It is a *count of rounds*, not a
#: distance, a timeout, or any guarantee about a physical vehicle.
DEFAULT_MAX_ROUNDS = 4


class LoopStopReason:
    """Why :func:`run_parking_loop` returned. Plain string constants, mirroring
    the style of :mod:`vln.ipc.envelope` (``SubmissionStatus`` etc.)."""

    #: The model explicitly declined to act (empty output) - a deliberate stop.
    MODEL_STOP = "model-stop"
    #: A round's real Response was not a success; the loop stops, no recovery.
    EXECUTION_FAILED = "execution-failed"
    #: The model output was not a valid AgentIntent v1; nothing was submitted.
    INVALID_OUTPUT = "invalid-output"
    #: The hard round cap was reached before the model stopped. NOT a success.
    MAX_ROUNDS = "max-rounds"

    ALL = frozenset({MODEL_STOP, EXECUTION_FAILED, INVALID_OUTPUT, MAX_ROUNDS})


@dataclass(frozen=True)
class ParkingLoopResult:
    """The outcome of :func:`run_parking_loop`.

    ``responses`` holds the REAL per-round :class:`~vln.ipc.envelope.Response`
    objects (one per executed round, in order); ``stop_reason`` is a
    :class:`LoopStopReason` value. Reaching ``MAX_ROUNDS`` is explicitly NOT a
    success, and ``MODEL_STOP`` means the *model* chose to stop - it never
    asserts that a vehicle reached or occupied a target.
    """

    responses: tuple[Response, ...]
    stop_reason: str

    @property
    def last_response(self) -> Optional[Response]:
        """The most recent executed round's response, or ``None`` if none ran."""

        return self.responses[-1] if self.responses else None

    @property
    def stopped_by_model(self) -> bool:
        """True only when the loop ended on the model's explicit stop decision."""

        return self.stop_reason == LoopStopReason.MODEL_STOP


def run_parking_loop(
    *,
    model: ModelClient,
    observation: object,
    instruction: str,
    host_client_factory: Callable[[], HostClient],
    request_id_factory: Callable[[int], str],
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    request_builder: Callable[..., Request] = build_request,
    round_executor: Optional[Callable[[str, int], Response]] = None,
) -> ParkingLoopResult:
    """Run parking rounds until an explicit terminal condition, and stop.

    Each round reuses the whole existing single-shot path
    (:func:`run_parking_intent`'s steps): ``model.generate`` -> the
    authoritative :func:`parse_model_output` -> ``request_builder`` ->
    ``HostClient.send``. The loop adds only *iteration*, the feedback hand-off
    and the stop rules - it re-implements no validation and invents no protocol
    field.

    ``round_executor`` is an optional hook for a different validated decision
    path (NAV-11A uses the NAV-09/NAV-10 chain). It receives the raw model text
    and the round index, performs its own validated execution, and returns the
    real :class:`Response`. When supplied, the default ``parse_model_output``
    and request-builder path is not used; the executor owns the round's IDs and
    host call. It must raise an :class:`AgentIntentError` for a refused decision
    (the loop then stops with :data:`LoopStopReason.INVALID_OUTPUT`); a
    non-success Response stops with :data:`LoopStopReason.EXECUTION_FAILED` as
    usual. Transport errors and model errors propagate unchanged.

    Feedback hand-off: the ``observation`` given to a round is the initial
    ``observation`` for round 0, and the previous round's real :class:`Response`
    for every later round. The model therefore decides from the actual software
    result, not from a value invented here.

    The model's explicit stop decision is an **empty output** (blank text): the
    AgentIntent v1 wire contract has no "stop" action, so "no action" is
    expressed at the model-output boundary as empty text, distinct from a
    non-empty unparseable output (which is :data:`LoopStopReason.INVALID_OUTPUT`).

    Terminal conditions (each returns immediately; there is no automatic
    recovery and no re-issue after a failure):

    * :data:`LoopStopReason.MODEL_STOP` - the model produced an empty output;
    * :data:`LoopStopReason.INVALID_OUTPUT` - the output failed the v1
      contract, so nothing was submitted;
    * :data:`LoopStopReason.EXECUTION_FAILED` - a round's response was not
      ``ok``; the loop stops rather than inventing a recovery action;
    * :data:`LoopStopReason.MAX_ROUNDS` - ``max_rounds`` reached first.

    ``request_id_factory(round_index)`` supplies each round's IPC correlation
    id; it is caller-owned and never derived from ``intent_id`` (same rule as
    the single-shot entry point).
    """

    if type(max_rounds) is not int or max_rounds < 1:
        raise ValueError("max_rounds must be a positive integer")

    responses: list[Response] = []
    current_observation = observation

    for round_index in range(max_rounds):
        try:
            raw_text = model.generate(current_observation, instruction)
        except ModelCallError:
            raise
        except Exception as exc:  # the model call is an untrusted boundary
            raise ModelCallError(f"model client failed: {exc}") from exc

        # Explicit stop: no action this round. Checked before parsing because an
        # empty output is not a malformed intent - it is a deliberate no-action.
        if type(raw_text) is str and raw_text.strip() == "":
            return ParkingLoopResult(tuple(responses), LoopStopReason.MODEL_STOP)

        if round_executor is None:
            try:
                intent: AgentIntent = parse_model_output(raw_text)
            except AgentIntentError:
                return ParkingLoopResult(
                    tuple(responses), LoopStopReason.INVALID_OUTPUT
                )

            request = request_builder(
                intent, request_id=request_id_factory(round_index)
            )

            with host_client_factory() as client:
                response = client.send(request)
        else:
            try:
                response = round_executor(raw_text, round_index)
            except AgentIntentError:
                # The injected decision layer refused the model text before any
                # host work; mirror the default path's INVALID_OUTPUT stop.
                return ParkingLoopResult(
                    tuple(responses), LoopStopReason.INVALID_OUTPUT
                )
        responses.append(response)

        if not response.ok:
            return ParkingLoopResult(
                tuple(responses), LoopStopReason.EXECUTION_FAILED
            )

        # Feedback: the real response drives the next round's decision.
        current_observation = response

    return ParkingLoopResult(tuple(responses), LoopStopReason.MAX_ROUNDS)
