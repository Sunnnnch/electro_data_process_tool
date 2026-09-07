"""Input helpers for coupled electrochemical calculations."""

from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from electrochem_v6.core.processing_coupled_models import CoupledCalculationError, ProductQuantification

PRODUCT_QUANTIFICATION_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "sample_name": ("sample_name", "sample", "sample_id", "sampleid", "sample name"),
    "product_name": ("product_name", "product", "product_id", "productid", "analyte", "species"),
    "product_moles": ("product_moles", "moles", "amount_mol", "product_amount_mol", "product mol"),
    "electron_count": ("electron_count", "n_electrons", "electron_number", "electrons", "n"),
    "charge_coulomb": ("charge_coulomb", "charge_c", "charge", "total_charge_c", "q_c", "q"),
}

DERIVED_CHARGE_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "current_ampere": ("current_a", "current_ampere", "current_amp", "i_a", "current", "i"),
    "current_milliampere": ("current_ma", "current_milliampere", "current_mamp", "i_ma"),
    "electrolysis_time_s": ("time_s", "duration_s", "electrolysis_time_s", "electrolysis_seconds", "time", "duration", "electrolysis_time"),
    "electrolysis_time_min": ("time_min", "duration_min", "electrolysis_time_min", "electrolysis_minutes"),
}

REQUIRED_PRODUCT_QUANTIFICATION_FIELDS = (
    "sample_name",
    "product_name",
    "product_moles",
    "electron_count",
    "charge_coulomb_or_current_time",
)


def normalize_table_column_name(name: Any) -> str:
    """Normalize external table column names for alias matching."""
    text = str(name or "").strip().lower()
    replacements = {
        "μ": "u",
        "µ": "u",
        "（": "(",
        "）": ")",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\([^)]*\)|\[[^]]*\]", "", text)
    text = re.sub(r"[^0-9a-z]+", "_", text).strip("_")
    return text


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, float):
        return math.isnan(value)
    try:
        return bool(value != value)
    except Exception:
        return False


def _clean_text(value: Any, field_name: str, row_number: int) -> str:
    if _is_missing(value):
        raise CoupledCalculationError(f"row {row_number}: {field_name} is required")
    text = str(value).strip()
    if not text:
        raise CoupledCalculationError(f"row {row_number}: {field_name} is required")
    return text


def _clean_float(value: Any, field_name: str, row_number: int, *, scale: float = 1.0) -> float:
    if _is_missing(value):
        raise CoupledCalculationError(f"row {row_number}: {field_name} is required")
    try:
        numeric = float(value) * scale
    except Exception as exc:
        raise CoupledCalculationError(f"row {row_number}: {field_name} must be numeric") from exc
    if not math.isfinite(numeric):
        raise CoupledCalculationError(f"row {row_number}: {field_name} must be finite")
    return numeric


def _build_normalized_column_map(columns: list[Any]) -> dict[str, str]:
    normalized_to_original: dict[str, str] = {}
    for column in columns:
        normalized = normalize_table_column_name(column)
        if normalized in normalized_to_original:
            raise CoupledCalculationError(
                f"ambiguous duplicate columns: {normalized_to_original[normalized]!r}, {column!r}"
            )
        if normalized:
            normalized_to_original[normalized] = str(column)
    return normalized_to_original


def _resolve_alias_column(
    normalized_to_original: Mapping[str, str],
    aliases: tuple[str, ...],
) -> str | None:
    matched = list(dict.fromkeys(
        normalized_to_original[normalize_table_column_name(alias)]
        for alias in aliases if normalize_table_column_name(alias) in normalized_to_original
    ))
    if len(matched) > 1:
        raise CoupledCalculationError(f"ambiguous columns for {aliases[0]}: {', '.join(matched)}")
    return matched[0] if matched else None


