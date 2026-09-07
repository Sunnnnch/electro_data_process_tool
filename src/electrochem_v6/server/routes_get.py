"""GET route dispatcher for v6 server."""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


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
from electrochem_v6.core.processing_module_runtime import processing_module_catalog
from electrochem_v6.core.processing_registry import processing_parameter_schema
from electrochem_v6.core.project_archive import (
    DEFAULT_MAX_ARCHIVE_FILES,
    DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES,
    ProjectArchiveLimitError,
    write_project_archive,
)
from electrochem_v6.core.storage_service import storage_summary
from electrochem_v6.llm import get_masked_config
from electrochem_v6.server.request_utils import path_parts
from electrochem_v6.server.routes_health import get_health
from electrochem_v6.server.routes_mcp import dispatch_mcp_get
from electrochem_v6.server.routes_recovery import dispatch_recovery_get
from electrochem_v6.server.routes_replicates import dispatch_replicates_get
from electrochem_v6.server.routes_runs import dispatch_runs_get
from electrochem_v6.server.routes_tasks import dispatch_tasks_get
from electrochem_v6.store.conversations import get_conversation, list_conversations
from electrochem_v6.store.history import (
    build_project_report,
    get_history_detail,
    get_stats,
    iter_project_archive_records,
    list_history_page,
)
from electrochem_v6.store.process_templates import list_process_templates
from electrochem_v6.store.projects import get_lsv_summary, list_project_samples, list_projects
from electrochem_v6.store.runtime import get_database


