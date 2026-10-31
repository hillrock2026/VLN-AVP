"""Binding decision layer: model letter -> real bay, or a refusal.

Three jobs, mirroring :mod:`vln.nav.visual_decision`:

1. :func:`parse_binding_decision` (structure) reads the closed-vocabulary answer
   block. It refuses missing/duplicate labels, invented labels and
   off-vocabulary occupancy values. It does not decide executability.
2. :func:`resolve_target_binding` (executability) maps a chosen temporary letter
   back to a real scene entity and applies system-side constraints: the bay must
   be visible, on the requested side, and vacant. Occupancy ``unknown`` never
   counts as vacant. More than one candidate satisfying the constraints is
   ``ambiguous`` even when the model chose one: a model choice is not evidence
   that the other candidate is different.
3. :class:`TargetBinding` / :class:`BindingArtifact` carry the result across
   rounds and to the navigation runtime. Once a bay is bound, later rounds
   re-observe the same ``bay_id``; a different model letter does not rebind it.
   A bound target that becomes occupied is ``invalidated`` and is never
   silently replaced by another bay.

The letters are temporary per-frame tokens. Identity is always ``bay_id`` /
``slot_node_id`` supplied by :mod:`vln.carla.parking_entities`, never by the
model and never by the instruction.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from vln.nav.parking_request import (
    SIDE_UNSPECIFIED,
    ParkingInstruction,
)
from vln.vlm.binding_prompt import (
    OCCUPANCY_ANSWERS,
    OCCUPANCY_OCCUPIED_ANSWER,
    OCCUPANCY_UNKNOWN_ANSWER,
    OCCUPANCY_VACANT_ANSWER,
    SELECTED_FIELD,
)

__all__ = [
    "BindingStatus",
    "BindingDecisionParseError",
    "BindingNotExecutableError",
    "BindingDecision",
    "CandidateObservation",
    "TargetBinding",
    "BindingArtifact",
    "parse_binding_decision",
    "resolve_target_binding",
    "parse_binding_artifact",
    "binding_goal_node",
    "INTERNAL_VACANT",
    "INTERNAL_OCCUPIED",
    "INTERNAL_UNKNOWN",
]


INTERNAL_VACANT = "vacant"
INTERNAL_OCCUPIED = "occupied"
INTERNAL_UNKNOWN = "unknown"
_INTERNAL_OCCUPANCIES = frozenset(
    {INTERNAL_VACANT, INTERNAL_OCCUPIED, INTERNAL_UNKNOWN}
)

_ANSWER_TO_INTERNAL = {
    OCCUPANCY_VACANT_ANSWER: INTERNAL_VACANT,
    OCCUPANCY_OCCUPIED_ANSWER: INTERNAL_OCCUPIED,
    OCCUPANCY_UNKNOWN_ANSWER: INTERNAL_UNKNOWN,
}
_UNKNOWN_ANSWER = OCCUPANCY_UNKNOWN_ANSWER


class BindingStatus:
    """The binding state machine values (plain strings, project style)."""

    BOUND = "bound"
    AMBIGUOUS = "ambiguous"
    TEMPORARILY_NOT_VISIBLE = "temporarily_not_visible"
    INVALIDATED = "invalidated"
    UNVERIFIED = "unverified"
    REFUSED = "refused"

    ALL = frozenset(
        {
            BOUND,
            AMBIGUOUS,
            TEMPORARILY_NOT_VISIBLE,
            INVALIDATED,
            UNVERIFIED,
            REFUSED,
        }
    )


class BindingDecisionParseError(ValueError):
    """The model's binding answer is not the required closed-vocabulary block."""


class BindingNotExecutableError(ValueError):
    """A binding artifact is not in the ``bound`` state."""


_FIELD_LINE_TEMPLATE = r"^[ \t>*`#\-\u2022]*{label}[ \t>*`]*[:：][ \t]*(.*?)[ \t]*$"
_VALUE_STRIP = "`*\"'。 "
_LABEL_LINE_RE = re.compile(
    r"^[ \t>*`#\-\u2022]*([A-H])[ \t>*`]*[:：][ \t]*(.*?)[ \t]*$", re.MULTILINE
)
_LABEL_ALPHABET = "ABCDEFGH"


