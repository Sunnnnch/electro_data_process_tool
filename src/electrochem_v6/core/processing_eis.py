"""EIS processing orchestration."""

from __future__ import annotations

import csv
import json
import math
import os
from typing import Any, Mapping

from . import processing_core_v6 as core
from .job_control import ProcessingCancelledError, check_cancelled
from .processing_common import build_file_context
from .processing_eis_calc import _randles_impedance, evaluate_eis_circuit_fit, fit_randles
from .processing_eis_history import add_eis_history_record, build_eis_history_record
from .processing_eis_io import read_eis_raw_data
from .processing_eis_plot import plot_eis_bode, plot_eis_nyquist, plot_eis_residuals
from .processing_eis_validation import validate_eis_kk
from .processing_metric_registry import resolve_metric
from .processing_result_models import MetricValue, ProcessingResult, SourceFileRef
from .processing_source_profile import (
    FREQUENCY_TO_HZ,
    IMPEDANCE_TO_OHM,
    column_number_to_index,
    imaginary_convention,
    unit_scale,
)
from .utils import as_bool

_resolve_plot_font = core._resolve_plot_font
HISTORY_MANAGER_AVAILABLE = core.HISTORY_MANAGER_AVAILABLE
PROJECT_MANAGER_AVAILABLE = core.PROJECT_MANAGER_AVAILABLE
get_history_manager = core.get_history_manager
get_project_manager = core.get_project_manager
log = core.log


def _metric(label: str, value: Any, *, key: str | None = None,
            unit: str | None = None, metadata: Mapping[str, Any] | None = None) -> MetricValue:
    resolved = resolve_metric("EIS", label, fallback_key=key)
    return MetricValue(
        key=resolved.key,
        label=resolved.label,
        value=value,
        unit=unit if unit is not None else resolved.unit,
        method=resolved.method,
        metadata={**resolved.metadata, **dict(metadata or {})},
    )


def _build_eis_metrics(
    *,
    frequency: list[float],
    randles_result: Mapping[str, Any] | None,
) -> tuple[MetricValue, ...]:
    metrics: list[MetricValue] = [
        _metric("data_points", len(frequency), key="data_points"),
        _metric("frequency_min_hz", min(frequency), key="frequency_min_hz"),
        _metric("frequency_max_hz", max(frequency), key="frequency_max_hz"),
    ]
    if randles_result:
        names = {
            "Rs": ("Rs", "rs_ohm"), "Rct": ("Rct", "rct_ohm"), "Cdl": ("Cdl", "cdl_f"),
            "Q": ("CPE Q", "cpe_q"), "n": ("CPE n", "cpe_n"), "sigma": ("Warburg sigma", "warburg_sigma"),
            "R1": ("R1", "r1_ohm"), "R2": ("R2", "r2_ohm"), "C1": ("C1", "c1_f"), "C2": ("C2", "c2_f"),
            "Q1": ("Q1", "q1"), "Q2": ("Q2", "q2"), "n1": ("n1", "n1"), "n2": ("n2", "n2"),
        }
        units = randles_result.get("parameter_units", {})
        intervals = randles_result.get("parameter_ci95", {})
        for name, (label, key) in names.items():
            if randles_result.get(name) is not None:
                metrics.append(_metric(label, randles_result[name], key=key, unit=units.get(name), metadata={
                    "circuit_model": randles_result.get("model"),
                    "ci95": intervals.get(name), "review_required": randles_result.get("review_required", False),
                }))
        metrics.extend([
            _metric("randles_r2", randles_result.get("r2"), key="randles_r2"),
            _metric("fit_rmse", randles_result.get("rmse_complex_ohm"), key="fit_rmse_ohm", unit="Ohm"),
        ])
    return tuple(metrics)


