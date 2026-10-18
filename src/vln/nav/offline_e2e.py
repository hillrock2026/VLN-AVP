"""NAV-18: offline end-to-end vision decision -> planner entry point.

One call performs the following, using the existing layers only:

    VisualDecisionInput (raw decision text + declared provenance)
        -> parse_visual_decision                 (vln.nav.visual_decision)
        -> verify_visual_decision                -> NavigationDirective
        -> constraint_from_directive(+ pose)     -> NavigationConstraint
        -> plan_with_navigation_constraint       (NAV-17 -> NAV-16)
        -> OfflineEndToEndResult

The entry point does **not** run a model, open an image, contact a host/kernel,
execute a route or claim physical arrival. It is a deterministic offline
integration of already-existing pieces.

Provenance is explicit. ``VisualDecisionInput.source`` is one of:

* ``frozen-replay`` - text previously produced by a real model run (the NAV-15
  RAW fixture), replayed here without a new inference;
* ``synthetic`` - text constructed for an offline test/demo;
* ``live-model`` - reserved for a caller that just ran a real model. This module
  never produces it by itself.

The NAV-17 constraint factory records ``verified-directive`` at the *type* level
(it consumed a value that only the verifier produces). That is deliberately not
the same thing as the input provenance: a synthetic decision that passes the
real parser/verifier still carries ``source="synthetic"`` in the end-to-end
result, so it is never reported as live model output.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from vln.planning_ltm.costs import DEFAULT_COST_WEIGHTS, CostWeights
from vln.planning_ltm.ltm import LongTermMemoryStore
from vln.planning_ltm.models import (
    ParkingScene,
    ParkingTopology,
    TopologyEdge,
    TopologyNode,
)
from vln.planning_ltm.selector import MODE_BASE

from .adapter import VehiclePose
from .errors import NavigationConstraintError, NavigationDecisionError
from .planner_bridge import (
    ConstraintSource,
    NavigationConstraint,
    NavigationPlanningResult,
    NavigationPlanningStatus,
    constraint_from_directive,
    plan_with_navigation_constraint,
)
from .visual_decision import (
    NavigationDirective,
    VisualNavigationDecision,
    parse_visual_decision,
    verify_visual_decision,
)

__all__ = [
    "DecisionSource",
    "DemoCase",
    "OfflineEndToEndResult",
    "OfflineEndToEndStatus",
    "VisualDecisionInput",
    "run_offline_decision",
    "direction_scene",
    "straight_only_scene",
    "frozen_nav15_decision",
    "invalid_decision_input",
    "synthetic_left_decision",
    "demo_cases",
    "build_demo",
    "main",
    "DEMO_AS_OF",
    "DEMO_POSE",
    "NAV15_RAW_REF",
]


class DecisionSource:
    """Declared provenance of the visual decision text."""

    LIVE_MODEL = "live-model"
    FROZEN_REPLAY = "frozen-replay"
    SYNTHETIC = "synthetic"
    ALL = frozenset({LIVE_MODEL, FROZEN_REPLAY, SYNTHETIC})


class OfflineEndToEndStatus:
    """Status of the whole offline chain; planning statuses are reused verbatim."""

    DECISION_INVALID = "decision-invalid"
    CONSTRAINT_INSUFFICIENT = "constraint-insufficient"
    SELECTED = NavigationPlanningStatus.SELECTED
    CONSTRAINT_CONFLICT = NavigationPlanningStatus.CONSTRAINT_CONFLICT
    NO_FEASIBLE_ROUTE = NavigationPlanningStatus.NO_FEASIBLE_ROUTE
    NO_CANDIDATES = NavigationPlanningStatus.NO_CANDIDATES
    ALL = frozenset(
        {
            DECISION_INVALID,
            CONSTRAINT_INSUFFICIENT,
            SELECTED,
            CONSTRAINT_CONFLICT,
            NO_FEASIBLE_ROUTE,
            NO_CANDIDATES,
        }
    )


@dataclass(frozen=True)
class VisualDecisionInput:
    """Raw navigation-decision text plus its declared provenance."""

    raw_text: str
    expected_identity: str
    source: str
    source_ref: str = ""
    model: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.raw_text, str):
            raise TypeError("raw_text must be a str")
        if not isinstance(self.expected_identity, str) or not self.expected_identity.strip():
            raise ValueError("expected_identity must be a non-blank str")
        if self.source not in DecisionSource.ALL:
            raise ValueError(
                f"unknown decision source {self.source!r}; "
                f"expected one of {sorted(DecisionSource.ALL)}"
            )
        for name in ("source_ref", "model", "note"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"{name} must be a str")
        if self.source in (DecisionSource.LIVE_MODEL, DecisionSource.FROZEN_REPLAY):
            if self.source_ref.strip() == "":
                raise ValueError(
                    f"{self.source} input requires a non-blank source_ref for traceability"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_ref": self.source_ref,
            "model": self.model,
            "expected_identity": self.expected_identity,
            "raw_text": self.raw_text,
            "note": self.note,
        }


@dataclass(frozen=True)
class OfflineEndToEndResult:
    """Traceable result of one offline decision -> constraint -> planning run."""

    scene_id: str
    target_id: str
    decision_input: VisualDecisionInput
    pose: VehiclePose
    status: str
    reason: str
    decision: VisualNavigationDecision | None = None
    directive: NavigationDirective | None = None
    constraint: NavigationConstraint | None = None
    planning: NavigationPlanningResult | None = None
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.status not in OfflineEndToEndStatus.ALL:
            raise ValueError(f"unknown end-to-end status {self.status!r}")
        if not isinstance(self.reason, str) or self.reason.strip() == "":
            raise ValueError("reason must be a non-blank str")
        if not isinstance(self.decision_input, VisualDecisionInput):
            raise TypeError("decision_input must be a VisualDecisionInput")
        if not isinstance(self.pose, VehiclePose):
            raise TypeError("pose must be a VehiclePose")
        if self.status in (
            OfflineEndToEndStatus.DECISION_INVALID,
            OfflineEndToEndStatus.CONSTRAINT_INSUFFICIENT,
        ):
            if self.planning is not None:
                raise ValueError("a pre-planning failure must not carry a planning result")
        else:
            if self.planning is None or self.constraint is None:
                raise ValueError("a planning status requires constraint and planning")
        if self.status == OfflineEndToEndStatus.SELECTED:
            if self.planning is None or self.planning.selected_candidate_id is None:
                raise ValueError("'selected' status requires a selected candidate")

    @property
    def ok(self) -> bool:
        return self.status == OfflineEndToEndStatus.SELECTED

    @property
    def selected_candidate_id(self) -> str | None:
        if self.planning is None:
            return None
        return self.planning.selected_candidate_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "target_id": self.target_id,
            "status": self.status,
            "ok": self.ok,
            "reason": self.reason,
            "decision_input": self.decision_input.to_dict(),
            "pose": {
                "x": self.pose.x,
                "y": self.pose.y,
                "heading": self.pose.heading,
                "provenance": "caller-supplied explicit pose; not localisation",
            },
            "decision": None if self.decision is None else asdict(self.decision),
            "directive": None if self.directive is None else asdict(self.directive),
            "constraint": None if self.constraint is None else self.constraint.to_dict(),
            "planning": None if self.planning is None else self.planning.to_dict(),
            "selected_candidate_id": self.selected_candidate_id,
            "error": (
                None
                if self.error_type is None
                else {"type": self.error_type, "message": self.error_message}
            ),
            "planning_only": True,
            "executed": False,
            "physical_arrival": "not-evaluated",
            "note": (
                "Offline planning only. A selected route is not an executed route "
                "and is not evidence of vehicle arrival or parking."
            ),
        }


def _pre_planning_failure(
    *,
    scene: ParkingScene,
    decision_input: VisualDecisionInput,
    pose: VehiclePose,
    status: str,
    reason: str,
    error: Exception,
    decision: VisualNavigationDecision | None = None,
    directive: NavigationDirective | None = None,
    constraint: NavigationConstraint | None = None,
) -> OfflineEndToEndResult:
    return OfflineEndToEndResult(
        scene_id=scene.scene_id,
        target_id=scene.target_id,
        decision_input=decision_input,
        pose=pose,
        status=status,
        reason=reason,
        decision=decision,
        directive=directive,
        constraint=constraint,
        planning=None,
        error_type=type(error).__name__,
        error_message=str(error),
    )


def run_offline_decision(
    scene: ParkingScene,
    decision_input: VisualDecisionInput,
    *,
    pose: VehiclePose,
    mode: str = MODE_BASE,
    ltm_store: LongTermMemoryStore | None = None,
    as_of: datetime | str | None = None,
    weights: CostWeights = DEFAULT_COST_WEIGHTS,
    max_candidates: int = 3,
) -> OfflineEndToEndResult:
    """Run the complete offline chain once; planning statuses are NAV-17's."""

    if not isinstance(scene, ParkingScene):
        raise TypeError("scene must be a ParkingScene")
    if not isinstance(decision_input, VisualDecisionInput):
        raise TypeError("decision_input must be a VisualDecisionInput")
    if not isinstance(pose, VehiclePose):
        raise TypeError("pose must be a VehiclePose")

    try:
        decision = parse_visual_decision(decision_input.raw_text)
    except NavigationDecisionError as exc:
        return _pre_planning_failure(
            scene=scene,
            decision_input=decision_input,
            pose=pose,
            status=OfflineEndToEndStatus.DECISION_INVALID,
            reason=f"visual decision text was not parsed: {exc}",
            error=exc,
        )

    try:
        directive = verify_visual_decision(
            decision, expected_identity=decision_input.expected_identity
        )
    except NavigationDecisionError as exc:
        return _pre_planning_failure(
            scene=scene,
            decision_input=decision_input,
            pose=pose,
            status=OfflineEndToEndStatus.DECISION_INVALID,
            reason=f"visual decision was parsed but failed verification: {exc}",
            error=exc,
            decision=decision,
        )

    try:
        constraint = constraint_from_directive(directive, pose=pose)
    except NavigationConstraintError as exc:
        return _pre_planning_failure(
            scene=scene,
            decision_input=decision_input,
            pose=pose,
            status=OfflineEndToEndStatus.CONSTRAINT_INSUFFICIENT,
            reason=(
                f"verified direction {directive.direction!r} could not become a "
                f"navigation constraint: {exc}"
            ),
            error=exc,
            decision=decision,
            directive=directive,
        )

    planning = plan_with_navigation_constraint(
        scene,
        constraint,
        mode=mode,
        ltm_store=ltm_store,
        as_of=as_of,
        weights=weights,
        max_candidates=max_candidates,
    )
    return OfflineEndToEndResult(
        scene_id=scene.scene_id,
        target_id=scene.target_id,
        decision_input=decision_input,
        pose=pose,
        status=planning.status,
        reason=planning.reason,
        decision=decision,
        directive=directive,
        constraint=constraint,
        planning=planning,
    )


