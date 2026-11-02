"""The hand-verified UndergroundCarPark waypoint graph and A* search.

The CARLA map exposes no OpenDrive topology (``get_topology()`` is empty), so
the route used by 01B/01D is an explicit graph. This module is the single
source of that graph: the 01B script and the 01D arbitration layer both build
their view from here instead of keeping two copies of the same nodes.

The graph is undirected. Nodes are (x, y) metres in the CARLA world frame at
the validated floor (z = 5.80 m); edges are straight, traversable in both
directions, and weighted by Euclidean distance. Graph connectivity is not a
safety proof: the runnable scripts still probe floor height and forward
clearance before driving.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

__all__ = [
    "WaypointNode",
    "RouteGraph",
    "UNDERGROUND_CARPARK_NODES",
    "UNDERGROUND_CARPARK_EDGES",
    "UNDERGROUND_CARPARK_START_NODE",
    "UNDERGROUND_CARPARK_GOAL_NODE",
    "underground_carpark_graph",
]


def _finite(value: object, name: str) -> float:
    if type(value) is not int and type(value) is not float:
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
    return float(value)


def _checked_edge_points(
    raw_points: Iterable[Sequence[float]],
) -> tuple[tuple[float, float], ...]:
    try:
        points = tuple(raw_points)
    except TypeError:
        raise TypeError("an edge path must be an iterable of (x, y) points") from None
    if len(points) < 2:
        raise ValueError("an edge path needs at least two points")
    checked: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            raise ValueError("each edge path point must be an (x, y) pair")
        checked.append((_finite(point[0], "edge x"), _finite(point[1], "edge y")))
    return tuple(checked)


def _same_point(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= 1e-6


def _bearing(dx: float, dy: float) -> float:
    return math.atan2(dy, dx)


@dataclass(frozen=True)
class WaypointNode:
    """One drivable waypoint, identified by name and positioned in the map."""

    node_id: str
    x: float
    y: float

    def __post_init__(self) -> None:
        if type(self.node_id) is not str or self.node_id.strip() == "":
            raise ValueError("node_id must be a non-blank str")
        object.__setattr__(self, "x", _finite(self.x, "node.x"))
        object.__setattr__(self, "y", _finite(self.y, "node.y"))

    def to_metadata(self) -> dict:
        return {"node_id": self.node_id, "x": self.x, "y": self.y}


class RouteGraph:
    """A small undirected waypoint graph with deterministic A* search.

    Edges are straight by default.  ``edge_paths`` optionally supplies a
    densified polyline for an edge, so a curved lane can be represented
    without cutting the curve with a chord.  Decision bearings then use the
    polyline tangent while :meth:`points` returns the sampled lane points that
    the controller actually follows.
    """

    def __init__(
        self,
        nodes: Mapping[str, WaypointNode],
        edges: Iterable[tuple[str, str]],
        edge_paths: Mapping[tuple[str, str], Iterable[Sequence[float]]] | None = None,
        *,
        directed: bool = False,
    ) -> None:
        if not isinstance(nodes, Mapping) or not nodes:
            raise ValueError("nodes must be a non-empty mapping")
        checked: dict[str, WaypointNode] = {}
        for key, node in nodes.items():
            if not isinstance(node, WaypointNode):
                raise TypeError(f"node {key!r} must be a WaypointNode")
            if key != node.node_id:
                raise ValueError(
                    f"node key {key!r} does not match node_id {node.node_id!r}"
                )
            checked[key] = node
        self._directed = bool(directed)
        adjacency: dict[str, list[tuple[str, float]]] = {key: [] for key in checked}
        seen: set[tuple[str, str]] = set()
        edge_keys: set[tuple[str, str]] = set()
        directed_edges: list[tuple[str, str]] = []
        for edge in edges:
            if not isinstance(edge, (tuple, list)) or len(edge) != 2:
                raise ValueError("each edge must be a (from, to) pair")
            a, b = edge
            if a not in checked or b not in checked:
                raise ValueError(f"edge {a!r}->{b!r} names an unknown node")
            if a == b:
                raise ValueError(f"self edge {a!r}->{b!r} is not allowed")
            key = tuple(sorted((a, b)))
            if key in seen:
                raise ValueError(f"duplicate edge {a!r}->{b!r}")
            seen.add(key)
            edge_keys.add(key)
            directed_edges.append((a, b))
        supplied_paths = {} if edge_paths is None else edge_paths
        if not isinstance(supplied_paths, Mapping):
            raise TypeError("edge_paths must be a mapping or None")
        checked_paths: dict[tuple[str, str], tuple[tuple[float, float], ...]] = {}
        for key, raw_points in supplied_paths.items():
            if not isinstance(key, (tuple, list)) or len(key) != 2:
                raise ValueError("each edge_paths key must be a (from, to) pair")
            a, b = key
            if a not in checked or b not in checked or a == b:
                raise ValueError(f"edge path {a!r}->{b!r} names an invalid edge")
            sorted_key = tuple(sorted((a, b)))
            if sorted_key not in edge_keys:
                raise ValueError(f"edge path {a!r}->{b!r} has no matching edge")
            if sorted_key in checked_paths:
                raise ValueError(f"duplicate edge path {a!r}->{b!r}")
            points = _checked_edge_points(raw_points)
            start = (checked[a].x, checked[a].y)
            end = (checked[b].x, checked[b].y)
            if _same_point(points[0], start) and _same_point(points[-1], end):
                oriented = points
            elif _same_point(points[0], end) and _same_point(points[-1], start):
                oriented = tuple(reversed(points))
            else:
                raise ValueError(
                    f"edge path {a!r}->{b!r} endpoints do not match its nodes"
                )
            if sorted_key[0] == a:
                checked_paths[sorted_key] = oriented
            else:
                checked_paths[sorted_key] = tuple(reversed(oriented))
        for a, b in (directed_edges if self._directed else sorted(edge_keys)):
            path = checked_paths.get(tuple(sorted((a, b))))
            if path is None:
                distance = math.hypot(
                    checked[b].x - checked[a].x, checked[b].y - checked[a].y
                )
            else:
                distance = sum(
                    math.hypot(
                        path[index][0] - path[index - 1][0],
                        path[index][1] - path[index - 1][1],
                    )
                    for index in range(1, len(path))
                )
            adjacency[a].append((b, distance))
            if not self._directed:
                adjacency[b].append((a, distance))
        for neighbours in adjacency.values():
            neighbours.sort(key=lambda item: item[0])
        self._nodes = MappingProxyType(dict(checked))
        self._adjacency = MappingProxyType(
            {key: tuple(value) for key, value in adjacency.items()}
        )
        self._edge_paths = MappingProxyType(checked_paths)

    @property
    def nodes(self) -> Mapping[str, WaypointNode]:
        return self._nodes

    def has_node(self, node_id: object) -> bool:
        return type(node_id) is str and node_id in self._nodes

    def neighbours(self, node_id: str) -> tuple[tuple[str, float], ...]:
        try:
            return self._adjacency[node_id]
        except KeyError:
            raise KeyError(f"unknown node {node_id!r}") from None

    def predecessors(self, node_id: str) -> tuple[tuple[str, float], ...]:
        """Nodes with an executable edge into ``node_id``.

        For an undirected graph this is the same set as :meth:`neighbours`.
        A directed graph only reports true predecessor edges; this is what
        prevents a wrong branch from routing back through the fork.
        """

        if node_id not in self._adjacency:
            raise KeyError(f"unknown node {node_id!r}")
        if not self._directed:
            return self._adjacency[node_id]
        return tuple(
            (source, cost)
            for source, neighbours in self._adjacency.items()
            for target, cost in neighbours
            if target == node_id
        )

    def bearing(self, from_node_id: str, to_node_id: str) -> float:
        """Compass-style world bearing in radians, CCW-positive from +X."""

        try:
            a = self._nodes[from_node_id]
            b = self._nodes[to_node_id]
        except KeyError as exc:
            raise KeyError(f"unknown node {exc.args[0]!r}") from None
        return math.atan2(b.y - a.y, b.x - a.x)

    def edge_path(
        self, from_node_id: str, to_node_id: str
    ) -> tuple[tuple[float, float], ...]:
        """The sampled polyline for one edge, oriented from ``from`` to ``to``."""

        try:
            a = self._nodes[from_node_id]
            b = self._nodes[to_node_id]
        except KeyError as exc:
            raise KeyError(f"unknown node {exc.args[0]!r}") from None
        if to_node_id not in {name for name, _ in self._adjacency[from_node_id]}:
            raise KeyError(f"no edge {from_node_id!r}->{to_node_id!r}")
        key = tuple(sorted((from_node_id, to_node_id)))
        path = self._edge_paths.get(key)
        if path is None:
            return ((a.x, a.y), (b.x, b.y))
        return path if key[0] == from_node_id else tuple(reversed(path))

    def edge_start_bearing(self, from_node_id: str, to_node_id: str) -> float:
        """Tangent bearing at the start of an edge (or its chord if straight)."""

        path = self.edge_path(from_node_id, to_node_id)
        for index in range(1, len(path)):
            dx = path[index][0] - path[index - 1][0]
            dy = path[index][1] - path[index - 1][1]
            if math.hypot(dx, dy) > 1e-9:
                return _bearing(dx, dy)
        raise ValueError(f"edge {from_node_id!r}->{to_node_id!r} has no length")

    def edge_end_bearing(self, from_node_id: str, to_node_id: str) -> float:
        """Tangent bearing at the end of an edge.

        This is the branch direction used when an edge is a curved lane: the
        immediate tangent can still look straight at the junction mouth while
        the branch actually turns.
        """

        path = self.edge_path(from_node_id, to_node_id)
        for index in range(len(path) - 1, 0, -1):
            dx = path[index][0] - path[index - 1][0]
            dy = path[index][1] - path[index - 1][1]
            if math.hypot(dx, dy) > 1e-9:
                return _bearing(dx, dy)
        raise ValueError(f"edge {from_node_id!r}->{to_node_id!r} has no length")

    def astar(
        self,
        start: str,
        goal: str,
        *,
        excluded_edges: Iterable[Sequence[str]] | None = None,
        excluded_nodes: Iterable[str] | None = None,
    ) -> tuple[list[str] | None, str | None]:
        """Return ``(path, status)``; status is None, invalid_start,
        invalid_target or no_path.

        The heuristic is the Euclidean distance to the goal; the graph is small
        and edge weights satisfy the triangle inequality, so the result is an
        optimal path with deterministic tie-breaking by node id.

        ``excluded_edges`` removes undirected (a, b) pairs from this search
        only; the graph itself keeps them for other callers.  ``excluded_nodes``
        prunes nodes (e.g. a different declared parking target) from this
        search only.
        """

        if start not in self._nodes:
            return None, "invalid_start"
        if goal not in self._nodes:
            return None, "invalid_target"
        excluded: set[tuple[str, str]] = set()
        if excluded_edges is not None:
            for pair in excluded_edges:
                a, b = pair
                if a not in self._nodes or b not in self._nodes or a == b:
                    raise ValueError(
                        f"excluded edge {a!r}->{b!r} names invalid nodes"
                    )
                excluded.add((a, b))
                excluded.add((b, a))
        excluded_node_ids: set[str] = set()
        if excluded_nodes is not None:
            for node_id in excluded_nodes:
                if node_id not in self._nodes:
                    raise ValueError(
                        f"excluded node {node_id!r} is not in the graph"
                    )
                excluded_node_ids.add(node_id)
        if start in excluded_node_ids or goal in excluded_node_ids:
            return None, "excluded_node"
        goal_node = self._nodes[goal]

        def heuristic(name: str) -> float:
            node = self._nodes[name]
            return math.hypot(goal_node.x - node.x, goal_node.y - node.y)

        open_heap = [(heuristic(start), 0.0, start)]
        best = {start: 0.0}
        parent: dict[str, str] = {}
        closed: set[str] = set()
        while open_heap:
            _, cost, current = heapq.heappop(open_heap)
            if current in closed:
                continue
            closed.add(current)
            if current == goal:
                path = [current]
                while path[-1] in parent:
                    path.append(parent[path[-1]])
                path.reverse()
                return path, None
            for neighbour, edge_cost in self._adjacency[current]:
                if neighbour in closed:
                    continue
                if neighbour in excluded_node_ids:
                    continue
                if (current, neighbour) in excluded:
                    continue
                tentative = cost + edge_cost
                if tentative < best.get(neighbour, float("inf")) - 1e-12:
                    best[neighbour] = tentative
                    parent[neighbour] = current
                    heapq.heappush(
                        open_heap,
                        (tentative + heuristic(neighbour), tentative, neighbour),
                    )
        return None, "no_path"

    def points(self, node_ids: Iterable[str]) -> tuple[tuple[float, float], ...]:
        ids = tuple(node_ids)
        if not ids:
            return ()
        try:
            result = [(self._nodes[ids[0]].x, self._nodes[ids[0]].y)]
        except KeyError as exc:
            raise KeyError(f"unknown node {exc.args[0]!r}") from None
        for a, b in zip(ids, ids[1:]):
            result.extend(self.edge_path(a, b)[1:])
        return tuple(result)

    def to_metadata(self) -> dict:
        metadata = {
            "nodes": {
                key: {"x": node.x, "y": node.y} for key, node in self._nodes.items()
            },
            "edges": [
                [a, b]
                for a, neighbours in self._adjacency.items()
                for b, _ in neighbours
                if self._directed or a < b
            ],
            "directed": self._directed,
        }
        if self._edge_paths:
            metadata["edge_paths"] = [
                [key[0], key[1], [list(point) for point in path]]
                for key, path in sorted(self._edge_paths.items())
            ]
        return metadata


#: Nodes validated by 01A/01B at floor z = 5.80 m. ``isolated`` is deliberately
#: unreachable and exists only for failure-path tests.
UNDERGROUND_CARPARK_NODES: Mapping[str, WaypointNode] = MappingProxyType(
    {
        name: WaypointNode(name, x, y)
        for name, (x, y) in (
            ("start", (-20.0, -7.0)),
            ("w1", (-16.0, -7.0)),
            ("w2", (-12.0, -7.0)),
            ("w3", (-9.5, -7.0)),
            ("w4", (-7.6, -7.6)),
            ("w5", (-6.3, -8.5)),
            ("w6", (-5.1, -9.9)),
            ("w7", (-4.2, -11.7)),
            ("w8", (-3.9, -14.0)),
            ("w9", (-4.0, -18.0)),
            ("goal", (-4.0, -20.0)),
            ("isolated", (-40.0, -60.0)),
        )
    }
)

UNDERGROUND_CARPARK_EDGES: tuple[tuple[str, str], ...] = (
    ("start", "w1"),
    ("w1", "w2"),
    ("w2", "w3"),
    ("w3", "w4"),
    ("w4", "w5"),
    ("w5", "w6"),
    ("w6", "w7"),
    ("w7", "w8"),
    ("w8", "w9"),
    ("w9", "goal"),
)

UNDERGROUND_CARPARK_START_NODE = "start"
UNDERGROUND_CARPARK_GOAL_NODE = "goal"


def underground_carpark_graph() -> RouteGraph:
    """Build the validated 01B graph from its canonical node/edge constants."""

    return RouteGraph(UNDERGROUND_CARPARK_NODES, UNDERGROUND_CARPARK_EDGES)