@dataclass(frozen=True)
class BindingDecision:
    """The model's answer as written, before any system constraint."""

    occupancies: Mapping[str, str]
    selected: str


@dataclass(frozen=True)
class CandidateObservation:
    """One scene bay observed in one round.

    ``label`` is the temporary letter painted on the frame, or ``""`` when the
    bay is not fully visible and was not offered to the model. ``occupancy`` is
    one of ``vacant``/``occupied``/``unknown``.
    """

    label: str
    bay_id: str
    slot_node_id: str
    occupancy: str
    visible: bool
    side: str
    bearing_deg: float
    distance_m: float
    image_bbox: Optional[tuple[float, float, float, float]] = None

    def __post_init__(self) -> None:
        if type(self.bay_id) is not str or not self.bay_id:
            raise ValueError("bay_id must be a non-blank str")
        if type(self.slot_node_id) is not str or not self.slot_node_id:
            raise ValueError("slot_node_id must be a non-blank str")
        if self.occupancy not in _INTERNAL_OCCUPANCIES:
            raise ValueError(f"unknown internal occupancy {self.occupancy!r}")
        if type(self.visible) is not bool:
            raise ValueError("visible must be a bool")
        if self.side not in {"LEFT", "RIGHT", "AHEAD", "BEHIND"}:
            raise ValueError(f"unknown side {self.side!r}")
        if not (math.isfinite(self.bearing_deg) and math.isfinite(self.distance_m)):
            raise ValueError("bearing/distance must be finite")
        if self.visible and (type(self.label) is not str or self.label == ""):
            raise ValueError("a visible candidate must carry a label")

    def to_metadata(self) -> dict:
        bbox = None
        if self.image_bbox is not None and all(
            math.isfinite(value) for value in self.image_bbox
        ):
            bbox = [round(float(value), 2) for value in self.image_bbox]
        return {
            "label": self.label,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "occupancy": self.occupancy,
            "visible": self.visible,
            "side": self.side,
            "bearing_deg": round(self.bearing_deg, 3),
            "distance_m": round(self.distance_m, 3),
            "image_bbox": bbox,
        }


@dataclass(frozen=True)
class TargetBinding:
    """The result of one binding round, plus the prior identity it continues."""

    status: str
    instruction: str
    round_index: int
    bay_id: Optional[str]
    slot_node_id: Optional[str]
    selected_label: Optional[str]
    reason: str
    candidates: tuple[CandidateObservation, ...] = ()
    prior_bay_id: Optional[str] = None
    evidence: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in BindingStatus.ALL:
            raise ValueError(f"unknown binding status {self.status!r}")
        if type(self.instruction) is not str or not self.instruction.strip():
            raise ValueError("instruction must be a non-blank str")
        if type(self.round_index) is not int or self.round_index < 0:
            raise ValueError("round_index must be a non-negative int")
        if self.status == BindingStatus.BOUND and (
            not self.bay_id or not self.slot_node_id
        ):
            raise ValueError("a bound result requires bay_id and slot_node_id")

    @property
    def executable(self) -> bool:
        return (
            self.status == BindingStatus.BOUND
            and bool(self.bay_id)
            and bool(self.slot_node_id)
        )

    def to_metadata(self) -> dict:
        return {
            "schema": "vln.parking_target_binding.v1",
            "status": self.status,
            "instruction": self.instruction,
            "round_index": self.round_index,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "selected_label": self.selected_label,
            "prior_bay_id": self.prior_bay_id,
            "reason": self.reason,
            "executable": self.executable,
            "candidates": [item.to_metadata() for item in self.candidates],
            "evidence": _json_safe(self.evidence),
        }


@dataclass(frozen=True)
class BindingArtifact:
    """The minimal, validated view of a binding JSON consumed by the runner."""

    status: str
    instruction: str
    bay_id: Optional[str]
    slot_node_id: Optional[str]
    round_index: int
    selected_label: Optional[str]
    reason: str

    @property
    def executable(self) -> bool:
        return (
            self.status == BindingStatus.BOUND
            and bool(self.bay_id)
            and bool(self.slot_node_id)
        )

    def to_metadata(self) -> dict:
        return {
            "schema": "vln.parking_target_binding.v1",
            "status": self.status,
            "instruction": self.instruction,
            "round_index": self.round_index,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "selected_label": self.selected_label,
            "reason": self.reason,
            "executable": self.executable,
        }


