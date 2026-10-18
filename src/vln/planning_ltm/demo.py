"""Deterministic offline demo: candidates -> constraints -> cost -> LTM -> sim.

Run from the repository root with ``PYTHONPATH=src python -m vln.planning_ltm``
(or ``python -m vln.planning_ltm`` after an editable install). It uses only
synthetic scenes, an in-process JSON LTM file in a temporary directory and a
simulated executor. No model, host, kernel or vehicle is contacted.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from .execution import SimulatedExecutor, record_execution_experience
from .ltm import LongTermMemoryStore, MemoryKind
from .models import ExecutionMode
from .scenarios import DEMO_AS_OF, all_scenarios, seed_histories
from .selector import MODE_BASE, MODE_LTM, plan

__all__ = ["build_demo", "main"]


def _memory_summary(record: Any) -> dict[str, Any]:
    return {
        "memory_id": record.memory_id,
        "kind": record.kind,
        "effect": record.effect,
        "evidence_level": record.evidence_level,
        "confidence": record.confidence,
        "route_key": record.route_key,
        "execution_id": record.execution_id,
        "execution_mode": record.execution_mode,
        "outcome": record.outcome,
        "physical_arrival": record.physical_arrival,
        "valid_until": record.valid_until,
        "invalidated_reason": record.invalidated_reason,
    }


def build_demo(*, as_of: str = DEMO_AS_OF) -> dict[str, Any]:
    """Run the complete offline pipeline and return a JSON-serialisable report."""

    with tempfile.TemporaryDirectory(prefix="vln-planning-ltm-") as temporary:
        path = Path(temporary) / "ltm.json"
        store = LongTermMemoryStore.create(path)
        seeds = seed_histories(store)

        scenarios: list[dict[str, Any]] = []
        for scene in all_scenarios():
            base = plan(scene, mode=MODE_BASE, as_of=as_of)
            ltm = plan(scene, mode=MODE_LTM, ltm_store=store, as_of=as_of)

            selected = ltm.selection.selected_evaluation()
            execution_payload: dict[str, Any] | None = None
            memory_update: dict[str, Any] | None = None
            if selected is not None:
                execution = SimulatedExecutor(success=True).execute(
                    scene, selected.candidate
                )
                record = record_execution_experience(
                    store,
                    execution,
                    created_at=as_of,
                    confidence=0.8,
                    source="synthetic-simulation-demo",
                )
                execution_payload = execution.to_dict()
                memory_update = _memory_summary(record)

            scenarios.append(
                {
                    "scene_id": scene.scene_id,
                    "target_id": scene.target_id,
                    "description": scene.description,
                    "current_scene_evidence": base.selection.scene_evidence,
                    "candidate_generation": base.candidate_set.to_dict(),
                    "base_mode": base.selection.to_dict(),
                    "ltm_mode": ltm.selection.to_dict(),
                    "ltm_effect": {
                        "changed_selection": ltm.selection.ltm_changed_selection,
                        "base_selected_candidate_id": (
                            ltm.selection.base_selected_candidate_id
                        ),
                        "ltm_selected_candidate_id": (
                            ltm.selection.selected_candidate_id
                        ),
                        "reason": ltm.selection.selection_reason,
                        "applied_memory_ids": [
                            application.memory_id
                            for application in ltm.selection.applied_memories
                        ],
                    },
                    "simulated_execution": execution_payload,
                    "memory_update": memory_update,
                }
            )

        # Re-open from disk to make cross-instance persistence visible.
        reopened = LongTermMemoryStore.load(path)
        execution_records = [
            record
            for record in reopened.all()
            if record.kind == MemoryKind.EXECUTION_EXPERIENCE
        ]
        simulated_execution_records = [
            record
            for record in execution_records
            if record.execution_mode == ExecutionMode.SIMULATED
        ]
        persistence = {
            "reopened_record_count": len(reopened),
            "seeded_memory_ids": [record.memory_id for record in seeds],
            "execution_memory_ids": [
                record.memory_id for record in execution_records
            ],
            "simulated_execution_outcomes": sorted(
                {
                    record.outcome
                    for record in simulated_execution_records
                    if record.outcome is not None
                }
            ),
            "simulated_physical_arrival_values": sorted(
                {
                    record.physical_arrival
                    for record in simulated_execution_records
                }
            ),
            "all_simulated_executions_have_unknown_arrival": all(
                record.physical_arrival == "unknown"
                for record in simulated_execution_records
            ),
        }

    return {
        "demo": "NAV-16-PLANNER-LTM-IMPL",
        "simulation_only": True,
        "as_of": as_of,
        "note": (
            "Synthetic scenes and simulated execution only; no model, host, "
            "kernel, vehicle or real image is involved."
        ),
        "scenarios": scenarios,
        "ltm_persistence": persistence,
        "not_verified": [
            "real visual navigation",
            "real vehicle trajectory safety",
            "real parking or physical arrival",
            "vehicle kinematics, body collision, dynamic avoidance",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vln.planning_ltm",
        description=(
            "Run the offline synthetic candidate-route + LTM demo "
            "(no model/host/kernel/vehicle)."
        ),
    )
    parser.add_argument(
        "--as-of",
        default=DEMO_AS_OF,
        help=f"decision timestamp (default: {DEMO_AS_OF})",
    )
    parser.add_argument(
        "--indent", type=int, default=2, help="JSON indentation (default: 2)"
    )
    args = parser.parse_args(argv)
    payload = build_demo(as_of=args.as_of)
    print(json.dumps(payload, ensure_ascii=False, indent=args.indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
