"""Town10HD_Opt M1-VLN-CARLA-05A upstream start for the north-blocked layout.

Scenario A (``town10_recovery_east``) blocks the east branch at ``j2c`` and
recovers north.  This graph adds a real upstream node ``j2w`` on road 19 lane
-1 so the same j2c junction can be reached through a genuine approach segment
while the *north* branch is blocked and the *east* branch (via the verified
``c_goal2 -> n1`` junction connector) is the recovery route.

``j2w -> j2c`` is sampled from the live road-19/road-296 eastbound lane at
1 m; the floor stays between z=0.001 m and z=0.057 m.  See
``docs/evidence/carla-05a-preflight/probe_05a_j2w_j2c.json``.

The module imports no CARLA and executes nothing.
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
    "TOWN10_RECOVERY_UPSTREAM_NODES",
    "TOWN10_RECOVERY_UPSTREAM_EDGES",
    "TOWN10_RECOVERY_UPSTREAM_EDGE_PATHS",
    "TOWN10_RECOVERY_UPSTREAM_START_NODE",
    "TOWN10_RECOVERY_UPSTREAM_GOAL_NODE",
    "town10_recovery_upstream_graph",
]

TOWN10_RECOVERY_UPSTREAM_START_NODE = "j2w"
TOWN10_RECOVERY_UPSTREAM_GOAL_NODE = "n1"

_NODES = dict(TOWN10_RECOVERY_EAST_NODES)
_NODES["j2w"] = WaypointNode("j2w", -71.0, 24.49)
TOWN10_RECOVERY_UPSTREAM_NODES = MappingProxyType(_NODES)

TOWN10_RECOVERY_UPSTREAM_EDGES = TOWN10_RECOVERY_EAST_EDGES + (("j2w", "j2c"),)

_PATHS = dict(TOWN10_RECOVERY_EAST_EDGE_PATHS)
_PATHS[("j2w", "j2c")] = (
    (-71.0, 24.49),
    (-70.0, 24.49),
    (-68.949, 24.471),
    (-67.898, 24.453),
    (-66.848, 24.434),
    (-65.797, 24.416),
    (-64.746, 24.397),
    (-63.696, 24.379),
    (-62.645, 24.36),
    (-61.594, 24.342),
)
TOWN10_RECOVERY_UPSTREAM_EDGE_PATHS = MappingProxyType(_PATHS)


def town10_recovery_upstream_graph() -> RouteGraph:
    return RouteGraph(
        TOWN10_RECOVERY_UPSTREAM_NODES,
        TOWN10_RECOVERY_UPSTREAM_EDGES,
        edge_paths=TOWN10_RECOVERY_UPSTREAM_EDGE_PATHS,
        directed=True,
    )
