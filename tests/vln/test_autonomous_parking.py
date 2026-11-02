"""Offline tests for the autonomous-parking target-verification stage.

Covers the two-observation agreement rules, identity continuity, evidence
independence, the permission artifact and its invalidation. No CARLA, model or
network is involved.
"""

from __future__ import annotations

import pytest

from vln.nav.target_verification import (
    VerificationDecisionParseError,
    parse_verification_decision,
)
from vln.nav.target_binding import BindingArtifact
from vln.parking.autonomous import (
    ApproachState,
    AutonomousParkingStage,
    EntryAuthorization,
    EntryAuthorizationError,
    VerificationObservation,
    approach_state_from_result,
    authorization_is_usable,
    authorize_entry,
    require_entry_authorization,
    verify_target,
)
from vln.vlm.verification_prompt import build_target_verification_prompt


def _binding(bay_id="bay03", slot="park_slot"):
    return BindingArtifact(
        status="bound",
        instruction="请将车辆停入左侧靠近出口的空闲车位",
        bay_id=bay_id,
        slot_node_id=slot,
        round_index=0,
        selected_label="B",
        reason="unique",
    )


def _approach(**overrides):
    values = dict(
        task_id="cap07b-02",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        pose={"x": -3.894, "y": -17.177, "z": 5.791, "yaw": -86.352},
        speed_mps=0.0,
    )
    values.update(overrides)
    return ApproachState(**values)


def _observation(index=1, **overrides):
    values = dict(
        observation_id=f"obs-{index}",
        entity_bay_id="bay03",
        image_path=f"/tmp/obs-{index}-overlay.png",
        image_sha256=f"sha-overlay-{index}",
        raw_image_path=f"/tmp/obs-{index}-raw.png",
        raw_image_sha256=f"sha-raw-{index}",
        frame_id=1000 + index,
        captured_at="2026-10-30T00:00:00+00:00",
        pose={"x": -3.894, "y": -17.177, "z": 5.791, "yaw": -86.352},
        camera={"x": -5.2, "y": -12.2, "z": 8.1, "yaw": -111.4},
        view_signature=f"view-{index}",
        model_request_id=f"req-{index}",
        server_response_id=f"resp-{index}",
        model_text="A: 空闲\n边界: 清晰\n遮挡: 无\n证据: 充分\nSelected: A",
        occupancy="vacant",
        boundary_clear=True,
        occluded=False,
        evidence_sufficient=True,
        identity_verified=True,
        identity_mismatch=False,
        parse_ok=True,
        request_ok=True,
        reasons=(),
        model_metadata={"usage": {"completion_tokens": 10}},
    )
    values.update(overrides)
    return VerificationObservation(**values)


def _confirmed():
    approach = _approach()
    return verify_target(
        approach,
        (_observation(1), _observation(2)),
        binding=_binding(),
        stopped=True,
    )


