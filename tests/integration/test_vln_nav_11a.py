"""NAV-11A integration: image+feedback model -> NAV-09/NAV-10 -> real Host.

The image backend is a test double (it records the image path/instruction and
performs no HTTP), so this is **not** evidence of real inference or real image
transport. Everything after it is real: the existing multi-round loop, the
NAV-09 three layers, the existing request builder, HostClient and the real
Agent-Kernel-backed ``kernel_host`` with the simulation-only ``parking.move``
stub. The second round's model input contains the first round's actual Host
Response, encoded by the existing feedback encoder.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from vln.client import HostClient, build_request
from vln.intent import AgentIntent
from vln.ipc.envelope import (
    ErrorCode,
    HostKind,
    ObservationStatus,
    Request,
    SubmissionStatus,
)
from vln.nav import VehiclePose
from vln.observation import ResponseFeedbackEncoder
from vln.pipeline import LoopStopReason
from vln.visual_loop import VisualLoopModelClient, run_visual_parking_loop
from vln.vlm.image_path_client import (
    FEEDBACK_SECTION_HEADER,
    ServerImageModelClient,
)

pytestmark = pytest.mark.integration

_EXE_ENV = "VLN_KERNEL_HOST_EXE"

#: Explicitly simulated/test-only; there is no localisation in this project.
SIMULATED_TEST_POSE = VehiclePose(x=12.5, y=-4.0, heading=0.25)

_IMAGE_PATH = "fake-frame.png"  # the fake backend never reads it
_INSTRUCTION = "park at D50"

_BLOCK = (
    "第五步 输出结论块：\n"
    "Target: D50\n"
    "Identified as: D50\n"
    "Visible: 是\n"
    "Relative position: LEFT\n"
    "Next direction: LEFT\n"
    "Evidence: 地面白色编号 D50\n"
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


class _FakeImageBackend:
    """Records the image entry calls; sends no HTTP and reads no file."""

    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.calls: list[tuple[str, str]] = []

    def generate_image(self, image_path: str, instruction: str) -> str:
        self.calls.append((image_path, instruction))
        if not self._outputs:
            return ""
        if len(self._outputs) == 1:
            return self._outputs[0]
        return self._outputs.pop(0)


class _CountingFactory:
    def __init__(self, command: list[str]) -> None:
        self._command = command
        self.calls = 0

    def __call__(self) -> HostClient:
        self.calls += 1
        return HostClient(self._command)


def test_two_visual_rounds_use_real_kernel_and_real_feedback(
    kernel_host_command: list[str],
) -> None:
    backend = _FakeImageBackend([_BLOCK, _BLOCK, ""])
    model = VisualLoopModelClient(
        image_path=_IMAGE_PATH,
        image_client=ServerImageModelClient(backend=backend),
    )
    factory = _CountingFactory(kernel_host_command)
    requests = []

    def _recording_builder(intent: AgentIntent, *, request_id: str):
        request = build_request(intent, request_id=request_id)
        requests.append(request)
        return request

    result = run_visual_parking_loop(
        model=model,
        image_path=_IMAGE_PATH,
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=factory,
        intent_id_factory=lambda index: f"nav11a-intent-{index}",
        request_id_factory=lambda index: f"nav11a-req-{index}",
        max_rounds=3,
        request_builder=_recording_builder,
    )

    # Two executed rounds, then the model's explicit empty stop.
    assert result.stop_reason == LoopStopReason.MODEL_STOP
    assert len(result.responses) == 2
    assert factory.calls == 2
    assert len(requests) == 2
    assert len(backend.calls) == 3

    # Every round reached the real Kernel host and returned real response fields.
    for index, response in enumerate(result.responses):
        assert response.request_id == f"nav11a-req-{index}"
        assert response.host_kind == HostKind.KERNEL
        assert response.accepted is True
        assert response.submission_status == SubmissionStatus.COMPLETED
        assert response.observation_status == ObservationStatus.SUCCESS
        assert response.execution_status == "completed"
        assert response.ok is True
        output = json.loads(response.output)
        assert output["status"] == "stub_completed"
        assert output["execution_mode"] == "simulation"
        assert output["intent_id"] == f"nav11a-intent-{index}"

    # The requests are the NAV-09-mapped intents on the existing IPC route.
    for index, request in enumerate(requests):
        intent = AgentIntent.from_payload(request.payload)
        assert request.request_id == f"nav11a-req-{index}"
        assert intent.intent_id == f"nav11a-intent-{index}"
        assert request.capability_id == intent.action == "parking.move"
        assert intent.target.x == SIMULATED_TEST_POSE.x
        assert intent.target.y == SIMULATED_TEST_POSE.y
        assert intent.target.heading != SIMULATED_TEST_POSE.heading  # LEFT

    # Round 0 has no feedback; round 1 carries the first real Response.
    assert backend.calls[0] == (_IMAGE_PATH, _INSTRUCTION)
    assert FEEDBACK_SECTION_HEADER not in backend.calls[0][1]
    for index, response in enumerate(result.responses, start=1):
        image_path, combined = backend.calls[index]
        assert image_path == _IMAGE_PATH
        assert combined.startswith(_INSTRUCTION)
        assert FEEDBACK_SECTION_HEADER in combined
        assert _IMAGE_PATH not in combined
        assert ResponseFeedbackEncoder().encode(response).text in combined
        assert json.loads(combined.partition(FEEDBACK_SECTION_HEADER + "\n")[2])[
            "request_id"
        ] == f"nav11a-req-{index - 1}"


def test_a_real_host_failure_stops_the_visual_loop_without_a_second_round(
    kernel_host_command: list[str],
) -> None:
    backend = _FakeImageBackend([_BLOCK])
    model = VisualLoopModelClient(
        image_path=_IMAGE_PATH,
        image_client=ServerImageModelClient(backend=backend),
    )
    factory = _CountingFactory(kernel_host_command)

    def _unregistered_builder(intent: AgentIntent, *, request_id: str) -> Request:
        # The intent is untouched; only the capability is unregistered, so the
        # failure originates in the real Host/Kernel resolution path.
        return Request(
            request_id=request_id,
            capability_id="parking.stop",
            payload=intent.to_payload(),
        )

    result = run_visual_parking_loop(
        model=model,
        image_path=_IMAGE_PATH,
        instruction=_INSTRUCTION,
        expected_identity="D50",
        pose=SIMULATED_TEST_POSE,
        host_client_factory=factory,
        intent_id_factory=lambda index: f"nav11a-intent-{index}",
        request_id_factory=lambda index: f"nav11a-req-{index}",
        max_rounds=3,
        request_builder=_unregistered_builder,
    )

    assert result.stop_reason == LoopStopReason.EXECUTION_FAILED
    assert result.stopped_by_model is False
    assert len(result.responses) == 1
    assert result.responses[0].host_kind == HostKind.KERNEL
    assert result.responses[0].ok is False
    assert result.responses[0].output is None
    assert result.responses[0].error is not None
    assert result.responses[0].error["code"] == ErrorCode.CAPABILITY_NOT_FOUND
    # One attempt, then stop: no second model call and no second Host process.
    assert factory.calls == 1
    assert backend.calls == [(_IMAGE_PATH, _INSTRUCTION)]
