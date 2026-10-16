"""End-to-end tests against the REAL Agent-Kernel-backed C++ host.

These tests spawn the compiled ``kernel_host`` executable and drive it with
the same Python :class:`~vln.client.HostClient` used for the stub host. They
exercise three distinct layers, and each test says which one it checks:

* **protocol** - envelope validation shared with ``vln.ipc.envelope``;
* **host process** - NDJSON framing, stdout/stderr separation, lifecycle;
* **Kernel execution** - a real ``ak::runtime::Runtime`` running ``test.echo``
  through ``IssueRuntimeExecutionAuthority`` -> ``Port().Submit/Observe``.

The host binary lives outside this repository in a build directory. Point the
environment variable ``VLN_KERNEL_HOST_EXE`` at it to run these tests; when it
is unset or missing the tests skip rather than fail, because the build is an
out-of-repo, machine-specific artifact.

These tests prove only the first real Kernel integration loops (``test.echo``
and the simulation-only ``parking.move`` stub). They are NOT evidence that the
K0 gate is closed, that navigation works, that ZDTaichu5.0-9B is integrated,
or that any production capability is safe.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from vln.client import HostClient
from vln.intent import AgentIntent, AgentIntentError, Target
from vln.ipc import envelope
from vln.ipc.envelope import (
    ErrorCode,
    HostKind,
    ObservationStatus,
    Request,
    SubmissionStatus,
)
from vln.pipeline import run_parking_intent
from vln.vlm import MockModelClient

pytestmark = pytest.mark.integration

_EXE_ENV = "VLN_KERNEL_HOST_EXE"


def _kernel_host_command() -> list[str]:
    exe = os.environ.get(_EXE_ENV)
    if not exe:
        pytest.skip(
            f"{_EXE_ENV} is not set; build kernel_host (see runtime_host/README.md)"
        )
    path = Path(exe)
    if not path.is_file():
        pytest.skip(f"{_EXE_ENV} points to a missing file: {exe}")
    return [str(path)]


@pytest.fixture()
def client():
    client = HostClient(_kernel_host_command())
    client.start()
    try:
        yield client
    finally:
        client.close()


def _wait_for(predicate, timeout: float = 5.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# -- Kernel execution -------------------------------------------------------


def test_test_echo_runs_through_real_kernel(client: HostClient) -> None:
    """Kernel execution: test.echo goes through the real Runtime path."""

    response = client.send(
        Request(request_id="k-echo-1", capability_id="test.echo", payload="hello")
    )
    assert response.request_id == "k-echo-1"
    assert response.host_kind == HostKind.KERNEL
    assert response.accepted is True
    assert response.submission_status == SubmissionStatus.COMPLETED
    assert response.observation_status == ObservationStatus.SUCCESS
    # A real ExecutionResult exists, so execution_status is populated and is
    # NOT the null the stub host reports.
    assert response.execution_status == "completed"
    assert response.output == "[kernel-echo]:hello"
    assert response.error is None
    assert response.ok is True


def test_sequential_requests_each_get_an_independent_runtime(
    client: HostClient,
) -> None:
    """Kernel execution: one Runtime per request, ids echoed exactly."""

    payloads = ["alpha", "beta", "gamma"]
    for index, payload in enumerate(payloads):
        request_id = f"k-seq-{index}"
        response = client.send(
            Request(
                request_id=request_id,
                capability_id="test.echo",
                payload=payload,
            )
        )
        assert response.request_id == request_id
        assert response.host_kind == HostKind.KERNEL
        assert response.execution_status == "completed"
        assert response.output == f"[kernel-echo]:{payload}"


def test_unknown_capability_fails_without_fake_success(client: HostClient) -> None:
    """Kernel execution: an unregistered capability is a real failure."""

    response = client.send(
        Request(request_id="k-unknown-1", capability_id="nav.go", payload="p")
    )
    assert response.request_id == "k-unknown-1"
    assert response.host_kind == HostKind.KERNEL
    # The submission was accepted by the port but the Kernel could not resolve
    # the capability: accepted != executed successfully.
    assert response.accepted is True
    assert response.submission_status == SubmissionStatus.FAILED
    assert response.observation_status == ObservationStatus.FAILURE
    # No ExecutionResult exists for a rejected resolution.
    assert response.execution_status is None
    assert response.output is None
    assert response.ok is False
    assert response.error is not None
    assert response.error["code"] == ErrorCode.CAPABILITY_NOT_FOUND


def test_blank_payload_is_rejected_not_executed(client: HostClient) -> None:
    """Protocol: a blank payload is rejected before any execution."""

    response = client.request_line(
        '{"protocol_version":"1","request_id":"k-blank-1","type":"submit",'
        '"capability_id":"test.echo","payload":""}'
    )
    assert response.host_kind == HostKind.KERNEL
    assert response.accepted is False
    assert response.submission_status is None
    assert response.execution_status is None
    assert response.output is None
    assert response.ok is False
    assert response.error is not None
    assert response.error["code"] == ErrorCode.INVALID_FIELD


def test_request_id_is_echoed_exactly(client: HostClient) -> None:
    """Protocol: the host echoes the exact request_id (basis for send())."""

    response = client.request_line(
        '{"protocol_version":"1","request_id":"k-exact-42","type":"submit",'
        '"capability_id":"test.echo","payload":"x"}'
    )
    assert response.request_id == "k-exact-42"


# -- Protocol rejection (no execution path) ---------------------------------


def test_malformed_json_is_rejected(client: HostClient) -> None:
    response = client.request_line("{not json")
    assert response.host_kind == HostKind.KERNEL
    assert response.accepted is False
    assert response.execution_status is None
    assert response.request_id is None
    assert response.error is not None
    assert response.error["code"] == ErrorCode.MALFORMED_JSON


def test_unsupported_version_is_rejected(client: HostClient) -> None:
    response = client.request_line(
        '{"protocol_version":"2","request_id":"k-v-1","type":"submit",'
        '"capability_id":"test.echo","payload":"p"}'
    )
    assert response.accepted is False
    assert response.execution_status is None
    assert response.error is not None
    assert response.error["code"] == ErrorCode.UNSUPPORTED_VERSION


def test_unknown_type_is_rejected(client: HostClient) -> None:
    response = client.request_line(
        '{"protocol_version":"1","request_id":"k-t-1","type":"frobnicate",'
        '"capability_id":"test.echo","payload":"p"}'
    )
    assert response.accepted is False
    assert response.execution_status is None
    assert response.error is not None
    assert response.error["code"] == ErrorCode.UNSUPPORTED_TYPE


def test_missing_field_is_rejected(client: HostClient) -> None:
    response = client.request_line(
        '{"protocol_version":"1","request_id":"k-m-1","type":"submit"}'
    )
    assert response.accepted is False
    assert response.execution_status is None
    assert response.error is not None
    assert response.error["code"] == ErrorCode.MISSING_FIELD


def test_oversize_line_is_rejected(client: HostClient) -> None:
    # A single line over the 64 KiB limit must be drained to the line boundary
    # and rejected, not partially parsed.
    response = client.request_line("x" * (envelope.MAX_REQUEST_LINE_BYTES + 5))
    assert response.accepted is False
    assert response.execution_status is None
    assert response.error is not None
    assert response.error["code"] == ErrorCode.OVERSIZE_LINE


# -- Host process behavior --------------------------------------------------


def test_stdout_is_protocol_only_and_stderr_carries_diagnostics(
    client: HostClient,
) -> None:
    # The client validates every stdout line as a v1 envelope, so a valid
    # response already proves stdout carried only protocol messages.
    response = client.send(
        Request(request_id="k-io-1", capability_id="test.echo", payload="p")
    )
    assert response.ok is True
    assert _wait_for(
        lambda: any("kernel-host: ready" in line for line in client.stderr_lines)
    )
    assert "kernel-host:" not in (response.output or "")


def test_kernel_host_reports_kernel_kind_and_real_status(
    client: HostClient,
) -> None:
    response = client.send(
        Request(request_id="k-kind-1", capability_id="test.echo", payload="p")
    )
    assert response.host_kind == HostKind.KERNEL
    assert response.host_kind != HostKind.STUB
    assert response.execution_status == "completed"


# -- parking.move stub ------------------------------------------------------
#
# M1-04B brings up the first intention-domain loop:
#   AgentIntent v1 payload -> Host -> Kernel Runtime -> parking.move stub.
# The stub is a SIMULATION: "stub_completed" says a simulation finished, not
# that any vehicle moved. The contract is frozen in
# docs/decisions/M1-04B0_PARKING_MOVE_STUB_DECISIONS.md (§5 output, §6 errors).

_PARKING_CAPABILITY = "parking.move"
_PARKING_INTENT_ID = "intent-0001"
_PARKING_TARGET = {"x": 1.5, "y": -2.25, "heading": 0.5}
#: The exact output field set (§5): version, status, mode, action, echo, target.
_PARKING_OUTPUT_FIELDS = frozenset(
    {"output_version", "status", "execution_mode", "action", "intent_id", "target"}
)


def _intent_payload(
    *,
    contract_version: str = "1",
    intent_id: object = _PARKING_INTENT_ID,
    action: str = _PARKING_CAPABILITY,
    target: object = None,
    extra: dict | None = None,
) -> str:
    """Build a parking.move payload JSON string (optionally malformed by design)."""

    obj: dict = {
        "contract_version": contract_version,
        "intent_id": intent_id,
        "action": action,
        "target": dict(_PARKING_TARGET) if target is None else target,
    }
    if extra:
        obj.update(extra)
    return json.dumps(obj, separators=(",", ":"))


def _valid_payload() -> str:
    """A payload produced by the authoritative Python AgentIntent v1 builder."""

    return AgentIntent(
        intent_id=_PARKING_INTENT_ID, target=Target(**_PARKING_TARGET)
    ).to_payload()


def _parking_request_line(request_id: str, payload: str) -> str:
    """A raw IPC v1 request line carrying an arbitrary parking.move payload."""

    return json.dumps(
        {
            "protocol_version": "1",
            "request_id": request_id,
            "type": "submit",
            "capability_id": _PARKING_CAPABILITY,
            "payload": payload,
        }
    )


# -- A. successful stub execution -------------------------------------------


def test_parking_move_stub_executes_through_real_kernel(client: HostClient) -> None:
    """Kernel execution: a valid intent runs the stub via the real Runtime path."""

    payload = _valid_payload()
    response = client.send(
        Request(
            request_id="k-park-1",
            capability_id=_PARKING_CAPABILITY,
            payload=payload,
        )
    )
    assert response.request_id == "k-park-1"
    assert response.host_kind == HostKind.KERNEL
    assert response.host_kind != HostKind.STUB
    assert response.accepted is True
    assert response.submission_status == SubmissionStatus.COMPLETED
    assert response.observation_status == ObservationStatus.SUCCESS
    # execution_status is read from the Kernel's own per-invocation
    # ExecutionResult, which only exists after Runtime::Run executed the
    # capability; a direct invoker call could not produce it. This is the
    # evidence that the request went through the Runtime submit/execute path.
    assert response.execution_status == "completed"
    assert response.error is None
    assert response.ok is True

    assert response.output is not None
    output = json.loads(response.output)
    # Exact field set: no request_id, no arrival/pose/timestamp fields (§5.4).
    assert set(output) == set(_PARKING_OUTPUT_FIELDS)
    assert output["output_version"] == "1"
    assert output["status"] == "stub_completed"
    assert output["execution_mode"] == "simulation"
    assert output["action"] == _PARKING_CAPABILITY
    assert output["intent_id"] == _PARKING_INTENT_ID
    assert set(output["target"]) == {"x", "y", "heading"}
    assert output["target"] == _PARKING_TARGET


def test_parking_move_output_is_deterministic_and_request_id_independent(
    client: HostClient,
) -> None:
    """Kernel execution: same intent -> byte-identical output across requests."""

    payload = _valid_payload()
    first = client.send(
        Request(request_id="k-park-det-1", capability_id=_PARKING_CAPABILITY, payload=payload)
    )
    second = client.send(
        Request(request_id="k-park-det-2", capability_id=_PARKING_CAPABILITY, payload=payload)
    )
    assert first.ok is True
    assert second.ok is True
    assert first.request_id != second.request_id
    assert first.output == second.output
    # The IPC request_id is carried by the envelope, never echoed by the stub.
    assert "k-park-det-1" not in (first.output or "")


# -- B. Python AgentIntent v1 authority (L2) --------------------------------
#
# The authoritative, complete v1 contract tests live in tests/vln/test_intent.py.
# These cases reuse the same public API to prove the L2 layering: a payload the
# Python contract rejects can never be produced by normal construction, so it
# never reaches the Host.


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("{not json", id="not-json"),
        pytest.param("[1, 2]", id="root-not-object"),
        pytest.param('{"contract_version":"1","intent_id":"i","action":"parking.move"}', id="missing-target"),
        pytest.param(
            '{"contract_version":"1","intent_id":"i","action":"parking.move","target":{"x":1.0,"y":2.0,"heading":0.5},"v":1.0}',
            id="unknown-top-level-field",
        ),
        pytest.param(_intent_payload(contract_version="2"), id="wrong-contract-version"),
        pytest.param(_intent_payload(action="parking.stop"), id="wrong-action"),
        pytest.param(_intent_payload(target={"x": 1.0, "y": 2.0}), id="target-missing-heading"),
        pytest.param(
            _intent_payload(target={"x": 1.0, "y": 2.0, "heading": 0.5, "z": 0.0}),
            id="target-unknown-field",
        ),
        pytest.param(
            _intent_payload(target={"x": True, "y": 2.0, "heading": 0.5}),
            id="x-is-bool",
        ),
        pytest.param(
            _intent_payload(target={"x": "1.0", "y": 2.0, "heading": 0.5}),
            id="x-is-string",
        ),
        pytest.param(
            '{"contract_version":"1","intent_id":"i","action":"parking.move","target":{"x":NaN,"y":2.0,"heading":0.5}}',
            id="x-not-finite",
        ),
        pytest.param(_intent_payload(intent_id="   "), id="intent-id-blank"),
        pytest.param(_intent_payload(intent_id=1), id="intent-id-not-string"),
    ],
)
def test_python_agent_intent_rejects_illegal_payloads(payload: str) -> None:
    with pytest.raises(AgentIntentError):
        AgentIntent.from_payload(payload)


# -- B-2/C. C++ Stub defensive subset (S1-S8) via raw IPC -------------------
#
# These bypass the Python builder on purpose and send the payload straight to
# the Host, so they exercise the stub's own fail-closed validation (M1-04B0
# §4.2). Every rejection must surface as an invocation failure: never a fake
# success and never an IPC-layer invalid-field (§6.1 #3).

_INVALID_PARKING_PAYLOADS = [
    pytest.param("{nope", id="s1-invalid-json"),
    pytest.param("[1,2]", id="s2-root-not-object"),
    pytest.param(
        '{"contract_version":"1","intent_id":"i","target":{"x":1.0,"y":2.0,"heading":0.5}}',
        id="s3-missing-action",
    ),
    pytest.param(_intent_payload(extra={"velocity": 1.0}), id="s3-unknown-top-level-field"),
    pytest.param(_intent_payload(contract_version="2"), id="s4-wrong-version"),
    pytest.param(_intent_payload(contract_version=1), id="s4-version-not-string"),
    pytest.param(_intent_payload(action="parking.stop"), id="s5-wrong-action"),
    pytest.param(_intent_payload(intent_id="   "), id="s6-blank-intent-id"),
    pytest.param(_intent_payload(intent_id=1), id="s6-intent-id-not-string"),
    pytest.param(_intent_payload(target={"x": 1.0, "y": 2.0}), id="s7-target-missing-heading"),
    pytest.param(
        _intent_payload(target={"x": 1.0, "y": 2.0, "heading": 0.5, "z": 0.0}),
        id="s7-target-unknown-field",
    ),
    pytest.param(
        _intent_payload(target={"x": True, "y": 2.0, "heading": 0.5}), id="s8-x-is-bool"
    ),
    pytest.param(
        _intent_payload(target={"x": "1.0", "y": 2.0, "heading": 0.5}), id="s8-x-is-string"
    ),
    pytest.param(
        _intent_payload(target={"x": None, "y": 2.0, "heading": 0.5}), id="s8-x-is-null"
    ),
    pytest.param(
        '{"contract_version":"1","intent_id":"i","action":"parking.move","target":{"x":1.0,"y":2.0,"heading":NaN}}',
        id="s8-heading-not-finite",
    ),
]


@pytest.mark.parametrize("payload", _INVALID_PARKING_PAYLOADS)
def test_parking_move_stub_rejects_invalid_payload(client: HostClient, payload: str) -> None:
    """Execution failure: the stub fails closed and produces no fake output."""

    response = client.request_line(_parking_request_line("k-park-bad-1", payload))
    assert response.host_kind == HostKind.KERNEL
    assert response.accepted is True
    assert response.submission_status == SubmissionStatus.FAILED
    assert response.observation_status == ObservationStatus.FAILURE
    # A failed ExecutionResult is still stored per-invocation by the Kernel.
    assert response.execution_status == "failed"
    assert response.output is None
    assert response.ok is False
    assert response.error is not None
    assert response.error["code"] == ErrorCode.CAPABILITY_INVOCATION_FAILED
    # The stub cannot emit an IPC-layer code; it must not be reported as one.
    assert response.error["code"] != ErrorCode.INVALID_FIELD


def test_parking_move_blank_payload_is_rejected_at_envelope(client: HostClient) -> None:
    """Protocol (L1): a blank payload never reaches the stub."""

    response = client.request_line(_parking_request_line("k-park-blank-1", ""))
    assert response.accepted is False
    assert response.submission_status is None
    assert response.execution_status is None
    assert response.output is None
    assert response.ok is False
    assert response.error is not None
    assert response.error["code"] == ErrorCode.INVALID_FIELD


def test_unregistered_parking_capability_maps_to_not_found(client: HostClient) -> None:
    """Kernel execution: an unregistered parking capability is a real failure."""

    response = client.send(
        Request(
            request_id="k-park-unreg-1",
            capability_id="parking.stop",
            payload=_valid_payload(),
        )
    )
    assert response.host_kind == HostKind.KERNEL
    assert response.accepted is True
    assert response.submission_status == SubmissionStatus.FAILED
    assert response.observation_status == ObservationStatus.FAILURE
    # Resolved before Run, so no per-invocation ExecutionResult exists.
    assert response.execution_status is None
    assert response.output is None
    assert response.ok is False
    assert response.error is not None
    assert response.error["code"] == ErrorCode.CAPABILITY_NOT_FOUND


# -- M1-05A: Python caller -> Host -> Runtime -> parking.move stub -> Python --
#
# The M1-04B section above tests the stub capability at the IPC/wire level.
# This section tests the same chain from the *Python caller's* point of view:
# a caller builds an AgentIntent with the public API, submits it through the
# real HostClient, and reads the real Runtime outcome back. The caller is test
# code (no model adapter exists yet), so no production API is added here.


def test_e2e_python_intent_roundtrip_through_real_host(client: HostClient) -> None:
    """E2E-1: a Python-built intent runs end to end and returns real results.

    Each response field is produced by a different layer, so asserting them
    together is what distinguishes a real Runtime execution from a fabricated
    success:

    * ``accepted`` / ``submission_status`` / ``observation_status`` - the Host
      and its authorization port;
    * ``execution_status`` - the Kernel's own per-invocation ExecutionResult;
    * ``output`` - the ``parking.move`` stub invoker, reached via Runtime::Run.
    """

    intent = AgentIntent(
        intent_id="intent-e2e-1", target=Target(x=1.5, y=-2.25, heading=0.5)
    )
    response = client.send(
        Request(
            request_id="k-e2e-1",
            # The capability is bound to the intent's action by the caller; no
            # action->capability table exists in the project.
            capability_id=intent.action,
            payload=intent.to_payload(),
        )
    )

    assert response.request_id == "k-e2e-1"
    assert response.host_kind == HostKind.KERNEL
    assert response.host_kind != HostKind.STUB
    assert response.accepted is True
    assert response.submission_status == SubmissionStatus.COMPLETED
    assert response.observation_status == ObservationStatus.SUCCESS
    assert response.execution_status == "completed"
    assert response.error is None
    assert response.ok is True

    assert response.output is not None
    output = json.loads(response.output)
    assert set(output) == set(_PARKING_OUTPUT_FIELDS)
    assert output["output_version"] == "1"
    assert output["action"] == intent.action
    # intent_id and the IPC request_id are independent identities that round-trip
    # separately; the stub echoes only the intent_id (it never sees request_id).
    assert output["intent_id"] == intent.intent_id
    assert output["intent_id"] != response.request_id
    assert output["target"] == {"x": 1.5, "y": -2.25, "heading": 0.5}
    # The result is explicitly a simulation and never claims arrival.
    assert output["status"] == "stub_completed"
    assert output["execution_mode"] == "simulation"
    assert not any(
        key in output for key in ("arrived", "pose", "position", "located", "timestamp")
    )


def test_e2e_invalid_intent_is_rejected_before_submission(client: HostClient) -> None:
    """E2E-2: an illegal intent cannot be prepared for submission at all.

    The Python AgentIntent layer is the authoritative v1 validator; it refuses
    to serialize an illegal intent, so the intent-driven path never reaches the
    Host. (Bypassing the builder and hand-writing a raw payload is a different
    path, caught by the stub's defensive subset - see the M1-04B tests above.)
    """

    # Authoritative construction/parse failures - no payload can be produced.
    with pytest.raises(AgentIntentError):
        AgentIntent(intent_id="   ", target=Target(x=1.0, y=2.0, heading=0.0))
    with pytest.raises(AgentIntentError):
        AgentIntent(
            intent_id="i", target=Target(x=float("nan"), y=2.0, heading=0.0)
        )
    with pytest.raises(AgentIntentError):
        AgentIntent.from_payload(
            '{"contract_version":"1","intent_id":"i","action":"parking.stop",'
            '"target":{"x":1.0,"y":2.0,"heading":0.0}}'
        )

    # Positive control: a legal intent serializes and IS executed by the Host,
    # proving the rejection above is validation, not a broken submission path.
    response = client.send(
        Request(
            request_id="k-e2e-2",
            capability_id=_PARKING_CAPABILITY,
            payload=_valid_payload(),
        )
    )
    assert response.ok is True


# -- M1-05C1: Mock model text -> parser -> RequestBuilder -> real Host -------
#
# This exercises the M1-05C1 orchestration seam against the REAL host: a Mock
# model's raw text is parsed by the authoritative parser, bridged to an IPC
# Request, and executed by the same Host/Runtime path as the M1-05A tests. The
# model is a MOCK (it returns configured text); nothing here is real
# ZDTaichu5.0-9B inference, and "stub_completed" is a simulation, not arrival.


def _kernel_host_client() -> HostClient:
    return HostClient(_kernel_host_command())


def test_mock_model_output_runs_through_real_host_pipeline() -> None:
    """E2E: Mock model text -> parse_model_output -> RequestBuilder -> Host."""

    intent = AgentIntent(
        intent_id="intent-mock-1", target=Target(x=1.5, y=-2.25, heading=0.5)
    )
    model = MockModelClient(intent.to_payload())

    response = run_parking_intent(
        model=model,
        observation={"note": "mock observation; no camera in this phase"},
        instruction="park at the target",
        request_id="k-pipe-1",
        host_client_factory=_kernel_host_client,
    )

    assert model.call_count == 1
    assert response.request_id == "k-pipe-1"
    assert response.host_kind == HostKind.KERNEL
    assert response.host_kind != HostKind.STUB
    assert response.accepted is True
    assert response.submission_status == SubmissionStatus.COMPLETED
    assert response.observation_status == ObservationStatus.SUCCESS
    assert response.execution_status == "completed"
    assert response.error is None
    assert response.ok is True

    assert response.output is not None
    output = json.loads(response.output)
    assert set(output) == set(_PARKING_OUTPUT_FIELDS)
    assert output["output_version"] == "1"
    assert output["status"] == "stub_completed"
    assert output["execution_mode"] == "simulation"
    assert output["action"] == _PARKING_CAPABILITY
    assert output["intent_id"] == intent.intent_id
    assert output["intent_id"] != response.request_id
    assert output["target"] == {"x": 1.5, "y": -2.25, "heading": 0.5}


# -- M1-VLN-FUNCTION-02: a real Host failure surfaced through the pipeline ----
#
# The M1-05C1 test above drives the SUCCESS path through run_parking_intent ->
# real HostClient -> real C++ Host. This test drives a FAILURE through the same
# entry point, so the pipeline's failure handling is exercised against the real
# cross-process boundary (not a Python-constructed result).
#
# Why an injected request_builder: the ``parking.move`` stub cannot be made to
# fail for a pipeline-originated request. The pipeline validates with the
# authoritative Python contract, which is at least as strict as the stub's
# defensive subset (S1-S8), so every pipeline-valid intent is stub-accepted and
# a parking.move *execution* failure is unreachable by construction. To reach a
# genuine *Host* failure through the pipeline, the existing injectable
# ``request_builder`` seam is bound to a capability the Host does not register;
# the rejection therefore originates in the real C++ Host/Kernel resolution
# path, never in Python.


def test_pipeline_surfaces_a_real_host_failure_as_failure() -> None:
    """E2E: a real C++ Host rejection reaches Python as a non-success result."""

    intent = AgentIntent(
        intent_id="intent-fail-1", target=Target(x=1.5, y=-2.25, heading=0.5)
    )
    model = MockModelClient(intent.to_payload())

    def _unregistered_capability_builder(validated, *, request_id: str) -> Request:
        # Same validated intent, bound to a capability the Host does not know.
        return Request(
            request_id=request_id,
            capability_id="parking.stop",
            payload=validated.to_payload(),
        )

    response = run_parking_intent(
        model=model,
        observation=None,
        instruction="park at the target",
        request_id="k-pipe-fail-1",
        host_client_factory=_kernel_host_client,
        request_builder=_unregistered_capability_builder,
    )

    assert model.call_count == 1
    assert response.request_id == "k-pipe-fail-1"
    assert response.host_kind == HostKind.KERNEL
    assert response.host_kind != HostKind.STUB
    # Accepted by the port but unresolvable by the Kernel: a real failure.
    assert response.accepted is True
    assert response.submission_status == SubmissionStatus.FAILED
    assert response.observation_status == ObservationStatus.FAILURE
    assert response.execution_status is None
    assert response.output is None
    assert response.ok is False
    assert response.error is not None
    assert response.error["code"] == ErrorCode.CAPABILITY_NOT_FOUND


def test_e2e_overflow_number_payload_cannot_produce_success(client: HostClient) -> None:
    """E2E-6: a number literal that would overflow to a non-finite value fails.

    Empirically, nlohmann/json 3.11.2 rejects ``1e999`` while parsing
    (``json.exception.out_of_range.406``), so here the rejection happens at the
    stub's parse step, not at its S8 ``std::isfinite`` check. Either way the
    outcome must be a real Runtime failure, never a fabricated success.
    """

    payload = (
        '{"contract_version":"1","intent_id":"intent-0001","action":"parking.move",'
        '"target":{"x":1.0,"y":2.0,"heading":1e999}}'
    )
    response = client.request_line(_parking_request_line("k-e2e-6", payload))
    assert response.host_kind == HostKind.KERNEL
    assert response.accepted is True
    assert response.submission_status == SubmissionStatus.FAILED
    assert response.observation_status == ObservationStatus.FAILURE
    assert response.execution_status == "failed"
    assert response.output is None
    assert response.ok is False
    assert response.error is not None
    assert response.error["code"] == ErrorCode.CAPABILITY_INVOCATION_FAILED
