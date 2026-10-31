"""Loopback planner bridge: Kernel TaichuPlanningEngine -> real ZDTaichu5.0-9B.

The C++ Kernel host owns an ``ak::planner::Planner`` whose ``IPlanningEngine``
is :class:`vln::taichu::TaichuPlanningEngine`. That engine speaks one NDJSON
request/response per connection to this process. This process is the only place
that touches the real model service, and it does so through the existing
``ZDTaichuServerBackend`` - the same backend the navigation script already uses.

Design rules:

* one request line -> one response line; no retry, no batching, no caching;
* the token is compared in constant time before anything else;
* the response carries the assistant text verbatim under ``raw_output``. It is
  never parsed, repaired, scored or turned into a route/execution decision;
* every failure (token, input, transport, HTTP, shape) is a ``status=failed``
  response with a typed message. No fabricated model output is ever returned;
* the model service endpoint, weights and server-side defaults are untouched:
  this script only supplies per-request generation parameters as a client.

stdout carries the single ``ready`` line; diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import signal
import socketserver
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from vln.vlm.context_prompt import (  # noqa: E402
    ContextPromptError,
    compose_prompt,
    select_context,
)
from vln.vlm.server_client import ZDTaichuServerBackend  # noqa: E402

PROTOCOL_VERSION = "1"
MAX_REQUEST_BYTES = 2 * 1024 * 1024
TOKEN_ENV = "VLN_TAICHU_PLANNER_TOKEN"


class BridgeInputError(Exception):
    """The bridge request itself is unusable."""


def _log(message: str) -> None:
    print(f"taichu-planner-bridge: {message}", file=sys.stderr, flush=True)


def _non_blank(value: object) -> bool:
    return isinstance(value, str) and any(not ch.isspace() for ch in value)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest_json(value: object) -> str:
    try:
        canonical = json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
    except (TypeError, ValueError):
        canonical = json.dumps(repr(value), ensure_ascii=False)
    return _sha256_text(canonical)


def _failure(request_id: object, error_type: str, message: str) -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id if isinstance(request_id, str) else None,
        "status": "failed",
        "raw_output": None,
        "error": {"type": error_type, "message": message},
    }


def _validate_request(request: object) -> tuple[str, str, str, dict]:
    if not isinstance(request, dict):
        raise BridgeInputError("request must be a JSON object")
    if request.get("protocol_version") != PROTOCOL_VERSION:
        raise BridgeInputError("unsupported protocol_version")
    request_id = request.get("request_id")
    if not _non_blank(request_id) or len(request_id) > 128:
        raise BridgeInputError("request_id must be a non-blank string <= 128 chars")
    image_path = request.get("image_path")
    if not _non_blank(image_path):
        raise BridgeInputError("image_path must be a non-blank string")
    instruction = request.get("instruction")
    if not _non_blank(instruction):
        raise BridgeInputError("instruction must be a non-blank string")
    return request_id, image_path, instruction, request


def process_request(
    request: object,
    *,
    expected_token: str,
    backend: ZDTaichuServerBackend,
) -> dict:
    """Handle one decoded bridge request and return one response object.

    This function never raises for an untrusted request or a model failure; it
    returns a ``status=failed`` response instead. It performs exactly one model
    call on the success path.
    """

    request_id = request.get("request_id") if isinstance(request, dict) else None

    if not isinstance(request, dict):
        return _failure(request_id, "BridgeInputError",
                        "request must be a JSON object")
    provided_token = request.get("token")
    if not isinstance(provided_token, str) or not hmac.compare_digest(
        provided_token, expected_token
    ):
        _log("rejected planner bridge request: invalid token")
        return _failure(request_id, "Unauthorized", "invalid planner bridge token")

    try:
        request_id, image_path, instruction, request = _validate_request(request)
    except BridgeInputError as error:
        return _failure(request_id, "BridgeInputError", str(error))

    path = Path(image_path)
    try:
        if not path.is_file():
            raise BridgeInputError(f"image_path is not a file: {image_path}")
        image_bytes = path.read_bytes()
    except BridgeInputError as error:
        return _failure(request_id, "ImagePathError", str(error))
    except OSError as error:
        return _failure(request_id, "ImagePathError",
                        f"cannot read image_path: {error}")

    context = request.get("context")
    domain = request.get("domain")
    if not isinstance(domain, dict):
        domain = {}
    try:
        selection = select_context(
            context,
            request_revision=request.get("context_revision"),
            request_session_id=request.get("session_id"),
            current_domain=domain,
        )
        prompt = compose_prompt(instruction, selection)
    except ContextPromptError as error:
        # Missing/malformed Context or a revision mismatch is a hard failure:
        # the bridge never falls back to an older Context or a bare prompt.
        _log(f"rejected planner request_id={request_id}: "
             f"{type(error).__name__}: {error}")
        return _failure(request_id, "ContextPromptError", str(error))

    started = time.monotonic()
    try:
        raw_output, server_metadata = backend.generate_image_with_metadata(
            image_path, prompt
        )
    except Exception as error:  # the model is an untrusted boundary
        _log(f"model call failed request_id={request_id}: "
             f"{type(error).__name__}: {error}")
        return _failure(request_id, type(error).__name__, str(error))
    latency_ms = round((time.monotonic() - started) * 1000.0, 3)

    if type(raw_output) is not str:
        return _failure(
            request_id,
            "BridgeProtocolError",
            f"model backend returned {type(raw_output).__name__}, expected str",
        )

    response = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "planner_session_id": request.get("planner_session_id"),
        "session_id": request.get("session_id"),
        "context_revision": request.get("context_revision"),
        "context_sha256": _digest_json(context),
        "status": "ok",
        "raw_output": raw_output,
        "raw_output_sha256": _sha256_text(raw_output),
        "latency_ms": latency_ms,
        "image_path": image_path,
        "image_sha256": _sha256_bytes(image_bytes),
        "image_size_bytes": len(image_bytes),
        "instruction": instruction,
        "instruction_sha256": _sha256_text(instruction),
        "prompt": prompt,
        "prompt_sha256": _sha256_text(prompt),
        "prompt_chars": len(prompt),
        "context_selection": selection.to_metadata(),
        "domain": domain,
        "model": {
            "backend": "zdt-taichu-server",
            "endpoint": backend.endpoint,
            "max_new_tokens": backend.max_new_tokens,
            "temperature": backend.temperature,
            "enable_thinking": backend.enable_thinking,
            "model_name": backend.model_name,
        },
        "server_response": server_metadata,
    }
    _log(
        f"planner model call completed request_id={request_id} "
        f"latency_ms={latency_ms} prompt_chars={len(prompt)} "
        f"raw_chars={len(raw_output)}"
    )
    return response


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        request_id: Any = None
        if len(line) > MAX_REQUEST_BYTES:
            response = _failure(request_id, "OversizeRequest",
                                "bridge request exceeds the size limit")
        else:
            try:
                request = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                response = _failure(None, "BridgeInputError",
                                    f"request is not valid JSON: {error}")
            else:
                server = self.server
                response = process_request(
                    request,
                    expected_token=server.expected_token,  # type: ignore[attr-defined]
                    backend=server.backend,  # type: ignore[attr-defined]
                )
        self.wfile.write(
            (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
        )
        self.wfile.flush()


class _Server(socketserver.TCPServer):
    allow_reuse_address = True
    timeout = 0.5

    def __init__(self, address, handler, *, expected_token: str, backend):
        self.expected_token = expected_token
        self.backend = backend
        super().__init__(address, handler)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Loopback planner bridge for the Kernel TaichuPlanningEngine"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--max-new-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--enable-thinking", action="store_true")
    parser.add_argument("--ready-file", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    token = os.environ.get(TOKEN_ENV, "")
    if not token.strip():
        _log(f"fatal: {TOKEN_ENV} must be set to a non-blank token")
        return 2
    if args.port < 0 or args.port > 65535:
        _log("fatal: --port is out of range")
        return 2

    backend = ZDTaichuServerBackend(
        timeout=float(args.timeout),
        max_new_tokens=int(args.max_new_tokens),
        temperature=0.0,
        enable_thinking=bool(args.enable_thinking),
        stop=None if args.enable_thinking else ["</think>"],
    )
    try:
        server = _Server(
            (args.host, args.port), _Handler,
            expected_token=token, backend=backend,
        )
    except OSError as error:
        _log(f"fatal: cannot bind {args.host}:{args.port}: {error}")
        return 2

    host, port = server.server_address[0], server.server_address[1]
    ready = {
        "status": "ready",
        "endpoint": f"{host}:{port}",
        "backend": "zdt-taichu-server",
        "model_endpoint": backend.endpoint,
        "max_new_tokens": backend.max_new_tokens,
        "temperature": backend.temperature,
        "enable_thinking": backend.enable_thinking,
    }
    if args.ready_file:
        try:
            Path(args.ready_file).write_text(
                json.dumps(ready, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as error:
            _log(f"fatal: cannot write ready file: {error}")
            server.server_close()
            return 2
    print(json.dumps(ready, ensure_ascii=False), flush=True)

    stop = False

    def _request_stop(_signum, _frame) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    _log(f"planner bridge ready at {host}:{port}")
    try:
        while not stop:
            server.handle_request()
    finally:
        server.server_close()
        _log("planner bridge stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
