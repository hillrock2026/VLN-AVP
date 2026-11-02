"""Bounded recovery for visual uncertainty.

The state machine exists so a visual verification failure cannot be turned into
a motion permit by retrying. It only authorises one *new observation* at a time:

    normal -> visual verification failure
           -> safe stop (caller must confirm the vehicle is stationary)
           -> new CARLA frame (never the old frame)
           -> update Kernel Context through the normal planning exchange
           -> real Taichu re-inference
           -> the original parse/verify chain runs again
           -> route arbitration and Kernel authorisation decide execution

Non-recoverable failures (malformed model output, transport failure, stale
Context revision) and an exhausted budget fail closed. This module never builds
an ``AgentIntent``, never calls a host and never commands a vehicle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vln.carla.observation import (
    INTENT_REJECTED,
    MODEL_OUTPUT_INVALID,
    MODEL_REQUEST_FAILED,
    SUCCESS,
    DecisionOutcome,
)
from vln.nav.visual_decision import identity_matches
from vln.vlm.nav_prompt import EVIDENCE_UNCERTAINTY_ANSWERS

__all__ = [
    "VisualUncertaintyKind",
    "VisualRecoveryAction",
    "VisualRecoveryState",
    "RecoveryBudget",
    "RecoveryRefused",
    "VisualRecoveryMachine",
    "classify_visual_uncertainty",
    "reobservation_note",
    "require_new_observation",
    "ensure_context_revision_advanced",
]


class VisualUncertaintyKind:
    IDENTITY_UNKNOWN = "identity_unknown"
    IDENTITY_MISMATCH = "identity_mismatch"
    TARGET_NOT_VISIBLE = "target_not_visible"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    OBSERVATION_CONFLICT = "observation_conflict"
    ALL = frozenset(
        {
            IDENTITY_UNKNOWN,
            IDENTITY_MISMATCH,
            TARGET_NOT_VISIBLE,
            EVIDENCE_INSUFFICIENT,
            OBSERVATION_CONFLICT,
        }
    )


class VisualRecoveryAction:
    REQUEST_REOBSERVATION = "request_reobservation"
    EXHAUSTED = "exhausted"
    REFUSED = "refused"
    ALL = frozenset({REQUEST_REOBSERVATION, EXHAUSTED, REFUSED})


class VisualRecoveryState:
    NORMAL = "normal"
    REOBSERVING = "reobserving"
    RECOVERED = "recovered"
    EXHAUSTED = "exhausted"
    REFUSED = "refused"
    ALL = frozenset({NORMAL, REOBSERVING, RECOVERED, EXHAUSTED, REFUSED})


class RecoveryRefused(Exception):
    """A recovery precondition is not met; no re-observation is authorised."""


def _unknown_identity_text(value: object) -> bool:
    if not isinstance(value, str) or value.strip() == "":
        return True
    return value.strip() in EVIDENCE_UNCERTAINTY_ANSWERS


def classify_visual_uncertainty(
    outcome: object,
    *,
    expected_identity: str,
    previously_confirmed_identity: str | None = None,
    history_identities: tuple[str, ...] = (),
) -> str | None:
    """Classify one failed outcome, or return ``None`` if it is not recoverable.

    Only failures that can plausibly be improved by looking again are
    recoverable. Structural model-output failures and transport failures are
    deliberately not retried: retrying them would hide a broken contract or a
    broken bridge rather than resolve a visual ambiguity.
    """

    if not isinstance(outcome, DecisionOutcome):
        return None
    if type(expected_identity) is not str or not expected_identity.strip():
        return None
    if outcome.status == SUCCESS:
        return None
    if outcome.status in (MODEL_REQUEST_FAILED, MODEL_OUTPUT_INVALID):
        return None
    if outcome.status != INTENT_REJECTED:
        return None

    error_type = outcome.error_type
    if error_type == "TargetNotVisibleError":
        return VisualUncertaintyKind.TARGET_NOT_VISIBLE
    if error_type == "EvidenceInsufficientError":
        return VisualUncertaintyKind.EVIDENCE_INSUFFICIENT
    if error_type != "TargetIdentityMismatchError":
        return None

    decision = outcome.decision
    identified = None if decision is None else decision.identified_as
    if _unknown_identity_text(identified):
        return VisualUncertaintyKind.IDENTITY_UNKNOWN

    if (
        isinstance(previously_confirmed_identity, str)
        and identity_matches(previously_confirmed_identity, expected_identity)
        and not identity_matches(str(identified), expected_identity)
    ):
        return VisualUncertaintyKind.OBSERVATION_CONFLICT

    for historical in history_identities:
        if (
            isinstance(historical, str)
            and not identity_matches(historical, expected_identity)
            and identity_matches(str(identified), historical)
        ):
            return VisualUncertaintyKind.OBSERVATION_CONFLICT

    return VisualUncertaintyKind.IDENTITY_MISMATCH


@dataclass(frozen=True)
class RecoveryBudget:
    """Bounded retry budget for one task."""

    max_total: int = 3
    max_per_type: int = 2

    def __post_init__(self) -> None:
        if type(self.max_total) is not int or self.max_total < 0:
            raise ValueError("max_total must be a non-negative int")
        if type(self.max_per_type) is not int or self.max_per_type < 0:
            raise ValueError("max_per_type must be a non-negative int")

    def to_metadata(self) -> dict:
        return {
            "max_total": self.max_total,
            "max_per_type": self.max_per_type,
        }


@dataclass
class VisualRecoveryMachine:
    """The recovery state machine and its bounded counters."""

    budget: RecoveryBudget = field(default_factory=RecoveryBudget)
    state: str = VisualRecoveryState.NORMAL
    attempts: list[dict] = field(default_factory=list)
    counts_by_type: dict[str, int] = field(default_factory=dict)
    last_uncertainty: str | None = None
    last_reason: str = ""

    def _transition(self, state: str, reason: str) -> None:
        self.state = state
        self.last_reason = reason

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    def on_failure(self, uncertainty: str | None, *, reason: str = "") -> str:
        """Decide what may happen after one failed visual verification."""

        if uncertainty not in VisualUncertaintyKind.ALL:
            self._transition(
                VisualRecoveryState.REFUSED,
                reason or "not a recoverable visual uncertainty",
            )
            return VisualRecoveryAction.REFUSED
        if self.attempt_count >= self.budget.max_total:
            self._transition(
                VisualRecoveryState.EXHAUSTED,
                f"total recovery budget {self.budget.max_total} is exhausted",
            )
            return VisualRecoveryAction.EXHAUSTED
        used = self.counts_by_type.get(uncertainty, 0)
        if used >= self.budget.max_per_type:
            self._transition(
                VisualRecoveryState.EXHAUSTED,
                f"per-type recovery budget {self.budget.max_per_type} is "
                f"exhausted for {uncertainty}",
            )
            return VisualRecoveryAction.EXHAUSTED
        self.counts_by_type[uncertainty] = used + 1
        self.last_uncertainty = uncertainty
        self.attempts.append(
            {
                "attempt": self.attempt_count + 1,
                "uncertainty_type": uncertainty,
                "reason": reason,
            }
        )
        self._transition(
            VisualRecoveryState.REOBSERVING,
            f"re-observation {self.attempt_count} authorised for {uncertainty}",
        )
        return VisualRecoveryAction.REQUEST_REOBSERVATION

    def on_success(self) -> None:
        self._transition(
            VisualRecoveryState.RECOVERED,
            "the re-observed decision passed the original verification chain",
        )

    def refuse(self, reason: str) -> str:
        self._transition(VisualRecoveryState.REFUSED, str(reason))
        return VisualRecoveryAction.REFUSED

    def to_metadata(self) -> dict:
        return {
            "state": self.state,
            "budget": self.budget.to_metadata(),
            "attempt_count": self.attempt_count,
            "authorised_attempts": [dict(attempt) for attempt in self.attempts],
            "attempts_by_type": dict(self.counts_by_type),
            "last_uncertainty": self.last_uncertainty,
            "last_reason": self.last_reason,
            "execution_permitted": False,
        }


def reobservation_note(uncertainty: str, attempt: int) -> str:
    """A failure-specific instruction for the next real observation."""

    if uncertainty not in VisualUncertaintyKind.ALL:
        raise ValueError(f"unknown visual uncertainty {uncertainty!r}")
    if type(attempt) is not int or attempt < 1:
        raise ValueError("attempt must be a positive int")

    header = f"【视觉不确定性恢复 第 {attempt} 次】"
    if uncertainty == VisualUncertaintyKind.IDENTITY_UNKNOWN:
        body = (
            "上一轮未能从图像中确认目标身份。请只依据本轮新图像重新辨认；"
            "不得根据 Target 回显或指令文字直接填写 Identified as；"
            "只有画面中真实可辨认的目标标识才能作为身份依据。"
        )
    elif uncertainty == VisualUncertaintyKind.TARGET_NOT_VISIBLE:
        body = (
            "上一轮报告目标不可见。请先确认本轮新图像中是否真的出现目标；"
            "如果仍不可见，Visible 必须为「否」，Relative position 和 "
            "Next direction 必须写「无法确定」。"
        )
    elif uncertainty == VisualUncertaintyKind.EVIDENCE_INSUFFICIENT:
        body = (
            "上一轮证据不足。请描述本轮画面中实际可见的依据；"
            "若仍无法支持判断，Evidence 写「无法确定」，不得编造证据。"
        )
    elif uncertainty == VisualUncertaintyKind.IDENTITY_MISMATCH:
        body = (
            "上一轮从画面读到的标识与请求目标不一致。请重新读取本轮新图像中的"
            "标识；不得把请求目标名称当作读取结果；如果仍不一致，保持拒绝。"
        )
    else:
        body = (
            "当前读取与已验证的历史目标身份冲突。当前图像优先；"
            "不得用历史确认替代本轮观察；如果本轮仍不一致，保持拒绝。"
        )
    return (
        f"{header}\n{body}\n"
        "本轮图像是新采集的帧，不是上一轮的旧帧；请按原有结论块格式输出。"
    )


def require_new_observation(
    *,
    previous_frame_id: object,
    previous_image_sha256: object,
    new_frame_id: object,
    new_image_sha256: object,
) -> dict:
    """Refuse a re-observation that reuses the old frame."""

    if type(previous_frame_id) is not int or type(new_frame_id) is not int:
        raise RecoveryRefused("frame ids must be ints")
    if (
        type(previous_image_sha256) is not str
        or type(new_image_sha256) is not str
        or not previous_image_sha256
        or not new_image_sha256
    ):
        raise RecoveryRefused("image sha256 values must be non-blank strings")
    if new_frame_id <= previous_frame_id:
        raise RecoveryRefused(
            f"re-observation frame {new_frame_id} is not newer than "
            f"the failed frame {previous_frame_id}"
        )
    if new_image_sha256 == previous_image_sha256:
        raise RecoveryRefused(
            "re-observation produced the same image bytes as the failed frame"
        )
    return {
        "previous_frame_id": previous_frame_id,
        "previous_image_sha256": previous_image_sha256,
        "new_frame_id": new_frame_id,
        "new_image_sha256": new_image_sha256,
        "new_frame": True,
    }


def ensure_context_revision_advanced(previous: object, current: object) -> int:
    """Fail closed unless a planning exchange advanced the Context revision."""

    if type(previous) is not int or previous < 0:
        raise RecoveryRefused("previous context revision must be a non-negative int")
    if type(current) is not int or current <= previous:
        raise RecoveryRefused(
            f"context revision did not advance: previous={previous}, "
            f"current={current}"
        )
    return current
