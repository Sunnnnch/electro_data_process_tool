"""POST route dispatcher for v6 server."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from typing import Any
from urllib.parse import unquote

from electrochem_v6.core import open_path_target, process_folder, select_folder_dialog
from electrochem_v6.core.logging_policy import get_v6_logger, log_event
from electrochem_v6.llm import update_provider
from electrochem_v6.server.request_utils import (
    extract_zip_safely,
    parse_multipart_form,
    path_parts,
    read_body_with_limit,
    read_json,
    write_uploaded_zip,
)
from electrochem_v6.store.conversations import delete_conversation, rename_conversation
from electrochem_v6.store.process_templates import delete_process_template, save_process_template
from electrochem_v6.store.projects import create_project, delete_project, update_project

_LOGGER = get_v6_logger("electrochem_v6.routes.post")


def _parse_params_value(params_value: Any):
    if not params_value:
        return None
    try:
        parsed = json.loads(str(params_value))
    except json.JSONDecodeError as exc:
        raise ValueError("params 字段必须是合法 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("params 字段必须是 JSON 对象")
    return parsed


def _process_uploaded_zip(handler: Any, fields: dict[str, Any], files: dict[str, Any]) -> dict[str, Any]:
    file_item = files.get("file")
    if file_item is None:
        return {"status": "error", "message": "缺少 file 字段"}

    data_type = str(fields.get("data_type") or "LSV").upper()
    project_name = (fields.get("project_name") or "").strip() or None
    potential_offset = fields.get("potential_offset")
    electrode_area = fields.get("electrode_area")
    target_current = fields.get("target_current")
    tafel_range = fields.get("tafel_range")
    params_obj = _parse_params_value(fields.get("params"))

    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix="electrochem_v6_upload_")
        zip_path = os.path.join(temp_dir, "upload.zip")
        extract_dir = os.path.join(temp_dir, "data")
        os.makedirs(extract_dir, exist_ok=True)

        write_uploaded_zip(file_item, zip_path, max_upload_file_bytes=handler.MAX_UPLOAD_FILE_BYTES)
        extract_zip_safely(
            zip_path,
            extract_dir,
            max_zip_files=handler.MAX_ZIP_FILES,
            max_zip_uncompressed_bytes=handler.MAX_ZIP_UNCOMPRESSED_BYTES,
        )
        return process_folder(
            {
                "folder_path": extract_dir,
                "data_type": data_type,
                "project_name": project_name,
                "potential_offset": potential_offset,
                "electrode_area": electrode_area,
                "target_current": target_current,
                "tafel_range": tafel_range,
                "params": params_obj,
            }
        )
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


def dispatch_post(handler: Any, manager: Any) -> bool:
    path = (handler.path.split("?", 1)[0] or "").rstrip("/") or "/"

    if path == "/api/v1/system/select-folder":
        initial_dir = None
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
            initial_dir = payload.get("initial_dir") if isinstance(payload, dict) else None
        except ValueError:
            initial_dir = None
        result = select_folder_dialog(initial_dir=initial_dir)
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path == "/api/v1/system/open-path":
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        except ValueError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        target_path = payload.get("path") if isinstance(payload, dict) else None
        reveal_only = bool((payload or {}).get("reveal_only", False)) if isinstance(payload, dict) else False
        result = open_path_target(target_path, reveal_only=reveal_only)
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path == "/api/v1/history/archive":
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        except ValueError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        from electrochem_v6.server.routes_history import archive_history_record

        result = archive_history_record(str((payload or {}).get("history_key") or ""))
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path == "/api/v1/history/delete":
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        except ValueError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        from electrochem_v6.server.routes_history import delete_history_record

        result = delete_history_record(str((payload or {}).get("history_key") or ""))
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path == "/api/v1/projects":
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        except ValueError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        name = payload.get("name")
        description = payload.get("description", "")
        tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
        color = payload.get("color")
        result = create_project(name=name, description=description, tags=tags, color=color)
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path.startswith("/api/v1/projects/") and path.endswith("/delete"):
        parts = path_parts(path)
        if len(parts) >= 5:
            project_id = parts[3]
            result = delete_project(project_id)
            handler._send_json(200 if result.get("status") == "success" else 404, result)
            return True

    if path.startswith("/api/v1/projects/") and path.endswith("/update"):
        parts = path_parts(path)
        if len(parts) >= 5:
            project_id = parts[3]
            try:
                payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
            except ValueError as exc:
                handler._send_json(400, {"status": "error", "message": str(exc)})
                return True
            result = update_project(
                project_id,
                name=payload.get("name") if isinstance(payload, dict) else None,
                description=payload.get("description") if isinstance(payload, dict) else None,
                tags=payload.get("tags") if isinstance(payload, dict) and isinstance(payload.get("tags"), list) else None,
                color=payload.get("color") if isinstance(payload, dict) else None,
                status=payload.get("status") if isinstance(payload, dict) else None,
            )
            handler._send_json(200 if result.get("status") == "success" else 400, result)
            return True

    if path == "/api/v1/llm/config":
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        except ValueError as exc:
            log_event(
                _LOGGER,
                "llm.config.update",
                {"status": "error", "message": str(exc), "path": path},
                level=logging.WARNING,
            )
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        log_event(_LOGGER, "llm.config.update.request", {"path": path, "payload": payload})
        result = update_provider(payload)
        log_event(
            _LOGGER,
            "llm.config.update.result",
            {"path": path, "status": result.get("status"), "provider": result.get("provider"), "result": result},
            level=logging.INFO if result.get("status") == "success" else logging.WARNING,
        )
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path == "/api/v1/agent/messages":
        content_type = (handler.headers.get("Content-Type") or "").lower()
        if "multipart/form-data" in content_type:
            try:
                body = read_body_with_limit(handler, max_bytes=handler.MAX_UPLOAD_BODY_BYTES)
                fields, files = parse_multipart_form(body, content_type)
            except ValueError as exc:
                handler._send_json(400, {"status": "error", "message": str(exc)})
                return True

            processing_result = None
            attachments = []
            if files.get("file") is not None:
                try:
                    process_result = _process_uploaded_zip(handler, fields, files)
                except ValueError as exc:
                    handler._send_json(400, {"status": "error", "message": str(exc)})
                    return True
                if process_result.get("status") != "success":
                    handler._send_json(400, process_result)
                    return True
                processing_result = process_result.get("result")
                attachments.append(
                    {
                        "type": "processing_result",
                        "file_name": files["file"].get_filename() or "upload.zip",
                        "project_name": fields.get("project_name"),
                        "data_type": str(fields.get("data_type") or "LSV").upper(),
                        "summary": (processing_result or {}).get("summary"),
                        "output_files": ((processing_result or {}).get("processing") or {}).get("output_files"),
                    }
                )

            message = str(fields.get("message") or fields.get("instruction") or "").strip()
            result = manager._agent_service.chat(
                message=message,
                conversation_id=fields.get("conversation_id"),
                provider=fields.get("provider"),
                model=fields.get("model"),
                project_name=fields.get("project_name"),
                data_type=(str(fields.get("data_type") or "").upper() or None),
                processing_result=processing_result,
                attachments=attachments,
            )
            handler._send_json(200 if result.get("status") == "success" else 400, result)
            return True

        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        except ValueError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        result = manager._agent_service.chat(
            message=payload.get("message", ""),
            conversation_id=payload.get("conversation_id"),
            provider=payload.get("provider"),
            model=payload.get("model"),
            project_name=payload.get("project_name"),
            data_type=payload.get("data_type"),
            processing_result=payload.get("processing_result"),
            attachments=payload.get("attachments") if isinstance(payload.get("attachments"), list) else None,
        )
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path == "/api/v1/process":
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        except ValueError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        result = process_folder(payload)
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path == "/api/v1/process/templates":
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        except ValueError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        result = save_process_template(
            name=payload.get("name"),
            state=payload.get("state"),
            overwrite=bool(payload.get("overwrite", False)),
        )
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path.startswith("/api/v1/process/templates/") and path.endswith("/delete"):
        parts = path_parts(path)
        if len(parts) >= 6:
            template_name = unquote(parts[4])
            result = delete_process_template(template_name)
            handler._send_json(200 if result.get("status") == "success" else 400, result)
            return True

    if path == "/api/v1/process-zip":
        content_type = handler.headers.get("Content-Type", "")
        try:
            body = read_body_with_limit(handler, max_bytes=handler.MAX_UPLOAD_BODY_BYTES)
            fields, files = parse_multipart_form(body, content_type)
            result = _process_uploaded_zip(handler, fields, files)
            handler._send_json(200 if result.get("status") == "success" else 400, result)
        except ValueError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
        except Exception as exc:  # pragma: no cover
            handler._send_json(500, {"status": "error", "message": str(exc)})
        return True

    if path.startswith("/api/v1/agent/conversations/") and path.endswith("/delete"):
        parts = path_parts(path)
        if len(parts) >= 6:
            conversation_id = parts[4]
            manager._agent_service.delete_session(conversation_id)
            ok = delete_conversation(conversation_id)
            if ok:
                handler._send_json(
                    200,
                    {"status": "success", "message": "会话已删除", "conversation_id": conversation_id},
                )
            else:
                handler._send_json(
                    404,
                    {"status": "error", "message": "会话不存在", "conversation_id": conversation_id},
                )
            return True

    if path.startswith("/api/v1/agent/conversations/") and path.endswith("/rename"):
        parts = path_parts(path)
        if len(parts) >= 6:
            conversation_id = parts[4]
            try:
                payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
            except ValueError as exc:
                handler._send_json(400, {"status": "error", "message": str(exc)})
                return True
            title = str((payload or {}).get("title") or "").strip()
            if not title:
                handler._send_json(400, {"status": "error", "message": "title is required"})
                return True
            if len(title) > 80:
                title = title[:80]
            ok = rename_conversation(conversation_id, title)
            if not ok:
                handler._send_json(
                    404,
                    {"status": "error", "message": "conversation not found", "conversation_id": conversation_id},
                )
                return True
            handler._send_json(
                200,
                {"status": "success", "message": "conversation renamed", "conversation_id": conversation_id, "title": title},
            )
            return True

    return False
