"""Unit tests for the IPC v1 envelope (no subprocess involved)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vln.ipc import envelope
from vln.ipc.envelope import (
    ErrorCode,
    HostKind,
    ObservationStatus,
    ProtocolViolation,
    Request,
    SubmissionStatus,
)


def _valid_object() -> dict:
    return {
        "protocol_version": "1",
        "request_id": "r-1",
        "type": "submit",
        "capability_id": "test.echo",
        "payload": "hello",
    }


def test_valid_request_roundtrip() -> None:
    request = Request(request_id="r-1", capability_id="test.echo", payload="hello")
    parsed = envelope.parse_request_line(request.to_line())
    assert parsed == request


@pytest.mark.parametrize("field", envelope.REQUIRED_REQUEST_FIELDS)
def test_missing_required_field(field: str) -> None:
    obj = _valid_object()
    del obj[field]
    with pytest.raises(ProtocolViolation) as exc:
        envelope.validate_request_object(obj)
    assert exc.value.code == ErrorCode.MISSING_FIELD


def test_unsupported_protocol_version() -> None:
    obj = _valid_object()
    obj["protocol_version"] = "2"
    with pytest.raises(ProtocolViolation) as exc:
        envelope.validate_request_object(obj)
    assert exc.value.code == ErrorCode.UNSUPPORTED_VERSION


def test_unknown_message_type() -> None:
    obj = _valid_object()
    obj["type"] = "frobnicate"
    with pytest.raises(ProtocolViolation) as exc:
        envelope.validate_request_object(obj)
    assert exc.value.code == ErrorCode.UNSUPPORTED_TYPE


def test_malformed_json() -> None:
    with pytest.raises(ProtocolViolation) as exc:
        envelope.parse_request_line("{not json")
    assert exc.value.code == ErrorCode.MALFORMED_JSON


def test_oversize_line() -> None:
    text = "x" * (envelope.MAX_REQUEST_LINE_BYTES + 1)
    with pytest.raises(ProtocolViolation) as exc:
        envelope.parse_request_line(text)
    assert exc.value.code == ErrorCode.OVERSIZE_LINE


def test_payload_too_large() -> None:
    obj = _valid_object()
    obj["payload"] = "x" * (envelope.MAX_PAYLOAD_BYTES + 1)
    with pytest.raises(ProtocolViolation) as exc:
        envelope.validate_request_object(obj)
    assert exc.value.code == ErrorCode.PAYLOAD_TOO_LARGE


def test_blank_payload_rejected() -> None:
    obj = _valid_object()
    obj["payload"] = "   "
    with pytest.raises(ProtocolViolation) as exc:
        envelope.validate_request_object(obj)
    assert exc.value.code == ErrorCode.INVALID_FIELD


def test_request_id_too_long() -> None:
    obj = _valid_object()
    obj["request_id"] = "r" * (envelope.MAX_REQUEST_ID_CHARS + 1)
    with pytest.raises(ProtocolViolation) as exc:
        envelope.validate_request_object(obj)
    assert exc.value.code == ErrorCode.INVALID_REQUEST_ID


def test_request_must_be_object() -> None:
    with pytest.raises(ProtocolViolation) as exc:
        envelope.validate_request_object([1, 2, 3])
    assert exc.value.code == ErrorCode.INVALID_FIELD


def test_peek_request_id() -> None:
    assert envelope.peek_request_id('{"request_id":"abc"}') == "abc"
    assert envelope.peek_request_id('{"request_id":"   "}') is None
    assert envelope.peek_request_id("not json") is None
    assert envelope.peek_request_id("[1,2]") is None


def test_response_roundtrip() -> None:
    obj = envelope.build_response(
        request_id="r-1",
        accepted=True,
        submission_status=SubmissionStatus.COMPLETED,
        observation_status=ObservationStatus.SUCCESS,
        output="out",
        host_kind=HostKind.STUB,
    )
    response = envelope.parse_response_line(json.dumps(obj))
    assert response.request_id == "r-1"
    assert response.ok is True
    assert response.output == "out"
    assert response.host_kind == HostKind.STUB


def test_response_missing_field_is_invalid() -> None:
    with pytest.raises(ProtocolViolation) as exc:
        envelope.parse_response_line('{"protocol_version":"1"}')
    assert exc.value.code == ErrorCode.INVALID_RESPONSE


def test_response_bad_submission_status_is_invalid() -> None:
    obj = envelope.build_response(request_id="r")
    obj["submission_status"] = "exploded"
    with pytest.raises(ProtocolViolation) as exc:
        envelope.parse_response_line(json.dumps(obj))
    assert exc.value.code == ErrorCode.INVALID_RESPONSE


def test_response_unknown_host_kind_is_invalid() -> None:
    obj = envelope.build_response(request_id="r")
    obj["host_kind"] = "mystery"
    with pytest.raises(ProtocolViolation) as exc:
        envelope.parse_response_line(json.dumps(obj))
    assert exc.value.code == ErrorCode.INVALID_RESPONSE


def test_response_not_json_is_invalid() -> None:
    with pytest.raises(ProtocolViolation) as exc:
        envelope.parse_response_line("this is not json")
    assert exc.value.code == ErrorCode.INVALID_RESPONSE


def test_error_response_shape() -> None:
    obj = envelope.error_response(None, ErrorCode.OVERSIZE_LINE, "too big")
    response = envelope.parse_response_line(json.dumps(obj))
    assert response.request_id is None
    assert response.error == {"code": "oversize-line", "message": "too big"}


def test_schema_file_is_valid_json_and_defines_both_shapes() -> None:
    schema_path = (
        Path(__file__).resolve().parents[2] / "protocol" / "v1" / "envelope.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$defs"]["request"]["properties"]["protocol_version"]["const"] == "1"
    assert set(schema["$defs"]["response"]["required"]) == set(
        envelope.REQUIRED_RESPONSE_FIELDS
    )
