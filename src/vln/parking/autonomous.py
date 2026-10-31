"""Minimal ``vln.parking.autonomous`` skill: approach -> target verification.

This is the VLN-AVP-side skill layer. The Agent-Kernel in this repository
registers capabilities, not a stageful Skill schema; adding a Kernel
capability for a verification that never moves the vehicle would be an
unnecessary interface change. This module therefore mirrors the existing
``vln.navigation.recovery`` skill style: a pure, deterministic stage machine
that consumes real pipeline observations and returns an explicit artifact.

Only two stages are implemented:

    APPROACH_COMPLETED -> TARGET_VERIFICATION -> TARGET_CONFIRMED
                                                -> ENTRY_AUTHORIZED
                                                -> UNVERIFIED / REJECTED / SAFE_STOP

``TARGET_CONFIRMED`` does not permit entry. A separate deterministic
:func:`authorize_entry` call re-checks the final safety conditions and emits
the permission. The permission is bound to the current task, target, bay, slot,
approach node and the exact observation image hashes; it is never derived from
raw model text and it never moves the vehicle.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence

__all__ = [
    "AUTONOMOUS_PARKING_SKILL",
    "AutonomousParkingStage",
    "EntryAuthorizationError",
    "ApproachState",
    "VerificationObservation",
    "TargetVerificationResult",
    "EntryAuthorization",
    "approach_state_from_result",
    "verify_target",
    "authorize_entry",
    "refusal_authorization",
    "authorization_is_usable",
    "require_entry_authorization",
    "entry_authorization_from_metadata",
]


AUTONOMOUS_PARKING_SKILL = "vln.parking.autonomous"
_OCCUPANCIES = frozenset({"vacant", "occupied", "unknown"})
_DECISIONS = frozenset({"ENTRY_AUTHORIZED", "UNVERIFIED", "REJECTED", "SAFE_STOP"})


class AutonomousParkingStage:
    """Explicit stage values; only APPROACH_COMPLETED starts verification."""

    APPROACH_COMPLETED = "APPROACH_COMPLETED"
    VERIFYING_TARGET = "VERIFYING_TARGET"
    TARGET_CONFIRMED = "TARGET_CONFIRMED"
    ENTRY_AUTHORIZED = "ENTRY_AUTHORIZED"
    UNVERIFIED = "UNVERIFIED"
    REJECTED = "REJECTED"
    SAFE_STOP = "SAFE_STOP"

    ALL = frozenset(
        {
            APPROACH_COMPLETED,
            VERIFYING_TARGET,
            TARGET_CONFIRMED,
            ENTRY_AUTHORIZED,
            UNVERIFIED,
            REJECTED,
            SAFE_STOP,
        }
    )


class EntryAuthorizationError(RuntimeError):
    """An entry permission is absent, for another task, or no longer current."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nonblank(value: object, name: str) -> str:
    if type(value) is not str or value.strip() == "":
        raise ValueError(f"{name} must be a non-blank str")
    return value


@dataclass(frozen=True)
class ApproachState:
    """The already-completed CAP-07B-01 approach identity and real pose."""

    task_id: str
    target_id: str
    bay_id: str
    slot_node_id: str
    approach_node_id: str
    stage: str = AutonomousParkingStage.APPROACH_COMPLETED
    pose: Mapping[str, float] = field(default_factory=dict)
    speed_mps: float = 0.0
    source: str = "cap07b-01"
    binding_status: str = "bound"

    def __post_init__(self) -> None:
        for name in (
            "task_id",
            "target_id",
            "bay_id",
            "slot_node_id",
            "approach_node_id",
        ):
            _nonblank(getattr(self, name), name)
        if self.stage != AutonomousParkingStage.APPROACH_COMPLETED:
            raise ValueError("approach state must be APPROACH_COMPLETED")
        if self.binding_status != "bound":
            raise ValueError("approach state requires a bound target")
        if type(self.speed_mps) not in (int, float):
            raise ValueError("speed_mps must be a number")
        if self.speed_mps < 0:
            raise ValueError("speed_mps must be non-negative")
        if not isinstance(self.pose, Mapping):
            raise ValueError("pose must be a mapping")

    def matches_binding(self, binding: object) -> bool:
        return (
            getattr(binding, "status", None) == "bound"
            and getattr(binding, "bay_id", None) == self.bay_id
            and getattr(binding, "slot_node_id", None) == self.slot_node_id
        )

    def to_metadata(self) -> dict:
        return {
            "skill": AUTONOMOUS_PARKING_SKILL,
            "stage": self.stage,
            "task_id": self.task_id,
            "target_id": self.target_id,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "approach_node_id": self.approach_node_id,
            "pose": dict(self.pose),
            "speed_mps": round(float(self.speed_mps), 3),
            "source": self.source,
            "binding_status": self.binding_status,
        }


