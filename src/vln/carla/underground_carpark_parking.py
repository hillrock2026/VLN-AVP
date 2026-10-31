"""M1-VLN-CARLA-DEMO-02/03/04: B1 bay-03 parking and two real bypasses.

The verified aisle runs ``w4 -> ... -> w8`` and the bay edge runs
``w8 -> park_entry -> park_slot``.  DEMO-03 adds one real alternative branch
from ``w6`` around a static obstruction placed at the normal ``w8`` point:

* ``w6 -> bypass_r1 -> bypass_r2 -> park_join -> park_slot``.

DEMO-04 adds a second alternative from ``bypass_r1`` that loops east across
the open deck, south of the measured columns, and rejoins the DEMO-02 parking
arc at ``park_join2`` (arc s=6.0 m):

* ``bypass_r1 -> bypass2_east -> park_join2 -> park_slot``.

Both bypasses are rounded polylines with a 3.5 m minimum radius, the vehicle's
own limit.  Offline 07A-footprint geometry gives 1.13 m clearance to the
DEMO-03 obstruction and, for the DEMO-04 loop, 0.95 m to the measured static
points.  Decision bearings use each edge's final tangent, so the branch
classes are well outside the 5 degree ambiguity window: the normal right edge
on the baseline, the first bypass when the normal edge is refused, and the
east loop when both the normal corridor and the first bypass are refused.

The bay edge and the final control aim are unchanged from DEMO-02:
``PARKING_ENTRY_XY=(-4.0,-17.74)``, ``PARKING_SLOT_XY=(-9.5,-21.3)`` heading
west.  The independent verdict still uses the calibrated bay centre
``(-9.5,-21.14)`` and the fixed 0.25 m / 5 deg / 0.05 m tolerances.
"""

from __future__ import annotations

import math
from types import MappingProxyType

from .parking_control import build_forward_right_arc
from .route_control import cumulative_lengths, point_at_s
from .waypoints import (
    UNDERGROUND_CARPARK_EDGES,
    UNDERGROUND_CARPARK_NODES,
    RouteGraph,
    WaypointNode,
)

__all__ = [
    "UNDERGROUND_CARPARK_PARKING_NODES",
    "UNDERGROUND_CARPARK_PARKING_EDGES",
    "UNDERGROUND_CARPARK_PARKING_EDGE_PATHS",
    "UNDERGROUND_CARPARK_PARKING_START_NODE",
    "UNDERGROUND_CARPARK_PARKING_GOAL_NODE",
    "UNDERGROUND_CARPARK_PARKING_ENTRY_NODE",
    "PARKING_ENTRY_XY",
    "PARKING_SLOT_XY",
    "PARKING_ARC_RADIUS_M",
    "PARKING_SLOT_HEADING_RAD",
    "BYPASS_NODE_IDS",
    "BYPASS_GUIDE",
    "BYPASS_RADII_M",
    "PARK_JOIN_NODE_ID",
    "PARK_JOIN_XY",
    "SECOND_BYPASS_NODE_IDS",
    "SECOND_BYPASS_ENTRY_NODE_ID",
    "SECOND_BYPASS_LEFT_NODE_ID",
    "SECOND_BYPASS_JOIN_NODE_ID",
    "SECOND_BYPASS_GUIDE",
    "SECOND_BYPASS_RADII_M",
    "SECOND_BYPASS_ENTRY_XY",
    "SECOND_BYPASS_LEFT_XY",
    "PARK_JOIN2_S_M",
    "PARK_JOIN2_XY",
    "RECOVERY_ENTRY_NODE_IDS",
    "BAY11_TURN_NODE_ID",
    "BAY11_SLOT_NODE_ID",
    "BAY11_TURN_XY",
    "BAY11_SLOT_XY",
    "BAY11_ARC_RADIUS_M",
    "underground_carpark_parking_graph",
]

