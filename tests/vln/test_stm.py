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


# -- CARLA visual-navigation rounds ----------------------------------------


def _carla_execution(*, moved_m: float = 10.0, success: bool = True) -> dict:
    return {
        "executed": True,
        "target_node_id": "a_mid",
        "moved_m": moved_m,
        "stop_reason": "success" if success else "timeout",
        "segment_success": success,
        "model_selected_edge": ["fork", "a_mid"],
        "route_node_ids": ["fork", "a_mid", "a_goal"],
        "kernel": {"response": {"execution_status": "completed"}},
        "post_state": {"x": 1.5, "y": 2.5, "yaw": -89.0, "speed": 0.0},
    }


def test_carla_round_records_decision_execution_and_next_context() -> None:
    memory = NavigationTaskMemory(task_id="carla-task", max_context_chars=4000)
    record = memory.record_carla_round(
        round_index=1,
        intent_id="carla-r1",
        action="NAVIGATE_TO",
        target={"x": 1.0, "y": 2.0},
        visual_decision=_decision(identified_as="blue car", direction="STRAIGHT", position="AHEAD"),
        directive=_directive(identified_as="blue car", direction="STRAIGHT", position="AHEAD"),
        outcome=RoundOutcome.SOFTWARE_SUCCEEDED,
        task_target="blue car",
        execution=_carla_execution(),
    )

    assert record.task_id == "carla-task"
    assert record.round_index == 1
    assert record.outcome == RoundOutcome.SOFTWARE_SUCCEEDED
    assert memory.next_round_index == 2
    assert memory.active_fact("task_target").value == "blue car"
    assert memory.active_fact("last_action_outcome").value == RoundOutcome.SOFTWARE_SUCCEEDED
    assert memory.active_fact("navigation_direction").value == "STRAIGHT"
    execution_fact = json.loads(memory.active_fact("last_execution").value)
    assert execution_fact["moved_m"] == 10.0
    assert execution_fact["target_node_id"] == "a_mid"

    context = memory.render_context()
    assert '"key":"task_target","value":"blue car"' in context
    assert '"round":1' in context
    assert '"key":"last_execution"' in context
    assert '"physical_arrival":"unknown"' in context
    assert "arrived" not in context.lower()


def test_carla_refusal_is_explicit_and_not_a_success() -> None:
    memory = NavigationTaskMemory(task_id="carla-task-refused")
    memory.record_carla_round(
        round_index=1,
        intent_id="carla-r1",
        action="NAVIGATE_TO",
        target={"x": 1.0, "y": 2.0},
        visual_decision=_decision(identified_as="red car", direction="LEFT", position="LEFT"),
        directive=_directive(identified_as="red car", direction="LEFT", position="LEFT"),
        outcome=RoundOutcome.REJECTED,
        task_target="red car",
        execution={
            "executed": False,
            "moved_m": 0.0,
            "stop_reason": "no_compatible_route",
            "segment_success": False,
            "post_state": {"x": 0.0, "y": 0.0, "yaw": 0.0, "speed": 0.0},
        },
        error="no_compatible_route: visual direction conflicts",
    )

    assert memory.active_fact("last_action_outcome").value == RoundOutcome.REJECTED
    assert memory.active_fact("last_execution").value.find("no_compatible_route") >= 0
    assert any("action outcome" in item.question for item in memory.unresolved)
    context = memory.render_context()
    assert "no_compatible_route" in context
    assert '"physical_arrival":"unknown"' in context


def test_carla_round_target_change_marks_previous_target_stale() -> None:
    memory = NavigationTaskMemory(task_id="carla-task-switch")
    memory.record_carla_round(
        round_index=1,
        intent_id="carla-r1",
        action="NAVIGATE_TO",
        target={"x": 1.0, "y": 2.0},
        visual_decision=_decision(identified_as="blue car"),
        directive=_directive(identified_as="blue car"),
        outcome=RoundOutcome.SOFTWARE_SUCCEEDED,
        task_target="blue car",
        execution=_carla_execution(),
    )
    memory.record_carla_round(
        round_index=2,
        intent_id="carla-r2",
        action="NAVIGATE_TO",
        target={"x": 3.0, "y": 4.0},
        visual_decision=_decision(identified_as="red car"),
        directive=_directive(identified_as="red car"),
        outcome=RoundOutcome.REJECTED,
        task_target="red car",
        execution=None,
        error="rejected",
    )

    stale = [fact for fact in memory.facts if fact.status == FactStatus.STALE]
    assert stale
    target_fact = memory.active_fact("task_target")
    assert target_fact.value == "red car"
    assert target_fact.previous_value == "blue car"
    assert target_fact.source_round == 2
    assert memory.next_round_index == 3


def test_carla_round_rejects_non_increasing_index_and_unknown_outcome() -> None:
    memory = NavigationTaskMemory(task_id="carla-task-order")
    memory.record_carla_round(
        round_index=2,
        intent_id="carla-r2",
        action="NAVIGATE_TO",
        target=None,
        visual_decision=None,
        directive=None,
        outcome=RoundOutcome.FAILED_BEFORE_EXECUTION,
        task_target="blue car",
        execution=None,
        error="model unavailable",
    )
    with pytest.raises(ValueError):
        memory.record_carla_round(
            round_index=2,
            intent_id="dup",
            action="NAVIGATE_TO",
            target=None,
            visual_decision=None,
            directive=None,
            outcome=RoundOutcome.REJECTED,
            task_target="blue car",
        )
    with pytest.raises(ValueError):
        memory.record_carla_round(
            round_index=3,
            intent_id="bad-outcome",
            action="NAVIGATE_TO",
            target=None,
            visual_decision=None,
            directive=None,
            outcome="success",
            task_target="blue car",
        )
    assert len(memory.records) == 1


