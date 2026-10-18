"""Candidate assessment and the two decision modes.

``base`` mode ignores LTM entirely. ``ltm`` mode first applies the same hard
constraints, then adjusts the cost of **feasible** candidates only using active,
relevant records. Historical preference therefore cannot resurrect a rejected
route, an expired record cannot dominate, and a low-confidence record is
ignored rather than treated as fact.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Iterable

from .constraints import check_hard_constraints
from .costs import DEFAULT_COST_WEIGHTS, CostWeights, compute_route_cost, with_ltm_adjustment
from .errors import PlanningValidationError
from .generation import generate_candidates
from .ltm import (
    LongTermMemoryStore,
    MemoryEffect,
    MemoryRecord,
    ensure_utc,
)
from .models import (
    CandidateEvaluation,
    CandidateSet,
    ConstraintViolation,
    IgnoredMemory,
    MemoryApplication,
    ParkingScene,
    PlanningResult,
    RouteCandidate,
    SelectionResult,
)

__all__ = [
    "MODE_BASE",
    "MODE_LTM",
    "LTM_MIN_CONFIDENCE",
    "LTM_PREFER_BONUS",
    "LTM_AVOID_PENALTY",
    "LTM_MAX_TOTAL_BONUS",
    "LTM_MAX_TOTAL_PENALTY",
    "plan",
]

MODE_BASE = "base"
MODE_LTM = "ltm"

#: Records below this confidence are ignored, never treated as facts.
LTM_MIN_CONFIDENCE = 0.35
#: A historical preference may lower a candidate cost by at most this much
#: (before confidence scaling).
LTM_PREFER_BONUS = -10.0
#: A historical avoidance may raise a candidate cost by this much (before
#: confidence scaling).
LTM_AVOID_PENALTY = 20.0
#: Bounds on the summed LTM adjustment, so history can never dominate freely.
LTM_MAX_TOTAL_BONUS = 30.0
LTM_MAX_TOTAL_PENALTY = 60.0


def _global_ignored_reason(
    record: MemoryRecord, as_of: datetime, scene: ParkingScene
) -> str | None:
    if record.scene_id is not None and record.scene_id != scene.scene_id:
        return "scene-mismatch"
    if record.target_id is not None and record.target_id != scene.target_id:
        return "target-mismatch"
    inactive = record.inactive_reason(as_of)
    if inactive is not None:
        return inactive
    if record.confidence < LTM_MIN_CONFIDENCE:
        return (
            f"confidence-below-threshold: {record.confidence:.2f} < "
            f"{LTM_MIN_CONFIDENCE:.2f}"
        )
    if record.effect == MemoryEffect.NEUTRAL:
        return "neutral-effect"
    return None


def _raw_adjustment(record: MemoryRecord) -> float:
    if record.effect == MemoryEffect.PREFER:
        return LTM_PREFER_BONUS * record.confidence
    if record.effect == MemoryEffect.AVOID:
        return LTM_AVOID_PENALTY * record.confidence
    return 0.0


def _cap_adjustment(value: float) -> float:
    if value < -LTM_MAX_TOTAL_BONUS:
        return -LTM_MAX_TOTAL_BONUS
    if value > LTM_MAX_TOTAL_PENALTY:
        return LTM_MAX_TOTAL_PENALTY
    return value


def _apply_memories(
    scene: ParkingScene,
    candidate: RouteCandidate,
    active_records: Iterable[MemoryRecord],
) -> tuple[tuple[MemoryApplication, ...], tuple[IgnoredMemory, ...], float]:
    applications: list[MemoryApplication] = []
    ignored: list[IgnoredMemory] = []
    raw_total = 0.0
    for record in active_records:
        mismatch = record.association_mismatch(
            scene_id=scene.scene_id,
            target_id=scene.target_id,
            route_key=candidate.route_key,
            node_ids=candidate.node_ids,
        )
        if mismatch is not None:
            ignored.append(IgnoredMemory(memory_id=record.memory_id, reason=mismatch))
            continue
        adjustment = _raw_adjustment(record)
        raw_total += adjustment
        applications.append(
            MemoryApplication(
                memory_id=record.memory_id,
                candidate_id=candidate.candidate_id,
                effect=record.effect,
                confidence=record.confidence,
                adjustment=adjustment,
                explanation=(
                    f"{record.kind}/{record.effect} at confidence "
                    f"{record.confidence:.2f} -> {adjustment:+.2f} cost units; "
                    f"statement={record.statement!r}"
                ),
            )
        )
    return tuple(applications), tuple(ignored), raw_total


def _choose(
    evaluations: Iterable[CandidateEvaluation], *, use_ltm_cost: bool
) -> str | None:
    feasible = [evaluation for evaluation in evaluations if evaluation.feasible]
    if not feasible:
        return None
    if use_ltm_cost:
        key = lambda evaluation: (
            evaluation.cost.total,  # type: ignore[union-attr]
            evaluation.candidate.route_key,
            evaluation.candidate_id,
        )
    else:
        key = lambda evaluation: (
            evaluation.cost.base_total,  # type: ignore[union-attr]
            evaluation.candidate.route_key,
            evaluation.candidate_id,
        )
    return min(feasible, key=key).candidate_id


def _find(
    evaluations: Iterable[CandidateEvaluation], candidate_id: str
) -> CandidateEvaluation:
    for evaluation in evaluations:
        if evaluation.candidate_id == candidate_id:
            return evaluation
    raise PlanningValidationError(f"unknown candidate id {candidate_id!r}")


def _dedupe_ignored(items: Iterable[IgnoredMemory]) -> tuple[IgnoredMemory, ...]:
    seen: set[tuple[str, str]] = set()
    result: list[IgnoredMemory] = []
    for item in items:
        key = (item.memory_id, item.reason)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result)


def plan(
    scene: ParkingScene,
    *,
    mode: str = MODE_BASE,
    ltm_store: LongTermMemoryStore | None = None,
    as_of: datetime | str | None = None,
    weights: CostWeights = DEFAULT_COST_WEIGHTS,
    max_candidates: int = 3,
    extra_hard_constraint: (
        Callable[[ParkingScene, RouteCandidate], tuple[ConstraintViolation, ...]]
        | None
    ) = None,
) -> PlanningResult:
    """Generate, check, cost and select routes in ``base`` or ``ltm`` mode.

    ``extra_hard_constraint`` is an optional caller-supplied checker (used by
    the NAV-17 navigation bridge). Its violations are combined with the scene
    constraints **before** any cost or LTM adjustment, so a caller cannot use
    it to bypass the normal hard constraints and LTM cannot override it.
    """

    if mode not in (MODE_BASE, MODE_LTM):
        raise PlanningValidationError(f"unknown planning mode {mode!r}")
    if ltm_store is not None and not isinstance(ltm_store, LongTermMemoryStore):
        raise PlanningValidationError("ltm_store must be a LongTermMemoryStore or None")
    if not isinstance(weights, CostWeights):
        raise PlanningValidationError("weights must be a CostWeights")
    if extra_hard_constraint is not None and not callable(extra_hard_constraint):
        raise PlanningValidationError("extra_hard_constraint must be callable or None")
    moment = (
        ensure_utc(as_of, "as_of")
        if as_of is not None
        else datetime.now(timezone.utc)
    )

    candidate_set: CandidateSet = generate_candidates(
        scene, max_candidates=max_candidates
    )
    records: tuple[MemoryRecord, ...] = (
        ltm_store.all() if mode == MODE_LTM and ltm_store is not None else ()
    )

    globally_ignored: list[IgnoredMemory] = []
    active_records: list[MemoryRecord] = []
    for record in records:
        reason = _global_ignored_reason(record, moment, scene)
        if reason is None:
            active_records.append(record)
        else:
            globally_ignored.append(
                IgnoredMemory(memory_id=record.memory_id, reason=reason)
            )

    ignored: list[IgnoredMemory] = list(globally_ignored)
    evaluations: list[CandidateEvaluation] = []
    for candidate in candidate_set.candidates:
        violations = list(check_hard_constraints(scene, candidate))
        if extra_hard_constraint is not None:
            extra = extra_hard_constraint(scene, candidate)
            if not isinstance(extra, tuple):
                raise PlanningValidationError(
                    "extra_hard_constraint must return a tuple of ConstraintViolation"
                )
            for violation in extra:
                if not isinstance(violation, ConstraintViolation):
                    raise PlanningValidationError(
                        "extra_hard_constraint returned a non-ConstraintViolation"
                    )
            violations.extend(extra)
        if violations:
            evaluations.append(
                CandidateEvaluation(
                    candidate=candidate, violations=violations, cost=None
                )
            )
            continue

        base_cost = compute_route_cost(scene.topology, candidate, weights)
        if mode == MODE_LTM:
            applications, candidate_ignored, raw_total = _apply_memories(
                scene, candidate, active_records
            )
            ignored.extend(candidate_ignored)
            cost = with_ltm_adjustment(base_cost, _cap_adjustment(raw_total))
            evaluations.append(
                CandidateEvaluation(
                    candidate=candidate,
                    violations=(),
                    cost=cost,
                    ltm_applications=applications,
                )
            )
        else:
            evaluations.append(
                CandidateEvaluation(
                    candidate=candidate, violations=(), cost=base_cost
                )
            )

    if mode == MODE_LTM:
        # Make the precedence of current evidence visible: a memory that would
        # otherwise match a candidate rejected by hard constraints is never
        # applied, even if its historical effect is a strong preference.
        infeasible_candidates = [
            evaluation.candidate
            for evaluation in evaluations
            if not evaluation.feasible
        ]
        for record in active_records:
            if any(
                record.association_mismatch(
                    scene_id=scene.scene_id,
                    target_id=scene.target_id,
                    route_key=candidate.route_key,
                    node_ids=candidate.node_ids,
                )
                is None
                for candidate in infeasible_candidates
            ):
                ignored.append(
                    IgnoredMemory(
                        memory_id=record.memory_id, reason="candidate-infeasible"
                    )
                )

    base_selected = _choose(evaluations, use_ltm_cost=False)
    ltm_selected = (
        _choose(evaluations, use_ltm_cost=True)
        if mode == MODE_LTM
        else base_selected
    )
    changed = mode == MODE_LTM and ltm_selected != base_selected
    feasible_count = sum(1 for evaluation in evaluations if evaluation.feasible)

    applied_memories: tuple[MemoryApplication, ...] = ()
    if mode == MODE_LTM:
        applied_memories = tuple(
            application
            for evaluation in evaluations
            for application in evaluation.ltm_applications
        )

    if base_selected is None:
        selection_reason = (
            "no feasible candidate after hard constraints; re-observation / "
            "re-planning is required and no violating route was selected"
        )
        no_solution_reason = (
            "no feasible candidate; current scene evidence must be re-observed"
        )
    elif mode == MODE_BASE:
        chosen = _find(evaluations, base_selected)
        selection_reason = (
            f"base mode: {base_selected} has the lowest base cost "
            f"{chosen.cost.base_total:.3f} among {feasible_count} feasible "
            f"candidate(s)"
        )  # type: ignore[union-attr]
        no_solution_reason = None
    else:
        chosen = _find(evaluations, ltm_selected)  # type: ignore[arg-type]
        base_chosen = _find(evaluations, base_selected)
        if changed:
            relevant_ids = sorted(
                {
                    application.memory_id
                    for application in chosen.ltm_applications
                }
                | {
                    application.memory_id
                    for application in base_chosen.ltm_applications
                }
            )
            selection_reason = (
                f"LTM changed selection from {base_selected} "
                f"(base total {base_chosen.cost.base_total:.3f}, LTM total "
                f"{base_chosen.cost.total:.3f}) to {ltm_selected} "
                f"(base total {chosen.cost.base_total:.3f}, LTM total "
                f"{chosen.cost.total:.3f}) using {relevant_ids}"
            )  # type: ignore[union-attr]
        elif not applied_memories:
            selection_reason = (
                f"LTM mode found no relevant active memory; degraded to base "
                f"selection {base_selected} (base total "
                f"{chosen.cost.base_total:.3f}) among {feasible_count} feasible "
                "candidate(s)"
            )  # type: ignore[union-attr]
        else:
            memory_ids = sorted({item.memory_id for item in applied_memories})
            selection_reason = (
                f"LTM mode did not change the selection: {ltm_selected} remains "
                f"lowest (base total {chosen.cost.base_total:.3f}, LTM total "
                f"{chosen.cost.total:.3f}) among {feasible_count} feasible "
                f"candidate(s); applied memories {memory_ids}"
            )  # type: ignore[union-attr]
        no_solution_reason = None

    selection = SelectionResult(
        scene_id=scene.scene_id,
        target_id=scene.target_id,
        mode=mode,
        evaluations=tuple(evaluations),
        selected_candidate_id=ltm_selected,
        base_selected_candidate_id=base_selected,
        ltm_changed_selection=changed,
        selection_reason=selection_reason,
        applied_memories=applied_memories,
        ignored_memories=_dedupe_ignored(ignored),
        scene_evidence=scene.evidence(),
        no_solution_reason=no_solution_reason,
    )
    return PlanningResult(
        scene_id=scene.scene_id,
        target_id=scene.target_id,
        mode=mode,
        candidate_set=candidate_set,
        selection=selection,
    )
