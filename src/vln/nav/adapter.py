"""Layer 3: a verified visual directive -> an existing ``AgentIntent`` v1.

This is the only place in the project where a discrete visual direction becomes
numbers, so the whole convention is stated here and nowhere else.

What the project does and does not define (checked in the actual sources before
this module was written - ``docs/decisions/M1-03B0_AGENT_INTENT_V1_DECISIONS.md``
§3.5/§7 and ``docs/decisions/M1-04B0_PARKING_MOVE_STUB_DECISIONS.md`` §5.3):

* ``AgentIntent v1`` fixes the *syntax and numeric* contract of ``target`` - x and
  y in metres, ``heading`` in radians, counter-clockwise positive from +X towards
  +Y, normalized into ``[-pi, pi)`` - and marks every one of those properties
  ``PROPOSED``;
* the map frame's origin and axes are explicitly ``UNRESOLVED``, because they
  depend on a simulator that does not exist in this repository;
* the ``parking.move`` capability is a stub that **echoes** the target it is given
  and interprets nothing, so there is no motion model, no vehicle kinematics and
  no ``direction -> coordinate`` rule anywhere in the tree;
* the only target values that exist in code today are the fabricated demo
  constants in ``src/vln/__main__.py`` / ``tests/integration/test_vln_loop_e2e.py``
  (a scripted simulation explicitly documented as "not a model").

The minimal adapter contract frozen here therefore claims exactly one thing -

    the discrete direction selects a **heading delta** applied to a
    caller-supplied vehicle heading

- and nothing else:

* **Inputs.** an already-verified
  :class:`~vln.nav.visual_decision.NavigationDirective`, a :class:`VehiclePose`
  supplied by the caller, and a caller-owned ``intent_id``.
* **Heading semantics.** ``target.heading == normalize_heading(pose.heading +
  DIRECTION_HEADING_DELTA[direction])``. The *signs* follow from the v1
  convention that heading increases counter-clockwise: a left turn adds, a right
  turn subtracts. The *magnitudes* are a declared simulation convention, not a
  measurement of any vehicle.
* **Coordinate semantics.** ``target.x``/``target.y`` are the pose's x and y. **No
  displacement is computed**, because there is no map frame, no pose source, no
  odometry and no motion model in this project to compute one against. The
  dependency is visible in the signature instead of hidden in a default.
* **Scope.** simulation only. Nothing produced here is a real road coordinate, a
  drivable trajectory, a feasible motion or a distance, and a mapped intent is
  never evidence that a vehicle moved.
* **Refusal.** A missing or malformed pose, or a direction with no declared
  delta, means the target's coordinate semantics cannot be determined, and the
  layer raises :class:`~vln.nav.errors.NavigationMappingError` rather than
  guessing a position or a heading.

The one thing this module deliberately will not do is read ``x < 0`` out of
``LEFT``: no source in this repository justifies that reading.

A ``NavigationDirective`` cannot be constructed from raw model text - only
:func:`~vln.nav.visual_decision.verify_visual_decision` returns one - so the
*type* is the guarantee that nothing unverified reaches ``AgentIntent``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType

from vln.intent.agent_intent import AgentIntent, Target, normalize_heading

from .errors import NavigationMappingError
from .visual_decision import NavigationDirective

__all__ = [
    "DIRECTION_HEADING_DELTA",
    "VehiclePose",
    "to_agent_intent",
]

#: The declared, simulation-only direction -> heading-delta table, in radians.
#: Signs follow the frozen v1 convention (counter-clockwise positive); the
#: magnitude is a convention of this layer and carries no vehicle-motion claim.
DIRECTION_HEADING_DELTA = MappingProxyType(
    {
        "LEFT": math.pi / 2.0,
        "RIGHT": -math.pi / 2.0,
        "STRAIGHT": 0.0,
    }
)


def _require_finite(value: object, name: str) -> None:
    """Reject non-numbers, booleans and non-finite numbers.

    The same rule :class:`~vln.intent.agent_intent.Target` applies; the v1
    helper for it is private to that module, so the check is restated here rather
    than imported across a module boundary.
    """

    if type(value) is not int and type(value) is not float:
        raise NavigationMappingError(f"{name} must be a number (int or float)")
    if not math.isfinite(value):
        raise NavigationMappingError(f"{name} must be a finite number")


@dataclass(frozen=True)
class VehiclePose:
    """The caller-supplied vehicle pose this layer maps *from*.

    Where the pose comes from is the caller's responsibility: this project has no
    localisation, odometry or simulator that could source one, and the layer
    never invents, defaults or estimates it. ``heading`` is stored normalized,
    exactly as :class:`~vln.intent.agent_intent.Target` stores its heading.
    """

    x: float
    y: float
    heading: float

    def __post_init__(self) -> None:
        _require_finite(self.x, "pose.x")
        _require_finite(self.y, "pose.y")
        _require_finite(self.heading, "pose.heading")
        object.__setattr__(self, "heading", normalize_heading(self.heading))


def to_agent_intent(
    directive: NavigationDirective, *, pose: VehiclePose, intent_id: str
) -> AgentIntent:
    """Map a verified directive onto a validated ``AgentIntent`` v1.

    Refuses (with :class:`~vln.nav.errors.NavigationMappingError`) when
    ``directive`` is not a verified directive, when ``pose`` is not a
    :class:`VehiclePose`, or when the directive's direction has no declared
    heading delta. ``intent_id`` is passed through untouched: it is validated by
    the authoritative v1 constructor, so a contract violation surfaces as
    :class:`~vln.intent.agent_intent.AgentIntentValidationError` rather than as a
    second, weaker rule here.
    """

    if not isinstance(directive, NavigationDirective):
        raise NavigationMappingError(
            "expected a verified NavigationDirective (only "
            "verify_visual_decision produces one), got "
            f"{type(directive).__name__}"
        )
    if not isinstance(pose, VehiclePose):
        raise NavigationMappingError(
            f"a VehiclePose is required to determine the target's coordinate "
            f"semantics, got {type(pose).__name__}"
        )

    delta = DIRECTION_HEADING_DELTA.get(directive.direction)
    if delta is None:
        raise NavigationMappingError(
            f"no declared heading delta for direction {directive.direction!r}; "
            f"declared directions are {sorted(DIRECTION_HEADING_DELTA)}"
        )

    return AgentIntent(
        intent_id=intent_id,
        target=Target(
            x=pose.x,
            y=pose.y,
            heading=normalize_heading(pose.heading + delta),
        ),
    )
