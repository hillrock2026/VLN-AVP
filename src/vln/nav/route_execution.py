"""NAV-19: selected route -> AgentIntent v1 -> real Host/Kernel stub -> feedback.

This is a thin integration layer, not a second navigation stack:

* the selected route and its provenance come from NAV-18's
  :class:`~vln.nav.offline_e2e.OfflineEndToEndResult`;
* the next target is the first node after the start on that **selected** route;
* its coordinates come from the synthetic topology node's explicit ``x/y``
  (local simulation frame - never a node-id string and never real localisation);
* the target heading is the absolute bearing from the caller-supplied
  :class:`~vln.nav.adapter.VehiclePose` position to that node;
* the intent is the existing :class:`~vln.intent.agent_intent.AgentIntent` v1,
  validated by its own constructor;
* the request is built by the existing ``vln.client.build_request`` and sent by
  the existing ``HostClient`` to the real Runtime Host / Agent-Kernel path;
* the real ``Response`` is classified by the existing STM helper and encoded by
  the existing ``ResponseFeedbackEncoder`` for a next round.

The ``parking.move`` capability remains a simulation stub. A successful
response means the real Host/Kernel runtime executed the stub; it is **not**
vehicle motion, arrival or parking.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping

from vln.client import HostClient, build_request
from vln.intent import AgentIntent, AgentIntentError, Target
from vln.intent.agent_intent import normalize_heading
from vln.ipc.envelope import HostKind, Request, Response
from vln.ipc.errors import IpcError
from vln.observation import ResponseFeedbackEncoder
from vln.planning_ltm.errors import TopologyValidationError
from vln.planning_ltm.models import ParkingScene
from vln.stm import RoundOutcome, classify_response
from vln.vlm import PreparedObservation

from .adapter import VehiclePose
from .errors import RouteIntentMappingError
from .offline_e2e import (
    DEMO_AS_OF,
    DEMO_POSE,
    OfflineEndToEndResult,
    OfflineEndToEndStatus,
    demo_cases,
    run_offline_decision,
)

__all__ = [
    "RouteExecutionStatus",
    "RouteIntentMapping",
    "Nav19ExecutionResult",
    "map_selected_route_to_agent_intent",
    "execute_selected_route",
    "build_nav19_demo",
    "main",
]


class RouteExecutionStatus:
    """Independent stages are reported separately in ``stages``."""

    PLANNING_FAILED = "planning-failed"
    MAPPING_FAILED = "mapping-failed"
    REQUEST_FAILED = "request-failed"
    HOST_UNAVAILABLE = "host-unavailable"
    EXECUTION_FAILED = "execution-failed"
    EXECUTION_UNCERTAIN = "execution-uncertain"
    SIMULATED_COMPLETED = "simulated-completed"
    ALL = frozenset(
        {
            PLANNING_FAILED,
            MAPPING_FAILED,
            REQUEST_FAILED,
            HOST_UNAVAILABLE,
            EXECUTION_FAILED,
            EXECUTION_UNCERTAIN,
            SIMULATED_COMPLETED,
        }
    )


@dataclass(frozen=True)
class RouteIntentMapping:
    """A selected route's next target mapped onto a validated AgentIntent v1."""

    intent: AgentIntent
    scene_id: str
    target_id: str
    candidate_id: str
    route_key: str
    route_node_ids: tuple[str, ...]
    next_node_id: str
    pose: VehiclePose
    turn_delta_rad: float
    navigation_direction: str
    plan_mode: str
    coordinate_frame: str = "synthetic-topology-local"
    source: str = "synthetic-simulation"
    note: str = (
        "Topology node x/y are synthetic simulation coordinates, not vehicle "
        "localisation. Target heading is the absolute bearing from the explicit "
        "pose position to the next node; turn_delta_rad = target heading minus "
        "the explicit current heading."
    )

    def __post_init__(self) -> None:
        if not isinstance(self.intent, AgentIntent):
            raise TypeError("intent must be an AgentIntent")
        if not isinstance(self.pose, VehiclePose):
            raise TypeError("pose must be a VehiclePose")
        if not isinstance(self.route_key, str) or self.route_key.strip() == "":
            raise ValueError("route_key must be a non-blank str")
        if not math.isfinite(float(self.turn_delta_rad)):
            raise ValueError("turn_delta_rad must be finite")
        for name in ("scene_id", "target_id", "candidate_id", "next_node_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or value.strip() == "":
                raise ValueError(f"{name} must be a non-blank str")

    @property
    def target(self) -> Target:
        return self.intent.target

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "target_id": self.target_id,
            "candidate_id": self.candidate_id,
            "route_key": self.route_key,
            "route_node_ids": list(self.route_node_ids),
            "next_node_id": self.next_node_id,
            "intent_id": self.intent.intent_id,
            "intent": self.intent.to_object(),
            "target": self.intent.target.to_object(),
            "pose": {
                "x": self.pose.x,
                "y": self.pose.y,
                "heading": self.pose.heading,
            },
            "turn_delta_rad": self.turn_delta_rad,
            "navigation_direction": self.navigation_direction,
            "plan_mode": self.plan_mode,
            "coordinate_frame": self.coordinate_frame,
            "source": self.source,
            "note": self.note,
        }


