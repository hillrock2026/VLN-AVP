"""Persistent long-term memory for the offline planner prototype.

The first version is a single JSON document written atomically. It stores three
kinds of records:

* ``confirmed_fact`` - a fact the caller declares confirmed;
* ``historical_observation`` - something observed earlier, possibly stale;
* ``execution_experience`` - an outcome tied to a specific route/candidate.

A record always carries its source, creation/update times, confidence, evidence
level, associations (scene/target/route), and an optional validity window. A
simulated success may not claim physical arrival; that rule is enforced both on
:class:`~vln.planning_ltm.models.ExecutionResult` and on memory records.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .errors import MemoryValidationError, StoreError, StoreFormatError
from .models import ExecutionMode, ExecutionOutcome, PhysicalArrival
from .storage import atomic_write_json, read_json_document

__all__ = [
    "MemoryKind",
    "EvidenceLevel",
    "MemoryEffect",
    "MemoryRecord",
    "LongTermMemoryStore",
    "STORE_KIND",
    "SCHEMA_VERSION",
    "format_timestamp",
    "parse_timestamp",
    "ensure_utc",
]


STORE_KIND = "parking-ltm"
SCHEMA_VERSION = 1
_MEMORY_ID_PATTERN = re.compile(r"^mem-(\d+)$")


class MemoryKind:
    CONFIRMED_FACT = "confirmed_fact"
    HISTORICAL_OBSERVATION = "historical_observation"
    EXECUTION_EXPERIENCE = "execution_experience"
    ALL = frozenset({CONFIRMED_FACT, HISTORICAL_OBSERVATION, EXECUTION_EXPERIENCE})


class EvidenceLevel:
    CONFIRMED = "confirmed"
    OBSERVED = "observed"
    SIMULATED = "simulated"
    HYPOTHESIZED = "hypothesized"
    ALL = frozenset({CONFIRMED, OBSERVED, SIMULATED, HYPOTHESIZED})


class MemoryEffect:
    """Decision effect of a record; scaled by confidence in the selector."""

    PREFER = "prefer"
    AVOID = "avoid"
    NEUTRAL = "neutral"
    ALL = frozenset({PREFER, AVOID, NEUTRAL})


def parse_timestamp(value: object, name: str = "timestamp") -> datetime:
    if not isinstance(value, str) or value.strip() == "":
        raise MemoryValidationError(f"{name} must be a non-blank ISO-8601 string")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MemoryValidationError(f"{name} is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise MemoryValidationError(f"{name} must include a timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def ensure_utc(value: object, name: str = "timestamp") -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise MemoryValidationError(f"{name} must include a timezone")
        return value.astimezone(timezone.utc)
    return parse_timestamp(value, name)


def format_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise MemoryValidationError("timestamp must be a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class MemoryRecord:
    """One long-term-memory record with explicit provenance and validity."""

    memory_id: str
    kind: str
    statement: str
    source: str
    created_at: str
    updated_at: str
    confidence: float
    evidence_level: str
    effect: str
    scene_id: str | None = None
    target_id: str | None = None
    route_key: str | None = None
    node_ids: tuple[str, ...] = ()
    edge_ids: tuple[str, ...] = ()
    valid_until: str | None = None
    invalidated_reason: str | None = None
    execution_id: str | None = None
    execution_mode: str | None = None
    outcome: str | None = None
    physical_arrival: str = PhysicalArrival.UNKNOWN

    def __post_init__(self) -> None:
        for name in ("memory_id", "statement", "source"):
            value = getattr(self, name)
            if not isinstance(value, str) or value.strip() == "":
                raise MemoryValidationError(f"{name} must be a non-blank str")
        if self.kind not in MemoryKind.ALL:
            raise MemoryValidationError(f"unknown memory kind {self.kind!r}")
        if self.evidence_level not in EvidenceLevel.ALL:
            raise MemoryValidationError(
                f"unknown evidence_level {self.evidence_level!r}"
            )
        if self.effect not in MemoryEffect.ALL:
            raise MemoryValidationError(f"unknown memory effect {self.effect!r}")
        if type(self.confidence) is not int and type(self.confidence) is not float:
            raise MemoryValidationError("confidence must be a number")
        confidence = float(self.confidence)
        if not 0.0 <= confidence <= 1.0:
            raise MemoryValidationError("confidence must be in [0, 1]")
        object.__setattr__(self, "confidence", confidence)

        created = parse_timestamp(self.created_at, "created_at")
        updated = parse_timestamp(self.updated_at, "updated_at")
        if updated < created:
            raise MemoryValidationError("updated_at must not precede created_at")
        if self.valid_until is not None:
            parse_timestamp(self.valid_until, "valid_until")

        for name in (
            "scene_id",
            "target_id",
            "route_key",
            "invalidated_reason",
            "execution_id",
        ):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or value.strip() == ""):
                raise MemoryValidationError(f"{name} must be None or a non-blank str")
        for name in ("node_ids", "edge_ids"):
            value = getattr(self, name)
            if isinstance(value, str) or not isinstance(value, (tuple, list)):
                raise MemoryValidationError(f"{name} must be a tuple or list")
            value = tuple(value)
            for item in value:
                if not isinstance(item, str) or item.strip() == "":
                    raise MemoryValidationError(f"{name} must contain non-blank str")
            object.__setattr__(self, name, value)
        if self.route_key is not None and self.node_ids:
            if self.route_key != ">".join(self.node_ids):
                raise MemoryValidationError(
                    "route_key must equal '>'.join(node_ids) when both are present"
                )

        if self.physical_arrival not in PhysicalArrival.ALL:
            raise MemoryValidationError(
                f"unknown physical_arrival {self.physical_arrival!r}"
            )
        if self.execution_mode is not None:
            if self.execution_mode not in ExecutionMode.ALL:
                raise MemoryValidationError(
                    f"unknown execution_mode {self.execution_mode!r}"
                )
            if self.execution_mode == ExecutionMode.SIMULATED and (
                self.physical_arrival != PhysicalArrival.UNKNOWN
            ):
                raise MemoryValidationError(
                    "a simulated execution memory cannot claim physical arrival"
                )
        if (self.execution_mode is None) != (self.outcome is None):
            raise MemoryValidationError(
                "execution_mode and outcome must be provided together"
            )
        if self.outcome is not None:
            if self.outcome not in ExecutionOutcome.ALL:
                raise MemoryValidationError(f"unknown outcome {self.outcome!r}")
            if not self.outcome.startswith(self.execution_mode + "-"):
                raise MemoryValidationError(
                    f"outcome {self.outcome!r} does not belong to mode "
                    f"{self.execution_mode!r}"
                )

        if self.kind == MemoryKind.EXECUTION_EXPERIENCE:
            for name in ("execution_id", "execution_mode", "outcome", "route_key"):
                if getattr(self, name) is None:
                    raise MemoryValidationError(
                        f"execution_experience requires {name}"
                    )

    def is_expired(self, as_of: datetime | str) -> bool:
        if self.valid_until is None:
            return False
        return ensure_utc(as_of, "as_of") > parse_timestamp(
            self.valid_until, "valid_until"
        )

    def inactive_reason(self, as_of: datetime | str) -> str | None:
        if self.invalidated_reason is not None:
            return f"invalidated: {self.invalidated_reason}"
        if self.is_expired(as_of):
            return f"expired: valid_until={self.valid_until}"
        return None

    def association_mismatch(
        self,
        *,
        scene_id: str,
        target_id: str,
        route_key: str,
        node_ids: tuple[str, ...],
    ) -> str | None:
        if self.scene_id is not None and self.scene_id != scene_id:
            return "scene-mismatch"
        if self.target_id is not None and self.target_id != target_id:
            return "target-mismatch"
        if self.route_key is not None and self.route_key != route_key:
            return "route-mismatch"
        if self.node_ids and not set(self.node_ids).issubset(node_ids):
            return "route-mismatch"
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "kind": self.kind,
            "statement": self.statement,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "confidence": self.confidence,
            "evidence_level": self.evidence_level,
            "effect": self.effect,
            "scene_id": self.scene_id,
            "target_id": self.target_id,
            "route_key": self.route_key,
            "node_ids": list(self.node_ids),
            "edge_ids": list(self.edge_ids),
            "valid_until": self.valid_until,
            "invalidated_reason": self.invalidated_reason,
            "execution_id": self.execution_id,
            "execution_mode": self.execution_mode,
            "outcome": self.outcome,
            "physical_arrival": self.physical_arrival,
        }

    @classmethod
    def from_dict(cls, data: object) -> "MemoryRecord":
        if not isinstance(data, Mapping):
            raise MemoryValidationError("memory record must be a JSON object")
        allowed = set(cls.to_dict_fields())
        keys = set(data)
        missing = allowed - keys
        extra = keys - allowed
        if missing:
            raise MemoryValidationError(
                f"memory record is missing fields: {sorted(missing)}"
            )
        if extra:
            raise MemoryValidationError(
                f"memory record has unsupported fields: {sorted(extra)}"
            )
        return cls(**data)  # type: ignore[arg-type]

    @classmethod
    def to_dict_fields(cls) -> tuple[str, ...]:
        return (
            "memory_id",
            "kind",
            "statement",
            "source",
            "created_at",
            "updated_at",
            "confidence",
            "evidence_level",
            "effect",
            "scene_id",
            "target_id",
            "route_key",
            "node_ids",
            "edge_ids",
            "valid_until",
            "invalidated_reason",
            "execution_id",
            "execution_mode",
            "outcome",
            "physical_arrival",
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LongTermMemoryStore:
    """A JSON-backed memory store with atomic writes and stable ``mem-NNNN`` ids."""

    def __init__(
        self, path: str | Path, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        self.path = Path(path)
        self._clock = clock or _utc_now
        self._records: list[MemoryRecord] = []
        self._next_sequence = 1
        self._loaded = False

    # -- lifecycle -------------------------------------------------------

    @classmethod
    def create(
        cls, path: str | Path, *, clock: Callable[[], datetime] | None = None
    ) -> "LongTermMemoryStore":
        store = cls(path, clock=clock)
        if store.path.exists():
            raise StoreError(f"refusing to overwrite existing store: {store.path}")
        store._loaded = True
        store.save()
        return store

    @classmethod
    def load(
        cls, path: str | Path, *, clock: Callable[[], datetime] | None = None
    ) -> "LongTermMemoryStore":
        store = cls(path, clock=clock)
        store._load()
        return store

    def _load(self) -> None:
        document = read_json_document(self.path)
        if not isinstance(document, Mapping):
            raise StoreFormatError(f"{self.path}: top-level JSON must be an object")
        if document.get("schema_version") != SCHEMA_VERSION:
            raise StoreFormatError(
                f"{self.path}: unsupported schema_version "
                f"{document.get('schema_version')!r}; expected {SCHEMA_VERSION}"
            )
        if document.get("kind") != STORE_KIND:
            raise StoreFormatError(
                f"{self.path}: kind must be {STORE_KIND!r}, "
                f"got {document.get('kind')!r}"
            )
        raw_records = document.get("records")
        next_sequence = document.get("next_sequence")
        if not isinstance(raw_records, list):
            raise StoreFormatError(f"{self.path}: records must be a JSON array")
        if type(next_sequence) is not int or next_sequence < 1:
            raise StoreFormatError(
                f"{self.path}: next_sequence must be an integer >= 1"
            )

        records: list[MemoryRecord] = []
        seen_ids: set[str] = set()
        numeric_ids: list[int] = []
        for index, raw in enumerate(raw_records):
            try:
                record = MemoryRecord.from_dict(raw)
            except MemoryValidationError as exc:
                raise StoreFormatError(
                    f"{self.path}: record[{index}] is invalid: {exc}"
                ) from exc
            if record.memory_id in seen_ids:
                raise StoreFormatError(
                    f"{self.path}: duplicate memory_id {record.memory_id!r}"
                )
            seen_ids.add(record.memory_id)
            match = _MEMORY_ID_PATTERN.match(record.memory_id)
            if match is not None:
                numeric_ids.append(int(match.group(1)))
            records.append(record)

        if numeric_ids and next_sequence <= max(numeric_ids):
            raise StoreFormatError(
                f"{self.path}: next_sequence {next_sequence} would reuse an "
                f"existing id (max {max(numeric_ids)})"
            )

        self._records = records
        self._next_sequence = next_sequence
        self._loaded = True

    def reload(self) -> None:
        self._load()

    def save(self) -> None:
        if not self._loaded:
            raise StoreError("store is not loaded; use create() or load()")
        atomic_write_json(
            self.path,
            {
                "schema_version": SCHEMA_VERSION,
                "kind": STORE_KIND,
                "next_sequence": self._next_sequence,
                "records": [record.to_dict() for record in self._records],
            },
        )

    # -- read ------------------------------------------------------------

    @property
    def records(self) -> tuple[MemoryRecord, ...]:
        return tuple(self._records)

    def all(self) -> tuple[MemoryRecord, ...]:
        return self.records

    def get(self, memory_id: str) -> MemoryRecord:
        for record in self._records:
            if record.memory_id == memory_id:
                return record
        raise MemoryValidationError(f"unknown memory_id {memory_id!r}")

    def __len__(self) -> int:
        return len(self._records)

    def query(
        self,
        *,
        scene_id: str | None = None,
        target_id: str | None = None,
        route_key: str | None = None,
        kind: str | None = None,
        as_of: datetime | str | None = None,
        include_inactive: bool = False,
    ) -> tuple[MemoryRecord, ...]:
        """Filter records; ``None`` associations are wildcards."""

        if kind is not None and kind not in MemoryKind.ALL:
            raise MemoryValidationError(f"unknown memory kind {kind!r}")
        moment = ensure_utc(as_of, "as_of") if as_of is not None else self._clock()
        selected: list[MemoryRecord] = []
        for record in self._records:
            if kind is not None and record.kind != kind:
                continue
            if scene_id is not None and record.scene_id not in (None, scene_id):
                continue
            if target_id is not None and record.target_id not in (None, target_id):
                continue
            if route_key is not None and record.route_key not in (None, route_key):
                continue
            if not include_inactive and record.inactive_reason(moment) is not None:
                continue
            selected.append(record)
        return tuple(selected)

    # -- write -----------------------------------------------------------

    def add(
        self,
        *,
        kind: str,
        statement: str,
        source: str,
        confidence: float,
        evidence_level: str,
        effect: str = MemoryEffect.NEUTRAL,
        scene_id: str | None = None,
        target_id: str | None = None,
        route_key: str | None = None,
        node_ids: tuple[str, ...] = (),
        edge_ids: tuple[str, ...] = (),
        valid_until: str | None = None,
        execution_id: str | None = None,
        execution_mode: str | None = None,
        outcome: str | None = None,
        physical_arrival: str = PhysicalArrival.UNKNOWN,
        created_at: str | datetime | None = None,
    ) -> MemoryRecord:
        now = self._clock()
        created = (
            format_timestamp(ensure_utc(created_at, "created_at"))
            if created_at is not None
            else format_timestamp(now)
        )
        memory_id = f"mem-{self._next_sequence:04d}"
        record = MemoryRecord(
            memory_id=memory_id,
            kind=kind,
            statement=statement,
            source=source,
            created_at=created,
            updated_at=created,
            confidence=confidence,
            evidence_level=evidence_level,
            effect=effect,
            scene_id=scene_id,
            target_id=target_id,
            route_key=route_key,
            node_ids=node_ids,
            edge_ids=edge_ids,
            valid_until=valid_until,
            execution_id=execution_id,
            execution_mode=execution_mode,
            outcome=outcome,
            physical_arrival=physical_arrival,
        )
        self._records.append(record)
        self._next_sequence += 1
        try:
            self.save()
        except Exception:
            self._records.pop()
            self._next_sequence -= 1
            raise
        return record

    def update(
        self,
        memory_id: str,
        *,
        statement: str | None = None,
        confidence: float | None = None,
        valid_until: str | None = None,
        invalidated_reason: str | None = None,
    ) -> MemoryRecord:
        """Update a record in place while keeping its stable id and provenance."""

        current = self.get(memory_id)
        changes: dict[str, Any] = {}
        if statement is not None:
            changes["statement"] = statement
        if confidence is not None:
            changes["confidence"] = confidence
        if valid_until is not None:
            changes["valid_until"] = valid_until
        if invalidated_reason is not None:
            changes["invalidated_reason"] = invalidated_reason
        if not changes:
            return current
        changes["updated_at"] = format_timestamp(self._clock())
        updated = replace(current, **changes)
        index = self._records.index(current)
        self._records[index] = updated
        try:
            self.save()
        except Exception:
            self._records[index] = current
            raise
        return updated