# ----------------------------------------------------------------------
# Deterministic synthetic topologies
# ----------------------------------------------------------------------


def direction_scene() -> ParkingScene:
    """Two routes: east (straight, cost 35) and north (left, cost 34).

    The unconstrained NAV-16 planner prefers the cheaper north route. A
    STRAIGHT hard constraint therefore visibly changes the selected route.
    """

    nodes = (
        TopologyNode("S", 0.0, 0.0, kind="entrance"),
        TopologyNode("A", 5.0, 0.0),
        TopologyNode("A2", 10.0, 0.0),
        TopologyNode("B", 0.0, 10.0),
        TopologyNode("M", 10.0, 10.0),
        TopologyNode("T", 10.0, 20.0, kind="parking", target_id="T"),
    )
    edges = (
        TopologyEdge("E-S-A", "S", "A", risk=1.0),
        TopologyEdge("E-A-A2", "A", "A2", risk=1.0),
        TopologyEdge("E-A2-M", "A2", "M", risk=1.0),
        TopologyEdge("E-M-T", "M", "T", risk=0.0),
        TopologyEdge("E-S-B", "S", "B", risk=0.0),
        TopologyEdge("E-B-M", "B", "M", risk=0.0),
    )
    return ParkingScene(
        scene_id="NAV18-DIRECTION",
        topology=ParkingTopology(nodes=nodes, edges=edges),
        start_node_id="S",
        target_node_id="T",
        target_id="T",
    )


