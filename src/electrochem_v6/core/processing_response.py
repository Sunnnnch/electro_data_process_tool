"""Response and output helpers for processing service results."""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping, Sequence

from electrochem_v6.config import APP_NAME, APP_VERSION

DATA_RESULT_REPORT_NAMES = {
    "summary.json",
    "quality_report.json",
    "latest_quality_report.json",
    "run_manifest.json",
    "run_report.html",
    "run_report.md",
}


def dedupe_keep_order(items: Sequence[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def collect_output_files(
    pipeline_result: Mapping[str, Any],
    *,
    path_exists: Callable[[str], bool] = os.path.exists,
) -> list[str]:
    candidates: list[str] = []
    for key in (
        "summary_path",
        "quality_report_path",
        "lsv_csv",
        "ecsa_csv",
        "coupled_results_csv",
        "combined_lsv_png",
        "processing_results_csv",
        "run_manifest_path",
        "run_report_html_path",
        "run_report_path",
    ):
        value = pipeline_result.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    for key in ("artifact_paths", "output_files"):
        values = pipeline_result.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())
    for msg in pipeline_result.get("messages", []):
        if isinstance(msg, str):
            text = msg.strip()
            if text and path_exists(text):
                candidates.append(text)
    unique = dedupe_keep_order(candidates)
    if unique:
        return unique
    return [str(msg) for msg in pipeline_result.get("messages", []) if str(msg).strip()]


def has_data_output_file(output_files: Sequence[str]) -> bool:
    for item in output_files:
        name = os.path.basename(str(item or "").strip()).lower()
        if not name:
            continue
        if name in DATA_RESULT_REPORT_NAMES or name.endswith("_summary.json") or name.endswith("_quality_report.json"):
            continue
        return True
    return False


def processing_stats(result: Mapping[str, Any], output_files: Sequence[str]) -> dict[str, Any]:
    skipped = result.get("skipped_errors", [])
    skipped_count = len(skipped) if isinstance(skipped, list) else 0
    matched_counts = result.get("matched_counts") if isinstance(result.get("matched_counts"), dict) else {}
    generated_files = [item for item in output_files if has_data_output_file([item])]
    return {
        "matched_counts": matched_counts,
        "matched_files": sum(int(v or 0) for v in matched_counts.values()) if isinstance(matched_counts, dict) else 0,
        "generated_files": len(generated_files),
        "skipped_files": skipped_count,
        "result_state": "partial_success" if skipped_count else "success",
    }


def build_process_error_result(
    message: str,
    *,
    result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "error", "message": message}
    if result is not None:
        payload["result"] = dict(result)
    return payload


def build_process_success_result(
    *,
    summary: str,
    data_types: Sequence[str],
    project_id: str | None,
    summary_path: str | None,
    output_files: Sequence[str],
    output_dir: str | None,
    preflight: Mapping[str, Any],
    quality_summary: Mapping[str, Any],
    skipped_errors: Sequence[Any],
    summary_json: Mapping[str, Any] | None,
    raw: Mapping[str, Any],
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    data_type_list = list(data_types)
    output_file_list = list(output_files)
    preflight_payload = dict(preflight) if isinstance(preflight, Mapping) else {}
    quality_payload = dict(quality_summary) if isinstance(quality_summary, Mapping) else {}
    raw_payload = dict(raw) if isinstance(raw, Mapping) else {}
    manifest_payload = dict(manifest) if isinstance(manifest, Mapping) else None
    return {
        "status": "success",
        "result": {
            "summary": summary,
            "data_type": data_type_list[0] if data_type_list else "",
            "data_types": data_type_list,
            "project_id": project_id,
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "summary_path": summary_path,
            "processing": {
                "output_files": output_file_list,
                "output_dir": output_dir,
                **processing_stats(raw_payload, output_file_list),
            },
            "preflight": preflight_payload,
            "quality_summary": quality_payload,
            "skipped_errors": list(skipped_errors),
            "summary_json": dict(summary_json) if isinstance(summary_json, Mapping) else summary_json,
            "raw": raw_payload,
            "manifest": manifest_payload,
        },
    }
