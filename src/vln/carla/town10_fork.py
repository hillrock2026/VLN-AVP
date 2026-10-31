"""Town10HD_Opt J719 two-branch graph.

Coordinates and edge polylines came from live CARLA lane waypoints
(road 5 lane -1 -> road 736 / road 795).  Branch B is a curved connector, so
its edge carries the sampled lane points; branch A and its goal are close to
the fork so the blue target is large enough for a real image decision.
The two goals are terminal in this project graph (no cross-branch edge), so a
wrong visual choice is unreachable instead of silently looping through Town10.

``approach`` is a real upstream point on the same lane, 26 m north of the fork
(road 5 lane -1, s=80). It exists so M1-VLN-CARLA-04B can start farther away
and make an additional real observation before the branch decision. Its edge
path is the sampled CARLA lane, not a chord.
"""

from __future__ import annotations

from types import MappingProxyType

from .waypoints import RouteGraph, WaypointNode

__all__ = [
    "TOWN10_FORK_NODES",
    "TOWN10_FORK_EDGES",
    "TOWN10_FORK_EDGE_PATHS",
    "TOWN10_FORK_START_NODE",
    "TOWN10_FORK_FAR_START_NODE",
    "TOWN10_FORK_GOAL_A",
    "TOWN10_FORK_GOAL_B",
    "town10_fork_graph",
]

TOWN10_FORK_NODES = MappingProxyType(
    {
        name: WaypointNode(name, x, y)
        for name, (x, y) in (
            ("approach", (-107.533, 70.648)),
            ("fork", (-107.242, 44.649)),
            ("a_mid", (-107.121, 33.9)),
            ("a_goal", (-107.031, 25.901)),
            ("b_mid", (-89.674, 24.435)),
            ("b_goal", (-85.676, 24.446)),
        )
    }
)

TOWN10_FORK_EDGES = (
    ("approach", "fork"),
    ("fork", "a_mid"),
    ("a_mid", "a_goal"),
    ("fork", "b_mid"),
    ("b_mid", "b_goal"),
)

TOWN10_FORK_EDGE_PATHS = MappingProxyType(
    {
    ("approach", "fork"): (
            (-107.533, 70.648),
            (-107.522, 69.648),
            (-107.511, 68.648),
            (-107.499, 67.648),
            (-107.488, 66.648),
            (-107.477, 65.648),
            (-107.466, 64.648),
            (-107.455, 63.648),
            (-107.443, 62.648),
            (-107.432, 61.648),
            (-107.421, 60.648),
            (-107.41, 59.648),
            (-107.399, 58.649),
            (-107.387, 57.649),
            (-107.376, 56.649),
            (-107.365, 55.649),
            (-107.354, 54.649),
            (-107.342, 53.649),
            (-107.331, 52.649),
            (-107.32, 51.649),
            (-107.309, 50.649),
            (-107.298, 49.649),
            (-107.286, 48.649),
            (-107.275, 47.649),
            (-107.264, 46.649),
            (-107.253, 45.649),
            (-107.242, 44.649),
    ),
    ("fork", "a_mid"): (
            (-107.242, 44.649),
            (-107.219, 42.65),
            (-107.197, 40.65),
            (-107.174, 38.65),
            (-107.152, 36.65),
            (-107.13, 34.65),
            (-107.121, 33.9),
    ),
    ("a_mid", "a_goal"): (
            (-107.121, 33.9),
            (-107.099, 31.9),
            (-107.076, 29.9),
            (-107.054, 27.9),
            (-107.031, 25.901),
    ),
    ("fork", "b_mid"): (
            (-107.242, 44.649),
            (-107.219, 42.649),
            (-107.197, 40.649),
            (-107.174, 38.65),
            (-107.085, 36.82),
            (-106.789, 35.053),
            (-106.286, 33.334),
            (-105.582, 31.687),
            (-104.688, 30.135),
            (-103.617, 28.7),
            (-102.399, 27.444),
            (-101.017, 26.382),
            (-99.495, 25.534),
            (-97.866, 24.916),
            (-96.164, 24.543),
            (-94.425, 24.422),
            (-92.425, 24.427),
            (-90.425, 24.433),
            (-89.674, 24.435),
    ),
    ("b_mid", "b_goal"): (
            (-89.674, 24.435),
            (-87.674, 24.44),
            (-85.676, 24.446),
    ),
    }
)

TOWN10_FORK_START_NODE = "fork"
TOWN10_FORK_FAR_START_NODE = "approach"
TOWN10_FORK_GOAL_A = "a_goal"
TOWN10_FORK_GOAL_B = "b_goal"


def town10_fork_graph() -> RouteGraph:
    return RouteGraph(
        TOWN10_FORK_NODES,
        TOWN10_FORK_EDGES,
        edge_paths=TOWN10_FORK_EDGE_PATHS,
        directed=True,
    )
