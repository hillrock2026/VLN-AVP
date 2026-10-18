"""Minimal client for the locally running ZDTaichu OpenAI-compatible server.

Why this exists: the adapter in :mod:`vln.vlm.zdtaichu_backend` can only reach the
model by loading the full weights in-process, which a second instance must not do
while ``taichu_server`` already holds them. This module is the smallest way to
reuse that running service instead: it implements the existing
:class:`~vln.vlm.zdtaichu_client.InferenceBackend` shape
(``generate(PreparedObservation, instruction) -> str``), so it drops into
:class:`~vln.vlm.zdtaichu_client.ZDTaichuModelClient` and the existing
``parse_model_output`` chain with no refactor anywhere else.

It returns the assistant text **verbatim** and nothing else: it never repairs
JSON, never builds an ``AgentIntent``, never touches the host or IPC layer.

Safety boundaries (all fail closed, all before or instead of a network send):

* **Confirmed endpoint only.** The request goes to
  ``http://127.0.0.1:8100/v1/chat/completions``; any other scheme, host, port,
  path, query or fragment is refused at construction time.
* **Credential from the environment only.** The key is read from
  ``VLN_ZDTAICHU_API_KEY``, never from the server's process, its startup
  scripts, logs or the repository. The confirmed service is a loopback process
  the owner runs without authentication, so a missing or blank value is not an
  error: the request goes out with **no** ``Authorization`` header rather than
  with a placeholder, an empty ``Bearer`` or a fabricated value. When a key is
  configured it is sent as ``Bearer``, so an authenticated deployment keeps
  working unchanged.
* **The key never leaves memory.** The ``Authorization`` header is built
  in-process; error messages carry only a status code and the server's own
  ``error.message``, never the key or the header.
* **One attempt, no retry.** A timeout, 401, 5xx or malformed response raises
  :class:`ModelCallError` immediately; the call is never repeated.
* **No redirects.** A 3xx answer is a failure, not a hop. The default opener
  would follow it - rewriting the POST into a GET for 301/302/303 and copying
  the non-content headers, ``Authorization`` among them, onto a request to
  whatever host ``Location`` names - so this client posts through its own
  opener, whose redirect handler refuses instead of following.
* **Images by data URI only.** The server's ``load_image`` accepts a ``data:``
  URI, an ``http(s)://`` URL or a local path; the URL form would make the
  *server* fetch an address this repository never vetted, so
  :meth:`ZDTaichuServerBackend.generate_image` sends a ``data:`` URI built from
  a local file by :mod:`vln.vlm.image_input`. An observation carrying in-memory
  images stays refused on the text path rather than being sent malformed.

The service is never started, stopped, reconfigured or probed: this module only
performs the one POST the caller asks for.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlsplit

from .image_input import ImagePart, load_image_part
from .model_client import ModelCallError
from .zdtaichu_backend import _build_message_parts
from .zdtaichu_client import PreparedObservation

__all__ = [
    "API_KEY_ENV",
    "DEFAULT_SERVER_URL",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_NEW_TOKENS",
    "DEFAULT_TEMPERATURE",
    "CHAT_COMPLETIONS_PATH",
    "ServerClientError",
    "UntrustedEndpointError",
    "UnsupportedServerInputError",
    "ZDTaichuServerBackend",
    "build_image_messages",
]

#: Environment variable the owner injects the API key through. Nothing else is
#: accepted as a source for it. Setting it is optional: see
#: :func:`_optional_api_key`.
API_KEY_ENV = "VLN_ZDTAICHU_API_KEY"

#: The one endpoint this client is allowed to talk to (loopback, confirmed port).
_CONFIRMED_SCHEME = "http"
_CONFIRMED_HOST = "127.0.0.1"
_CONFIRMED_PORT = 8100
DEFAULT_SERVER_URL = f"{_CONFIRMED_SCHEME}://{_CONFIRMED_HOST}:{_CONFIRMED_PORT}"

#: The confirmed inference route of ``taichu_server``.
CHAT_COMPLETIONS_PATH = "/v1/chat/completions"

#: One request's timeout, in seconds. A real single-round generation on this
#: model is seconds; this is a generous upper bound, not a retry budget.
DEFAULT_TIMEOUT_SECONDS = 60.0

#: Bounded first-round generation and greedy decoding: the server's
#: ``gen_kwargs`` treats ``temperature == 0`` as ``do_sample=False``.
DEFAULT_MAX_NEW_TOKENS = 64
DEFAULT_TEMPERATURE = 0.0

#: Upper bound on a response body; the server answers with one JSON object.
_MAX_RESPONSE_BYTES = 1 << 20


class ServerClientError(ModelCallError):
    """The local inference server could not produce raw assistant text."""


class UntrustedEndpointError(ServerClientError):
    """The configured server URL is not the confirmed loopback endpoint."""


class UnsupportedServerInputError(ServerClientError):
    """The observation carries input the server path cannot represent."""


def _checked_endpoint(base_url: str) -> str:
    """Return the chat-completions URL, or refuse an unconfirmed base URL."""

    parts = urlsplit(base_url)
    try:
        port = parts.port
    except ValueError:
        port = None
    if (
        parts.scheme != _CONFIRMED_SCHEME
        or parts.hostname != _CONFIRMED_HOST
        or port != _CONFIRMED_PORT
    ):
        raise UntrustedEndpointError(
            "server client is restricted to "
            f"{DEFAULT_SERVER_URL} (got scheme={parts.scheme!r}, "
            f"host={parts.hostname!r}, port={port!r})"
        )
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise UntrustedEndpointError(
            "server client base URL must not carry a path, query or fragment"
        )
    return f"{DEFAULT_SERVER_URL}{CHAT_COMPLETIONS_PATH}"


def _optional_api_key(env_name: str) -> Optional[str]:
    """Return the configured key, or ``None`` when none is set.

    ``taichu_server`` skips authentication entirely when its own ``API_KEY`` is
    empty, which is how the owner runs the confirmed loopback service. An
    absent or blank value therefore means "send no ``Authorization`` header",
    not "refuse to send": no placeholder, empty ``Bearer`` or invented value is
    ever constructed in its place.
    """

    key = os.environ.get(env_name)
    if key is None or key.strip() == "":
        return None
    return key


def _build_payload(
    messages: list,
    *,
    model_name: Optional[str],
    max_new_tokens: int,
    temperature: float,
    enable_thinking: Optional[bool],
) -> bytes:
    """Serialise the confirmed ``ChatRequest`` fields for one request."""

    payload: dict = {
        "messages": messages,
        "stream": False,
        "max_tokens": int(max_new_tokens),
        "temperature": temperature,
    }
    if model_name is not None:
        payload["model"] = model_name
    if enable_thinking is not None:
        payload["enable_thinking"] = bool(enable_thinking)
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def build_image_messages(part: ImagePart, instruction: str) -> list:
    """Build the one user message carrying ``part`` and ``instruction``.

    The shape is the confirmed ``ChatRequest.messages`` vocabulary: a content
    list whose items are ``{"type": "image_url", "image_url": {"url": ...}}``
    and ``{"type": "text", "text": ...}``. The image is always first and the
    instruction second, so the instruction is never reordered away from the
    image it qualifies. Both parts are required: this entry point exists to send
    an image, so a blank instruction is refused rather than silently omitted.
    """

    if not isinstance(part, ImagePart):
        raise UnsupportedServerInputError(
            f"expected an ImagePart, got {type(part).__name__}"
        )
    if type(instruction) is not str or instruction.strip() == "":
        raise UnsupportedServerInputError(
            "instruction must be a non-blank str for an image request"
        )
    return [
        {
            "role": "user",
            "content": [part.content_part(), {"type": "text", "text": instruction}],
        }
    ]


def _server_error_message(exc: object) -> str:
    """Extract the server's own ``error.message``; never echo the request."""

    try:
        body = exc.read()  # type: ignore[attr-defined]
    except Exception:
        return "no response body"
    if not isinstance(body, (bytes, bytearray)):
        return "no response body"
    try:
        decoded = json.loads(body[:_MAX_RESPONSE_BYTES].decode("utf-8", "replace"))
        message = decoded["error"]["message"]
    except Exception:
        return "unparsable error body"
    return message if isinstance(message, str) else "unparsable error body"


