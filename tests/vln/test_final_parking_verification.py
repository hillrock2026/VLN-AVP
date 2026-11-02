"""Final parking verification and completion gate tests (CAP-07B-06)."""

from __future__ import annotations

import json
import math
import re
from dataclasses import replace
from pathlib import Path

import pytest

from vln.carla.parking_geometry import Footprint
from vln.carla.parking_verdict import (
    BAY03_CENTER,
    BAY03_POLYGON,
    PARKING_FOOTPRINT,
)
from vln.parking.completion import (
    FINAL_VERIFICATION_VERSION,
    REQUIRED_FINAL_CHECKS,
    CollisionEvidence,
    CompletionGateError,
    CompletionRequest,
    CompletionSource,
    CompletionStage,
    FinalParkingInputs,
    FinalParkingStage,
    FinalParkingTolerances,
    FinalParkingVerifier,
    ObstacleEvidence,
    ParkingCompletionGate,
    StabilitySample,
    VehicleSnapshot,
    artifact_sha256,
    measure_final_stability,
    reject_ungated_parking_completion,
    require_gate_decision,
    verify_result_metadata,
)
from vln.parking.refinement import compute_entry_completion_id

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-10-31T00:00:00+00:00"
BAY = tuple((float(x), float(y)) for x, y in BAY03_POLYGON)
CENTER = (float(BAY03_CENTER[0]), float(BAY03_CENTER[1]))
POSE = (-9.4816, -21.1966, -3.104287)
ENTRY_AUTH = "a" * 64
ENTRY_ROUTE_HASH = "r" * 64
PLAN_HASH = "p" * 64
OBSTACLES = tuple(
    (float(point[0]), float(point[1]))
    for point in json.loads(
        (
            REPO_ROOT / "tests" / "fixtures" / "carla_07a_geometry_probe.json"
        ).read_text(encoding="utf-8")
    )["obstacle_points"]
)
POSE_CHECKS = {
    key: True
    for key in (
        "identity",
        "authorization",
        "footprint_inside_bay",
        "boundary_clearance",
        "obstacle_clearance",
        "heading",
        "position",
        "stopped",
        "stop_stable",
        "no_collision",
    )
}


def _entry_artifact() -> dict:
    return {
        "schema": "vln.parking.entry_result.v1",
        "skill": "vln.parking.entry",
        "stage": "ENTRY_COMPLETED",
        "task_id": "cap07b-04",
        "bay_id": "bay03",
        "slot_node_id": "park_slot",
        "approach_node_id": "park_entry",
        "route_id": "bay03-entry-test",
        "route_hash": ENTRY_ROUTE_HASH,
        "entry_valid": True,
        "completed": True,
        "identity_verified": True,
        "authorization_verified": True,
        "checks": {"all": True},
        "reasons": [],
        "measurement": {
            "x": -9.4864,
            "y": -21.2488,
            "yaw_rad": -3.081319,
            "boundary_clearance_m": 0.052,
            "heading_error_deg": 3.4534,
        },
        "vehicle_actor_id": 681,
    }


def _entry_completion_id(entry: dict | None = None) -> str:
    entry = entry or _entry_artifact()
    measurement = entry["measurement"]
    return compute_entry_completion_id(
        entry_task_id="cap07b-04",
        entry_authorization_id=ENTRY_AUTH,
        entry_route_hash=str(entry["route_hash"]),
        final_pose=(
            float(measurement["x"]),
            float(measurement["y"]),
            float(measurement["yaw_rad"]),
        ),
        final_verification_stage="ENTRY_COMPLETED",
        final_boundary_clearance_m=float(measurement["boundary_clearance_m"]),
        final_heading_error_deg=float(measurement["heading_error_deg"]),
    )


