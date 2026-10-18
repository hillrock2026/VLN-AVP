"""Offline tests for the minimal local-server client.

Everything here is a fake: the module's POST opener is replaced, no socket is
opened to the inference server, no server is contacted, and the API key used is
a marker string that is asserted never to appear in any error message. The real
credential (``VLN_ZDTAICHU_API_KEY``) is never read.

The redirect tests are the one exception to "no socket": they stand up their
own throwaway loopback HTTP server (and a second one as the redirect target) so
the *real* opener is exercised. Nothing outside ``127.0.0.1`` is contacted.

The tests pin the boundaries that make a single real request safe: the endpoint
is fixed, a configured credential is sent as ``Bearer`` while an unconfigured
one sends no ``Authorization`` header at all (never a placeholder), the request
carries the confirmed fields, the assistant text is returned verbatim, a 3xx is
a failed call rather than a hop, and 401/timeout/error responses fail closed
with exactly one attempt.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import HTTPRedirectHandler

import pytest

from vln.intent import ModelOutputParseError, parse_model_output
from vln.vlm import server_client as server_client_module
from vln.vlm.image_input import (
    ImageInputError,
    UnsupportedImageFormatError,
    load_image_part,
)
from vln.vlm.model_client import ModelCallError
from vln.vlm.server_client import (
    CHAT_COMPLETIONS_PATH,
    DEFAULT_SERVER_URL,
    API_KEY_ENV,
    ServerClientError,
    UnsupportedServerInputError,
    UntrustedEndpointError,
    ZDTaichuServerBackend,
)
from vln.vlm.zdtaichu_client import InferenceBackend, PreparedObservation

#: A marker, not a credential: every test asserts it never leaks.
_FAKE_KEY = "test-marker-key-not-a-real-credential"
_ENV = "VLN_TEST_ZDTAICHU_KEY"

_VALID_TEXT = (
    '{"contract_version":"1","intent_id":"intent-05b","action":"parking.move",'
    '"target":{"x":1.5,"y":-2.25,"heading":0.5}}'
)


class _Response:
    """Stands in for the ``urlopen`` context manager."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self, limit: int | None = None) -> bytes:
        return self._body if limit is None else self._body[:limit]

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _Urlopen:
    """Records calls and returns a scripted result; never touches the network."""

    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.calls: list = []

    def __call__(self, request, timeout=None):
        self.calls.append({"request": request, "timeout": timeout})
        if self._error is not None:
            raise self._error
        return self._result


def _chat_response(content: str, **extra: object) -> bytes:
    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "ZDTaichu5.0-9B",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        **extra,
    }
    return json.dumps(payload).encode("utf-8")


@pytest.fixture()
def fake_urlopen(monkeypatch):
    def _install(result: object = None, error: Exception | None = None) -> _Urlopen:
        opener = _Urlopen(result=result, error=error)
        # The client posts through its own no-redirect opener; replacing that
        # opener's ``open`` keeps every socket out of these tests.
        monkeypatch.setattr(server_client_module._OPENER, "open", opener)
        return opener

    return _install


@pytest.fixture()
def with_key(monkeypatch):
    monkeypatch.setenv(_ENV, _FAKE_KEY)


def _backend(**kwargs) -> ZDTaichuServerBackend:
    kwargs.setdefault("api_key_env", _ENV)
    return ZDTaichuServerBackend(**kwargs)


# ----------------------------------------------------------------------
# Loopback HTTP doubles: the only place in this file that opens a socket,
# and only ever on 127.0.0.1 with an ephemeral port
# ----------------------------------------------------------------------


class _RecordingHandler(BaseHTTPRequestHandler):
    """Answers every request with the scripted status/body and records it."""

    def _respond(self) -> None:
        self.server.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
            }
        )
        body = self.server.body
        self.send_response(self.server.status)
        for name, value in self.server.extra_headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass  # the client dropped the connection after reading the status

    do_GET = _respond
    do_POST = _respond

    def log_message(self, format: str, *args: object) -> None:
        pass


class _LocalHttpServer(ThreadingHTTPServer):
    """A throwaway loopback server with a scripted answer and a request log."""

    daemon_threads = True
    status = 200
    body = b"{}"
    extra_headers: tuple = ()

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _RecordingHandler)
        self.requests: list = []

    @property
    def base_url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"


