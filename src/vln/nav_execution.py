"""NAV-10: one real single-round chain from a visual judgement to the Host.

This is the composition point the repository lacked. It wires the existing
layers together in this order and delegates every step to its owner:

    model.generate(observation, instruction)     # vln.vlm
      -> parse_visual_decision                  # vln.nav layer 1
      -> verify_visual_decision                 # vln.nav layer 2
      -> to_agent_intent                        # vln.nav layer 3
      -> build_request(intent, request_id=...)  # vln.client
      -> HostClient.send(request)               # vln.client -> host process

Nothing is re-implemented here: no model text is parsed twice, no intent is
repaired, no protocol field is invented, and the ``parking.move`` capability is
reached only through the existing IPC envelope and HostClient. The
``AgentIntent`` is produced by the NAV-09 layers, so its type is the guarantee
that no unverified judgement reaches the execution path.

Failure semantics (fail closed):

* a model-call failure raises :class:`~vln.vlm.ModelCallError`;
* a structure/executability/mapping failure raises the NAV-09 error unchanged
  (all rooted at :class:`~vln.intent.agent_intent.AgentIntentError`);
* a request-builder failure propagates unchanged - and, because the builder is
  called before the host client is constructed, no host is started;
* a transport failure or an uncertain outcome propagates as the existing
  :mod:`vln.ipc.errors` type; the chain never retries;
* a host response is returned as-is. A non-success response is **not** turned
  into a success: :attr:`VisualParkingExecution.ok` is false and
  :attr:`~VisualParkingExecution.stub_output` is ``None``. Only a successful
  response from the Agent-Kernel host (``host_kind == "kernel"``) with the
  frozen ``parking.move`` output-v1 contract is accepted as an execution.

Correlation. The IPC envelope's ``request_id`` is the request/response
correlation id; the stub echoes the intent's own ``intent_id`` and target.
``intent_id`` and ``request_id`` are independent, caller-owned identities - this
module never derives one from the other. The result retains the request, the
intent and the response so a caller can verify both identities against one run.

Scope. The caller supplies the :class:`~vln.nav.adapter.VehiclePose`; this
project has no localisation, odometry or simulator. A pose may be a clearly
labelled simulated/test value, but the mapping is a declared convention, not
vehicle kinematics, and a ``stub_completed`` response is not evidence that a
vehicle moved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from vln.client import HostClient, build_request
from vln.intent import AgentIntent
from vln.ipc.envelope import HostKind, Request, Response
from vln.nav import (
    NavigationDirective,
    VehiclePose,
    VisualNavigationDecision,
    parse_visual_decision,
    to_agent_intent,
    verify_visual_decision,
)
from vln.vlm import ModelCallError, ModelClient

__all__ = [
    "NavigationExecutionError",
    "VisualParkingExecution",
    "execute_visual_decision",
    "run_visual_parking_intent",
]

#: The exact ``parking.move`` output-v1 field set (M1-04B0 section 5). A
#: successful response whose output is not exactly this is refused.
_STUB_OUTPUT_FIELDS = frozenset(
    {"output_version", "status", "execution_mode", "action", "intent_id", "target"}
)

_STUB_OUTPUT_VALUES = {
    "output_version": "1",
    "status": "stub_completed",
    "execution_mode": "simulation",
}


class NavigationExecutionError(Exception):
    """A successful host response was not a valid, correlated stub result.

    Raised only after a request has been submitted and the host answered with
    ``response.ok`` but the answer cannot be trusted as this intent's
    ``parking.move`` execution: a ``request_id`` mismatch, a non-Kernel host, a
    missing/malformed output, or an ``intent_id``/target that is not this
    request's intent. The actual ``request``/``response``/``output`` are
    attached so the evidence survives the failure.

    A host response that is itself a failure (``response.ok`` is false) is not
    this error: it is returned in :class:`VisualParkingExecution` with
    ``ok == False`` and no stub output. Transport errors propagate as their
    existing :mod:`vln.ipc.errors` types instead.
    """

    def __init__(
        self,
        message: str,
        *,
        request: Optional[Request] = None,
        response: Optional[Response] = None,
        output: Optional[object] = None,
    ) -> None:
        super().__init__(message)
        self.request = request
        self.response = response
        self.output = output


@dataclass(frozen=True)
class VisualParkingExecution:
    """The evidence of one single-round NAV-09 -> Host execution.

    ``response`` is the exact object returned by ``HostClient.send``.
    ``stub_output`` is the decoded ``parking.move`` output only when the
    response is ``ok`` and every contract/correlation check passed; otherwise
    it is ``None``. The ``pose`` is recorded as supplied by the caller and
    carries no localisation claim.
    """

    raw_model_output: str
    decision: VisualNavigationDecision
    directive: NavigationDirective
    intent: AgentIntent
    pose: VehiclePose
    request: Request
    response: Response
    stub_output: Optional[Mapping[str, Any]]

    @property
    def ok(self) -> bool:
        """True only for a validated, correlated successful stub execution."""

        return self.response.ok and self.stub_output is not None


def _validated_stub_output(
    response: Response, request: Request, intent: AgentIntent
) -> Optional[Mapping[str, Any]]:
    """Return the stub output for a successful response, or ``None`` on failure.

    A non-success response is a real failure and is returned to the caller, not
    converted into an exception or a success. A success response is checked
    against the frozen output-v1 contract and both correlation identities.
    """

    if response.request_id != request.request_id:
        raise NavigationExecutionError(
            "response request_id does not match the submitted request: "
            f"sent={request.request_id!r} received={response.request_id!r}",
            request=request,
            response=response,
        )
    if not response.ok:
        return None
    if response.host_kind != HostKind.KERNEL:
        raise NavigationExecutionError(
            "a successful response came from "
            f"host_kind={response.host_kind!r}, not the Agent-Kernel host",
            request=request,
            response=response,
        )
    if response.output is None:
        raise NavigationExecutionError(
            "a successful kernel response carried no parking.move output",
            request=request,
            response=response,
        )
    try:
        output = json.loads(response.output)
    except ValueError as exc:
        raise NavigationExecutionError(
            f"parking.move output is not valid JSON: {exc}",
            request=request,
            response=response,
            output=response.output,
        ) from exc
    if not isinstance(output, Mapping):
        raise NavigationExecutionError(
            "parking.move output must decode to a JSON object",
            request=request,
            response=response,
            output=output,
        )
    if set(output) != _STUB_OUTPUT_FIELDS:
        raise NavigationExecutionError(
            "parking.move output has an unexpected field set: "
            f"{sorted(output)}",
            request=request,
            response=response,
            output=output,
        )
    for name, expected in _STUB_OUTPUT_VALUES.items():
        if output[name] != expected:
            raise NavigationExecutionError(
                f"parking.move output {name} must be {expected!r}, "
                f"got {output[name]!r}",
                request=request,
                response=response,
                output=output,
            )
    if output["action"] != intent.action:
        raise NavigationExecutionError(
            "parking.move output action does not match the intent: "
            f"output={output['action']!r} intent={intent.action!r}",
            request=request,
            response=response,
            output=output,
        )
    if output["intent_id"] != intent.intent_id:
        raise NavigationExecutionError(
            "parking.move output intent_id does not match the submitted intent: "
            f"output={output['intent_id']!r} intent={intent.intent_id!r}",
            request=request,
            response=response,
            output=output,
        )
    target = output["target"]
    if not isinstance(target, Mapping) or set(target) != {"x", "y", "heading"}:
        raise NavigationExecutionError(
            "parking.move output target must be exactly {x, y, heading}",
            request=request,
            response=response,
            output=output,
        )
    if target != intent.target.to_object():
        raise NavigationExecutionError(
            "parking.move output target does not match the submitted intent: "
            f"output={dict(target)!r} intent={intent.target.to_object()!r}",
            request=request,
            response=response,
            output=output,
        )
    return output


def execute_visual_decision(
    raw_text: str,
    *,
    expected_identity: str,
    pose: VehiclePose,
    intent_id: str,
    request_id: str,
    host_client_factory: Callable[[], HostClient],
    request_builder: Callable[..., Request] = build_request,
) -> VisualParkingExecution:
    """Run the NAV-09 -> request -> Host half of the NAV-10 chain.

    This is the same execution path as :func:`run_visual_parking_intent`, split
    out for an existing multi-round loop that already obtained ``raw_text`` from
    the model. It performs no model call: the three NAV-09 layers, the request
    builder and the HostClient are the unchanged NAV-10 path, and no step is
    retried or bypassed.
    """

    decision = parse_visual_decision(raw_text)
    directive = verify_visual_decision(decision, expected_identity=expected_identity)
    intent = to_agent_intent(directive, pose=pose, intent_id=intent_id)

    request = request_builder(intent, request_id=request_id)

    with host_client_factory() as client:
        response = client.send(request)

    stub_output = _validated_stub_output(response, request, intent)
    return VisualParkingExecution(
        raw_model_output=raw_text,
        decision=decision,
        directive=directive,
        intent=intent,
        pose=pose,
        request=request,
        response=response,
        stub_output=stub_output,
    )


def run_visual_parking_intent(
    *,
    model: ModelClient,
    observation: object,
    instruction: str,
    expected_identity: str,
    pose: VehiclePose,
    intent_id: str,
    request_id: str,
    host_client_factory: Callable[[], HostClient],
    request_builder: Callable[..., Request] = build_request,
) -> VisualParkingExecution:
    """Run one model -> NAV-09 -> request -> Host -> Response chain.

    ``expected_identity`` is the identity the caller asked for; it is supplied
    to layer 2 and is never read out of the model's own ``Target`` echo.
    ``pose`` is caller-owned (there is no localisation in this project).
    ``intent_id`` and ``request_id`` are independent, caller-owned identities.

    The host client is constructed only after the three NAV-09 layers produced
    a validated intent and the request builder succeeded, so a model, judgement
    or request-building failure cannot start a host process.
    """

    try:
        raw_text = model.generate(observation, instruction)
    except ModelCallError:
        raise
    except Exception as exc:  # the model call is an untrusted external boundary
        raise ModelCallError(f"model client failed: {exc}") from exc

    return execute_visual_decision(
        raw_text,
        expected_identity=expected_identity,
        pose=pose,
        intent_id=intent_id,
        request_id=request_id,
        host_client_factory=host_client_factory,
        request_builder=request_builder,
    )