def _pose_artifact(
    *,
    pose: tuple[float, float, float] = POSE,
    entry_completion_id: str | None = None,
) -> dict:
    completion_id = entry_completion_id or _entry_completion_id()
    entry_measurement = _entry_artifact()["measurement"]
    return {
        "schema": "vln.parking.refinement_result.v1",
        "skill": "vln.parking.refinement",
        "stage": "PARKING_POSE_READY",
        "task_id": "cap07b-05",
        "bay_id": "bay03",
        "slot_node_id": "park_slot",
        "entry_completion_id": completion_id,
        "plan_hash": PLAN_HASH,
        "identity_verified": True,
        "authorization_verified": True,
        "ready": True,
        "parking_completed": False,
        "checks": dict(POSE_CHECKS),
        "reasons": [],
        "measurement": {
            "x": pose[0],
            "y": pose[1],
            "yaw_rad": pose[2],
        },
        "entry_completion_inputs": {
            "entry_task_id": "cap07b-04",
            "parking_task_id": "cap07b-06",
            "vehicle_actor_id": 681,
            "entry_authorization_id": ENTRY_AUTH,
            "entry_route_hash": ENTRY_ROUTE_HASH,
            "final_pose": [
                entry_measurement["x"],
                entry_measurement["y"],
                entry_measurement["yaw_rad"],
            ],
            "final_verification_stage": "ENTRY_COMPLETED",
            "final_boundary_clearance_m": entry_measurement[
                "boundary_clearance_m"
            ],
            "final_heading_error_deg": entry_measurement[
                "heading_error_deg"
            ],
            "entry_completion_id": completion_id,
        },
        "vehicle_actor_id": 681,
    }


def _samples(
    *,
    count: int = 5,
    x: float = POSE[0],
    y: float = POSE[1],
    yaw: float = POSE[2],
    drift_x: float = 0.0,
    heading_drift: float = 0.0,
    speed: float = 0.0,
) -> tuple[StabilitySample, ...]:
    return tuple(
        StabilitySample(
            frame=1110 + index,
            sim_time=55.5 + index * 0.05,
            x=x + (drift_x if index else 0.0),
            y=y,
            yaw_rad=yaw + (heading_drift if index else 0.0),
            speed_mps=speed,
        )
        for index in range(count)
    )


def _inputs(**overrides) -> FinalParkingInputs:
    entry = _entry_artifact()
    pose = _pose_artifact()
    base = FinalParkingInputs(
        task_id="cap07b-06",
        bay_id="bay03",
        slot_node_id="park_slot",
        entry_task_id="cap07b-04",
        refinement_task_id="cap07b-05",
        entry_authorization_id=ENTRY_AUTH,
        expected_vehicle_actor_id=681,
        vehicle=VehicleSnapshot(
            actor_id=681,
            type_id="vehicle.dodge.charger",
            x=POSE[0],
            y=POSE[1],
            z=5.7859,
            yaw_rad=POSE[2],
            frame=1114,
            half_length=2.503,
            half_width=0.9405,
            half_height=0.7702,
        ),
        config_footprint=PARKING_FOOTPRINT,
        bay_polygon=BAY,
        bay_center=CENTER,
        bay_heading_rad=math.pi,
        obstacle_evidence=ObstacleEvidence(
            source="historical_static_samples",
            points=OBSTACLES,
            live=False,
            coverage_note="29 historical static collision-mesh samples",
            historical_point_count=len(OBSTACLES),
        ),
        collision=CollisionEvidence(
            sensor_available=True,
            sensor_role="vln_test_collision",
            monitoring_started_frame=1000,
            monitoring_started_utc=NOW,
            first_motion_frame=1010,
            current_frame=1114,
        ),
        stability_samples=_samples(),
        actor_alive=True,
        actor_id_consistent=True,
        bay_identity_consistent=True,
        entry_artifact=entry,
        entry_artifact_sha256=artifact_sha256(entry),
        pose_ready_artifact=pose,
        pose_ready_artifact_sha256=artifact_sha256(pose),
        entry_frame=1000,
        pose_ready_frame=1100,
        now=NOW,
    )
    return replace(base, **overrides)


def _with_vehicle(
    x: float = POSE[0],
    y: float = POSE[1],
    yaw: float = POSE[2],
    **vehicle_kwargs,
) -> FinalParkingInputs:
    """Move the current state and the pose-ready artifact together."""

    base = _inputs()
    vehicle = replace(
        base.vehicle, x=x, y=y, yaw_rad=yaw, **vehicle_kwargs
    )
    pose = dict(base.pose_ready_artifact)
    pose["measurement"] = {
        **pose["measurement"],
        "x": x,
        "y": y,
        "yaw_rad": yaw,
    }
    return replace(
        base,
        vehicle=vehicle,
        pose_ready_artifact=pose,
        pose_ready_artifact_sha256=artifact_sha256(pose),
    )


def _verify(inputs: FinalParkingInputs):
    return FinalParkingVerifier().verify(inputs)


