"""Shared type-coercion utilities used by multiple core modules."""

from __future__ import annotations

from typing import Any


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
