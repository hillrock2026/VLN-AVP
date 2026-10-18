"""NAV-17: verified navigation decision -> NAV-16 route-planning bridge.

The bridge exists because the two layers speak different, already-frozen
contracts:

* NAV-15 produces a :class:`~vln.nav.visual_decision.NavigationDirective`
  (``direction`` is one of ``LEFT`` / ``RIGHT`` / ``STRAIGHT``) and maps it to an
  ``AgentIntent v1`` whose only payload is ``target.x/y/heading``;
* ``AgentIntent v1`` has **no** ``direction``, ``turn`` or ``landmark`` field.
  It therefore cannot, on its own, establish a navigation-direction constraint;
* NAV-16 plans over an explicit topological graph and accepts optional extra
  hard constraints through ``vln.planning_ltm.selector.plan``.

The bridge therefore introduces one explicit input type, :class:`NavigationConstraint`,
and two provenance-preserving factories:

``constraint_from_directive``
    Only accepts a verified :class:`NavigationDirective` plus a caller-supplied
    :class:`~vln.nav.adapter.VehiclePose`. It reuses the declared
    ``DIRECTION_HEADING_DELTA`` convention (the same one ``to_agent_intent``
    uses) to derive the required first-segment heading.
``synthetic_navigation_constraint``
    Explicitly marks a constraint as offline/synthetic (``source`` is
    ``"synthetic-offline"``). Tests and demos use this; it is never presented as
    real model output.

Semantics
---------
The navigation direction is a **hard constraint** (``NavigationConstraint.HARD``):

    a candidate route is compatible iff the heading of its first topological
    segment is within ``tolerance_rad`` of

        normalize(reference_heading + DIRECTION_HEADING_DELTA[direction])

A violating candidate is rejected before NAV-16 computes any cost or applies
LTM. LTM and route cost can only order candidates that already satisfy the hard
constraint. If no candidate satisfies it, the bridge returns an explicit
``constraint-conflict`` and selects nothing; it never falls back to a violating
route.

The pose is supplied by the caller and is not sourced here. Whether it is
simulated or real is the caller's provenance; the bridge itself makes no
localisation claim and performs no model inference, host call or vehicle motion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from vln.intent.agent_intent import AgentIntent, normalize_heading
from vln.planning_ltm.costs import DEFAULT_COST_WEIGHTS, CostWeights
from vln.planning_ltm.errors import TopologyValidationError
from vln.planning_ltm.ltm import LongTermMemoryStore
from vln.planning_ltm.models import (
    CandidateEvaluation,
    ConstraintViolation,
    ParkingScene,
    PlanningResult,
    RouteCandidate,
    ViolationCode,
)
from vln.planning_ltm.selector import MODE_BASE, MODE_LTM, plan

from .adapter import DIRECTION_HEADING_DELTA, VehiclePose
from .errors import NavigationConstraintError
from .visual_decision import NavigationDirective

__all__ = [
    "ConstraintSource",
    "ConstraintBuildStatus",
    "ConstraintBuildResult",
    "NavigationConstraint",
    "NavigationPlanningStatus",
    "NavigationPlanningResult",
    "DEFAULT_TOLERANCE_DEG",
    "constraint_from_directive",
    "constraint_from_agent_intent",
    "synthetic_navigation_constraint",
    "plan_with_navigation_constraint",
]


class ConstraintSource:
    """Where a constraint came from. Kept explicit so synthetic data cannot be
    mistaken for a verified upstream decision."""

    VERIFIED_DIRECTIVE = "verified-directive"
    SYNTHETIC_OFFLINE = "synthetic-offline"
    ALL = frozenset({VERIFIED_DIRECTIVE, SYNTHETIC_OFFLINE})


class ConstraintBuildStatus:
    OK = "ok"
    INSUFFICIENT = "insufficient"
    INVALID = "invalid"
    ALL = frozenset({OK, INSUFFICIENT, INVALID})


class NavigationPlanningStatus:
    SELECTED = "selected"
    CONSTRAINT_CONFLICT = "constraint-conflict"
    NO_FEASIBLE_ROUTE = "no-feasible-route"
    NO_CANDIDATES = "no-candidates"
    ALL = frozenset(
        {SELECTED, CONSTRAINT_CONFLICT, NO_FEASIBLE_ROUTE, NO_CANDIDATES}
    )


DEFAULT_TOLERANCE_DEG = 45.0


def _require_finite(value: object, name: str) -> float:
    if type(value) is not int and type(value) is not float:
        raise NavigationConstraintError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise NavigationConstraintError(f"{name} must be finite")
    return number


def _angular_difference(first: float, second: float) -> float:
    return abs((first - second + math.pi) % (2.0 * math.pi) - math.pi)


@dataclass(frozen=True)
class NavigationConstraint:
    """A hard navigation-direction constraint over the synthetic local frame.

    ``source`` is mandatory: a constraint must say whether it came from a
    verified directive or from offline synthetic data. The direction is always
    hard; there is no soft-direction mode in this version.
    """

    direction: str
    reference_heading: float
    source: str
    tolerance_rad: float = math.radians(DEFAULT_TOLERANCE_DEG)
    identified_as: str = ""
    evidence: str = ""

    #: A navigation direction is never a soft preference in this contract.
    HARD = True

    def __post_init__(self) -> None:
        if self.direction not in DIRECTION_HEADING_DELTA:
            raise NavigationConstraintError(
                f"unsupported navigation direction {self.direction!r}; "
                f"supported directions are {sorted(DIRECTION_HEADING_DELTA)}"
            )
        if self.source not in ConstraintSource.ALL:
            raise NavigationConstraintError(
                f"unsupported constraint source {self.source!r}; "
                f"supported sources are {sorted(ConstraintSource.ALL)}"
            )
        reference = _require_finite(self.reference_heading, "reference_heading")
        tolerance = _require_finite(self.tolerance_rad, "tolerance_rad")
        if tolerance <= 0.0 or tolerance >= math.pi / 2.0:
            raise NavigationConstraintError(
                "tolerance_rad must be in (0, pi/2) so directions stay distinct"
            )
        if not isinstance(self.identified_as, str):
            raise NavigationConstraintError("identified_as must be a str")
        if not isinstance(self.evidence, str):
            raise NavigationConstraintError("evidence must be a str")
        object.__setattr__(self, "reference_heading", normalize_heading(reference))
        object.__setattr__(self, "tolerance_rad", tolerance)

    @property
    def required_heading(self) -> float:
        return normalize_heading(
            self.reference_heading + DIRECTION_HEADING_DELTA[self.direction]
        )

    @property
    def tolerance_deg(self) -> float:
        return math.degrees(self.tolerance_rad)

    def first_segment_heading(
        self, scene: ParkingScene, candidate: RouteCandidate
    ) -> float:
        if not isinstance(scene, ParkingScene):
            raise NavigationConstraintError("scene must be a ParkingScene")
        if not isinstance(candidate, RouteCandidate):
            raise NavigationConstraintError("candidate must be a RouteCandidate")
        try:
            first = scene.topology.node(candidate.node_ids[0])
            second = scene.topology.node(candidate.node_ids[1])
        except TopologyValidationError as exc:
            raise NavigationConstraintError(
                "candidate contains a node that does not exist in the scene topology"
            ) from exc
        return math.atan2(second.y - first.y, second.x - first.x)

    def angular_error(self, scene: ParkingScene, candidate: RouteCandidate) -> float:
        return _angular_difference(
            self.first_segment_heading(scene, candidate), self.required_heading
        )

    def satisfies(self, scene: ParkingScene, candidate: RouteCandidate) -> bool:
        return self.angular_error(scene, candidate) <= self.tolerance_rad + 1e-12

    def violation_for(
        self, scene: ParkingScene, candidate: RouteCandidate
    ) -> ConstraintViolation | None:
        error = self.angular_error(scene, candidate)
        if error <= self.tolerance_rad + 1e-12:
            return None
        actual = self.first_segment_heading(scene, candidate)
        return ConstraintViolation(
            code=ViolationCode.NAVIGATION_DIRECTION_MISMATCH,
            message=(
                f"first segment heading {math.degrees(actual):.1f}° does not match "
                f"hard navigation direction {self.direction!r} (required "
                f"{math.degrees(self.required_heading):.1f}° from reference "
                f"{math.degrees(self.reference_heading):.1f}°, tolerance "
                f"{self.tolerance_deg:.1f}°)"
            ),
        )

    def violations(
        self, scene: ParkingScene, candidate: RouteCandidate
    ) -> tuple[ConstraintViolation, ...]:
        """NAV-16 extra-hard-constraint hook.

        If a candidate contains unknown nodes, the base hard-constraint checker
        already reports that; the bridge does not turn it into a second error.
        Wrong argument types are still refused.
        """

        if not isinstance(scene, ParkingScene):
            raise NavigationConstraintError("scene must be a ParkingScene")
        if not isinstance(candidate, RouteCandidate):
            raise NavigationConstraintError("candidate must be a RouteCandidate")
        try:
            violation = self.violation_for(scene, candidate)
        except NavigationConstraintError:
            return ()
        return () if violation is None else (violation,)

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "hard": self.HARD,
            "reference_heading": self.reference_heading,
            "required_heading": self.required_heading,
            "tolerance_deg": self.tolerance_deg,
            "source": self.source,
            "identified_as": self.identified_as,
            "evidence": self.evidence,
            "semantics": (
                "candidate first-segment heading must be within tolerance of "
                "reference_heading + DIRECTION_HEADING_DELTA[direction]"
            ),
        }


@dataclass(frozen=True)
class ConstraintBuildResult:
    """Outcome of attempting to derive a constraint from an upstream object."""

    status: str
    constraint: NavigationConstraint | None
    reason: str
    input_type: str
    intent_id: str | None = None

    def __post_init__(self) -> None:
        if self.status not in ConstraintBuildStatus.ALL:
            raise NavigationConstraintError(f"unknown build status {self.status!r}")
        if self.status == ConstraintBuildStatus.OK:
            if not isinstance(self.constraint, NavigationConstraint):
                raise NavigationConstraintError(
                    "an ok build result must carry a NavigationConstraint"
                )
        elif self.constraint is not None:
            raise NavigationConstraintError(
                "a failed build result must not carry a constraint"
            )
        if not isinstance(self.reason, str) or self.reason.strip() == "":
            raise NavigationConstraintError("reason must be a non-blank str")

    @property
    def ok(self) -> bool:
        return self.status == ConstraintBuildStatus.OK

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "constraint": None if self.constraint is None else self.constraint.to_dict(),
            "reason": self.reason,
            "input_type": self.input_type,
            "intent_id": self.intent_id,
        }


def constraint_from_directive(
    directive: object,
    *,
    pose: object,
    tolerance_deg: float = DEFAULT_TOLERANCE_DEG,
) -> NavigationConstraint:
    """Build a hard constraint from a *verified* directive and caller pose.

    The input type is the guarantee: only
    :func:`~vln.nav.visual_decision.verify_visual_decision` produces a
    ``NavigationDirective``. The pose is caller-supplied; the bridge never
    invents or localises one.
    """

    if not isinstance(directive, NavigationDirective):
        raise NavigationConstraintError(
            "expected a verified NavigationDirective; got "
            f"{type(directive).__name__}"
        )
    if not isinstance(pose, VehiclePose):
        raise NavigationConstraintError(
            f"a VehiclePose is required to derive the reference heading; got "
            f"{type(pose).__name__}"
        )
    tolerance = _require_finite(tolerance_deg, "tolerance_deg")
    return NavigationConstraint(
        direction=directive.direction,
        reference_heading=pose.heading,
        source=ConstraintSource.VERIFIED_DIRECTIVE,
        tolerance_rad=math.radians(tolerance),
        identified_as=directive.identified_as,
        evidence=directive.evidence,
    )


def synthetic_navigation_constraint(
    direction: str,
    *,
    reference_heading: float = 0.0,
    tolerance_deg: float = DEFAULT_TOLERANCE_DEG,
    evidence: str = "offline synthetic constraint; not model output",
) -> NavigationConstraint:
    """Build a constraint explicitly marked as offline/synthetic.

    This is the only sanctioned path for tests and demos that do not have a
    verified upstream directive.
    """

    tolerance = _require_finite(tolerance_deg, "tolerance_deg")
    return NavigationConstraint(
        direction=direction,
        reference_heading=reference_heading,
        source=ConstraintSource.SYNTHETIC_OFFLINE,
        tolerance_rad=math.radians(tolerance),
        identified_as="",
        evidence=evidence,
    )


def constraint_from_agent_intent(
    intent: object, *, pose: VehiclePose | None = None
) -> ConstraintBuildResult:
    """Try to derive a direction constraint from an ``AgentIntent``.

    ``AgentIntent v1`` contains only ``contract_version``, ``intent_id``,
    ``action`` and ``target{x,y,heading}``. It has no direction/turn/landmark
    field, so this function deliberately returns ``insufficient`` rather than
    guessing a direction from the target heading or from a previous round.
    """

    if not isinstance(intent, AgentIntent):
        return ConstraintBuildResult(
            status=ConstraintBuildStatus.INVALID,
            constraint=None,
            reason=(
                "expected an AgentIntent; got "
                f"{type(intent).__name__}"
            ),
            input_type="AgentIntent",
        )
    return ConstraintBuildResult(
        status=ConstraintBuildStatus.INSUFFICIENT,
        constraint=None,
        reason=(
            "AgentIntent v1 exposes contract_version, intent_id, action and "
            "target{x,y,heading} only; it has no direction, turn or landmark "
            "field. A navigation constraint cannot be derived without inventing "
            "data. Use a verified NavigationDirective plus a caller-supplied "
            "VehiclePose."
        ),
        input_type="AgentIntent",
        intent_id=intent.intent_id,
    )


@dataclass(frozen=True)
class NavigationPlanningResult:
    """NAV-16 planning result plus the bridge's constraint diagnostics."""

    constraint: NavigationConstraint
    planning: PlanningResult
    status: str
    constraint_conflict: bool
    satisfying_candidate_ids: tuple[str, ...]
    violating_candidate_ids: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.constraint, NavigationConstraint):
            raise NavigationConstraintError("constraint must be a NavigationConstraint")
        if not isinstance(self.planning, PlanningResult):
            raise NavigationConstraintError("planning must be a PlanningResult")
        if self.status not in NavigationPlanningStatus.ALL:
            raise NavigationConstraintError(f"unknown planning status {self.status!r}")
        selected = self.planning.selection.selected_candidate_id
        if selected is not None:
            if self.status != NavigationPlanningStatus.SELECTED:
                raise NavigationConstraintError(
                    "a selected candidate requires status 'selected'"
                )
            if selected not in self.satisfying_candidate_ids:
                raise NavigationConstraintError(
                    "the planner selected a candidate that does not satisfy the "
                    "hard navigation constraint"
                )
        elif self.status == NavigationPlanningStatus.SELECTED:
            raise NavigationConstraintError(
                "status 'selected' requires a selected candidate"
            )
        if self.constraint_conflict != (
            self.status == NavigationPlanningStatus.CONSTRAINT_CONFLICT
        ):
            raise NavigationConstraintError(
                "constraint_conflict must match the constraint-conflict status"
            )
        if not isinstance(self.reason, str) or self.reason.strip() == "":
            raise NavigationConstraintError("reason must be a non-blank str")

    @property
    def selected_candidate_id(self) -> str | None:
        return self.planning.selection.selected_candidate_id

    @property
    def selected_evaluation(self) -> CandidateEvaluation | None:
        return self.planning.selection.selected_evaluation()

    @property
    def selected_route_satisfies_constraint(self) -> bool | None:
        if self.selected_candidate_id is None:
            return None
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint": self.constraint.to_dict(),
            "status": self.status,
            "constraint_conflict": self.constraint_conflict,
            "satisfying_candidate_ids": list(self.satisfying_candidate_ids),
            "violating_candidate_ids": list(self.violating_candidate_ids),
            "selected_candidate_id": self.selected_candidate_id,
            "selected_route_satisfies_constraint": (
                self.selected_route_satisfies_constraint
            ),
            "reason": self.reason,
            "planning": self.planning.to_dict(),
        }