def _gate_request(result, **overrides) -> CompletionRequest:
    base = CompletionRequest(
        source=CompletionSource.FINAL_PARKING_VERIFIER,
        verifier_result=result,
        task_id="cap07b-06",
        bay_id="bay03",
        slot_node_id="park_slot",
        vehicle_actor_id=681,
        current_frame=1114,
        now=NOW,
    )
    return replace(base, **overrides)


# --- geometry ---------------------------------------------------------------


def test_valid_parking_is_verified() -> None:
    result = _verify(_inputs())
    assert result.decision == FinalParkingStage.VERIFIED
    assert result.parking_completed is False
    assert result.failed_checks == ()
    assert set(result.checks) == set(REQUIRED_FINAL_CHECKS)
    assert all(result.checks.values())
    assert result.measurement is not None
    assert result.measurement.boundary_clearance_m == pytest.approx(0.160, abs=0.002)
    assert result.measurement.heading_error_deg == pytest.approx(2.1375, abs=0.001)
    assert result.measurement.lateral_error_m == pytest.approx(0.0566, abs=0.001)
    assert result.measurement.longitudinal_error_m == pytest.approx(-0.0184, abs=0.001)
    assert result.result_sha256 == verify_result_metadata(result.to_metadata())[
        "result_sha256"
    ]


def test_footprint_partially_outside_bay_fails() -> None:
    result = _verify(_with_vehicle(y=-21.50))
    assert result.decision == FinalParkingStage.NOT_COMPLETED
    assert result.checks["footprint_inside_bay"] is False


def test_footprint_completely_outside_bay_fails() -> None:
    result = _verify(_with_vehicle(x=-2.0, y=-18.0))
    assert result.decision == FinalParkingStage.NOT_COMPLETED
    assert result.checks["footprint_inside_bay"] is False
    assert result.checks["boundary_clearance"] is False


def test_boundary_clearance_below_threshold_fails() -> None:
    result = _verify(
        _inputs(
            tolerances=FinalParkingTolerances(boundary_clearance_m=0.30)
        )
    )
    assert result.checks["boundary_clearance"] is False
    assert result.decision == FinalParkingStage.NOT_COMPLETED


def test_heading_error_over_limit_fails() -> None:
    result = _verify(
        _with_vehicle(yaw=math.radians(-167.0))
    )
    assert result.checks["heading_error"] is False


def test_lateral_error_over_limit_fails() -> None:
    result = _verify(
        _inputs(tolerances=FinalParkingTolerances(lateral_error_m=0.01))
    )
    assert result.checks["lateral_error"] is False


def test_longitudinal_error_over_limit_fails() -> None:
    result = _verify(
        _inputs(tolerances=FinalParkingTolerances(longitudinal_error_m=0.01))
    )
    assert result.checks["longitudinal_error"] is False


def test_position_over_limit_fails() -> None:
    result = _verify(
        _inputs(tolerances=FinalParkingTolerances(position_m=0.01))
    )
    assert result.checks["position_tolerance"] is False


def test_obstacle_clearance_fails() -> None:
    points = OBSTACLES + ((-6.90, -20.50),)
    result = _verify(
        _inputs(
            obstacle_evidence=ObstacleEvidence(
                source="historical_static_samples+test_point",
                points=points,
                live=False,
                coverage_note="test point near the east footprint edge",
                historical_point_count=len(OBSTACLES),
            )
        )
    )
    assert result.checks["obstacle_clearance"] is False
    assert result.measurement.obstacle_clearance_m < 0.20


def test_bbox_size_mismatch_fails() -> None:
    result = _verify(_with_vehicle(half_width=1.20))
    assert result.checks["vehicle_geometry_consistent"] is False
    assert result.decision == FinalParkingStage.NOT_COMPLETED


def test_bbox_submillimetre_difference_is_conservative() -> None:
    result = _verify(_with_vehicle())
    assert result.checks["vehicle_geometry_consistent"] is True
    assert result.measurement is not None
    assert result.measurement.bbox_vs_config_delta_m == pytest.approx(
        0.0005, abs=1e-6
    )
    assert result.measurement.boundary_clearance_m <= (
        result.measurement.config_boundary_clearance_m + 1e-9
    )


def test_invalid_transform_fails_closed() -> None:
    inputs = _inputs(vehicle=replace(_inputs().vehicle, x=float("nan")))
    result = _verify(inputs)
    assert result.decision == FinalParkingStage.NOT_COMPLETED
    assert result.checks["inputs_complete"] is False
    assert any("vehicle_x_invalid" in reason for reason in result.reasons)


