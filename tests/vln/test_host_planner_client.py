"""Unit tests for the Host-backed planner model client.

These tests use a fake host client: they prove the request shape, raw-output
handling and context-revision bookkeeping. They do not call a model, a Kernel
host or CARLA.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

from vln.vlm.host_planner_client import (
    HostPlannerError,
    HostPlannerModelClient,
)


@dataclass
class _Response:
    request_id: str
    accepted: bool = True
    submission_status: Optional[str] = "completed"
    observation_status: Optional[str] = "success"
    execution_status: Optional[str] = None
    output: Optional[str] = None
    error: Optional[dict] = None
    session_id: Optional[str] = "S1"
    session_state: Optional[str] = "READY"
    task_id: Optional[str] = None
    workflow_id: Optional[str] = None
    context_revision: Optional[int] = None
    context_before: Optional[dict] = None
    context_after: Optional[dict] = None
    turn: Optional[int] = None
    context_updated: Optional[bool] = True


@dataclass
class _FakeHost:
    responses: list[_Response]
    requests: list[Any] = field(default_factory=list)

    def send(self, request):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected host request")
        return self.responses.pop(0)


def _candidate(request_id: str, raw: str, revision: int) -> _Response:
    output = {
        "status": "candidate",
        "is_execution_permit": False,
        "planner_session_id": "1",
        "planner_request_id": "7",
        "planning_result_id": "3",
        "planning_artifact_id": "2",
        "strategy": "taichu",
        "raw_output": raw,
        "raw_output_sha256": "a" * 64,
        "model": {"backend": "zdt-taichu-server"},
        "server_response": {"server_response_id": "resp-1"},
    }
    return _Response(
        request_id=request_id,
        output=json.dumps(output),
        context_revision=revision,
        turn=revision,
        context_before={"turn": revision - 1},
        context_after={"turn": revision},
    )


def test_candidate_output_is_returned_verbatim_and_revision_updates() -> None:
    host = _FakeHost([_candidate("p-001", "RAW MODEL TEXT", 3)])
    client = HostPlannerModelClient(
        host,
        session_id="S1",
        context_revision=2,
        request_id_prefix="p",
        domain={"round": 1},
    )

    assert client.generate("/tmp/frame.png", "go to the blue car") == "RAW MODEL TEXT"

    request = host.requests[0]
    assert request.capability_id == "planner.plan"
    assert request.session_id == "S1"
    assert request.expected_context_revision == 2
    assert request.domain == {"round": 1}
    payload = json.loads(request.payload)
    assert payload["image_path"] == "/tmp/frame.png"
    assert payload["instruction"] == "go to the blue car"
    assert payload["domain"] == {"round": 1}

    assert client.context_revision == 3
    exchange = client.last_exchange
    assert exchange is not None
    assert exchange.planner_request_id == "7"
    assert exchange.planning_artifact_id == "2"
    assert exchange.raw_output == "RAW MODEL TEXT"
    metadata = exchange.to_metadata()
    assert metadata["context_revision"] == 3
    assert "raw_output" not in metadata["output"]


def test_host_error_raises_and_keeps_failure_exchange() -> None:
    response = _Response(
        request_id="p-001",
        accepted=True,
        submission_status="completed",
        observation_status="failure",
        output=json.dumps({"status": "failed", "error": {"message": "boom"}}),
        error={"code": "planner-failed", "message": "boom"},
        context_revision=4,
        turn=4,
    )
    host = _FakeHost([response])
    client = HostPlannerModelClient(host, session_id="S1", context_revision=3)

    with pytest.raises(HostPlannerError, match="planner-failed: boom"):
        client.generate("/tmp/frame.png", "instruction")

    assert client.context_revision == 4
    assert client.last_exchange is not None
    assert client.last_exchange.response["observation_status"] == "failure"
    assert client.last_exchange.response["error"] == {
        "code": "planner-failed",
        "message": "boom",
    }


def test_non_candidate_output_is_rejected() -> None:
    response = _Response(
        request_id="p-001",
        observation_status="success",
        output=json.dumps({"status": "candidate", "raw_output": "   "}),
    )
    client = HostPlannerModelClient(_FakeHost([response]), session_id="S1",
                                    context_revision=0)

    with pytest.raises(HostPlannerError, match="planner-output-rejected"):
        client.generate("/tmp/frame.png", "instruction")


def test_missing_output_object_is_rejected() -> None:
    response = _Response(request_id="p-001", output="not json")
    client = HostPlannerModelClient(_FakeHost([response]), session_id="S1",
                                    context_revision=0)

    with pytest.raises(HostPlannerError, match="planner-output-rejected"):
        client.generate("/tmp/frame.png", "instruction")


def test_blank_or_non_path_input_is_refused_before_sending() -> None:
    host = _FakeHost([])
    client = HostPlannerModelClient(host, session_id="S1", context_revision=0)

    with pytest.raises(HostPlannerError):
        client.generate(object(), "instruction")
    with pytest.raises(HostPlannerError):
        client.generate("/tmp/frame.png", "   ")

    assert host.requests == []


def test_request_ids_are_unique_per_client() -> None:
    host = _FakeHost([
        _candidate("p-001", "one", 1),
        _candidate("p-002", "two", 2),
    ])
    client = HostPlannerModelClient(host, session_id="S1", context_revision=0,
                                    request_id_prefix="p")

    assert client.generate("/tmp/frame.png", "a") == "one"
    assert client.generate("/tmp/frame.png", "b") == "two"
    assert [request.request_id for request in host.requests] == ["p-001", "p-002"]
    assert host.requests[1].expected_context_revision == 1
