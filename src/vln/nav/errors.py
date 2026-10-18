"""Error family for the navigation-decision layer.

Kept deliberately small and rooted at
:class:`~vln.intent.agent_intent.AgentIntentError`, mirroring how
:class:`~vln.intent.model_output.ModelOutputError` is rooted: a caller that
guards the intent boundary with one ``except AgentIntentError`` also catches
every navigation-decision failure, so a failure cannot slip past that boundary
as if it were a validated intent.

The leaves are kept distinct because the task requires a failure to be
diagnosable by *which* check refused it - a visual failure, a structure failure,
an identity mismatch and a mapping failure are different problems with different
owners, and collapsing them into one code would hide that.

Nothing here is raised for an ``AgentIntent`` contract violation: the
authoritative :class:`~vln.intent.agent_intent.AgentIntentValidationError`
propagates **unchanged** through this layer rather than being wrapped, so the
v1 contract keeps a single semantics source (same reasoning as M1-04B0 §4.3
"避免形成第二套语义").
"""

from __future__ import annotations

from vln.intent.agent_intent import AgentIntentError

__all__ = [
    "NavigationDecisionError",
    "VisualDecisionParseError",
    "VisualDecisionValidationError",
    "TargetNotVisibleError",
    "TargetIdentityMismatchError",
    "EvidenceInsufficientError",
    "NavigationMappingError",
    "NavigationConstraintError",
    "RouteIntentMappingError",
]


class NavigationDecisionError(AgentIntentError):
    """Base class: a model visual judgement could not become a validated intent.

    Every failure this layer raises is one of its subclasses, so nothing here is
    silently converted into a default direction, a default coordinate or an
    empty success.
    """


class VisualDecisionParseError(NavigationDecisionError):
    """The raw model text is not a well-formed decision block.

    Structure-level failures: a non-string or blank response, a required field
    label that never appears, or a required field label that appears more than
    once (an ambiguous answer - the first occurrence is *not* silently taken).
    Field *values* are not judged here.
    """


class VisualDecisionValidationError(NavigationDecisionError):
    """A well-formed block whose values cannot authorise a navigation intent.

    Raised for an off-vocabulary token (including ``无法确定``), a missing or
    unusable discrete direction, or a self-contradictory answer where the
    relative position and the discrete direction disagree.
    """


class TargetNotVisibleError(VisualDecisionValidationError):
    """The model stated that the requested target is not visible in the image.

    Distinct from :class:`VisualDecisionValidationError` so a caller can tell
    "the model refused to see it" from "the model answered with a form the
    contract does not accept".
    """


class TargetIdentityMismatchError(VisualDecisionValidationError):
    """An identity field names something other than the requested target.

    Two cases. The identity the model says it *read* (``Identified as``) is not
    the requested one - the check the 08A measurement made necessary, because
    naming a target in an instruction can make a model state an identity it
    cannot read. Or the ``Target`` echo names a different label than the
    request, an internal contradiction even though that field is never treated
    as evidence of a read.
    """


class EvidenceInsufficientError(VisualDecisionValidationError):
    """The ``Evidence`` field states that it cannot support the judgement.

    Distinct from :class:`TargetNotVisibleError`: the model may claim the target
    is visible (``Visible: 是``) while its evidence value says it cannot
    determine anything. Only an Evidence value composed solely of approved
    uncertainty answers is classified here; free prose is never keyword-matched.
    """


class NavigationMappingError(NavigationDecisionError):
    """A verified decision could not be mapped onto an AgentIntent target.

    Raised when the layer cannot determine the target's coordinate semantics -
    for example when no vehicle pose was supplied, or the discrete direction has
    no declared heading delta. The layer refuses rather than guessing a
    position or a heading.
    """


class NavigationConstraintError(NavigationDecisionError):
    """A navigation constraint could not be built or consumed safely.

    Raised for a missing/unsupported direction, an invalid tolerance or source,
    a non-directive input, or a planning result that would select a route
    violating the declared hard constraint. The bridge refuses rather than
    guessing a direction or silently dropping the constraint.
    """


class RouteIntentMappingError(NavigationDecisionError):
    """A selected planned route could not be mapped to an ``AgentIntent v1``.

    Raised when planning did not select a route, the scene/route do not match,
    the next topology node is missing, or the explicit pose coincides with the
    target so no finite heading can be computed. The mapper refuses rather than
    inventing a target or a heading.
    """
