"""Run recipes, checked replay jobs, exact-history comparisons, and report exports."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from electrochem_v6.core.run_replay import build_replay_plan
from electrochem_v6.server.request_utils import read_json
from electrochem_v6.store.run_recipes import get_run_recipe, list_run_recipes_page


def dispatch_runs_get(handler: Any) -> bool:
    parsed = urlparse(handler.path)
    path = parsed.path.rstrip("/")
    if path == "/api/v1/runs":
        query = parse_qs(parsed.query)
        try:
            limit = int(query.get("limit", ["100"])[0])
            offset = int(query.get("offset", ["0"])[0])
        except ValueError:
            limit = 100
            offset = 0
        page = list_run_recipes_page(query.get("project_id", [None])[0], limit=limit, offset=offset)
        handler._send_json(200, {"status": "success", **page})
        return True
    parts = path.strip("/").split("/")
    if len(parts) != 4 or parts[:3] != ["api", "v1", "runs"]:
        return False
    run = get_run_recipe(unquote(parts[3]))
    handler._send_json(
        200 if run else 404,
        {"status": "success", "run": run} if run else
        {"status": "error", "message": "这次历史运行未保存完整配方，无法可靠恢复参数；仍可查看已有历史结果"},
    )
    return True


def dispatch_runs_post(handler: Any, manager: Any) -> bool:
    path = urlparse(handler.path).path.rstrip("/")
    parts = path.strip("/").split("/")
    run_action = len(parts) == 5 and parts[:3] == ["api", "v1", "runs"] and parts[4] in {"replay-plan", "replay", "report"}
    project_report = len(parts) == 5 and parts[:3] == ["api", "v1", "projects"] and parts[4] == "report"
    comparison = path == "/api/v1/history/compare"
    if not (run_action or project_report or comparison):
        return False
    try:
        payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        if comparison:
            from electrochem_v6.core.history_compare import compare_history_records

            result = compare_history_records(
                left_record_key=str(payload.get("left_record_key") or ""), right_record_key=str(payload.get("right_record_key") or ""),
                project_id=payload.get("project_id"),
            )
            handler._send_json(200 if result.get("status") == "success" else 400, result)
        elif project_report:
            from electrochem_v6.config import user_config_dir
            from electrochem_v6.core.project_report import export_project_report
            from electrochem_v6.store.history import build_project_report
            from electrochem_v6.store.runtime import get_database

            project_id = unquote(parts[3])
            project = get_database().get_project(project_id)
            if not project:
                raise LookupError("项目不存在")
            report = build_project_report(
                project_id, include_archived=payload.get("include_archived") is True,
                run_ids=payload.get("run_ids"), record_keys=payload.get("record_keys"),
            )
            if report.get("status") != "success":
                handler._send_json(400, report)
                return True
            result = export_project_report(
                project=project, report_data=report["report"], output_dir=str(user_config_dir() / "project_reports"),
                format=str(payload.get("format") or "html"),
            )
            handler._send_json(200 if result.get("status") == "success" else 400, result)
        elif parts[4] == "report":
            from electrochem_v6.config import user_config_dir
            from electrochem_v6.core.reproducible_report_service import export_run_report

            result = export_run_report(unquote(parts[3]), output_dir=str(user_config_dir() / "project_reports"), format=str(payload.get("format") or "html"))
            handler._send_json(200 if result.get("status") == "success" else 400, result)
        else:
            plan = build_replay_plan(unquote(parts[3]), payload)
            process_payload = plan.pop("payload")
            if parts[4] == "replay-plan":
                handler._send_json(200, {"status": "success", "plan": plan})
            elif not plan["can_replay"]:
                handler._send_json(409, {"status": "error", "message": "; ".join(plan["issues"]), "plan": plan})
            elif getattr(manager, "_job_manager", None) is None:
                handler._send_json(503, {"status": "error", "message": "处理任务服务不可用"})
            else:
                job = manager._job_manager.submit_process(process_payload)
                handler._send_json(202, {"status": "success", "job": job, "job_id": job["job_id"]})
    except LookupError as exc:
        handler._send_json(404, {"status": "error", "message": str(exc)})
    except ValueError as exc:
        handler._send_json(400, {"status": "error", "message": str(exc)})
    return True
