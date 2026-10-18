"""NAV-10 integration: NAV-09 intent -> existing IPC -> real ``kernel_host``.

Two evidence levels, kept explicitly apart:

* **Mock-model + real Host (always runs when ``VLN_KERNEL_HOST_EXE`` is set).**
  The model is :class:`~vln.vlm.MockModelClient`, so the raw text is controlled;
  the three NAV-09 layers still produce the ``AgentIntent``. The request then
  goes through the existing ``build_request``, ``HostClient`` and the real
  Agent-Kernel-backed ``kernel_host`` (``parking.move`` stub). A passing test
  proves that a NAV-09 intent is executed by the real Runtime path; it does not
  prove real inference.
* **Real model + real Host (gated on ``VLN_ZDTAICHU_NAV_10=1``).** A native,
  unmagnified EXIT frame and the real local ZDTaichu service drive the same
  chain, and the raw answer, intent, request and correlated response are written
  to the path in ``VLN_ZDTAICHU_NAV_10_OUT``.

The pose is the labelled :data:`SIMULATED_TEST_POSE` - a test carrier for the
NAV-09 heading-delta convention, not a measured vehicle pose. A successful
``stub_completed`` response is not evidence that a vehicle moved.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_vln_nav_07b import _install_recorder, server_client_module  # noqa: E402

from vln.client import HostClient, build_request  # noqa: E402
from vln.intent import AgentIntent  # noqa: E402
from vln.ipc.envelope import (  # noqa: E402
    ErrorCode,
    HostKind,
    ObservationStatus,
    Request,
    SubmissionStatus,
)
from vln.nav import (  # noqa: E402
    DIRECTION_HEADING_DELTA,
    NavigationDecisionError,
    VehiclePose,
)
from vln.nav_execution import (  # noqa: E402
    NavigationExecutionError,
    run_visual_parking_intent,
)
from vln.observation import (  # noqa: E402
    CompositeObservationEncoder,
    ResponseFeedbackEncoder,
)
from vln.vlm import (  # noqa: E402
    MockModelClient,
    ModelCallError,
    PreparedObservation,
    Variant,
    ZDTaichuServerBackend,
    build_nav_prompt,
    load_image_part,
)
from vln.vlm.image_path_client import ServerImageModelClient  # noqa: E402

pytestmark = pytest.mark.integration

_EXE_ENV = "VLN_KERNEL_HOST_EXE"
_REAL_ENV = "VLN_ZDTAICHU_NAV_10"
_OUT_ENV = "VLN_ZDTAICHU_NAV_10_OUT"
_IMAGES_DIR = Path(__file__).resolve().parents[2] / "images"

_IMG01 = "17931c01d3fda4038c76944a334b3aef.png"
_IMG04 = "9a6908511ef1211af2ae8483c103bb63.png"

#: Explicitly simulated/test-only. This project has no localisation, odometry or
#: simulator, so no pose can be measured here; the caller must inject one.
SIMULATED_TEST_POSE = VehiclePose(x=12.5, y=-4.0, heading=0.25)

_BLOCK_TEMPLATE = (
    "第五步 输出结论块：\n"
    "Target: {target}\n"
    "Identified as: {identified}\n"
    "Visible: {visible}\n"
    "Relative position: {position}\n"
    "Next direction: {direction}\n"
    "Evidence: {evidence}\n"
)


def _block(
    *,
    target: str = "D50",
    identified: str = "D50",
    visible: str = "是",
    position: str = "LEFT",
    direction: str = "LEFT",
) -> str:
    return _BLOCK_TEMPLATE.format(
        target=target,
        identified=identified,
        visible=visible,
        position=position,
        direction=direction,
        evidence="地面白色编号 D50",
    )


@pytest.fixture()
def kernel_host_command() -> list[str]:
    exe = os.environ.get(_EXE_ENV)
    if not exe:
        pytest.skip(f"{_EXE_ENV} is not set; build kernel_host")
    path = Path(exe)
    if not path.is_file():
        pytest.skip(f"{_EXE_ENV} points to a missing file: {exe}")
    return [str(path)]


class _CountingFactory:
    def __init__(self, command: list[str]) -> None:
        self._command = command
        self.calls = 0

    def __call__(self) -> HostClient:
        self.calls += 1
        return HostClient(self._command)


def _run(
    *,
    model,
    factory: _CountingFactory,
    builder=build_request,
    expected_identity: str = "D50",
    intent_id: str = "nav10-intent-1",
    request_id: str = "nav10-req-1",
):
    return run_visual_parking_intent(
        model=model,
        observation="a parking-lot frame",
        instruction="park at D50",
        expected_identity=expected_identity,
        pose=SIMULATED_TEST_POSE,
        intent_id=intent_id,
        request_id=request_id,
        host_client_factory=factory,
        request_builder=builder,
    )


# ----------------------------------------------------------------------
# Mock model -> NAV-09 -> IPC -> real kernel_host -> parking.move
# ----------------------------------------------------------------------


def test_nav09_intent_executes_through_real_kernel(
    kernel_host_command: list[str],
) -> None:
    model = MockModelClient(_block())
    factory = _CountingFactory(kernel_host_command)

    result = _run(model=model, factory=factory)

    assert model.call_count == 1
    assert factory.calls == 1
    assert result.intent == AgentIntent.from_payload(result.intent.to_payload())

    # The request carries the NAV-09 intent, not a fixture and not a rewrite.
    assert result.request.request_id == "nav10-req-1"
    assert result.request.capability_id == result.intent.action == "parking.move"
    assert result.request.payload == result.intent.to_payload()

    # The response is the real C++ Host's answer.
    assert result.response.request_id == result.request.request_id
    assert result.response.host_kind == HostKind.KERNEL
    assert result.response.accepted is True
    assert result.response.submission_status == SubmissionStatus.COMPLETED
    assert result.response.observation_status == ObservationStatus.SUCCESS
    assert result.response.execution_status == "completed"
    assert result.response.error is None
    assert result.response.ok is True
    assert result.ok is True

    # The stub echoes this run's intent identity and target, under output v1.
    assert result.stub_output is not None
    assert set(result.stub_output) == {
        "output_version",
        "status",
        "execution_mode",
        "action",
        "intent_id",
        "target",
    }
    assert result.stub_output["output_version"] == "1"
    assert result.stub_output["status"] == "stub_completed"
    assert result.stub_output["execution_mode"] == "simulation"
    assert result.stub_output["action"] == "parking.move"
    assert result.stub_output["intent_id"] == result.intent.intent_id
    assert result.stub_output["target"] == result.intent.target.to_object()


def test_real_host_rejection_is_returned_as_failure_not_faked(
    kernel_host_command: list[str],
) -> None:
    """A real C++ Host rejection reaches the caller with no synthetic output."""

    def _unregistered_builder(intent: AgentIntent, *, request_id: str) -> Request:
        # The intent itself is untouched; only the capability is unregistered so
        # the rejection originates in the real Host/Kernel resolution path.
        return Request(
            request_id=request_id,
            capability_id="parking.stop",
            payload=intent.to_payload(),
        )

    factory = _CountingFactory(kernel_host_command)
    result = _run(
        model=MockModelClient(_block()),
        factory=factory,
        builder=_unregistered_builder,
    )

    assert factory.calls == 1
    assert result.request.payload == result.intent.to_payload()
    assert result.ok is False
    assert result.stub_output is None
    assert result.response.request_id == result.request.request_id
    assert result.response.host_kind == HostKind.KERNEL
    assert result.response.accepted is True
    assert result.response.submission_status == SubmissionStatus.FAILED
    assert result.response.observation_status == ObservationStatus.FAILURE
    assert result.response.execution_status is None
    assert result.response.output is None
    assert result.response.error is not None
    assert result.response.error["code"] == ErrorCode.CAPABILITY_NOT_FOUND


def test_the_real_host_response_is_encoded_by_the_existing_feedback_encoder(
    kernel_host_command: list[str],
) -> None:
    result = _run(
        model=MockModelClient(_block()),
        factory=_CountingFactory(kernel_host_command),
    )
    assert result.ok is True

    prepared = CompositeObservationEncoder().encode(result.response)
    assert isinstance(prepared, PreparedObservation)
    feedback = json.loads(prepared.text)

    assert feedback["request_id"] == result.request.request_id
    assert feedback["host_kind"] == "kernel"
    assert feedback["accepted"] is True
    assert feedback["submission_status"] == "completed"
    assert feedback["observation_status"] == "success"
    assert feedback["execution_status"] == "completed"
    assert feedback["ok"] is True
    assert feedback["truncated"] == {}

    output = json.loads(feedback["output"])
    assert output["intent_id"] == result.intent.intent_id
    assert output["status"] == "stub_completed"

    direct = ResponseFeedbackEncoder().encode(result.response)
    assert direct.text == prepared.text


# ----------------------------------------------------------------------
# Real model + real host (gated)
# ----------------------------------------------------------------------

_REAL_CASES = (
    {
        "id": "NAV10-EXIT-LEFT",
        "file": _IMG01,
        "target": "出口",
        "target_kind": "目标标识",
        "expected_direction": "LEFT",
        "intent_id": "nav-10-real-exit-left",
        "request_id": "nav-10-real-req-exit-left",
        "note": "08A U-EXIT-LEFT: native 出口/EXIT sign at frame x 0-7%, GT LEFT",
    },
    {
        "id": "NAV10-EXIT-AHEAD",
        "file": _IMG04,
        "target": "出口",
        "target_kind": "目标标识",
        "expected_direction": "STRAIGHT",
        "intent_id": "nav-10-real-exit-ahead",
        "request_id": "nav-10-real-req-exit-ahead",
        "note": "08A U-EXIT-AHEAD: native 89x31 px 出口 sign at x 51-55%, GT AHEAD",
    },
)


def _gate() -> None:
    if os.environ.get(_REAL_ENV) != "1":
        pytest.skip(
            f"{_REAL_ENV} is not set to 1; this sends a real multimodal request "
            "and executes on the real host"
        )
    if not _IMAGES_DIR.is_dir():
        pytest.skip(f"image directory not found: {_IMAGES_DIR}")


def _emit(record: dict) -> None:
    line = json.dumps(record, ensure_ascii=False)
    print("NAV10 " + line)
    path = os.environ.get(_OUT_ENV, "").strip()
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


class _RecordingModel:
    """Records the one raw model answer even when the chain later refuses it."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls = 0
        self.raw: str | None = None

    def generate(self, observation: object, instruction: str) -> str:
        self.calls += 1
        self.raw = self._inner.generate(observation, instruction)
        return self.raw


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


