"""Minimal, injectable application composition for the simulated VLN-AVP loop.

This is the **composition root** the Intelligence side previously lacked: it
wires the existing pieces into one runnable application without re-implementing
any of them. It owns *assembly only* - the loop, the model-output parser, the
``AgentIntent`` validator, the IPC request builder, the host client and the
feedback encoding all stay the responsibility of their existing modules:

    ZDTaichuModelClient(backend_factory=..., encoder=CompositeObservationEncoder())
      -> run_parking_loop
           -> parse_model_output / AgentIntent      (vln.intent)
           -> build_request                          (vln.client)
           -> HostClient -> kernel_host subprocess   (vln.client / runtime_host)
           -> Response -> CompositeObservationEncoder -> next round

Importing this module has **no** side effects: it loads no model, opens no
network connection and starts no host process. The inference backend and the
host client factory are both injected, so the application can be built and run
offline with a fake backend - a passing run proves the *simulated* chain only,
never real ZDTaichu5.0-9B inference, real vision or a real vehicle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from vln.client import HostClient, build_request
from vln.ipc.envelope import Request
from vln.observation import CompositeObservationEncoder
from vln.pipeline import DEFAULT_MAX_ROUNDS, ParkingLoopResult, run_parking_loop
from vln.vlm import InferenceBackend, ZDTaichuModelClient

__all__ = [
    "SimulatedVlnApp",
    "build_simulated_loop",
    "default_request_id_factory",
]


def default_request_id_factory(round_index: int) -> str:
    """The IPC correlation id for ``round_index`` (independent of intent_id)."""

    return f"vln-sim-req-{round_index + 1}"


@dataclass
class SimulatedVlnApp:
    """A composed, injectable simulated VLN-AVP application.

    It holds the assembled collaborators and exposes :meth:`run`. It adds no
    lifecycle framework of its own: :func:`~vln.pipeline.run_parking_loop`
    already opens and closes one host client per round via the context manager,
    so each round's host process is reaped by the existing client.
    """

    model: ZDTaichuModelClient
    host_client_factory: Callable[[], HostClient]
    instruction: str
    max_rounds: int = DEFAULT_MAX_ROUNDS
    request_id_factory: Callable[[int], str] = default_request_id_factory
    request_builder: Callable[..., Request] = build_request

    @property
    def encoder(self) -> CompositeObservationEncoder:
        """The observation encoder this application injected into its model."""

        return self.model.encoder  # type: ignore[return-value]

    def run(self, observation: object) -> ParkingLoopResult:
        """Run the multi-round simulated loop for ``observation``."""

        return run_parking_loop(
            model=self.model,
            observation=observation,
            instruction=self.instruction,
            host_client_factory=self.host_client_factory,
            request_id_factory=self.request_id_factory,
            max_rounds=self.max_rounds,
            request_builder=self.request_builder,
        )


def build_simulated_loop(
    *,
    backend_factory: Callable[[], InferenceBackend],
    host_client_factory: Callable[[], HostClient],
    instruction: str,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    request_id_factory: Callable[[int], str] = default_request_id_factory,
    request_builder: Callable[..., Request] = build_request,
) -> SimulatedVlnApp:
    """Assemble the simulated loop, explicitly injecting the composite encoder.

    ``backend_factory`` is called lazily (at most once, on the first model
    call) by :class:`~vln.vlm.ZDTaichuModelClient`, so building the application
    loads no model. The observation encoder is created here and injected into
    the model, so the assembled application - not a test - is what selects
    :class:`~vln.observation.CompositeObservationEncoder`.
    """

    encoder = CompositeObservationEncoder()
    model = ZDTaichuModelClient(
        backend_factory=backend_factory,
        encoder=encoder,
    )
    return SimulatedVlnApp(
        model=model,
        host_client_factory=host_client_factory,
        instruction=instruction,
        max_rounds=max_rounds,
        request_id_factory=request_id_factory,
        request_builder=request_builder,
    )
