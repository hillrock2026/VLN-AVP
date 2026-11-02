"""Deterministic Entry stage for the bay-03 autonomous parking pipeline.

Entry is the stage after ``ALIGNMENT_COMPLETED``: the vehicle follows the
validated parking arc from the alignment staging pose into the bound bay and
stops at the declared terminal pose. It is **not** ``PARKING_COMPLETED``:
there is no final-parking business flow, no parking verdict and no
``PARKING_COMPLETED`` artifact.

The module is deliberately split the same way as the Alignment stage:

* :class:`EntryRoute` - a measured, hashed, segmented route with a terminal
  pose. It carries the footprint, bay polygon and obstacle points used by the
  verifier.
* :func:`measure_entry` - deterministic geometry from a real CARLA pose:
  route progress, cross-track deviation, terminal pose error, rotated
  footprint, bay boundary clearance and static-obstacle clearance.
* :func:`verify_entry` - the independent verifier. It never trusts the
  controller, the Kernel completion flag or a model answer.
* :class:`EntryAuthorization` - a single-use, expiring, revocable stage
  permission bound to an :class:`AlignmentCompletion`, the route hash and the
  actual alignment final pose. It never permits Alignment, a generic parking
  arc or ``PARKING_COMPLETED``; each actual motion still needs its own
  Agent-Kernel single-use permit.
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
    point_to_segment_distance,
)

__all__ = [
    "ENTRY_SKILL",
    "EntryStage",
    "EntryTolerances",
    "EntryBudget",
    "EntryRouteSegment",
    "EntryRoute",
    "AlignmentCompletion",
    "EntryMeasurement",
    "EntryResult",
    "EntryAuthorization",
    "EntryAuthorizationError",
    "EntryGeometryError",
    "measure_stability",
    "measure_entry",
    "verify_entry",
    "entry_round_improved",
    "compute_alignment_completion_id",
    "entry_route_hash",
    "authorize_entry",
    "entry_refusal_authorization",
    "entry_authorization_from_metadata",
    "consume_entry_authorization",
    "require_entry_authorization",
    "revoke_entry_authorization",
    "alignment_completion_is_usable",
    "wrap_degrees",
]

ENTRY_SKILL = "vln.parking.entry"
ALIGNMENT_COMPLETED_STAGE = "ALIGNMENT_COMPLETED"


class EntryStage:
    PENDING = "ENTRY_PENDING"
    AUTHORIZED = "ENTRY_AUTHORIZED"
    EXECUTING = "ENTRY_EXECUTING"
    VALID = "ENTRY_VALID"
    COMPLETED = "ENTRY_COMPLETED"
    REJECTED = "ENTRY_REJECTED"
    SAFE_STOP = "SAFE_STOP"

    ALL = frozenset(
        {
            PENDING,
            AUTHORIZED,
            EXECUTING,
            VALID,
            COMPLETED,
            REJECTED,
            SAFE_STOP,
        }
    )


class EntryGeometryError(ValueError):
    """The Entry route/target geometry is missing, degenerate or inconsistent."""


class EntryAuthorizationError(RuntimeError):
    """An Entry permission is absent, for another task/route, or not current."""


_DECISIONS = frozenset(
    {"ENTRY_AUTHORIZED", "UNVERIFIED", "REJECTED", "SAFE_STOP"}
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
    value = _finite(value, "angle_deg")
    return (value + 180.0) % 360.0 - 180.0


def _wrap_radians(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi


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


def _canonical(payload: object) -> str:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha256_json(payload: object) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def compute_alignment_completion_id(
    *,
    task_id: str,
    target_id: str,
    bay_id: str,
    slot_node_id: str,
    approach_node_id: str,
    final_pose: Mapping[str, float],
    final_speed_mps: float,
    verification_stage: str,
    alignment_authorization_id: str,
    alignment_result_sha256: str,
    alignment_authorization_sha256: str,
) -> str:
    """Stable id for the accepted CAP-07B-03 completion evidence."""

    return _sha256_json(
        {
            "task_id": task_id,
            "target_id": target_id,
            "bay_id": bay_id,
            "slot_node_id": slot_node_id,
            "approach_node_id": approach_node_id,
            "final_pose": {
                key: round(float(final_pose[key]), 6)
                for key in ("x", "y", "yaw")
            },
            "final_speed_mps": round(float(final_speed_mps), 6),
            "verification_stage": verification_stage,
            "alignment_authorization_id": alignment_authorization_id,
            "alignment_result_sha256": alignment_result_sha256,
            "alignment_authorization_sha256": alignment_authorization_sha256,
        }
    )


@dataclass(frozen=True)
class EntryTolerances:
    """Thresholds fixed before the Entry acceptance run.

    The terminal tolerances are the already-validated final-parking geometry
    tolerances (0.25 m / 5 deg / 0.05 m) because they are the only calibrated
    acceptance values for this scene; Entry additionally requires the *whole
    rotated footprint* to be inside the bay, which is stricter than a
    reference-point check. Route deviation and obstacle guard are the
    validated driving guards.
    """

    position_m: float = 0.25
    heading_deg: float = 5.0
    boundary_clearance_m: float = 0.05
    obstacle_clearance_m: float = 0.20
    stop_speed_mps: float = 0.05
    stable_drift_m: float = 0.02
    stable_samples: int = 3
    route_deviation_m: float = 0.50
    progress_tolerance_m: float = 0.35
    corridor_half_width_m: float = 3.00

    def __post_init__(self) -> None:
        for name in (
            "position_m",
            "heading_deg",
            "boundary_clearance_m",
            "obstacle_clearance_m",
            "stop_speed_mps",
            "stable_drift_m",
            "route_deviation_m",
            "progress_tolerance_m",
            "corridor_half_width_m",
        ):
            value = _finite(getattr(self, name), name)
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative")
        if type(self.stable_samples) is not int or self.stable_samples < 3:
            raise ValueError("stable_samples must be an int >= 3")

    def to_metadata(self) -> dict:
        return {
            "position_m": self.position_m,
            "heading_deg": self.heading_deg,
            "boundary_clearance_m": self.boundary_clearance_m,
            "obstacle_clearance_m": self.obstacle_clearance_m,
            "stop_speed_mps": self.stop_speed_mps,
            "stable_drift_m": self.stable_drift_m,
            "stable_samples": self.stable_samples,
            "route_deviation_m": self.route_deviation_m,
            "progress_tolerance_m": self.progress_tolerance_m,
            "corridor_half_width_m": self.corridor_half_width_m,
        }


@dataclass(frozen=True)
class EntryBudget:
    max_segments: int = 8
    max_segment_distance_m: float = 4.20
    max_total_distance_m: float = 15.0
    max_segment_sim_seconds: float = 40.0
    max_total_sim_seconds: float = 240.0
    speed_cap_mps: float = 0.35
    segments_used: int = 0
    distance_used_m: float = 0.0
    sim_used_s: float = 0.0

    def __post_init__(self) -> None:
        if type(self.max_segments) is not int or self.max_segments < 1:
            raise ValueError("max_segments must be a positive int")
        for name in (
            "max_segment_distance_m",
            "max_total_distance_m",
            "max_segment_sim_seconds",
            "max_total_sim_seconds",
            "speed_cap_mps",
        ):
            value = _finite(getattr(self, name), name)
            if value <= 0.0:
                raise ValueError(f"{name} must be positive")
        if type(self.segments_used) is not int or self.segments_used < 0:
            raise ValueError("segments_used must be non-negative")
        if _finite(self.distance_used_m, "distance_used_m") < 0.0:
            raise ValueError("distance_used_m must be non-negative")
        if _finite(self.sim_used_s, "sim_used_s") < 0.0:
            raise ValueError("sim_used_s must be non-negative")

    @property
    def can_start_segment(self) -> bool:
        return (
            self.segments_used < self.max_segments
            and self.distance_used_m < self.max_total_distance_m
            and self.sim_used_s < self.max_total_sim_seconds
        )

    def remaining_distance_m(self) -> float:
        return max(0.0, self.max_total_distance_m - self.distance_used_m)

    def record_segment(self, travelled_m: float, sim_seconds: float) -> "EntryBudget":
        travelled = _finite(travelled_m, "travelled_m")
        sim = _finite(sim_seconds, "sim_seconds")
        if travelled < 0.0 or sim < 0.0:
            raise ValueError("segment travel/time must be non-negative")
        if not self.can_start_segment:
            raise ValueError("entry budget is exhausted")
        return EntryBudget(
            max_segments=self.max_segments,
            max_segment_distance_m=self.max_segment_distance_m,
            max_total_distance_m=self.max_total_distance_m,
            max_segment_sim_seconds=self.max_segment_sim_seconds,
            max_total_sim_seconds=self.max_total_sim_seconds,
            speed_cap_mps=self.speed_cap_mps,
            segments_used=self.segments_used + 1,
            distance_used_m=self.distance_used_m + travelled,
            sim_used_s=self.sim_used_s + sim,
        )

    def to_metadata(self) -> dict:
        return {
            "max_segments": self.max_segments,
            "max_segment_distance_m": self.max_segment_distance_m,
            "max_total_distance_m": self.max_total_distance_m,
            "max_segment_sim_seconds": self.max_segment_sim_seconds,
            "max_total_sim_seconds": self.max_total_sim_seconds,
            "speed_cap_mps": self.speed_cap_mps,
            "segments_used": self.segments_used,
            "distance_used_m": round(self.distance_used_m, 4),
            "sim_used_s": round(self.sim_used_s, 4),
            "remaining_distance_m": round(self.remaining_distance_m(), 4),
            "can_start_segment": self.can_start_segment,
        }


@dataclass(frozen=True)
class EntryRouteSegment:
    index: int
    start_s: float
    end_s: float
    length_m: float
    target_x: float
    target_y: float
    target_heading_rad: float
    phase: str

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 1:
            raise ValueError("segment index must be a positive int")
        for name in ("start_s", "end_s", "length_m", "target_x", "target_y", "target_heading_rad"):
            _finite(getattr(self, name), name)
        if self.end_s <= self.start_s:
            raise ValueError("segment end_s must be greater than start_s")
        if not math.isclose(
            self.length_m, self.end_s - self.start_s, abs_tol=1e-6
        ):
            raise ValueError("segment length does not match its s span")
        _nonblank(self.phase, "phase")

    @property
    def target_pose(self) -> tuple[float, float, float]:
        return (self.target_x, self.target_y, self.target_heading_rad)

    def to_metadata(self) -> dict:
        return {
            "index": self.index,
            "phase": self.phase,
            "start_s": round(self.start_s, 4),
            "end_s": round(self.end_s, 4),
            "length_m": round(self.length_m, 4),
            "target_pose": {
                "x": round(self.target_x, 4),
                "y": round(self.target_y, 4),
                "heading_deg": round(math.degrees(self.target_heading_rad), 4),
            },
        }


def entry_route_hash(
    *,
    points: Sequence[Sequence[float]],
    segments: Sequence[EntryRouteSegment],
    target_pose: Sequence[float],
    target_heading_rad: float,
    bay_id: str,
    slot_node_id: str,
    approach_node_id: str,
) -> str:
    return _sha256_json(
        {
            "points": [[round(float(x), 6), round(float(y), 6)] for x, y in points],
            "segments": [segment.to_metadata() for segment in segments],
            "target_pose": [round(float(target_pose[0]), 6), round(float(target_pose[1]), 6)],
            "target_heading_rad": round(float(target_heading_rad), 9),
            "bay_id": bay_id,
            "slot_node_id": slot_node_id,
            "approach_node_id": approach_node_id,
        }
    )


@dataclass(frozen=True)
class EntryRoute:
    """One measured Entry route with segments and an independent terminal target."""

    task_id: str
    bay_id: str
    slot_node_id: str
    approach_node_id: str
    start_pose: tuple[float, float, float]
    points: tuple[tuple[float, float], ...]
    cumulative: tuple[float, ...]
    segments: tuple[EntryRouteSegment, ...]
    target_pose: tuple[float, float]
    target_heading_rad: float
    bay_polygon: tuple[tuple[float, float], ...]
    footprint: Footprint
    obstacle_points: tuple[tuple[float, float], ...]
    tolerances: EntryTolerances
    route_hash: str
    route_id: str
    source: str = "validated_parking_arc"
    geometry_status: str = "valid"

    def __post_init__(self) -> None:
        for name in ("task_id", "bay_id", "slot_node_id", "approach_node_id", "route_hash", "route_id", "source"):
            _nonblank(getattr(self, name), name)
        if len(self.start_pose) != 3:
            raise EntryGeometryError("start_pose must be (x, y, yaw)")
        for value in self.start_pose:
            _finite(value, "start_pose")
        if len(self.points) < 2 or len(self.cumulative) != len(self.points):
            raise EntryGeometryError("route points/cumulative are inconsistent")
        if self.cumulative[0] != 0.0:
            raise EntryGeometryError("route cumulative must start at 0")
        for index in range(1, len(self.cumulative)):
            if self.cumulative[index] <= self.cumulative[index - 1]:
                raise EntryGeometryError("route cumulative must increase")
        if not self.segments:
            raise EntryGeometryError("route has no segments")
        expected_start = 0.0
        for segment in self.segments:
            if not math.isclose(segment.start_s, expected_start, abs_tol=1e-6):
                raise EntryGeometryError("route segments are not contiguous")
            expected_start = segment.end_s
        if not math.isclose(
            expected_start, self.cumulative[-1], abs_tol=1e-6
        ):
            raise EntryGeometryError("route segments do not cover the route")
        if len(self.bay_polygon) < 3:
            raise EntryGeometryError("bay polygon needs at least three points")
        if type(self.footprint) is not Footprint:
            raise EntryGeometryError("footprint must be a Footprint")
        if len(self.target_pose) != 2:
            raise EntryGeometryError("target_pose must be (x, y)")
        _finite(self.target_pose[0], "target_pose.x")
        _finite(self.target_pose[1], "target_pose.y")
        _finite(self.target_heading_rad, "target_heading_rad")
        if type(self.tolerances) is not EntryTolerances:
            raise EntryGeometryError("tolerances must be EntryTolerances")
        recomputed = entry_route_hash(
            points=self.points,
            segments=self.segments,
            target_pose=self.target_pose,
            target_heading_rad=self.target_heading_rad,
            bay_id=self.bay_id,
            slot_node_id=self.slot_node_id,
            approach_node_id=self.approach_node_id,
        )
        if recomputed != self.route_hash:
            raise EntryGeometryError("route hash does not match the route geometry")

    @property
    def length_m(self) -> float:
        return float(self.cumulative[-1])

    def point_at_s(self, s: float) -> tuple[float, float]:
        s = max(0.0, min(self.length_m, float(s)))
        for index in range(1, len(self.cumulative)):
            if s <= self.cumulative[index]:
                span = self.cumulative[index] - self.cumulative[index - 1]
                t = 0.0 if span <= 1e-9 else (s - self.cumulative[index - 1]) / span
                a = self.points[index - 1]
                b = self.points[index]
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        return self.points[-1]

    def tangent_at_s(self, s: float) -> float:
        if s >= self.length_m - 1e-9:
            return self.target_heading_rad
        p0 = self.point_at_s(s)
        p1 = self.point_at_s(min(self.length_m, s + 0.20))
        if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < 1e-9:
            return self.target_heading_rad
        return math.atan2(p1[1] - p0[1], p1[0] - p0[0])

    def segment_for_s(self, s: float) -> EntryRouteSegment:
        s = max(0.0, min(self.length_m, float(s)))
        for segment in self.segments:
            if s <= segment.end_s + 1e-9:
                return segment
        return self.segments[-1]

    def distance_to_route(self, x: float, y: float) -> float:
        return min(
            point_to_segment_distance(
                x, y,
                self.points[index - 1][0], self.points[index - 1][1],
                self.points[index][0], self.points[index][1],
            )
            for index in range(1, len(self.points))
        )

    def point_in_start_cap(
        self, x: float, y: float, *, margin_m: float = 0.25
    ) -> bool:
        """Include the authorized staging footprint in the corridor union.

        The route starts at the vehicle reference point, so the rear of the
        car is behind the first route sample. The start cap is the staging
        footprint plus a small margin; it is not a general free-driving area.
        """

        start_x, start_y, start_yaw = self.start_pose
        dx, dy = x - start_x, y - start_y
        c, s = math.cos(start_yaw), math.sin(start_yaw)
        local_x = dx * c + dy * s
        local_y = -dx * s + dy * c
        return (
            abs(local_x) <= self.footprint.half_length + margin_m
            and abs(local_y) <= self.footprint.half_width + margin_m
        )

    def to_metadata(self) -> dict:
        return {
            "schema": "vln.parking.entry_route.v1",
            "skill": ENTRY_SKILL,
            "task_id": self.task_id,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "approach_node_id": self.approach_node_id,
            "route_id": self.route_id,
            "route_hash": self.route_hash,
            "start_pose": {
                "x": round(self.start_pose[0], 4),
                "y": round(self.start_pose[1], 4),
                "yaw_deg": round(math.degrees(self.start_pose[2]), 4),
            },
            "length_m": round(self.length_m, 4),
            "target_pose": {
                "x": round(self.target_pose[0], 4),
                "y": round(self.target_pose[1], 4),
                "heading_deg": round(math.degrees(self.target_heading_rad), 4),
            },
            "segments": [segment.to_metadata() for segment in self.segments],
            "points": [[round(x, 4), round(y, 4)] for x, y in self.points],
            "bay_polygon": [list(point) for point in self.bay_polygon],
            "footprint": self.footprint.to_metadata(),
            "obstacle_point_count": len(self.obstacle_points),
            "tolerances": self.tolerances.to_metadata(),
            "source": self.source,
            "geometry_status": self.geometry_status,
            "coordinate_contract": {
                "frame": "CARLA world (x, y) metres",
                "vehicle_reference": "CARLA actor transform (bounding-box centre)",
                "heading": "radians, numeric x-y plane, CCW positive",
                "terminal_target": "parking graph slot pose, west heading",
            },
        }


@dataclass(frozen=True)
class AlignmentCompletion:
    """Accepted CAP-07B-03 evidence that Entry is allowed to start from."""

    task_id: str
    target_id: str
    bay_id: str
    slot_node_id: str
    approach_node_id: str
    final_pose: tuple[float, float, float]
    final_speed_mps: float
    verification_stage: str
    alignment_authorization_id: str
    alignment_result_sha256: str
    alignment_authorization_sha256: str
    completion_id: str
    created_at: str

    def __post_init__(self) -> None:
        for name in (
            "task_id",
            "target_id",
            "bay_id",
            "slot_node_id",
            "approach_node_id",
            "verification_stage",
            "alignment_authorization_id",
            "alignment_result_sha256",
            "alignment_authorization_sha256",
            "completion_id",
            "created_at",
        ):
            _nonblank(getattr(self, name), name)
        if self.verification_stage != ALIGNMENT_COMPLETED_STAGE:
            raise EntryGeometryError("alignment completion stage is not ALIGNMENT_COMPLETED")
        if len(self.final_pose) != 3:
            raise EntryGeometryError("alignment final pose must be (x, y, yaw)")
        for value in self.final_pose:
            _finite(value, "alignment final pose")
        _finite(self.final_speed_mps, "final_speed_mps")
        _parse_time(self.created_at)
        expected = compute_alignment_completion_id(
            task_id=self.task_id,
            target_id=self.target_id,
            bay_id=self.bay_id,
            slot_node_id=self.slot_node_id,
            approach_node_id=self.approach_node_id,
            final_pose={"x": self.final_pose[0], "y": self.final_pose[1], "yaw": self.final_pose[2]},
            final_speed_mps=self.final_speed_mps,
            verification_stage=self.verification_stage,
            alignment_authorization_id=self.alignment_authorization_id,
            alignment_result_sha256=self.alignment_result_sha256,
            alignment_authorization_sha256=self.alignment_authorization_sha256,
        )
        if expected != self.completion_id:
            raise EntryGeometryError("alignment completion id does not match its evidence")

    def to_metadata(self) -> dict:
        return {
            "schema": "vln.parking.alignment_completion.v1",
            "task_id": self.task_id,
            "target_id": self.target_id,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "approach_node_id": self.approach_node_id,
            "completion_id": self.completion_id,
            "verification_stage": self.verification_stage,
            "final_pose": {
                "x": round(self.final_pose[0], 4),
                "y": round(self.final_pose[1], 4),
                "yaw_deg": round(math.degrees(self.final_pose[2]), 4),
            },
            "final_speed_mps": round(self.final_speed_mps, 4),
            "alignment_authorization_id": self.alignment_authorization_id,
            "alignment_result_sha256": self.alignment_result_sha256,
            "alignment_authorization_sha256": self.alignment_authorization_sha256,
            "created_at": self.created_at,
        }


def alignment_completion_is_usable(
    completion: object,
    *,
    binding: object,
    route: EntryRoute,
    now: Optional[str] = None,
    max_age_s: float = 86400.0,
) -> bool:
    if not isinstance(completion, AlignmentCompletion):
        return False
    if getattr(binding, "status", None) != "bound":
        return False
    if getattr(binding, "bay_id", None) != completion.bay_id:
        return False
    if getattr(binding, "slot_node_id", None) != completion.slot_node_id:
        return False
    if completion.bay_id != route.bay_id or completion.slot_node_id != route.slot_node_id:
        return False
    if completion.approach_node_id != route.approach_node_id:
        return False
    age_limit = _finite(max_age_s, "max_age_s")
    try:
        created = _parse_time(completion.created_at)
        current = _parse_time(now or _utc_now())
    except ValueError:
        return False
    return (current - created).total_seconds() <= age_limit


@dataclass(frozen=True)
class EntryMeasurement:
    x: float
    y: float
    yaw_rad: float
    speed_mps: float
    stopped: bool
    route_s: float
    cross_track_m: float
    route_deviation_m: float
    progress_m: float
    remaining_m: float
    distance_to_target_m: float
    heading_error_deg: float
    lateral_error_m: float
    longitudinal_error_m: float
    footprint_corners: tuple[tuple[float, float], ...]
    footprint_inside_bay: bool
    boundary_clearance_m: Optional[float]
    obstacle_clearance_m: Optional[float]
    reference_to_route_m: float
    footprint_corners_inside_corridor: bool
    stability: "EntryStability"
    collision_count: int

    def to_metadata(self) -> dict:
        return {
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "yaw_rad": round(self.yaw_rad, 6),
            "yaw_deg": round(math.degrees(self.yaw_rad), 4),
            "speed_mps": round(self.speed_mps, 4),
            "stopped": self.stopped,
            "route_s": round(self.route_s, 4),
            "cross_track_m": round(self.cross_track_m, 4),
            "route_deviation_m": round(self.route_deviation_m, 4),
            "progress_m": round(self.progress_m, 4),
            "remaining_m": round(self.remaining_m, 4),
            "distance_to_target_m": round(self.distance_to_target_m, 4),
            "heading_error_deg": round(self.heading_error_deg, 4),
            "lateral_error_m": round(self.lateral_error_m, 4),
            "longitudinal_error_m": round(self.longitudinal_error_m, 4),
            "footprint_corners": [[round(x, 4), round(y, 4)] for x, y in self.footprint_corners],
            "footprint_inside_bay": self.footprint_inside_bay,
            "boundary_clearance_m": None if self.boundary_clearance_m is None else round(self.boundary_clearance_m, 4),
            "obstacle_clearance_m": None if self.obstacle_clearance_m is None else round(self.obstacle_clearance_m, 4),
            "reference_to_route_m": round(self.reference_to_route_m, 4),
            "footprint_corners_inside_corridor": self.footprint_corners_inside_corridor,
            "stability": self.stability.to_metadata(),
            "collision_count": self.collision_count,
        }


@dataclass(frozen=True)
class EntryStability:
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
    tolerances: EntryTolerances,
) -> EntryStability:
    if not isinstance(tolerances, EntryTolerances):
        raise TypeError("tolerances must be EntryTolerances")
    checked: list[tuple[float, float, float]] = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, Mapping):
            raise ValueError(f"stability sample {index} must be a mapping")
        try:
            x = _finite(sample["x"], f"samples[{index}].x")
            y = _finite(sample["y"], f"samples[{index}].y")
            speed = _finite(sample["speed"], f"samples[{index}].speed")
        except KeyError as error:
            raise ValueError(f"stability sample {index} is missing {error.args[0]!r}") from None
        if speed < 0.0:
            raise ValueError(f"samples[{index}].speed must be non-negative")
        checked.append((x, y, speed))
    if not checked:
        return EntryStability(0, 0.0, 0.0, False)
    x0, y0, _ = checked[0]
    drift = max(math.hypot(x - x0, y - y0) for x, y, _ in checked)
    max_speed = max(speed for _, _, speed in checked)
    stable = (
        len(checked) >= tolerances.stable_samples
        and max_speed < tolerances.stop_speed_mps
        and drift <= tolerances.stable_drift_m
    )
    return EntryStability(len(checked), max_speed, drift, stable)


def measure_entry(
    route: EntryRoute,
    *,
    x: float,
    y: float,
    yaw_rad: float,
    speed_mps: float,
    stopped: bool,
    route_s: float,
    cross_track_m: float,
    stability: Optional[EntryStability] = None,
    collision_count: int = 0,
    footprint: Optional[Footprint] = None,
) -> EntryMeasurement:
    if not isinstance(route, EntryRoute):
        raise TypeError("route must be an EntryRoute")
    x = _finite(x, "x")
    y = _finite(y, "y")
    yaw_rad = _finite(yaw_rad, "yaw_rad")
    speed_mps = _finite(speed_mps, "speed_mps")
    route_s = _finite(route_s, "route_s")
    cross = _finite(cross_track_m, "cross_track_m")
    if speed_mps < 0.0 or route_s < 0.0:
        raise ValueError("speed/route_s must be non-negative")
    if type(stopped) is not bool:
        raise ValueError("stopped must be a bool")
    if type(collision_count) is not int or collision_count < 0:
        raise ValueError("collision_count must be a non-negative int")
    stability = stability or EntryStability(0, speed_mps, 0.0, False)
    if not isinstance(stability, EntryStability):
        raise TypeError("stability must be an EntryStability")
    footprint = footprint or route.footprint
    tol = route.tolerances

    target_x, target_y = route.target_pose
    forward = (math.cos(route.target_heading_rad), math.sin(route.target_heading_rad))
    left = (-forward[1], forward[0])
    dx, dy = x - target_x, y - target_y
    lateral = dx * left[0] + dy * left[1]
    longitudinal = dx * forward[0] + dy * forward[1]
    heading_error = wrap_degrees(math.degrees(yaw_rad - route.target_heading_rad))
    distance_target = math.hypot(dx, dy)

    corners = footprint.corners(x, y, yaw_rad)
    inside = all(_point_in_polygon(px, py, route.bay_polygon) for px, py in corners)
    boundary = footprint_polygon_clearance(x, y, yaw_rad, footprint, route.bay_polygon)
    obstacle = None
    if route.obstacle_points:
        obstacle = footprint_clearance(x, y, yaw_rad, footprint, route.obstacle_points)["min_clearance_m"]
    reference_to_route = route.distance_to_route(x, y)
    corners_in_corridor = all(
        _point_in_polygon(px, py, route.bay_polygon)
        or route.distance_to_route(px, py) <= tol.corridor_half_width_m
        or route.point_in_start_cap(px, py)
        for px, py in corners
    )
    return EntryMeasurement(
        x=x,
        y=y,
        yaw_rad=yaw_rad,
        speed_mps=speed_mps,
        stopped=stopped,
        route_s=route_s,
        cross_track_m=cross,
        route_deviation_m=abs(cross),
        progress_m=route_s,
        remaining_m=max(0.0, route.length_m - route_s),
        distance_to_target_m=distance_target,
        heading_error_deg=heading_error,
        lateral_error_m=lateral,
        longitudinal_error_m=longitudinal,
        footprint_corners=tuple(corners),
        footprint_inside_bay=inside,
        boundary_clearance_m=boundary["min_clearance_m"],
        obstacle_clearance_m=obstacle,
        reference_to_route_m=reference_to_route,
        footprint_corners_inside_corridor=corners_in_corridor,
        stability=stability,
        collision_count=collision_count,
    )


@dataclass(frozen=True)
class EntryResult:
    stage: str
    task_id: str
    bay_id: str
    slot_node_id: str
    approach_node_id: str
    route_id: str
    route_hash: str
    entry_valid: bool
    completed: bool
    identity_verified: bool
    authorization_verified: bool
    checks: Mapping[str, bool]
    reasons: tuple[str, ...]
    measurement: Optional[EntryMeasurement]
    stage_history: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.stage not in EntryStage.ALL:
            raise ValueError(f"unknown entry stage {self.stage!r}")
        if self.completed != (self.stage == EntryStage.COMPLETED):
            raise ValueError("completed must be true exactly for ENTRY_COMPLETED")
        if self.entry_valid != (self.stage in (EntryStage.VALID, EntryStage.COMPLETED)):
            raise ValueError("entry_valid must be true exactly for VALID/COMPLETED")
        if self.stage == EntryStage.COMPLETED and self.reasons:
            raise ValueError("a completed entry cannot carry failure reasons")
        if self.stage not in (EntryStage.VALID, EntryStage.COMPLETED) and not self.reasons:
            raise ValueError("a non-valid entry must carry at least one reason")

    def to_metadata(self) -> dict:
        return {
            "schema": "vln.parking.entry_result.v1",
            "skill": ENTRY_SKILL,
            "stage": self.stage,
            "task_id": self.task_id,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "approach_node_id": self.approach_node_id,
            "route_id": self.route_id,
            "route_hash": self.route_hash,
            "entry_valid": self.entry_valid,
            "completed": self.completed,
            "identity_verified": self.identity_verified,
            "authorization_verified": self.authorization_verified,
            "checks": dict(self.checks),
            "reasons": list(self.reasons),
            "measurement": None if self.measurement is None else self.measurement.to_metadata(),
            "stage_history": list(self.stage_history),
        }


def verify_entry(
    route: Optional[EntryRoute],
    completion: Optional[AlignmentCompletion],
    authorization: Optional["EntryAuthorization"],
    *,
    binding: object,
    measurement: Optional[EntryMeasurement] = None,
    collision_count: int = 0,
    now: Optional[str] = None,
    geometry_error: Optional[str] = None,
) -> EntryResult:
    """Independently verify one Entry state.

    Mid-route safe states are ``ENTRY_PENDING``; the footprint-inside-bay and
    terminal-pose conditions are only required once the route progress is
    terminal. Identity/authorization/route-hash failures are terminal
    ``ENTRY_REJECTED``; collision, obstacle, deviation and corridor failures
    are ``SAFE_STOP``.
    """

    if type(collision_count) is not int or collision_count < 0:
        raise ValueError("collision_count must be a non-negative int")
    if route is None or completion is None or geometry_error is not None:
        reason = geometry_error or "entry_route_or_completion_missing"
        return EntryResult(
            stage=EntryStage.REJECTED,
            task_id="unknown",
            bay_id="unknown",
            slot_node_id="unknown",
            approach_node_id="unknown",
            route_id="unknown",
            route_hash="unknown",
            entry_valid=False,
            completed=False,
            identity_verified=False,
            authorization_verified=False,
            checks={"route_and_completion_present": False},
            reasons=(str(reason),),
            measurement=measurement,
            stage_history=(EntryStage.PENDING, EntryStage.REJECTED),
        )
    if not isinstance(route, EntryRoute):
        raise TypeError("route must be an EntryRoute")
    if not isinstance(completion, AlignmentCompletion):
        raise TypeError("completion must be an AlignmentCompletion")
    if authorization is None:
        return EntryResult(
            stage=EntryStage.REJECTED,
            task_id=route.task_id,
            bay_id=route.bay_id,
            slot_node_id=route.slot_node_id,
            approach_node_id=route.approach_node_id,
            route_id=route.route_id,
            route_hash=route.route_hash,
            entry_valid=False,
            completed=False,
            identity_verified=False,
            authorization_verified=False,
            checks={"authorization_present": False},
            reasons=("entry_authorization_missing",),
            measurement=measurement,
            stage_history=(EntryStage.PENDING, EntryStage.REJECTED),
        )
    if not isinstance(authorization, EntryAuthorization):
        raise TypeError("authorization must be an EntryAuthorization")

    identity_ok = (
        getattr(binding, "status", None) == "bound"
        and getattr(binding, "bay_id", None) == route.bay_id
        and getattr(binding, "slot_node_id", None) == route.slot_node_id
        and completion.bay_id == route.bay_id
        and completion.slot_node_id == route.slot_node_id
        and completion.approach_node_id == route.approach_node_id
        and completion.target_id == route.bay_id
    )
    route_ok = (
        authorization.route_hash == route.route_hash
        and authorization.route_id == route.route_id
        and authorization.alignment_completion_id == completion.completion_id
        and authorization.alignment_authorization_id == completion.alignment_authorization_id
    )
    auth_ok = (
        authorization.is_active(
            task_id=route.task_id,
            bay_id=route.bay_id,
            slot_node_id=route.slot_node_id,
            approach_node_id=route.approach_node_id,
            route_id=route.route_id,
            route_hash=route.route_hash,
            now=now,
        )
        and authorization.consumed_at is not None
    )
    checks: dict[str, bool] = {
        "target_identity_matches_binding": identity_ok,
        "route_identity_matches_authorization": route_ok,
        "entry_authorization_active": auth_ok,
        "vehicle_state_valid": measurement is not None,
    }
    if not identity_ok or not route_ok or not auth_ok or measurement is None:
        reasons = []
        if not identity_ok:
            reasons.append("target_identity_mismatch")
        if not route_ok:
            reasons.append("route_identity_mismatch")
        if not auth_ok:
            reasons.append("entry_authorization_inactive")
        if measurement is None:
            reasons.append("vehicle_state_missing")
        return EntryResult(
            stage=EntryStage.REJECTED,
            task_id=route.task_id,
            bay_id=route.bay_id,
            slot_node_id=route.slot_node_id,
            approach_node_id=route.approach_node_id,
            route_id=route.route_id,
            route_hash=route.route_hash,
            entry_valid=False,
            completed=False,
            identity_verified=identity_ok,
            authorization_verified=auth_ok and route_ok,
            checks=checks,
            reasons=tuple(reasons),
            measurement=measurement,
            stage_history=(EntryStage.PENDING, EntryStage.REJECTED),
        )

    tol = route.tolerances
    terminal_progress = measurement.route_s >= route.length_m - tol.progress_tolerance_m
    terminal_position = measurement.distance_to_target_m <= tol.position_m
    terminal_heading = abs(measurement.heading_error_deg) <= tol.heading_deg
    terminal_footprint = measurement.footprint_inside_bay
    terminal_boundary = (
        measurement.boundary_clearance_m is not None
        and measurement.boundary_clearance_m >= tol.boundary_clearance_m
    )
    obstacle_ok = (
        measurement.obstacle_clearance_m is None
        or measurement.obstacle_clearance_m >= tol.obstacle_clearance_m
    )
    deviation_ok = measurement.route_deviation_m <= tol.route_deviation_m
    corridor_ok = measurement.footprint_corners_inside_corridor
    stopped_ok = measurement.stopped and measurement.speed_mps < tol.stop_speed_mps
    stable_ok = measurement.stability.stable
    no_collision = collision_count == 0

    checks.update(
        {
            "route_progress_terminal": terminal_progress,
            "terminal_position": terminal_position,
            "terminal_heading": terminal_heading,
            "footprint_inside_bay": terminal_footprint,
            "boundary_clearance": terminal_boundary,
            "obstacle_clearance": obstacle_ok,
            "route_deviation": deviation_ok,
            "entry_corridor": corridor_ok,
            "stopped": stopped_ok,
            "stop_stable": stable_ok,
            "no_collision": no_collision,
        }
    )
    safety_failures = []
    if not no_collision:
        safety_failures.append("no_collision")
    if not obstacle_ok:
        safety_failures.append("obstacle_clearance")
    if not deviation_ok:
        safety_failures.append("route_deviation")
    if not corridor_ok:
        safety_failures.append("entry_corridor")

    if safety_failures:
        return EntryResult(
            stage=EntryStage.SAFE_STOP,
            task_id=route.task_id,
            bay_id=route.bay_id,
            slot_node_id=route.slot_node_id,
            approach_node_id=route.approach_node_id,
            route_id=route.route_id,
            route_hash=route.route_hash,
            entry_valid=False,
            completed=False,
            identity_verified=True,
            authorization_verified=True,
            checks=checks,
            reasons=tuple(safety_failures),
            measurement=measurement,
            stage_history=(EntryStage.PENDING, EntryStage.SAFE_STOP),
        )
    if not terminal_progress or not terminal_position or not terminal_heading:
        reasons = [
            "route_progress_terminal"
            if not terminal_progress
            else "",
            "terminal_position" if not terminal_position else "",
            "terminal_heading" if not terminal_heading else "",
        ]
        reasons = [reason for reason in reasons if reason]
        return EntryResult(
            stage=EntryStage.PENDING,
            task_id=route.task_id,
            bay_id=route.bay_id,
            slot_node_id=route.slot_node_id,
            approach_node_id=route.approach_node_id,
            route_id=route.route_id,
            route_hash=route.route_hash,
            entry_valid=False,
            completed=False,
            identity_verified=True,
            authorization_verified=True,
            checks=checks,
            reasons=tuple(reasons),
            measurement=measurement,
            stage_history=(EntryStage.PENDING,),
        )
    if not terminal_footprint or not terminal_boundary:
        reasons = []
        if not terminal_footprint:
            reasons.append("footprint_inside_bay")
        if not terminal_boundary:
            reasons.append("boundary_clearance")
        return EntryResult(
            stage=EntryStage.PENDING,
            task_id=route.task_id,
            bay_id=route.bay_id,
            slot_node_id=route.slot_node_id,
            approach_node_id=route.approach_node_id,
            route_id=route.route_id,
            route_hash=route.route_hash,
            entry_valid=False,
            completed=False,
            identity_verified=True,
            authorization_verified=True,
            checks=checks,
            reasons=tuple(reasons),
            measurement=measurement,
            stage_history=(EntryStage.PENDING,),
        )
    if not stopped_ok:
        return EntryResult(
            stage=EntryStage.SAFE_STOP,
            task_id=route.task_id,
            bay_id=route.bay_id,
            slot_node_id=route.slot_node_id,
            approach_node_id=route.approach_node_id,
            route_id=route.route_id,
            route_hash=route.route_hash,
            entry_valid=False,
            completed=False,
            identity_verified=True,
            authorization_verified=True,
            checks=checks,
            reasons=("stopped",),
            measurement=measurement,
            stage_history=(EntryStage.PENDING, EntryStage.SAFE_STOP),
        )
    if not stable_ok:
        return EntryResult(
            stage=EntryStage.VALID,
            task_id=route.task_id,
            bay_id=route.bay_id,
            slot_node_id=route.slot_node_id,
            approach_node_id=route.approach_node_id,
            route_id=route.route_id,
            route_hash=route.route_hash,
            entry_valid=True,
            completed=False,
            identity_verified=True,
            authorization_verified=True,
            checks=checks,
            reasons=("stop_stable_not_confirmed",),
            measurement=measurement,
            stage_history=(EntryStage.PENDING, EntryStage.VALID),
        )
    return EntryResult(
        stage=EntryStage.COMPLETED,
        task_id=route.task_id,
        bay_id=route.bay_id,
        slot_node_id=route.slot_node_id,
        approach_node_id=route.approach_node_id,
        route_id=route.route_id,
        route_hash=route.route_hash,
        entry_valid=True,
        completed=True,
        identity_verified=True,
        authorization_verified=True,
        checks=checks,
        reasons=(),
        measurement=measurement,
        stage_history=(EntryStage.PENDING, EntryStage.COMPLETED),
    )


def entry_round_improved(
    route: EntryRoute,
    *,
    before: EntryMeasurement,
    after: EntryMeasurement,
    segment: EntryRouteSegment,
) -> tuple[bool, tuple[str, ...]]:
    """Check that one bounded segment progressed safely and stopped."""

    if not isinstance(route, EntryRoute):
        raise TypeError("route must be an EntryRoute")
    if not isinstance(before, EntryMeasurement) or not isinstance(after, EntryMeasurement):
        raise TypeError("before/after must be EntryMeasurements")
    if not isinstance(segment, EntryRouteSegment):
        raise TypeError("segment must be an EntryRouteSegment")
    tol = route.tolerances
    reasons: list[str] = []
    if after.route_s <= before.route_s + 0.05:
        reasons.append("segment_no_progress")
    if after.route_deviation_m > tol.route_deviation_m:
        reasons.append("segment_route_deviation")
    if after.route_deviation_m > before.route_deviation_m + 0.20:
        reasons.append("segment_cross_track_worsened")
    if (
        after.obstacle_clearance_m is not None
        and after.obstacle_clearance_m < tol.obstacle_clearance_m
    ):
        reasons.append("segment_obstacle_clearance")
    if not after.footprint_corners_inside_corridor:
        reasons.append("segment_outside_entry_corridor")
    if not after.stopped or after.speed_mps >= tol.stop_speed_mps:
        reasons.append("segment_not_stopped")
    if after.collision_count:
        reasons.append("segment_collision")
    return (not reasons, tuple(reasons))


@dataclass(frozen=True)
class EntryAuthorization:
    authorization_id: str
    task_id: str
    bay_id: str
    slot_node_id: str
    approach_node_id: str
    alignment_completion_id: str
    alignment_authorization_id: str
    alignment_final_pose: tuple[float, float, float]
    route_id: str
    route_hash: str
    entry_target_pose: tuple[float, float, float]
    decision: str
    reason: str
    created_at: str
    expires_at: str
    consumed_at: Optional[str]
    revoked: bool
    max_segments: int
    max_segment_distance_m: float
    max_total_distance_m: float
    max_segment_sim_seconds: float
    max_total_sim_seconds: float
    speed_cap_mps: float
    tolerances: Mapping[str, object] = field(default_factory=dict)
    evidence: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.decision not in _DECISIONS:
            raise ValueError(f"unknown entry decision {self.decision!r}")
        for name in (
            "authorization_id",
            "task_id",
            "bay_id",
            "slot_node_id",
            "approach_node_id",
            "alignment_completion_id",
            "alignment_authorization_id",
            "route_id",
            "route_hash",
            "created_at",
            "expires_at",
        ):
            _nonblank(getattr(self, name), name)
        if len(self.alignment_final_pose) != 3 or len(self.entry_target_pose) != 3:
            raise ValueError("poses must be (x, y, yaw)")
        for value in (*self.alignment_final_pose, *self.entry_target_pose):
            _finite(value, "pose")
        _parse_time(self.created_at)
        _parse_time(self.expires_at)
        if _parse_time(self.expires_at) <= _parse_time(self.created_at):
            raise ValueError("expires_at must be after created_at")
        if self.consumed_at is not None:
            _parse_time(self.consumed_at)
        if type(self.revoked) is not bool:
            raise ValueError("revoked must be a bool")
        if type(self.max_segments) is not int or self.max_segments < 1:
            raise ValueError("max_segments must be a positive int")
        for name in (
            "max_segment_distance_m",
            "max_total_distance_m",
            "max_segment_sim_seconds",
            "max_total_sim_seconds",
            "speed_cap_mps",
        ):
            value = _finite(getattr(self, name), name)
            if value <= 0.0:
                raise ValueError(f"{name} must be positive")

    @property
    def permits_entry(self) -> bool:
        return self.decision == "ENTRY_AUTHORIZED" and not self.revoked

    @property
    def permits_alignment(self) -> bool:
        return False

    @property
    def permits_parking_arc(self) -> bool:
        """The declared route contains the validated arc; no generic arc grant."""

        return False

    @property
    def permits_parking_completed(self) -> bool:
        return False

    @property
    def executes_motion(self) -> bool:
        return False

    def is_expired(self, now: Optional[str] = None) -> bool:
        return _parse_time(now or _utc_now()) >= _parse_time(self.expires_at)

    def _identity_ok(
        self,
        *,
        task_id: str,
        bay_id: str,
        slot_node_id: str,
        approach_node_id: str,
        route_id: str,
        route_hash: str,
    ) -> bool:
        return (
            self.task_id == task_id
            and self.bay_id == bay_id
            and self.slot_node_id == slot_node_id
            and self.approach_node_id == approach_node_id
            and self.route_id == route_id
            and self.route_hash == route_hash
        )

    def is_usable(
        self,
        *,
        task_id: str,
        bay_id: str,
        slot_node_id: str,
        approach_node_id: str,
        route_id: str,
        route_hash: str,
        now: Optional[str] = None,
    ) -> bool:
        return (
            self.permits_entry
            and self.consumed_at is None
            and not self.is_expired(now)
            and self._identity_ok(
                task_id=task_id,
                bay_id=bay_id,
                slot_node_id=slot_node_id,
                approach_node_id=approach_node_id,
                route_id=route_id,
                route_hash=route_hash,
            )
        )

    def is_active(
        self,
        *,
        task_id: str,
        bay_id: str,
        slot_node_id: str,
        approach_node_id: str,
        route_id: str,
        route_hash: str,
        now: Optional[str] = None,
    ) -> bool:
        return (
            self.permits_entry
            and not self.is_expired(now)
            and self._identity_ok(
                task_id=task_id,
                bay_id=bay_id,
                slot_node_id=slot_node_id,
                approach_node_id=approach_node_id,
                route_id=route_id,
                route_hash=route_hash,
            )
        )

    def to_metadata(self) -> dict:
        return {
            "schema": "vln.parking.entry_authorization.v1",
            "skill": ENTRY_SKILL,
            "authorization_id": self.authorization_id,
            "task_id": self.task_id,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "approach_node_id": self.approach_node_id,
            "alignment_completion_id": self.alignment_completion_id,
            "alignment_authorization_id": self.alignment_authorization_id,
            "alignment_final_pose": {
                "x": round(self.alignment_final_pose[0], 4),
                "y": round(self.alignment_final_pose[1], 4),
                "yaw_deg": round(math.degrees(self.alignment_final_pose[2]), 4),
            },
            "route_id": self.route_id,
            "route_hash": self.route_hash,
            "entry_target_pose": {
                "x": round(self.entry_target_pose[0], 4),
                "y": round(self.entry_target_pose[1], 4),
                "yaw_deg": round(math.degrees(self.entry_target_pose[2]), 4),
            },
            "decision": self.decision,
            "reason": self.reason,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "consumed_at": self.consumed_at,
            "revoked": self.revoked,
            "stage_scope": "ENTRY",
            "permits_entry": self.permits_entry,
            "permits_alignment": False,
            "permits_parking_arc": False,
            "permits_parking_completed": False,
            "executes_motion": False,
            "single_use": True,
            "budget": {
                "max_segments": self.max_segments,
                "max_segment_distance_m": self.max_segment_distance_m,
                "max_total_distance_m": self.max_total_distance_m,
                "max_segment_sim_seconds": self.max_segment_sim_seconds,
                "max_total_sim_seconds": self.max_total_sim_seconds,
                "speed_cap_mps": self.speed_cap_mps,
            },
            "tolerances": dict(self.tolerances),
            "evidence": dict(self.evidence),
        }


def _entry_authorization_id(
    *,
    task_id: str,
    bay_id: str,
    slot_node_id: str,
    approach_node_id: str,
    alignment_completion_id: str,
    alignment_authorization_id: str,
    route_id: str,
    route_hash: str,
    decision: str,
    created_at: str,
) -> str:
    return _sha256_json(
        {
            "task_id": task_id,
            "bay_id": bay_id,
            "slot_node_id": slot_node_id,
            "approach_node_id": approach_node_id,
            "alignment_completion_id": alignment_completion_id,
            "alignment_authorization_id": alignment_authorization_id,
            "route_id": route_id,
            "route_hash": route_hash,
            "decision": decision,
            "created_at": created_at,
        }
    )


def authorize_entry(
    completion: AlignmentCompletion,
    route: EntryRoute,
    *,
    binding: object,
    task_id: str,
    now: Optional[str] = None,
    ttl_s: float = 600.0,
    max_completion_age_s: float = 86400.0,
    budget: Optional[EntryBudget] = None,
    actual_pose: Optional[Sequence[float]] = None,
    pose_tolerance_m: float = 0.15,
    heading_tolerance_deg: float = 2.0,
    terminal_correction_policy: Optional[Mapping[str, object]] = None,
) -> EntryAuthorization:
    """Issue the single-use Entry stage permission.

    The only precondition is the accepted Alignment completion plus the current
    binding and the actual pose. The CAP-07B-03 ``ALIGNMENT_AUTHORIZED`` is
    referenced as evidence (its id is bound), but it is **not** reused as an
    Entry motion permission.
    """

    if not isinstance(completion, AlignmentCompletion):
        raise TypeError("completion must be an AlignmentCompletion")
    if not isinstance(route, EntryRoute):
        raise TypeError("route must be an EntryRoute")
    if binding is None:
        raise ValueError("binding is required")
    if getattr(binding, "status", None) != "bound":
        raise ValueError("binding is not bound")
    if getattr(binding, "bay_id", None) != route.bay_id:
        raise ValueError("binding bay does not match the entry route")
    if getattr(binding, "slot_node_id", None) != route.slot_node_id:
        raise ValueError("binding slot does not match the entry route")
    _nonblank(task_id, "task_id")
    if task_id == completion.task_id:
        raise ValueError("entry must run under its own task id")
    if completion.task_id == route.task_id:
        raise ValueError("alignment completion and entry task collide")
    if not alignment_completion_is_usable(
        completion,
        binding=binding,
        route=route,
        now=now,
        max_age_s=max_completion_age_s,
    ):
        raise ValueError("alignment completion is not usable for this route/binding")
    if completion.verification_stage != ALIGNMENT_COMPLETED_STAGE:
        raise ValueError("alignment completion is not ALIGNMENT_COMPLETED")
    if completion.bay_id != route.bay_id or completion.slot_node_id != route.slot_node_id:
        raise ValueError("alignment completion identity does not match the route")
    if completion.approach_node_id != route.approach_node_id:
        raise ValueError("alignment completion approach does not match the route")
    if actual_pose is not None:
        if len(actual_pose) != 3:
            raise ValueError("actual_pose must be (x, y, yaw)")
        pose_tol = _finite(pose_tolerance_m, "pose_tolerance_m")
        heading_tol = _finite(heading_tolerance_deg, "heading_tolerance_deg")
        distance = math.hypot(
            float(actual_pose[0]) - completion.final_pose[0],
            float(actual_pose[1]) - completion.final_pose[1],
        )
        heading_error = abs(
            wrap_degrees(
                math.degrees(float(actual_pose[2]) - completion.final_pose[2])
            )
        )
        if distance > pose_tol:
            raise ValueError(
                f"actual pose is {distance:.3f} m from the alignment final pose"
            )
        if heading_error > heading_tol:
            raise ValueError(
                f"actual heading is {heading_error:.3f} deg from alignment final"
            )
    ttl = _finite(ttl_s, "ttl_s")
    if ttl <= 0.0:
        raise ValueError("ttl_s must be positive")
    entry_budget = budget or EntryBudget()
    if not isinstance(entry_budget, EntryBudget):
        raise TypeError("budget must be an EntryBudget")
    created_at = now or _utc_now()
    created = _parse_time(created_at)
    expires_at = datetime.fromtimestamp(
        created.timestamp() + ttl, timezone.utc
    ).isoformat()
    return EntryAuthorization(
        authorization_id=_entry_authorization_id(
            task_id=task_id,
            bay_id=route.bay_id,
            slot_node_id=route.slot_node_id,
            approach_node_id=route.approach_node_id,
            alignment_completion_id=completion.completion_id,
            alignment_authorization_id=completion.alignment_authorization_id,
            route_id=route.route_id,
            route_hash=route.route_hash,
            decision="ENTRY_AUTHORIZED",
            created_at=created_at,
        ),
        task_id=task_id,
        bay_id=route.bay_id,
        slot_node_id=route.slot_node_id,
        approach_node_id=route.approach_node_id,
        alignment_completion_id=completion.completion_id,
        alignment_authorization_id=completion.alignment_authorization_id,
        alignment_final_pose=completion.final_pose,
        route_id=route.route_id,
        route_hash=route.route_hash,
        entry_target_pose=(
            route.target_pose[0],
            route.target_pose[1],
            route.target_heading_rad,
        ),
        decision="ENTRY_AUTHORIZED",
        reason=(
            "ALIGNMENT_COMPLETED evidence is current; this permission covers "
            "the declared Entry route only"
        ),
        created_at=created_at,
        expires_at=expires_at,
        consumed_at=None,
        revoked=False,
        max_segments=entry_budget.max_segments,
        max_segment_distance_m=entry_budget.max_segment_distance_m,
        max_total_distance_m=entry_budget.max_total_distance_m,
        max_segment_sim_seconds=entry_budget.max_segment_sim_seconds,
        max_total_sim_seconds=entry_budget.max_total_sim_seconds,
        speed_cap_mps=entry_budget.speed_cap_mps,
        tolerances=route.tolerances.to_metadata(),
        evidence={
            "completion": completion.to_metadata(),
            "route": route.to_metadata(),
            "terminal_correction_policy": (
                dict(terminal_correction_policy)
                if terminal_correction_policy is not None
                else None
            ),
        },
    )


def entry_refusal_authorization(
    route: EntryRoute,
    decision: str,
    reason: str,
    *,
    task_id: str,
    completion_id: str = "none",
    alignment_authorization_id: str = "none",
    now: Optional[str] = None,
) -> EntryAuthorization:
    if decision not in ("UNVERIFIED", "REJECTED", "SAFE_STOP"):
        raise ValueError("refusal decision must be UNVERIFIED/REJECTED/SAFE_STOP")
    _nonblank(task_id, "task_id")
    _nonblank(completion_id, "completion_id")
    _nonblank(alignment_authorization_id, "alignment_authorization_id")
    created_at = now or _utc_now()
    created = _parse_time(created_at)
    expires = datetime.fromtimestamp(
        created.timestamp() + 60.0, timezone.utc
    ).isoformat()
    return EntryAuthorization(
        authorization_id=_entry_authorization_id(
            task_id=task_id,
            bay_id=route.bay_id,
            slot_node_id=route.slot_node_id,
            approach_node_id=route.approach_node_id,
            alignment_completion_id=completion_id,
            alignment_authorization_id=alignment_authorization_id,
            route_id=route.route_id,
            route_hash=route.route_hash,
            decision=decision,
            created_at=created_at,
        ),
        task_id=task_id,
        bay_id=route.bay_id,
        slot_node_id=route.slot_node_id,
        approach_node_id=route.approach_node_id,
        alignment_completion_id=completion_id,
        alignment_authorization_id=alignment_authorization_id,
        alignment_final_pose=(0.0, 0.0, 0.0),
        route_id=route.route_id,
        route_hash=route.route_hash,
        entry_target_pose=(
            route.target_pose[0],
            route.target_pose[1],
            route.target_heading_rad,
        ),
        decision=decision,
        reason=reason,
        created_at=created_at,
        expires_at=expires,
        consumed_at=None,
        revoked=False,
        max_segments=1,
        max_segment_distance_m=0.01,
        max_total_distance_m=0.01,
        max_segment_sim_seconds=1.0,
        max_total_sim_seconds=1.0,
        speed_cap_mps=0.01,
        tolerances=route.tolerances.to_metadata(),
    )


def entry_authorization_from_metadata(
    metadata: Mapping[str, object],
) -> EntryAuthorization:
    if not isinstance(metadata, Mapping):
        raise ValueError("entry authorization must be a JSON object")
    schema = metadata.get("schema")
    if schema not in (None, "vln.parking.entry_authorization.v1"):
        raise ValueError(f"unexpected entry authorization schema {schema!r}")
    budget = metadata.get("budget")
    if not isinstance(budget, Mapping):
        raise ValueError("entry authorization has no budget")
    tolerances = metadata.get("tolerances")
    if not isinstance(tolerances, Mapping):
        raise ValueError("entry authorization has no tolerances")
    final = metadata.get("alignment_final_pose")
    target = metadata.get("entry_target_pose")
    if not isinstance(final, Mapping) or not isinstance(target, Mapping):
        raise ValueError("entry authorization poses are missing")

    def _pose(value: Mapping[str, object]) -> tuple[float, float, float]:
        return (
            float(value["x"]),
            float(value["y"]),
            math.radians(float(value["yaw_deg"])),
        )

    return EntryAuthorization(
        authorization_id=metadata.get("authorization_id"),
        task_id=metadata.get("task_id"),
        bay_id=metadata.get("bay_id"),
        slot_node_id=metadata.get("slot_node_id"),
        approach_node_id=metadata.get("approach_node_id"),
        alignment_completion_id=metadata.get("alignment_completion_id"),
        alignment_authorization_id=metadata.get("alignment_authorization_id"),
        alignment_final_pose=_pose(final),
        route_id=metadata.get("route_id"),
        route_hash=metadata.get("route_hash"),
        entry_target_pose=_pose(target),
        decision=metadata.get("decision"),
        reason=metadata.get("reason", ""),
        created_at=metadata.get("created_at"),
        expires_at=metadata.get("expires_at"),
        consumed_at=metadata.get("consumed_at"),
        revoked=metadata.get("revoked", False),
        max_segments=budget.get("max_segments"),
        max_segment_distance_m=budget.get("max_segment_distance_m"),
        max_total_distance_m=budget.get("max_total_distance_m"),
        max_segment_sim_seconds=budget.get("max_segment_sim_seconds"),
        max_total_sim_seconds=budget.get("max_total_sim_seconds"),
        speed_cap_mps=budget.get("speed_cap_mps"),
        tolerances=tolerances,
        evidence=metadata.get("evidence", {}),
    )


def consume_entry_authorization(
    authorization: EntryAuthorization,
    *,
    task_id: str,
    bay_id: str,
    slot_node_id: str,
    approach_node_id: str,
    route_id: str,
    route_hash: str,
    now: Optional[str] = None,
) -> EntryAuthorization:
    if not isinstance(authorization, EntryAuthorization):
        raise TypeError("authorization must be an EntryAuthorization")
    if not authorization.is_usable(
        task_id=task_id,
        bay_id=bay_id,
        slot_node_id=slot_node_id,
        approach_node_id=approach_node_id,
        route_id=route_id,
        route_hash=route_hash,
        now=now,
    ):
        raise EntryAuthorizationError(
            "entry authorization is absent, for another task/route, already "
            "consumed, revoked or expired"
        )
    return replace(authorization, consumed_at=now or _utc_now())


def revoke_entry_authorization(
    authorization: EntryAuthorization,
    reason: str,
    *,
    now: Optional[str] = None,
) -> EntryAuthorization:
    if not isinstance(authorization, EntryAuthorization):
        raise TypeError("authorization must be an EntryAuthorization")
    _nonblank(reason, "reason")
    _parse_time(now or _utc_now())
    return replace(authorization, revoked=True, reason=reason)


def require_entry_authorization(
    authorization: EntryAuthorization,
    *,
    task_id: str,
    bay_id: str,
    slot_node_id: str,
    approach_node_id: str,
    route_id: str,
    route_hash: str,
    now: Optional[str] = None,
) -> None:
    if not isinstance(authorization, EntryAuthorization):
        raise EntryAuthorizationError(
            "entry stage requires an EntryAuthorization; an Alignment "
            "permission is not an entry permission"
        )
    if not authorization.is_usable(
        task_id=task_id,
        bay_id=bay_id,
        slot_node_id=slot_node_id,
        approach_node_id=approach_node_id,
        route_id=route_id,
        route_hash=route_hash,
        now=now,
    ):
        raise EntryAuthorizationError(
            "entry authorization is absent, for another task/route, already "
            "consumed, revoked or expired"
        )
