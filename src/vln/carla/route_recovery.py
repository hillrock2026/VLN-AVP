"""Bounded cross-round route recovery policy.

This module is deliberately a **policy value object**, not an executor. It
decides whether a real blocked stop may be followed by a new observation and a
new route decision. It never moves a vehicle, never talks to the Kernel and
never weakens any verifier or arbitration rule.

Two real trigger families are accepted:

* a pre-execution safety refusal that did not move the vehicle
  (``stop_reason=safety_precheck``), the DEMO-03 case; and
* a real blocked stop after motion (``obstacle`` or ``clearance_margin``), or a
  static-clearance refusal at the very start of a segment, with the vehicle
  confirmed stopped.  The caller must pass the graph node nearest the *real
  post-stop pose* for these cases; the failed segment's start node is not
  necessarily where the vehicle now is.

The caller must still capture a new frame, run the normal model/verify/
arbitration/execution_route chain and reach the goal through the existing
Kernel path. Recovery is only eligible when the vehicle is stopped, the
recovery node is identified, and more than one goal-reachable edge exists at
that node.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "RecoveryStatus",
    "RecoveryDecision",
    "RECOVERABLE_PRE_MOTION_REASONS",
    "RECOVERABLE_BLOCKED_STOP_REASONS",
    "evaluate_recovery_trigger",
]

RECOVERABLE_PRE_MOTION_REASONS = frozenset(
    {"safety_precheck", "clearance_preecheck"}
)
RECOVERABLE_BLOCKED_STOP_REASONS = frozenset({"obstacle", "clearance_margin"})


class RecoveryStatus:
    NOT_APPLICABLE = "not_applicable"
    ELIGIBLE = "eligible"
    REFUSED = "refused"
    ALL = frozenset({NOT_APPLICABLE, ELIGIBLE, REFUSED})


@dataclass(frozen=True)
class RecoveryDecision:
    status: str
    reason: str
    attempt: int
    max_attempts: int
    matched_node_id: str | None = None
    forward_candidates: int = 0
    blocked_candidates: int = 0
    eligible_candidates: int = 0
    blocking_evidence: str = "unknown"
    trigger: str | None = None

    def __post_init__(self) -> None:
        if self.status not in RecoveryStatus.ALL:
            raise ValueError(f"unknown recovery status {self.status!r}")
        if self.attempt < 0 or self.max_attempts < 0:
            raise ValueError("recovery attempt counts must be non-negative")
        if self.attempt > self.max_attempts:
            raise ValueError("attempt cannot exceed max_attempts")
        for name in (
            "forward_candidates",
            "blocked_candidates",
            "eligible_candidates",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative int")
        if self.eligible_candidates > self.forward_candidates:
            raise ValueError("eligible candidates cannot exceed forward candidates")
        if self.blocked_candidates > self.forward_candidates:
            raise ValueError("blocked candidates cannot exceed forward candidates")

    @property
    def allowed(self) -> bool:
        return self.status == RecoveryStatus.ELIGIBLE

    def to_metadata(self) -> dict:
        return {
            "status": self.status,
            "allowed": self.allowed,
            "reason": self.reason,
            "trigger": self.trigger,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "matched_node_id": self.matched_node_id,
            "forward_candidates": self.forward_candidates,
            "blocked_candidates": self.blocked_candidates,
            "eligible_candidates": self.eligible_candidates,
            "blocking_evidence": self.blocking_evidence,
        }


def evaluate_recovery_trigger(
    *,
    enabled: bool,
    attempts: int,
    max_attempts: int,
    executed: object,
    stopped: object = None,
    stop_reason: object,
    matched_node_id: object,
    goal_reached: bool,
    forward_candidates: int,
    blocked_candidates: int,
    eligible_candidates: int,
    blocking_evidence: str = "fresh",
) -> RecoveryDecision:
    """Return whether one new observation may follow a real blocked stop.

    ``eligible_candidates`` counts forward, goal-reachable outgoing edges that
    are not the edge that just failed and are **not confirmed blocked** by the
    caller's fresh clearance evidence. An edge that is merely absent from the
    blocked set is not proof of safety; the next arbitration and precheck stay
    the only authorities on whether it can be driven.
    """

    if type(enabled) is not bool:
        raise ValueError("enabled must be a bool")
    if type(attempts) is not int or attempts < 0:
        raise ValueError("attempts must be a non-negative int")
    if type(max_attempts) is not int or max_attempts < 0:
        raise ValueError("max_attempts must be a non-negative int")
    if type(goal_reached) is not bool:
        raise ValueError("goal_reached must be a bool")
    for name, value in (
        ("forward_candidates", forward_candidates),
        ("blocked_candidates", blocked_candidates),
        ("eligible_candidates", eligible_candidates),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a non-negative int")
    if eligible_candidates > forward_candidates:
        raise ValueError("eligible candidates cannot exceed forward candidates")
    if blocked_candidates > forward_candidates:
        raise ValueError("blocked candidates cannot exceed forward candidates")
    if type(blocking_evidence) is not str or blocking_evidence not in (
        "fresh",
        "unavailable",
        "unknown",
    ):
        raise ValueError("blocking_evidence must be fresh, unavailable or unknown")
    if attempts > max_attempts:
        raise ValueError("attempts cannot exceed max_attempts")
    node = matched_node_id if type(matched_node_id) is str else None

    base = {
        "attempt": attempts,
        "max_attempts": max_attempts,
        "matched_node_id": node,
        "forward_candidates": forward_candidates,
        "blocked_candidates": blocked_candidates,
        "eligible_candidates": eligible_candidates,
        "blocking_evidence": blocking_evidence,
    }
    if not enabled:
        return RecoveryDecision(
            RecoveryStatus.NOT_APPLICABLE,
            "recovery is disabled for this run",
            **base,
        )
    if goal_reached:
        return RecoveryDecision(
            RecoveryStatus.REFUSED,
            "the real goal evaluation already succeeded",
            **base,
        )

    if executed is False:
        if stop_reason not in RECOVERABLE_PRE_MOTION_REASONS:
            return RecoveryDecision(
                RecoveryStatus.REFUSED,
                f"stop_reason {stop_reason!r} is not a recoverable "
                "pre-execution refusal",
                **base,
            )
        trigger = "pre_execution_refusal"
    else:
        if stopped is not True:
            return RecoveryDecision(
                RecoveryStatus.REFUSED,
                "the segment did not confirm a stopped vehicle after execution",
                **base,
            )
        if stop_reason in RECOVERABLE_PRE_MOTION_REASONS:
            # A Kernel-invoked segment can refuse at its own initial gate
            # without motion; the vehicle is still stationary.
            trigger = "pre_execution_refusal"
        elif stop_reason in RECOVERABLE_BLOCKED_STOP_REASONS:
            trigger = "post_motion_blocked_stop"
        else:
            return RecoveryDecision(
                RecoveryStatus.REFUSED,
                f"stop_reason {stop_reason!r} is not a recoverable blocked stop",
                **base,
            )

    if node is None:
        return RecoveryDecision(
            RecoveryStatus.REFUSED,
            "the failed arbitration has no matched graph node",
            **base,
        )
    if attempts >= max_attempts:
        return RecoveryDecision(
            RecoveryStatus.REFUSED,
            "the recovery attempt budget is exhausted",
            **base,
        )
    if forward_candidates <= 0:
        return RecoveryDecision(
            RecoveryStatus.REFUSED,
            "the current node has no forward goal-reachable edge",
            **base,
        )
    if eligible_candidates < 1:
        if blocked_candidates >= forward_candidates:
            reason = (
                "every forward candidate is confirmed blocked by a real "
                "obstruction"
            )
        elif forward_candidates <= 1:
            reason = (
                "the current node has no alternative: the only forward "
                "candidate is the edge that just failed"
            )
        else:
            reason = "no forward candidate is free of confirmed blocking"
        return RecoveryDecision(RecoveryStatus.REFUSED, reason, **base)
    return RecoveryDecision(
        RecoveryStatus.ELIGIBLE,
        (
            "a real blocked stop left the vehicle stationary; at least one "
            "forward goal-reachable edge is not the failed edge and is not "
            "confirmed blocked, so a new observation may choose it"
        ),
        attempt=attempts + 1,
        max_attempts=max_attempts,
        matched_node_id=node,
        forward_candidates=forward_candidates,
        blocked_candidates=blocked_candidates,
        eligible_candidates=eligible_candidates,
        blocking_evidence=blocking_evidence,
        trigger=trigger,
    )