@pytest.fixture()
def loopback_server():
    """Start throwaway loopback servers and shut them down afterwards."""

    started: list = []

    def _start(**attribute: object) -> _LocalHttpServer:
        server = _LocalHttpServer()
        for name, value in attribute.items():
            setattr(server, name, value)
        started.append(server)
        threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()
        return server

    yield _start

    for server in started:
        server.shutdown()
        server.server_close()


def _backend_at(url: str, **kwargs) -> ZDTaichuServerBackend:
    """Point a validated backend's transport at a loopback double.

    Construction still runs the confirmed-endpoint check; only the URL the
    transport posts to is overridden, so a real socket write happens without a
    server ever being bound on the confirmed port.
    """

    backend = _backend(**kwargs)
    backend._endpoint = f"{url}{CHAT_COMPLETIONS_PATH}"
    return backend


# ----------------------------------------------------------------------
# Credential handling: no configured key means no Authorization header at all
# ----------------------------------------------------------------------


def _auth_header_of(request) -> object:
    """Return the request's Authorization header, or ``None`` if it has none."""

    headers = {name.lower(): value for name, value in request.header_items()}
    return headers.get("authorization")


def test_no_credential_still_sends_the_request_without_an_auth_header(
    fake_urlopen, monkeypatch
) -> None:
    """The confirmed loopback service needs no key: send, but never fake one."""

    monkeypatch.delenv(_ENV, raising=False)
    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    raw = _backend().generate(PreparedObservation(text="scene"), "park")

    assert raw == _VALID_TEXT
    (call,) = opener.calls
    assert _auth_header_of(call["request"]) is None


def test_blank_credential_is_treated_as_unset(fake_urlopen, monkeypatch) -> None:
    monkeypatch.setenv(_ENV, "   ")
    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    raw = _backend().generate(PreparedObservation(text="scene"), "park")

    assert raw == _VALID_TEXT
    (call,) = opener.calls
    assert _auth_header_of(call["request"]) is None


def test_configured_credential_is_still_sent_as_bearer(fake_urlopen, with_key) -> None:
    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    _backend().generate(PreparedObservation(text="scene"), "park")

    (call,) = opener.calls
    assert _auth_header_of(call["request"]) == f"Bearer {_FAKE_KEY}"


def test_no_credential_never_becomes_a_placeholder_or_an_empty_bearer(
    fake_urlopen, monkeypatch
) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    _backend().generate(PreparedObservation(text="scene"), "park")

    rendered = repr(opener.calls[0]["request"].header_items())
    assert "authorization" not in rendered.lower()
    assert "Bearer" not in rendered
    assert "None" not in rendered


def test_default_credential_variable_is_the_owner_injected_name() -> None:
    assert API_KEY_ENV == "VLN_ZDTAICHU_API_KEY"
    assert ZDTaichuServerBackend().api_key_env == API_KEY_ENV


# ----------------------------------------------------------------------
# Endpoint restriction
# ----------------------------------------------------------------------


def test_endpoint_is_the_confirmed_loopback_route() -> None:
    backend = _backend()
    assert DEFAULT_SERVER_URL == "http://127.0.0.1:8100"
    assert backend.endpoint == f"{DEFAULT_SERVER_URL}{CHAT_COMPLETIONS_PATH}"
    assert backend.endpoint == "http://127.0.0.1:8100/v1/chat/completions"


@pytest.mark.parametrize(
    "url",
    [
        "http://0.0.0.0:8100",
        "http://localhost:8100",
        "http://127.0.0.1:8101",
        "http://127.0.0.1:8000",
        "https://127.0.0.1:8100",
        "http://192.168.1.10:8100",
        "http://127.0.0.1:8100/other/path",
        "http://127.0.0.1:8100/?x=1",
    ],
)
def test_other_endpoints_are_refused(url: str) -> None:
    with pytest.raises(UntrustedEndpointError):
        ZDTaichuServerBackend(base_url=url)


# ----------------------------------------------------------------------
# Request construction
# ----------------------------------------------------------------------


