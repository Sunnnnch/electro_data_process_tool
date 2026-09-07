"""CV processing orchestration."""

from __future__ import annotations

from typing import Any

import pandas as pd

from . import processing_core_v6 as core
from .processing_common import build_file_context
from .processing_cv_calc import compute_cv_metrics, parse_cycle_selection, split_cv_cycles
from .processing_cv_history import add_cv_history_record, build_cv_history_record
from .processing_cv_io import read_cv_raw_data
from .processing_cv_plot import plot_cv_curve
from .processing_metric_registry import resolve_metric
from .processing_quality import DataQualityChecker
from .processing_result_models import MetricValue, ProcessingResult, SourceFileRef
from .processing_source_profile import (
    CURRENT_TO_MA,
    POTENTIAL_TO_V,
    column_number_to_index,
    unit_scale,
)
from .utils import as_bool, as_int

_resolve_plot_font = core._resolve_plot_font
HISTORY_MANAGER_AVAILABLE = core.HISTORY_MANAGER_AVAILABLE
PROJECT_MANAGER_AVAILABLE = core.PROJECT_MANAGER_AVAILABLE
get_history_manager = core.get_history_manager
get_project_manager = core.get_project_manager
log = core.log


def _metric(label: str, value: Any, *, key: str | None = None) -> MetricValue:
    resolved = resolve_metric("CV", label, fallback_key=key)
    return MetricValue(
        key=resolved.key,
        label=resolved.label,
        value=value,
        unit=resolved.unit,
        method=resolved.method,
        metadata=resolved.metadata,
    )


def _build_cv_metrics(potential, current, metrics) -> tuple[MetricValue, ...]:
    values: list[MetricValue] = [
        _metric("data_points", len(potential), key="data_points"),
        _metric("potential_min_v", min(potential), key="potential_min_v"),
        _metric("potential_max_v", max(potential), key="potential_max_v"),
        _metric("current_min_mA", min(current), key="current_min_mA"),
        _metric("current_max_mA", max(current), key="current_max_mA"),
        _metric("peak_count", len(metrics.peaks), key="peak_count"),
    ]
    if metrics.charge_mC_rounded is not None:
        values.append(_metric("charge_mC", metrics.charge_mC_rounded, key="charge_mC"))
    if metrics.delta_ep_mV is not None:
        values.append(_metric("delta_ep_mV", metrics.delta_ep_mV, key="delta_ep_mV"))
    return tuple(values)


def _fallback_quality_report(*, sample_name: str, file_name: str, data_points: int, parse_errors: int) -> dict[str, Any]:
    warnings: list[str] = []
    if data_points < 10:
        warnings.append("CV data point count is low.")
    if parse_errors:
        warnings.append(f"Skipped {parse_errors} unparsable rows.")
    return {
        "filename": f"{sample_name}/{file_name}" if sample_name else file_name,
        "is_valid": True,
        "warnings": warnings,
        "issues": [],
        "quality_level": "warning" if warnings else "normal",
        "recommendation": "review_cv_input" if warnings else "none",
        "stats": {
            "data_points": data_points,
            "parse_errors": parse_errors,
        },
    }


