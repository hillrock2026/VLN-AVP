"""Parking Pose Refinement stage for bay03.

CAP-07B-05 starts from a real ``ENTRY_COMPLETED`` state and asks whether the
vehicle can improve its in-bay pose without reducing the current safety
margin. It does **not** produce ``PARKING_COMPLETED``.

The module is pure and independent of the controller:

* :func:`generate_candidates` searches a small pose grid around the bay centre
  and rejects every pose whose rotated footprint is not fully inside the bay,
  lacks boundary clearance or lacks obstacle clearance.
* :func:`measure_refinement` computes the same independent geometry from a real
  CARLA pose.
* :func:`verify_refinement` decides ``PARKING_POSE_READY`` only from the real
  final state, the Entry completion identity, the refinement authorization and
  the accepted path hash.
* :class:`RefinementAuthorization` is a single-use, expiring, revocable stage
  permission. Every actual motion still needs a separate Agent-Kernel permit.
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
    "REFINEMENT_SKILL",
    "RefinementStage",
    "RefinementTolerances",
    "RefinementBudget",
    "CandidatePose",
    "RefinementSelection",
    "RefinementMeasurement",
    "RefinementResult",
    "RefinementAuthorization",
    "RefinementAuthorizationError",
    "generate_candidates",
    "select_candidate",
    "measure_refinement",
    "measure_stability",
    "verify_refinement",
    "refinement_phase_improved",
    "no_safe_refinement_result",
    "compute_entry_completion_id",
    "authorize_refinement",
    "consume_refinement_authorization",
    "revoke_refinement_authorization",
    "refinement_authorization_from_metadata",
    "wrap_degrees",
]

REFINEMENT_SKILL = "vln.parking.refinement"


class RefinementStage:
    PENDING = "REFINEMENT_PENDING"
    AUTHORIZED = "REFINEMENT_AUTHORIZED"
    EXECUTING = "REFINEMENT_EXECUTING"
    VALID = "REFINEMENT_VALID"
    READY = "PARKING_POSE_READY"
    NO_SAFE = "NO_SAFE_REFINEMENT"
    FAILED = "REFINEMENT_FAILED"
    SAFE_STOP = "SAFE_STOP"

    ALL = frozenset(
        {
            PENDING,
            AUTHORIZED,
            EXECUTING,
            VALID,
            READY,
            NO_SAFE,
            FAILED,
            SAFE_STOP,
        }
    )


class RefinementAuthorizationError(RuntimeError):
    """A refinement permission is absent, for another task/plan, or not current."""


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
    return (float(value) + 180.0) % 360.0 - 180.0


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class RefinementTolerances:
    """Thresholds fixed before the CAP-07B-05 run.

    The accepted Entry pose has boundary clearance 0.052 m against the existing
    0.05 m floor. A refinement target of 0.10 m is twice that floor, while the
    path must never reduce the current clearance (the planner uses the real
    current value as its floor). The heading target 2.5 deg is half the existing
    5 deg final-parking heading gate; it is a real improvement over the Entry
    residual of 3.45 deg without claiming a final-parking result.
    """

    target_heading_deg: float = 2.5
    target_position_m: float = 0.15
    target_boundary_clearance_m: float = 0.10
    target_obstacle_clearance_m: float = 0.20
    stop_speed_mps: float = 0.05
    stable_drift_m: float = 0.02
    stable_samples: int = 3
    reverse_max_distance_m: float = 1.8
    reverse_speed_cap_mps: float = 0.10
    reverse_max_sim_seconds: float = 30.0
    forward_max_distance_m: float = 2.0
    forward_speed_cap_mps: float = 0.10
    forward_max_sim_seconds: float = 30.0
    #: Calibrated from the CAP-07B-04 real low-speed response (about 1/6 of the
    #: kinematic bicycle model). Used only by the offline path plan.
    yaw_response_factor: float = 0.16

    def __post_init__(self) -> None:
        for name in (
            "target_heading_deg",
            "target_position_m",
            "target_boundary_clearance_m",
            "target_obstacle_clearance_m",
            "stop_speed_mps",
            "stable_drift_m",
            "reverse_max_distance_m",
            "reverse_speed_cap_mps",
            "reverse_max_sim_seconds",
            "forward_max_distance_m",
            "forward_speed_cap_mps",
            "forward_max_sim_seconds",
            "yaw_response_factor",
        ):
            value = _finite(getattr(self, name), name)
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative")
        if not 0.0 < self.yaw_response_factor <= 1.5:
            raise ValueError("yaw_response_factor must be in (0, 1.5]")
        if type(self.stable_samples) is not int or self.stable_samples < 3:
            raise ValueError("stable_samples must be an int >= 3")

    def to_metadata(self) -> dict:
        return {
            "target_heading_deg": self.target_heading_deg,
            "target_position_m": self.target_position_m,
            "target_boundary_clearance_m": self.target_boundary_clearance_m,
            "target_obstacle_clearance_m": self.target_obstacle_clearance_m,
            "stop_speed_mps": self.stop_speed_mps,
            "stable_drift_m": self.stable_drift_m,
            "stable_samples": self.stable_samples,
            "reverse_max_distance_m": self.reverse_max_distance_m,
            "reverse_speed_cap_mps": self.reverse_speed_cap_mps,
            "reverse_max_sim_seconds": self.reverse_max_sim_seconds,
            "forward_max_distance_m": self.forward_max_distance_m,
            "forward_speed_cap_mps": self.forward_speed_cap_mps,
            "forward_max_sim_seconds": self.forward_max_sim_seconds,
            "yaw_response_factor": self.yaw_response_factor,
        }


@dataclass(frozen=True)
class RefinementBudget:
    max_segments: int = 2
    max_segment_distance_m: float = 2.0
    max_total_distance_m: float = 4.0
    max_segment_sim_seconds: float = 30.0
    max_total_sim_seconds: float = 60.0
    speed_cap_mps: float = 0.10
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

    def record_segment(self, travelled_m: float, sim_seconds: float) -> "RefinementBudget":
        travelled = _finite(travelled_m, "travelled_m")
        sim = _finite(sim_seconds, "sim_seconds")
        if travelled < 0.0 or sim < 0.0:
            raise ValueError("segment travel/time must be non-negative")
        if not self.can_start_segment:
            raise ValueError("refinement budget is exhausted")
        return RefinementBudget(
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
            "can_start_segment": self.can_start_segment,
        }


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
class CandidatePose:
    x: float
    y: float
    heading_rad: float
    heading_error_deg: float
    distance_to_center_m: float
    footprint_corners: tuple[tuple[float, float], ...]
    footprint_inside_bay: bool
    boundary_clearance_m: Optional[float]
    obstacle_clearance_m: Optional[float]
    accepted: bool
    reasons: tuple[str, ...] = ()

    def to_metadata(self) -> dict:
        return {
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "heading_rad": round(self.heading_rad, 6),
            "heading_deg": round(math.degrees(self.heading_rad), 4),
            "heading_error_deg": round(self.heading_error_deg, 4),
            "distance_to_center_m": round(self.distance_to_center_m, 4),
            "footprint_corners": [[round(x, 4), round(y, 4)] for x, y in self.footprint_corners],
            "footprint_inside_bay": self.footprint_inside_bay,
            "boundary_clearance_m": None if self.boundary_clearance_m is None else round(self.boundary_clearance_m, 4),
            "obstacle_clearance_m": None if self.obstacle_clearance_m is None else round(self.obstacle_clearance_m, 4),
            "accepted": self.accepted,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class RefinementSelection:
    current: CandidatePose
    candidates: tuple[CandidatePose, ...]
    selected: Optional[CandidatePose]
    reasons: tuple[str, ...]
    grid: Mapping[str, object]

    @property
    def ok(self) -> bool:
        return self.selected is not None

    def to_metadata(self) -> dict:
        return {
            "current": self.current.to_metadata(),
            "selected": None if self.selected is None else self.selected.to_metadata(),
            "candidates": [candidate.to_metadata() for candidate in self.candidates],
            "reasons": list(self.reasons),
            "grid": dict(self.grid),
        }


def _candidate(
    *,
    x: float,
    y: float,
    heading_rad: float,
    center: tuple[float, float],
    bay_heading_rad: float,
    bay_polygon,
    footprint: Footprint,
    obstacle_points,
    tolerances: RefinementTolerances,
) -> CandidatePose:
    corners = footprint.corners(x, y, heading_rad)
    inside = all(_point_in_polygon(px, py, bay_polygon) for px, py in corners)
    boundary = footprint_polygon_clearance(
        x, y, heading_rad, footprint, bay_polygon
    )["min_clearance_m"]
    obstacle = None
    if obstacle_points:
        obstacle = footprint_clearance(
            x, y, heading_rad, footprint, obstacle_points
        )["min_clearance_m"]
    heading_error = wrap_degrees(math.degrees(heading_rad - bay_heading_rad))
    distance_center = math.hypot(x - center[0], y - center[1])
    reasons = []
    if not inside:
        reasons.append("footprint_not_inside_bay")
    if boundary is None or boundary < tolerances.target_boundary_clearance_m:
        reasons.append("boundary_clearance")
    if obstacle is not None and obstacle < tolerances.target_obstacle_clearance_m:
        reasons.append("obstacle_clearance")
    if abs(heading_error) > tolerances.target_heading_deg:
        reasons.append("heading")
    return CandidatePose(
        x=x,
        y=y,
        heading_rad=heading_rad,
        heading_error_deg=heading_error,
        distance_to_center_m=distance_center,
        footprint_corners=tuple(corners),
        footprint_inside_bay=inside,
        boundary_clearance_m=boundary,
        obstacle_clearance_m=obstacle,
        accepted=not reasons,
        reasons=tuple(reasons),
    )


def generate_candidates(
    *,
    current_x: float,
    current_y: float,
    current_heading_rad: float,
    center: tuple[float, float],
    bay_heading_rad: float,
    bay_polygon,
    footprint: Footprint,
    obstacle_points: Sequence[Sequence[float]] = (),
    tolerances: Optional[RefinementTolerances] = None,
    offsets_m: Sequence[float] = (-0.10, -0.05, 0.0, 0.05, 0.10),
    heading_offsets_deg: Sequence[float] = (-2.0, -1.0, 0.0, 1.0, 2.0),
) -> RefinementSelection:
    """Search a small bay-centred pose grid and filter by independent geometry."""

    tolerances = tolerances or RefinementTolerances()
    center = (float(center[0]), float(center[1]))
    current = _candidate(
        x=float(current_x),
        y=float(current_y),
        heading_rad=float(current_heading_rad),
        center=center,
        bay_heading_rad=float(bay_heading_rad),
        bay_polygon=bay_polygon,
        footprint=footprint,
        obstacle_points=obstacle_points,
        tolerances=tolerances,
    )
    candidates: list[CandidatePose] = []
    for dx in offsets_m:
        for dy in offsets_m:
            for dh in heading_offsets_deg:
                candidates.append(
                    _candidate(
                        x=center[0] + dx,
                        y=center[1] + dy,
                        heading_rad=bay_heading_rad + math.radians(dh),
                        center=center,
                        bay_heading_rad=bay_heading_rad,
                        bay_polygon=bay_polygon,
                        footprint=footprint,
                        obstacle_points=obstacle_points,
                        tolerances=tolerances,
                    )
                )
    accepted = [candidate for candidate in candidates if candidate.accepted]
    selected = None
    reasons: list[str] = []
    if accepted:
        selected = sorted(
            accepted,
            key=lambda item: (
                -float(item.boundary_clearance_m or 0.0),
                abs(item.heading_error_deg),
                item.distance_to_center_m,
                abs(item.x - current_x),
                abs(item.y - current_y),
            ),
        )[0]
        heading_improved = abs(selected.heading_error_deg) <= abs(
            current.heading_error_deg
        ) - 0.5
        clearance_improved = (
            selected.boundary_clearance_m is not None
            and current.boundary_clearance_m is not None
            and selected.boundary_clearance_m >= current.boundary_clearance_m + 0.03
        )
        if not heading_improved:
            reasons.append("selected_heading_not_improved")
        if not clearance_improved:
            reasons.append("selected_clearance_not_improved")
        if reasons:
            selected = None
    else:
        reasons.append("no_candidate_passes_independent_geometry")
    return RefinementSelection(
        current=current,
        candidates=tuple(candidates),
        selected=selected,
        reasons=tuple(reasons),
        grid={
            "offsets_m": list(offsets_m),
            "heading_offsets_deg": list(heading_offsets_deg),
            "center": list(center),
            "bay_heading_deg": round(math.degrees(bay_heading_rad), 4),
            "accepted_count": len(accepted),
            "total_count": len(candidates),
        },
    )


def select_candidate(selection: RefinementSelection) -> CandidatePose:
    if not isinstance(selection, RefinementSelection):
        raise TypeError("selection must be a RefinementSelection")
    if selection.selected is None:
        raise ValueError("no refinement candidate was selected")
    return selection.selected


@dataclass(frozen=True)
class RefinementStability:
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
    tolerances: RefinementTolerances,
) -> RefinementStability:
    if not isinstance(tolerances, RefinementTolerances):
        raise TypeError("tolerances must be RefinementTolerances")
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
        return RefinementStability(0, 0.0, 0.0, False)
    x0, y0, _ = checked[0]
    drift = max(math.hypot(x - x0, y - y0) for x, y, _ in checked)
    max_speed = max(speed for _, _, speed in checked)
    stable = (
        len(checked) >= tolerances.stable_samples
        and max_speed < tolerances.stop_speed_mps
        and drift <= tolerances.stable_drift_m
    )
    return RefinementStability(len(checked), max_speed, drift, stable)


@dataclass(frozen=True)
class RefinementMeasurement:
    x: float
    y: float
    yaw_rad: float
    speed_mps: float
    stopped: bool
    heading_error_deg: float
    lateral_error_m: float
    longitudinal_error_m: float
    distance_to_center_m: float
    footprint_corners: tuple[tuple[float, float], ...]
    footprint_inside_bay: bool
    boundary_clearance_m: Optional[float]
    obstacle_clearance_m: Optional[float]
    stability: RefinementStability
    collision_count: int

    def to_metadata(self) -> dict:
        return {
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "yaw_rad": round(self.yaw_rad, 6),
            "yaw_deg": round(math.degrees(self.yaw_rad), 4),
            "speed_mps": round(self.speed_mps, 4),
            "stopped": self.stopped,
            "heading_error_deg": round(self.heading_error_deg, 4),
            "lateral_error_m": round(self.lateral_error_m, 4),
            "longitudinal_error_m": round(self.longitudinal_error_m, 4),
            "distance_to_center_m": round(self.distance_to_center_m, 4),
            "footprint_corners": [[round(x, 4), round(y, 4)] for x, y in self.footprint_corners],
            "footprint_inside_bay": self.footprint_inside_bay,
            "boundary_clearance_m": None if self.boundary_clearance_m is None else round(self.boundary_clearance_m, 4),
            "obstacle_clearance_m": None if self.obstacle_clearance_m is None else round(self.obstacle_clearance_m, 4),
            "stability": self.stability.to_metadata(),
            "collision_count": self.collision_count,
        }


def measure_refinement(
    *,
    x: float,
    y: float,
    yaw_rad: float,
    speed_mps: float,
    stopped: bool,
    center: tuple[float, float],
    bay_heading_rad: float,
    bay_polygon,
    footprint: Footprint,
    obstacle_points: Sequence[Sequence[float]] = (),
    stability: Optional[RefinementStability] = None,
    collision_count: int = 0,
) -> RefinementMeasurement:
    x = _finite(x, "x")
    y = _finite(y, "y")
    yaw_rad = _finite(yaw_rad, "yaw_rad")
    speed = _finite(speed_mps, "speed_mps")
    if speed < 0.0:
        raise ValueError("speed_mps must be non-negative")
    if type(stopped) is not bool:
        raise ValueError("stopped must be a bool")
    if type(collision_count) is not int or collision_count < 0:
        raise ValueError("collision_count must be a non-negative int")
    stability = stability or RefinementStability(0, speed, 0.0, False)
    forward = (math.cos(bay_heading_rad), math.sin(bay_heading_rad))
    left = (-forward[1], forward[0])
    dx, dy = x - center[0], y - center[1]
    lateral = dx * left[0] + dy * left[1]
    longitudinal = dx * forward[0] + dy * forward[1]
    corners = footprint.corners(x, y, yaw_rad)
    inside = all(_point_in_polygon(px, py, bay_polygon) for px, py in corners)
    boundary = footprint_polygon_clearance(
        x, y, yaw_rad, footprint, bay_polygon
    )["min_clearance_m"]
    obstacle = None
    if obstacle_points:
        obstacle = footprint_clearance(
            x, y, yaw_rad, footprint, obstacle_points
        )["min_clearance_m"]
    return RefinementMeasurement(
        x=x,
        y=y,
        yaw_rad=yaw_rad,
        speed_mps=speed,
        stopped=stopped,
        heading_error_deg=wrap_degrees(math.degrees(yaw_rad - bay_heading_rad)),
        lateral_error_m=lateral,
        longitudinal_error_m=longitudinal,
        distance_to_center_m=math.hypot(dx, dy),
        footprint_corners=tuple(corners),
        footprint_inside_bay=inside,
        boundary_clearance_m=boundary,
        obstacle_clearance_m=obstacle,
        stability=stability,
        collision_count=collision_count,
    )


@dataclass(frozen=True)
class RefinementResult:
    stage: str
    task_id: str
    bay_id: str
    slot_node_id: str
    entry_completion_id: str
    plan_hash: Optional[str]
    identity_verified: bool
    authorization_verified: bool
    checks: Mapping[str, bool]
    reasons: tuple[str, ...]
    measurement: Optional[RefinementMeasurement]
    stage_history: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.stage not in RefinementStage.ALL:
            raise ValueError(f"unknown refinement stage {self.stage!r}")
        if self.stage == RefinementStage.READY and self.reasons:
            raise ValueError("PARKING_POSE_READY cannot carry failure reasons")
        if self.stage in (RefinementStage.FAILED, RefinementStage.SAFE_STOP) and not self.reasons:
            raise ValueError("a failed/safe-stop refinement needs a reason")

    @property
    def ready(self) -> bool:
        return self.stage == RefinementStage.READY

    def to_metadata(self) -> dict:
        return {
            "schema": "vln.parking.refinement_result.v1",
            "skill": REFINEMENT_SKILL,
            "stage": self.stage,
            "task_id": self.task_id,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "entry_completion_id": self.entry_completion_id,
            "plan_hash": self.plan_hash,
            "identity_verified": self.identity_verified,
            "authorization_verified": self.authorization_verified,
            "ready": self.ready,
            "parking_completed": False,
            "checks": dict(self.checks),
            "reasons": list(self.reasons),
            "measurement": None if self.measurement is None else self.measurement.to_metadata(),
            "stage_history": list(self.stage_history),
        }


def _check_measurement(
    measurement: RefinementMeasurement,
    tolerances: RefinementTolerances,
) -> dict:
    return {
        "footprint_inside_bay": measurement.footprint_inside_bay,
        "boundary_clearance": (
            measurement.boundary_clearance_m is not None
            and measurement.boundary_clearance_m
            >= tolerances.target_boundary_clearance_m
        ),
        "obstacle_clearance": (
            measurement.obstacle_clearance_m is None
            or measurement.obstacle_clearance_m
            >= tolerances.target_obstacle_clearance_m
        ),
        "heading": abs(measurement.heading_error_deg)
        <= tolerances.target_heading_deg,
        "position": measurement.distance_to_center_m
        <= tolerances.target_position_m,
        "stopped": measurement.stopped
        and measurement.speed_mps < tolerances.stop_speed_mps,
        "stop_stable": measurement.stability.stable,
        "no_collision": measurement.collision_count == 0,
    }


def verify_refinement(
    *,
    task_id: str,
    bay_id: str,
    slot_node_id: str,
    entry_completion_id: str,
    plan_hash: Optional[str],
    authorization: Optional["RefinementAuthorization"],
    measurement: Optional[RefinementMeasurement],
    tolerances: Optional[RefinementTolerances] = None,
    now: Optional[str] = None,
) -> RefinementResult:
    tolerances = tolerances or RefinementTolerances()
    if measurement is None or authorization is None:
        return RefinementResult(
            stage=RefinementStage.FAILED,
            task_id=task_id,
            bay_id=bay_id,
            slot_node_id=slot_node_id,
            entry_completion_id=entry_completion_id,
            plan_hash=plan_hash,
            identity_verified=False,
            authorization_verified=False,
            checks={"authorization_present": authorization is not None, "state_present": measurement is not None},
            reasons=("refinement_state_or_authorization_missing",),
            measurement=measurement,
            stage_history=(RefinementStage.PENDING, RefinementStage.FAILED),
        )
    identity_ok = (
        authorization.bay_id == bay_id
        and authorization.slot_node_id == slot_node_id
        and authorization.entry_completion_id == entry_completion_id
        and authorization.plan_hash == plan_hash
    )
    auth_ok = identity_ok and authorization.is_active(
        task_id=task_id,
        bay_id=bay_id,
        slot_node_id=slot_node_id,
        entry_completion_id=entry_completion_id,
        plan_hash=plan_hash,
        now=now,
    )
    checks = {
        "identity": identity_ok,
        "authorization": auth_ok,
    }
    if not auth_ok:
        return RefinementResult(
            stage=RefinementStage.FAILED,
            task_id=task_id,
            bay_id=bay_id,
            slot_node_id=slot_node_id,
            entry_completion_id=entry_completion_id,
            plan_hash=plan_hash,
            identity_verified=identity_ok,
            authorization_verified=False,
            checks=checks,
            reasons=("refinement_authorization_inactive",),
            measurement=measurement,
            stage_history=(RefinementStage.PENDING, RefinementStage.FAILED),
        )
    checks.update(
        _check_measurement(measurement, tolerances)
    )
    safety_keys = ("footprint_inside_bay", "obstacle_clearance", "no_collision")
    if not all(checks[name] for name in safety_keys):
        return RefinementResult(
            stage=RefinementStage.SAFE_STOP,
            task_id=task_id,
            bay_id=bay_id,
            slot_node_id=slot_node_id,
            entry_completion_id=entry_completion_id,
            plan_hash=plan_hash,
            identity_verified=True,
            authorization_verified=True,
            checks=checks,
            reasons=tuple(name for name in safety_keys if not checks[name]),
            measurement=measurement,
            stage_history=(RefinementStage.PENDING, RefinementStage.SAFE_STOP),
        )
    if not all(checks.values()):
        if (
            checks["heading"]
            and checks["position"]
            and checks["boundary_clearance"]
            and not checks["stop_stable"]
        ):
            return RefinementResult(
                stage=RefinementStage.VALID,
                task_id=task_id,
                bay_id=bay_id,
                slot_node_id=slot_node_id,
                entry_completion_id=entry_completion_id,
                plan_hash=plan_hash,
                identity_verified=True,
                authorization_verified=True,
                checks=checks,
                reasons=("stop_stable_not_confirmed",),
                measurement=measurement,
                stage_history=(RefinementStage.PENDING, RefinementStage.VALID),
            )
        return RefinementResult(
            stage=RefinementStage.FAILED,
            task_id=task_id,
            bay_id=bay_id,
            slot_node_id=slot_node_id,
            entry_completion_id=entry_completion_id,
            plan_hash=plan_hash,
            identity_verified=True,
            authorization_verified=True,
            checks=checks,
            reasons=tuple(name for name, passed in checks.items() if not passed),
            measurement=measurement,
            stage_history=(RefinementStage.PENDING, RefinementStage.FAILED),
        )
    return RefinementResult(
        stage=RefinementStage.READY,
        task_id=task_id,
        bay_id=bay_id,
        slot_node_id=slot_node_id,
        entry_completion_id=entry_completion_id,
        plan_hash=plan_hash,
        identity_verified=True,
        authorization_verified=True,
        checks=checks,
        reasons=(),
        measurement=measurement,
        stage_history=(RefinementStage.PENDING, RefinementStage.READY),
    )


def refinement_phase_improved(
    phase: str,
    *,
    before: RefinementMeasurement,
    after: RefinementMeasurement,
    boundary_floor_m: float,
    route_or_none=None,
    tolerances: Optional[RefinementTolerances] = None,
) -> tuple[bool, tuple[str, ...]]:
    """Check one executed refinement phase against the real post state."""

    if phase not in ("TERMINAL_REVERSE_ALIGN", "TERMINAL_FORWARD_RETURN"):
        raise ValueError(f"unknown refinement phase {phase!r}")
    if not isinstance(before, RefinementMeasurement) or not isinstance(after, RefinementMeasurement):
        raise TypeError("before/after must be RefinementMeasurements")
    tolerances = tolerances or RefinementTolerances()
    reasons: list[str] = []
    if not after.footprint_inside_bay:
        reasons.append("phase_footprint_outside_bay")
    if (
        after.boundary_clearance_m is None
        or after.boundary_clearance_m < boundary_floor_m - 1e-9
    ):
        reasons.append("phase_boundary_clearance_below_floor")
    if (
        after.obstacle_clearance_m is not None
        and after.obstacle_clearance_m < tolerances.target_obstacle_clearance_m
    ):
        reasons.append("phase_obstacle_clearance")
    if not after.stopped or after.speed_mps >= tolerances.stop_speed_mps:
        reasons.append("phase_not_stopped")
    if after.collision_count:
        reasons.append("phase_collision")
    if phase == "TERMINAL_REVERSE_ALIGN":
        if abs(after.heading_error_deg) > abs(before.heading_error_deg) - 0.2:
            reasons.append("phase_reverse_did_not_reduce_heading")
    else:
        if abs(after.heading_error_deg) > abs(before.heading_error_deg) + 0.5:
            reasons.append("phase_forward_heading_worsened")
        if (
            after.distance_to_center_m > before.distance_to_center_m - 0.005
            and after.distance_to_center_m > tolerances.target_position_m
        ):
            reasons.append("phase_forward_did_not_reduce_position")
    return (not reasons, tuple(reasons))


def no_safe_refinement_result(
    *,
    task_id: str,
    bay_id: str,
    slot_node_id: str,
    entry_completion_id: str,
    current: RefinementMeasurement,
    reasons: Sequence[str],
    tolerances: Optional[RefinementTolerances] = None,
) -> RefinementResult:
    """PASS NO_SAFE_REFINEMENT: the real current pose is preserved safely."""

    tolerances = tolerances or RefinementTolerances()
    checks = _check_measurement(current, tolerances)
    checks["current_stable"] = current.stability.stable
    safe = (
        checks["footprint_inside_bay"]
        and checks["obstacle_clearance"]
        and checks["no_collision"]
        and checks["stopped"]
        and checks["stop_stable"]
        and (
            current.boundary_clearance_m is not None
            and current.boundary_clearance_m >= 0.05
        )
        and abs(current.heading_error_deg) <= 5.0
        and current.distance_to_center_m <= 0.25
    )
    if not safe:
        return RefinementResult(
            stage=RefinementStage.SAFE_STOP,
            task_id=task_id,
            bay_id=bay_id,
            slot_node_id=slot_node_id,
            entry_completion_id=entry_completion_id,
            plan_hash=None,
            identity_verified=True,
            authorization_verified=False,
            checks=checks,
            reasons=("current_pose_not_safe_to_preserve",),
            measurement=current,
            stage_history=(RefinementStage.PENDING, RefinementStage.SAFE_STOP),
        )
    return RefinementResult(
        stage=RefinementStage.NO_SAFE,
        task_id=task_id,
        bay_id=bay_id,
        slot_node_id=slot_node_id,
        entry_completion_id=entry_completion_id,
        plan_hash=None,
        identity_verified=True,
        authorization_verified=False,
        checks=checks,
        reasons=tuple(dict.fromkeys(reasons)),
        measurement=current,
        stage_history=(RefinementStage.PENDING, RefinementStage.NO_SAFE),
    )


def compute_entry_completion_id(
    *,
    entry_task_id: str,
    entry_authorization_id: str,
    entry_route_hash: str,
    final_pose: Sequence[float],
    final_verification_stage: str,
    final_boundary_clearance_m: Optional[float],
    final_heading_error_deg: float,
) -> str:
    return _sha256_json(
        {
            "entry_task_id": entry_task_id,
            "entry_authorization_id": entry_authorization_id,
            "entry_route_hash": entry_route_hash,
            "final_pose": [round(float(v), 6) for v in final_pose],
            "final_verification_stage": final_verification_stage,
            "final_boundary_clearance_m": (
                None
                if final_boundary_clearance_m is None
                else round(float(final_boundary_clearance_m), 6)
            ),
            "final_heading_error_deg": round(float(final_heading_error_deg), 6),
        }
    )


@dataclass(frozen=True)
class RefinementAuthorization:
    authorization_id: str
    task_id: str
    bay_id: str
    slot_node_id: str
    entry_completion_id: str
    entry_authorization_id: str
    start_pose: tuple[float, float, float]
    target_pose: tuple[float, float, float]
    plan_hash: str
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
        if self.decision not in ("REFINEMENT_AUTHORIZED", "UNVERIFIED", "REJECTED", "SAFE_STOP"):
            raise ValueError(f"unknown refinement decision {self.decision!r}")
        for name in (
            "authorization_id",
            "task_id",
            "bay_id",
            "slot_node_id",
            "entry_completion_id",
            "entry_authorization_id",
            "plan_hash",
            "created_at",
            "expires_at",
        ):
            _nonblank(getattr(self, name), name)
        if len(self.start_pose) != 3 or len(self.target_pose) != 3:
            raise ValueError("poses must be (x, y, yaw)")
        for value in (*self.start_pose, *self.target_pose):
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
    def permits_refinement(self) -> bool:
        return self.decision == "REFINEMENT_AUTHORIZED" and not self.revoked

    @property
    def permits_parking_completed(self) -> bool:
        return False

    @property
    def permits_entry(self) -> bool:
        return False

    @property
    def permits_alignment(self) -> bool:
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
        entry_completion_id: str,
        plan_hash: str,
    ) -> bool:
        return (
            self.task_id == task_id
            and self.bay_id == bay_id
            and self.slot_node_id == slot_node_id
            and self.entry_completion_id == entry_completion_id
            and self.plan_hash == plan_hash
        )

    def is_usable(
        self,
        *,
        task_id: str,
        bay_id: str,
        slot_node_id: str,
        entry_completion_id: str,
        plan_hash: str,
        now: Optional[str] = None,
    ) -> bool:
        return (
            self.permits_refinement
            and self.consumed_at is None
            and not self.is_expired(now)
            and self._identity_ok(
                task_id=task_id,
                bay_id=bay_id,
                slot_node_id=slot_node_id,
                entry_completion_id=entry_completion_id,
                plan_hash=plan_hash,
            )
        )

    def is_active(
        self,
        *,
        task_id: str,
        bay_id: str,
        slot_node_id: str,
        entry_completion_id: str,
        plan_hash: str,
        now: Optional[str] = None,
    ) -> bool:
        return (
            self.permits_refinement
            and not self.is_expired(now)
            and self._identity_ok(
                task_id=task_id,
                bay_id=bay_id,
                slot_node_id=slot_node_id,
                entry_completion_id=entry_completion_id,
                plan_hash=plan_hash,
            )
        )

    def to_metadata(self) -> dict:
        return {
            "schema": "vln.parking.refinement_authorization.v1",
            "skill": REFINEMENT_SKILL,
            "authorization_id": self.authorization_id,
            "task_id": self.task_id,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "entry_completion_id": self.entry_completion_id,
            "entry_authorization_id": self.entry_authorization_id,
            "start_pose": {
                "x": round(self.start_pose[0], 4),
                "y": round(self.start_pose[1], 4),
                "yaw_deg": round(math.degrees(self.start_pose[2]), 4),
            },
            "target_pose": {
                "x": round(self.target_pose[0], 4),
                "y": round(self.target_pose[1], 4),
                "yaw_deg": round(math.degrees(self.target_pose[2]), 4),
            },
            "plan_hash": self.plan_hash,
            "decision": self.decision,
            "reason": self.reason,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "consumed_at": self.consumed_at,
            "revoked": self.revoked,
            "stage_scope": "REFINEMENT",
            "permits_refinement": self.permits_refinement,
            "permits_parking_completed": False,
            "permits_entry": False,
            "permits_alignment": False,
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


def _refinement_authorization_id(
    *,
    task_id: str,
    bay_id: str,
    slot_node_id: str,
    entry_completion_id: str,
    entry_authorization_id: str,
    plan_hash: str,
    decision: str,
    created_at: str,
) -> str:
    return _sha256_json(
        {
            "task_id": task_id,
            "bay_id": bay_id,
            "slot_node_id": slot_node_id,
            "entry_completion_id": entry_completion_id,
            "entry_authorization_id": entry_authorization_id,
            "plan_hash": plan_hash,
            "decision": decision,
            "created_at": created_at,
        }
    )


def authorize_refinement(
    *,
    task_id: str,
    bay_id: str,
    slot_node_id: str,
    entry_completion_id: str,
    entry_authorization_id: str,
    start_pose: Sequence[float],
    target_pose: Sequence[float],
    plan_hash: str,
    tolerances: Optional[RefinementTolerances] = None,
    budget: Optional[RefinementBudget] = None,
    now: Optional[str] = None,
    ttl_s: float = 600.0,
    evidence: Optional[Mapping[str, object]] = None,
) -> RefinementAuthorization:
    _nonblank(task_id, "task_id")
    _nonblank(entry_completion_id, "entry_completion_id")
    if len(start_pose) != 3 or len(target_pose) != 3:
        raise ValueError("poses must be (x, y, yaw)")
    tolerances = tolerances or RefinementTolerances()
    budget = budget or RefinementBudget()
    if not isinstance(budget, RefinementBudget):
        raise TypeError("budget must be a RefinementBudget")
    created_at = now or _utc_now()
    created = _parse_time(created_at)
    ttl = _finite(ttl_s, "ttl_s")
    if ttl <= 0.0:
        raise ValueError("ttl_s must be positive")
    expires_at = datetime.fromtimestamp(created.timestamp() + ttl, timezone.utc).isoformat()
    start = (float(start_pose[0]), float(start_pose[1]), float(start_pose[2]))
    target = (float(target_pose[0]), float(target_pose[1]), float(target_pose[2]))
    return RefinementAuthorization(
        authorization_id=_refinement_authorization_id(
            task_id=task_id,
            bay_id=bay_id,
            slot_node_id=slot_node_id,
            entry_completion_id=entry_completion_id,
            entry_authorization_id=entry_authorization_id,
            plan_hash=plan_hash,
            decision="REFINEMENT_AUTHORIZED",
            created_at=created_at,
        ),
        task_id=task_id,
        bay_id=bay_id,
        slot_node_id=slot_node_id,
        entry_completion_id=entry_completion_id,
        entry_authorization_id=entry_authorization_id,
        start_pose=start,
        target_pose=target,
        plan_hash=plan_hash,
        decision="REFINEMENT_AUTHORIZED",
        reason=(
            "ENTRY_COMPLETED is current; this permission covers only the "
            "declared bounded refinement plan"
        ),
        created_at=created_at,
        expires_at=expires_at,
        consumed_at=None,
        revoked=False,
        max_segments=budget.max_segments,
        max_segment_distance_m=budget.max_segment_distance_m,
        max_total_distance_m=budget.max_total_distance_m,
        max_segment_sim_seconds=budget.max_segment_sim_seconds,
        max_total_sim_seconds=budget.max_total_sim_seconds,
        speed_cap_mps=budget.speed_cap_mps,
        tolerances=tolerances.to_metadata(),
        evidence=dict(evidence or {}),
    )


def consume_refinement_authorization(
    authorization: RefinementAuthorization,
    *,
    task_id: str,
    bay_id: str,
    slot_node_id: str,
    entry_completion_id: str,
    plan_hash: str,
    now: Optional[str] = None,
) -> RefinementAuthorization:
    if not isinstance(authorization, RefinementAuthorization):
        raise TypeError("authorization must be a RefinementAuthorization")
    if not authorization.is_usable(
        task_id=task_id,
        bay_id=bay_id,
        slot_node_id=slot_node_id,
        entry_completion_id=entry_completion_id,
        plan_hash=plan_hash,
        now=now,
    ):
        raise RefinementAuthorizationError(
            "refinement authorization is absent, for another task/plan, "
            "already consumed, revoked or expired"
        )
    return replace(authorization, consumed_at=now or _utc_now())


def revoke_refinement_authorization(
    authorization: RefinementAuthorization,
    reason: str,
    *,
    now: Optional[str] = None,
) -> RefinementAuthorization:
    if not isinstance(authorization, RefinementAuthorization):
        raise TypeError("authorization must be a RefinementAuthorization")
    _nonblank(reason, "reason")
    _parse_time(now or _utc_now())
    return replace(authorization, revoked=True, reason=reason)


def refinement_authorization_from_metadata(
    metadata: Mapping[str, object],
) -> RefinementAuthorization:
    if not isinstance(metadata, Mapping):
        raise ValueError("refinement authorization must be a JSON object")
    schema = metadata.get("schema")
    if schema not in (None, "vln.parking.refinement_authorization.v1"):
        raise ValueError(f"unexpected refinement authorization schema {schema!r}")
    budget = metadata.get("budget")
    if not isinstance(budget, Mapping):
        raise ValueError("refinement authorization has no budget")
    tolerances = metadata.get("tolerances")
    if not isinstance(tolerances, Mapping):
        raise ValueError("refinement authorization has no tolerances")
    start = metadata.get("start_pose")
    target = metadata.get("target_pose")
    if not isinstance(start, Mapping) or not isinstance(target, Mapping):
        raise ValueError("refinement authorization poses are missing")

    def _pose(value: Mapping[str, object]) -> tuple[float, float, float]:
        return (
            float(value["x"]),
            float(value["y"]),
            math.radians(float(value["yaw_deg"])),
        )

    return RefinementAuthorization(
        authorization_id=metadata.get("authorization_id"),
        task_id=metadata.get("task_id"),
        bay_id=metadata.get("bay_id"),
        slot_node_id=metadata.get("slot_node_id"),
        entry_completion_id=metadata.get("entry_completion_id"),
        entry_authorization_id=metadata.get("entry_authorization_id"),
        start_pose=_pose(start),
        target_pose=_pose(target),
        plan_hash=metadata.get("plan_hash"),
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