def dispatch_get(handler: Any, manager: Any = None) -> bool:
    if dispatch_mcp_get(handler, manager):
        return True
    if dispatch_replicates_get(handler):
        return True
    if dispatch_tasks_get(handler, manager):
        return True
    if dispatch_recovery_get(handler):
        return True
    if dispatch_runs_get(handler):
        return True
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
                "/api/v1/agent/jobs",
                "/api/v1/process",
                "/api/v1/process/jobs",
                "/api/v1/process/preflight",
                "/api/v1/process/modules",
                "/api/v1/process/schema",
                "/api/v1/process-zip",
                "/api/v1/process/templates",
                "/api/v1/diagnostics/export",
                "/api/v1/storage",
            ],
        }
        handler._send_json(200, payload)
        return True

    if path == "/health":
        handler._send_json(200, get_health())
        return True

    if path == "/api/v1/storage":
        handler._send_json(200, storage_summary())
        return True

    if path == "/api/v1/process/jobs":
        limit = _safe_int(query.get("limit", ["20"])[0], 20, lo=1, hi=100)
        handler._send_json(
            200,
            {"status": "success", "jobs": get_database().list_processing_jobs(limit=limit)},
        )
        return True

    if path.startswith("/api/v1/process/jobs/"):
        job_id = unquote(path[len("/api/v1/process/jobs/") :])
        job = get_database().get_processing_job(job_id)
        handler._send_json(
            200 if job else 404,
            {"status": "success", "job": job}
            if job
            else {"status": "error", "message": "processing job not found"},
        )
        return True

    if path.startswith("/api/v1/agent/jobs/"):
        job_id = unquote(path[len("/api/v1/agent/jobs/") :])
        job = get_database().get_processing_job(job_id)
        if job and job.get("kind") != "agent":
            job = None
        handler._send_json(
            200 if job else 404,
            {"status": "success", "job": job}
            if job
            else {"status": "error", "message": "AI job not found"},
        )
        return True

    if path == "/api/v1/projects":
        status = (query.get("status", ["active"])[0] or "active").strip()
        handler._send_json(200, list_projects(status=status))
        return True

    if path.startswith("/api/v1/projects/") and path.endswith("/samples"):
        parts = path_parts(path)
        if len(parts) == 5:
            include_archived = (query.get("include_archived", ["0"])[0] or "").strip().lower() in {
                "1", "true", "yes"
            }
            payload = list_project_samples(parts[3], include_archived=include_archived)
            handler._send_json(200 if payload.get("status") == "success" else 400, payload)
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
            from electrochem_v6.config import user_config_dir
            export_payload = export_project_report(
                project=project,
                report_data=report_payload.get("report") or {},
                output_dir=str(user_config_dir() / "project_reports"),
            )
            handler._send_json(200 if export_payload.get("status") == "success" else 400, export_payload)
            return True

    if path.startswith("/api/v1/projects/") and path.endswith("/export-zip"):
        parts = path_parts(path)
        if len(parts) >= 5:
            project_id = parts[3]
            include_archived = (query.get("include_archived", ["0"])[0] or "").strip().lower() in {"1", "true", "yes"}
            records = iter_project_archive_records(
                project_id,
                include_archived=include_archived,
            )
            max_files = int(getattr(handler, "MAX_ZIP_FILES", DEFAULT_MAX_ARCHIVE_FILES))
            max_bytes = int(
                getattr(
                    handler,
                    "MAX_ZIP_UNCOMPRESSED_BYTES",
                    DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES,
                )
            )
            try:
                with tempfile.TemporaryDirectory(prefix="electrochem_project_export_") as temp_dir:
                    archive_path = os.path.join(temp_dir, "project.zip")
                    summary = write_project_archive(
                        records,
                        archive_path,
                        max_files=max_files,
                        max_uncompressed_bytes=max_bytes,
                    )
                    handler.send_response(200)
                    handler.send_header("Content-Type", "application/zip")
                    import re as _re
                    safe_pid = _re.sub(r'[^A-Za-z0-9_\-]', '_', str(project_id))[:64]
                    handler.send_header("Content-Disposition", f'attachment; filename="project_{safe_pid}.zip"')
                    handler.send_header("Content-Length", str(os.path.getsize(archive_path)))
                    handler.send_header("X-Electrochem-Archive-Files", str(summary.file_count))
                    handler.send_header("X-Electrochem-Archive-Skipped", str(len(summary.skipped_files)))
                    handler.end_headers()
                    with open(archive_path, "rb") as source:
                        shutil.copyfileobj(source, handler.wfile, length=1024 * 1024)
            except ProjectArchiveLimitError as exc:
                handler._send_json(413, {"status": "error", "message": str(exc)})
            return True

    if path.startswith("/api/v1/history/"):
        record_key = unquote(path[len("/api/v1/history/") :])
        payload = get_history_detail(record_key)
        handler._send_json(200 if payload.get("status") == "success" else 404, payload)
        return True

    if path == "/api/v1/history":
        project_id = query.get("project", [None])[0]
        limit = _safe_int(query.get("limit", ["50"])[0], 50, lo=1, hi=100)
        cursor = query.get("cursor", [None])[0]
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
        payload = list_history_page(
            project_id=project_id, limit=limit, include_archived=include_archived,
            cursor=cursor, metric_key=metric_key, metric_min=metric_min,
            metric_max=metric_max, data_type=data_type,
            q=query.get("q", [None])[0],
            date_from=query.get("date_from", [None])[0],
            date_to=query.get("date_to", [None])[0],
        )
        handler._send_json(200 if payload.get("status") == "success" else 400, payload)
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

    if path == "/api/v1/process/modules":
        selected_types = []
        for raw in query.get("data_type", []) + query.get("data_types", []):
            for part in str(raw or "").split(","):
                text = part.strip()
                if text:
                    selected_types.append(text)
        try:
            payload = processing_module_catalog(selected_types or None)
        except KeyError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        handler._send_json(200, payload)
        return True

    if path == "/api/v1/process/schema":
        selected_types = []
        for raw in query.get("data_type", []) + query.get("data_types", []):
            for part in str(raw or "").split(","):
                text = part.strip()
                if text:
                    selected_types.append(text)
        try:
            schema = processing_parameter_schema(selected_types or None)
        except KeyError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        handler._send_json(200, {"status": "success", "schema": schema})
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
            agent_service = getattr(manager, "_agent_service", None)
            annotator = getattr(agent_service, "annotate_conversation_approvals", None)
            if callable(annotator):
                conv = annotator(conv) or conv
            handler._send_json(200, {"status": "success", "conversation": conv})
            return True

    return False
