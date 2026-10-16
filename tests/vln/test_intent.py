"""Contract tests for the AgentIntent v1 data model (no subprocess involved).

Covers, in order, the 14 required cases in
``docs/decisions/M1-03B0_AGENT_INTENT_V1_DECISIONS.md`` section 11.2, plus a
few supporting checks (failure-class separation, the frozen action/capability
binding). Every test asserts concrete outcomes rather than merely "did not
raise".
"""

from __future__ import annotations

import json
import math

import pytest

from vln.intent import (
    ACTION_PARKING_MOVE,
    CONTRACT_VERSION,
    MAX_INTENT_ID_CHARS,
    AgentIntent,
    AgentIntentError,
    AgentIntentParseError,
    AgentIntentSerializationError,
    AgentIntentValidationError,
    Target,
)
from vln.ipc import envelope
from vln.ipc.envelope import Request

_ACTION = "parking.move"


def _target_kwargs() -> dict:
    return {"x": 1.5, "y": -2.25, "heading": 0.0}


def _intent(**overrides) -> AgentIntent:
    fields: dict = {"intent_id": "intent-0001", "target": Target(**_target_kwargs())}
    fields.update(overrides)
    return AgentIntent(**fields)


def _payload_object() -> dict:
    return {
        "contract_version": "1",
        "intent_id": "intent-0001",
        "action": "parking.move",
        "target": {"x": 1.5, "y": -2.25, "heading": 0.0},
    }


# ----------------------------------------------------------------------
# Item 1 - valid construction and serialization
# ----------------------------------------------------------------------


def test_1_valid_construction_and_serialization() -> None:
    intent = _intent()
    assert intent.contract_version == CONTRACT_VERSION == "1"
    assert intent.intent_id == "intent-0001"
    assert intent.action == ACTION_PARKING_MOVE == _ACTION
    assert intent.target == Target(x=1.5, y=-2.25, heading=0.0)
    assert intent.to_payload() == (
        '{"contract_version":"1","intent_id":"intent-0001",'
        '"action":"parking.move","target":{"x":1.5,"y":-2.25,"heading":0.0}}'
    )


# ----------------------------------------------------------------------
# Item 2 - parse and round-trip consistency
# ----------------------------------------------------------------------


def test_2_parse_and_roundtrip() -> None:
    original = _intent()
    reparsed = AgentIntent.from_payload(original.to_payload())
    assert reparsed == original

    from_documented_example = AgentIntent.from_payload(json.dumps(_payload_object()))
    assert from_documented_example == original


# ----------------------------------------------------------------------
# Item 3 - missing required fields (parameterized per field)
# ----------------------------------------------------------------------


@pytest.mark.parametrize("field", ["contract_version", "intent_id", "action", "target"])
def test_3_missing_top_level_field(field: str) -> None:
    obj = _payload_object()
    del obj[field]
    with pytest.raises(AgentIntentValidationError):
        AgentIntent.from_payload(json.dumps(obj))


@pytest.mark.parametrize("field", ["x", "y", "heading"])
def test_3_missing_target_field(field: str) -> None:
    obj = _payload_object()
    del obj["target"][field]
    with pytest.raises(AgentIntentValidationError):
        AgentIntent.from_payload(json.dumps(obj))


# ----------------------------------------------------------------------
# Item 4 - unknown fields are rejected
# ----------------------------------------------------------------------


def test_4_unknown_top_level_field() -> None:
    obj = _payload_object()
    obj["velocity"] = 1.0
    with pytest.raises(AgentIntentValidationError):
        AgentIntent.from_payload(json.dumps(obj))


def test_4_unknown_target_field() -> None:
    obj = _payload_object()
    obj["target"]["z"] = 0.0
    with pytest.raises(AgentIntentValidationError):
        AgentIntent.from_payload(json.dumps(obj))


# ----------------------------------------------------------------------
# Item 5 - unknown action is rejected
# ----------------------------------------------------------------------


def test_5_unknown_action_rejected() -> None:
    obj = _payload_object()
    obj["action"] = "parking.stop"
    with pytest.raises(AgentIntentValidationError):
        AgentIntent.from_payload(json.dumps(obj))
    with pytest.raises(AgentIntentValidationError):
        _intent(action="parking.stop")


