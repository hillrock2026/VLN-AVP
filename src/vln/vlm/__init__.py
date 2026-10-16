"""VLN-AVP model-adapter package.

Public surface:

* :mod:`vln.vlm.model_client` - the replaceable model-call boundary
  (:class:`ModelClient`) and a deterministic :class:`MockModelClient` test
  double.
* :mod:`vln.vlm.zdtaichu_client` - the minimal adapter that implements
  :class:`ModelClient` over a lazily-loaded, injected ZDTaichu backend. No real
  model is loaded by importing it (the inference stack and Pillow are deferred).
* :mod:`vln.vlm.zdtaichu_backend` - the real :class:`InferenceBackend` over an
  injected ZDTaichu runtime (``from_messages`` -> ``generate`` -> strip prompt
  tokens -> ``batch_decode``). Its inference stack is imported only inside
  ``load_zdtaichu_runtime``, so importing it loads no model either.
* :mod:`vln.vlm.server_client` - the minimal client for the separately running,
  OpenAI-compatible local ZDTaichu service: it reuses that already-loaded model
  instead of loading a second copy, and still returns raw text only (optional
  key from the environment, loopback endpoint only, one attempt, no retries).

This package is the *only* place a model is invoked. It has no dependency on
the IPC layer, the host client or Agent-Kernel, and it does not parse model
output into an intent - that is :mod:`vln.intent`'s job. No real model is
integrated in this phase.
"""

from .model_client import ModelCallError, MockModelClient, ModelClient
from .server_client import (
    API_KEY_ENV,
    DEFAULT_SERVER_URL,
    ServerClientError,
    UnsupportedServerInputError,
    UntrustedEndpointError,
    ZDTaichuServerBackend,
)
from .zdtaichu_backend import (
    DEFAULT_DO_SAMPLE,
    DEFAULT_MAX_NEW_TOKENS,
    MODEL_ID,
    MODEL_REVISION,
    UntrustedImageInputError,
    ZDTaichuBackend,
    ZDTaichuRuntime,
    load_zdtaichu_runtime,
)
from .zdtaichu_client import (
    DefaultObservationEncoder,
    InferenceBackend,
    ObservationEncoder,
    PreparedObservation,
    UnsupportedObservationError,
    ZDTaichuModelClient,
)

__all__ = [
    "ModelCallError",
    "ModelClient",
    "MockModelClient",
    "PreparedObservation",
    "ObservationEncoder",
    "DefaultObservationEncoder",
    "InferenceBackend",
    "UnsupportedObservationError",
    "ZDTaichuModelClient",
    "MODEL_ID",
    "MODEL_REVISION",
    "DEFAULT_MAX_NEW_TOKENS",
    "DEFAULT_DO_SAMPLE",
    "ZDTaichuRuntime",
    "UntrustedImageInputError",
    "ZDTaichuBackend",
    "load_zdtaichu_runtime",
    "ZDTaichuServerBackend",
    "ServerClientError",
    "UntrustedEndpointError",
    "UnsupportedServerInputError",
    "DEFAULT_SERVER_URL",
    "API_KEY_ENV",
]
