#!/usr/bin/env python3
"""Bind a natural-language parking target to a real scene bay.

One round does exactly this:

    real ego pose + fresh front RGB frame
      -> project the known bay polygons (scene geometry, no model numbers)
      -> overlay neutral candidate regions/letters on the real frame
      -> one real ZDTaichu image request (occupancy per letter + one letter)
      -> strict parse -> system-side visibility/side/vacancy constraints
      -> TargetBinding (bound / ambiguous / not visible / invalidated / refused)

The model never receives a bay id, a coordinate or a ground-truth occupancy. The
only thing it may return is a temporary letter painted on the frame; the letter
is mapped back to ``bay_id``/``slot_node_id`` by the system.

The script is also importable: :func:`run_binding_round` is used by the CAP-07A
experiment orchestrator, which keeps one CARLA session open for multi-round
scenarios. The CLI path spawns its own ego (and optionally one parked car), and
always restores the world settings and destroys its own actors.

Exit codes: 0 bound, 2 non-executable binding, 3 model call failure, 4 setup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import carla  # noqa: E402

import carla_parking_nav as nav01b  # noqa: E402
from vln.carla import CameraFrame, write_rgb_png  # noqa: E402
from vln.carla.image_annotate import annotate_candidates  # noqa: E402
from vln.carla.parking_entities import (  # noqa: E402
    BAY_ENTITIES,
    CameraPose,
    EgoPose2D,
    project_bay,
    visible_candidates,
)
from vln.carla.parking_verdict import BAY03_CENTER, BAY11_CENTER  # noqa: E402
from vln.carla.session import leftover_actors  # noqa: E402
from vln.nav.parking_request import ParkingInstruction, parse_parking_instruction  # noqa: E402
from vln.nav.target_binding import (  # noqa: E402
    BindingStatus,
    CandidateObservation,
    TargetBinding,
    parse_binding_artifact,
    parse_binding_decision,
    resolve_target_binding,
)
from vln.vlm.binding_prompt import build_binding_prompt  # noqa: E402
from vln.vlm.model_client import ModelCallError  # noqa: E402
from vln.vlm.server_client import ZDTaichuServerBackend  # noqa: E402

MAP_NAME = "UndergroundCarPark"
FLOOR_Z = 5.78
CAM_W, CAM_H = 1280, 720
EGO_ROLE = "vln_cap07a_ego"
CAM_ROLE = "vln_cap07a_bind_cam"
PARKED_ROLE_PREFIX = "vln_cap07a_parked_"

DEFAULT_SPAWN = (-5.1, -9.9, 6.7, -75.0)
DEFAULT_CAMERA_OFFSET = (2.4, 0.0, 1.6)
DEFAULT_CAMERA_PITCH = -12.0
DEFAULT_CAMERA_YAW = -40.0
DEFAULT_FOV = 110.0

BAY_CENTERS = {"bay03": BAY03_CENTER, "bay11": BAY11_CENTER}


class BindingRoundError(RuntimeError):
    """A binding round could not produce a model-backed decision."""

    exit_code = 4


class BindingModelError(BindingRoundError):
    """The real model request failed; no binding was produced."""

    exit_code = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_or_none(value: float):
    return round(float(value), 3) if math.isfinite(value) else None


def _projection_payload(projected, label: str = "") -> dict:
    corners = [
        [_finite_or_none(u), _finite_or_none(v)] for u, v in projected.corners
    ]
    return {
        "bay_id": projected.entity.bay_id,
        "slot_node_id": projected.entity.slot_node_id,
        "label": label,
        "visible_corners": projected.visible_corners,
        "all_in_frame": projected.all_in_frame,
        "side": projected.side,
        "bearing_deg": round(projected.bearing_deg, 3),
        "distance_m": round(projected.distance_m, 3),
        "corners": corners,
        "center_image": [
            _finite_or_none(projected.center_image[0]),
            _finite_or_none(projected.center_image[1]),
        ],
    }


def capture_binding_frame(
    session,
    ego,
    out_dir: Path,
    *,
    name: str,
    fov: float = DEFAULT_FOV,
    camera_offset: tuple[float, float, float] = DEFAULT_CAMERA_OFFSET,
    camera_pitch: float = DEFAULT_CAMERA_PITCH,
    camera_yaw: float = DEFAULT_CAMERA_YAW,
):
    """Capture one fresh real RGB frame from the binding camera."""

    world = session.world
    camera_bp = world.get_blueprint_library().find("sensor.camera.rgb")
    camera_bp.set_attribute("image_size_x", str(CAM_W))
    camera_bp.set_attribute("image_size_y", str(CAM_H))
    camera_bp.set_attribute("fov", str(fov))
    camera_bp.set_attribute("sensor_tick", "0.0")
    camera_bp.set_attribute("role_name", CAM_ROLE)
    local_transform = carla.Transform(
        carla.Location(
            x=camera_offset[0], y=camera_offset[1], z=camera_offset[2]
        ),
        carla.Rotation(pitch=camera_pitch, yaw=camera_yaw),
    )
    camera = world.spawn_actor(camera_bp, local_transform, attach_to=ego)
    session.actors.append(camera)
    latest = nav01b.LatestImage()
    camera.listen(latest)
    try:
        session.tick(25)
        image = None
        for _ in range(30):
            snapshot = world.get_snapshot()
            candidate = latest.image
            if candidate is not None and 0 <= snapshot.frame - candidate.frame <= 2:
                image = candidate
                break
            session.tick()
        if image is None:
            raise BindingRoundError("camera produced no fresh frame within 30 ticks")
        if image.width != CAM_W or image.height != CAM_H:
            raise BindingRoundError(
                f"camera frame is {image.width}x{image.height}, expected {CAM_W}x{CAM_H}"
            )
        if len(image.raw_data) != CAM_W * CAM_H * 4:
            raise BindingRoundError(
                f"camera buffer is {len(image.raw_data)} bytes, expected "
                f"{CAM_W * CAM_H * 4}"
            )
        frame = CameraFrame.from_bgra(
            frame_id=image.frame,
            timestamp=image.timestamp,
            width=image.width,
            height=image.height,
            raw_bgra=bytes(image.raw_data),
        )
        raw_path = out_dir / f"{name}_raw_{image.frame}.png"
        write_rgb_png(str(raw_path), frame.rgb, frame.width, frame.height)
        transform = camera.get_transform()
        rotation = transform.rotation
        camera_pose = CameraPose(
            transform.location.x,
            transform.location.y,
            transform.location.z,
            rotation.yaw,
            rotation.pitch,
            rotation.roll,
        )
        ego_transform = ego.get_transform()
        ego_pose = EgoPose2D(
            ego_transform.location.x,
            ego_transform.location.y,
            ego_transform.rotation.yaw,
        )
        camera_meta = {
            "actor_id": camera.id,
            "role_name": CAM_ROLE,
            "fov": fov,
            "width": CAM_W,
            "height": CAM_H,
            "image_frame": image.frame,
            "local_offset": list(camera_offset),
            "local_pitch": camera_pitch,
            "local_yaw": camera_yaw,
            "world_transform": {
                "x": round(transform.location.x, 4),
                "y": round(transform.location.y, 4),
                "z": round(transform.location.z, 4),
                "pitch": round(rotation.pitch, 4),
                "yaw": round(rotation.yaw, 4),
                "roll": round(rotation.roll, 4),
            },
            "raw_png": str(raw_path),
            "raw_png_sha256": _sha256_file(raw_path),
        }
        ego_meta = {
            "x": round(ego_transform.location.x, 4),
            "y": round(ego_transform.location.y, 4),
            "z": round(ego_transform.location.z, 4),
            "yaw": round(ego_transform.rotation.yaw, 4),
            "pitch": round(ego_transform.rotation.pitch, 4),
            "roll": round(ego_transform.rotation.roll, 4),
        }
        return frame, str(raw_path), camera_meta, ego_meta, camera_pose, ego_pose
    finally:
        camera.stop()
        camera.destroy()
        if camera in session.actors:
            session.actors.remove(camera)


def _observations(
    projected_all,
    labelled,
    decision,
) -> tuple[CandidateObservation, ...]:
    labels = {item.entity.bay_id: item.label for item in labelled}
    observations = []
    for projected in projected_all:
        label = labels.get(projected.entity.bay_id, "")
        if label:
            occupancy = decision.occupancies[label]
            visible = True
        else:
            occupancy = "unknown"
            visible = False
        observations.append(
            CandidateObservation(
                label=label,
                bay_id=projected.entity.bay_id,
                slot_node_id=projected.entity.slot_node_id,
                occupancy=occupancy,
                visible=visible,
                side=projected.side,
                bearing_deg=projected.bearing_deg,
                distance_m=projected.distance_m,
                image_bbox=projected.bbox if projected.all_in_frame else None,
            )
        )
    return tuple(observations)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def run_binding_round(
    session,
    ego,
    *,
    request: ParkingInstruction,
    round_index: int,
    prior: TargetBinding | None,
    backend: ZDTaichuServerBackend,
    out_dir: Path,
    fov: float = DEFAULT_FOV,
    camera_offset: tuple[float, float, float] = DEFAULT_CAMERA_OFFSET,
    camera_pitch: float = DEFAULT_CAMERA_PITCH,
    camera_yaw: float = DEFAULT_CAMERA_YAW,
    label_order: str = "near_to_far",
    name: str = "round",
) -> tuple[TargetBinding, dict]:
    """Run one binding round and persist its full evidence."""

    out_dir.mkdir(parents=True, exist_ok=True)
    (
        frame,
        raw_path,
        camera_meta,
        ego_meta,
        camera_pose,
        ego_pose,
    ) = capture_binding_frame(
        session,
        ego,
        out_dir,
        name=name,
        fov=fov,
        camera_offset=camera_offset,
        camera_pitch=camera_pitch,
        camera_yaw=camera_yaw,
    )
    projected_all = [
        project_bay(
            entity,
            camera_pose,
            fov_deg=fov,
            width=CAM_W,
            height=CAM_H,
            floor_z=FLOOR_Z,
            ego=ego_pose,
        )
        for entity in BAY_ENTITIES
    ]
    labelled = list(
        visible_candidates(
            camera_pose,
            ego_pose,
            fov_deg=fov,
            width=CAM_W,
            height=CAM_H,
            floor_z=FLOOR_Z,
            order=label_order,
        )
    )
    labels = tuple(item.label for item in labelled)
    label_by_bay = {item.entity.bay_id: item.label for item in labelled}
    record = {
        "round_index": round_index,
        "timestamp": _now_iso(),
        "instruction": request.raw,
        "request": request.to_metadata(),
        "camera": camera_meta,
        "ego_pose": ego_meta,
        "label_order": label_order,
        "projected": [
            _projection_payload(item, label_by_bay.get(item.entity.bay_id, ""))
            for item in projected_all
        ],
        "visible_labels": list(labels),
        "overlay_png": None,
        "overlay_png_sha256": None,
        "prompt": None,
        "model_text": None,
        "parse": None,
        "binding": None,
        "model_error": None,
    }

    overlay_path = None
    if labelled:
        buffer = bytearray(frame.rgb)
        annotate_candidates(buffer, frame.width, frame.height, labelled)
        overlay_path = out_dir / f"{name}_overlay_{frame.frame_id}.png"
        write_rgb_png(str(overlay_path), bytes(buffer), frame.width, frame.height)
        record["overlay_png"] = str(overlay_path)
        record["overlay_png_sha256"] = _sha256_file(overlay_path)

    decision = None
    model_error = None
    parse_error = None
    if labelled:
        prompt = build_binding_prompt(labels, request.raw)
        record["prompt"] = prompt
        try:
            raw_text = backend.generate_image(str(overlay_path), prompt)
        except ModelCallError as error:
            model_error = str(error)
        else:
            record["model_text"] = raw_text
            try:
                decision = parse_binding_decision(raw_text, labels)
            except ValueError as error:
                parse_error = str(error)
            else:
                record["parse"] = {
                    "ok": True,
                    "occupancies": dict(decision.occupancies),
                    "selected": decision.selected,
                }
            if parse_error is not None:
                record["parse"] = {"ok": False, "error": parse_error}
    else:
        record["parse"] = {
            "ok": True,
            "skipped": "no candidate is fully visible; no model request",
        }

    if model_error is not None:
        record["model_error"] = model_error
        record["binding"] = None
        _write_json(out_dir / f"{name}.json", record)
        raise BindingModelError(model_error)

    if parse_error is not None:
        observations = tuple(
            CandidateObservation(
                label="",
                bay_id=projected.entity.bay_id,
                slot_node_id=projected.entity.slot_node_id,
                occupancy="unknown",
                visible=False,
                side=projected.side,
                bearing_deg=projected.bearing_deg,
                distance_m=projected.distance_m,
            )
            for projected in projected_all
        )
        binding = TargetBinding(
            status=BindingStatus.REFUSED,
            instruction=request.raw,
            round_index=round_index,
            bay_id=None,
            slot_node_id=None,
            selected_label=None,
            reason=f"model output not parseable: {parse_error}",
            candidates=observations,
            prior_bay_id=None if prior is None else prior.bay_id,
            evidence={
                "request": request.to_metadata(),
                "parse_error": parse_error,
                "raw_model_text": record["model_text"],
            },
        )
    else:
        observations = _observations(projected_all, labelled, decision)
        binding = resolve_target_binding(
            request,
            observations,
            decision,
            prior=prior,
            round_index=round_index,
        )

    record["binding"] = binding.to_metadata()
    _write_json(out_dir / f"{name}.json", record)
    return binding, record


def spawn_parked_vehicle(session, bay_id: str) -> object:
    """Spawn one real vehicle inside a known bay for occupancy experiments.

    The exact bay centre can overlap a structural pillar in this map, and the
    ceiling above bay03 is lower than above bay11, so a few points along the
    bay's long axis and a few spawn heights are tried in a fixed order. Every
    point is inside the declared polygon; the choice is reported by the
    vehicle's real transform in the evidence.
    """

    if bay_id not in BAY_CENTERS:
        raise ValueError(f"unknown bay {bay_id!r}")
    center_x, center_y = BAY_CENTERS[bay_id]
    blueprint = session.world.get_blueprint_library().find(nav01b.VEHICLE_BP)
    blueprint.set_attribute("role_name", f"{PARKED_ROLE_PREFIX}{bay_id}")
    if blueprint.has_attribute("color"):
        blueprint.set_attribute("color", "235,235,235")
    errors = []
    for offset_x in (0.0, 2.0, -2.0, 1.0, -1.0):
        for z in (6.7, 6.3, 6.0):
            vehicle = session.world.try_spawn_actor(
                blueprint,
                carla.Transform(
                    carla.Location(x=center_x + offset_x, y=center_y, z=z),
                    carla.Rotation(yaw=180.0),
                ),
            )
            if vehicle is not None:
                session.actors.append(vehicle)
                session.tick(10)
                return vehicle
            errors.append((offset_x, z))
    raise BindingRoundError(
        f"could not spawn a parked vehicle in {bay_id}; tried (x offset, z) "
        f"{errors}"
    )


def destroy_actor(session, actor) -> None:
    try:
        if actor.is_alive:
            actor.destroy()
    finally:
        if actor in session.actors:
            session.actors.remove(actor)
    session.tick(3)


def _parse_offset(text: str) -> tuple[float, float, float]:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("camera offset must be x,y,z")
    try:
        return tuple(float(part) for part in parts)  # type: ignore[return-value]
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--round-index", type=int, default=0)
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--prior-binding-json", default=None)
    parser.add_argument("--spawn-x", type=float, default=DEFAULT_SPAWN[0])
    parser.add_argument("--spawn-y", type=float, default=DEFAULT_SPAWN[1])
    parser.add_argument("--spawn-z", type=float, default=DEFAULT_SPAWN[2])
    parser.add_argument("--spawn-yaw", type=float, default=DEFAULT_SPAWN[3])
    parser.add_argument("--camera-offset", type=_parse_offset, default=DEFAULT_CAMERA_OFFSET)
    parser.add_argument("--camera-pitch", type=float, default=DEFAULT_CAMERA_PITCH)
    parser.add_argument("--camera-yaw", type=float, default=DEFAULT_CAMERA_YAW)
    parser.add_argument("--fov", type=float, default=DEFAULT_FOV)
    parser.add_argument(
        "--label-order",
        choices=("near_to_far", "far_to_near", "bay_id"),
        default="near_to_far",
    )
    parser.add_argument("--parked-bay", default=None, choices=tuple(BAY_CENTERS))
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--enable-thinking",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--allow-existing-actors", action="store_true")
    args = parser.parse_args(argv)

    try:
        request = parse_parking_instruction(args.instruction)
    except ValueError as error:
        parser.error(str(error))
    if args.round_index < 0:
        parser.error("--round-index must be non-negative")
    if not 0.0 < args.fov < 180.0:
        parser.error("--fov must be in (0, 180)")

    out_dir = (
        Path(args.output_dir)
        if args.output_dir
        else REPO_ROOT / "docs" / "evidence" / "cap07a-bind"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    prior = None
    if args.prior_binding_json:
        try:
            prior = parse_binding_artifact(
                json.loads(Path(args.prior_binding_json).read_text(encoding="utf-8"))
            )
        except (OSError, ValueError) as error:
            parser.error(f"invalid --prior-binding-json: {error}")

    session = None
    try:
        session = nav01b.Session(args.host, args.port, str(out_dir), map_name=MAP_NAME)
        leftovers = leftover_actors(session.world)
        if leftovers and not args.allow_existing_actors:
            types = sorted(
                {str(actor.attributes.get("role_name", "")) for actor in leftovers}
            )
            raise BindingRoundError(
                "world already contains vln_ actors: "
                + ", ".join(types)
                + "; pass --allow-existing-actors only for a scene you own"
            )
        ego = session.spawn_vehicle(
            EGO_ROLE, args.spawn_x, args.spawn_y, args.spawn_z, args.spawn_yaw
        )
        session.tick(30)
        parked = None
        if args.parked_bay:
            parked = spawn_parked_vehicle(session, args.parked_bay)
        backend = ZDTaichuServerBackend(
            max_new_tokens=args.max_new_tokens,
            timeout=args.timeout,
            enable_thinking=bool(args.enable_thinking),
        )
        binding, record = run_binding_round(
            session,
            ego,
            request=request,
            round_index=args.round_index,
            prior=prior,
            backend=backend,
            out_dir=out_dir,
            fov=args.fov,
            camera_offset=tuple(args.camera_offset),
            camera_pitch=args.camera_pitch,
            camera_yaw=args.camera_yaw,
            label_order=args.label_order,
            name=f"round_{args.round_index:02d}",
        )
        binding_path = out_dir / "binding.json"
        _write_json(binding_path, binding.to_metadata())
        print(
            json.dumps(
                {
                    "binding_json": str(binding_path),
                    "round_json": str(out_dir / f"round_{args.round_index:02d}.json"),
                    "status": binding.status,
                    "bay_id": binding.bay_id,
                    "slot_node_id": binding.slot_node_id,
                    "selected_label": binding.selected_label,
                    "reason": binding.reason,
                    "executable": binding.executable,
                    "model_text": record.get("model_text"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if binding.executable else 2
    except BindingModelError as error:
        print(f"MODEL ERROR: {error}", file=sys.stderr)
        return 3
    except (BindingRoundError, RuntimeError) as error:
        print(f"SETUP/ROUND ERROR: {error}", file=sys.stderr)
        return 4
    finally:
        if session is not None:
            try:
                session.close()
            finally:
                remaining = leftover_actors(session.world)
                if remaining:
                    print(
                        "WARNING: leftover vln_ actors after cleanup: "
                        + ", ".join(str(actor.id) for actor in remaining),
                        file=sys.stderr,
                    )


if __name__ == "__main__":
    sys.exit(main())
