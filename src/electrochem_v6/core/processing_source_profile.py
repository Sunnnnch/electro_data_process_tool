"""Column and unit normalization for instrument-exported text tables."""

from __future__ import annotations

import re
from typing import Any, Mapping

CURRENT_TO_MA: Mapping[str, float] = {
    "a": 1000.0,
    "ma": 1.0,
    "ua": 0.001,
}
CURRENT_TO_A: Mapping[str, float] = {
    "a": 1.0,
    "ma": 0.001,
    "ua": 0.000001,
}
POTENTIAL_TO_V: Mapping[str, float] = {
    "v": 1.0,
    "mv": 0.001,
}
FREQUENCY_TO_HZ: Mapping[str, float] = {
    "hz": 1.0,
    "khz": 1000.0,
}
IMPEDANCE_TO_OHM: Mapping[str, float] = {
    "ohm": 1.0,
    "kohm": 1000.0,
}

ZIMAG_CONVENTIONS: Mapping[str, float] = {
    "z_imaginary": 1.0,
    "negative_z_imaginary": -1.0,
}

_TABLE_SEPARATOR_RE = re.compile(r"[,;\t\s]+")


def split_table_row(line: str, delimiter: str | None = None) -> list[str]:
    """Split a text-table row using the same rules as input auto-detection."""
    stripped = str(line or "").strip()
    if not stripped:
        return []
    if delimiter:
        return [part.strip() for part in stripped.split(delimiter) if part.strip()]
    return [part for part in _TABLE_SEPARATOR_RE.split(stripped) if part]


def imaginary_convention(value: Any, *, default: str = "z_imaginary") -> tuple[str, float]:
    """Return the normalized EIS imaginary-column convention and sign factor.

    Internally EIS always uses signed Z''. Instruments exporting positive -Z''
    values therefore receive a factor of -1.
    """
    text = str(value or default).strip().lower().replace(" ", "_")
    aliases = {
        "z''": "z_imaginary",
        "zimag": "z_imaginary",
        "signed": "z_imaginary",
        "-z''": "negative_z_imaginary",
        "negative_zimag": "negative_z_imaginary",
        "positive_minus_zimag": "negative_z_imaginary",
    }
    normalized = aliases.get(text, text)
    if normalized not in ZIMAG_CONVENTIONS:
        choices = ", ".join(ZIMAG_CONVENTIONS)
        raise ValueError(f"Unsupported EIS imaginary convention {value!r}; expected one of: {choices}")
    return normalized, float(ZIMAG_CONVENTIONS[normalized])


def normalize_unit(value: Any, *, default: str, supported: Mapping[str, float]) -> str:
    text = str(value or default).strip().lower().replace("μ", "u").replace("µ", "u")
    aliases = {
        "amp": "a",
        "amps": "a",
        "ampere": "a",
        "millivolt": "mv",
        "volt": "v",
        "ω": "ohm",
        "Ω": "ohm",
        "kω": "kohm",
        "kΩ": "kohm",
        "kiloohm": "kohm",
    }
    normalized = aliases.get(text, text)
    if normalized not in supported:
        choices = ", ".join(supported)
        raise ValueError(f"Unsupported source unit {value!r}; expected one of: {choices}")
    return normalized


def unit_scale(value: Any, *, default: str, supported: Mapping[str, float]) -> tuple[str, float]:
    normalized = normalize_unit(value, default=default, supported=supported)
    return normalized, float(supported[normalized])


def column_number_to_index(value: Any, *, default: int, label: str) -> int:
    """Convert a user-facing 1-based column number to a zero-based index."""
    raw = default if value in (None, "") else value
    try:
        numeric = float(raw)
        number = int(numeric)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer column number starting at 1") from exc
    if numeric != number or number < 1:
        raise ValueError(f"{label} must be an integer column number starting at 1")
    return number - 1


__all__ = [
    "CURRENT_TO_A",
    "CURRENT_TO_MA",
    "FREQUENCY_TO_HZ",
    "IMPEDANCE_TO_OHM",
    "POTENTIAL_TO_V",
    "ZIMAG_CONVENTIONS",
    "column_number_to_index",
    "imaginary_convention",
    "normalize_unit",
    "split_table_row",
    "unit_scale",
]