def test_request_uses_the_confirmed_contract_and_returns_raw_content(
    fake_urlopen, with_key
) -> None:
    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    raw = _backend().generate(
        PreparedObservation(text="a parking-lot scene with slot P-07"), "drive to P-07"
    )
    assert raw == _VALID_TEXT

    (call,) = opener.calls
    request = call["request"]
    assert request.get_full_url() == "http://127.0.0.1:8100/v1/chat/completions"
    assert request.get_method() == "POST"
    assert call["timeout"] == ZDTaichuServerBackend().timeout

    payload = json.loads(request.data.decode("utf-8"))
    assert payload["stream"] is False
    assert payload["max_tokens"] == ZDTaichuServerBackend().max_new_tokens
    assert payload["temperature"] == 0.0
    assert payload["enable_thinking"] is False
    assert "model" not in payload  # the server's own default applies
    (message,) = payload["messages"]
    assert message["role"] == "user"
    assert message["content"][-1]["type"] == "text"
    assert "P-07" in message["content"][-1]["text"]


def test_thinking_and_model_name_are_configurable(fake_urlopen, with_key) -> None:
    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    _backend(enable_thinking=True, model_name="ZDTaichu5.0-9B").generate(
        PreparedObservation(text="scene"), "park"
    )
    payload = json.loads(opener.calls[0]["request"].data.decode("utf-8"))
    assert payload["enable_thinking"] is True
    assert payload["model"] == "ZDTaichu5.0-9B"


def test_empty_input_is_rejected_before_any_request(fake_urlopen, with_key) -> None:
    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    with pytest.raises(ModelCallError, match="empty ZDTaichu input"):
        _backend().generate(PreparedObservation(text=""), "")
    assert opener.calls == []


def test_image_observation_is_refused_before_any_request(fake_urlopen, with_key) -> None:
    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    with pytest.raises(UnsupportedServerInputError):
        _backend().generate(
            PreparedObservation(text="scene", images=(object(),)), "park"
        )
    assert opener.calls == []


# ----------------------------------------------------------------------
# Failure handling: fail closed, exactly one attempt, no leakage
# ----------------------------------------------------------------------


def test_http_401_fails_closed_with_one_attempt(fake_urlopen, with_key) -> None:
    from urllib.error import HTTPError

    error = HTTPError(
        "http://127.0.0.1:8100/v1/chat/completions",
        401,
        "Unauthorized",
        {},
        None,
    )
    opener = fake_urlopen(error=error)
    with pytest.raises(ServerClientError, match="HTTP 401"):
        _backend().generate(PreparedObservation(text="scene"), "park")
    assert len(opener.calls) == 1


def test_timeout_fails_closed_with_one_attempt(fake_urlopen, with_key) -> None:
    opener = fake_urlopen(error=TimeoutError("timed out"))
    with pytest.raises(ServerClientError, match="timed out"):
        _backend().generate(PreparedObservation(text="scene"), "park")
    assert len(opener.calls) == 1


def test_transport_error_fails_closed_with_one_attempt(fake_urlopen, with_key) -> None:
    from urllib.error import URLError

    opener = fake_urlopen(error=URLError(ConnectionRefusedError(111, "refused")))
    with pytest.raises(ServerClientError):
        _backend().generate(PreparedObservation(text="scene"), "park")
    assert len(opener.calls) == 1


def test_server_error_body_message_is_surfaced_without_the_request(
    fake_urlopen, with_key
) -> None:
    from urllib.error import HTTPError
    import io

    body = json.dumps({"error": {"message": "invalid request", "type": "bad_request"}})
    error = HTTPError(
        "http://127.0.0.1:8100/v1/chat/completions",
        400,
        "Bad Request",
        {},
        io.BytesIO(body.encode("utf-8")),
    )
    fake_urlopen(error=error)
    with pytest.raises(ServerClientError) as excinfo:
        _backend().generate(PreparedObservation(text="scene"), "park")
    assert "invalid request" in str(excinfo.value)


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[1, 2, 3]",
        json.dumps({"choices": []}).encode("utf-8"),
        json.dumps({"choices": [{"message": {"content": 42}}]}).encode("utf-8"),
    ],
)
def test_malformed_responses_fail_closed(fake_urlopen, with_key, body: bytes) -> None:
    opener = fake_urlopen(result=_Response(body))
    with pytest.raises(ServerClientError):
        _backend().generate(PreparedObservation(text="scene"), "park")
    assert len(opener.calls) == 1


