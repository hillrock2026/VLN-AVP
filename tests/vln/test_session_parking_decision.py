"""Strict Session-centric parking decisions (goal + verification)."""

from __future__ import annotations

import pytest

from vln.parking.session_decision import (
    AUTONOMOUS_VALET_PARKING,
    GoalUnderstandingAction,
    GoalUnderstandingParseError,
    SessionDecisionAction,
    SessionDecisionParseError,
    build_goal_understanding_prompt,
    build_session_decision_prompt,
    evaluate_goal_understanding,
    evaluate_session_decision,
    parse_goal_understanding,
    parse_session_decision,
)


def _goal_block(
    *,
    task: str = AUTONOMOUS_VALET_PARKING,
    target: str = "bay03",
    clear: str = "是",
    decision: str = "START_SESSION",
    evidence: str = "binding and current image support the target",
) -> str:
    return (
        f"Task: {task}\n"
        f"Target: {target}\n"
        f"Target identity clear: {clear}\n"
        f"Decision: {decision}\n"
        f"Evidence: {evidence}\n"
    )


def _verification_block(
    decision: str = "CONTINUE_CURRENT_STAGE",
    *,
    occupancy: str = "空闲",
    boundary: str = "清晰",
    occlusion: str = "无",
    evidence: str = "充分",
    selected: str = "A",
) -> str:
    return (
        f"Decision: {decision}\n"
        f"A: {occupancy}\n"
        f"边界: {boundary}\n"
        f"遮挡: {occlusion}\n"
        f"证据: {evidence}\n"
        f"Selected: {selected}\n"
    )


def test_goal_understanding_accepts_bound_target() -> None:
    parsed = parse_goal_understanding(_goal_block())
    result = evaluate_goal_understanding(
        parsed, expected_bay="bay03", expected_slot="park_slot"
    )
    assert result["valid"] is True
    assert result["start_session"] is True
    assert result["reasons"] == []


def test_goal_understanding_refuses_unclear_or_wrong_target() -> None:
    unclear = parse_goal_understanding(_goal_block(clear="否"))
    result = evaluate_goal_understanding(
        unclear, expected_bay="bay03", expected_slot="park_slot"
    )
    assert result["valid"] is False
    assert "identity_clear" in result["reasons"]

    wrong = parse_goal_understanding(_goal_block(target="bay11"))
    result = evaluate_goal_understanding(
        wrong, expected_bay="bay03", expected_slot="park_slot"
    )
    assert result["valid"] is False
    assert "target_matches_binding" in result["reasons"]


def test_goal_understanding_observation_and_safe_stop_do_not_start() -> None:
    observation = parse_goal_understanding(
        _goal_block(clear="否", decision="REQUEST_OBSERVATION")
    )
    result = evaluate_goal_understanding(
        observation, expected_bay="bay03", expected_slot="park_slot"
    )
    assert result["valid"] is True
    assert result["request_observation"] is True
    assert result["start_session"] is False

    stop = parse_goal_understanding(
        _goal_block(clear="否", decision="SAFE_STOP")
    )
    result = evaluate_goal_understanding(
        stop, expected_bay="bay03", expected_slot="park_slot"
    )
    assert result["valid"] is True
    assert result["safe_stop"] is True
    assert result["start_session"] is False


def test_goal_understanding_rejects_bad_or_duplicate_fields() -> None:
    with pytest.raises(GoalUnderstandingParseError):
        parse_goal_understanding("Task: AUTONOMOUS_VALET_PARKING\n")
    with pytest.raises(GoalUnderstandingParseError):
        parse_goal_understanding(_goal_block() + "Decision: SAFE_STOP\n")
    with pytest.raises(GoalUnderstandingParseError):
        parse_goal_understanding(_goal_block(task="DELIVERY"))


def test_goal_prompt_contains_bound_target_and_closed_actions() -> None:
    prompt = build_goal_understanding_prompt(
        instruction="请将车辆停入左侧靠近出口的空闲车位",
        target_bay="bay03",
        target_slot="park_slot",
        binding_status="bound",
        vehicle_state="stopped at park_entry",
        stage="TARGET_BINDING",
    )
    assert "bay03" in prompt
    assert "park_slot" in prompt
    assert AUTONOMOUS_VALET_PARKING in prompt
    for action in GoalUnderstandingAction.ALL:
        assert action in prompt
    assert "不要猜测未绑定" in prompt
    assert "不得把未绑定的车位当作目标" in prompt


