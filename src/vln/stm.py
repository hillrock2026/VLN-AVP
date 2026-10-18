"""Application-level short-term navigation memory (STM).

This module is deliberately small and in-memory only. It owns two things the
Agent-Kernel and the IPC protocol do not provide:

* a per-task round ledger: which intent/action/request/response belongs to
  which round of one continuous navigation task;
* a bounded set of navigation facts with an explicit epistemic status and
  conflict handling.

It never executes anything, never talks to a Host, and never invents a physical
arrival fact. ``parking.move`` is a simulation stub, so a successful software
response is recorded as ``software-succeeded`` only; ``stub_completed`` is not
translated into "arrived" or "parked".

The model-input path consumes :meth:`NavigationTaskMemory.render_context` and
appends it as a separate, clearly labelled history section. The real previous
``Response`` remains the existing feedback section and is never replaced by
this summary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Mapping, Optional

from vln.ipc.envelope import HostKind, ObservationStatus, Response, SubmissionStatus
from vln.nav.visual_decision import NavigationDirective, VisualNavigationDecision

if TYPE_CHECKING:  # pragma: no cover - typing only
    from vln.nav_execution import VisualParkingExecution

__all__ = [
    "FactStatus",
    "RoundOutcome",
    "MemoryFact",
    "UnresolvedQuestion",
    "NavigationRoundRecord",
    "NavigationTaskMemory",
    "classify_response",
    "MAX_TASK_ID_CHARS",
]


MAX_TASK_ID_CHARS = 128


class FactStatus:
    """Epistemic status of one remembered fact.

    The values are plain strings to stay consistent with the existing
    ``SubmissionStatus``/``LoopStopReason`` style in this project.
    """

    OBSERVED = "observed"
    CONFIRMED = "confirmed"
    HYPOTHESIZED = "hypothesized"
    STALE = "stale"

    ALL = frozenset({OBSERVED, CONFIRMED, HYPOTHESIZED, STALE})


class RoundOutcome:
    """Application-level outcome classification for one navigation round."""

    NOT_SUBMITTED = "not-submitted"
    REJECTED = "rejected"
    FAILED_BEFORE_EXECUTION = "failed-before-execution"
    EXECUTION_FAILED = "execution-failed"
    OBSERVATION_FAILED = "observation-failed"
    SOFTWARE_SUCCEEDED = "software-succeeded"
    UNCERTAIN = "uncertain"

    ALL = frozenset(
        {
            NOT_SUBMITTED,
            REJECTED,
            FAILED_BEFORE_EXECUTION,
            EXECUTION_FAILED,
            OBSERVATION_FAILED,
            SOFTWARE_SUCCEEDED,
            UNCERTAIN,
        }
    )


def classify_response(response: Optional[Response]) -> str:
    """Map one real IPC ``Response`` onto a ``RoundOutcome`` value.

    The mapping follows the current Host implementation, but it does not use
    ``Response.ok`` alone: ``ok`` ignores ``execution_status`` and
    ``host_kind``. It also never treats a software success as a physical
    arrival.
    """

    if response is None:
        return RoundOutcome.NOT_SUBMITTED
    if response.host_kind != HostKind.KERNEL:
        return RoundOutcome.UNCERTAIN
    if not response.accepted:
        return RoundOutcome.REJECTED
    if response.submission_status == SubmissionStatus.REJECTED:
        return RoundOutcome.REJECTED
    if response.submission_status == SubmissionStatus.FAILED:
        code = response.error.get("code") if response.error else None
        if code == "capability-not-found":
            return RoundOutcome.FAILED_BEFORE_EXECUTION
        if response.execution_status in {
            "failed",
            "cancelled",
            "unresolvable",
            "internal-error",
        }:
            return RoundOutcome.EXECUTION_FAILED
        return RoundOutcome.UNCERTAIN
    if response.submission_status == SubmissionStatus.COMPLETED:
        if response.observation_status == ObservationStatus.SUCCESS:
            if response.execution_status in (None, "completed"):
                return RoundOutcome.SOFTWARE_SUCCEEDED
            return RoundOutcome.UNCERTAIN
        return RoundOutcome.OBSERVATION_FAILED
    return RoundOutcome.UNCERTAIN


@dataclass
class MemoryFact:
    """One bounded navigation fact with its source and epistemic status."""

    key: str
    value: str
    status: str
    source_round: int
    evidence: str = ""
    previous_value: Optional[str] = None
    superseded_by_round: Optional[int] = None


@dataclass(frozen=True)
class UnresolvedQuestion:
    """A question the current navigation task has not answered yet."""

    question: str
    source_round: int
    evidence: str = ""


@dataclass(frozen=True)
class NavigationRoundRecord:
    """The ledger entry for one navigation round.

    ``response`` is the exact object returned by the execution chain (or
    ``None`` when the round never reached the Host). It is retained by
    reference so callers can still verify the original Response fields.
    """

    task_id: str
    round_index: int
    intent_id: Optional[str]
    action: Optional[str]
    target: Optional[Mapping[str, float]]
    visual_decision: Optional[VisualNavigationDecision]
    directive: Optional[NavigationDirective]
    request_id: Optional[str]
    response: Optional[Response]
    outcome: str
    error: Optional[str] = None
    stop_reason: Optional[str] = None


class NavigationTaskMemory:
    """A bounded, in-memory short-term memory for one navigation task.

    The object is caller-owned and passed explicitly to the visual loop. The
    same object is also installed on :class:`~vln.visual_loop.VisualLoopModelClient`
    so the next round's model input can read the context. There is no global
    singleton, database or persistence layer.
    """

    def __init__(
        self,
        task_id: str,
        *,
        max_entries: int = 8,
        max_facts: int = 16,
        max_unresolved: int = 8,
        max_context_chars: int = 1200,
    ) -> None:
        if not isinstance(task_id, str) or task_id.strip() == "":
            raise ValueError("task_id must be a non-blank str")
        if len(task_id) > MAX_TASK_ID_CHARS:
            raise ValueError(f"task_id exceeds {MAX_TASK_ID_CHARS} characters")
        if type(max_entries) is not int or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        if type(max_facts) is not int or max_facts < 1:
            raise ValueError("max_facts must be a positive integer")
        if type(max_unresolved) is not int or max_unresolved < 1:
            raise ValueError("max_unresolved must be a positive integer")
        if type(max_context_chars) is not int or max_context_chars < 128:
            raise ValueError("max_context_chars must be an integer >= 128")

        self.task_id = task_id
        self.max_entries = max_entries
        self.max_facts = max_facts
        self.max_unresolved = max_unresolved
        self.max_context_chars = max_context_chars
        self.stop_reason: Optional[str] = None
        self._records: list[NavigationRoundRecord] = []
        self._facts: list[MemoryFact] = []
        self._unresolved: list[UnresolvedQuestion] = []

    # -- read-only views -------------------------------------------------

    @property
    def records(self) -> tuple[NavigationRoundRecord, ...]:
        return tuple(self._records)

    @property
    def facts(self) -> tuple[MemoryFact, ...]:
        return tuple(self._facts)

    @property
    def unresolved(self) -> tuple[UnresolvedQuestion, ...]:
        return tuple(self._unresolved)

    @property
    def next_round_index(self) -> int:
        return self._records[-1].round_index + 1 if self._records else 0

    def active_fact(self, key: str) -> Optional[MemoryFact]:
        """Return the newest non-stale fact for ``key``, if any."""

        for fact in reversed(self._facts):
            if fact.key == key and fact.status != FactStatus.STALE:
                return fact
        return None

    # -- round ledger ----------------------------------------------------

    def record_execution(
        self,
        execution: "VisualParkingExecution",
        *,
        round_index: int,
    ) -> NavigationRoundRecord:
        """Record one completed NAV-10 execution returned by the real chain."""

        response = execution.response
        outcome = classify_response(response)
        intent = execution.intent
        decision = execution.decision
        directive = execution.directive
        target = intent.target.to_object()

        record = NavigationRoundRecord(
            task_id=self.task_id,
            round_index=round_index,
            intent_id=intent.intent_id,
            action=intent.action,
            target=target,
            visual_decision=decision,
            directive=directive,
            request_id=execution.request.request_id,
            response=response,
            outcome=outcome,
            error=self._response_error(response),
        )
        self._append_record(record)
        self._update_from_execution(
            round_index=round_index,
            decision=decision,
            directive=directive,
            intent=intent,
            target=target,
            outcome=outcome,
            error=record.error,
        )
        return record

    def record_unsubmitted(
        self,
        *,
        round_index: int,
        error: object,
    ) -> NavigationRoundRecord:
        """Record a round refused before any Host request was built."""

        message = str(error)
        record = NavigationRoundRecord(
            task_id=self.task_id,
            round_index=round_index,
            intent_id=None,
            action=None,
            target=None,
            visual_decision=None,
            directive=None,
            request_id=None,
            response=None,
            outcome=RoundOutcome.NOT_SUBMITTED,
            error=message,
        )
        self._append_record(record)
        self.remember_fact(
            "last_action_outcome",
            RoundOutcome.NOT_SUBMITTED,
            status=FactStatus.OBSERVED,
            source_round=round_index,
            evidence=message,
        )
        self.add_unresolved(
            f"round {round_index}: decision not submitted ({message})",
            round_index=round_index,
            evidence="validation/refusal",
        )
        return record

    def record_uncertain(
        self,
        *,
        round_index: int,
        request_id: Optional[str],
        response: Optional[Response],
        error: object,
    ) -> NavigationRoundRecord:
        """Record a round whose outcome cannot be confirmed from a Response."""

        message = str(error)
        record = NavigationRoundRecord(
            task_id=self.task_id,
            round_index=round_index,
            intent_id=None,
            action=None,
            target=None,
            visual_decision=None,
            directive=None,
            request_id=request_id,
            response=response,
            outcome=RoundOutcome.UNCERTAIN,
            error=message,
        )
        self._append_record(record)
        self.remember_fact(
            "last_action_outcome",
            RoundOutcome.UNCERTAIN,
            status=FactStatus.OBSERVED,
            source_round=round_index,
            evidence=message,
        )
        self.add_unresolved(
            f"round {round_index}: outcome uncertain ({message})",
            round_index=round_index,
            evidence="transport/contract",
        )
        return record

    def mark_stopped(self, reason: str) -> None:
        """Attach the loop's terminal stop reason to the task and last round."""

        if not isinstance(reason, str) or reason.strip() == "":
            raise ValueError("stop reason must be a non-blank str")
        self.stop_reason = reason
        if self._records:
            self._records[-1] = replace(self._records[-1], stop_reason=reason)

    # -- navigation facts ------------------------------------------------

    def remember_fact(
        self,
        key: str,
        value: str,
        *,
        status: str,
        source_round: int,
        evidence: str = "",
    ) -> MemoryFact:
        """Add or update one fact, marking a conflicting old value stale.

        A newer observation always wins. The old fact is retained with
        ``status="stale"`` and ``superseded_by_round`` set, so the conflict is
        visible instead of silently overwritten.
        """

        if not isinstance(key, str) or key.strip() == "":
            raise ValueError("fact key must be a non-blank str")
        if status not in FactStatus.ALL:
            raise ValueError(f"unknown fact status: {status!r}")
        if not isinstance(value, str):
            value = str(value)

        active = self.active_fact(key)
        if active is not None and active.value == value:
            # Do not downgrade a confirmed fact; a stronger new status may
            # upgrade it. The source round/evidence are those of the newest
            # observation.
            if status == FactStatus.CONFIRMED or active.status == FactStatus.HYPOTHESIZED:
                active.status = status
            active.source_round = source_round
            active.evidence = evidence
            return active

        previous_value: Optional[str] = None
        if active is not None:
            previous_value = active.value
            active.status = FactStatus.STALE
            active.superseded_by_round = source_round

        fact = MemoryFact(
            key=key,
            value=value,
            status=status,
            source_round=source_round,
            evidence=evidence,
            previous_value=previous_value,
        )
        self._facts.append(fact)
        self._trim_facts()
        return fact

    def observe_target(
        self, label: str, *, round_index: int, evidence: str = ""
    ) -> MemoryFact:
        """Record the target identity the model reported in this round."""

        return self.remember_fact(
            "target_identity",
            label,
            status=FactStatus.OBSERVED,
            source_round=round_index,
            evidence=evidence,
        )

    def observe_landmark(
        self, label: str, *, round_index: int, evidence: str = ""
    ) -> MemoryFact:
        """Record an actually reported landmark; never records absence."""

        return self.remember_fact(
            f"landmark:{label}",
            label,
            status=FactStatus.OBSERVED,
            source_round=round_index,
            evidence=evidence,
        )

    def set_subgoal(
        self, description: str, *, round_index: int, evidence: str = ""
    ) -> MemoryFact:
        """Record the current navigation subgoal as a hypothesis to verify."""

        return self.remember_fact(
            "subgoal",
            description,
            status=FactStatus.HYPOTHESIZED,
            source_round=round_index,
            evidence=evidence,
        )

    def add_unresolved(
        self, question: str, *, round_index: int, evidence: str = ""
    ) -> None:
        """Add one open question, deduplicated by its text."""

        if not isinstance(question, str) or question.strip() == "":
            raise ValueError("question must be a non-blank str")
        if any(item.question == question for item in self._unresolved):
            return
        self._unresolved.append(
            UnresolvedQuestion(
                question=question,
                source_round=round_index,
                evidence=evidence,
            )
        )
        if len(self._unresolved) > self.max_unresolved:
            del self._unresolved[: len(self._unresolved) - self.max_unresolved]

    # -- model-input rendering ------------------------------------------

    def render_context(self, *, max_chars: Optional[int] = None) -> str:
        """Render a bounded, deterministic history block for the model.

        The block is a summary only. It explicitly says that it is history, not
        current image evidence, and that physical arrival is unknown. The real
        previous ``Response`` remains in the separate feedback section.
        """

        limit = self.max_context_chars if max_chars is None else max_chars
        if type(limit) is not int or limit < 128:
            raise ValueError("max_chars must be an integer >= 128")

        payload: dict[str, Any] = {
            "task_id": self.task_id,
            "source": "history",
            "note": (
                "History only; not current image evidence. physical_arrival is "
                "unknown; stub_completed does not mean arrival."
            ),
            "physical_arrival": "unknown",
            "round": self.next_round_index,
            "stop_reason": self.stop_reason,
            "facts": [self._fact_payload(fact) for fact in self._facts[-self.max_facts :]],
            "rounds": [
                self._record_payload(record)
                for record in self._records[-self.max_entries :]
            ],
            "unresolved": [
                self._unresolved_payload(item)
                for item in self._unresolved[-self.max_unresolved :]
            ],
            "truncated": False,
        }
        text = self._dump(payload)
        if len(text) <= limit:
            return text

        payload["truncated"] = True
        while payload["rounds"] and len(text) > limit:
            payload["rounds"].pop(0)
            text = self._dump(payload)
        while payload["facts"] and len(text) > limit:
            payload["facts"].pop(0)
            text = self._dump(payload)
        while payload["unresolved"] and len(text) > limit:
            payload["unresolved"].pop(0)
            text = self._dump(payload)
        if len(text) > limit:
            text = self._dump({"truncated": True})
        return text

    # -- internals -------------------------------------------------------

    def _append_record(self, record: NavigationRoundRecord) -> None:
        if self._records and record.round_index <= self._records[-1].round_index:
            raise ValueError(
                "round_index must strictly increase within one task: "
                f"last={self._records[-1].round_index}, new={record.round_index}"
            )
        self._records.append(record)
        if len(self._records) > self.max_entries:
            del self._records[: len(self._records) - self.max_entries]

    def _trim_facts(self) -> None:
        while len(self._facts) > self.max_facts:
            stale_index = next(
                (index for index, fact in enumerate(self._facts) if fact.status == FactStatus.STALE),
                None,
            )
            del self._facts[0 if stale_index is None else stale_index]

    def _update_from_execution(
        self,
        *,
        round_index: int,
        decision: VisualNavigationDecision,
        directive: NavigationDirective,
        intent: Any,
        target: Mapping[str, float],
        outcome: str,
        error: Optional[str],
    ) -> None:
        self.observe_target(
            decision.identified_as,
            round_index=round_index,
            evidence=decision.evidence,
        )
        self.remember_fact(
            "navigation_direction",
            directive.direction,
            status=FactStatus.OBSERVED,
            source_round=round_index,
            evidence=decision.evidence,
        )
        self.set_subgoal(
            f"{directive.direction} toward {directive.identified_as}",
            round_index=round_index,
            evidence=decision.evidence,
        )

        action_value = (
            f"{intent.action} intent_id={intent.intent_id} "
            f"target={json.dumps(target, sort_keys=True, separators=(',', ':'))}"
        )
        self.remember_fact(
            "last_action",
            action_value,
            status=(
                FactStatus.CONFIRMED
                if outcome == RoundOutcome.SOFTWARE_SUCCEEDED
                else FactStatus.OBSERVED
            ),
            source_round=round_index,
            evidence=outcome,
        )
        self.remember_fact(
            "last_action_outcome",
            outcome,
            status=FactStatus.CONFIRMED,
            source_round=round_index,
            evidence=error or outcome,
        )
        if outcome != RoundOutcome.SOFTWARE_SUCCEEDED:
            self.add_unresolved(
                f"round {round_index}: action outcome {outcome}",
                round_index=round_index,
                evidence=error or outcome,
            )

    @staticmethod
    def _response_error(response: Response) -> Optional[str]:
        if not response.error:
            return None
        code = response.error.get("code")
        message = response.error.get("message")
        if code is None and message is None:
            return None
        return f"{code}: {message}"

    @staticmethod
    def _dump(value: Any) -> str:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _fact_payload(fact: MemoryFact) -> dict[str, Any]:
        return {
            "key": fact.key,
            "value": fact.value,
            "status": fact.status,
            "source_round": fact.source_round,
            "evidence": fact.evidence,
            "previous_value": fact.previous_value,
            "superseded_by_round": fact.superseded_by_round,
        }

    @staticmethod
    def _record_payload(record: NavigationRoundRecord) -> dict[str, Any]:
        visual = None
        if record.visual_decision is not None:
            visual = {
                "target": record.visual_decision.target_field,
                "identified_as": record.visual_decision.identified_as,
                "visible": record.visual_decision.visible,
                "position": record.visual_decision.position,
                "direction": record.visual_decision.direction,
                "evidence": record.visual_decision.evidence,
            }
        directive = None
        if record.directive is not None:
            directive = {
                "direction": record.directive.direction,
                "position": record.directive.position,
                "identified_as": record.directive.identified_as,
            }
        return {
            "round": record.round_index,
            "intent_id": record.intent_id,
            "action": record.action,
            "target": record.target,
            "request_id": record.request_id,
            "outcome": record.outcome,
            "error": record.error,
            "stop_reason": record.stop_reason,
            "visual": visual,
            "verified": directive,
        }

    @staticmethod
    def _unresolved_payload(item: UnresolvedQuestion) -> dict[str, Any]:
        return {
            "question": item.question,
            "source_round": item.source_round,
            "evidence": item.evidence,
        }
