"""Shared type-coercion and I/O utilities used by multiple core modules."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from itertools import islice
from typing import Any, List, Optional, Sequence

_logger = logging.getLogger(__name__)

# Default fallback encoding list used across all processing modules.
DEFAULT_ENCODINGS: Sequence[str] = ("utf-8", "gbk", "gb2312", "ascii", "latin-1", "cp1252")


def _validated_text_encoding(filepath: str, encodings: Sequence[str] | None) -> str | None:
    for enc in (encodings or DEFAULT_ENCODINGS):
        try:
            with open(filepath, "r", encoding=enc) as handle:
                for _line in handle:
                    pass
            return enc
        except UnicodeDecodeError:
            continue
        except (FileNotFoundError, PermissionError, OSError) as exc:
            _logger.error("无法读取文件 %s: %s", filepath, exc)
            raise
    return None


def iter_file_with_fallback_encodings(
    filepath: str,
    *,
    start_line: int = 1,
    encodings: Sequence[str] | None = None,
) -> Iterator[str]:
    """Yield text lines with bounded memory after validating an encoding.

    Each candidate is validated in a streaming pass before lines are yielded,
    preventing partial data from one encoding from being mixed with a fallback.
    """

    selected = _validated_text_encoding(filepath, encodings)
    if selected is None:
        return
    skip = max(0, int(start_line) - 1)
    with open(filepath, "r", encoding=selected) as handle:
        yield from islice(handle, skip, None)


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
    selected = _validated_text_encoding(filepath, encodings)
    if selected is None:
        return None
    skip = max(0, int(start_line) - 1)
    with open(filepath, "r", encoding=selected) as handle:
        return list(islice(handle, skip, None))


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
