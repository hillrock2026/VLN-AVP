"""JSON persistence for the synthetic parking-lot topology."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .errors import PlanningLtmError, StoreError, StoreFormatError
from .models import ParkingTopology
from .storage import atomic_write_json, read_json_document

__all__ = ["JsonTopologyStore", "SCHEMA_VERSION", "STORE_KIND"]

SCHEMA_VERSION = 1
STORE_KIND = "parking-topology"


class JsonTopologyStore:
    """Load/save one :class:`ParkingTopology` as a single JSON document.

    Querying is provided by the loaded topology itself (``node``, ``edge``,
    ``edge_between``, ``neighbors``, ``target_node``). The store deliberately
    has no "load or create empty" behaviour: a missing or invalid file is an
    error, never a silent reset.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @classmethod
    def create(cls, path: str | Path, topology: ParkingTopology) -> "JsonTopologyStore":
        store = cls(path)
        if store.path.exists():
            raise StoreError(f"refusing to overwrite existing store: {store.path}")
        store.save(topology)
        return store

    def save(self, topology: ParkingTopology) -> None:
        if not isinstance(topology, ParkingTopology):
            raise StoreError("topology store can only persist a ParkingTopology")
        atomic_write_json(
            self.path,
            {
                "schema_version": SCHEMA_VERSION,
                "kind": STORE_KIND,
                "topology": topology.to_dict(),
            },
        )

    def load(self) -> ParkingTopology:
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
        payload: Any = document.get("topology")
        if not isinstance(payload, Mapping):
            raise StoreFormatError(f"{self.path}: topology must be a JSON object")
        try:
            return ParkingTopology.from_dict(payload)
        except PlanningLtmError as exc:
            raise StoreFormatError(f"{self.path}: invalid topology: {exc}") from exc
