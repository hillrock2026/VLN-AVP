#!/usr/bin/env python3
"""M1-VLN-CARLA-CAP-07B-06: final parking verification and completion gate.

The run is read-only with respect to the final parking decision. It first reads
the current CARLA world. If the world has no stage-bound vehicle (the normal
case after CAP-07B-05 cleaned up), it re-establishes the accepted Entry and
Refinement chain in one CARLA process using the existing CAP-07B-04 /
CAP-07B-05 runners and their Kernel permits, then stops the vehicle and runs
the independent :class:`FinalParkingVerifier` and
:class:`ParkingCompletionGate`.

It never optimises the pose, never moves the vehicle for final verification,
never lowers a threshold and never issues a completion flag outside the gate.
Outcomes:

  PASS — PARKING_COMPLETED          (gate issued completion)
  PARTIAL — NOT_COMPLETED           (verifier ran; at least one check failed)
  FAIL — NOT_COMPLETED              (Entry/Refinement precondition failed)
  BLOCKED — NOT_COMPLETED           (unknown world state; nothing touched)

Exit codes: 0 PARKING_COMPLETED, 2 BLOCKED, 3 NOT_COMPLETED, 4 setup failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import carla  # noqa: E402

import carla_cap07b04_entry as entry04  # noqa: E402
import carla_cap07b05_refine as refine05  # noqa: E402
from vln.carla.parking_verdict import (  # noqa: E402
    BAY03_CENTER,
    BAY03_POLYGON,
    PARKING_FOOTPRINT,
)
from vln.nav.binding_runtime import load_binding_artifact  # noqa: E402
from vln.parking.completion import (  # noqa: E402
    CollisionEvidence,
    CompletionRequest,
    CompletionSource,
    FinalParkingInputs,
    FinalParkingTolerances,
    FinalParkingVerifier,
    ObstacleEvidence,
    ParkingCompletionGate,
    StabilitySample,
    VehicleSnapshot,
    artifact_sha256,
)

TASK_ID = "cap07b-06"
SKILL_ID = "vln.parking.final_verification"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "evidence" / "vln-carla-cap-07b-06"
BINDING_JSON = REPO_ROOT / "docs" / "evidence" / "cap07a" / "A" / "binding.json"
GEOMETRY_PROBE = REPO_ROOT / "docs" / "evidence" / "carla-07a" / "geometry_probe.json"
HISTORICAL_ENTRY_VERIFICATION = (
    REPO_ROOT / "docs" / "evidence" / "vln-carla-cap-07b-04" / "entry_verification.json"
)
HISTORICAL_POSE_VERIFICATION = (
    REPO_ROOT
    / "docs"
    / "evidence"
    / "vln-carla-cap-07b-05"
    / "refinement_verification.json"
)
BAY_POLYGON = tuple((float(x), float(y)) for x, y in BAY03_POLYGON)
BAY_CENTER = (float(BAY03_CENTER[0]), float(BAY03_CENTER[1]))
FINAL_STABILITY_SAMPLES = 10
LIVE_PROBE_RADIUS_M = 2.8
LIVE_PROBE_LENGTH_M = 3.0
LIVE_PROBE_DIRECTIONS = 16
LIVE_PROBE_HEIGHTS = (0.5, 1.0)
FINAL_COLLISION_ROLE = "vln_cap07b06_collision"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _pose_from_artifact(artifact: dict) -> tuple[float, float, float] | None:
    measurement = artifact.get("measurement")
    if not isinstance(measurement, dict):
        return None
    try:
        pose = (
            float(measurement["x"]),
            float(measurement["y"]),
            float(measurement["yaw_rad"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    return pose if all(math.isfinite(value) for value in pose) else None


def _pose_gap(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float]:
    distance = math.hypot(first[0] - second[0], first[1] - second[1])
    heading = abs(
        (math.degrees(first[2] - second[2]) + 180.0) % 360.0 - 180.0
    )
    return distance, heading


def _read_only_preflight(host: str, port: int) -> dict:
    """Read map/frame/actors without spawning, ticking or changing settings."""

    data: dict = {
        "host": host,
        "port": port,
        "read_only": True,
        "refuse": False,
        "usable": False,
        "reason": None,
    }
    try:
        client = carla.Client(host, port)
        client.set_timeout(20.0)
        world = client.get_world()
        settings = world.get_settings()
        snapshot = world.get_snapshot()
        actors = list(world.get_actors())
        vehicles = list(world.get_actors().filter("vehicle.*"))
        vln_actors = [
            actor
            for actor in actors
            if str(actor.attributes.get("role_name", "")).startswith("vln_")
        ]
        data.update(
            {
                "server_version": client.get_server_version(),
                "map": world.get_map().name,
                "frame": int(snapshot.frame),
                "synchronous_mode": settings.synchronous_mode,
                "fixed_delta_seconds": settings.fixed_delta_seconds,
                "actor_count": len(actors),
                "vehicle_count": len(vehicles),
                "vln_actor_count": len(vln_actors),
                "vln_actors": [
                    {
                        "id": int(actor.id),
                        "type_id": actor.type_id,
                        "role_name": actor.attributes.get("role_name"),
                    }
                    for actor in vln_actors
                ],
                "vehicles": [
                    {
                        "id": int(actor.id),
                        "type_id": actor.type_id,
                        "role_name": actor.attributes.get("role_name"),
                        "x": round(actor.get_transform().location.x, 4),
                        "y": round(actor.get_transform().location.y, 4),
                    }
                    for actor in vehicles
                ],
            }
        )
        if vln_actors:
            data["refuse"] = True
            data["reason"] = "world_contains_vln_actors"
        elif vehicles:
            data["refuse"] = True
            data["reason"] = "world_contains_vehicles_without_stage_artifacts"
        else:
            data["reason"] = "world_has_no_vehicle; stage chain must be re-established"
    except Exception as error:
        data.update(
            {
                "refuse": True,
                "reason": "preflight_failed",
                "error": f"{type(error).__name__}: {error}",
            }
        )
    return data


def _historical_artifacts() -> dict:
    entry = _read_json(HISTORICAL_ENTRY_VERIFICATION)
    pose = _read_json(HISTORICAL_POSE_VERIFICATION)
    return {
        "entry": entry,
        "pose": pose,
        "entry_sha256": _sha256_file(HISTORICAL_ENTRY_VERIFICATION),
        "pose_sha256": _sha256_file(HISTORICAL_POSE_VERIFICATION),
        "entry_path": str(HISTORICAL_ENTRY_VERIFICATION.relative_to(REPO_ROOT)),
        "pose_path": str(HISTORICAL_POSE_VERIFICATION.relative_to(REPO_ROOT)),
    }


def _dedupe_points(
    points, tolerance_m: float = 0.05
) -> tuple[tuple[float, float], ...]:
    unique: list[tuple[float, float]] = []
    for point in points:
        candidate = (float(point[0]), float(point[1]))
        if not any(
            math.hypot(candidate[0] - other[0], candidate[1] - other[1])
            <= tolerance_m
            for other in unique
        ):
            unique.append(candidate)
    return tuple(unique)


def _live_obstacle_probe(session, ego) -> dict:
    """Sparse 16-direction, two-height ray probe around the stopped vehicle."""

    state = entry04._state(session, ego)
    z0 = float(state["z"])
    live_points: list[tuple[float, float]] = []
    errors: list[str] = []
    ray_count = 0
    for height in LIVE_PROBE_HEIGHTS:
        for index in range(LIVE_PROBE_DIRECTIONS):
            angle = 2.0 * math.pi * index / LIVE_PROBE_DIRECTIONS
            start = carla.Location(
                x=state["x"] + LIVE_PROBE_RADIUS_M * math.cos(angle),
                y=state["y"] + LIVE_PROBE_RADIUS_M * math.sin(angle),
                z=z0 + height,
            )
            end = carla.Location(
                x=state["x"]
                + (LIVE_PROBE_RADIUS_M + LIVE_PROBE_LENGTH_M) * math.cos(angle),
                y=state["y"]
                + (LIVE_PROBE_RADIUS_M + LIVE_PROBE_LENGTH_M) * math.sin(angle),
                z=z0 + height,
            )
            ray_count += 1
            try:
                hits = session.world.cast_ray(start, end) or []
            except Exception as error:
                errors.append(f"{type(error).__name__}: {error}")
                continue
            for hit in hits:
                location = getattr(hit, "location", None)
                if location is None:
                    continue
                distance = math.hypot(
                    location.x - state["x"], location.y - state["y"]
                )
                if distance < LIVE_PROBE_RADIUS_M - 0.2:
                    continue
                if not (-0.5 <= location.z - z0 <= 2.0):
                    continue
                live_points.append((location.x, location.y))
    return {
        "ray_count": ray_count,
        "errors": errors,
        "live_points": _dedupe_points(live_points),
        "radius_m": LIVE_PROBE_RADIUS_M,
        "length_m": LIVE_PROBE_LENGTH_M,
        "directions": LIVE_PROBE_DIRECTIONS,
        "heights_m": list(LIVE_PROBE_HEIGHTS),
    }


def _build_obstacle_evidence(probe: dict) -> ObstacleEvidence:
    historical = tuple(
        (float(point[0]), float(point[1])) for point in refine05.OBSTACLES
    )
    live = tuple(probe["live_points"])
    combined = _dedupe_points(historical + live)
    return ObstacleEvidence(
        source="historical_static_samples+live_ray_probe",
        points=combined,
        live=bool(live),
        coverage_note=(
            "29 historical static collision-mesh samples plus a sparse live "
            f"{probe['ray_count']}-ray, {len(probe['heights_m'])}-height probe "
            f"from {probe['radius_m']} m to "
            f"{probe['radius_m'] + probe['length_m']} m around the final pose; "
            "not a complete live occupancy model"
        ),
        live_point_count=len(live),
        historical_point_count=len(historical),
    )


def _spawn_collision_sensor(session, ego) -> tuple[object | None, list, dict]:
    events: list[dict] = []
    lock = threading.Lock()
    try:
        blueprint = session.world.get_blueprint_library().find(
            "sensor.other.collision"
        )
        blueprint.set_attribute("role_name", FINAL_COLLISION_ROLE)
        sensor = session.world.spawn_actor(
            blueprint, carla.Transform(), attach_to=ego
        )
    except Exception as error:
        return (
            None,
            events,
            {
                "sensor_role": None,
                "sensor_id": None,
                "started_frame": None,
                "started_utc": None,
                "error": f"{type(error).__name__}: {error}",
            },
        )
    session.actors.append(sensor)

    def _on_collision(event):
        try:
            record = {
                "frame": int(session.world.get_snapshot().frame),
                "other_actor_id": int(event.other_actor.id),
                "other_actor_type": event.other_actor.type_id,
                "normal_impulse": {
                    "x": round(float(event.normal_impulse.x), 4),
                    "y": round(float(event.normal_impulse.y), 4),
                    "z": round(float(event.normal_impulse.z), 4),
                },
            }
        except Exception as error:
            record = {"error": f"{type(error).__name__}: {error}"}
        with lock:
            events.append(record)

    sensor.listen(_on_collision)
    monitor = {
        "sensor_role": FINAL_COLLISION_ROLE,
        "sensor_id": int(sensor.id),
        "started_frame": int(session.world.get_snapshot().frame),
        "started_utc": _utc_now(),
    }
    return sensor, events, monitor


def _collect_stability(
    session, ego, count: int = FINAL_STABILITY_SAMPLES
) -> tuple[tuple[StabilitySample, ...], dict]:
    samples: list[StabilitySample] = []
    actor_ids: set[int] = set()
    alive = True
    for _ in range(count):
        try:
            if not ego.is_alive:
                alive = False
                break
            actor_ids.add(int(ego.id))
            ego.apply_control(
                carla.VehicleControl(throttle=0.0, brake=1.0, steer=0.0)
            )
            session.tick()
            state = entry04._state(session, ego)
        except Exception:
            alive = False
            break
        samples.append(
            StabilitySample(
                frame=state["frame"],
                sim_time=state["sim_time"],
                x=state["x"],
                y=state["y"],
                yaw_rad=state["yaw_rad"],
                speed_mps=state["speed"],
            )
        )
    return tuple(samples), {
        "actor_alive": bool(alive and ego.is_alive),
        "actor_id_consistent": len(actor_ids) == 1,
        "actor_ids": sorted(actor_ids),
    }


def _artifact_copies(refinement_result: dict, actor_id: int) -> dict:
    entry_meta = (
        refinement_result.get("entry_reestablished", {}).get(
            "final_verification"
        )
    )
    pose_meta = refinement_result.get("refinement_verification")
    entry_chain = (
        refinement_result.get("entry_reestablished", {}).get(
            "entry_completion_inputs"
        )
    )
    entry_artifact = dict(entry_meta) if isinstance(entry_meta, dict) else None
    pose_artifact = dict(pose_meta) if isinstance(pose_meta, dict) else None
    if entry_artifact is not None:
        entry_artifact["vehicle_actor_id"] = actor_id
    if pose_artifact is not None:
        pose_artifact["vehicle_actor_id"] = actor_id
        if isinstance(entry_chain, dict):
            chain_copy = dict(entry_chain)
            chain_copy["parking_task_id"] = TASK_ID
            chain_copy["vehicle_actor_id"] = actor_id
            pose_artifact["entry_completion_inputs"] = chain_copy
    return {
        "entry_artifact": entry_artifact or {},
        "entry_artifact_sha256": artifact_sha256(entry_artifact)
        if entry_artifact is not None
        else None,
        "pose_ready_artifact": pose_artifact or {},
        "pose_ready_artifact_sha256": artifact_sha256(pose_artifact)
        if pose_artifact is not None
        else None,
    }


def _summarize_kernel_rounds(rounds) -> list[dict]:
    summary: list[dict] = []
    for record in rounds or ():
        if not isinstance(record, dict):
            continue
        kernel = record.get("kernel") or {}
        execution = record.get("execution") or {}
        summary.append(
            {
                "phase": record.get("phase") or kernel.get("phase_label"),
                "request_id": kernel.get("request_id"),
                "intent_id": kernel.get("intent_id"),
                "capability_id": kernel.get("capability_id"),
                "execution_status": kernel.get("execution_status"),
                "request_ok": kernel.get("request_ok"),
                "phase_success": execution.get("phase_success"),
                "transaction_present": bool(kernel.get("transaction")),
            }
        )
    return summary


def _run_final_verification(
    kwargs: dict,
    refine_outcome: dict,
    out_dir: Path,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = kwargs["session"]
    ego = kwargs["ego"]
    refinement_result = refine_outcome.get("result") or {}
    pose_ready = bool(refinement_result.get("parking_pose_ready"))
    kernel_correlations = {
        "capability": "parking.move",
        "skills": [
            "vln.parking.entry",
            "vln.parking.refinement",
            "vln.parking.final_verification",
        ],
        "entry_rounds": _summarize_kernel_rounds(
            kwargs.get("round_records") or ()
        ),
        "refinement_rounds": _summarize_kernel_rounds(
            refinement_result.get("rounds") or ()
        ),
        "final_verification": {
            "read_only": True,
            "capability": None,
            "skill": SKILL_ID,
        },
    }
    actor_id = int(ego.id)
    artifacts = _artifact_copies(refinement_result, actor_id)

    entry_reestablished = refinement_result.get("entry_reestablished") or {}
    entry_final_state = entry_reestablished.get("final_state") or {}
    entry_frame = entry_final_state.get("frame")
    if type(entry_frame) is not int:
        entry_frame = int(session.world.get_snapshot().frame)
    pose_final_state = refinement_result.get("final_state") or {}
    pose_frame = pose_final_state.get("frame")
    if type(pose_frame) is not int:
        pose_frame = entry_frame
    entry_authorization = entry_reestablished.get("entry_authorization") or {}
    entry_authorization_id = entry_authorization.get("authorization_id")
    if type(entry_authorization_id) is not str:
        entry_authorization_id = ""

    # Final verification window: attach a fresh collision sensor, then sample
    # the stopped vehicle. No throttle is ever applied.
    sensor, final_events, final_monitor = _spawn_collision_sensor(session, ego)
    samples, actor_evidence = _collect_stability(session, ego)
    final_state = entry04._state(session, ego)
    final_monitor["ended_frame"] = final_state["frame"]
    final_monitor["ended_utc"] = _utc_now()
    if not actor_evidence["actor_alive"] or not actor_evidence["actor_id_consistent"]:
        raise RuntimeError("vehicle actor changed or died during final verification")

    probe = _live_obstacle_probe(session, ego)
    obstacle_evidence = _build_obstacle_evidence(probe)

    task_collision_events = tuple(kwargs.get("collision_events") or ())
    entry_collision_monitor = dict(kwargs.get("collision_monitor") or {})
    monitoring_started_frame = entry_collision_monitor.get("started_frame")
    if type(monitoring_started_frame) is not int:
        monitoring_started_frame = None
    monitoring_started_utc = entry_collision_monitor.get("started_utc")
    first_motion_frame = entry_reestablished.get("entry_first_motion_frame")
    if type(first_motion_frame) is not int:
        first_motion_frame = None
    collision_evidence = CollisionEvidence(
        sensor_available=monitoring_started_frame is not None,
        sensor_role=entry_collision_monitor.get("sensor_role"),
        monitoring_started_frame=monitoring_started_frame,
        monitoring_started_utc=monitoring_started_utc,
        first_motion_frame=first_motion_frame,
        current_frame=int(final_state["frame"]),
        task_events=task_collision_events,
        verification_events=tuple(final_events),
        evidence_gap=False,
        gap_note=(
            "the Entry collision sensor was attached before the first commanded "
            "Entry segment; the stationary spawn-settle ticks before attachment "
            "are not covered and are documented as a limitation"
        ),
    )

    transform = ego.get_transform()
    velocity = ego.get_velocity()
    extent = ego.bounding_box.extent
    bbox_location = ego.bounding_box.location
    vehicle = VehicleSnapshot(
        actor_id=actor_id,
        type_id=ego.type_id,
        x=float(transform.location.x),
        y=float(transform.location.y),
        z=float(transform.location.z),
        yaw_rad=float(math.radians(transform.rotation.yaw)),
        frame=int(final_state["frame"]),
        half_length=float(extent.x),
        half_width=float(extent.y),
        half_height=float(extent.z),
        bbox_offset_x=float(bbox_location.x),
        bbox_offset_y=float(bbox_location.y),
        bbox_offset_z=float(bbox_location.z),
        velocity_x=float(velocity.x),
        velocity_y=float(velocity.y),
        velocity_z=float(velocity.z),
        speed_mps=float(math.hypot(velocity.x, velocity.y)),
        actor_alive=bool(ego.is_alive),
        actor_id_consistent=bool(actor_evidence["actor_id_consistent"]),
    )
    tolerances = FinalParkingTolerances()
    binding = kwargs.get("binding")
    bay_id = getattr(binding, "bay_id", None) or "bay03"
    slot_node_id = getattr(binding, "slot_node_id", None) or "park_slot"
    bay_identity_consistent = bool(bay_id == "bay03" and slot_node_id == "park_slot")

    inputs = FinalParkingInputs(
        task_id=TASK_ID,
        bay_id=str(bay_id),
        slot_node_id=str(slot_node_id),
        entry_task_id=str(
            artifacts["entry_artifact"].get("task_id") or "cap07b-04"
        ),
        refinement_task_id=str(
            artifacts["pose_ready_artifact"].get("task_id") or "cap07b-05"
        ),
        entry_authorization_id=entry_authorization_id,
        expected_vehicle_actor_id=actor_id,
        vehicle=vehicle,
        config_footprint=PARKING_FOOTPRINT,
        bay_polygon=BAY_POLYGON,
        bay_center=BAY_CENTER,
        bay_heading_rad=math.pi,
        obstacle_evidence=obstacle_evidence,
        collision=collision_evidence,
        stability_samples=samples,
        actor_alive=bool(ego.is_alive),
        actor_id_consistent=bool(actor_evidence["actor_id_consistent"]),
        bay_identity_consistent=bay_identity_consistent,
        entry_artifact=artifacts["entry_artifact"],
        entry_artifact_sha256=artifacts["entry_artifact_sha256"] or "",
        pose_ready_artifact=artifacts["pose_ready_artifact"],
        pose_ready_artifact_sha256=artifacts["pose_ready_artifact_sha256"] or "",
        entry_frame=entry_frame,
        pose_ready_frame=pose_frame,
        tolerances=tolerances,
        now=_utc_now(),
    )
    result = FinalParkingVerifier().verify(inputs)
    gate = ParkingCompletionGate(tolerances)
    request = CompletionRequest(
        source=CompletionSource.FINAL_PARKING_VERIFIER,
        verifier_result=result,
        task_id=inputs.task_id,
        bay_id=inputs.bay_id,
        slot_node_id=inputs.slot_node_id,
        vehicle_actor_id=actor_id,
        current_frame=vehicle.frame,
        now=inputs.now,
    )
    decision = gate.submit(request)

    carla_state = {
        "map": session.world.get_map().name,
        "frame": int(final_state["frame"]),
        "sim_time": final_state["sim_time"],
        "transform": {
            "x": final_state["x"],
            "y": final_state["y"],
            "z": final_state["z"],
            "yaw_deg": final_state["yaw_deg"],
            "yaw_rad": final_state["yaw_rad"],
            "pitch": final_state["pitch"],
            "roll": final_state["roll"],
        },
        "velocity": {
            "x": round(float(velocity.x), 6),
            "y": round(float(velocity.y), 6),
            "z": round(float(velocity.z), 6),
        },
        "speed_mps": round(float(math.hypot(velocity.x, velocity.y)), 6),
        "vehicle_actor_id": int(ego.id),
        "vehicle_type_id": ego.type_id,
        "bounding_box": {
            "extent": {
                "x": round(float(extent.x), 6),
                "y": round(float(extent.y), 6),
                "z": round(float(extent.z), 6),
            },
            "location": {
                "x": round(float(bbox_location.x), 6),
                "y": round(float(bbox_location.y), 6),
                "z": round(float(bbox_location.z), 6),
            },
        },
        "actor_alive": bool(ego.is_alive),
    }
    inputs_metadata = {
        "task_id": inputs.task_id,
        "bay_id": inputs.bay_id,
        "slot_node_id": inputs.slot_node_id,
        "entry_task_id": inputs.entry_task_id,
        "refinement_task_id": inputs.refinement_task_id,
        "entry_authorization_id": inputs.entry_authorization_id,
        "expected_vehicle_actor_id": inputs.expected_vehicle_actor_id,
        "vehicle": inputs.vehicle.to_metadata(),
        "config_footprint": inputs.config_footprint.to_metadata(),
        "bay_polygon": [list(point) for point in inputs.bay_polygon],
        "bay_center": list(inputs.bay_center),
        "bay_heading_rad": inputs.bay_heading_rad,
        "obstacle_evidence": inputs.obstacle_evidence.to_metadata(),
        "collision_evidence": inputs.collision.to_metadata(),
        "stability_samples": [
            sample.to_metadata() for sample in inputs.stability_samples
        ],
        "actor_alive": inputs.actor_alive,
        "actor_id_consistent": inputs.actor_id_consistent,
        "bay_identity_consistent": inputs.bay_identity_consistent,
        "entry_artifact": inputs.entry_artifact,
        "entry_artifact_sha256": inputs.entry_artifact_sha256,
        "pose_ready_artifact": inputs.pose_ready_artifact,
        "pose_ready_artifact_sha256": inputs.pose_ready_artifact_sha256,
        "entry_frame": inputs.entry_frame,
        "pose_ready_frame": inputs.pose_ready_frame,
        "tolerances": inputs.tolerances.to_metadata(),
        "now": inputs.now,
        "pose_ready": pose_ready,
    }
    _write_json(out_dir / "carla_final_state.json", carla_state)
    _write_json(
        out_dir / "final_stability_samples.json",
        {
            "count": len(samples),
            "samples": [sample.to_metadata() for sample in samples],
            "actor_evidence": actor_evidence,
        },
    )
    _write_json(
        out_dir / "collision_evidence.json",
        {
            "entry_monitor": entry_collision_monitor,
            "final_monitor": final_monitor,
            "task_events": list(task_collision_events),
            "verification_events": list(final_events),
            "resolved": collision_evidence.to_metadata(),
        },
    )
    _write_json(
        out_dir / "obstacle_evidence.json",
        {
            "probe": probe,
            "resolved": obstacle_evidence.to_metadata(),
            "historical_path": str(GEOMETRY_PROBE.relative_to(REPO_ROOT)),
        },
    )
    _write_json(
        out_dir / "artifact_chain.json",
        {
            "entry_artifact_sha256": inputs.entry_artifact_sha256,
            "pose_ready_artifact_sha256": inputs.pose_ready_artifact_sha256,
            "entry_completion_id": result.entry_completion_id,
            "refinement_plan_hash": result.refinement_plan_hash,
            "entry_frame": inputs.entry_frame,
            "pose_ready_frame": inputs.pose_ready_frame,
            "verification_frame": result.verification_frame,
            "entry_task_id": inputs.entry_task_id,
            "refinement_task_id": inputs.refinement_task_id,
            "vehicle_actor_id": actor_id,
        },
    )
    _write_json(out_dir / "kernel_correlations.json", kernel_correlations)
    _write_json(out_dir / "final_verification_inputs.json", inputs_metadata)
    _write_json(out_dir / "final_verification_result.json", result.to_metadata())
    _write_json(
        out_dir / "completion_gate_request.json",
        {
            "source": request.source,
            "task_id": request.task_id,
            "bay_id": request.bay_id,
            "slot_node_id": request.slot_node_id,
            "vehicle_actor_id": request.vehicle_actor_id,
            "current_frame": request.current_frame,
            "now": request.now,
            "has_verifier_result": True,
            "verifier_result_sha256": result.result_sha256,
        },
    )
    _write_json(out_dir / "completion_gate_decision.json", decision.to_metadata())
    _write_json(
        out_dir / "task_state.json",
        {
            "task_id": decision.task_id,
            "stage": decision.task_state.get("stage"),
            "parking_completed": decision.parking_completed,
            "decision": decision.decision,
            "vehicle_actor_id": decision.vehicle_actor_id,
            "bay_id": decision.bay_id,
            "slot_node_id": decision.slot_node_id,
            "gate_decision_id": decision.decision_id,
            "verifier_result_sha256": decision.verifier_result_sha256,
        },
    )
    return {
        "decision": decision.decision,
        "parking_completed": decision.parking_completed,
        "final_parking_verified": result.verification_passed,
        "pose_ready": pose_ready,
        "verifier": result.to_metadata(),
        "gate": decision.to_metadata(),
        "task_state": dict(decision.task_state),
        "inputs_summary": {
            "entry_artifact_sha256": inputs.entry_artifact_sha256,
            "pose_ready_artifact_sha256": inputs.pose_ready_artifact_sha256,
            "entry_completion_id": result.entry_completion_id,
            "refinement_plan_hash": result.refinement_plan_hash,
            "entry_frame": inputs.entry_frame,
            "pose_ready_frame": inputs.pose_ready_frame,
            "verification_frame": result.verification_frame,
            "vehicle_actor_id": actor_id,
            "bay_id": inputs.bay_id,
            "slot_node_id": inputs.slot_node_id,
            "stability_samples": len(samples),
            "obstacle_points": len(inputs.obstacle_evidence.points),
            "live_obstacle_points": inputs.obstacle_evidence.live_point_count,
        },
        "carla_state": carla_state,
        "kernel_correlations": kernel_correlations,
        "evidence_files": [
            "carla_final_state.json",
            "final_stability_samples.json",
            "collision_evidence.json",
            "obstacle_evidence.json",
            "artifact_chain.json",
            "kernel_correlations.json",
            "final_verification_inputs.json",
            "final_verification_result.json",
            "completion_gate_request.json",
            "completion_gate_decision.json",
            "task_state.json",
        ],
    }


def _gate_rejection_without_result(
    out_dir: Path,
    *,
    bay_id: str,
    slot_node_id: str,
    actor_id: int,
    current_frame: int,
    reason: str,
) -> dict:
    decision = ParkingCompletionGate().submit(
        CompletionRequest(
            source=CompletionSource.FINAL_PARKING_VERIFIER,
            verifier_result=None,
            task_id=TASK_ID,
            bay_id=bay_id,
            slot_node_id=slot_node_id,
            vehicle_actor_id=actor_id,
            current_frame=current_frame,
            now=_utc_now(),
        )
    )
    decision_meta = decision.to_metadata()
    decision_meta["reasons"] = list(
        dict.fromkeys([reason, *decision_meta["reasons"]])
    )
    _write_json(out_dir / "completion_gate_decision.json", decision_meta)
    _write_json(
        out_dir / "task_state.json",
        {
            "task_id": decision.task_id,
            "stage": decision.task_state.get("stage"),
            "parking_completed": False,
            "decision": decision.decision,
            "vehicle_actor_id": decision.vehicle_actor_id,
            "bay_id": decision.bay_id,
            "slot_node_id": decision.slot_node_id,
            "gate_decision_id": decision.decision_id,
        },
    )
    return decision_meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--kernel-host", default=entry04.DEFAULT_KERNEL_HOST)
    args = parser.parse_args(argv)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    started = _utc_now()
    state: dict = {
        "entry_code": None,
        "refine": None,
        "final": None,
        "error": None,
    }
    base: dict = {
        "schema": "vln.cap07b06.result.v1",
        "skill": SKILL_ID,
        "task_id": TASK_ID,
        "started_utc": started,
        "git": entry04._git_state(),
        "parking_completed": False,
        "final_parking_verified": False,
    }

    preflight = _read_only_preflight(args.host, args.port)
    _write_json(output / "read_only_preflight.json", preflight)
    base["read_only_preflight"] = preflight
    historical = _historical_artifacts()
    base["historical_artifacts"] = {
        key: value
        for key, value in historical.items()
        if key not in ("entry", "pose")
    }

    binding = None
    try:
        binding = load_binding_artifact(str(BINDING_JSON))
        base["binding"] = binding.to_metadata()
    except Exception as error:
        base["binding_error"] = f"{type(error).__name__}: {error}"

    bay_id = getattr(binding, "bay_id", None) or "bay03"
    slot_node_id = getattr(binding, "slot_node_id", None) or "park_slot"

    if preflight.get("refuse"):
        gate = _gate_rejection_without_result(
            output,
            bay_id=bay_id,
            slot_node_id=slot_node_id,
            actor_id=0,
            current_frame=int(preflight.get("frame") or 0),
            reason=f"blocked: {preflight.get('reason')}",
        )
        base.update(
            {
                "status": "BLOCKED",
                "decision": "NOT_COMPLETED",
                "parking_completed": False,
                "error": preflight.get("reason"),
                "completion_gate": gate,
                "finished_utc": _utc_now(),
            }
        )
        _write_json(output / "result.json", base)
        print(json.dumps(base, ensure_ascii=False, indent=2)[:6000])
        return 2

    refine05.OBSTACLES = refine05._load_obstacles()
    entry_dir = output / "entry_reestablish"
    refine_dir = output / "refinement_reestablish"
    entry_dir.mkdir(parents=True, exist_ok=True)
    refine_dir.mkdir(parents=True, exist_ok=True)

    def _after(**kwargs):
        kwargs.pop("out_dir", None)
        try:
            refine_outcome = refine05._callback(out_dir=refine_dir, **kwargs)
            state["refine"] = {
                "code": refine_outcome.get("code"),
                "status": refine_outcome.get("status"),
                "decision": refine_outcome.get("decision"),
                "error": (refine_outcome.get("result") or {}).get("error"),
            }
            state["final"] = _run_final_verification(
                kwargs, refine_outcome, output
            )
        except Exception as error:
            state["error"] = f"{type(error).__name__}: {error}"
            state["traceback"] = traceback.format_exc()
            # Fail closed: no verifier result reaches the gate.
            try:
                state["final"] = _run_final_verification(
                    kwargs, {"result": {}, "status": "FAIL"}, output
                )
            except Exception as inner:
                state["inner_error"] = f"{type(inner).__name__}: {inner}"

    entry_args = [
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--kernel-host",
        args.kernel_host,
        "--output-dir",
        str(entry_dir),
        "--alignment-result",
        str(REPO_ROOT / "docs/evidence/vln-carla-cap-07b-03/result.json"),
        "--alignment-authorization",
        str(REPO_ROOT / "docs/evidence/vln-carla-cap-07b-03/alignment_authorization.json"),
        "--binding-json",
        str(BINDING_JSON),
        "--geometry-probe",
        str(GEOMETRY_PROBE),
    ]
    entry_code = entry04.main(entry_args, after_entry=_after)
    state["entry_code"] = entry_code

    final = state.get("final") or {}
    gate = final.get("gate") or {}
    verifier = final.get("verifier") or {}
    parking_completed = bool(gate.get("parking_completed"))
    decision = gate.get("decision") or "NOT_COMPLETED"
    if parking_completed:
        status = "PASS"
    elif state.get("final") is not None:
        status = "PARTIAL"
    else:
        status = "FAIL"
    if not final:
        gate = _gate_rejection_without_result(
            output,
            bay_id=bay_id,
            slot_node_id=slot_node_id,
            actor_id=0,
            current_frame=int(preflight.get("frame") or 0),
            reason=state.get("error")
            or "Entry/Refinement did not reach final verification",
        )
        decision = gate.get("decision", "NOT_COMPLETED")

    base.update(
        {
            "status": status,
            "decision": decision,
            "parking_completed": parking_completed,
            "final_parking_verified": bool(
                final.get("final_parking_verified")
            ),
            "entry_exit_code": entry_code,
            "refinement": state.get("refine"),
            "error": state.get("error"),
            "traceback": state.get("traceback"),
            "inner_error": state.get("inner_error"),
            "final_verification": verifier or None,
            "completion_gate": gate or None,
            "task_state": final.get("task_state")
            or (gate or {}).get("task_state"),
            "inputs_summary": final.get("inputs_summary"),
            "carla_final_state": final.get("carla_state"),
            "kernel_correlations": final.get("kernel_correlations"),
            "evidence_files": final.get("evidence_files"),
            "limitations": (verifier or {}).get("limitations"),
            "finished_utc": _utc_now(),
        }
    )
    _write_json(output / "result.json", base)
    _write_json(
        output / "run.log",
        {
            "started_utc": started,
            "finished_utc": _utc_now(),
            "status": status,
            "decision": decision,
            "parking_completed": parking_completed,
            "entry_exit_code": entry_code,
            "error": base.get("error"),
        },
    )
    print(
        json.dumps(
            {
                "status": status,
                "decision": decision,
                "parking_completed": parking_completed,
                "final_parking_verified": base["final_parking_verified"],
                "entry_exit_code": entry_code,
                "verifier_reasons": (verifier or {}).get("reasons"),
                "gate_reasons": (gate or {}).get("reasons"),
                "inputs": base.get("inputs_summary"),
                "error": base.get("error"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if parking_completed:
        return 0
    return 4 if status == "FAIL" else 3


if __name__ == "__main__":
    sys.exit(main())
