"""Resolve a start/goal sub-route on the existing hand-verified graph.

The current CARLA map graph is a **single corridor** (``start -> w1 -> ... ->
w9 -> goal``) with no branches. There is therefore no way to select genuinely
different topologies without adding and validating new map waypoints, which is
outside M1-VLN-CARLA-03B. This module makes the limitation explicit and
supports the minimal alternative: three distinct start/goal sub-routes.

It only reads the validated graph and computes geometry. It does not call the
model, arbitrate a direction, or move a vehicle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .route_control import cumulative_lengths
from .waypoints import RouteGraph

__all__ = [
    "GRAPH_NOTE",
    "RouteSelection",
    "RouteDefinition",
    "ROUTE_CATALOG",
    "resolve_route",
    "validate_catalog",
]

GRAPH_NOTE = (
    "The hand-verified UndergroundCarPark graph is a single corridor with no "
    "branches. These are distinct start/goal sub-routes, not different "
    "topologies; no unvalidated branch or map asset is invented."
)


@dataclass(frozen=True)
class RouteSelection:
    """One validated start/goal sub-route and its initial/final headings."""

    start_node_id: str
    goal_node_id: str
    start_previous_node_id: Optional[str]
    path: tuple[str, ...]
    start_yaw_rad: float
    derived_start_yaw_rad: float
    start_yaw_source: str
    goal_heading_rad: float
    length_m: float
    edge_keys: tuple[tuple[str, str], ...]
    graph_note: str = GRAPH_NOTE

    def __post_init__(self) -> None:
        if len(self.path) < 2:
            raise ValueError("a route must contain at least two nodes")
        if self.path[0] != self.start_node_id or self.path[-1] != self.goal_node_id:
            raise ValueError("route path endpoints do not match start/goal")
        if self.start_yaw_source not in ("derived", "explicit"):
            raise ValueError("start_yaw_source must be 'derived' or 'explicit'")
        for name in ("start_yaw_rad", "derived_start_yaw_rad", "goal_heading_rad", "length_m"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be a finite number")

    def to_metadata(self) -> dict:
        return {
            "start_node_id": self.start_node_id,
            "goal_node_id": self.goal_node_id,
            "start_previous_node_id": self.start_previous_node_id,
            "path": list(self.path),
            "edge_keys": [list(edge) for edge in self.edge_keys],
            "start_yaw_rad": self.start_yaw_rad,
            "start_yaw_deg": round(math.degrees(self.start_yaw_rad), 3),
            "derived_start_yaw_deg": round(
                math.degrees(self.derived_start_yaw_rad), 3
            ),
            "start_yaw_source": self.start_yaw_source,
            "goal_heading_rad": self.goal_heading_rad,
            "goal_heading_deg": round(math.degrees(self.goal_heading_rad), 3),
            "length_m": round(self.length_m, 3),
            "edge_count": len(self.edge_keys),
            "graph_note": self.graph_note,
        }


def resolve_route(
    graph: RouteGraph,
    start_node_id: str,
    goal_node_id: str,
    *,
    start_previous_node_id: Optional[str] = None,
    start_yaw_deg: Optional[float] = None,
) -> RouteSelection:
    """Validate one sub-route and derive its spawn/approach headings.

    ``start_previous_node_id`` disambiguates the spawn orientation at a node
    with more than one incoming neighbour. If omitted, it is derived from the
    graph; the corridor entrance has no previous node and uses its outgoing
    edge as the initial orientation. ``start_yaw_deg`` overrides the derived
    spawn yaw (the real 01E post-state yaw at w6/w8 is an explicit, auditable
    choice); both values are recorded.
    """

    if not isinstance(graph, RouteGraph):
        raise TypeError("graph must be a RouteGraph")
    for name, value in (
        ("start_node_id", start_node_id),
        ("goal_node_id", goal_node_id),
    ):
        if type(value) is not str or value.strip() == "":
            raise ValueError(f"{name} must be a non-blank str")
    if not graph.has_node(start_node_id):
        raise ValueError(f"start node {start_node_id!r} is not in the graph")
    if not graph.has_node(goal_node_id):
        raise ValueError(f"goal node {goal_node_id!r} is not in the graph")
    if start_node_id == goal_node_id:
        raise ValueError("start and goal must be different nodes")

    path, status = graph.astar(start_node_id, goal_node_id)
    if path is None:
        raise ValueError(
            f"no route {start_node_id!r}->{goal_node_id!r} (A* status {status!r})"
        )
    if len(path) < 2:
        raise ValueError("a route must contain at least two nodes")

    next_node_id = path[1]
    if start_previous_node_id is not None:
        if type(start_previous_node_id) is not str or not graph.has_node(
            start_previous_node_id
        ):
            raise ValueError(
                f"start_previous_node_id {start_previous_node_id!r} is not in the graph"
            )
        predecessors = {
            name for name, _ in graph.predecessors(start_node_id)
        }
        if start_previous_node_id not in predecessors:
            raise ValueError(
                f"{start_previous_node_id!r} is not adjacent to {start_node_id!r}"
            )
        previous_node_id = start_previous_node_id
        derived_yaw = graph.edge_end_bearing(previous_node_id, start_node_id)
    else:
        incoming = [
            name
            for name, _ in graph.predecessors(start_node_id)
            if name != next_node_id
        ]
        if len(incoming) > 1:
            raise ValueError(
                f"start node {start_node_id!r} has multiple possible previous "
                f"neighbours {sorted(incoming)!r}; pass start_previous_node_id"
            )
        if incoming:
            previous_node_id = incoming[0]
            derived_yaw = graph.edge_end_bearing(previous_node_id, start_node_id)
        else:
            previous_node_id = None
            derived_yaw = graph.edge_start_bearing(start_node_id, next_node_id)

    if start_yaw_deg is None:
        start_yaw = derived_yaw
        source = "derived"
    else:
        if type(start_yaw_deg) not in (int, float) or not math.isfinite(
            float(start_yaw_deg)
        ):
            raise ValueError("start_yaw_deg must be a finite number")
        start_yaw = math.radians(float(start_yaw_deg))
        source = "explicit"

    goal_heading = graph.edge_end_bearing(path[-2], path[-1])
    length_m = cumulative_lengths(graph.points(path))[-1]
    edge_keys = tuple(
        tuple(sorted((path[index], path[index + 1])))
        for index in range(len(path) - 1)
    )
    return RouteSelection(
        start_node_id=start_node_id,
        goal_node_id=goal_node_id,
        start_previous_node_id=previous_node_id,
        path=tuple(path),
        start_yaw_rad=start_yaw,
        derived_start_yaw_rad=derived_yaw,
        start_yaw_source=source,
        goal_heading_rad=goal_heading,
        length_m=float(length_m),
        edge_keys=edge_keys,
    )


@dataclass(frozen=True)
class RouteDefinition:
    """One reproducible 03B run configuration."""

    name: str
    start_node_id: str
    goal_node_id: str
    start_yaw_deg: Optional[float]
    round_fovs: str
    segment_nodes: int
    description: str
    spawn_x: Optional[float] = None
    spawn_y: Optional[float] = None
    spawn_z: float = 6.7

    def __post_init__(self) -> None:
        if type(self.name) is not str or self.name.strip() == "":
            raise ValueError("name must be a non-blank str")
        if type(self.segment_nodes) is not int or self.segment_nodes < 1:
            raise ValueError("segment_nodes must be a positive int")
        if type(self.description) is not str or self.description.strip() == "":
            raise ValueError("description must be a non-blank str")
        if (self.spawn_x is None) != (self.spawn_y is None):
            raise ValueError("spawn_x and spawn_y must be supplied together")
        if self.spawn_x is not None:
            if not (
                math.isfinite(float(self.spawn_x))
                and math.isfinite(float(self.spawn_y))
            ):
                raise ValueError("spawn_x/spawn_y must be finite")
        if type(self.spawn_z) not in (int, float) or not math.isfinite(
            float(self.spawn_z)
        ):
            raise ValueError("spawn_z must be a finite number")


#: Three distinct start/goal sub-routes on the only available corridor.
#: The explicit yaw values are the real 01E/03A vehicle headings at w6/w8; w4
#: uses the approach bearing w3->w4, which is the same value.
ROUTE_CATALOG: tuple[RouteDefinition, ...] = (
    RouteDefinition(
        name="w4-to-goal",
        start_node_id="w4",
        goal_node_id="goal",
        start_yaw_deg=-17.526,
        round_fovs="100,70",
        segment_nodes=2,
        description="existing 01E/03A mid-corridor route; decisions at w4, w6, w8",
    ),
    RouteDefinition(
        name="w6-to-w9",
        start_node_id="w6",
        goal_node_id="w9",
        start_yaw_deg=-42.956,
        round_fovs="70,70",
        segment_nodes=2,
        description="different start and target; decisions at w6 and w8",
        spawn_x=-5.597,
        spawn_y=-9.639,
    ),
    RouteDefinition(
        name="w8-to-goal",
        start_node_id="w8",
        goal_node_id="goal",
        start_yaw_deg=-72.348,
        round_fovs="70",
        segment_nodes=2,
        description="different start; direct test of the w8 conflict and re-decision",
        spawn_x=-4.166,
        spawn_y=-13.501,
        spawn_z=5.85,
    ),
)


def validate_catalog(graph: RouteGraph) -> tuple[tuple[RouteDefinition, RouteSelection], ...]:
    """Resolve every catalog route; raise on the first invalid definition."""

    if not isinstance(graph, RouteGraph):
        raise TypeError("graph must be a RouteGraph")
    resolved = []
    for definition in ROUTE_CATALOG:
        selection = resolve_route(
            graph,
            definition.start_node_id,
            definition.goal_node_id,
            start_yaw_deg=definition.start_yaw_deg,
        )
        if definition.spawn_x is not None:
            node = graph.nodes[selection.start_node_id]
            if math.hypot(
                float(definition.spawn_x) - node.x,
                float(definition.spawn_y) - node.y,
            ) > 2.0:
                raise ValueError(
                    f"route {definition.name!r} spawn pose is more than 2.0 m "
                    "from its start node"
                )
        resolved.append((definition, selection))
    return tuple(resolved)
