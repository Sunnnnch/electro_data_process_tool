"""Peak-based product quantification feeding the generic COUPLED/FE engine."""

from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from electrochem_v6.core.processing_coupled import export_coupled_results_csv
from electrochem_v6.core.processing_coupled_calc import (
    calculate_coupled_product_results,
    coupled_results_to_processing_results,
)
from electrochem_v6.core.processing_coupled_io import (
    normalize_table_column_name,
    read_product_quantification_dataframe,
)
from electrochem_v6.core.processing_coupled_models import (
    CoupledCalculationError,
    ProductQuantification,
)
from electrochem_v6.core.processing_formula import formulas_for_run
from electrochem_v6.core.processing_peak_quant import (
    PeakDefinition,
    PeakMeasurement,
    PeakQuantificationError,
    PeakQuantificationOptions,
    quantify_with_reference,
    read_signal_trace,
)
from electrochem_v6.core.utils import as_bool

FE_PEAK_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class FEProductPeakMethod:
    """Reaction-specific product definition and its quantitative peak."""

    product_name: str
    electron_count: float
    peak: PeakDefinition
    reaction_id: str = ""
    response_factor: float = 1.0


@dataclass(frozen=True)
class FEPeakMethod:
    """Validated qNMR internal-standard method."""

    method_id: str
    axis_unit: str
    internal_standard: PeakDefinition
    internal_standard_concentration_mM: float
    internal_standard_volume_uL: float
    products: tuple[FEProductPeakMethod, ...]
    electrolyte_volume_mL: float
    sample_aliquot_volume_uL: float
    source_payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FEPeakMeasurementRow:
    """One electrolysis sample linked to one exported signal trace."""

    sample_name: str
    signal_file: str
    charge_coulomb: float
    electrolyte_volume_mL: float
    sample_aliquot_volume_uL: float
    internal_standard_concentration_mM: float
    internal_standard_volume_uL: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FEPeakDiagnostic:
    """Peak and qNMR calculation provenance for one product result."""

    sample_name: str
    product_name: str
    signal_file: str
    charge_coulomb: float
    reference_shift: float
    reference: PeakMeasurement
    product: PeakMeasurement
    area_ratio: float
    product_moles: float
    status: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        reference = self.reference.to_dict()
        product = self.product.to_dict()
        return {
            "sample_name": self.sample_name,
            "product_name": self.product_name,
            "signal_file": self.signal_file,
            "charge_coulomb": self.charge_coulomb,
            "reference_shift": self.reference_shift,
            "reference_expected_position": reference["expected_position"],
            "reference_found_position": reference["found_position"],
            "reference_area": reference["area"],
            "reference_snr": reference["snr"],
            "product_expected_position": product["expected_position"],
            "product_aligned_expected_position": product["aligned_expected_position"],
            "product_found_position": product["found_position"],
            "product_search_min": product["search_min"],
            "product_search_max": product["search_max"],
            "product_quantification_min": product["quantification_min"],
            "product_quantification_max": product["quantification_max"],
            "product_area": product["area"],
            "product_snr": product["snr"],
            "product_candidate_count": product["candidate_count"],
            "product_fit_r2": product["fit_r2"],
            "quantification_method": product["method"],
            "area_ratio": self.area_ratio,
            "product_moles": self.product_moles,
            "status": self.status,
            "warnings": list(self.warnings),
        }


MEASUREMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "sample_name": ("sample_name", "sample", "sample_id", "sampleid"),
    "signal_file": ("signal_file", "spectrum_file", "nmr_file", "peak_file", "trace_file"),
    "charge_coulomb": ("charge_coulomb", "charge_c", "charge", "q_c", "q"),
    "current_ampere": ("current_a", "current_ampere", "current_amp", "i_a"),
    "current_milliampere": ("current_ma", "current_milliampere", "current_mamp", "i_ma"),
    "electrolysis_time_s": ("time_s", "duration_s", "electrolysis_time_s"),
    "electrolysis_time_min": ("time_min", "duration_min", "electrolysis_time_min"),
    "electrolyte_volume_mL": ("electrolyte_volume_ml", "total_volume_ml", "electrolyte_ml"),
    "sample_aliquot_volume_uL": ("sample_aliquot_volume_ul", "aliquot_volume_ul", "sample_volume_ul"),
    "internal_standard_concentration_mM": (
        "internal_standard_concentration_mm",
        "is_concentration_mm",
        "standard_concentration_mm",
    ),
    "internal_standard_volume_uL": (
        "internal_standard_volume_ul",
        "is_volume_ul",
        "standard_volume_ul",
    ),
}


