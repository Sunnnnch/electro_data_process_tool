"""Shared processing/assistant task panel routes."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from electrochem_v6.core.task_service import list_tasks, task_summary
from electrochem_v6.server.request_utils import read_json
from electrochem_v6.store.runtime import get_database


def dispatch_tasks_get(handler: Any, manager: Any = None) -> bool:
    parsed = urlparse(handler.path)
    parts = parsed.path.rstrip("/").strip("/").split("/")
    if parts[:3] != ["api", "v1", "tasks"] or len(parts) not in {3, 4}:
        return False
    runner = getattr(manager, "_job_manager", None)
    try:
        if len(parts) == 3:
            query = parse_qs(parsed.query)
            result = list_tasks(kind=query.get("kind", ["all"])[0], status=query.get("status", ["all"])[0],
                                limit=int(query.get("limit", ["30"])[0]), offset=int(query.get("offset", ["0"])[0]), manager=runner)
            handler._send_json(200, result)
        else:
            job = get_database().get_processing_job(unquote(parts[3]))
            handler._send_json(200 if job else 404, {"status": "success", "task": task_summary(job, runner)} if job else {"status": "error", "message": "任务不存在或已超出保留范围"})
    except ValueError as exc:
        handler._send_json(400, {"status": "error", "message": str(exc)})
    return True


def dispatch_tasks_post(handler: Any, manager: Any = None) -> bool:
    parts = urlparse(handler.path).path.rstrip("/").strip("/").split("/")
    if len(parts) != 5 or parts[:3] != ["api", "v1", "tasks"] or parts[4] != "cancel":
        return False
    try:
        read_json(handler, handler.MAX_JSON_BODY_BYTES)
        job_id = unquote(parts[3])
        runner = getattr(manager, "_job_manager", None)
        if not runner or not runner.can_cancel(job_id) or not runner.cancel(job_id):
            handler._send_json(409, {"status": "error", "message": "任务已结束、正在保存结果，或由其他程序实例执行；请刷新任务状态"})
        else:
            handler._send_json(200, {"status": "success", "job_id": job_id, "cancel_requested": True})
    except ValueError as exc:
        handler._send_json(400, {"status": "error", "message": str(exc)})
    return True
