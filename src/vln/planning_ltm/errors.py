"""Errors raised by the standalone planner / long-term-memory prototype.

The hierarchy is intentionally small. Every error is explicit: none of the
storage helpers silently resets or repairs a damaged file.
"""

from __future__ import annotations

__all__ = [
    "PlanningLtmError",
    "PlanningValidationError",
    "TopologyValidationError",
    "SceneValidationError",
    "CandidateGenerationError",
    "StoreError",
    "StoreCorruptionError",
    "StoreFormatError",
    "MemoryValidationError",
    "ExecutionValidationError",
]


class PlanningLtmError(Exception):
    """Base class for every error raised by :mod:`vln.planning_ltm`."""


class PlanningValidationError(PlanningLtmError):
    """A value violates a local contract (ids, numbers, enums)."""


class TopologyValidationError(PlanningValidationError):
    """The parking-lot topology is internally inconsistent."""


class SceneValidationError(PlanningValidationError):
    """The scene references nodes, edges or targets that do not exist."""


class CandidateGenerationError(PlanningLtmError):
    """Candidate routes cannot be generated for a scene."""


class StoreError(PlanningLtmError):
    """A JSON store cannot be read or written."""


class StoreCorruptionError(StoreError):
    """The file is not valid JSON, or its bytes cannot be decoded."""


class StoreFormatError(StoreError):
    """The JSON is valid but does not match the supported store schema."""


class MemoryValidationError(PlanningValidationError):
    """A long-term-memory record violates its contract."""


class ExecutionValidationError(PlanningValidationError):
    """An execution result violates its contract (mode/outcome/arrival)."""