@dataclass(frozen=True)
class VerificationObservation:
    """One fresh close-range observation, already parsed and associated."""

    observation_id: str
    entity_bay_id: str
    image_path: str
    image_sha256: str
    raw_image_path: str
    raw_image_sha256: str
    frame_id: int
    captured_at: str
    pose: Mapping[str, float]
    camera: Mapping[str, float]
    view_signature: str
    model_request_id: str
    server_response_id: Optional[str]
    model_text: str
    occupancy: str
    boundary_clear: bool
    occluded: bool
    evidence_sufficient: bool
    identity_verified: bool
    identity_mismatch: bool
    parse_ok: bool
    request_ok: bool
    reasons: tuple[str, ...] = ()
    model_metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "entity_bay_id",
            "image_path",
            "image_sha256",
            "raw_image_path",
            "raw_image_sha256",
            "view_signature",
            "model_request_id",
        ):
            _nonblank(getattr(self, name), name)
        if type(self.frame_id) is not int or self.frame_id < 0:
            raise ValueError("frame_id must be a non-negative int")
        _nonblank(self.captured_at, "captured_at")
        if self.occupancy not in _OCCUPANCIES:
            raise ValueError(f"unknown occupancy {self.occupancy!r}")
        for name in (
            "boundary_clear",
            "occluded",
            "evidence_sufficient",
            "identity_verified",
            "identity_mismatch",
            "parse_ok",
            "request_ok",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a bool")
        if self.server_response_id is not None and type(self.server_response_id) is not str:
            raise ValueError("server_response_id must be a str or None")
        if type(self.model_text) is not str:
            raise ValueError("model_text must be a str")

    @property
    def valid(self) -> bool:
        return self.request_ok and self.parse_ok

    def to_metadata(self) -> dict:
        return {
            "observation_id": self.observation_id,
            "entity_bay_id": self.entity_bay_id,
            "image_path": self.image_path,
            "image_sha256": self.image_sha256,
            "raw_image_path": self.raw_image_path,
            "raw_image_sha256": self.raw_image_sha256,
            "frame_id": self.frame_id,
            "captured_at": self.captured_at,
            "pose": dict(self.pose),
            "camera": dict(self.camera),
            "view_signature": self.view_signature,
            "model_request_id": self.model_request_id,
            "server_response_id": self.server_response_id,
            "model_text": self.model_text,
            "occupancy": self.occupancy,
            "boundary_clear": self.boundary_clear,
            "occluded": self.occluded,
            "evidence_sufficient": self.evidence_sufficient,
            "identity_verified": self.identity_verified,
            "identity_mismatch": self.identity_mismatch,
            "parse_ok": self.parse_ok,
            "request_ok": self.request_ok,
            "reasons": list(self.reasons),
            "model_metadata": dict(self.model_metadata),
        }


@dataclass(frozen=True)
class TargetVerificationResult:
    """The deterministic result of comparing all close-range observations."""

    stage: str
    task_id: str
    target_id: str
    bay_id: str
    slot_node_id: str
    approach_node_id: str
    observation_ids: tuple[str, ...]
    observation_image_hashes: tuple[str, ...]
    identity_verified: bool
    occupancy_verified: bool
    evidence_sufficient: bool
    target_confirmed: bool
    reasons: tuple[str, ...]
    stage_history: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.stage not in (
            AutonomousParkingStage.TARGET_CONFIRMED,
            AutonomousParkingStage.UNVERIFIED,
            AutonomousParkingStage.REJECTED,
            AutonomousParkingStage.SAFE_STOP,
        ):
            raise ValueError(f"unexpected verification stage {self.stage!r}")
        for name in (
            "task_id",
            "target_id",
            "bay_id",
            "slot_node_id",
            "approach_node_id",
        ):
            _nonblank(getattr(self, name), name)
        if self.stage == AutonomousParkingStage.TARGET_CONFIRMED:
            if not self.target_confirmed:
                raise ValueError("TARGET_CONFIRMED must set target_confirmed")
            if self.reasons:
                raise ValueError("TARGET_CONFIRMED cannot carry failure reasons")
        elif self.target_confirmed:
            raise ValueError("target_confirmed is only true for TARGET_CONFIRMED")
        if not self.target_confirmed and not self.reasons:
            raise ValueError("a non-confirmed result must carry at least one reason")

    @property
    def entry_ready(self) -> bool:
        return self.stage == AutonomousParkingStage.TARGET_CONFIRMED

    def to_metadata(self) -> dict:
        return {
            "skill": AUTONOMOUS_PARKING_SKILL,
            "stage": self.stage,
            "task_id": self.task_id,
            "target_id": self.target_id,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "approach_node_id": self.approach_node_id,
            "observation_ids": list(self.observation_ids),
            "observation_image_hashes": list(self.observation_image_hashes),
            "identity_verified": self.identity_verified,
            "occupancy_verified": self.occupancy_verified,
            "evidence_sufficient": self.evidence_sufficient,
            "target_confirmed": self.target_confirmed,
            "reasons": list(self.reasons),
            "stage_history": list(self.stage_history),
        }


@dataclass(frozen=True)
class EntryAuthorization:
    """The permission artifact (or an explicit refusal artifact)."""

    authorization_id: str
    task_id: str
    target_id: str
    bay_id: str
    slot_node_id: str
    approach_node_id: str
    verification_status: str
    target_confirmed: bool
    observation_ids: tuple[str, ...]
    observation_image_hashes: tuple[str, ...]
    identity_verified: bool
    occupancy_verified: bool
    evidence_sufficient: bool
    decision: str
    reason: str
    created_at: str
    stage_history: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.verification_status not in _DECISIONS:
            raise ValueError(
                f"unknown verification status {self.verification_status!r}"
            )
        if self.decision not in _DECISIONS:
            raise ValueError(f"unknown decision {self.decision!r}")
        if self.verification_status != self.decision:
            raise ValueError("verification_status and decision must agree")
        for name in (
            "authorization_id",
            "task_id",
            "target_id",
            "bay_id",
            "slot_node_id",
            "approach_node_id",
            "created_at",
        ):
            _nonblank(getattr(self, name), name)
        if len(self.observation_ids) != len(self.observation_image_hashes):
            raise ValueError("observation ids and image hashes must have equal length")
        if self.decision == "ENTRY_AUTHORIZED":
            if not self.target_confirmed:
                raise ValueError("ENTRY_AUTHORIZED requires target_confirmed")
            if len(self.observation_ids) < 2:
                raise ValueError("ENTRY_AUTHORIZED requires at least two observations")
            if len(set(self.observation_image_hashes)) < 2:
                raise ValueError(
                    "ENTRY_AUTHORIZED requires two distinct observation images"
                )
            if not (
                self.identity_verified
                and self.occupancy_verified
                and self.evidence_sufficient
            ):
                raise ValueError(
                    "ENTRY_AUTHORIZED requires identity, occupancy and evidence"
                )

    @property
    def permits_entry(self) -> bool:
        return self.decision == "ENTRY_AUTHORIZED"

    @property
    def executes_motion(self) -> bool:
        """The permission is a decision artifact; it never drives a vehicle."""

        return False

    def is_usable_by(
        self,
        *,
        task_id: str,
        target_id: str,
        bay_id: str,
        slot_node_id: str,
        approach_node_id: str,
    ) -> bool:
        return (
            self.permits_entry
            and self.task_id == task_id
            and self.target_id == target_id
            and self.bay_id == bay_id
            and self.slot_node_id == slot_node_id
            and self.approach_node_id == approach_node_id
        )

    def is_current(
        self,
        *,
        binding_status: str,
        approach_stage: str,
        observation_image_hashes: Sequence[str],
    ) -> bool:
        """False when the bound identity, stage or evidence has changed."""

        if not self.permits_entry:
            return False
        if binding_status != "bound":
            return False
        if approach_stage != AutonomousParkingStage.APPROACH_COMPLETED:
            return False
        current = [hash_value for hash_value in observation_image_hashes]
        return set(current) == set(self.observation_image_hashes)

    def to_metadata(self) -> dict:
        return {
            "schema": "vln.parking.entry_authorization.v1",
            "skill": AUTONOMOUS_PARKING_SKILL,
            "authorization_id": self.authorization_id,
            "task_id": self.task_id,
            "target_id": self.target_id,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "approach_node_id": self.approach_node_id,
            "verification_status": self.verification_status,
            "target_confirmed": self.target_confirmed,
            "observation_ids": list(self.observation_ids),
            "observation_image_hashes": list(self.observation_image_hashes),
            "identity_verified": self.identity_verified,
            "occupancy_verified": self.occupancy_verified,
            "evidence_sufficient": self.evidence_sufficient,
            "decision": self.decision,
            "reason": self.reason,
            "created_at": self.created_at,
            "stage_history": list(self.stage_history),
            "permits_entry": self.permits_entry,
            "executes_motion": False,
        }


def approach_state_from_result(result: Mapping[str, object]) -> ApproachState:
    """Recover ``APPROACH_COMPLETED`` from a verified CAP-07B-01 result."""

    if not isinstance(result, Mapping):
        raise ValueError("approach result must be a JSON object")
    if result.get("status") != "PASS":
        raise ValueError("approach result is not PASS")
    if result.get("task_status") != "goal_reached":
        raise ValueError("approach result did not reach the goal")
    verdict = result.get("target_approach_verdict")
    if not isinstance(verdict, Mapping) or verdict.get("ok") is not True:
        raise ValueError("approach target verdict is not ok")
    meta = result.get("meta")
    if not isinstance(meta, Mapping):
        raise ValueError("approach result has no meta")
    binding = meta.get("target_binding")
    approach = meta.get("target_approach")
    final_state = result.get("final_state")
    if not isinstance(binding, Mapping) or binding.get("status") != "bound":
        raise ValueError("approach binding is not bound")
    if not isinstance(approach, Mapping) or not approach.get("enabled"):
        raise ValueError("approach metadata is not enabled")
    if not isinstance(final_state, Mapping):
        raise ValueError("approach result has no final_state")
    identity = {
        "task_id": approach.get("task_id"),
        "target_id": approach.get("target_id"),
        "bay_id": approach.get("bay_id"),
        "slot_node_id": approach.get("slot_node_id"),
        "approach_node_id": approach.get("approach_node_id"),
    }
    if identity["bay_id"] != binding.get("bay_id"):
        raise ValueError("approach bay does not match the binding")
    if identity["slot_node_id"] != binding.get("slot_node_id"):
        raise ValueError("approach slot does not match the binding")
    pose = {
        "x": final_state.get("x"),
        "y": final_state.get("y"),
        "z": final_state.get("z"),
        "yaw": final_state.get("yaw"),
    }
    return ApproachState(
        **identity,
        pose=pose,
        speed_mps=float(final_state.get("speed", 0.0)),
        source="cap07b-01",
        binding_status="bound",
    )


def _verification(
    approach: ApproachState,
    stage: str,
    observations: Sequence[VerificationObservation],
    reasons: Sequence[str],
    *,
    identity_verified: bool,
    occupancy_verified: bool,
    evidence_sufficient: bool,
) -> TargetVerificationResult:
    confirmed = stage == AutonomousParkingStage.TARGET_CONFIRMED
    history = [
        AutonomousParkingStage.APPROACH_COMPLETED,
        AutonomousParkingStage.VERIFYING_TARGET,
        stage,
    ]
    return TargetVerificationResult(
        stage=stage,
        task_id=approach.task_id,
        target_id=approach.target_id,
        bay_id=approach.bay_id,
        slot_node_id=approach.slot_node_id,
        approach_node_id=approach.approach_node_id,
        observation_ids=tuple(item.observation_id for item in observations),
        observation_image_hashes=tuple(item.image_sha256 for item in observations),
        identity_verified=identity_verified,
        occupancy_verified=occupancy_verified,
        evidence_sufficient=evidence_sufficient,
        target_confirmed=confirmed,
        reasons=tuple(dict.fromkeys(reasons)),
        stage_history=tuple(history),
    )


def verify_target(
    approach: ApproachState,
    observations: Sequence[VerificationObservation],
    *,
    binding: object,
    stopped: bool,
    collision_count: int = 0,
) -> TargetVerificationResult:
    """Apply the deterministic two-observation target-verification rules."""

    if not isinstance(approach, ApproachState):
        raise TypeError("approach must be an ApproachState")
    if type(stopped) is not bool:
        raise ValueError("stopped must be a bool")
    if type(collision_count) is not int or collision_count < 0:
        raise ValueError("collision_count must be a non-negative int")
    obs = tuple(observations)
    if any(not isinstance(item, VerificationObservation) for item in obs):
        raise TypeError("observations must contain VerificationObservation")

    if approach.stage != AutonomousParkingStage.APPROACH_COMPLETED:
        return _verification(
            approach,
            AutonomousParkingStage.SAFE_STOP,
            obs,
            ["approach_not_completed"],
            identity_verified=False,
            occupancy_verified=False,
            evidence_sufficient=False,
        )
    if not approach.matches_binding(binding):
        return _verification(
            approach,
            AutonomousParkingStage.REJECTED,
            obs,
            ["binding_identity_mismatch"],
            identity_verified=False,
            occupancy_verified=False,
            evidence_sufficient=False,
        )
    if not stopped or approach.speed_mps >= 0.25 or collision_count:
        reasons = []
        if not stopped or approach.speed_mps >= 0.25:
            reasons.append("vehicle_not_stopped")
        if collision_count:
            reasons.append(f"collision_count={collision_count}")
        return _verification(
            approach,
            AutonomousParkingStage.SAFE_STOP,
            obs,
            reasons,
            identity_verified=False,
            occupancy_verified=False,
            evidence_sufficient=False,
        )
    if len(obs) < 2:
        return _verification(
            approach,
            AutonomousParkingStage.UNVERIFIED,
            obs,
            ["fewer_than_two_observations"],
            identity_verified=False,
            occupancy_verified=False,
            evidence_sufficient=False,
        )

    # Positive rejection: a visible mismatch or occupancy is decisive.
    for item in obs:
        if item.entity_bay_id != approach.bay_id:
            return _verification(
                approach,
                AutonomousParkingStage.REJECTED,
                obs,
                [f"observation_entity_mismatch:{item.observation_id}"],
                identity_verified=False,
                occupancy_verified=False,
                evidence_sufficient=False,
            )
        if item.identity_mismatch:
            return _verification(
                approach,
                AutonomousParkingStage.REJECTED,
                obs,
                [f"identity_mismatch:{item.observation_id}"],
                identity_verified=False,
                occupancy_verified=False,
                evidence_sufficient=False,
            )
        if item.occupancy == "occupied":
            return _verification(
                approach,
                AutonomousParkingStage.REJECTED,
                obs,
                [f"target_occupied:{item.observation_id}"],
                identity_verified=False,
                occupancy_verified=False,
                evidence_sufficient=False,
            )

    if len({item.image_sha256 for item in obs}) != len(obs):
        return _verification(
            approach,
            AutonomousParkingStage.UNVERIFIED,
            obs,
            ["duplicate_observation_image"],
            identity_verified=False,
            occupancy_verified=False,
            evidence_sufficient=False,
        )
    if len({item.view_signature for item in obs}) != len(obs):
        return _verification(
            approach,
            AutonomousParkingStage.UNVERIFIED,
            obs,
            ["no_independent_view_difference"],
            identity_verified=False,
            occupancy_verified=False,
            evidence_sufficient=False,
        )

    reasons: list[str] = []
    identity_ok = True
    occupancy_ok = True
    evidence_ok = True
    for item in obs:
        if not item.request_ok:
            reasons.append(f"model_request_failed:{item.observation_id}")
            evidence_ok = False
            continue
        if not item.parse_ok:
            reasons.append(f"observation_unparseable:{item.observation_id}")
            evidence_ok = False
            continue
        if not item.identity_verified:
            reasons.append(f"identity_unverified:{item.observation_id}")
            identity_ok = False
        if item.occupancy != "vacant":
            reasons.append(f"occupancy_unverified:{item.observation_id}")
            occupancy_ok = False
        if not item.boundary_clear:
            reasons.append(f"boundary_unclear:{item.observation_id}")
            evidence_ok = False
        if item.occluded:
            reasons.append(f"view_occluded:{item.observation_id}")
            evidence_ok = False
        if not item.evidence_sufficient:
            reasons.append(f"evidence_insufficient:{item.observation_id}")
            evidence_ok = False

    if reasons:
        return _verification(
            approach,
            AutonomousParkingStage.UNVERIFIED,
            obs,
            reasons,
            identity_verified=identity_ok,
            occupancy_verified=occupancy_ok,
            evidence_sufficient=evidence_ok,
        )
    return _verification(
        approach,
        AutonomousParkingStage.TARGET_CONFIRMED,
        obs,
        (),
        identity_verified=True,
        occupancy_verified=True,
        evidence_sufficient=True,
    )


def _authorization_id(
    *,
    task_id: str,
    target_id: str,
    bay_id: str,
    slot_node_id: str,
    approach_node_id: str,
    decision: str,
    observation_hashes: Sequence[str],
    created_at: str,
) -> str:
    payload = {
        "task_id": task_id,
        "target_id": target_id,
        "bay_id": bay_id,
        "slot_node_id": slot_node_id,
        "approach_node_id": approach_node_id,
        "decision": decision,
        "observation_image_hashes": list(observation_hashes),
        "created_at": created_at,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def authorize_entry(
    verification: TargetVerificationResult,
    *,
    stopped: bool,
    collision_count: int = 0,
    now: Optional[str] = None,
) -> EntryAuthorization:
    """Emit ENTRY_AUTHORIZED only after a confirmed, still-safe stop."""

    if not isinstance(verification, TargetVerificationResult):
        raise TypeError("verification must be a TargetVerificationResult")
    if type(stopped) is not bool:
        raise ValueError("stopped must be a bool")
    if type(collision_count) is not int or collision_count < 0:
        raise ValueError("collision_count must be a non-negative int")
    created_at = now or _utc_now()
    decision = verification.stage
    reason = (
        "two independent close-range observations confirm the bound target is "
        "vacant and the vehicle is stopped"
        if verification.stage == AutonomousParkingStage.TARGET_CONFIRMED
        else "; ".join(verification.reasons)
    )
    if verification.stage == AutonomousParkingStage.TARGET_CONFIRMED:
        if not stopped or collision_count:
            decision = AutonomousParkingStage.SAFE_STOP
            reason = (
                "vehicle_not_stopped"
                if not stopped
                else f"collision_count={collision_count}"
            )
        else:
            decision = AutonomousParkingStage.ENTRY_AUTHORIZED
    history = list(verification.stage_history)
    if decision not in history:
        history.append(decision)
    return EntryAuthorization(
        authorization_id=_authorization_id(
            task_id=verification.task_id,
            target_id=verification.target_id,
            bay_id=verification.bay_id,
            slot_node_id=verification.slot_node_id,
            approach_node_id=verification.approach_node_id,
            decision=decision,
            observation_hashes=verification.observation_image_hashes,
            created_at=created_at,
        ),
        task_id=verification.task_id,
        target_id=verification.target_id,
        bay_id=verification.bay_id,
        slot_node_id=verification.slot_node_id,
        approach_node_id=verification.approach_node_id,
        verification_status=decision,
        target_confirmed=verification.target_confirmed,
        observation_ids=verification.observation_ids,
        observation_image_hashes=verification.observation_image_hashes,
        identity_verified=verification.identity_verified,
        occupancy_verified=verification.occupancy_verified,
        evidence_sufficient=verification.evidence_sufficient,
        decision=decision,
        reason=reason,
        created_at=created_at,
        stage_history=tuple(history),
    )


def refusal_authorization(
    approach: ApproachState,
    decision: str,
    reason: str,
    *,
    now: Optional[str] = None,
) -> EntryAuthorization:
    """Build an explicit refusal artifact for a setup/safety gate failure."""

    if decision not in (
        AutonomousParkingStage.UNVERIFIED,
        AutonomousParkingStage.REJECTED,
        AutonomousParkingStage.SAFE_STOP,
    ):
        raise ValueError(f"refusal decision must be UNVERIFIED/REJECTED/SAFE_STOP")
    verification = TargetVerificationResult(
        stage=decision,
        task_id=approach.task_id,
        target_id=approach.target_id,
        bay_id=approach.bay_id,
        slot_node_id=approach.slot_node_id,
        approach_node_id=approach.approach_node_id,
        observation_ids=(),
        observation_image_hashes=(),
        identity_verified=False,
        occupancy_verified=False,
        evidence_sufficient=False,
        target_confirmed=False,
        reasons=(reason,),
        stage_history=(
            AutonomousParkingStage.APPROACH_COMPLETED,
            AutonomousParkingStage.VERIFYING_TARGET,
            decision,
        ),
    )
    return authorize_entry(verification, stopped=True, collision_count=0, now=now)


def authorization_is_usable(
    authorization: EntryAuthorization,
    *,
    task_id: str,
    target_id: str,
    bay_id: str,
    slot_node_id: str,
    approach_node_id: str,
    binding_status: str,
    approach_stage: str,
    observation_image_hashes: Sequence[str],
) -> bool:
    """Check task/identity/evidence freshness before any future entry stage."""

    if not isinstance(authorization, EntryAuthorization):
        return False
    return authorization.is_usable_by(
        task_id=task_id,
        target_id=target_id,
        bay_id=bay_id,
        slot_node_id=slot_node_id,
        approach_node_id=approach_node_id,
    ) and authorization.is_current(
        binding_status=binding_status,
        approach_stage=approach_stage,
        observation_image_hashes=observation_image_hashes,
    )


def require_entry_authorization(
    authorization: EntryAuthorization,
    *,
    task_id: str,
    target_id: str,
    bay_id: str,
    slot_node_id: str,
    approach_node_id: str,
    binding_status: str,
    approach_stage: str,
    observation_image_hashes: Sequence[str],
) -> None:
    """Raise unless the permission is authorized, for this target and current."""

    if not authorization_is_usable(
        authorization,
        task_id=task_id,
        target_id=target_id,
        bay_id=bay_id,
        slot_node_id=slot_node_id,
        approach_node_id=approach_node_id,
        binding_status=binding_status,
        approach_stage=approach_stage,
        observation_image_hashes=observation_image_hashes,
    ):
        raise EntryAuthorizationError(
            "entry authorization is absent, for another task/target, or no "
            "longer current"
        )


def entry_authorization_from_metadata(
    metadata: Mapping[str, object],
) -> EntryAuthorization:
    """Validate an on-disk CAP-07B-02 permission before consuming it.

    This is an additive reader: it does not change the historical artifact
    contract. Missing fields, wrong types, a refusal decision or an
    ``executes_motion`` flag are refused by the dataclass invariants instead of
    being repaired.
    """

    if not isinstance(metadata, Mapping):
        raise ValueError("entry authorization must be a JSON object")
    schema = metadata.get("schema")
    if schema not in (None, "vln.parking.entry_authorization.v1"):
        raise ValueError(f"unexpected entry authorization schema {schema!r}")
    observation_ids = metadata.get("observation_ids")
    hashes = metadata.get("observation_image_hashes")
    history = metadata.get("stage_history")
    if not isinstance(observation_ids, list):
        raise ValueError("observation_ids must be a list")
    if not isinstance(hashes, list):
        raise ValueError("observation_image_hashes must be a list")
    if not isinstance(history, list):
        raise ValueError("stage_history must be a list")
    if metadata.get("executes_motion") not in (None, False):
        raise ValueError("entry authorization claims to execute motion")
    return EntryAuthorization(
        authorization_id=metadata.get("authorization_id"),
        task_id=metadata.get("task_id"),
        target_id=metadata.get("target_id"),
        bay_id=metadata.get("bay_id"),
        slot_node_id=metadata.get("slot_node_id"),
        approach_node_id=metadata.get("approach_node_id"),
        verification_status=metadata.get("verification_status"),
        target_confirmed=metadata.get("target_confirmed"),
        observation_ids=tuple(observation_ids),
        observation_image_hashes=tuple(hashes),
        identity_verified=metadata.get("identity_verified"),
        occupancy_verified=metadata.get("occupancy_verified"),
        evidence_sufficient=metadata.get("evidence_sufficient"),
        decision=metadata.get("decision"),
        reason=metadata.get("reason", ""),
        created_at=metadata.get("created_at"),
        stage_history=tuple(history),
    )
