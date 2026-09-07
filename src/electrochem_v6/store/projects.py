"""Project store adapter for v6."""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from electrochem_v6.core.storage_service import remove_managed_artifact_roots

from .runtime import get_database, get_history_store, get_project_store

_PROJECTS_IO_LOCK = threading.RLock()
_logger = logging.getLogger(__name__)

_MAX_PROJECT_NAME_LEN = 128
_MAX_DESCRIPTION_LEN = 1024
_MAX_SAMPLE_NOTE_LEN = 4000
_MAX_SAMPLE_TAGS = 20
_MAX_SAMPLE_TAG_LEN = 64
# Strip control characters (C0/C1) except common whitespace
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _validate_project_name(name: str | None) -> tuple[str | None, str | None]:
    """Return (clean_name, error_message). error_message is None on success."""
    clean = _CONTROL_CHARS_RE.sub("", str(name or "")).strip()
    if not clean:
        return None, "项目名称不能为空"
    if len(clean) > _MAX_PROJECT_NAME_LEN:
        return None, f"项目名称不能超过 {_MAX_PROJECT_NAME_LEN} 个字符"
    return clean, None


def _sanitize_description(desc: str | None) -> str:
    clean = _CONTROL_CHARS_RE.sub("", str(desc or "")).strip()
    return clean[:_MAX_DESCRIPTION_LEN]


def _validate_project_template_name(value: Any, *, current_name: str | None = None) -> tuple[str, str | None]:
    """Validate a new reference while allowing an existing deleted reference to remain."""
    if not isinstance(value, str):
        return "", "项目常用模板名称必须是字符串"
    clean = value.strip()
    if not clean or clean == current_name:
        return clean, None
    from .process_templates import list_process_templates

    templates = list_process_templates().get("templates", [])
    if not any(item.get("name") == clean for item in templates):
        return "", f"常用参数模板“{clean}”不存在，请重新选择或解除关联"
    return clean, None


def _find_project_name_conflict(
    name: str,
    *,
    exclude_project_id: str | None = None,
) -> Optional[Dict[str, Any]]:
    normalized = str(name or "").strip().casefold()
    excluded = str(exclude_project_id or "").strip()
    for project in get_project_store().get_all_projects("all"):
        if str(project.get("id") or "") == excluded:
            continue
        if str(project.get("name") or "").strip().casefold() == normalized:
            return project
    return None


def get_or_create_project_id_by_name(
    name: str | None,
    *,
    description: str = "v6 process api auto-created",
    tags: Optional[List[str]] = None,
    color: Optional[str] = None,
) -> Optional[str]:
    clean_name, error = _validate_project_name(name)
    if error or clean_name is None:
        return None
    proj_mgr = get_project_store()
    with _PROJECTS_IO_LOCK:
        try:
            conflict = _find_project_name_conflict(clean_name)
            if conflict:
                if conflict.get("status") == "active":
                    return str(conflict.get("id") or "") or None
                _logger.warning(
                    "Cannot auto-create project %r because an archived project uses that name",
                    clean_name,
                )
                return None
        except Exception as exc:
            _logger.warning("Failed to lookup existing projects: %s", exc)
        return proj_mgr.create_project(
            clean_name,
            description=str(description or "").strip(),
            tags=tags or [],
            color=color,
        )


def list_projects(status: str = "active") -> Dict[str, Any]:
    proj_mgr = get_project_store()
    with _PROJECTS_IO_LOCK:
        projects = proj_mgr.get_all_projects(status=status)
    safe_projects: List[Dict[str, Any]] = []
    for project in projects:
        item = dict(project)
        try:
            pid = item.get("id")
            if pid:
                stats = proj_mgr.get_project_stats(pid)
                item["file_count"] = stats.get("total_files", item.get("file_count", 0))
        except Exception as exc:
            _logger.debug("Could not get stats for project %s: %s", item.get("id"), exc)
        safe_projects.append(item)
    return {"status": "success", "projects": safe_projects}


def list_project_samples(
    project_id: str,
    *,
    include_archived: bool = False,
) -> Dict[str, Any]:
    pid = str(project_id or "").strip()
    if not pid:
        return {"status": "error", "message": "missing project id", "samples": []}
    samples = get_database().list_project_samples(pid, include_archived=include_archived)
    return {"status": "success", "project_id": pid, "samples": samples}