def _real_round(case: dict, kernel_host_command: list[str]) -> dict:
    image_path = _IMAGES_DIR / case["file"]
    if not image_path.is_file():
        pytest.skip(f"scene image missing: {image_path}")

    prompt = build_nav_prompt(
        Variant.TARGET_DIRECTION,
        target=case["target"],
        target_kind=case["target_kind"],
        require_identity=True,
        require_evidence=True,
    )
    part = load_image_part(image_path)
    backend = ZDTaichuServerBackend(
        max_new_tokens=400, temperature=0.0, enable_thinking=False, timeout=180.0
    )
    model = _RecordingModel(ServerImageModelClient(backend=backend))
    factory = _CountingFactory(kernel_host_command)

    calls, original = _install_recorder()
    try:
        try:
            result = run_visual_parking_intent(
                model=model,
                observation=str(image_path),
                instruction=prompt,
                expected_identity=case["target"],
                pose=SIMULATED_TEST_POSE,
                intent_id=case["intent_id"],
                request_id=case["request_id"],
                host_client_factory=factory,
            )
            outcome = {
                "kind": "executed",
                "intent_payload": result.intent.to_payload(),
                "intent_target": result.intent.target.to_object(),
                "direction": result.directive.direction,
                "position": result.directive.position,
                "identified_as": result.directive.identified_as,
                "request": result.request.to_object(),
                "response": _response_record(result.response),
                "stub_output": None
                if result.stub_output is None
                else dict(result.stub_output),
                "correlated": {
                    "request_id_matches": result.response.request_id
                    == result.request.request_id,
                    "stub_intent_id_matches": result.stub_output is not None
                    and result.stub_output["intent_id"] == result.intent.intent_id,
                    "stub_target_matches": result.stub_output is not None
                    and result.stub_output["target"] == result.intent.target.to_object(),
                },
            }
        except NavigationDecisionError as exc:
            outcome = {
                "kind": "decision-refused",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        except ModelCallError as exc:
            outcome = {
                "kind": "model-failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        except NavigationExecutionError as exc:
            outcome = {
                "kind": "host-response-invalid",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        except Exception as exc:  # record the evidence, then fail the assertion
            outcome = {
                "kind": "chain-failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
    finally:
        server_client_module._OPENER.open = original

    wire_ok = None
    usage = None
    if calls:
        payload = json.loads(calls[0]["body"].decode("utf-8"))
        (message,) = payload["messages"]
        encoded = message["content"][0]["image_url"]["url"].partition(";base64,")[2]
        wire_ok = hashlib.sha256(base64.b64decode(encoded)).hexdigest() == part.sha256
        response_body = calls[0].get("response_body")
        if response_body:
            try:
                usage = json.loads(response_body.decode("utf-8")).get("usage")
            except ValueError:
                usage = None

    host_path = Path(kernel_host_command[0])
    record = {
        "scene_id": case["id"],
        "note": case["note"],
        "target": case["target"],
        "target_kind": case["target_kind"],
        "expected_direction": case["expected_direction"],
        "temperature": 0.0,
        "max_new_tokens": 400,
        "prompt_chars": len(prompt),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "image": part.safe_description(),
        "wire_image_matches_file": wire_ok,
        "authorization_header_present": calls[0]["authorization"] is not None
        if calls
        else None,
        "usage": usage,
        "model_calls": model.calls,
        "host_builds": factory.calls,
        "host_exe": str(host_path),
        "host_sha256": hashlib.sha256(host_path.read_bytes()).hexdigest(),
        "pose": {
            "x": SIMULATED_TEST_POSE.x,
            "y": SIMULATED_TEST_POSE.y,
            "heading": SIMULATED_TEST_POSE.heading,
            "simulated": True,
            "note": "explicit caller-supplied test pose; not a measurement",
        },
        "raw_model_output": model.raw,
        "outcome": outcome,
    }
    _emit(record)
    return record


@pytest.mark.parametrize("case", _REAL_CASES, ids=[case["id"] for case in _REAL_CASES])
def test_real_model_to_real_host_stub(
    case: dict, kernel_host_command: list[str]
) -> None:
    _gate()
    record = _real_round(case, kernel_host_command)

    assert record["model_calls"] == 1, "one round must be exactly one model call"
    assert record["wire_image_matches_file"] is True, "the wire image was not the file"
    assert record["outcome"]["kind"] == "executed", record["outcome"]
    assert record["outcome"]["direction"] == case["expected_direction"]

    # The intent is the NAV-09 mapping of the recorded real answer.
    delta = DIRECTION_HEADING_DELTA[record["outcome"]["direction"]]
    expected_heading = (
        (SIMULATED_TEST_POSE.heading + delta + math.pi) % (2 * math.pi)
    ) - math.pi
    assert record["outcome"]["intent_target"]["x"] == SIMULATED_TEST_POSE.x
    assert record["outcome"]["intent_target"]["y"] == SIMULATED_TEST_POSE.y
    assert record["outcome"]["intent_target"]["heading"] == pytest.approx(expected_heading)

    # The actual Host answer, correlated to this exact intent/request.
    response = record["outcome"]["response"]
    assert record["host_builds"] == 1
    assert response["host_kind"] == "kernel"
    assert response["accepted"] is True
    assert response["submission_status"] == "completed"
    assert response["observation_status"] == "success"
    assert response["execution_status"] == "completed"
    assert response["ok"] is True
    assert response["request_id"] == case["request_id"]
    assert record["outcome"]["correlated"] == {
        "request_id_matches": True,
        "stub_intent_id_matches": True,
        "stub_target_matches": True,
    }
    assert record["outcome"]["stub_output"]["status"] == "stub_completed"
    assert record["outcome"]["stub_output"]["execution_mode"] == "simulation"