UNDERGROUND_CARPARK_PARKING_START_NODE = "w4"
UNDERGROUND_CARPARK_PARKING_ENTRY_NODE = "park_entry"
UNDERGROUND_CARPARK_PARKING_GOAL_NODE = "park_slot"

PARKING_ENTRY_XY = (-4.0, -17.74)
PARKING_SLOT_XY = (-9.5, -21.3)
PARKING_ARC_RADIUS_M = 3.56
# Nose-in into bay 03: the car faces west, toward the west wall.
PARKING_SLOT_HEADING_RAD = math.pi

BYPASS_NODE_IDS = ("bypass_r1", "bypass_r2")
PARK_JOIN_NODE_ID = "park_join"
PARK_JOIN_S_M = 4.5

# DEMO-05A-C / DEMO-05B: a second reachable target bay in the same row
# (bay 11, one 2.5 m stall north of bay 03).
#
# DEMO-05A put the branch node at (-4.9, -12.64), so the w7 entry edge left at
# -126.7 deg while the car actually arrived at about -66 deg. The resulting
# 60 deg corner could not be followed inside the 0.6 m off-route corridor and
# the real run stopped after 1.5 m. DEMO-05B rebuilds the entry as a tangent
# lead-in on the verified w7->w8 corridor: follow the aisle from w7 to the
# tangent point T, then one R3.5 right arc that becomes westbound exactly on
# the bay-11 centre line y=-16.14, then a straight to the slot. T is the foot
# of the perpendicular from the arc centre, so the straight->arc heading is
# continuous. The entry edge ends at the arc exit E so its decision bearing is
# a clear west/RIGHT branch instead of a near-straight corner.
BAY11_TURN_NODE_ID = "bay11_turn"
BAY11_SLOT_NODE_ID = "bay11_slot"
BAY11_ARC_RADIUS_M = 3.5
BAY11_SLOT_XY = (-9.5, -16.14)
_W7 = UNDERGROUND_CARPARK_NODES["w7"]
_W8 = UNDERGROUND_CARPARK_NODES["w8"]
_W7W8_LENGTH = math.hypot(_W8.x - _W7.x, _W8.y - _W7.y)
_W7W8_DIR = (
    (_W8.x - _W7.x) / _W7W8_LENGTH,
    (_W8.y - _W7.y) / _W7W8_LENGTH,
)
# Arc centre for a westbound exit on the bay-11 centre line.
_BAY11_CENTRE_Y = BAY11_SLOT_XY[1] + BAY11_ARC_RADIUS_M
_BAY11_CENTRE_X = _W7.x + (
    BAY11_ARC_RADIUS_M + (_BAY11_CENTRE_Y - _W7.y) * _W7W8_DIR[0]
) / _W7W8_DIR[1]
_BAY11_CENTRE = (_BAY11_CENTRE_X, _BAY11_CENTRE_Y)
_BAY11_T_S = (
    (_BAY11_CENTRE[0] - _W7.x) * _W7W8_DIR[0]
    + (_BAY11_CENTRE[1] - _W7.y) * _W7W8_DIR[1]
)
_BAY11_T = (
    _W7.x + _BAY11_T_S * _W7W8_DIR[0],
    _W7.y + _BAY11_T_S * _W7W8_DIR[1],
)
_BAY11_ARC_START_RAD = math.atan2(
    _BAY11_T[1] - _BAY11_CENTRE[1], _BAY11_T[0] - _BAY11_CENTRE[0]
)
_BAY11_ARC_END_RAD = -math.pi / 2.0
_BAY11_ARC_STEPS = 60
_BAY11_ARC_POINTS = tuple(
    (
        _BAY11_CENTRE[0]
        + BAY11_ARC_RADIUS_M
        * math.cos(
            _BAY11_ARC_START_RAD
            + (_BAY11_ARC_END_RAD - _BAY11_ARC_START_RAD)
            * index
            / _BAY11_ARC_STEPS
        ),
        _BAY11_CENTRE[1]
        + BAY11_ARC_RADIUS_M
        * math.sin(
            _BAY11_ARC_START_RAD
            + (_BAY11_ARC_END_RAD - _BAY11_ARC_START_RAD)
            * index
            / _BAY11_ARC_STEPS
        ),
    )
    for index in range(_BAY11_ARC_STEPS + 1)
)
BAY11_TURN_XY = (_BAY11_CENTRE_X, BAY11_SLOT_XY[1])
_BAY11_ENTRY_POINTS = ((_W7.x, _W7.y),) + _BAY11_ARC_POINTS
_BAY11_SLOT_POINTS = (BAY11_TURN_XY, BAY11_SLOT_XY)
_PARKING_ARC_POINTS = build_forward_right_arc(
    PARKING_ENTRY_XY[0],
    PARKING_ENTRY_XY[1],
    PARKING_ARC_RADIUS_M,
    final_x=PARKING_SLOT_XY[0],
    step_deg=2.5,
)
_PARKING_ARC_CUMULATIVE = cumulative_lengths(_PARKING_ARC_POINTS)
PARK_JOIN_XY = point_at_s(
    _PARKING_ARC_POINTS, _PARKING_ARC_CUMULATIVE, PARK_JOIN_S_M
)
BYPASS_GUIDE = (
    (-5.1, -9.9),      # w6
    (-2.5, -12.0),     # guide corner 1
    (-1.5, -18.0),     # guide corner 2
    PARK_JOIN_XY,      # verified DEMO-02 parking arc
)
BYPASS_RADII_M = (3.5, 3.5)


