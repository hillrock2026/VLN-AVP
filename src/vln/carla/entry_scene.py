"""Measured bay-03 Entry route from the validated parking graph.

The route is the only physical entry path used by CAP-07B-04:

    actual alignment staging pose
      -> short straight connector to ``park_entry``
      -> validated 3.56 m forward-right arc
      -> validated final straight to the parking slot pose (west heading)

The arc/straight constants come from :mod:`vln.carla.underground_carpark_parking`
and :func:`vln.carla.parking_control.build_forward_right_arc`; no new curve,
waypoint or acceptance threshold is invented. The terminal pose is the same
``PARKING_SLOT_XY`` / west heading used by the validated parking runs, but this
stage only claims ``ENTRY_COMPLETED``; it does not run a parking verdict.
"""

from __future__ import annotations

import math

from vln.carla.entry_route import build_segments, route_geometry_audit, validate_entry_route
from vln.carla.parking_control import build_forward_right_arc
from vln.carla.parking_verdict import (
    BAY03_ID,
    BAY03_POLYGON,
    PARKING_FOOTPRINT,
    PARKING_SLOT_NODE_ID,
)
from vln.carla.route_control import cumulative_lengths
from vln.carla.underground_carpark_parking import (
    PARKING_ARC_RADIUS_M,
    PARKING_ENTRY_XY,
    PARKING_SLOT_HEADING_RAD,
    PARKING_SLOT_XY,
    UNDERGROUND_CARPARK_PARKING_ENTRY_NODE,
)
from vln.parking.entry import (
    EntryBudget,
    EntryGeometryError,
    EntryRoute,
    EntryTolerances,
    entry_route_hash,
)

__all__ = ["bay03_entry_route"]


def bay03_entry_route(
    *,
    task_id: str,
    actual_pose: tuple[float, float, float],
    obstacle_points: tuple[tuple[float, float], ...] = (),
    tolerances: EntryTolerances | None = None,
    budget: EntryBudget | None = None,
) -> tuple[EntryRoute, dict]:
    """Build and geometrically validate the bay-03 Entry route."""

    if type(task_id) is not str or not task_id.strip():
        raise ValueError("task_id must be a non-blank str")
    if len(actual_pose) != 3:
        raise EntryGeometryError("actual_pose must be (x, y, yaw)")
    for value in actual_pose:
        if not math.isfinite(float(value)):
            raise EntryGeometryError("actual_pose values must be finite")
    tolerances = tolerances or EntryTolerances()
    budget = budget or EntryBudget()
    entry_x, entry_y = PARKING_ENTRY_XY
    arc = build_forward_right_arc(
        entry_x,
        entry_y,
        PARKING_ARC_RADIUS_M,
        final_x=PARKING_SLOT_XY[0],
    )
    start_x, start_y = float(actual_pose[0]), float(actual_pose[1])
    points: list[tuple[float, float]] = [(start_x, start_y)]
    if math.hypot(start_x - entry_x, start_y - entry_y) > 0.02:
        points.append((float(entry_x), float(entry_y)))
    points.extend((float(x), float(y)) for x, y in arc[1:])
    # Remove a duplicate start point if the spawn is numerically on park_entry.
    deduped: list[tuple[float, float]] = []
    for point in points:
        if deduped and math.hypot(
            point[0] - deduped[-1][0], point[1] - deduped[-1][1]
        ) <= 1e-6:
            continue
        deduped.append(point)
    route_points = tuple(deduped)
    cumulative = tuple(cumulative_lengths(route_points))
    target_pose = (float(PARKING_SLOT_XY[0]), float(PARKING_SLOT_XY[1]))
    target_heading = float(PARKING_SLOT_HEADING_RAD)
    segments = build_segments(
        route_points,
        cumulative,
        max_segment_distance_m=budget.max_segment_distance_m,
        target_heading_rad=target_heading,
    )
    route_hash = entry_route_hash(
        points=route_points,
        segments=segments,
        target_pose=target_pose,
        target_heading_rad=target_heading,
        bay_id=BAY03_ID,
        slot_node_id=PARKING_SLOT_NODE_ID,
        approach_node_id=UNDERGROUND_CARPARK_PARKING_ENTRY_NODE,
    )
    route = EntryRoute(
        task_id=task_id,
        bay_id=BAY03_ID,
        slot_node_id=PARKING_SLOT_NODE_ID,
        approach_node_id=UNDERGROUND_CARPARK_PARKING_ENTRY_NODE,
        start_pose=(start_x, start_y, float(actual_pose[2])),
        points=route_points,
        cumulative=cumulative,
        segments=segments,
        target_pose=target_pose,
        target_heading_rad=target_heading,
        bay_polygon=tuple((float(x), float(y)) for x, y in BAY03_POLYGON),
        footprint=PARKING_FOOTPRINT,
        obstacle_points=tuple(
            (float(x), float(y)) for x, y in obstacle_points
        ),
        tolerances=tolerances,
        route_hash=route_hash,
        route_id=f"{BAY03_ID}-entry-{route_hash[:12]}",
        source=(
            "park_entry + build_forward_right_arc(3.56 m) + validated final "
            "straight to PARKING_SLOT_XY"
        ),
    )
    audit = route_geometry_audit(route)
    validate_entry_route(route)
    return route, audit