def test_invalid_bay_polygon_fails_closed() -> None:
    result = _verify(_inputs(bay_polygon=((-4.0, -19.89), (-14.4, -19.89))))
    assert result.decision == FinalParkingStage.NOT_COMPLETED
    assert result.checks["inputs_complete"] is False
    assert "bay_polygon_invalid" in result.reasons


def test_geometry_exception_fails_closed(monkeypatch) -> None:
    import vln.parking.completion as completion

    def _boom(*args, **kwargs):
        raise RuntimeError("synthetic geometry failure")

    monkeypatch.setattr(completion, "footprint_polygon_clearance", _boom)
    result = _verify(_inputs())
    assert result.decision == FinalParkingStage.NOT_COMPLETED
    assert result.parking_completed is False
    assert any("verification_exception" in reason for reason in result.reasons)


# --- identity and artifacts -------------------------------------------------


def test_vehicle_actor_mismatch_fails() -> None:
    result = _verify(_inputs(expected_vehicle_actor_id=999))
    assert result.checks["vehicle_identity"] is False


def test_artifact_vehicle_actor_mismatch_fails() -> None:
    base = _inputs()
    pose = dict(base.pose_ready_artifact)
    pose["vehicle_actor_id"] = 999
    result = _verify(
        replace(
            base,
            pose_ready_artifact=pose,
            pose_ready_artifact_sha256=artifact_sha256(pose),
        )
    )
    assert result.checks["vehicle_identity"] is False


def test_bay_identity_mismatch_fails() -> None:
    result = _verify(_inputs(bay_id="bay11"))
    assert result.checks["bay_identity"] is False


def test_task_identity_mismatch_fails() -> None:
    result = _verify(_inputs(entry_task_id="cap07b-03"))
    assert result.checks["task_identity"] is False


def test_slot_identity_mismatch_fails() -> None:
    result = _verify(_inputs(slot_node_id="bay11_slot"))
    assert result.checks["slot_identity"] is False


def test_missing_entry_artifact_fails() -> None:
    empty = {}
    result = _verify(
        _inputs(entry_artifact=empty, entry_artifact_sha256=artifact_sha256(empty))
    )
    assert result.checks["entry_artifact_valid"] is False


def test_missing_pose_ready_artifact_fails() -> None:
    empty = {}
    result = _verify(
        _inputs(
            pose_ready_artifact=empty,
            pose_ready_artifact_sha256=artifact_sha256(empty),
        )
    )
    assert result.checks["pose_ready_artifact_valid"] is False


def test_artifact_hash_mismatch_fails() -> None:
    result = _verify(_inputs(entry_artifact_sha256="0" * 64))
    assert result.checks["entry_artifact_hash"] is False
    assert result.checks["entry_artifact_valid"] is True


def test_artifact_tamper_is_detected_by_hash() -> None:
    base = _inputs()
    entry = dict(base.entry_artifact)
    entry["measurement"] = {**entry["measurement"], "x": -9.0}
    result = _verify(replace(base, entry_artifact=entry))
    assert result.checks["entry_artifact_hash"] is False


def test_artifact_from_another_task_fails() -> None:
    base = _inputs()
    entry = dict(base.entry_artifact)
    entry["task_id"] = "cap07b-03"
    result = _verify(
        replace(
            base,
            entry_artifact=entry,
            entry_artifact_sha256=artifact_sha256(entry),
        )
    )
    assert result.checks["task_identity"] is False
    assert result.checks["entry_artifact_valid"] is False


def test_causality_wrong_entry_completion_id_fails() -> None:
    base = _inputs()
    pose = dict(base.pose_ready_artifact)
    pose["entry_completion_id"] = "x" * 64
    result = _verify(
        replace(
            base,
            pose_ready_artifact=pose,
            pose_ready_artifact_sha256=artifact_sha256(pose),
        )
    )
    assert result.checks["stage_chain_causal"] is False


def test_missing_entry_completion_inputs_fails() -> None:
    base = _inputs()
    pose = dict(base.pose_ready_artifact)
    pose.pop("entry_completion_inputs")
    result = _verify(
        replace(
            base,
            pose_ready_artifact=pose,
            pose_ready_artifact_sha256=artifact_sha256(pose),
        )
    )
    assert result.checks["stage_chain_causal"] is False
    assert any("stage_chain_error" in reason for reason in result.reasons)


