"""Shared JSON serialisation and atomic-write helpers used across the storage layer."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

_logger = logging.getLogger(__name__)


def to_json_safe(value: Any) -> Any:
    """Recursively convert *value* to a JSON-serialisable structure.

    Handles dicts, lists, tuples, sets, numpy scalars/arrays, Path objects,
    datetime, and falls back to ``str()`` for unknown types.
    """
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if __import__("math").isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "tolist"):
        try:
            return to_json_safe(value.tolist())
        except Exception:
            _logger.debug("tolist() failed for %s", type(value).__name__, exc_info=True)
    if hasattr(value, "item"):
        try:
            return to_json_safe(value.item())
        except Exception:
            _logger.debug("item() failed for %s", type(value).__name__, exc_info=True)
    if hasattr(value, "as_posix"):
        try:
            return value.as_posix()
        except Exception:
            _logger.debug("as_posix() failed for %s", type(value).__name__, exc_info=True)
    return str(value)


def atomic_write_json(path: str | Path, payload: Dict[str, Any]) -> None:
    """Write *payload* to *path* atomically with ``fsync`` for crash safety."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f"{target.stem}_", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(to_json_safe(payload), f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(target))
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def json_dumps_safe(obj: Any) -> str:
    """Serialise *obj* to a JSON string, handling non-standard types."""
    return json.dumps(to_json_safe(obj), ensure_ascii=False)
