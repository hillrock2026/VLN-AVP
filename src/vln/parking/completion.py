"""Independent final parking verification and completion gate.

CAP-07B-06 answers one question from the real CARLA state: is the vehicle
actually parked in the bound bay, with the stage chain intact, stopped,
stable and collision-free? The answer is produced by
:class:`FinalParkingVerifier`, which is pure: it reads evidence and never
controls the vehicle or writes CARLA state.

:class:`ParkingCompletionGate` is the only component allowed to set
``parking_completed=True``. The verifier deliberately returns
``parking_completed=False`` even when every check passes; only the gate can
turn a verified result into ``PARKING_COMPLETED``.

Coordinate convention
---------------------
The bay frame uses the same convention as Entry and Refinement:

* ``bay_heading_rad`` points into the bay (``pi`` is west / nose-in);
* ``forward = (cos(h), sin(h))`` and ``left = (-forward_y, forward_x)``;
* ``lateral`` is the left component and ``longitudinal`` the forward
  component of the vehicle-centre minus the bay-centre vector;
* heading error is ``wrap_degrees(vehicle_yaw - bay_heading)``.

Thresholds
----------
The final-parking tolerances are fixed before the run. Radial position,
heading, stop speed, stability drift and painted-boundary clearance reuse the
values already declared in :mod:`vln.carla.parking_verdict`. The per-axis
lateral/longitudinal bounds use that same radial position gate. The obstacle
guard reuses the 0.20 m driving guard. Five consecutive stability samples
reuse the CAP-07B-03/04/05 rule. CAP-07B-06 adds only a pre-declared 0.5 deg
heading-drift bound and a 2000-frame freshness bound between the pose-ready
artifact and the final read.
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
    point_in_polygon,
)
from vln.parking.refinement import compute_entry_completion_id, wrap_degrees

__all__ = [
    "FINAL_VERIFICATION_SKILL",
    "FINAL_VERIFICATION_VERSION",
    "COMPLETION_GATE_VERSION",
    "FinalParkingStage",
    "CompletionStage",
    "CompletionSource",
    "FinalParkingTolerances",
    "VehicleSnapshot",
    "ObstacleEvidence",
    "CollisionEvidence",
    "StabilitySample",
    "FinalStability",
    "FinalParkingMeasurement",
    "FinalParkingInputs",
    "FinalParkingResult",
    "CompletionRequest",
    "CompletionDecision",
    "CompletionGateError",
    "VerificationIntegrityError",
    "artifact_sha256",
    "measure_final_stability",
    "FinalParkingVerifier",
    "ParkingCompletionGate",
    "verify_result_metadata",
    "reject_ungated_parking_completion",
    "require_gate_decision",
    "REQUIRED_FINAL_CHECKS",
    "FINAL_VERIFICATION_LIMITATIONS",
]

FINAL_VERIFICATION_SKILL = "vln.parking.final_verification"
FINAL_VERIFICATION_VERSION = "vln.parking.final_verification.v1"
COMPLETION_GATE_VERSION = "vln.parking.completion_gate.v1"


class FinalParkingStage:
    VERIFIED = "FINAL_PARKING_VERIFIED"
    NOT_COMPLETED = "NOT_COMPLETED"

    ALL = frozenset({VERIFIED, NOT_COMPLETED})


class CompletionStage:
    COMPLETED = "PARKING_COMPLETED"
    NOT_COMPLETED = "NOT_COMPLETED"

    ALL = frozenset({COMPLETED, NOT_COMPLETED})


class CompletionSource:
    FINAL_PARKING_VERIFIER = "final_parking_verifier"
    TAICHU = "taichu"
    CARLA_EXECUTOR = "carla_executor"
    ENTRY_SKILL = "vln.parking.entry"
    ALIGNMENT_SKILL = "vln.parking.alignment"
    REFINEMENT_SKILL = "vln.parking.refinement"
    STATE_UPDATE = "state_update"

    ALL = frozenset(
        {
            FINAL_PARKING_VERIFIER,
            TAICHU,
            CARLA_EXECUTOR,
            ENTRY_SKILL,
            ALIGNMENT_SKILL,
            REFINEMENT_SKILL,
            STATE_UPDATE,
        }
    )


REQUIRED_FINAL_CHECKS = (
    "inputs_complete",
    "task_identity",
    "bay_identity",
    "slot_identity",
    "vehicle_identity",
    "vehicle_geometry_consistent",
    "entry_artifact_valid",
    "entry_artifact_hash",
    "pose_ready_artifact_valid",
    "pose_ready_artifact_hash",
    "stage_chain_causal",
    "current_state_matches_pose_ready",
    "footprint_inside_bay",
    "boundary_clearance",
    "lateral_error",
    "longitudinal_error",
    "heading_error",
    "position_tolerance",
    "obstacle_evidence_present",
    "obstacle_clearance",
    "collision_sensor_available",
    "collision_history_complete",
    "no_collision",
    "velocity_readable",
    "stopped",
    "stability_samples",
    "stability_position_drift",
    "stability_heading_drift",
    "actor_stable",
    "bay_stable",
)

FINAL_VERIFICATION_LIMITATIONS = (
    "Final verification uses discrete CARLA stability samples, not a continuous-time proof.",
    "Obstacle evidence combines historical static collision-mesh samples with a sparse live ray probe; it is not a complete live occupancy model.",
    "Boundary clearance uses the declared bay polygon; painted lines are not physical obstacles.",
    "The configured footprint and the real CARLA bounding box can differ by sub-millimetre amounts; the stricter clearance of the two is used.",
    "Collision monitoring starts when the collision sensor is attached; the stationary spawn-settle ticks before attachment are not covered.",
    "CARLA simulation only; single executor; the existing monocular-RGB perception limits remain.",
    "This is not a production safety certification.",
)


class VerificationIntegrityError(RuntimeError):
    """A verifier result failed its own canonical hash check."""


class CompletionGateError(RuntimeError):
    """A caller tried to produce or bypass PARKING_COMPLETED outside the gate."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: object, name: str) -> datetime:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-blank ISO timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must carry a timezone")
    return parsed


