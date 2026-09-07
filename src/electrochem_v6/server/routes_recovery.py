"""Owner-checked task recovery endpoints; mutations create new jobs only."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from electrochem_v6.core.job_recovery_service import build_recovery_plan, list_recovery_items, resume_recovery
from electrochem_v6.server.request_utils import read_json


def dispatch_recovery_get(handler: Any) -> bool:
    parsed = urlparse(handler.path)
    if parsed.path.rstrip("/") != "/api/v1/process/recovery":
        return False
    query = parse_qs(parsed.query)
    handler._send_json(200, list_recovery_items(query.get("project_id", [None])[0]))
    return True


def dispatch_recovery_post(handler: Any, manager: Any) -> bool:
    path = urlparse(handler.path).path.rstrip("/")
    if path not in {"/api/v1/process/recovery/plan", "/api/v1/process/recovery/resume"}:
        return False
    try:
        payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        recovery_id = payload.get("recovery_id")
        if not isinstance(recovery_id, str):
            raise ValueError("recovery_id 必须指定一条恢复记录")
        if path.endswith("/plan"):
            plan = build_recovery_plan(recovery_id, payload)
            plan.pop("payload", None)
            handler._send_json(200, {"status": "success", "plan": plan})
        elif getattr(manager, "_job_manager", None) is None:
            handler._send_json(503, {"status": "error", "message": "处理任务服务不可用"})
        else:
            result = resume_recovery(recovery_id, payload, manager._job_manager)
            handler._send_json(202 if result.get("status") == "success" else 409, result)
    except (ValueError, LookupError) as exc:
        handler._send_json(400, {"status": "error", "message": str(exc)})
    return True
