"""VLN-AVP IPC v1 envelope: build, serialize and validate messages.

The protocol is deliberately minimal. It is a versioned, newline-delimited
JSON (NDJSON) request/response contract exchanged over a host process's
stdin/stdout. One request line produces exactly one terminal response line;
there is no asynchronous "pending" state in v1.

This module is the single source of truth for the envelope rules and is
shared by the Python client and by the test-only stub host. It performs
*protocol-level* validation only: it does not know about Agent-Kernel
capabilities, and it never claims a request_id provides deduplication or
exactly-once execution.

Field mapping note: every field here is a proposed *adapter-level* field of
this protocol. The names are chosen to mirror the Agent-Kernel integration
types used by the future real host (see ``protocol/v1/messages.md``), but
they are NOT existing Agent-Kernel JSON types.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .errors import ProtocolViolation

# ----------------------------------------------------------------------
# Protocol constants and limits
# ----------------------------------------------------------------------

#: The only protocol version this implementation speaks.
PROTOCOL_VERSION = "1"

#: Maximum size of one encoded request line, in bytes (excluding the
#: terminating newline).
MAX_REQUEST_LINE_BYTES = 64 * 1024

#: Maximum length of ``request_id`` in characters.
MAX_REQUEST_ID_CHARS = 128

#: Maximum length of ``payload`` in bytes.
MAX_PAYLOAD_BYTES = 1024 * 1024

#: The only message type supported by protocol v1.
MESSAGE_SUBMIT = "submit"
SUPPORTED_TYPES = frozenset({MESSAGE_SUBMIT})

#: Required request fields, in deterministic validation order.
REQUIRED_REQUEST_FIELDS = (
    "protocol_version",
    "request_id",
    "type",
    "capability_id",
    "payload",
)

#: Response fields that must always be present (values may be null).
REQUIRED_RESPONSE_FIELDS = (
    "protocol_version",
    "request_id",
    "host_kind",
    "accepted",
    "submission_status",
    "observation_status",
    "execution_status",
    "output",
    "error",
)


class ErrorCode:
    """Stable machine-readable error codes used in a response ``error``."""

    MALFORMED_JSON = "malformed-json"
    OVERSIZE_LINE = "oversize-line"
    MISSING_FIELD = "missing-field"
    INVALID_FIELD = "invalid-field"
    UNSUPPORTED_VERSION = "unsupported-version"
    UNSUPPORTED_TYPE = "unsupported-type"
    INVALID_REQUEST_ID = "invalid-request-id"
    PAYLOAD_TOO_LARGE = "payload-too-large"
    CAPABILITY_NOT_FOUND = "capability-not-found"
    CAPABILITY_INVOCATION_FAILED = "capability-invocation-failed"
    INTERNAL_ERROR = "internal-error"
    #: Client-side: the host returned a response envelope that violates v1.
    INVALID_RESPONSE = "invalid-response"


class SubmissionStatus:
    """Terminal submission outcome (mirrors the Kernel's submission status)."""

    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"

    ALL = frozenset({COMPLETED, REJECTED, FAILED})


class ObservationStatus:
    """Terminal observation outcome (mirrors the Kernel's observation status)."""

    SUCCESS = "success"
    FAILURE = "failure"

    ALL = frozenset({SUCCESS, FAILURE})


class HostKind:
    """Identifies which host produced a response."""

    #: The test-only stub host. Never Agent-Kernel execution.
    STUB = "stub"
    #: A host backed by the real Agent-Kernel runtime (Phase 3B-2+).
    KERNEL = "kernel"

    ALL = frozenset({STUB, KERNEL})


def is_non_blank(value: str) -> bool:
    """True when ``value`` contains at least one non-whitespace character."""

    return any(not ch.isspace() for ch in value)


# ----------------------------------------------------------------------
# Request
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Request:
    """A validated IPC v1 request."""

    request_id: str
    capability_id: str
    payload: str
    protocol_version: str = PROTOCOL_VERSION
    type: str = MESSAGE_SUBMIT

    def to_object(self) -> dict:
        """Return the on-the-wire JSON object for this request."""

        return {
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "type": self.type,
            "capability_id": self.capability_id,
            "payload": self.payload,
        }

    def to_line(self) -> str:
        """Return the compact single-line JSON encoding of this request."""

        return json.dumps(self.to_object(), separators=(",", ":"), ensure_ascii=False)


def validate_request_object(obj: Any) -> Request:
    """Validate an already-decoded request object.

    Raises :class:`ProtocolViolation` with a specific ``code`` on the first
    rule that fails. This performs value-level validation only; use
    :func:`parse_request_line` to also enforce the encoded line-size limit.
    """

    if not isinstance(obj, Mapping):
        raise ProtocolViolation(
            ErrorCode.INVALID_FIELD, "request must be a JSON object"
        )

    for field in REQUIRED_REQUEST_FIELDS:
        if field not in obj:
            raise ProtocolViolation(
                ErrorCode.MISSING_FIELD, f"missing required field: {field}"
            )

    version = obj["protocol_version"]
    if not isinstance(version, str):
        raise ProtocolViolation(
            ErrorCode.INVALID_FIELD, "protocol_version must be a string"
        )
    if version != PROTOCOL_VERSION:
        raise ProtocolViolation(
            ErrorCode.UNSUPPORTED_VERSION,
            f"unsupported protocol_version: {version!r}",
        )

    request_id = obj["request_id"]
    if not isinstance(request_id, str):
        raise ProtocolViolation(
            ErrorCode.INVALID_FIELD, "request_id must be a string"
        )
    if len(request_id) > MAX_REQUEST_ID_CHARS:
        raise ProtocolViolation(
            ErrorCode.INVALID_REQUEST_ID,
            f"request_id exceeds {MAX_REQUEST_ID_CHARS} characters",
        )
    if not is_non_blank(request_id):
        raise ProtocolViolation(
            ErrorCode.INVALID_REQUEST_ID,
            "request_id must be non-empty and non-blank",
        )

    message_type = obj["type"]
    if not isinstance(message_type, str):
        raise ProtocolViolation(ErrorCode.INVALID_FIELD, "type must be a string")
    if message_type not in SUPPORTED_TYPES:
        raise ProtocolViolation(
            ErrorCode.UNSUPPORTED_TYPE, f"unsupported type: {message_type!r}"
        )

    capability_id = obj["capability_id"]
    if not isinstance(capability_id, str):
        raise ProtocolViolation(
            ErrorCode.INVALID_FIELD, "capability_id must be a string"
        )
    if not is_non_blank(capability_id):
        raise ProtocolViolation(
            ErrorCode.INVALID_FIELD, "capability_id must be non-empty and non-blank"
        )

    payload = obj["payload"]
    if not isinstance(payload, str):
        raise ProtocolViolation(ErrorCode.INVALID_FIELD, "payload must be a string")
    if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ProtocolViolation(
            ErrorCode.PAYLOAD_TOO_LARGE,
            f"payload exceeds {MAX_PAYLOAD_BYTES} bytes",
        )
    if not is_non_blank(payload):
        # The Kernel adapter rejects a blank payload before execution; the
        # protocol rejects it at the envelope boundary for the same reason.
        raise ProtocolViolation(
            ErrorCode.INVALID_FIELD, "payload must be non-empty and non-blank"
        )

    return Request(
        request_id=request_id,
        capability_id=capability_id,
        payload=payload,
        protocol_version=version,
        type=message_type,
    )


def parse_request_line(text: str) -> Request:
    """Validate a decoded (newline-stripped) request line.

    Enforces the encoded line-size limit first, then the envelope rules.
    Malformed input is rejected here and therefore never reaches any
    execution path.
    """

    if len(text.encode("utf-8")) > MAX_REQUEST_LINE_BYTES:
        raise ProtocolViolation(
            ErrorCode.OVERSIZE_LINE,
            f"request line exceeds {MAX_REQUEST_LINE_BYTES} bytes",
        )
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolViolation(
            ErrorCode.MALFORMED_JSON, f"invalid JSON: {exc.msg}"
        ) from exc
    return validate_request_object(obj)


def peek_request_id(text: str) -> Optional[str]:
    """Best-effort extraction of a valid ``request_id`` from raw input.

    Used only to echo an identity on an error response when full validation
    failed. Returns ``None`` when no usable identity can be recovered.
    """

    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, Mapping):
        return None
    request_id = obj.get("request_id")
    if (
        isinstance(request_id, str)
        and len(request_id) <= MAX_REQUEST_ID_CHARS
        and is_non_blank(request_id)
    ):
        return request_id
    return None


