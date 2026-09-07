"""Workflow helpers for coupled electrochemical calculations."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from electrochem_v6.core.processing_coupled_calc import (
    calculate_coupled_product_results,
    coupled_results_to_processing_results,
)
from electrochem_v6.core.processing_coupled_io import read_product_quantification_table
from electrochem_v6.core.processing_coupled_models import CoupledProductResult
from electrochem_v6.core.processing_registry import (
    COUPLED_INPUT_MODES,
    COUPLED_PEAK_METHOD_SOURCES,
)
from electrochem_v6.core.processing_result_models import ProcessingResult

COUPLED_RESULT_COLUMNS = [
    "sample_name",
    "product_name",
    "product_moles",
    "electron_count",
    "charge_coulomb",
    "faradaic_efficiency_pct",
    "product_selectivity_pct",
    "fe_selectivity_pct",
    "metadata",
]


def _metadata_text(metadata: Any) -> str:
    if not metadata:
        return ""
    return json.dumps(dict(metadata), ensure_ascii=False, sort_keys=True, default=str)


def build_coupled_quality_reports(
    results: Sequence[CoupledProductResult],
    *,
    source_file: str | os.PathLike[str] | None = None,
) -> list[dict[str, Any]]:
    """Build sample-level FE closure checks for every input strategy."""
    totals: dict[str, float] = {}
    products: dict[str, int] = {}
    for item in results:
        totals[item.sample_name] = totals.get(item.sample_name, 0.0) + float(item.faradaic_efficiency_pct)
        products[item.sample_name] = products.get(item.sample_name, 0) + 1

    reports: list[dict[str, Any]] = []
    for sample_name, total_fe in totals.items():
        warnings = ["total_fe_above_100_pct"] if total_fe > 100.0 + 1e-6 else []
        reports.append(
            {
                "filename": str(source_file or sample_name),
                "sample_name": sample_name,
                "is_valid": True,
                "warnings": warnings,
                "issues": [],
                "quality_level": "warning" if warnings else "good",
                "recommendation": "review_charge_and_quantification" if warnings else "accept",
                "stats": {
                    "product_count": products[sample_name],
                    "total_sample_fe_pct": total_fe,
                },
                "total_sample_fe_pct": total_fe,
            }
        )
    return reports


def export_coupled_results_csv(
    results: Sequence[CoupledProductResult],
    output_path: str | os.PathLike[str],
) -> str:
    """Write product-level coupled results as a wide CSV."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COUPLED_RESULT_COLUMNS)
        writer.writeheader()
        for result in results:
            row = result.to_dict()
            row["metadata"] = _metadata_text(row.get("metadata"))
            writer.writerow({column: row.get(column) for column in COUPLED_RESULT_COLUMNS})
    return str(path)


def process_coupled_products_file(
    products_file: str | os.PathLike[str],
    *,
    output_dir: str | os.PathLike[str],
    csv_filename: str = "coupled_results.csv",
    sheet_name: str | int = 0,
    project_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Read a product table, calculate FE/selectivity, and export results."""
    output_path = Path(output_dir) / csv_filename
    quantified = read_product_quantification_table(products_file, sheet_name=sheet_name)
    calculated = calculate_coupled_product_results(quantified)
    csv_path = export_coupled_results_csv(calculated, output_path)
    quality_reports = build_coupled_quality_reports(calculated, source_file=products_file)
    processing_results: list[ProcessingResult] = coupled_results_to_processing_results(
        calculated,
        project_id=project_id,
        run_id=run_id,
    )
    return {
        "input_rows": len(quantified),
        "rows": len(calculated),
        "results": calculated,
        "processing_results": processing_results,
        "coupled_results_csv": csv_path,
        "quality_reports": quality_reports,
    }


def normalize_coupled_input_mode(value: Any) -> str:
    """Normalize public aliases while preserving the legacy table default."""
    normalized = str(value or "product_table").strip().lower()
    aliases = {
        "products": "product_table",
        "generic": "product_table",
        "generic_products": "product_table",
        "peak": "peak_analysis",
        "peaks": "peak_analysis",
        "qnmr": "peak_analysis",
        "analytical_peaks": "peak_analysis",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in COUPLED_INPUT_MODES:
        raise ValueError(f"unsupported COUPLED input mode: {normalized}")
    return normalized


def normalize_coupled_peak_method_source(
    value: Any,
    *,
    method_payload: Mapping[str, Any] | None = None,
) -> str:
    """Normalize the peak-method source, preferring inline data when supplied."""
    default = "panel" if isinstance(method_payload, Mapping) else "file"
    normalized = str(value or default).strip().lower()
    aliases = {
        "inline": "panel",
        "form": "panel",
        "json": "file",
        "method_file": "file",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in COUPLED_PEAK_METHOD_SOURCES:
        raise ValueError(f"unsupported FE peak method source: {normalized}")
    return normalized


def process_coupled_input(
    products_file: str | os.PathLike[str],
    *,
    input_mode: str = "product_table",
    peak_method_file: str | os.PathLike[str] | None = None,
    peak_method_source: str | None = None,
    peak_method_payload: Mapping[str, Any] | None = None,
    output_dir: str | os.PathLike[str],
    csv_filename: str = "coupled_results.csv",
    sheet_name: str | int = 0,
    params: dict[str, Any] | None = None,
    project_id: str | None = None,
    run_id: str | None = None,
    allowed_signal_roots: Sequence[str | os.PathLike[str]] | None = None,
) -> dict[str, Any]:
    """Dispatch a stable COUPLED input contract to the selected quantification strategy."""
    mode = normalize_coupled_input_mode(input_mode)
    if mode == "product_table":
        return process_coupled_products_file(
            products_file,
            output_dir=output_dir,
            csv_filename=csv_filename,
            sheet_name=sheet_name,
            project_id=project_id,
            run_id=run_id,
        )
    method_source = normalize_coupled_peak_method_source(
        peak_method_source,
        method_payload=peak_method_payload,
    )
    method_file = str(peak_method_file or "").strip()
    if method_source == "file" and not method_file:
        raise ValueError("coupled_peak_method_file is required for file-based peak_analysis")
    if method_source == "panel" and not isinstance(peak_method_payload, Mapping):
        raise ValueError("coupled_peak_method is required for panel-based peak_analysis")
    from electrochem_v6.core.processing_fe_peak import process_fe_peak_file

    return process_fe_peak_file(
        products_file,
        method_file or None,
        method_payload=peak_method_payload if method_source == "panel" else None,
        output_dir=output_dir,
        csv_filename=csv_filename,
        sheet_name=sheet_name,
        params=params,
        project_id=project_id,
        run_id=run_id,
        allowed_signal_roots=allowed_signal_roots,
    )


__all__ = [
    "COUPLED_INPUT_MODES",
    "COUPLED_PEAK_METHOD_SOURCES",
    "COUPLED_RESULT_COLUMNS",
    "build_coupled_quality_reports",
    "export_coupled_results_csv",
    "normalize_coupled_input_mode",
    "normalize_coupled_peak_method_source",
    "process_coupled_input",
    "process_coupled_products_file",
]