def straight_only_scene() -> ParkingScene:
    """Only the east/straight route exists; LEFT must conflict."""

    nodes = (
        TopologyNode("S", 0.0, 0.0, kind="entrance"),
        TopologyNode("A", 5.0, 0.0),
        TopologyNode("A2", 10.0, 0.0),
        TopologyNode("M", 10.0, 10.0),
        TopologyNode("T", 10.0, 20.0, kind="parking", target_id="T"),
    )
    edges = (
        TopologyEdge("E-S-A", "S", "A"),
        TopologyEdge("E-A-A2", "A", "A2"),
        TopologyEdge("E-A2-M", "A2", "M"),
        TopologyEdge("E-M-T", "M", "T"),
    )
    return ParkingScene(
        scene_id="NAV18-CONFLICT",
        topology=ParkingTopology(nodes=nodes, edges=edges),
        start_node_id="S",
        target_node_id="T",
        target_id="T",
    )


# ----------------------------------------------------------------------
# Frozen NAV-15 replay + synthetic fixtures
# ----------------------------------------------------------------------


NAV15_RAW_REF = "docs/M1-VLN-NAV-15-RAW.jsonl"
EXPECTED_IDENTITY = "出口"

#: Exact raw model text from docs/M1-VLN-NAV-15-RAW.jsonl, round 0.
#: Replayed offline; this module performs no model inference.
FROZEN_NAV15_ROUND_0_TEXT = (
    "第一步 观察：画面中可见多根立柱，立柱上有橙色条纹和白色字母“C”作为区域标识；"
    "地面有白色车位编号（如“196”）和方向箭头（包括直行和分道箭头）；"
    "左侧上方有蓝色“出口 EXIT”标识；画面中有闸门、护栏、挡车器及通道结构，"
    "中间为双向车道，两侧为停车区域。\n\n"
    "第二步 查找目标：画面中确实出现了“出口”标识，位于左侧上方蓝色指示牌上，"
    "文字为“出口 EXIT”。\n\n"
    "第三步 判断相对方位：以当前视角看，出口位于画面的左侧。\n\n"
    "第四步 给出下一步离散导航方向：从左侧可见出口标识，建议向左行驶。\n\n"
    "第五步 输出结论块：\n"
    "Target: 出口\n"
    "Identified as: 出口 EXIT\n"
    "Visible: 是\n"
    "Relative position: LEFT\n"
    "Next direction: LEFT\n"
    "Evidence: 左侧上方蓝色指示牌上清晰显示“出口 EXIT”字样。"
)