def test_errors_never_leak_the_credential_or_the_auth_header(
    fake_urlopen, with_key
) -> None:
    from urllib.error import HTTPError

    error = HTTPError("http://127.0.0.1:8100/v1/chat/completions", 401, "Unauthorized", {}, None)
    opener = fake_urlopen(error=error)
    with pytest.raises(ModelCallError) as excinfo:
        _backend().generate(PreparedObservation(text="scene"), "park")

    rendered = f"{excinfo.value!r} {excinfo.value} {excinfo.value.args!r}"
    assert _FAKE_KEY not in rendered
    assert "Bearer" not in rendered
    assert "Authorization" not in rendered

    sent = opener.calls[0]["request"].header_items()
    headers = {name.lower(): value for name, value in sent}
    assert headers["authorization"] == f"Bearer {_FAKE_KEY}"


def test_client_never_retries_after_a_failure(fake_urlopen, with_key) -> None:
    from urllib.error import HTTPError

    opener = fake_urlopen(error=HTTPError("http://127.0.0.1:8100/v1/chat/completions", 500, "Server Error", {}, None))
    for _attempt in range(3):
        with pytest.raises(ServerClientError):
            _backend().generate(PreparedObservation(text="scene"), "park")
    # Three explicit calls made by the caller -> three sends, never more.
    assert len(opener.calls) == 3


# ----------------------------------------------------------------------
# Boundary with the existing abstraction and parser
# ----------------------------------------------------------------------


def test_backend_satisfies_the_inference_backend_protocol() -> None:
    assert isinstance(_backend(), InferenceBackend)


def test_raw_output_is_handed_to_the_existing_parser_unchanged(
    fake_urlopen, with_key
) -> None:
    """A thinking-prefixed answer must still be rejected: no repair anywhere."""

    opener = fake_urlopen(
        result=_Response(_chat_response("<think>\nhmm\n</think>\n" + _VALID_TEXT))
    )
    raw = _backend().generate(PreparedObservation(text="scene"), "park")
    assert raw.startswith("<think>")  # returned verbatim
    with pytest.raises(ModelOutputParseError):
        parse_model_output(raw)
    assert len(opener.calls) == 1


def test_a_clean_answer_parses_through_the_existing_chain(fake_urlopen, with_key) -> None:
    fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    raw = _backend().generate(PreparedObservation(text="scene"), "park")
    intent = parse_model_output(raw)
    assert intent.intent_id == "intent-05b"
    assert intent.action == "parking.move"
    assert intent.target.x == 1.5


def test_module_import_pulls_in_no_model_stack_or_http_client_at_import() -> None:
    """Importing the client must not import torch/transformers or open sockets."""

    import subprocess
    import sys

    code = (
        "import sys, vln.vlm.server_client as m;"
        "bad=[x for x in ('torch','transformers') if x in sys.modules];"
        "assert not bad, bad;"
        "assert 'vln.client' not in sys.modules;"
        "assert callable(m.ZDTaichuServerBackend)"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2] / "src"),
    )
    assert result.returncode == 0, result.stderr


# ----------------------------------------------------------------------
# HTTP redirects: a 3xx is a failed call, never a hop
# ----------------------------------------------------------------------


def test_opener_replaces_the_following_redirect_handler() -> None:
    """The module posts through an opener that cannot follow a 3xx."""

    redirect_handlers = [
        handler
        for handler in server_client_module._OPENER.handlers
        if isinstance(handler, HTTPRedirectHandler)
    ]
    assert [type(handler) for handler in redirect_handlers] == [
        server_client_module._RefuseRedirects
    ]


def test_redirect_handler_refuses_instead_of_offering_a_new_request() -> None:
    handler = server_client_module._RefuseRedirects()
    with pytest.raises(ServerClientError, match="redirect"):
        handler.redirect_request(
            object(),
            object(),
            302,
            "Found",
            {"location": "http://127.0.0.1:9/v1/chat/completions"},
            "http://127.0.0.1:9/v1/chat/completions",
        )


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_fails_the_call_and_never_reaches_the_target(
    loopback_server, with_key, status: int
) -> None:
    target = loopback_server(status=200, body=_chat_response(_VALID_TEXT))
    origin = loopback_server(
        status=status,
        body=b"",
        extra_headers=(("Location", f"{target.base_url}{CHAT_COMPLETIONS_PATH}"),),
    )

    with pytest.raises(ServerClientError) as excinfo:
        _backend_at(origin.base_url).generate(PreparedObservation(text="scene"), "park")

    message = f"{excinfo.value!r} {excinfo.value}"
    assert f"HTTP {status}" in message
    assert "redirect" in message
    assert _FAKE_KEY not in message
    assert "Bearer" not in message

    # Exactly one request, to the confirmed origin, and nothing to the target.
    assert [record["method"] for record in origin.requests] == ["POST"]
    assert origin.requests[0]["authorization"] == f"Bearer {_FAKE_KEY}"
    assert target.requests == []


