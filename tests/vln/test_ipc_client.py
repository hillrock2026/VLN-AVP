"""Client-level tests for transport, error and no-retry behavior.

These tests use small purpose-built fake host scripts (not the stub host) so
each failure mode is isolated and deterministic.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from vln.client import HostClient
from vln.ipc.envelope import ErrorCode, ProtocolViolation, Request
from vln.ipc.errors import (
    HostTerminatedError,
    ResponseMismatchError,
    TransportError,
)


def _write_script(tmp_path: Path, name: str, source: str) -> str:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return str(path)


def _command(script: str, *args: str) -> list[str]:
    return [sys.executable, script, *args]


_ECHO_HOST = """
import json, sys
sys.stderr.write("fake-host: ready\\n"); sys.stderr.flush()
for line in sys.stdin.buffer:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    resp = {
        "protocol_version": "1",
        "request_id": req["request_id"],
        "host_kind": "stub",
        "accepted": True,
        "submission_status": "completed",
        "observation_status": "success",
        "execution_status": None,
        "output": "OK:" + req["payload"],
        "error": None,
    }
    sys.stdout.write(json.dumps(resp) + "\\n"); sys.stdout.flush()
"""


_WRONG_ID_HOST = """
import json, sys
for line in sys.stdin.buffer:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    resp = {
        "protocol_version": "1",
        "request_id": "some-other-id",
        "host_kind": "stub",
        "accepted": True,
        "submission_status": "completed",
        "observation_status": "success",
        "execution_status": None,
        "output": "OK",
        "error": None,
    }
    sys.stdout.write(json.dumps(resp) + "\\n"); sys.stdout.flush()
"""


_EXIT_IMMEDIATELY_HOST = """
import sys
sys.stderr.write("fake-host: exiting\\n"); sys.stderr.flush()
sys.exit(0)
"""


_COUNT_ONCE_HOST = """
import sys
count_file = sys.argv[1]
line = sys.stdin.buffer.readline()
with open(count_file, "a", encoding="utf-8") as handle:
    handle.write("x")
sys.exit(3)
"""


_NON_JSON_STDOUT_HOST = """
import sys
sys.stdin.buffer.readline()
sys.stdout.write("this is not json\\n"); sys.stdout.flush()
sys.exit(0)
"""


_BAD_ENVELOPE_HOST = """
import json, sys
sys.stdin.buffer.readline()
sys.stdout.write(json.dumps({"protocol_version": "1"}) + "\\n"); sys.stdout.flush()
sys.exit(0)
"""


def _wait_for(predicate, timeout: float = 5.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_send_returns_matching_response(tmp_path: Path) -> None:
    client = HostClient(_command(_write_script(tmp_path, "echo.py", _ECHO_HOST)))
    try:
        response = client.send(
            Request(request_id="a", capability_id="test.echo", payload="p")
        )
        assert response.ok is True
        assert response.output == "OK:p"
    finally:
        client.close()


def test_response_id_mismatch_raises(tmp_path: Path) -> None:
    client = HostClient(_command(_write_script(tmp_path, "wrong.py", _WRONG_ID_HOST)))
    try:
        with pytest.raises(ResponseMismatchError):
            client.send(Request(request_id="a", capability_id="test.echo", payload="p"))
    finally:
        client.close()


def test_host_termination_raises(tmp_path: Path) -> None:
    client = HostClient(_command(_write_script(tmp_path, "exit.py", _EXIT_IMMEDIATELY_HOST)))
    try:
        with pytest.raises((TransportError, HostTerminatedError)):
            client.send(Request(request_id="a", capability_id="test.echo", payload="p"))
    finally:
        client.close()


def test_no_automatic_retry_after_uncertain_outcome(tmp_path: Path) -> None:
    count_file = tmp_path / "count.txt"
    script = _write_script(tmp_path, "count.py", _COUNT_ONCE_HOST)
    client = HostClient(_command(script, str(count_file)))
    request = Request(request_id="a", capability_id="test.echo", payload="p")
    try:
        with pytest.raises((TransportError, HostTerminatedError)):
            client.send(request)
        # A second attempt must not silently resend on the caller's behalf;
        # and the host must have been written to exactly once.
        with pytest.raises((TransportError, HostTerminatedError)):
            client.send(request)
    finally:
        client.close()
    assert count_file.read_text(encoding="utf-8") == "x"


def test_invalid_response_envelope_rejected(tmp_path: Path) -> None:
    client = HostClient(
        _command(_write_script(tmp_path, "badenv.py", _BAD_ENVELOPE_HOST))
    )
    try:
        with pytest.raises(ProtocolViolation) as exc:
            client.send(Request(request_id="a", capability_id="test.echo", payload="p"))
        assert exc.value.code == ErrorCode.INVALID_RESPONSE
    finally:
        client.close()


def test_non_json_stdout_is_protocol_violation(tmp_path: Path) -> None:
    client = HostClient(
        _command(_write_script(tmp_path, "nonjson.py", _NON_JSON_STDOUT_HOST))
    )
    try:
        with pytest.raises(ProtocolViolation) as exc:
            client.send(Request(request_id="a", capability_id="test.echo", payload="p"))
        assert exc.value.code == ErrorCode.INVALID_RESPONSE
    finally:
        client.close()


def test_stderr_is_separated_from_stdout(tmp_path: Path) -> None:
    client = HostClient(_command(_write_script(tmp_path, "echo2.py", _ECHO_HOST)))
    try:
        response = client.send(
            Request(request_id="a", capability_id="test.echo", payload="p")
        )
        assert response.output == "OK:p"
        assert _wait_for(
            lambda: any("fake-host: ready" in line for line in client.stderr_lines)
        )
        # Diagnostics never leak into the protocol output.
        assert "fake-host" not in (response.output or "")
    finally:
        client.close()
