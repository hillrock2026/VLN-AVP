"""Small JSON I/O helpers shared by the topology and LTM stores.

Writes are atomic: the payload is written to a temporary file in the target
directory, flushed and fsynced, then renamed over the destination. A process
crash therefore leaves either the old file or the new file, never a half-written
one. Reads never repair or reset a damaged file.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .errors import StoreCorruptionError, StoreError

__all__ = ["atomic_write_json", "read_json_document"]


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StoreError(f"cannot create parent directory for {path}: {exc}") from exc

    descriptor = -1
    temporary = ""
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError) as exc:
        raise StoreError(f"cannot write {path}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def read_json_document(path: Path) -> Any:
    path = Path(path)
    if not path.exists():
        raise StoreError(f"store does not exist: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise StoreCorruptionError(f"cannot read {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise StoreCorruptionError(f"invalid JSON in {path}: {exc}") from exc
