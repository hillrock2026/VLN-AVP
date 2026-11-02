"""Independent final parking verdict for bay 03.

This module answers one question from the real CARLA post-run state: is the
vehicle actually parked inside the declared bay?  It deliberately does not
trust the model's ``completed`` field, the Kernel invocation status, or a
segment's arrival radius.  Those are reported as separate checks; the
geometric verdict stands on its own.

Geometry originates from measured evidence, not a guess:

* bay polygon: 07C calibrated visual boundary, north line y=-19.89, south line
  y=-22.39, west wall x=-14.4, east opening x=-4.0 (2.5 m conservative width,
  +-0.15 m calibration uncertainty);
* vehicle footprint: the CARLA ``vehicle.dodge.charger`` bounds used by the
  07A/07B/07C probes (5.006 m x 1.88 m);
* final heading: west (nose-in), as declared by the DEMO-01/07B scene.

The painted-line acceptance margin (0.05 m) is distinct from the 0.2 m
physical-obstacle guard used by the driving controller: a painted line is not
a collision object, but every footprint corner must still stay inside it.

The tolerances below are fixed before an acceptance run.  Changing them after
seeing a run would invalidate the verdict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .parking_geometry import Footprint, footprint_polygon_clearance

__all__ = [
    "BAY03_ID",
    "BAY03_POLYGON",
    "BAY03_CENTER",
    "BAY11_ID",
    "BAY11_SLOT_NODE_ID",
    "BAY11_POLYGON",
    "BAY11_CENTER",
    "PARKING_SLOT_NODE_ID",
    "PARKING_SLOT_HEADING_RAD",
    "PARKING_POSITION_TOLERANCE_M",
    "PARKING_HEADING_TOLERANCE_DEG",
    "PARKING_STOP_SPEED_MPS",
    "PARKING_STABLE_DRIFT_M",
    "PARKING_BOUNDARY_CLEARANCE_M",
    "PARKING_FOOTPRINT",
    "ParkingVerdict",
    "evaluate_parking_verdict",
]

BAY03_ID = "bay03"
PARKING_SLOT_NODE_ID = "park_slot"
PARKING_SLOT_HEADING_RAD = math.pi

# 07C conservative polygon: the east edge x=-4.0 is the bay opening and is
# intentionally part of the closed boundary; the footprint must stay inside.
BAY03_POLYGON = (
    (-4.0, -19.89),
    (-14.4, -19.89),
    (-14.4, -22.39),
    (-4.0, -22.39),
)
BAY03_CENTER = (-9.5, -21.14)

# DEMO-05A-C: the adjacent 2.5 m stall row (bay 11), same 07A-style row
# polygon one stall north of bay 03. The target slot is the row centre line
# y=-16.14; the independent tolerances are unchanged.
BAY11_ID = "bay11"
BAY11_SLOT_NODE_ID = "bay11_slot"
BAY11_POLYGON = (
    (-4.0, -14.89),
    (-14.4, -14.89),
    (-14.4, -17.39),
    (-4.0, -17.39),
)
BAY11_CENTER = (-9.5, -16.14)

PARKING_FOOTPRINT = Footprint(half_length=2.503, half_width=0.94, front_margin=0.3)

PARKING_POSITION_TOLERANCE_M = 0.25
PARKING_HEADING_TOLERANCE_DEG = 5.0
PARKING_STOP_SPEED_MPS = 0.05
PARKING_STABLE_DRIFT_M = 0.02
# The painted bay line is not a physical obstacle, so this acceptance margin
# is smaller than the 0.2 m physical-obstacle guard used while driving.  The
# 2.5 m polygon is already 0.1 m narrower than the 2.6 m visual estimate; a
# centred 1.88 m car leaves 0.31 m per side, and a 5 deg heading error consumes
# at most 0.22 m of that.  A positive 0.05 m margin still requires every corner
# to remain on the legal side of the painted line.
PARKING_BOUNDARY_CLEARANCE_M = 0.05


def _wrap(angle: float) -> float:
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def _point_in_polygon(x: float, y: float, polygon) -> bool:
    inside = False
    count = len(polygon)
    for index in range(count):
        x0, y0 = polygon[index]
        x1, y1 = polygon[(index + 1) % count]
        if (y0 > y) != (y1 > y):
            x_cross = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < x_cross:
                inside = not inside
    return inside


@dataclass(frozen=True)
class ParkingVerdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    checks: dict = field(default_factory=dict)
    measurements: dict = field(default_factory=dict)
    bay_id: str = BAY03_ID
    bay_polygon: tuple = BAY03_POLYGON
    bay_center: tuple = BAY03_CENTER
    slot_heading_rad: float = PARKING_SLOT_HEADING_RAD

    def to_metadata(self) -> dict:
        return {
            "ok": self.ok,
            "reasons": list(self.reasons),
            "checks": dict(self.checks),
            "measurements": dict(self.measurements),
            "bay_id": self.bay_id,
            "bay_polygon": [list(point) for point in self.bay_polygon],
            "bay_center": list(self.bay_center),
            "slot_heading_rad": self.slot_heading_rad,
            "tolerances": {
                "position_m": PARKING_POSITION_TOLERANCE_M,
                "heading_deg": PARKING_HEADING_TOLERANCE_DEG,
                "stop_speed_mps": PARKING_STOP_SPEED_MPS,
                "stable_drift_m": PARKING_STABLE_DRIFT_M,
                "boundary_clearance_m": PARKING_BOUNDARY_CLEARANCE_M,
            },
        }


def evaluate_parking_verdict(
    *,
    target_node_id: str,
    target_bay_id: str,
    x: float,
    y: float,
    yaw_rad: float,
    speed_mps: float,
    stop_stable: bool,
    stable_position_drift_m: float,
    collision_count: int,
    safety_stop_reason: str | None,
    kernel_execution_status: str | None,
    slot_node_id: str = PARKING_SLOT_NODE_ID,
    bay_id: str = BAY03_ID,
    bay_polygon=BAY03_POLYGON,
    bay_center=BAY03_CENTER,
    slot_heading_rad: float = PARKING_SLOT_HEADING_RAD,
    footprint: Footprint = PARKING_FOOTPRINT,
    position_tolerance_m: float = PARKING_POSITION_TOLERANCE_M,
    heading_tolerance_deg: float = PARKING_HEADING_TOLERANCE_DEG,
    stop_speed_mps: float = PARKING_STOP_SPEED_MPS,
    stable_drift_m: float = PARKING_STABLE_DRIFT_M,
    boundary_clearance_m: float = PARKING_BOUNDARY_CLEARANCE_M,
) -> ParkingVerdict:
    """Evaluate every independent parking condition with fixed tolerances."""

    for name, value in (
        ("x", x),
        ("y", y),
        ("yaw_rad", yaw_rad),
        ("speed_mps", speed_mps),
        ("stable_position_drift_m", stable_position_drift_m),
    ):
        if type(value) is not int and type(value) is not float:
            raise ValueError(f"{name} must be a number")
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
    if speed_mps < 0.0 or stable_position_drift_m < 0.0:
        raise ValueError("speed and drift must be non-negative")
    if collision_count < 0:
        raise ValueError("collision_count must be non-negative")

    distance = math.hypot(x - bay_center[0], y - bay_center[1])
    heading_error = math.degrees(_wrap(yaw_rad - slot_heading_rad))
    polygon_clearance = footprint_polygon_clearance(
        x, y, yaw_rad, footprint, bay_polygon
    )
    corners = footprint.corners(x, y, yaw_rad)
    corners_inside = all(
        _point_in_polygon(px, py, bay_polygon) for px, py in corners
    )
    boundary_ok = corners_inside and (
        polygon_clearance["min_clearance_m"] >= boundary_clearance_m
    )

    checks = {
        "target_identity": (
            target_node_id == slot_node_id and target_bay_id == bay_id
        ),
        "position_inside_tolerance": distance <= position_tolerance_m,
        "heading_aligned": abs(heading_error) <= heading_tolerance_deg,
        "footprint_inside_bay": boundary_ok,
        "stopped": speed_mps < stop_speed_mps,
        "stop_stable": bool(stop_stable)
        and stable_position_drift_m <= stable_drift_m,
        "no_collision": collision_count == 0,
        "no_unresolved_safety_stop": safety_stop_reason in (None, "success"),
        "kernel_execution_completed": kernel_execution_status == "completed",
    }
    reasons = [name for name, passed in checks.items() if not passed]
    return ParkingVerdict(
        ok=not reasons,
        reasons=reasons,
        checks=checks,
        bay_id=bay_id,
        bay_polygon=tuple(tuple(point) for point in bay_polygon),
        bay_center=tuple(bay_center),
        slot_heading_rad=slot_heading_rad,
        measurements={
            "target_node_id": target_node_id,
            "target_bay_id": target_bay_id,
            "x": round(float(x), 3),
            "y": round(float(y), 3),
            "yaw_deg": round(math.degrees(float(yaw_rad)), 3),
            "speed_mps": round(float(speed_mps), 3),
            "distance_to_bay_center_m": round(distance, 3),
            "heading_error_deg": round(heading_error, 3),
            "boundary_clearance_m": polygon_clearance["min_clearance_m"],
            "boundary_worst": polygon_clearance["worst"],
            "footprint_corners": [
                [round(px, 3), round(py, 3)] for px, py in corners
            ],
            "corners_inside_polygon": corners_inside,
            "stable_position_drift_m": round(float(stable_position_drift_m), 3),
            "collision_count": int(collision_count),
            "safety_stop_reason": safety_stop_reason,
            "kernel_execution_status": kernel_execution_status,
        },
    )