#: Exact raw model text from docs/M1-VLN-NAV-15-RAW.jsonl, round 1.
FROZEN_NAV15_ROUND_1_TEXT = (
    "Target: 出口\n"
    "Identified as: 出口\n"
    "Visible: 是\n"
    "Relative position: AHEAD\n"
    "Next direction: STRAIGHT\n"
    "Evidence: 画面正前方远处悬挂的蓝色指示牌上清晰显示“出口”字样"
)

_FROZEN_NAV15 = {
    0: {
        "text": FROZEN_NAV15_ROUND_0_TEXT,
        "image": "17931c01d3fda4038c76944a334b3aef.png",
        "direction": "LEFT",
    },
    1: {
        "text": FROZEN_NAV15_ROUND_1_TEXT,
        "image": "9a6908511ef1211af2ae8483c103bb63.png",
        "direction": "STRAIGHT",
    },
}


def frozen_nav15_decision(round_index: int) -> VisualDecisionInput:
    """Frozen NAV-15 RAW text as a replay input (no new model inference)."""

    record = _FROZEN_NAV15.get(round_index)
    if record is None:
        raise ValueError(f"no frozen NAV-15 round {round_index}; available: 0, 1")
    return VisualDecisionInput(
        raw_text=record["text"],
        expected_identity=EXPECTED_IDENTITY,
        source=DecisionSource.FROZEN_REPLAY,
        source_ref=f"{NAV15_RAW_REF}#round={round_index}",
        model="ZDTaichu5.0-9B",
        note=(
            f"Frozen replay of NAV-15 round {round_index} "
            f"(image {record['image']}); not a live inference."
        ),
    )


def invalid_decision_input() -> VisualDecisionInput:
    """Malformed synthetic decision: missing required fields."""

    return VisualDecisionInput(
        raw_text=(
            "Target: 出口\n"
            "Identified as: 出口\n"
            "Visible: 是\n"
        ),
        expected_identity=EXPECTED_IDENTITY,
        source=DecisionSource.SYNTHETIC,
        source_ref="nav18-invalid-fixture",
        note="Synthetic malformed decision; must fail before planning.",
    )