# ----------------------------------------------------------------------
# Response
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Response:
    """A validated IPC v1 response."""

    request_id: Optional[str]
    host_kind: str
    accepted: bool
    submission_status: Optional[str]
    observation_status: Optional[str]
    execution_status: Optional[str]
    output: Optional[str]
    error: Optional[Mapping[str, str]]
    protocol_version: str = PROTOCOL_VERSION

    @property
    def ok(self) -> bool:
        """True when the request reached a terminal success outcome."""

        return (
            self.accepted
            and self.submission_status == SubmissionStatus.COMPLETED
            and self.observation_status == ObservationStatus.SUCCESS
        )


def build_response(
    *,
    request_id: Optional[str],
    accepted: bool = False,
    submission_status: Optional[str] = None,
    observation_status: Optional[str] = None,
    execution_status: Optional[str] = None,
    output: Optional[str] = None,
    error: Optional[Mapping[str, str]] = None,
    host_kind: str = HostKind.STUB,
) -> dict:
    """Build a complete response object (all v1 keys present)."""

    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "host_kind": host_kind,
        "accepted": accepted,
        "submission_status": submission_status,
        "observation_status": observation_status,
        "execution_status": execution_status,
        "output": output,
        "error": dict(error) if error is not None else None,
    }


def error_response(
    request_id: Optional[str],
    code: str,
    message: str,
    *,
    accepted: bool = False,
    submission_status: Optional[str] = None,
    observation_status: Optional[str] = None,
    execution_status: Optional[str] = None,
    host_kind: str = HostKind.STUB,
) -> dict:
    """Build an error response (no ``output``)."""

    return build_response(
        request_id=request_id,
        accepted=accepted,
        submission_status=submission_status,
        observation_status=observation_status,
        execution_status=execution_status,
        output=None,
        error={"code": code, "message": message},
        host_kind=host_kind,
    )


