"""CARLA RGB frame -> existing VLN observation -> real model decision.

The adapter has three deliberately small jobs:

1. **Pixels.** :func:`bgra_to_rgb` converts a CARLA ``sensor.camera.rgb``
   frame's BGRA buffer to tightly packed RGB and rejects an invalid frame
   instead of passing a malformed blob to the model. :func:`write_rgb_png`
   writes those exact RGB bytes (the script never substitutes a recorded image).
2. **Observation.** :class:`CarlaVisualObservation` carries the real frame
   metadata, the real ego pose, the caller's instruction and the prompt. Its
   :meth:`CarlaVisualObservation.model_observation` value is the local image
   path, which is exactly what the existing
   :class:`~vln.vlm.image_path_client.ServerImageModelClient` sends through the
   confirmed `data:` URI multimodal path.
3. **Decision.** :func:`generate_and_decide` makes one model call and then
   delegates, without re-implementation, to the frozen chain
   ``parse_visual_decision -> verify_visual_decision -> to_agent_intent``.
   Failures are classified as model-request, model-output or intent-rejection;
   no failure is converted into a default direction or a fabricated intent.

This module never imports ``carla``, never executes a vehicle and never talks to
the host/IPC layer. The intent it returns is a value only.
"""

from __future__ import annotations

import hashlib
import math
import struct
import time
import zlib
from dataclasses import dataclass
from typing import Optional

from vln.intent.agent_intent import AgentIntent
from vln.nav import (
    NavigationDirective,
    VehiclePose,
    VisualNavigationDecision,
    parse_visual_decision,
    to_agent_intent,
    verify_visual_decision,
)
from vln.vlm.model_client import ModelClient

__all__ = [
    "SUCCESS",
    "MODEL_REQUEST_FAILED",
    "MODEL_OUTPUT_INVALID",
    "INTENT_REJECTED",
    "CarlaObservationError",
    "InvalidCameraFrame",
    "CameraFrame",
    "CarlaVisualObservation",
    "DecisionOutcome",
    "bgra_to_rgb",
    "write_rgb_png",
    "generate_and_decide",
]

#: Terminal outcomes of :func:`generate_and_decide`.
SUCCESS = "success"
MODEL_REQUEST_FAILED = "model_request_failed"
MODEL_OUTPUT_INVALID = "model_output_invalid"
INTENT_REJECTED = "intent_rejected"


class CarlaObservationError(Exception):
    """A CARLA frame or observation could not be represented safely."""


class InvalidCameraFrame(CarlaObservationError):
    """The BGRA buffer or its declared dimensions are inconsistent."""


def _require_non_negative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise InvalidCameraFrame(f"{name} must be a non-negative int")
    return value


def bgra_to_rgb(raw: bytes, width: int, height: int) -> bytes:
    """Convert CARLA's BGRA8 sensor buffer to tightly packed RGB8.

    A CARLA RGB camera reports ``width * height * 4`` bytes in B, G, R, A
    order. Alpha is discarded. The length check is exact: a partial frame is
    rejected rather than padded or truncated.
    """

    if not isinstance(raw, (bytes, bytearray)):
        raise InvalidCameraFrame(
            f"BGRA buffer must be bytes or bytearray, got {type(raw).__name__}"
        )
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise InvalidCameraFrame("width and height must be positive ints")
    expected = width * height * 4
    if len(raw) != expected:
        raise InvalidCameraFrame(
            f"BGRA buffer is {len(raw)} bytes, expected {expected} "
            f"for {width}x{height}"
        )
    rgb = bytearray(width * height * 3)
    out = 0
    for i in range(0, expected, 4):
        rgb[out] = raw[i + 2]
        rgb[out + 1] = raw[i + 1]
        rgb[out + 2] = raw[i]
        out += 3
    return bytes(rgb)


