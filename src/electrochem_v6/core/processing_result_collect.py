"""Helpers for collecting normalized processing results from legacy tables."""

from __future__ import annotations

import math
from typing import Any, Callable, Mapping, Sequence

from electrochem_v6.core.processing_metric_registry import normalize_metric_key, resolve_metric
from electrochem_v6.core.processing_result_models import MetricValue, ProcessingResult, SourceFileRef

UnitResolver = Callable[[str], str | None]
MethodResolver = Callable[[str], str | None]


def make_metric_key(label: str) -> str:
    """Convert a result-table column label into a stable ASCII metric key."""
    return normalize_metric_key(label)


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


def _text(value: Any) -> str | None:
    if _is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def _dedupe_metric_key(key: str, used: set[str]) -> str:
    if key not in used:
        used.add(key)
        return key
    idx = 2
    while f"{key}_{idx}" in used:
        idx += 1
    final_key = f"{key}_{idx}"
    used.add(final_key)
    return final_key


def _resolve_unit(
    column: str,
    units: Mapping[str, str | None] | UnitResolver | None,
) -> str | None:
    if units is None:
        return None
    if callable(units):
        return units(column)
    return units.get(column)


def _resolve_method(column: str, resolver: MethodResolver | None) -> str | None:
    if resolver is None:
        return None
    return resolver(column)


def processing_results_from_dataframe(
    dataframe: Any,
    *,
    data_type: str,
    sample_column: str,
    file_column: str | None = None,
    artifact_columns: Sequence[str] = (),
    skip_columns: Sequence[str] = (),
    units: Mapping[str, str | None] | UnitResolver | None = None,
    method_resolver: MethodResolver | None = None,
    project_id: str | None = None,
    run_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> list[ProcessingResult]:
    """Build normalized results from a pandas-like dataframe."""
    records = dataframe.to_dict(orient="records")
    skip = {sample_column, *(artifact_columns or ()), *(skip_columns or ())}
    if file_column:
        skip.add(file_column)

    results: list[ProcessingResult] = []
    for record in records:
        sample_name = _text(record.get(sample_column)) or "unknown_sample"
        file_name = _text(record.get(file_column)) if file_column else None
        used_keys: set[str] = set()
        metrics: list[MetricValue] = []
        for column, value in record.items():
            if column in skip or _is_missing(value):
                continue
            base_key = _dedupe_metric_key(make_metric_key(str(column)), used_keys)
            resolved_metric = resolve_metric(data_type, str(column), fallback_key=base_key)
            unit = resolved_metric.unit
            if unit is None:
                unit = _resolve_unit(str(column), units)
            method = resolved_metric.method
            if method is None:
                method = _resolve_method(str(column), method_resolver)
            metrics.append(
                MetricValue(
                    key=resolved_metric.key,
                    label=resolved_metric.label,
                    value=value,
                    unit=unit,
                    method=method,
                    metadata=resolved_metric.metadata,
                )
            )

        artifacts = tuple(
            path for path in (_text(record.get(column)) for column in artifact_columns) if path is not None
        )
        source = SourceFileRef(
            sample_name=sample_name,
            file_name=file_name,
            data_type=str(data_type).upper(),
        )
        results.append(
            ProcessingResult(
                data_type=str(data_type).upper(),
                sample_name=sample_name,
                source=source,
                metrics=tuple(metrics),
                artifacts=artifacts,
                project_id=project_id,
                run_id=run_id,
                metadata=metadata or {},
            )
        )
    return results


def processing_results_from_lsv_dataframe(
    dataframe: Any,
    *,
    project_id: str | None = None,
    run_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> list[ProcessingResult]:
    """Normalize the existing LSV summary dataframe."""
    return processing_results_from_dataframe(
        dataframe,
        data_type="LSV",
        sample_column="Sample_Name",
        file_column="File_Name",
        project_id=project_id,
        run_id=run_id,
        metadata=metadata,
    )


def processing_results_from_ecsa_dataframe(
    dataframe: Any,
    *,
    project_id: str | None = None,
    run_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> list[ProcessingResult]:
    """Normalize the existing ECSA summary dataframe."""
    return processing_results_from_dataframe(
        dataframe,
        data_type="ECSA",
        sample_column="sample",
        artifact_columns=("png",),
        project_id=project_id,
        run_id=run_id,
        metadata=metadata,
    )


def collect_results_by_sample(results: Sequence[ProcessingResult]) -> dict[str, list[ProcessingResult]]:
    """Group normalized results by sample name for coupled calculations."""
    grouped: dict[str, list[ProcessingResult]] = {}
    for result in results:
        grouped.setdefault(result.sample_name, []).append(result)
    return grouped


__all__ = [
    "collect_results_by_sample",
    "make_metric_key",
    "processing_results_from_dataframe",
    "processing_results_from_ecsa_dataframe",
    "processing_results_from_lsv_dataframe",
]
