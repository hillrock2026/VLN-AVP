#!/usr/bin/env python3
"""TEST-ONLY stub host for the VLN-AVP IPC v1 protocol.

THIS IS NOT THE AGENT-KERNEL RUNTIME.

This process exists solely to exercise the wire protocol, the Python client
and the process/transport behavior end to end without an authorized,
reproducible Agent-Kernel baseline. It:

* never loads, constructs or invokes Agent-Kernel;
* does not register, resolve or execute any real capability;
* reports ``host_kind = "stub"`` and leaves ``execution_status`` null;
* implements exactly one test behavior for ``test.echo`` (see below).

A response from this host MUST NOT be represented as Kernel execution. The
real, Kernel-backed host is deferred to Phase 3B-2 (see runtime_host/README.md).

Protocol behavior
-----------------
* Reads one JSON request per line from stdin; writes one JSON response line
  per request to stdout.
* Diagnostics go to stderr only.
* Envelope validation is delegated to the shared ``vln.ipc.envelope`` module,
  so the client and the host cannot diverge on the contract.
* Malformed input never reaches any execution path.

Test capabilities
-----------------
* ``test.echo``: returns ``"[stub-echo]:" + payload`` as the output.
* Anything else: a ``capability-not-found`` failure (accepted, then failed),
  mirroring the Kernel adapter's "accepted submission, deterministic failure"
  outcome. No other capability exists.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the repository's ``src`` importable so this script can be run directly
# (``python runtime_host/stub_host.py``) without installing the package.
_REPO_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from vln.ipc import envelope
from vln.ipc.envelope import (
    ErrorCode,
    HostKind,
    ObservationStatus,
    SubmissionStatus,
)

SUPPORTED_CAPABILITIES = frozenset({"test.echo"})

#: Hard cap on how much of an oversized line the stub will drain before it
#: gives up (protects the test process from an unbounded junk stream).
_OVERSIZE_DRAIN_CAP = 16 * 1024 * 1024


class _OversizeDrainExceeded(Exception):
    pass


def _log(message: str) -> None:
    sys.stderr.write(f"stub-host: {message}\n")
    sys.stderr.flush()


def _write_response(obj: dict) -> None:
    line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _read_bounded_line(stream, limit: int, hard_cap: int):
    """Read one line (without the trailing newline).

    Returns ``(payload_bytes, oversize, eof)``. A line longer than ``limit``
    is marked oversize and drained up to ``hard_cap`` bytes; exceeding the
    hard cap raises :class:`_OversizeDrainExceeded`.
    """

    buf = bytearray()
    oversize = False
    drained = 0
    while True:
        ch = stream.read(1)
        if ch == b"":
            return bytes(buf), oversize, True
        if ch == b"\n":
            return bytes(buf), oversize, False
        if oversize:
            drained += 1
            if drained > hard_cap:
                raise _OversizeDrainExceeded()
            continue
        buf += ch
        if len(buf) > limit:
            oversize = True
            buf = bytearray()


def _handle_request(text: str) -> dict:
    """Validate one request line and return a response object."""

    try:
        request = envelope.parse_request_line(text)
    except envelope.ProtocolViolation as exc:
        _log(f"rejected request: {exc.code}")
        return envelope.error_response(
            envelope.peek_request_id(text), exc.code, exc.message
        )

    if request.capability_id not in SUPPORTED_CAPABILITIES:
        _log(f"unknown capability: {request.capability_id}")
        return envelope.error_response(
            request.request_id,
            ErrorCode.CAPABILITY_NOT_FOUND,
            f"stub host has no capability: {request.capability_id!r}",
            accepted=True,
            submission_status=SubmissionStatus.FAILED,
            observation_status=ObservationStatus.FAILURE,
        )

    output = "[stub-echo]:" + request.payload
    _log(f"handled test.echo for request_id={request.request_id}")
    return envelope.build_response(
        request_id=request.request_id,
        accepted=True,
        submission_status=SubmissionStatus.COMPLETED,
        observation_status=ObservationStatus.SUCCESS,
        execution_status=None,  # a stub has no Kernel execution status
        output=output,
        error=None,
        host_kind=HostKind.STUB,
    )


def main() -> int:
    _log("ready (TEST-ONLY STUB; no Agent-Kernel runtime)")
    stream = sys.stdin.buffer
    while True:
        try:
            payload, oversize, eof = _read_bounded_line(
                stream, envelope.MAX_REQUEST_LINE_BYTES, _OVERSIZE_DRAIN_CAP
            )
        except _OversizeDrainExceeded:
            _log("fatal: oversize line exceeded drain cap; exiting")
            return 2

        if oversize:
            _log("rejected request: oversize-line")
            _write_response(
                envelope.error_response(
                    None,
                    ErrorCode.OVERSIZE_LINE,
                    f"request line exceeds {envelope.MAX_REQUEST_LINE_BYTES} bytes",
                )
            )
            continue

        if eof and payload == b"":
            break

        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            _write_response(
                envelope.error_response(
                    None,
                    ErrorCode.MALFORMED_JSON,
                    "request line is not valid UTF-8",
                )
            )
            continue

        _write_response(_handle_request(text))

    _log("stdin closed; exiting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
