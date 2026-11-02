"""Strict parser for one close-range target-verification answer.

The occupancy field and ``Selected`` field reuse the CAP-07A closed-vocabulary
parser. The three additional fields (boundary, occlusion, evidence) use the
same line-oriented contract and a closed vocabulary; there is no second visual
protocol. An answer with a missing/duplicated/off-vocabulary field is refused,
never repaired.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from vln.nav.target_binding import (
    INTERNAL_OCCUPIED,
    INTERNAL_UNKNOWN,
    INTERNAL_VACANT,
    BindingDecisionParseError,
    parse_binding_decision,
)
from vln.vlm.verification_prompt import (
    BOUNDARY_ANSWERS,
    BOUNDARY_CLEAR,
    EVIDENCE_ANSWERS,
    EVIDENCE_SUFFICIENT,
    OCCLUSION_ANSWERS,
    OCCLUSION_NONE,
    UNKNOWN_ANSWER,
)

__all__ = [
    "VerificationDecision",
    "VerificationDecisionParseError",
    "parse_verification_decision",
]


class VerificationDecisionParseError(ValueError):
    """The model's close-range verification answer is not the required block."""


_FIELD_LINE_TEMPLATE = r"^[ \t>*`#\-\u2022]*{field}[ \t>*`]*[:：][ \t]*(.*?)[ \t]*$"
_VALUE_STRIP = "`*\"'。 "


@dataclass(frozen=True)
class VerificationDecision:
    """Structured answer for one observation, before any system constraint."""

    occupancy: str
    boundary_answer: str
    occlusion_answer: str
    evidence_answer: str
    selected: str

    @property
    def boundary_clear(self) -> bool:
        return self.boundary_answer == BOUNDARY_CLEAR

    @property
    def occluded(self) -> bool:
        return self.occlusion_answer not in (OCCLUSION_NONE, UNKNOWN_ANSWER)

    @property
    def evidence_sufficient(self) -> bool:
        return self.evidence_answer == EVIDENCE_SUFFICIENT

    def to_metadata(self) -> dict:
        return {
            "occupancy": self.occupancy,
            "boundary_answer": self.boundary_answer,
            "occlusion_answer": self.occlusion_answer,
            "evidence_answer": self.evidence_answer,
            "selected": self.selected,
            "boundary_clear": self.boundary_clear,
            "occluded": self.occluded,
            "evidence_sufficient": self.evidence_sufficient,
        }


def _field_values(raw_text: str, field: str) -> tuple[str, ...]:
    pattern = re.compile(
        _FIELD_LINE_TEMPLATE.format(field=re.escape(field)),
        re.IGNORECASE | re.MULTILINE,
    )
    return tuple(
        match.group(1).strip().strip(_VALUE_STRIP) for match in pattern.finditer(raw_text)
    )


def _required_value(raw_text: str, field: str, allowed: tuple[str, ...]) -> str:
    values = _field_values(raw_text, field)
    if not values:
        raise VerificationDecisionParseError(f"missing field {field!r}")
    if len(values) > 1:
        raise VerificationDecisionParseError(
            f"duplicate field {field!r}: the answer is ambiguous"
        )
    value = values[0]
    if value == "":
        raise VerificationDecisionParseError(f"field {field!r} is empty")
    if value not in allowed:
        raise VerificationDecisionParseError(
            f"field {field!r} uses off-vocabulary value {value!r}; "
            f"expected one of {list(allowed)}"
        )
    return value


def parse_verification_decision(
    raw_text: str, label: str = "A"
) -> VerificationDecision:
    """Parse the occupancy/Selected contract plus boundary/occlusion/evidence."""

    if type(raw_text) is not str or raw_text.strip() == "":
        raise VerificationDecisionParseError("model response is blank")
    try:
        binding = parse_binding_decision(raw_text, (label,))
    except BindingDecisionParseError as error:
        raise VerificationDecisionParseError(str(error)) from error
    occupancy = binding.occupancies[label]
    if occupancy not in (INTERNAL_VACANT, INTERNAL_OCCUPIED, INTERNAL_UNKNOWN):
        raise VerificationDecisionParseError(
            f"unsupported occupancy {occupancy!r}"
        )
    return VerificationDecision(
        occupancy=occupancy,
        boundary_answer=_required_value(raw_text, "边界", BOUNDARY_ANSWERS),
        occlusion_answer=_required_value(raw_text, "遮挡", OCCLUSION_ANSWERS),
        evidence_answer=_required_value(raw_text, "证据", EVIDENCE_ANSWERS),
        selected=binding.selected,
    )