def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    return (dx / length, dy / length), length


def _rounded_path(guide, radii, samples_per_arc=20):
    """Rounded polyline; returns points and each corner's outgoing arc end."""

    points = [guide[0]]
    corner_end_indices = []
    for index in range(1, len(guide) - 1):
        p0, p1, p2 = guide[index - 1], guide[index], guide[index + 1]
        u1, l1 = _unit(p0, p1)
        u2, l2 = _unit(p1, p2)
        dot = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
        angle = math.acos(dot)
        if angle <= 1e-6:
            continue
        crossover = u1[0] * u2[1] - u1[1] * u2[0]
        sign = 1.0 if crossover > 0.0 else -1.0
        tangent_limit = min(l1, l2) / (2.0 * math.tan(angle / 2.0))
        radius = min(radii[index - 1], tangent_limit)
        tangent = radius * math.tan(angle / 2.0)
        start = (p1[0] - u1[0] * tangent, p1[1] - u1[1] * tangent)
        end = (p1[0] + u2[0] * tangent, p1[1] + u2[1] * tangent)
        left1 = (-u1[1], u1[0])
        centre = (
            start[0] + sign * radius * left1[0],
            start[1] + sign * radius * left1[1],
        )
        a0 = math.atan2(start[1] - centre[1], start[0] - centre[0])
        a1 = math.atan2(end[1] - centre[1], end[0] - centre[0])
        delta = a1 - a0
        while delta > math.pi:
            delta -= 2.0 * math.pi
        while delta < -math.pi:
            delta += 2.0 * math.pi
        points.append(start)
        for step in range(1, samples_per_arc + 1):
            theta = a0 + delta * step / samples_per_arc
            points.append(
                (
                    centre[0] + radius * math.cos(theta),
                    centre[1] + radius * math.sin(theta),
                )
            )
        corner_end_indices.append(len(points) - 1)
    points.append(guide[-1])
    return points, corner_end_indices


_BYPASS_POINTS, _BYPASS_CORNER_ENDS = _rounded_path(BYPASS_GUIDE, BYPASS_RADII_M)
_BYPASS_NODE_XY = {
    BYPASS_NODE_IDS[0]: _BYPASS_POINTS[_BYPASS_CORNER_ENDS[0]],
    BYPASS_NODE_IDS[1]: _BYPASS_POINTS[_BYPASS_CORNER_ENDS[1]],
}