# ----------------------------------------------------------------------
# Item 6 - wrong contract_version type or value is rejected
# ----------------------------------------------------------------------


@pytest.mark.parametrize("bad", [1, True, None, "2", "1.0", ""])
def test_6_bad_contract_version_rejected(bad: object) -> None:
    obj = _payload_object()
    obj["contract_version"] = bad
    with pytest.raises(AgentIntentValidationError):
        AgentIntent.from_payload(json.dumps(obj))
    with pytest.raises(AgentIntentValidationError):
        _intent(contract_version=bad)


# ----------------------------------------------------------------------
# Item 7 - blank / invalid / oversize intent_id is rejected
# ----------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", " ", "\t\n ", "   \u00a0"])
def test_7_blank_intent_id_rejected(bad: str) -> None:
    obj = _payload_object()
    obj["intent_id"] = bad
    with pytest.raises(AgentIntentValidationError):
        AgentIntent.from_payload(json.dumps(obj))
    with pytest.raises(AgentIntentValidationError):
        _intent(intent_id=bad)


def test_7_intent_id_too_long_rejected() -> None:
    obj = _payload_object()
    obj["intent_id"] = "i" * (MAX_INTENT_ID_CHARS + 1)
    with pytest.raises(AgentIntentValidationError):
        AgentIntent.from_payload(json.dumps(obj))


def test_7_intent_id_wrong_type_rejected() -> None:
    obj = _payload_object()
    obj["intent_id"] = 123
    with pytest.raises(AgentIntentValidationError):
        AgentIntent.from_payload(json.dumps(obj))


# ----------------------------------------------------------------------
# Item 8 - bool is not accepted as a number
# ----------------------------------------------------------------------


@pytest.mark.parametrize("axis", ["x", "y", "heading"])
@pytest.mark.parametrize("flag", [True, False])
def test_8_bool_is_not_a_number(axis: str, flag: bool) -> None:
    obj = _payload_object()
    obj["target"][axis] = flag
    with pytest.raises(AgentIntentValidationError):
        AgentIntent.from_payload(json.dumps(obj))
    with pytest.raises(AgentIntentValidationError):
        Target(**{**_target_kwargs(), axis: flag})


# ----------------------------------------------------------------------
# Item 9 - NaN / Infinity / -Infinity rejected on parse and on construction
# ----------------------------------------------------------------------


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_9_nonfinite_literal_is_parse_error(literal: str) -> None:
    text = (
        '{"contract_version":"1","intent_id":"i","action":"parking.move",'
        f'"target":{{"x":{literal},"y":0.0,"heading":0.0}}}}'
    )
    with pytest.raises(AgentIntentParseError):
        AgentIntent.from_payload(text)


@pytest.mark.parametrize("axis", ["x", "y", "heading"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_9_nonfinite_construction_rejected(axis: str, value: float) -> None:
    with pytest.raises(AgentIntentValidationError):
        Target(**{**_target_kwargs(), axis: value})


# ----------------------------------------------------------------------
# Item 10 - serialization is strict (allow_nan=False)
# ----------------------------------------------------------------------


def test_10_nonfinite_serialization_error() -> None:
    intent = _intent()
    # Bypass the constructor's finiteness guard to reach the defensive
    # serialization branch; the frozen value is injected directly.
    object.__setattr__(intent.target, "heading", float("nan"))
    with pytest.raises(AgentIntentSerializationError) as exc:
        intent.to_payload()
    assert isinstance(exc.value, AgentIntentError)


# ----------------------------------------------------------------------
# Item 11 - heading normalization and boundaries
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (math.pi, -math.pi),
        (-math.pi, -math.pi),
        (1.5 * math.pi, -0.5 * math.pi),
        (-1.5 * math.pi, 0.5 * math.pi),
        (0.0, 0.0),
    ],
)
def test_11_heading_normalization(raw: float, expected: float) -> None:
    heading = Target(x=0.0, y=0.0, heading=raw).heading
    assert math.isclose(heading, expected, rel_tol=0.0, abs_tol=1e-12)
    assert -math.pi <= heading < math.pi


