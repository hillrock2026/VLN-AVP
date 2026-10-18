"""Data models for the standalone candidate-route planner and LTM prototype.

Everything here is offline and simulation-oriented. In particular:

* a :class:`ParkingTopology` is a small explicit graph, not a map frame;
* a :class:`RouteCandidate` is a proposal that may be infeasible - feasibility
  and rejection reasons live in :class:`CandidateEvaluation`, so rejected
  candidates are retained rather than silently filtered away;
* an :class:`ExecutionResult` distinguishes *simulated* execution from *real*
  feedback and keeps physical arrival as a separate, explicit fact. A simulated
  success can never claim physical arrival.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .errors import (
    ExecutionValidationError,
    PlanningValidationError,
    SceneValidationError,
    TopologyValidationError,
)

__all__ = [
    "TopologyNode",
    "TopologyEdge",
    "ParkingTopology",
    "Bounds",
    "ParkingScene",
    "RouteCandidate",
    "CandidateSet",
    "ViolationCode",
    "ConstraintViolation",
    "RouteCost",
    "MemoryApplication",
    "IgnoredMemory",
    "CandidateEvaluation",
    "SelectionResult",
    "PlanningResult",
    "ExecutionMode",
    "ExecutionOutcome",
    "PhysicalArrival",
    "ExecutionResult",
]


TURN_ANGLE_THRESHOLD_RAD = math.radians(30.0)


def _require_non_blank(value: object, name: str, error: type[Exception]) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise error(f"{name} must be a non-blank str")
    return value


def _require_finite(value: object, name: str, error: type[Exception]) -> float:
    if type(value) is not int and type(value) is not float:
        raise error(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise error(f"{name} must be finite")
    return number


def _as_tuple(value: object, name: str, error: type[Exception]) -> tuple[Any, ...]:
    if isinstance(value, str) or not isinstance(value, (tuple, list)):
        raise error(f"{name} must be a tuple or list")
    return tuple(value)


class ExecutionMode:
    """How an execution result was produced."""

    SIMULATED = "simulated"
    REAL = "real"
    ALL = frozenset({SIMULATED, REAL})


class ExecutionOutcome:
    """Outcome vocabulary kept separate from physical arrival."""

    SIMULATED_SUCCESS = "simulated-success"
    SIMULATED_FAILURE = "simulated-failure"
    REAL_SUCCESS = "real-success"
    REAL_FAILURE = "real-failure"
    ALL = frozenset(
        {SIMULATED_SUCCESS, SIMULATED_FAILURE, REAL_SUCCESS, REAL_FAILURE}
    )


class PhysicalArrival:
    """Whether a vehicle physically arrived; never inferred from software."""

    UNKNOWN = "unknown"
    CONFIRMED = "confirmed"
    NOT_CONFIRMED = "not-confirmed"
    ALL = frozenset({UNKNOWN, CONFIRMED, NOT_CONFIRMED})


@dataclass(frozen=True)
class TopologyNode:
    """One waypoint / parking node in metres.

    ``target_id`` is only set on nodes that represent a parking target. The
    coordinate frame is synthetic and local to this prototype; it is not the
    unresolved map frame of the production navigation chain.
    """

    node_id: str
    x: float
    y: float
    kind: str = "waypoint"
    target_id: str | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.node_id, "node_id", TopologyValidationError)
        object.__setattr__(
            self, "x", _require_finite(self.x, "node.x", TopologyValidationError)
        )
        object.__setattr__(
            self, "y", _require_finite(self.y, "node.y", TopologyValidationError)
        )
        _require_non_blank(self.kind, "node.kind", TopologyValidationError)
        if self.target_id is not None:
            _require_non_blank(self.target_id, "node.target_id", TopologyValidationError)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "x": self.x,
            "y": self.y,
            "kind": self.kind,
            "target_id": self.target_id,
        }

    @classmethod
    def from_dict(cls, data: object) -> "TopologyNode":
        if not isinstance(data, Mapping):
            raise TopologyValidationError("node must be a JSON object")
        try:
            return cls(
                node_id=data["node_id"],
                x=data["x"],
                y=data["y"],
                kind=data.get("kind", "waypoint"),
                target_id=data.get("target_id"),
            )
        except KeyError as exc:
            raise TopologyValidationError(f"node is missing field {exc.args[0]!r}") from exc


@dataclass(frozen=True)
class TopologyEdge:
    """One undirected drivable connection between two nodes."""

    edge_id: str
    start_node_id: str
    end_node_id: str
    risk: float = 0.0

    def __post_init__(self) -> None:
        _require_non_blank(self.edge_id, "edge_id", TopologyValidationError)
        _require_non_blank(self.start_node_id, "edge.start_node_id", TopologyValidationError)
        _require_non_blank(self.end_node_id, "edge.end_node_id", TopologyValidationError)
        if self.start_node_id == self.end_node_id:
            raise TopologyValidationError(f"edge {self.edge_id!r} is a self-loop")
        risk = _require_finite(self.risk, "edge.risk", TopologyValidationError)
        if risk < 0.0 or risk > 1.0:
            raise TopologyValidationError("edge.risk must be in [0, 1]")
        object.__setattr__(self, "risk", risk)

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "start_node_id": self.start_node_id,
            "end_node_id": self.end_node_id,
            "risk": self.risk,
        }

    @classmethod
    def from_dict(cls, data: object) -> "TopologyEdge":
        if not isinstance(data, Mapping):
            raise TopologyValidationError("edge must be a JSON object")
        try:
            return cls(
                edge_id=data["edge_id"],
                start_node_id=data["start_node_id"],
                end_node_id=data["end_node_id"],
                risk=data.get("risk", 0.0),
            )
        except KeyError as exc:
            raise TopologyValidationError(f"edge is missing field {exc.args[0]!r}") from exc


@dataclass(frozen=True)
class ParkingTopology:
    """A small, explicit undirected graph used for deterministic path search.

    Parallel edges between the same pair of nodes are rejected so that
    ``edge_between`` is unambiguous and route generation is deterministic.
    """

    nodes: tuple[TopologyNode, ...]
    edges: tuple[TopologyEdge, ...]

    def __post_init__(self) -> None:
        nodes = tuple(self.nodes)
        edges = tuple(self.edges)
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)

        node_index: dict[str, TopologyNode] = {}
        for node in nodes:
            if not isinstance(node, TopologyNode):
                raise TopologyValidationError("topology.nodes must contain TopologyNode")
            if node.node_id in node_index:
                raise TopologyValidationError(f"duplicate node id {node.node_id!r}")
            node_index[node.node_id] = node
        if not node_index:
            raise TopologyValidationError("topology must contain at least one node")

        edge_index: dict[str, TopologyEdge] = {}
        pair_index: dict[tuple[str, str], TopologyEdge] = {}
        adjacency: dict[str, list[tuple[str, str]]] = {
            node_id: [] for node_id in node_index
        }
        for edge in edges:
            if not isinstance(edge, TopologyEdge):
                raise TopologyValidationError("topology.edges must contain TopologyEdge")
            if edge.edge_id in edge_index:
                raise TopologyValidationError(f"duplicate edge id {edge.edge_id!r}")
            if edge.start_node_id not in node_index:
                raise TopologyValidationError(
                    f"edge {edge.edge_id!r} references unknown node "
                    f"{edge.start_node_id!r}"
                )
            if edge.end_node_id not in node_index:
                raise TopologyValidationError(
                    f"edge {edge.edge_id!r} references unknown node "
                    f"{edge.end_node_id!r}"
                )
            pair = tuple(sorted((edge.start_node_id, edge.end_node_id)))
            if pair in pair_index:
                raise TopologyValidationError(
                    f"parallel edges between {pair[0]!r} and {pair[1]!r}"
                )
            length = math.dist(
                (
                    node_index[edge.start_node_id].x,
                    node_index[edge.start_node_id].y,
                ),
                (node_index[edge.end_node_id].x, node_index[edge.end_node_id].y),
            )
            if length <= 0.0:
                raise TopologyValidationError(
                    f"edge {edge.edge_id!r} has zero geometric length"
                )
            edge_index[edge.edge_id] = edge
            pair_index[pair] = edge
            adjacency[edge.start_node_id].append((edge.end_node_id, edge.edge_id))
            adjacency[edge.end_node_id].append((edge.start_node_id, edge.edge_id))

        for entries in adjacency.values():
            entries.sort()
        object.__setattr__(self, "_node_index", MappingProxyType(node_index))
        object.__setattr__(self, "_edge_index", MappingProxyType(edge_index))
        object.__setattr__(self, "_pair_index", MappingProxyType(pair_index))
        object.__setattr__(
            self,
            "_adjacency",
            MappingProxyType(
                {node_id: tuple(entries) for node_id, entries in adjacency.items()}
            ),
        )

    # -- queries ---------------------------------------------------------

    def node(self, node_id: str) -> TopologyNode:
        node = self._node_index.get(node_id)
        if node is None:
            raise TopologyValidationError(f"unknown node {node_id!r}")
        return node

    def edge(self, edge_id: str) -> TopologyEdge:
        edge = self._edge_index.get(edge_id)
        if edge is None:
            raise TopologyValidationError(f"unknown edge {edge_id!r}")
        return edge

    def edge_between(self, first: str, second: str) -> TopologyEdge | None:
        return self._pair_index.get(tuple(sorted((first, second))))

    def neighbors(self, node_id: str) -> tuple[tuple[str, str], ...]:
        entries = self._adjacency.get(node_id)
        if entries is None:
            raise TopologyValidationError(f"unknown node {node_id!r}")
        return entries

    def target_node(self, target_id: str) -> TopologyNode:
        matches = [node for node in self.nodes if node.target_id == target_id]
        if not matches:
            raise TopologyValidationError(f"no node represents target {target_id!r}")
        if len(matches) > 1:
            raise TopologyValidationError(f"target {target_id!r} is represented twice")
        return matches[0]

    def edge_length(self, edge_id: str) -> float:
        edge = self.edge(edge_id)
        start = self.node(edge.start_node_id)
        end = self.node(edge.end_node_id)
        return math.dist((start.x, start.y), (end.x, end.y))

    def route_length(self, node_ids: tuple[str, ...]) -> float:
        if len(node_ids) < 2:
            return 0.0
        total = 0.0
        for first, second in zip(node_ids, node_ids[1:]):
            edge = self.edge_between(first, second)
            if edge is None:
                raise TopologyValidationError(
                    f"route is not connected: {first!r} -> {second!r}"
                )
            total += self.edge_length(edge.edge_id)
        return total

    def route_turn_count(self, node_ids: tuple[str, ...]) -> int:
        """Count heading changes larger than the declared 30-degree threshold."""

        if len(node_ids) < 3:
            return 0
        headings: list[float] = []
        for first, second in zip(node_ids, node_ids[1:]):
            start = self.node(first)
            end = self.node(second)
            headings.append(math.atan2(end.y - start.y, end.x - start.x))
        turns = 0
        for previous, current in zip(headings, headings[1:]):
            delta = (current - previous + math.pi) % (2.0 * math.pi) - math.pi
            if abs(delta) > TURN_ANGLE_THRESHOLD_RAD:
                turns += 1
        return turns

    @staticmethod
    def route_key(node_ids: tuple[str, ...]) -> str:
        return ">".join(node_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }

    @classmethod
    def from_dict(cls, data: object) -> "ParkingTopology":
        if not isinstance(data, Mapping):
            raise TopologyValidationError("topology must be a JSON object")
        nodes = data.get("nodes")
        edges = data.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise TopologyValidationError("topology must contain nodes[] and edges[]")
        return cls(
            nodes=tuple(TopologyNode.from_dict(item) for item in nodes),
            edges=tuple(TopologyEdge.from_dict(item) for item in edges),
        )


@dataclass(frozen=True)
class Bounds:
    """Axis-aligned allowed area in the synthetic local frame."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def __post_init__(self) -> None:
        min_x = _require_finite(self.min_x, "bounds.min_x", PlanningValidationError)
        min_y = _require_finite(self.min_y, "bounds.min_y", PlanningValidationError)
        max_x = _require_finite(self.max_x, "bounds.max_x", PlanningValidationError)
        max_y = _require_finite(self.max_y, "bounds.max_y", PlanningValidationError)
        if min_x >= max_x or min_y >= max_y:
            raise PlanningValidationError("bounds must satisfy min < max on both axes")
        object.__setattr__(self, "min_x", min_x)
        object.__setattr__(self, "min_y", min_y)
        object.__setattr__(self, "max_x", max_x)
        object.__setattr__(self, "max_y", max_y)

    def contains(self, x: float, y: float) -> bool:
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y

    def to_dict(self) -> dict[str, float]:
        return {
            "min_x": self.min_x,
            "min_y": self.min_y,
            "max_x": self.max_x,
            "max_y": self.max_y,
        }