def _column_unit_scale(column: str, field: str) -> float:
    """Validate declared units and convert to the legacy field's expected unit.

    Bare canonical columns keep their existing units. A neutral name such as
    ``Product Moles`` can declare mmol; a unit-bearing name such as
    ``amount_mol`` cannot also declare a conflicting unit in parentheses.
    """
    units = {
        "product_moles": {"mol": 1.0, "mmol": 1e-3, "umol": 1e-6, "nmol": 1e-9},
        "charge_coulomb": {"C": 1.0, "c": 1.0, "coulomb": 1.0, "mC": 1e-3, "mc": 1e-3, "uC": 1e-6, "uc": 1e-6},
        "current_ampere": {"A": 1.0, "a": 1.0, "ampere": 1.0, "mA": 1e-3, "ma": 1e-3, "uA": 1e-6, "ua": 1e-6},
        "electrolysis_time_s": {"s": 1.0, "sec": 1.0, "seconds": 1.0, "min": 60.0, "minutes": 60.0, "h": 3600.0, "hours": 3600.0},
        "electron_count": {"1": 1.0, "count": 1.0, "dimensionless": 1.0},
    }
    dimension = {"current_milliampere": "current_ampere", "electrolysis_time_min": "electrolysis_time_s"}.get(field, field)
    if dimension not in units:
        return 1.0
    default_scale = {"current_milliampere": 1e-3, "electrolysis_time_min": 60.0}.get(field, 1.0)
    text = str(column).replace("（", "(").replace("）", ")").replace("μ", "u").replace("µ", "u")
    declarations = [left or right for left, right in re.findall(r"\(([^)]*)\)|\[([^]]*)\]", text)]
    if not declarations:
        return 1.0
    scales = []
    for declaration in declarations:
        unit = declaration.strip()
        if unit not in units[dimension]:
            raise CoupledCalculationError(f"unsupported unit {unit!r} for {field} in column {column!r}")
        scales.append(units[dimension][unit])
    if len(set(scales)) != 1:
        raise CoupledCalculationError(f"conflicting units in column {column!r}")
    neutral_names = {
        "product_moles": {"product_moles", "moles"},
        "charge_coulomb": {"charge", "q"},
        "current_ampere": {"current", "i"},
        "electrolysis_time_s": {"time", "duration", "electrolysis_time"},
        "electron_count": set(PRODUCT_QUANTIFICATION_FIELD_ALIASES["electron_count"]),
    }
    if normalize_table_column_name(column) not in neutral_names.get(field, set()) and scales[0] != default_scale:
        raise CoupledCalculationError(f"conflicting unit suffix and declaration in column {column!r}")
    return scales[0] / default_scale


def _resolve_required_columns(columns: list[Any]) -> dict[str, str]:
    normalized_to_original = _build_normalized_column_map(columns)
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for field, aliases in PRODUCT_QUANTIFICATION_FIELD_ALIASES.items():
        if field == "charge_coulomb":
            continue
        matched_column = _resolve_alias_column(normalized_to_original, aliases)
        if matched_column is None:
            missing.append(field)
        else:
            resolved[field] = matched_column

    charge_column = _resolve_alias_column(normalized_to_original, PRODUCT_QUANTIFICATION_FIELD_ALIASES["charge_coulomb"])
    if charge_column:
        resolved["charge_coulomb"] = charge_column
    else:
        current_a_column = _resolve_alias_column(normalized_to_original, DERIVED_CHARGE_FIELD_ALIASES["current_ampere"])
        current_ma_column = _resolve_alias_column(normalized_to_original, DERIVED_CHARGE_FIELD_ALIASES["current_milliampere"])
        time_s_column = _resolve_alias_column(normalized_to_original, DERIVED_CHARGE_FIELD_ALIASES["electrolysis_time_s"])
        time_min_column = _resolve_alias_column(normalized_to_original, DERIVED_CHARGE_FIELD_ALIASES["electrolysis_time_min"])
        if current_a_column and current_ma_column:
            raise CoupledCalculationError("ambiguous current columns: specify one current unit")
        if time_s_column and time_min_column:
            raise CoupledCalculationError("ambiguous time columns: specify one time unit")
        if (current_a_column or current_ma_column) and (time_s_column or time_min_column):
            if current_a_column:
                resolved["current_ampere"] = current_a_column
            else:
                resolved["current_milliampere"] = current_ma_column or ""
            if time_s_column:
                resolved["electrolysis_time_s"] = time_s_column
            else:
                resolved["electrolysis_time_min"] = time_min_column or ""
        else:
            missing.append("charge_coulomb or current/time")

    if missing:
        raise CoupledCalculationError(
            "missing required product quantification columns: " + ", ".join(missing)
        )
    return resolved


def _metadata_from_row(
    row: Mapping[str, Any],
    *,
    required_columns: set[str],
    source_path: str | None,
    row_number: int,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"source_row": row_number}
    if source_path:
        metadata["source_table"] = source_path
    for column, value in row.items():
        if column in required_columns or _is_missing(value):
            continue
        metadata[normalize_table_column_name(column) or str(column)] = value.item() if hasattr(value, "item") else value
    return metadata