def test_redirect_target_receives_no_request_and_no_authorization_header(
    loopback_server, with_key
) -> None:
    """Both doubles are live; only the origin ever sees the credential."""

    target = loopback_server(status=200, body=_chat_response(_VALID_TEXT))
    origin = loopback_server(
        status=302, body=b"", extra_headers=(("Location", target.base_url),)
    )

    with pytest.raises(ServerClientError):
        _backend_at(origin.base_url).generate(PreparedObservation(text="scene"), "park")

    assert target.requests == []
    assert len(origin.requests) == 1

    # Non-vacuity: the target double does record what it is sent, so the empty
    # log above means "never contacted", not "never observed".
    _backend_at(target.base_url).generate(PreparedObservation(text="scene"), "park")
    assert [record["authorization"] for record in target.requests] == [
        f"Bearer {_FAKE_KEY}"
    ]


def test_a_normal_response_still_travels_over_a_real_socket(
    loopback_server, with_key
) -> None:
    origin = loopback_server(status=200, body=_chat_response(_VALID_TEXT))
    raw = _backend_at(origin.base_url).generate(
        PreparedObservation(text="scene"), "park"
    )
    assert raw == _VALID_TEXT
    assert [record["method"] for record in origin.requests] == ["POST"]
    assert origin.requests[0]["path"] == CHAT_COMPLETIONS_PATH


def test_an_error_response_still_fails_closed_over_a_real_socket(
    loopback_server, with_key
) -> None:
    body = json.dumps({"error": {"message": "invalid request"}}).encode("utf-8")
    origin = loopback_server(status=401, body=body)

    with pytest.raises(ServerClientError, match="HTTP 401") as excinfo:
        _backend_at(origin.base_url).generate(PreparedObservation(text="scene"), "park")

    assert "invalid request" in str(excinfo.value)
    assert len(origin.requests) == 1


def test_no_credential_reaches_a_live_server_without_an_auth_header(
    loopback_server, monkeypatch
) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    origin = loopback_server(status=200, body=_chat_response(_VALID_TEXT))

    raw = _backend_at(origin.base_url).generate(
        PreparedObservation(text="scene"), "park"
    )

    assert raw == _VALID_TEXT
    assert [record["method"] for record in origin.requests] == ["POST"]
    assert origin.requests[0]["authorization"] is None


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_are_never_treated_as_success(
    loopback_server, monkeypatch, status: int
) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    body = json.dumps({"error": {"message": "Invalid API key"}}).encode("utf-8")
    origin = loopback_server(status=status, body=body)

    with pytest.raises(ServerClientError, match=f"HTTP {status}") as excinfo:
        _backend_at(origin.base_url).generate(PreparedObservation(text="scene"), "park")

    rendered = f"{excinfo.value!r} {excinfo.value}"
    assert "Invalid API key" in rendered  # the server's own message, nothing else
    assert "authorization" not in rendered.lower()
    assert "Bearer" not in rendered
    assert len(origin.requests) == 1


def test_redirect_is_refused_without_a_credential_too(
    loopback_server, monkeypatch
) -> None:
    """307 keeps method and headers, so it is the code that would leak most."""

    monkeypatch.delenv(_ENV, raising=False)
    target = loopback_server(status=200, body=_chat_response(_VALID_TEXT))
    origin = loopback_server(
        status=307, body=b"", extra_headers=(("Location", target.base_url),)
    )

    with pytest.raises(ServerClientError, match="redirect"):
        _backend_at(origin.base_url).generate(PreparedObservation(text="scene"), "park")

    assert len(origin.requests) == 1
    assert origin.requests[0]["authorization"] is None
    assert target.requests == []


# ----------------------------------------------------------------------
# Multimodal requests: one image file plus the instruction
# ----------------------------------------------------------------------

#: A genuinely valid 1x1 PNG; the request assertions decode it back out.
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)
_INSTRUCTION = "drive to slot P07"


