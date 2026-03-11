"""History store adapter for v6."""

from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Any, Dict, Optional

from .legacy_runtime import _USE_SQLITE, get_history_manager_v6

_logger = logging.getLogger(__name__)


def _normalize_history_payload(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, list):
        return {"records": payload, "version": "1.0"}
    if not isinstance(payload, dict):
        return {"records": [], "version": "1.0"}
    if not isinstance(payload.get("records"), list):
        payload["records"] = []
    payload.setdefault("version", "1.0")
    return payload


def _write_history_payload(hist_mgr: Any, payload: Dict[str, Any]) -> None:
    safe_payload = hist_mgr._to_json_safe(payload) if hasattr(hist_mgr, "_to_json_safe") else payload
    # Create backup before writing
    history_file = str(hist_mgr.history_file)
    if os.path.exists(history_file):
        try:
            shutil.copy2(history_file, history_file + ".bak")
        except Exception:
            _logger.warning("Failed to create history backup before write")
    if hasattr(hist_mgr, "_atomic_write_payload"):
        hist_mgr._atomic_write_payload(safe_payload)
        return
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(safe_payload, f, ensure_ascii=False, indent=2)

def _record_key(record: Dict[str, Any]) -> str:
    file_value = record.get("file_path") or record.get("file_name") or record.get("sample_name") or ""
    return f"{record.get('timestamp', '')}|{record.get('type', '')}|{file_value}"


def _filter_records(records: list[Dict[str, Any]], project_id: Optional[str] = None, include_archived: bool = False,
                    metric_key: Optional[str] = None, metric_min: Optional[float] = None, metric_max: Optional[float] = None,
                    data_type: Optional[str] = None) -> list[Dict[str, Any]]:
    items = [item for item in records if isinstance(item, dict)]
    if project_id:
        items = [item for item in items if item.get("project_id") == project_id]
    if not include_archived:
        items = [item for item in items if not bool(item.get("archived", False))]
    if data_type:
        dt_upper = data_type.strip().upper()
        items = [item for item in items if str(item.get("type") or "").upper() == dt_upper]
    if metric_key and (metric_min is not None or metric_max is not None):
        filtered = []
        for item in items:
            results = item.get("results") or {}
            val = results.get(metric_key)
            if val is None:
                continue
            try:
                fval = float(val)
            except (ValueError, TypeError):
                continue
            if metric_min is not None and fval < metric_min:
                continue
            if metric_max is not None and fval > metric_max:
                continue
            filtered.append(item)
        items = filtered
    return items


def list_history(project_id: Optional[str] = None, limit: int = 100, include_archived: bool = False,
                 metric_key: Optional[str] = None, metric_min: Optional[float] = None, metric_max: Optional[float] = None,
                 data_type: Optional[str] = None) -> Dict[str, Any]:
    if _USE_SQLITE:
        hist_mgr = get_history_manager_v6()
        records = hist_mgr.db.filter_history(
            project_id=project_id, include_archived=include_archived,
            data_type=data_type, metric_key=metric_key, metric_min=metric_min, metric_max=metric_max,
            limit=limit,
        )
        return {"status": "success", "records": records}
    hist_mgr = get_history_manager_v6()
    records = _filter_records(hist_mgr.get_all_records(), project_id=project_id, include_archived=include_archived,
                              metric_key=metric_key, metric_min=metric_min, metric_max=metric_max, data_type=data_type)
    records = sorted(records, key=lambda x: x.get("timestamp", ""), reverse=True)
    safe_limit = max(1, min(int(limit), 500))
    return {"status": "success", "records": records[:safe_limit]}


def get_stats(project_id: Optional[str] = None, include_archived: bool = False) -> Dict[str, Any]:
    if _USE_SQLITE:
        hist_mgr = get_history_manager_v6()
        stats = hist_mgr.db.get_history_stats(project_id=project_id, include_archived=include_archived)
        return {"status": "success", "data": stats}
    hist_mgr = get_history_manager_v6()
    records = _filter_records(hist_mgr.get_all_records(), project_id=project_id, include_archived=include_archived)
    stats = {
        "total_files": len(records),
        "lsv_count": sum(1 for item in records if str(item.get("type") or "").upper() == "LSV"),
        "cv_count": sum(1 for item in records if str(item.get("type") or "").upper() == "CV"),
        "eis_count": sum(1 for item in records if str(item.get("type") or "").upper() == "EIS"),
        "ecsa_count": sum(1 for item in records if str(item.get("type") or "").upper() == "ECSA"),
    }
    return {"status": "success", "data": stats}