@dataclass(frozen=True)
class ParkingScene:
    """A synthetic parking scene: topology + start/target + current constraints.

    ``blocked_node_ids`` and ``blocked_edge_ids`` are *current scene evidence*.
    Candidate generation deliberately ignores them so that an obstructed route
    appears in the candidate list and is rejected with a reason by the hard
    constraint checker. LTM can never override those rejections.
    """

    scene_id: str
    topology: ParkingTopology
    start_node_id: str
    target_node_id: str
    target_id: str
    blocked_node_ids: frozenset[str] = frozenset()
    blocked_edge_ids: frozenset[str] = frozenset()
    allowed_bounds: Bounds | None = None
    max_length_m: float | None = None
    max_turn_count: int | None = None
    description: str = ""

    def __post_init__(self) -> None:
        _require_non_blank(self.scene_id, "scene_id", SceneValidationError)
        if not isinstance(self.topology, ParkingTopology):
            raise SceneValidationError("scene.topology must be a ParkingTopology")
        _require_non_blank(self.start_node_id, "scene.start_node_id", SceneValidationError)
        _require_non_blank(self.target_node_id, "scene.target_node_id", SceneValidationError)
        _require_non_blank(self.target_id, "scene.target_id", SceneValidationError)
        object.__setattr__(self, "blocked_node_ids", frozenset(self.blocked_node_ids))
        object.__setattr__(self, "blocked_edge_ids", frozenset(self.blocked_edge_ids))

        start = self.topology.node(self.start_node_id)
        target = self.topology.node(self.target_node_id)
        if start.node_id == target.node_id:
            raise SceneValidationError("start and target nodes must differ")
        if target.target_id != self.target_id:
            raise SceneValidationError(
                f"target node {target.node_id!r} represents {target.target_id!r}, "
                f"not {self.target_id!r}"
            )
        for node_id in self.blocked_node_ids:
            self.topology.node(node_id)
        for edge_id in self.blocked_edge_ids:
            self.topology.edge(edge_id)

        if self.allowed_bounds is not None and not isinstance(self.allowed_bounds, Bounds):
            raise SceneValidationError("scene.allowed_bounds must be a Bounds or None")
        if self.max_length_m is not None:
            object.__setattr__(
                self,
                "max_length_m",
                _require_finite(self.max_length_m, "scene.max_length_m", SceneValidationError),
            )
            if self.max_length_m <= 0.0:
                raise SceneValidationError("scene.max_length_m must be positive")
        if self.max_turn_count is not None:
            if type(self.max_turn_count) is not int or self.max_turn_count < 0:
                raise SceneValidationError("scene.max_turn_count must be an int >= 0")

    def evidence(self) -> dict[str, Any]:
        """Current scene evidence used by a decision (no history)."""

        return {
            "scene_id": self.scene_id,
            "start_node_id": self.start_node_id,
            "target_node_id": self.target_node_id,
            "target_id": self.target_id,
            "blocked_node_ids": sorted(self.blocked_node_ids),
            "blocked_edge_ids": sorted(self.blocked_edge_ids),
            "allowed_bounds": (
                None if self.allowed_bounds is None else self.allowed_bounds.to_dict()
            ),
            "max_length_m": self.max_length_m,
            "max_turn_count": self.max_turn_count,
        }