@pytest.fixture()
def png_file(tmp_path):
    path = tmp_path / "frame.png"
    path.write_bytes(_PNG_BYTES)
    return path


def _image_payload(opener) -> dict:
    (call,) = opener.calls
    return json.loads(call["request"].data.decode("utf-8"))


def test_image_request_carries_both_the_image_and_the_instruction(
    fake_urlopen, with_key, png_file
) -> None:
    """The core property: one request holds the image *and* the instruction."""

    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    raw = _backend().generate_image(str(png_file), _INSTRUCTION)
    assert raw == _VALID_TEXT

    payload = _image_payload(opener)
    (message,) = payload["messages"]
    assert message["role"] == "user"
    image_part, text_part = message["content"]
    assert image_part["type"] == "image_url"
    assert text_part == {"type": "text", "text": _INSTRUCTION}

    # The image really is in the body: MIME prefix plus the exact file bytes.
    url = image_part["image_url"]["url"]
    prefix = "data:image/png;base64,"
    assert url.startswith(prefix)
    assert base64.b64decode(url[len(prefix):]) == _PNG_BYTES


def test_image_request_uses_the_confirmed_contract_fields(
    fake_urlopen, with_key, png_file
) -> None:
    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    _backend(enable_thinking=True, model_name="ZDTaichu5.0-9B", max_new_tokens=256).generate_image(
        str(png_file), _INSTRUCTION
    )
    payload = _image_payload(opener)

    assert payload["stream"] is False
    assert payload["max_tokens"] == 256
    assert payload["temperature"] == 0.0
    assert payload["enable_thinking"] is True
    assert payload["model"] == "ZDTaichu5.0-9B"
    assert set(payload["messages"][0]) == {"role", "content"}


def test_image_request_sends_no_image_url_over_the_network(
    fake_urlopen, with_key, png_file
) -> None:
    """The server must never be handed a URL it would fetch itself."""

    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    _backend().generate_image(str(png_file), _INSTRUCTION)

    url = _image_payload(opener)["messages"][0]["content"][0]["image_url"]["url"]
    assert url.startswith("data:")
    assert "http://" not in url and "https://" not in url
    # A bare path would make ``load_image`` read from the server's filesystem.
    assert not url.startswith("/")


def test_image_request_keeps_the_credential_rules(fake_urlopen, monkeypatch, png_file) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    raw = _backend().generate_image(str(png_file), _INSTRUCTION)

    assert raw == _VALID_TEXT
    assert _auth_header_of(opener.calls[0]["request"]) is None


def test_image_output_is_handed_to_the_existing_chain(
    fake_urlopen, with_key, png_file
) -> None:
    """One image round reuses the text chain unchanged: raw text -> AgentIntent."""

    fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    raw = _backend().generate_image(str(png_file), _INSTRUCTION)

    intent = parse_model_output(raw)
    assert intent.action == "parking.move"
    assert intent.target.y == -2.25
    assert json.loads(intent.to_payload())["target"].keys() == {"x", "y", "heading"}


def test_a_thinking_prefixed_image_answer_is_not_repaired(
    fake_urlopen, with_key, png_file
) -> None:
    fake_urlopen(
        result=_Response(_chat_response("<think>\nlooking\n</think>\n" + _VALID_TEXT))
    )
    raw = _backend().generate_image(str(png_file), _INSTRUCTION)
    with pytest.raises(ModelOutputParseError):
        parse_model_output(raw)
    assert raw.startswith("<think>")


def test_a_non_json_image_answer_fails_the_parse_boundary(
    fake_urlopen, with_key, png_file
) -> None:
    fake_urlopen(result=_Response(_chat_response("I cannot see slot P07 in this image.")))
    raw = _backend().generate_image(str(png_file), _INSTRUCTION)
    assert raw == "I cannot see slot P07 in this image."
    with pytest.raises(ModelOutputParseError):
        parse_model_output(raw)


def test_an_empty_image_answer_parses_to_nothing_rather_than_being_invented(
    fake_urlopen, with_key, png_file
) -> None:
    """The model's explicit abstention stays an empty string, never a target."""

    fake_urlopen(result=_Response(_chat_response("")))
    raw = _backend().generate_image(str(png_file), _INSTRUCTION)
    assert raw == ""
    with pytest.raises(ModelOutputParseError):
        parse_model_output(raw)


