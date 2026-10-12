"""VLN-AVP IPC v1 protocol package.

Public surface:

* :mod:`vln.ipc.envelope` - the versioned request/response envelope rules,
  shared by the Python client and the test-only stub host.
* :mod:`vln.ipc.errors` - the IPC exception types.

This package encodes and validates the wire protocol only. It is not a
general RPC framework and it performs no execution.
"""

from . import envelope, errors
from .envelope import (
    PROTOCOL_VERSION,
    ErrorCode,
    HostKind,
    ObservationStatus,
    Request,
    Response,
    SubmissionStatus,
)

__all__ = [
    "envelope",
    "errors",
    "PROTOCOL_VERSION",
    "ErrorCode",
    "HostKind",
    "ObservationStatus",
    "Request",
    "Response",
    "SubmissionStatus",
]