@dataclass(frozen=True)
class RouteCandidate:
    """One generated route proposal, before hard-constraint evaluation."""

    candidate_id: str
    target_id: str
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    length_m: float

    def __post_init__(self) -> None:
        _require_non_blank(self.candidate_id, "candidate_id", PlanningValidationError)
        _require_non_blank(self.target_id, "candidate.target_id", PlanningValidationError)
        node_ids = _as_tuple(self.node_ids, "candidate.node_ids", PlanningValidationError)
        edge_ids = _as_tuple(self.edge_ids, "candidate.edge_ids", PlanningValidationError)
        if len(node_ids) < 2:
            raise PlanningValidationError("candidate must contain at least two nodes")
        if len(edge_ids) != len(node_ids) - 1:
            raise PlanningValidationError(
                "candidate.edge_ids must contain one edge per node transition"
            )
        for node_id in node_ids:
            _require_non_blank(node_id, "candidate.node_ids[]", PlanningValidationError)
        for edge_id in edge_ids:
            _require_non_blank(edge_id, "candidate.edge_ids[]", PlanningValidationError)
        length_m = _require_finite(
            self.length_m, "candidate.length_m", PlanningValidationError
        )
        if length_m < 0.0:
            raise PlanningValidationError("candidate.length_m must be >= 0")
        object.__setattr__(self, "node_ids", node_ids)
        object.__setattr__(self, "edge_ids", edge_ids)
        object.__setattr__(self, "length_m", length_m)

    @property
    def route_key(self) -> str:
        return ParkingTopology.route_key(self.node_ids)

    @property
    def start_node_id(self) -> str:
        return self.node_ids[0]

    @property
    def end_node_id(self) -> str:
        return self.node_ids[-1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "target_id": self.target_id,
            "route_key": self.route_key,
            "node_ids": list(self.node_ids),
            "edge_ids": list(self.edge_ids),
            "length_m": self.length_m,
        }