class _RefuseRedirects(urlrequest.HTTPRedirectHandler):
    """Treat an HTTP redirect as a failed call instead of a hop to follow.

    Following a 3xx would issue a second request to a host the endpoint check
    never approved, carrying the ``Authorization`` header that the default
    :class:`~urllib.request.HTTPRedirectHandler` copies onto it. Refusing here
    keeps both the request count at one and the credential at one confirmed
    host; the status code is reported, no response body is echoed.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ServerClientError(
            f"inference server returned HTTP {code} redirect; refusing to "
            "follow it to an unconfirmed endpoint"
        )


#: The opener this module posts through: the same handler set as the default
#: one ``urlopen`` builds, except that :class:`_RefuseRedirects` replaces the
#: redirect handler.
_OPENER = urlrequest.build_opener(_RefuseRedirects())


def _post_once(
    endpoint: str, api_key: Optional[str], body: bytes, timeout: float
) -> dict:
    """Send exactly one POST through :data:`_OPENER` and decode its JSON object.

    Never retried and never redirected: a 3xx raises before any second request
    could be built. ``api_key`` is ``None`` when the owner configured none, in
    which case no ``Authorization`` header is added at all.
    """

    headers = {"Content-Type": "application/json"}
    if api_key is not None:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urlrequest.Request(
        endpoint,
        data=body,
        method="POST",
        headers=headers,
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except urlerror.HTTPError as exc:
        # `from None` keeps the request object (which holds the header) out of
        # the exception chain and out of any traceback a caller may print.
        raise ServerClientError(
            f"inference server returned HTTP {exc.code}: {_server_error_message(exc)}"
        ) from None
    except urlerror.URLError as exc:
        raise ServerClientError(
            f"could not reach the inference server: {exc.reason}"
        ) from None
    except TimeoutError:
        raise ServerClientError("inference request timed out") from None
    except OSError as exc:
        raise ServerClientError(
            f"inference request failed: {type(exc).__name__}"
        ) from None

    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ServerClientError("inference response exceeded the size cap")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except Exception:
        raise ServerClientError("inference response was not valid UTF-8 JSON") from None
    if not isinstance(decoded, dict):
        raise ServerClientError("inference response was not a JSON object")
    return decoded


def _assistant_content(payload: dict) -> str:
    """Return ``choices[0].message.content``, unmodified."""

    try:
        content = payload["choices"][0]["message"]["content"]
    except Exception:
        raise ServerClientError(
            "inference response has no choices[0].message.content"
        ) from None
    if type(content) is not str:
        raise ServerClientError(
            f"assistant content is {type(content).__name__}, expected str"
        )
    return content


@dataclass
class ZDTaichuServerBackend:
    """An :class:`InferenceBackend` over the already-running local server.

    ``generate`` builds the same message shape as the in-process adapter
    (:func:`vln.vlm.zdtaichu_backend._build_message_parts`), sends exactly one POST,
    and returns the assistant text verbatim. Every failure - input, transport,
    HTTP status, shape - becomes a :class:`ModelCallError` subclass; no retry is
    ever attempted.

    ``api_key_env`` names the environment variable the key is read from; it
    defaults to :data:`API_KEY_ENV`. When that variable is unset or blank the
    request carries no ``Authorization`` header at all, which is what the
    confirmed loopback service expects; when it is set the key is sent as
    ``Bearer``. ``model_name`` is omitted from the request unless set, so the
    server's own default applies instead of a name invented here.
    """

    base_url: str = DEFAULT_SERVER_URL
    api_key_env: str = API_KEY_ENV
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    enable_thinking: Optional[bool] = False
    model_name: Optional[str] = None
    _endpoint: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._endpoint = _checked_endpoint(self.base_url)

    @property
    def endpoint(self) -> str:
        """The only URL this backend will ever post to."""

        return self._endpoint

    def generate(self, observation: PreparedObservation, instruction: str) -> str:
        """Return the server's raw assistant text for this one request."""

        messages, images = _build_message_parts(observation, instruction)
        if images:
            raise UnsupportedServerInputError(
                "the server path cannot carry in-memory images: the server loads "
                "images from a URL/path/base64 string, which this client does not "
                "synthesise; send a text-only observation instead"
            )

        body = _build_payload(
            messages,
            model_name=self.model_name,
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
            enable_thinking=self.enable_thinking,
        )
        api_key = _optional_api_key(self.api_key_env)
        return _assistant_content(_post_once(self._endpoint, api_key, body, self.timeout))

    def generate_image(self, image_path: str, instruction: str) -> str:
        """Return the server's raw assistant text for one image + instruction.

        The image is read from ``image_path`` (a local file), validated and
        encoded by :func:`~vln.vlm.image_input.load_image_part`, and sent as a
        ``data:`` URI in the same message as the instruction. The result is the
        assistant text **verbatim** - no JSON repair, no intent, no execution.

        Every failure is a :class:`ServerClientError`: an unusable image
        (:class:`~vln.vlm.image_input.ImageInputError`), a blank instruction, an
        HTTP status, a timeout, or an unparsable response. As on the text path
        the call is made once and a redirect is refused rather than followed.
        """

        part = load_image_part(image_path)
        messages = build_image_messages(part, instruction)
        body = _build_payload(
            messages,
            model_name=self.model_name,
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
            enable_thinking=self.enable_thinking,
        )
        api_key = _optional_api_key(self.api_key_env)
        return _assistant_content(_post_once(self._endpoint, api_key, body, self.timeout))