def _build_quality_report(
    *,
    sample_name: str,
    file_name: str,
    data_points: int,
    parse_errors: int,
    randles_requested: bool,
    randles_result: Mapping[str, Any] | None,
    fit_diagnostics: Mapping[str, Any] | None = None,
    kk_validation: Mapping[str, Any] | None = None,
    frequency_selection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    issues: list[str] = []
    if data_points < 5:
        warnings.append("EIS data point count is low.")
    if parse_errors:
        warnings.append(f"Skipped {parse_errors} unparsable rows.")
    if randles_requested and randles_result is None:
        reason = str((fit_diagnostics or {}).get("rejection_reason") or "fit failed")
        warnings.append(f"Equivalent-circuit fit was requested but not accepted: {reason}.")
    for reason in (fit_diagnostics or {}).get("review_reasons", []):
        warnings.append(f"EIS fit review: {reason}")
    if kk_validation and kk_validation.get("status") != "consistent":
        warnings.append(f"KK consistency {kk_validation.get('status')}: {kk_validation.get('reason')}")

    return {
        "filename": f"{sample_name}/{file_name}" if sample_name else file_name,
        "is_valid": not issues,
        "warnings": warnings,
        "issues": issues,
        "quality_level": "warning" if warnings else "normal",
        "recommendation": "review_eis_input" if warnings else "none",
        "stats": {
            "data_points": data_points,
            "parse_errors": parse_errors,
            "randles_fit": bool(randles_result),
            "fit_status": (fit_diagnostics or {}).get("status") if randles_requested else "not_requested",
            "fit_model": (fit_diagnostics or {}).get("model") if randles_requested else None,
            "fit_review_required": bool((fit_diagnostics or {}).get("review_required")),
            "kk_status": (kk_validation or {}).get("status", "not_requested"),
            "selected_points": (frequency_selection or {}).get("selected_points", data_points),
        },
    }


def select_eis_frequency(frequency, z_real, z_imag, params):
    """Select a closed interval in normalized Hz without rewriting the source."""
    bounds = []
    for key in ("eis_fit_frequency_min_hz", "eis_fit_frequency_max_hz"):
        raw = params.get(key)
        value = None if raw is None or str(raw).strip() == "" else float(raw)
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise ValueError(f"{key} must be finite and greater than zero")
        bounds.append(value)
    low, high = bounds
    if low is not None and high is not None and low > high:
        raise ValueError("EIS fit minimum frequency must not exceed maximum frequency")
    indices = [i for i, value in enumerate(frequency)
               if (low is None or value >= low) and (high is None or value <= high)]
    selected = [frequency[i] for i in indices]
    selection = {"requested_min_hz": low, "requested_max_hz": high,
                 "actual_min_hz": min(selected) if selected else None,
                 "actual_max_hz": max(selected) if selected else None,
                 "total_points": len(frequency), "selected_points": len(indices),
                 "excluded_points": len(frequency) - len(indices), "selected_indices": indices,
                 "index_basis": "zero_based_valid_parsed_points", "interval": "closed", "unit": "Hz"}
    return selected, [z_real[i] for i in indices], [z_imag[i] for i in indices], selection


def _export_eis_analysis(ctx, frequency, z_real, z_imag, analysis):
    """Persist diagnostics and residuals with explicit units and point provenance."""
    stem = os.path.join(ctx.output_dir, f"{ctx.sample_name}_{ctx.file_stem}_EIS")
    json_path = stem + "_Diagnostics.json"
    with open(json_path, "w", encoding="utf-8") as stream:
        json.dump(analysis, stream, ensure_ascii=False, indent=2, allow_nan=False)
    csv_path = stem + "_Residuals.csv"
    fit, kk = analysis.get("fit") or {}, analysis.get("kk") or {}
    def at(mapping, key, index):
        values = mapping.get(key) or []
        return values[index] if index < len(values) else ""
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["parsed_point_index", "frequency_hz", "z_real_ohm", "z_imag_ohm",
                         "fit_z_real_ohm", "fit_z_imag_ohm", "fit_residual_real_ohm", "fit_residual_imag_ohm",
                         "kk_residual_real_relative", "kk_residual_imag_relative"])
        indices = analysis["frequency_selection"]["selected_indices"]
        for i, value in enumerate(frequency):
            writer.writerow([indices[i], value, z_real[i], z_imag[i],
                at(fit, "z_fit_real", i), at(fit, "z_fit_imag", i),
                at(fit, "residual_real_ohm", i), at(fit, "residual_imag_ohm", i),
                at(kk, "residual_real", i), at(kk, "residual_imag", i)])
    return [json_path, csv_path]