@dataclass(frozen=True)
class CandidateSet:
    """The generated candidates plus an explicit insufficient-candidates flag."""

    scene_id: str
    target_id: str
    requested_count: int
    candidates: tuple[RouteCandidate, ...]

    @property
    def sufficient(self) -> bool:
        return len(self.candidates) >= self.requested_count

    @property
    def insufficient_reason(self) -> str | None:
        if self.sufficient:
            return None
        return (
            f"topology yielded {len(self.candidates)} distinct route(s) to target "
            f"{self.target_id!r}, but {self.requested_count} were requested; "
            "no alternative routes were fabricated"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "target_id": self.target_id,
            "requested_count": self.requested_count,
            "candidate_count": len(self.candidates),
            "sufficient": self.sufficient,
            "insufficient_reason": self.insufficient_reason,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


class ViolationCode:
    """Stable codes for hard-constraint rejection reasons."""

    START_MISMATCH = "start-mismatch"
    TARGET_MISMATCH = "target-mismatch"
    TARGET_NODE_MISMATCH = "target-node-mismatch"
    UNKNOWN_NODE = "unknown-node"
    DISCONNECTED_ROUTE = "disconnected-route"
    EDGE_SEQUENCE_MISMATCH = "edge-sequence-mismatch"
    BLOCKED_NODE = "blocked-node"
    BLOCKED_EDGE = "blocked-edge"
    OUTSIDE_ALLOWED_AREA = "outside-allowed-area"
    LENGTH_MISMATCH = "length-mismatch"
    LENGTH_LIMIT = "length-limit"
    TURN_LIMIT = "turn-limit"
    NAVIGATION_DIRECTION_MISMATCH = "navigation-direction-mismatch"
    ALL = frozenset(
        {
            START_MISMATCH,
            TARGET_MISMATCH,
            TARGET_NODE_MISMATCH,
            UNKNOWN_NODE,
            DISCONNECTED_ROUTE,
            EDGE_SEQUENCE_MISMATCH,
            BLOCKED_NODE,
            BLOCKED_EDGE,
            OUTSIDE_ALLOWED_AREA,
            LENGTH_MISMATCH,
            LENGTH_LIMIT,
            TURN_LIMIT,
            NAVIGATION_DIRECTION_MISMATCH,
        }
    )


@dataclass(frozen=True)
class ConstraintViolation:
    code: str
    message: str

    def __post_init__(self) -> None:
        if self.code not in ViolationCode.ALL:
            raise PlanningValidationError(f"unknown violation code {self.code!r}")
        _require_non_blank(self.message, "violation.message", PlanningValidationError)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class RouteCost:
    """Cost components; **lower is better**.

    ``total == length_component + turn_component + risk_component +
    ltm_component`` and ``base_total`` excludes only the LTM component.
    """

    length_component: float
    turn_component: float
    risk_component: float
    ltm_component: float
    total: float
    turn_count: int
    risk_sum: float

    @property
    def base_total(self) -> float:
        return self.total - self.ltm_component

    def to_dict(self) -> dict[str, Any]:
        return {
            "length_component": self.length_component,
            "turn_component": self.turn_component,
            "risk_component": self.risk_component,
            "ltm_component": self.ltm_component,
            "base_total": self.base_total,
            "total": self.total,
            "turn_count": self.turn_count,
            "risk_sum": self.risk_sum,
        }


@dataclass(frozen=True)
class MemoryApplication:
    """One LTM record that changed (or was consulted for) a candidate cost."""

    memory_id: str
    candidate_id: str
    effect: str
    confidence: float
    adjustment: float
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "candidate_id": self.candidate_id,
            "effect": self.effect,
            "confidence": self.confidence,
            "adjustment": self.adjustment,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class IgnoredMemory:
    """A memory record that was not applied, with an explicit reason."""

    memory_id: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"memory_id": self.memory_id, "reason": self.reason}


