"""Shared type-coercion and I/O utilities used by multiple core modules."""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Sequence

_logger = logging.getLogger(__name__)

# Default fallback encoding list used across all processing modules.
DEFAULT_ENCODINGS: Sequence[str] = ("utf-8", "gbk", "gb2312", "ascii", "latin-1", "cp1252")


def read_file_with_fallback_encodings(
    filepath: str,
    *,
    start_line: int = 1,
    encodings: Sequence[str] | None = None,
) -> Optional[List[str]]:
    """Read a text file trying multiple encodings in order.

    Returns the list of lines starting from *start_line* (1-based) or
    ``None`` when all encodings fail.
    """
    skip = max(0, int(start_line) - 1)
    for enc in (encodings or DEFAULT_ENCODINGS):
        try:
            with open(filepath, "r", encoding=enc) as fh:
                lines = fh.readlines()[skip:]
            return lines
        except UnicodeDecodeError:
            continue
        except (FileNotFoundError, PermissionError, OSError) as exc:
            _logger.error("无法读取文件 %s: %s", filepath, exc)
            raise
    return None


def as_float(value: Any, default: float) -> float:
    """Safely convert *value* to float, returning *default* on failure."""
    try:
        return float(value)
    except Exception:
        return default


def as_int(value: Any, default: int) -> int:
    """Safely convert *value* to int, returning *default* on failure."""
    try:
        return int(value)
    except Exception:
        return default


def as_bool(value: Any, default: bool = False) -> bool:
    """Coerce *value* to bool using common truthy/falsy strings."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", "", "none"}:
            return False
    return bool(value)
