"""Offline end-to-end integration tests for the synthetic planner + LTM demo."""

from __future__ import annotations

import json

from vln.planning_ltm import PhysicalArrival
from vln.planning_ltm.demo import build_demo, main


def test_build_demo_runs_the_full_offline_data_flow() -> None:
    payload = build_demo()

    assert payload["simulation_only"] is True
    assert payload["demo"] == "NAV-16-PLANNER-LTM-IMPL"
    assert len(payload["scenarios"]) == 3
    assert payload["not_verified"]

    obstacle, history, conflict = payload["scenarios"]

    assert obstacle["scene_id"] == "SYN-OBSTACLE-01"
    assert obstacle["target_id"] == "P1"
    assert obstacle["candidate_generation"]["candidate_count"] == 3
    assert obstacle["candidate_generation"]["sufficient"] is True
    blocked = [
        evaluation
        for evaluation in obstacle["base_mode"]["evaluations"]
        if "A2" in evaluation["node_ids"]
    ]
    assert len(blocked) == 1
    assert blocked[0]["feasibility"] == "infeasible"
    assert any(
        violation["code"] == "blocked-node"
        for violation in blocked[0]["rejection_reasons"]
    )
    assert obstacle["ltm_effect"]["changed_selection"] is False

    assert history["scene_id"] == "SYN-HISTORY-02"
    assert history["target_id"] == "P2"
    assert history["ltm_effect"]["changed_selection"] is True
    assert (
        history["ltm_effect"]["base_selected_candidate_id"]
        != history["ltm_effect"]["ltm_selected_candidate_id"]
    )
    assert history["ltm_effect"]["applied_memory_ids"]

    assert conflict["scene_id"] == "SYN-CONFLICT-03"
    assert conflict["target_id"] == "P1"
    assert conflict["ltm_effect"]["changed_selection"] is False
    assert conflict["ltm_mode"]["selected_candidate_id"] is not None
    conflict_selected = next(
        evaluation
        for evaluation in conflict["ltm_mode"]["evaluations"]
        if evaluation["candidate_id"] == conflict["ltm_mode"]["selected_candidate_id"]
    )
    assert "A2" not in conflict_selected["node_ids"]

    for scenario in payload["scenarios"]:
        execution = scenario["simulated_execution"]
        assert execution is not None
        assert execution["execution_mode"] == "simulated"
        assert execution["physical_arrival"] == PhysicalArrival.UNKNOWN
        assert execution["succeeded"] is True
        assert scenario["memory_update"] is not None
        assert scenario["memory_update"]["kind"] == "execution_experience"
        assert (
            scenario["memory_update"]["physical_arrival"]
            == PhysicalArrival.UNKNOWN
        )

    persistence = payload["ltm_persistence"]
    assert persistence["reopened_record_count"] == 7
    assert persistence["seeded_memory_ids"] == [
        "mem-0001",
        "mem-0002",
        "mem-0003",
        "mem-0004",
    ]
    assert persistence["execution_memory_ids"] == [
        "mem-0001",
        "mem-0002",
        "mem-0005",
        "mem-0006",
        "mem-0007",
    ]
    assert persistence["simulated_physical_arrival_values"] == ["unknown"]
    assert persistence["all_simulated_executions_have_unknown_arrival"] is True


def test_demo_cli_prints_parseable_json(capsys: object) -> None:
    exit_code = main(["--indent", "0"])
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["simulation_only"] is True
    assert len(payload["scenarios"]) == 3
    assert "real parking or physical arrival" in payload["not_verified"]
