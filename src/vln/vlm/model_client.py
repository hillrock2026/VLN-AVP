"""The model-call boundary: model input -> raw model text.

This module defines the *replaceable* seam between the Intelligence side and a
vision-language model. It is deliberately tiny and has **no** dependency on the
IPC layer, the host client or Agent-Kernel: a model client only turns an
observation and an instruction into the *raw text* the model returned. It does
**not** parse that text, does **not** build an intent and does **not** submit
anything.

No real model is loaded or called here. ``MockModelClient`` is a deterministic
test double that returns caller-supplied text: it is explicitly a MOCK and
claims no visual understanding whatsoever. A real ZDTaichu5.0-9B client is a
later-phase implementation of :class:`ModelClient`; nothing in this module
downloads weights, reads the network, or requires a GPU.

The contract for implementations:

* :meth:`ModelClient.generate` returns the model's raw output text verbatim;
* a failure to obtain that text is raised as :class:`ModelCallError` (or is
  allowed to propagate) - it must never be replaced by fabricated valid text,
  because a fabricated success would defeat the fail-closed parse boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = ["ModelCallError", "ModelClient", "MockModelClient"]


class ModelCallError(Exception):
    """A model client failed to produce raw output text.

    Raised (or allowed to propagate) when the underlying model/service cannot
    be reached, times out, or errors. It carries no fabricated text: callers
    must treat a model failure as a failure, never as a valid model output.
    """


@runtime_checkable
class ModelClient(Protocol):
    """The replaceable model-call boundary.

    ``observation`` is intentionally an opaque placeholder for now: no formal
    sensor or image type is frozen in this phase, so the boundary stays minimal
    rather than inventing a sensor abstraction. ``instruction`` is the natural
    language task/command. The return value is the model's raw text and is the
    *only* contract this layer fixes.
    """

    def generate(self, observation: object, instruction: str) -> str:
        """Return the raw text produced for ``observation`` + ``instruction``."""
        ...


@dataclass
class MockModelClient:
    """A deterministic MOCK model client that returns caller-supplied text.

    This is a test double, not a model: it performs no inference, loads no
    weights, performs no I/O, and makes no claim to understand the observation.
    It lets tests drive the exact raw text a real model might return, including
    intentionally malformed text, so the parse/validation boundary can be
    exercised deterministically.

    Attributes:
        output: the exact text every :meth:`generate` call returns.
        call_count: number of :meth:`generate` calls made.
        last_observation / last_instruction: the arguments of the most recent
            call (``None`` before the first call), for assertions.
    """

    output: str
    call_count: int = field(default=0, init=False)
    last_observation: object = field(default=None, init=False)
    last_instruction: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if type(self.output) is not str:
            raise TypeError(
                f"MockModelClient.output must be a str, got {type(self.output).__name__}"
            )

    def generate(self, observation: object, instruction: str) -> str:
        self.call_count += 1
        self.last_observation = observation
        self.last_instruction = instruction
        return self.output
