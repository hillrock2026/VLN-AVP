"""Tests for the model-call boundary (:mod:`vln.vlm.model_client`).

These are pure Python unit tests. The mock returns caller-supplied text
verbatim; it is explicitly a MOCK and claims no inference. Nothing here calls
a real model, loads weights, touches the network or uses a GPU.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from vln.vlm import ModelCallError, MockModelClient, ModelClient

_VALID_TEXT = (
    '{"contract_version":"1","intent_id":"intent-1","action":"parking.move",'
    '"target":{"x":1.0,"y":2.0,"heading":0.5}}'
)
_INVALID_TEXT = '{"contract_version":"1","intent_id":"intent-1"  '  # truncated


def test_mock_returns_valid_text_verbatim() -> None:
    model = MockModelClient(_VALID_TEXT)
    assert model.generate(observation=None, instruction="park") == _VALID_TEXT


def test_mock_returns_invalid_text_verbatim_without_interpreting_it() -> None:
    # The mock never "fixes" or judges the text; the parse layer owns rejection.
    model = MockModelClient(_INVALID_TEXT)
    assert model.generate(observation="frame", instruction="park") == _INVALID_TEXT


def test_mock_records_calls_for_assertions() -> None:
    model = MockModelClient(_VALID_TEXT)
    assert model.call_count == 0
    assert model.last_observation is None
    assert model.last_instruction is None

    model.generate(observation={"cam": "rgb"}, instruction="go to slot 3")
    assert model.call_count == 1
    assert model.last_observation == {"cam": "rgb"}
    assert model.last_instruction == "go to slot 3"

    model.generate(observation=None, instruction="again")
    assert model.call_count == 2
    assert model.last_instruction == "again"


def test_mock_rejects_a_non_string_output() -> None:
    with pytest.raises(TypeError):
        MockModelClient(output=123)  # type: ignore[arg-type]


def test_mock_satisfies_the_model_client_protocol() -> None:
    model = MockModelClient(_VALID_TEXT)
    assert isinstance(model, ModelClient)


def test_model_call_error_is_a_plain_exception() -> None:
    assert issubclass(ModelCallError, Exception)


def test_model_client_module_has_no_host_or_ipc_dependency() -> None:
    """Structural proof the model boundary cannot reach the host or the wire."""

    src_root = Path(__file__).resolve().parents[2] / "src"
    code = (
        "import sys, vln.vlm.model_client as m;"
        "assert 'vln.client' not in sys.modules, 'vlm imports vln.client';"
        "assert 'vln.ipc' not in sys.modules, 'vlm imports vln.ipc';"
        "assert callable(getattr(m, 'MockModelClient'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(src_root)},
    )
    assert result.returncode == 0, result.stderr


def test_model_client_module_does_not_import_a_real_inference_stack() -> None:
    """No implicit model load: importing the boundary pulls in no torch/transformers."""

    src_root = Path(__file__).resolve().parents[2] / "src"
    code = (
        "import sys, vln.vlm.model_client;"  # noqa: F401
        "forbidden = [m for m in ('torch', 'transformers') if m in sys.modules];"
        "assert not forbidden, f'unexpected inference deps: {forbidden}'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(src_root)},
    )
    assert result.returncode == 0, result.stderr