def test_chain_authorization_mismatch_fails() -> None:
    base = _inputs()
    pose = dict(base.pose_ready_artifact)
    chain = dict(pose["entry_completion_inputs"])
    chain["entry_authorization_id"] = "b" * 64
    pose["entry_completion_inputs"] = chain
    result = _verify(
        replace(
            base,
            pose_ready_artifact=pose,
            pose_ready_artifact_sha256=artifact_sha256(pose),
        )
    )
    assert result.checks["stage_chain_causal"] is False


def test_chain_route_mismatch_fails() -> None:
    base = _inputs()
    pose = dict(base.pose_ready_artifact)
    chain = dict(pose["entry_completion_inputs"])
    chain["entry_route_hash"] = "q" * 64
    pose["entry_completion_inputs"] = chain
    result = _verify(
        replace(
            base,
            pose_ready_artifact=pose,
            pose_ready_artifact_sha256=artifact_sha256(pose),
        )
    )
    assert result.checks["stage_chain_causal"] is False


def test_chain_parking_task_mismatch_fails() -> None:
    base = _inputs()
    pose = dict(base.pose_ready_artifact)
    chain = dict(pose["entry_completion_inputs"])
    chain["parking_task_id"] = "cap07b-99"
    pose["entry_completion_inputs"] = chain
    result = _verify(
        replace(
            base,
            pose_ready_artifact=pose,
            pose_ready_artifact_sha256=artifact_sha256(pose),
        )
    )
    assert result.checks["stage_chain_causal"] is False


def test_chain_vehicle_mismatch_fails() -> None:
    base = _inputs()
    pose = dict(base.pose_ready_artifact)
    chain = dict(pose["entry_completion_inputs"])
    chain["vehicle_actor_id"] = 999
    pose["entry_completion_inputs"] = chain
    result = _verify(
        replace(
            base,
            pose_ready_artifact=pose,
            pose_ready_artifact_sha256=artifact_sha256(pose),
        )
    )
    assert result.checks["stage_chain_causal"] is False


def test_history_masquerading_as_current_state_fails() -> None:
    base = _inputs()
    vehicle = replace(base.vehicle, x=-5.0, y=-20.0)
    result = _verify(replace(base, vehicle=vehicle))
    assert result.checks["current_state_matches_pose_ready"] is False


def test_frame_order_and_freshness_fail() -> None:
    result = _verify(_inputs(pose_ready_frame=1200))
    assert result.checks["stage_chain_causal"] is False
    result = _verify(_inputs(pose_ready_frame=1000, vehicle=replace(_inputs().vehicle, frame=4000)))
    assert result.checks["stage_chain_causal"] is False


# --- stability and collision ------------------------------------------------


def test_single_zero_speed_sample_is_not_stable() -> None:
    result = _verify(_inputs(stability_samples=_samples(count=1)))
    assert result.checks["stability_samples"] is False
    assert result.decision == FinalParkingStage.NOT_COMPLETED


def test_five_zero_speed_samples_are_stable() -> None:
    result = _verify(_inputs(stability_samples=_samples(count=5)))
    assert result.checks["stability_samples"] is True
    assert result.checks["stopped"] is True
    assert result.stability.stable is True


def test_position_drift_fails() -> None:
    result = _verify(_inputs(stability_samples=_samples(drift_x=0.05)))
    assert result.checks["stability_position_drift"] is False


def test_heading_drift_fails() -> None:
    result = _verify(
        _inputs(stability_samples=_samples(heading_drift=math.radians(1.0)))
    )
    assert result.checks["stability_heading_drift"] is False


def test_speed_above_stop_gate_fails() -> None:
    result = _verify(_inputs(stability_samples=_samples(speed=0.10)))
    assert result.checks["stopped"] is False


def test_collision_event_fails() -> None:
    base = _inputs()
    collision = replace(base.collision, task_events=({"frame": 1050},))
    result = _verify(replace(base, collision=collision))
    assert result.checks["no_collision"] is False


def test_verification_collision_event_fails() -> None:
    base = _inputs()
    collision = replace(
        base.collision, verification_events=({"frame": 1112},)
    )
    result = _verify(replace(base, collision=collision))
    assert result.checks["no_collision"] is False


