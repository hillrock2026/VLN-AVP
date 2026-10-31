"""Kernel Context -> model prompt selection and serialization."""

from __future__ import annotations

import pytest

from vln.vlm.context_prompt import (
    ContextPromptError,
    compose_prompt,
    select_context,
)


def _planning(
    turn: int,
    revision: int,
    preview: str,
    *,
    target: str = "blue car",
    status: str = "planned",
    error: dict | None = None,
) -> dict:
    entry = {
        "kind": "planning",
        "turn": turn,
        "revision": revision,
        "request_id": f"plan-{turn}",
        "status": status,
        "raw_output_preview": preview,
        "domain": {
            "target": target,
            "route_goal_node_id": "b_goal",
            "round": turn,
        },
    }
    if error is not None:
        entry["error"] = error
    return entry


def _execution(
    turn: int,
    revision: int,
    *,
    moved_m: float = 1.25,
    status: str = "completed",
) -> dict:
    return {
        "kind": "execution",
        "turn": turn,
        "revision": revision,
        "request_id": f"exec-{turn}",
        "capability_id": "parking.move",
        "status": status,
        "moved_m": moved_m,
        "stop_reason": "goal",
        "pre_state": {"x": 0.0, "y": 0.0, "yaw": 0.0, "speed": 0.0},
        "post_state": {"x": 1.2, "y": 0.1, "yaw": 2.0, "speed": 0.0},
        "domain": {
            "target": "blue car",
            "route_goal_node_id": "c_goal",
            "target_node_id": "b_mid",
            "round": turn,
        },
    }


def _context(
    *,
    turn: int = 2,
    revision: int = 2,
    history: list | None = None,
    session_id: str = "S1",
) -> dict:
    return {
        "session_id": session_id,
        "turn": turn,
        "context_revision": revision,
        "phase": "planning",
        "status": "planned",
        "history": (
            [
                _planning(1, 1, "Target: blue car\nIdentified as: 无法确定"),
                _execution(2, 2),
            ]
            if history is None
            else history
        ),
    }


def test_renders_current_task_vehicle_progress_and_provenance() -> None:
    selection = select_context(
        _context(),
        request_revision=2,
        request_session_id="S1",
        current_domain={
            "target": "blue car",
            "target_kind": "车辆",
            "route_goal_node_id": "c_goal",
            "round": 3,
        },
    )
    metadata = selection.to_metadata()
    assert metadata["source"] == "kernel.session.context.history"
    assert metadata["context_revision"] == 2
    assert metadata["current_task"]["target"] == "blue car"
    assert metadata["progress"]["completed_executions"] == 1
    assert metadata["progress"]["total_moved_m"] == 1.25
    assert metadata["progress"]["last_execution_target_node_id"] == "b_mid"

    entries = metadata["selected_entries"]
    assert [entry["kind"] for entry in entries] == ["planning", "execution"]
    assert entries[0]["verified"] is False
    assert entries[1]["verified"] is True
    assert all(
        entry["source"] == "kernel.session.context.history" for entry in entries
    )

    block = selection.render()
    assert "Kernel 持久上下文" in block
    assert "当前任务：目标 blue car（车辆）" in block
    assert "路线目标节点 c_goal" in block
    assert "未经验证的模型候选" in block
    assert "真实 Kernel 执行结果" in block
    assert "执行目标节点=b_mid" in block
    assert "post_state=(x=1.2, y=0.1, yaw=2.0, speed=0.0)" in block


def test_a_context_change_changes_the_model_prompt() -> None:
    first = compose_prompt(
        "CURRENT INSTRUCTION",
        select_context(_context(), request_revision=2),
    )
    changed_history = [
        _planning(1, 1, "Target: blue car\nIdentified as: blue car"),
        _execution(2, 2, moved_m=4.5),
    ]
    second = compose_prompt(
        "CURRENT INSTRUCTION",
        select_context(
            _context(history=changed_history), request_revision=2
        ),
    )
    assert first != second
    assert "Identified as: 无法确定" in first
    assert "Identified as: blue car" not in first
    assert "Identified as: blue car" in second
    assert "位移=4.5 m" in second
    assert "位移=1.25 m" not in second


