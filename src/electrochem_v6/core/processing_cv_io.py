"""Input parsing helpers for CV processing."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .processing_source_profile import split_table_row
from .utils import as_int, iter_file_with_fallback_encodings


def _log_debug(logger: Any | None, message: str, *args: Any) -> None:
    if logger is None:
        return
    text = message % args if args else message
    if hasattr(logger, "debug"):
        logger.debug(message, *args)
    elif callable(logger):
        logger(text)


def _log_info(logger: Any | None, message: str, *args: Any) -> None:
    if logger is None:
        return
    text = message % args if args else message
    if hasattr(logger, "info"):
        logger.info(message, *args)
    elif callable(logger):
        logger(text)


@dataclass(frozen=True)
class CvRawData:
    """Raw CV vectors parsed from a source file."""

    potential: list[float]
    current: list[float]
    parse_errors: int = 0


def parse_cv_lines(
    lines: Iterable[str],
    *,
    potential_column: int = 0,
    current_column: int = 1,
    potential_scale: float = 1.0,
    current_scale: float = 1000.0,
    logger: Any | None = None,
) -> CvRawData:
    """Parse CV text rows into potential/current vectors."""
    potential: list[float] = []
    current: list[float] = []
    parse_errors = 0

    required_columns = max(potential_column, current_column) + 1
    for line in lines:
        parts = split_table_row(line)
        if len(parts) < required_columns:
            continue
        try:
            potential_value = float(parts[potential_column]) * potential_scale
            current_value = float(parts[current_column]) * current_scale
            if not math.isfinite(potential_value) or not math.isfinite(current_value):
                raise ValueError("CV row contains a non-finite value")
        except (ValueError, TypeError):
            parse_errors += 1
            if logger is not None and parse_errors <= 5:
                _log_debug(logger, "CV row parse failed: %s", line.strip())
            continue
        potential.append(potential_value)
        current.append(current_value)

    return CvRawData(potential=potential, current=current, parse_errors=parse_errors)


def read_cv_raw_data(
    filepath: str,
    *,
    start_line: Any = 1,
    potential_column: int = 0,
    current_column: int = 1,
    potential_scale: float = 1.0,
    current_scale: float = 1000.0,
    logger: Any | None = None,
) -> CvRawData | None:
    """Read and parse a CV file using the standard encoding fallback policy."""
    lines = iter_file_with_fallback_encodings(
        filepath,
        start_line=as_int(start_line, 1),
    )
    raw = parse_cv_lines(
        lines,
        potential_column=potential_column,
        current_column=current_column,
        potential_scale=potential_scale,
        current_scale=current_scale,
        logger=logger,
    )
    if raw.parse_errors > 0 and logger is not None:
        _log_info(logger, "Skipped %s unparsable CV rows", raw.parse_errors)
    if not raw.potential or not raw.current:
        return None
    return raw


__all__ = ["CvRawData", "parse_cv_lines", "read_cv_raw_data"]
