"""Strict Taichu decisions for a Session-centric parking task.

These are domain decisions, not a task lifecycle. The Agent-Kernel Session is
the only task lifecycle; this module only validates model candidates that the
session driver may act on.

Two protocols:

* goal understanding: confirm the task type, the already-bound target and the
  execution preconditions from the user instruction, the current image and the
  Kernel Context;
* target verification: combine a next-action candidate with the existing
  closed-vocabulary target-verification fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from vln.nav.target_binding import INTERNAL_VACANT
from vln.nav.target_verification import (
    VerificationDecision,
    VerificationDecisionParseError,
    parse_verification_decision,
)
from vln.vlm.verification_prompt import (
    BOUNDARY_CLEAR,
    EVIDENCE_SUFFICIENT,
    OCCLUSION_NONE,
    build_target_verification_prompt,
)

__all__ = [
    "AUTONOMOUS_VALET_PARKING",
    "TaskUnderstandingAction",
    "TaskUnderstanding",
    "TaskUnderstandingParseError",
    "build_task_understanding_prompt",
    "parse_task_understanding",
    "evaluate_task_understanding",
    "GoalUnderstandingAction",
    "GoalUnderstanding",
    "GoalUnderstandingParseError",
    "SessionDecisionAction",
    "SessionDecision",
    "SessionDecisionParseError",
    "build_goal_understanding_prompt",
    "parse_goal_understanding",
    "evaluate_goal_understanding",
    "build_session_decision_prompt",
    "parse_session_decision",
    "evaluate_session_decision",
]

AUTONOMOUS_VALET_PARKING = "AUTONOMOUS_VALET_PARKING"

_FIELD_LINE_TEMPLATE = r"^[ \t>*`#\-\u2022]*{field}[ \t>*`]*[:：][ \t]*(.*?)[ \t]*$"
_VALUE_STRIP = "`*\"'。 "


def _field_values(raw_text: str, field: str) -> tuple[str, ...]:
    pattern = re.compile(
        _FIELD_LINE_TEMPLATE.format(field=re.escape(field)),
        re.IGNORECASE | re.MULTILINE,
    )
    return tuple(
        match.group(1).strip().strip(_VALUE_STRIP)
        for match in pattern.finditer(raw_text)
    )


def _required_value(
    raw_text: str,
    field: str,
    allowed: tuple[str, ...],
    error_cls=None,
) -> str:
    if error_cls is None:
        error_cls = GoalUnderstandingParseError
    values = _field_values(raw_text, field)
    if not values:
        raise error_cls(f"missing field {field!r}")
    if len(values) > 1:
        raise error_cls(
            f"duplicate field {field!r}: the answer is ambiguous"
        )
    value = values[0]
    if value == "":
        raise error_cls(f"field {field!r} is empty")
    if value not in allowed:
        raise error_cls(
            f"field {field!r} uses off-vocabulary value {value!r}; "
            f"expected one of {list(allowed)}"
        )
    return value


class TaskUnderstandingAction:
    START_TASK = "START_TASK"
    REQUEST_OBSERVATION = "REQUEST_OBSERVATION"
    SAFE_STOP = "SAFE_STOP"
    ALL = frozenset({START_TASK, REQUEST_OBSERVATION, SAFE_STOP})


class TaskUnderstandingParseError(ValueError):
    """The model's task-understanding answer is not the required block."""


@dataclass(frozen=True)
class TaskUnderstanding:
    task_type: str
    constraints: str
    decision: str
    evidence: str
    raw_text: str

    def __post_init__(self) -> None:
        if self.task_type != AUTONOMOUS_VALET_PARKING:
            raise TaskUnderstandingParseError(
                f"unsupported task_type {self.task_type!r}"
            )
        if self.decision not in TaskUnderstandingAction.ALL:
            raise TaskUnderstandingParseError(
                f"unsupported task decision {self.decision!r}"
            )

    def to_metadata(self) -> dict:
        return {
            "task_type": self.task_type,
            "constraints": self.constraints,
            "decision": self.decision,
            "evidence": self.evidence,
            "raw_text": self.raw_text,
        }