def map_selected_route_to_agent_intent(
    scene: ParkingScene,
    e2e_result: OfflineEndToEndResult,
    *,
    pose: VehiclePose,
    intent_id: str,
) -> RouteIntentMapping:
    """Map the NAV-18 selected route's first next node to an AgentIntent.

    Fail-closed conditions: no selected route, scene/plan mismatch, unknown
    next node, zero distance from the pose to the node, or an invalid intent id.
    """

    if not isinstance(scene, ParkingScene):
        raise RouteIntentMappingError("scene must be a ParkingScene")
    if not isinstance(e2e_result, OfflineEndToEndResult):
        raise RouteIntentMappingError("e2e_result must be an OfflineEndToEndResult")
    if not isinstance(pose, VehiclePose):
        raise RouteIntentMappingError("pose must be a VehiclePose")
    if e2e_result.status != OfflineEndToEndStatus.SELECTED:
        raise RouteIntentMappingError(
            "NAV-18 did not select a route "
            f"(status={e2e_result.status!r}); no intent can be built"
        )
    if e2e_result.planning is None:
        raise RouteIntentMappingError("selected NAV-18 result has no planning result")
    if scene.scene_id != e2e_result.scene_id:
        raise RouteIntentMappingError(
            f"scene_id mismatch: scene={scene.scene_id!r}, "
            f"result={e2e_result.scene_id!r}"
        )
    if scene.target_id != e2e_result.target_id:
        raise RouteIntentMappingError(
            f"target_id mismatch: scene={scene.target_id!r}, "
            f"result={e2e_result.target_id!r}"
        )

    selected = e2e_result.planning.selected_evaluation
    if selected is None:
        raise RouteIntentMappingError(
            "NAV-18 status is selected but no selected candidate evaluation exists"
        )
    candidate = selected.candidate
    if e2e_result.planning.selected_candidate_id != candidate.candidate_id:
        raise RouteIntentMappingError(
            "selected candidate identity is inconsistent with the planning result"
        )
    if candidate.target_id != scene.target_id:
        raise RouteIntentMappingError(
            f"selected candidate targets {candidate.target_id!r}, "
            f"scene targets {scene.target_id!r}"
        )
    if candidate.start_node_id != scene.start_node_id:
        raise RouteIntentMappingError(
            f"selected candidate starts at {candidate.start_node_id!r}, "
            f"scene starts at {scene.start_node_id!r}"
        )
    if candidate.end_node_id != scene.target_node_id:
        raise RouteIntentMappingError(
            f"selected candidate ends at {candidate.end_node_id!r}, "
            f"target node is {scene.target_node_id!r}"
        )
    if len(candidate.node_ids) < 2:
        raise RouteIntentMappingError(
            "selected candidate has no next node after the start"
        )

    start_node_id = candidate.node_ids[0]
    next_node_id = candidate.node_ids[1]
    if scene.topology.edge_between(start_node_id, next_node_id) is None:
        raise RouteIntentMappingError(
            f"selected route is not connected: {start_node_id!r} -> "
            f"{next_node_id!r}"
        )
    try:
        next_node = scene.topology.node(next_node_id)
    except TopologyValidationError as exc:
        raise RouteIntentMappingError(
            f"next node {next_node_id!r} does not exist in the scene topology"
        ) from exc

    dx = next_node.x - pose.x
    dy = next_node.y - pose.y
    distance = math.hypot(dx, dy)
    if not math.isfinite(distance) or distance <= 0.0:
        raise RouteIntentMappingError(
            "cannot compute a finite target heading: the explicit pose "
            f"({pose.x}, {pose.y}) coincides with next node {next_node_id!r} "
            f"({next_node.x}, {next_node.y})"
        )

    target_heading = math.atan2(dy, dx)
    turn_delta = normalize_heading(target_heading - pose.heading)
    target = Target(
        x=next_node.x,
        y=next_node.y,
        heading=target_heading,
    )
    try:
        intent = AgentIntent(intent_id=intent_id, target=target)
    except AgentIntentError as exc:
        raise RouteIntentMappingError(
            f"cannot build a valid AgentIntent v1: {exc}"
        ) from exc

    direction = ""
    if e2e_result.directive is not None:
        direction = e2e_result.directive.direction
    elif e2e_result.constraint is not None:
        direction = e2e_result.constraint.direction

    return RouteIntentMapping(
        intent=intent,
        scene_id=scene.scene_id,
        target_id=scene.target_id,
        candidate_id=candidate.candidate_id,
        route_key=candidate.route_key,
        route_node_ids=candidate.node_ids,
        next_node_id=next_node_id,
        pose=pose,
        turn_delta_rad=turn_delta,
        navigation_direction=direction,
        plan_mode=e2e_result.planning.planning.mode,
    )