def _resolve_charge_coulomb(
    row: Mapping[str, Any],
    column_map: Mapping[str, str],
    row_number: int,
    unit_scales: Mapping[str, float],
) -> tuple[float, dict[str, Any]]:
    def value(field: str) -> float:
        return _clean_float(row.get(column_map[field]), field, row_number, scale=unit_scales[field])

    if "charge_coulomb" in column_map:
        return value("charge_coulomb"), {}
    if "current_ampere" in column_map:
        current_a = value("current_ampere")
    else:
        current_ma = value("current_milliampere")
        current_a = current_ma / 1000.0
    if "electrolysis_time_s" in column_map:
        time_s = value("electrolysis_time_s")
    else:
        time_min = value("electrolysis_time_min")
        time_s = time_min * 60.0
    if time_s <= 0:
        raise CoupledCalculationError(f"row {row_number}: electrolysis_time must be greater than 0")
    charge = abs(current_a) * time_s
    if not math.isfinite(charge):
        raise CoupledCalculationError(f"row {row_number}: derived charge_coulomb must be finite")
    return charge, {
        "charge_source": "current_time",
        "current_ampere": current_a,
        "electrolysis_time_s": time_s,
    }


def product_quantifications_from_dataframe(
    dataframe: Any,
    *,
    source_path: str | None = None,
) -> list[ProductQuantification]:
    """Convert a pandas-like dataframe into ProductQuantification inputs."""
    if dataframe is None or len(dataframe.index) == 0:
        return []
    column_map = _resolve_required_columns(list(dataframe.columns))
    unit_scales = {field: _column_unit_scale(column, field) for field, column in column_map.items()}
    required_columns = set(column_map.values())
    output: list[ProductQuantification] = []
    for zero_based_index, row in dataframe.iterrows():
        row_number = int(zero_based_index) + 2 if isinstance(zero_based_index, int) else len(output) + 2
        row_dict = row.to_dict()
        if all(_is_missing(row_dict.get(column)) for column in required_columns):
            continue
        charge_coulomb, charge_metadata = _resolve_charge_coulomb(row_dict, column_map, row_number, unit_scales)
        metadata = _metadata_from_row(
            row_dict,
            required_columns=required_columns,
            source_path=source_path,
            row_number=row_number,
        )
        metadata.update(charge_metadata)
        output.append(
            ProductQuantification(
                sample_name=_clean_text(row_dict.get(column_map["sample_name"]), "sample_name", row_number),
                product_name=_clean_text(row_dict.get(column_map["product_name"]), "product_name", row_number),
                product_moles=_clean_float(
                    row_dict.get(column_map["product_moles"]), "product_moles", row_number,
                    scale=unit_scales["product_moles"],
                ),
                electron_count=_clean_float(row_dict.get(column_map["electron_count"]), "electron_count", row_number),
                charge_coulomb=charge_coulomb,
                metadata=metadata,
            )
        )
    return output


def read_product_quantification_dataframe(path: str | os.PathLike[str], *, sheet_name: str | int = 0) -> pd.DataFrame:
    """Read a product quantification table from CSV/TSV/TXT or Excel."""
    table_path = Path(path)
    suffix = table_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(table_path, sheet_name=sheet_name)
    if suffix in {".csv", ".tsv", ".txt"}:
        for encoding in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
            try:
                return pd.read_csv(table_path, sep=None, engine="python", encoding=encoding)
            except UnicodeDecodeError:
                continue
        return pd.read_csv(table_path, sep=None, engine="python", encoding="latin-1")
    raise CoupledCalculationError(f"unsupported product quantification table format: {suffix or '<none>'}")


def read_product_quantification_table(
    path: str | os.PathLike[str],
    *,
    sheet_name: str | int = 0,
) -> list[ProductQuantification]:
    """Read product quantification inputs from a table file."""
    table_path = Path(path)
    dataframe = read_product_quantification_dataframe(table_path, sheet_name=sheet_name)
    return product_quantifications_from_dataframe(dataframe, source_path=str(table_path))


__all__ = [
    "PRODUCT_QUANTIFICATION_FIELD_ALIASES",
    "DERIVED_CHARGE_FIELD_ALIASES",
    "REQUIRED_PRODUCT_QUANTIFICATION_FIELDS",
    "normalize_table_column_name",
    "product_quantifications_from_dataframe",
    "read_product_quantification_dataframe",
    "read_product_quantification_table",
]