@dataclass(frozen=True)
class CandidateEvaluation:
    """A retained candidate plus its feasibility, cost and LTM evidence."""

    candidate: RouteCandidate
    violations: tuple[ConstraintViolation, ...]
    cost: RouteCost | None
    ltm_applications: tuple[MemoryApplication, ...] = ()

    def __post_init__(self) -> None:
        if self.violations and self.cost is not None:
            raise PlanningValidationError(
                "an infeasible candidate must not carry a cost"
            )
        if not self.violations and self.cost is None:
            raise PlanningValidationError(
                "a feasible candidate must carry a cost"
            )

    @property
    def candidate_id(self) -> str:
        return self.candidate.candidate_id

    @property
    def target_id(self) -> str:
        return self.candidate.target_id

    @property
    def feasible(self) -> bool:
        return not self.violations

    @property
    def feasibility(self) -> str:
        return "feasible" if self.feasible else "infeasible"

    @property
    def rejection_reason(self) -> str | None:
        if self.feasible:
            return None
        return "; ".join(violation.message for violation in self.violations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "target_id": self.target_id,
            "route_key": self.candidate.route_key,
            "node_ids": list(self.candidate.node_ids),
            "edge_ids": list(self.candidate.edge_ids),
            "length_m": self.candidate.length_m,
            "feasibility": self.feasibility,
            "rejection_reasons": [
                violation.to_dict() for violation in self.violations
            ],
            "rejection_reason": self.rejection_reason,
            "cost": None if self.cost is None else self.cost.to_dict(),
            "ltm_applications": [
                application.to_dict() for application in self.ltm_applications
            ],
        }