def _finite_float(value: Any, name: str, *, positive: bool = False) -> float:
    try:
        number = float(value)
    except Exception as exc:
        raise CoupledCalculationError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise CoupledCalculationError(f"{name} must be finite")
    if positive and number <= 0:
        raise CoupledCalculationError(f"{name} must be greater than 0")
    return number


def _optional_override(mapping: Mapping[str, Any], key: str) -> float | None:
    value = mapping.get(key)
    if value in (None, ""):
        return None
    return _finite_float(value, key, positive=True)


def peak_options_from_params(params: Mapping[str, Any] | None) -> PeakQuantificationOptions:
    values = dict(params or {})
    return PeakQuantificationOptions(
        auto_locate=as_bool(values.get("fe_peak_auto_locate", True), True),
        reference_align=as_bool(values.get("fe_peak_reference_align", True), True),
        fit_enabled=as_bool(values.get("fe_peak_fit_enabled", False), False),
        min_detection_snr=_finite_float(
            values.get("fe_peak_min_detection_snr", 3.0), "fe_peak_min_detection_snr", positive=True
        ),
        min_quantification_snr=_finite_float(
            values.get("fe_peak_min_quantification_snr", 10.0),
            "fe_peak_min_quantification_snr",
            positive=True,
        ),
        search_tolerance_override=_optional_override(values, "fe_peak_search_tolerance"),
        window_left_override=_optional_override(values, "fe_peak_window_left"),
        window_right_override=_optional_override(values, "fe_peak_window_right"),
    )


def _peak_definition(payload: Mapping[str, Any], *, default_name: str) -> PeakDefinition:
    name = str(payload.get("name") or default_name).strip()
    if not name:
        raise CoupledCalculationError("peak name is required")
    return PeakDefinition(
        name=name,
        expected_position=_finite_float(payload.get("expected_position"), f"{name}.expected_position"),
        nuclei_count=_finite_float(payload.get("nuclei_count", 1.0), f"{name}.nuclei_count", positive=True),
        search_tolerance=_finite_float(
            payload.get("search_tolerance", 0.08), f"{name}.search_tolerance", positive=True
        ),
        window_left=_finite_float(payload.get("window_left", 0.05), f"{name}.window_left", positive=True),
        window_right=_finite_float(payload.get("window_right", 0.05), f"{name}.window_right", positive=True),
        polarity=str(payload.get("polarity") or "positive").strip().lower(),
    )


def _validate_method_peak_windows(
    reference: PeakDefinition,
    products: Sequence[FEProductPeakMethod],
) -> None:
    definitions = (reference, *(item.peak for item in products))
    for left_index, left in enumerate(definitions):
        left_bounds = (
            left.expected_position - left.window_left,
            left.expected_position + left.window_right,
        )
        for right in definitions[left_index + 1 :]:
            right_bounds = (
                right.expected_position - right.window_left,
                right.expected_position + right.window_right,
            )
            if min(left_bounds[1], right_bounds[1]) > max(left_bounds[0], right_bounds[0]):
                raise CoupledCalculationError(
                    f"FE peak method quantification windows overlap: {left.name} and {right.name}"
                )


