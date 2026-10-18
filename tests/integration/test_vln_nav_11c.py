"""NAV-11C authorized real-model probe and two-round closed-loop test.

This file is inert unless ``VLN_ZDTAICHU_NAV_11C=1``. It has two separately
selected phases, via ``VLN_ZDTAICHU_NAV_11C_PHASE``:

* ``probe``      - exactly one real image inference; output -> NAV-09 -> real Host.
* ``closed_loop`` - exactly two real image inferences; round 2 must receive the
  encoded real round-1 ``Response``.

Every HTTP POST is recorded in a persistent ledger under the evidence directory;
the hard cap is 4 POSTs across all phases. No Authorization value is written to
evidence, only whether a header was present.

Evidence is appended to ``VLN_ZDTAICHU_NAV_11C_OUT``. The test does not start,
stop or reconfigure the model service; it uses the existing loopback client and
the existing ``kernel_host`` binary supplied by ``VLN_KERNEL_HOST_EXE``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest

import vln.vlm.server_client as server_client_module
from vln.client import HostClient, build_request
from vln.intent import AgentIntent
from vln.ipc.envelope import HostKind
from vln.nav import (
    VehiclePose,
    parse_visual_decision,
    verify_visual_decision,
)
from vln.nav_execution import run_visual_parking_intent
from vln.observation import ResponseFeedbackEncoder
from vln.pipeline import LoopStopReason
from vln.visual_loop import VisualLoopModelClient, run_visual_parking_loop
from vln.vlm import (
    Variant,
    ZDTaichuServerBackend,
    build_nav_prompt,
    load_image_part,
)
from vln.vlm.image_path_client import (
    FEEDBACK_SECTION_HEADER,
    ServerImageModelClient,
)

pytestmark = pytest.mark.integration

_GATE_ENV = "VLN_ZDTAICHU_NAV_11C"
_PHASE_ENV = "VLN_ZDTAICHU_NAV_11C_PHASE"
_OUT_ENV = "VLN_ZDTAICHU_NAV_11C_OUT"
_SCENE_ENV = "VLN_ZDTAICHU_NAV_11C_SCENE"
_HOST_ENV = "VLN_KERNEL_HOST_EXE"

_IMAGES_DIR = Path(__file__).resolve().parents[2] / "images"
_EXPECTED_HOST_SHA256 = (
    "c12362804087ce65c2c7e0b9d8b54981ed9b766427c33fc7cde0cfadef3a754c"
)
_MAX_POSTS = 4

_SCENES = {
    "exit_left": {
        "file": "17931c01d3fda4038c76944a334b3aef.png",
        "sha256": "da9f92932ae401ae16dda1e262379cf34bc324cf13da5e5d15aac5f123420eba",
        "history": "NAV-10/09 certified EXIT/LEFT",
    },
    "exit_ahead": {
        "file": "9a6908511ef1211af2ae8483c103bb63.png",
        "sha256": "07e1c631aa9a6a5f2c070b32fc096a2023b0b5034fd64dd167414b6ebed14505",
        "history": "NAV-10/09 certified EXIT/AHEAD",
    },
}

#: Explicitly simulated/test-only; no localisation exists in this project.
SIMULATED_TEST_POSE = VehiclePose(x=12.5, y=-4.0, heading=0.25)

_PROMPT = build_nav_prompt(
    Variant.TARGET_DIRECTION,
    target="出口",
    target_kind="目标标识",
    require_identity=True,
    require_evidence=True,
)


class _PostLedger:
    """Persistent, auditable POST budget across separate phase processes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries = self._count()

    def _count(self) -> int:
        if not self.path.is_file():
            return 0
        return sum(
            1
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    @property
    def entries(self) -> int:
        return self._entries

    def append(self, phase: str, call_index: int) -> int:
        if self._entries >= _MAX_POSTS:
            raise RuntimeError(
                f"NAV-11C POST budget exhausted: {self._entries}/{_MAX_POSTS}"
            )
        self._entries += 1
        entry = {
            "attempt": self._entries,
            "phase": phase,
            "call_index": call_index,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n"
            )
        return self._entries


class _RecordingResponse:
    def __init__(self, response, sink: dict) -> None:
        self._response = response
        self._sink = sink

    def read(self, limit: int | None = None) -> bytes:
        data = self._response.read(limit)
        self._sink["response_body"] = data
        return data

    def __enter__(self):
        self._response.__enter__()
        return self

    def __exit__(self, *exc: object):
        return self._response.__exit__(*exc)

    def __getattr__(self, name: str):
        return getattr(self._response, name)


def _install_recorder(ledger: _PostLedger, phase: str):
    """Patch the confirmed server opener; count and capture each POST attempt."""

    original = server_client_module._OPENER.open
    calls: list[dict] = []

    def _open(request, timeout=None):
        call_index = len(calls)
        attempt = ledger.append(phase, call_index)
        entry = {
            "attempt": attempt,
            "phase": phase,
            "call_index": call_index,
            "body": request.data,
            # Never store the Authorization value.
            "authorization_header_present": request.get_header("Authorization")
            is not None,
        }
        calls.append(entry)
        return _RecordingResponse(original(request, timeout=timeout), entry)

    server_client_module._OPENER.open = _open
    return calls, original


def _request_info(call: dict, part, scene: dict) -> dict:
    """Return sanitized request evidence: text, image hash, body hash only."""

    body = call["body"]
    payload = json.loads(body.decode("utf-8"))
    (message,) = payload["messages"]
    contents = message["content"]
    image_url = next(
        item["image_url"]["url"]
        for item in contents
        if item.get("type") == "image_url"
    )
    text = next(item["text"] for item in contents if item.get("type") == "text")
    encoded = image_url.partition(";base64,")[2]
    wire_sha = hashlib.sha256(base64.b64decode(encoded)).hexdigest()

    response_body = call.get("response_body")
    usage = None
    response_sha = None
    raw_assistant = None
    if isinstance(response_body, (bytes, bytearray)):
        response_sha = hashlib.sha256(response_body).hexdigest()
        try:
            decoded = json.loads(response_body.decode("utf-8"))
            usage = decoded.get("usage")
            raw_assistant = decoded["choices"][0]["message"]["content"]
        except Exception:
            raw_assistant = None

    header_index = text.find(FEEDBACK_SECTION_HEADER)
    return {
        "attempt": call["attempt"],
        "phase": call["phase"],
        "call_index": call["call_index"],
        "authorization_header_present": call["authorization_header_present"],
        "request_body_sha256": hashlib.sha256(body).hexdigest(),
        "request_body_chars": len(body),
        "image_wire_sha256": wire_sha,
        "wire_image_matches_file": wire_sha == scene["sha256"],
        "text_part": text,
        "text_is_prompt": text == _PROMPT,
        "text_starts_with_prompt": text.startswith(_PROMPT),
        "feedback_section_present": header_index >= 0,
        "feedback_after_instruction": header_index >= len(_PROMPT),
        "feedback_text": None
        if header_index < 0
        else text.partition(FEEDBACK_SECTION_HEADER + "\n")[2],
        "response_body_sha256": response_sha,
        "usage": usage,
        "raw_assistant_from_http": raw_assistant,
    }


def _response_record(response) -> dict:
    return {
        "protocol_version": response.protocol_version,
        "request_id": response.request_id,
        "host_kind": response.host_kind,
        "accepted": response.accepted,
        "submission_status": response.submission_status,
        "observation_status": response.observation_status,
        "execution_status": response.execution_status,
        "ok": response.ok,
        "output": response.output,
        "error": None if response.error is None else dict(response.error),
    }


def _decision_record(raw: str) -> dict:
    try:
        decision = parse_visual_decision(raw)
        directive = verify_visual_decision(
            decision, expected_identity="出口"
        )
        return {
            "refused": None,
            "target": decision.target_field,
            "identified_as": decision.identified_as,
            "visible": decision.visible,
            "position": decision.position,
            "direction": decision.direction,
            "verified_position": directive.position,
            "verified_direction": directive.direction,
        }
    except Exception as exc:
        return {"refused": f"{type(exc).__name__}: {exc}"}


def _emit(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


class _RecordingModel:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls = 0
        self.raws: list[str] = []

    def generate(self, observation: object, instruction: str) -> str:
        self.calls += 1
        raw = self._inner.generate(observation, instruction)
        self.raws.append(raw)
        return raw


class _CountingHostFactory:
    def __init__(self, host_exe: str) -> None:
        self._host_exe = host_exe
        self.calls = 0

    def __call__(self) -> HostClient:
        self.calls += 1
        return HostClient([self._host_exe])


def _gate():
    if os.environ.get(_GATE_ENV) != "1":
        pytest.skip(
            f"{_GATE_ENV} is not set to 1; real model inference is not authorized"
        )
    phase = os.environ.get(_PHASE_ENV, "").strip()
    if phase not in ("probe", "closed_loop"):
        pytest.fail(
            f"{_PHASE_ENV} must be 'probe' or 'closed_loop', got {phase!r}"
        )
    out = os.environ.get(_OUT_ENV, "").strip()
    if not out:
        pytest.fail(f"{_OUT_ENV} must name the evidence file")
    host = os.environ.get(_HOST_ENV, "").strip()
    if not host or not Path(host).is_file():
        pytest.fail(f"{_HOST_ENV} missing or not a file: {host!r}")
    host_sha = hashlib.sha256(Path(host).read_bytes()).hexdigest()
    if host_sha != _EXPECTED_HOST_SHA256:
        pytest.fail(
            "Host SHA-256 mismatch: "
            f"expected {_EXPECTED_HOST_SHA256}, got {host_sha}"
        )
    scene_name = os.environ.get(_SCENE_ENV, "exit_left").strip().lower()
    scene = _SCENES.get(scene_name)
    if scene is None:
        pytest.fail(f"unknown scene {scene_name!r}; expected {sorted(_SCENES)}")
    image_path = _IMAGES_DIR / scene["file"]
    if not image_path.is_file():
        pytest.fail(f"image missing: {image_path}")
    part = load_image_part(image_path)
    if part.sha256 != scene["sha256"]:
        pytest.fail(
            "image SHA-256 mismatch: "
            f"expected {scene['sha256']}, got {part.sha256}"
        )
    ledger = _PostLedger(Path(out).with_name("post_ledger.jsonl"))
    if ledger.entries >= _MAX_POSTS:
        pytest.fail(
            f"POST budget already exhausted: {ledger.entries}/{_MAX_POSTS}"
        )
    return (
        phase,
        Path(out),
        Path(host),
        host_sha,
        scene_name,
        scene,
        image_path,
        part,
        ledger,
    )


def _base_record(
    *,
    phase: str,
    scene_name: str,
    scene: dict,
    part,
    host: Path,
    host_sha: str,
    ledger: _PostLedger,
    backend: ZDTaichuServerBackend,
    factory: _CountingHostFactory,
) -> dict:
    return {
        "phase": phase,
        "scene": scene_name,
        "scene_history": scene["history"],
        "image": part.safe_description(),
        "prompt": _PROMPT,
        "prompt_chars": len(_PROMPT),
        "prompt_sha256": hashlib.sha256(_PROMPT.encode("utf-8")).hexdigest(),
        "pose": {
            "x": SIMULATED_TEST_POSE.x,
            "y": SIMULATED_TEST_POSE.y,
            "heading": SIMULATED_TEST_POSE.heading,
            "simulated": True,
            "note": "explicit test-only pose; not a measurement",
        },
        "host_exe": str(host),
        "host_sha256": host_sha,
        "model": {
            "endpoint": backend.endpoint,
            "temperature": 0.0,
            "max_new_tokens": 400,
            "enable_thinking": False,
            "timeout": 180.0,
        },
        "post_count_total": ledger.entries,
        "host_builds": factory.calls,
    }


def _run_probe(
    *,
    out: Path,
    scene_name: str,
    scene: dict,
    image_path: Path,
    part,
    host: Path,
    host_sha: str,
    ledger: _PostLedger,
) -> None:
    backend = ZDTaichuServerBackend(
        max_new_tokens=400, temperature=0.0, enable_thinking=False, timeout=180.0
    )
    model = VisualLoopModelClient(
        image_path=str(image_path),
        image_client=ServerImageModelClient(backend=backend),
    )
    factory = _CountingHostFactory(str(host))

    calls, original = _install_recorder(ledger, "probe")
    try:
        try:
            result = run_visual_parking_intent(
                model=model,
                observation=str(image_path),
                instruction=_PROMPT,
                expected_identity="出口",
                pose=SIMULATED_TEST_POSE,
                intent_id="nav11c-probe-intent",
                request_id="nav11c-probe-req",
                host_client_factory=factory,
            )
        except Exception as exc:
            record = _base_record(
                phase="probe",
                scene_name=scene_name,
                scene=scene,
                part=part,
                host=host,
                host_sha=host_sha,
                ledger=ledger,
                backend=backend,
                factory=factory,
            )
            record.update(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "calls": _safe_call_evidence(calls, part, scene),
                }
            )
            _emit(out, record)
            raise
    finally:
        server_client_module._OPENER.open = original

    info = _request_info(calls[0], part, scene) if calls else None
    record = _base_record(
        phase="probe",
        scene_name=scene_name,
        scene=scene,
        part=part,
        host=host,
        host_sha=host_sha,
        ledger=ledger,
        backend=backend,
        factory=factory,
    )
    record.update(
        {
            "status": "success",
            "calls": [info] if info else [],
            "raw_model_output": result.raw_model_output,
            "decision": _decision_record(result.raw_model_output),
            "intent_payload": result.intent.to_payload(),
            "request": result.request.to_object(),
            "response": _response_record(result.response),
            "stub_output": None
            if result.stub_output is None
            else dict(result.stub_output),
            "correlation": {
                "request_id_matches": result.response.request_id
                == result.request.request_id,
                "stub_intent_id_matches": result.stub_output is not None
                and result.stub_output["intent_id"] == result.intent.intent_id,
                "stub_target_matches": result.stub_output is not None
                and result.stub_output["target"] == result.intent.target.to_object(),
            },
        }
    )
    _emit(out, record)

    assert len(calls) == 1, "probe must make exactly one real model POST"
    assert factory.calls == 1, "probe must execute on the Host exactly once"
    assert info is not None
    assert info["wire_image_matches_file"] is True
    assert info["text_is_prompt"] is True
    assert info["feedback_section_present"] is False
    assert result.ok is True
    assert result.response.host_kind == HostKind.KERNEL
    assert result.response.request_id == result.request.request_id
    assert result.response.execution_status == "completed"
    assert result.stub_output is not None
    assert result.stub_output["status"] == "stub_completed"
    assert result.stub_output["intent_id"] == result.intent.intent_id
    assert record["decision"].get("refused") is None


def _safe_call_evidence(calls: list[dict], part, scene: dict) -> list[dict]:
    evidence = []
    for call in calls:
        try:
            evidence.append(_request_info(call, part, scene))
        except Exception as exc:
            evidence.append(
                {
                    "attempt": call.get("attempt"),
                    "phase": call.get("phase"),
                    "call_index": call.get("call_index"),
                    "authorization_header_present": call.get(
                        "authorization_header_present"
                    ),
                    "parse_error": f"{type(exc).__name__}: {exc}",
                }
            )
    return evidence


def _run_closed_loop(
    *,
    out: Path,
    scene_name: str,
    scene: dict,
    image_path: Path,
    part,
    host: Path,
    host_sha: str,
    ledger: _PostLedger,
) -> None:
    backend = ZDTaichuServerBackend(
        max_new_tokens=400, temperature=0.0, enable_thinking=False, timeout=180.0
    )
    model = VisualLoopModelClient(
        image_path=str(image_path),
        image_client=ServerImageModelClient(backend=backend),
    )
    recording_model = _RecordingModel(model)
    factory = _CountingHostFactory(str(host))
    requests = []

    def _recording_builder(intent: AgentIntent, *, request_id: str):
        request = build_request(intent, request_id=request_id)
        requests.append(request)
        return request

    calls, original = _install_recorder(ledger, "closed_loop")
    try:
        try:
            result = run_visual_parking_loop(
                model=recording_model,
                image_path=str(image_path),
                instruction=_PROMPT,
                expected_identity="出口",
                pose=SIMULATED_TEST_POSE,
                host_client_factory=factory,
                intent_id_factory=lambda index: f"nav11c-intent-{index}",
                request_id_factory=lambda index: f"nav11c-req-{index}",
                max_rounds=2,
                request_builder=_recording_builder,
            )
        except Exception as exc:
            record = _base_record(
                phase="closed_loop",
                scene_name=scene_name,
                scene=scene,
                part=part,
                host=host,
                host_sha=host_sha,
                ledger=ledger,
                backend=backend,
                factory=factory,
            )
            record.update(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "model_calls": recording_model.calls,
                    "raw_model_outputs": list(recording_model.raws),
                    "requests": [request.to_object() for request in requests],
                    "calls": _safe_call_evidence(calls, part, scene),
                }
            )
            _emit(out, record)
            raise
    finally:
        server_client_module._OPENER.open = original

    infos = [_request_info(call, part, scene) for call in calls]
    expected_feedback = (
        ResponseFeedbackEncoder().encode(result.responses[0]).text
        if result.responses
        else None
    )

    rounds = []
    for index, response in enumerate(result.responses):
        request = requests[index] if index < len(requests) else None
        intent = AgentIntent.from_payload(request.payload) if request else None
        stub_output = json.loads(response.output) if response.output else None
        info = infos[index] if index < len(infos) else None
        rounds.append(
            {
                "round_index": index,
                "request": None if request is None else request.to_object(),
                "intent_payload": None if intent is None else intent.to_payload(),
                "intent_id": None if intent is None else intent.intent_id,
                "raw_model_output": None
                if index >= len(recording_model.raws)
                else recording_model.raws[index],
                "decision": None
                if index >= len(recording_model.raws)
                else _decision_record(recording_model.raws[index]),
                "response": _response_record(response),
                "stub_output": stub_output,
                "call": info,
                "correlation": {
                    "request_id_matches": request is not None
                    and response.request_id == request.request_id,
                    "stub_intent_id_matches": intent is not None
                    and stub_output is not None
                    and stub_output.get("intent_id") == intent.intent_id,
                    "stub_target_matches": intent is not None
                    and stub_output is not None
                    and stub_output.get("target") == intent.target.to_object(),
                },
            }
        )

    record = _base_record(
        phase="closed_loop",
        scene_name=scene_name,
        scene=scene,
        part=part,
        host=host,
        host_sha=host_sha,
        ledger=ledger,
        backend=backend,
        factory=factory,
    )
    record.update(
        {
            "status": "success",
            "model_calls": recording_model.calls,
            "host_builds": factory.calls,
            "stop_reason": result.stop_reason,
            "calls": infos,
            "rounds": rounds,
            "feedback_expected_from_round_1": expected_feedback,
            "feedback_matches_round_2_request": (
                len(infos) >= 2
                and expected_feedback is not None
                and infos[1]["feedback_text"] == expected_feedback
            ),
        }
    )
    _emit(out, record)

    assert len(calls) == 2, "closed loop must make exactly two real model POSTs"
    assert recording_model.calls == 2
    assert factory.calls == 2
    assert len(requests) == 2
    assert len(result.responses) == 2
    assert result.stop_reason == LoopStopReason.MAX_ROUNDS
    assert infos[0]["text_is_prompt"] is True
    assert infos[0]["feedback_section_present"] is False
    assert infos[1]["text_starts_with_prompt"] is True
    assert infos[1]["feedback_section_present"] is True
    assert infos[1]["feedback_after_instruction"] is True
    assert expected_feedback is not None
    assert infos[1]["feedback_text"] == expected_feedback
    for index, response in enumerate(result.responses):
        assert response.request_id == f"nav11c-req-{index}"
        assert response.host_kind == HostKind.KERNEL
        assert response.ok is True
        assert response.execution_status == "completed"
        output = json.loads(response.output)
        assert output["status"] == "stub_completed"
        assert output["execution_mode"] == "simulation"
        assert output["intent_id"] == f"nav11c-intent-{index}"
        assert output["target"] == AgentIntent.from_payload(
            requests[index].payload
        ).target.to_object()


def test_nav11c_authorized_run() -> None:
    (
        phase,
        out,
        host,
        host_sha,
        scene_name,
        scene,
        image_path,
        part,
        ledger,
    ) = _gate()

    if phase == "probe":
        _run_probe(
            out=out,
            scene_name=scene_name,
            scene=scene,
            image_path=image_path,
            part=part,
            host=host,
            host_sha=host_sha,
            ledger=ledger,
        )
    else:
        _run_closed_loop(
            out=out,
            scene_name=scene_name,
            scene=scene,
            image_path=image_path,
            part=part,
            host=host,
            host_sha=host_sha,
            ledger=ledger,
        )
