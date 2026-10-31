"""Unit tests for the loopback Taichu planner bridge.

The bridge is exercised with a fake backend: no model service, no network
inference. These tests pin the fail-closed protocol: token rejection, input
validation, verbatim raw output, and typed model failures.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_BRIDGE_PATH = REPO_ROOT / "scripts" / "taichu_planner_bridge.py"


def _load_bridge():
    spec = importlib.util.spec_from_file_location(
        "taichu_planner_bridge_under_test", _BRIDGE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bridge = _load_bridge()


class _FakeBackend:
    endpoint = "fake://zdt-taichu"
    max_new_tokens = 32
    temperature = 0.0
    enable_thinking = False
    model_name = "fake-taichu"

    def __init__(self, output="RAW", error=None, metadata=None):
        self.output = output
        self.error = error
        self.metadata = metadata or {
            "server_response_id": "resp-1",
            "response_model": "fake-taichu",
            "finish_reason": "stop",
            "usage": {"completion_tokens": 3},
        }
        self.calls = []

    def generate_image_with_metadata(self, image_path: str, instruction: str):
        self.calls.append((image_path, instruction))
        if self.error is not None:
            raise self.error
        return self.output, self.metadata


@pytest.fixture()
def image_path(tmp_path: Path) -> str:
    path = tmp_path / "frame.png"
    path.write_bytes(b"fake-image-bytes")
    return str(path)


TOKEN = "test-token"


def _context(**overrides) -> dict:
    context = {
        "session_id": "S1",
        "turn": 2,
        "context_revision": 2,
        "phase": "planning",
        "status": "planned",
        "history": [
            {
                "kind": "planning",
                "turn": 1,
                "revision": 1,
                "status": "planned",
                "raw_output_preview": "Target: blue car\nVisible: 是",
                "domain": {"target": "blue car", "round": 1},
            },
            {
                "kind": "execution",
                "turn": 2,
                "revision": 2,
                "status": "completed",
                "moved_m": 1.5,
                "post_state": {"x": 1.0, "y": 2.0, "yaw": 3.0, "speed": 0.0},
                "domain": {"target": "blue car", "round": 2},
            },
        ],
    }
    context.update(overrides)
    return context


def _request(image_path: str, **overrides) -> dict:
    request = {
        "protocol_version": "1",
        "request_id": "p-001",
        "planner_session_id": "1",
        "session_id": "S1",
        "context_revision": 2,
        "context": _context(),
        "image_path": image_path,
        "instruction": "go to the blue car",
        "domain": {"round": 2, "target": "blue car"},
        "token": TOKEN,
    }
    request.update(overrides)
    return request


def test_valid_request_returns_raw_output_and_evidence(image_path: str) -> None:
    backend = _FakeBackend(output="MODEL RAW")
    response = bridge.process_request(
        _request(image_path), expected_token=TOKEN, backend=backend
    )

    assert response["status"] == "ok"
    assert response["request_id"] == "p-001"
    assert response["raw_output"] == "MODEL RAW"
    assert response["planner_session_id"] == "1"
    assert response["session_id"] == "S1"
    assert response["context_revision"] == 2
    assert response["image_sha256"]
    assert response["instruction_sha256"]
    assert response["context_sha256"]
    assert response["model"]["backend"] == "zdt-taichu-server"
    assert response["server_response"]["server_response_id"] == "resp-1"
    assert response["instruction_sha256"]
    assert response["prompt"].startswith("go to the blue car")
    assert "Kernel 持久上下文" in response["prompt"]
    assert "Target: blue car" in response["prompt"]
    assert "位移=1.5 m" in response["prompt"]
    assert response["context_selection"]["selected_count"] == 2
    assert response["context_selection"]["source"] == (
        "kernel.session.context.history"
    )
    assert backend.calls == [(image_path, response["prompt"])]


def test_context_change_changes_the_final_model_prompt(image_path: str) -> None:
    first_backend = _FakeBackend(output="RAW")
    first = bridge.process_request(
        _request(image_path), expected_token=TOKEN, backend=first_backend
    )
    changed = _context()
    changed["history"][0]["raw_output_preview"] = (
        "Target: blue car\nIdentified as: blue car"
    )
    second_backend = _FakeBackend(output="RAW")
    second = bridge.process_request(
        _request(image_path, context=changed),
        expected_token=TOKEN,
        backend=second_backend,
    )
    assert first["prompt_sha256"] != second["prompt_sha256"]
    assert "Visible: 是" in first["prompt"]
    assert "Identified as: blue car" not in first["prompt"]
    assert "Identified as: blue car" in second["prompt"]
    assert first_backend.calls[0][1] == first["prompt"]
    assert second_backend.calls[0][1] == second["prompt"]


def test_revision_mismatch_fails_before_the_model(image_path: str) -> None:
    backend = _FakeBackend()
    response = bridge.process_request(
        _request(image_path, context_revision=1),
        expected_token=TOKEN,
        backend=backend,
    )
    assert response["status"] == "failed"
    assert response["error"]["type"] == "ContextPromptError"
    assert "revision mismatch" in response["error"]["message"]
    assert backend.calls == []


def test_missing_context_fails_before_the_model(image_path: str) -> None:
    backend = _FakeBackend()
    response = bridge.process_request(
        _request(image_path, context=None),
        expected_token=TOKEN,
        backend=backend,
    )
    assert response["status"] == "failed"
    assert response["error"]["type"] == "ContextPromptError"
    assert backend.calls == []


def test_invalid_token_is_rejected_without_calling_model(image_path: str) -> None:
    backend = _FakeBackend()
    response = bridge.process_request(
        _request(image_path, token="wrong"), expected_token=TOKEN, backend=backend
    )

    assert response["status"] == "failed"
    assert response["error"]["type"] == "Unauthorized"
    assert backend.calls == []


def test_missing_image_is_rejected_without_calling_model(tmp_path: Path) -> None:
    backend = _FakeBackend()
    response = bridge.process_request(
        _request(str(tmp_path / "absent.png")),
        expected_token=TOKEN,
        backend=backend,
    )

    assert response["status"] == "failed"
    assert response["error"]["type"] == "ImagePathError"
    assert backend.calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", ""),
        ("image_path", "   "),
        ("instruction", ""),
        ("protocol_version", "2"),
    ],
)
def test_invalid_fields_are_rejected(image_path: str, field, value) -> None:
    backend = _FakeBackend()
    request = _request(image_path)
    request[field] = value
    response = bridge.process_request(
        request,
        expected_token=TOKEN,
        backend=backend,
    )

    assert response["status"] == "failed"
    assert response["error"]["type"] == "BridgeInputError"
    assert backend.calls == []


def test_model_exception_is_a_typed_failure(image_path: str) -> None:
    backend = _FakeBackend(error=RuntimeError("service unavailable"))
    response = bridge.process_request(
        _request(image_path), expected_token=TOKEN, backend=backend
    )

    assert response["status"] == "failed"
    assert response["error"] == {
        "type": "RuntimeError",
        "message": "service unavailable",
    }
    assert response["raw_output"] is None


def test_empty_model_output_is_returned_verbatim(image_path: str) -> None:
    backend = _FakeBackend(output="")
    response = bridge.process_request(
        _request(image_path), expected_token=TOKEN, backend=backend
    )

    assert response["status"] == "ok"
    assert response["raw_output"] == ""
    assert response["raw_output_sha256"] == (
        "e3b0c44298fc1c149afbf4c8996fb924"
        "27ae41e4649b934ca495991b7852b855"
    )


def test_non_string_model_output_is_a_protocol_failure(image_path: str) -> None:
    backend = _FakeBackend(output=123)
    response = bridge.process_request(
        _request(image_path), expected_token=TOKEN, backend=backend
    )

    assert response["status"] == "failed"
    assert response["error"]["type"] == "BridgeProtocolError"
