"""Export helpers for normalized processing results."""

from __future__ import annotations

import csv
import json
import os
from typing import Any, Sequence

from electrochem_v6.core.processing_result_models import ProcessingResult

RESULT_CSV_COLUMNS = [
    "sample_name",
    "data_type",
    "file_name",
    "source_path",
    "metric_key",
    "metric_label",
    "value",
    "unit",
    "method",
    "metric_metadata",
    "project_id",
    "run_id",
    "artifacts",
    "metadata",
]


def _json_text(value: Any) -> str:
    if not value:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def build_processing_result_records(results: Sequence[ProcessingResult]) -> list[dict[str, Any]]:
    """Convert normalized results into long-format CSV records."""
    records: list[dict[str, Any]] = []
    for result in results:
        result_dict = result.to_dict()
        source = result_dict.get("source") or {}
        artifacts = ";".join(result_dict.get("artifacts") or [])
        metadata = result_dict.get("metadata") or {}
        for metric in result_dict.get("metrics") or []:
            records.append(
                {
                    "sample_name": result_dict.get("sample_name") or "",
                    "data_type": result_dict.get("data_type") or "",
                    "file_name": source.get("file_name") or "",
                    "source_path": source.get("path") or "",
                    "metric_key": metric.get("key") or "",
                    "metric_label": metric.get("label") or "",
                    "value": metric.get("value"),
                    "unit": metric.get("unit") or "",
                    "method": metric.get("method") or "",
                    "metric_metadata": _json_text(metric.get("metadata") or {}),
                    "project_id": result_dict.get("project_id") or "",
                    "run_id": result_dict.get("run_id") or "",
                    "artifacts": artifacts,
                    "metadata": _json_text(metadata),
                }
            )
    return records


def export_processing_results_csv(results: Sequence[ProcessingResult], output_path: str) -> str:
    """Write normalized results as a long-format CSV and return the path."""
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    rows = build_processing_result_records(results)
    with open(output_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


__all__ = ["RESULT_CSV_COLUMNS", "build_processing_result_records", "export_processing_results_csv"]
