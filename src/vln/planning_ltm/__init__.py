"""Standalone planning + long-term-memory prototype (offline, synthetic only).

This package is intentionally independent of the production navigation chain:
it does not import the VLM, STM, visual loop, AgentIntent, Host client or
Agent-Kernel. It demonstrates a traceable data flow:

synthetic scene -> deterministic candidates -> hard constraints -> explainable
cost -> base/LTM selection -> simulated execution -> LTM update.

Nothing here is evidence of real visual navigation, a safe vehicle trajectory or
physical parking. Vehicle kinematics, body collision and dynamic avoidance are
not implemented.
"""

from __future__ import annotations

from .constraints import check_hard_constraints
from .costs import DEFAULT_COST_WEIGHTS, CostWeights, compute_route_cost
from .demo import build_demo
from .errors import (
    CandidateGenerationError,
    ExecutionValidationError,
    MemoryValidationError,
    PlanningLtmError,
    PlanningValidationError,
    SceneValidationError,
    StoreCorruptionError,
    StoreError,
    StoreFormatError,
    TopologyValidationError,
)
from .execution import SimulatedExecutor, record_execution_experience
from .generation import generate_candidates
from .ltm import (
    EvidenceLevel,
    LongTermMemoryStore,
    MemoryEffect,
    MemoryKind,
    MemoryRecord,
)
from .models import (
    Bounds,
    CandidateEvaluation,
    CandidateSet,
    ConstraintViolation,
    ExecutionMode,
    ExecutionOutcome,
    ExecutionResult,
    IgnoredMemory,
    MemoryApplication,
    ParkingScene,
    ParkingTopology,
    PhysicalArrival,
    PlanningResult,
    RouteCandidate,
    RouteCost,
    SelectionResult,
    TopologyEdge,
    TopologyNode,
    ViolationCode,
)
from .scenarios import all_scenarios, scene_conflict, scene_history, scene_obstacle
from .selector import MODE_BASE, MODE_LTM, plan
from .topology_store import JsonTopologyStore

__all__ = [
    "Bounds",
    "CandidateEvaluation",
    "CandidateGenerationError",
    "CandidateSet",
    "ConstraintViolation",
    "CostWeights",
    "DEFAULT_COST_WEIGHTS",
    "EvidenceLevel",
    "ExecutionMode",
    "ExecutionOutcome",
    "ExecutionResult",
    "ExecutionValidationError",
    "IgnoredMemory",
    "JsonTopologyStore",
    "LongTermMemoryStore",
    "MODE_BASE",
    "MODE_LTM",
    "MemoryApplication",
    "MemoryEffect",
    "MemoryKind",
    "MemoryRecord",
    "MemoryValidationError",
    "ParkingScene",
    "ParkingTopology",
    "PhysicalArrival",
    "PlanningLtmError",
    "PlanningResult",
    "PlanningValidationError",
    "RouteCandidate",
    "RouteCost",
    "SceneValidationError",
    "SelectionResult",
    "SimulatedExecutor",
    "StoreCorruptionError",
    "StoreError",
    "StoreFormatError",
    "TopologyEdge",
    "TopologyNode",
    "TopologyValidationError",
    "ViolationCode",
    "all_scenarios",
    "build_demo",
    "check_hard_constraints",
    "compute_route_cost",
    "generate_candidates",
    "plan",
    "record_execution_experience",
    "scene_conflict",
    "scene_history",
    "scene_obstacle",
]