@dataclass(frozen=True)
class Nav19ExecutionResult:
    """Stage-by-stage result of route -> intent -> real Host -> feedback.

    ``status`` is the execution outcome; ``stages`` records the independent
    planning, mapping, request, host, stub and feedback steps. ``ok`` is true
    only for a real Kernel-hosted ``stub_completed`` response whose feedback was
    encoded. Physical arrival is always ``"unknown"``.
    """

    scene_id: str
    target_id: str
    e2e_status: str
    status: str
    reason: str
    mapping: RouteIntentMapping | None = None
    request: Request | None = None
    response: Response | None = None
    outcome: str | None = None
    stub_output: Mapping[str, Any] | None = None
    stub_output_error: str | None = None
    stub_execution_mode: str | None = None
    feedback_text: str | None = None
    feedback_error: str | None = None
    host_called: bool = False
    physical_arrival: str = "unknown"
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.status not in RouteExecutionStatus.ALL:
            raise ValueError(f"unknown execution status {self.status!r}")
        if self.physical_arrival != "unknown":
            raise ValueError("physical arrival must remain unknown in NAV-19")
        if self.feedback_text is not None and self.feedback_error is not None:
            raise ValueError("feedback cannot be both encoded and failed")
        if self.host_called and self.request is None:
            raise ValueError("host_called requires a request")
        if self.response is not None and self.request is None:
            raise ValueError("a response requires a request")
        if self.request is not None and self.mapping is None:
            raise ValueError("a request requires an intent mapping")
        if self.status in (
            RouteExecutionStatus.PLANNING_FAILED,
            RouteExecutionStatus.MAPPING_FAILED,
        ):
            if self.host_called or self.request is not None or self.response is not None:
                raise ValueError("pre-execution failure must not reach the host")
        if self.status == RouteExecutionStatus.REQUEST_FAILED:
            if self.host_called or self.response is not None:
                raise ValueError("request failure must not reach the host")
        if self.status == RouteExecutionStatus.HOST_UNAVAILABLE:
            if self.host_called or self.response is not None:
                raise ValueError("host-unavailable must not carry a host response")
        if self.status in (
            RouteExecutionStatus.EXECUTION_FAILED,
            RouteExecutionStatus.EXECUTION_UNCERTAIN,
            RouteExecutionStatus.SIMULATED_COMPLETED,
        ):
            if self.request is None:
                raise ValueError("an execution status requires a request")
        if self.status in (
            RouteExecutionStatus.EXECUTION_FAILED,
            RouteExecutionStatus.SIMULATED_COMPLETED,
        ):
            if not self.host_called or self.response is None:
                raise ValueError("this execution status requires a host response")

    @property
    def ok(self) -> bool:
        return (
            self.status == RouteExecutionStatus.SIMULATED_COMPLETED
            and self.feedback_text is not None
            and self.feedback_error is None
        )

    @property
    def intent(self) -> AgentIntent | None:
        return None if self.mapping is None else self.mapping.intent

    @property
    def selected_candidate_id(self) -> str | None:
        return None if self.mapping is None else self.mapping.candidate_id

    @property
    def stages(self) -> dict[str, Any]:
        return {
            "nav18_planning_status": self.e2e_status,
            "intent_mapping": self.mapping is not None,
            "request_built": self.request is not None,
            "host_called": self.host_called,
            "host_response_received": self.response is not None,
            "host_response_ok": None if self.response is None else self.response.ok,
            "stub_simulated_completed": (
                self.status == RouteExecutionStatus.SIMULATED_COMPLETED
            ),
            "feedback_encoded": self.feedback_text is not None,
            "physical_arrival": self.physical_arrival,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "target_id": self.target_id,
            "status": self.status,
            "ok": self.ok,
            "reason": self.reason,
            "selected_candidate_id": self.selected_candidate_id,
            "intent_id": None if self.intent is None else self.intent.intent_id,
            "stages": self.stages,
            "mapping": None if self.mapping is None else self.mapping.to_dict(),
            "request": None if self.request is None else self.request.to_object(),
            "response": None if self.response is None else asdict(self.response),
            "outcome": self.outcome,
            "stub_output": (
                None if self.stub_output is None else dict(self.stub_output)
            ),
            "stub_output_error": self.stub_output_error,
            "stub_execution_mode": self.stub_execution_mode,
            "feedback": {
                "encoded": self.feedback_text is not None,
                "text": self.feedback_text,
                "error": self.feedback_error,
            },
            "host_called": self.host_called,
            "physical_arrival": self.physical_arrival,
            "error": (
                None
                if self.error_type is None
                else {"type": self.error_type, "message": self.error_message}
            ),
            "note": (
                "The parking.move capability is simulation-only. A successful "
                "response means the real Host/Kernel runtime executed the stub; "
                "it is not vehicle motion, arrival or parking."
            ),
        }


