"""NAV-15 opt-in real-model, two-round visual navigation experiment.

This test is skipped unless explicitly enabled. It requires:

* ``VLN_NAV15_REAL=1``
* the already-running local ZDTaichu server at ``127.0.0.1:8100``
* ``VLN_KERNEL_HOST_EXE`` pointing at an existing ``kernel_host`` binary

It does **not** start/stop the server, download a model, install a dependency,
or rebuild the Host. It sends real image requests to the local model and uses
the existing simulation-only ``parking.move`` stub for execution.

The raw JSONL is written before assertions so a failed model output still leaves
verifiable evidence. ``VLN_NAV15_RAW`` may override the output path.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

import pytest
from PIL import Image

from vln.client import HostClient
from vln.ipc.envelope import HostKind
from vln.nav import VehiclePose
from vln.pipeline import LoopStopReason
from vln.stm import NavigationTaskMemory, RoundOutcome
from vln.visual_loop import VisualLoopModelClient, run_visual_parking_loop
from vln.vlm.image_path_client import (
    FEEDBACK_SECTION_HEADER,
    STM_SECTION_HEADER,
    ServerImageModelClient,
)
from vln.vlm.nav_prompt import Variant, build_nav_prompt
from vln.vlm.server_client import ZDTaichuServerBackend

pytestmark = pytest.mark.integration

_REAL_ENV = "VLN_NAV15_REAL"
_HOST_ENV = "VLN_KERNEL_HOST_EXE"
_RAW_ENV = "VLN_NAV15_RAW"
_HEALTH_URL = "http://127.0.0.1:8100/health"

_REPO = Path(__file__).resolve().parents[2]
_IMAGE_A = _REPO / "images" / "17931c01d3fda4038c76944a334b3aef.png"  # IMG-01
_IMAGE_B = _REPO / "images" / "9a6908511ef1211af2ae8483c103bb63.png"  # IMG-04

# Explicitly simulated/test-only; no localisation exists in this project.
_POSE = VehiclePose(x=12.5, y=-4.0, heading=0.25)
_TASK_ID = "nav15-real-two-round-20261017"
_EXPECTED_IDENTITY = "出口"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _health() -> dict:
    with urlopen(_HEALTH_URL, timeout=5) as response:  # noqa: S310 - fixed loopback
        return json.loads(response.read().decode("utf-8"))


class _RecordingBackend(ZDTaichuServerBackend):
    """The real server backend, recording the actual image + final text + raw output."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.calls: list[dict] = []

    def generate_image(self, image_path: str, instruction: str) -> str:
        started_at = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        try:
            raw = super().generate_image(image_path, instruction)
        except Exception as exc:
            self.calls.append(
                {
                    "image_path": str(image_path),
                    "instruction": instruction,
                    "raw_model_output": None,
                    "error": f"{type(exc).__name__}: {exc}",
                    "started_at_utc": started_at,
                    "duration_seconds": round(time.perf_counter() - started, 3),
                }
            )
            raise
        self.calls.append(
            {
                "image_path": str(image_path),
                "instruction": instruction,
                "raw_model_output": raw,
                "error": None,
                "started_at_utc": started_at,
                "duration_seconds": round(time.perf_counter() - started, 3),
            }
        )
        return raw


def _extract_sections(input_text: str) -> tuple[str | None, str | None]:
    if FEEDBACK_SECTION_HEADER not in input_text:
        return None, None
    after_feedback = input_text.split(FEEDBACK_SECTION_HEADER + "\n", 1)[1]
    if STM_SECTION_HEADER in after_feedback:
        feedback, stm = after_feedback.split(STM_SECTION_HEADER + "\n", 1)
        return feedback.strip(), stm.strip()
    return after_feedback.strip(), None


def _raw_path() -> Path:
    configured = os.environ.get(_RAW_ENV)
    path = Path(configured) if configured else _REPO / "docs" / "M1-VLN-NAV-15-RAW.jsonl"
    if path.exists():
        path = path.with_name(f"{path.stem}-rerun{path.suffix}")
    return path