def test_11_normalized_heading_stays_in_half_open_range() -> None:
    for raw in (math.pi, -math.pi, 3 * math.pi, -3 * math.pi, 100.0, -100.0, 7.0):
        heading = Target(x=0.0, y=0.0, heading=raw).heading
        assert -math.pi <= heading < math.pi


# ----------------------------------------------------------------------
# Item 12 - to_payload() passes the existing envelope request validation
# ----------------------------------------------------------------------


def test_12_payload_passes_envelope_validation() -> None:
    intent = _intent()
    request = Request(
        request_id="req-1",
        capability_id=ACTION_PARKING_MOVE,
        payload=intent.to_payload(),
    )
    parsed = envelope.parse_request_line(request.to_line())
    assert parsed.payload == intent.to_payload()
    assert parsed.capability_id == ACTION_PARKING_MOVE


# ----------------------------------------------------------------------
# Item 13 - intent_id is not the IPC request_id
# ----------------------------------------------------------------------


def test_13_intent_id_is_not_request_id() -> None:
    intent = _intent(intent_id="intent-abc")
    request = Request(
        request_id="req-xyz",
        capability_id=ACTION_PARKING_MOVE,
        payload=intent.to_payload(),
    )
    parsed = envelope.parse_request_line(request.to_line())
    assert parsed.request_id == "req-xyz"
    assert intent.intent_id == "intent-abc"
    assert parsed.request_id != intent.intent_id
    # The intent identity travels inside the payload, independent of request_id.
    assert AgentIntent.from_payload(parsed.payload).intent_id == "intent-abc"


# ----------------------------------------------------------------------
# Item 14 - frozen boundary values have explicit boundary tests
# ----------------------------------------------------------------------


def test_14_intent_id_length_boundary() -> None:
    at_limit = _payload_object()
    at_limit["intent_id"] = "i" * MAX_INTENT_ID_CHARS
    parsed = AgentIntent.from_payload(json.dumps(at_limit))
    assert parsed.intent_id == "i" * MAX_INTENT_ID_CHARS
    assert len(parsed.intent_id) == MAX_INTENT_ID_CHARS

    over_limit = _payload_object()
    over_limit["intent_id"] = "i" * (MAX_INTENT_ID_CHARS + 1)
    with pytest.raises(AgentIntentValidationError):
        AgentIntent.from_payload(json.dumps(over_limit))


def test_14_heading_boundary_values() -> None:
    assert Target(0.0, 0.0, math.pi).heading == -math.pi
    assert Target(0.0, 0.0, -math.pi).heading == -math.pi
    assert Target(0.0, 0.0, math.pi).heading == Target(0.0, 0.0, -math.pi).heading
    assert Target(0.0, 0.0, 1.5 * math.pi).heading == pytest.approx(-0.5 * math.pi)
    assert Target(0.0, 0.0, -1.5 * math.pi).heading == pytest.approx(0.5 * math.pi)


# ----------------------------------------------------------------------
# Supporting checks (failure-class separation and capability binding)
# ----------------------------------------------------------------------


@pytest.mark.parametrize("text", ["{not json", "[1, 2, 3]", '"a string"', "123", ""])
def test_parse_failures_are_parse_errors(text: str) -> None:
    with pytest.raises(AgentIntentParseError):
        AgentIntent.from_payload(text)


def test_non_string_payload_is_parse_error() -> None:
    with pytest.raises(AgentIntentParseError):
        AgentIntent.from_payload(b"{}")  # type: ignore[arg-type]


def test_error_hierarchy() -> None:
    for error in (
        AgentIntentParseError,
        AgentIntentValidationError,
        AgentIntentSerializationError,
    ):
        assert issubclass(error, AgentIntentError)


def test_capability_binding_matches_action() -> None:
    # Section 5.5 / 9: capability_id is fixed to the action value, with no
    # dynamic action-to-capability mapping.
    assert ACTION_PARKING_MOVE == _ACTION
    intent = _intent()
    request = Request(
        request_id="r",
        capability_id=ACTION_PARKING_MOVE,
        payload=intent.to_payload(),
    )
    parsed = envelope.parse_request_line(request.to_line())
    assert parsed.capability_id == AgentIntent.from_payload(parsed.payload).action
