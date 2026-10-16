"""Bridge a validated :class:`~vln.intent.agent_intent.AgentIntent` to an IPC :class:`~vln.ipc.envelope.Request`.

This module is a pure, side-effect-free data layer. It performs **no** IPC,
constructs **no** host and submits **nothing**; it only maps an already
validated intent value onto the existing IPC v1 request envelope
(:mod:`vln.ipc.envelope`). It never re-parses raw model text, never repairs or
rewrites the intent, and never invents protocol fields.

Mapping (all from the frozen AgentIntent v1 contract):

* ``capability_id`` <- ``intent.action`` (``"parking.move"`` in v1);
* ``payload``       <- ``intent.to_payload()`` (the authoritative serialization);
* ``request_id``    <- supplied by the caller, per the existing ``Request``
  contract. It is **not** derived from ``intent.intent_id``: the two are
  independent identities (an intent_id is a semantic-intent id; a request_id is
  the IPC correlation id). This bridge never equates them.

The bridge owns no idempotency, deduplication, retry or exactly-once claim;
``request_id`` is not treated as an idempotency key.
"""

from __future__ import annotations

from vln.intent import AgentIntent
from vln.ipc.envelope import Request

__all__ = ["build_request"]


def build_request(intent: AgentIntent, *, request_id: str) -> Request:
    """Map a validated :class:`AgentIntent` to an IPC v1 :class:`Request`.

    Raises :class:`TypeError` when ``intent`` is not an :class:`AgentIntent`
    instance: the bridge accepts only an already-validated intent value and
    never silently coerces, repairs or accepts an arbitrary object. The intent
    itself is already validated by its own authoritative contract, so no field
    is re-checked, defaulted or rewritten here.
    """

    if not isinstance(intent, AgentIntent):
        raise TypeError(
            "build_request expects a validated AgentIntent, "
            f"got {type(intent).__name__}"
        )

    return Request(
        request_id=request_id,
        capability_id=intent.action,
        payload=intent.to_payload(),
    )
