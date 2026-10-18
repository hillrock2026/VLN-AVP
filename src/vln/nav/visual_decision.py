"""Layers 1-2: raw model text -> structured visual judgement -> verified directive.

Two steps, kept apart on purpose:

* :func:`parse_visual_decision` (layer 1, *structure*) reads the conclusion block
  the navigation prompt asks for and returns a :class:`VisualNavigationDecision`.
  It judges shape only: a non-string or blank response, a required field label
  that is absent, a label that appears twice (an ambiguous block - the first
  occurrence is not silently taken), or a field left empty. It never looks at the
  outside world and never invents a value the model did not write.
* :func:`verify_visual_decision` (layer 2, *executability*) decides whether that
  judgement may drive a navigation intent: the target must be reported visible,
  the identity the model says it read must be the identity that was requested,
  the ``Evidence`` value must not be an explicit "cannot determine" answer, and
  the relative position and the discrete direction must both be approved tokens
  that agree with each other. It returns a :class:`NavigationDirective`.

Why the identity check exists. 08A measured that naming a target in the
instruction can make the model state an identity it cannot read: with a target
named it returned ``Identified as: 316`` / ``283`` at the correct position and
stably, but a target-free read of the same frames reproduced **none** of the real
deck numbers (``docs/M1-VLN-NAV-08A-RESULT.md`` §6-§8). A named-target identity
answer therefore counts for nothing on its own, so the field the model fills with
what it *read* (``Identified as``, added by 08A) is required here and must match
the request. ``Target`` is never trusted as evidence: the prompt defines it as a
copy of the requested label, so agreement there carries no information. It must
still echo the request, because a ``Target`` naming a different label is an
internal contradiction and is refused.

Why whole-token matching. The same 08A evidence shows the concrete failure the
matcher must not paper over: a 180-degree-rotated ``D50`` comes back as ``050``,
and ``1316`` must not count for ``316``. :func:`identity_matches` therefore
matches a whole token, not a substring.

Answer vocabulary. The approved tokens are imported from
:mod:`vln.vlm.nav_prompt` - the module that writes the prompt - so the parser and
the prompt cannot drift into two different vocabularies. An off-vocabulary answer
(``右侧`` for ``RIGHT``, ``no`` for ``否``) is **refused**, not translated:
translating would create a second semantics source next to the prompt, which is
the same reasoning M1-04B0 §4.3 uses for the C++ stub (``避免形成第二套语义``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from vln.vlm.nav_prompt import (
    DIRECTION_ANSWERS,
    EVIDENCE_UNCERTAINTY_ANSWERS,
    IDENTITY_FIELD,
    POSITION_ANSWERS,
    VISIBLE_ANSWERS,
)

from .errors import (
    EvidenceInsufficientError,
    TargetIdentityMismatchError,
    TargetNotVisibleError,
    VisualDecisionParseError,
    VisualDecisionValidationError,
)

__all__ = [
    "FIELD_TARGET",
    "FIELD_VISIBLE",
    "FIELD_POSITION",
    "FIELD_DIRECTION",
    "FIELD_EVIDENCE",
    "DECISION_FIELDS",
    "POSITION_TO_DIRECTION",
    "VisualNavigationDecision",
    "NavigationDirective",
    "parse_visual_decision",
    "verify_visual_decision",
    "identity_matches",
    "evidence_is_insufficient",
]

#: The conclusion-block field labels. These mirror the block the navigation
#: prompt asks for; ``tests/vln/test_visual_decision.py`` asserts each one really
#: appears in the prompt text, so the parser and the prompt cannot silently
#: diverge.
FIELD_TARGET = "Target"
FIELD_VISIBLE = "Visible"
FIELD_POSITION = "Relative position"
FIELD_DIRECTION = "Next direction"
FIELD_EVIDENCE = "Evidence"

#: Every field the block must contain exactly once. ``Identified as`` is 08A's
#: field and is required here: without it the identity cannot be checked, and an
#: unchecked identity is exactly what 08A showed to be untrustworthy.
DECISION_FIELDS = (
    FIELD_TARGET,
    IDENTITY_FIELD,
    FIELD_VISIBLE,
    FIELD_POSITION,
    FIELD_DIRECTION,
    FIELD_EVIDENCE,
)

#: The approved position -> discrete-direction correspondence. A block whose two
#: answers disagree is refused rather than resolved by picking one of them.
POSITION_TO_DIRECTION = {
    "LEFT": "LEFT",
    "RIGHT": "RIGHT",
    "AHEAD": "STRAIGHT",
}

#: A field label at the start of a line, optionally behind markdown decoration.
_FIELD_LINE_TEMPLATE = r"^[ \t>*`#\-\u2022]*{label}[ \t>*`]*[:：][ \t]*(.*?)[ \t]*$"

#: Characters stripped from a field value (the model decorates answers freely).
_VALUE_STRIP = "`*\"'。 "

#: ASCII alphanumerics, used to decide whether a token boundary is meaningful.
#: ``str.isalnum()`` is unusable here because it is true for CJK characters too.
_ASCII_ALNUM = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

_COMPACT_RE = re.compile(r"[\s`*\"'。.,;:：]")

#: Separators ignored when deciding whether an Evidence value is *only* an
#: uncertainty answer. The rule is whole-value composition, never keyword search.
_EVIDENCE_SEPARATOR_RE = re.compile(
    r"[\s`*\"'。.,;:：、，；！？!?“”‘’「」『』()（）\[\]【】/|]+"
)

_EVIDENCE_UNCERTAINTY_TOKENS = tuple(
    sorted(EVIDENCE_UNCERTAINTY_ANSWERS, key=len, reverse=True)
)

#: A single generic object may end an uncertainty-only Evidence value, as in
#: ``无法确定方向``. It is not accepted anywhere else, so a substantive sentence
#: such as ``可见出口，无法确定方向`` is still not classified as insufficient.
_EVIDENCE_UNCERTAINTY_OBJECTS = frozenset({"方向", "位置", "目标", "方位"})


@dataclass(frozen=True)
class VisualNavigationDecision:
    """The model's judgement as written, before any executability check.

    Field values are the model's own text, stripped of decoration but not
    translated. Holding this type means only that the answer block was
    well-formed - it does **not** mean the judgement is usable.
    """

    target_field: str
    identified_as: str
    visible: str
    position: str
    direction: str
    evidence: str


@dataclass(frozen=True)
class NavigationDirective:
    """A verified judgement: the only thing this layer will map to an intent.

    A value of this type has passed every check in
    :func:`verify_visual_decision`, so ``direction`` is an approved token and the
    identity has been shown to match the request.
    """

    direction: str
    position: str
    identified_as: str
    evidence: str


def _field_values(raw_text: str, label: str) -> tuple:
    """Every value written for ``label`` at the start of a line, in order."""

    pattern = re.compile(
        _FIELD_LINE_TEMPLATE.format(label=re.escape(label)),
        re.IGNORECASE | re.MULTILINE,
    )
    return tuple(
        match.group(1).strip().strip(_VALUE_STRIP) for match in pattern.finditer(raw_text)
    )


def parse_visual_decision(raw_text: str) -> VisualNavigationDecision:
    """Read one conclusion block out of ``raw_text``.

    Raises :class:`~vln.nav.errors.VisualDecisionParseError` when the text is not
    a string, is blank, is missing a required field, repeats a required field, or
    leaves one empty. Nothing is defaulted and no field is guessed.
    """

    if type(raw_text) is not str:
        raise VisualDecisionParseError(
            f"model response must be a string, got {type(raw_text).__name__}"
        )
    if raw_text.strip() == "":
        raise VisualDecisionParseError("model response is blank")

    values: dict = {}
    for label in DECISION_FIELDS:
        found = _field_values(raw_text, label)
        if not found:
            raise VisualDecisionParseError(f"missing required field: {label!r}")
        if len(found) > 1:
            raise VisualDecisionParseError(
                f"duplicate field {label!r}: the answer block appears "
                f"{len(found)} times, so the decision is ambiguous"
            )
        if found[0] == "":
            raise VisualDecisionParseError(f"field {label!r} is present but empty")
        values[label] = found[0]

    return VisualNavigationDecision(
        target_field=values[FIELD_TARGET],
        identified_as=values[IDENTITY_FIELD],
        visible=values[FIELD_VISIBLE],
        position=values[FIELD_POSITION],
        direction=values[FIELD_DIRECTION],
        evidence=values[FIELD_EVIDENCE],
    )


def identity_matches(identified: str, expected: str) -> bool:
    """Is ``expected`` present in ``identified`` as a whole token?

    Whole-token, not substring, so the measured misread is caught: ``050`` must
    not stand in for ``D50`` and ``1316`` must not stand in for ``316``. A token
    boundary is only enforced where it means something, i.e. against ASCII
    alphanumerics on either side of an expected token that itself starts or ends
    with one, so ``D50ABC`` does not stand in for ``D50`` and ``AB`` does not
    stand in for ``A``, while a CJK label such as ``出口`` still matches inside
    ``出口 EXIT``.
    """

    if type(identified) is not str or type(expected) is not str:
        return False
    compact_expected = _COMPACT_RE.sub("", expected).upper()
    if compact_expected == "":
        return False
    compact_identified = _COMPACT_RE.sub("", identified).upper()
    prefix = "(?<![A-Z0-9])" if compact_expected[0] in _ASCII_ALNUM else ""
    suffix = "(?![A-Z0-9])" if compact_expected[-1] in _ASCII_ALNUM else ""
    pattern = rf"{prefix}{re.escape(compact_expected)}{suffix}"
    return re.search(pattern, compact_identified) is not None


def evidence_is_insufficient(evidence: str) -> bool:
    """Is the *whole* Evidence value an approved uncertainty answer?

    The check is composition, not keyword search: ``证据不足，无法确定`` is
    insufficient, while ``可见左侧出口标识，但无法确定距离`` is not - the
    latter states a visual basis. Free text cannot be fully validated; this
    rule only makes the contract's explicit abstention forms non-executable.
    """

    if type(evidence) is not str:
        return False
    compact = _EVIDENCE_SEPARATOR_RE.sub("", evidence)
    if compact == "":
        return False
    index = 0
    while index < len(compact):
        for token in _EVIDENCE_UNCERTAINTY_TOKENS:
            if compact.startswith(token, index):
                index += len(token)
                break
        else:
            return compact[index:] in _EVIDENCE_UNCERTAINTY_OBJECTS
    return True


def verify_visual_decision(
    decision: VisualNavigationDecision, *, expected_identity: str
) -> NavigationDirective:
    """Turn a well-formed judgement into a directive, or refuse.

    ``expected_identity`` is the identity the human instruction asked for; it is
    supplied by the caller, never read out of the model's own ``Target`` echo.

    Refusals, each with its own class so the cause is diagnosable:

    * ``Visible`` is not an approved token -> :class:`VisualDecisionValidationError`;
    * ``Visible`` is the approved "no" -> :class:`TargetNotVisibleError`;
    * the identity the model read, or the ``Target`` echo, is not the requested
      one -> :class:`TargetIdentityMismatchError`;
    * ``Evidence`` consists solely of an approved uncertainty answer
      -> :class:`EvidenceInsufficientError`;
    * ``Relative position`` or ``Next direction`` is off-vocabulary or
      ``无法确定`` -> :class:`VisualDecisionValidationError`;
    * the position and the direction disagree
      -> :class:`VisualDecisionValidationError`.
    """

    if not isinstance(decision, VisualNavigationDecision):
        raise VisualDecisionValidationError(
            f"expected a VisualNavigationDecision, got {type(decision).__name__}"
        )
    if type(expected_identity) is not str or expected_identity.strip() == "":
        raise VisualDecisionValidationError("expected_identity must be a non-blank str")

    if decision.visible not in VISIBLE_ANSWERS:
        raise VisualDecisionValidationError(
            f"Visible must be one of {list(VISIBLE_ANSWERS)}, got {decision.visible!r}"
        )
    if decision.visible != VISIBLE_ANSWERS[0]:
        raise TargetNotVisibleError(
            f"the model reports target {expected_identity!r} as not visible"
        )

    if not identity_matches(decision.identified_as, expected_identity):
        raise TargetIdentityMismatchError(
            f"the model reports reading {decision.identified_as!r}, which is not "
            f"the requested target {expected_identity!r}"
        )
    # ``Target`` is never evidence of a read (the prompt defines it as a copy of
    # the request), but a copy that names a different label is an internal
    # contradiction: the model is answering a different task than the one asked.
    if not identity_matches(decision.target_field, expected_identity):
        raise TargetIdentityMismatchError(
            f"the model's Target field {decision.target_field!r} does not echo "
            f"the requested target {expected_identity!r}"
        )

    # A concrete Visible/direction pair is not executable when the model's own
    # evidence says it cannot determine anything. Only an Evidence value made
    # up entirely of approved uncertainty answers triggers this; a substantive
    # sentence that happens to contain 无法确定 does not.
    if evidence_is_insufficient(decision.evidence):
        raise EvidenceInsufficientError(
            "Evidence states that the decision cannot be supported: "
            f"{decision.evidence!r}"
        )

    approved_positions = POSITION_ANSWERS[:-1]  # 无法确定 is the last entry
    if decision.position not in approved_positions:
        raise VisualDecisionValidationError(
            f"Relative position must be one of {list(approved_positions)}, "
            f"got {decision.position!r}"
        )
    approved_directions = DIRECTION_ANSWERS[:-1]
    if decision.direction not in approved_directions:
        raise VisualDecisionValidationError(
            f"Next direction must be one of {list(approved_directions)}, "
            f"got {decision.direction!r}"
        )
    if POSITION_TO_DIRECTION[decision.position] != decision.direction:
        raise VisualDecisionValidationError(
            f"the answer contradicts itself: Relative position "
            f"{decision.position!r} does not correspond to Next direction "
            f"{decision.direction!r}"
        )

    return NavigationDirective(
        direction=decision.direction,
        position=decision.position,
        identified_as=decision.identified_as,
        evidence=decision.evidence,
    )