def _failure(
    *,
    scene: ParkingScene,
    e2e_result: OfflineEndToEndResult,
    status: str,
    reason: str,
    mapping: RouteIntentMapping | None = None,
    request: Request | None = None,
    response: Response | None = None,
    host_called: bool = False,
    error: Exception | None = None,
) -> Nav19ExecutionResult:
    return Nav19ExecutionResult(
        scene_id=scene.scene_id,
        target_id=scene.target_id,
        e2e_status=e2e_result.status,
        status=status,
        reason=reason,
        mapping=mapping,
        request=request,
        response=response,
        host_called=host_called,
        error_type=None if error is None else type(error).__name__,
        error_message=None if error is None else str(error),
    )


def _decode_stub_output(
    response: Response,
) -> tuple[Mapping[str, Any] | None, str | None]:
    if response.output is None:
        return None, None
    try:
        payload = json.loads(response.output)
    except ValueError as exc:
        return None, f"stub output is not valid JSON: {exc}"
    if not isinstance(payload, Mapping):
        return None, "stub output must decode to a JSON object"
    return payload, None


def _target_matches(
    actual: object, expected: Mapping[str, float]
) -> str | None:
    if not isinstance(actual, Mapping):
        return "stub output target is missing or not an object"
    if set(actual) != {"x", "y", "heading"}:
        return f"stub output target has an unexpected field set: {sorted(actual)}"
    for key in ("x", "y", "heading"):
        value = actual[key]
        if type(value) is not int and type(value) is not float:
            return f"stub output target.{key} is not a number"
        if not math.isfinite(float(value)):
            return f"stub output target.{key} is not finite"
        if not math.isclose(
            float(value), float(expected[key]), rel_tol=0.0, abs_tol=1e-9
        ):
            return (
                f"stub output target.{key}={value!r} does not match the "
                f"submitted target {expected[key]!r}"
            )
    return None