def _finite(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _nonblank(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def artifact_sha256(payload: object) -> str:
    """Canonical hash used to bind stage artifacts and verifier results."""

    return _sha256_json(payload)


def _wrap_degrees(value: float) -> float:
    return wrap_degrees(float(value))


@dataclass(frozen=True)
class FinalParkingTolerances:
    position_m: float = 0.25
    lateral_error_m: float = 0.25
    longitudinal_error_m: float = 0.25
    heading_deg: float = 5.0
    boundary_clearance_m: float = 0.05
    obstacle_clearance_m: float = 0.20
    stop_speed_mps: float = 0.05
    stable_samples: int = 5
    stable_position_drift_m: float = 0.02
    stable_heading_drift_deg: float = 0.5
    sample_interval_s: float = 0.05
    pose_ready_pose_gap_m: float = 0.10
    pose_ready_heading_gap_deg: float = 2.0
    max_final_frame_gap: int = 2000
    max_verification_age_s: float = 300.0
    max_bbox_vs_config_delta_m: float = 0.01

    def __post_init__(self) -> None:
        for name in (
            "position_m",
            "lateral_error_m",
            "longitudinal_error_m",
            "heading_deg",
            "boundary_clearance_m",
            "obstacle_clearance_m",
            "stop_speed_mps",
            "stable_position_drift_m",
            "stable_heading_drift_deg",
            "sample_interval_s",
            "pose_ready_pose_gap_m",
            "pose_ready_heading_gap_deg",
            "max_verification_age_s",
            "max_bbox_vs_config_delta_m",
        ):
            value = getattr(self, name)
            if not _finite(value) or float(value) < 0.0:
                raise ValueError(f"{name} must be a finite non-negative number")
        if type(self.stable_samples) is not int or self.stable_samples < 3:
            raise ValueError("stable_samples must be an int >= 3")
        if type(self.max_final_frame_gap) is not int or self.max_final_frame_gap <= 0:
            raise ValueError("max_final_frame_gap must be a positive int")
        if float(self.sample_interval_s) <= 0.0:
            raise ValueError("sample_interval_s must be positive")

    def to_metadata(self) -> dict:
        return {
            "position_m": self.position_m,
            "lateral_error_m": self.lateral_error_m,
            "longitudinal_error_m": self.longitudinal_error_m,
            "heading_deg": self.heading_deg,
            "boundary_clearance_m": self.boundary_clearance_m,
            "obstacle_clearance_m": self.obstacle_clearance_m,
            "stop_speed_mps": self.stop_speed_mps,
            "stable_samples": self.stable_samples,
            "stable_position_drift_m": self.stable_position_drift_m,
            "stable_heading_drift_deg": self.stable_heading_drift_deg,
            "sample_interval_s": self.sample_interval_s,
            "pose_ready_pose_gap_m": self.pose_ready_pose_gap_m,
            "pose_ready_heading_gap_deg": self.pose_ready_heading_gap_deg,
            "max_final_frame_gap": self.max_final_frame_gap,
            "max_verification_age_s": self.max_verification_age_s,
            "max_bbox_vs_config_delta_m": self.max_bbox_vs_config_delta_m,
        }


@dataclass(frozen=True)
class VehicleSnapshot:
    actor_id: int
    type_id: str
    x: float
    y: float
    z: float
    yaw_rad: float
    frame: int
    half_length: float
    half_width: float
    half_height: float
    bbox_offset_x: float = 0.0
    bbox_offset_y: float = 0.0
    bbox_offset_z: float = 0.0
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    velocity_z: float = 0.0
    speed_mps: float = 0.0
    actor_alive: bool = True
    actor_id_consistent: bool = True

    def to_metadata(self) -> dict:
        return {
            "actor_id": self.actor_id,
            "type_id": self.type_id,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "yaw_rad": self.yaw_rad,
            "yaw_deg": math.degrees(self.yaw_rad) if _finite(self.yaw_rad) else None,
            "frame": self.frame,
            "bounding_box": {
                "half_length": self.half_length,
                "half_width": self.half_width,
                "half_height": self.half_height,
                "offset_x": self.bbox_offset_x,
                "offset_y": self.bbox_offset_y,
                "offset_z": self.bbox_offset_z,
            },
            "velocity": {
                "x": self.velocity_x,
                "y": self.velocity_y,
                "z": self.velocity_z,
            },
            "speed_mps": self.speed_mps,
            "actor_alive": self.actor_alive,
            "actor_id_consistent": self.actor_id_consistent,
        }


@dataclass(frozen=True)
class ObstacleEvidence:
    source: str
    points: tuple[tuple[float, float], ...]
    live: bool
    coverage_note: str
    live_point_count: int = 0
    historical_point_count: int = 0

    def to_metadata(self) -> dict:
        return {
            "source": self.source,
            "live": self.live,
            "point_count": len(self.points),
            "live_point_count": self.live_point_count,
            "historical_point_count": self.historical_point_count,
            "coverage_note": self.coverage_note,
            "points": [[round(x, 4), round(y, 4)] for x, y in self.points],
        }


@dataclass(frozen=True)
class CollisionEvidence:
    sensor_available: bool
    sensor_role: Optional[str]
    monitoring_started_frame: Optional[int]
    monitoring_started_utc: Optional[str]
    first_motion_frame: Optional[int]
    current_frame: int
    task_events: tuple[Mapping[str, object], ...] = ()
    verification_events: tuple[Mapping[str, object], ...] = ()
    evidence_gap: bool = False
    gap_note: str = ""

    def to_metadata(self) -> dict:
        return {
            "sensor_available": self.sensor_available,
            "sensor_role": self.sensor_role,
            "monitoring_started_frame": self.monitoring_started_frame,
            "monitoring_started_utc": self.monitoring_started_utc,
            "first_motion_frame": self.first_motion_frame,
            "current_frame": self.current_frame,
            "task_event_count": len(self.task_events),
            "verification_event_count": len(self.verification_events),
            "task_events": [dict(event) for event in self.task_events],
            "verification_events": [
                dict(event) for event in self.verification_events
            ],
            "evidence_gap": self.evidence_gap,
            "gap_note": self.gap_note,
        }


@dataclass(frozen=True)
class StabilitySample:
    frame: int
    sim_time: float
    x: float
    y: float
    yaw_rad: float
    speed_mps: float

    def to_metadata(self) -> dict:
        return {
            "frame": self.frame,
            "sim_time": self.sim_time,
            "x": self.x,
            "y": self.y,
            "yaw_rad": self.yaw_rad,
            "yaw_deg": math.degrees(self.yaw_rad)
            if _finite(self.yaw_rad)
            else None,
            "speed_mps": self.speed_mps,
        }


@dataclass(frozen=True)
class FinalStability:
    samples: int
    max_speed_mps: float
    position_drift_m: float
    heading_drift_deg: float
    frame_monotonic: bool
    interval_ok: bool
    stable: bool
    reasons: tuple[str, ...] = ()

    def to_metadata(self) -> dict:
        return {
            "samples": self.samples,
            "max_speed_mps": self.max_speed_mps,
            "position_drift_m": self.position_drift_m,
            "heading_drift_deg": self.heading_drift_deg,
            "frame_monotonic": self.frame_monotonic,
            "interval_ok": self.interval_ok,
            "stable": self.stable,
            "reasons": list(self.reasons),
        }


def measure_final_stability(
    samples: Sequence[StabilitySample],
    tolerances: FinalParkingTolerances,
) -> FinalStability:
    """Evaluate consecutive real CARLA velocity/pose samples."""

    reasons: list[str] = []
    values: list[tuple[int, float, float, float, float, float]] = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, StabilitySample):
            reasons.append(f"sample_{index}_not_a_stability_sample")
            continue
        if (
            type(sample.frame) is not int
            or sample.frame < 0
            or not _finite(sample.sim_time)
            or not _finite(sample.x)
            or not _finite(sample.y)
            or not _finite(sample.yaw_rad)
            or not _finite(sample.speed_mps)
            or float(sample.speed_mps) < 0.0
        ):
            reasons.append(f"sample_{index}_invalid")
            continue
        values.append(
            (
                sample.frame,
                float(sample.sim_time),
                float(sample.x),
                float(sample.y),
                float(sample.yaw_rad),
                float(sample.speed_mps),
            )
        )
    if not values:
        return FinalStability(
            samples=0,
            max_speed_mps=0.0,
            position_drift_m=0.0,
            heading_drift_deg=0.0,
            frame_monotonic=False,
            interval_ok=False,
            stable=False,
            reasons=tuple(reasons or ["stability_samples_missing"]),
        )
    max_speed = max(value[5] for value in values)
    x0, y0, yaw0 = values[0][2], values[0][3], values[0][4]
    drift = max(math.hypot(value[2] - x0, value[3] - y0) for value in values)
    heading_drift = max(
        abs(_wrap_degrees(math.degrees(value[4] - yaw0))) for value in values
    )
    frame_monotonic = all(
        values[index][0] > values[index - 1][0]
        for index in range(1, len(values))
    )
    interval_ok = all(
        0.0
        < values[index][1] - values[index - 1][1]
        <= 1.5 * float(tolerances.sample_interval_s) + 1e-9
        for index in range(1, len(values))
    )
    if len(values) < tolerances.stable_samples:
        reasons.append("stability_sample_count")
    if max_speed >= tolerances.stop_speed_mps:
        reasons.append("stability_speed")
    if drift > tolerances.stable_position_drift_m:
        reasons.append("stability_position_drift")
    if heading_drift > tolerances.stable_heading_drift_deg:
        reasons.append("stability_heading_drift")
    if not frame_monotonic:
        reasons.append("stability_frame_order")
    if not interval_ok:
        reasons.append("stability_sample_interval")
    return FinalStability(
        samples=len(values),
        max_speed_mps=max_speed,
        position_drift_m=drift,
        heading_drift_deg=heading_drift,
        frame_monotonic=frame_monotonic,
        interval_ok=interval_ok,
        stable=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
    )


@dataclass(frozen=True)
class FinalParkingMeasurement:
    x: float
    y: float
    yaw_rad: float
    heading_error_deg: float
    lateral_error_m: float
    longitudinal_error_m: float
    distance_to_center_m: float
    footprint_corners: tuple[tuple[float, float], ...]
    bbox_center_footprint_corners: tuple[tuple[float, float], ...]
    config_footprint_corners: tuple[tuple[float, float], ...]
    footprint_inside_bay: bool
    bbox_center_footprint_inside_bay: bool
    config_footprint_inside_bay: bool
    boundary_clearance_m: Optional[float]
    bbox_center_boundary_clearance_m: Optional[float]
    config_boundary_clearance_m: Optional[float]
    obstacle_clearance_m: Optional[float]
    bbox_vs_config_delta_m: float
    speed_mps: float
    limiting_footprint: str

    def to_metadata(self) -> dict:
        return {
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "yaw_rad": round(self.yaw_rad, 6),
            "yaw_deg": round(math.degrees(self.yaw_rad), 4),
            "heading_error_deg": round(self.heading_error_deg, 4),
            "lateral_error_m": round(self.lateral_error_m, 4),
            "longitudinal_error_m": round(self.longitudinal_error_m, 4),
            "distance_to_center_m": round(self.distance_to_center_m, 4),
            "footprint_corners": [
                [round(px, 4), round(py, 4)] for px, py in self.footprint_corners
            ],
            "bbox_center_footprint_corners": [
                [round(px, 4), round(py, 4)]
                for px, py in self.bbox_center_footprint_corners
            ],
            "config_footprint_corners": [
                [round(px, 4), round(py, 4)]
                for px, py in self.config_footprint_corners
            ],
            "footprint_inside_bay": self.footprint_inside_bay,
            "bbox_center_footprint_inside_bay": self.bbox_center_footprint_inside_bay,
            "config_footprint_inside_bay": self.config_footprint_inside_bay,
            "boundary_clearance_m": None
            if self.boundary_clearance_m is None
            else round(self.boundary_clearance_m, 4),
            "bbox_center_boundary_clearance_m": None
            if self.bbox_center_boundary_clearance_m is None
            else round(self.bbox_center_boundary_clearance_m, 4),
            "config_boundary_clearance_m": None
            if self.config_boundary_clearance_m is None
            else round(self.config_boundary_clearance_m, 4),
            "obstacle_clearance_m": None
            if self.obstacle_clearance_m is None
            else round(self.obstacle_clearance_m, 4),
            "bbox_vs_config_delta_m": round(self.bbox_vs_config_delta_m, 6),
            "speed_mps": round(self.speed_mps, 4),
            "limiting_footprint": self.limiting_footprint,
        }


@dataclass(frozen=True)
class FinalParkingInputs:
    task_id: str
    bay_id: str
    slot_node_id: str
    entry_task_id: str
    refinement_task_id: str
    entry_authorization_id: str
    expected_vehicle_actor_id: int
    vehicle: VehicleSnapshot
    config_footprint: Footprint
    bay_polygon: tuple[tuple[float, float], ...]
    bay_center: tuple[float, float]
    bay_heading_rad: float
    obstacle_evidence: ObstacleEvidence
    collision: CollisionEvidence
    stability_samples: tuple[StabilitySample, ...]
    actor_alive: bool
    actor_id_consistent: bool
    bay_identity_consistent: bool
    entry_artifact: Mapping[str, object]
    entry_artifact_sha256: str
    pose_ready_artifact: Mapping[str, object]
    pose_ready_artifact_sha256: str
    entry_frame: int
    pose_ready_frame: int
    tolerances: FinalParkingTolerances = field(
        default_factory=FinalParkingTolerances
    )
    now: Optional[str] = None


@dataclass(frozen=True)
class FinalParkingResult:
    decision: str
    parking_completed: bool
    task_id: str
    bay_id: str
    slot_node_id: str
    vehicle_actor_id: Optional[int]
    entry_artifact_sha256: Optional[str]
    pose_ready_artifact_sha256: Optional[str]
    entry_completion_id: Optional[str]
    refinement_plan_hash: Optional[str]
    verification_frame: Optional[int]
    verification_timestamp_utc: str
    initial_transform: Optional[Mapping[str, object]]
    final_transform: Optional[Mapping[str, object]]
    measurement: Optional[FinalParkingMeasurement]
    stability: Optional[FinalStability]
    collision: Optional[Mapping[str, object]]
    obstacle: Optional[Mapping[str, object]]
    velocity_samples: tuple[Mapping[str, object], ...]
    checks: Mapping[str, bool]
    failed_checks: tuple[str, ...]
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]
    verifier_version: str = FINAL_VERIFICATION_VERSION
    producer: str = CompletionSource.FINAL_PARKING_VERIFIER
    result_sha256: str = ""

    def __post_init__(self) -> None:
        if self.decision not in FinalParkingStage.ALL:
            raise ValueError(f"unknown final parking decision {self.decision!r}")
        if self.parking_completed:
            raise ValueError(
                "FinalParkingVerifier must never set parking_completed=True; "
                "only ParkingCompletionGate may issue PARKING_COMPLETED"
            )
        if self.decision == FinalParkingStage.VERIFIED and self.failed_checks:
            raise ValueError("a verified result cannot carry failed checks")
        if self.decision == FinalParkingStage.NOT_COMPLETED and not self.reasons:
            raise ValueError("a not-completed result must carry a reason")

    @property
    def verification_passed(self) -> bool:
        return self.decision == FinalParkingStage.VERIFIED

    def payload(self) -> dict:
        return {
            "schema": FINAL_VERIFICATION_VERSION,
            "skill": FINAL_VERIFICATION_SKILL,
            "verifier_version": self.verifier_version,
            "producer": self.producer,
            "decision": self.decision,
            "verification_passed": self.verification_passed,
            "parking_completed": self.parking_completed,
            "task_id": self.task_id,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "vehicle_actor_id": self.vehicle_actor_id,
            "entry_artifact_sha256": self.entry_artifact_sha256,
            "pose_ready_artifact_sha256": self.pose_ready_artifact_sha256,
            "entry_completion_id": self.entry_completion_id,
            "refinement_plan_hash": self.refinement_plan_hash,
            "verification_frame": self.verification_frame,
            "verification_timestamp_utc": self.verification_timestamp_utc,
            "initial_transform": dict(self.initial_transform)
            if self.initial_transform is not None
            else None,
            "final_transform": dict(self.final_transform)
            if self.final_transform is not None
            else None,
            "measurement": None
            if self.measurement is None
            else self.measurement.to_metadata(),
            "stability": None
            if self.stability is None
            else self.stability.to_metadata(),
            "collision": None
            if self.collision is None
            else dict(self.collision),
            "obstacle": None if self.obstacle is None else dict(self.obstacle),
            "velocity_samples": [dict(sample) for sample in self.velocity_samples],
            "checks": dict(self.checks),
            "failed_checks": list(self.failed_checks),
            "reasons": list(self.reasons),
            "limitations": list(self.limitations),
        }

    def to_metadata(self) -> dict:
        payload = self.payload()
        payload["result_sha256"] = self.result_sha256 or artifact_sha256(payload)
        return payload


