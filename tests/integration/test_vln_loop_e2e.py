"""Cross-process multi-round E2E: real loop + real adapter + real kernel_host.

The inference backend is a fake (no model is loaded). Everything else is real:
the composition in :mod:`vln.app`, the loop in :mod:`vln.pipeline`, the
``ZDTaichuModelClient`` adapter, the ``CompositeObservationEncoder``, the IPC
``HostClient`` and a real ``kernel_host`` subprocess (Agent-Kernel Runtime plus
the SIMULATION-ONLY ``parking.move`` stub).

A passing run proves the *simulated* chain only. It is NOT evidence of real
ZDTaichu5.0-9B inference, a real vision/Processor path, real vehicle execution
or production readiness.

The host executable is located through ``VLN_KERNEL_HOST_EXE`` (the same
mechanism as ``tests/integration/test_kernel_host.py``); when it is absent the
tests skip. Run the dedicated E2E with the variable set so it actually executes:

    VLN_KERNEL_HOST_EXE=<build>/kernel_host \\
      python -m pytest tests/integration/test_vln_loop_e2e.py -v
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from vln.app import build_simulated_loop
from vln.client import HostClient
from vln.ipc.envelope import HostKind, Request, Response
from vln.observation import CompositeObservationEncoder, ResponseFeedbackEncoder
from vln.pipeline import LoopStopReason
from vln.vlm import PreparedObservation, ZDTaichuModelClient

_EXE_ENV = "VLN_KERNEL_HOST_EXE"


def _intent_text(*, x: float, intent_id: str = "intent-e2e") -> str:
    return json.dumps(
        {
            "contract_version": "1",
            "intent_id": intent_id,
            "action": "parking.move",
            "target": {"x": x, "y": -2.25, "heading": 0.5},
        },
        separators=(",", ":"),
    )


# ----------------------------------------------------------------------
# Host location and test doubles (the backend is a fake; the host is real)
# ----------------------------------------------------------------------


@pytest.fixture
def kernel_host_command() -> list[str]:
    exe = os.environ.get(_EXE_ENV)
    if not exe:
        pytest.skip(f"{_EXE_ENV} is not set; build kernel_host (see runtime_host/README.md)")
    if not Path(exe).is_file():
        pytest.skip(f"{_EXE_ENV} points to a missing file: {exe}")
    return [exe]


class _CountingHostFactory:
    """A factory that builds a real :class:`HostClient` and counts how often."""

    def __init__(self, command: list[str]) -> None:
        self._command = command
        self.calls = 0

    def __call__(self) -> HostClient:
        self.calls += 1
        return HostClient(self._command)


class _FeedbackDrivenBackend:
    """Fake InferenceBackend whose later rounds read the encoded feedback.

    Round 0 returns an intent targeting ``start_x``. Later rounds parse the
    feedback text, read the previous round's echoed target x, and continue to
    ``+1`` until ``done_x`` (then empty text = the model's explicit stop).
    """

    def __init__(self, *, start_x: float = 1.0, done_x: float = 2.0) -> None:
        self._start_x = start_x
        self._done_x = done_x
        self.observations: list[object] = []

    def generate(self, observation: object, instruction: str) -> str:
        self.observations.append(observation)
        if len(self.observations) == 1:
            return _intent_text(x=self._start_x)
        last_x = json.loads(json.loads(observation.text)["output"])["target"]["x"]
        if last_x >= self._done_x:
            return ""
        return _intent_text(x=last_x + 1.0)


class _ConstantBackend:
    """Fake InferenceBackend that always returns the same raw text."""

    def __init__(self, text: str) -> None:
        self.text = text

    def generate(self, observation: object, instruction: str) -> str:
        return self.text


# ----------------------------------------------------------------------
# A + B: the entry wires the composite encoder and runs >=2 real rounds
# ----------------------------------------------------------------------


def test_app_entry_injects_composite_encoder_and_drives_two_real_rounds(
    kernel_host_command: list[str],
) -> None:
    backend = _FeedbackDrivenBackend(start_x=1.0, done_x=2.0)
    factory = _CountingHostFactory(kernel_host_command)

    app = build_simulated_loop(
        backend_factory=lambda: backend,
        host_client_factory=factory,
        instruction="park at the target",
    )

    # A. the APPLICATION (not the test) selected the composite encoder.
    assert isinstance(app.model, ZDTaichuModelClient)
    assert isinstance(app.encoder, CompositeObservationEncoder)
    assert app.model.encoder is app.encoder

    result = app.run("a parking-lot scene")

    # B. >=2 real cross-process rounds against the kernel host.
    assert result.stop_reason == LoopStopReason.MODEL_STOP
    assert len(result.responses) == 2
    assert factory.calls == 2  # one host process per executed round
    for response in result.responses:
        assert response.host_kind == HostKind.KERNEL  # real Kernel host, not stub
        assert response.ok is True
        output = json.loads(response.output)
        assert output["status"] == "stub_completed"
        assert output["execution_mode"] == "simulation"

    # Round 2's model input is the ENCODED feedback of the REAL round-1 Response
    # - not the Response object, and not merely "the model was called again".
    assert len(backend.observations) == 3  # 2 executed rounds + 1 stop round
    first, second, third = backend.observations
    assert isinstance(first, PreparedObservation)
    assert first.text == "a parking-lot scene"  # round 0 keeps str behaviour
    assert isinstance(second, PreparedObservation)
    assert not isinstance(second, Response)
    assert second.text == ResponseFeedbackEncoder().encode(result.responses[0]).text
    feedback = json.loads(second.text)
    assert feedback["ok"] is True
    assert json.loads(feedback["output"])["target"]["x"] == 1.0
    assert third.text == ResponseFeedbackEncoder().encode(result.responses[1]).text


# ----------------------------------------------------------------------
# C: fail-closed - invalid model output never reaches the host
# ----------------------------------------------------------------------


def test_invalid_model_output_never_reaches_the_host(
    kernel_host_command: list[str],
) -> None:
    factory = _CountingHostFactory(kernel_host_command)
    app = build_simulated_loop(
        backend_factory=lambda: _ConstantBackend("{not a valid intent"),
        host_client_factory=factory,
        instruction="park",
    )

    result = app.run("scene")

    assert result.stop_reason == LoopStopReason.INVALID_OUTPUT
    assert result.responses == ()
    # No HostClient was constructed, so no host process started and no request
    # was ever submitted.
    assert factory.calls == 0


# ----------------------------------------------------------------------
# D: a genuine cross-process execution failure stops the loop
# ----------------------------------------------------------------------


def test_execution_failure_propagates_from_the_real_host(
    kernel_host_command: list[str],
) -> None:
    # The pipeline's own builder always targets the registered ``parking.move``
    # capability, so an injected builder is used to reach a genuine cross-process
    # host failure (same technique as tests/integration/test_kernel_host.py).
    def _unregistered_capability(intent, *, request_id):
        return Request(
            request_id=request_id,
            capability_id="parking.move.unregistered",
            payload=intent.to_payload(),
        )

    factory = _CountingHostFactory(kernel_host_command)
    app = build_simulated_loop(
        backend_factory=lambda: _ConstantBackend(_intent_text(x=1.0)),
        host_client_factory=factory,
        instruction="park",
        request_builder=_unregistered_capability,
    )

    result = app.run("scene")

    assert result.stop_reason == LoopStopReason.EXECUTION_FAILED
    assert len(result.responses) == 1
    assert result.responses[0].host_kind == HostKind.KERNEL
    assert result.responses[0].ok is False  # a real Host failure, not fabricated
    assert factory.calls == 1  # exactly one attempt, then stop: no recovery
