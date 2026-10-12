"""A minimal NDJSON client for the VLN-AVP IPC host process.

The client owns a single child process and exchanges one JSON request line
for one JSON response line at a time. Protocol responses arrive on the
child's **stdout**; diagnostics arrive on its **stderr** and are drained on
a background thread so they never interleave with the protocol stream.

Design rules baked into this client:

* No automatic retry. A transport failure, a terminated host, or a malformed
  response is raised to the caller. The client never re-sends a request whose
  outcome is uncertain.
* A response whose ``request_id`` does not match the request is rejected.
* Anything on stdout that is not a valid v1 response envelope is a protocol
  violation, not a diagnostic.

This is intentionally not a general RPC framework.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Optional, Sequence

from vln.ipc import envelope
from vln.ipc.envelope import Request, Response
from vln.ipc.errors import (
    HostTerminatedError,
    ProtocolViolation,
    ResponseMismatchError,
    TransportError,
)


class HostClient:
    """A long-lived NDJSON client bound to one host child process."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
    ) -> None:
        if not command:
            raise ValueError("command must not be empty")
        self._command = list(command)
        self._cwd = cwd
        self._env = env
        self._proc: Optional[subprocess.Popen] = None
        self._stderr_lines: list[str] = []
        self._stderr_lock = threading.Lock()
        self._stderr_thread: Optional[threading.Thread] = None

    # -- lifecycle ------------------------------------------------------

    def start(self) -> None:
        """Start the host process if it is not already running."""

        if self._proc is not None and self._proc.poll() is None:
            return
        child_env = self._env
        if child_env is None:
            child_env = os.environ.copy()
        self._proc = subprocess.Popen(
            self._command,
            cwd=self._cwd,
            env=child_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=-1,
            text=False,
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, args=(self._proc,), daemon=True
        )
        self._stderr_thread.start()

    def _drain_stderr(self, proc: subprocess.Popen) -> None:
        assert proc.stderr is not None
        for raw in iter(proc.stderr.readline, b""):
            with self._stderr_lock:
                self._stderr_lines.append(raw.decode("utf-8", errors="replace"))

    @property
    def stderr_lines(self) -> list[str]:
        """A snapshot of the host's stderr lines collected so far."""

        with self._stderr_lock:
            return list(self._stderr_lines)

    @property
    def pid(self) -> Optional[int]:
        return None if self._proc is None else self._proc.pid

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def close(self, timeout: float = 5.0) -> None:
        """Close the connection and reap the child process."""

        proc = self._proc
        if proc is None:
            return
        if proc.stdin is not None and not proc.stdin.closed:
            try:
                proc.stdin.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=timeout)
        for stream in (proc.stdout, proc.stderr):
            if stream is not None and not stream.closed:
                try:
                    stream.close()
                except OSError:
                    pass

    def __enter__(self) -> "HostClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # -- request/response ----------------------------------------------

    def send(self, request: Request) -> Response:
        """Send one validated request and return its matching response.

        Raises :class:`ResponseMismatchError` when the host answers with a
        different ``request_id`` than the one sent. Never retries.
        """

        response = self.request_line(request.to_line())
        if response.request_id != request.request_id:
            raise ResponseMismatchError(
                "response request_id does not match the request: "
                f"sent={request.request_id!r} received={response.request_id!r}"
            )
        return response

    def request_line(self, text: str) -> Response:
        """Send an arbitrary line (for protocol-level tests) and read a response.

        The response is validated as a v1 envelope but its ``request_id`` is
        not required to match. Never retries.
        """

        self.start()
        proc = self._proc
        assert proc is not None and proc.stdin is not None and proc.stdout is not None

        data = text.encode("utf-8") + b"\n"
        try:
            proc.stdin.write(data)
            proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise TransportError(f"failed to write request: {exc}") from exc

        try:
            raw = proc.stdout.readline()
        except (OSError, ValueError) as exc:
            raise TransportError(f"failed to read response: {exc}") from exc
        if raw == b"":
            code = proc.poll()
            raise HostTerminatedError(
                f"host terminated before responding (exit code {code})"
            )
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolViolation(
                envelope.ErrorCode.INVALID_RESPONSE,
                "response line is not valid UTF-8",
            ) from exc
        line = decoded.rstrip("\n").rstrip("\r")
        return envelope.parse_response_line(line)


__all__ = ["HostClient"]
