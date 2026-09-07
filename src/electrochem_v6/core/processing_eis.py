"""EIS processing orchestration."""

from __future__ import annotations

from typing import Any, Mapping

from . import processing_core_v6 as core
from .processing_common import build_file_context
from .processing_eis_calc import _randles_impedance, evaluate_eis_circuit_fit, fit_randles
from .processing_eis_history import add_eis_history_record, build_eis_history_record
from .processing_eis_io import read_eis_raw_data
from .processing_eis_plot import plot_eis_bode, plot_eis_nyquist
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


def _metric(label: str, value: Any, *, key: str | None = None) -> MetricValue:
    resolved = resolve_metric("EIS", label, fallback_key=key)
    return MetricValue(
        key=resolved.key,
        label=resolved.label,
        value=value,
        unit=resolved.unit,
        method=resolved.method,
        metadata=resolved.metadata,
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
        metrics.extend(
            [
                _metric("Rs", randles_result.get("Rs"), key="rs_ohm"),
                _metric("Rct", randles_result.get("Rct"), key="rct_ohm"),
                _metric("randles_r2", randles_result.get("r2"), key="randles_r2"),
                _metric("fit_rmse", randles_result.get("rmse_complex_ohm"), key="fit_rmse_ohm"),
            ]
        )
        if randles_result.get("model") == "randles_cpe":
            metrics.extend(
                [
                    _metric("CPE Q", randles_result.get("Q"), key="cpe_q"),
                    _metric("CPE n", randles_result.get("n"), key="cpe_n"),
                ]
            )
        else:
            metrics.append(_metric("Cdl", randles_result.get("Cdl"), key="cdl_f"))
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
        },
    }


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
    fit_requested = as_bool(params.get("randles_fit", False), False)
    if fit_requested:
        try:
            fit_diagnostics = evaluate_eis_circuit_fit(
                frequency,
                z_real,
                z_imag,
                model=str(params.get("eis_circuit_model", "randles_rc")),
                min_r2=float(params.get("eis_fit_min_r2", 0.5)),
            )
            if fit_diagnostics.get("accepted"):
                randles_result = fit_diagnostics
            else:
                log(f"Equivalent-circuit fit not accepted: {fit_diagnostics.get('rejection_reason')}")
        except Exception as exc:
            fit_diagnostics = {
                "model": str(params.get("eis_circuit_model", "randles_rc")),
                "accepted": False,
                "status": "fit_failed",
                "rejection_reason": str(exc),
            }
            log(f"Equivalent-circuit fit failed for {file}: {exc}")

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
                randles_result=randles_result,
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
            )
        )

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
            )
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
        "metadata": {
            "module": "direct_eis",
            "parse_errors": raw_eis.parse_errors,
            "data_points": len(frequency),
            "equivalent_circuit_fit": fit_diagnostics,
        },
    }


__all__ = ["_randles_impedance", "fit_randles", "process_eis"]
