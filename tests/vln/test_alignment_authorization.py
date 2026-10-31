"""Alignment stage authorization tests (CAP-07B-03).

The permission is single-use, expiring, revocable and stage-scoped. It is
derived from a CAP-07B-02 ENTRY_AUTHORIZED artifact but never extends it:
``permits_entry`` is permanently false and an Entry permission cannot be used
as an Alignment permission (or vice versa).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from vln.carla.alignment_scene import bay03_alignment_target
from vln.parking.alignment import (
    AlignmentAuthorization,
    AlignmentAuthorizationError,
    AlignmentBudget,
    AlignmentStage,
    alignment_authorization_from_metadata,
    alignment_refusal_authorization,
    authorize_alignment,
    consume_alignment_authorization,
    entry_authorization_is_fresh,
    require_alignment_authorization,
    revoke_alignment_authorization,
)
from vln.parking.autonomous import (
    EntryAuthorization,
    EntryAuthorizationError,
    require_entry_authorization,
)

NOW = "2026-10-30T00:00:00+00:00"
HASHES = ("h1", "h2")


class _Binding:
    status = "bound"
    bay_id = "bay03"
    slot_node_id = "park_slot"


def _entry_authorization(**overrides) -> EntryAuthorization:
    values = dict(
        authorization_id="e" * 64,
        task_id="cap07b-02",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        verification_status="ENTRY_AUTHORIZED",
        target_confirmed=True,
        observation_ids=("obs_01_view_a", "obs_02_view_b"),
        observation_image_hashes=HASHES,
        identity_verified=True,
        occupancy_verified=True,
        evidence_sufficient=True,
        decision="ENTRY_AUTHORIZED",
        reason="two independent close-range observations",
        created_at=NOW,
        stage_history=(
            "APPROACH_COMPLETED",
            "VERIFYING_TARGET",
            "TARGET_CONFIRMED",
            "ENTRY_AUTHORIZED",
        ),
    )
    values.update(overrides)
    return EntryAuthorization(**values)


def _target():
    return bay03_alignment_target(task_id="cap07b-03")


def _authorized(**kwargs):
    defaults = dict(
        entry_authorization=_entry_authorization(),
        target=_target(),
        binding=_Binding(),
        verification_observation_hashes=HASHES,
        task_id="cap07b-03",
        now=NOW,
        ttl_s=600.0,
        budget=AlignmentBudget(),
    )
    defaults.update(kwargs)
    return authorize_alignment(**defaults)


def _consume_args():
    target = _target()
    return dict(
        task_id="cap07b-03",
        target_id=target.target_id,
        bay_id=target.bay_id,
        slot_node_id=target.slot_node_id,
        approach_node_id=target.approach_node_id,
    )


def test_valid_entry_precondition_issues_alignment_only_permission() -> None:
    authorization = _authorized()
    assert authorization.decision == "ALIGNMENT_AUTHORIZED"
    assert authorization.permits_alignment
    assert authorization.permits_entry is False
    assert authorization.permits_parking_arc is False
    assert authorization.executes_motion is False
    assert authorization.consumed_at is None
    assert authorization.entry_authorization_id == "e" * 64
    assert authorization.entry_observation_image_hashes == HASHES
    metadata = authorization.to_metadata()
    assert metadata["stage_scope"] == "ALIGNMENT"
    assert metadata["single_use"] is True
    assert metadata["permits_entry"] is False


def test_missing_entry_permission_is_refused() -> None:
    with pytest.raises(TypeError):
        authorize_alignment(
            None,
            _target(),
            binding=_Binding(),
            verification_observation_hashes=HASHES,
            task_id="cap07b-03",
        )


def test_refused_entry_permission_cannot_authorize_alignment() -> None:
    refused = _entry_authorization(
        verification_status="SAFE_STOP",
        decision="SAFE_STOP",
        target_confirmed=False,
        observation_ids=(),
        observation_image_hashes=(),
        identity_verified=False,
        occupancy_verified=False,
        evidence_sufficient=False,
        reason="vehicle_not_stopped",
        stage_history=("APPROACH_COMPLETED", "VERIFYING_TARGET", "SAFE_STOP"),
    )
    with pytest.raises(ValueError):
        _authorized(entry_authorization=refused)


def test_binding_identity_mismatch_is_refused() -> None:
    class OtherBinding:
        status = "bound"
        bay_id = "bay11"
        slot_node_id = "bay11_slot"

    with pytest.raises(ValueError):
        _authorized(binding=OtherBinding())


def test_evidence_mismatch_is_refused() -> None:
    with pytest.raises(ValueError):
        _authorized(verification_observation_hashes=("h1", "other"))


def test_single_observation_is_not_enough() -> None:
    with pytest.raises(ValueError):
        _entry_authorization(
            observation_ids=("obs_01_view_a",),
            observation_image_hashes=("h1",),
        )


def test_alignment_must_have_its_own_task_id() -> None:
    with pytest.raises(ValueError):
        _authorized(task_id="cap07b-02")


def test_expired_permission_is_not_usable() -> None:
    authorization = _authorized(ttl_s=60.0)
    assert authorization.is_usable(
        task_id="cap07b-03",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        now="2026-10-30T00:00:30+00:00",
    )
    assert not authorization.is_usable(
        task_id="cap07b-03",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        now="2026-10-30T00:02:00+00:00",
    )
    with pytest.raises(AlignmentAuthorizationError):
        consume_alignment_authorization(
            authorization, now="2026-10-30T00:02:00+00:00", **_consume_args()
        )


def test_permission_is_consumed_once() -> None:
    authorization = _authorized()
    consumed = consume_alignment_authorization(
        authorization, now="2026-10-30T00:00:10+00:00", **_consume_args()
    )
    assert consumed.consumed_at == "2026-10-30T00:00:10+00:00"
    assert not consumed.is_usable(
        task_id="cap07b-03",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        now="2026-10-30T00:00:20+00:00",
    )
    # The consumed artifact remains active for the already-started stage and
    # can fund bounded rounds until expiry/revocation.
    assert consumed.is_active(
        task_id="cap07b-03",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        now="2026-10-30T00:00:20+00:00",
    )
    with pytest.raises(AlignmentAuthorizationError):
        consume_alignment_authorization(
            consumed, now="2026-10-30T00:00:20+00:00", **_consume_args()
        )


def test_revocation_blocks_further_rounds() -> None:
    authorization = _authorized()
    revoked = replace(authorization, revoked=True, reason="operator_revoked")
    assert not revoked.is_usable(
        task_id="cap07b-03",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        now=NOW,
    )
    assert not revoked.is_active(
        task_id="cap07b-03",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        now=NOW,
    )


def test_task_id_mismatch_on_consume_is_refused() -> None:
    authorization = _authorized()
    args = _consume_args()
    args["task_id"] = "other-task"
    with pytest.raises(AlignmentAuthorizationError):
        consume_alignment_authorization(authorization, now=NOW, **args)


def test_entry_permission_cannot_be_used_as_alignment_permission() -> None:
    entry = _entry_authorization()
    with pytest.raises(AlignmentAuthorizationError):
        require_alignment_authorization(entry, now=NOW, **_consume_args())


def test_alignment_permission_cannot_be_used_as_entry_permission() -> None:
    alignment = _authorized()
    with pytest.raises(EntryAuthorizationError):
        require_entry_authorization(
            alignment,
            task_id="cap07b-02",
            target_id="bay03",
            bay_id="bay03",
            slot_node_id="park_slot",
            approach_node_id="park_entry",
            binding_status="bound",
            approach_stage="APPROACH_COMPLETED",
            observation_image_hashes=HASHES,
        )


def test_stale_entry_evidence_is_refused() -> None:
    stale = _entry_authorization(created_at="2026-10-28T00:00:00+00:00")
    with pytest.raises(ValueError):
        _authorized(entry_authorization=stale)
    assert not entry_authorization_is_fresh(
        stale, now=NOW, max_age_s=86400.0
    )
    assert entry_authorization_is_fresh(
        _entry_authorization(), now=NOW, max_age_s=86400.0
    )


def test_revocation_helper_records_reason() -> None:
    authorization = _authorized()
    revoked = revoke_alignment_authorization(
        authorization, "phase_failed", now=NOW
    )
    assert revoked.revoked
    assert revoked.reason == "phase_failed"
    assert not revoked.is_active(
        task_id="cap07b-03",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        now=NOW,
    )


def test_metadata_round_trip_validates_scope() -> None:
    authorization = _authorized()
    parsed = alignment_authorization_from_metadata(authorization.to_metadata())
    assert parsed.authorization_id == authorization.authorization_id
    assert parsed.permits_entry is False
    tampered = authorization.to_metadata()
    tampered["permits_entry"] = True
    parsed_tampered = alignment_authorization_from_metadata(tampered)
    assert parsed_tampered.permits_entry is False


def test_refusal_artifact_never_permits_motion() -> None:
    artifact = alignment_refusal_authorization(
        _target(),
        AlignmentStage.SAFE_STOP,
        "initial verification refused",
        task_id="cap07b-03",
        entry_authorization_id="e" * 64,
        now=NOW,
    )
    assert artifact.decision == "SAFE_STOP"
    assert not artifact.permits_alignment
    assert not artifact.permits_entry
    assert not artifact.permits_parking_arc


def test_budget_round_and_distance_limits() -> None:
    budget = AlignmentBudget(max_rounds=2, max_phase_distance_m=1.0,
                             max_total_distance_m=1.5)
    assert budget.can_start_round
    after_one = budget.record_round(1.0)
    assert after_one.rounds_used == 1
    assert after_one.remaining_distance_m() == pytest.approx(0.5)
    after_two = after_one.record_round(0.5)
    assert not after_two.can_start_round
    with pytest.raises(ValueError):
        after_two.record_round(0.1)


def test_budget_is_embedded_in_the_permission() -> None:
    authorization = _authorized(
        budget=AlignmentBudget(
            max_rounds=3,
            max_phase_distance_m=0.8,
            max_total_distance_m=2.0,
        )
    )
    assert authorization.max_rounds == 3
    assert authorization.max_phase_distance_m == 0.8
    assert authorization.max_total_distance_m == 2.0
    assert authorization.to_metadata()["budget"]["max_rounds"] == 3
