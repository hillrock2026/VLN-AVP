"""Three hand-checkable synthetic parking scenes.

Coordinates are a local synthetic frame in metres. The graphs are deliberately
small so every route can be verified by hand:

1. ``SYN-OBSTACLE-01`` - three routes to ``P1``; the shortest passes through
   blocked node ``A2``.
2. ``SYN-HISTORY-02`` - three feasible routes to ``P2``; the shortest is the
   direct route, and a synthetic historical failure can make the planner prefer
   a parallel aisle.
3. ``SYN-CONFLICT-03`` - the same topology as scene 1 with current evidence
   blocking ``A2``; old "success" plus expired/low-confidence preferences for
   other routes must not override the blockage.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .execution import record_execution_experience
from .ltm import (
    EvidenceLevel,
    LongTermMemoryStore,
    MemoryEffect,
    MemoryKind,
    MemoryRecord,
)
from .models import (
    Bounds,
    ExecutionMode,
    ExecutionOutcome,
    ExecutionResult,
    ParkingScene,
    ParkingTopology,
    PhysicalArrival,
    TopologyEdge,
    TopologyNode,
)

__all__ = [
    "scene_obstacle",
    "scene_history",
    "scene_conflict",
    "all_scenarios",
    "seed_histories",
    "DEMO_AS_OF",
]


DEMO_AS_OF = "2026-10-17T00:00:00Z"


def _obstacle_topology() -> ParkingTopology:
    nodes = (
        TopologyNode("S1", 0.0, 0.0, kind="entrance"),
        TopologyNode("A1", 10.0, 0.0),
        TopologyNode("A2", 20.0, 0.0),
        TopologyNode("P1", 30.0, 0.0, kind="parking", target_id="P1"),
        TopologyNode("B1", 0.0, 10.0),
        TopologyNode("B2", 20.0, 10.0),
        TopologyNode("C1", 0.0, 20.0),
        TopologyNode("C2", 10.0, 20.0),
        TopologyNode("C3", 20.0, 20.0),
    )
    edges = (
        TopologyEdge("E-S1-A1", "S1", "A1"),
        TopologyEdge("E-A1-A2", "A1", "A2"),
        TopologyEdge("E-A2-P1", "A2", "P1"),
        TopologyEdge("E-S1-B1", "S1", "B1"),
        TopologyEdge("E-B1-B2", "B1", "B2"),
        TopologyEdge("E-B2-P1", "B2", "P1"),
        TopologyEdge("E-S1-C1", "S1", "C1"),
        TopologyEdge("E-C1-C2", "C1", "C2"),
        TopologyEdge("E-C2-C3", "C2", "C3"),
        TopologyEdge("E-C3-P1", "C3", "P1"),
    )
    return ParkingTopology(nodes=nodes, edges=edges)


def scene_obstacle() -> ParkingScene:
    """Scene 1: shortest route is blocked by current scene evidence."""

    return ParkingScene(
        scene_id="SYN-OBSTACLE-01",
        topology=_obstacle_topology(),
        start_node_id="S1",
        target_node_id="P1",
        target_id="P1",
        blocked_node_ids=frozenset({"A2"}),
        allowed_bounds=Bounds(-5.0, -5.0, 35.0, 25.0),
        description=(
            "Three routes to P1; the shortest (S1>A1>A2>P1) crosses blocked "
            "node A2 and must be rejected."
        ),
    )


def scene_history() -> ParkingScene:
    """Scene 2: direct route is shortest; a parallel aisle is the alternative."""

    nodes = (
        TopologyNode("S2", 0.0, 0.0, kind="entrance"),
        TopologyNode("X1", 15.0, 0.0),
        TopologyNode("P2", 30.0, 0.0, kind="parking", target_id="P2"),
        TopologyNode("Y1", 0.0, 4.0),
        TopologyNode("Y2", 15.0, 4.0),
        TopologyNode("Y3", 30.0, 4.0),
        TopologyNode("Z1", 0.0, -4.0),
        TopologyNode("Z2", 15.0, -4.0),
        TopologyNode("Z3", 30.0, -4.0),
    )
    edges = (
        TopologyEdge("E-S2-X1", "S2", "X1"),
        TopologyEdge("E-X1-P2", "X1", "P2"),
        TopologyEdge("E-S2-Y1", "S2", "Y1"),
        TopologyEdge("E-Y1-Y2", "Y1", "Y2"),
        TopologyEdge("E-Y2-Y3", "Y2", "Y3"),
        TopologyEdge("E-Y3-P2", "Y3", "P2"),
        TopologyEdge("E-S2-Z1", "S2", "Z1"),
        TopologyEdge("E-Z1-Z2", "Z1", "Z2"),
        TopologyEdge("E-Z2-Z3", "Z2", "Z3"),
        TopologyEdge("E-Z3-P2", "Z3", "P2"),
    )
    return ParkingScene(
        scene_id="SYN-HISTORY-02",
        topology=ParkingTopology(nodes=nodes, edges=edges),
        start_node_id="S2",
        target_node_id="P2",
        target_id="P2",
        allowed_bounds=Bounds(-5.0, -5.0, 35.0, 10.0),
        description=(
            "Three feasible routes to P2. The direct route S2>X1>P2 is shortest "
            "(30 m); both parallel aisles are 38 m with two turns."
        ),
    )


def scene_conflict() -> ParkingScene:
    """Scene 3: old history conflicts with current blocked-node evidence."""

    return ParkingScene(
        scene_id="SYN-CONFLICT-03",
        topology=_obstacle_topology(),
        start_node_id="S1",
        target_node_id="P1",
        target_id="P1",
        blocked_node_ids=frozenset({"A2"}),
        allowed_bounds=Bounds(-5.0, -5.0, 35.0, 25.0),
        max_length_m=80.0,
        max_turn_count=3,
        description=(
            "Current evidence blocks A2. A simulated historical success on the "
            "A2 route, an expired preference and a low-confidence claim must "
            "not override the current blockage."
        ),
    )


def all_scenarios() -> tuple[ParkingScene, ...]:
    return (scene_obstacle(), scene_history(), scene_conflict())


def seed_histories(store: LongTermMemoryStore) -> tuple[MemoryRecord, ...]:
    """Seed deterministic synthetic history used by the offline demo/tests.

    The seeded execution outcomes are *simulated*; none of them claims physical
    arrival or parking completion.
    """

    if not isinstance(store, LongTermMemoryStore):
        raise TypeError("store must be a LongTermMemoryStore")

    short_route_failure = ExecutionResult(
        execution_id="sim-history-02-short-failure",
        scene_id="SYN-HISTORY-02",
        target_id="P2",
        candidate_id="history-candidate-short",
        route_key="S2>X1>P2",
        execution_mode=ExecutionMode.SIMULATED,
        outcome=ExecutionOutcome.SIMULATED_FAILURE,
        physical_arrival=PhysicalArrival.UNKNOWN,
        note="Seeded synthetic history; no vehicle involved.",
    )
    blocked_route_success = ExecutionResult(
        execution_id="sim-history-03-blocked-route-success",
        scene_id="SYN-CONFLICT-03",
        target_id="P1",
        candidate_id="history-candidate-blocked",
        route_key="S1>A1>A2>P1",
        execution_mode=ExecutionMode.SIMULATED,
        outcome=ExecutionOutcome.SIMULATED_SUCCESS,
        physical_arrival=PhysicalArrival.UNKNOWN,
        note="Seeded synthetic history; the route is now blocked.",
    )

    records: list[MemoryRecord] = []
    records.append(
        record_execution_experience(
            store,
            short_route_failure,
            created_at="2026-09-01T00:00:00Z",
            confidence=0.9,
            source="synthetic-history",
        )
    )
    records.append(
        record_execution_experience(
            store,
            blocked_route_success,
            created_at="2026-09-02T00:00:00Z",
            confidence=0.95,
            source="synthetic-history",
        )
    )
    records.append(
        store.add(
            kind=MemoryKind.HISTORICAL_OBSERVATION,
            statement=(
                "Historical observation: the long west loop was uncongested in "
                "an earlier synthetic run."
            ),
            source="synthetic-history",
            confidence=0.99,
            evidence_level=EvidenceLevel.OBSERVED,
            effect=MemoryEffect.PREFER,
            scene_id="SYN-CONFLICT-03",
            target_id="P1",
            route_key="S1>C1>C2>C3>P1",
            node_ids=("S1", "C1", "C2", "C3", "P1"),
            valid_until="2025-01-01T00:00:00Z",
            created_at="2024-01-01T00:00:00Z",
        )
    )
    records.append(
        store.add(
            kind=MemoryKind.CONFIRMED_FACT,
            statement=(
                "Low-confidence claim only: the west loop is preferred. This "
                "must not be treated as confirmed."
            ),
            source="synthetic-rumor",
            confidence=0.2,
            evidence_level=EvidenceLevel.HYPOTHESIZED,
            effect=MemoryEffect.PREFER,
            scene_id="SYN-CONFLICT-03",
            target_id="P1",
            route_key="S1>C1>C2>C3>P1",
            node_ids=("S1", "C1", "C2", "C3", "P1"),
            created_at="2026-09-03T00:00:00Z",
        )
    )
    return tuple(records)


def demo_as_of() -> datetime:
    """The fixed decision time used by the demo (keeps output reproducible)."""

    return datetime(2026, 10, 17, tzinfo=timezone.utc)