def test_stale_entries_are_excluded_from_the_prompt() -> None:
    history = [
        _planning(1, 1, "STALE-PREVIEW"),
        _planning(10, 10, "RECENT-PREVIEW"),
    ]
    selection = select_context(
        _context(turn=10, revision=10, history=history),
        request_revision=10,
        max_turns=3,
    )
    assert selection.stale_count == 1
    block = selection.render()
    assert "STALE-PREVIEW" not in block
    assert "RECENT-PREVIEW" in block
    assert "stale" in block


def test_planning_is_never_promoted_to_confirmed() -> None:
    selection = select_context(
        _context(
            turn=1,
            revision=1,
            history=[_planning(1, 1, "confirmed target blue car")],
        ),
        request_revision=1,
        max_turns=6,
    )
    entry = selection.to_metadata()["selected_entries"][0]
    assert entry["verified"] is False
    block = selection.render()
    assert "不得升级为已确认事实" in block
    assert "verified=否" in block


def test_missing_or_malformed_context_fails_closed() -> None:
    with pytest.raises(ContextPromptError):
        select_context(None)
    with pytest.raises(ContextPromptError):
        select_context({"session_id": "S1", "turn": 0, "history": []})
    with pytest.raises(ContextPromptError):
        select_context(
            {"session_id": "S1", "turn": 0, "context_revision": 0, "history": {}}
        )
    with pytest.raises(ContextPromptError):
        select_context(
            {
                "session_id": "S1",
                "turn": 1,
                "context_revision": 1,
                "history": [{"kind": "planning", "turn": 2, "status": "planned"}],
            }
        )
    # The last history turn must match the Context turn.
    with pytest.raises(ContextPromptError):
        select_context(
            {
                "session_id": "S1",
                "turn": 5,
                "context_revision": 1,
                "history": [{"kind": "planning", "turn": 1, "status": "planned"}],
            }
        )


def test_revision_and_session_mismatch_fail_closed() -> None:
    with pytest.raises(ContextPromptError, match="revision mismatch"):
        select_context(_context(), request_revision=1)
    with pytest.raises(ContextPromptError, match="session_id"):
        select_context(_context(), request_session_id="OTHER")


def test_overlong_context_is_bounded() -> None:
    history = [
        _planning(turn, turn, f"preview-{turn}-" + ("x" * 200))
        for turn in range(1, 41)
    ]
    selection = select_context(
        _context(turn=40, revision=40, history=history),
        request_revision=40,
        max_entries=4,
        max_turns=50,
        max_chars=1200,
    )
    metadata = selection.to_metadata()
    assert metadata["selected_count"] == 4
    assert metadata["omitted_count"] == 36
    assert metadata["truncated"] is True
    assert len(selection.render()) <= 1202


def test_stage_transition_entry_is_rendered_as_domain_state() -> None:
    history = [
        {
            "kind": "stage_transition",
            "turn": 1,
            "revision": 1,
            "request_id": "stage-1",
            "status": "completed",
            "domain": {
                "parking": {
                    "current_stage": "ENTRY",
                    "completed_stages": ["TARGET_BINDING", "APPROACH"],
                    "target": {"bay_id": "bay03", "slot_node_id": "park_slot"},
                }
            },
        }
    ]
    selection = select_context(
        _context(turn=1, revision=1, history=history),
        request_revision=1,
    )
    entry = selection.to_metadata()["selected_entries"][0]
    assert entry["kind"] == "stage_transition"
    assert entry["verified"] is True
    block = selection.render()
    assert "domain/阶段状态" in block
    assert "current_stage=ENTRY" in block
    assert "completed_stages=['TARGET_BINDING', 'APPROACH']" in block
    assert "目标=bay03" in block


def test_compose_keeps_current_instruction_first_and_marks_priority() -> None:
    selection = select_context(_context(), request_revision=2)
    prompt = compose_prompt("CURRENT INSTRUCTION", selection)
    assert prompt.startswith("CURRENT INSTRUCTION")
    assert prompt.index("Kernel 持久上下文") > prompt.index("CURRENT INSTRUCTION")
    assert "当前图像和用户指令中的当前车辆状态优先" in prompt


def test_current_domain_is_part_of_the_rendered_task() -> None:
    selection = select_context(
        _context(turn=0, revision=0, history=[]),
        request_revision=0,
        current_domain={
            "target": "blue car",
            "target_kind": "车辆",
            "route_goal_node_id": "c_goal",
            "round": 3,
        },
    )
    block = selection.render()
    assert "目标 blue car（车辆）" in block
    assert "路线目标节点 c_goal" in block
    assert "已完成执行 0 次" in block