def write_rgb_png(path: str, rgb: bytes, width: int, height: int) -> str:
    """Write ``rgb`` as an RGB PNG. Returns ``path``.

    This is deliberately a tiny stdlib writer: the evidence file is built from
    the converted sensor bytes, not from a recorded screenshot.
    """

    if type(path) is not str or path.strip() == "":
        raise CarlaObservationError("PNG path must be a non-blank str")
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise CarlaObservationError("width and height must be positive ints")
    if not isinstance(rgb, (bytes, bytearray)) or len(rgb) != width * height * 3:
        raise CarlaObservationError(
            f"RGB buffer must be exactly {width * height * 3} bytes"
        )

    stride = width * 3
    scanlines = bytearray()
    for y in range(height):
        scanlines.append(0)  # PNG filter type 0
        scanlines.extend(rgb[y * stride:(y + 1) * stride])

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(
            ">I", zlib.crc32(body) & 0xFFFFFFFF
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(scanlines), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as handle:
        handle.write(png)
    return path


@dataclass(frozen=True)
class CameraFrame:
    """One real CARLA RGB frame, with the identifiers needed to trace it."""

    frame_id: int
    timestamp: float
    width: int
    height: int
    rgb: bytes
    sim_frame: Optional[int] = None
    source: str = "carla.sensor.camera.rgb"

    def __post_init__(self) -> None:
        _require_non_negative_int(self.frame_id, "frame_id")
        if type(self.timestamp) not in (int, float) or not math.isfinite(self.timestamp):
            raise InvalidCameraFrame("timestamp must be a finite number")
        if self.timestamp < 0:
            raise InvalidCameraFrame("timestamp must be non-negative")
        if type(self.width) is not int or type(self.height) is not int:
            raise InvalidCameraFrame("width and height must be ints")
        if self.width <= 0 or self.height <= 0:
            raise InvalidCameraFrame("width and height must be positive")
        if not isinstance(self.rgb, bytes) or len(self.rgb) != self.width * self.height * 3:
            raise InvalidCameraFrame(
                "rgb must be bytes with exactly width*height*3 elements"
            )
        if self.sim_frame is not None:
            _require_non_negative_int(self.sim_frame, "sim_frame")
        if type(self.source) is not str or self.source.strip() == "":
            raise InvalidCameraFrame("source must be a non-blank str")

    @classmethod
    def from_bgra(
        cls,
        *,
        frame_id: int,
        timestamp: float,
        width: int,
        height: int,
        raw_bgra: bytes,
        sim_frame: Optional[int] = None,
        source: str = "carla.sensor.camera.rgb",
    ) -> "CameraFrame":
        return cls(
            frame_id=frame_id,
            timestamp=timestamp,
            width=width,
            height=height,
            rgb=bgra_to_rgb(raw_bgra, width, height),
            sim_frame=sim_frame,
            source=source,
        )

    def rgb_sha256(self) -> str:
        return hashlib.sha256(self.rgb).hexdigest()

    def to_metadata(self) -> dict:
        return {
            "frame_id": self.frame_id,
            "sim_frame": self.sim_frame,
            "timestamp": self.timestamp,
            "width": self.width,
            "height": self.height,
            "source": self.source,
            "rgb_sha256": self.rgb_sha256(),
            "frame_delta": (
                None if self.sim_frame is None else self.sim_frame - self.frame_id
            ),
        }


@dataclass(frozen=True)
class CarlaVisualObservation:
    """The real frame + pose + instruction mapped onto the existing model seam.

    ``model_observation`` is the local image path consumed by
    :class:`~vln.vlm.image_path_client.ServerImageModelClient`; it is not a
    textual description of the image. The prompt also carries the real pose so
    the model request has the available state context.
    """

    frame: CameraFrame
    image_path: str
    image_sha256: str
    image_size_bytes: int
    pose: VehiclePose
    instruction: str
    prompt: str

    def __post_init__(self) -> None:
        if not isinstance(self.frame, CameraFrame):
            raise CarlaObservationError("frame must be a CameraFrame")
        if type(self.image_path) is not str or self.image_path.strip() == "":
            raise CarlaObservationError("image_path must be a non-blank str")
        if type(self.image_sha256) is not str or len(self.image_sha256) != 64:
            raise CarlaObservationError("image_sha256 must be a 64-char hash")
        if type(self.image_size_bytes) is not int or self.image_size_bytes <= 0:
            raise CarlaObservationError("image_size_bytes must be positive")
        if not isinstance(self.pose, VehiclePose):
            raise CarlaObservationError("pose must be a VehiclePose")
        if type(self.instruction) is not str or self.instruction.strip() == "":
            raise CarlaObservationError("instruction must be a non-blank str")
        if type(self.prompt) is not str or self.prompt.strip() == "":
            raise CarlaObservationError("prompt must be a non-blank str")

    def model_observation(self) -> str:
        """The value the existing image model client treats as the observation."""

        return self.image_path

    def to_metadata(self) -> dict:
        return {
            "image_path": self.image_path,
            "image_sha256": self.image_sha256,
            "image_size_bytes": self.image_size_bytes,
            "image_prompt_sha256": hashlib.sha256(self.prompt.encode("utf-8")).hexdigest(),
            "instruction": self.instruction,
            "prompt": self.prompt,
            "pose": {
                "x": self.pose.x,
                "y": self.pose.y,
                "heading": self.pose.heading,
            },
            "frame": self.frame.to_metadata(),
        }


@dataclass(frozen=True)
class DecisionOutcome:
    """One model call plus the existing parse/verify/map result.

    ``intent`` is non-``None`` only when every layer accepted the model's
    judgement. A rejection preserves the raw output and the error so the
    failure is diagnosable; it is never repaired into a success.
    """

    status: str
    raw_model_output: Optional[str]
    decision: Optional[VisualNavigationDecision]
    directive: Optional[NavigationDirective]
    intent: Optional[AgentIntent]
    error_type: Optional[str]
    error_message: Optional[str]
    model_duration_seconds: float
    total_duration_seconds: float

    def to_metadata(self) -> dict:
        return {
            "status": self.status,
            "raw_model_output": self.raw_model_output,
            "decision": (
                None
                if self.decision is None
                else {
                    "target_field": self.decision.target_field,
                    "identified_as": self.decision.identified_as,
                    "visible": self.decision.visible,
                    "position": self.decision.position,
                    "direction": self.decision.direction,
                    "evidence": self.decision.evidence,
                }
            ),
            "directive": (
                None
                if self.directive is None
                else {
                    "direction": self.directive.direction,
                    "position": self.directive.position,
                    "identified_as": self.directive.identified_as,
                    "evidence": self.directive.evidence,
                }
            ),
            "intent": None if self.intent is None else self.intent.to_object(),
            "intent_payload": None if self.intent is None else self.intent.to_payload(),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "model_duration_seconds": round(self.model_duration_seconds, 3),
            "total_duration_seconds": round(self.total_duration_seconds, 3),
        }


def _error(exc: Exception) -> tuple[str, str]:
    return type(exc).__name__, str(exc)


def generate_and_decide(
    model: ModelClient,
    observation: CarlaVisualObservation,
    *,
    expected_identity: str,
    intent_id: str,
) -> DecisionOutcome:
    """Call the model once and run the frozen NAV-09 decision chain.

    The model is called through the existing ``ModelClient`` seam. The image
    path is the observation, so a real image path reaches
    ``ZDTaichuServerBackend.generate_image``. The return value records exactly
    which stage failed; no default direction, coordinate or intent is produced.
    """

    if not isinstance(observation, CarlaVisualObservation):
        raise CarlaObservationError("observation must be a CarlaVisualObservation")
    if type(expected_identity) is not str or expected_identity.strip() == "":
        raise CarlaObservationError("expected_identity must be a non-blank str")
    if type(intent_id) is not str or intent_id.strip() == "":
        raise CarlaObservationError("intent_id must be a non-blank str")

    total_start = time.perf_counter()
    model_start = time.perf_counter()
    try:
        raw = model.generate(observation.model_observation(), observation.prompt)
    except Exception as exc:  # the model is an untrusted boundary
        elapsed = time.perf_counter() - model_start
        error_type, message = _error(exc)
        return DecisionOutcome(
            status=MODEL_REQUEST_FAILED,
            raw_model_output=None,
            decision=None,
            directive=None,
            intent=None,
            error_type=error_type,
            error_message=message,
            model_duration_seconds=elapsed,
            total_duration_seconds=time.perf_counter() - total_start,
        )
    model_duration = time.perf_counter() - model_start
    if type(raw) is not str:
        return DecisionOutcome(
            status=MODEL_REQUEST_FAILED,
            raw_model_output=None,
            decision=None,
            directive=None,
            intent=None,
            error_type="ModelReturnTypeError",
            error_message=f"model returned {type(raw).__name__}, expected str",
            model_duration_seconds=model_duration,
            total_duration_seconds=time.perf_counter() - total_start,
        )

    try:
        decision = parse_visual_decision(raw)
    except Exception as exc:
        error_type, message = _error(exc)
        return DecisionOutcome(
            status=MODEL_OUTPUT_INVALID,
            raw_model_output=raw,
            decision=None,
            directive=None,
            intent=None,
            error_type=error_type,
            error_message=message,
            model_duration_seconds=model_duration,
            total_duration_seconds=time.perf_counter() - total_start,
        )

    try:
        directive = verify_visual_decision(
            decision, expected_identity=expected_identity
        )
    except Exception as exc:
        error_type, message = _error(exc)
        return DecisionOutcome(
            status=INTENT_REJECTED,
            raw_model_output=raw,
            decision=decision,
            directive=None,
            intent=None,
            error_type=error_type,
            error_message=message,
            model_duration_seconds=model_duration,
            total_duration_seconds=time.perf_counter() - total_start,
        )

    try:
        intent = to_agent_intent(
            directive, pose=observation.pose, intent_id=intent_id
        )
    except Exception as exc:
        error_type, message = _error(exc)
        return DecisionOutcome(
            status=INTENT_REJECTED,
            raw_model_output=raw,
            decision=decision,
            directive=directive,
            intent=None,
            error_type=error_type,
            error_message=message,
            model_duration_seconds=model_duration,
            total_duration_seconds=time.perf_counter() - total_start,
        )

    return DecisionOutcome(
        status=SUCCESS,
        raw_model_output=raw,
        decision=decision,
        directive=directive,
        intent=intent,
        error_type=None,
        error_message=None,
        model_duration_seconds=model_duration,
        total_duration_seconds=time.perf_counter() - total_start,
    )
