#!/usr/bin/env python3
"""M1-VLN-CARLA-01C: real CARLA RGB frame -> real ZDTaichu5.0-9B decision.

One run does exactly this and stops:

    CARLA sync tick -> front RGB camera -> BGRA->RGB PNG
      -> existing ServerImageModelClient (real image data: URI POST)
      -> real assistant text
      -> parse_visual_decision -> verify_visual_decision -> to_agent_intent

The resulting intent is recorded only. It is **not** turned into throttle,
brake or steering, and no Agent-Kernel host is started. The CARLA server is
managed by the companion launcher; the Taichu service is used as-is and is
never started, stopped or reconfigured here.

Exit codes: 0 validated intent, 2 model output invalid or intent rejected,
3 model request failed, 4 image capture failed, 5 unexpected error.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import carla  # noqa: E402  (CARLA client is only available in the CARLA venv)

from vln.carla import (  # noqa: E402
    INTENT_REJECTED,
    MODEL_OUTPUT_INVALID,
    MODEL_REQUEST_FAILED,
    SUCCESS,
    CameraFrame,
    CarlaVisualObservation,
    generate_and_decide,
    write_rgb_png,
)
from vln.carla.session import (  # noqa: E402
    destroy_actors,
    leftover_actors,
    restore_settings,
    settings_snapshot,
)
from vln.nav import VehiclePose  # noqa: E402
from vln.vlm import server_client as server_client_module  # noqa: E402
from vln.vlm.image_path_client import ServerImageModelClient  # noqa: E402
from vln.vlm.nav_prompt import Variant, build_nav_prompt  # noqa: E402
from vln.vlm.server_client import ZDTaichuServerBackend  # noqa: E402

MAP_NAME = "UndergroundCarPark"
HEALTH_URL = "http://127.0.0.1:8100/health"
CAM_W, CAM_H = 1280, 720
EXIT_SUCCESS = 0
EXIT_REJECTED = 2
EXIT_MODEL = 3
EXIT_CAPTURE = 4
EXIT_UNEXPECTED = 5


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def health() -> dict:
    try:
        with urlopen(HEALTH_URL, timeout=5) as response:  # noqa: S310 - fixed loopback
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


class LatestImage:
    def __init__(self):
        self.image = None

    def __call__(self, image):
        self.image = image


class RecordingResponse:
    """Tee the real response body so the exact request can be hashed."""

    def __init__(self, response, sink: dict):
        self._response = response
        self._sink = sink

    def read(self, limit=None):
        data = self._response.read(limit)
        self._sink["response_body"] = data
        return data

    def __enter__(self):
        self._response.__enter__()
        return self

    def __exit__(self, *exc):
        return self._response.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._response, name)


def install_request_recorder():
    """Record the one real POST without changing where it is sent."""

    original = server_client_module._OPENER.open
    calls: list[dict] = []

    def _open(request, timeout=None):
        sink = {
            "method": request.get_method(),
            "url": request.get_full_url(),
            "body": request.data,
            "has_authorization": any(
                name.lower() == "authorization" for name, _ in request.header_items()
            ),
            "http_status": None,
        }
        calls.append(sink)
        response = original(request, timeout=timeout)
        sink["http_status"] = getattr(response, "status", None)
        return RecordingResponse(response, sink)

    server_client_module._OPENER.open = _open

    def restore():
        server_client_module._OPENER.open = original

    return calls, restore


def request_evidence(calls: list[dict], image_sha256: str) -> dict:
    if not calls:
        return {"request_count": 0}
    if len(calls) != 1:
        return {"request_count": len(calls), "error": "expected exactly one request"}
    sink = calls[0]
    body = sink.get("body") or b""
    evidence = {
        "request_count": 1,
        "url": sink.get("url"),
        "method": sink.get("method"),
        "authorization_header_present": sink.get("has_authorization"),
        "http_status": sink.get("http_status"),
        "body_bytes": len(body),
        "body_sha256": sha256_bytes(body) if body else None,
        "image_sha256_in_request": None,
        "image_sha256_matches_frame": None,
        "content_part_types": None,
        "payload_prompt_sha256": None,
        "server_response_id": None,
        "response_model": None,
        "finish_reason": None,
        "usage": None,
        "generation_time": None,
        "assistant_content": None,
        "assistant_content_sha256": None,
        "reasoning_content": None,
    }
    try:
        payload = json.loads(body.decode("utf-8"))
        content = payload["messages"][0]["content"]
        evidence["content_part_types"] = [
            item.get("type") if isinstance(item, dict) else type(item).__name__
            for item in content
        ]
        text_part = next(
            item for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
        evidence["payload_prompt_sha256"] = sha256_bytes(
            text_part["text"].encode("utf-8")
        )
        image_part = next(
            item for item in content
            if isinstance(item, dict) and item.get("type") == "image_url"
        )
        url = image_part["image_url"]["url"]
        _, _, encoded = url.partition(";base64,")
        decoded = base64.b64decode(encoded)
        evidence["image_sha256_in_request"] = sha256_bytes(decoded)
        evidence["image_sha256_matches_frame"] = (
            evidence["image_sha256_in_request"] == image_sha256
        )
    except Exception as exc:
        evidence["payload_error"] = f"{type(exc).__name__}: {exc}"
    response_body = sink.get("response_body")
    if response_body:
        try:
            response = json.loads(response_body.decode("utf-8"))
            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content")
            evidence.update({
                "server_response_id": response.get("id"),
                "response_model": response.get("model"),
                "finish_reason": choice.get("finish_reason"),
                "usage": response.get("usage"),
                "generation_time": response.get("generation_time"),
                "assistant_content": content,
                "assistant_content_sha256": (
                    sha256_bytes(content.encode("utf-8"))
                    if isinstance(content, str) else None
                ),
                "reasoning_content": message.get("reasoning_content"),
            })
        except Exception as exc:
            evidence["response_payload_error"] = f"{type(exc).__name__}: {exc}"
    return evidence


def spawn_ego(world):
    bp = world.get_blueprint_library().find("vehicle.dodge.charger")
    bp.set_attribute("role_name", "vln_ego_01c")
    spawn_point = world.get_map().get_spawn_points()[0]
    ego = world.try_spawn_actor(bp, spawn_point)
    if ego is None:
        raise RuntimeError("failed to spawn the ego vehicle")
    return ego, spawn_point


def capture_frame(world, ego, out_dir: Path):
    """Tick the sync world and return one fresh RGB frame + ego state."""

    camera_bp = world.get_blueprint_library().find("sensor.camera.rgb")
    camera_bp.set_attribute("image_size_x", str(CAM_W))
    camera_bp.set_attribute("image_size_y", str(CAM_H))
    camera_bp.set_attribute("fov", "100")
    camera_bp.set_attribute("sensor_tick", "0.0")
    camera_bp.set_attribute("role_name", "vln_camera_01c")
    camera_tf = carla.Transform(
        carla.Location(x=-4.0, y=0.0, z=2.0),
        carla.Rotation(pitch=-5.0, yaw=0.0),
    )
    camera = world.spawn_actor(camera_bp, camera_tf, attach_to=ego)
    latest = LatestImage()
    camera.listen(latest)
    try:
        for _ in range(30):
            world.tick()
        image = latest.image
        if image is None:
            raise RuntimeError("camera produced no frame")
        if image.width != CAM_W or image.height != CAM_H:
            raise RuntimeError(
                f"camera frame is {image.width}x{image.height}, expected {CAM_W}x{CAM_H}"
            )
        if len(image.raw_data) != image.width * image.height * 4:
            raise RuntimeError(
                f"camera buffer is {len(image.raw_data)} bytes, expected "
                f"{image.width * image.height * 4}"
            )
        snapshot = world.get_snapshot()
        state_frame = snapshot.frame
        if state_frame - image.frame > 2:
            raise RuntimeError(
                f"stale camera frame: image.frame={image.frame}, "
                f"world.frame={state_frame}"
            )
        frame = CameraFrame.from_bgra(
            frame_id=image.frame,
            timestamp=image.timestamp,
            width=image.width,
            height=image.height,
            raw_bgra=bytes(image.raw_data),
            sim_frame=state_frame,
        )
        image_path = str(out_dir / ("frame_%06d.png" % frame.frame_id))
        write_rgb_png(image_path, frame.rgb, frame.width, frame.height)

        transform = ego.get_transform()
        velocity = ego.get_velocity()
        state = {
            "x": round(transform.location.x, 3),
            "y": round(transform.location.y, 3),
            "z": round(transform.location.z, 3),
            "yaw_deg": round(transform.rotation.yaw, 3),
            "heading_rad": round(math.radians(transform.rotation.yaw), 6),
            "speed_mps": round(math.hypot(velocity.x, velocity.y), 3),
            "snapshot_frame": state_frame,
            "sim_timestamp": snapshot.timestamp.elapsed_seconds,
            "image_frame_delta": state_frame - image.frame,
        }
        return frame, state, image_path, camera.id, camera_tf
    finally:
        camera.stop()
        camera.destroy()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--target", default="B1")
    parser.add_argument("--target-kind", default="区域标识")
    parser.add_argument(
        "--instruction",
        default=(
            "观察当前地下停车场环境，判断下一步适合沿当前通道直行、向左转还是向右转；"
            "若图像证据不足或无法确定安全方向，应明确表示不确定，不要猜测。"
        ),
    )
    parser.add_argument("--max-new-tokens", type=int, default=700)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else REPO_ROOT / "docs" / "evidence" / "carla-01c"
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = "carla-01c-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result = {
        "meta": {
            "task": "M1-VLN-CARLA-01C",
            "run_id": run_id,
            "map": MAP_NAME,
            "carla_endpoint": f"{args.host}:{args.port}",
            "model_endpoint": "http://127.0.0.1:8100/v1/chat/completions",
            "target": args.target,
            "target_kind": args.target_kind,
            "instruction": args.instruction,
        },
        "status": None,
        "error": None,
    }

    client = carla.Client(args.host, args.port)
    client.set_timeout(120.0)
    world = None
    ego = None
    snapshot = None
    actors: list[object] = []
    restore_opener = None
    exit_code = EXIT_UNEXPECTED
    capture_started = utc_now()

    try:
        world = client.get_world()
        if not world.get_map().name.endswith(MAP_NAME):
            client.load_world(MAP_NAME)
            world = client.get_world()
        result["meta"]["server_version"] = client.get_server_version()
        result["meta"]["map_loaded"] = world.get_map().name
        result["meta"]["model_health"] = health()

        settings = world.get_settings()
        snapshot = settings_snapshot(settings)
        result["settings"] = {"before": snapshot, "after": None}
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        settings.no_rendering_mode = False
        world.apply_settings(settings)

        leftovers = leftover_actors(world)
        if leftovers:
            destroy_actors(leftovers)
            world.tick()

        ego, spawn_point = spawn_ego(world)
        actors.append(ego)
        for _ in range(40):
            world.tick()
        result["meta"]["spawn_point"] = {
            "x": spawn_point.location.x,
            "y": spawn_point.location.y,
            "z": spawn_point.location.z,
            "yaw": spawn_point.rotation.yaw,
        }

        frame, state, image_path, camera_id, camera_tf = capture_frame(world, ego, out_dir)
        image_sha = sha256_file(image_path)
        image_size = os.path.getsize(image_path)
        capture_finished = utc_now()
        result["capture"] = {
            "started_utc": capture_started,
            "finished_utc": capture_finished,
            "camera_actor_id": camera_id,
            "camera_transform": {
                "x": camera_tf.location.x,
                "y": camera_tf.location.y,
                "z": camera_tf.location.z,
                "pitch": camera_tf.rotation.pitch,
                "yaw": camera_tf.rotation.yaw,
            },
            "image_path": image_path,
            "image_sha256": image_sha,
            "image_size_bytes": image_size,
            "frame": frame.to_metadata(),
            "state": state,
        }

        pose = VehiclePose(
            x=state["x"],
            y=state["y"],
            heading=state["heading_rad"],
        )
        intent_id = f"carla-01c-intent-{frame.frame_id}"
        state_text = (
            f"当前车辆状态（来自 CARLA 本轮仿真）：x={state['x']:.3f} m，"
            f"y={state['y']:.3f} m，yaw={state['yaw_deg']:.3f}°"
            f"（{state['heading_rad']:.6f} rad），速度={state['speed_mps']:.3f} m/s。"
        )
        nav_prompt = build_nav_prompt(
            Variant.TARGET_DIRECTION,
            target=args.target,
            intent_id=intent_id,
            target_kind=args.target_kind,
            require_identity=True,
            require_evidence=True,
        )
        prompt = (
            f"用户导航指令：{args.instruction}\n"
            f"{state_text}\n\n"
            + nav_prompt
        )
        observation = CarlaVisualObservation(
            frame=frame,
            image_path=image_path,
            image_sha256=image_sha,
            image_size_bytes=image_size,
            pose=pose,
            instruction=args.instruction,
            prompt=prompt,
        )
        result["observation"] = observation.to_metadata()
        result["observation"]["intent_id"] = intent_id

        calls, restore_opener = install_request_recorder()
        # This server returns the whole generation (including </think> and the
        # repeated final block) as `content` when thinking is disabled. Keeping
        # the server's reasoning separation enabled returns only the final
        # answer as `content` and exposes the reasoning in
        # `reasoning_content`; the strict parser is not changed or bypassed.
        backend = ZDTaichuServerBackend(
            max_new_tokens=args.max_new_tokens,
            timeout=args.timeout,
            temperature=0.0,
            enable_thinking=True,
        )
        model = ServerImageModelClient(backend=backend)
        inference_started = utc_now()
        outcome = generate_and_decide(
            model,
            observation,
            expected_identity=args.target,
            intent_id=intent_id,
        )
        inference_finished = utc_now()

        evidence = request_evidence(calls, image_sha)
        evidence["inference_started_utc"] = inference_started
        evidence["inference_finished_utc"] = inference_finished
        evidence["local_request_id"] = run_id
        result["request"] = evidence
        result["decision"] = outcome.to_metadata()
        result["status"] = outcome.status
        if outcome.status != SUCCESS:
            result["error"] = {
                "type": outcome.error_type,
                "message": outcome.error_message,
            }

        if outcome.status == SUCCESS:
            exit_code = EXIT_SUCCESS
        elif outcome.status in (MODEL_OUTPUT_INVALID, INTENT_REJECTED):
            exit_code = EXIT_REJECTED
        elif outcome.status == MODEL_REQUEST_FAILED:
            exit_code = EXIT_MODEL
        else:
            exit_code = EXIT_UNEXPECTED
    except Exception as exc:
        result["status"] = "image_capture_failed" if result.get("capture") is None else "error"
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        exit_code = EXIT_CAPTURE if result.get("capture") is None else EXIT_UNEXPECTED
    finally:
        if restore_opener is not None:
            restore_opener()
        destroy_errors = destroy_actors(actors)
        if world is not None:
            remaining = leftover_actors(world)
            if remaining:
                destroy_errors.extend(destroy_actors(remaining))
                try:
                    world.tick()
                except Exception:
                    pass
            result["cleanup"] = {
                "destroyed_ego": ego is not None,
                "destroy_errors": destroy_errors,
                "leftover_vln_actors": len(leftover_actors(world)),
            }
        if world is not None and snapshot is not None:
            try:
                after = restore_settings(world, snapshot)
            except Exception as exc:
                after = {"restore_error": f"{type(exc).__name__}: {exc}"}
            result["settings"]["after"] = after
        path = out_dir / "result.json"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False)
        print("wrote", path)
        print(
            "status=%s frame=%s image=%s"
            % (
                result.get("status"),
                result.get("capture", {}).get("frame", {}).get("frame_id"),
                result.get("capture", {}).get("image_sha256"),
            )
        )
        if result.get("decision"):
            print(
                "raw_output=%r"
                % (result["decision"].get("raw_model_output"),)
            )
            print(
                "direction=%s intent=%s"
                % (
                    (result["decision"].get("directive") or {}).get("direction"),
                    result["decision"].get("intent"),
                )
            )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
