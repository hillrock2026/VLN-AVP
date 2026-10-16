"""Tests for the AgentIntent -> IPC Request bridge (:mod:`vln.client.request_builder`).

These are pure Python unit tests: the bridge maps an already-validated
``AgentIntent`` onto the existing IPC v1 ``Request`` envelope. No host is
spawned and no submission happens here.
"""

from __future__ import annotations

import json

import pytest

from vln.client import build_request
from vln.client.request_builder import build_request as build_request_direct
from vln.intent import AgentIntent, Target, parse_model_output
from vln.ipc import envelope
from vln.ipc.envelope import Request


def _intent(intent_id: str = "intent-0001") -> AgentIntent:
    return AgentIntent(
        intent_id=intent_id, target=Target(x=1.5, y=-2.25, heading=0.5)
    )


def test_legal_intent_maps_to_a_request() -> None:
    intent = _intent()
    request = build_request(intent, request_id="req-1")
    assert isinstance(request, Request)
    assert request.request_id == "req-1"


def test_capability_id_comes_from_intent_action() -> None:
    intent = _intent()
    request = build_request(intent, request_id="req-1")
    assert request.capability_id == "parking.move"
    assert request.capability_id == intent.action


def test_payload_is_the_authoritative_serialization() -> None:
    intent = _intent()
    request = build_request(intent, request_id="req-1")
    # Verbatim reuse of the intent's own serializer - no re-encoding here.
    assert request.payload == intent.to_payload()
    # ...and it round-trips back through the authoritative parser unchanged.
    assert AgentIntent.from_payload(request.payload) == intent


def test_intent_id_and_request_id_are_independent() -> None:
    intent = _intent(intent_id="intent-abc")
    request = build_request(intent, request_id="req-xyz")
    assert request.request_id == "req-xyz"
    assert request.request_id != intent.intent_id
    # The request_id is never derived from the intent_id.
    assert AgentIntent.from_payload(request.payload).intent_id == "intent-abc"


def test_output_conforms_to_the_existing_request_envelope() -> None:
    intent = _intent()
    request = build_request(intent, request_id="req-1")
    assert request.protocol_version == "1"
    assert request.type == "submit"
    assert set(request.to_object()) == {
        "protocol_version",
        "request_id",
        "type",
        "capability_id",
        "payload",
    }
    # The encoded line passes the authoritative envelope validation.
    reparsed = envelope.parse_request_line(request.to_line())
    assert reparsed == request


def test_intent_id_length_is_not_the_request_id_limit() -> None:
    # A legal intent_id of 128 chars maps to a payload; the request_id is a
    # separate, caller-owned identity (here deliberately different).
    intent = _intent(intent_id="i" * 128)
    request = build_request(intent, request_id="req-1")
    assert request.request_id == "req-1"


def test_non_agent_intent_is_rejected_not_repaired() -> None:
    # The bridge accepts only an already-validated AgentIntent; it must not
    # silently coerce an arbitrary object that merely looks intent-shaped.
    with pytest.raises(TypeError):
        build_request({"action": "parking.move"}, request_id="req-1")  # type: ignore[arg-type]


def test_bridge_mirrors_action_without_altering_the_intent() -> None:
    intent = _intent()
    request = build_request(intent, request_id="req-1")
    # The (frozen) intent is never rewritten; the request simply mirrors it.
    assert request.capability_id == intent.action
    assert json.loads(request.payload)["action"] == intent.action


def test_build_request_is_exported_from_the_package() -> None:
    assert build_request is build_request_direct


def test_parse_model_output_feeds_the_bridge_directly() -> None:
    # A valid model-output string goes parser -> bridge with no manual step.
    raw = (
        '{"contract_version":"1","intent_id":"intent-1","action":"parking.move",'
        '"target":{"x":1.0,"y":2.0,"heading":0.5}}'
    )
    intent = parse_model_output(raw)
    request = build_request(intent, request_id="req-1")
    assert request.capability_id == "parking.move"
    assert request.payload == intent.to_payload()
