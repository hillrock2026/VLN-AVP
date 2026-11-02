"""One constrained re-decision after a route/vision conflict.

The first visual decision remains authoritative evidence: this module never
rewrites it. It is called only after ``arbitrate_route`` returned
``no_compatible_route`` for a successful model decision. It then:

1. describes the **route facts** that already exist in the failed arbitration
   (matched node, every outgoing edge, relative turn, reachability);
2. asks the same model one extra question using the **same frame** (the vehicle
   must be stationary, and that is checked by the caller-supplied state);
3. runs the new answer through the existing parser, verifier and route
   arbitration again;
4. returns a typed result. It never registers an execution permit, never calls
   the Kernel and never moves the vehicle.

The route facts are explicitly labels as facts, not visual evidence: a
candidate edge can only say that a direction is geometrically available, never
that the target is really in that direction. The model still has to report what
it sees and the existing verifier still refuses ``无法确定`` and contradictory
position/direction pairs.

At most one re-decision is performed by the caller. Retrying is not implemented
here: a failed re-decision is a terminal refusal.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from vln.intent.agent_intent import AgentIntent
from vln.vlm.model_client import ModelClient
from vln.vlm.nav_prompt import Variant, build_nav_prompt

from .observation import (
    INTENT_REJECTED,
    MODEL_OUTPUT_INVALID,
    MODEL_REQUEST_FAILED,
    SUCCESS,
    CarlaVisualObservation,
    DecisionOutcome,
    generate_and_decide,
)
from .route_arbitration import (
    RouteArbitrationResult,
    RouteArbitrationStatus,
    arbitrate_route,
)
from .waypoints import RouteGraph

__all__ = [
    "TURN_CLASS_LABEL",
    "RouteRedecisionStatus",
    "RouteRedecisionResult",
    "build_route_facts",
    "build_route_facts_from_candidates",
    "format_route_facts",
    "run_route_redecision",
]

TURN_CLASS_LABEL = {
    "LEFT": "左转（LEFT）",
    "RIGHT": "右转（RIGHT）",
    "STRAIGHT": "直行（STRAIGHT）",
    "BEHIND": "后方（不属前进方向）",
}

_FORWARD_CLASSES = frozenset({"LEFT", "RIGHT", "STRAIGHT"})


class RouteRedecisionStatus:
    """Terminal outcomes of the one extra decision attempt."""

    NOT_APPLICABLE = "not_applicable"
    CONTEXT_UNAVAILABLE = "context_unavailable"
    OBSERVATION_STALE = "observation_stale"
    NOT_STOPPED = "not_stopped"
    SELECTED = "selected"
    MODEL_REQUEST_FAILED = "model_request_failed"
    MODEL_OUTPUT_INVALID = "model_output_invalid"
    INTENT_REJECTED = "intent_rejected"
    ARBITRATION_REFUSED = "arbitration_refused"
    ERROR = "error"

    ALL = frozenset(
        {
            NOT_APPLICABLE,
            CONTEXT_UNAVAILABLE,
            OBSERVATION_STALE,
            NOT_STOPPED,
            SELECTED,
            MODEL_REQUEST_FAILED,
            MODEL_OUTPUT_INVALID,
            INTENT_REJECTED,
            ARBITRATION_REFUSED,
            ERROR,
        }
    )


@dataclass(frozen=True)
class RouteRedecisionResult:
    """Outcome of one re-decision, with the original failure and new evidence.

    ``route_facts`` is the exact data shown to the model. ``prompt`` is the
    exact text sent, and ``outcome`` is the new model decision. The original
    decision and arbitration are **not** fields here: the caller keeps them in
    its own round record, so nothing can overwrite the first answer.
    """

    status: str
    attempted: bool
    trigger_status: str
    reason: str
    route_facts: Mapping[str, Any] | None = None
    prompt: str | None = None
    prompt_sha256: str | None = None
    outcome: DecisionOutcome | None = None
    arbitration: RouteArbitrationResult | None = None
    intent: AgentIntent | None = None
    intent_id: str | None = None
    frame_id: int | None = None
    same_frame: bool = True
    vehicle_stationary: bool | None = None
    current_state: Mapping[str, Any] | None = None
    note: str = (
        "one extra decision only; same frame when the vehicle did not move; "
        "no execution or permit is performed by this module"
    )

    def __post_init__(self) -> None:
        if self.status not in RouteRedecisionStatus.ALL:
            raise ValueError(f"unknown re-decision status {self.status!r}")
        if self.status == RouteRedecisionStatus.SELECTED:
            if self.outcome is None or self.arbitration is None:
                raise ValueError("a selected re-decision requires outcome and arbitration")
            if self.arbitration.status != RouteArbitrationStatus.SELECTED:
                raise ValueError("selected re-decision arbitration must be selected")
            if self.intent is None:
                raise ValueError("a selected re-decision requires an intent")

    @property
    def selected(self) -> bool:
        return self.status == RouteRedecisionStatus.SELECTED

    def to_metadata(self) -> dict:
        return {
            "status": self.status,
            "attempted": self.attempted,
            "trigger_status": self.trigger_status,
            "reason": self.reason,
            "selected": self.selected,
            "frame_id": self.frame_id,
            "same_frame": self.same_frame,
            "vehicle_stationary": self.vehicle_stationary,
            "current_state": (
                None if self.current_state is None else dict(self.current_state)
            ),
            "intent_id": self.intent_id,
            "route_facts": (
                None if self.route_facts is None else dict(self.route_facts)
            ),
            "prompt": self.prompt,
            "prompt_sha256": self.prompt_sha256,
            "outcome": None if self.outcome is None else self.outcome.to_metadata(),
            "arbitration": (
                None if self.arbitration is None else self.arbitration.to_metadata()
            ),
            "note": self.note,
        }


def _finite(value: object) -> Optional[float]:
    if type(value) is int:
        return float(value)
    if type(value) is float and math.isfinite(value):
        return value
    return None


def _stationarity_error(
    *,
    observation: CarlaVisualObservation,
    current_state: Mapping[str, Any] | None,
    stop_speed_mps: float,
    max_pose_delta_m: float,
    max_yaw_delta_deg: float,
) -> tuple[str, str] | None:
    """Return ``(status, reason)`` when the same frame may not be reused."""

    if current_state is None:
        return None
    if not isinstance(current_state, Mapping):
        return (
            RouteRedecisionStatus.ERROR,
            "current_state must be a mapping",
        )
    speed = _finite(current_state.get("speed"))
    x = _finite(current_state.get("x"))
    y = _finite(current_state.get("y"))
    yaw = _finite(current_state.get("yaw"))
    if speed is None or x is None or y is None or yaw is None:
        return (
            RouteRedecisionStatus.ERROR,
            "current_state is missing finite x/y/yaw/speed",
        )
    if speed >= stop_speed_mps:
        return (
            RouteRedecisionStatus.NOT_STOPPED,
            f"vehicle speed {speed:.3f} m/s is not below {stop_speed_mps:.3f} m/s",
        )
    moved = math.hypot(x - observation.pose.x, y - observation.pose.y)
    yaw_delta = abs((yaw - math.degrees(observation.pose.heading) + 180.0) % 360.0 - 180.0)
    if moved > max_pose_delta_m or yaw_delta > max_yaw_delta_deg:
        return (
            RouteRedecisionStatus.OBSERVATION_STALE,
            "the vehicle moved after the observation "
            f"(dx={moved:.3f} m, dyaw={yaw_delta:.3f} deg); a new frame is required",
        )
    return None


def build_route_facts(
    *,
    arbitration: RouteArbitrationResult,
    graph: RouteGraph,
    goal_node_id: str,
) -> dict:
    """Describe the failed arbitration's real candidate edges.

    The facts come from ``arbitration.candidates`` (already computed by
    :func:`vln.carla.route_arbitration.arbitrate_route` from the real pose and
    the validated graph), so the prompt cannot drift from the map used by the
    execution gate.
    """

    if not isinstance(arbitration, RouteArbitrationResult):
        raise TypeError("arbitration must be a RouteArbitrationResult")
    if not isinstance(graph, RouteGraph):
        raise TypeError("graph must be a RouteGraph")
    if not graph.has_node(goal_node_id):
        raise ValueError(f"goal node {goal_node_id!r} is not in the graph")
    node_id = arbitration.matched_node_id
    if node_id is None or not graph.has_node(node_id):
        raise ValueError("the failed arbitration has no matched graph node")
    if not arbitration.candidates:
        raise ValueError("the failed arbitration has no outgoing candidates")

    candidates = []
    for candidate in arbitration.candidates:
        if candidate.from_node_id != node_id:
            raise ValueError(
                "candidate starts at "
                f"{candidate.from_node_id!r}, not the matched node {node_id!r}"
            )
        candidates.append(candidate)
    return build_route_facts_from_candidates(
        node_id=node_id,
        matched_node_distance_m=arbitration.matched_node_distance_m,
        pose=arbitration.pose,
        candidates=candidates,
        goal_node_id=goal_node_id,
    )


def build_route_facts_from_candidates(
    *,
    node_id: str,
    matched_node_distance_m: float | None,
    pose: object,
    candidates: object,
    goal_node_id: str,
) -> dict:
    """Render the facts block from already-computed real candidates.

    Both the one-shot re-decision and the first-round prompt use this, so the
    facts a model sees always describe edges produced by the graph and the
    real pose - never a hand-written hint.
    """

    if type(node_id) is not str or node_id.strip() == "":
        raise ValueError("node_id must be a non-blank str")
    if type(goal_node_id) is not str or goal_node_id.strip() == "":
        raise ValueError("goal_node_id must be a non-blank str")
    rows = list(candidates)
    if not rows:
        raise ValueError("route facts require at least one candidate")

    facts_rows = []
    for candidate in rows:
        if candidate.from_node_id != node_id:
            raise ValueError(
                "candidate starts at "
                f"{candidate.from_node_id!r}, not the matched node {node_id!r}"
            )
        forward = (
            candidate.turn_class in _FORWARD_CLASSES and candidate.reachable
        )
        facts_rows.append(
            {
                "from_node_id": candidate.from_node_id,
                "to_node_id": candidate.to_node_id,
                "distance_m": round(candidate.distance_m, 3),
                "bearing_deg": round(math.degrees(candidate.bearing_rad), 3),
                "relative_turn_deg": round(
                    math.degrees(candidate.relative_turn_rad), 3
                ),
                "turn_class": candidate.turn_class,
                "reachable": candidate.reachable,
                "forward_candidate": forward,
                "route_node_ids": (
                    list(candidate.route_node_ids) if forward else []
                ),
            }
        )
    facts_rows.sort(
        key=lambda item: (not item["forward_candidate"], item["to_node_id"])
    )
    forward = [item for item in facts_rows if item["forward_candidate"]]
    return {
        "matched_node_id": node_id,
        "matched_node_distance_m": (
            None
            if matched_node_distance_m is None
            else round(matched_node_distance_m, 3)
        ),
        "goal_node_id": goal_node_id,
        "pose": {
            "x": round(pose.x, 3) if pose else None,
            "y": round(pose.y, 3) if pose else None,
            "heading_deg": (
                None
                if pose is None
                else round(math.degrees(pose.heading), 3)
            ),
        },
        "candidates": facts_rows,
        "forward_candidates": forward,
        "forward_candidate_count": len(forward),
        "note": (
            "route facts are computed from the map and the real pose; they are "
            "not visual evidence and cannot prove the target direction"
        ),
    }


def format_route_facts(facts: Mapping[str, Any], *, target: str) -> str:
    """Render route facts for the model prompt without recommending a choice."""

    if not isinstance(facts, Mapping):
        raise TypeError("facts must be a mapping")
    if type(target) is not str or target.strip() == "":
        raise ValueError("target must be a non-blank str")
    node_id = facts["matched_node_id"]
    lines = [
        "【路线事实】以下由地图和当前真实位姿计算，不是从图像中看到的视觉证据，"
        f"也不能单独证明 {target} 位于哪个方向。",
        f"当前位姿匹配路点：{node_id}"
        + (
            ""
            if facts.get("matched_node_distance_m") is None
            else f"（距该路点 {facts['matched_node_distance_m']:.3f} m）"
        )
        + "。",
        f"从 {node_id} 出发的边：",
    ]
    for candidate in facts["candidates"]:
        label = TURN_CLASS_LABEL.get(
            candidate["turn_class"], candidate["turn_class"]
        )
        reachable = "可到达目标" if candidate["reachable"] else "不可到达目标"
        kind = (
            "属于向前候选"
            if candidate["forward_candidate"]
            else "不构成向前候选"
        )
        line = (
            f"- {candidate['from_node_id']}->{candidate['to_node_id']}："
            f"{label}，相对车头 {candidate['relative_turn_deg']:+.1f}°，"
            f"{reachable}，{kind}。"
        )
        if candidate["forward_candidate"] and candidate["route_node_ids"]:
            line += (
                " 该边之后到目标的参考节点："
                + "→".join(candidate["route_node_ids"])
                + "。"
            )
        lines.append(line)
    if facts["forward_candidate_count"]:
        summary = "、".join(
            f"{item['from_node_id']}->{item['to_node_id']}"
            f"（{TURN_CLASS_LABEL.get(item['turn_class'], item['turn_class'])}）"
            for item in facts["forward_candidates"]
        )
        lines.append(f"可向前行驶且可到达目标的候选边：{summary}。")
    else:
        lines.append("没有可向前行驶且可到达目标的候选边。")
    lines.append(
        "这些事实只说明几何上哪些边可行；目标是否可见、位于画面哪一侧，"
        "仍须由图像证据判断。"
    )
    return "\n".join(lines)


def _context_note(
    *,
    original_outcome: DecisionOutcome,
    arbitration: RouteArbitrationResult,
    observation: CarlaVisualObservation,
    history_note: str,
) -> str:
    decision = original_outcome.decision
    lines = [
        "说明：这是路口冲突后的同帧重新判断。原始判断之后车辆没有移动，"
        f"本请求仍使用同一张图像（frame_id={observation.frame.frame_id}），"
        "不是新的视觉观察。",
        "原始判断："
        + (
            "无结构化结论。"
            if decision is None
            else (
                f"Relative position={decision.position}，"
                f"Next direction={decision.direction}，"
                f"Evidence={decision.evidence}。"
            )
        ),
        f"原始路线仲裁：{arbitration.status}；{arbitration.reason}",
    ]
    if history_note:
        lines.append(history_note.rstrip())
    return "\n".join(lines)


def run_route_redecision(
    *,
    graph: RouteGraph,
    arbitration: RouteArbitrationResult,
    original_outcome: DecisionOutcome,
    observation: CarlaVisualObservation,
    goal_node_id: str,
    expected_identity: str,
    intent_id: str,
    model: ModelClient,
    instruction: str,
    target_kind: str,
    target_note: str = "",
    history_note: str = "",
    current_state: Mapping[str, Any] | None = None,
    stop_speed_mps: float = 0.25,
    max_pose_delta_m: float = 0.05,
    max_yaw_delta_deg: float = 0.5,
    max_node_distance_m: float = 2.0,
    straight_tolerance_deg: float = 10.0,
    turn_limit_deg: float = 150.0,
    edge_ambiguity_tolerance_deg: float = 5.0,
    invert_turn_direction: bool = False,
    blocked_edges: object = None,
    excluded_nodes: object = None,
) -> RouteRedecisionResult:
    """Perform at most one extra decision after ``no_compatible_route``.

    This function does not move the vehicle, register a permit or submit to the
    Kernel. The caller must check ``selected`` and then use the existing
    execution gate with ``result.arbitration``.
    """

    if not isinstance(arbitration, RouteArbitrationResult):
        raise TypeError("arbitration must be a RouteArbitrationResult")
    if not isinstance(original_outcome, DecisionOutcome):
        raise TypeError("original_outcome must be a DecisionOutcome")
    if not isinstance(observation, CarlaVisualObservation):
        raise TypeError("observation must be a CarlaVisualObservation")
    if not isinstance(graph, RouteGraph):
        raise TypeError("graph must be a RouteGraph")
    if not isinstance(model, ModelClient):
        raise TypeError("model must be a ModelClient")
    for name, value in (
        ("goal_node_id", goal_node_id),
        ("expected_identity", expected_identity),
        ("intent_id", intent_id),
        ("instruction", instruction),
        ("target_kind", target_kind),
    ):
        if type(value) is not str or value.strip() == "":
            raise ValueError(f"{name} must be a non-blank str")
    if type(target_note) is not str:
        raise ValueError("target_note must be a str")
    if type(history_note) is not str:
        raise ValueError("history_note must be a str")

    if arbitration.status != RouteArbitrationStatus.NO_COMPATIBLE_ROUTE:
        return RouteRedecisionResult(
            status=RouteRedecisionStatus.NOT_APPLICABLE,
            attempted=False,
            trigger_status=arbitration.status,
            reason="the original arbitration did not report no_compatible_route",
            frame_id=observation.frame.frame_id,
        )

    stationarity_error = _stationarity_error(
        observation=observation,
        current_state=current_state,
        stop_speed_mps=float(stop_speed_mps),
        max_pose_delta_m=float(max_pose_delta_m),
        max_yaw_delta_deg=float(max_yaw_delta_deg),
    )
    if stationarity_error is not None:
        status, reason = stationarity_error
        return RouteRedecisionResult(
            status=status,
            attempted=False,
            trigger_status=arbitration.status,
            reason=reason,
            frame_id=observation.frame.frame_id,
            same_frame=False,
            vehicle_stationary=False,
            current_state=current_state,
        )

    # From here the same frame may be reused: the vehicle is stopped and its
    # pose is unchanged (or the caller supplied no state to verify).
    vehicle_stationary = None if current_state is None else True

    try:
        facts = build_route_facts(
            arbitration=arbitration,
            graph=graph,
            goal_node_id=goal_node_id,
        )
        route_text = format_route_facts(facts, target=expected_identity)
        note = _context_note(
            original_outcome=original_outcome,
            arbitration=arbitration,
            observation=observation,
            history_note=history_note,
        )
        prompt = build_nav_prompt(
            Variant.TARGET_DIRECTION,
            target=expected_identity,
            intent_id=intent_id,
            target_kind=target_kind,
            target_note=target_note,
            require_identity=True,
            require_evidence=True,
            route_context=route_text,
            context_note=note,
            clarify_decision_fields=True,
        )
    except Exception as exc:
        return RouteRedecisionResult(
            status=RouteRedecisionStatus.CONTEXT_UNAVAILABLE,
            attempted=False,
            trigger_status=arbitration.status,
            reason=f"cannot build route context: {type(exc).__name__}: {exc}",
            frame_id=observation.frame.frame_id,
            current_state=current_state,
            vehicle_stationary=vehicle_stationary,
        )

    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    reobservation = CarlaVisualObservation(
        frame=observation.frame,
        image_path=observation.image_path,
        image_sha256=observation.image_sha256,
        image_size_bytes=observation.image_size_bytes,
        pose=observation.pose,
        instruction=instruction,
        prompt=prompt,
    )

    try:
        outcome = generate_and_decide(
            model,
            reobservation,
            expected_identity=expected_identity,
            intent_id=intent_id,
        )
    except Exception as exc:
        return RouteRedecisionResult(
            status=RouteRedecisionStatus.ERROR,
            attempted=True,
            trigger_status=arbitration.status,
            reason=f"re-decision call raised: {type(exc).__name__}: {exc}",
            route_facts=facts,
            prompt=prompt,
            prompt_sha256=prompt_sha,
            intent_id=intent_id,
            frame_id=observation.frame.frame_id,
            current_state=current_state,
            vehicle_stationary=vehicle_stationary,
        )

    if outcome.status != SUCCESS:
        status = {
            MODEL_REQUEST_FAILED: RouteRedecisionStatus.MODEL_REQUEST_FAILED,
            MODEL_OUTPUT_INVALID: RouteRedecisionStatus.MODEL_OUTPUT_INVALID,
            INTENT_REJECTED: RouteRedecisionStatus.INTENT_REJECTED,
        }.get(outcome.status, RouteRedecisionStatus.ERROR)
        return RouteRedecisionResult(
            status=status,
            attempted=True,
            trigger_status=arbitration.status,
            reason=(
                f"re-decision did not produce a usable directive: {outcome.status}"
                + (
                    ""
                    if outcome.error_message is None
                    else f" ({outcome.error_type}: {outcome.error_message})"
                )
            ),
            route_facts=facts,
            prompt=prompt,
            prompt_sha256=prompt_sha,
            outcome=outcome,
            intent_id=intent_id,
            frame_id=observation.frame.frame_id,
            current_state=current_state,
            vehicle_stationary=vehicle_stationary,
        )

    assert outcome.intent is not None  # guaranteed by generate_and_decide on SUCCESS
    try:
        new_arbitration = arbitrate_route(
            graph,
            observation.pose,
            outcome.directive,
            intent=outcome.intent,
            goal_node_id=goal_node_id,
            expected_node_id=arbitration.matched_node_id,
            max_node_distance_m=float(max_node_distance_m),
            straight_tolerance_deg=float(straight_tolerance_deg),
            turn_limit_deg=float(turn_limit_deg),
            edge_ambiguity_tolerance_deg=float(edge_ambiguity_tolerance_deg),
            safety_ok=True,
            invert_turn_direction=invert_turn_direction,
            blocked_edges=blocked_edges,
            excluded_nodes=excluded_nodes,
        )
    except Exception as exc:
        return RouteRedecisionResult(
            status=RouteRedecisionStatus.ERROR,
            attempted=True,
            trigger_status=arbitration.status,
            reason=f"re-decision arbitration raised: {type(exc).__name__}: {exc}",
            route_facts=facts,
            prompt=prompt,
            prompt_sha256=prompt_sha,
            outcome=outcome,
            intent_id=intent_id,
            frame_id=observation.frame.frame_id,
            current_state=current_state,
            vehicle_stationary=vehicle_stationary,
        )

    if new_arbitration.status != RouteArbitrationStatus.SELECTED:
        return RouteRedecisionResult(
            status=RouteRedecisionStatus.ARBITRATION_REFUSED,
            attempted=True,
            trigger_status=arbitration.status,
            reason=(
                "re-decision still conflicts with the feasible routes: "
                f"{new_arbitration.status}: {new_arbitration.reason}"
            ),
            route_facts=facts,
            prompt=prompt,
            prompt_sha256=prompt_sha,
            outcome=outcome,
            arbitration=new_arbitration,
            intent=outcome.intent,
            intent_id=intent_id,
            frame_id=observation.frame.frame_id,
            current_state=current_state,
            vehicle_stationary=vehicle_stationary,
        )

    return RouteRedecisionResult(
        status=RouteRedecisionStatus.SELECTED,
        attempted=True,
        trigger_status=arbitration.status,
        reason=(
            f"re-decision selected {new_arbitration.selected_edge} and passed "
            "the existing parser, verifier and route arbitration"
        ),
        route_facts=facts,
        prompt=prompt,
        prompt_sha256=prompt_sha,
        outcome=outcome,
        arbitration=new_arbitration,
        intent=outcome.intent,
        intent_id=intent_id,
        frame_id=observation.frame.frame_id,
        same_frame=True,
        vehicle_stationary=vehicle_stationary,
        current_state=current_state,
    )