def verify_result_metadata(metadata: Mapping[str, object]) -> dict:
    """Validate a serialized verifier result against its canonical hash.

    Raises :class:`VerificationIntegrityError` if a field was changed while
    keeping the old ``result_sha256``. The returned dict includes the verified
    hash so it can be passed to :class:`ParkingCompletionGate`.
    """

    if not isinstance(metadata, Mapping):
        raise VerificationIntegrityError("verifier result must be a mapping")
    data = dict(metadata)
    claimed = data.pop("result_sha256", None)
    if not _nonblank(claimed):
        raise VerificationIntegrityError("verifier result has no result_sha256")
    recomputed = artifact_sha256(data)
    if recomputed != claimed:
        raise VerificationIntegrityError(
            "verifier result hash does not match its payload"
        )
    data["result_sha256"] = claimed
    return data


def _footprint_report(
    x: float,
    y: float,
    yaw_rad: float,
    footprint: Footprint,
    bay_polygon: Sequence[Sequence[float]],
    obstacle_points: Sequence[Sequence[float]],
) -> dict:
    corners = footprint.corners(x, y, yaw_rad)
    inside = all(
        point_in_polygon(px, py, bay_polygon) for px, py in corners
    )
    boundary = footprint_polygon_clearance(
        x, y, yaw_rad, footprint, bay_polygon
    )["min_clearance_m"]
    obstacle = None
    if obstacle_points:
        obstacle = footprint_clearance(
            x, y, yaw_rad, footprint, obstacle_points
        )["min_clearance_m"]
    return {
        "corners": tuple(corners),
        "inside": inside,
        "boundary": boundary,
        "obstacle": obstacle,
    }