def _field_values(raw_text: str, label: str) -> tuple[str, ...]:
    pattern = re.compile(
        _FIELD_LINE_TEMPLATE.format(label=re.escape(label)),
        re.IGNORECASE | re.MULTILINE,
    )
    return tuple(
        match.group(1).strip().strip(_VALUE_STRIP) for match in pattern.finditer(raw_text)
    )


def parse_binding_decision(raw_text: str, labels: Sequence[str]) -> BindingDecision:
    """Read the per-candidate block and the selected label, or refuse."""

    if type(raw_text) is not str:
        raise BindingDecisionParseError(
            f"model response must be a string, got {type(raw_text).__name__}"
        )
    if raw_text.strip() == "":
        raise BindingDecisionParseError("model response is blank")
    expected = tuple(labels)
    if not expected:
        raise BindingDecisionParseError("no candidate labels were offered")
    if len(set(expected)) != len(expected):
        raise BindingDecisionParseError("candidate labels must be unique")
    for label in expected:
        if label not in _LABEL_ALPHABET:
            raise BindingDecisionParseError(f"invalid candidate label {label!r}")

    for match in _LABEL_LINE_RE.finditer(raw_text):
        if match.group(1) not in expected:
            raise BindingDecisionParseError(
                f"model reported unexpected candidate label {match.group(1)!r}"
            )

    occupancies: dict[str, str] = {}
    for label in expected:
        found = _field_values(raw_text, label)
        if not found:
            raise BindingDecisionParseError(f"missing candidate line: {label!r}")
        if len(found) > 1:
            raise BindingDecisionParseError(
                f"duplicate candidate line {label!r}: the answer is ambiguous"
            )
        value = found[0]
        if value == "":
            raise BindingDecisionParseError(f"candidate {label!r} is empty")
        if value not in OCCUPANCY_ANSWERS:
            raise BindingDecisionParseError(
                f"candidate {label!r} uses off-vocabulary occupancy {value!r}; "
                f"expected one of {list(OCCUPANCY_ANSWERS)}"
            )
        occupancies[label] = _ANSWER_TO_INTERNAL[value]

    selected_values = _field_values(raw_text, SELECTED_FIELD)
    if not selected_values:
        raise BindingDecisionParseError(f"missing required field {SELECTED_FIELD!r}")
    if len(selected_values) > 1:
        raise BindingDecisionParseError(
            f"duplicate field {SELECTED_FIELD!r}: the answer is ambiguous"
        )
    selected = selected_values[0]
    if selected not in expected and selected != _UNKNOWN_ANSWER:
        raise BindingDecisionParseError(
            f"{SELECTED_FIELD} must be a candidate label or {_UNKNOWN_ANSWER!r}, "
            f"got {selected!r}"
        )
    return BindingDecision(occupancies=occupancies, selected=selected)


def _candidate_table(candidates: tuple[CandidateObservation, ...]) -> list[dict]:
    return [item.to_metadata() for item in candidates]


def _resolve(
    *,
    status: str,
    request: ParkingInstruction,
    round_index: int,
    bay_id: Optional[str],
    slot_node_id: Optional[str],
    selected_label: Optional[str],
    reason: str,
    candidates: tuple[CandidateObservation, ...],
    prior_bay_id: Optional[str],
    evidence: Mapping[str, object],
) -> TargetBinding:
    return TargetBinding(
        status=status,
        instruction=request.raw,
        round_index=round_index,
        bay_id=bay_id,
        slot_node_id=slot_node_id,
        selected_label=selected_label,
        reason=reason,
        candidates=candidates,
        prior_bay_id=prior_bay_id,
        evidence=evidence,
    )