def build_task_understanding_prompt(
    *,
    instruction: str,
    parsed_constraints: str,
    vehicle_state: str,
) -> str:
    """Build the pre-binding task/constraint understanding prompt."""

    for value, name in (
        (instruction, "instruction"),
        (parsed_constraints, "parsed_constraints"),
        (vehicle_state, "vehicle_state"),
    ):
        if type(value) is not str or not value.strip():
            raise ValueError(f"{name} must be a non-blank str")
    return (
        "你是自主泊车任务的目标理解模块。请只依据用户指令、当前车辆状态和这张"
        "刚刚采集的停车场图像，确认任务类型和目标约束；此时还没有绑定具体车位。\n"
        f"用户原始指令：{instruction}\n"
        f"已解析的目标约束：{parsed_constraints}\n"
        f"当前车辆状态：{vehicle_state}\n"
        "请确认任务类型，并用自己的话复述你理解的目标约束。不得在此阶段猜测或"
        "指定具体车位编号，具体绑定由后续 Target Binding 的真实观察完成。\n"
        "\n请严格按以下字段逐行输出，每行只写一个值，不要输出其他内容：\n"
        f"Task: {AUTONOMOUS_VALET_PARKING}\n"
        "Constraints: 用一句话复述目标约束\n"
        f"Decision: {TaskUnderstandingAction.START_TASK} 或 "
        f"{TaskUnderstandingAction.REQUEST_OBSERVATION} 或 "
        f"{TaskUnderstandingAction.SAFE_STOP}\n"
        "Evidence: 一句话说明你据以判断的依据\n"
        "\n规则：\n"
        "1. 只有任务类型和约束都明确时，才能选择 START_TASK。\n"
        "2. 不得把未绑定的具体车位当作目标；不得猜测车位编号。\n"
        "3. 不确定或图像不足时选择 REQUEST_OBSERVATION 或 SAFE_STOP。\n"
        "4. 不要照抄本说明中的整句文字。"
    )


def parse_task_understanding(raw_text: str) -> TaskUnderstanding:
    if type(raw_text) is not str or raw_text.strip() == "":
        raise TaskUnderstandingParseError("model response is blank")
    task_type = _required_value(
        raw_text,
        "Task",
        (AUTONOMOUS_VALET_PARKING,),
        TaskUnderstandingParseError,
    )
    constraints_values = _field_values(raw_text, "Constraints")
    if not constraints_values:
        raise TaskUnderstandingParseError("missing field 'Constraints'")
    if len(constraints_values) > 1:
        raise TaskUnderstandingParseError("duplicate field 'Constraints'")
    constraints = constraints_values[0]
    if constraints == "":
        raise TaskUnderstandingParseError("field 'Constraints' is empty")
    decision = _required_value(
        raw_text,
        "Decision",
        tuple(TaskUnderstandingAction.ALL),
        TaskUnderstandingParseError,
    )
    evidence_values = _field_values(raw_text, "Evidence")
    if not evidence_values:
        raise TaskUnderstandingParseError("missing field 'Evidence'")
    if len(evidence_values) > 1:
        raise TaskUnderstandingParseError("duplicate field 'Evidence'")
    evidence = evidence_values[0]
    if evidence == "":
        raise TaskUnderstandingParseError("field 'Evidence' is empty")
    return TaskUnderstanding(
        task_type=task_type,
        constraints=constraints,
        decision=decision,
        evidence=evidence,
        raw_text=raw_text,
    )


