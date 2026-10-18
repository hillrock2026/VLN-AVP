"""Simulation-only execution and execution-experience memory updates."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ExecutionValidationError, MemoryValidationError
from .ltm import (
    EvidenceLevel,
    LongTermMemoryStore,
    MemoryEffect,
    MemoryKind,
    MemoryRecord,
)
from .models import (
    ExecutionMode,
    ExecutionOutcome,
    ExecutionResult,
    ParkingScene,
    PhysicalArrival,
    RouteCandidate,
)

__all__ = ["SimulatedExecutor", "record_execution_experience"]


@dataclass(frozen=True)
class SimulatedExecutor:
    """A deterministic stand-in for a vehicle.

    It performs no motion and contacts no host/kernel/vehicle. A successful run
    is recorded as ``simulated-success`` and always keeps ``physical_arrival``
    at ``unknown``.
    """

    success: bool = True

    def execute(
        self, scene: ParkingScene, candidate: RouteCandidate
    ) -> ExecutionResult:
        if not isinstance(scene, ParkingScene):
            raise ExecutionValidationError("scene must be a ParkingScene")
        if not isinstance(candidate, RouteCandidate):
            raise ExecutionValidationError("candidate must be a RouteCandidate")
        if candidate.target_id != scene.target_id:
            raise ExecutionValidationError(
                "candidate target does not match the scene target"
            )
        outcome = (
            ExecutionOutcome.SIMULATED_SUCCESS
            if self.success
            else ExecutionOutcome.SIMULATED_FAILURE
        )
        return ExecutionResult(
            execution_id=f"sim-{scene.scene_id}-{candidate.candidate_id}",
            scene_id=scene.scene_id,
            target_id=scene.target_id,
            candidate_id=candidate.candidate_id,
            route_key=candidate.route_key,
            execution_mode=ExecutionMode.SIMULATED,
            outcome=outcome,
            physical_arrival=PhysicalArrival.UNKNOWN,
            note=(
                "SIMULATION ONLY: no vehicle, no host, no kernel and no motion; "
                "physical arrival is unknown."
            ),
        )


def record_execution_experience(
    store: LongTermMemoryStore,
    execution: ExecutionResult,
    *,
    created_at: str | None = None,
    confidence: float = 0.8,
    valid_until: str | None = None,
    source: str | None = None,
) -> MemoryRecord:
    """Append one execution experience tied to a specific route and outcome.

    A failure can only be recorded when the result names the candidate and the
    route (enforced by :class:`ExecutionResult`). The experience is evidence of
    what the simulator/caller reported, not of physical arrival.
    """

    if not isinstance(store, LongTermMemoryStore):
        raise MemoryValidationError("store must be a LongTermMemoryStore")
    if not isinstance(execution, ExecutionResult):
        raise ExecutionValidationError("execution must be an ExecutionResult")

    effect = MemoryEffect.PREFER if execution.succeeded else MemoryEffect.AVOID
    evidence_level = (
        EvidenceLevel.SIMULATED
        if execution.execution_mode == ExecutionMode.SIMULATED
        else EvidenceLevel.OBSERVED
    )
    default_source = (
        "synthetic-simulation"
        if execution.execution_mode == ExecutionMode.SIMULATED
        else "caller-reported-execution"
    )
    statement = (
        f"{execution.execution_mode} execution {execution.outcome} for "
        f"candidate {execution.candidate_id} on route {execution.route_key}; "
        f"physical_arrival={execution.physical_arrival}. "
        "This is not evidence of a real vehicle arriving or parking."
    )
    return store.add(
        kind=MemoryKind.EXECUTION_EXPERIENCE,
        statement=statement,
        source=source or default_source,
        confidence=confidence,
        evidence_level=evidence_level,
        effect=effect,
        scene_id=execution.scene_id,
        target_id=execution.target_id,
        route_key=execution.route_key,
        node_ids=tuple(execution.route_key.split(">")),
        valid_until=valid_until,
        execution_id=execution.execution_id,
        execution_mode=execution.execution_mode,
        outcome=execution.outcome,
        physical_arrival=execution.physical_arrival,
        created_at=created_at,
    )
