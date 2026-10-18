"""Navigation-decision layer: a model's visual judgement -> ``AgentIntent`` v1.

The layer exists to make one boundary explicit and reviewable. The model speaks
in a closed vocabulary about what it sees; ``AgentIntent`` speaks in metres and
radians. Between the two there was - before this package - nothing at all, so a
model answer could not become an intent without somebody inventing a meaning for
it. The chain is now three named steps, each of which can only consume the
previous step's output type:

    raw model text
      -> parse_visual_decision      # layer 1, structure (vln.nav.visual_decision)
      -> verify_visual_decision     # layer 2, executability  -> NavigationDirective
      -> to_agent_intent            # layer 3, mapping         -> AgentIntent v1

Every step fails closed: a malformed answer, an unreadable identity, an
off-vocabulary direction, a self-contradictory block, a missing pose or a
contract violation each raise, and no step substitutes a default direction or a
default coordinate. The layer never talks to a host, never submits a request and
never executes anything - it returns a validated *intent value* and stops there,
leaving registration, authorisation and execution to the existing Agent-Kernel
path.

Scope, stated because it is easy to overclaim: the mapping is a declared
simulation-only convention (see :mod:`vln.nav.adapter`), not vehicle kinematics,
and a produced intent says nothing about whether a vehicle moved.
"""

from .adapter import DIRECTION_HEADING_DELTA, VehiclePose, to_agent_intent
from .errors import (
    EvidenceInsufficientError,
    NavigationConstraintError,
    NavigationDecisionError,
    NavigationMappingError,
    RouteIntentMappingError,
    TargetIdentityMismatchError,
    TargetNotVisibleError,
    VisualDecisionParseError,
    VisualDecisionValidationError,
)
from .planner_bridge import (
    DEFAULT_TOLERANCE_DEG,
    ConstraintBuildResult,
    ConstraintBuildStatus,
    ConstraintSource,
    NavigationConstraint,
    NavigationPlanningResult,
    NavigationPlanningStatus,
    constraint_from_agent_intent,
    constraint_from_directive,
    plan_with_navigation_constraint,
    synthetic_navigation_constraint,
)
from .visual_decision import (
    DECISION_FIELDS,
    POSITION_TO_DIRECTION,
    NavigationDirective,
    VisualNavigationDecision,
    evidence_is_insufficient,
    identity_matches,
    parse_visual_decision,
    verify_visual_decision,
)

__all__ = [
    "DIRECTION_HEADING_DELTA",
    "VehiclePose",
    "to_agent_intent",
    "NavigationDecisionError",
    "NavigationMappingError",
    "NavigationConstraintError",
    "RouteIntentMappingError",
    "TargetIdentityMismatchError",
    "TargetNotVisibleError",
    "EvidenceInsufficientError",
    "VisualDecisionParseError",
    "VisualDecisionValidationError",
    "DECISION_FIELDS",
    "POSITION_TO_DIRECTION",
    "NavigationDirective",
    "VisualNavigationDecision",
    "evidence_is_insufficient",
    "identity_matches",
    "parse_visual_decision",
    "verify_visual_decision",
    "DEFAULT_TOLERANCE_DEG",
    "ConstraintBuildResult",
    "ConstraintBuildStatus",
    "ConstraintSource",
    "NavigationConstraint",
    "NavigationPlanningResult",
    "NavigationPlanningStatus",
    "constraint_from_agent_intent",
    "constraint_from_directive",
    "plan_with_navigation_constraint",
    "synthetic_navigation_constraint",
]