def evaluate_task_understanding(understanding: TaskUnderstanding) -> dict:
    if not isinstance(understanding, TaskUnderstanding):
        raise TypeError("understanding must be a TaskUnderstanding")
    checks = {
        "task_type": understanding.task_type == AUTONOMOUS_VALET_PARKING,
        "constraints_present": bool(understanding.constraints.strip()),
        "evidence_present": bool(understanding.evidence.strip()),
    }
    failed = [name for name, value in checks.items() if not value]
    if understanding.decision == TaskUnderstandingAction.START_TASK:
        return {
            "valid": not failed,
            "start_task": not failed,
            "request_observation": False,
            "safe_stop": False,
            "checks": checks,
            "reasons": failed,
            "decision": understanding.decision,
        }
    if understanding.decision == TaskUnderstandingAction.SAFE_STOP:
        return {
            "valid": True,
            "start_task": False,
            "request_observation": False,
            "safe_stop": True,
            "checks": checks,
            "reasons": [],
            "decision": understanding.decision,
        }
    return {
        "valid": True,
        "start_task": False,
        "request_observation": True,
        "safe_stop": False,
        "checks": checks,
        "reasons": [],
        "decision": understanding.decision,
    }


class GoalUnderstandingAction:
    START_SESSION = "START_SESSION"
    REQUEST_OBSERVATION = "REQUEST_OBSERVATION"
    SAFE_STOP = "SAFE_STOP"
    ALL = frozenset({START_SESSION, REQUEST_OBSERVATION, SAFE_STOP})


class GoalUnderstandingParseError(ValueError):
    """The model's goal-understanding answer is not the required block."""


@dataclass(frozen=True)
class GoalUnderstanding:
    task_type: str
    target: str
    identity_clear: str
    decision: str
    evidence: str
    raw_text: str

    def __post_init__(self) -> None:
        if self.task_type != AUTONOMOUS_VALET_PARKING:
            raise GoalUnderstandingParseError(
                f"unsupported task_type {self.task_type!r}"
            )
        if self.decision not in GoalUnderstandingAction.ALL:
            raise GoalUnderstandingParseError(
                f"unsupported goal decision {self.decision!r}"
            )

    def to_metadata(self) -> dict:
        return {
            "task_type": self.task_type,
            "target": self.target,
            "identity_clear": self.identity_clear,
            "decision": self.decision,
            "evidence": self.evidence,
            "raw_text": self.raw_text,
        }


def build_goal_understanding_prompt(
    *,
    instruction: str,
    target_bay: str,
    target_slot: str,
    binding_status: str,
    vehicle_state: str,
    stage: str,
) -> str:
    """Build the real-model goal-understanding prompt."""

    for value, name in (
        (instruction, "instruction"),
        (target_bay, "target_bay"),
        (target_slot, "target_slot"),
        (binding_status, "binding_status"),
        (vehicle_state, "vehicle_state"),
        (stage, "stage"),
    ):
        if type(value) is not str or not value.strip():
            raise ValueError(f"{name} must be a non-blank str")

    return (
        "你是自主泊车任务的目标理解模块。请只依据用户指令、已验收的目标绑定、"
        "当前车辆状态和这张刚刚采集的停车场图像作答，不要猜测未绑定的目标。\n"
        f"用户原始指令：{instruction}\n"
        f"已绑定目标：{target_bay} / {target_slot}（binding status={binding_status}）。\n"
        f"当前阶段：{stage}。\n"
        f"当前车辆状态：{vehicle_state}。\n"
        "请确认任务类型、目标身份是否明确，以及当前任务是否具备继续执行的条件。\n"
        "如果目标绑定不明确、图像无法支持任务或车辆状态不安全，不得选择开始。\n"
        "\n请严格按以下字段逐行输出，每行只写一个值，不要输出其他内容：\n"
        f"Task: {AUTONOMOUS_VALET_PARKING}\n"
        f"Target: {target_bay}\n"
        "Target identity clear: 是 或 否\n"
        f"Decision: {GoalUnderstandingAction.START_SESSION} 或 "
        f"{GoalUnderstandingAction.REQUEST_OBSERVATION} 或 "
        f"{GoalUnderstandingAction.SAFE_STOP}\n"
        "Evidence: 一句话说明你据以判断的可见或上下文依据\n"
        "\n规则：\n"
        f"1. 只有 Target identity clear=是 且目标与已绑定目标一致时，才能选择 "
        f"{GoalUnderstandingAction.START_SESSION}。\n"
        "2. 不得根据本指令假定目标存在；不得把未绑定的车位当作目标。\n"
        "3. 不确定、目标不明确、图像不足或车辆状态不安全时，选择 "
        f"{GoalUnderstandingAction.REQUEST_OBSERVATION} 或 "
        f"{GoalUnderstandingAction.SAFE_STOP}。\n"
        "4. 不要照抄本说明中的整句文字。"
    )