# DEMO-04 second alternative: a wide east loop across the open B1 deck.
# The first segment is a 3.5 m-radius left arc tangent to the measured
# stopped heading (-57.142 deg), so the path starts where the car actually
# points instead of demanding an immediate 66 deg turn. Two entry nodes share
# the same path and differ only in their end tangent: one reads LEFT (east)
# and one RIGHT (south-west), so the real model's B1 side always has a
# matching unblocked edge. The loop rejoins the DEMO-02 arc at s=6.0 m.
SECOND_BYPASS_ENTRY_NODE_ID = "bypass2_east"
SECOND_BYPASS_LEFT_NODE_ID = "bypass2_left"
SECOND_BYPASS_JOIN_NODE_ID = "park_join2"
SECOND_BYPASS_NODE_IDS = (
    SECOND_BYPASS_ENTRY_NODE_ID,
    SECOND_BYPASS_LEFT_NODE_ID,
    SECOND_BYPASS_JOIN_NODE_ID,
)
PARK_JOIN2_S_M = 6.0
PARK_JOIN2_XY = point_at_s(
    _PARKING_ARC_POINTS, _PARKING_ARC_CUMULATIVE, PARK_JOIN2_S_M
)
SECOND_BYPASS_STOP_HEADING_RAD = math.radians(-57.142)
SECOND_BYPASS_TANGENT_RADIUS_M = 3.5
SECOND_BYPASS_TANGENT_TURN_RAD = math.radians(38.0)
SECOND_BYPASS_TURN_RADIUS_M = 3.5
SECOND_BYPASS_GUIDE = (
    (3.2, -16.0),
    (4.5, -19.0),
    (4.5, -23.2),
    (0.5, -24.8),
    (-3.5, -22.0),
    PARK_JOIN2_XY,
)
SECOND_BYPASS_RADII_M = (3.5,) * 5
RECOVERY_ENTRY_NODE_IDS = frozenset(BYPASS_NODE_IDS) | frozenset(
    (SECOND_BYPASS_ENTRY_NODE_ID, SECOND_BYPASS_LEFT_NODE_ID)
)
_SECOND_R1 = _BYPASS_NODE_XY[BYPASS_NODE_IDS[0]]


def _arc_samples(centre, radius, a0, a1, steps):
    return [
        (
            centre[0] + radius * math.cos(a0 + (a1 - a0) * index / steps),
            centre[1] + radius * math.sin(a0 + (a1 - a0) * index / steps),
        )
        for index in range(steps + 1)
    ]


_h0 = SECOND_BYPASS_STOP_HEADING_RAD
_r_arc = SECOND_BYPASS_TANGENT_RADIUS_M
_arc_centre = (
    _SECOND_R1[0] - _r_arc * math.sin(_h0),
    _SECOND_R1[1] + _r_arc * math.cos(_h0),
)
_a0 = math.atan2(
    _SECOND_R1[1] - _arc_centre[1], _SECOND_R1[0] - _arc_centre[0]
)
_ARC_A = _arc_samples(
    _arc_centre, _r_arc, _a0, _a0 + SECOND_BYPASS_TANGENT_TURN_RAD, 36
)
_SECOND_ROUNDED, _SECOND_CORNER_ENDS = _rounded_path(
    (_ARC_A[-1],) + SECOND_BYPASS_GUIDE,
    SECOND_BYPASS_RADII_M,
    samples_per_arc=24,
)
_SECOND_FULL = _ARC_A + _SECOND_ROUNDED[1:]
_SECOND_LEFT_INDEX = len(_ARC_A) - 1
_SECOND_EAST_INDEX = _SECOND_LEFT_INDEX + _SECOND_CORNER_ENDS[2]
SECOND_BYPASS_LEFT_XY = _SECOND_FULL[_SECOND_LEFT_INDEX]
SECOND_BYPASS_ENTRY_XY = _SECOND_FULL[_SECOND_EAST_INDEX]
_SECOND_POINTS = tuple(_SECOND_FULL)
_SECOND_SLICES = (
    (
        (BYPASS_NODE_IDS[0], SECOND_BYPASS_LEFT_NODE_ID),
        0,
        _SECOND_LEFT_INDEX + 1,
    ),
    (
        (SECOND_BYPASS_LEFT_NODE_ID, SECOND_BYPASS_JOIN_NODE_ID),
        _SECOND_LEFT_INDEX,
        len(_SECOND_FULL),
    ),
    (
        (BYPASS_NODE_IDS[0], SECOND_BYPASS_ENTRY_NODE_ID),
        0,
        _SECOND_EAST_INDEX + 1,
    ),
    (
        (SECOND_BYPASS_ENTRY_NODE_ID, SECOND_BYPASS_JOIN_NODE_ID),
        _SECOND_EAST_INDEX,
        len(_SECOND_FULL),
    ),
)

