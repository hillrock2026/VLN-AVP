"""Tests for the model-output adapter (:mod:`vln.intent.model_output`).

These are pure Python unit tests: model output is a string, the adapter turns
it into a validated ``AgentIntent`` or raises, and nothing here spawns a host,
a model or a GPU. The tests are deliberately layered so a failure says *which*
boundary rejected the input:

* parse-layer   -> :class:`ModelOutputParseError`;
* shape-layer   -> :class:`ModelOutputShapeError`;
* validator-layer -> :class:`ModelOutputValidationError`.

The last case is delegated to the authoritative ``AgentIntent`` validator, so
those tests also assert the chain back to the underlying ``AgentIntentError``.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from vln.intent import (
    AgentIntent,
    AgentIntentError,
    AgentIntentValidationError,
    ModelOutputError,
    ModelOutputParseError,
    ModelOutputShapeError,
    ModelOutputValidationError,
    Target,
    parse_model_output,
)
from vln.ipc import envelope
from vln.ipc.envelope import Request

_ACTION = "parking.move"


def _object(**overrides: object) -> dict:
    obj = {
        "contract_version": "1",
        "intent_id": "intent-0001",
        "action": _ACTION,
        "target": {"x": 1.5, "y": -2.25, "heading": 0.5},
    }
    obj.update(overrides)
    return obj


def _text(**overrides: object) -> str:
    return json.dumps(_object(**overrides))


# ----------------------------------------------------------------------
# Legal model output
# ----------------------------------------------------------------------


def test_valid_output_builds_a_validated_agent_intent() -> None:
    intent = parse_model_output(_text())
    assert isinstance(intent, AgentIntent)
    assert intent.contract_version == "1"
    assert intent.action == _ACTION
    assert intent.intent_id == "intent-0001"
    assert intent.target == Target(x=1.5, y=-2.25, heading=0.5)


def test_output_has_no_extra_or_implicit_fields() -> None:
    intent = parse_model_output(_text())
    assert set(intent.to_object()) == {
        "contract_version",
        "intent_id",
        "action",
        "target",
    }
    assert set(intent.target.to_object()) == {"x", "y", "heading"}


def test_heading_is_normalized_by_the_authoritative_api() -> None:
    # The adapter does not normalize; the AgentIntent/Target API does.
    intent = parse_model_output(_text(target={"x": 0.0, "y": 0.0, "heading": math.pi}))
    assert intent.target.heading == -math.pi


def test_legal_output_round_trips_through_agent_intent() -> None:
    intent = parse_model_output(_text())
    assert AgentIntent.from_payload(intent.to_payload()) == intent


def test_surrounding_whitespace_is_tolerated() -> None:
    # Whitespace padding a single JSON object is not a non-standard wrapper.
    intent = parse_model_output("\n  " + _text() + "\t\n ")
    assert intent.intent_id == "intent-0001"


# ----------------------------------------------------------------------
# Parse-layer rejection (text is not a well-formed JSON object)
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("", id="empty"),
        pytest.param("   \n\t ", id="blank"),
        pytest.param("{not json", id="malformed"),
        pytest.param('{"contract_version":"1","intent_id":"i"', id="truncated"),
        pytest.param("[1, 2, 3]", id="top-level-array"),
        pytest.param('"a string"', id="top-level-string"),
        pytest.param("123", id="top-level-number"),
        pytest.param("null", id="top-level-null"),
        pytest.param("true", id="top-level-bool"),
        pytest.param('{"a":1} {"b":2}', id="two-json-objects"),
        pytest.param("```json\n" + _text() + "\n```", id="markdown-fenced"),
        pytest.param("Here is the intent: " + _text(), id="prose-prefix"),
        pytest.param(_text() + " done", id="prose-suffix"),
        pytest.param(
            '{"contract_version":"1","contract_version":"1","intent_id":"i",'
            '"action":"parking.move","target":{"x":1.0,"y":2.0,"heading":0.0}}',
            id="duplicate-top-level-key",
        ),
        pytest.param(
            '{"contract_version":"1","intent_id":"i","action":"parking.move",'
            '"target":{"x":1.0,"x":2.0,"heading":0.0}}',
            id="duplicate-target-key",
        ),
        pytest.param(
            '{"contract_version":"1","intent_id":"i","action":"parking.move",'
            '"target":{"x":NaN,"y":2.0,"heading":0.0}}',
            id="nan-constant",
        ),
        pytest.param(
            '{"contract_version":"1","intent_id":"i","action":"parking.move",'
            '"target":{"x":Infinity,"y":2.0,"heading":0.0}}',
            id="infinity-constant",
        ),
    ],
)
def test_parse_layer_rejects_non_object_or_non_standard_text(raw: str) -> None:
    with pytest.raises(ModelOutputParseError) as exc:
        parse_model_output(raw)
    # Distinct from the shape and validator layers.
    assert not isinstance(exc.value, ModelOutputShapeError)
    assert not isinstance(exc.value, ModelOutputValidationError)


def test_non_string_input_is_a_parse_error() -> None:
    with pytest.raises(ModelOutputParseError):
        parse_model_output(b'{"contract_version":"1"}')  # type: ignore[arg-type]


def test_duplicate_key_is_not_silently_resolved() -> None:
    # json.loads would otherwise keep the last value; the adapter fails closed.
    raw = (
        '{"contract_version":"1","intent_id":"i","action":"parking.stop",'
        '"action":"parking.move","target":{"x":1.0,"y":2.0,"heading":0.0}}'
    )
    with pytest.raises(ModelOutputParseError):
        parse_model_output(raw)


# ----------------------------------------------------------------------
# Shape-layer rejection (object, but wrong top-level field set)
# ----------------------------------------------------------------------


@pytest.mark.parametrize("field", ["contract_version", "intent_id", "action", "target"])
def test_shape_layer_rejects_missing_top_level_field(field: str) -> None:
    obj = _object()
    del obj[field]
    with pytest.raises(ModelOutputShapeError) as exc:
        parse_model_output(json.dumps(obj))
    assert not isinstance(exc.value, ModelOutputParseError)
    assert not isinstance(exc.value, ModelOutputValidationError)


def test_shape_layer_rejects_unknown_top_level_field() -> None:
    with pytest.raises(ModelOutputShapeError):
        parse_model_output(json.dumps({**_object(), "confidence": 0.9}))


def test_shape_layer_rejects_empty_object() -> None:
    with pytest.raises(ModelOutputShapeError):
        parse_model_output("{}")


# ----------------------------------------------------------------------
# Validator-layer rejection (delegated to the authoritative AgentIntent API)
# ----------------------------------------------------------------------

_INVALID_CONTENT = [
    pytest.param(_text(contract_version="2"), id="unknown-contract-version"),
    pytest.param(_text(contract_version=1), id="contract-version-not-string"),
    pytest.param(_text(contract_version=True), id="contract-version-bool"),
    pytest.param(_text(contract_version=None), id="contract-version-null"),
    pytest.param(_text(action="parking.stop"), id="unknown-action"),
    pytest.param(_text(action=1), id="action-not-string"),
    pytest.param(_text(intent_id=""), id="empty-intent-id"),
    pytest.param(_text(intent_id="   "), id="blank-intent-id"),
    pytest.param(_text(intent_id="i" * 129), id="oversize-intent-id"),
    pytest.param(_text(intent_id=123), id="intent-id-not-string"),
    pytest.param(_text(target=5), id="target-not-object"),
    pytest.param(_text(target={"x": 1.0, "y": 2.0}), id="target-missing-heading"),
    pytest.param(
        _text(target={"x": 1.0, "y": 2.0, "heading": 0.0, "z": 0.0}),
        id="target-unknown-field",
    ),
    pytest.param(_text(target={"x": True, "y": 2.0, "heading": 0.0}), id="x-bool"),
    pytest.param(_text(target={"x": "1.0", "y": 2.0, "heading": 0.0}), id="x-string"),
    pytest.param(_text(target={"x": None, "y": 2.0, "heading": 0.0}), id="x-null"),
    pytest.param(
        '{"contract_version":"1","intent_id":"i","action":"parking.move",'
        '"target":{"x":1e999,"y":2.0,"heading":0.0}}',
        id="x-overflow-to-infinity",
    ),
]


@pytest.mark.parametrize("raw", _INVALID_CONTENT)
def test_validator_layer_rejects_invalid_content(raw: str) -> None:
    with pytest.raises(ModelOutputValidationError) as exc:
        parse_model_output(raw)
    assert not isinstance(exc.value, ModelOutputParseError)
    assert not isinstance(exc.value, ModelOutputShapeError)
    # Delegation evidence: the authoritative AgentIntent error is chained.
    assert isinstance(exc.value.__cause__, AgentIntentError)


def test_validator_rejection_chains_the_specific_agent_intent_error() -> None:
    with pytest.raises(ModelOutputValidationError) as exc:
        parse_model_output(_text(action="parking.stop"))
    assert isinstance(exc.value.__cause__, AgentIntentValidationError)


# ----------------------------------------------------------------------
# Error taxonomy and caller boundary
# ----------------------------------------------------------------------


def test_error_hierarchy() -> None:
    for error in (
        ModelOutputParseError,
        ModelOutputShapeError,
        ModelOutputValidationError,
    ):
        assert issubclass(error, ModelOutputError)
        assert issubclass(error, AgentIntentError)


def test_failure_returns_no_intent() -> None:
    # A failing conversion has no value; a caller cannot accidentally use an
    # unvalidated object as an AgentIntent.
    with pytest.raises(ModelOutputError):
        parse_model_output('{"action":"parking.move"}')


def test_success_is_a_pure_intent_value_not_a_submission() -> None:
    intent = parse_model_output(_text())
    assert isinstance(intent, AgentIntent)
    # The adapter returns an intent value only; it has no host/IPC dependency,
    # so a successful parse cannot have submitted or executed anything.
    assert not isinstance(intent, envelope.Response)


def test_intent_id_round_trips_independently_of_ipc_request_id() -> None:
    intent = parse_model_output(_text(intent_id="intent-abc"))
    request = Request(
        request_id="req-xyz",
        capability_id=intent.action,
        payload=intent.to_payload(),
    )
    parsed = envelope.parse_request_line(request.to_line())
    assert parsed.request_id == "req-xyz"
    assert parsed.request_id != intent.intent_id
    assert AgentIntent.from_payload(parsed.payload).intent_id == "intent-abc"


def test_adapter_module_has_no_host_client_dependency() -> None:
    """Structural proof that a parse cannot reach a host process.

    A fresh interpreter imports only the adapter; ``vln.client`` (the only way
    to spawn the Host) must not be pulled in, so no code path can submit.
    """

    src_root = Path(__file__).resolve().parents[2] / "src"
    code = (
        "import sys, vln.intent.model_output as m;"
        "assert 'vln.client' not in sys.modules, 'adapter imports vln.client';"
        "assert callable(m.parse_model_output)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(src_root)},
    )
    assert result.returncode == 0, result.stderr
