"""Exception types for the VLN-AVP IPC v1 protocol.

These are the only errors the IPC layer raises. They are intentionally
small: the protocol is a synchronous, newline-delimited JSON exchange, so
the failure surface is (1) a protocol/envelope violation, (2) a transport
failure against the host process, or (3) a response that does not match the
request that was sent.

None of these errors is retried automatically. A transport error or an
uncertain outcome is reported to the caller; it is never silently resent.
"""

from __future__ import annotations


class IpcError(Exception):
    """Base class for every IPC-layer error."""


class ProtocolViolation(IpcError):
    """A protocol or envelope rule was broken.

    ``code`` is the stable machine-readable error code (see
    :class:`vln.ipc.envelope.ErrorCode`); ``message`` is the human-readable
    detail. The pair is what the host puts into a response ``error`` object,
    and what the client raises when a response envelope is invalid.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class TransportError(IpcError):
    """Communicating with the host process failed (pipe write/read error)."""


class HostTerminatedError(TransportError):
    """The host process ended (stdout/stdin closed) before responding."""


class UncertainOutcomeError(TransportError):
    """A request may have executed, but its outcome could not be confirmed.

    Raised when the client refuses to (re)submit a request that it cannot prove
    was never executed - for example after the host terminated while a request
    was in flight. The outcome is unknown, not known-to-have-failed: the
    capability may already have run, so a caller must not blindly retry. This
    is deliberately a transport error, never a deterministic execution failure.
    """


class ResponseMismatchError(IpcError):
    """A response was received for a different ``request_id`` than sent."""


__all__ = [
    "IpcError",
    "ProtocolViolation",
    "TransportError",
    "HostTerminatedError",
    "UncertainOutcomeError",
    "ResponseMismatchError",
]