def update_project_sample(
    project_id: str,
    sample_id: str,
    *,
    note: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    pid = str(project_id or "").strip()
    sid = str(sample_id or "").strip()
    if not pid or not sid:
        return {"status": "error", "message": "missing project or sample id"}

    clean_note: Optional[str] = None
    if note is not None:
        clean_note = _CONTROL_CHARS_RE.sub("", str(note)).strip()[:_MAX_SAMPLE_NOTE_LEN]

    clean_tags: Optional[List[str]] = None
    if tags is not None:
        clean_tags = []
        seen: set[str] = set()
        for raw_tag in tags:
            tag = _CONTROL_CHARS_RE.sub("", str(raw_tag)).strip()[:_MAX_SAMPLE_TAG_LEN]
            key = tag.casefold()
            if not tag or key in seen:
                continue
            seen.add(key)
            clean_tags.append(tag)
            if len(clean_tags) >= _MAX_SAMPLE_TAGS:
                break

    if clean_note is None and clean_tags is None:
        return {"status": "error", "message": "no sample fields to update"}
    database = get_database()
    if not database.update_project_sample(pid, sid, note=clean_note, tags=clean_tags):
        return {"status": "error", "message": "sample not found"}
    sample = database.get_project_sample(pid, sid)
    return {
        "status": "success",
        "message": "sample updated",
        "project_id": pid,
        "sample": sample,
    }


def create_project(
    name: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    color: Optional[str] = None,
    default_template_name: str = "",
) -> Dict[str, Any]:
    clean_name, err = _validate_project_name(name)
    if err or clean_name is None:
        return {"status": "error", "message": err or "项目名称无效"}
    clean_desc = _sanitize_description(description)
    clean_template, template_error = _validate_project_template_name(default_template_name)
    if template_error:
        return {"status": "error", "message": template_error}
    proj_mgr = get_project_store()
    with _PROJECTS_IO_LOCK:
        conflict = _find_project_name_conflict(clean_name)
        if conflict:
            state = "已归档" if conflict.get("status") == "archived" else "已存在"
            return {
                "status": "error",
                "message": f"项目名称“{clean_name}”{state}，请使用其他名称",
                "conflict_project_id": conflict.get("id"),
            }
        try:
            project_id = proj_mgr.create_project(
                clean_name,
                description=clean_desc,
                tags=tags or [],
                color=color,
                default_template_name=clean_template,
            )
        except sqlite3.IntegrityError:
            return {"status": "error", "message": f"项目名称“{clean_name}”已存在"}
    if not project_id:
        return {"status": "error", "message": "project create failed"}
    project = proj_mgr.get_project(project_id)
    return {"status": "success", "project_id": project_id, "project": project}


def delete_project(project_id: str) -> Dict[str, Any]:
    pid = str(project_id or "").strip()
    if not pid:
        return {"status": "error", "message": "missing project id"}
    proj_mgr = get_project_store()
    with _PROJECTS_IO_LOCK:
        success = proj_mgr.delete_project(pid, delete_data=False)
    if not success:
        return {"status": "error", "message": "project not found or delete failed", "project_id": pid}
    return {"status": "success", "message": "project archived", "project_id": pid}


def restore_project(project_id: str) -> Dict[str, Any]:
    pid = str(project_id or "").strip()
    database = get_database()
    with _PROJECTS_IO_LOCK:
        project = database.get_project(pid) if pid else None
        if not project:
            return {"status": "error", "message": "project not found", "project_id": pid}
        if project.get("status") != "archived":
            return {"status": "error", "message": "project is not archived", "project_id": pid}
        conflict = _find_project_name_conflict(str(project.get("name") or ""), exclude_project_id=pid)
        if conflict:
            return {
                "status": "error",
                "message": "存在同名项目，请先重命名后再恢复",
                "project_id": pid,
                "conflict_project_id": conflict.get("id"),
            }
        try:
            restored = database.update_project(pid, status="active")
        except sqlite3.IntegrityError:
            restored = False
        if not restored:
            return {"status": "error", "message": "project restore failed", "project_id": pid}
        if not database.get_default_project():
            database.set_default_project(pid)
    return {"status": "success", "message": "project restored", "project_id": pid}


def permanently_delete_project(project_id: str, *, delete_artifacts: bool = True) -> Dict[str, Any]:
    pid = str(project_id or "").strip()
    database = get_database()
    project = database.get_project(pid) if pid else None
    if not project:
        return {"status": "error", "message": "project not found", "project_id": pid}
    if project.get("status") != "archived":
        return {
            "status": "error",
            "message": "archive the project before permanent deletion",
            "project_id": pid,
        }
    roots = database.get_managed_artifact_roots(project_id=pid) if delete_artifacts else []
    deleted = database.purge_project(pid)
    cleanup = remove_managed_artifact_roots(roots) if delete_artifacts else {
        "removed": [], "skipped": [], "bytes_reclaimed": 0,
    }
    cleanup_complete = not bool(cleanup.get("skipped"))
    return {
        "status": "success",
        "message": (
            "project permanently deleted"
            if cleanup_complete
            else "project deleted, but some managed files could not be removed"
        ),
        "project_id": pid,
        "deleted": deleted,
        "artifact_cleanup": cleanup,
        "artifact_cleanup_complete": cleanup_complete,
    }


def update_project(
    project_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    color: Optional[str] = None,
    status: Optional[str] = None,
    default_template_name: Optional[str] = None,
) -> Dict[str, Any]:
    pid = str(project_id or "").strip()
    if not pid:
        return {"status": "error", "message": "missing project id"}
    payload: Dict[str, Any] = {}
    if default_template_name is not None:
        existing = get_project_store().get_project(pid)
        current_name = str((existing or {}).get("default_template_name") or "")
        clean_template, template_error = _validate_project_template_name(
            default_template_name, current_name=current_name,
        )
        if template_error:
            return {"status": "error", "message": template_error, "project_id": pid}
        payload["default_template_name"] = clean_template
    if name is not None:
        clean_name, err = _validate_project_name(name)
        if err:
            return {"status": "error", "message": err}
        payload["name"] = clean_name
    if description is not None:
        payload["description"] = _sanitize_description(description)
    if tags is not None:
        payload["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]
    if color is not None:
        payload["color"] = str(color).strip()
    if status is not None:
        normalized_status = str(status).strip().lower()
        if normalized_status not in {"active", "archived"}:
            return {"status": "error", "message": "invalid project status", "project_id": pid}
        payload["status"] = normalized_status
    if not payload:
        return {"status": "error", "message": "no project fields to update", "project_id": pid}

    proj_mgr = get_project_store()
    with _PROJECTS_IO_LOCK:
        if payload.get("name"):
            conflict = _find_project_name_conflict(
                str(payload["name"]),
                exclude_project_id=pid,
            )
            if conflict:
                return {
                    "status": "error",
                    "message": f"项目名称“{payload['name']}”已存在",
                    "project_id": pid,
                    "conflict_project_id": conflict.get("id"),
                }
        try:
            success = proj_mgr.update_project(pid, **payload)
        except sqlite3.IntegrityError:
            return {
                "status": "error",
                "message": f"项目名称“{payload.get('name') or ''}”已存在",
                "project_id": pid,
            }
        project = proj_mgr.get_project(pid) if success else None
    if not success or not project:
        return {"status": "error", "message": "project not found or update failed", "project_id": pid}
    try:
        stats = proj_mgr.get_project_stats(pid)
        project = dict(project)
        project["file_count"] = stats.get("total_files", project.get("file_count", 0))
    except Exception as exc:
        _logger.debug("Could not get stats for project %s: %s", pid, exc)
    return {"status": "success", "message": "project updated", "project_id": pid, "project": project}


def get_lsv_summary(
    project_id: str,
    page: int = 1,
    page_size: int = 15,
    sort_by: str = "eta",
) -> Dict[str, Any]:
    pid = str(project_id or "").strip()
    if not pid:
        return {"status": "error", "message": "missing project id", "lsv_summary": {"samples": []}}
    hist_mgr = get_history_store()
    summary = hist_mgr.get_lsv_summary(project_id=pid)
    samples = list(summary.get("samples", []))
    total = len(samples)
    if sort_by == "tafel":
        samples.sort(key=lambda x: x.get("tafel_slope", 999))
    else:
        samples.sort(
            key=lambda x: (
                0 if x.get("overpotential_10") is not None else 1,
                x.get("overpotential_10")
                if x.get("overpotential_10") is not None
                else (x.get("potential_10") if x.get("potential_10") is not None else 999),
            )
        )

    safe_page_size = max(1, min(int(page_size), 100))
    safe_page = max(1, int(page))
    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    paged_samples = samples[start:end]

    payload = dict(summary)
    payload["samples"] = paged_samples
    payload["total"] = total
    payload["page"] = safe_page
    payload["page_size"] = safe_page_size
    payload["total_pages"] = (total + safe_page_size - 1) // safe_page_size

    return {"status": "success", "project_id": pid, "lsv_summary": payload}