def test_verification_continue_requires_all_fields() -> None:
    parsed = parse_session_decision(_verification_block())
    result = evaluate_session_decision(
        parsed,
        expected_label="A",
        expected_bay="bay03",
        observed_bay="bay03",
    )
    assert result["valid"] is True
    assert result["continue_session"] is True


def test_verification_contradiction_is_refused() -> None:
    parsed = parse_session_decision(
        _verification_block(occupancy="占用", selected="无法确定")
    )
    result = evaluate_session_decision(
        parsed,
        expected_label="A",
        expected_bay="bay03",
        observed_bay="bay03",
    )
    assert result["valid"] is False
    assert "occupancy_vacant" in result["reasons"]
    assert "selected_label" in result["reasons"]


def test_verification_observation_and_safe_stop_do_not_continue() -> None:
    observation = parse_session_decision(
        _verification_block(decision="REQUEST_NEW_OBSERVATION", occupancy="无法确定")
    )
    result = evaluate_session_decision(
        observation,
        expected_label="A",
        expected_bay="bay03",
        observed_bay="bay03",
    )
    assert result["valid"] is True
    assert result["request_observation"] is True
    assert result["continue_session"] is False

    stop = parse_session_decision(
        _verification_block(decision="PROPOSE_SAFE_STOP")
    )
    result = evaluate_session_decision(
        stop,
        expected_label="A",
        expected_bay="bay03",
        observed_bay="bay03",
    )
    assert result["valid"] is True
    assert result["safe_stop"] is True


def test_verification_bad_actions_and_wrong_bay_are_refused() -> None:
    with pytest.raises(SessionDecisionParseError):
        parse_session_decision(
            "A: 空闲\n边界: 清晰\n遮挡: 无\n证据: 充分\nSelected: A\n"
        )
    with pytest.raises(SessionDecisionParseError):
        parse_session_decision(_verification_block(decision="MAYBE"))
    parsed = parse_session_decision(_verification_block())
    result = evaluate_session_decision(
        parsed,
        expected_label="A",
        expected_bay="bay03",
        observed_bay="bay11",
    )
    assert result["valid"] is False
    assert "bay_identity_matches" in result["reasons"]


def test_verification_prompt_uses_closed_vocabulary() -> None:
    prompt = build_session_decision_prompt(
        instruction="请将车辆停入左侧靠近出口的空闲车位",
        target_bay="bay03",
        target_slot="park_slot",
        stage="TARGET_VERIFICATION",
        completed_stages=("TARGET_BINDING", "APPROACH"),
        recent_feedback="goal understanding passed",
        label="A",
    )
    for action in SessionDecisionAction.ALL:
        assert action in prompt
    assert "A: 判断结果，只能从 空闲" in prompt
    assert "Selected" in prompt
    assert "第一行必须是 Decision" in prompt
    assert prompt.rstrip().endswith("Selected: A 或 无法确定")


def _task_block(
    *,
    task: str = AUTONOMOUS_VALET_PARKING,
    constraints: str = "left side, vacant, near exit",
    decision: str = "START_TASK",
    evidence: str = "instruction and current image are clear",
) -> str:
    return (
        f"Task: {task}\n"
        f"Constraints: {constraints}\n"
        f"Decision: {decision}\n"
        f"Evidence: {evidence}\n"
    )


def test_task_understanding_starts_with_constraints() -> None:
    from vln.parking.session_decision import (
        TaskUnderstandingAction,
        build_task_understanding_prompt,
        evaluate_task_understanding,
        parse_task_understanding,
    )

    parsed = parse_task_understanding(_task_block())
    result = evaluate_task_understanding(parsed)
    assert result["valid"] is True
    assert result["start_task"] is True
    prompt = build_task_understanding_prompt(
        instruction="请将车辆停入左侧靠近出口的空闲车位",
        parsed_constraints="side=left, occupancy=vacant, landmark=near_exit",
        vehicle_state="stopped at w4",
    )
    for action in TaskUnderstandingAction.ALL:
        assert action in prompt
    assert "不得在此阶段猜测" in prompt


def test_task_understanding_refuses_missing_constraints_and_bad_decision() -> None:
    from vln.parking.session_decision import (
        TaskUnderstandingParseError,
        parse_task_understanding,
    )

    with pytest.raises(TaskUnderstandingParseError):
        parse_task_understanding("Task: AUTONOMOUS_VALET_PARKING\nDecision: START_TASK\n")
    with pytest.raises(TaskUnderstandingParseError):
        parse_task_understanding(_task_block(decision="MAYBE_START"))
    with pytest.raises(TaskUnderstandingParseError):
        parse_task_understanding(_task_block(constraints=""))
