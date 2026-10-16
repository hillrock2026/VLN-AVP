"""VLN-AVP AgentIntent v1 contract package.

Public surface:

* :mod:`vln.intent.agent_intent` - the ``AgentIntent`` v1 data model, its
  strict validation and its JSON (de)serialization, plus the error family.
* :mod:`vln.intent.model_output` - the adapter that turns untrusted raw model
  text into a validated ``AgentIntent`` (still not execution).

This package defines a pure data contract. It performs no execution and does
not change the IPC envelope; a serialized intent is carried verbatim in the
existing IPC ``payload`` field.
"""

from .agent_intent import (
    ACTION_PARKING_MOVE,
    CONTRACT_VERSION,
    MAX_INTENT_ID_CHARS,
    AgentIntent,
    AgentIntentError,
    AgentIntentParseError,
    AgentIntentSerializationError,
    AgentIntentValidationError,
    Target,
)
from .model_output import (
    ModelOutputError,
    ModelOutputParseError,
    ModelOutputShapeError,
    ModelOutputValidationError,
    parse_model_output,
)

__all__ = [
    "CONTRACT_VERSION",
    "ACTION_PARKING_MOVE",
    "MAX_INTENT_ID_CHARS",
    "AgentIntent",
    "AgentIntentError",
    "AgentIntentParseError",
    "AgentIntentValidationError",
    "AgentIntentSerializationError",
    "Target",
    "ModelOutputError",
    "ModelOutputParseError",
    "ModelOutputShapeError",
    "ModelOutputValidationError",
    "parse_model_output",
]
