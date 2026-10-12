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

These tests prove only the first real Kernel integration loop (``test.echo``).
They are NOT evidence that the K0 gate is closed, that navigation works, that
ZDTaichu5.0-9B is integrated, or that any production capability is safe.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from vln.client import HostClient
from vln.ipc import envelope
from vln.ipc.envelope import (
    ErrorCode,
    HostKind,
    ObservationStatus,
    Request,
    SubmissionStatus,
)

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
