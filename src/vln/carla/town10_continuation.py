"""Town10HD_Opt M1-VLN-CARLA-06 multi-decision continuation graph.

The 05B recovery scenarios execute the alternative route directly to the goal.
This graph keeps the verified j2c/east graph and adds a real eastbound goal
``e_goal`` on road 255/road 20 after ``c_goal2``.  The route
``j2c -> c_goal2 -> e_goal`` therefore contains a second decision point at
``c_goal2`` after the alternative route has been driven: the eastbound
``c_goal2 -> e_goal`` edge and the existing ``c_goal2 -> n1`` junction
connector are both goal-reachable, so the model must choose again there.

``c_goal2 -> e_goal`` is sampled from the live road-255 lane -1 at 1 m; the
floor is -0.019..0.024 m.  The module imports no CARLA and executes nothing.
"""

from __future__ import annotations

from types import MappingProxyType

from .town10_recovery_east import (
    TOWN10_RECOVERY_EAST_EDGES,
    TOWN10_RECOVERY_EAST_EDGE_PATHS,
    TOWN10_RECOVERY_EAST_NODES,
)
from .waypoints import RouteGraph, WaypointNode

__all__ = [
    "TOWN10_CONTINUATION_NODES",
    "TOWN10_CONTINUATION_EDGES",
    "TOWN10_CONTINUATION_EDGE_PATHS",
    "TOWN10_CONTINUATION_START_NODE",
    "TOWN10_CONTINUATION_GOAL_NODE",
    "town10_continuation_graph",
]

TOWN10_CONTINUATION_START_NODE = "j2c"
TOWN10_CONTINUATION_GOAL_NODE = "e_goal"

_NODES = dict(TOWN10_RECOVERY_EAST_NODES)
_NODES["e_goal"] = WaypointNode("e_goal", -36.0, 24.58)
TOWN10_CONTINUATION_NODES = MappingProxyType(_NODES)

TOWN10_CONTINUATION_EDGES = TOWN10_RECOVERY_EAST_EDGES + (("c_goal2", "e_goal"),)

_PATHS = dict(TOWN10_RECOVERY_EAST_EDGE_PATHS)
_PATHS[("c_goal2", "e_goal")] = (
    (-46.826, 24.55),
    (-45.826, 24.557),
    (-44.826, 24.559),
    (-43.826, 24.562),
    (-42.826, 24.565),
    (-41.826, 24.568),
    (-40.826, 24.571),
    (-39.826, 24.573),
    (-38.826, 24.576),
    (-37.826, 24.579),
    (-36.826, 24.582),
    (-36.0, 24.58),
)
TOWN10_CONTINUATION_EDGE_PATHS = MappingProxyType(_PATHS)


def town10_continuation_graph() -> RouteGraph:
    return RouteGraph(
        TOWN10_CONTINUATION_NODES,
        TOWN10_CONTINUATION_EDGES,
        edge_paths=TOWN10_CONTINUATION_EDGE_PATHS,
        directed=True,
    )