def parse_fe_peak_method(
    payload: Mapping[str, Any],
    *,
    source_name: str = "panel",
) -> FEPeakMethod:
    """Validate a peak-based qNMR method supplied by a file or the UI."""
    if not isinstance(payload, Mapping):
        raise CoupledCalculationError("FE peak method must be an object")
    schema_version = str(payload.get("schema_version") or FE_PEAK_SCHEMA_VERSION)
    if schema_version != FE_PEAK_SCHEMA_VERSION:
        raise CoupledCalculationError(f"unsupported FE peak method schema_version: {schema_version}")
    analysis_method = str(payload.get("analysis_method") or "qnmr_internal_standard").strip().lower()
    if analysis_method != "qnmr_internal_standard":
        raise CoupledCalculationError(f"unsupported FE peak analysis_method: {analysis_method}")

    internal_payload = payload.get("internal_standard")
    if not isinstance(internal_payload, Mapping):
        raise CoupledCalculationError("internal_standard must be configured")
    internal_standard = _peak_definition(internal_payload, default_name="internal_standard")
    standard_concentration = _finite_float(
        internal_payload.get("concentration_mM"),
        "internal_standard.concentration_mM",
        positive=True,
    )
    standard_volume = _finite_float(
        internal_payload.get("volume_uL"),
        "internal_standard.volume_uL",
        positive=True,
    )

    product_payloads = payload.get("products")
    if not isinstance(product_payloads, list) or not product_payloads:
        raise CoupledCalculationError("FE peak method requires at least one product")
    products: list[FEProductPeakMethod] = []
    seen_names: set[str] = set()
    for index, item in enumerate(product_payloads, start=1):
        if not isinstance(item, Mapping):
            raise CoupledCalculationError(f"products[{index}] must be an object")
        product_name = str(item.get("name") or item.get("product_name") or "").strip()
        if not product_name:
            raise CoupledCalculationError(f"products[{index}].name is required")
        normalized_name = product_name.casefold()
        if normalized_name in seen_names:
            raise CoupledCalculationError(f"duplicate product in FE peak method: {product_name}")
        seen_names.add(normalized_name)
        products.append(
            FEProductPeakMethod(
                product_name=product_name,
                electron_count=_finite_float(
                    item.get("electron_count"), f"{product_name}.electron_count", positive=True
                ),
                peak=_peak_definition(item, default_name=product_name),
                reaction_id=str(item.get("reaction_id") or "").strip(),
                response_factor=_finite_float(
                    item.get("response_factor", 1.0), f"{product_name}.response_factor", positive=True
                ),
            )
        )

    _validate_method_peak_windows(internal_standard, products)

    defaults = payload.get("sample_defaults")
    defaults = defaults if isinstance(defaults, Mapping) else {}
    return FEPeakMethod(
        method_id=str(payload.get("method_id") or source_name or "panel").strip(),
        axis_unit=str(payload.get("axis_unit") or "ppm").strip(),
        internal_standard=internal_standard,
        internal_standard_concentration_mM=standard_concentration,
        internal_standard_volume_uL=standard_volume,
        products=tuple(products),
        electrolyte_volume_mL=_finite_float(
            defaults.get("electrolyte_volume_mL"), "sample_defaults.electrolyte_volume_mL", positive=True
        ),
        sample_aliquot_volume_uL=_finite_float(
            defaults.get("sample_aliquot_volume_uL"),
            "sample_defaults.sample_aliquot_volume_uL",
            positive=True,
        ),
        source_payload=dict(payload),
    )