def _artifact_pose(artifact: Mapping[str, object]) -> Optional[tuple[float, float, float]]:
    measurement = artifact.get("measurement")
    if not isinstance(measurement, Mapping):
        return None
    try:
        x = float(measurement["x"])
        y = float(measurement["y"])
        yaw = float(measurement["yaw_rad"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x, y, yaw)):
        return None
    return (x, y, yaw)


def _pose_gap(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float]:
    distance = math.hypot(first[0] - second[0], first[1] - second[1])
    heading = abs(
        _wrap_degrees(math.degrees(first[2] - second[2]))
    )
    return distance, heading


class FinalParkingVerifier:
    """Pure final-parking verifier; it never moves or writes the vehicle."""

    def verify(self, inputs: FinalParkingInputs) -> FinalParkingResult:
        now = inputs.now or _utc_now()
        checks = {key: False for key in REQUIRED_FINAL_CHECKS}
        reasons: list[str] = []
        try:
            tolerances = inputs.tolerances
            if not isinstance(tolerances, FinalParkingTolerances):
                raise TypeError("tolerances must be FinalParkingTolerances")
            complete, incomplete_reasons = self._validate_inputs(inputs)
            checks["inputs_complete"] = complete
            if not complete:
                return self._not_completed(
                    inputs,
                    checks,
                    reasons=incomplete_reasons,
                    now=now,
                )
            vehicle = inputs.vehicle
            bay_polygon = tuple(
                (float(px), float(py)) for px, py in inputs.bay_polygon
            )
            bay_center = (
                float(inputs.bay_center[0]),
                float(inputs.bay_center[1]),
            )
            yaw = float(vehicle.yaw_rad)
            cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
            bbox_center_x = (
                float(vehicle.x)
                + cos_yaw * float(vehicle.bbox_offset_x)
                - sin_yaw * float(vehicle.bbox_offset_y)
            )
            bbox_center_y = (
                float(vehicle.y)
                + sin_yaw * float(vehicle.bbox_offset_x)
                + cos_yaw * float(vehicle.bbox_offset_y)
            )
            actual_footprint = Footprint(
                half_length=float(vehicle.half_length),
                half_width=float(vehicle.half_width),
                front_margin=0.0,
            )
            actor_report = _footprint_report(
                float(vehicle.x),
                float(vehicle.y),
                yaw,
                actual_footprint,
                bay_polygon,
                inputs.obstacle_evidence.points,
            )
            bbox_report = _footprint_report(
                bbox_center_x,
                bbox_center_y,
                yaw,
                actual_footprint,
                bay_polygon,
                inputs.obstacle_evidence.points,
            )
            config_report = _footprint_report(
                float(vehicle.x),
                float(vehicle.y),
                yaw,
                inputs.config_footprint,
                bay_polygon,
                inputs.obstacle_evidence.points,
            )
            bbox_delta = max(
                abs(float(vehicle.half_length) - inputs.config_footprint.half_length),
                abs(float(vehicle.half_width) - inputs.config_footprint.half_width),
            )
            reports = {
                "actor": actor_report,
                "bbox_center": bbox_report,
                "config": config_report,
            }
            limiting_footprint = min(
                reports,
                key=lambda name: (
                    float("inf")
                    if reports[name]["boundary"] is None
                    else float(reports[name]["boundary"])
                ),
            )
            boundary_values = [
                float(report["boundary"])
                for report in reports.values()
                if report["boundary"] is not None
                and math.isfinite(float(report["boundary"]))
            ]
            obstacle_values = [
                float(report["obstacle"])
                for report in reports.values()
                if report["obstacle"] is not None
                and math.isfinite(float(report["obstacle"]))
            ]
            footprint_inside = all(
                report["inside"] for report in reports.values()
            )
            forward = (math.cos(inputs.bay_heading_rad), math.sin(inputs.bay_heading_rad))
            left = (-forward[1], forward[0])
            dx = float(vehicle.x) - bay_center[0]
            dy = float(vehicle.y) - bay_center[1]
            measurement = FinalParkingMeasurement(
                x=float(vehicle.x),
                y=float(vehicle.y),
                yaw_rad=yaw,
                heading_error_deg=_wrap_degrees(
                    math.degrees(yaw - float(inputs.bay_heading_rad))
                ),
                lateral_error_m=dx * left[0] + dy * left[1],
                longitudinal_error_m=dx * forward[0] + dy * forward[1],
                distance_to_center_m=math.hypot(dx, dy),
                footprint_corners=actor_report["corners"],
                bbox_center_footprint_corners=bbox_report["corners"],
                config_footprint_corners=config_report["corners"],
                footprint_inside_bay=actor_report["inside"],
                bbox_center_footprint_inside_bay=bbox_report["inside"],
                config_footprint_inside_bay=config_report["inside"],
                boundary_clearance_m=(
                    min(boundary_values) if boundary_values else None
                ),
                bbox_center_boundary_clearance_m=bbox_report["boundary"],
                config_boundary_clearance_m=config_report["boundary"],
                obstacle_clearance_m=(
                    min(obstacle_values) if obstacle_values else None
                ),
                bbox_vs_config_delta_m=bbox_delta,
                speed_mps=float(vehicle.speed_mps),
                limiting_footprint=limiting_footprint,
            )
            checks["vehicle_geometry_consistent"] = (
                bbox_delta <= tolerances.max_bbox_vs_config_delta_m
            )
            checks["footprint_inside_bay"] = footprint_inside
            checks["boundary_clearance"] = (
                footprint_inside
                and measurement.boundary_clearance_m is not None
                and measurement.boundary_clearance_m
                >= tolerances.boundary_clearance_m
            )
            checks["lateral_error"] = (
                abs(measurement.lateral_error_m) <= tolerances.lateral_error_m
            )
            checks["longitudinal_error"] = (
                abs(measurement.longitudinal_error_m)
                <= tolerances.longitudinal_error_m
            )
            checks["heading_error"] = (
                abs(measurement.heading_error_deg) <= tolerances.heading_deg
            )
            checks["position_tolerance"] = (
                measurement.distance_to_center_m <= tolerances.position_m
            )
            checks["obstacle_evidence_present"] = (
                len(inputs.obstacle_evidence.points) > 0
            )
            checks["obstacle_clearance"] = (
                measurement.obstacle_clearance_m is not None
                and measurement.obstacle_clearance_m
                >= tolerances.obstacle_clearance_m
            )

            stability = measure_final_stability(
                inputs.stability_samples, tolerances
            )
            checks["velocity_readable"] = stability.samples > 0
            checks["stopped"] = (
                stability.samples > 0
                and stability.max_speed_mps < tolerances.stop_speed_mps
            )
            checks["stability_samples"] = (
                stability.samples >= tolerances.stable_samples
            )
            checks["stability_position_drift"] = (
                stability.position_drift_m
                <= tolerances.stable_position_drift_m
            )
            checks["stability_heading_drift"] = (
                stability.heading_drift_deg
                <= tolerances.stable_heading_drift_deg
            )
            if not stability.frame_monotonic or not stability.interval_ok:
                checks["velocity_readable"] = False

            collision = inputs.collision
            checks["collision_sensor_available"] = bool(
                collision.sensor_available and collision.sensor_role
            )
            start = collision.monitoring_started_frame
            first_motion = collision.first_motion_frame
            checks["collision_history_complete"] = (
                type(start) is int
                and start >= 0
                and type(collision.current_frame) is int
                and collision.current_frame >= start
                and (first_motion is None or start <= first_motion)
                and not collision.evidence_gap
            )
            checks["no_collision"] = (
                len(collision.task_events) == 0
                and len(collision.verification_events) == 0
            )
            checks["actor_stable"] = bool(
                inputs.actor_alive
                and inputs.actor_id_consistent
                and vehicle.actor_alive
                and vehicle.actor_id_consistent
            )
            checks["bay_stable"] = bool(inputs.bay_identity_consistent)

            artifact = self._artifact_checks(inputs, tolerances)
            checks.update(artifact["checks"])
            reasons.extend(artifact["reasons"])

            checks["task_identity"] = (
                _nonblank(inputs.task_id)
                and _nonblank(inputs.entry_task_id)
                and _nonblank(inputs.refinement_task_id)
                and artifact["entry_task_id"] == inputs.entry_task_id
                and artifact["refinement_task_id"] == inputs.refinement_task_id
            )
            checks["bay_identity"] = (
                _nonblank(inputs.bay_id)
                and artifact["entry_bay_id"] == inputs.bay_id
                and artifact["pose_bay_id"] == inputs.bay_id
            )
            checks["slot_identity"] = (
                _nonblank(inputs.slot_node_id)
                and artifact["entry_slot_node_id"] == inputs.slot_node_id
                and artifact["pose_slot_node_id"] == inputs.slot_node_id
            )
            checks["vehicle_identity"] = (
                type(inputs.expected_vehicle_actor_id) is int
                and inputs.expected_vehicle_actor_id == vehicle.actor_id
                and artifact["entry_vehicle_actor_id"] == vehicle.actor_id
                and artifact["pose_vehicle_actor_id"] == vehicle.actor_id
            )
            pose_pose = artifact["pose_pose"]
            if pose_pose is not None:
                pose_gap, heading_gap = _pose_gap(
                    (
                        float(vehicle.x),
                        float(vehicle.y),
                        yaw,
                    ),
                    pose_pose,
                )
                checks["current_state_matches_pose_ready"] = (
                    pose_gap <= tolerances.pose_ready_pose_gap_m
                    and heading_gap <= tolerances.pose_ready_heading_gap_deg
                )
                artifact["pose_gap_m"] = pose_gap
                artifact["pose_heading_gap_deg"] = heading_gap
            else:
                checks["current_state_matches_pose_ready"] = False
                artifact["pose_gap_m"] = None
                artifact["pose_heading_gap_deg"] = None

            failed = tuple(
                key for key in REQUIRED_FINAL_CHECKS if not checks[key]
            )
            if failed:
                reasons.extend(failed)
                reasons.extend(stability.reasons)
                reasons.extend(artifact["reasons"])
            else:
                reasons = []
            decision = (
                FinalParkingStage.VERIFIED
                if not failed
                else FinalParkingStage.NOT_COMPLETED
            )
            result = FinalParkingResult(
                decision=decision,
                parking_completed=False,
                task_id=inputs.task_id,
                bay_id=inputs.bay_id,
                slot_node_id=inputs.slot_node_id,
                vehicle_actor_id=vehicle.actor_id,
                entry_artifact_sha256=inputs.entry_artifact_sha256,
                pose_ready_artifact_sha256=inputs.pose_ready_artifact_sha256,
                entry_completion_id=artifact["entry_completion_id"],
                refinement_plan_hash=artifact["plan_hash"],
                verification_frame=vehicle.frame,
                verification_timestamp_utc=now,
                initial_transform=(
                    None
                    if pose_pose is None
                    else {
                        "x": pose_pose[0],
                        "y": pose_pose[1],
                        "yaw_rad": pose_pose[2],
                        "source": "PARKING_POSE_READY artifact",
                    }
                ),
                final_transform={
                    "x": float(vehicle.x),
                    "y": float(vehicle.y),
                    "yaw_rad": yaw,
                    "frame": vehicle.frame,
                    "source": "live CARLA transform",
                },
                measurement=measurement,
                stability=stability,
                collision=collision.to_metadata(),
                obstacle={
                    **inputs.obstacle_evidence.to_metadata(),
                    "clearance_m": measurement.obstacle_clearance_m,
                },
                velocity_samples=tuple(
                    sample.to_metadata() for sample in inputs.stability_samples
                ),
                checks=checks,
                failed_checks=failed,
                reasons=tuple(dict.fromkeys(reasons)),
                limitations=FINAL_VERIFICATION_LIMITATIONS,
            )
            payload = result.payload()
            return replace(
                result, result_sha256=artifact_sha256(payload)
            )
        except Exception as error:
            return self._not_completed(
                inputs,
                checks,
                reasons=(
                    f"verification_exception: {type(error).__name__}: {error}",
                ),
                now=now,
            )

    def _not_completed(
        self,
        inputs: FinalParkingInputs,
        checks: Mapping[str, bool],
        *,
        reasons: Sequence[str],
        now: str,
    ) -> FinalParkingResult:
        failed = tuple(
            key for key in REQUIRED_FINAL_CHECKS if not checks.get(key, False)
        )
        result = FinalParkingResult(
            decision=FinalParkingStage.NOT_COMPLETED,
            parking_completed=False,
            task_id=str(inputs.task_id),
            bay_id=str(inputs.bay_id),
            slot_node_id=str(inputs.slot_node_id),
            vehicle_actor_id=(
                inputs.vehicle.actor_id
                if isinstance(inputs.vehicle, VehicleSnapshot)
                else None
            ),
            entry_artifact_sha256=inputs.entry_artifact_sha256
            if _nonblank(inputs.entry_artifact_sha256)
            else None,
            pose_ready_artifact_sha256=inputs.pose_ready_artifact_sha256
            if _nonblank(inputs.pose_ready_artifact_sha256)
            else None,
            entry_completion_id=None,
            refinement_plan_hash=None,
            verification_frame=(
                inputs.vehicle.frame
                if isinstance(inputs.vehicle, VehicleSnapshot)
                and type(inputs.vehicle.frame) is int
                else None
            ),
            verification_timestamp_utc=now,
            initial_transform=None,
            final_transform=None,
            measurement=None,
            stability=None,
            collision=None,
            obstacle=None,
            velocity_samples=(),
            checks={key: bool(checks.get(key, False)) for key in REQUIRED_FINAL_CHECKS},
            failed_checks=failed,
            reasons=tuple(dict.fromkeys(str(reason) for reason in reasons))
            or ("final_parking_verification_not_completed",),
            limitations=FINAL_VERIFICATION_LIMITATIONS,
        )
        payload = result.payload()
        return replace(result, result_sha256=artifact_sha256(payload))

    def _validate_inputs(
        self, inputs: FinalParkingInputs
    ) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []

        def bad(reason: str) -> None:
            reasons.append(reason)

        if not isinstance(inputs, FinalParkingInputs):
            return False, ("inputs_not_final_parking_inputs",)
        for name in (
            "task_id",
            "bay_id",
            "slot_node_id",
            "entry_task_id",
            "refinement_task_id",
            "entry_authorization_id",
        ):
            if not _nonblank(getattr(inputs, name)):
                bad(f"{name}_missing")
        if type(inputs.expected_vehicle_actor_id) is not int:
            bad("expected_vehicle_actor_id_missing")
        vehicle = inputs.vehicle
        if not isinstance(vehicle, VehicleSnapshot):
            bad("vehicle_snapshot_missing")
        else:
            if type(vehicle.actor_id) is not int or vehicle.actor_id <= 0:
                bad("vehicle_actor_id_invalid")
            if not _nonblank(vehicle.type_id):
                bad("vehicle_type_id_missing")
            if type(vehicle.frame) is not int or vehicle.frame < 0:
                bad("vehicle_frame_invalid")
            for name in (
                "x",
                "y",
                "z",
                "yaw_rad",
                "half_length",
                "half_width",
                "half_height",
                "bbox_offset_x",
                "bbox_offset_y",
                "bbox_offset_z",
                "velocity_x",
                "velocity_y",
                "velocity_z",
                "speed_mps",
            ):
                value = getattr(vehicle, name)
                if not _finite(value):
                    bad(f"vehicle_{name}_invalid")
            if _finite(vehicle.half_length) and float(vehicle.half_length) <= 0.0:
                bad("vehicle_half_length_invalid")
            if _finite(vehicle.half_width) and float(vehicle.half_width) <= 0.0:
                bad("vehicle_half_width_invalid")
            if _finite(vehicle.speed_mps) and float(vehicle.speed_mps) < 0.0:
                bad("vehicle_speed_negative")
        if not isinstance(inputs.config_footprint, Footprint):
            bad("config_footprint_missing")
        try:
            polygon = tuple(
                (float(px), float(py)) for px, py in inputs.bay_polygon
            )
        except (TypeError, ValueError, IndexError):
            polygon = ()
        if len(polygon) < 3 or any(
            not math.isfinite(px) or not math.isfinite(py) for px, py in polygon
        ):
            bad("bay_polygon_invalid")
        try:
            center = (
                float(inputs.bay_center[0]),
                float(inputs.bay_center[1]),
            )
        except (TypeError, ValueError, IndexError):
            center = ()
        if len(center) != 2 or not all(math.isfinite(value) for value in center):
            bad("bay_center_invalid")
        if not _finite(inputs.bay_heading_rad):
            bad("bay_heading_invalid")
        obstacle = inputs.obstacle_evidence
        if not isinstance(obstacle, ObstacleEvidence):
            bad("obstacle_evidence_missing")
        else:
            if not _nonblank(obstacle.source):
                bad("obstacle_source_missing")
            if type(obstacle.live) is not bool:
                bad("obstacle_live_flag_invalid")
            if not obstacle.points:
                bad("obstacle_points_missing")
            for index, point in enumerate(obstacle.points):
                try:
                    px, py = float(point[0]), float(point[1])
                except (TypeError, ValueError, IndexError):
                    bad(f"obstacle_point_{index}_invalid")
                    continue
                if not math.isfinite(px) or not math.isfinite(py):
                    bad(f"obstacle_point_{index}_invalid")
        collision = inputs.collision
        if not isinstance(collision, CollisionEvidence):
            bad("collision_evidence_missing")
        else:
            if type(collision.sensor_available) is not bool:
                bad("collision_sensor_flag_invalid")
            if type(collision.current_frame) is not int:
                bad("collision_current_frame_invalid")
        if not isinstance(inputs.stability_samples, tuple):
            bad("stability_samples_must_be_a_tuple")
        if not isinstance(inputs.entry_artifact, Mapping):
            bad("entry_artifact_missing")
        if not isinstance(inputs.pose_ready_artifact, Mapping):
            bad("pose_ready_artifact_missing")
        if not _nonblank(inputs.entry_artifact_sha256):
            bad("entry_artifact_sha256_missing")
        if not _nonblank(inputs.pose_ready_artifact_sha256):
            bad("pose_ready_artifact_sha256_missing")
        if type(inputs.entry_frame) is not int or inputs.entry_frame < 0:
            bad("entry_frame_invalid")
        if type(inputs.pose_ready_frame) is not int or inputs.pose_ready_frame < 0:
            bad("pose_ready_frame_invalid")
        if not isinstance(inputs.actor_alive, bool):
            bad("actor_alive_flag_invalid")
        if not isinstance(inputs.actor_id_consistent, bool):
            bad("actor_id_consistent_flag_invalid")
        if not isinstance(inputs.bay_identity_consistent, bool):
            bad("bay_identity_consistent_flag_invalid")
        if inputs.tolerances is None:
            bad("tolerances_missing")
        return (not reasons, tuple(dict.fromkeys(reasons)))

    def _artifact_checks(
        self,
        inputs: FinalParkingInputs,
        tolerances: FinalParkingTolerances,
    ) -> dict:
        reasons: list[str] = []
        checks = {
            "entry_artifact_valid": False,
            "entry_artifact_hash": False,
            "pose_ready_artifact_valid": False,
            "pose_ready_artifact_hash": False,
            "stage_chain_causal": False,
        }
        entry = inputs.entry_artifact
        pose = inputs.pose_ready_artifact
        entry_hash = artifact_sha256(dict(entry)) if isinstance(entry, Mapping) else None
        pose_hash = artifact_sha256(dict(pose)) if isinstance(pose, Mapping) else None
        checks["entry_artifact_hash"] = bool(
            entry_hash is not None
            and _nonblank(inputs.entry_artifact_sha256)
            and entry_hash == inputs.entry_artifact_sha256
        )
        checks["pose_ready_artifact_hash"] = bool(
            pose_hash is not None
            and _nonblank(inputs.pose_ready_artifact_sha256)
            and pose_hash == inputs.pose_ready_artifact_sha256
        )
        if not checks["entry_artifact_hash"]:
            reasons.append("entry_artifact_hash_mismatch")
        if not checks["pose_ready_artifact_hash"]:
            reasons.append("pose_ready_artifact_hash_mismatch")

        entry_stage = entry.get("stage")
        entry_measurement = entry.get("measurement")
        entry_pose = _artifact_pose(entry)
        checks["entry_artifact_valid"] = bool(
            entry_stage == "ENTRY_COMPLETED"
            and entry.get("completed") is True
            and entry.get("entry_valid") is True
            and entry.get("identity_verified") is True
            and entry.get("task_id") == inputs.entry_task_id
            and _nonblank(entry.get("route_hash"))
            and entry_pose is not None
            and isinstance(entry_measurement, Mapping)
            and _finite(entry_measurement.get("boundary_clearance_m"))
            and _finite(entry_measurement.get("heading_error_deg"))
        )
        if not checks["entry_artifact_valid"]:
            reasons.append("entry_artifact_invalid")

        pose_stage = pose.get("stage")
        pose_measurement = pose.get("measurement")
        pose_pose = _artifact_pose(pose)
        pose_checks = pose.get("checks")
        checks["pose_ready_artifact_valid"] = bool(
            pose_stage == "PARKING_POSE_READY"
            and pose.get("ready") is True
            and pose.get("parking_completed") is False
            and pose.get("identity_verified") is True
            and pose.get("authorization_verified") is True
            and pose.get("task_id") == inputs.refinement_task_id
            and _nonblank(pose.get("entry_completion_id"))
            and _nonblank(pose.get("plan_hash"))
            and pose_pose is not None
            and isinstance(pose_measurement, Mapping)
            and isinstance(pose_checks, Mapping)
            and len(pose_checks) > 0
            and all(value is True for value in pose_checks.values())
            and not pose.get("reasons")
        )
        if not checks["pose_ready_artifact_valid"]:
            reasons.append("pose_ready_artifact_invalid")

        entry_completion_id = None
        plan_hash = None
        causal = False
        try:
            if checks["entry_artifact_valid"] and checks["pose_ready_artifact_valid"]:
                chain = pose.get("entry_completion_inputs")
                if not isinstance(chain, Mapping):
                    raise ValueError(
                        "pose-ready artifact has no entry_completion_inputs"
                    )
                chain_pose_raw = chain.get("final_pose")
                if (
                    not isinstance(chain_pose_raw, Sequence)
                    or isinstance(chain_pose_raw, (str, bytes))
                    or len(chain_pose_raw) != 3
                ):
                    raise ValueError(
                        "entry_completion_inputs.final_pose must have 3 values"
                    )
                chain_pose = tuple(float(value) for value in chain_pose_raw)
                if not all(math.isfinite(value) for value in chain_pose):
                    raise ValueError(
                        "entry_completion_inputs.final_pose is not finite"
                    )
                if chain.get("entry_task_id") != inputs.entry_task_id:
                    raise ValueError(
                        "entry_completion_inputs entry task mismatch"
                    )
                if chain.get("parking_task_id") != inputs.task_id:
                    raise ValueError(
                        "entry_completion_inputs parking task mismatch"
                    )
                if chain.get("vehicle_actor_id") != inputs.vehicle.actor_id:
                    raise ValueError(
                        "entry_completion_inputs vehicle mismatch"
                    )
                if chain.get("entry_authorization_id") != inputs.entry_authorization_id:
                    raise ValueError(
                        "entry_completion_inputs authorization mismatch"
                    )
                if chain.get("entry_route_hash") != entry.get("route_hash"):
                    raise ValueError("entry_completion_inputs route mismatch")
                if chain.get("final_verification_stage") != "ENTRY_COMPLETED":
                    raise ValueError("entry_completion_inputs stage mismatch")
                recomputed = compute_entry_completion_id(
                    entry_task_id=str(chain["entry_task_id"]),
                    entry_authorization_id=str(chain["entry_authorization_id"]),
                    entry_route_hash=str(chain["entry_route_hash"]),
                    final_pose=chain_pose,
                    final_verification_stage=str(
                        chain["final_verification_stage"]
                    ),
                    final_boundary_clearance_m=(
                        None
                        if chain.get("final_boundary_clearance_m") is None
                        else float(chain["final_boundary_clearance_m"])
                    ),
                    final_heading_error_deg=float(
                        chain["final_heading_error_deg"]
                    ),
                )
                entry_pose_gap, entry_heading_gap = _pose_gap(
                    chain_pose, entry_pose
                )
                entry_completion_id = str(pose["entry_completion_id"])
                plan_hash = str(pose["plan_hash"])
                causal = bool(
                    recomputed == entry_completion_id
                    and chain.get("entry_completion_id")
                    == entry_completion_id
                    and entry_pose_gap <= 0.01
                    and entry_heading_gap <= 0.01
                    and type(inputs.entry_frame) is int
                    and type(inputs.pose_ready_frame) is int
                    and inputs.entry_frame <= inputs.pose_ready_frame
                    and inputs.pose_ready_frame <= inputs.vehicle.frame
                    and inputs.vehicle.frame - inputs.pose_ready_frame
                    <= tolerances.max_final_frame_gap
                )
        except Exception as error:
            reasons.append(f"stage_chain_error: {type(error).__name__}: {error}")
        checks["stage_chain_causal"] = causal
        if not causal:
            reasons.append("stage_chain_not_causal")

        entry_actor = entry.get("vehicle_actor_id")
        pose_actor = pose.get("vehicle_actor_id")
        return {
            "checks": checks,
            "reasons": tuple(dict.fromkeys(reasons)),
            "entry_task_id": entry.get("task_id"),
            "refinement_task_id": pose.get("task_id"),
            "entry_bay_id": entry.get("bay_id"),
            "pose_bay_id": pose.get("bay_id"),
            "entry_slot_node_id": entry.get("slot_node_id"),
            "pose_slot_node_id": pose.get("slot_node_id"),
            "entry_vehicle_actor_id": entry_actor,
            "pose_vehicle_actor_id": pose_actor,
            "entry_completion_id": entry_completion_id,
            "plan_hash": plan_hash,
            "pose_pose": pose_pose,
        }