def process_eis(subfolder, file, params):
    """Process an EIS data file and write configured plots/history.

    The legacy caller ignored the return value. New module callers use the
    returned normalized payload for reports, exports, and extension APIs.
    """
    ctx = build_file_context(subfolder, file, params)

    frequency_column = column_number_to_index(
        params.get("eis_frequency_column", 1), default=1, label="EIS frequency column"
    )
    zreal_column = column_number_to_index(
        params.get("eis_zreal_column", 2), default=2, label="EIS Z-real column"
    )
    zimag_column = column_number_to_index(
        params.get("eis_zimag_column", 3), default=3, label="EIS Z-imaginary column"
    )
    frequency_unit, frequency_scale = unit_scale(
        params.get("eis_frequency_unit"), default="hz", supported=FREQUENCY_TO_HZ
    )
    impedance_unit, impedance_scale = unit_scale(
        params.get("eis_impedance_unit"), default="ohm", supported=IMPEDANCE_TO_OHM
    )
    zimag_convention, zimag_sign = imaginary_convention(
        params.get("eis_zimag_convention", "z_imaginary")
    )

    raw_eis = read_eis_raw_data(
        ctx.filepath,
        start_line=params.get("start_line", 1),
        frequency_column=frequency_column,
        zreal_column=zreal_column,
        zimag_column=zimag_column,
        frequency_scale=frequency_scale,
        impedance_scale=impedance_scale,
        zimag_sign=zimag_sign,
        logger=log,
    )
    if raw_eis is None:
        log(f"Unable to read valid EIS data from {ctx.filepath}")
        return None

    frequency = raw_eis.frequency
    z_real = raw_eis.z_real
    z_imag = raw_eis.z_imag

    randles_result = None
    fit_diagnostics: dict[str, Any] | None = None
    kk_validation = None
    fit_requested = as_bool(params.get("randles_fit", params.get("eis_randles_fit", False)), False)
    kk_requested = as_bool(params.get("eis_kk_check", False), False)
    selected_f, selected_r, selected_i, selection = select_eis_frequency(frequency, z_real, z_imag,
        params if fit_requested or kk_requested else {})
    if fit_requested:
        try:
            fit_diagnostics = evaluate_eis_circuit_fit(
                selected_f,
                selected_r,
                selected_i,
                model=str(params.get("eis_circuit_model", "randles_rc")),
                min_r2=float(params.get("eis_fit_min_r2", 0.5)),
                weighting=str(params.get("eis_fit_weighting", "uniform")),
                cancel_check=lambda: check_cancelled(params),
            )
            fit_diagnostics["frequency_hz"] = selected_f
            if fit_diagnostics.get("accepted"):
                randles_result = fit_diagnostics
            else:
                log(f"Equivalent-circuit fit not accepted: {fit_diagnostics.get('rejection_reason')}")
        except ProcessingCancelledError:
            raise
        except Exception as exc:
            check_cancelled(params)
            fit_diagnostics = {
                "model": str(params.get("eis_circuit_model", "randles_rc")),
                "accepted": False,
                "status": "fit_failed",
                "rejection_reason": str(exc),
            }
            log(f"Equivalent-circuit fit failed for {file}: {exc}")
    check_cancelled(params)
    if kk_requested:
        kk_validation = validate_eis_kk(selected_f, selected_r, selected_i)
    check_cancelled(params)
    analysis = {"fit": fit_diagnostics, "kk": kk_validation, "frequency_selection": selection}

    font_to_use = _resolve_plot_font(params.get("font"))
    artifacts: list[str] = []
    if as_bool(params.get("plot_nyquist", True), True):
        artifacts.append(
            plot_eis_nyquist(
                z_real=z_real,
                z_imag=z_imag,
                params=params,
                sample_name=ctx.sample_name,
                file_stem=ctx.file_stem,
                output_dir=ctx.output_dir,
                font_name=font_to_use,
                randles_result=fit_diagnostics,
            )
        )

    if as_bool(params.get("plot_bode", False), False):
        artifacts.append(
            plot_eis_bode(
                frequency=frequency,
                z_real=z_real,
                z_imag=z_imag,
                params=params,
                sample_name=ctx.sample_name,
                file_stem=ctx.file_stem,
                output_dir=ctx.output_dir,
                font_name=font_to_use,
                fit_result=fit_diagnostics,
            )
        )
    if fit_requested or kk_requested:
        artifacts.extend(_export_eis_analysis(ctx, selected_f, selected_r, selected_i, analysis))
        if as_bool(params.get("plot_eis_residuals", True), True) and (
            (fit_diagnostics or {}).get("z_fit_real") or (kk_validation or {}).get("z_fit_real")
        ):
            artifacts.append(plot_eis_residuals(frequency=selected_f, fit_result=fit_diagnostics,
                kk_validation=kk_validation, params=params, sample_name=ctx.sample_name,
                file_stem=ctx.file_stem, output_dir=ctx.output_dir, font_name=font_to_use))

    processing_result = ProcessingResult(
        data_type="EIS",
        sample_name=ctx.sample_name,
        source=SourceFileRef(
            sample_name=ctx.sample_name,
            file_name=ctx.filename,
            path=ctx.filepath,
            data_type="EIS",
        ),
        metrics=_build_eis_metrics(frequency=frequency, randles_result=randles_result),
        artifacts=tuple(artifacts),
        project_id=params.get("project_id"),
        run_id=params.get("run_id"),
        metadata={
            "module": "direct_eis",
            "parse_errors": raw_eis.parse_errors,
            "randles_fit": bool(randles_result),
            "equivalent_circuit_fit": fit_diagnostics,
            "kk_validation": kk_validation,
            "frequency_selection": selection,
            "source_profile": {
                "frequency_column": frequency_column + 1,
                "zreal_column": zreal_column + 1,
                "zimag_column": zimag_column + 1,
                "frequency_unit": frequency_unit,
                "impedance_unit": impedance_unit,
                "zimag_convention": zimag_convention,
                "normalized_frequency_unit": "Hz",
                "normalized_impedance_unit": "Ohm",
            },
        },
    )
    quality_report = _build_quality_report(
        sample_name=ctx.sample_name,
        file_name=ctx.filename,
        data_points=len(frequency),
        parse_errors=raw_eis.parse_errors,
        randles_requested=fit_requested,
        randles_result=randles_result,
        fit_diagnostics=fit_diagnostics,
        kk_validation=kk_validation,
        frequency_selection=selection,
    )

    if HISTORY_MANAGER_AVAILABLE:
        try:
            history_mgr = get_history_manager()
            project_manager = get_project_manager() if PROJECT_MANAGER_AVAILABLE else None
            record = build_eis_history_record(
                sample_name=ctx.sample_name,
                file_stem=ctx.file_stem,
                file_path=ctx.filepath,
                params=params,
                frequency=frequency,
                z_real=z_real,
                randles_result=randles_result,
                project_manager=project_manager,
                analysis=analysis,
            )
            record["quality_summary"] = quality_report
            add_eis_history_record(
                history_mgr,
                record,
                log_func=log,
                sample_name=ctx.sample_name,
                file_stem=ctx.file_stem,
            )
        except Exception as exc:
            log(f"Failed to save EIS history record: {exc}")
    return {
        "processing_result": processing_result,
        "artifacts": artifacts,
        "quality_report": quality_report,
        "randles_result": randles_result,
        "fit_diagnostics": fit_diagnostics,
        "kk_validation": kk_validation,
        "metadata": {
            "module": "direct_eis",
            "parse_errors": raw_eis.parse_errors,
            "data_points": len(frequency),
            "equivalent_circuit_fit": fit_diagnostics,
            "kk_validation": kk_validation,
            "frequency_selection": selection,
        },
    }


__all__ = ["_randles_impedance", "fit_randles", "process_eis"]