def load_fe_peak_method(path: str | os.PathLike[str]) -> FEPeakMethod:
    """Load and validate a peak-based qNMR method JSON file."""
    method_path = Path(path)
    try:
        payload = json.loads(method_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise CoupledCalculationError(f"failed to read FE peak method {method_path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise CoupledCalculationError("FE peak method must be a JSON object")
    return parse_fe_peak_method(payload, source_name=method_path.stem)


def resolve_fe_peak_method(
    method_file: str | os.PathLike[str] | None = None,
    *,
    method_payload: Mapping[str, Any] | None = None,
) -> FEPeakMethod:
    """Resolve one method source while keeping file-based workflows compatible."""
    if method_payload is not None:
        return parse_fe_peak_method(method_payload, source_name="panel")
    if method_file is None or not str(method_file).strip():
        raise CoupledCalculationError("FE peak method file or panel configuration is required")
    return load_fe_peak_method(method_file)


def _column_map(columns: Sequence[Any]) -> dict[str, str]:
    normalized = {normalize_table_column_name(column): str(column) for column in columns}
    output: dict[str, str] = {}
    for field_name, aliases in MEASUREMENT_ALIASES.items():
        for alias in aliases:
            matched = normalized.get(normalize_table_column_name(alias))
            if matched:
                output[field_name] = matched
                break
    return output


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def _row_value(
    row: Mapping[str, Any],
    columns: Mapping[str, str],
    field_name: str,
    default: Any = None,
) -> Any:
    column = columns.get(field_name)
    if not column:
        return default
    value = row.get(column)
    return default if _missing(value) else value


def _charge_from_row(row: Mapping[str, Any], columns: Mapping[str, str], row_number: int) -> tuple[float, dict[str, Any]]:
    supplied = _row_value(row, columns, "charge_coulomb")
    if supplied is not None:
        charge = _finite_float(supplied, f"row {row_number}: charge_coulomb", positive=True)
        return charge, {"charge_source": "supplied_charge"}
    current_a = _row_value(row, columns, "current_ampere")
    if current_a is None:
        current_ma = _row_value(row, columns, "current_milliampere")
        if current_ma is not None:
            current_a = _finite_float(current_ma, f"row {row_number}: current_mA") / 1000.0
    if current_a is None:
        raise CoupledCalculationError(f"row {row_number}: charge_C or current/time is required")
    current_a = _finite_float(current_a, f"row {row_number}: current_A")
    duration_s = _row_value(row, columns, "electrolysis_time_s")
    if duration_s is None:
        duration_min = _row_value(row, columns, "electrolysis_time_min")
        if duration_min is not None:
            duration_s = _finite_float(duration_min, f"row {row_number}: time_min", positive=True) * 60.0
    if duration_s is None:
        raise CoupledCalculationError(f"row {row_number}: charge_C or current/time is required")
    duration_s = _finite_float(duration_s, f"row {row_number}: time_s", positive=True)
    return abs(current_a) * duration_s, {
        "charge_source": "current_time",
        "current_ampere": current_a,
        "electrolysis_time_s": duration_s,
    }


def read_fe_peak_measurements(
    path: str | os.PathLike[str],
    *,
    method: FEPeakMethod,
    sheet_name: str | int = 0,
    allowed_signal_roots: Sequence[str | os.PathLike[str]] | None = None,
) -> list[FEPeakMeasurementRow]:
    """Read sample-to-signal mappings and qNMR preparation values."""
    table_path = Path(path)
    roots = tuple(
        Path(root).expanduser().resolve()
        for root in (allowed_signal_roots or (table_path.parent,))
    )
    dataframe = read_product_quantification_dataframe(table_path, sheet_name=sheet_name)
    if dataframe.empty:
        return []
    columns = _column_map(list(dataframe.columns))
    missing = [field for field in ("sample_name", "signal_file") if field not in columns]
    if missing:
        raise CoupledCalculationError("missing FE peak measurement columns: " + ", ".join(missing))
    has_charge = "charge_coulomb" in columns
    has_current = "current_ampere" in columns or "current_milliampere" in columns
    has_time = "electrolysis_time_s" in columns or "electrolysis_time_min" in columns
    if not has_charge and not (has_current and has_time):
        raise CoupledCalculationError("missing FE peak measurement charge_C or current/time columns")

    output: list[FEPeakMeasurementRow] = []
    used_columns = set(columns.values())
    for index, series in dataframe.iterrows():
        row_number = int(index) + 2 if isinstance(index, int) else len(output) + 2
        row = series.to_dict()
        sample_value = _row_value(row, columns, "sample_name")
        signal_value = _row_value(row, columns, "signal_file")
        if sample_value is None and signal_value is None:
            continue
        sample_name = str(sample_value or "").strip()
        if not sample_name:
            raise CoupledCalculationError(f"row {row_number}: sample_name is required")
        signal_text = str(signal_value or "").strip()
        if not signal_text:
            raise CoupledCalculationError(f"row {row_number}: signal_file is required")
        signal_path = Path(os.path.expanduser(signal_text))
        if not signal_path.is_absolute():
            signal_path = table_path.parent / signal_path
        signal_path = signal_path.resolve()
        if not any(signal_path == root or root in signal_path.parents for root in roots):
            raise CoupledCalculationError(
                f"row {row_number}: signal_file is outside the allowed data roots: {signal_path}"
            )
        if not signal_path.is_file():
            raise CoupledCalculationError(f"row {row_number}: signal_file not found: {signal_path}")
        charge, charge_metadata = _charge_from_row(row, columns, row_number)
        metadata: dict[str, Any] = {
            "source_table": str(table_path),
            "source_row": row_number,
            **charge_metadata,
        }
        for column, value in row.items():
            if column in used_columns or _missing(value):
                continue
            metadata[normalize_table_column_name(column) or str(column)] = (
                value.item() if hasattr(value, "item") else value
            )
        output.append(
            FEPeakMeasurementRow(
                sample_name=sample_name,
                signal_file=str(signal_path),
                charge_coulomb=charge,
                electrolyte_volume_mL=_finite_float(
                    _row_value(
                        row,
                        columns,
                        "electrolyte_volume_mL",
                        method.electrolyte_volume_mL,
                    ),
                    f"row {row_number}: electrolyte_volume_mL",
                    positive=True,
                ),
                sample_aliquot_volume_uL=_finite_float(
                    _row_value(
                        row,
                        columns,
                        "sample_aliquot_volume_uL",
                        method.sample_aliquot_volume_uL,
                    ),
                    f"row {row_number}: sample_aliquot_volume_uL",
                    positive=True,
                ),
                internal_standard_concentration_mM=_finite_float(
                    _row_value(
                        row,
                        columns,
                        "internal_standard_concentration_mM",
                        method.internal_standard_concentration_mM,
                    ),
                    f"row {row_number}: internal_standard_concentration_mM",
                    positive=True,
                ),
                internal_standard_volume_uL=_finite_float(
                    _row_value(
                        row,
                        columns,
                        "internal_standard_volume_uL",
                        method.internal_standard_volume_uL,
                    ),
                    f"row {row_number}: internal_standard_volume_uL",
                    positive=True,
                ),
                metadata=metadata,
            )
        )
    return output


def _product_moles_from_qnmr(
    *,
    product_area: float,
    product_nuclei: float,
    reference_area: float,
    reference_nuclei: float,
    standard_concentration_mM: float,
    standard_volume_uL: float,
    sample_aliquot_volume_uL: float,
    electrolyte_volume_mL: float,
    response_factor: float,
) -> tuple[float, float]:
    normalized_ratio = (product_area / product_nuclei) / (reference_area / reference_nuclei)
    internal_standard_moles = standard_concentration_mM * 1e-3 * standard_volume_uL * 1e-6
    aliquot_product_moles = normalized_ratio * internal_standard_moles * response_factor
    scale_to_electrolyte = (electrolyte_volume_mL * 1000.0) / sample_aliquot_volume_uL
    product_moles = aliquot_product_moles * scale_to_electrolyte
    if not math.isfinite(product_moles) or product_moles < 0:
        raise CoupledCalculationError("calculated product moles are invalid")
    return product_moles, normalized_ratio


def inspect_fe_peak_inputs(
    measurements_file: str | os.PathLike[str],
    method_file: str | os.PathLike[str] | None = None,
    *,
    method_payload: Mapping[str, Any] | None = None,
    sheet_name: str | int = 0,
    allowed_signal_roots: Sequence[str | os.PathLike[str]] | None = None,
) -> dict[str, Any]:
    """Validate the method and sample mapping without running peak fitting."""
    try:
        method = resolve_fe_peak_method(method_file, method_payload=method_payload)
        rows = read_fe_peak_measurements(
            measurements_file,
            method=method,
            sheet_name=sheet_name,
            allowed_signal_roots=allowed_signal_roots,
        )
    except (CoupledCalculationError, PeakQuantificationError, OSError, ValueError) as exc:
        return {"ok": False, "errors": [str(exc)], "warnings": []}
    warnings: list[str] = []
    if len(rows) < 3:
        warnings.append("fewer_than_three_measurements")
    return {
        "ok": bool(rows),
        "errors": [] if rows else ["FE peak measurement table has no valid rows"],
        "warnings": warnings,
        "method_id": method.method_id,
        "axis_unit": method.axis_unit,
        "measurement_rows": len(rows),
        "signal_files": len({row.signal_file for row in rows}),
        "products": [item.product_name for item in method.products],
    }


def _write_diagnostics_csv(path: Path, diagnostics: Sequence[FEPeakDiagnostic]) -> str:
    rows = [item.to_dict() for item in diagnostics]
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else ["sample_name", "product_name", "status"]
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                    for key, value in row.items()
                }
            )
    return str(path)