def _authorization():
    return authorize_entry(
        _confirmed(),
        stopped=True,
        collision_count=0,
        now="2026-10-30T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# prompt / parser
# ---------------------------------------------------------------------------


def test_prompt_has_only_label_and_closed_fields() -> None:
    prompt = build_target_verification_prompt("A")
    assert "A:" in prompt
    assert "边界:" in prompt and "遮挡:" in prompt and "证据:" in prompt
    assert "Selected:" in prompt
    for forbidden in ("bay03", "park_slot", "park_entry", "x=", "y="):
        assert forbidden not in prompt.lower()


def test_parse_valid_verification_block() -> None:
    decision = parse_verification_decision(
        "A: 空闲\n边界: 清晰\n遮挡: 无\n证据: 充分\nSelected: A"
    )
    assert decision.occupancy == "vacant"
    assert decision.boundary_clear is True
    assert decision.occluded is False
    assert decision.evidence_sufficient is True
    assert decision.selected == "A"


def test_parse_chinese_colon_and_decorations() -> None:
    decision = parse_verification_decision(
        "**A：占用**\n- 边界: 不清晰\n- 遮挡: 有\n- 证据: 不足\n`Selected`: A"
    )
    assert decision.occupancy == "occupied"
    assert decision.boundary_clear is False
    assert decision.occluded is True
    assert decision.evidence_sufficient is False


@pytest.mark.parametrize(
    "text",
    [
        "",
        "A: 空闲\n边界: 清晰\n遮挡: 无\nSelected: A",  # missing evidence
        "A: 空闲\n边界: 模糊\n遮挡: 无\n证据: 充分\nSelected: A",
        "A: 空闲\n边界: 清晰\n遮挡: 无\n证据: 充分\n边界: 不清晰\nSelected: A",
        "A: 空着\n边界: 清晰\n遮挡: 无\n证据: 充分\nSelected: A",
        "A: 空闲\n边界: 清晰\n遮挡: 无\n证据: 充分\nSelected: B",
        "A: 空闲\n边界: 清晰\n遮挡: 无\n证据: 充分",  # missing Selected
    ],
)
def test_parse_refusals(text: str) -> None:
    with pytest.raises(VerificationDecisionParseError):
        parse_verification_decision(text)


# ---------------------------------------------------------------------------
# two-observation agreement
# ---------------------------------------------------------------------------


def test_two_good_observations_create_entry_authorization() -> None:
    verification = _confirmed()
    assert verification.stage == AutonomousParkingStage.TARGET_CONFIRMED
    assert verification.target_confirmed is True
    assert verification.identity_verified is True
    assert verification.occupancy_verified is True
    assert verification.evidence_sufficient is True
    assert verification.reasons == ()
    assert verification.stage_history == (
        "APPROACH_COMPLETED",
        "VERIFYING_TARGET",
        "TARGET_CONFIRMED",
    )

    authorization = authorize_entry(
        verification, stopped=True, collision_count=0, now="2026-10-30T00:00:00+00:00"
    )
    assert authorization.decision == "ENTRY_AUTHORIZED"
    assert authorization.permits_entry is True
    assert authorization.target_confirmed is True
    assert authorization.bay_id == "bay03"
    assert authorization.slot_node_id == "park_slot"
    assert authorization.approach_node_id == "park_entry"
    assert len(authorization.observation_image_hashes) == 2
    assert authorization.stage_history[-1] == "ENTRY_AUTHORIZED"
    assert authorization.executes_motion is False
    require_entry_authorization(
        authorization,
        task_id="cap07b-02",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        binding_status="bound",
        approach_stage="APPROACH_COMPLETED",
        observation_image_hashes=("sha-overlay-1", "sha-overlay-2"),
    )


def test_same_image_sha_is_not_two_observations() -> None:
    verification = verify_target(
        _approach(),
        (
            _observation(1),
            _observation(2, image_sha256="sha-overlay-1"),
        ),
        binding=_binding(),
        stopped=True,
    )
    assert verification.stage == AutonomousParkingStage.UNVERIFIED
    assert "duplicate_observation_image" in verification.reasons
    assert authorize_entry(verification, stopped=True).permits_entry is False


def test_same_view_signature_is_not_independent() -> None:
    verification = verify_target(
        _approach(),
        (
            _observation(1),
            _observation(2, view_signature="view-1"),
        ),
        binding=_binding(),
        stopped=True,
    )
    assert verification.stage == AutonomousParkingStage.UNVERIFIED
    assert "no_independent_view_difference" in verification.reasons


def test_one_unknown_observation_is_unverified() -> None:
    verification = verify_target(
        _approach(),
        (_observation(1), _observation(2, occupancy="unknown")),
        binding=_binding(),
        stopped=True,
    )
    assert verification.stage == AutonomousParkingStage.UNVERIFIED
    assert any(
        reason.startswith("occupancy_unverified")
        for reason in verification.reasons
    )
    assert authorization_is_usable(
        authorize_entry(verification, stopped=True),
        task_id="cap07b-02",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        binding_status="bound",
        approach_stage="APPROACH_COMPLETED",
        observation_image_hashes=("sha-overlay-1", "sha-overlay-2"),
    ) is False


def test_identity_mismatch_is_rejected_and_never_rebound() -> None:
    verification = verify_target(
        _approach(),
        (_observation(1), _observation(2, identity_mismatch=True)),
        binding=_binding(),
        stopped=True,
    )
    assert verification.stage == AutonomousParkingStage.REJECTED
    assert verification.bay_id == "bay03"
    assert verification.target_id == "bay03"
    assert verification.slot_node_id == "park_slot"
    assert authorize_entry(verification, stopped=True).permits_entry is False


def test_observation_for_another_bay_is_rejected_without_rebinding() -> None:
    verification = verify_target(
        _approach(),
        (_observation(1), _observation(2, entity_bay_id="bay11")),
        binding=_binding(),
        stopped=True,
    )
    assert verification.stage == AutonomousParkingStage.REJECTED
    assert verification.bay_id == "bay03"
    assert any(
        reason.startswith("observation_entity_mismatch")
        for reason in verification.reasons
    )
    assert authorize_entry(verification, stopped=True).permits_entry is False


def test_occupied_target_is_rejected() -> None:
    verification = verify_target(
        _approach(),
        (_observation(1), _observation(2, occupancy="occupied")),
        binding=_binding(),
        stopped=True,
    )
    assert verification.stage == AutonomousParkingStage.REJECTED


def test_parse_failure_is_unverified() -> None:
    verification = verify_target(
        _approach(),
        (_observation(1), _observation(2, parse_ok=False)),
        binding=_binding(),
        stopped=True,
    )
    assert verification.stage == AutonomousParkingStage.UNVERIFIED
    assert any(
        reason.startswith("observation_unparseable")
        for reason in verification.reasons
    )


def test_empty_model_request_is_unverified() -> None:
    verification = verify_target(
        _approach(),
        (_observation(1), _observation(2, request_ok=False)),
        binding=_binding(),
        stopped=True,
    )
    assert verification.stage == AutonomousParkingStage.UNVERIFIED
    assert any(
        reason.startswith("model_request_failed")
        for reason in verification.reasons
    )


def test_occupancy_disagreement_is_not_authorized() -> None:
    rejected = verify_target(
        _approach(),
        (_observation(1), _observation(2, occupancy="occupied")),
        binding=_binding(),
        stopped=True,
    )
    assert rejected.stage == AutonomousParkingStage.REJECTED
    unverified = verify_target(
        _approach(),
        (_observation(1), _observation(2, occupancy="unknown")),
        binding=_binding(),
        stopped=True,
    )
    assert unverified.stage == AutonomousParkingStage.UNVERIFIED


def test_binding_identity_mismatch_is_rejected() -> None:
    verification = verify_target(
        _approach(),
        (_observation(1), _observation(2)),
        binding=_binding(bay_id="bay11", slot="bay11_slot"),
        stopped=True,
    )
    assert verification.stage == AutonomousParkingStage.REJECTED
    assert "binding_identity_mismatch" in verification.reasons


def test_unclear_boundary_or_occlusion_is_unverified() -> None:
    unclear = verify_target(
        _approach(),
        (_observation(1), _observation(2, boundary_clear=False)),
        binding=_binding(),
        stopped=True,
    )
    assert unclear.stage == AutonomousParkingStage.UNVERIFIED
    occluded = verify_target(
        _approach(),
        (_observation(1), _observation(2, occluded=True, evidence_sufficient=False)),
        binding=_binding(),
        stopped=True,
    )
    assert occluded.stage == AutonomousParkingStage.UNVERIFIED


# ---------------------------------------------------------------------------
# permission scope / freshness
# ---------------------------------------------------------------------------


def test_other_task_or_bay_cannot_reuse_authorization() -> None:
    authorization = _authorization()
    assert not authorization.is_usable_by(
        task_id="other-task",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
    )
    assert not authorization.is_usable_by(
        task_id="cap07b-02",
        target_id="bay11",
        bay_id="bay11",
        slot_node_id="bay11_slot",
        approach_node_id="bay11_turn",
    )
    with pytest.raises(EntryAuthorizationError):
        require_entry_authorization(
            authorization,
            task_id="other-task",
            target_id="bay03",
            bay_id="bay03",
            slot_node_id="park_slot",
            approach_node_id="park_entry",
            binding_status="bound",
            approach_stage="APPROACH_COMPLETED",
            observation_image_hashes=("sha-overlay-1", "sha-overlay-2"),
        )


def test_authorization_invalid_after_evidence_or_identity_change() -> None:
    authorization = _authorization()
    assert not authorization.is_current(
        binding_status="bound",
        approach_stage="APPROACH_COMPLETED",
        observation_image_hashes=("sha-overlay-1", "other"),
    )
    assert not authorization.is_current(
        binding_status="invalidated",
        approach_stage="APPROACH_COMPLETED",
        observation_image_hashes=("sha-overlay-1", "sha-overlay-2"),
    )
    assert not authorization.is_current(
        binding_status="bound",
        approach_stage="TARGET_CONFIRMED",
        observation_image_hashes=("sha-overlay-1", "sha-overlay-2"),
    )


def test_missing_evidence_cannot_construct_permission() -> None:
    verification = verify_target(
        _approach(), (_observation(1),), binding=_binding(), stopped=True
    )
    assert verification.stage == AutonomousParkingStage.UNVERIFIED
    authorization = authorize_entry(verification, stopped=True)
    assert authorization.permits_entry is False
    with pytest.raises(ValueError):
        EntryAuthorization(
            authorization_id="fake",
            task_id="cap07b-02",
            target_id="bay03",
            bay_id="bay03",
            slot_node_id="park_slot",
            approach_node_id="park_entry",
            verification_status="ENTRY_AUTHORIZED",
            target_confirmed=True,
            observation_ids=(),
            observation_image_hashes=(),
            identity_verified=True,
            occupancy_verified=True,
            evidence_sufficient=True,
            decision="ENTRY_AUTHORIZED",
            reason="fabricated",
            created_at="2026-10-30T00:00:00+00:00",
            stage_history=(),
        )


@pytest.mark.parametrize("decision", ["UNVERIFIED", "REJECTED", "SAFE_STOP"])
def test_non_authorized_decisions_cannot_enter(decision: str) -> None:
    if decision == "UNVERIFIED":
        verification = verify_target(
            _approach(), (_observation(1),), binding=_binding(), stopped=True
        )
        authorization = authorize_entry(verification, stopped=True)
    elif decision == "REJECTED":
        verification = verify_target(
            _approach(),
            (_observation(1), _observation(2, occupancy="occupied")),
            binding=_binding(),
            stopped=True,
        )
        authorization = authorize_entry(verification, stopped=True)
    else:
        verification = _confirmed()
        authorization = authorize_entry(
            verification, stopped=False, collision_count=0
        )
    assert authorization.decision == decision
    assert authorization.permits_entry is False
    with pytest.raises(EntryAuthorizationError):
        require_entry_authorization(
            authorization,
            task_id="cap07b-02",
            target_id="bay03",
            bay_id="bay03",
            slot_node_id="park_slot",
            approach_node_id="park_entry",
            binding_status="bound",
            approach_stage="APPROACH_COMPLETED",
            observation_image_hashes=("sha-overlay-1", "sha-overlay-2"),
        )


def test_stopped_and_collision_are_safe_stop() -> None:
    moving = verify_target(
        _approach(speed_mps=1.0),
        (_observation(1), _observation(2)),
        binding=_binding(),
        stopped=False,
    )
    assert moving.stage == AutonomousParkingStage.SAFE_STOP
    collision = verify_target(
        _approach(),
        (_observation(1), _observation(2)),
        binding=_binding(),
        stopped=True,
        collision_count=1,
    )
    assert collision.stage == AutonomousParkingStage.SAFE_STOP


def test_approach_state_from_verified_cap07b01_result() -> None:
    result = {
        "status": "PASS",
        "task_status": "goal_reached",
        "final_state": {"x": -3.894, "y": -17.177, "z": 5.791, "yaw": -86.352, "speed": 0.0},
        "target_approach_verdict": {"ok": True},
        "meta": {
            "target_binding": {
                "status": "bound",
                "bay_id": "bay03",
                "slot_node_id": "park_slot",
            },
            "target_approach": {
                "enabled": True,
                "task_id": "cap07b-01",
                "target_id": "bay03",
                "bay_id": "bay03",
                "slot_node_id": "park_slot",
                "approach_node_id": "park_entry",
            },
        },
    }
    approach = approach_state_from_result(result)
    assert approach.stage == AutonomousParkingStage.APPROACH_COMPLETED
    assert approach.task_id == "cap07b-01"
    assert approach.approach_node_id == "park_entry"
    assert approach.matches_binding(_binding())