def _validate_stub_success(
    response: Response,
    mapping: RouteIntentMapping,
    stub_output: Mapping[str, Any] | None,
    stub_output_error: str | None,
) -> str | None:
    if response.host_kind != HostKind.KERNEL:
        return f"successful response came from host_kind={response.host_kind!r}"
    if response.execution_status != "completed":
        return (
            "successful response has no completed Kernel execution status: "
            f"{response.execution_status!r}"
        )
    if stub_output_error is not None:
        return stub_output_error
    if stub_output is None:
        return "successful response carried no stub output"
    expected_fields = {
        "output_version",
        "status",
        "execution_mode",
        "action",
        "intent_id",
        "target",
    }
    if set(stub_output) != expected_fields:
        return (
            "stub output has an unexpected field set: "
            f"{sorted(stub_output)}"
        )
    if stub_output.get("output_version") != "1":
        return f"unexpected stub output_version {stub_output.get('output_version')!r}"
    if stub_output.get("status") != "stub_completed":
        return f"unexpected stub status {stub_output.get('status')!r}"
    if stub_output.get("execution_mode") != "simulation":
        return (
            "unexpected stub execution_mode "
            f"{stub_output.get('execution_mode')!r}"
        )
    if stub_output.get("action") != mapping.intent.action:
        return f"stub action {stub_output.get('action')!r} does not match the intent"
    if stub_output.get("intent_id") != mapping.intent.intent_id:
        return (
            f"stub intent_id {stub_output.get('intent_id')!r} does not match "
            f"{mapping.intent.intent_id!r}"
        )
    target_error = _target_matches(
        stub_output.get("target"), mapping.intent.target.to_object()
    )
    if target_error is not None:
        return target_error
    return None


def _feedback(
    response: Response, encoder: object
) -> tuple[str | None, str | None]:
    try:
        prepared = encoder.encode(response)  # type: ignore[attr-defined]
        if not isinstance(prepared, PreparedObservation):
            return None, (
                "feedback encoder returned "
                f"{type(prepared).__name__}, not PreparedObservation"
            )
        return prepared.text, None
    except Exception as exc:  # the injected encoder is a fail-closed boundary
        return None, f"{type(exc).__name__}: {exc}"