def process_fe_peak_file(
    measurements_file: str | os.PathLike[str],
    method_file: str | os.PathLike[str] | None = None,
    *,
    method_payload: Mapping[str, Any] | None = None,
    output_dir: str | os.PathLike[str],
    csv_filename: str = "coupled_results.csv",
    sheet_name: str | int = 0,
    params: Mapping[str, Any] | None = None,
    project_id: str | None = None,
    run_id: str | None = None,
    allowed_signal_roots: Sequence[str | os.PathLike[str]] | None = None,
) -> dict[str, Any]:
    """Quantify product peaks, calculate FE/selectivity, and export provenance."""
    method = resolve_fe_peak_method(method_file, method_payload=method_payload)
    rows = read_fe_peak_measurements(
        measurements_file,
        method=method,
        sheet_name=sheet_name,
        allowed_signal_roots=allowed_signal_roots,
    )
    if not rows:
        raise CoupledCalculationError("FE peak measurement table has no valid rows")
    options = peak_options_from_params(params)

    quantified: list[ProductQuantification] = []
    diagnostics: list[FEPeakDiagnostic] = []
    quality_reports: list[dict[str, Any]] = []
    product_peak_definitions = tuple(item.peak for item in method.products)
    for row in rows:
        try:
            x, y = read_signal_trace(row.signal_file)
            reference, product_peaks, reference_shift = quantify_with_reference(
                x,
                y,
                reference=method.internal_standard,
                products=product_peak_definitions,
                options=options,
            )
        except (PeakQuantificationError, OSError, ValueError) as exc:
            raise CoupledCalculationError(f"{row.sample_name}: {exc}") from exc

        for product_method, product_peak in zip(method.products, product_peaks):
            product_moles, area_ratio = _product_moles_from_qnmr(
                product_area=product_peak.area,
                product_nuclei=product_method.peak.nuclei_count,
                reference_area=reference.area,
                reference_nuclei=method.internal_standard.nuclei_count,
                standard_concentration_mM=row.internal_standard_concentration_mM,
                standard_volume_uL=row.internal_standard_volume_uL,
                sample_aliquot_volume_uL=row.sample_aliquot_volume_uL,
                electrolyte_volume_mL=row.electrolyte_volume_mL,
                response_factor=product_method.response_factor,
            )
            warnings = tuple(dict.fromkeys((*reference.warnings, *product_peak.warnings)))
            status = "warning" if warnings else "pass"
            diagnostic = FEPeakDiagnostic(
                sample_name=row.sample_name,
                product_name=product_method.product_name,
                signal_file=row.signal_file,
                charge_coulomb=row.charge_coulomb,
                reference_shift=reference_shift,
                reference=reference,
                product=product_peak,
                area_ratio=area_ratio,
                product_moles=product_moles,
                status=status,
                warnings=warnings,
            )
            diagnostics.append(diagnostic)
            quality_reports.append(
                {
                    "data_type": "COUPLED",
                    "sample_name": row.sample_name,
                    "product_name": product_method.product_name,
                    "level": status,
                    "warnings": list(warnings),
                    "reference_shift": reference_shift,
                    "product_snr": product_peak.snr,
                    "fit_r2": product_peak.fit_r2,
                }
            )
            quantified.append(
                ProductQuantification(
                    sample_name=row.sample_name,
                    product_name=product_method.product_name,
                    product_moles=product_moles,
                    electron_count=product_method.electron_count,
                    charge_coulomb=row.charge_coulomb,
                    metadata={
                        **dict(row.metadata),
                        "analysis_method": "qnmr_internal_standard",
                        "method_id": method.method_id,
                        "reaction_id": product_method.reaction_id,
                        "axis_unit": method.axis_unit,
                        "signal_file": row.signal_file,
                        "reference_shift": reference_shift,
                        "reference_area": reference.area,
                        "product_area": product_peak.area,
                        "area_ratio": area_ratio,
                        "peak_status": status,
                        "peak_warnings": list(warnings),
                    },
                )
            )

    calculated = calculate_coupled_product_results(quantified)
    result_lookup = {
        (item.sample_name, item.product_name): item
        for item in calculated
    }
    total_fe_by_sample: dict[str, float] = {}
    for item in calculated:
        total_fe_by_sample[item.sample_name] = (
            total_fe_by_sample.get(item.sample_name, 0.0) + item.faradaic_efficiency_pct
        )
    for report in quality_reports:
        calculated_item = result_lookup.get((str(report.get("sample_name")), str(report.get("product_name"))))
        if calculated_item is None:
            continue
        total_fe = total_fe_by_sample.get(calculated_item.sample_name, calculated_item.faradaic_efficiency_pct)
        warnings = list(report.get("warnings") or [])
        if total_fe > 100.0 + 1e-6:
            warnings.append("total_fe_above_100_pct")
        report["warnings"] = list(dict.fromkeys(warnings))
        report["faradaic_efficiency_pct"] = calculated_item.faradaic_efficiency_pct
        report["total_sample_fe_pct"] = total_fe
        report["level"] = "warning" if report["warnings"] else "pass"
        report["is_valid"] = True
        report["quality_level"] = "warning" if report["warnings"] else "good"
        report["recommendation"] = "review_peak_diagnostics" if report["warnings"] else "accept"
    formula_params = {"coupled_input_mode": "peak_analysis", **dict(params or {})}
    processing_results = coupled_results_to_processing_results(
        calculated,
        project_id=project_id,
        run_id=run_id,
        formula_keys=[item["key"] for item in formulas_for_run(["COUPLED"], formula_params)],
    )
    output_path = Path(output_dir)
    results_csv = export_coupled_results_csv(calculated, output_path / csv_filename)
    diagnostics_csv = _write_diagnostics_csv(output_path / "fe_peak_diagnostics.csv", diagnostics)
    result_json = output_path / "fe_peak_results.json"
    result_json.write_text(
        json.dumps(
            {
                "schema_version": FE_PEAK_SCHEMA_VERSION,
                "method": dict(method.source_payload),
                "options": {
                    "auto_locate": options.auto_locate,
                    "reference_align": options.reference_align,
                    "fit_enabled": options.fit_enabled,
                    "min_detection_snr": options.min_detection_snr,
                    "min_quantification_snr": options.min_quantification_snr,
                    "search_tolerance_override": options.search_tolerance_override,
                    "window_left_override": options.window_left_override,
                    "window_right_override": options.window_right_override,
                },
                "diagnostics": [item.to_dict() for item in diagnostics],
                "results": [item.to_dict() for item in calculated],
                "quality_reports": quality_reports,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return {
        "input_rows": len(rows),
        "rows": len(calculated),
        "results": calculated,
        "processing_results": processing_results,
        "coupled_results_csv": results_csv,
        "fe_peak_diagnostics_csv": diagnostics_csv,
        "fe_peak_results_json": str(result_json),
        "quality_reports": quality_reports,
        "method_id": method.method_id,
        "products": [item.product_name for item in method.products],
    }


__all__ = [
    "FEPeakDiagnostic",
    "FEPeakMeasurementRow",
    "FEPeakMethod",
    "FEProductPeakMethod",
    "FE_PEAK_SCHEMA_VERSION",
    "inspect_fe_peak_inputs",
    "load_fe_peak_method",
    "parse_fe_peak_method",
    "peak_options_from_params",
    "process_fe_peak_file",
    "read_fe_peak_measurements",
    "resolve_fe_peak_method",
]
