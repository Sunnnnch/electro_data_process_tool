"""Run manifest helpers for reproducible processing results."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Any, Mapping, Sequence

from electrochem_v6.core.processing_formula import FORMULA_SCHEMA_VERSION, formulas_for_run
from electrochem_v6.store._json_utils import atomic_write_json

MANIFEST_SCHEMA_VERSION = "1.1"
SENSITIVE_PARAM_TOKENS = ("api_key", "apikey", "token", "secret", "password", "authorization")


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        try:
            return _json_ready(value.item())
        except Exception:
            pass
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    return str(value)


def _redact_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in dict(params or {}).items():
        key_text = str(key)
        if any(token in key_text.lower() for token in SENSITIVE_PARAM_TOKENS):
            redacted[key_text] = "***REDACTED***"
        elif isinstance(value, Mapping):
            redacted[key_text] = _redact_params(value)
        else:
            redacted[key_text] = _json_ready(value)
    return redacted


def _file_identity(path: str) -> dict[str, Any]:
    identity: dict[str, Any] = {"exists": False}
    try:
        stat = os.stat(path)
    except OSError as exc:
        identity["identity_error"] = str(exc)
        return identity

    identity.update(
        {
            "exists": True,
            "size_bytes": int(stat.st_size),
            "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        identity["sha256"] = digest.hexdigest()
    except OSError as exc:
        identity["identity_error"] = str(exc)
    return identity


def input_file_refs_from_preflight(preflight: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    by_type = (preflight or {}).get("by_type") if isinstance(preflight, Mapping) else {}
    if not isinstance(by_type, Mapping):
        return files
    for data_type, item in by_type.items():
        if not isinstance(item, Mapping):
            continue
        paths = item.get("files") or item.get("examples") or []
        for path in paths if isinstance(paths, list) else []:
            text = str(path or "").strip()
            if not text:
                continue
            normalized = os.path.normcase(os.path.abspath(text))
            if normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            files.append(
                {
                    "data_type": str(data_type).upper(),
                    "path": text,
                    "file_name": os.path.basename(text),
                    "match": str(item.get("match") or item.get("pattern") or ""),
                    **_file_identity(text),
                }
            )
    ir_info = (preflight or {}).get("ir_compensation") if isinstance(preflight, Mapping) else {}
    ir_items = ir_info.get("items") if isinstance(ir_info, Mapping) else []
    for item in ir_items if isinstance(ir_items, list) else []:
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("eis_file") or "").strip()
        if not text:
            continue
        normalized = os.path.normcase(os.path.abspath(text))
        if normalized in seen_paths:
            continue
        seen_paths.add(normalized)
        files.append(
            {
                "data_type": "EIS (iR)",
                "path": text,
                "file_name": os.path.basename(text),
                "match": f"{item.get('scope') or '-'} / {item.get('match_mode') or '-'} / {item.get('match_pattern') or '-'}",
                **_file_identity(text),
            }
        )
    return files


def _result_summary(raw_result: Mapping[str, Any] | None) -> dict[str, Any]:
    rows = (raw_result or {}).get("processing_results") if isinstance(raw_result, Mapping) else []
    if not isinstance(rows, list):
        rows = []
    by_type: dict[str, int] = {}
    metric_count = 0
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        data_type = str(item.get("data_type") or "").upper() or "UNKNOWN"
        by_type[data_type] = by_type.get(data_type, 0) + 1
        metrics = item.get("metrics") or []
        if isinstance(metrics, list):
            metric_count += len(metrics)
    return {
        "normalized_results": len(rows),
        "normalized_metrics": metric_count,
        "by_type": by_type,
    }


def build_run_manifest(
    *,
    app_name: str,
    app_version: str,
    run_id: str | None,
    project_id: str | None,
    data_types: Sequence[str],
    params: Mapping[str, Any] | None,
    preflight: Mapping[str, Any] | None,
    output_files: Sequence[str],
    output_dir: str | None,
    summary_path: str | None,
    processing: Mapping[str, Any] | None,
    quality_summary: Mapping[str, Any] | None,
    skipped_errors: Sequence[Any] | None,
    raw_result: Mapping[str, Any] | None,
    generated_at: str | None = None,
    input_files: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    matched_counts = (preflight or {}).get("matched_counts") if isinstance(preflight, Mapping) else {}
    ir_compensation = dict((preflight or {}).get("ir_compensation") or {}) if isinstance(preflight, Mapping) else {}
    runtime_ir = (raw_result or {}).get("ir_compensation") if isinstance(raw_result, Mapping) else []
    if isinstance(runtime_ir, list):
        ir_compensation["results"] = _json_ready(runtime_ir)
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "app": {
            "name": app_name,
            "version": app_version,
        },
        "run": {
            "run_id": run_id,
            "project_id": project_id,
            "data_types": [str(item).upper() for item in data_types],
            "generated_at": generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "inputs": {
            "matched_counts": dict(matched_counts) if isinstance(matched_counts, Mapping) else {},
            "matched_files": int((preflight or {}).get("matched_files") or 0) if isinstance(preflight, Mapping) else 0,
            "files": _json_ready(list(input_files)) if input_files is not None else input_file_refs_from_preflight(preflight),
        },
        "parameters": _redact_params(params),
        "calculation": {
            "formula_schema_version": FORMULA_SCHEMA_VERSION,
            "formulas": formulas_for_run(data_types, params),
            "ir_compensation": _json_ready(ir_compensation) if ir_compensation else None,
        },
        "outputs": {
            "output_dir": output_dir,
            "summary_path": summary_path,
            "output_files": [str(item) for item in output_files],
        },
        "processing": dict(processing or {}),
        "quality": dict(quality_summary or {}),
        "skipped_errors": _json_ready(list(skipped_errors or [])),
        "results": _result_summary(raw_result),
        "processing_results": _json_ready((raw_result or {}).get("processing_results") or []),
        "quality_reports": _json_ready((raw_result or {}).get("quality_reports") or []),
    }


def write_run_manifest(
    manifest: Mapping[str, Any],
    *,
    output_dir: str,
    filename: str = "run_manifest.json",
) -> str:
    target_dir = os.path.abspath(output_dir)
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, filename)
    atomic_write_json(path, dict(manifest))
    return path


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "build_run_manifest",
    "input_file_refs_from_preflight",
    "write_run_manifest",
]
