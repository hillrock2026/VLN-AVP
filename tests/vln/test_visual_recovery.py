"""Bounded visual-uncertainty recovery state machine."""

from __future__ import annotations

import pytest

from vln.carla.observation import (
    INTENT_REJECTED,
    MODEL_OUTPUT_INVALID,
    MODEL_REQUEST_FAILED,
    SUCCESS,
    DecisionOutcome,
)
from vln.nav.visual_decision import VisualNavigationDecision
from vln.nav.visual_recovery import (
    RecoveryBudget,
    RecoveryRefused,
    VisualRecoveryAction,
    VisualRecoveryMachine,
    VisualRecoveryState,
    VisualUncertaintyKind,
    classify_visual_uncertainty,
    ensure_context_revision_advanced,
    reobservation_note,
    require_new_observation,
)


def _decision(
    *,
    identified_as: str = "blue car",
    visible: str = "是",
    evidence: str = "blue car visible ahead",
) -> VisualNavigationDecision:
    return VisualNavigationDecision(
        target_field="blue car",
        identified_as=identified_as,
        visible=visible,
        position="AHEAD",
        direction="STRAIGHT",
        evidence=evidence,
    )


def _outcome(
    status: str,
    *,
    error_type: str | None = None,
    decision: VisualNavigationDecision | None = None,
) -> DecisionOutcome:
    return DecisionOutcome(
        status=status,
        raw_model_output="raw",
        decision=decision,
        directive=None,
        intent=None,
        error_type=error_type,
        error_message=error_type or status,
        model_duration_seconds=0.0,
        total_duration_seconds=0.0,
    )


def test_classifies_each_visual_uncertainty_type() -> None:
    assert (
        classify_visual_uncertainty(
            _outcome(
                INTENT_REJECTED,
                error_type="TargetIdentityMismatchError",
                decision=_decision(identified_as="无法确定"),
            ),
            expected_identity="blue car",
        )
        == VisualUncertaintyKind.IDENTITY_UNKNOWN
    )
    assert (
        classify_visual_uncertainty(
            _outcome(
                INTENT_REJECTED,
                error_type="TargetIdentityMismatchError",
                decision=_decision(identified_as="red car"),
            ),
            expected_identity="blue car",
        )
        == VisualUncertaintyKind.IDENTITY_MISMATCH
    )
    assert (
        classify_visual_uncertainty(
            _outcome(
                INTENT_REJECTED,
                error_type="TargetIdentityMismatchError",
                decision=_decision(identified_as="red car"),
            ),
            expected_identity="blue car",
            previously_confirmed_identity="blue car",
        )
        == VisualUncertaintyKind.OBSERVATION_CONFLICT
    )
    assert (
        classify_visual_uncertainty(
            _outcome(
                INTENT_REJECTED,
                error_type="TargetNotVisibleError",
                decision=_decision(visible="否"),
            ),
            expected_identity="blue car",
        )
        == VisualUncertaintyKind.TARGET_NOT_VISIBLE
    )
    assert (
        classify_visual_uncertainty(
            _outcome(
                INTENT_REJECTED,
                error_type="EvidenceInsufficientError",
                decision=_decision(evidence="无法确定"),
            ),
            expected_identity="blue car",
        )
        == VisualUncertaintyKind.EVIDENCE_INSUFFICIENT
    )


def test_non_visual_failures_are_not_retried() -> None:
    assert (
        classify_visual_uncertainty(
            _outcome(MODEL_OUTPUT_INVALID, error_type="VisualDecisionParseError"),
            expected_identity="blue car",
        )
        is None
    )
    assert (
        classify_visual_uncertainty(
            _outcome(MODEL_REQUEST_FAILED, error_type="ServerClientError"),
            expected_identity="blue car",
        )
        is None
    )
    assert (
        classify_visual_uncertainty(
            _outcome(SUCCESS, decision=_decision()),
            expected_identity="blue car",
        )
        is None
    )
    assert (
        classify_visual_uncertainty(
            _outcome(
                INTENT_REJECTED,
                error_type="VisualDecisionValidationError",
                decision=_decision(),
            ),
            expected_identity="blue car",
        )
        is None
    )


def test_recovery_budget_is_total_and_per_type_bounded() -> None:
    machine = VisualRecoveryMachine(
        budget=RecoveryBudget(max_total=3, max_per_type=2)
    )
    assert (
        machine.on_failure(VisualUncertaintyKind.IDENTITY_UNKNOWN)
        == VisualRecoveryAction.REQUEST_REOBSERVATION
    )
    assert (
        machine.on_failure(VisualUncertaintyKind.TARGET_NOT_VISIBLE)
        == VisualRecoveryAction.REQUEST_REOBSERVATION
    )
    assert (
        machine.on_failure(VisualUncertaintyKind.IDENTITY_UNKNOWN)
        == VisualRecoveryAction.REQUEST_REOBSERVATION
    )
    assert (
        machine.on_failure(VisualUncertaintyKind.EVIDENCE_INSUFFICIENT)
        == VisualRecoveryAction.EXHAUSTED
    )
    assert machine.state == VisualRecoveryState.EXHAUSTED
    assert machine.to_metadata()["execution_permitted"] is False