def test_two_real_rounds_use_a_then_b_feedback_and_stm() -> None:
    if os.environ.get(_REAL_ENV) != "1":
        pytest.skip(f"{_REAL_ENV} is not set to 1")
    host_exe = os.environ.get(_HOST_ENV)
    if not host_exe:
        pytest.skip(f"{_HOST_ENV} is not set")
    if not Path(host_exe).is_file():
        pytest.skip(f"{_HOST_ENV} points to a missing file: {host_exe}")
    if not _IMAGE_A.is_file() or not _IMAGE_B.is_file():
        pytest.skip("NAV-15 experiment images are missing")

    health = _health()
    prompt = build_nav_prompt(
        Variant.TARGET_DIRECTION,
        target=_EXPECTED_IDENTITY,
        intent_id="nav15-real",
        target_kind="目标标识",
        require_identity=True,
        require_evidence=False,
    )
    backend = _RecordingBackend(
        max_new_tokens=400,
        timeout=180.0,
        temperature=0.0,
        enable_thinking=False,
    )
    model = VisualLoopModelClient(
        image_path=str(_IMAGE_A),
        image_paths=[str(_IMAGE_A), str(_IMAGE_B)],
        image_client=ServerImageModelClient(backend=backend),
    )
    memory = NavigationTaskMemory(
        task_id=_TASK_ID,
        max_entries=4,
        max_facts=12,
        max_context_chars=2000,
    )

    result = run_visual_parking_loop(
        model=model,
        image_path=str(_IMAGE_A),
        image_paths=[str(_IMAGE_A), str(_IMAGE_B)],
        instruction=prompt,
        expected_identity=_EXPECTED_IDENTITY,
        pose=_POSE,
        host_client_factory=lambda: HostClient([host_exe]),
        intent_id_factory=lambda index: f"nav15-real-intent-{index}",
        request_id_factory=lambda index: f"nav15-real-req-{index}",
        max_rounds=2,
        memory=memory,
    )

    model_info = {
        "id": health.get("model"),
        "model_path": health.get("model_path"),
        "revision": None,
        "revision_source": "not exposed by /health or /v1/models",
        "device": health.get("device"),
        "dtype": health.get("dtype"),
        "endpoint": "http://127.0.0.1:8100/v1/chat/completions",
        "client": "ZDTaichuServerBackend.generate_image (data: URI)",
        "temperature": 0.0,
        "enable_thinking": False,
        "max_new_tokens": 400,
        "timeout_seconds": 180.0,
        "server_started_by_this_test": False,
    }

    records: list[dict] = []
    for round_index, call in enumerate(backend.calls):
        memory_record = (
            memory.records[round_index] if round_index < len(memory.records) else None
        )
        response = memory_record.response if memory_record is not None else None
        feedback_text, stm_text = _extract_sections(call["instruction"])
        image_path = Path(call["image_path"])
        try:
            with Image.open(image_path) as image:
                image_size = list(image.size)
        except Exception:
            image_size = None

        parse_ok = bool(
            memory_record is not None
            and memory_record.visual_decision is not None
            and memory_record.directive is not None
        )
        records.append(
            {
                "event": "round",
                "task_id": memory.task_id,
                "round_index": round_index,
                "image_path": str(image_path),
                "image_name": image_path.name,
                "image_sha256": _sha256_file(image_path) if image_path.is_file() else None,
                "image_size": image_size,
                "instruction": prompt,
                "instruction_sha256": _sha256_text(prompt),
                "model": model_info,
                "model_input_text": call["instruction"],
                "model_input_sha256": _sha256_text(call["instruction"]),
                "input_has_feedback": feedback_text is not None,
                "input_has_stm": stm_text is not None,
                "feedback_text": feedback_text,
                "stm_context": stm_text,
                "raw_model_output": call["raw_model_output"],
                "raw_output_sha256": (
                    _sha256_text(call["raw_model_output"])
                    if isinstance(call["raw_model_output"], str)
                    else None
                ),
                "started_at_utc": call["started_at_utc"],
                "duration_seconds": call["duration_seconds"],
                "parse": {
                    "ok": parse_ok,
                    "error": None if parse_ok else (
                        memory_record.error
                        if memory_record is not None
                        else "no memory record for this model call"
                    ),
                    "decision": (
                        asdict(memory_record.visual_decision)
                        if memory_record is not None
                        and memory_record.visual_decision is not None
                        else None
                    ),
                    "directive": (
                        asdict(memory_record.directive)
                        if memory_record is not None
                        and memory_record.directive is not None
                        else None
                    ),
                },
                "intent": (
                    {
                        "intent_id": memory_record.intent_id,
                        "action": memory_record.action,
                        "target": memory_record.target,
                    }
                    if memory_record is not None
                    else None
                ),
                "intent_id": (
                    memory_record.intent_id if memory_record is not None else None
                ),
                "request_id": (
                    memory_record.request_id if memory_record is not None else None
                ),
                "execution": {
                    "outcome": (
                        memory_record.outcome if memory_record is not None else None
                    ),
                    "response": asdict(response) if response is not None else None,
                },
                "stm": {
                    "enabled": True,
                    "task_id": memory.task_id,
                    "records_before_round": round_index,
                    "context_injected_this_round": stm_text is not None,
                    "context_sha256": (
                        _sha256_text(stm_text) if stm_text is not None else None
                    ),
                },
            }
        )

    records.append(
        {
            "event": "task_summary",
            "task_id": memory.task_id,
            "stop_reason": result.stop_reason,
            "memory_stop_reason": memory.stop_reason,
            "rounds_executed": len(result.responses),
            "model_calls": len(backend.calls),
            "model": model_info,
            "responses": [asdict(response) for response in result.responses],
            "stm_facts": [asdict(fact) for fact in memory.facts],
            "stm_unresolved": [asdict(item) for item in memory.unresolved],
            "physical_arrival": "unknown",
            "note": (
                "parking.move is simulation-only; stub_completed does not mean "
                "vehicle movement, arrival or parking success"
            ),
        }
    )

    raw_path = _raw_path()
    raw_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )
    print(f"NAV15_RAW_PATH={raw_path}")

    # The experiment must have made exactly two real model calls, with image A
    # then image B, and no accidental reuse.
    assert len(backend.calls) == 2
    assert [Path(call["image_path"]).name for call in backend.calls] == [
        _IMAGE_A.name,
        _IMAGE_B.name,
    ]
    assert FEEDBACK_SECTION_HEADER not in backend.calls[0]["instruction"]
    assert STM_SECTION_HEADER not in backend.calls[0]["instruction"]
    assert FEEDBACK_SECTION_HEADER in backend.calls[1]["instruction"]
    assert STM_SECTION_HEADER in backend.calls[1]["instruction"]

    # Both real model outputs parsed, mapped to an AgentIntent, and executed via
    # the existing Host/Kernel path.
    assert result.stop_reason == LoopStopReason.MAX_ROUNDS
    assert len(result.responses) == 2
    assert len(memory.records) == 2
    assert [record.task_id for record in memory.records] == [_TASK_ID, _TASK_ID]
    assert [record.round_index for record in memory.records] == [0, 1]
    assert [record.outcome for record in memory.records] == [
        RoundOutcome.SOFTWARE_SUCCEEDED,
        RoundOutcome.SOFTWARE_SUCCEEDED,
    ]
    for index, record in enumerate(memory.records):
        assert record.visual_decision is not None
        assert record.directive is not None
        assert record.action == "parking.move"
        assert record.request_id == f"nav15-real-req-{index}"
        assert record.response is result.responses[index]
        assert record.response.request_id == record.request_id
        assert record.response.host_kind == HostKind.KERNEL
        assert record.response.ok is True
        assert record.response.execution_status == "completed"
        assert record.response.output is not None
        assert json.loads(record.response.output)["status"] == "stub_completed"

    assert memory.active_fact("arrived") is None
    assert memory.active_fact("parked") is None
    assert memory.active_fact("physical_arrival") is None
    assert memory.active_fact("target_identity") is not None
