"""Input parsing helpers for EIS processing."""

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
class EisRawData:
    """Raw EIS vectors parsed from a source file."""

    frequency: list[float]
    z_real: list[float]
    z_imag: list[float]
    parse_errors: int = 0


def parse_eis_lines(
    lines: Iterable[str],
    *,
    frequency_column: int = 0,
    zreal_column: int = 1,
    zimag_column: int = 2,
    frequency_scale: float = 1.0,
    impedance_scale: float = 1.0,
    zimag_sign: float = 1.0,
    logger: Any | None = None,
) -> EisRawData:
    """Parse EIS text rows into frequency, real-Z, and imaginary-Z vectors."""
    frequency: list[float] = []
    z_real: list[float] = []
    z_imag: list[float] = []
    parse_errors = 0

    required_columns = max(frequency_column, zreal_column, zimag_column) + 1
    for line in lines:
        parts = split_table_row(line)
        if len(parts) < required_columns:
            continue
        try:
            frequency_value = float(parts[frequency_column]) * frequency_scale
            z_real_value = float(parts[zreal_column]) * impedance_scale
            z_imag_value = float(parts[zimag_column]) * impedance_scale * zimag_sign
            if not all(math.isfinite(value) for value in (frequency_value, z_real_value, z_imag_value)):
                raise ValueError("EIS row contains a non-finite value")
        except (ValueError, TypeError):
            parse_errors += 1
            if parse_errors <= 5:
                _log_debug(logger, "EIS row parse failed: %s", line.strip())
            continue
        frequency.append(frequency_value)
        z_real.append(z_real_value)
        z_imag.append(z_imag_value)

    return EisRawData(
        frequency=frequency,
        z_real=z_real,
        z_imag=z_imag,
        parse_errors=parse_errors,
    )


def read_eis_raw_data(
    filepath: str,
    *,
    start_line: Any = 1,
    frequency_column: int = 0,
    zreal_column: int = 1,
    zimag_column: int = 2,
    frequency_scale: float = 1.0,
    impedance_scale: float = 1.0,
    zimag_sign: float = 1.0,
    logger: Any | None = None,
) -> EisRawData | None:
    """Read and parse an EIS file using the standard encoding fallback policy."""
    lines = iter_file_with_fallback_encodings(
        filepath,
        start_line=as_int(start_line, 1),
    )
    raw = parse_eis_lines(
        lines,
        frequency_column=frequency_column,
        zreal_column=zreal_column,
        zimag_column=zimag_column,
        frequency_scale=frequency_scale,
        impedance_scale=impedance_scale,
        zimag_sign=zimag_sign,
        logger=logger,
    )
    if raw.parse_errors > 0:
        _log_info(logger, "Skipped %s unparsable EIS rows", raw.parse_errors)
    if not raw.frequency or not raw.z_real or not raw.z_imag:
        return None
    return raw


__all__ = ["EisRawData", "parse_eis_lines", "read_eis_raw_data"]
