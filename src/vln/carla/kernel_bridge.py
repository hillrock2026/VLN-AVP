"""Authorized CARLA execution bridge for the Agent-Kernel ``parking.move``.

The real Kernel host is a C++ process (:file:`runtime_host/kernel_host.cpp`).
It cannot import the CARLA Python API. This module closes that gap with the
smallest possible adapter:

* The runnable CARLA script owns the world, the ego vehicle and the validated
  route. It starts a loopback-only TCP server and registers a **single-use
  execution permit** for one round.
* The Kernel host reaches the registered ``parking.move`` capability through
  its normal Runtime authorization path. When a bridge is configured, that
  capability sends one JSON request to this server and blocks for the answer.
* The permit binds the Kernel request_id, intent_id, capability, target and
  payload to the already-arbitrated route. A request that does not match the
  permit, arrives without the token, is duplicated, or arrives concurrently is
  rejected **before** the controller callback runs.
* Only an accepted request invokes the callback. The callback is the existing
  CARLA constrained controller path; it returns the real pre/post state read
  from CARLA after braking.

This module is stdlib-only and never imports ``carla``. It is not a general
RPC framework: one host, one capability, one in-flight execution, no retry and
no idempotency claim. ``request_id`` is a correlation id, not a dedup key.
"""

from __future__ import annotations

import hmac
import json
import math
import secrets
import socket
import socketserver
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

__all__ = [
    "CAPABILITY_ID",
    "KernelBridgeError",
    "ExecutionPermit",
    "CarlaExecutionBridge",
]

CAPABILITY_ID = "parking.move"
PROTOCOL_VERSION = "1"
OUTPUT_VERSION = "2"
MAX_REQUEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
REQUEST_TIMEOUT_S = 30.0

_ALLOWED_STATUSES = frozenset({"completed", "stopped", "failed"})
_STATE_KEYS = ("x", "y", "speed")


