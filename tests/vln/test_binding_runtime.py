"""Offline tests for the binding-artifact -> runner goal gate.

Module under test: :mod:`vln.nav.binding_runtime`.
"""

from __future__ import annotations

import json

import pytest

from vln.nav.binding_runtime import (
    BindingRuntimeError,
    load_binding_artifact,
    resolve_bound_goal,
)


def _artifact(**overrides):
    metadata = {
        "schema": "vln.parking_target_binding.v1",
        "status": "bound",
        "instruction": "请将车辆停入左侧的空闲车位",
        "round_index": 0,
        "bay_id": "bay03",
        "slot_node_id": "park_slot",
        "selected_label": "B",
        "prior_bay_id": None,
        "reason": "unique visible vacant candidate",
        "executable": True,
        "candidates": [],
        "evidence": {},
    }
    metadata.update(overrides)
    return metadata


def _write(tmp_path, metadata) -> str:
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_valid_bound_artifact_resolves_the_slot(tmp_path) -> None:
    artifact = load_binding_artifact(_write(tmp_path, _artifact()))
    assert artifact.status == "bound"
    assert resolve_bound_goal(artifact) == "park_slot"
    assert (
        resolve_bound_goal(
            artifact,
            instruction="请将车辆停入左侧的空闲车位",
            explicit_goal_node="park_slot",
        )
        == "park_slot"
    )


@pytest.mark.parametrize(
    "status",
    ["ambiguous", "temporarily_not_visible", "invalidated", "unverified", "refused"],
)
def test_non_bound_artifact_is_refused(tmp_path, status: str) -> None:
    artifact = load_binding_artifact(
        _write(
            tmp_path,
            _artifact(
                status=status,
                bay_id="bay03",
                slot_node_id="park_slot",
                executable=False,
            ),
        )
    )
    with pytest.raises(BindingRuntimeError):
        resolve_bound_goal(artifact)


def test_instruction_mismatch_is_refused(tmp_path) -> None:
    artifact = load_binding_artifact(_write(tmp_path, _artifact()))
    with pytest.raises(BindingRuntimeError):
        resolve_bound_goal(artifact, instruction="停入右侧的空闲车位")
    with pytest.raises(BindingRuntimeError):
        resolve_bound_goal(artifact, instruction="")


def test_explicit_goal_conflict_is_refused(tmp_path) -> None:
    artifact = load_binding_artifact(_write(tmp_path, _artifact()))
    with pytest.raises(BindingRuntimeError):
        resolve_bound_goal(artifact, explicit_goal_node="bay11_slot")


def test_invalid_json_and_missing_file_are_refused(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(BindingRuntimeError):
        load_binding_artifact(str(bad))
    with pytest.raises(BindingRuntimeError):
        load_binding_artifact(str(tmp_path / "missing.json"))
    with pytest.raises(BindingRuntimeError):
        load_binding_artifact(_write(tmp_path, {"status": "bound"}))