def parse_goal_understanding(raw_text: str) -> GoalUnderstanding:
    """Parse the strict goal-understanding block, or refuse."""

    if type(raw_text) is not str or raw_text.strip() == "":
        raise GoalUnderstandingParseError("model response is blank")
    task_type = _required_value(raw_text, "Task", (AUTONOMOUS_VALET_PARKING,))
    targets = _field_values(raw_text, "Target")
    if not targets:
        raise GoalUnderstandingParseError("missing field 'Target'")
    if len(targets) > 1:
        raise GoalUnderstandingParseError("duplicate field 'Target'")
    target = targets[0]
    if target == "":
        raise GoalUnderstandingParseError("field 'Target' is empty")
    identity_clear = _required_value(
        raw_text, "Target identity clear", ("是", "否")
    )
    decision = _required_value(raw_text, "Decision", tuple(GoalUnderstandingAction.ALL))
    evidence_values = _field_values(raw_text, "Evidence")
    if not evidence_values:
        raise GoalUnderstandingParseError("missing field 'Evidence'")
    if len(evidence_values) > 1:
        raise GoalUnderstandingParseError("duplicate field 'Evidence'")
    evidence = evidence_values[0]
    if evidence == "":
        raise GoalUnderstandingParseError("field 'Evidence' is empty")
    return GoalUnderstanding(
        task_type=task_type,
        target=target,
        identity_clear=identity_clear,
        decision=decision,
        evidence=evidence,
        raw_text=raw_text,
    )


def _missing(field: str):
    raise GoalUnderstandingParseError(f"missing field {field!r}")


def evaluate_goal_understanding(
    understanding: GoalUnderstanding,
    *,
    expected_bay: str,
    expected_slot: str,
) -> dict:
    """Check the model's goal understanding against the bound target."""

    if not isinstance(understanding, GoalUnderstanding):
        raise TypeError("understanding must be a GoalUnderstanding")
    if type(expected_bay) is not str or not expected_bay.strip():
        raise ValueError("expected_bay must be a non-blank str")
    if type(expected_slot) is not str or not expected_slot.strip():
        raise ValueError("expected_slot must be a non-blank str")

    checks = {
        "task_type": understanding.task_type == AUTONOMOUS_VALET_PARKING,
        "target_matches_binding": understanding.target == expected_bay,
        "identity_clear": understanding.identity_clear == "是",
        "evidence_present": bool(understanding.evidence.strip()),
    }
    failed = [name for name, value in checks.items() if not value]
    if understanding.decision == GoalUnderstandingAction.START_SESSION:
        return {
            "valid": not failed,
            "start_session": not failed,
            "request_observation": False,
            "safe_stop": False,
            "checks": checks,
            "reasons": failed,
            "decision": understanding.decision,
            "expected_slot": expected_slot,
        }
    if understanding.decision == GoalUnderstandingAction.SAFE_STOP:
        return {
            "valid": True,
            "start_session": False,
            "request_observation": False,
            "safe_stop": True,
            "checks": checks,
            "reasons": [],
            "decision": understanding.decision,
            "expected_slot": expected_slot,
        }
    return {
        "valid": True,
        "start_session": False,
        "request_observation": True,
        "safe_stop": False,
        "checks": checks,
        "reasons": [],
        "decision": understanding.decision,
        "expected_slot": expected_slot,
    }


# ---------------------------------------------------------------------------
# Target-verification decision (domain-level action + verification block)
# ---------------------------------------------------------------------------