def process_cv(subfolder, file, params, enable_quality_check=True):
    """Process a CV data file and return quality/metric metadata."""
    ctx = build_file_context(subfolder, file, params)

    potential_column = column_number_to_index(
        params.get("cv_potential_column", 1), default=1, label="CV potential column"
    )
    current_column = column_number_to_index(
        params.get("cv_current_column", 2), default=2, label="CV current column"
    )
    potential_unit, potential_scale = unit_scale(
        params.get("cv_potential_unit"), default="v", supported=POTENTIAL_TO_V
    )
    current_unit, current_scale = unit_scale(
        params.get("cv_current_unit"), default="a", supported=CURRENT_TO_MA
    )

    raw_cv = read_cv_raw_data(
        ctx.filepath,
        start_line=params.get("start_line", 1),
        potential_column=potential_column,
        current_column=current_column,
        potential_scale=potential_scale,
        current_scale=current_scale,
        logger=log,
    )
    if raw_cv is None:
        log(f"Unable to read valid CV data from {ctx.filepath}")
        return None

    potential = raw_cv.potential
    current = raw_cv.current

    cv_quality_report = None
    if enable_quality_check:
        try:
            df = pd.DataFrame(
                {
                    "Potential": potential,
                    "Current": current,
                }
            )
            display_name = f"{ctx.sample_name}/{file}" if ctx.sample_name else file
            cv_quality_report = DataQualityChecker.check_cv_data(
                df,
                display_name,
                config=params.get("quality_config"),
            )
        except Exception as exc:
            log(f"CV quality check failed; continuing: {exc}")

    metrics = compute_cv_metrics(potential, current, params, logger=log)
    font_to_use = _resolve_plot_font(params.get("font"))
    artifact = plot_cv_curve(
        potential=potential,
        current=current,
        peaks=metrics.peaks,
        delta_ep=metrics.delta_ep,
        params=params,
        sample_name=ctx.sample_name,
        file_stem=ctx.file_stem,
        output_dir=ctx.output_dir,
        font_name=font_to_use,
    )
    artifacts = [artifact]
    cycle_plot_warnings: list[str] = []
    selected_cycle_numbers: list[int] = []
    detected_cycle_count = 0
    if as_bool(params.get("cycle_plot_enabled", params.get("cv_cycle_plot_enabled", False)), False):
        cycles = split_cv_cycles(
            potential,
            current,
            reversal_tolerance=params.get("cv_cycle_reversal_tolerance"),
            min_segment_points=params.get("cv_cycle_min_segment_points", 3),
        )
        detected_cycle_count = len(cycles)
        requested_numbers = parse_cycle_selection(params.get("cycle_numbers", params.get("cv_cycle_numbers", "")))
        selected = [cycle for cycle in cycles if not requested_numbers or cycle.number in requested_numbers]
        selected_cycle_numbers = [cycle.number for cycle in selected]
        missing = [number for number in requested_numbers if number not in selected_cycle_numbers]
        if not cycles:
            cycle_plot_warnings.append("No full CV cycles were detected for separate cycle plotting.")
        elif cycles[-1].end_index < len(potential) - 1:
            cycle_plot_warnings.append("The trailing incomplete CV cycle was excluded from separate cycle plots; the full curve retains all points.")
        if missing:
            cycle_plot_warnings.append(f"Requested CV cycles were not detected: {', '.join(map(str, missing))}.")
        for cycle in selected:
            cycle_params = dict(params)
            cycle_params["title"] = f"{params.get('title', 'CV of {sample}')} - Cycle {cycle.number}"
            cycle_metrics = compute_cv_metrics(cycle.potential, cycle.current, cycle_params, logger=log)
            artifacts.append(
                plot_cv_curve(
                    potential=cycle.potential,
                    current=cycle.current,
                    peaks=cycle_metrics.peaks,
                    delta_ep=cycle_metrics.delta_ep,
                    params=cycle_params,
                    sample_name=ctx.sample_name,
                    file_stem=f"{ctx.file_stem}_cycle{cycle.number}",
                    output_dir=ctx.output_dir,
                    font_name=font_to_use,
                )
            )

    if cv_quality_report is None:
        cv_quality_report = _fallback_quality_report(
            sample_name=ctx.sample_name,
            file_name=ctx.filename,
            data_points=len(potential),
            parse_errors=raw_cv.parse_errors,
        )
    if cycle_plot_warnings:
        warnings = list(cv_quality_report.get("warnings") or [])
        warnings.extend(cycle_plot_warnings)
        cv_quality_report["warnings"] = warnings
        cv_quality_report["quality_level"] = "warning"
        if cv_quality_report.get("recommendation") in (None, "", "none"):
            cv_quality_report["recommendation"] = "review_cv_cycle_selection"

    processing_result = ProcessingResult(
        data_type="CV",
        sample_name=ctx.sample_name,
        source=SourceFileRef(
            sample_name=ctx.sample_name,
            file_name=ctx.filename,
            path=ctx.filepath,
            data_type="CV",
        ),
        metrics=_build_cv_metrics(potential, current, metrics),
        artifacts=tuple(artifacts),
        project_id=params.get("project_id"),
        run_id=params.get("run_id"),
        metadata={
            "module": "direct_cv",
            "parse_errors": raw_cv.parse_errors,
            "scan_rate_v_s": params.get("scan_rate_v_s", params.get("cv_scan_rate_v_s")),
            "charge_method": "absolute_current_time_integral" if metrics.charge_mC is not None else None,
            "source_profile": {
                "potential_column": potential_column + 1,
                "current_column": current_column + 1,
                "potential_unit": potential_unit,
                "current_unit": current_unit,
                "normalized_potential_unit": "V",
                "normalized_current_unit": "mA",
            },
            "peaks_enabled": as_bool(params.get("peaks_enabled", False), False),
            "cycle_plot_enabled": as_bool(
                params.get("cycle_plot_enabled", params.get("cv_cycle_plot_enabled", False)),
                False,
            ),
            "detected_cycles": detected_cycle_count,
            "selected_cycles": selected_cycle_numbers,
            "cycle_reversal_tolerance": params.get("cv_cycle_reversal_tolerance") or "auto",
            "cycle_min_segment_points": as_int(params.get("cv_cycle_min_segment_points", 3), 3),
        },
    )

    if HISTORY_MANAGER_AVAILABLE:
        try:
            history_mgr = get_history_manager()
            project_manager = get_project_manager() if PROJECT_MANAGER_AVAILABLE else None
            record = build_cv_history_record(
                sample_name=ctx.sample_name,
                file_stem=ctx.file_stem,
                file_path=ctx.filepath,
                params=params,
                potential=potential,
                current=current,
                delta_ep_mV=metrics.delta_ep_mV,
                charge_mC=metrics.charge_mC_rounded,
                project_manager=project_manager,
            )
            add_cv_history_record(
                history_mgr,
                record,
                log_func=log,
                sample_name=ctx.sample_name,
                file_stem=ctx.file_stem,
            )
        except Exception as exc:
            log(f"Failed to save CV history record: {exc}")

    return {
        "quality_report": cv_quality_report,
        "processing_result": processing_result,
        "artifacts": artifacts,
        "delta_ep_mV": metrics.delta_ep_mV,
        "charge_mC": metrics.charge_mC_rounded,
    }


__all__ = ["process_cv"]