@dataclass(frozen=True)
class SelectionResult:
    """A fully traceable decision over one candidate set."""

    scene_id: str
    target_id: str
    mode: str
    evaluations: tuple[CandidateEvaluation, ...]
    selected_candidate_id: str | None
    base_selected_candidate_id: str | None
    ltm_changed_selection: bool
    selection_reason: str
    applied_memories: tuple[MemoryApplication, ...]
    ignored_memories: tuple[IgnoredMemory, ...]
    scene_evidence: Mapping[str, Any]
    no_solution_reason: str | None = None

    def selected_evaluation(self) -> CandidateEvaluation | None:
        if self.selected_candidate_id is None:
            return None
        for evaluation in self.evaluations:
            if evaluation.candidate_id == self.selected_candidate_id:
                return evaluation
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "target_id": self.target_id,
            "mode": self.mode,
            "selected_candidate_id": self.selected_candidate_id,
            "base_selected_candidate_id": self.base_selected_candidate_id,
            "ltm_changed_selection": self.ltm_changed_selection,
            "selection_reason": self.selection_reason,
            "no_solution_reason": self.no_solution_reason,
            "scene_evidence": dict(self.scene_evidence),
            "evaluations": [evaluation.to_dict() for evaluation in self.evaluations],
            "applied_memories": [
                application.to_dict() for application in self.applied_memories
            ],
            "ignored_memories": [
                memory.to_dict() for memory in self.ignored_memories
            ],
        }