def test_collision_sensor_unavailable_fails() -> None:
    base = _inputs()
    collision = replace(
        base.collision, sensor_available=False, monitoring_started_frame=None
    )
    result = _verify(replace(base, collision=collision))
    assert result.checks["collision_sensor_available"] is False
    assert result.checks["collision_history_complete"] is False


def test_collision_monitor_started_after_motion_fails() -> None:
    base = _inputs()
    collision = replace(
        base.collision, monitoring_started_frame=1020, first_motion_frame=1010
    )
    result = _verify(replace(base, collision=collision))
    assert result.checks["collision_history_complete"] is False


def test_actor_replacement_fails() -> None:
    result = _verify(_inputs(actor_alive=False))
    assert result.checks["actor_stable"] is False
    result = _verify(_inputs(actor_id_consistent=False))
    assert result.checks["actor_stable"] is False


def test_bay_identity_not_stable_fails() -> None:
    result = _verify(_inputs(bay_identity_consistent=False))
    assert result.checks["bay_stable"] is False


def test_state_read_failure_fails_closed() -> None:
    result = _verify(_inputs(vehicle=None))
    assert result.decision == FinalParkingStage.NOT_COMPLETED
    assert result.checks["inputs_complete"] is False


def test_stability_helper_rejects_bad_intervals() -> None:
    samples = (
        StabilitySample(1110, 55.0, POSE[0], POSE[1], POSE[2], 0.0),
        StabilitySample(1112, 56.0, POSE[0], POSE[1], POSE[2], 0.0),
        StabilitySample(1114, 57.0, POSE[0], POSE[1], POSE[2], 0.0),
        StabilitySample(1116, 58.0, POSE[0], POSE[1], POSE[2], 0.0),
        StabilitySample(1118, 59.0, POSE[0], POSE[1], POSE[2], 0.0),
    )
    stability = measure_final_stability(samples, FinalParkingTolerances())
    assert stability.stable is False
    assert "stability_sample_interval" in stability.reasons


# --- completion gate --------------------------------------------------------


def test_gate_issues_completion_for_valid_result() -> None:
    result = _verify(_inputs())
    gate = ParkingCompletionGate()
    decision = gate.submit(_gate_request(result))
    assert decision.decision == CompletionStage.COMPLETED
    assert decision.parking_completed is True
    assert decision.failed_checks == ()
    assert decision.task_state["stage"] == CompletionStage.COMPLETED
    assert decision.verifier_result_sha256 == result.result_sha256
    assert require_gate_decision(decision) is True


def test_gate_rejects_failed_verifier_result() -> None:
    result = _verify(_inputs(stability_samples=_samples(count=1)))
    decision = ParkingCompletionGate().submit(_gate_request(result))
    assert decision.decision == CompletionStage.NOT_COMPLETED
    assert decision.parking_completed is False
    assert "verifier_did_not_verify" in decision.reasons


def test_gate_rejects_missing_result() -> None:
    decision = ParkingCompletionGate().submit(
        _gate_request(None)
    )
    assert decision.decision == CompletionStage.NOT_COMPLETED
    assert "verifier_result_missing" in decision.reasons


def test_gate_rejects_tampered_result_mapping() -> None:
    result = _verify(_inputs())
    metadata = result.to_metadata()
    metadata["checks"] = {**metadata["checks"], "footprint_inside_bay": False}
    decision = ParkingCompletionGate().submit(_gate_request(metadata))
    assert decision.decision == CompletionStage.NOT_COMPLETED
    assert any("tampered" in reason for reason in decision.reasons)


def test_gate_rejects_task_mismatch() -> None:
    result = _verify(_inputs())
    decision = ParkingCompletionGate().submit(
        _gate_request(result, task_id="cap07b-99")
    )
    assert decision.decision == CompletionStage.NOT_COMPLETED
    assert "task_identity_mismatch" in decision.reasons


def test_gate_rejects_bay_and_vehicle_mismatch() -> None:
    result = _verify(_inputs())
    gate = ParkingCompletionGate()
    assert "bay_identity_mismatch" in gate.submit(
        _gate_request(result, bay_id="bay11")
    ).reasons
    assert "vehicle_identity_mismatch" in gate.submit(
        _gate_request(result, vehicle_actor_id=999)
    ).reasons


