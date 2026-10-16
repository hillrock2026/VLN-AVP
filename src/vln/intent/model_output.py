"""Model-output adapter: raw model text -> validated ``AgentIntent`` v1.

Model output is **untrusted input**. This module is the single sanctioned gate
that turns raw model text into an :class:`~vln.intent.agent_intent.AgentIntent`.
It is a pure, side-effect-free data layer: it never executes a capability,
never talks to a host, never submits a request, and never guesses a value the
model did not supply.

The model-output contract v1 is exactly the ``AgentIntent`` v1 payload object
(see ``docs/MODEL_OUTPUT_CONTRACT.md``)::

    {"contract_version":"1","intent_id":"intent-0001","action":"parking.move",
     "target":{"x":1.5,"y":-2.25,"heading":0.5}}

Three failure layers are kept distinct so a caller can tell *who* rejected the
input:

* :class:`ModelOutputParseError` - the raw text is not a well-formed JSON
  *object* (non-string, empty/blank, malformed/truncated, trailing content,
  duplicate keys, a non-standard numeric constant, or a non-object top level);
* :class:`ModelOutputShapeError` - it is a JSON object, but its top-level
  fields are not exactly the model-output contract's fields;
* :class:`ModelOutputValidationError` - it has the right outer shape but the
  authoritative :class:`AgentIntent` validator rejected its contents (field
  types/values, ``target`` structure, finiteness, version, action, intent_id).

Only the outer shape is checked here; every semantic rule is delegated to
:meth:`AgentIntent.from_payload`, the single source of truth for the v1
contract. No rule is re-implemented and no field is added, defaulted or
repaired. A model-output failure is never a submission, and a success is only
a validated intent value - not authorization, submission or execution.
"""

from __future__ import annotations

import json
from typing import Any

from .agent_intent import REQUIRED_FIELDS, AgentIntent, AgentIntentError

__all__ = [
    "ModelOutputError",
    "ModelOutputParseError",
    "ModelOutputShapeError",
    "ModelOutputValidationError",
    "parse_model_output",
]


class ModelOutputError(AgentIntentError):
    """Base class: raw model output could not become a validated AgentIntent.

    Subclasses :class:`~vln.intent.agent_intent.AgentIntentError` so a caller
    that guards the AgentIntent boundary also catches every model-output
    failure; the specific subclass identifies the rejecting layer.
    """


class ModelOutputParseError(ModelOutputError):
    """The raw model text is not a well-formed JSON *object*.

    Text-level failures: non-string input, empty or blank text, malformed or
    truncated JSON, trailing content (including a second JSON object), a
    duplicate object key, a non-standard numeric constant (``NaN`` /
    ``Infinity`` / ``-Infinity``), or a top-level value that is not an object
    (array, string, number, boolean, null).
    """


class ModelOutputShapeError(ModelOutputError):
    """A JSON object whose top-level fields are not the model-output contract.

    Raised when the top-level field set is not exactly ``contract_version``,
    ``intent_id``, ``action`` and ``target`` - i.e. a required field is absent
    or an unknown field is present. Field *values* are not inspected here.
    """


class ModelOutputValidationError(ModelOutputError):
    """A correctly shaped object that the AgentIntent v1 validator rejected.

    The authoritative :meth:`AgentIntent.from_payload` failed on the object's
    contents; the underlying :class:`AgentIntentError` is chained as
    ``__cause__``.
    """


class _DuplicateJsonKeyError(ValueError):
    """Internal: a JSON object repeated a key (ambiguous input)."""


def _object_pairs_rejecting_duplicate_keys(pairs: list) -> dict:
    """``object_pairs_hook`` that fails closed on a repeated key.

    ``json.loads`` would otherwise keep the last value silently, so an
    ambiguous model output could be resolved to an unintended value.
    """

    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            raise _DuplicateJsonKeyError(f"duplicate key {key!r}")
        obj[key] = value
    return obj


def _reject_json_constant(name: str) -> Any:
    """``parse_constant`` callback: ``NaN``/``Infinity`` are not standard JSON."""

    raise ValueError(f"non-standard numeric constant is not allowed: {name}")


def _parse_strict_object(raw_text: str) -> dict:
    """Decode ``raw_text`` into a JSON object, rejecting every non-standard form."""

    if type(raw_text) is not str:
        raise ModelOutputParseError("model output must be a string")
    try:
        decoded = json.loads(
            raw_text,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_object_pairs_rejecting_duplicate_keys,
        )
    except _DuplicateJsonKeyError as exc:
        raise ModelOutputParseError(
            f"model output contains a duplicate field: {exc}"
        ) from exc
    except ValueError as exc:
        # json.JSONDecodeError and a rejected numeric constant are both ValueError.
        raise ModelOutputParseError(
            f"model output is not valid JSON: {exc}"
        ) from exc
    if not isinstance(decoded, dict):
        raise ModelOutputParseError("model output must decode to a JSON object")
    return decoded


def parse_model_output(raw_text: str) -> AgentIntent:
    """Convert raw model text into a validated :class:`AgentIntent`.

    The text must be a compact JSON object matching the model-output contract
    v1. The object is first checked for the exact top-level field set, then
    handed unchanged to :meth:`AgentIntent.from_payload`, which performs the
    authoritative v1 validation. On any failure a :class:`ModelOutputError`
    subclass is raised and no ``AgentIntent`` is produced.
    """

    obj = _parse_strict_object(raw_text)

    if set(obj) != set(REQUIRED_FIELDS):
        missing = [name for name in REQUIRED_FIELDS if name not in obj]
        unknown = [name for name in obj if name not in REQUIRED_FIELDS]
        raise ModelOutputShapeError(
            "model output must have exactly the fields "
            f"{list(REQUIRED_FIELDS)}; missing={missing}, unknown={unknown}"
        )

    try:
        return AgentIntent.from_payload(raw_text)
    except AgentIntentError as exc:
        raise ModelOutputValidationError(
            f"model output is not a valid AgentIntent v1: {exc}"
        ) from exc
