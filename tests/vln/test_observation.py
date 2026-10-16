"""Offline tests for host-feedback observation encoding (:mod:`vln.observation`).

These tests exercise only the encoding boundary. No model, weights, network,
GPU or host is involved: the point under test is the deterministic conversion of
a real :class:`~vln.ipc.envelope.Response` into model input and the explicit
type dispatch around it. A passing run here is NOT a claim that ZDTaichu5.0-9B
runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from vln.ipc.envelope import (
    ErrorCode,
    HostKind,
    ObservationStatus,
    Response,
    SubmissionStatus,
)
from vln.observation import (
    MAX_FEEDBACK_TEXT_CHARS,
    CompositeObservationEncoder,
    ResponseFeedbackEncoder,
)
from vln.vlm import (
    DefaultObservationEncoder,
    ModelCallError,
    ObservationEncoder,
    PreparedObservation,
    UnsupportedObservationError,
)

_FIELD_ORDER = (
    "protocol_version",
    "request_id",
    "host_kind",
    "accepted",
    "submission_status",
    "observation_status",
    "execution_status",
    "ok",
    "output",
    "error",
    "truncated",
)


def _response(**overrides) -> Response:
    base: dict = {
        "request_id": "req-1",
        "host_kind": HostKind.KERNEL,
        "accepted": True,
        "submission_status": SubmissionStatus.COMPLETED,
        "observation_status": ObservationStatus.SUCCESS,
        "execution_status": "completed",
        "output": '{"target":{"x":1.0}}',
        "error": None,
    }
    base.update(overrides)
    return Response(**base)


# ----------------------------------------------------------------------
# ResponseFeedbackEncoder
# ----------------------------------------------------------------------


def test_approved_text_cap_is_4096() -> None:
    assert MAX_FEEDBACK_TEXT_CHARS == 4096


def test_feedback_encoder_rejects_non_response_inputs() -> None:
    encoder = ResponseFeedbackEncoder()
    for bad in ("a scene", 42, {"scene": "structured"}, None):
        with pytest.raises(UnsupportedObservationError) as exc:
            encoder.encode(bad)
        assert exc.value.observation_type == type(bad).__name__


def test_encoded_feedback_is_deterministic_compact_json() -> None:
    response = _response()
    encoder = ResponseFeedbackEncoder()

    text = encoder.encode(response).text
    assert text == encoder.encode(response).text  # deterministic
    assert ", " not in text and '": ' not in text  # compact separators

    parsed = json.loads(text)  # parsable, fixed field order
    assert tuple(parsed) == _FIELD_ORDER


def test_encoded_values_come_from_the_real_response() -> None:
    response = _response(
        accepted=False,
        submission_status=SubmissionStatus.FAILED,
        observation_status=ObservationStatus.FAILURE,
        execution_status="failed",
        output=None,
        error={
            "code": ErrorCode.CAPABILITY_INVOCATION_FAILED,
            "message": "capability-invocation-failed:parking.move",
        },
    )

    parsed = json.loads(ResponseFeedbackEncoder().encode(response).text)

    assert parsed["protocol_version"] == "1"
    assert parsed["request_id"] == "req-1"
    assert parsed["host_kind"] == "kernel"
    assert parsed["accepted"] is False
    assert parsed["submission_status"] == "failed"
    assert parsed["observation_status"] == "failure"
    assert parsed["execution_status"] == "failed"
    assert parsed["ok"] is False
    assert parsed["output"] is None
    assert parsed["error"] == {
        "code": "capability-invocation-failed",
        "message": "capability-invocation-failed:parking.move",
    }
    assert parsed["truncated"] == {}


def test_a_response_is_never_encoded_as_an_image() -> None:
    prepared = ResponseFeedbackEncoder().encode(_response())
    assert isinstance(prepared, PreparedObservation)
    assert prepared.images == ()


# ----------------------------------------------------------------------
# Existing default-encoder behaviour is unchanged
# ----------------------------------------------------------------------


def test_str_and_image_keep_their_existing_default_behaviour() -> None:
    assert DefaultObservationEncoder().encode("scene text").text == "scene text"

    pil_image = pytest.importorskip("PIL.Image")
    frame = pil_image.new("RGB", (2, 2))
    prepared = DefaultObservationEncoder().encode(frame)
    assert prepared.images == (frame,)
    assert prepared.text == ""


def test_default_encoder_still_rejects_unsupported_types_including_response() -> None:
    encoder = DefaultObservationEncoder()
    with pytest.raises(UnsupportedObservationError) as exc:
        encoder.encode({"scene": "structured"})
    assert exc.value.observation_type == "dict"

    # The new feature does not widen the default encoder: a Response is still
    # not a default-encoder input.
    with pytest.raises(UnsupportedObservationError):
        encoder.encode(_response())


# ----------------------------------------------------------------------
# CompositeObservationEncoder: explicit dispatch
# ----------------------------------------------------------------------


def test_composite_dispatches_str_to_the_default_encoder() -> None:
    assert CompositeObservationEncoder().encode("scene text").text == "scene text"


def test_composite_dispatches_response_to_the_feedback_encoder() -> None:
    response = _response()
    expected = ResponseFeedbackEncoder().encode(response)
    assert CompositeObservationEncoder().encode(response) == expected


def test_composite_dispatches_supported_pil_image() -> None:
    pil_image = pytest.importorskip("PIL.Image")
    frame = pil_image.new("RGB", (2, 2))

    prepared = CompositeObservationEncoder().encode(frame)

    assert prepared.images == (frame,)
    assert prepared.text == ""


def test_composite_routes_unknown_objects_to_the_unsupported_path() -> None:
    encoder = CompositeObservationEncoder()
    for bad, expected_name in (({"scene": "x"}, "dict"), (object(), "object")):
        with pytest.raises(UnsupportedObservationError) as exc:
            encoder.encode(bad)
        assert exc.value.observation_type == expected_name


def test_both_encoders_satisfy_the_observation_encoder_protocol() -> None:
    assert isinstance(ResponseFeedbackEncoder(), ObservationEncoder)
    assert isinstance(CompositeObservationEncoder(), ObservationEncoder)


# ----------------------------------------------------------------------
# Truncation policy (approved: 4096 chars, free text only)
# ----------------------------------------------------------------------


def test_long_output_is_truncated_and_explicitly_annotated() -> None:
    long_output = "x" * (MAX_FEEDBACK_TEXT_CHARS + 100)

    parsed = json.loads(
        ResponseFeedbackEncoder().encode(_response(output=long_output)).text
    )

    assert parsed["output"] == long_output[:MAX_FEEDBACK_TEXT_CHARS]
    assert len(parsed["output"]) == MAX_FEEDBACK_TEXT_CHARS
    assert parsed["truncated"] == {"output": len(long_output)}
    # Status fields are kept intact and are never listed as truncated.
    assert parsed["submission_status"] == "completed"
    assert parsed["observation_status"] == "success"
    assert "submission_status" not in parsed["truncated"]


def test_long_error_message_is_truncated_but_error_code_is_not() -> None:
    long_message = "e" * (MAX_FEEDBACK_TEXT_CHARS + 7)
    response = _response(
        output=None,
        error={"code": ErrorCode.INTERNAL_ERROR, "message": long_message},
    )

    parsed = json.loads(ResponseFeedbackEncoder().encode(response).text)

    assert parsed["error"]["code"] == "internal-error"  # machine code untouched
    assert len(parsed["error"]["message"]) == MAX_FEEDBACK_TEXT_CHARS
    assert parsed["truncated"] == {"error.message": len(long_message)}


def test_short_free_text_is_not_annotated() -> None:
    parsed = json.loads(ResponseFeedbackEncoder().encode(_response(output="short")).text)
    assert parsed["output"] == "short"
    assert parsed["truncated"] == {}


# ----------------------------------------------------------------------
# Fail-closed: malformed feedback is never a fabricated success
# ----------------------------------------------------------------------


def test_malformed_field_types_fail_closed() -> None:
    encoder = ResponseFeedbackEncoder()
    bad_responses = (
        _response(output=123),
        _response(accepted="yes"),
        _response(request_id=5),
        _response(error={"code": 1, "message": "m"}),
        _response(error={"code": "c", "message": 2}),
        _response(error="boom"),
    )
    for response in bad_responses:
        with pytest.raises(ModelCallError):
            encoder.encode(response)


def test_unsupported_observation_error_is_a_model_call_error() -> None:
    # So the pipeline's existing fail-closed handling applies unchanged.
    assert issubclass(UnsupportedObservationError, ModelCallError)


def test_module_pulls_in_no_inference_stack_host_or_pillow() -> None:
    """Structural proof: importing the encoder loads no model stack or Pillow."""

    src_root = Path(__file__).resolve().parents[2] / "src"
    code = (
        "import sys, vln.observation as m;"
        "forbidden = [x for x in ('torch', 'transformers') if x in sys.modules];"
        "assert not forbidden, f'inference deps imported: {forbidden}';"
        "assert 'PIL' not in sys.modules, 'Pillow imported at module import';"
        "assert 'vln.client' not in sys.modules, 'encoder imports vln.client';"
        "assert callable(getattr(m, 'ResponseFeedbackEncoder'));"
        "assert callable(getattr(m, 'CompositeObservationEncoder'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(src_root)},
    )
    assert result.returncode == 0, result.stderr
