"""Skip-gated REAL multimodal round: one parking-lot image -> the local service.

What this is: the honest counterpart of the offline image tests. The offline
tests replace the transport, so they can only show that the *right request would
be built*; this file sends the request to the already-running
``taichu_server`` on the confirmed loopback endpoint and records what actually
crossed the wire.

The service is contacted, never managed: it is not started, stopped, restarted
or reconfigured here, and its listening address, authentication mode and
startup script are untouched. Nothing is sent unless ``VLN_ZDTAICHU_IMAGE_SMOKE``
is explicitly set to ``1``, and the endpoint is the module's own confirmed
``http://127.0.0.1:8100/v1/chat/completions`` - the transport override used for
evidence capture wraps the real opener, it does not redirect anywhere.

Evidence captured per scene, all without printing the image or any credential:

* the image the client resolved - path, media type, byte count, SHA-256;
* the request that was actually written to the socket - body byte count and
  body SHA-256, the content-part types, whether an ``Authorization`` header was
  present, and the POST count;
* the base64 payload decoded back out of that recorded body and hashed, which
  must equal the file's own SHA-256. That equality is what proves the image
  bytes - not just a file name - reached the model;
* the raw assistant text, the full decoded response object, the
  ``parse_model_output`` result and the ``AgentIntent.from_payload`` result.

The model output is never repaired and no outcome is asserted to be a valid
intent: a refusal or an unparsable answer is recorded as such. The scene
expectations below are written from the actual images (crops were inspected),
not from their file names.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest

from vln.intent import AgentIntent, ModelOutputError, parse_model_output
from vln.vlm import server_client as server_client_module
from vln.vlm.image_input import load_image_part
from vln.vlm.server_client import ZDTaichuServerBackend
from vln.vlm.zdtaichu_client import PreparedObservation

pytestmark = pytest.mark.integration

_SMOKE_ENV = "VLN_ZDTAICHU_IMAGE_SMOKE"
_SCENES_ENV = "VLN_ZDTAICHU_SCENES"
_IMAGES_DIR = Path(__file__).resolve().parents[2] / "images"

#: One instruction for every scene, so a difference between two answers can only
#: come from the image. It asks for the existing contract exactly and gives the
#: model an explicit, contract-shaped way out: an empty answer.
INSTRUCTION = (
    "请观察这张停车场图像，判断可见的车位标识、道路结构、通行区域及可能的障碍物。"
    "导航目标为 P07。只输出一个 JSON 对象，不要输出任何其他文字、解释或代码块标记，"
    '键必须恰好是 contract_version、intent_id、action、target：{"contract_version":"1",'
    '"intent_id":"<字符串>","action":"parking.move","target":{"x":<数值>,"y":<数值>,'
    '"heading":<数值>}}。'
    "如果图像中没有可见的车位编号标识、目标标识不是 P07、或无法判断通道是否畅通，"
    "请直接返回空字符串，不要编造坐标。"
)

#: The four owner-supplied frames, identified by what the images actually show.
SCENES = {
    "IMG-01": {
        "file": "17931c01d3fda4038c76944a334b3aef.png",
        "seen": (
            "CARLA UE4 underground level: a single aisle seen head-on, orange 'C' column "
            "markers, a blue 出口/EXIT sign and a raised metal gate on the left wall, a blue "
            "circular straight-ahead sign, a straight/cross floor arrow mid-lane with a "
            "right-turn arrow to its right, dashed bay outlines both sides, yellow-black "
            "chevrons on the column bases, ceiling strip lights"
        ),
        "expected": (
            "no bay identifier is legible; no P07 marking is visible; the left-hand gate "
            "reads as closed, so the left branch is not a confirmed through-route"
        ),
        # A question whose answer is verifiable from the pixels alone and shares no
        # wording with the JSON contract, so an answer here cannot be a template echo.
        "grounding_question": "这张图中的立柱上重复出现了什么字母标识？只回答该字母，不要解释。",
        "grounding_answer": "C",
    },
    "IMG-02": {
        "file": "7328a8047ee41f088cceadaa7daa9b6d.png",
        "seen": (
            "same garage, teal 'A' column markers, a much wider bay field on both sides, a "
            "straight/left/right floor arrow, black-orange wheel stops in the bays, a "
            "yellow-black hazard bar across the near foreground, blue circular signs ahead"
        ),
        "expected": (
            "rotated bay identifiers are legible on the near-right bay row, 'D65' among "
            "them, and further 'D6x' identifiers up that row; none of them is P07"
        ),
        "detail": "confirmed on a 3x crop of the right-hand bay row",
        "grounding_question": "这张图中的立柱上重复出现了什么字母标识？只回答该字母，不要解释。",
        "grounding_answer": "A",
    },
    "IMG-03": {
        "file": "7ea84b439661950fcb5ec85d81011bfd.png",
        "seen": (
            "same garage, navy 'B' column markers, the widest view of the four - long bay "
            "rows on both sides receding into the distance, wheel stops throughout, a "
            "straight/right floor arrow in the left lane and a straight arrow in the right"
        ),
        "expected": (
            "rotated bay identifiers in the 'D0x' range are partly legible on the right-hand "
            "row; no P07 marking is visible"
        ),
        "detail": "read from a 3.5x crop; the digits are partially occluded",
        "grounding_question": "这张图中的立柱上重复出现了什么字母标识？只回答该字母，不要解释。",
        "grounding_answer": "B",
    },
    "IMG-04": {
        "file": "9a6908511ef1211af2ae8483c103bb63.png",
        "seen": (
            "same garage, orange 'C' column markers, wall-mounted charging boxes with "
            "cables along the right-hand wall, an overhead blue 出口/EXIT sign paired with a "
            "turn arrow sign in the centre distance, a straight/left arrow and a "
            "straight/right arrow on the deck, a yellow-black hazard bar across the lane"
        ),
        "expected": (
            "a rotated bay identifier reading '316' is legible on the near-right deck; "
            "no P07 marking is visible"
        ),
        "detail": "confirmed on a 3x crop of the right-hand deck marking",
        "grounding_question": "这张图中的立柱上重复出现了什么字母标识？只回答该字母，不要解释。",
        "grounding_answer": "C",
    },
}

#: The two scenes whose visual content differs most (different section letter and
#: different layout), used for the comparison round.
_DEFAULT_SCENES = ("IMG-01", "IMG-02")


class _RecordingResponse:
    """Tee ``read`` off the real response so the wire body can be recorded."""

    def __init__(self, response, sink: dict) -> None:
        self._response = response
        self._sink = sink

    def read(self, limit: int | None = None) -> bytes:
        data = self._response.read(limit)
        self._sink["response_body"] = data
        return data

    def __enter__(self) -> "_RecordingResponse":
        self._response.__enter__()
        return self

    def __exit__(self, *exc: object) -> object:
        return self._response.__exit__(*exc)

    def __getattr__(self, name: str) -> object:
        return getattr(self._response, name)


def _install_recorder():
    """Wrap the real opener so each POST is recorded, then sent as usual."""

    original = server_client_module._OPENER.open
    calls: list = []

    def _open(request, timeout=None):
        sink: dict = {
            "method": request.get_method(),
            "url": request.get_full_url(),
            "body": request.data,
            "has_authorization": any(
                name.lower() == "authorization" for name, _ in request.header_items()
            ),
        }
        calls.append(sink)
        return _RecordingResponse(original(request, timeout=timeout), sink)

    server_client_module._OPENER.open = _open
    return calls, original


def _request_evidence(sink: dict, part=None) -> dict:
    """Describe one recorded request without printing the image payload.

    ``part`` is the client-side :class:`~vln.vlm.image_input.ImagePart`; when it
    is ``None`` the request carried no image part (the text-only control) and the
    image fields are omitted.
    """

    body = sink["body"]
    payload = json.loads(body.decode("utf-8"))
    (message,) = payload["messages"]
    content = message["content"]

    evidence = {
        "url": sink["url"],
        "method": sink["method"],
        "authorization_header_present": sink["has_authorization"],
        "body_bytes": len(body),
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "payload_keys": sorted(payload),
        "content_part_types": [
            item["type"] if isinstance(item, dict) else type(item).__name__
            for item in content
        ],
    }
    if part is None:
        evidence["text_chars"] = len(content[-1]["text"])
        return evidence

    image_part, text_part = content
    url = image_part["image_url"]["url"]
    media_type, _, encoded = url.partition(";base64,")
    decoded = base64.b64decode(encoded)

    evidence.update(
        {
            "instruction_chars": len(text_part["text"]),
            "image_data_uri_prefix": media_type + ";base64,",
            "image_base64_chars": len(encoded),
            "image_decoded_bytes": len(decoded),
            "image_decoded_sha256": hashlib.sha256(decoded).hexdigest(),
            "matches_the_file_on_disk": hashlib.sha256(decoded).hexdigest()
            == part.sha256,
        }
    )
    return evidence


def _scenes_to_run() -> tuple:
    raw = os.environ.get(_SCENES_ENV, "").strip()
    if not raw:
        return _DEFAULT_SCENES
    chosen = tuple(name.strip() for name in raw.split(",") if name.strip())
    unknown = [name for name in chosen if name not in SCENES]
    if unknown:
        pytest.fail(f"unknown scene id(s) in ${_SCENES_ENV}: {unknown}")
    return chosen


def _gate() -> None:
    if os.environ.get(_SMOKE_ENV) != "1":
        pytest.skip(
            f"{_SMOKE_ENV} is not set to 1; this test sends real multimodal "
            "requests to the local inference service"
        )
    if not _IMAGES_DIR.is_dir():
        pytest.skip(f"image directory not found: {_IMAGES_DIR}")


def _one_image_round(scene_id: str, instruction: str, *, max_new_tokens: int = 256):
    """Send exactly one image round and return everything the record needs."""

    scene = SCENES[scene_id]
    image_path = _IMAGES_DIR / scene["file"]
    if not image_path.is_file():
        pytest.skip(f"scene image missing: {image_path}")

    backend = ZDTaichuServerBackend(
        max_new_tokens=max_new_tokens,
        temperature=0.0,
        enable_thinking=False,
        timeout=180.0,
    )
    part = load_image_part(image_path)

    calls, original = _install_recorder()
    try:
        raw = backend.generate_image(str(image_path), instruction)
    finally:
        server_client_module._OPENER.open = original

    assert type(raw) is str
    assert len(calls) == 1, "an image round must be exactly one POST"
    return backend, image_path, part, raw, calls


def _emit(record: dict) -> None:
    print("SCENE EVIDENCE " + json.dumps(record, ensure_ascii=False))


@pytest.mark.parametrize("scene_id", _scenes_to_run())
def test_real_image_round_reaches_the_model_and_the_parse_boundary(scene_id: str) -> None:
    _gate()
    scene = SCENES[scene_id]
    backend, image_path, part, raw, calls = _one_image_round(scene_id, INSTRUCTION)

    evidence = {
        "phase": "contract-round",
        "scene_id": scene_id,
        "image": part.safe_description(),
        "image_content": scene["seen"],
        "expected_observations": scene["expected"],
        "instruction_chars": len(INSTRUCTION),
        "endpoint": backend.endpoint,
        "request": _request_evidence(calls[0], part),
    }
    assert evidence["request"]["matches_the_file_on_disk"], (
        "the bytes on the wire were not the image file's bytes"
    )

    response = json.loads(calls[0]["response_body"].decode("utf-8"))
    evidence["response"] = {
        "id": response.get("id"),
        "model": response.get("model"),
        "usage": response.get("usage"),
        "choices_count": len(response.get("choices", [])),
        "finish_reason": response["choices"][0].get("finish_reason"),
        "reasoning_content_chars": len(
            response["choices"][0]["message"].get("reasoning_content") or ""
        ),
    }
    evidence["raw_assistant_text"] = raw

    try:
        intent = parse_model_output(raw)
    except ModelOutputError as exc:
        evidence["parse_model_output"] = {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
        }
        _emit(evidence)
        return

    intent_payload = json.loads(intent.to_payload())
    evidence["parse_model_output"] = {"ok": True, "payload": intent_payload}
    evidence["agent_intent_from_payload"] = {
        "ok": True,
        "equals_the_parsed_intent": AgentIntent.from_payload(raw).to_object()
        == intent.to_object(),
        "contract_verified": isinstance(intent, AgentIntent),
        "action": intent.action,
        "intent_id": intent.intent_id,
        "target": {"x": intent.target.x, "y": intent.target.y,
                   "heading": intent.target.heading},
        "note": (
            "contract-valid syntax only: this target was produced by the model from "
            "the image and is NOT a measured real-world coordinate"
        ),
    }
    _emit(evidence)


@pytest.mark.parametrize("scene_id", _scenes_to_run())
def test_real_image_visual_grounding_probe(scene_id: str) -> None:
    """Ask a question the JSON contract cannot answer, and record the answer.

    A target-only round cannot distinguish "read the image" from "copied the
    template in the instruction". This round removes the template: the answer is
    a single character that exists only in the pixels.

    Nothing about the answer is asserted - a wrong or evasive answer is a real
    result about the model, and this record must not manufacture a pass.
    """

    _gate()
    scene = SCENES[scene_id]
    backend, _image_path, part, raw, calls = _one_image_round(
        scene_id, scene["grounding_question"], max_new_tokens=64
    )

    answer = raw.strip()
    request = _request_evidence(calls[0], part)
    _emit(
        {
            "phase": "grounding-probe",
            "scene_id": scene_id,
            "image_sha256": part.sha256,
            "question": scene["grounding_question"],
            "expected_answer_from_the_pixels": scene["grounding_answer"],
            "raw_assistant_text": raw,
            "answer_matches_the_pixels": answer.upper()
            == scene["grounding_answer"].upper(),
            "request": {
                "content_part_types": request["content_part_types"],
                "matches_the_file_on_disk": request["matches_the_file_on_disk"],
            },
            "endpoint": backend.endpoint,
        }
    )


def test_text_only_control_without_any_image() -> None:
    """The discriminating control: the same prompts, sent with no image.

    If the text-only answer equals the image answer, then the image did not
    change the output and the round above proves nothing about vision.
    """

    _gate()
    backend = ZDTaichuServerBackend(
        max_new_tokens=256, temperature=0.0, enable_thinking=False, timeout=180.0
    )

    calls, original = _install_recorder()
    try:
        contract_answer = backend.generate(PreparedObservation(text=INSTRUCTION), "")
        grounding_answer = backend.generate(
            PreparedObservation(text=SCENES["IMG-01"]["grounding_question"]), ""
        )
    finally:
        server_client_module._OPENER.open = original

    assert len(calls) == 2
    _emit(
        {
            "phase": "text-only-control",
            "note": (
                "no image in these requests; compare with the contract-round and "
                "grounding-probe records for the same prompts"
            ),
            "content_part_types_per_request": [
                _request_evidence(call)["content_part_types"] for call in calls
            ],
            "contract_answer_without_image": contract_answer,
            "grounding_answer_without_image": grounding_answer,
        }
    )
