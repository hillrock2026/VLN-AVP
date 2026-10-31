"""Kernel persistent Context -> Taichu prompt block.

The Kernel carries its own Session/Context through ``planner.plan``. This module
is the intelligence-side boundary that decides which of those entries are still
useful for the current decision and serialises them into a clearly labelled
historical block. Kernel code carries generic state; it never encodes parking
business rules.

Rules enforced here:

* the current image and the current vehicle state stay in the instruction built
  by the caller and take priority over everything rendered here;
* a planning entry is an **unverified model candidate** and is never labelled
  ``confirmed``;
* an execution entry is real Kernel execution feedback, but it does not prove
  that the target is visible now or that its identity still holds;
* entries outside the recent-turn window are counted as stale and are not
  rendered as usable state;
* a missing/malformed Context or a revision mismatch fails closed instead of
  silently using possibly stale data;
* the rendered block is bounded by an entry limit and a character budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

__all__ = [
    "ContextPromptError",
    "SelectedContextEntry",
    "ContextSelection",
    "MAX_CONTEXT_ENTRIES",
    "MAX_CONTEXT_TURNS",
    "MAX_CONTEXT_CHARS",
    "select_context",
    "compose_prompt",
]

#: How many recent history entries may be rendered.
MAX_CONTEXT_ENTRIES = 8

#: Entries older than ``context.turn - MAX_CONTEXT_TURNS`` are stale.
MAX_CONTEXT_TURNS = 6

#: Character budget of the rendered context block.
MAX_CONTEXT_CHARS = 2600

#: The only history kinds the Kernel writes today.
_ENTRY_KINDS = frozenset({"planning", "execution", "stage_transition"})

_SOURCE = "kernel.session.context.history"


class ContextPromptError(ValueError):
    """The Context cannot be used safely for a model prompt."""


def _non_blank(value: object) -> bool:
    return isinstance(value, str) and any(not ch.isspace() for ch in value)


def _required_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ContextPromptError(f"{name} must be a non-negative int")
    return value


def _optional_mapping(value: object, name: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ContextPromptError(f"{name} must be an object or null")
    return value


def _short(value: object, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _domain_field(domain: Mapping[str, Any] | None, key: str) -> object:
    if domain is None:
        return None
    return domain.get(key)


@dataclass(frozen=True)
class SelectedContextEntry:
    """One history entry selected for the prompt, with its provenance."""

    turn: int
    kind: str
    status: str
    source: str
    verified: bool
    revision: int | None
    summary: str
    domain_target: object
    route_goal_node_id: object
    target_node_id: object
    moved_m: object
    stop_reason: object
    post_state: Mapping[str, Any] | None
    error_type: object
    error_message: object
    raw_preview: str | None

    def to_metadata(self) -> dict:
        return {
            "source": self.source,
            "turn": self.turn,
            "kind": self.kind,
            "status": self.status,
            "verified": self.verified,
            "revision": self.revision,
            "summary": self.summary,
            "target": self.domain_target,
            "route_goal_node_id": self.route_goal_node_id,
            "target_node_id": self.target_node_id,
            "moved_m": self.moved_m,
            "stop_reason": self.stop_reason,
            "post_state": (
                None if self.post_state is None else dict(self.post_state)
            ),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "raw_output_preview": self.raw_preview,
        }

    def render(self) -> str:
        if self.kind == "planning":
            label = "planning/模型候选"
            verified = "否（未经验证的模型候选，不得升级为已确认事实）"
        elif self.kind == "execution":
            label = "execution/真实执行反馈"
            verified = "是（真实 Kernel 执行结果；不证明目标当前可见）"
        else:
            label = "domain/阶段状态"
            verified = "是（VLN-AVP 领域状态记录；不是视觉证据）"
        parts = [
            f"- turn={self.turn} kind={label} status={self.status} "
            f"verified={verified}"
        ]
        if self.revision is not None:
            parts[0] += f" revision={self.revision}"
        if self.summary:
            parts.append(f"  {self.summary}")
        return "\n".join(parts)


@dataclass(frozen=True)
class ContextSelection:
    """A bounded, provenance-preserving view of one Kernel Context."""

    session_id: str
    revision: int
    turn: int
    phase: str
    status: str
    current_task: Mapping[str, Any]
    progress: Mapping[str, Any]
    entries: tuple[SelectedContextEntry, ...]
    stale_count: int
    omitted_count: int
    max_chars: int

    @property
    def truncated(self) -> bool:
        return self.stale_count > 0 or self.omitted_count > 0

    def to_metadata(self) -> dict:
        return {
            "source": _SOURCE,
            "session_id": self.session_id,
            "context_revision": self.revision,
            "turn": self.turn,
            "phase": self.phase,
            "status": self.status,
            "current_task": dict(self.current_task),
            "progress": dict(self.progress),
            "selected_entries": [entry.to_metadata() for entry in self.entries],
            "selected_count": len(self.entries),
            "stale_count": self.stale_count,
            "omitted_count": self.omitted_count,
            "truncated": self.truncated,
            "max_chars": self.max_chars,
        }

    def render(self) -> str:
        target = self.current_task.get("target")
        target_kind = self.current_task.get("target_kind")
        goal = self.current_task.get("route_goal_node_id")
        round_index = self.current_task.get("round")
        task_line = "当前任务："
        if target is not None:
            task_line += f"目标 {target}"
            if target_kind:
                task_line += f"（{target_kind}）"
            task_line += "；"
        if goal is not None:
            task_line += f"路线目标节点 {goal}；"
        if round_index is not None:
            task_line += f"当前轮次 {round_index}；"
        task_line = task_line.rstrip("；") + "。"

        completed = self.progress.get("completed_executions")
        total_moved = self.progress.get("total_moved_m")
        last_target = self.progress.get("last_execution_target_node_id")
        progress_line = (
            f"任务进度：已完成执行 {completed} 次，累计位移 "
            f"{total_moved} m；最近执行目标节点 {last_target}。"
        )

        header = (
            "【Kernel 持久上下文（历史记录，不是当前图像证据）】\n"
            f"上下文来源：{_SOURCE}（session={self.session_id}, "
            f"revision={self.revision}, turn={self.turn}, phase={self.phase}, "
            f"status={self.status}）\n"
            f"{task_line}\n"
            f"{progress_line}\n"
            "历史条目（旧 → 新；planning 为未验证模型候选，execution 为真实执行反馈）："
        )
        footer = (
            "【上下文使用规则】\n"
            "1. 当前图像和用户指令中的当前车辆状态优先于以上历史。\n"
            "2. planning 条目只是未经验证的模型候选，不得当作已确认事实或当前可见证据。\n"
            "3. execution 条目是真实执行反馈，但不证明目标当前可见、身份仍然成立。\n"
            "4. 当前图像与历史冲突时以当前图像为准，并如实输出本轮结论块。\n"
            "5. 以上历史不得替代本轮的目标身份、可见性和证据验证。"
        )
        if self.stale_count:
            header += (
                f"\n（已排除 {self.stale_count} 条超出最近轮次窗口的 stale 条目，"
                "不得作为当前状态使用）"
            )
        if self.omitted_count:
            header += (
                f"\n（因长度限制省略 {self.omitted_count} 条较早的有效条目）"
            )
        if not self.entries:
            header += "\n- 当前没有可用的历史条目。"

        budget = max(0, self.max_chars - len(header) - len(footer) - 2)
        lines: list[str] = []
        used = 0
        for entry in self.entries:
            line = entry.render()
            if used + len(line) + 1 > budget:
                remaining = budget - used - 1
                if remaining > 32:
                    lines.append(line[: remaining - 1] + "…")
                break
            lines.append(line)
            used += len(line) + 1

        body = "\n".join(lines) if lines else "- 无。"
        return f"{header}\n{body}\n{footer}"


def _entry_from_history(
    entry: Mapping[str, Any],
    *,
    index: int,
    session_id: str,
    previous_turn: int,
    previous_revision: int | None,
    context_revision: int,
    context_turn: int,
) -> SelectedContextEntry:
    kind = entry.get("kind")
    if kind not in _ENTRY_KINDS:
        raise ContextPromptError(
            f"history[{index}].kind must be one of {sorted(_ENTRY_KINDS)}"
        )
    turn = _required_int(entry.get("turn"), f"history[{index}].turn")
    if turn > context_turn:
        raise ContextPromptError(
            f"history[{index}].turn {turn} exceeds context turn {context_turn}"
        )
    if turn <= previous_turn:
        raise ContextPromptError(
            f"history[{index}].turn {turn} is not strictly increasing"
        )
    revision = entry.get("revision")
    if revision is not None:
        revision = _required_int(revision, f"history[{index}].revision")
        if revision > context_revision:
            raise ContextPromptError(
                f"history[{index}].revision {revision} exceeds context "
                f"revision {context_revision}"
            )
        if previous_revision is not None and revision <= previous_revision:
            raise ContextPromptError(
                f"history[{index}].revision {revision} is not increasing"
            )

    status = entry.get("status")
    if not _non_blank(status):
        raise ContextPromptError(f"history[{index}].status must be a non-blank str")
    domain = _optional_mapping(entry.get("domain"), f"history[{index}].domain")
    error = _optional_mapping(entry.get("error"), f"history[{index}].error")
    post_state = _optional_mapping(
        entry.get("post_state"), f"history[{index}].post_state"
    )

    error_type = None if error is None else error.get("type") or error.get("code")
    error_message = None if error is None else error.get("message")
    raw_preview = _short(entry.get("raw_output_preview"), 240)
    moved_m = entry.get("moved_m")
    stop_reason = entry.get("stop_reason")
    domain_target = _domain_field(domain, "target")
    route_goal = _domain_field(domain, "route_goal_node_id")
    target_node = _domain_field(domain, "target_node_id")

    if kind == "planning":
        verified = False
        pieces = []
        if domain_target is not None:
            pieces.append(f"目标={domain_target}")
        if route_goal is not None:
            pieces.append(f"路线目标节点={route_goal}")
        if raw_preview:
            pieces.append(f"模型输出预览={raw_preview!r}")
        if status == "failed" and (error_type or error_message):
            pieces.append(f"失败原因={error_type}: {error_message}")
        summary = "；".join(pieces) if pieces else "无摘要"
    elif kind == "stage_transition":
        verified = True
        parking = (
            domain.get("parking") if isinstance(domain, Mapping) else None
        )
        parking = parking if isinstance(parking, Mapping) else {}
        parking_target = parking.get("target")
        if isinstance(parking_target, Mapping):
            domain_target = (
                parking_target.get("bay_id")
                or parking_target.get("target_id")
                or domain_target
            )
        pieces = []
        if parking.get("current_stage") is not None:
            pieces.append(f"current_stage={parking.get('current_stage')}")
        if parking.get("completed_stages") is not None:
            pieces.append(
                "completed_stages="
                f"{list(parking.get('completed_stages') or ())}"
            )
        if domain_target is not None:
            pieces.append(f"目标={domain_target}")
        summary = "；".join(pieces) if pieces else "领域状态已记录"
    else:
        verified = True
        pieces = []
        if domain_target is not None:
            pieces.append(f"目标={domain_target}")
        if route_goal is not None:
            pieces.append(f"路线目标节点={route_goal}")
        if target_node is not None:
            pieces.append(f"执行目标节点={target_node}")
        if moved_m is not None:
            pieces.append(f"位移={moved_m} m")
        if stop_reason is not None:
            pieces.append(f"停止原因={stop_reason}")
        if post_state:
            pieces.append(
                "post_state=("
                f"x={post_state.get('x')}, y={post_state.get('y')}, "
                f"yaw={post_state.get('yaw')}, speed={post_state.get('speed')})"
            )
        if status == "failed" and (error_type or error_message):
            pieces.append(f"失败原因={error_type}: {error_message}")
        summary = "；".join(pieces) if pieces else "无摘要"

    return SelectedContextEntry(
        turn=turn,
        kind=str(kind),
        status=str(status),
        source=_SOURCE,
        verified=verified,
        revision=revision,
        summary=summary,
        domain_target=domain_target,
        route_goal_node_id=route_goal,
        target_node_id=target_node,
        moved_m=moved_m,
        stop_reason=stop_reason,
        post_state=post_state,
        error_type=error_type,
        error_message=error_message,
        raw_preview=raw_preview,
    )


def select_context(
    context: object,
    *,
    request_revision: object = None,
    request_session_id: object = None,
    current_domain: Mapping[str, Any] | None = None,
    max_entries: int = MAX_CONTEXT_ENTRIES,
    max_turns: int = MAX_CONTEXT_TURNS,
    max_chars: int = MAX_CONTEXT_CHARS,
) -> ContextSelection:
    """Validate one Kernel Context and select the entries to render.

    Raises :class:`ContextPromptError` for a missing/malformed Context, a
    revision mismatch, or an inconsistent history. Never silently substitutes a
    previous Context for the current one.
    """

    if not isinstance(context, Mapping):
        raise ContextPromptError("context must be an object")
    if type(max_entries) is not int or max_entries < 1:
        raise ContextPromptError("max_entries must be a positive int")
    if type(max_turns) is not int or max_turns < 0:
        raise ContextPromptError("max_turns must be a non-negative int")
    if type(max_chars) is not int or max_chars < 512:
        raise ContextPromptError("max_chars must be an int >= 512")

    session_id = context.get("session_id")
    if not _non_blank(session_id):
        raise ContextPromptError("context.session_id must be a non-blank str")
    revision = _required_int(
        context.get("context_revision"), "context.context_revision"
    )
    turn = _required_int(context.get("turn"), "context.turn")
    phase = context.get("phase", "unknown")
    status = context.get("status", "unknown")
    if not _non_blank(phase):
        raise ContextPromptError("context.phase must be a non-blank str")
    if not _non_blank(status):
        raise ContextPromptError("context.status must be a non-blank str")

    if request_session_id is not None and request_session_id != session_id:
        raise ContextPromptError(
            "request session_id does not match the Context session_id"
        )
    if request_revision is not None and request_revision != revision:
        raise ContextPromptError(
            f"context revision mismatch: request={request_revision}, "
            f"context={revision}"
        )

    raw_history = context.get("history")
    if raw_history is None:
        raw_history = []
    if not isinstance(raw_history, list):
        raise ContextPromptError("context.history must be an array")

    parsed: list[SelectedContextEntry] = []
    previous_turn = -1
    previous_revision: int | None = None
    for index, item in enumerate(raw_history):
        if not isinstance(item, Mapping):
            raise ContextPromptError(f"history[{index}] must be an object")
        parsed_entry = _entry_from_history(
            item,
            index=index,
            session_id=session_id,
            previous_turn=previous_turn,
            previous_revision=previous_revision,
            context_revision=revision,
            context_turn=turn,
        )
        parsed.append(parsed_entry)
        previous_turn = parsed_entry.turn
        if parsed_entry.revision is not None:
            previous_revision = parsed_entry.revision

    if parsed and parsed[-1].turn != turn:
        raise ContextPromptError(
            f"context history ends at turn {parsed[-1].turn}, but Context turn "
            f"is {turn}; the Context is inconsistent"
        )

    cutoff = turn - max_turns
    recent = [entry for entry in parsed if entry.turn >= cutoff]
    stale_count = len(parsed) - len(recent)
    selected = recent[-max_entries:]
    omitted_count = len(recent) - len(selected)

    completed_executions = sum(
        1
        for entry in parsed
        if entry.kind == "execution" and entry.status == "completed"
    )
    total_moved = 0.0
    for entry in parsed:
        if entry.kind == "execution" and isinstance(entry.moved_m, (int, float)):
            total_moved += float(entry.moved_m)
    last_execution = next(
        (entry for entry in reversed(parsed) if entry.kind == "execution"), None
    )

    current_task: dict[str, Any] = {}
    if isinstance(current_domain, Mapping):
        for key in (
            "target",
            "target_kind",
            "route_goal_node_id",
            "round",
            "intent_id",
            "frame_id",
            "trigger",
        ):
            if key in current_domain:
                current_task[key] = current_domain.get(key)
    progress = {
        "completed_executions": completed_executions,
        "total_moved_m": round(total_moved, 3),
        "last_execution_target_node_id": (
            None
            if last_execution is None
            else (
                last_execution.target_node_id
                if last_execution.target_node_id is not None
                else last_execution.route_goal_node_id
            )
        ),
    }

    return ContextSelection(
        session_id=str(session_id),
        revision=revision,
        turn=turn,
        phase=str(phase),
        status=str(status),
        current_task=current_task,
        progress=progress,
        entries=tuple(selected),
        stale_count=stale_count,
        omitted_count=omitted_count,
        max_chars=max_chars,
    )


def compose_prompt(instruction: str, selection: ContextSelection) -> str:
    """Append the bounded historical block to the caller's current prompt."""

    if type(instruction) is not str or not instruction.strip():
        raise ContextPromptError("instruction must be a non-blank str")
    if not isinstance(selection, ContextSelection):
        raise ContextPromptError("selection must be a ContextSelection")
    return f"{instruction.rstrip()}\n\n{selection.render()}"