def synthetic_left_decision() -> VisualDecisionInput:
    """A well-formed synthetic LEFT decision, clearly not model output."""

    return VisualDecisionInput(
        raw_text=(
            "Target: 出口\n"
            "Identified as: 出口\n"
            "Visible: 是\n"
            "Relative position: LEFT\n"
            "Next direction: LEFT\n"
            "Evidence: 合成测试文本，并非模型输出。\n"
        ),
        expected_identity=EXPECTED_IDENTITY,
        source=DecisionSource.SYNTHETIC,
        source_ref="nav18-synthetic-left",
        note="Synthetic decision used only for deterministic offline tests.",
    )


# ----------------------------------------------------------------------
# Demo / CLI
# ----------------------------------------------------------------------


DEMO_AS_OF = "2026-10-17T00:00:00Z"
DEMO_POSE = VehiclePose(x=0.0, y=0.0, heading=0.0)


@dataclass(frozen=True)
class DemoCase:
    name: str
    scene: ParkingScene
    decision_input: VisualDecisionInput
    note: str


def demo_cases() -> tuple[DemoCase, ...]:
    return (
        DemoCase(
            name="left",
            scene=direction_scene(),
            decision_input=frozen_nav15_decision(0),
            note="Frozen NAV-15 LEFT decision; left route satisfies the constraint.",
        ),
        DemoCase(
            name="straight",
            scene=direction_scene(),
            decision_input=frozen_nav15_decision(1),
            note=(
                "Frozen NAV-15 STRAIGHT decision; the unconstrained planner would "
                "choose the cheaper north route, so the selection must change."
            ),
        ),
        DemoCase(
            name="conflict",
            scene=straight_only_scene(),
            decision_input=frozen_nav15_decision(0),
            note="Frozen LEFT decision against a topology with no left exit.",
        ),
        DemoCase(
            name="invalid",
            scene=direction_scene(),
            decision_input=invalid_decision_input(),
            note="Malformed synthetic decision; must stop before planning.",
        ),
    )


def build_demo(case: str = "all") -> dict[str, Any]:
    """Run the deterministic offline demo and return a JSON-serialisable payload."""

    valid_cases = ("all",) + tuple(item.name for item in demo_cases())
    if case not in valid_cases:
        raise ValueError(f"unknown case {case!r}; expected one of {list(valid_cases)}")
    selected_cases = [
        item for item in demo_cases() if case in ("all", item.name)
    ]

    results: list[dict[str, Any]] = []
    for item in selected_cases:
        result = run_offline_decision(
            item.scene,
            item.decision_input,
            pose=DEMO_POSE,
            as_of=DEMO_AS_OF,
        )
        results.append(
            {
                "case": item.name,
                "case_note": item.note,
                "result": result.to_dict(),
            }
        )

    return {
        "demo": "M1-VLN-NAV-18-EXEC",
        "simulation_only": True,
        "planning_only": True,
        "executed": False,
        "as_of": DEMO_AS_OF,
        "pose": {
            "x": DEMO_POSE.x,
            "y": DEMO_POSE.y,
            "heading": DEMO_POSE.heading,
            "provenance": "explicit synthetic reference pose; not localisation",
        },
        "data_sources": sorted(
            {item.decision_input.source for item in selected_cases}
        ),
        "cases": results,
        "note": (
            "Frozen NAV-15 replay + synthetic topologies. No live model, no host, "
            "no kernel, no vehicle and no execution. A selected route is a "
            "planning result only."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vln.nav.offline_e2e",
        description=(
            "Run the offline NAV-18 decision -> constraint -> planning demo "
            "(no model, host, kernel, vehicle or execution)."
        ),
    )
    parser.add_argument(
        "--case",
        default="all",
        choices=("all", "left", "straight", "conflict", "invalid"),
        help="which deterministic case to run (default: all)",
    )
    parser.add_argument(
        "--indent", type=int, default=2, help="JSON indentation (default: 2)"
    )
    args = parser.parse_args(argv)
    print(json.dumps(build_demo(args.case), ensure_ascii=False, indent=args.indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
