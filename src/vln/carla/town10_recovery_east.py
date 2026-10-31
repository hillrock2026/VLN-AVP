"""Town10HD_Opt M1-VLN-CARLA-05A east-blocked recovery graph.

The 04D graph blocks the northbound ``j2c -> n1`` edge.  This graph keeps the
same two j2c branches but makes the *east* ``j2c -> c_goal2`` edge the blocked
choice and uses the north ``j2c -> n1`` edge as the recovery route.

``c_goal2 -> n1`` is a junction-interior reachability connector: it lets the
east branch remain a goal-reachable A* candidate for goal ``n1`` so the normal
arbitration can select it and the safety precheck can refuse it.  The connector
is never executed (the blocked segment stops before any motion).  Its 1 m
samples were checked against the live Town10HD_Opt map: every point projects
to a driving junction lane with lane width 3.5 m and a flat floor between
z=0.018 m and z=0.139 m.  See
``docs/evidence/carla-05a-preflight/probe_05a_c_goal2_n1_connector.json``.

The module imports no CARLA and executes nothing.
"""

from __future__ import annotations

from types import MappingProxyType

from .town10_recovery import (
    TOWN10_RECOVERY_EDGES,
    TOWN10_RECOVERY_EDGE_PATHS,
    TOWN10_RECOVERY_NODES,
)
from .waypoints import RouteGraph

__all__ = [
    "TOWN10_RECOVERY_EAST_NODES",
    "TOWN10_RECOVERY_EAST_EDGES",
    "TOWN10_RECOVERY_EAST_EDGE_PATHS",
    "TOWN10_RECOVERY_EAST_START_NODE",
    "TOWN10_RECOVERY_EAST_GOAL_NODE",
    "town10_recovery_east_graph",
]

TOWN10_RECOVERY_EAST_START_NODE = "j2c"
TOWN10_RECOVERY_EAST_GOAL_NODE = "n1"

TOWN10_RECOVERY_EAST_NODES = TOWN10_RECOVERY_NODES

TOWN10_RECOVERY_EAST_EDGES = TOWN10_RECOVERY_EDGES + (("c_goal2", "n1"),)

_PATHS = dict(TOWN10_RECOVERY_EDGE_PATHS)
_PATHS[("c_goal2", "n1")] = (
    (-46.826, 24.55),
    (-46.273, 23.779),
    (-46.041, 22.805),
    (-45.887, 21.815),
    (-45.772, 20.82),
    (-45.682, 19.821),
    (-45.609, 18.822),
    (-45.548, 17.824),
    (-45.498, 16.823),
    (-45.455, 15.821),
    (-45.42, 14.818),
    (-45.39, 13.818),
    (-45.366, 12.818),
    (-45.345, 11.816),
    (-45.329, 10.813),
    (-45.316, 9.813),
    (-45.306, 8.812),
    (-45.299, 7.807),
    (-45.294, 6.8),
    (-45.292, 5.795),
    (-45.292, 5.266),
)
TOWN10_RECOVERY_EAST_EDGE_PATHS = MappingProxyType(_PATHS)


def town10_recovery_east_graph() -> RouteGraph:
    return RouteGraph(
        TOWN10_RECOVERY_EAST_NODES,
        TOWN10_RECOVERY_EAST_EDGES,
        edge_paths=TOWN10_RECOVERY_EAST_EDGE_PATHS,
        directed=True,
    )
