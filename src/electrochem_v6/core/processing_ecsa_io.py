"""Input parsing and scan-rate helpers for ECSA processing."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .processing_source_profile import split_table_row
from .utils import iter_file_with_fallback_encodings, read_file_with_fallback_encodings


@dataclass(frozen=True)
class EcsaCvTable:
    """Potential/current table plus original text lines."""

    potential: np.ndarray
    current: np.ndarray
    lines: list[str]


def _ecsa_read_text_lines(filepath: str) -> list[str]:
    """Read text lines using the standard encoding fallback policy."""
    lines = read_file_with_fallback_encodings(filepath)
    return lines or []


def _ecsa_extract_v_from_content(lines: Sequence[str]):
    """Extract scan rate in V/s from common metadata lines."""
    number = r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    patterns = (
        (re.compile(rf"scan\s*rate\s*\(\s*mV\s*/\s*s\s*\)\s*[:=]\s*{number}", re.IGNORECASE), 1e-3),
        (re.compile(rf"scan\s*rate\s*\(\s*V\s*/\s*s\s*\)\s*[:=]\s*{number}", re.IGNORECASE), 1.0),
        (re.compile(rf"scan\s*rate\s*[:=]\s*{number}\s*mV\s*/?\s*s", re.IGNORECASE), 1e-3),
        (re.compile(rf"scan\s*rate\s*[:=]\s*{number}\s*V\s*/?\s*s", re.IGNORECASE), 1.0),
    )
    for line in lines:
        for pattern, scale in patterns:
            match = pattern.search(line)
            if match:
                try:
                    value = float(match.group(1)) * scale
                except ValueError:
                    continue
                if value > 0:
                    return value
    return None


def _ecsa_extract_v_from_name(filename: str):
    """Extract scan rate in V/s from common ECSA filename patterns."""
    name = os.path.splitext(os.path.basename(filename))[0]
    number = r"([0-9]+(?:\.[0-9]+)?)"
    # Unit-bearing forms must be checked before the historical ECSA50 fallback,
    # otherwise decimal names such as ECSA_2.5mV_s are truncated to 2.
    match = re.search(rf"{number}\s*mV(?:\s*(?:/|_|-)?\s*s)?(?![A-Za-z])", name, re.IGNORECASE)
    if match:
        return float(match.group(1)) / 1000.0
    match = re.search(rf"(?<![A-Za-z]){number}\s*V(?:\s*(?:/|_|-)?\s*s)?(?![A-Za-z])", name, re.IGNORECASE)
    if match:
        return float(match.group(1))
    match = re.search(rf"ECSA[^0-9]*{number}(?![0-9.])", name, re.IGNORECASE)
    if match:
        return float(match.group(1)) / 1000.0
    return None


def _ecsa_read_cv_table(
    filepath: str,
    *,
    potential_column: int = 0,
    current_column: int = 1,
    potential_scale: float = 1.0,
    current_scale: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Read an ECSA CV table, skipping a detected Potential/Current header."""
    # Retain a bounded metadata prefix for scan-rate discovery while parsing
    # the numeric vectors as a stream.
    lines: list[str] = []
    metadata_line_limit = 2048
    header_seen = False
    potential: list[float] = []
    current: list[float] = []
    required_columns = max(potential_column, current_column) + 1
    for line in iter_file_with_fallback_encodings(filepath):
        if len(lines) < metadata_line_limit:
            lines.append(line)
        lower = line.lower()
        if not header_seen and "potential" in lower and "current" in lower:
            header_seen = True
            continue
        parts = split_table_row(line)
        if len(parts) < required_columns:
            continue
        try:
            potential_value = float(parts[potential_column]) * potential_scale
            current_value = float(parts[current_column]) * current_scale
            if not math.isfinite(potential_value) or not math.isfinite(current_value):
                raise ValueError("ECSA row contains a non-finite value")
        except (ValueError, TypeError):
            continue
        potential.append(potential_value)
        current.append(current_value)
    return np.asarray(potential, float), np.asarray(current, float), lines


def read_ecsa_cv_table(
    filepath: str,
    *,
    potential_column: int = 0,
    current_column: int = 1,
    potential_scale: float = 1.0,
    current_scale: float = 1.0,
) -> EcsaCvTable:
    """Read an ECSA CV table into a structured container."""
    potential, current, lines = _ecsa_read_cv_table(
        filepath,
        potential_column=potential_column,
        current_column=current_column,
        potential_scale=potential_scale,
        current_scale=current_scale,
    )
    return EcsaCvTable(potential=potential, current=current, lines=lines)


__all__ = [
    "EcsaCvTable",
    "_ecsa_extract_v_from_content",
    "_ecsa_extract_v_from_name",
    "_ecsa_read_cv_table",
    "_ecsa_read_text_lines",
    "read_ecsa_cv_table",
]
