"""Project store adapter for v6."""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from electrochem_v6.config import ensure_parent_dir

from .legacy_runtime import _USE_SQLITE, get_history_manager_v6, get_project_manager_v6

_PROJECTS_IO_LOCK = threading.RLock()
_logger = logging.getLogger(__name__)

_MAX_PROJECT_NAME_LEN = 128
_MAX_DESCRIPTION_LEN = 1024
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


def _safe_load_projects(projects_file: str) -> dict[str, Any]:
    try:
        with open(projects_file, "r", encoding="utf-8") as f:
            parsed = json.load(f)
            if isinstance(parsed, dict):
                return parsed
    except Exception as exc:
        _logger.warning("Failed to load projects file %s: %s", projects_file, exc)
    return {"version": "1.0", "projects": [], "default_project": None}


def _atomic_write_json(path: str, data: dict[str, Any]) -> None:
    from electrochem_v6.store._json_utils import atomic_write_json

    target = ensure_parent_dir(Path(path))
    # Create backup before writing
    if target.exists():
        try:
            shutil.copy2(str(target), str(target) + ".bak")
        except Exception:
            _logger.warning("Failed to create backup for %s", path)
    atomic_write_json(target, data)


def _create_project_fallback(
    proj_mgr: Any,
    *,
    name: str,
    description: str,
    tags: List[str],
    color: Optional[str],
) -> Optional[str]:
    """Fallback path when v5 manager fails due terminal encoding side effects."""
    projects_file = str(getattr(proj_mgr, "projects_file", "projects.json"))
    data = _safe_load_projects(projects_file)

    for item in data.get("projects", []):
        if isinstance(item, dict) and item.get("name") == name and item.get("status", "active") == "active":
            return item.get("id")

    try:
        project_id = proj_mgr._generate_project_id()
    except Exception as exc:
        _logger.warning("Failed to generate project id via manager, using fallback: %s", exc)
        project_id = f"proj_fallback_{int(datetime.now().timestamp())}"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not color:
        preset = getattr(proj_mgr, "PRESET_COLORS", ["#2196F3"])
        color = preset[len(data.get("projects", [])) % len(preset)]

    project = {
        "id": project_id,
        "name": name,
        "description": description,
        "created_at": now,
        "updated_at": now,
        "status": "active",
        "tags": tags or [],
        "file_count": 0,
        "color": color,
    }
    if "projects" not in data or not isinstance(data["projects"], list):
        data["projects"] = []
    data["projects"].append(project)
    if not data.get("default_project"):
        data["default_project"] = project_id
    try:
        _atomic_write_json(projects_file, data)
        return project_id
    except Exception as exc:
        _logger.error("Failed to write project file: %s", exc)
        return None


def get_or_create_project_id_by_name(
    name: str | None,
    *,
    description: str = "v6 process api auto-created",
    tags: Optional[List[str]] = None,
    color: Optional[str] = None,
) -> Optional[str]:
    clean_name = str(name or "").strip()
    if not clean_name:
        return None
    proj_mgr = get_project_manager_v6()
    with _PROJECTS_IO_LOCK:
        try:
            for proj in proj_mgr.get_all_projects("active"):
                if proj.get("name") == clean_name:
                    return proj.get("id")
        except Exception as exc:
            _logger.warning("Failed to lookup existing projects: %s", exc)
        # SQLite backend: use the manager's create_project directly
        if _USE_SQLITE:
            return proj_mgr.create_project(
                clean_name,
                description=str(description or "").strip(),
                tags=tags or [],
                color=color,
            )
        return _create_project_fallback(
            proj_mgr,
            name=clean_name,
            description=str(description or "").strip(),
            tags=tags or [],
            color=color,
        )


def list_projects(status: str = "active") -> Dict[str, Any]:
    proj_mgr = get_project_manager_v6()
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


def create_project(
    name: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    color: Optional[str] = None,
) -> Dict[str, Any]:
    clean_name, err = _validate_project_name(name)
    if err or clean_name is None:
        return {"status": "error", "message": err or "项目名称无效"}
    clean_desc = _sanitize_description(description)
    project_id = get_or_create_project_id_by_name(
        clean_name,
        description=clean_desc,
        tags=tags or [],
        color=color,
    )
    if not project_id:
        return {"status": "error", "message": "project create failed"}
    proj_mgr = get_project_manager_v6()
    project = proj_mgr.get_project(project_id)
    return {"status": "success", "project_id": project_id, "project": project}


def delete_project(project_id: str) -> Dict[str, Any]:
    pid = str(project_id or "").strip()
    if not pid:
        return {"status": "error", "message": "missing project id"}
    proj_mgr = get_project_manager_v6()
    with _PROJECTS_IO_LOCK:
        success = proj_mgr.delete_project(pid, delete_data=False)
    if not success:
        return {"status": "error", "message": "project not found or delete failed", "project_id": pid}
    return {"status": "success", "message": "project deleted", "project_id": pid}


def update_project(
    project_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    color: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    pid = str(project_id or "").strip()
    if not pid:
        return {"status": "error", "message": "missing project id"}
    payload: Dict[str, Any] = {}
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
        payload["status"] = str(status).strip()
    if not payload:
        return {"status": "error", "message": "no project fields to update", "project_id": pid}

    proj_mgr = get_project_manager_v6()
    with _PROJECTS_IO_LOCK:
        success = proj_mgr.update_project(pid, **payload)
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
    hist_mgr = get_history_manager_v6()
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