def parse_response_line(text: str) -> Response:
    """Validate a decoded (newline-stripped) response line.

    Raises :class:`ProtocolViolation` with code
    :data:`ErrorCode.INVALID_RESPONSE` when the host returned an envelope the
    client does not understand.
    """

    def bad(message: str) -> ProtocolViolation:
        return ProtocolViolation(ErrorCode.INVALID_RESPONSE, message)

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise bad(f"response is not valid JSON: {exc.msg}") from exc
    if not isinstance(obj, Mapping):
        raise bad("response must be a JSON object")
    for field in REQUIRED_RESPONSE_FIELDS:
        if field not in obj:
            raise bad(f"response missing required field: {field}")

    version = obj["protocol_version"]
    if version != PROTOCOL_VERSION:
        raise bad(f"unexpected response protocol_version: {version!r}")

    request_id = obj["request_id"]
    if request_id is not None and not isinstance(request_id, str):
        raise bad("response request_id must be a string or null")

    if obj["host_kind"] not in HostKind.ALL:
        raise bad(f"unknown host_kind: {obj['host_kind']!r}")

    if not isinstance(obj["accepted"], bool):
        raise bad("response accepted must be a boolean")

    submission_status = obj["submission_status"]
    if submission_status is not None and submission_status not in SubmissionStatus.ALL:
        raise bad(f"unknown submission_status: {submission_status!r}")

    observation_status = obj["observation_status"]
    if (
        observation_status is not None
        and observation_status not in ObservationStatus.ALL
    ):
        raise bad(f"unknown observation_status: {observation_status!r}")

    execution_status = obj["execution_status"]
    if execution_status is not None and not isinstance(execution_status, str):
        raise bad("response execution_status must be a string or null")

    output = obj["output"]
    if output is not None and not isinstance(output, str):
        raise bad("response output must be a string or null")

    error = obj["error"]
    if error is not None:
        if (
            not isinstance(error, Mapping)
            or not isinstance(error.get("code"), str)
            or not isinstance(error.get("message"), str)
        ):
            raise bad("response error must be null or {code, message} strings")

    return Response(
        request_id=request_id,
        host_kind=obj["host_kind"],
        accepted=obj["accepted"],
        submission_status=submission_status,
        observation_status=observation_status,
        execution_status=execution_status,
        output=output,
        error=error,
        protocol_version=version,
    )


__all__ = [
    "PROTOCOL_VERSION",
    "MAX_REQUEST_LINE_BYTES",
    "MAX_REQUEST_ID_CHARS",
    "MAX_PAYLOAD_BYTES",
    "MESSAGE_SUBMIT",
    "SUPPORTED_TYPES",
    "REQUIRED_REQUEST_FIELDS",
    "REQUIRED_RESPONSE_FIELDS",
    "ErrorCode",
    "SubmissionStatus",
    "ObservationStatus",
    "HostKind",
    "Request",
    "Response",
    "is_non_blank",
    "validate_request_object",
    "parse_request_line",
    "peek_request_id",
    "build_response",
    "error_response",
    "parse_response_line",
]
