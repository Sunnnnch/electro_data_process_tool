"""Compact, persisted task summaries for the shared workbench task panel."""

from __future__ import annotations

import json
from typing import Any

from electrochem_v6.store.runtime import get_database

_STATUSES = {"queued", "running", "succeeded", "failed", "cancelled", "interrupted"}


def _references(job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("payload") or {}
    result = job.get("result") or {}
    reference: dict[str, Any] = {
        "project_id": payload.get("project_id"),
        "project_name": payload.get("project_name"),
        "conversation_id": result.get("conversation_id") or payload.get("conversation_id"),
        "run_id": None,
        "record_keys": [],
    }

    def visit(node: Any, depth: int = 0) -> None:
        if not isinstance(node, dict) or depth > 5:
            return
        for key in ("project_id", "project_name", "run_id", "conversation_id"):
            if node.get(key):
                reference[key] = str(node[key])
        for key in ("result", "processing_result", "approved_action_result", "manifest", "run"):
            visit(node.get(key), depth + 1)

    visit(result)
    database = get_database()
    if not reference["run_id"]:
        with database.read() as connection:
            row = connection.execute(
                "SELECT run_id FROM processing_recovery WHERE job_id=?", (job["job_id"],)
            ).fetchone() if connection.execute("SELECT 1 FROM sqlite_master WHERE name='processing_recovery'").fetchone() else None
        if row:
            reference["run_id"] = row["run_id"]
    if reference["run_id"]:
        from electrochem_v6.store.run_recipes import get_run_recipe

        recipe = get_run_recipe(reference["run_id"])
        if recipe:
            reference["project_id"] = recipe.get("project_id") or reference["project_id"]
            reference["record_keys"] = list(recipe.get("record_keys") or [])
    if reference["project_id"]:
        project = database.get_project(reference["project_id"])
        if project:
            reference["project_name"] = project["name"]
        else:
            reference["project_id"] = None
    if reference["conversation_id"]:
        with database.read() as connection:
            row = connection.execute("SELECT title FROM conversations WHERE conversation_id=?", (reference["conversation_id"],)).fetchone()
        reference["conversation_title"] = row["title"] if row else None
        if not row:
            reference["conversation_id"] = None
    return reference


def task_summary(job: dict[str, Any], manager: Any = None) -> dict[str, Any]:
    """No raw processing payload, credentials, chat text or duplicate results."""
    item = {key: job.get(key) for key in (
        "job_id", "kind", "status", "error", "current_item", "progress_current", "progress_total",
        "cancel_requested", "created_at", "started_at", "finished_at", "updated_at",
    )}
    item["can_cancel"] = bool(manager and manager.can_cancel(job["job_id"]))
    item["cancel_requested"] = bool(item.get("cancel_requested"))
    item["reference"] = _references(job)
    return item


def list_tasks(*, kind: str = "all", status: str = "all", limit: int = 30, offset: int = 0, manager: Any = None) -> dict[str, Any]:
    if kind not in {"all", "process", "agent"} or status not in _STATUSES | {"all", "active"}:
        raise ValueError("任务筛选条件无效")
    if isinstance(limit, bool) or isinstance(offset, bool) or not 1 <= limit <= 100 or offset < 0:
        raise ValueError("任务分页范围无效")
    conditions, parameters = [], []
    if kind != "all":
        conditions.append("kind=?")
        parameters.append(kind)
    if status == "active":
        conditions.append("status IN ('queued','running')")
    elif status != "all":
        conditions.append("status=?")
        parameters.append(status)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    database = get_database()
    with database.read() as connection:
        counts = {row["status"]: row["total"] for row in connection.execute("SELECT status, COUNT(*) AS total FROM processing_jobs GROUP BY status")}
        total = connection.execute("SELECT COUNT(*) FROM processing_jobs" + where, parameters).fetchone()[0]
        rows = connection.execute(
            "SELECT * FROM processing_jobs" + where
            + " ORDER BY CASE WHEN status IN ('queued','running') THEN 0 ELSE 1 END, COALESCE(created_at,'') DESC, job_id DESC LIMIT ? OFFSET ?",
            [*parameters, limit, offset],
        ).fetchall()
    jobs = [{**dict(row), "payload": json.loads(row["payload"] or "{}"), "result": json.loads(row["result"] or "{}")} for row in rows]
    return {"status": "success", "items": [task_summary(job, manager) for job in jobs], "total": total,
            "offset": offset, "limit": limit, "has_more": offset + len(jobs) < total,
            "counts": counts, "active_count": counts.get("queued", 0) + counts.get("running", 0)}