_NODES = dict(UNDERGROUND_CARPARK_NODES)
_NODES[UNDERGROUND_CARPARK_PARKING_ENTRY_NODE] = WaypointNode(
    UNDERGROUND_CARPARK_PARKING_ENTRY_NODE, *PARKING_ENTRY_XY
)
_NODES[UNDERGROUND_CARPARK_PARKING_GOAL_NODE] = WaypointNode(
    UNDERGROUND_CARPARK_PARKING_GOAL_NODE, *PARKING_SLOT_XY
)
_NODES[PARK_JOIN_NODE_ID] = WaypointNode(PARK_JOIN_NODE_ID, *PARK_JOIN_XY)
_NODES[SECOND_BYPASS_ENTRY_NODE_ID] = WaypointNode(
    SECOND_BYPASS_ENTRY_NODE_ID, *SECOND_BYPASS_ENTRY_XY
)
_NODES[SECOND_BYPASS_LEFT_NODE_ID] = WaypointNode(
    SECOND_BYPASS_LEFT_NODE_ID, *SECOND_BYPASS_LEFT_XY
)
_NODES[SECOND_BYPASS_JOIN_NODE_ID] = WaypointNode(
    SECOND_BYPASS_JOIN_NODE_ID, *PARK_JOIN2_XY
)
_NODES[BAY11_TURN_NODE_ID] = WaypointNode(
    BAY11_TURN_NODE_ID, *BAY11_TURN_XY
)
_NODES[BAY11_SLOT_NODE_ID] = WaypointNode(
    BAY11_SLOT_NODE_ID, *BAY11_SLOT_XY
)
for _node_id, _xy in _BYPASS_NODE_XY.items():
    _NODES[_node_id] = WaypointNode(_node_id, *_xy)
UNDERGROUND_CARPARK_PARKING_NODES = MappingProxyType(_NODES)

UNDERGROUND_CARPARK_PARKING_EDGES = tuple(
    edge
    for edge in UNDERGROUND_CARPARK_EDGES
    # In the parking scenario the bay entry replaces the old dead-end
    # w8->w9->goal continuation. Keeping both would make w8->w9 and
    # w8->park_entry two visually identical RIGHT edges (0.19 deg apart), which
    # the arbitration correctly refuses as ambiguous.
    if edge not in (("w8", "w9"), ("w9", "goal"))
) + (
    ("w8", UNDERGROUND_CARPARK_PARKING_ENTRY_NODE),
    (UNDERGROUND_CARPARK_PARKING_ENTRY_NODE, UNDERGROUND_CARPARK_PARKING_GOAL_NODE),
    ("w6", BYPASS_NODE_IDS[0]),
    (BYPASS_NODE_IDS[0], BYPASS_NODE_IDS[1]),
    (BYPASS_NODE_IDS[1], PARK_JOIN_NODE_ID),
    (PARK_JOIN_NODE_ID, UNDERGROUND_CARPARK_PARKING_GOAL_NODE),
    (BYPASS_NODE_IDS[0], SECOND_BYPASS_ENTRY_NODE_ID),
    (SECOND_BYPASS_ENTRY_NODE_ID, SECOND_BYPASS_JOIN_NODE_ID),
    (SECOND_BYPASS_JOIN_NODE_ID, UNDERGROUND_CARPARK_PARKING_GOAL_NODE),
    (BYPASS_NODE_IDS[0], SECOND_BYPASS_LEFT_NODE_ID),
    (SECOND_BYPASS_LEFT_NODE_ID, SECOND_BYPASS_JOIN_NODE_ID),
    ("w7", BAY11_TURN_NODE_ID),
    (BAY11_TURN_NODE_ID, BAY11_SLOT_NODE_ID),
)

