"""Unit tests for LTM persistence, expiry/confidence rules, selection and sim."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from vln.planning_ltm import (
    EvidenceLevel,
    ExecutionMode,
    ExecutionOutcome,
    ExecutionResult,
    ExecutionValidationError,
    LongTermMemoryStore,
    MemoryEffect,
    MemoryKind,
    MemoryRecord,
    MemoryValidationError,
    PhysicalArrival,
    SimulatedExecutor,
    StoreCorruptionError,
    StoreFormatError,
    ViolationCode,
    plan,
    record_execution_experience,
)
from vln.planning_ltm.scenarios import (
    DEMO_AS_OF,
    scene_conflict,
    scene_history,
    scene_obstacle,
    seed_histories,
)


def _store(tmp_path: Path, name: str = "ltm.json") -> LongTermMemoryStore:
    return LongTermMemoryStore.create(tmp_path / name)


def _selected(result: object) -> object:
    return result.selection.selected_evaluation()  # type: ignore[attr-defined]


def test_store_persists_add_read_and_update_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "ltm.json"
    store = LongTermMemoryStore.create(path)
    added = store.add(
        kind=MemoryKind.CONFIRMED_FACT,
        statement="Synthetic fact for persistence test.",
        source="unit-test",
        confidence=0.9,
        evidence_level=EvidenceLevel.CONFIRMED,
        scene_id="SYN-HISTORY-02",
        target_id="P2",
    )
    assert added.memory_id == "mem-0001"

    loaded = LongTermMemoryStore.load(path)
    assert loaded.get("mem-0001").statement == added.statement
    updated = loaded.update(
        "mem-0001", confidence=0.6, invalidated_reason="superseded in unit test"
    )
    assert updated.memory_id == "mem-0001"
    assert updated.confidence == 0.6

    reloaded = LongTermMemoryStore.load(path)
    record = reloaded.get("mem-0001")
    assert record.confidence == 0.6
    assert record.invalidated_reason == "superseded in unit test"
    assert reloaded.query(scene_id="SYN-HISTORY-02", target_id="P2") == ()
    assert len(reloaded.query(include_inactive=True)) == 1


def test_corrupt_ltm_file_raises_and_is_not_reset(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    original = "{this is not json"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(StoreCorruptionError):
        LongTermMemoryStore.load(path)
    assert path.read_text(encoding="utf-8") == original


def test_incompatible_ltm_schema_raises_and_is_not_reset(tmp_path: Path) -> None:
    path = tmp_path / "future.json"
    original = json.dumps(
        {
            "schema_version": 999,
            "kind": "parking-ltm",
            "next_sequence": 1,
            "records": [],
        }
    )
    path.write_text(original, encoding="utf-8")

    with pytest.raises(StoreFormatError):
        LongTermMemoryStore.load(path)
    assert path.read_text(encoding="utf-8") == original


def test_history_can_change_selection_with_traceable_explanation(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    seeds = seed_histories(store)
    scene = scene_history()

    base = plan(scene, mode="base", as_of=DEMO_AS_OF)
    ltm = plan(scene, mode="ltm", ltm_store=store, as_of=DEMO_AS_OF)

    assert base.selection.selected_candidate_id == "cand-SYN-HISTORY-02-01"
    assert ltm.selection.selected_candidate_id == "cand-SYN-HISTORY-02-02"
    assert ltm.selection.base_selected_candidate_id == "cand-SYN-HISTORY-02-01"
    assert ltm.selection.ltm_changed_selection is True
    assert seeds[0].memory_id in ltm.selection.selection_reason
    assert any(
        application.memory_id == seeds[0].memory_id
        and application.candidate_id == "cand-SYN-HISTORY-02-01"
        for application in ltm.selection.applied_memories
    )

    direct = next(
        evaluation
        for evaluation in ltm.selection.evaluations
        if evaluation.candidate_id == "cand-SYN-HISTORY-02-01"
    )
    alternative = next(
        evaluation
        for evaluation in ltm.selection.evaluations
        if evaluation.candidate_id == "cand-SYN-HISTORY-02-02"
    )
    assert direct.cost is not None and alternative.cost is not None
    assert direct.cost.base_total == pytest.approx(30.0)
    assert direct.cost.ltm_component == pytest.approx(18.0)
    assert direct.cost.total == pytest.approx(48.0)
    assert alternative.cost.total == pytest.approx(42.0)
    # The seeded experience is scoped to the direct route only.
    assert alternative.ltm_applications == ()


def test_without_relevant_memory_ltm_mode_degrades_to_base(tmp_path: Path) -> None:
    store = _store(tmp_path)
    scene = scene_history()
    base = plan(scene, mode="base", as_of=DEMO_AS_OF)
    ltm = plan(scene, mode="ltm", ltm_store=store, as_of=DEMO_AS_OF)

    assert ltm.selection.selected_candidate_id == base.selection.selected_candidate_id
    assert ltm.selection.ltm_changed_selection is False
    assert ltm.selection.applied_memories == ()
    assert "degraded to base" in ltm.selection.selection_reason


def test_expired_and_low_confidence_records_do_not_dominate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    seeds = seed_histories(store)
    expired_id = seeds[2].memory_id
    low_confidence_id = seeds[3].memory_id
    blocked_success_id = seeds[1].memory_id
    scene = scene_conflict()

    result = plan(scene, mode="ltm", ltm_store=store, as_of=DEMO_AS_OF)

    assert result.selection.selected_candidate_id == "cand-SYN-CONFLICT-03-02"
    assert result.selection.ltm_changed_selection is False
    assert result.selection.applied_memories == ()

    ignored = {
        (item.memory_id, item.reason)
        for item in result.selection.ignored_memories
    }
    assert (expired_id, "expired: valid_until=2025-01-01T00:00:00Z") in ignored
    assert any(
        memory_id == low_confidence_id
        and reason.startswith("confidence-below-threshold")
        for memory_id, reason in ignored
    )
    # The old success on the now-blocked route is not applied either.
    assert (blocked_success_id, "candidate-infeasible") in ignored

    blocked = next(
        evaluation
        for evaluation in result.selection.evaluations
        if "A2" in evaluation.candidate.node_ids
    )
    assert blocked.feasible is False
    assert blocked.cost is None
    assert blocked.ltm_applications == ()
    assert ViolationCode.BLOCKED_NODE in {
        violation.code for violation in blocked.violations
    }


def test_invalidated_record_stops_influencing_selection(tmp_path: Path) -> None:
    store = _store(tmp_path)
    seeds = seed_histories(store)
    failure_id = seeds[0].memory_id
    store.update(failure_id, invalidated_reason="obsolete synthetic experience")

    result = plan(scene_history(), mode="ltm", ltm_store=store, as_of=DEMO_AS_OF)
    assert result.selection.selected_candidate_id == "cand-SYN-HISTORY-02-01"
    assert result.selection.ltm_changed_selection is False
    assert any(
        item.memory_id == failure_id
        and item.reason.startswith("invalidated:")
        for item in result.selection.ignored_memories
    )


def test_ltm_selection_is_deterministic(tmp_path: Path) -> None:
    store = _store(tmp_path)
    seed_histories(store)
    scene = scene_history()
    first = plan(scene, mode="ltm", ltm_store=store, as_of=DEMO_AS_OF)
    second = plan(scene, mode="ltm", ltm_store=store, as_of=DEMO_AS_OF)
    assert first.selection.to_dict() == second.selection.to_dict()


def test_simulated_success_never_creates_physical_arrival(tmp_path: Path) -> None:
    path = tmp_path / "ltm.json"
    store = LongTermMemoryStore.create(path)
    scene = scene_obstacle()
    result = plan(scene, mode="base", as_of=DEMO_AS_OF)
    selected = _selected(result)
    assert selected is not None

    execution = SimulatedExecutor(success=True).execute(scene, selected.candidate)
    assert execution.execution_mode == ExecutionMode.SIMULATED
    assert execution.outcome == ExecutionOutcome.SIMULATED_SUCCESS
    assert execution.physical_arrival == PhysicalArrival.UNKNOWN

    record = record_execution_experience(
        store, execution, created_at=DEMO_AS_OF, confidence=0.8
    )
    assert record.kind == MemoryKind.EXECUTION_EXPERIENCE
    assert record.outcome == ExecutionOutcome.SIMULATED_SUCCESS
    assert record.physical_arrival == PhysicalArrival.UNKNOWN
    assert record.effect == MemoryEffect.PREFER
    assert record.execution_id == execution.execution_id

    reloaded = LongTermMemoryStore.load(path)
    assert all(
        item.physical_arrival != PhysicalArrival.CONFIRMED
        for item in reloaded.all()
    )
    with pytest.raises(MemoryValidationError):
        replace(record, physical_arrival=PhysicalArrival.CONFIRMED)
    with pytest.raises(ExecutionValidationError):
        replace(
            execution,
            physical_arrival=PhysicalArrival.CONFIRMED,
        )


def test_execution_failure_is_recorded_as_failure_not_progress(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    scene = scene_history()
    result = plan(scene, mode="base", as_of=DEMO_AS_OF)
    selected = _selected(result)
    assert selected is not None

    execution = SimulatedExecutor(success=False).execute(scene, selected.candidate)
    assert execution.outcome == ExecutionOutcome.SIMULATED_FAILURE
    assert execution.succeeded is False
    assert execution.physical_arrival == PhysicalArrival.UNKNOWN

    record = record_execution_experience(store, execution, created_at=DEMO_AS_OF)
    assert record.outcome == ExecutionOutcome.SIMULATED_FAILURE
    assert record.effect == MemoryEffect.AVOID
    assert record.physical_arrival == PhysicalArrival.UNKNOWN
    assert record.route_key == selected.candidate.route_key
    assert record.execution_id == execution.execution_id
    assert "success" not in record.outcome

    with pytest.raises(ExecutionValidationError):
        ExecutionResult(
            execution_id="bad-failure",
            scene_id="SYN-HISTORY-02",
            target_id="P2",
            candidate_id="candidate",
            route_key="",
            execution_mode=ExecutionMode.SIMULATED,
            outcome=ExecutionOutcome.SIMULATED_FAILURE,
        )


def test_simulated_success_memory_cannot_claim_arrival() -> None:
    with pytest.raises(MemoryValidationError):
        MemoryRecord(
            memory_id="mem-9999",
            kind=MemoryKind.EXECUTION_EXPERIENCE,
            statement="invalid simulated arrival",
            source="unit-test",
            created_at="2026-10-17T00:00:00Z",
            updated_at="2026-10-17T00:00:00Z",
            confidence=0.9,
            evidence_level=EvidenceLevel.SIMULATED,
            effect=MemoryEffect.PREFER,
            route_key="S1>B1>B2>P1",
            execution_id="sim-invalid",
            execution_mode=ExecutionMode.SIMULATED,
            outcome=ExecutionOutcome.SIMULATED_SUCCESS,
            physical_arrival=PhysicalArrival.CONFIRMED,
        )
