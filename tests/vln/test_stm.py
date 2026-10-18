"""Deterministic offline tests for the application-level STM.

No model, network, Host process or Kernel call is involved. The tests cover the
memory semantics themselves: round/task correlation, conflict handling, failed
and uncertain outcomes, the stub boundary, and bounded context rendering.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from vln.intent import AgentIntent, Target
from vln.ipc.envelope import (
    ErrorCode,
    HostKind,
    ObservationStatus,
    Request,
    Response,
    SubmissionStatus,
)
from vln.nav import NavigationDirective, VisualNavigationDecision
from vln.stm import (
    FactStatus,
    NavigationTaskMemory,
    RoundOutcome,
    classify_response,
)

_TARGET = Target(x=12.5, y=-4.0, heading=0.5)


def _decision(
    *,
    identified_as: str = "D50",
    direction: str = "LEFT",
    position: str = "LEFT",
    evidence: str = "地面白色编号 D50",
) -> VisualNavigationDecision:
    return VisualNavigationDecision(
        target_field=identified_as,
        identified_as=identified_as,
        visible="是",
        position=position,
        direction=direction,
        evidence=evidence,
    )


def _directive(
    *,
    identified_as: str = "D50",
    direction: str = "LEFT",
    position: str = "LEFT",
    evidence: str = "地面白色编号 D50",
) -> NavigationDirective:
    return NavigationDirective(
        direction=direction,
        position=position,
        identified_as=identified_as,
        evidence=evidence,
    )


def _intent(intent_id: str = "intent-0", target: Target = _TARGET) -> AgentIntent:
    return AgentIntent(intent_id=intent_id, target=target)


def _request(intent: AgentIntent, request_id: str) -> Request:
    return Request(
        request_id=request_id,
        capability_id=intent.action,
        payload=intent.to_payload(),
    )


def _response(
    request_id: str,
    *,
    accepted: bool = True,
    submission_status=SubmissionStatus.COMPLETED,
    observation_status=ObservationStatus.SUCCESS,
    execution_status="completed",
    output: str | None = '{"status":"stub_completed","execution_mode":"simulation"}',
    error=None,
    host_kind: str = HostKind.KERNEL,
) -> Response:
    return Response(
        request_id=request_id,
        host_kind=host_kind,
        accepted=accepted,
        submission_status=submission_status,
        observation_status=observation_status,
        execution_status=execution_status,
        output=output,
        error=error,
    )


def _execution(
    *,
    round_index: int = 0,
    intent_id: str = "intent-0",
    request_id: str = "req-0",
    identified_as: str = "D50",
    response: Response | None = None,
):
    intent = _intent(intent_id)
    request = _request(intent, request_id)
    if response is None:
        response = _response(request_id)
    return SimpleNamespace(
        intent=intent,
        decision=_decision(identified_as=identified_as),
        directive=_directive(identified_as=identified_as),
        request=request,
        response=response,
        round_index=round_index,
    )


def test_round_ledger_links_task_intent_request_and_response() -> None:
    memory = NavigationTaskMemory(task_id="task-1")
    execution = _execution(round_index=0, request_id="req-0")

    record = memory.record_execution(execution, round_index=0)

    assert record.task_id == "task-1"
    assert record.round_index == 0
    assert record.intent_id == "intent-0"
    assert record.action == "parking.move"
    assert record.target == _TARGET.to_object()
    assert record.request_id == "req-0"
    assert record.response is execution.response
    assert record.outcome == RoundOutcome.SOFTWARE_SUCCEEDED
    assert memory.records == (record,)
    assert memory.next_round_index == 1

    assert memory.active_fact("target_identity").value == "D50"
    assert memory.active_fact("target_identity").status == FactStatus.OBSERVED
    assert memory.active_fact("navigation_direction").value == "LEFT"
    assert memory.active_fact("subgoal").status == FactStatus.HYPOTHESIZED
    assert memory.active_fact("last_action").status == FactStatus.CONFIRMED
    assert (
        memory.active_fact("last_action_outcome").value
        == RoundOutcome.SOFTWARE_SUCCEEDED
    )


def test_new_observation_wins_and_old_fact_becomes_stale() -> None:
    memory = NavigationTaskMemory(task_id="task-conflict")
    memory.observe_target("D50", round_index=0, evidence="frame-0")
    memory.observe_target("D65", round_index=1, evidence="frame-1")

    old, new = memory.facts
    assert old.value == "D50"
    assert old.status == FactStatus.STALE
    assert old.superseded_by_round == 1
    assert new.value == "D65"
    assert new.status == FactStatus.OBSERVED
    assert new.previous_value == "D50"
    assert memory.active_fact("target_identity").value == "D65"

    context = json.loads(memory.render_context())
    target_facts = [
        fact for fact in context["facts"] if fact["key"] == "target_identity"
    ]
    assert [fact["value"] for fact in target_facts] == ["D50", "D65"]
    assert [fact["status"] for fact in target_facts] == ["stale", "observed"]


def test_unmentioned_landmark_is_not_inferred_absent() -> None:
    memory = NavigationTaskMemory(task_id="task-absence")
    memory.observe_target("D50", round_index=0, evidence="frame-0")

    assert memory.active_fact("landmark:D65") is None
    assert all(fact.key != "landmark:D65" for fact in memory.facts)
    assert "D65" not in memory.render_context()

    # An actually reported landmark is remembered; only silence is not treated
    # as evidence of absence.
    memory.observe_landmark("D65", round_index=1, evidence="frame-1")
    assert memory.active_fact("landmark:D65").value == "D65"
    assert "D65" in memory.render_context()


@pytest.mark.parametrize(
    "response, expected",
    [
        (
            _response(
                "req-rejected",
                accepted=False,
                submission_status=SubmissionStatus.REJECTED,
                observation_status=ObservationStatus.FAILURE,
                execution_status=None,
                output=None,
                error={"code": ErrorCode.CAPABILITY_NOT_FOUND, "message": "no"},
            ),
            RoundOutcome.REJECTED,
        ),
        (
            _response(
                "req-pre-exec",
                accepted=True,
                submission_status=SubmissionStatus.FAILED,
                observation_status=ObservationStatus.FAILURE,
                execution_status=None,
                output=None,
                error={"code": ErrorCode.CAPABILITY_NOT_FOUND, "message": "no"},
            ),
            RoundOutcome.FAILED_BEFORE_EXECUTION,
        ),
        (
            _response(
                "req-exec-failed",
                submission_status=SubmissionStatus.FAILED,
                observation_status=ObservationStatus.FAILURE,
                execution_status="failed",
                output=None,
                error={
                    "code": ErrorCode.CAPABILITY_INVOCATION_FAILED,
                    "message": "failed",
                },
            ),
            RoundOutcome.EXECUTION_FAILED,
        ),
        (
            _response(
                "req-obs-failed",
                submission_status=SubmissionStatus.COMPLETED,
                observation_status=ObservationStatus.FAILURE,
                execution_status="completed",
                output=None,
                error={
                    "code": ErrorCode.CAPABILITY_INVOCATION_FAILED,
                    "message": "unobservable",
                },
            ),
            RoundOutcome.OBSERVATION_FAILED,
        ),
        (
            _response("req-stub", host_kind=HostKind.STUB),
            RoundOutcome.UNCERTAIN,
        ),
    ],
)
def test_response_outcomes_are_not_flattened(response: Response, expected: str) -> None:
    assert classify_response(response) == expected


def test_failed_execution_is_recorded_without_success_or_arrival() -> None:
    failed = _response(
        "req-1",
        accepted=True,
        submission_status=SubmissionStatus.FAILED,
        observation_status=ObservationStatus.FAILURE,
        execution_status="failed",
        output=None,
        error={
            "code": ErrorCode.CAPABILITY_INVOCATION_FAILED,
            "message": "stub failed",
        },
    )
    memory = NavigationTaskMemory(task_id="task-failure")
    record = memory.record_execution(
        _execution(request_id="req-1", response=failed),
        round_index=0,
    )

    assert record.outcome == RoundOutcome.EXECUTION_FAILED
    assert memory.active_fact("last_action").status != FactStatus.CONFIRMED
    assert memory.active_fact("last_action_outcome").value == RoundOutcome.EXECUTION_FAILED
    assert memory.active_fact("arrived") is None
    assert memory.active_fact("parked") is None
    assert memory.unresolved


def test_stub_completed_never_creates_an_arrival_fact() -> None:
    memory = NavigationTaskMemory(task_id="task-stub")
    memory.record_execution(_execution(), round_index=0)

    keys = {fact.key for fact in memory.facts}
    assert "arrived" not in keys
    assert "parked" not in keys
    assert "physical_arrival" not in keys
    assert memory.active_fact("last_action_outcome").value == RoundOutcome.SOFTWARE_SUCCEEDED

    context = json.loads(memory.render_context())
    assert context["physical_arrival"] == "unknown"
    assert "stub_completed does not mean arrival" in context["note"]


def test_unsubmitted_and_uncertain_rounds_are_not_success() -> None:
    memory = NavigationTaskMemory(task_id="task-uncertain")
    unsubmitted = memory.record_unsubmitted(
        round_index=0, error=ValueError("missing Visual field")
    )
    uncertain = memory.record_uncertain(
        round_index=1,
        request_id="req-1",
        response=_response(
            "req-1",
            accepted=True,
            submission_status=SubmissionStatus.FAILED,
            observation_status=ObservationStatus.FAILURE,
            execution_status=None,
            output=None,
            error={"code": ErrorCode.INTERNAL_ERROR, "message": "host terminated"},
        ),
        error="HostTerminatedError: host terminated before responding",
    )

    assert unsubmitted.outcome == RoundOutcome.NOT_SUBMITTED
    assert unsubmitted.request_id is None
    assert unsubmitted.response is None
    assert uncertain.outcome == RoundOutcome.UNCERTAIN
    assert uncertain.request_id == "req-1"
    assert uncertain.response is not None
    assert memory.active_fact("last_action_outcome").value == RoundOutcome.UNCERTAIN
    assert memory.active_fact("last_action") is None

    memory.mark_stopped("exception")
    assert memory.stop_reason == "exception"
    assert memory.records[-1].stop_reason == "exception"


def test_memory_and_rendered_context_are_bounded() -> None:
    memory = NavigationTaskMemory(
        task_id="task-bounds",
        max_entries=2,
        max_facts=3,
        max_unresolved=2,
        max_context_chars=300,
    )
    for round_index in range(5):
        memory.record_execution(
            _execution(
                round_index=round_index,
                intent_id=f"intent-{round_index}",
                request_id=f"req-{round_index}",
                identified_as=f"D{round_index}",
            ),
            round_index=round_index,
        )
        memory.add_unresolved(
            f"question {round_index}", round_index=round_index, evidence="x" * 200
        )

    assert len(memory.records) == 2
    assert [record.round_index for record in memory.records] == [3, 4]
    assert len(memory.facts) <= 3
    assert len(memory.unresolved) <= 2

    context = memory.render_context()
    assert len(context) <= 300
    parsed = json.loads(context)
    assert parsed["truncated"] is True

    minimal = memory.render_context(max_chars=128)
    assert len(minimal) <= 128
    assert json.loads(minimal)["truncated"] is True

    with pytest.raises(ValueError):
        memory.render_context(max_chars=127)