class SessionDecisionAction:
    CONTINUE_CURRENT_STAGE = "CONTINUE_CURRENT_STAGE"
    REQUEST_NEW_OBSERVATION = "REQUEST_NEW_OBSERVATION"
    PROPOSE_RECOVERY = "PROPOSE_RECOVERY"
    PROPOSE_REPLAN = "PROPOSE_REPLAN"
    PROPOSE_SAFE_STOP = "PROPOSE_SAFE_STOP"
    ALL = frozenset(
        {
            CONTINUE_CURRENT_STAGE,
            REQUEST_NEW_OBSERVATION,
            PROPOSE_RECOVERY,
            PROPOSE_REPLAN,
            PROPOSE_SAFE_STOP,
        }
    )
    OBSERVATION_ACTIONS = frozenset(
        {REQUEST_NEW_OBSERVATION, PROPOSE_RECOVERY, PROPOSE_REPLAN}
    )


class SessionDecisionParseError(ValueError):
    """The model's target-verification decision is not the required block."""


@dataclass(frozen=True)
class SessionDecision:
    action: str
    verification: VerificationDecision
    raw_text: str

    def __post_init__(self) -> None:
        if self.action not in SessionDecisionAction.ALL:
            raise SessionDecisionParseError(
                f"unknown session action {self.action!r}"
            )
        if not isinstance(self.verification, VerificationDecision):
            raise SessionDecisionParseError(
                "verification must be a VerificationDecision"
            )

    def to_metadata(self) -> dict:
        return {
            "action": self.action,
            "verification": self.verification.to_metadata(),
            "raw_text": self.raw_text,
        }


def build_session_decision_prompt(
    *,
    instruction: str,
    target_bay: str,
    target_slot: str,
    stage: str,
    completed_stages: tuple[str, ...],
    recent_feedback: str,
    label: str = "A",
) -> str:
    """Build the target-verification action prompt over the overlay image."""

    for value, name in (
        (instruction, "instruction"),
        (target_bay, "target_bay"),
        (target_slot, "target_slot"),
        (stage, "stage"),
    ):
        if type(value) is not str or not value.strip():
            raise ValueError(f"{name} must be a non-blank str")
    if type(label) is not str or label not in "ABCDEFGH" or len(label) != 1:
        raise ValueError(f"unsupported label {label!r}")
    if not isinstance(completed_stages, tuple):
        completed_stages = tuple(completed_stages)
    if any(type(item) is not str or not item.strip() for item in completed_stages):
        raise ValueError("completed_stages must contain non-blank strings")
    if type(recent_feedback) is not str:
        raise ValueError("recent_feedback must be a str")

    base = build_target_verification_prompt(label)
    context = (
        "\n本次泊车会话的上下文：\n"
        f"用户原始指令：{instruction}\n"
        f"绑定目标：{target_bay} / {target_slot}。\n"
        f"当前阶段：{stage}。\n"
        f"已完成阶段：{', '.join(completed_stages) if completed_stages else '无'}。\n"
        f"最近真实反馈：{recent_feedback or '无'}。\n"
        "请同时给出下一步候选决策。只有高亮区域空闲、边界清晰、无遮挡且证据充分时，"
        f"才能选择 {SessionDecisionAction.CONTINUE_CURRENT_STAGE}；"
        "任何不确定、不可见、占用或证据不足都必须选择 "
        f"{SessionDecisionAction.REQUEST_NEW_OBSERVATION} 或 "
        f"{SessionDecisionAction.PROPOSE_SAFE_STOP}，不得选择继续。\n"
        "不要照抄本说明，不要根据文字假定目标存在。\n"
        "\n请在上述字段块之前先写一行：\n"
        "Decision: "
        f"{SessionDecisionAction.CONTINUE_CURRENT_STAGE} 或 "
        f"{SessionDecisionAction.REQUEST_NEW_OBSERVATION} 或 "
        f"{SessionDecisionAction.PROPOSE_RECOVERY} 或 "
        f"{SessionDecisionAction.PROPOSE_REPLAN} 或 "
        f"{SessionDecisionAction.PROPOSE_SAFE_STOP}\n"
    )
    output_block = (
        "\n输出格式（必须严格按以下顺序逐行输出，共 6 行；"
        "第一行必须是 Decision，任何一行都不得省略）：\n"
        "Decision: 从上面列出的动作值中选择一个\n"
        "A: 空闲、占用或无法确定\n"
        "边界: 清晰、不清晰或无法确定\n"
        "遮挡: 无、有或无法确定\n"
        "证据: 充分、不足或无法确定\n"
        "Selected: A 或 无法确定\n"
    )
    return context + "\n" + base + output_block


