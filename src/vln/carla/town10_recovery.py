"""Town10HD_Opt M1-VLN-CARLA-04D recovery branch graph.

``j2c`` is a real point on the road-296 approach (s=5).  Its north edge ends
north (LEFT relative to the start heading) and its east edge ends east
(STRAIGHT).  The east edge uses a small in-lane offset around the parked
blocker and ends at ``c_goal2`` on road 255.  The north loop rejoins through
``n1 -> loop_n -> j2 -> c_goal2``.  All coordinates are live CARLA waypoints or
within-lane offsets; the module does not import CARLA.
"""

from __future__ import annotations

from types import MappingProxyType

from .town10_multipoint import (
    TOWN10_MULTIPOINT_EDGES,
    TOWN10_MULTIPOINT_EDGE_PATHS,
    TOWN10_MULTIPOINT_NODES,
)
from .waypoints import RouteGraph, WaypointNode

__all__ = [
    "TOWN10_RECOVERY_NODES",
    "TOWN10_RECOVERY_EDGES",
    "TOWN10_RECOVERY_EDGE_PATHS",
    "TOWN10_RECOVERY_START_NODE",
    "TOWN10_RECOVERY_GOAL_NODE",
    "town10_recovery_graph",
]

TOWN10_RECOVERY_START_NODE = "j2c"
TOWN10_RECOVERY_GOAL_NODE = "c_goal2"

_NODES = dict(TOWN10_MULTIPOINT_NODES)
_NODES["j2c"] = WaypointNode("j2c", -61.594, 24.342)
_NODES["c_goal2"] = WaypointNode("c_goal2", -46.826, 24.550)
TOWN10_RECOVERY_NODES = MappingProxyType(_NODES)

TOWN10_RECOVERY_EDGES = TOWN10_MULTIPOINT_EDGES + (
    ("j2c", "n1"),
    ("j2c", "c_goal2"),
    ("j2", "c_goal2"),
)

_PATHS = dict(TOWN10_MULTIPOINT_EDGE_PATHS)
_PATHS[("j2c", "n1")] = ((-61.594, 24.342), (-60.502, 24.16), (-59.424, 23.913), (-58.363, 23.601), (-57.323, 23.225), (-56.308, 22.787), (-55.321, 22.288), (-54.366, 21.73), (-53.446, 21.115), (-52.566, 20.445), (-51.728, 19.724), (-50.956, 18.977), (-50.247, 18.271), (-49.5, 17.51), (-48.764, 16.659), (-48.091, 15.758), (-47.483, 14.811), (-46.945, 13.823), (-46.479, 12.8), (-46.087, 11.745), (-45.772, 10.666), (-45.534, 9.566), (-45.375, 8.453), (-45.297, 7.331), (-45.289, 6.266), (-45.292, 5.266))
_PATHS[("j2c", "c_goal2")] = ((-61.594, 24.342), (-60.2, 24.75), (-58.5, 25.0), (-56.5, 25.0), (-55.0, 25.0), (-53.5, 25.0), (-52.0, 25.0), (-50.5, 24.72), (-49.0, 24.6), (-48.0, 24.57), (-46.826, 24.55))
_PATHS[("j2", "c_goal2")] = ((-68.066, 24.494), (-67.066, 24.498), (-66.866, 24.498), (-66.826, 24.498), (-65.826, 24.501), (-64.826, 24.504), (-63.826, 24.507), (-62.826, 24.509), (-61.826, 24.512), (-60.826, 24.515), (-59.826, 24.518), (-58.826, 24.521), (-57.826, 24.523), (-56.826, 24.526), (-55.826, 24.529), (-54.826, 24.532), (-53.826, 24.534), (-52.826, 24.537), (-51.826, 24.54), (-50.826, 24.543), (-49.826, 24.546), (-48.826, 24.548), (-47.826, 24.551), (-46.826, 24.554), (-46.826, 24.55))
TOWN10_RECOVERY_EDGE_PATHS = MappingProxyType(_PATHS)


def town10_recovery_graph() -> RouteGraph:
    return RouteGraph(
        TOWN10_RECOVERY_NODES,
        TOWN10_RECOVERY_EDGES,
        edge_paths=TOWN10_RECOVERY_EDGE_PATHS,
        directed=True,
    )