@dataclass(frozen=True)
class CompletionRequest:
    source: str
    verifier_result: Optional[object]
    task_id: str
    bay_id: str
    slot_node_id: str
    vehicle_actor_id: int
    current_frame: int
    now: Optional[str] = None


@dataclass(frozen=True)
class CompletionDecision:
    decision: str
    parking_completed: bool
    task_id: str
    bay_id: str
    slot_node_id: str
    vehicle_actor_id: int
    verifier_result_sha256: Optional[str]
    verification_frame: Optional[int]
    checks: Mapping[str, bool]
    failed_checks: tuple[str, ...]
    reasons: tuple[str, ...]
    task_state: Mapping[str, object]
    decided_at_utc: str
    decision_id: str
    gate_version: str = COMPLETION_GATE_VERSION
    idempotent_replay: bool = False
    limitations: tuple[str, ...] = FINAL_VERIFICATION_LIMITATIONS

    def __post_init__(self) -> None:
        if self.decision not in CompletionStage.ALL:
            raise ValueError(f"unknown completion decision {self.decision!r}")
        if self.parking_completed != (self.decision == CompletionStage.COMPLETED):
            raise ValueError(
                "parking_completed must be true exactly for PARKING_COMPLETED"
            )

    def to_metadata(self) -> dict:
        return {
            "schema": COMPLETION_GATE_VERSION,
            "gate_version": self.gate_version,
            "decision": self.decision,
            "parking_completed": self.parking_completed,
            "task_id": self.task_id,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "vehicle_actor_id": self.vehicle_actor_id,
            "verifier_result_sha256": self.verifier_result_sha256,
            "verification_frame": self.verification_frame,
            "checks": dict(self.checks),
            "failed_checks": list(self.failed_checks),
            "reasons": list(self.reasons),
            "task_state": dict(self.task_state),
            "decided_at_utc": self.decided_at_utc,
            "decision_id": self.decision_id,
            "idempotent_replay": self.idempotent_replay,
            "limitations": list(self.limitations),
        }