_EDGE_PATHS = {
    (
        UNDERGROUND_CARPARK_PARKING_ENTRY_NODE,
        UNDERGROUND_CARPARK_PARKING_GOAL_NODE,
    ): _PARKING_ARC_POINTS
}
_BYPASS_SLICES = (
    (("w6", BYPASS_NODE_IDS[0]), 0, _BYPASS_CORNER_ENDS[0] + 1),
    ((BYPASS_NODE_IDS[0], BYPASS_NODE_IDS[1]), _BYPASS_CORNER_ENDS[0], _BYPASS_CORNER_ENDS[1] + 1),
    ((BYPASS_NODE_IDS[1], PARK_JOIN_NODE_ID), _BYPASS_CORNER_ENDS[1], len(_BYPASS_POINTS)),
)
for _key, _start, _stop in _BYPASS_SLICES:
    _EDGE_PATHS[_key] = tuple(_BYPASS_POINTS[_start:_stop])

_JOIN_INDEX = min(
    range(len(_PARKING_ARC_POINTS)),
    key=lambda i: math.hypot(
        _PARKING_ARC_POINTS[i][0] - PARK_JOIN_XY[0],
        _PARKING_ARC_POINTS[i][1] - PARK_JOIN_XY[1],
    ),
)
_EDGE_PATHS[(PARK_JOIN_NODE_ID, UNDERGROUND_CARPARK_PARKING_GOAL_NODE)] = (
    (PARK_JOIN_XY,) + _PARKING_ARC_POINTS[_JOIN_INDEX + 1 :]
)

for _key, _start, _stop in _SECOND_SLICES:
    _EDGE_PATHS[_key] = tuple(_SECOND_POINTS[_start:_stop])

_JOIN2_INDEX = min(
    range(len(_PARKING_ARC_POINTS)),
    key=lambda i: math.hypot(
        _PARKING_ARC_POINTS[i][0] - PARK_JOIN2_XY[0],
        _PARKING_ARC_POINTS[i][1] - PARK_JOIN2_XY[1],
    ),
)
_EDGE_PATHS[(SECOND_BYPASS_JOIN_NODE_ID, UNDERGROUND_CARPARK_PARKING_GOAL_NODE)] = (
    (PARK_JOIN2_XY,) + _PARKING_ARC_POINTS[_JOIN2_INDEX + 1 :]
)

_W7_NODE = UNDERGROUND_CARPARK_NODES["w7"]
_EDGE_PATHS[("w7", BAY11_TURN_NODE_ID)] = _BAY11_ENTRY_POINTS
_EDGE_PATHS[(BAY11_TURN_NODE_ID, BAY11_SLOT_NODE_ID)] = _BAY11_SLOT_POINTS

UNDERGROUND_CARPARK_PARKING_EDGE_PATHS = MappingProxyType(_EDGE_PATHS)


def underground_carpark_parking_graph() -> RouteGraph:
    return RouteGraph(
        UNDERGROUND_CARPARK_PARKING_NODES,
        UNDERGROUND_CARPARK_PARKING_EDGES,
        edge_paths=UNDERGROUND_CARPARK_PARKING_EDGE_PATHS,
    )