@pytest.mark.parametrize(
    "source",
    [
        CompletionSource.TAICHU,
        CompletionSource.CARLA_EXECUTOR,
        CompletionSource.ENTRY_SKILL,
        CompletionSource.ALIGNMENT_SKILL,
        CompletionSource.REFINEMENT_SKILL,
        CompletionSource.STATE_UPDATE,
    ],
)
def test_gate_rejects_non_verifier_sources(source: str) -> None:
    result = _verify(_inputs())
    decision = ParkingCompletionGate().submit(
        _gate_request(result, source=source)
    )
    assert decision.decision == CompletionStage.NOT_COMPLETED
    assert "completion_source_not_authorized" in decision.reasons


def test_legacy_state_writer_cannot_bypass_gate() -> None:
    with pytest.raises(CompletionGateError):
        reject_ungated_parking_completion(CompletionSource.STATE_UPDATE)


def test_gate_is_idempotent() -> None:
    result = _verify(_inputs())
    gate = ParkingCompletionGate()
    first = gate.submit(_gate_request(result))
    second = gate.submit(_gate_request(result, now="2026-10-31T00:00:05+00:00"))
    assert second.decision == CompletionStage.COMPLETED
    assert second.idempotent_replay is True
    assert second.decision_id == first.decision_id


def test_gate_rejects_stale_result() -> None:
    result = _verify(_inputs())
    gate = ParkingCompletionGate()
    decision = gate.submit(
        _gate_request(result, current_frame=5000, now="2026-10-31T01:00:00+00:00")
    )
    assert decision.decision == CompletionStage.NOT_COMPLETED
    assert "verification_result_stale" in decision.reasons
    assert "verification_result_expired" in decision.reasons


def test_gate_rejects_not_completed_upgrade() -> None:
    result = _verify(_inputs(stability_samples=_samples(count=1)))
    metadata = result.to_metadata()
    metadata["decision"] = FinalParkingStage.NOT_COMPLETED
    metadata["verification_passed"] = False
    metadata.pop("result_sha256", None)
    metadata["result_sha256"] = artifact_sha256(metadata)
    decision = ParkingCompletionGate().submit(_gate_request(metadata))
    assert decision.decision == CompletionStage.NOT_COMPLETED
    assert "verifier_did_not_verify" in decision.reasons


def test_gate_rejects_verifier_that_signs_completion() -> None:
    result = _verify(_inputs())
    metadata = result.to_metadata()
    metadata["parking_completed"] = True
    metadata.pop("result_sha256", None)
    metadata["result_sha256"] = artifact_sha256(metadata)
    decision = ParkingCompletionGate().submit(_gate_request(metadata))
    assert decision.decision == CompletionStage.NOT_COMPLETED
    assert "verifier_must_not_sign_completion" in decision.reasons


def test_gate_rejects_unsupported_verifier_version() -> None:
    result = _verify(_inputs())
    metadata = result.to_metadata()
    metadata["verifier_version"] = "vln.parking.final_verification.v0"
    metadata.pop("result_sha256", None)
    metadata["result_sha256"] = artifact_sha256(metadata)
    decision = ParkingCompletionGate().submit(_gate_request(metadata))
    assert decision.decision == CompletionStage.NOT_COMPLETED
    assert "verifier_version_unsupported" in decision.reasons


def test_require_gate_decision_rejects_plain_values() -> None:
    with pytest.raises(CompletionGateError):
        require_gate_decision({"decision": "PARKING_COMPLETED"})
    with pytest.raises(CompletionGateError):
        require_gate_decision(None)


def test_result_metadata_hash_is_mandatory() -> None:
    result = _verify(_inputs())
    metadata = result.to_metadata()
    metadata.pop("result_sha256")
    with pytest.raises(Exception):
        verify_result_metadata(metadata)


def test_verifier_version_and_producer_are_declared() -> None:
    result = _verify(_inputs())
    metadata = result.to_metadata()
    assert metadata["verifier_version"] == FINAL_VERIFICATION_VERSION
    assert metadata["producer"] == CompletionSource.FINAL_PARKING_VERIFIER
    assert metadata["parking_completed"] is False


# --- write-path guard -------------------------------------------------------


def test_no_code_path_outside_gate_writes_parking_completed_true() -> None:
    pattern = re.compile(
        r"parking_completed\s*[=:]\s*True|"
        r"decision\s*=\s*[\"']PARKING_COMPLETED[\"']"
    )
    offenders = []
    for root in (REPO_ROOT / "src" / "vln", REPO_ROOT / "scripts"):
        for path in root.rglob("*.py"):
            if path.name == "completion.py" or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line_number, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{line_number}")
    assert offenders == [], offenders