class ParkingCompletionGate:
    """The only component allowed to issue ``PARKING_COMPLETED``."""

    def __init__(self, tolerances: Optional[FinalParkingTolerances] = None) -> None:
        self.tolerances = tolerances or FinalParkingTolerances()
        self._decisions: dict[str, CompletionDecision] = {}

    def submit(self, request: CompletionRequest) -> CompletionDecision:
        now = request.now or _utc_now()
        reasons: list[str] = []
        checks = {key: False for key in REQUIRED_FINAL_CHECKS}
        result_payload: Optional[Mapping[str, object]] = None
        result_sha: Optional[str] = None

        if not isinstance(request, CompletionRequest):
            return self._reject(
                None,
                {},
                ("completion_request_invalid",),
                now,
                task_id="",
                bay_id="",
                slot_node_id="",
                vehicle_actor_id=0,
            )
        if request.source != CompletionSource.FINAL_PARKING_VERIFIER:
            reasons.append("completion_source_not_authorized")
            return self._reject(
                request,
                checks,
                reasons,
                now,
            )
        if request.verifier_result is None:
            reasons.append("verifier_result_missing")
            return self._reject(request, checks, reasons, now)

        try:
            if isinstance(request.verifier_result, FinalParkingResult):
                result_payload = request.verifier_result.payload()
                result_sha = artifact_sha256(result_payload)
                if request.verifier_result.result_sha256 != result_sha:
                    raise VerificationIntegrityError(
                        "FinalParkingResult hash does not match its payload"
                    )
            elif isinstance(request.verifier_result, Mapping):
                raw = dict(request.verifier_result)
                claimed = raw.pop("result_sha256", None)
                if not _nonblank(claimed):
                    raise VerificationIntegrityError(
                        "verifier result has no result_sha256"
                    )
                result_sha = artifact_sha256(raw)
                if result_sha != claimed:
                    raise VerificationIntegrityError(
                        "verifier result hash does not match its payload"
                    )
                result_payload = raw
            else:
                raise VerificationIntegrityError(
                    "verifier result must be a FinalParkingResult or mapping"
                )
        except VerificationIntegrityError as error:
            reasons.append(f"verifier_result_tampered: {error}")
            return self._reject(request, checks, reasons, now)

        checks = {
            str(key): bool(value)
            for key, value in dict(result_payload.get("checks") or {}).items()
        }
        failed = tuple(
            key for key in REQUIRED_FINAL_CHECKS if not checks.get(key, False)
        )
        if failed:
            reasons.append("verifier_checks_failed")
            reasons.extend(failed)
        if result_payload.get("decision") != FinalParkingStage.VERIFIED:
            reasons.append("verifier_did_not_verify")
        if result_payload.get("verification_passed") is not True:
            reasons.append("verifier_not_passed")
        if result_payload.get("parking_completed") is not False:
            reasons.append("verifier_must_not_sign_completion")
        if result_payload.get("producer") != CompletionSource.FINAL_PARKING_VERIFIER:
            reasons.append("verifier_producer_not_authorized")
        if result_payload.get("verifier_version") != FINAL_VERIFICATION_VERSION:
            reasons.append("verifier_version_unsupported")
        if tuple(result_payload.get("failed_checks") or ()):
            reasons.append("verifier_failed_checks_present")
        if request.task_id != result_payload.get("task_id"):
            reasons.append("task_identity_mismatch")
        if request.bay_id != result_payload.get("bay_id"):
            reasons.append("bay_identity_mismatch")
        if request.slot_node_id != result_payload.get("slot_node_id"):
            reasons.append("slot_identity_mismatch")
        if request.vehicle_actor_id != result_payload.get("vehicle_actor_id"):
            reasons.append("vehicle_identity_mismatch")
        verification_frame = result_payload.get("verification_frame")
        if type(verification_frame) is not int:
            reasons.append("verification_frame_missing")
        else:
            if type(request.current_frame) is not int:
                reasons.append("current_frame_invalid")
            elif request.current_frame < verification_frame:
                reasons.append("current_frame_before_verification")
            elif (
                request.current_frame - verification_frame
                > self.tolerances.max_final_frame_gap
            ):
                reasons.append("verification_result_stale")
        try:
            verified_at = _parse_time(
                result_payload.get("verification_timestamp_utc"),
                "verification_timestamp_utc",
            )
            decided_at = _parse_time(now, "now")
            age = (decided_at - verified_at).total_seconds()
            if age < -1e-6:
                reasons.append("verification_timestamp_in_future")
            elif age > self.tolerances.max_verification_age_s:
                reasons.append("verification_result_expired")
        except ValueError as error:
            reasons.append(f"verification_timestamp_invalid: {error}")

        if reasons:
            return self._reject(request, checks, reasons, now, result_sha=result_sha)
        return self._issue(
            request,
            checks,
            result_sha,
            now,
            verification_frame=verification_frame,
        )

    def _decision_id(
        self,
        request: CompletionRequest,
        result_sha: Optional[str],
    ) -> str:
        return artifact_sha256(
            {
                "gate_version": COMPLETION_GATE_VERSION,
                "task_id": request.task_id,
                "bay_id": request.bay_id,
                "slot_node_id": request.slot_node_id,
                "vehicle_actor_id": request.vehicle_actor_id,
                "verifier_result_sha256": result_sha,
            }
        )

    def _issue(
        self,
        request: CompletionRequest,
        checks: Mapping[str, bool],
        result_sha: Optional[str],
        now: str,
        *,
        verification_frame: Optional[int] = None,
    ) -> CompletionDecision:
        decision_id = self._decision_id(request, result_sha)
        if decision_id in self._decisions:
            return replace(
                self._decisions[decision_id], idempotent_replay=True
            )
        decision = CompletionDecision(
            decision=CompletionStage.COMPLETED,
            parking_completed=True,
            task_id=request.task_id,
            bay_id=request.bay_id,
            slot_node_id=request.slot_node_id,
            vehicle_actor_id=request.vehicle_actor_id,
            verifier_result_sha256=result_sha,
            verification_frame=verification_frame,
            checks=dict(checks),
            failed_checks=(),
            reasons=(),
            task_state={
                "task_id": request.task_id,
                "stage": CompletionStage.COMPLETED,
                "vehicle_actor_id": request.vehicle_actor_id,
                "bay_id": request.bay_id,
                "slot_node_id": request.slot_node_id,
                "gate_decision_id": decision_id,
                "source": "parking_completion_gate",
                "verifier_result_sha256": result_sha,
            },
            decided_at_utc=now,
            decision_id=decision_id,
        )
        self._decisions[decision_id] = decision
        return decision

    def _reject(
        self,
        request: Optional[CompletionRequest],
        checks: Mapping[str, bool],
        reasons: Sequence[str],
        now: str,
        *,
        task_id: Optional[str] = None,
        bay_id: Optional[str] = None,
        slot_node_id: Optional[str] = None,
        vehicle_actor_id: Optional[int] = None,
        result_sha: Optional[str] = None,
    ) -> CompletionDecision:
        task_id = task_id if task_id is not None else getattr(request, "task_id", "")
        bay_id = bay_id if bay_id is not None else getattr(request, "bay_id", "")
        slot_node_id = (
            slot_node_id
            if slot_node_id is not None
            else getattr(request, "slot_node_id", "")
        )
        actor_id = (
            vehicle_actor_id
            if vehicle_actor_id is not None
            else getattr(request, "vehicle_actor_id", 0)
        )
        reason_tuple = tuple(dict.fromkeys(str(reason) for reason in reasons))
        return CompletionDecision(
            decision=CompletionStage.NOT_COMPLETED,
            parking_completed=False,
            task_id=str(task_id),
            bay_id=str(bay_id),
            slot_node_id=str(slot_node_id),
            vehicle_actor_id=int(actor_id) if type(actor_id) is int else 0,
            verifier_result_sha256=result_sha,
            verification_frame=None,
            checks={key: bool(checks.get(key, False)) for key in REQUIRED_FINAL_CHECKS},
            failed_checks=tuple(
                key for key in REQUIRED_FINAL_CHECKS if not checks.get(key, False)
            ),
            reasons=reason_tuple or ("parking_completion_rejected",),
            task_state={
                "task_id": str(task_id),
                "stage": CompletionStage.NOT_COMPLETED,
                "vehicle_actor_id": actor_id,
                "bay_id": str(bay_id),
                "slot_node_id": str(slot_node_id),
                "source": "parking_completion_gate",
                "verifier_result_sha256": result_sha,
            },
            decided_at_utc=now,
            decision_id=artifact_sha256(
                {
                    "gate_version": COMPLETION_GATE_VERSION,
                    "task_id": str(task_id),
                    "bay_id": str(bay_id),
                    "slot_node_id": str(slot_node_id),
                    "vehicle_actor_id": actor_id,
                    "verifier_result_sha256": result_sha,
                    "reasons": list(reason_tuple),
                    "decided_at_utc": now,
                }
            ),
        )


def reject_ungated_parking_completion(source: str) -> None:
    """Legacy/state writers must call this instead of setting completion."""

    raise CompletionGateError(
        f"{source!r} cannot set PARKING_COMPLETED; only ParkingCompletionGate "
        "may issue it from a FinalParkingVerifier result"
    )


def require_gate_decision(decision: object) -> bool:
    """Return True only for a real gate decision that may update task state."""

    if not isinstance(decision, CompletionDecision):
        raise CompletionGateError("PARKING_COMPLETED requires a CompletionDecision")
    if decision.gate_version != COMPLETION_GATE_VERSION:
        raise CompletionGateError("completion decision gate version is not current")
    if (
        decision.decision != CompletionStage.COMPLETED
        or decision.parking_completed is not True
    ):
        raise CompletionGateError("completion decision did not pass the gate")
    return True
