"""Preflight result helpers for folder processing."""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def matched_counts_from_preflight(scan: Mapping[str, Any]) -> dict[str, int]:
    by_type = scan.get("by_type") if isinstance(scan, Mapping) else {}
    if not isinstance(by_type, Mapping):
        return {}
    counts: dict[str, int] = {}
    for dtype, item in by_type.items():
        if isinstance(item, Mapping):
            counts[str(dtype)] = _as_int(item.get("matched"), 0)
        else:
            counts[str(dtype)] = 0
    return counts


def add_coupled_preflight(
    scan: Mapping[str, Any],
    product_table_path: Any,
    *,
    input_mode: str = "product_table",
    peak_method_path: Any = None,
    peak_inspection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    table_path = str(product_table_path or "").strip()
    updated = dict(scan or {})
    if not table_path:
        return updated

    mode = str(input_mode or "product_table").strip().lower()
    method_path = str(peak_method_path or "").strip()
    inspection = dict(peak_inspection or {})
    peak_ok = mode != "peak_analysis" or bool(inspection.get("ok"))
    examples = [table_path]
    if method_path:
        examples.append(method_path)
    by_type = dict(updated.get("by_type") or {})
    by_type["COUPLED"] = {
        "enabled": True,
        "matched": 1 if peak_ok else 0,
        "pattern": os.path.basename(table_path),
        "prefix": os.path.basename(table_path),
        "match": mode,
        "examples": examples,
        "input_mode": mode,
        "peak_method": inspection if mode == "peak_analysis" else {},
    }
    updated["by_type"] = by_type
    if peak_ok:
        updated["selected_matched"] = _as_int(updated.get("selected_matched"), 0) + 1
    if mode == "peak_analysis":
        updated["coupled_peak"] = inspection
        inspection_errors = [str(item) for item in inspection.get("errors") or []]
        if inspection_errors:
            warnings = list(updated.get("warnings") or [])
            warnings.extend(inspection_errors)
            updated["warnings"] = list(dict.fromkeys(warnings))
    return updated


def build_preflight_checks(
    scan: Mapping[str, Any],
    *,
    param_error: str | None = None,
    output_error: str | None = None,
) -> dict[str, dict[str, Any]]:
    selected_matched = _as_int(scan.get("selected_matched"), 0)
    warnings = scan.get("warnings") if isinstance(scan, Mapping) else []
    warning_items = list(warnings) if isinstance(warnings, list) else []
    files_ok = selected_matched > 0 and not warning_items
    params_ok = not param_error
    output_ok = not output_error
    runnable_ok = files_ok and params_ok and output_ok

    return {
        "file_recognition": {
            "ok": files_ok,
            "status": "pass" if files_ok else "check",
            "matched": selected_matched,
            "warnings": warning_items,
        },
        "param_completeness": {
            "ok": params_ok,
            "status": "pass" if params_ok else "check",
            "message": param_error or "",
        },
        "output_dir": {
            "ok": output_ok,
            "status": "normal" if output_ok else "abnormal",
            "message": output_error or "",
        },
        "runnable": {
            "ok": runnable_ok,
            "status": "yes" if runnable_ok else "no",
        },
    }


def finalize_preflight_scan(
    scan: Mapping[str, Any],
    *,
    data_types: Sequence[str] | None = None,
    param_error: str | None = None,
    output_error: str | None = None,
) -> dict[str, Any]:
    updated = dict(scan or {})
    if data_types is not None:
        updated["data_types"] = list(data_types)
    counts = matched_counts_from_preflight(updated)
    updated["matched_counts"] = counts
    updated["matched_files"] = sum(counts.values())
    checks = build_preflight_checks(updated, param_error=param_error, output_error=output_error)
    updated["checks"] = checks
    updated["runnable"] = bool(checks["runnable"]["ok"])
    return updated
