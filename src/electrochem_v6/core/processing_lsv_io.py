"""Input parsing helpers for LSV processing."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Mapping

from .processing_core_v6 import DataProcessingError, FileFormatError
from .processing_source_profile import (
    CURRENT_TO_MA,
    POTENTIAL_TO_V,
    column_number_to_index,
    split_table_row,
    unit_scale,
)
from .utils import as_bool, as_float, as_int, iter_file_with_fallback_encodings


@dataclass(frozen=True)
class LsvRawData:
    """Raw LSV vectors parsed from a source file."""

    potential: list[float]
    current: list[float]
    current_signed: list[float]
    parse_errors: int = 0
    potential_column: int = 1
    current_column: int = 2
    potential_unit: str = "v"
    current_unit: str = "a"


def parse_lsv_lines(
    lines: Iterable[str],
    *,
    start_line: int = 1,
    offset: Any = 0,
    area: Any = 1.0,
    use_abs_current: bool = True,
    potential_column: int = 0,
    current_column: int = 1,
    potential_scale: float = 1.0,
    current_scale: float = 1000.0,
    potential_unit: str = "v",
    current_unit: str = "a",
    logger: Any | None = None,
) -> LsvRawData:
    """Parse LSV text rows into potential/current vectors."""
    potential: list[float] = []
    current: list[float] = []
    current_signed: list[float] = []
    parse_errors = 0

    area_value = as_float(area, 1.0)
    if area_value == 0:
        area_value = 1.0
    offset_value = as_float(offset, 0.0)

    required_columns = max(potential_column, current_column) + 1
    for line_num, line in enumerate(lines, start=as_int(start_line, 1)):
        parts = split_table_row(line)
        if len(parts) < required_columns:
            continue
        try:
            pot = float(parts[potential_column]) * potential_scale + offset_value
            signed = float(parts[current_column]) * current_scale / area_value
            used = abs(signed) if use_abs_current else signed
            potential.append(pot)
            current_signed.append(signed)
            current.append(used)
        except ValueError:
            parse_errors += 1
            if logger is not None and parse_errors <= 5:
                logger.debug("LSV parse failed at line %s: %s", line_num, line.strip())
            continue
        except Exception as exc:
            if logger is not None:
                logger.warning("LSV row processing failed at line %s: %s", line_num, exc)
            continue

    return LsvRawData(
        potential=potential,
        current=current,
        current_signed=current_signed,
        parse_errors=parse_errors,
        potential_column=potential_column + 1,
        current_column=current_column + 1,
        potential_unit=potential_unit,
        current_unit=current_unit,
    )


def read_lsv_raw_data(
    filepath: str,
    *,
    file_label: str,
    params: Mapping[str, Any],
    logger: Any | None = None,
) -> LsvRawData:
    """Read and parse an LSV file using the standard encoding fallback policy."""
    start_line = as_int(params.get("start_line", 1), 1)
    try:
        lines = iter_file_with_fallback_encodings(filepath, start_line=start_line)
    except (FileNotFoundError, OSError) as exc:
        if logger is not None:
            logger.error("LSV file read failed: %s - %s", filepath, exc)
        raise FileFormatError(f"无法读取LSV文件: {file_label} - {exc}") from exc

    potential_column = column_number_to_index(
        params.get("lsv_potential_column", 1), default=1, label="LSV potential column"
    )
    current_column = column_number_to_index(
        params.get("lsv_current_column", 2), default=2, label="LSV current column"
    )
    potential_unit, potential_scale = unit_scale(
        params.get("lsv_potential_unit"), default="v", supported=POTENTIAL_TO_V
    )
    current_unit, current_scale = unit_scale(
        params.get("lsv_current_unit"), default="a", supported=CURRENT_TO_MA
    )

    try:
        raw = parse_lsv_lines(
            lines,
            start_line=start_line,
            offset=params.get("offset", 0),
            area=params.get("area", 1.0),
            use_abs_current=as_bool(params.get("use_abs_current", True), True),
            potential_column=potential_column,
            current_column=current_column,
            potential_scale=potential_scale,
            current_scale=current_scale,
            potential_unit=potential_unit,
            current_unit=current_unit,
            logger=logger,
        )
    except (FileNotFoundError, OSError) as exc:
        if logger is not None:
            logger.error("LSV file read failed: %s - %s", filepath, exc)
        raise FileFormatError(f"无法读取LSV文件: {file_label} - {exc}") from exc

    if raw.parse_errors > 0 and logger is not None:
        logger.info("Skipped %s unparsable LSV rows", raw.parse_errors)

    if not raw.potential or not raw.current:
        if logger is not None:
            logger.error("No valid LSV data points found in file: %s", file_label)
        raise DataProcessingError(f"LSV文件 {file_label} 中未找到有效数据点")

    return raw


__all__ = [
    "LsvRawData",
    "parse_lsv_lines",
    "read_lsv_raw_data",
]