def _update_history_records(*, match_key: str, action: str) -> Dict[str, Any]:
    safe_key = str(match_key or "").strip()
    if not safe_key:
        return {"status": "error", "message": "missing history key", "updated": 0}

    if _USE_SQLITE:
        hist_mgr = get_history_manager_v6()
        updated = hist_mgr.db.update_history_by_key(safe_key, action)
        if updated == 0:
            return {"status": "error", "message": "history record not found", "updated": 0}
        return {"status": "success", "updated": updated, "action": action}

    hist_mgr = get_history_manager_v6()
    updated = 0
    with hist_mgr.lock:
        try:
            with open(hist_mgr.history_file, "r", encoding="utf-8") as f:
                payload = _normalize_history_payload(json.load(f))
        except Exception as exc:
            return {"status": "error", "message": f"read history failed: {exc}", "updated": 0}
        records = payload.get("records", [])
        if not isinstance(records, list):
            records = []
        next_records = []
        for record in records:
            if not isinstance(record, dict):
                continue
            if _record_key(record) == safe_key:
                if action == "archive":
                    record["archived"] = True
                    updated += 1
                    next_records.append(record)
                    continue
                if action == "delete":
                    updated += 1
                    continue
            next_records.append(record)
        payload["records"] = next_records
        try:
            _write_history_payload(hist_mgr, payload)
        except Exception as exc:
            return {"status": "error", "message": f"write history failed: {exc}", "updated": 0}
    if updated == 0:
        return {"status": "error", "message": "history record not found", "updated": 0}
    return {"status": "success", "updated": updated, "action": action}


def archive_history_record(history_key: str) -> Dict[str, Any]:
    return _update_history_records(match_key=history_key, action="archive")


def delete_history_record(history_key: str) -> Dict[str, Any]:
    return _update_history_records(match_key=history_key, action="delete")


def build_project_report(project_id: str, include_archived: bool = False) -> Dict[str, Any]:
    safe_project_id = str(project_id or "").strip()
    if not safe_project_id:
        return {"status": "error", "message": "missing project id"}
    records_resp = list_history(project_id=safe_project_id, limit=500, include_archived=include_archived)
    stats_resp = get_stats(project_id=safe_project_id, include_archived=include_archived)
    records = records_resp.get("records") or []
    stats = stats_resp.get("data") or {}
    report = {
        "project_id": safe_project_id,
        "generated_at": records[0].get("timestamp") if records else "",
        "include_archived": include_archived,
        "stats": stats,
        "recent_records": records[:20],
    }
    return {"status": "success", "report": report}


def attach_run_outputs(
    *,
    run_id: str,
    output_files: list[str],
    summary_path: Optional[str] = None,
    quality_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    safe_run_id = str(run_id or "").strip()
    if not safe_run_id:
        return {"status": "error", "message": "missing run id", "updated": 0}
    safe_output_files = [str(item).strip() for item in output_files if str(item).strip()]

    if _USE_SQLITE:
        hist_mgr = get_history_manager_v6()
        updated = hist_mgr.db.attach_run_outputs(
            run_id=safe_run_id,
            output_files=safe_output_files,
            summary_path=summary_path,
            quality_summary=quality_summary,
        )
        return {"status": "success", "updated": updated}

    hist_mgr = get_history_manager_v6()
    updated = 0
    with hist_mgr.lock:
        try:
            with open(hist_mgr.history_file, "r", encoding="utf-8") as f:
                payload = _normalize_history_payload(json.load(f))
        except Exception as exc:
            return {"status": "error", "message": f"read history failed: {exc}", "updated": 0}
        records = payload.get("records", [])
        if not isinstance(records, list):
            records = []
        for record in records:
            if not isinstance(record, dict):
                continue
            if str(record.get("run_id") or "").strip() != safe_run_id:
                continue
            record["output_files"] = list(safe_output_files)
            if summary_path:
                record["summary_path"] = str(summary_path)
            if isinstance(quality_summary, dict):
                record["quality_summary"] = hist_mgr._to_json_safe(quality_summary) if hasattr(hist_mgr, "_to_json_safe") else quality_summary
            updated += 1
        payload["records"] = records
        try:
            _write_history_payload(hist_mgr, payload)
        except Exception as exc:
            return {"status": "error", "message": f"write history failed: {exc}", "updated": 0}
    return {"status": "success", "updated": updated}