class KernelBridgeError(Exception):
    """The bridge could not accept or complete one execution request."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(message: str) -> None:
    sys.stderr.write(f"carla-bridge: {message}\n")
    sys.stderr.flush()


def _finite_number(value: object) -> bool:
    if type(value) is int:
        return True
    return type(value) is float and math.isfinite(value)


def _state(value: object, name: str) -> dict:
    if not isinstance(value, Mapping):
        raise KernelBridgeError(f"{name} must be an object")
    missing = [key for key in _STATE_KEYS if key not in value]
    if missing:
        raise KernelBridgeError(f"{name} is missing {missing}")
    for key in _STATE_KEYS:
        if not _finite_number(value[key]):
            raise KernelBridgeError(f"{name}.{key} must be a finite number")
    return dict(value)


def _exact_target(value: object) -> dict:
    if not isinstance(value, Mapping) or set(value) != {"x", "y", "heading"}:
        raise KernelBridgeError("target must be an object with exactly x, y, heading")
    for key in ("x", "y", "heading"):
        if not _finite_number(value[key]):
            raise KernelBridgeError(f"target.{key} must be a finite number")
    return {"x": value["x"], "y": value["y"], "heading": value["heading"]}


def _targets_equal(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    try:
        return all(float(a[key]) == float(b[key]) for key in ("x", "y", "heading"))
    except (KeyError, TypeError, ValueError):
        return False


@dataclass(frozen=True)
class ExecutionPermit:
    """One round's authorization to move the vehicle through ``parking.move``.

    ``context`` is opaque to the bridge and is handed to the execution callback
    (for the 01E runner it carries the arbitrated route and limits). The bridge
    itself never interprets it.
    """

    request_id: str
    intent_id: str
    target: Mapping[str, Any]
    payload: str
    context: Any = field(default=None, compare=False, repr=False)


class CarlaExecutionBridge:
    """Loopback JSON-lines server guarded by a token and single-use permits.

    Usage::

        with CarlaExecutionBridge(handler, token=token) as bridge:
            bridge.register_permit(...)
            response = host_client.send(request)
            transaction = bridge.get_transaction(request.request_id)
    """

    def __init__(
        self,
        handler: Callable[[ExecutionPermit], Mapping[str, Any]],
        *,
        token: Optional[str] = None,
        host: str = "127.0.0.1",
        port: int = 0,
        request_timeout_s: float = REQUEST_TIMEOUT_S,
    ) -> None:
        if not callable(handler):
            raise TypeError("handler must be callable")
        if type(host) is not str or host.strip() == "":
            raise ValueError("host must be a non-blank str")
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("port must be an int in [0, 65535]")
        self._handler = handler
        self._token = token if token is not None else secrets.token_hex(32)
        if type(self._token) is not str or self._token.strip() == "":
            raise ValueError("token must be a non-blank str")
        self._host = host
        self._port = port
        self._request_timeout_s = float(request_timeout_s)
        self._lock = threading.Lock()
        self._permits: dict[str, ExecutionPermit] = {}
        self._transactions: list[dict] = []
        self._executing = False
        self._server: Optional[_BridgeServer] = None
        self._thread: Optional[threading.Thread] = None

    # -- lifecycle ------------------------------------------------------

    def set_handler(self, handler: Callable[[ExecutionPermit], Mapping[str, Any]]) -> None:
        """Select the stage handler for the next single-use permit.

        The session driver reuses one bridge across navigation, alignment and
        Entry; each stage registers its own permits and installs its handler
        before submitting. Changing the handler while an execution is in
        flight is refused.
        """

        if not callable(handler):
            raise TypeError("handler must be callable")
        with self._lock:
            if self._executing:
                raise KernelBridgeError(
                    "cannot change the bridge handler while executing"
                )
            self._handler = handler

    def start(self) -> "CarlaExecutionBridge":
        if self._server is not None:
            return self
        server = _BridgeServer(
            (self._host, self._port), _BridgeRequestHandler, self
        )
        server.timeout = 0.5
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            name="carla-kernel-bridge",
            daemon=True,
        )
        self._thread.start()
        _log(f"listening on {self.endpoint} (token required)")
        return self

    @property
    def endpoint(self) -> str:
        if self._server is None:
            raise KernelBridgeError("bridge is not started")
        host, port = self._server.server_address[:2]
        return f"{host}:{port}"

    @property
    def token(self) -> str:
        return self._token

    def close(self) -> None:
        server = self._server
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._server = None
        self._thread = None
        _log("stopped")

    def __enter__(self) -> "CarlaExecutionBridge":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # -- permits and evidence ------------------------------------------

    def register_permit(
        self,
        *,
        request_id: str,
        intent_id: str,
        target: Mapping[str, Any],
        payload: str,
        context: Any = None,
    ) -> ExecutionPermit:
        """Authorize exactly one execution for ``request_id``.

        Callers must do this only after the route was arbitrated and the
        pre-execution safety gate passed. Registering a permit performs no
        motion; it only allows a matching Kernel request to reach the callback.
        """

        for name, value in (("request_id", request_id), ("intent_id", intent_id)):
            if type(value) is not str or value.strip() == "":
                raise ValueError(f"{name} must be a non-blank str")
        if type(payload) is not str or payload.strip() == "":
            raise ValueError("payload must be a non-blank str")
        normalized_target = _exact_target(target)
        permit = ExecutionPermit(
            request_id=request_id,
            intent_id=intent_id,
            target=normalized_target,
            payload=payload,
            context=context,
        )
        with self._lock:
            if request_id in self._permits:
                raise KernelBridgeError(f"permit already registered for {request_id!r}")
            self._permits[request_id] = permit
        return permit

    def revoke_permit(self, request_id: str) -> None:
        with self._lock:
            self._permits.pop(request_id, None)

    def get_transaction(self, request_id: str) -> Optional[dict]:
        with self._lock:
            for transaction in reversed(self._transactions):
                if transaction["request_id"] == request_id:
                    return json.loads(json.dumps(transaction))
        return None

    @property
    def transactions(self) -> list[dict]:
        with self._lock:
            return json.loads(json.dumps(self._transactions))

    # -- request handling ----------------------------------------------

    def _consume_permit(
        self, request_id: str, intent_id: str, target: Mapping[str, Any]
    ) -> tuple[Optional[ExecutionPermit], str]:
        with self._lock:
            permit = self._permits.pop(request_id, None)
            if permit is None:
                return None, "no_execution_permit"
            if permit.intent_id != intent_id:
                return None, "intent_id_mismatch"
            if not _targets_equal(permit.target, target):
                return None, "target_mismatch"
            return permit, ""

    def _record(self, transaction: dict) -> None:
        with self._lock:
            transaction["index"] = len(self._transactions) + 1
            self._transactions.append(transaction)

    def _handle_line(self, raw: bytes) -> dict:
        received = _utc_now()
        base = {
            "received_utc": received,
            "request_id": None,
            "intent_id": None,
            "authorized": False,
            "handler_started": False,
            "handler_finished": False,
            "status": "rejected",
            "reason": "",
            "vehicle": None,
            "error": None,
        }
        try:
            if len(raw) > MAX_REQUEST_BYTES:
                raise KernelBridgeError("request exceeds the bridge size limit")
            try:
                request = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise KernelBridgeError(f"request is not valid JSON: {exc}") from exc
            if not isinstance(request, Mapping):
                raise KernelBridgeError("request must be a JSON object")

            request_id = request.get("request_id")
            intent_id = request.get("intent_id")
            if type(request_id) is str:
                base["request_id"] = request_id
            if type(intent_id) is str:
                base["intent_id"] = intent_id

            token = request.get("token")
            if type(token) is not str or not hmac.compare_digest(
                token, self._token
            ):
                raise KernelBridgeError("token mismatch")

            if request.get("protocol_version") != PROTOCOL_VERSION:
                raise KernelBridgeError("unsupported bridge protocol_version")
            if request.get("capability_id") != CAPABILITY_ID:
                raise KernelBridgeError("unsupported capability_id")
            if type(request_id) is not str or request_id.strip() == "":
                raise KernelBridgeError("request_id must be a non-blank str")
            if type(intent_id) is not str or intent_id.strip() == "":
                raise KernelBridgeError("intent_id must be a non-blank str")
            intent = request.get("payload")
            if not isinstance(intent, Mapping):
                raise KernelBridgeError("payload must be an AgentIntent object")
            if set(intent) != {"contract_version", "intent_id", "action", "target"}:
                raise KernelBridgeError("unexpected AgentIntent field set")
            if intent.get("contract_version") != "1":
                raise KernelBridgeError("unsupported contract_version")
            if intent.get("action") != CAPABILITY_ID:
                raise KernelBridgeError("AgentIntent action is not parking.move")
            if intent.get("intent_id") != intent_id:
                raise KernelBridgeError("payload intent_id does not match the envelope")
            target = _exact_target(intent.get("target"))

            permit, reason = self._consume_permit(request_id, intent_id, target)
            if permit is None:
                raise KernelBridgeError(reason)
            try:
                permitted_intent = json.loads(permit.payload)
            except ValueError as exc:
                # The permit is consumed; a mismatch is terminal for this id.
                raise KernelBridgeError(
                    f"permitted payload is not valid JSON: {exc}"
                ) from exc
            if permitted_intent != intent:
                raise KernelBridgeError("payload mismatch")
            base["authorized"] = True

            with self._lock:
                if self._executing:
                    raise KernelBridgeError("another execution is in progress")
                self._executing = True
            try:
                base["handler_started"] = True
                _log(
                    "execution authorized "
                    f"request_id={request_id} intent_id={intent_id}"
                )
                result = self._handler(permit)
                base["handler_finished"] = True
            finally:
                with self._lock:
                    self._executing = False

            if not isinstance(result, Mapping):
                raise KernelBridgeError("execution handler returned a non-object")
            status = result.get("status")
            if status not in _ALLOWED_STATUSES:
                raise KernelBridgeError(f"invalid execution status {status!r}")
            pre_state = _state(result.get("pre_state"), "pre_state")
            post_state = _state(result.get("post_state"), "post_state")
            stop_reason = result.get("stop_reason")
            if type(stop_reason) is not str or stop_reason.strip() == "":
                raise KernelBridgeError("stop_reason must be a non-blank str")
            stopped = result.get("stopped")
            if type(stopped) is not bool:
                raise KernelBridgeError("stopped must be a boolean")

            moved = math.hypot(
                float(post_state["x"]) - float(pre_state["x"]),
                float(post_state["y"]) - float(pre_state["y"]),
            )
            if not math.isfinite(moved):
                raise KernelBridgeError("computed displacement is not finite")
            if status == "completed" and not stopped:
                raise KernelBridgeError(
                    "completed execution did not confirm a stopped vehicle"
                )

            vehicle = dict(result)
            vehicle["pre_state"] = pre_state
            vehicle["post_state"] = post_state
            vehicle["moved_m"] = moved
            vehicle["stopped"] = stopped
            vehicle["stop_reason"] = stop_reason

            base.update(
                {
                    "status": status,
                    "reason": "executed",
                    "vehicle": vehicle,
                    "error": result.get("error"),
                }
            )
            # The transaction keeps the full result (control records and the
            # parking alignment phases) for evidence. The Host response only
            # needs the validation summary: a full parking result can exceed
            # the 1 MB bridge limit and the Host correctly rejects it.
            host_vehicle = {
                "status": status,
                "pre_state": pre_state,
                "post_state": post_state,
                "stopped": stopped,
                "stop_reason": stop_reason,
                "moved_m": moved,
            }
            for key in (
                "target_node_id",
                "segment_success",
                "distance_to_target_m",
                "final_heading_error_deg",
                "parking_phase",
                "stop_diagnostics",
                "stop_detail",
                "brake_error",
            ):
                if key in result:
                    host_vehicle[key] = result[key]
            _log(
                f"execution finished request_id={request_id} status={status} "
                f"moved_m={moved:.3f} stopped={stopped}"
            )
            return {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request_id,
                "intent_id": intent_id,
                "capability_id": CAPABILITY_ID,
                "execution_mode": "carla",
                "status": status,
                "target": target,
                "vehicle": host_vehicle,
                "error": result.get("error"),
            }
        except Exception as exc:
            base["status"] = "rejected"
            base["reason"] = f"{type(exc).__name__}: {exc}"
            base["error"] = {"type": type(exc).__name__, "message": str(exc)}
            _log(
                "execution rejected "
                f"request_id={base['request_id']} reason={base['reason']}"
            )
            return {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": base["request_id"],
                "intent_id": base["intent_id"],
                "capability_id": CAPABILITY_ID,
                "execution_mode": "carla",
                "status": "rejected",
                "reason": base["reason"],
                "error": base["error"],
            }
        finally:
            self._record(base)

    def _reject_without_line(self, reason: str) -> dict:
        self._record(
            {
                "received_utc": _utc_now(),
                "request_id": None,
                "intent_id": None,
                "authorized": False,
                "handler_started": False,
                "handler_finished": False,
                "status": "rejected",
                "reason": reason,
                "vehicle": None,
                "error": {"type": "BridgeReadError", "message": reason},
            }
        )
        return {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": None,
            "intent_id": None,
            "capability_id": CAPABILITY_ID,
            "execution_mode": "carla",
            "status": "rejected",
            "reason": reason,
            "error": {"type": "BridgeReadError", "message": reason},
        }


class _BridgeServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler_class, bridge: CarlaExecutionBridge):
        self.bridge = bridge
        super().__init__(address, handler_class)


class _BridgeRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        bridge: CarlaExecutionBridge = self.server.bridge  # type: ignore[attr-defined]
        self.request.settimeout(bridge._request_timeout_s)
        buffer = bytearray()
        try:
            while b"\n" not in buffer:
                chunk = self.request.recv(65536)
                if not chunk:
                    break
                buffer.extend(chunk)
                if len(buffer) > MAX_REQUEST_BYTES:
                    break
        except (socket.timeout, OSError):
            pass
        if b"\n" in buffer:
            raw = bytes(buffer).split(b"\n", 1)[0]
            response = bridge._handle_line(raw)
        else:
            response = bridge._reject_without_line("request line was not received")
        encoded = json.dumps(response, separators=(",", ":"), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_RESPONSE_BYTES:
            encoded = json.dumps(
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": response.get("request_id"),
                    "intent_id": response.get("intent_id"),
                    "capability_id": CAPABILITY_ID,
                    "execution_mode": "carla",
                    "status": "rejected",
                    "reason": "response exceeds the bridge size limit",
                    "error": {
                        "type": "BridgeResponseTooLarge",
                        "message": "response exceeds the bridge size limit",
                    },
                },
                separators=(",", ":"),
            )
        try:
            self.request.sendall(encoded.encode("utf-8") + b"\n")
        except OSError as exc:
            _log(f"failed to send bridge response: {exc}")