def test_missing_image_file_fails_before_any_request(fake_urlopen, with_key, tmp_path) -> None:
    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    with pytest.raises(ImageInputError, match="does not exist"):
        _backend().generate_image(str(tmp_path / "absent.png"), _INSTRUCTION)
    assert opener.calls == []


def test_unsupported_image_file_fails_before_any_request(
    fake_urlopen, with_key, tmp_path
) -> None:
    path = tmp_path / "notes.png"  # the name lies; the content decides
    path.write_bytes(b"this is not an image")
    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    with pytest.raises(UnsupportedImageFormatError):
        _backend().generate_image(str(path), _INSTRUCTION)
    assert opener.calls == []


def test_blank_instruction_fails_before_any_request(fake_urlopen, with_key, png_file) -> None:
    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    with pytest.raises(UnsupportedServerInputError, match="non-blank str"):
        _backend().generate_image(str(png_file), "   ")
    assert opener.calls == []


def test_image_http_error_fails_closed_with_one_attempt(fake_urlopen, with_key, png_file) -> None:
    from urllib.error import HTTPError

    opener = fake_urlopen(
        error=HTTPError(
            "http://127.0.0.1:8100/v1/chat/completions",
            400,
            "Bad Request",
            {},
            None,
        )
    )
    with pytest.raises(ServerClientError, match="HTTP 400"):
        _backend().generate_image(str(png_file), _INSTRUCTION)
    assert len(opener.calls) == 1


def test_image_timeout_fails_closed_with_one_attempt(fake_urlopen, with_key, png_file) -> None:
    opener = fake_urlopen(error=TimeoutError("timed out"))
    with pytest.raises(ServerClientError, match="timed out"):
        _backend().generate_image(str(png_file), _INSTRUCTION)
    assert len(opener.calls) == 1


def test_malformed_image_responses_fail_closed(fake_urlopen, with_key, png_file) -> None:
    opener = fake_urlopen(result=_Response(b'{"choices":[{"message":{"content":7}}]}'))
    with pytest.raises(ServerClientError, match="expected str"):
        _backend().generate_image(str(png_file), _INSTRUCTION)
    assert len(opener.calls) == 1


def test_image_errors_never_leak_the_credential(fake_urlopen, with_key, png_file) -> None:
    from urllib.error import HTTPError

    fake_urlopen(
        error=HTTPError(
            "http://127.0.0.1:8100/v1/chat/completions", 401, "Unauthorized", {}, None
        )
    )
    with pytest.raises(ModelCallError) as excinfo:
        _backend().generate_image(str(png_file), _INSTRUCTION)

    rendered = f"{excinfo.value!r} {excinfo.value} {excinfo.value.args!r}"
    assert _FAKE_KEY not in rendered
    assert "Bearer" not in rendered


def test_image_request_still_posts_to_the_confirmed_endpoint(
    fake_urlopen, with_key, png_file
) -> None:
    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    _backend().generate_image(str(png_file), _INSTRUCTION)

    request = opener.calls[0]["request"]
    assert request.get_full_url() == "http://127.0.0.1:8100/v1/chat/completions"
    assert request.get_method() == "POST"


def test_image_request_is_refused_by_an_unconfirmed_endpoint(
    fake_urlopen, with_key, png_file
) -> None:
    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    with pytest.raises(UntrustedEndpointError):
        ZDTaichuServerBackend(base_url="http://192.168.1.10:8100").generate_image(
            str(png_file), _INSTRUCTION
        )
    assert opener.calls == []


def test_the_text_path_still_refuses_in_memory_images(fake_urlopen, with_key, png_file) -> None:
    """Adding the image entry point must not loosen the text entry point."""

    opener = fake_urlopen(result=_Response(_chat_response(_VALID_TEXT)))
    with pytest.raises(UnsupportedServerInputError):
        _backend().generate(PreparedObservation(text="scene", images=(object(),)), "park")
    assert opener.calls == []


def test_the_four_repository_images_are_all_loadable() -> None:
    """The owner-supplied frames this entry point exists to send."""

    images = sorted((Path(__file__).resolve().parents[2] / "images").glob("*.png"))
    assert len(images) == 4
    for path in images:
        part = load_image_part(path)
        assert part.media_type == "image/png"
        assert part.content_part()["image_url"]["url"].startswith("data:image/png;base64,")
