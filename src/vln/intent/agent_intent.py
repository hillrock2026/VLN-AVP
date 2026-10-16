"""AgentIntent v1 data contract: model, validation and serialization.

This module is the single source of truth for the ``AgentIntent`` v1 data
contract. It is a pure, side-effect-free data layer: it never executes a
capability, never talks to a host, and never claims idempotency,
deduplication or exactly-once behaviour.

The contract is frozen in
``docs/decisions/M1-03B0_AGENT_INTENT_V1_DECISIONS.md``. A valid
``AgentIntent`` can only be produced two ways - by constructing it from
structured fields, or by parsing an existing payload with
:meth:`AgentIntent.from_payload` - and both paths run the same value
validator. Values are never coerced loosely: an invalid field is rejected
rather than repaired.

Failure classes are kept distinct on purpose:

* :class:`AgentIntentParseError` - the payload text is not legal JSON, does
  not decode to a JSON object, or uses a non-standard numeric constant.
* :class:`AgentIntentValidationError` - a decoded intent violates a field or
  value rule of the v1 contract.
* :class:`AgentIntentSerializationError` - an intent could not be encoded as
  standard JSON.

The serialized payload is carried verbatim in the existing IPC ``payload``
field; this module does not change the IPC envelope, its version, its limits
or its error semantics.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from vln.ipc.envelope import is_non_blank

# ----------------------------------------------------------------------
# Frozen contract constants
# ----------------------------------------------------------------------

#: The AgentIntent contract version this implementation speaks. This is a
#: property of the intent itself and is independent of the IPC protocol
#: version (both happen to be the string ``"1"``).
CONTRACT_VERSION = "1"

#: The only ``action`` accepted by AgentIntent v1.
ACTION_PARKING_MOVE = "parking.move"

#: Maximum length of ``intent_id`` in characters (bounded input; kept equal
#: to the IPC ``MAX_REQUEST_ID_CHARS`` by convention).
MAX_INTENT_ID_CHARS = 128

#: Required top-level fields, in deterministic validation order.
REQUIRED_FIELDS = ("contract_version", "intent_id", "action", "target")

#: Required ``target`` fields, in deterministic validation order.
REQUIRED_TARGET_FIELDS = ("x", "y", "heading")


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------


class AgentIntentError(Exception):
    """Base class for every AgentIntent contract error."""


class AgentIntentParseError(AgentIntentError):
    """The payload text is not legal JSON or is not a JSON object."""


class AgentIntentValidationError(AgentIntentError):
    """A decoded intent violates a field or value rule of the v1 contract."""


class AgentIntentSerializationError(AgentIntentError):
    """An intent could not be encoded as standard JSON."""


# ----------------------------------------------------------------------
# Value helpers
# ----------------------------------------------------------------------


def _require_finite_number(value: Any, name: str) -> None:
    """Reject non-numbers, booleans and non-finite numbers.

    ``bool`` is a subclass of ``int`` in Python, so it is excluded by an
    exact-type check *before* the finiteness check; ``True``/``False`` must
    never masquerade as coordinates.
    """

    if type(value) is not int and type(value) is not float:
        raise AgentIntentValidationError(f"{name} must be a number (int or float)")
    if not math.isfinite(value):
        raise AgentIntentValidationError(f"{name} must be a finite number")


def normalize_heading(heading: float) -> float:
    """Normalize a finite angle in radians into the half-open range ``[-pi, pi)``.

    Angles are periodic, so an equivalent representation (for example
    ``3*pi/2`` and ``-pi/2``) is normalized rather than rejected.
    """

    return ((heading + math.pi) % (2.0 * math.pi)) - math.pi


def _reject_json_constant(name: str) -> Any:
    """``json.loads`` callback that turns ``NaN``/``Infinity`` into a failure."""

    raise ValueError(f"non-standard numeric constant is not allowed: {name}")


# ----------------------------------------------------------------------
# Target
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """The destination of an intent, in the parking-map ``map`` frame.

    ``x`` and ``y`` are metres; ``heading`` is radians (counter-clockwise
    positive from +X toward +Y). Only the syntax and numeric contract are
    defined here - whether a target lies inside a drivable area is a later
    scene/planning concern and is deliberately not checked.
    """

    x: float
    y: float
    heading: float

    def __post_init__(self) -> None:
        _require_finite_number(self.x, "target.x")
        _require_finite_number(self.y, "target.y")
        _require_finite_number(self.heading, "target.heading")
        # The single normalization point: the constructor stores the
        # canonical heading, and serialization writes it out unchanged.
        object.__setattr__(self, "heading", normalize_heading(self.heading))

    def to_object(self) -> dict:
        """Return the on-the-wire JSON object for this target."""

        return {"x": self.x, "y": self.y, "heading": self.heading}


# ----------------------------------------------------------------------
# AgentIntent
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class AgentIntent:
    """A validated AgentIntent v1.

    The field set is strict: unknown top-level or ``target`` fields are
    rejected, never ignored. ``contract_version`` and ``action`` default to
    the sole v1 values (mirroring the defaulted ``protocol_version``/``type``
    of :class:`vln.ipc.envelope.Request`) but an explicit wrong value is
    still rejected.
    """

    intent_id: str
    target: Target
    contract_version: str = CONTRACT_VERSION
    action: str = ACTION_PARKING_MOVE

    def __post_init__(self) -> None:
        if type(self.contract_version) is not str or self.contract_version != CONTRACT_VERSION:
            raise AgentIntentValidationError(
                f"contract_version must be the string {CONTRACT_VERSION!r}"
            )
        if type(self.intent_id) is not str:
            raise AgentIntentValidationError("intent_id must be a string")
        if len(self.intent_id) > MAX_INTENT_ID_CHARS:
            raise AgentIntentValidationError(
                f"intent_id exceeds {MAX_INTENT_ID_CHARS} characters"
            )
        if not is_non_blank(self.intent_id):
            raise AgentIntentValidationError(
                "intent_id must be non-empty and non-blank"
            )
        if type(self.action) is not str or self.action != ACTION_PARKING_MOVE:
            raise AgentIntentValidationError(f"unsupported action: {self.action!r}")
        if not isinstance(self.target, Target):
            raise AgentIntentValidationError("target must be a Target")

    def to_object(self) -> dict:
        """Return the on-the-wire JSON object for this intent."""

        return {
            "contract_version": self.contract_version,
            "intent_id": self.intent_id,
            "action": self.action,
            "target": self.target.to_object(),
        }

    def to_payload(self) -> str:
        """Serialize this intent to the compact JSON string used as IPC payload.

        ``allow_nan=False`` guarantees only standard JSON numbers are emitted;
        a non-finite value (unreachable through the constructors) raises
        :class:`AgentIntentSerializationError` rather than producing invalid
        JSON.
        """

        try:
            return json.dumps(
                self.to_object(),
                allow_nan=False,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except ValueError as exc:
            raise AgentIntentSerializationError(
                f"intent is not representable as standard JSON: {exc}"
            ) from exc

    @classmethod
    def from_payload(cls, text: str) -> "AgentIntent":
        """Parse and validate a payload string into an :class:`AgentIntent`.

        Malformed or non-object JSON raises :class:`AgentIntentParseError`;
        a structurally valid object that violates the contract raises
        :class:`AgentIntentValidationError`.
        """

        if type(text) is not str:
            raise AgentIntentParseError("payload must be a string")
        try:
            obj = json.loads(text, parse_constant=_reject_json_constant)
        except ValueError as exc:
            # json.JSONDecodeError is a ValueError subclass, so this covers
            # both malformed JSON and a rejected numeric constant.
            raise AgentIntentParseError(f"payload is not valid JSON: {exc}") from exc
        if not isinstance(obj, Mapping):
            raise AgentIntentParseError("payload must decode to a JSON object")
        return _build_from_object(obj)


def _build_from_object(obj: Mapping) -> AgentIntent:
    """Validate an already-decoded intent object and build an :class:`AgentIntent`.

    Performs the strict structural checks (required and unknown fields) and
    then delegates the value checks to the shared constructors.
    """

    for name in REQUIRED_FIELDS:
        if name not in obj:
            raise AgentIntentValidationError(f"missing required field: {name}")
    for name in obj:
        if name not in REQUIRED_FIELDS:
            raise AgentIntentValidationError(f"unknown field: {name}")

    target_obj = obj["target"]
    if not isinstance(target_obj, Mapping):
        raise AgentIntentValidationError("target must be a JSON object")
    for name in REQUIRED_TARGET_FIELDS:
        if name not in target_obj:
            raise AgentIntentValidationError(f"missing required target field: {name}")
    for name in target_obj:
        if name not in REQUIRED_TARGET_FIELDS:
            raise AgentIntentValidationError(f"unknown target field: {name}")

    return AgentIntent(
        intent_id=obj["intent_id"],
        target=Target(
            x=target_obj["x"],
            y=target_obj["y"],
            heading=target_obj["heading"],
        ),
        contract_version=obj["contract_version"],
        action=obj["action"],
    )


__all__ = [
    "CONTRACT_VERSION",
    "ACTION_PARKING_MOVE",
    "MAX_INTENT_ID_CHARS",
    "REQUIRED_FIELDS",
    "REQUIRED_TARGET_FIELDS",
    "AgentIntentError",
    "AgentIntentParseError",
    "AgentIntentValidationError",
    "AgentIntentSerializationError",
    "Target",
    "AgentIntent",
    "normalize_heading",
]
