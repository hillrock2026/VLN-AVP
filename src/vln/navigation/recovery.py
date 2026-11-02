"""Minimal navigation-recovery skill.

This module is the narrow, stable entry point a task-level caller uses after a
real blocked stop. It does **not** plan routes, drive the vehicle or weaken any
safety gate: it consumes the candidates and fresh clearance evidence produced
by the existing pipeline, asks the existing recovery policy whether one new
observation may be taken, and returns a skill-level status.

Execution boundary (unchanged):
    skill -> existing route arbitration -> safety precheck -> Agent-Kernel
          -> CARLA state feedback

The skill never treats "not observed blocked" as "proven safe"; only the next
arbitration and precheck decide what may be driven.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vln.carla.route_recovery import (
    RecoveryDecision,
    RecoveryStatus,
    evaluate_recovery_trigger,
)

__all__ = [
    "NAVIGATION_RECOVERY_SKILL",
    "RecoverySkillStatus",
    "RecoverySkillInput",
    "RecoverySkillResult",
    "evaluate_navigation_recovery",
]

NAVIGATION_RECOVERY_SKILL = "vln.navigation.recovery"


class RecoverySkillStatus:
    """Skill-level outcomes; only RECOVER/NEED_OBSERVATION allow a new round."""

    RECOVER = "recover"
    NEED_OBSERVATION = "need_observation"
    SAFE_STOP = "safe_stop"
    FAILED = "failed"
    ALL = frozenset({RECOVER, NEED_OBSERVATION, SAFE_STOP, FAILED})


@dataclass(frozen=True)
class RecoverySkillInput:
    """Everything the skill may use; all of it comes from the real pipeline."""

    goal_node_id: str
    observation_frame_id: int | None
    observation_image_sha256: str | None
    stop_reason: str
    executed: object
    stopped: object
    goal_reached: bool
    matched_node_id: object
    candidates: object
    failed_edge: object
    blocking_evidence: str
    attempts: int
    max_attempts: int
    recovery_enabled: bool = True


@dataclass(frozen=True)
class RecoverySkillResult:
    status: str
    reason: str
    forward_candidates: int
    blocked_candidates: int
    eligible_candidates: int
    blocking_evidence: str
    attempts: int
    max_attempts: int
    matched_node_id: str | None
    decision: RecoveryDecision | None = field(
        default=None, repr=False, compare=False
    )
    skill: str = NAVIGATION_RECOVERY_SKILL

    def __post_init__(self) -> None:
        if self.status not in RecoverySkillStatus.ALL:
            raise ValueError(f"unknown recovery skill status {self.status!r}")

    @property
    def new_observation_allowed(self) -> bool:
        """True when the caller may take one new observation and re-decide."""

        return self.status in (
            RecoverySkillStatus.RECOVER,
            RecoverySkillStatus.NEED_OBSERVATION,
        )

    def to_metadata(self) -> dict:
        return {
            "skill": self.skill,
            "status": self.status,
            "new_observation_allowed": self.new_observation_allowed,
            "reason": self.reason,
            "forward_candidates": self.forward_candidates,
            "blocked_candidates": self.blocked_candidates,
            "eligible_candidates": self.eligible_candidates,
            "blocking_evidence": self.blocking_evidence,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "matched_node_id": self.matched_node_id,
            "policy": None if self.decision is None else self.decision.to_metadata(),
        }


def _failed(
    payload: RecoverySkillInput, reason: str
) -> RecoverySkillResult:
    decision = RecoveryDecision(
        RecoveryStatus.REFUSED,
        f"recovery skill failed: {reason}",
        attempt=int(payload.attempts)
        if type(payload.attempts) is int and 0 <= payload.attempts
        else 0,
        max_attempts=int(payload.max_attempts)
        if type(payload.max_attempts) is int and payload.max_attempts >= 0
        else 0,
    )
    return RecoverySkillResult(
        status=RecoverySkillStatus.FAILED,
        reason=reason,
        forward_candidates=0,
        blocked_candidates=0,
        eligible_candidates=0,
        blocking_evidence=payload.blocking_evidence
        if isinstance(payload.blocking_evidence, str)
        else "unknown",
        attempts=decision.attempt,
        max_attempts=decision.max_attempts,
        matched_node_id=None,
        decision=decision,
    )


def evaluate_navigation_recovery(
    payload: RecoverySkillInput,
) -> RecoverySkillResult:
    """Evaluate whether one new observation may follow the real blocked stop.

    Counts forward, goal-reachable candidates (already produced by the existing
    arbitration code), how many are confirmed blocked by the caller's fresh
    clearance evidence, and how many remain eligible (not the failed edge and
    not confirmed blocked). It then delegates the decision to the existing
    :func:`vln.carla.route_recovery.evaluate_recovery_trigger` policy.
    """

    if not isinstance(payload, RecoverySkillInput):
        raise TypeError("payload must be a RecoverySkillInput")

    try:
        candidates = tuple(payload.candidates or ())
        failed_edge = None
        if payload.failed_edge is not None:
            failed_edge = tuple(payload.failed_edge)
            if len(failed_edge) != 2 or not all(
                isinstance(item, str) for item in failed_edge
            ):
                raise ValueError("failed_edge must be a (from, to) pair")

        def edge(candidate) -> tuple[str, str]:
            return (candidate.from_node_id, candidate.to_node_id)

        forward = [candidate for candidate in candidates if candidate.reachable]
        # Blocked flags are only evidence when the caller's clearance check ran
        # at this stop; otherwise no candidate is "confirmed blocked".
        blocked = (
            [candidate for candidate in forward if candidate.blocked]
            if payload.blocking_evidence == "fresh"
            else []
        )
        if payload.blocking_evidence == "fresh":
            eligible = [
                candidate
                for candidate in forward
                if not candidate.blocked and edge(candidate) != failed_edge
            ]
        else:
            # Unknown evidence: the caller's policy is to re-observe and let
            # arbitration/precheck decide. The skill reports that a refresh is
            # required instead of claiming safety.
            eligible = [
                candidate
                for candidate in forward
                if edge(candidate) != failed_edge
            ]

        decision = evaluate_recovery_trigger(
            enabled=payload.recovery_enabled,
            attempts=payload.attempts,
            max_attempts=payload.max_attempts,
            executed=payload.executed,
            stopped=payload.stopped,
            stop_reason=payload.stop_reason,
            matched_node_id=payload.matched_node_id,
            goal_reached=payload.goal_reached,
            forward_candidates=len(forward),
            blocked_candidates=len(blocked),
            eligible_candidates=len(eligible),
            blocking_evidence=payload.blocking_evidence,
        )
    except Exception as exc:  # never turn a skill bug into a silent recovery
        return _failed(payload, f"{type(exc).__name__}: {exc}")

    if decision.allowed:
        status = (
            RecoverySkillStatus.RECOVER
            if payload.blocking_evidence == "fresh"
            else RecoverySkillStatus.NEED_OBSERVATION
        )
    else:
        status = RecoverySkillStatus.SAFE_STOP
    return RecoverySkillResult(
        status=status,
        reason=decision.reason,
        forward_candidates=len(forward),
        blocked_candidates=len(blocked),
        eligible_candidates=len(eligible),
        blocking_evidence=payload.blocking_evidence,
        attempts=decision.attempt,
        max_attempts=decision.max_attempts,
        matched_node_id=decision.matched_node_id,
        decision=decision,
    )