def resolve_target_binding(
    request: ParkingInstruction,
    candidates: Sequence[CandidateObservation],
    decision: Optional[BindingDecision],
    *,
    prior: Optional[TargetBinding | BindingArtifact] = None,
    round_index: int = 0,
    landmark_verified: bool = False,
) -> TargetBinding:
    """Map the model's letter to a bay, apply system checks, or refuse."""

    if not isinstance(request, ParkingInstruction):
        raise TypeError("request must be a ParkingInstruction")
    candidate_tuple = tuple(candidates)
    if not candidate_tuple:
        raise ValueError("at least one candidate observation is required")
    if len({item.bay_id for item in candidate_tuple}) != len(candidate_tuple):
        raise ValueError("candidate bay ids must be unique")
    visible = tuple(item for item in candidate_tuple if item.visible)
    visible_labels = tuple(item.label for item in visible)
    if len(set(visible_labels)) != len(visible_labels):
        raise ValueError("visible candidate labels must be unique")
    if visible and decision is None:
        raise ValueError("a model decision is required when candidates are visible")
    if decision is not None:
        if set(decision.occupancies) != set(visible_labels):
            raise ValueError(
                "decision labels do not match the visible candidate labels"
            )
        for item in visible:
            if decision.occupancies[item.label] != item.occupancy:
                raise ValueError(
                    f"decision occupancy for {item.label!r} does not match the "
                    "candidate observation"
                )

    evidence: dict = {
        "request": request.to_metadata(),
        "visible_labels": list(visible_labels),
        "selected": None if decision is None else decision.selected,
        "model_occupancy_answers": (
            {} if decision is None else dict(decision.occupancies)
        ),
        "landmark_used": False,
        "landmark_verified": bool(landmark_verified),
        "candidate_table": _candidate_table(candidate_tuple),
    }

    if prior is not None:
        if prior.instruction != request.raw:
            return _resolve(
                status=BindingStatus.REFUSED,
                request=request,
                round_index=round_index,
                bay_id=None,
                slot_node_id=None,
                selected_label=None if decision is None else decision.selected,
                reason=(
                    "instruction changed during the task; the prior binding is "
                    "not silently re-applied"
                ),
                candidates=candidate_tuple,
                prior_bay_id=prior.bay_id,
                evidence=evidence,
            )
        if prior.status == BindingStatus.INVALIDATED:
            return _resolve(
                status=BindingStatus.INVALIDATED,
                request=request,
                round_index=round_index,
                bay_id=prior.bay_id,
                slot_node_id=prior.slot_node_id,
                selected_label=None if decision is None else decision.selected,
                reason="the target was invalidated earlier; no rebinding is attempted",
                candidates=candidate_tuple,
                prior_bay_id=prior.bay_id,
                evidence=evidence,
            )
        if prior.status in (
            BindingStatus.BOUND,
            BindingStatus.TEMPORARILY_NOT_VISIBLE,
            BindingStatus.UNVERIFIED,
        ):
            return _continue_prior(
                request=request,
                candidates=candidate_tuple,
                decision=decision,
                prior=prior,
                round_index=round_index,
                evidence=evidence,
            )

    if not visible:
        return _resolve(
            status=BindingStatus.TEMPORARILY_NOT_VISIBLE,
            request=request,
            round_index=round_index,
            bay_id=None,
            slot_node_id=None,
            selected_label=None,
            reason="no known bay is fully visible in the current frame",
            candidates=candidate_tuple,
            prior_bay_id=None,
            evidence=evidence,
        )

    assert decision is not None
    side_matches = [
        item
        for item in visible
        if request.side == SIDE_UNSPECIFIED or item.side == request.side
    ]
    hard = [item for item in side_matches if item.occupancy == INTERNAL_VACANT]
    unknown = [
        item for item in side_matches if item.occupancy == INTERNAL_UNKNOWN
    ]

    if not hard:
        if unknown and len(unknown) == len(side_matches):
            status = BindingStatus.UNVERIFIED
            reason = (
                "occupancy is unknown for every candidate matching the "
                "instruction; unknown is never treated as vacant"
            )
        else:
            status = BindingStatus.REFUSED
            reason = (
                "no fully visible candidate is vacant and matches the "
                "instruction"
            )
        return _resolve(
            status=status,
            request=request,
            round_index=round_index,
            bay_id=None,
            slot_node_id=None,
            selected_label=decision.selected,
            reason=reason,
            candidates=candidate_tuple,
            prior_bay_id=None,
            evidence=evidence,
        )

    if len(hard) > 1:
        return _resolve(
            status=BindingStatus.AMBIGUOUS,
            request=request,
            round_index=round_index,
            bay_id=None,
            slot_node_id=None,
            selected_label=decision.selected,
            reason=(
                "multiple candidates satisfy the instruction: "
                + ", ".join(item.label for item in hard)
            ),
            candidates=candidate_tuple,
            prior_bay_id=None,
            evidence=evidence,
        )

    only = hard[0]
    if decision.selected != only.label:
        if decision.selected == _UNKNOWN_ANSWER:
            status = BindingStatus.UNVERIFIED
            reason = (
                f"the model did not select the unique matching candidate "
                f"{only.label}"
            )
        else:
            status = BindingStatus.REFUSED
            reason = (
                f"the model selected {decision.selected}, but system "
                f"constraints leave only {only.label}"
            )
        return _resolve(
            status=status,
            request=request,
            round_index=round_index,
            bay_id=None,
            slot_node_id=None,
            selected_label=decision.selected,
            reason=reason,
            candidates=candidate_tuple,
            prior_bay_id=None,
            evidence=evidence,
        )

    return _resolve(
        status=BindingStatus.BOUND,
        request=request,
        round_index=round_index,
        bay_id=only.bay_id,
        slot_node_id=only.slot_node_id,
        selected_label=only.label,
        reason=(
            "unique visible vacant candidate on the requested side"
            if request.side != SIDE_UNSPECIFIED
            else "unique visible vacant candidate"
        ),
        candidates=candidate_tuple,
        prior_bay_id=None,
        evidence=evidence,
    )