def test_per_type_limit_is_enforced_independently_of_total() -> None:
    machine = VisualRecoveryMachine(
        budget=RecoveryBudget(max_total=5, max_per_type=1)
    )
    assert (
        machine.on_failure(VisualUncertaintyKind.IDENTITY_UNKNOWN)
        == VisualRecoveryAction.REQUEST_REOBSERVATION
    )
    assert (
        machine.on_failure(VisualUncertaintyKind.IDENTITY_MISMATCH)
        == VisualRecoveryAction.REQUEST_REOBSERVATION
    )
    assert (
        machine.on_failure(VisualUncertaintyKind.IDENTITY_UNKNOWN)
        == VisualRecoveryAction.EXHAUSTED
    )


def test_repeated_invisibility_exhausts_without_a_permit() -> None:
    machine = VisualRecoveryMachine(
        budget=RecoveryBudget(max_total=2, max_per_type=2)
    )
    assert (
        machine.on_failure(VisualUncertaintyKind.TARGET_NOT_VISIBLE)
        == VisualRecoveryAction.REQUEST_REOBSERVATION
    )
    assert (
        machine.on_failure(VisualUncertaintyKind.TARGET_NOT_VISIBLE)
        == VisualRecoveryAction.REQUEST_REOBSERVATION
    )
    assert (
        machine.on_failure(VisualUncertaintyKind.TARGET_NOT_VISIBLE)
        == VisualRecoveryAction.EXHAUSTED
    )
    assert machine.state == VisualRecoveryState.EXHAUSTED
    assert machine.to_metadata()["execution_permitted"] is False


def test_mismatch_after_reobservation_stays_rejected() -> None:
    machine = VisualRecoveryMachine(
        budget=RecoveryBudget(max_total=2, max_per_type=1)
    )
    assert (
        machine.on_failure(VisualUncertaintyKind.IDENTITY_UNKNOWN)
        == VisualRecoveryAction.REQUEST_REOBSERVATION
    )
    # The new image now reads a concrete but wrong identity. The machine may
    # authorise one more look but never marks the task recovered.
    assert (
        machine.on_failure(VisualUncertaintyKind.IDENTITY_MISMATCH)
        == VisualRecoveryAction.REQUEST_REOBSERVATION
    )
    assert (
        machine.on_failure(VisualUncertaintyKind.IDENTITY_MISMATCH)
        == VisualRecoveryAction.EXHAUSTED
    )
    assert machine.state != VisualRecoveryState.RECOVERED
    assert machine.to_metadata()["execution_permitted"] is False


def test_non_recoverable_failure_is_refused_and_success_is_explicit() -> None:
    machine = VisualRecoveryMachine()
    assert machine.on_failure(None) == VisualRecoveryAction.REFUSED
    assert machine.state == VisualRecoveryState.REFUSED

    recovered = VisualRecoveryMachine()
    assert (
        recovered.on_failure(VisualUncertaintyKind.IDENTITY_UNKNOWN)
        == VisualRecoveryAction.REQUEST_REOBSERVATION
    )
    recovered.on_success()
    assert recovered.state == VisualRecoveryState.RECOVERED
    assert recovered.to_metadata()["execution_permitted"] is False


def test_reobservation_notes_are_failure_specific() -> None:
    unknown = reobservation_note(VisualUncertaintyKind.IDENTITY_UNKNOWN, 1)
    invisible = reobservation_note(
        VisualUncertaintyKind.TARGET_NOT_VISIBLE, 1
    )
    mismatch = reobservation_note(VisualUncertaintyKind.IDENTITY_MISMATCH, 1)
    assert unknown != invisible != mismatch
    assert "身份" in unknown
    assert "不可见" in invisible
    assert "不一致" in mismatch
    for note in (unknown, invisible, mismatch):
        assert "新采集" in note
        assert "旧帧" in note


def test_reobservation_requires_a_new_frame_and_bytes() -> None:
    with pytest.raises(RecoveryRefused):
        require_new_observation(
            previous_frame_id=10,
            previous_image_sha256="a" * 64,
            new_frame_id=10,
            new_image_sha256="b" * 64,
        )
    with pytest.raises(RecoveryRefused):
        require_new_observation(
            previous_frame_id=10,
            previous_image_sha256="a" * 64,
            new_frame_id=11,
            new_image_sha256="a" * 64,
        )
    record = require_new_observation(
        previous_frame_id=10,
        previous_image_sha256="a" * 64,
        new_frame_id=11,
        new_image_sha256="b" * 64,
    )
    assert record["new_frame"] is True


def test_context_revision_must_advance() -> None:
    assert ensure_context_revision_advanced(2, 3) == 3
    with pytest.raises(RecoveryRefused):
        ensure_context_revision_advanced(2, 2)
    with pytest.raises(RecoveryRefused):
        ensure_context_revision_advanced(2, None)
