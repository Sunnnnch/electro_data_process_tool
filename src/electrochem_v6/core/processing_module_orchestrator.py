"""Batch orchestration through the runtime processing-module registry."""

from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Any, Mapping, Sequence

from electrochem_v6.config import APP_VERSION, ensure_parent_dir, get_quality_report_file
from electrochem_v6.core.job_control import ProcessingCancelledError, check_cancelled
from electrochem_v6.core.processing_module_contract import ModuleRunContext, ModuleRunResult
from electrochem_v6.core.processing_module_runtime import (
    ProcessingModuleRegistry,
    get_processing_module_registry,
)
from electrochem_v6.core.processing_result_export import export_processing_results_csv
from electrochem_v6.core.processing_result_models import ProcessingResult
from electrochem_v6.store._json_utils import atomic_write_json


def _dedupe(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _safe_csv_filename(value: Any, default: str) -> str:
    text = str(value or default).strip()
    if not text or os.path.basename(text) != text or text in {".", ".."}:
        text = default
    if not text.lower().endswith(".csv"):
        text += ".csv"
    return text


def _wide_result_records(results: Sequence[ProcessingResult]) -> tuple[list[str], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    metric_keys: list[str] = []
    for result in results:
        source = result.source
        record: dict[str, Any] = {
            "sample_name": result.sample_name,
            "file_name": source.file_name if source else "",
            "source_path": source.path if source else "",
        }
        for metric in result.metrics:
            key = str(metric.key)
            if key not in metric_keys:
                metric_keys.append(key)
            record[key] = metric.value
        records.append(record)
    return ["sample_name", "file_name", "source_path", *metric_keys], records


def _export_wide_results(results: Sequence[ProcessingResult], output_path: str) -> str | None:
    if not results:
        return None
    fields, records = _wide_result_records(results)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    return output_path


def _normalize_quality_report(report: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(report)
    warnings = list(normalized.get("warnings") or [])
    issues = list(normalized.get("issues") or [])
    level = str(normalized.get("level") or normalized.get("quality_level") or "").lower()
    normalized["warnings"] = warnings
    normalized["issues"] = issues
    normalized.setdefault("is_valid", level not in {"error", "failed", "invalid"} and not issues)
    normalized.setdefault("quality_level", "warning" if warnings else ("failed" if issues else "normal"))
    normalized.setdefault("recommendation", "review" if warnings or issues else "none")
    return normalized


def _quality_summary(
    reports: Sequence[Mapping[str, Any]],
    skipped_errors: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    normalized = [_normalize_quality_report(item) for item in reports]
    quality_levels: dict[str, int] = {}
    recommendations: dict[str, int] = {}
    for report in normalized:
        level = str(report.get("quality_level") or "unknown")
        recommendation = str(report.get("recommendation") or "unknown")
        quality_levels[level] = quality_levels.get(level, 0) + 1
        recommendations[recommendation] = recommendations.get(recommendation, 0) + 1
    problem_reports = [
        report
        for report in normalized
        if report.get("warnings") or report.get("issues") or not report.get("is_valid", True)
    ]
    return {
        "total_files": len(normalized),
        "passed": sum(1 for item in normalized if item.get("is_valid", True)),
        "failed": sum(1 for item in normalized if not item.get("is_valid", True)),
        "warnings": sum(1 for item in normalized if item.get("warnings")),
        "skipped": len(skipped_errors),
        "quality_levels": quality_levels,
        "recommendations": recommendations,
        "files": problem_reports,
    }


def _module_skip_errors(data_type: str, result: ModuleRunResult) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for message in result.messages:
        lower = str(message).lower()
        if "skipped" in lower or "no valid" in lower or "failed" in lower:
            errors.append({"type": data_type, "error": str(message)})
    return errors


def run_module_pipeline(
    folder_path: str,
    params: Mapping[str, Any],
    *,
    data_types: Sequence[str],
    registry: ProcessingModuleRegistry | None = None,
) -> dict[str, Any]:
    """Run selected modules and return the legacy-compatible service payload."""

    runtime = registry or get_processing_module_registry()
    selected = runtime.validate_data_types(data_types, default_all=False)
    output_dir = os.path.abspath(str(params.get("output_dir") or folder_path))
    os.makedirs(output_dir, exist_ok=True)
    context = ModuleRunContext(
        folder_path=os.path.abspath(folder_path),
        params=dict(params),
        project_id=str(params.get("project_id") or "") or None,
        run_id=str(params.get("run_id") or "") or None,
        output_dir=output_dir,
    )

    all_results: list[ProcessingResult] = []
    artifacts: list[str] = []
    quality_reports: list[Mapping[str, Any]] = []
    messages: list[str] = []
    skipped_errors: list[dict[str, Any]] = []
    matched_counts = {key: 0 for key in runtime.supported_data_types()}
    module_runs: list[dict[str, Any]] = []
    results_by_type: dict[str, list[ProcessingResult]] = {key: [] for key in selected}
    ir_compensation: list[dict[str, Any]] = []
    combined_lsv_png: str | None = None
    coupled_metadata: dict[str, Any] = {}
    explicit_files = params.get("_selected_files_by_type")

    for data_type in selected:
        check_cancelled(context.params)
        try:
            if isinstance(explicit_files, Mapping) and data_type in explicit_files:
                raw_files = explicit_files.get(data_type)
                files = tuple(str(item) for item in (raw_files or ()) if str(item).strip())
            else:
                files = runtime.detect_module_files(data_type, context)
            matched_counts[data_type] = len(files)
            module_result = runtime.run_module(data_type, context, files)
        except ProcessingCancelledError:
            raise
        except Exception as exc:
            skipped_errors.append({"type": data_type, "error": str(exc)})
            module_runs.append(
                {
                    "data_type": data_type,
                    "matched": matched_counts[data_type],
                    "processed": 0,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            continue

        all_results.extend(module_result.results)
        results_by_type[data_type].extend(module_result.results)
        artifacts.extend(module_result.artifacts)
        quality_reports.extend(module_result.quality_reports)
        messages.extend(module_result.messages)
        skipped_errors.extend(_module_skip_errors(data_type, module_result))
        metadata = dict(module_result.metadata or {})
        if data_type == "LSV":
            ir_items = metadata.get("ir_compensation")
            if isinstance(ir_items, list):
                ir_compensation.extend(dict(item) for item in ir_items if isinstance(item, Mapping))
            combined_value = str(metadata.get("combined_lsv_png") or "").strip()
            combined_lsv_png = combined_value or None
        elif data_type == "COUPLED":
            coupled_metadata = metadata
        module_runs.append(
            {
                "data_type": data_type,
                "matched": len(files),
                "processed": len(module_result.results),
                "status": "success" if module_result.results else "no_result",
                "metadata": metadata,
            }
        )

    artifact_paths = _dedupe(artifacts)
    output_files = list(artifact_paths)
    processing_results_csv = None
    if all_results:
        processing_results_csv = os.path.join(
            output_dir,
            _safe_csv_filename(params.get("processing_results_csv_filename"), "processing_results.csv"),
        )
        export_processing_results_csv(all_results, processing_results_csv)
        output_files.append(processing_results_csv)

    lsv_csv = _export_wide_results(
        results_by_type.get("LSV", []),
        os.path.join(output_dir, _safe_csv_filename(params.get("csv_filename"), "LSV_results.csv")),
    )
    ecsa_csv = _export_wide_results(
        results_by_type.get("ECSA", []),
        os.path.join(output_dir, _safe_csv_filename(params.get("ecsa_csv_filename"), "ECSA_results.csv")),
    )
    output_files.extend(path for path in (lsv_csv, ecsa_csv) if path)

    coupled_results_name = _safe_csv_filename(
        params.get("coupled_results_csv_filename"),
        "coupled_results.csv",
    ).lower()
    coupled_results_csv = next(
        (path for path in artifact_paths if os.path.basename(path).lower() == coupled_results_name),
        None,
    )
    fe_peak_diagnostics_csv = next(
        (path for path in artifact_paths if "peak_diagnostics" in os.path.basename(path).lower()),
        None,
    )
    fe_peak_results_json = next(
        (path for path in artifact_paths if "peak_results" in os.path.basename(path).lower()),
        None,
    )

    quality_summary = _quality_summary(quality_reports, skipped_errors)
    quality_report_path = None
    if quality_reports or skipped_errors:
        quality_report_path = os.path.join(output_dir, "quality_report.json")
        atomic_write_json(quality_report_path, quality_summary)
        output_files.append(quality_report_path)
        try:
            latest_path = str(ensure_parent_dir(get_quality_report_file()))
            atomic_write_json(
                latest_path,
                {
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "data": quality_summary,
                },
            )
        except Exception:
            pass

    summary = {
        "version": APP_VERSION,
        "folder": os.path.abspath(folder_path),
        "output_dir": output_dir,
        "recursive_scan": bool(params.get("recursive_scan", False)),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "runtime": "module_registry",
        "data_types": selected,
        "module_runs": module_runs,
        "lsv": {"csv": lsv_csv, "rows": len(results_by_type.get("LSV", []))},
        "ecsa": {"csv": ecsa_csv, "rows": len(results_by_type.get("ECSA", []))},
        "coupled": {
            **coupled_metadata,
            "csv": coupled_results_csv,
            "rows": len(results_by_type.get("COUPLED", [])),
            "peak_diagnostics_csv": fe_peak_diagnostics_csv,
            "peak_results_json": fe_peak_results_json,
        },
        "combined_lsv_png": combined_lsv_png,
        "processing_results": {
            "csv": processing_results_csv,
            "results": len(all_results),
            "metrics": sum(len(result.metrics) for result in all_results),
        },
        "ir_compensation": ir_compensation,
        "quality_report": quality_report_path,
        "quality_summary": quality_summary,
        "messages": messages,
    }
    summary_path = os.path.join(output_dir, "summary.json")
    atomic_write_json(summary_path, summary)
    output_files.append(summary_path)

    return {
        "messages": messages,
        "lsv_csv": lsv_csv,
        "ecsa_csv": ecsa_csv,
        "coupled_results_csv": coupled_results_csv,
        "fe_peak_diagnostics_csv": fe_peak_diagnostics_csv,
        "fe_peak_results_json": fe_peak_results_json,
        "combined_lsv_png": combined_lsv_png,
        "processing_results_csv": processing_results_csv,
        "summary_path": summary_path,
        "quality_report_path": quality_report_path,
        "output_dir": output_dir,
        "recursive_scan": bool(params.get("recursive_scan", False)),
        "artifact_paths": artifact_paths,
        "output_files": _dedupe(output_files),
        "quality_reports": [dict(item) for item in quality_reports],
        "quality_summary": quality_summary,
        "skipped_errors": skipped_errors,
        "matched_counts": matched_counts,
        "module_runs": module_runs,
        "processing_results": [result.to_dict() for result in all_results],
        "ir_compensation": ir_compensation,
    }


__all__ = ["run_module_pipeline"]