def execute_selected_route(
    scene: ParkingScene,
    e2e_result: OfflineEndToEndResult,
    *,
    pose: VehiclePose,
    intent_id: str,
    request_id: str,
    host_client_factory: Callable[[], HostClient],
    request_builder: Callable[..., Request] = build_request,
    feedback_encoder: object | None = None,
) -> Nav19ExecutionResult:
    """Execute one NAV-18 selected route through the real Host/Kernel path.

    Nothing is submitted before the route mapping and request construction
    succeed. A transport/uncertain outcome is returned as uncertain and is
    never retried. The returned feedback is the existing encoder's text for the
    next model round.
    """

    if not isinstance(scene, ParkingScene):
        raise TypeError("scene must be a ParkingScene")
    if not isinstance(e2e_result, OfflineEndToEndResult):
        raise TypeError("e2e_result must be an OfflineEndToEndResult")
    if not isinstance(pose, VehiclePose):
        raise TypeError("pose must be a VehiclePose")

    if e2e_result.status != OfflineEndToEndStatus.SELECTED:
        return _failure(
            scene=scene,
            e2e_result=e2e_result,
            status=RouteExecutionStatus.PLANNING_FAILED,
            reason=(
                f"NAV-18 planning status is {e2e_result.status!r}, not 'selected'; "
                "no AgentIntent was built and the host was not called"
            ),
        )

    try:
        mapping = map_selected_route_to_agent_intent(
            scene, e2e_result, pose=pose, intent_id=intent_id
        )
    except RouteIntentMappingError as exc:
        return _failure(
            scene=scene,
            e2e_result=e2e_result,
            status=RouteExecutionStatus.MAPPING_FAILED,
            reason=f"route-to-intent mapping failed: {exc}",
            error=exc,
        )

    try:
        request = request_builder(mapping.intent, request_id=request_id)
    except Exception as exc:
        return _failure(
            scene=scene,
            e2e_result=e2e_result,
            status=RouteExecutionStatus.REQUEST_FAILED,
            reason=f"IPC request construction failed: {exc}",
            mapping=mapping,
            error=exc,
        )

    host_called = False
    try:
        with host_client_factory() as client:
            host_called = True
            response = client.send(request)
    except IpcError as exc:
        # The request may have reached the host; do not retry or claim failure.
        return _failure(
            scene=scene,
            e2e_result=e2e_result,
            status=RouteExecutionStatus.EXECUTION_UNCERTAIN,
            reason=(
                "Host/IPC outcome is uncertain; no retry was attempted: "
                f"{type(exc).__name__}: {exc}"
            ),
            mapping=mapping,
            request=request,
            host_called=host_called,
            error=exc,
        )
    except OSError as exc:
        return _failure(
            scene=scene,
            e2e_result=e2e_result,
            status=RouteExecutionStatus.HOST_UNAVAILABLE,
            reason=f"Host process could not be used: {exc}",
            mapping=mapping,
            request=request,
            host_called=host_called,
            error=exc,
        )

    if response.request_id != request.request_id:
        outcome = RoundOutcome.UNCERTAIN
        stub_output, stub_output_error = _decode_stub_output(response)
        stub_execution_mode = None
        status = RouteExecutionStatus.EXECUTION_UNCERTAIN
        reason = (
            "response request_id does not match the submitted request: "
            f"sent={request.request_id!r} received={response.request_id!r}"
        )
        feedback_text, feedback_error = _feedback(
            response, feedback_encoder or ResponseFeedbackEncoder()
        )
        return Nav19ExecutionResult(
            scene_id=scene.scene_id,
            target_id=scene.target_id,
            e2e_status=e2e_result.status,
            status=status,
            reason=reason,
            mapping=mapping,
            request=request,
            response=response,
            outcome=outcome,
            stub_output=stub_output,
            stub_output_error=stub_output_error,
            stub_execution_mode=stub_execution_mode,
            feedback_text=feedback_text,
            feedback_error=feedback_error,
            host_called=host_called,
        )

    outcome = classify_response(response)
    stub_output, stub_output_error = _decode_stub_output(response)
    stub_execution_mode = None
    if stub_output is not None:
        declared_mode = stub_output.get("execution_mode")
        if isinstance(declared_mode, str):
            stub_execution_mode = declared_mode

    if outcome == RoundOutcome.SOFTWARE_SUCCEEDED:
        validation_error = _validate_stub_success(
            response, mapping, stub_output, stub_output_error
        )
        if validation_error is None:
            status = RouteExecutionStatus.SIMULATED_COMPLETED
            reason = (
                "real Agent-Kernel host completed the parking.move simulation "
                "stub; this is not vehicle motion, arrival or parking"
            )
        else:
            status = RouteExecutionStatus.EXECUTION_UNCERTAIN
            reason = f"successful response failed stub validation: {validation_error}"
    elif outcome == RoundOutcome.UNCERTAIN:
        status = RouteExecutionStatus.EXECUTION_UNCERTAIN
        reason = f"execution outcome is uncertain: {outcome}"
    else:
        status = RouteExecutionStatus.EXECUTION_FAILED
        reason = f"execution did not succeed: {outcome}"
        if response.error:
            reason += (
                f" ({response.error.get('code')}: "
                f"{response.error.get('message')})"
            )

    feedback_text, feedback_error = _feedback(
        response, feedback_encoder or ResponseFeedbackEncoder()
    )
    return Nav19ExecutionResult(
        scene_id=scene.scene_id,
        target_id=scene.target_id,
        e2e_status=e2e_result.status,
        status=status,
        reason=reason,
        mapping=mapping,
        request=request,
        response=response,
        outcome=outcome,
        stub_output=stub_output,
        stub_output_error=stub_output_error,
        stub_execution_mode=stub_execution_mode,
        feedback_text=feedback_text,
        feedback_error=feedback_error,
        host_called=host_called,
    )