def test_compact_context_keeps_recent_rounds_and_active_facts() -> None:
    memory = NavigationTaskMemory(
        task_id="carla-compact", max_entries=8, max_facts=32
    )
    for round_index in range(1, 6):
        memory.record_carla_round(
            round_index=round_index,
            intent_id=f"carla-r{round_index}",
            action="NAVIGATE_TO",
            target={"x": float(round_index), "y": 2.0},
            visual_decision=_decision(identified_as=f"target-{round_index}"),
            directive=_directive(identified_as=f"target-{round_index}"),
            outcome=RoundOutcome.SOFTWARE_SUCCEEDED,
            task_target=f"target-{round_index}",
            execution=_carla_execution(moved_m=float(round_index)),
        )
    context = memory.render_compact_context(max_chars=2400)
    assert len(context) <= 2400
    payload = json.loads(context)
    assert payload["task_id"] == "carla-compact"
    assert payload["physical_arrival"] == "unknown"
    assert payload["round"] == 6
    assert len(payload["rounds"]) <= 3
    assert payload["rounds"][-1]["round"] == 5
    assert "task_target" in payload["facts"]
    assert "last_execution" in payload["facts"]
    assert "previous_value" not in context
    assert "stale" not in context
    # Only the newest target survives as an active fact.
    assert payload["facts"]["task_target"] == "target-5"


def test_compact_context_remains_bounded() -> None:
    memory = NavigationTaskMemory(task_id="carla-compact-bound", max_context_chars=4000)
    memory.record_carla_round(
        round_index=1,
        intent_id="carla-r1",
        action="NAVIGATE_TO",
        target={"x": 1.0, "y": 2.0},
        visual_decision=_decision(identified_as="blue car"),
        directive=_directive(identified_as="blue car"),
        outcome=RoundOutcome.SOFTWARE_SUCCEEDED,
        task_target="blue car",
        execution=_carla_execution(),
    )
    compact = memory.render_compact_context(max_chars=128)
    assert len(compact) <= 128
    assert json.loads(compact)["truncated"] is True
    with pytest.raises(ValueError):
        memory.render_compact_context(max_chars=127)


def _binding(status: str, round_index: int, *, bay_id="bay03", slot="park_slot", label="B"):
    from vln.nav.target_binding import TargetBinding

    return TargetBinding(
        status=status,
        instruction="请将车辆停入左侧的空闲车位",
        round_index=round_index,
        bay_id=bay_id,
        slot_node_id=slot,
        selected_label=label,
        reason="round result",
    )


def test_target_binding_history_and_facts() -> None:
    memory = NavigationTaskMemory("cap07a-stm")

    first = memory.record_target_binding(_binding("bound", 0, label="B"))
    second = memory.record_target_binding(
        _binding("bound", 1, label="A")
    )

    assert first.bay_id == second.bay_id == "bay03"
    assert first.selected_label == "B"
    assert second.selected_label == "A"
    assert memory.target_binding is not None
    assert memory.target_binding.selected_label == "A"
    assert memory.target_binding.bay_id == "bay03"
    assert memory.bound_target is not None
    assert memory.bound_target.slot_node_id == "park_slot"
    assert len(memory.target_bindings) == 2
    assert memory.active_fact("target_binding_status").value == "bound"
    assert memory.active_fact("target_binding_bay").value == "bay03"
    assert memory.active_fact("target_binding_instruction").value == first.instruction

    context = json.loads(memory.render_context())
    assert context["target_binding"]["bay_id"] == "bay03"
    assert context["target_binding"]["round"] == 1

    compact = json.loads(memory.render_compact_context())
    assert compact["target_binding"]["status"] == "bound"
    assert compact["target_binding"]["bay_id"] == "bay03"


def test_target_binding_invalidation_is_memory_visible() -> None:
    memory = NavigationTaskMemory("cap07a-stm-invalid")
    memory.record_target_binding(_binding("bound", 0))
    memory.record_target_binding(_binding("invalidated", 2, label="B"))

    assert memory.target_binding.status == "invalidated"
    assert memory.bound_target is None
    assert memory.active_fact("target_binding_status").value == "invalidated"
    context = json.loads(memory.render_context())
    assert context["target_binding"]["status"] == "invalidated"
    assert context["target_binding"]["executable"] is False


def test_target_binding_requires_scene_identity_when_bound() -> None:
    memory = NavigationTaskMemory("cap07a-stm-invalid-record")
    bad = SimpleNamespace(
        status="bound",
        instruction="停入空位",
        round_index=0,
        bay_id=None,
        slot_node_id=None,
        selected_label="A",
        reason="",
    )
    with pytest.raises(ValueError):
        memory.record_target_binding(bad)
    assert memory.target_binding is None