@dataclass(frozen=True)
class PlanningResult:
    scene_id: str
    target_id: str
    mode: str
    candidate_set: CandidateSet
    selection: SelectionResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "target_id": self.target_id,
            "mode": self.mode,
            "candidate_generation": self.candidate_set.to_dict(),
            "selection": self.selection.to_dict(),
        }


@dataclass(frozen=True)
class ExecutionResult:
    """A simulated or real execution outcome.

    A simulated result is *always* ``physical_arrival == "unknown"``; claiming
    otherwise is rejected at construction time. Real feedback must state its
    physical arrival explicitly.
    """

    execution_id: str
    scene_id: str
    target_id: str
    candidate_id: str
    route_key: str
    execution_mode: str
    outcome: str
    physical_arrival: str = PhysicalArrival.UNKNOWN
    note: str = ""

    def __post_init__(self) -> None:
        for name in (
            "execution_id",
            "scene_id",
            "target_id",
            "candidate_id",
            "route_key",
        ):
            _require_non_blank(
                getattr(self, name), f"execution.{name}", ExecutionValidationError
            )
        if self.execution_mode not in ExecutionMode.ALL:
            raise ExecutionValidationError(
                f"unknown execution_mode {self.execution_mode!r}"
            )
        if self.outcome not in ExecutionOutcome.ALL:
            raise ExecutionValidationError(f"unknown outcome {self.outcome!r}")
        if not self.outcome.startswith(self.execution_mode + "-"):
            raise ExecutionValidationError(
                f"outcome {self.outcome!r} does not belong to mode "
                f"{self.execution_mode!r}"
            )
        if self.physical_arrival not in PhysicalArrival.ALL:
            raise ExecutionValidationError(
                f"unknown physical_arrival {self.physical_arrival!r}"
            )
        if (
            self.execution_mode == ExecutionMode.SIMULATED
            and self.physical_arrival != PhysicalArrival.UNKNOWN
        ):
            raise ExecutionValidationError(
                "a simulated execution cannot claim physical arrival"
            )

    @property
    def succeeded(self) -> bool:
        return self.outcome in (
            ExecutionOutcome.SIMULATED_SUCCESS,
            ExecutionOutcome.REAL_SUCCESS,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "scene_id": self.scene_id,
            "target_id": self.target_id,
            "candidate_id": self.candidate_id,
            "route_key": self.route_key,
            "execution_mode": self.execution_mode,
            "outcome": self.outcome,
            "succeeded": self.succeeded,
            "physical_arrival": self.physical_arrival,
            "note": self.note,
        }
