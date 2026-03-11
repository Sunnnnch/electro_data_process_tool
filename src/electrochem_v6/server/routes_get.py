"""GET route dispatcher for v6 server."""

from __future__ import annotations

import io
import os
import zipfile
from typing import Any
from urllib.parse import parse_qs, urlparse


def _safe_int(raw: str, default: int, lo: int = 1, hi: int = 10000) -> int:
    """Parse *raw* as int, clamping to [lo, hi]. Returns *default* on failure."""
    try:
        return max(lo, min(int(raw), hi))
    except (ValueError, TypeError):
        return default


from electrochem_v6.core import (
    build_project_lsv_compare_plot,
    export_project_report,
    get_latest_project_lsv_compare_plot,
    get_latest_quality_report,
    get_project_lsv_target_currents,
)
from electrochem_v6.llm import get_masked_config
from electrochem_v6.server.request_utils import path_parts
from electrochem_v6.server.routes_health import get_health
from electrochem_v6.store.conversations import get_conversation, list_conversations
from electrochem_v6.store.history import build_project_report, get_stats, list_history
from electrochem_v6.store.process_templates import list_process_templates
from electrochem_v6.store.projects import get_lsv_summary, list_projects


def dispatch_get(handler: Any) -> bool:
    parsed = urlparse(handler.path)
    path = parsed.path.rstrip("/") or "/"
    query = parse_qs(parsed.query)

    if path == "/":
        payload = {
            "name": "electrochem-v6-api",
            "status": "running",
            "endpoints": [
                "/health",
                "/api/v1/projects",
                "/api/v1/history",
                "/api/v1/stats",
                "/api/v1/llm/config",
                "/api/v1/agent/messages",
                "/api/v1/process",
                "/api/v1/process-zip",
                "/api/v1/process/templates",
            ],
        }
        handler._send_json(200, payload)
        return True

    if path == "/health":
        handler._send_json(200, get_health())
        return True

    if path == "/api/v1/projects":
        status = (query.get("status", ["active"])[0] or "active").strip()
        handler._send_json(200, list_projects(status=status))
        return True

    if path.startswith("/api/v1/projects/") and path.endswith("/lsv-summary"):
        parts = path_parts(path)
        if len(parts) >= 5:
            project_id = parts[3]
            page = _safe_int(query.get("page", ["1"])[0], 1)
            page_size = _safe_int(query.get("page_size", ["15"])[0], 15, lo=1, hi=100)
            sort_by = query.get("sort", ["eta"])[0]
            if sort_by not in ("eta", "tafel"):
                sort_by = "eta"
            handler._send_json(
                200,
                get_lsv_summary(
                    project_id=project_id,
                    page=page,
                    page_size=page_size,
                    sort_by=sort_by,
                ),
            )
            return True

    if path.startswith("/api/v1/projects/") and path.endswith("/lsv-target-currents"):
        parts = path_parts(path)
        if len(parts) >= 5:
            project_id = parts[3]
            include_archived = (query.get("include_archived", ["0"])[0] or "").strip().lower() in {"1", "true", "yes"}
            payload = get_project_lsv_target_currents(project_id=project_id, include_archived=include_archived)
            handler._send_json(200 if payload.get("status") == "success" else 400, payload)
            return True

    if path.startswith("/api/v1/projects/") and path.endswith("/lsv-compare-plot"):
        parts = path_parts(path)
        if len(parts) >= 5:
            project_id = parts[3]
            include_archived = (query.get("include_archived", ["0"])[0] or "").strip().lower() in {"1", "true", "yes"}
            selected_samples = []
            for item in query.get("sample", []):
                text = str(item or "").strip()
                if text:
                    selected_samples.append(text)
            for item in query.get("samples", []):
                for part in str(item or "").split(","):
                    text = part.strip()
                    if text:
                        selected_samples.append(text)
            chart_type = query.get("chart_type", ["overlay"])[0]
            if chart_type not in ("overlay", "bar", "scatter", "radar"):
                chart_type = "overlay"
            metric_key = query.get("metric", ["overpotential_10"])[0]
            target_current = query.get("target_current", ["10"])[0]
            payload = build_project_lsv_compare_plot(
                project_id=project_id,
                selected_samples=selected_samples,
                include_archived=include_archived,
                chart_type=chart_type,
                metric_key=metric_key,
                target_current=target_current,
            )
            handler._send_json(200 if payload.get("status") == "success" else 400, payload)
            return True

    if path.startswith("/api/v1/projects/") and path.endswith("/lsv-compare-plot/latest"):
        parts = path_parts(path)
        if len(parts) >= 6:
            project_id = parts[3]
            chart_type = query.get("chart_type", ["overlay"])[0]
            if chart_type not in ("overlay", "bar", "scatter", "radar"):
                chart_type = "overlay"
            metric_key = query.get("metric", ["overpotential_10"])[0]
            target_current = query.get("target_current", ["10"])[0]
            payload = get_latest_project_lsv_compare_plot(
                project_id=project_id,
                chart_type=chart_type,
                metric_key=metric_key,
                target_current=target_current,
            )
            handler._send_json(200 if payload.get("status") == "success" else 404, payload)
            return True

    if path.startswith("/api/v1/projects/") and path.endswith("/report"):
        parts = path_parts(path)
        if len(parts) >= 5:
            project_id = parts[3]
            include_archived = (query.get("include_archived", ["0"])[0] or "").strip().lower() in {"1", "true", "yes"}
            projects_payload = list_projects(status="active")
            project = next((item for item in (projects_payload.get("projects") or []) if item.get("id") == project_id), None)
            if not project:
                handler._send_json(404, {"status": "error", "message": "project not found", "project_id": project_id})
                return True
            report_payload = build_project_report(project_id, include_archived=include_archived)
            if report_payload.get("status") != "success":
                handler._send_json(400, report_payload)
                return True
            export_payload = export_project_report(
                project=project,
                report_data=report_payload.get("report") or {},
                output_dir=os.path.join(os.getcwd(), "project_reports"),
            )
            handler._send_json(200 if export_payload.get("status") == "success" else 400, export_payload)
            return True

    if path.startswith("/api/v1/projects/") and path.endswith("/export-zip"):
        parts = path_parts(path)
        if len(parts) >= 5:
            project_id = parts[3]
            include_archived = (query.get("include_archived", ["0"])[0] or "").strip().lower() in {"1", "true", "yes"}
            history_payload = list_history(project_id=project_id, limit=500, include_archived=include_archived)
            records = history_payload.get("records") or history_payload.get("history") or []
            buf = io.BytesIO()
            added = set()

            # Build a set of allowed roots from history records so that
            # export-zip only bundles files belonging to known data dirs.
            _export_allowed_roots = set()
            for _rec in records:
                _folder = str(_rec.get("folder_path") or "").strip()
                if _folder and os.path.isdir(_folder):
                    _export_allowed_roots.add(os.path.realpath(_folder))
            # Also allow cwd and user home as fallback
            _export_allowed_roots.add(os.path.realpath(os.getcwd()))
            _export_allowed_roots.add(os.path.realpath(os.path.expanduser("~")))

            def _is_export_safe(fpath: str) -> bool:
                resolved = os.path.realpath(fpath)
                return any(
                    resolved == root or resolved.startswith(root + os.sep)
                    for root in _export_allowed_roots
                )

            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for rec in records:
                    for fp in (rec.get("output_files") or []):
                        abs_fp = os.path.abspath(fp)
                        if abs_fp not in added and os.path.isfile(abs_fp) and _is_export_safe(abs_fp):
                            zf.write(abs_fp, os.path.basename(abs_fp))
                            added.add(abs_fp)
                    src = rec.get("file_path")
                    if src:
                        abs_src = os.path.abspath(src)
                        if abs_src not in added and os.path.isfile(abs_src) and _is_export_safe(abs_src):
                            zf.write(abs_src, f"source/{os.path.basename(abs_src)}")
                            added.add(abs_src)
            data = buf.getvalue()
            handler.send_response(200)
            handler.send_header("Content-Type", "application/zip")
            handler.send_header("Content-Disposition", f'attachment; filename="project_{project_id}.zip"')
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            return True

    if path == "/api/v1/history":
        project_id = query.get("project", [None])[0]
        limit = _safe_int(query.get("limit", ["100"])[0], 100, lo=1, hi=500)
        include_archived = (query.get("include_archived", ["0"])[0] or "").strip().lower() in {"1", "true", "yes"}
        data_type = query.get("type", [None])[0]
        metric_key = query.get("metric_key", [None])[0]
        metric_min = None
        metric_max = None
        try:
            raw_min = query.get("metric_min", [None])[0]
            if raw_min is not None:
                metric_min = float(raw_min)
        except (ValueError, TypeError):
            pass
        try:
            raw_max = query.get("metric_max", [None])[0]
            if raw_max is not None:
                metric_max = float(raw_max)
        except (ValueError, TypeError):
            pass
        handler._send_json(200, list_history(
            project_id=project_id, limit=limit, include_archived=include_archived,
            metric_key=metric_key, metric_min=metric_min, metric_max=metric_max, data_type=data_type,
        ))
        return True

    if path == "/api/v1/stats":
        project_id = query.get("project", [None])[0]
        include_archived = (query.get("include_archived", ["0"])[0] or "").strip().lower() in {"1", "true", "yes"}
        handler._send_json(200, get_stats(project_id=project_id, include_archived=include_archived))
        return True

    if path == "/api/v1/llm/config":
        handler._send_json(200, get_masked_config())
        return True

    if path == "/api/v1/process/templates":
        payload = list_process_templates()
        handler._send_json(200 if payload.get("status") == "success" else 400, payload)
        return True

    if path == "/api/v1/quality-report/latest":
        payload = get_latest_quality_report()
        handler._send_json(200 if payload.get("status") == "success" else 404, payload)
        return True

    if path == "/api/v1/agent/conversations":
        page = _safe_int(query.get("page", ["1"])[0], 1)
        page_size = _safe_int(query.get("page_size", ["20"])[0], 20, lo=1, hi=100)
        filters = {
            "keyword": query.get("keyword", [""])[0],
            "project_name": query.get("project_name", [""])[0],
            "data_type": query.get("data_type", [""])[0],
            "provider": query.get("provider", [""])[0],
        }
        payload = {
            "status": "success",
            **list_conversations(page=page, page_size=page_size, filters=filters),
        }
        handler._send_json(200, payload)
        return True

    if path.startswith("/api/v1/agent/conversations/"):
        parts = path_parts(path)
        if len(parts) >= 5:
            conversation_id = parts[4]
            conv = get_conversation(conversation_id)
            if not conv:
                handler._send_json(404, {"status": "error", "message": "会话不存在"})
                return True
            handler._send_json(200, {"status": "success", "conversation": conv})
            return True

    return False
