"""Deterministic Alignment stage for the bay-03 parking pipeline.

This module is the VLN-AVP-side stage layer between target verification and
bay entry. It has four independent jobs:

1. :class:`AlignmentTarget` - the measured staging geometry, built from the
   same bay polygon / footprint / parking-arc entry pose used by the validated
   CARLA scene. No model output and no image pixel coordinate enters it.
2. :func:`measure_alignment` - a deterministic geometry measurement in the
   CARLA world frame. It records the coordinate system, the reference point and
   the sign convention of every error.
3. :func:`verify_alignment` - the independent verifier. It never trusts the
   model, the Kernel status or a parking flag; it re-computes every condition
   from the real pose and only then emits ``ALIGNMENT_COMPLETED``.
4. :class:`AlignmentAuthorization` - a single-use, expiring, revocable
   permission whose scope is *bounded alignment only*. It is derived from an
   already usable ``ENTRY_AUTHORIZED`` artifact, but it never extends that
   artifact's scope and never authorizes Entry or the parking arc.

Stage vocabulary::

    ALIGNMENT_PENDING -> ALIGNMENT_VALID -> ALIGNMENT_COMPLETED
                      -> ALIGNMENT_REJECTED / SAFE_STOP

``ALIGNMENT_PENDING`` means "not aligned yet, a bounded correction may still be
attempted"; ``ALIGNMENT_VALID`` means "all static conditions are true but the
stop has not been confirmed stable"; only repeated, stable real samples yield
``ALIGNMENT_COMPLETED``.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence

from vln.carla.parking_geometry import (
    Footprint,
    footprint_clearance,
    footprint_polygon_clearance,
)

__all__ = [
    "ALIGNMENT_SKILL",
    "AlignmentStage",
    "AlignmentPhase",
    "AlignmentGeometryError",
    "AlignmentAuthorizationError",
    "AlignmentTolerances",
    "AlignmentTarget",
    "AlignmentMeasurement",
    "AlignmentStability",
    "AlignmentResult",
    "AlignmentAuthorization",
    "AlignmentBudget",
    "measure_stability",
    "measure_alignment",
    "verify_alignment",
    "authorize_alignment",
    "alignment_refusal_authorization",
    "alignment_authorization_from_metadata",
    "require_alignment_authorization",
    "consume_alignment_authorization",
    "revoke_alignment_authorization",
    "entry_authorization_is_fresh",
    "wrap_degrees",
]

ALIGNMENT_SKILL = "vln.parking.alignment"


class AlignmentStage:
    PENDING = "ALIGNMENT_PENDING"
    VALID = "ALIGNMENT_VALID"
    COMPLETED = "ALIGNMENT_COMPLETED"
    REJECTED = "ALIGNMENT_REJECTED"
    SAFE_STOP = "SAFE_STOP"

    ALL = frozenset({PENDING, VALID, COMPLETED, REJECTED, SAFE_STOP})


class AlignmentPhase:
    REVERSE_ALIGN = "REVERSE_ALIGN"
    FORWARD_TO_STAGING = "FORWARD_TO_STAGING"

    ALL = frozenset({REVERSE_ALIGN, FORWARD_TO_STAGING})


class AlignmentGeometryError(ValueError):
    """The bay/staging geometry is missing, degenerate or inconsistent."""


class AlignmentAuthorizationError(RuntimeError):
    """An alignment permission is absent, for another task, or not current."""


_DECISIONS = frozenset(
    {
        "ALIGNMENT_AUTHORIZED",
        "UNVERIFIED",
        "REJECTED",
        "SAFE_STOP",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    if type(value) is not str or value.strip() == "":
        raise ValueError("timestamp must be a non-blank str")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must carry a timezone")
    return parsed


def _nonblank(value: object, name: str) -> str:
    if type(value) is not str or value.strip() == "":
        raise ValueError(f"{name} must be a non-blank str")
    return value


def _finite(value: object, name: str) -> float:
    if type(value) is not int and type(value) is not float:
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def wrap_degrees(value: float) -> float:
    """Wrap an angle in degrees into ``[-180, 180)``."""

    value = _finite(value, "angle_deg")
    return (value + 180.0) % 360.0 - 180.0


def _wrap_radians(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi


def _polygon_area(points: Sequence[Sequence[float]]) -> float:
    area = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        area += x0 * y1 - x1 * y0
    return 0.5 * abs(area)


def _point_in_polygon(x: float, y: float, polygon: Sequence[Sequence[float]]) -> bool:
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
class AlignmentTolerances:
    """Thresholds fixed before the acceptance run.

    They are deliberately *tighter* than the final parking verdict (0.25 m /
    5 deg / 0.05 m) because Alignment is the last opportunity to remove entry
    error before the parking arc starts:

    * lateral 0.15 m: the 2.5 m painted bay minus the 1.88 m body leaves
      0.31 m per side when centred; 0.15 m preserves at least 0.16 m.
    * heading 2.0 deg: less than half of the final parking tolerance, so the
      residual consumed by the entry arc stays inside the in-bay corrector's
      margin.
    * longitudinal 0.08 m: the staging standoff is 0.55 m from ``park_entry``;
      the window keeps the front bumper at least ~0.12 m north of the painted
      bay boundary.
    * boundary 0.10 m: the bay line is painted, not a collision mesh; 0.10 m
      is twice the final-parking painted-line margin and still keeps the whole
      footprint outside the bay polygon.
    """

    lateral_m: float = 0.15
    heading_deg: float = 2.0
    longitudinal_m: float = 0.08
    boundary_clearance_m: float = 0.10
    obstacle_clearance_m: float = 0.20
    stop_speed_mps: float = 0.05
    stable_drift_m: float = 0.02
    stable_samples: int = 3

    def __post_init__(self) -> None:
        for name in (
            "lateral_m",
            "heading_deg",
            "longitudinal_m",
            "boundary_clearance_m",
            "obstacle_clearance_m",
            "stop_speed_mps",
            "stable_drift_m",
        ):
            value = _finite(getattr(self, name), name)
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative")
        if type(self.stable_samples) is not int or self.stable_samples < 3:
            raise ValueError("stable_samples must be an int >= 3")

    def to_metadata(self) -> dict:
        return {
            "lateral_m": self.lateral_m,
            "heading_deg": self.heading_deg,
            "longitudinal_m": self.longitudinal_m,
            "boundary_clearance_m": self.boundary_clearance_m,
            "obstacle_clearance_m": self.obstacle_clearance_m,
            "stop_speed_mps": self.stop_speed_mps,
            "stable_drift_m": self.stable_drift_m,
            "stable_samples": self.stable_samples,
        }


@dataclass(frozen=True)
class AlignmentTarget:
    """Measured staging geometry for one bound bay.

    Coordinate contract
    -------------------
    * Frame: CARLA world ``(x, y)`` metres, z ignored by the planar verifier.
    * Vehicle reference point: the CARLA actor transform origin. For the
      ``vehicle.dodge.charger`` used by this scene it is the centre of the
      bounding box that :class:`~vln.carla.parking_geometry.Footprint`
      describes (5.006 m x 1.88 m); the front/rear axle are *not* used.
    * Bay reference: the closed painted polygon from
      :mod:`vln.carla.parking_verdict`.
    * Target heading: the tangent of the validated forward-right parking arc
      at ``park_entry`` (southbound, ``-pi/2`` rad).
    * ``lateral_error_m`` is the signed offset of the vehicle reference to the
      *left* of the staging line when facing along the target heading. Facing
      south, left is east, so a positive value means the vehicle is east of
      the staging line.
    * ``heading_error_deg`` is ``wrap(vehicle_yaw - target_heading)`` in
      degrees; positive means the vehicle is rotated counter-clockwise in the
      numeric x-y plane from the target heading.
    * ``longitudinal_error_m`` is the projection of
      ``target_reference - vehicle_reference`` on the target heading; positive
      means the vehicle is farther north (up-route) and must move forward
      (south) to reach the staging point.
    """

    task_id: str
    target_id: str
    bay_id: str
    slot_node_id: str
    approach_node_id: str
    entry_node_id: str
    entry_xy: tuple[float, float]
    reference_xy: tuple[float, float]
    reference_heading_rad: float
    standoff_m: float
    bay_polygon: tuple[tuple[float, float], ...]
    bay_center: tuple[float, float]
    footprint: Footprint
    region_x_min: float
    region_x_max: float
    region_y_min: float
    region_y_max: float
    tolerances: AlignmentTolerances = field(default_factory=AlignmentTolerances)
    obstacle_points: tuple[tuple[float, float], ...] = ()
    source: str = "measured_scene_geometry"
    geometry_status: str = "valid"

    def __post_init__(self) -> None:
        for name in (
            "task_id",
            "target_id",
            "bay_id",
            "slot_node_id",
            "approach_node_id",
            "entry_node_id",
            "source",
        ):
            _nonblank(getattr(self, name), name)
        if type(self.footprint) is not Footprint:
            raise AlignmentGeometryError("footprint must be a Footprint")
        if len(self.bay_polygon) < 3:
            raise AlignmentGeometryError("bay polygon needs at least three points")
        for index, point in enumerate(self.bay_polygon):
            if not isinstance(point, (tuple, list)) or len(point) != 2:
                raise AlignmentGeometryError(
                    f"bay polygon point {index} must be an (x, y) pair"
                )
            _finite(point[0], f"bay_polygon[{index}].x")
            _finite(point[1], f"bay_polygon[{index}].y")
        if _polygon_area(self.bay_polygon) < 1e-6:
            raise AlignmentGeometryError("bay polygon is degenerate (zero area)")
        if len(self.bay_center) != 2:
            raise AlignmentGeometryError("bay center must be an (x, y) pair")
        for name in ("entry_xy", "reference_xy"):
            point = getattr(self, name)
            if not isinstance(point, (tuple, list)) or len(point) != 2:
                raise AlignmentGeometryError(f"{name} must be an (x, y) pair")
            _finite(point[0], f"{name}.x")
            _finite(point[1], f"{name}.y")
        _finite(self.reference_heading_rad, "reference_heading_rad")
        standoff = _finite(self.standoff_m, "standoff_m")
        if standoff <= 0.0:
            raise AlignmentGeometryError("standoff_m must be positive")
        for name in (
            "region_x_min",
            "region_x_max",
            "region_y_min",
            "region_y_max",
        ):
            _finite(getattr(self, name), name)
        if self.region_x_min >= self.region_x_max:
            raise AlignmentGeometryError("allowed region x range is empty")
        if self.region_y_min >= self.region_y_max:
            raise AlignmentGeometryError("allowed region y range is empty")
        if not self.region_contains(*self.reference_xy):
            raise AlignmentGeometryError(
                "staging reference point is outside the allowed region"
            )
        if _point_in_polygon(
            self.reference_xy[0], self.reference_xy[1], self.bay_polygon
        ):
            raise AlignmentGeometryError(
                "staging reference point is inside the bay polygon"
            )
        if type(self.obstacle_points) is not tuple:
            raise AlignmentGeometryError("obstacle_points must be a tuple")
        for index, point in enumerate(self.obstacle_points):
            if not isinstance(point, (tuple, list)) or len(point) != 2:
                raise AlignmentGeometryError(
                    f"obstacle point {index} must be an (x, y) pair"
                )
            _finite(point[0], f"obstacle_points[{index}].x")
            _finite(point[1], f"obstacle_points[{index}].y")

    @property
    def forward(self) -> tuple[float, float]:
        return (
            math.cos(self.reference_heading_rad),
            math.sin(self.reference_heading_rad),
        )

    @property
    def left(self) -> tuple[float, float]:
        return (
            -math.sin(self.reference_heading_rad),
            math.cos(self.reference_heading_rad),
        )

    def region_contains(self, x: float, y: float) -> bool:
        return (
            self.region_x_min <= float(x) <= self.region_x_max
            and self.region_y_min <= float(y) <= self.region_y_max
        )

    def geometry_checks(self) -> dict:
        return {
            "polygon_point_count": len(self.bay_polygon),
            "polygon_area_m2": round(_polygon_area(self.bay_polygon), 4),
            "reference_inside_region": self.region_contains(*self.reference_xy),
            "reference_inside_bay": _point_in_polygon(
                self.reference_xy[0], self.reference_xy[1], self.bay_polygon
            ),
            "standoff_m": self.standoff_m,
        }

    def to_metadata(self) -> dict:
        return {
            "schema": "vln.parking.alignment_target.v1",
            "skill": ALIGNMENT_SKILL,
            "task_id": self.task_id,
            "target_id": self.target_id,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "approach_node_id": self.approach_node_id,
            "entry_node_id": self.entry_node_id,
            "entry_xy": list(self.entry_xy),
            "reference_xy": list(self.reference_xy),
            "reference_heading_rad": self.reference_heading_rad,
            "reference_heading_deg": round(
                math.degrees(self.reference_heading_rad), 6
            ),
            "standoff_m": self.standoff_m,
            "bay_polygon": [list(point) for point in self.bay_polygon],
            "bay_center": list(self.bay_center),
            "footprint": self.footprint.to_metadata(),
            "region": {
                "x_min": self.region_x_min,
                "x_max": self.region_x_max,
                "y_min": self.region_y_min,
                "y_max": self.region_y_max,
            },
            "tolerances": self.tolerances.to_metadata(),
            "obstacle_point_count": len(self.obstacle_points),
            "source": self.source,
            "geometry_status": self.geometry_status,
            "coordinate_contract": {
                "frame": "CARLA world (x, y) metres",
                "vehicle_reference": "CARLA actor transform (bounding-box centre)",
                "bay_reference": "closed painted polygon",
                "heading": "radians, numeric x-y plane, CCW positive",
                "lateral_sign": "positive = vehicle left of the staging line",
                "longitudinal_sign": "positive = vehicle north of the staging point",
            },
            "geometry_checks": self.geometry_checks(),
        }


@dataclass(frozen=True)
class AlignmentStability:
    samples: int
    max_speed_mps: float
    position_drift_m: float
    stable: bool

    def to_metadata(self) -> dict:
        return {
            "samples": self.samples,
            "max_speed_mps": round(self.max_speed_mps, 4),
            "position_drift_m": round(self.position_drift_m, 4),
            "stable": self.stable,
        }


def measure_stability(
    samples: Sequence[Mapping[str, float]],
    tolerances: AlignmentTolerances,
) -> AlignmentStability:
    """Measure real stop stability from consecutive CARLA state samples.

    Every sample must carry finite ``x``, ``y`` and ``speed``. At least
    ``tolerances.stable_samples`` are required; fewer samples are never
    reported as stable.
    """

    if not isinstance(tolerances, AlignmentTolerances):
        raise TypeError("tolerances must be AlignmentTolerances")
    checked: list[tuple[float, float, float]] = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, Mapping):
            raise ValueError(f"stability sample {index} must be a mapping")
        try:
            x = _finite(sample["x"], f"samples[{index}].x")
            y = _finite(sample["y"], f"samples[{index}].y")
            speed = _finite(sample["speed"], f"samples[{index}].speed")
        except KeyError as error:
            raise ValueError(
                f"stability sample {index} is missing {error.args[0]!r}"
            ) from None
        if speed < 0.0:
            raise ValueError(f"samples[{index}].speed must be non-negative")
        checked.append((x, y, speed))
    if not checked:
        return AlignmentStability(0, 0.0, 0.0, False)
    x0, y0, _ = checked[0]
    drift = max(math.hypot(x - x0, y - y0) for x, y, _ in checked)
    max_speed = max(speed for _, _, speed in checked)
    stable = (
        len(checked) >= tolerances.stable_samples
        and max_speed < tolerances.stop_speed_mps
        and drift <= tolerances.stable_drift_m
    )
    return AlignmentStability(
        samples=len(checked),
        max_speed_mps=max_speed,
        position_drift_m=drift,
        stable=stable,
    )


@dataclass(frozen=True)
class AlignmentMeasurement:
    x: float
    y: float
    yaw_rad: float
    speed_mps: float
    stopped: bool
    lateral_error_m: float
    heading_error_deg: float
    longitudinal_error_m: float
    standoff_m: float
    boundary_clearance_m: Optional[float]
    obstacle_clearance_m: Optional[float]
    reference_inside_bay: bool
    inside_allowed_region: bool
    stability: AlignmentStability

    def to_metadata(self) -> dict:
        return {
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "yaw_rad": round(self.yaw_rad, 6),
            "yaw_deg": round(math.degrees(self.yaw_rad), 4),
            "speed_mps": round(self.speed_mps, 4),
            "stopped": self.stopped,
            "lateral_error_m": round(self.lateral_error_m, 4),
            "heading_error_deg": round(self.heading_error_deg, 4),
            "longitudinal_error_m": round(self.longitudinal_error_m, 4),
            "standoff_m": round(self.standoff_m, 4),
            "boundary_clearance_m": (
                None
                if self.boundary_clearance_m is None
                else round(self.boundary_clearance_m, 4)
            ),
            "obstacle_clearance_m": (
                None
                if self.obstacle_clearance_m is None
                else round(self.obstacle_clearance_m, 4)
            ),
            "reference_inside_bay": self.reference_inside_bay,
            "inside_allowed_region": self.inside_allowed_region,
            "stability": self.stability.to_metadata(),
        }


def measure_alignment(
    target: AlignmentTarget,
    *,
    x: float,
    y: float,
    yaw_rad: float,
    speed_mps: float,
    stopped: bool,
    stability: Optional[AlignmentStability] = None,
) -> AlignmentMeasurement:
    """Compute the planar alignment error from a real CARLA pose."""

    if not isinstance(target, AlignmentTarget):
        raise TypeError("target must be an AlignmentTarget")
    x = _finite(x, "x")
    y = _finite(y, "y")
    yaw_rad = _finite(yaw_rad, "yaw_rad")
    speed_mps = _finite(speed_mps, "speed_mps")
    if speed_mps < 0.0:
        raise ValueError("speed_mps must be non-negative")
    if type(stopped) is not bool:
        raise ValueError("stopped must be a bool")
    if stability is None:
        stability = AlignmentStability(0, speed_mps, 0.0, False)
    if not isinstance(stability, AlignmentStability):
        raise TypeError("stability must be an AlignmentStability")

    forward = target.forward
    left = target.left
    dx = x - target.reference_xy[0]
    dy = y - target.reference_xy[1]
    lateral = dx * left[0] + dy * left[1]
    heading_error = wrap_degrees(math.degrees(yaw_rad - target.reference_heading_rad))
    longitudinal = -(dx * forward[0] + dy * forward[1])
    north = (-forward[0], -forward[1])
    entry_dx = x - target.entry_xy[0]
    entry_dy = y - target.entry_xy[1]
    standoff = entry_dx * north[0] + entry_dy * north[1]

    clearance = footprint_polygon_clearance(
        x, y, yaw_rad, target.footprint, target.bay_polygon
    )
    obstacle = None
    if target.obstacle_points:
        measured = footprint_clearance(
            x, y, yaw_rad, target.footprint, target.obstacle_points
        )
        obstacle = measured["min_clearance_m"]

    return AlignmentMeasurement(
        x=x,
        y=y,
        yaw_rad=yaw_rad,
        speed_mps=speed_mps,
        stopped=stopped,
        lateral_error_m=lateral,
        heading_error_deg=heading_error,
        longitudinal_error_m=longitudinal,
        standoff_m=standoff,
        boundary_clearance_m=clearance["min_clearance_m"],
        obstacle_clearance_m=obstacle,
        reference_inside_bay=_point_in_polygon(x, y, target.bay_polygon),
        inside_allowed_region=target.region_contains(x, y),
        stability=stability,
    )


@dataclass(frozen=True)
class AlignmentResult:
    stage: str
    task_id: str
    target_id: str
    bay_id: str
    slot_node_id: str
    approach_node_id: str
    alignment_valid: bool
    checks: Mapping[str, bool]
    reasons: tuple[str, ...]
    measurement: Optional[AlignmentMeasurement]
    stage_history: tuple[str, ...]
    identity_verified: bool

    def __post_init__(self) -> None:
        if self.stage not in AlignmentStage.ALL:
            raise ValueError(f"unknown alignment stage {self.stage!r}")
        if self.alignment_valid != (
            self.stage in (AlignmentStage.VALID, AlignmentStage.COMPLETED)
        ):
            raise ValueError(
                "alignment_valid must be true exactly for VALID/COMPLETED"
            )
        if self.stage == AlignmentStage.COMPLETED and self.reasons:
            raise ValueError("a completed alignment cannot carry failure reasons")
        if self.stage not in (AlignmentStage.VALID, AlignmentStage.COMPLETED) and (
            not self.reasons
        ):
            raise ValueError("a non-valid alignment must carry at least one reason")

    @property
    def completed(self) -> bool:
        return self.stage == AlignmentStage.COMPLETED

    def to_metadata(self) -> dict:
        return {
            "schema": "vln.parking.alignment_result.v1",
            "skill": ALIGNMENT_SKILL,
            "stage": self.stage,
            "task_id": self.task_id,
            "target_id": self.target_id,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "approach_node_id": self.approach_node_id,
            "alignment_valid": self.alignment_valid,
            "completed": self.completed,
            "identity_verified": self.identity_verified,
            "checks": dict(self.checks),
            "reasons": list(self.reasons),
            "measurement": (
                None if self.measurement is None else self.measurement.to_metadata()
            ),
            "stage_history": list(self.stage_history),
        }


def verify_alignment(
    target: Optional[AlignmentTarget],
    *,
    binding: object,
    task_id: Optional[str] = None,
    target_id: Optional[str] = None,
    bay_id: Optional[str] = None,
    slot_node_id: Optional[str] = None,
    approach_node_id: Optional[str] = None,
    measurement: Optional[AlignmentMeasurement] = None,
    collision_count: int = 0,
    geometry_error: Optional[str] = None,
) -> AlignmentResult:
    """Deterministically verify one real alignment state.

    ``binding`` is the CAP-07A artifact (``status``/``bay_id``/``slot_node_id``).
    The optional identity arguments default to the target's own identity and
    are used to detect a caller mixing two tasks or targets. ``geometry_error``
    lets a caller turn a construction/geometry failure into an explicit
    ``ALIGNMENT_REJECTED`` result instead of an exception.
    """

    if type(collision_count) is not int or collision_count < 0:
        raise ValueError("collision_count must be a non-negative int")
    binding_status = getattr(binding, "status", None)
    binding_bay = getattr(binding, "bay_id", None)
    binding_slot = getattr(binding, "slot_node_id", None)

    if target is None or geometry_error is not None:
        reason = geometry_error or "alignment_geometry_missing"
        return AlignmentResult(
            stage=AlignmentStage.REJECTED,
            task_id=task_id or "unknown",
            target_id=target_id or "unknown",
            bay_id=bay_id or "unknown",
            slot_node_id=slot_node_id or "unknown",
            approach_node_id=approach_node_id or "unknown",
            alignment_valid=False,
            checks={"target_geometry_valid": False},
            reasons=(str(reason),),
            measurement=None,
            stage_history=(AlignmentStage.PENDING, AlignmentStage.REJECTED),
            identity_verified=False,
        )

    if not isinstance(target, AlignmentTarget):
        raise TypeError("target must be an AlignmentTarget or None")
    expected_task = task_id if task_id is not None else target.task_id
    expected_target = target_id if target_id is not None else target.target_id
    expected_bay = bay_id if bay_id is not None else target.bay_id
    expected_slot = slot_node_id if slot_node_id is not None else target.slot_node_id
    expected_approach = (
        approach_node_id
        if approach_node_id is not None
        else target.approach_node_id
    )

    identity_ok = (
        target.task_id == expected_task
        and target.target_id == expected_target
        and target.bay_id == expected_bay
        and target.slot_node_id == expected_slot
        and target.approach_node_id == expected_approach
        and binding_status == "bound"
        and binding_bay == target.bay_id
        and binding_slot == target.slot_node_id
    )
    measurement_ok = measurement is not None
    checks: dict[str, bool] = {
        "target_identity_matches_binding": identity_ok,
        "target_geometry_valid": target.geometry_status == "valid",
        "vehicle_state_valid": measurement_ok,
    }
    reasons: list[str] = []
    history = [AlignmentStage.PENDING]

    if not identity_ok:
        return AlignmentResult(
            stage=AlignmentStage.REJECTED,
            task_id=expected_task,
            target_id=expected_target,
            bay_id=expected_bay,
            slot_node_id=expected_slot,
            approach_node_id=expected_approach,
            alignment_valid=False,
            checks=checks,
            reasons=("target_identity_mismatch",),
            measurement=measurement,
            stage_history=tuple(history + [AlignmentStage.REJECTED]),
            identity_verified=False,
        )
    if target.geometry_status != "valid":
        return AlignmentResult(
            stage=AlignmentStage.REJECTED,
            task_id=expected_task,
            target_id=expected_target,
            bay_id=expected_bay,
            slot_node_id=expected_slot,
            approach_node_id=expected_approach,
            alignment_valid=False,
            checks=checks,
            reasons=("alignment_geometry_invalid",),
            measurement=measurement,
            stage_history=tuple(history + [AlignmentStage.REJECTED]),
            identity_verified=True,
        )
    if measurement is None:
        return AlignmentResult(
            stage=AlignmentStage.REJECTED,
            task_id=expected_task,
            target_id=expected_target,
            bay_id=expected_bay,
            slot_node_id=expected_slot,
            approach_node_id=expected_approach,
            alignment_valid=False,
            checks=checks,
            reasons=("vehicle_state_missing",),
            measurement=None,
            stage_history=tuple(history + [AlignmentStage.REJECTED]),
            identity_verified=True,
        )

    tol = target.tolerances
    checks.update(
        {
            "inside_allowed_region": measurement.inside_allowed_region,
            "reference_not_inside_bay": not measurement.reference_inside_bay,
            "lateral_within_tolerance": abs(measurement.lateral_error_m)
            <= tol.lateral_m,
            "heading_within_tolerance": abs(measurement.heading_error_deg)
            <= tol.heading_deg,
            "longitudinal_within_tolerance": abs(
                measurement.longitudinal_error_m
            )
            <= tol.longitudinal_m,
            "boundary_clearance": (
                measurement.boundary_clearance_m is not None
                and measurement.boundary_clearance_m >= tol.boundary_clearance_m
            ),
            "obstacle_clearance": (
                measurement.obstacle_clearance_m is None
                or measurement.obstacle_clearance_m >= tol.obstacle_clearance_m
            ),
            "stopped": measurement.stopped
            and measurement.speed_mps < tol.stop_speed_mps,
            "stop_stable": measurement.stability.stable,
            "no_collision": collision_count == 0,
        }
    )

    safety_keys = (
        "inside_allowed_region",
        "reference_not_inside_bay",
        "boundary_clearance",
        "obstacle_clearance",
        "no_collision",
        "stopped",
    )
    for name, passed in checks.items():
        if not passed:
            reasons.append(name)

    if not all(checks[name] for name in safety_keys):
        stage = AlignmentStage.SAFE_STOP
    elif all(checks.values()):
        stage = AlignmentStage.COMPLETED
    elif (
        checks["lateral_within_tolerance"]
        and checks["heading_within_tolerance"]
        and checks["longitudinal_within_tolerance"]
        and checks["stop_stable"]
    ):
        # every geometric condition and the stable stop pass; the remaining
        # false must be a non-geometric flag already covered above.
        stage = AlignmentStage.COMPLETED
    elif (
        checks["lateral_within_tolerance"]
        and checks["heading_within_tolerance"]
        and checks["longitudinal_within_tolerance"]
    ):
        stage = AlignmentStage.VALID
    else:
        stage = AlignmentStage.PENDING

    if stage in (AlignmentStage.VALID, AlignmentStage.COMPLETED):
        reasons = [
            f"{name}_not_confirmed"
            for name, passed in checks.items()
            if not passed
        ]
        # VALID is a static pass; it may only be missing stop stability.
        if stage == AlignmentStage.VALID and reasons != ["stop_stable_not_confirmed"]:
            stage = AlignmentStage.PENDING
        if stage == AlignmentStage.COMPLETED and reasons:
            stage = AlignmentStage.VALID
    if stage == AlignmentStage.VALID and not reasons:
        reasons = ["stop_stable_not_confirmed"]
    if stage == AlignmentStage.PENDING and not reasons:
        reasons = ["alignment_out_of_tolerance"]
    history.append(stage)
    return AlignmentResult(
        stage=stage,
        task_id=expected_task,
        target_id=expected_target,
        bay_id=expected_bay,
        slot_node_id=expected_slot,
        approach_node_id=expected_approach,
        alignment_valid=stage in (AlignmentStage.VALID, AlignmentStage.COMPLETED),
        checks=checks,
        reasons=tuple(dict.fromkeys(reasons)),
        measurement=measurement,
        stage_history=tuple(history),
        identity_verified=True,
    )


@dataclass(frozen=True)
class AlignmentBudget:
    max_rounds: int = 6
    max_phase_distance_m: float = 1.30
    max_total_distance_m: float = 6.00
    max_phase_sim_seconds: float = 25.0
    reverse_speed_cap_mps: float = 0.15
    forward_speed_cap_mps: float = 0.12
    rounds_used: int = 0
    distance_used_m: float = 0.0

    def __post_init__(self) -> None:
        if type(self.max_rounds) is not int or self.max_rounds < 1:
            raise ValueError("max_rounds must be a positive int")
        for name in (
            "max_phase_distance_m",
            "max_total_distance_m",
            "max_phase_sim_seconds",
            "reverse_speed_cap_mps",
            "forward_speed_cap_mps",
        ):
            value = _finite(getattr(self, name), name)
            if value <= 0.0:
                raise ValueError(f"{name} must be positive")
        if type(self.rounds_used) is not int or self.rounds_used < 0:
            raise ValueError("rounds_used must be a non-negative int")
        if _finite(self.distance_used_m, "distance_used_m") < 0.0:
            raise ValueError("distance_used_m must be non-negative")

    @property
    def can_start_round(self) -> bool:
        return (
            self.rounds_used < self.max_rounds
            and self.distance_used_m < self.max_total_distance_m
        )

    def remaining_distance_m(self) -> float:
        return max(0.0, self.max_total_distance_m - self.distance_used_m)

    def all_rounds_metadata(self) -> dict:
        return {
            "max_rounds": self.max_rounds,
            "max_phase_distance_m": self.max_phase_distance_m,
            "max_total_distance_m": self.max_total_distance_m,
            "max_phase_sim_seconds": self.max_phase_sim_seconds,
            "reverse_speed_cap_mps": self.reverse_speed_cap_mps,
            "forward_speed_cap_mps": self.forward_speed_cap_mps,
        }

    def record_round(self, travelled_m: float) -> "AlignmentBudget":
        travelled = _finite(travelled_m, "travelled_m")
        if travelled < 0.0:
            raise ValueError("travelled_m must be non-negative")
        if not self.can_start_round:
            raise ValueError("alignment budget is exhausted")
        return AlignmentBudget(
            max_rounds=self.max_rounds,
            max_phase_distance_m=self.max_phase_distance_m,
            max_total_distance_m=self.max_total_distance_m,
            max_phase_sim_seconds=self.max_phase_sim_seconds,
            reverse_speed_cap_mps=self.reverse_speed_cap_mps,
            forward_speed_cap_mps=self.forward_speed_cap_mps,
            rounds_used=self.rounds_used + 1,
            distance_used_m=self.distance_used_m + travelled,
        )

    def to_metadata(self) -> dict:
        return {
            **self.all_rounds_metadata(),
            "rounds_used": self.rounds_used,
            "distance_used_m": round(self.distance_used_m, 4),
            "remaining_distance_m": round(self.remaining_distance_m(), 4),
            "can_start_round": self.can_start_round,
        }


@dataclass(frozen=True)
class AlignmentAuthorization:
    authorization_id: str
    task_id: str
    target_id: str
    bay_id: str
    slot_node_id: str
    approach_node_id: str
    entry_authorization_id: str
    entry_observation_image_hashes: tuple[str, ...]
    decision: str
    reason: str
    created_at: str
    expires_at: str
    consumed_at: Optional[str]
    revoked: bool
    max_rounds: int
    max_phase_distance_m: float
    max_total_distance_m: float
    max_phase_sim_seconds: float
    reverse_speed_cap_mps: float
    forward_speed_cap_mps: float
    target_definition: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.decision not in _DECISIONS:
            raise ValueError(f"unknown alignment decision {self.decision!r}")
        for name in (
            "authorization_id",
            "task_id",
            "target_id",
            "bay_id",
            "slot_node_id",
            "approach_node_id",
            "entry_authorization_id",
            "created_at",
            "expires_at",
        ):
            _nonblank(getattr(self, name), name)
        _parse_time(self.created_at)
        _parse_time(self.expires_at)
        if _parse_time(self.expires_at) <= _parse_time(self.created_at):
            raise ValueError("expires_at must be after created_at")
        if self.consumed_at is not None:
            _parse_time(self.consumed_at)
        if type(self.revoked) is not bool:
            raise ValueError("revoked must be a bool")
        if type(self.entry_observation_image_hashes) is not tuple:
            raise ValueError("entry observation hashes must be a tuple")
        for index, value in enumerate(self.entry_observation_image_hashes):
            _nonblank(value, f"entry_observation_image_hashes[{index}]")
        if self.decision == "ALIGNMENT_AUTHORIZED":
            if len(set(self.entry_observation_image_hashes)) < 2:
                raise ValueError(
                    "ALIGNMENT_AUTHORIZED requires two distinct target-"
                    "verification observation images"
                )
        if type(self.max_rounds) is not int or self.max_rounds < 1:
            raise ValueError("max_rounds must be a positive int")
        for name in (
            "max_phase_distance_m",
            "max_total_distance_m",
            "max_phase_sim_seconds",
            "reverse_speed_cap_mps",
            "forward_speed_cap_mps",
        ):
            value = _finite(getattr(self, name), name)
            if value <= 0.0:
                raise ValueError(f"{name} must be positive")

    @property
    def permits_alignment(self) -> bool:
        return self.decision == "ALIGNMENT_AUTHORIZED" and not self.revoked

    @property
    def permits_entry(self) -> bool:
        """Alignment never authorizes Entry, even if metadata is tampered."""

        return False

    @property
    def permits_parking_arc(self) -> bool:
        return False

    @property
    def executes_motion(self) -> bool:
        return False

    def is_expired(self, now: Optional[str] = None) -> bool:
        current = _parse_time(now or _utc_now())
        return current >= _parse_time(self.expires_at)

    def is_usable(
        self,
        *,
        task_id: str,
        target_id: str,
        bay_id: str,
        slot_node_id: str,
        approach_node_id: str,
        now: Optional[str] = None,
    ) -> bool:
        return (
            self.permits_alignment
            and self.consumed_at is None
            and not self.is_expired(now)
            and self.task_id == task_id
            and self.target_id == target_id
            and self.bay_id == bay_id
            and self.slot_node_id == slot_node_id
            and self.approach_node_id == approach_node_id
        )

    def is_active(
        self,
        *,
        task_id: str,
        target_id: str,
        bay_id: str,
        slot_node_id: str,
        approach_node_id: str,
        now: Optional[str] = None,
    ) -> bool:
        """True for an already-consumed permission that may fund more rounds.

        Round-level motion is funded by the single-use stage authorization
        consumed at alignment start; each round additionally needs its own
        Kernel execution permit. This check rejects revocation, expiry and
        identity drift between rounds.
        """

        return (
            self.permits_alignment
            and not self.is_expired(now)
            and self.task_id == task_id
            and self.target_id == target_id
            and self.bay_id == bay_id
            and self.slot_node_id == slot_node_id
            and self.approach_node_id == approach_node_id
        )

    def to_metadata(self) -> dict:
        return {
            "schema": "vln.parking.alignment_authorization.v1",
            "skill": ALIGNMENT_SKILL,
            "authorization_id": self.authorization_id,
            "task_id": self.task_id,
            "target_id": self.target_id,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "approach_node_id": self.approach_node_id,
            "entry_authorization_id": self.entry_authorization_id,
            "entry_observation_image_hashes": list(
                self.entry_observation_image_hashes
            ),
            "decision": self.decision,
            "reason": self.reason,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "consumed_at": self.consumed_at,
            "revoked": self.revoked,
            "stage_scope": "ALIGNMENT",
            "permits_alignment": self.permits_alignment,
            "permits_entry": False,
            "permits_parking_arc": False,
            "executes_motion": False,
            "single_use": True,
            "budget": {
                "max_rounds": self.max_rounds,
                "max_phase_distance_m": self.max_phase_distance_m,
                "max_total_distance_m": self.max_total_distance_m,
                "max_phase_sim_seconds": self.max_phase_sim_seconds,
                "reverse_speed_cap_mps": self.reverse_speed_cap_mps,
                "forward_speed_cap_mps": self.forward_speed_cap_mps,
            },
            "target_definition": dict(self.target_definition),
        }


def _authorization_id(
    *,
    task_id: str,
    target_id: str,
    bay_id: str,
    slot_node_id: str,
    approach_node_id: str,
    entry_authorization_id: str,
    decision: str,
    created_at: str,
    target_definition: Mapping[str, object],
) -> str:
    payload = {
        "task_id": task_id,
        "target_id": target_id,
        "bay_id": bay_id,
        "slot_node_id": slot_node_id,
        "approach_node_id": approach_node_id,
        "entry_authorization_id": entry_authorization_id,
        "decision": decision,
        "created_at": created_at,
        "target_definition": target_definition,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def entry_authorization_is_fresh(
    entry_authorization: object,
    *,
    now: Optional[str] = None,
    max_age_s: float = 86400.0,
) -> bool:
    """True when the target-verification artifact is within its evidence age.

    CAP-07B-02 did not define an expiry field, so the Alignment stage imposes
    its own freshness bound on the precondition artifact. The default is one
    day; the real run's artifact was ~1.7 hours old.
    """

    if entry_authorization is None:
        return False
    created_at = getattr(entry_authorization, "created_at", None)
    if type(created_at) is not str:
        return False
    age_limit = _finite(max_age_s, "max_age_s")
    if age_limit < 0.0:
        raise ValueError("max_age_s must be non-negative")
    try:
        created = _parse_time(created_at)
        current = _parse_time(now or _utc_now())
    except ValueError:
        return False
    return (current - created).total_seconds() <= age_limit


def authorize_alignment(
    entry_authorization: object,
    target: AlignmentTarget,
    *,
    binding: object,
    verification_observation_hashes: Sequence[str],
    task_id: str,
    now: Optional[str] = None,
    ttl_s: float = 600.0,
    max_entry_age_s: float = 86400.0,
    budget: Optional[AlignmentBudget] = None,
) -> AlignmentAuthorization:
    """Issue a single-use Alignment permission from a usable Entry permission.

    The Entry permission is a *precondition only*. Its task identity stays
    untouched; this function checks that its target/bay/slot/approach identity
    matches the current binding and that its evidence is the current
    two-observation verification evidence. It then issues a new artifact whose
    scope is bounded alignment and whose ``permits_entry`` is permanently
    false.
    """

    from vln.parking.autonomous import EntryAuthorization

    if not isinstance(entry_authorization, EntryAuthorization):
        raise TypeError("entry_authorization must be an EntryAuthorization")
    if not isinstance(target, AlignmentTarget):
        raise TypeError("target must be an AlignmentTarget")
    if binding is None:
        raise ValueError("binding is required")
    if getattr(binding, "status", None) != "bound":
        raise ValueError("binding is not bound")
    if getattr(binding, "bay_id", None) != target.bay_id:
        raise ValueError("binding bay does not match the alignment target")
    if getattr(binding, "slot_node_id", None) != target.slot_node_id:
        raise ValueError("binding slot does not match the alignment target")
    _nonblank(task_id, "task_id")
    if task_id == entry_authorization.task_id:
        raise ValueError(
            "alignment must run under its own task id, not the verification task"
        )
    if entry_authorization.decision != "ENTRY_AUTHORIZED":
        raise ValueError(
            f"entry authorization decision is {entry_authorization.decision!r}"
        )
    if not entry_authorization.permits_entry or entry_authorization.executes_motion:
        raise ValueError("entry authorization has inconsistent semantics")
    if (
        entry_authorization.bay_id != target.bay_id
        or entry_authorization.slot_node_id != target.slot_node_id
        or entry_authorization.approach_node_id != target.approach_node_id
        or entry_authorization.target_id != target.target_id
    ):
        raise ValueError(
            "entry authorization identity does not match the alignment target"
        )
    hashes = tuple(verification_observation_hashes)
    if len(hashes) < 2 or len(set(hashes)) < 2:
        raise ValueError("current verification evidence needs two distinct images")
    if set(hashes) != set(entry_authorization.observation_image_hashes):
        raise ValueError(
            "entry authorization evidence is not the current verification evidence"
        )
    if not entry_authorization.is_current(
        binding_status="bound",
        approach_stage="APPROACH_COMPLETED",
        observation_image_hashes=hashes,
    ):
        raise ValueError("entry authorization is no longer current")
    if not entry_authorization_is_fresh(
        entry_authorization, now=now, max_age_s=max_entry_age_s
    ):
        raise ValueError(
            "entry authorization evidence is older than the allowed age"
        )

    ttl = _finite(ttl_s, "ttl_s")
    if ttl <= 0.0:
        raise ValueError("ttl_s must be positive")
    alignment_budget = budget or AlignmentBudget()
    if not isinstance(alignment_budget, AlignmentBudget):
        raise TypeError("budget must be an AlignmentBudget")
    created_at = now or _utc_now()
    created = _parse_time(created_at)
    expires_at = (
        created.timestamp() + ttl
    )
    expires = datetime.fromtimestamp(expires_at, timezone.utc).isoformat()
    target_definition = target.to_metadata()
    return AlignmentAuthorization(
        authorization_id=_authorization_id(
            task_id=task_id,
            target_id=target.target_id,
            bay_id=target.bay_id,
            slot_node_id=target.slot_node_id,
            approach_node_id=target.approach_node_id,
            entry_authorization_id=entry_authorization.authorization_id,
            decision="ALIGNMENT_AUTHORIZED",
            created_at=created_at,
            target_definition=target_definition,
        ),
        task_id=task_id,
        target_id=target.target_id,
        bay_id=target.bay_id,
        slot_node_id=target.slot_node_id,
        approach_node_id=target.approach_node_id,
        entry_authorization_id=entry_authorization.authorization_id,
        entry_observation_image_hashes=hashes,
        decision="ALIGNMENT_AUTHORIZED",
        reason=(
            "the bound target was verified by two independent close-range "
            "observations; this permission allows bounded low-speed alignment "
            "only"
        ),
        created_at=created_at,
        expires_at=expires,
        consumed_at=None,
        revoked=False,
        max_rounds=alignment_budget.max_rounds,
        max_phase_distance_m=alignment_budget.max_phase_distance_m,
        max_total_distance_m=alignment_budget.max_total_distance_m,
        max_phase_sim_seconds=alignment_budget.max_phase_sim_seconds,
        reverse_speed_cap_mps=alignment_budget.reverse_speed_cap_mps,
        forward_speed_cap_mps=alignment_budget.forward_speed_cap_mps,
        target_definition=target_definition,
    )


def alignment_refusal_authorization(
    target: AlignmentTarget,
    decision: str,
    reason: str,
    *,
    task_id: str,
    entry_authorization_id: str = "none",
    now: Optional[str] = None,
) -> AlignmentAuthorization:
    """Build an explicit refusal artifact; it never permits motion."""

    if decision not in ("UNVERIFIED", "REJECTED", "SAFE_STOP"):
        raise ValueError("refusal decision must be UNVERIFIED/REJECTED/SAFE_STOP")
    _nonblank(task_id, "task_id")
    _nonblank(entry_authorization_id, "entry_authorization_id")
    created_at = now or _utc_now()
    created = _parse_time(created_at)
    expires = datetime.fromtimestamp(
        created.timestamp() + 60.0, timezone.utc
    ).isoformat()
    target_definition = target.to_metadata()
    return AlignmentAuthorization(
        authorization_id=_authorization_id(
            task_id=task_id,
            target_id=target.target_id,
            bay_id=target.bay_id,
            slot_node_id=target.slot_node_id,
            approach_node_id=target.approach_node_id,
            entry_authorization_id=entry_authorization_id,
            decision=decision,
            created_at=created_at,
            target_definition=target_definition,
        ),
        task_id=task_id,
        target_id=target.target_id,
        bay_id=target.bay_id,
        slot_node_id=target.slot_node_id,
        approach_node_id=target.approach_node_id,
        entry_authorization_id=entry_authorization_id,
        entry_observation_image_hashes=(),
        decision=decision,
        reason=reason,
        created_at=created_at,
        expires_at=expires,
        consumed_at=None,
        revoked=False,
        max_rounds=1,
        max_phase_distance_m=0.01,
        max_total_distance_m=0.01,
        max_phase_sim_seconds=1.0,
        reverse_speed_cap_mps=0.01,
        forward_speed_cap_mps=0.01,
        target_definition=target_definition,
    )


def alignment_authorization_from_metadata(
    metadata: Mapping[str, object],
) -> AlignmentAuthorization:
    """Validate an on-disk Alignment authorization before reuse."""

    if not isinstance(metadata, Mapping):
        raise ValueError("alignment authorization must be a JSON object")
    schema = metadata.get("schema")
    if schema not in (None, "vln.parking.alignment_authorization.v1"):
        raise ValueError(f"unexpected alignment authorization schema {schema!r}")
    budget = metadata.get("budget")
    if not isinstance(budget, Mapping):
        raise ValueError("alignment authorization has no budget object")
    hashes = metadata.get("entry_observation_image_hashes")
    if not isinstance(hashes, list):
        raise ValueError("entry_observation_image_hashes must be a list")
    target_definition = metadata.get("target_definition")
    if not isinstance(target_definition, Mapping):
        raise ValueError("alignment authorization has no target_definition")
    return AlignmentAuthorization(
        authorization_id=metadata.get("authorization_id"),
        task_id=metadata.get("task_id"),
        target_id=metadata.get("target_id"),
        bay_id=metadata.get("bay_id"),
        slot_node_id=metadata.get("slot_node_id"),
        approach_node_id=metadata.get("approach_node_id"),
        entry_authorization_id=metadata.get("entry_authorization_id"),
        entry_observation_image_hashes=tuple(hashes),
        decision=metadata.get("decision"),
        reason=metadata.get("reason", ""),
        created_at=metadata.get("created_at"),
        expires_at=metadata.get("expires_at"),
        consumed_at=metadata.get("consumed_at"),
        revoked=metadata.get("revoked", False),
        max_rounds=budget.get("max_rounds"),
        max_phase_distance_m=budget.get("max_phase_distance_m"),
        max_total_distance_m=budget.get("max_total_distance_m"),
        max_phase_sim_seconds=budget.get("max_phase_sim_seconds"),
        reverse_speed_cap_mps=budget.get("reverse_speed_cap_mps"),
        forward_speed_cap_mps=budget.get("forward_speed_cap_mps"),
        target_definition=target_definition,
    )


def consume_alignment_authorization(
    authorization: AlignmentAuthorization,
    *,
    task_id: str,
    target_id: str,
    bay_id: str,
    slot_node_id: str,
    approach_node_id: str,
    now: Optional[str] = None,
) -> AlignmentAuthorization:
    """Consume the permission exactly once, returning the consumed artifact."""

    if not isinstance(authorization, AlignmentAuthorization):
        raise TypeError("authorization must be an AlignmentAuthorization")
    if not authorization.is_usable(
        task_id=task_id,
        target_id=target_id,
        bay_id=bay_id,
        slot_node_id=slot_node_id,
        approach_node_id=approach_node_id,
        now=now,
    ):
        raise AlignmentAuthorizationError(
            "alignment authorization is absent, for another task/target, "
            "already consumed, revoked or expired"
        )
    return replace(authorization, consumed_at=now or _utc_now())


def revoke_alignment_authorization(
    authorization: AlignmentAuthorization,
    reason: str,
    *,
    now: Optional[str] = None,
) -> AlignmentAuthorization:
    """Return a revoked copy; revocation is recorded, not silent."""

    if not isinstance(authorization, AlignmentAuthorization):
        raise TypeError("authorization must be an AlignmentAuthorization")
    _nonblank(reason, "reason")
    if authorization.decision not in _DECISIONS:
        raise ValueError("authorization decision is not revocable")
    _parse_time(now or _utc_now())
    return replace(authorization, revoked=True, reason=reason)


def require_alignment_authorization(
    authorization: AlignmentAuthorization,
    *,
    task_id: str,
    target_id: str,
    bay_id: str,
    slot_node_id: str,
    approach_node_id: str,
    now: Optional[str] = None,
) -> None:
    if not isinstance(authorization, AlignmentAuthorization):
        raise AlignmentAuthorizationError(
            "alignment stage requires an AlignmentAuthorization; an entry "
            "permission is not an alignment permission"
        )
    if not authorization.is_usable(
        task_id=task_id,
        target_id=target_id,
        bay_id=bay_id,
        slot_node_id=slot_node_id,
        approach_node_id=approach_node_id,
        now=now,
    ):
        raise AlignmentAuthorizationError(
            "alignment authorization is absent, for another task/target, "
            "already consumed, revoked or expired"
        )