def plan_with_navigation_constraint(
    scene: ParkingScene,
    constraint: NavigationConstraint | None,
    *,
    mode: str = MODE_BASE,
    ltm_store: LongTermMemoryStore | None = None,
    as_of: datetime | str | None = None,
    weights: CostWeights = DEFAULT_COST_WEIGHTS,
    max_candidates: int = 3,
) -> NavigationPlanningResult:
    """Plan routes with a hard navigation-direction constraint.

    The constraint is passed into NAV-16's extra-hard-constraint hook, so it is
    evaluated together with the scene constraints **before** cost and LTM. The
    wrapper only classifies the result and explains it; route search, cost and
    selection remain NAV-16's.
    """

    if constraint is None:
        raise NavigationConstraintError(
            "a NavigationConstraint is required; a missing constraint is refused "
            "rather than silently ignored"
        )
    if not isinstance(constraint, NavigationConstraint):
        raise NavigationConstraintError(
            f"constraint must be a NavigationConstraint; got "
            f"{type(constraint).__name__}"
        )
    if not isinstance(scene, ParkingScene):
        raise NavigationConstraintError("scene must be a ParkingScene")

    planning = plan(
        scene,
        mode=mode,
        ltm_store=ltm_store,
        as_of=as_of,
        weights=weights,
        max_candidates=max_candidates,
        extra_hard_constraint=constraint.violations,
    )

    evaluations = planning.selection.evaluations
    satisfying = tuple(
        evaluation.candidate_id
        for evaluation in evaluations
        if constraint.satisfies(scene, evaluation.candidate)
    )
    violating = tuple(
        evaluation.candidate_id
        for evaluation in evaluations
        if evaluation.candidate_id not in satisfying
    )

    selected = planning.selection.selected_candidate_id
    if not evaluations:
        status = NavigationPlanningStatus.NO_CANDIDATES
        conflict = False
        reason = (
            "no candidate routes were generated for this scene/target; no route "
            "was selected and no route was fabricated"
        )
    elif not satisfying:
        status = NavigationPlanningStatus.CONSTRAINT_CONFLICT
        conflict = True
        reason = (
            f"no candidate satisfies the hard navigation constraint "
            f"{constraint.direction!r} (required heading "
            f"{math.degrees(constraint.required_heading):.1f}°, tolerance "
            f"{constraint.tolerance_deg:.1f}°); no violating fallback was "
            f"selected. {planning.selection.no_solution_reason or ''}"
        ).strip()
    elif selected is None:
        status = NavigationPlanningStatus.NO_FEASIBLE_ROUTE
        conflict = False
        reason = (
            f"candidate(s) {list(satisfying)} satisfy the hard navigation "
            "constraint, but none is feasible after scene constraints; no route "
            f"was selected. {planning.selection.no_solution_reason or ''}"
        ).strip()
    else:
        status = NavigationPlanningStatus.SELECTED
        conflict = False
        reason = (
            f"{planning.selection.selection_reason}; hard navigation constraint "
            f"{constraint.direction!r} is satisfied by the selected candidate "
            f"{selected}"
        )

    return NavigationPlanningResult(
        constraint=constraint,
        planning=planning,
        status=status,
        constraint_conflict=conflict,
        satisfying_candidate_ids=satisfying,
        violating_candidate_ids=violating,
        reason=reason,
    )
