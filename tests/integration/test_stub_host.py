"""End-to-end protocol tests against the test-only stub host.

These tests exercise the wire protocol, the client and process/transport
behavior. They do NOT exercise Agent-Kernel and must never be read as proof
of Kernel integration or of any real capability execution.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from vln.client import HostClient
from vln.ipc import envelope
from vln.ipc.envelope import ErrorCode, HostKind, Request

pytestmark = pytest.mark.integration

_STUB_PATH = Path(__file__).resolve().parents[2] / "runtime_host" / "stub_host.py"
_COMMAND = [sys.executable, str(_STUB_PATH)]


@pytest.fixture()
def client():
    client = HostClient(_COMMAND)
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


def test_successful_request_response(client: HostClient) -> None:
    response = client.send(
        Request(request_id="ok-1", capability_id="test.echo", payload="hello")
    )
    assert response.request_id == "ok-1"
    assert response.host_kind == HostKind.STUB
    assert response.accepted is True
    assert response.ok is True
    assert response.output == "[stub-echo]:hello"
    assert response.execution_status is None  # a stub has no Kernel status


def test_sequential_requests_over_one_process(client: HostClient) -> None:
    for index in range(3):
        request_id = f"seq-{index}"
        response = client.send(
            Request(
                request_id=request_id,
                capability_id="test.echo",
                payload=f"payload-{index}",
            )
        )
        assert response.request_id == request_id
        assert response.output == f"[stub-echo]:payload-{index}"


def test_missing_field_is_rejected(client: HostClient) -> None:
    response = client.request_line(
        '{"protocol_version":"1","request_id":"m-1","type":"submit"}'
    )
    assert response.error is not None
    assert response.error["code"] == ErrorCode.MISSING_FIELD


def test_unsupported_version_is_rejected(client: HostClient) -> None:
    response = client.request_line(
        '{"protocol_version":"2","request_id":"v-1","type":"submit",'
        '"capability_id":"test.echo","payload":"p"}'
    )
    assert response.error is not None
    assert response.error["code"] == ErrorCode.UNSUPPORTED_VERSION


def test_unknown_type_is_rejected(client: HostClient) -> None:
    response = client.request_line(
        '{"protocol_version":"1","request_id":"t-1","type":"frobnicate",'
        '"capability_id":"test.echo","payload":"p"}'
    )
    assert response.error is not None
    assert response.error["code"] == ErrorCode.UNSUPPORTED_TYPE


def test_malformed_json_is_rejected(client: HostClient) -> None:
    response = client.request_line("{not json")
    assert response.error is not None
    assert response.error["code"] == ErrorCode.MALFORMED_JSON
    assert response.request_id is None


def test_oversize_line_is_rejected(client: HostClient) -> None:
    response = client.request_line("x" * (envelope.MAX_REQUEST_LINE_BYTES + 5))
    assert response.error is not None
    assert response.error["code"] == ErrorCode.OVERSIZE_LINE


def test_unknown_capability_fails_without_execution(client: HostClient) -> None:
    response = client.send(
        Request(request_id="c-1", capability_id="nav.go", payload="p")
    )
    assert response.accepted is True
    assert response.submission_status == envelope.SubmissionStatus.FAILED
    assert response.observation_status == envelope.ObservationStatus.FAILURE
    assert response.output is None
    assert response.error is not None
    assert response.error["code"] == ErrorCode.CAPABILITY_NOT_FOUND


def test_stdout_carries_only_protocol_and_stderr_carries_diagnostics(
    client: HostClient,
) -> None:
    # The client enforces that every stdout line is a valid v1 envelope.
    response = client.send(
        Request(request_id="s-1", capability_id="test.echo", payload="p")
    )
    assert response.ok is True
    # The stub's banner and per-request diagnostics arrive on stderr only.
    assert _wait_for(
        lambda: any("stub-host: ready" in line for line in client.stderr_lines)
    )
    assert _wait_for(
        lambda: any("handled test.echo" in line for line in client.stderr_lines)
    )
    assert "stub-host:" not in (response.output or "")


def test_stub_never_claims_kernel_execution(client: HostClient) -> None:
    response = client.send(
        Request(request_id="k-1", capability_id="test.echo", payload="p")
    )
    assert response.host_kind == HostKind.STUB
    assert response.host_kind != HostKind.KERNEL
    assert response.execution_status is None