def _continue_prior(
    *,
    request: ParkingInstruction,
    candidates: tuple[CandidateObservation, ...],
    decision: Optional[BindingDecision],
    prior: TargetBinding | BindingArtifact,
    round_index: int,
    evidence: dict,
) -> TargetBinding:
    prior_candidate = next(
        (item for item in candidates if item.bay_id == prior.bay_id), None
    )
    if prior_candidate is None:
        return _resolve(
            status=BindingStatus.TEMPORARILY_NOT_VISIBLE,
            request=request,
            round_index=round_index,
            bay_id=prior.bay_id,
            slot_node_id=prior.slot_node_id,
            selected_label=None if decision is None else decision.selected,
            reason="the bound bay is not in the current candidate set",
            candidates=candidates,
            prior_bay_id=prior.bay_id,
            evidence=evidence,
        )
    if not prior_candidate.visible:
        return _resolve(
            status=BindingStatus.TEMPORARILY_NOT_VISIBLE,
            request=request,
            round_index=round_index,
            bay_id=prior.bay_id,
            slot_node_id=prior.slot_node_id,
            selected_label=None if decision is None else decision.selected,
            reason="the bound bay is not fully visible in the current frame",
            candidates=candidates,
            prior_bay_id=prior.bay_id,
            evidence=evidence,
        )
    if prior_candidate.occupancy == INTERNAL_UNKNOWN:
        return _resolve(
            status=BindingStatus.UNVERIFIED,
            request=request,
            round_index=round_index,
            bay_id=prior.bay_id,
            slot_node_id=prior.slot_node_id,
            selected_label=None if decision is None else decision.selected,
            reason=(
                "the bound bay's occupancy is unknown in this round; unknown is "
                "never treated as vacant"
            ),
            candidates=candidates,
            prior_bay_id=prior.bay_id,
            evidence=evidence,
        )
    if prior_candidate.occupancy != INTERNAL_VACANT:
        return _resolve(
            status=BindingStatus.INVALIDATED,
            request=request,
            round_index=round_index,
            bay_id=prior.bay_id,
            slot_node_id=prior.slot_node_id,
            selected_label=None if decision is None else decision.selected,
            reason="the bound bay is no longer vacant",
            candidates=candidates,
            prior_bay_id=prior.bay_id,
            evidence=evidence,
        )
    if decision is None:
        return _resolve(
            status=BindingStatus.UNVERIFIED,
            request=request,
            round_index=round_index,
            bay_id=prior.bay_id,
            slot_node_id=prior.slot_node_id,
            selected_label=None,
            reason="no model observation for the bound bay in this round",
            candidates=candidates,
            prior_bay_id=prior.bay_id,
            evidence=evidence,
        )
    selected_candidate = next(
        (item for item in candidates if item.visible and item.label == decision.selected),
        None,
    )
    if decision.selected == _UNKNOWN_ANSWER:
        return _resolve(
            status=BindingStatus.UNVERIFIED,
            request=request,
            round_index=round_index,
            bay_id=prior.bay_id,
            slot_node_id=prior.slot_node_id,
            selected_label=decision.selected,
            reason="the model did not confirm the bound candidate in this round",
            candidates=candidates,
            prior_bay_id=prior.bay_id,
            evidence=evidence,
        )
    if selected_candidate is None or selected_candidate.bay_id != prior.bay_id:
        return _resolve(
            status=BindingStatus.AMBIGUOUS,
            request=request,
            round_index=round_index,
            bay_id=prior.bay_id,
            slot_node_id=prior.slot_node_id,
            selected_label=decision.selected,
            reason=(
                "the model selected a different candidate than the bound bay; "
                "identity is not rebound"
            ),
            candidates=candidates,
            prior_bay_id=prior.bay_id,
            evidence=evidence,
        )
    return _resolve(
        status=BindingStatus.BOUND,
        request=request,
        round_index=round_index,
        bay_id=prior.bay_id,
        slot_node_id=prior.slot_node_id,
        selected_label=selected_candidate.label,
        reason="the bound bay remains visible, vacant and selected",
        candidates=candidates,
        prior_bay_id=prior.bay_id,
        evidence=evidence,
    )


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def parse_binding_artifact(metadata: Mapping[str, object]) -> BindingArtifact:
    """Validate a binding JSON object before the runner may use it."""

    if not isinstance(metadata, Mapping):
        raise ValueError("binding artifact must be a JSON object")
    status = metadata.get("status")
    if status not in BindingStatus.ALL:
        raise ValueError(f"unknown binding status {status!r}")
    instruction = metadata.get("instruction")
    if type(instruction) is not str or instruction.strip() == "":
        raise ValueError("binding artifact instruction must be a non-blank str")
    round_index = metadata.get("round_index")
    if type(round_index) is not int or round_index < 0:
        raise ValueError("binding artifact round_index must be a non-negative int")
    bay_id = metadata.get("bay_id")
    slot_node_id = metadata.get("slot_node_id")
    if status == BindingStatus.BOUND:
        if type(bay_id) is not str or not bay_id:
            raise ValueError("a bound artifact requires bay_id")
        if type(slot_node_id) is not str or not slot_node_id:
            raise ValueError("a bound artifact requires slot_node_id")
    else:
        if bay_id is not None and (type(bay_id) is not str or not bay_id):
            raise ValueError("bay_id must be a non-blank str or null")
        if slot_node_id is not None and (
            type(slot_node_id) is not str or not slot_node_id
        ):
            raise ValueError("slot_node_id must be a non-blank str or null")
    selected = metadata.get("selected_label")
    if selected is not None and type(selected) is not str:
        raise ValueError("selected_label must be a str or null")
    reason = metadata.get("reason", "")
    if type(reason) is not str:
        raise ValueError("reason must be a str")
    return BindingArtifact(
        status=status,
        instruction=instruction,
        bay_id=bay_id if type(bay_id) is str else None,
        slot_node_id=slot_node_id if type(slot_node_id) is str else None,
        round_index=round_index,
        selected_label=selected,
        reason=reason,
    )


def binding_goal_node(artifact: BindingArtifact) -> str:
    """Return the executable parking goal node, or refuse."""

    if not isinstance(artifact, BindingArtifact):
        raise TypeError("artifact must be a BindingArtifact")
    if not artifact.executable:
        raise BindingNotExecutableError(
            f"binding status {artifact.status!r} is not executable: "
            f"{artifact.reason}"
        )
    return artifact.slot_node_id  # type: ignore[return-value]