# ----------------------------------------------------------------------
# CLI: NAV-18 planning -> this adapter -> real Host/Kernel stub -> feedback
# ----------------------------------------------------------------------


def _case(name: str):
    return next(item for item in demo_cases() if item.name == name)


def build_nav19_demo(
    case: str,
    *,
    host_exe: str | None,
    pose: VehiclePose,
    intent_id: str,
    request_id: str,
) -> dict[str, Any]:
    """Run one NAV-18 case and, when selected, submit it to the real host."""

    if case not in {item.name for item in demo_cases()}:
        raise ValueError(f"unknown case {case!r}")

    item = _case(case)
    nav18 = run_offline_decision(
        item.scene, item.decision_input, pose=pose, as_of=DEMO_AS_OF
    )

    def factory() -> HostClient:
        if not host_exe:
            raise FileNotFoundError(
                "no host executable; pass --host-exe or set VLN_KERNEL_HOST_EXE"
            )
        return HostClient([host_exe])

    execution = execute_selected_route(
        item.scene,
        nav18,
        pose=pose,
        intent_id=intent_id,
        request_id=request_id,
        host_client_factory=factory,
    )
    return {
        "demo": "M1-VLN-NAV-19-EXEC",
        "case": case,
        "host_exe": host_exe,
        "pose": {
            "x": pose.x,
            "y": pose.y,
            "heading": pose.heading,
            "provenance": "explicit synthetic reference pose; not localisation",
        },
        "nav18": nav18.to_dict(),
        "execution": execution.to_dict(),
        "note": (
            "Frozen NAV-15 replay + synthetic topology + real Runtime "
            "Host/Agent-Kernel parking.move simulation stub. No live model, no "
            "vehicle and no physical arrival."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vln.nav.route_execution",
        description=(
            "Map a NAV-18 selected route to AgentIntent v1, execute the "
            "parking.move stub through the real Host/Kernel, and print feedback."
        ),
    )
    parser.add_argument(
        "--case",
        default="straight",
        choices=("left", "straight", "conflict", "invalid"),
        help="NAV-18 case to execute (default: straight)",
    )
    parser.add_argument(
        "--host-exe",
        default=None,
        help="path to kernel_host (default: $VLN_KERNEL_HOST_EXE)",
    )
    parser.add_argument("--pose-x", type=float, default=DEMO_POSE.x)
    parser.add_argument("--pose-y", type=float, default=DEMO_POSE.y)
    parser.add_argument("--pose-heading", type=float, default=DEMO_POSE.heading)
    parser.add_argument("--intent-id", default="nav19-intent-1")
    parser.add_argument("--request-id", default="nav19-req-1")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)

    host_exe = args.host_exe or os.environ.get("VLN_KERNEL_HOST_EXE")
    payload = build_nav19_demo(
        args.case,
        host_exe=host_exe,
        pose=VehiclePose(args.pose_x, args.pose_y, args.pose_heading),
        intent_id=args.intent_id,
        request_id=args.request_id,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=args.indent))
    return 0 if payload["execution"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
