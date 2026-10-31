"""A :class:`~vln.vlm.model_client.ModelClient` over the Kernel planner path.

This client does not talk to a model service. It sends one ``planner.plan``
request to the compiled Kernel host, whose real ``ak::planner::Planner`` owns a
``TaichuPlanningEngine`` and whose engine reaches the model through the loopback
planner bridge. The host returns the planner exchange metadata plus the model's
raw assistant text.

The raw text is returned verbatim to the existing ``generate_and_decide``
chain, which continues to own parsing, identity verification, route arbitration
and intent construction. This client never parses a decision, never builds a
route and never treats the model output as an execution permit.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from vln.ipc.envelope import Request
from vln.vlm.model_client import ModelCallError

__all__ = ["HostPlannerError", "HostPlannerExchange", "HostPlannerModelClient"]

PLANNER_CAPABILITY_ID = "planner.plan"


class HostPlannerError(ModelCallError):
    """The Kernel planner path did not yield a usable candidate output."""


@dataclass(frozen=True)
class HostPlannerExchange:
    """One Kernel planner exchange, retained for evidence."""

    request_id: str
    planner_session_id: Optional[str]
    planner_request_id: Optional[str]
    planning_result_id: Optional[str]
    planning_artifact_id: Optional[str]
    context_revision: Optional[int]
    turn: Optional[int]
    session_id: Optional[str]
    session_state: Optional[str]
    model: Optional[Mapping[str, Any]]
    raw_output: str
    output: Mapping[str, Any]
    response: Mapping[str, Any]
    context_before: Optional[Mapping[str, Any]] = None
    context_after: Optional[Mapping[str, Any]] = None

    def to_metadata(self) -> dict:
        raw = self.raw_output
        return {
            "request_id": self.request_id,
            "planner_session_id": self.planner_session_id,
            "planner_request_id": self.planner_request_id,
            "planning_result_id": self.planning_result_id,
            "planning_artifact_id": self.planning_artifact_id,
            "context_revision": self.context_revision,
            "turn": self.turn,
            "session_id": self.session_id,
            "session_state": self.session_state,
            "model": dict(self.model) if self.model else None,
            "raw_output_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "raw_output_chars": len(raw),
            "context_before": (
                dict(self.context_before)
                if self.context_before is not None
                else None
            ),
            "context_after": (
                dict(self.context_after)
                if self.context_after is not None
                else None
            ),
            "output": {
                key: value
                for key, value in self.output.items()
                if key != "raw_output"
            },
            "response": dict(self.response),
        }


@dataclass
class HostPlannerModelClient:
    """``ModelClient`` backed by the Host's real Kernel Planner path."""

    host_client: Any
    session_id: str
    context_revision: Optional[int]
    request_id_prefix: str = "planner"
    domain: Optional[Mapping[str, Any]] = None
    timeout_seconds: Optional[float] = None
    _sequence: int = field(default=0, init=False)
    last_exchange: Optional[HostPlannerExchange] = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not hasattr(self.host_client, "send"):
            raise TypeError("host_client must expose send(request)")
        if type(self.session_id) is not str or not self.session_id.strip():
            raise ValueError("session_id must be a non-blank str")
        if len(self.session_id) > 128:
            raise ValueError("session_id must be at most 128 characters")
        if self.context_revision is not None:
            if (
                type(self.context_revision) is not int
                or self.context_revision < 0
            ):
                raise ValueError("context_revision must be a non-negative int")
        if type(self.request_id_prefix) is not str or not self.request_id_prefix.strip():
            raise ValueError("request_id_prefix must be a non-blank str")
        if self.domain is not None and not isinstance(self.domain, Mapping):
            raise ValueError("domain must be a mapping or None")

    @property
    def context_revision_after(self) -> Optional[int]:
        return None if self.last_exchange is None else self.last_exchange.context_revision

    def _next_request_id(self) -> str:
        self._sequence += 1
        request_id = f"{self.request_id_prefix}-{self._sequence:03d}"
        if len(request_id) > 128:
            raise ValueError("planner request_id exceeds 128 characters")
        return request_id

    def generate(self, observation: object, instruction: str) -> str:
        if not isinstance(observation, (str, os.PathLike)):
            raise HostPlannerError(
                f"planner observation must be an image path, got "
                f"{type(observation).__name__}"
            )
        image_path = os.fspath(observation)
        if not isinstance(image_path, str) or not image_path.strip():
            raise HostPlannerError("planner image path must be a non-blank str")
        if type(instruction) is not str or not instruction.strip():
            raise HostPlannerError("planner instruction must be a non-blank str")

        payload_object: dict[str, Any] = {
            "image_path": image_path,
            "instruction": instruction,
        }
        if self.domain is not None:
            payload_object["domain"] = dict(self.domain)
        payload = json.dumps(payload_object, ensure_ascii=False, separators=(",", ":"))
        if len(payload.encode("utf-8")) > 1024 * 1024:
            raise HostPlannerError("planner payload exceeds 1048576 bytes")

        request_id = self._next_request_id()
        request = Request(
            request_id=request_id,
            capability_id=PLANNER_CAPABILITY_ID,
            payload=payload,
            session_id=self.session_id,
            expected_context_revision=self.context_revision,
            domain=dict(self.domain) if self.domain is not None else None,
        )
        response = self.host_client.send(request)

        output: dict[str, Any] = {}
        if isinstance(response.output, str):
            try:
                parsed = json.loads(response.output)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                output = parsed

        if isinstance(response.context_revision, int):
            self.context_revision = response.context_revision

        raw_output = output.get("raw_output")
        candidate = (
            response.accepted
            and response.submission_status == "completed"
            and response.observation_status == "success"
            and output.get("status") == "candidate"
            and isinstance(raw_output, str)
            and raw_output.strip() != ""
        )
        response_summary = {
            "accepted": response.accepted,
            "submission_status": response.submission_status,
            "observation_status": response.observation_status,
            "execution_status": response.execution_status,
            "context_revision": response.context_revision,
            "turn": response.turn,
            "context_updated": response.context_updated,
            "error": None if response.error is None else dict(response.error),
        }
        exchange = HostPlannerExchange(
            request_id=request_id,
            planner_session_id=output.get("planner_session_id"),
            planner_request_id=output.get("planner_request_id"),
            planning_result_id=output.get("planning_result_id"),
            planning_artifact_id=output.get("planning_artifact_id"),
            context_revision=(
                response.context_revision
                if isinstance(response.context_revision, int)
                else None
            ),
            turn=response.turn if isinstance(response.turn, int) else None,
            session_id=response.session_id,
            session_state=response.session_state,
            model=output.get("model") if isinstance(output.get("model"), dict) else None,
            raw_output=raw_output if isinstance(raw_output, str) else "",
            output=output,
            response=response_summary,
            context_before=(
                dict(response.context_before)
                if response.context_before is not None
                else None
            ),
            context_after=(
                dict(response.context_after)
                if response.context_after is not None
                else None
            ),
        )
        self.last_exchange = exchange

        if not candidate:
            if response.error is not None:
                code = response.error.get("code", "planner-failed")
                message = response.error.get("message", "planner request failed")
            else:
                code = "planner-output-rejected"
                message = (
                    "planner response did not contain a candidate model output "
                    f"(submission={response.submission_status}, "
                    f"observation={response.observation_status}, "
                    f"status={output.get('status')})"
                )
            raise HostPlannerError(f"{code}: {message}")
        return raw_output
