"""Scene binding for the bay-03 Alignment target.

Everything here comes from measured constants already used by the validated
parking pipeline: the 07C bay polygon, the 5.006 m x 1.88 m charger footprint
and the parking graph's ``park_entry`` point / forward-right arc. No value is
taken from an image, a model answer or a hand-tuned acceptance run.

The staging point is deliberately *north* of ``park_entry`` by a measured
standoff. At the CAP-07B-01 stop the whole footprint stayed outside the painted
bay polygon (0.15 m minimum clearance); moving the reference point all the way
to ``park_entry`` would put the front corner over the bay line before Entry is
authorized. Alignment therefore corrects heading/lateral error at a staging
standoff while the footprint remains outside the bay.
"""

from __future__ import annotations

import math

from vln.parking.alignment import (
    AlignmentTarget,
    AlignmentTolerances,
    AlignmentGeometryError,
)
from vln.carla.parking_verdict import (
    BAY03_CENTER,
    BAY03_ID,
    BAY03_POLYGON,
    PARKING_FOOTPRINT,
    PARKING_SLOT_NODE_ID,
)
from vln.carla.underground_carpark_parking import (
    PARKING_ARC_RADIUS_M,
    PARKING_ENTRY_XY,
    UNDERGROUND_CARPARK_PARKING_ENTRY_NODE,
)

__all__ = [
    "ALIGNMENT_STANDOFF_M",
    "ALIGNMENT_ENTRY_HEADING_RAD",
    "BAY03_ALIGNMENT_REGION",
    "alignment_entry_heading_rad",
    "bay03_alignment_target",
]

#: The measured CAP-07B-01 stop was 0.561 m north of ``park_entry``. The
#: staging target keeps a 0.55 m standoff so the front bumper stays north of
#: the painted bay line with a real margin.
ALIGNMENT_STANDOFF_M = 0.55

#: ``build_forward_right_arc`` starts southbound. Derive the true tangent from
#: the arc centre instead of copying a magic angle; the first sampled chord is
#: 1.25 deg steeper because the arc is discretised in 2.5 deg steps.
def alignment_entry_heading_rad() -> float:
    start_x, start_y = PARKING_ENTRY_XY
    centre_x = start_x - PARKING_ARC_RADIUS_M
    centre_y = start_y
    return math.atan2(start_y - centre_y, start_x - centre_x) - math.pi / 2.0


ALIGNMENT_ENTRY_HEADING_RAD = alignment_entry_heading_rad()

#: Allowed reference-point region: a 1.5 m wide, 2.4 m long box around the
#: staging point, entirely north/east of the bay polygon. The reverse phase
#: uses the northern part; the forward phase returns to the staging line.
BAY03_ALIGNMENT_REGION = {
    "x_min": -4.25,
    "x_max": -2.75,
    "y_min": -18.00,
    "y_max": -15.60,
}


def bay03_alignment_target(
    *,
    task_id: str,
    target_id: str = BAY03_ID,
    obstacle_points: tuple[tuple[float, float], ...] = (),
    standoff_m: float = ALIGNMENT_STANDOFF_M,
    tolerances: AlignmentTolerances | None = None,
) -> AlignmentTarget:
    """Build the measured bay-03 staging target for one Alignment task."""

    if type(task_id) is not str or not task_id.strip():
        raise ValueError("task_id must be a non-blank str")
    if type(target_id) is not str or target_id != BAY03_ID:
        raise AlignmentGeometryError(
            f"this scene builder only supports {BAY03_ID!r}, got {target_id!r}"
        )
    if not math.isclose(
        alignment_entry_heading_rad(), -math.pi / 2.0, abs_tol=1e-9
    ):
        raise AlignmentGeometryError(
            "the validated parking arc no longer starts southbound"
        )
    start = (float(PARKING_ENTRY_XY[0]), float(PARKING_ENTRY_XY[1]))
    forward = (
        math.cos(ALIGNMENT_ENTRY_HEADING_RAD),
        math.sin(ALIGNMENT_ENTRY_HEADING_RAD),
    )
    reference = (
        start[0] - standoff_m * forward[0],
        start[1] - standoff_m * forward[1],
    )
    region = BAY03_ALIGNMENT_REGION
    return AlignmentTarget(
        task_id=task_id,
        target_id=target_id,
        bay_id=BAY03_ID,
        slot_node_id=PARKING_SLOT_NODE_ID,
        approach_node_id=UNDERGROUND_CARPARK_PARKING_ENTRY_NODE,
        entry_node_id=UNDERGROUND_CARPARK_PARKING_ENTRY_NODE,
        entry_xy=start,
        reference_xy=reference,
        reference_heading_rad=ALIGNMENT_ENTRY_HEADING_RAD,
        standoff_m=standoff_m,
        bay_polygon=tuple((float(x), float(y)) for x, y in BAY03_POLYGON),
        bay_center=(float(BAY03_CENTER[0]), float(BAY03_CENTER[1])),
        footprint=PARKING_FOOTPRINT,
        region_x_min=region["x_min"],
        region_x_max=region["x_max"],
        region_y_min=region["y_min"],
        region_y_max=region["y_max"],
        tolerances=tolerances or AlignmentTolerances(),
        obstacle_points=tuple(
            (float(x), float(y)) for x, y in obstacle_points
        ),
        source=(
            "vln.carla.parking_verdict bay03 polygon + PARKING_FOOTPRINT + "
            "parking graph park_entry forward-right arc"
        ),
    )
