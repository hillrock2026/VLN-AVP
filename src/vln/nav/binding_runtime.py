"""Resolve the runner's parking goal from a binding artifact before execution.

The natural-language task is parsed and bound by the binder script, not by the
navigation runner. The runner therefore starts from a small JSON artifact and
must enforce three things before it plans a route or contacts the Host:

* the artifact is structurally valid (:func:`parse_binding_artifact`);
* its status is ``bound`` - every other status is a refusal, not a fallback;
* the bound slot node is the goal the caller asked for.

This module is pure and importable without CARLA so the refusal paths are
unit-tested; the runner only adds argument parsing around it.
"""

from __future__ import annotations

import json
from pathlib import Path

from vln.nav.target_binding import (
    BindingArtifact,
    BindingNotExecutableError,
    binding_goal_node,
    parse_binding_artifact,
)

__all__ = [
    "BindingRuntimeError",
    "load_binding_artifact",
    "resolve_bound_goal",
]


class BindingRuntimeError(ValueError):
    """The binding artifact cannot drive this run."""


def load_binding_artifact(path: str | Path) -> BindingArtifact:
    """Read and validate one binding JSON file."""

    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise BindingRuntimeError(f"cannot read binding artifact: {error}") from error
    try:
        metadata = json.loads(text)
    except json.JSONDecodeError as error:
        raise BindingRuntimeError(f"binding artifact is not valid JSON: {error}") from error
    try:
        return parse_binding_artifact(metadata)
    except (TypeError, ValueError) as error:
        raise BindingRuntimeError(f"invalid binding artifact: {error}") from error


def resolve_bound_goal(
    artifact: BindingArtifact,
    *,
    instruction: str | None = None,
    explicit_goal_node: str | None = None,
) -> str:
    """Return the executable goal node, or refuse.

    ``instruction`` is the natural-language task supplied to the runner. It must
    be textually the same task the binder resolved; otherwise the artifact
    belongs to a different request and cannot be reused. ``explicit_goal_node``
    is a caller-supplied ``--goal-node`` and must not conflict with the bound
    target.
    """

    if not isinstance(artifact, BindingArtifact):
        raise TypeError("artifact must be a BindingArtifact")
    try:
        goal_node = binding_goal_node(artifact)
    except BindingNotExecutableError as error:
        raise BindingRuntimeError(
            f"refusing to execute: binding status {artifact.status!r}: "
            f"{artifact.reason}"
        ) from error
    if instruction is not None:
        if type(instruction) is not str or instruction.strip() == "":
            raise BindingRuntimeError("instruction must be a non-blank str")
        if instruction.strip() != artifact.instruction.strip():
            raise BindingRuntimeError(
                "the runner instruction does not match the binding artifact "
                "instruction"
            )
    if explicit_goal_node is not None and explicit_goal_node != goal_node:
        raise BindingRuntimeError(
            f"--goal-node {explicit_goal_node!r} conflicts with the bound target "
            f"{goal_node!r}"
        )
    return goal_node