def parse_session_decision(raw_text: str, label: str = "A") -> SessionDecision:
    """Parse the action and the closed-vocabulary verification block."""

    if type(raw_text) is not str or raw_text.strip() == "":
        raise SessionDecisionParseError("model response is blank")
    actions = _field_values(raw_text, "Decision")
    if not actions:
        raise SessionDecisionParseError("missing required field: 'Decision'")
    if len(actions) > 1:
        raise SessionDecisionParseError(
            f"duplicate field 'Decision': {len(actions)} occurrences"
        )
    action = actions[0]
    if action not in SessionDecisionAction.ALL:
        raise SessionDecisionParseError(
            f"off-vocabulary Decision {action!r}; expected one of "
            f"{sorted(SessionDecisionAction.ALL)}"
        )
    try:
        verification = parse_verification_decision(raw_text, label=label)
    except VerificationDecisionParseError as error:
        raise SessionDecisionParseError(str(error)) from error
    return SessionDecision(
        action=action,
        verification=verification,
        raw_text=raw_text,
    )


def evaluate_session_decision(
    decision: SessionDecision,
    *,
    expected_label: str = "A",
    expected_bay: str,
    observed_bay: str,
) -> dict:
    """Decide whether a target-verification action may continue the session."""

    if not isinstance(decision, SessionDecision):
        raise TypeError("decision must be a SessionDecision")
    for value, name in (
        (expected_bay, "expected_bay"),
        (observed_bay, "observed_bay"),
    ):
        if type(value) is not str or not value.strip():
            raise ValueError(f"{name} must be a non-blank str")
    if expected_label not in "ABCDEFGH" or len(expected_label) != 1:
        raise ValueError("expected_label must be one of A-H")

    verification = decision.verification
    checks = {
        "bay_identity_matches": expected_bay == observed_bay,
        "selected_label": verification.selected == expected_label,
        "occupancy_vacant": verification.occupancy == INTERNAL_VACANT,
        "boundary_clear": verification.boundary_answer == BOUNDARY_CLEAR,
        "not_occluded": verification.occlusion_answer == OCCLUSION_NONE,
        "evidence_sufficient": (
            verification.evidence_answer == EVIDENCE_SUFFICIENT
        ),
    }
    failed = [name for name, value in checks.items() if not value]
    action = decision.action
    if action == SessionDecisionAction.CONTINUE_CURRENT_STAGE:
        return {
            "valid": not failed,
            "continue_session": not failed,
            "request_observation": False,
            "safe_stop": False,
            "checks": checks,
            "reasons": failed,
            "action": action,
        }
    if action == SessionDecisionAction.PROPOSE_SAFE_STOP:
        return {
            "valid": True,
            "continue_session": False,
            "request_observation": False,
            "safe_stop": True,
            "checks": checks,
            "reasons": [],
            "action": action,
        }
    if action in SessionDecisionAction.OBSERVATION_ACTIONS:
        return {
            "valid": True,
            "continue_session": False,
            "request_observation": True,
            "safe_stop": False,
            "checks": checks,
            "reasons": [],
            "action": action,
        }
    return {
        "valid": False,
        "continue_session": False,
        "request_observation": False,
        "safe_stop": False,
        "checks": checks,
        "reasons": [f"unsupported_action:{action}"],
        "action": action,
    }
