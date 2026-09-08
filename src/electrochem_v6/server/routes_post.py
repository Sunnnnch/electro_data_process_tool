"""POST route dispatcher for v6 server."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from electrochem_v6.config import user_config_dir
from electrochem_v6.core import (
    discover_process_inputs,
    export_diagnostics,
    open_path_target,
    preflight_process_folder,
    process_folder,
    select_file_dialog,
    select_files_dialog,
    select_folder_dialog,
)
from electrochem_v6.core.artifact_lifecycle import create_active_upload_root, finish_uploaded_run
from electrochem_v6.core.logging_policy import get_v6_logger, log_event
from electrochem_v6.core.storage_service import cleanup_orphaned_runs
from electrochem_v6.core.upload_recovery import build_upload_source
from electrochem_v6.llm import check_provider_connection, update_provider
from electrochem_v6.llm.model_discovery import discover_provider_models
from electrochem_v6.server.request_utils import (
    extract_zip_safely,
    parse_multipart_form,
    path_parts,
    read_body_with_limit,
    read_json,
    write_uploaded_zip,
)
from electrochem_v6.server.routes_recovery import dispatch_recovery_post
from electrochem_v6.server.routes_replicates import dispatch_replicates_post
from electrochem_v6.server.routes_runs import dispatch_runs_post
from electrochem_v6.server.routes_tasks import dispatch_tasks_post
from electrochem_v6.store.conversations import delete_conversation, rename_conversation
from electrochem_v6.store.history import attach_run_provenance
from electrochem_v6.store.process_templates import delete_process_template, save_process_template
from electrochem_v6.store.projects import (
    create_project,
    delete_project,
    permanently_delete_project,
    restore_project,
    update_project,
    update_project_sample,
)
from electrochem_v6.store.run_recipes import attach_run_upload_source
from electrochem_v6.store.runtime import get_database

_LOGGER = get_v6_logger("electrochem_v6.routes.post")


def _parse_params_value(params_value: Any):
    if not params_value:
        return None
    if isinstance(params_value, dict):
        return params_value
    if not isinstance(params_value, str):
        params_value = str(params_value)
    try:
        parsed = json.loads(params_value)
    except json.JSONDecodeError as exc:
        raise ValueError("params 字段必须是合法 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("params 字段必须是 JSON 对象")
    return parsed


def _uploaded_zip_output_dir() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_token = uuid.uuid4().hex[:8]
    try:
        root = user_config_dir() / "runs" / "uploads"
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        root = Path(tempfile.gettempdir()) / "electrochem_v6" / "runs" / "uploads"
        root.mkdir(parents=True, exist_ok=True)
    target = root / f"{stamp}_{run_token}"
    create_active_upload_root(target)
    return str(target)


def _safe_upload_filename(file_item: Any) -> str:
    original = str(file_item.get_filename() or "upload.zip").replace("\\", "/")
    base = original.rsplit("/", 1)[-1]
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._")[:120]
    if not stem.lower().endswith(".zip"):
        stem = f"{stem or 'upload'}.zip"
    return stem or "upload.zip"


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_run_id(manifest: dict[str, Any]) -> str:
    run = manifest.get("run")
    nested_id = run.get("run_id") if isinstance(run, dict) else None
    return str(nested_id or manifest.get("run_id") or "").strip()


def _finish_uploaded_source(run_root: str, *, keep: bool) -> None:
    # A captured recipe is recoverable even when processing never returned a
    # successful result. Keep its ZIP after releasing the active upload lease.
    retained = keep or get_database().count_artifact_root_references(str(Path(run_root).resolve())) > 0
    finish_uploaded_run(run_root, keep=retained)


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
    coupled_input_mode = fields.get("coupled_input_mode")
    coupled_products_file = fields.get("coupled_products_file")
    coupled_products_sheet = fields.get("coupled_products_sheet")
    coupled_peak_method_file = fields.get("coupled_peak_method_file")
    coupled_results_csv_filename = fields.get("coupled_results_csv_filename")
    params_obj = _parse_params_value(fields.get("params"))

    temp_dir = None
    run_root = None
    keep_run = False
    try:
        run_root = _uploaded_zip_output_dir()
        source_dir = os.path.join(run_root, "source")
        output_dir = os.path.join(run_root, "outputs")
        os.makedirs(source_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        zip_path = os.path.join(source_dir, _safe_upload_filename(file_item))
        write_uploaded_zip(file_item, zip_path, max_upload_file_bytes=handler.MAX_UPLOAD_FILE_BYTES)
        archive_sha256 = _sha256_file(zip_path)

        temp_dir = tempfile.mkdtemp(prefix="electrochem_v6_upload_")
        extract_dir = os.path.join(temp_dir, "data")
        os.makedirs(extract_dir, exist_ok=True)

        extract_zip_safely(
            zip_path,
            extract_dir,
            max_zip_files=handler.MAX_ZIP_FILES,
            max_zip_uncompressed_bytes=handler.MAX_ZIP_UNCOMPRESSED_BYTES,
        )
        params_obj = dict(params_obj or {})
        field_params = {
            "potential_offset": potential_offset,
            "area": electrode_area,
            "lsv_target_current": target_current,
            "tafel_range": tafel_range,
            "coupled_input_mode": coupled_input_mode,
            "coupled_products_file": coupled_products_file,
            "coupled_products_sheet": coupled_products_sheet,
            "coupled_peak_method_file": coupled_peak_method_file,
            "coupled_results_csv_filename": coupled_results_csv_filename,
        }
        for key, value in field_params.items():
            if value not in (None, ""):
                params_obj[key] = value
        result = process_folder(
            {
                "folder_path": extract_dir,
                "data_types": [data_type],
                "project_name": project_name,
                "output_dir": output_dir,
                "params": params_obj,
                "_upload_source": build_upload_source(
                    zip_path=zip_path, source_archive_sha256=archive_sha256,
                    artifact_root=run_root, input_root=extract_dir,
                ),
            }
        )
        if result.get("status") != "success":
            return result
        raw_result_payload = result.get("result")
        result_payload: dict[str, Any] = raw_result_payload if isinstance(raw_result_payload, dict) else {}
        raw_manifest = result_payload.get("manifest")
        manifest: dict[str, Any] = raw_manifest if isinstance(raw_manifest, dict) else {}
        run_id = _manifest_run_id(manifest)
        provenance = {
            "source_archive_path": zip_path,
            "source_archive_sha256": archive_sha256,
            "artifact_root": run_root,
            "artifact_owner": "application",
        }
        metadata_path = os.path.join(run_root, "upload_metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    **provenance,
                    "original_filename": str(file_item.get_filename() or "upload.zip"),
                    "stored_at": datetime.now().isoformat(),
                    "run_id": run_id or None,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
        provenance["metadata_path"] = metadata_path
        if run_id:
            attach_run_provenance(run_id=run_id, **{
                key: provenance[key]
                for key in ("source_archive_path", "artifact_root", "artifact_owner")
            })
            attach_run_upload_source(run_id, source_archive_path=zip_path, source_archive_sha256=provenance["source_archive_sha256"], artifact_root=run_root)
        result_payload["provenance"] = provenance
        keep_run = True
        return result
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        if run_root:
            _finish_uploaded_source(run_root, keep=keep_run)


def _prepare_uploaded_zip_job(handler: Any, fields: dict[str, Any], files: dict[str, Any]) -> dict[str, Any]:
    """Persist an uploaded archive so extraction and processing can run in a job."""
    file_item = files.get("file")
    if file_item is None:
        raise ValueError("缺少 file 字段")
    run_root = _uploaded_zip_output_dir()
    try:
        source_dir = os.path.join(run_root, "source")
        output_dir = os.path.join(run_root, "outputs")
        os.makedirs(source_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        zip_path = os.path.join(source_dir, _safe_upload_filename(file_item))
        write_uploaded_zip(file_item, zip_path, max_upload_file_bytes=handler.MAX_UPLOAD_FILE_BYTES)
        params_obj = dict(_parse_params_value(fields.get("params")) or {})
        field_params = {
            "potential_offset": fields.get("potential_offset"),
            "area": fields.get("electrode_area"),
            "lsv_target_current": fields.get("target_current"),
            "tafel_range": fields.get("tafel_range"),
            "coupled_input_mode": fields.get("coupled_input_mode"),
            "coupled_products_file": fields.get("coupled_products_file"),
            "coupled_products_sheet": fields.get("coupled_products_sheet"),
            "coupled_peak_method_file": fields.get("coupled_peak_method_file"),
            "coupled_results_csv_filename": fields.get("coupled_results_csv_filename"),
        }
        for key, value in field_params.items():
            if value not in (None, ""):
                params_obj[key] = value
        return {
            "run_root": run_root,
            "zip_path": zip_path,
            "output_dir": output_dir,
            "original_filename": str(file_item.get_filename() or "upload.zip"),
            "source_archive_sha256": _sha256_file(zip_path),
            "data_type": str(fields.get("data_type") or "LSV").upper(),
            "project_name": (fields.get("project_name") or "").strip() or None,
            "params": params_obj,
            "max_zip_files": int(handler.MAX_ZIP_FILES),
            "max_zip_uncompressed_bytes": int(handler.MAX_ZIP_UNCOMPRESSED_BYTES),
        }
    except Exception:
        finish_uploaded_run(run_root)
        raise


def _process_prepared_uploaded_zip(
    prepared: dict[str, Any],
    *,
    cancel_check=None,
    progress_callback=None,
) -> dict[str, Any]:
    """Extract and process a previously persisted upload with cooperative cancellation."""
    temp_dir = None
    keep_run = False
    run_root = str(prepared["run_root"])
    try:
        if cancel_check and cancel_check():
            from electrochem_v6.core.job_control import ProcessingCancelledError

            raise ProcessingCancelledError("AI upload job was cancelled")
        temp_dir = tempfile.mkdtemp(prefix="electrochem_v6_upload_")
        extract_dir = os.path.join(temp_dir, "data")
        os.makedirs(extract_dir, exist_ok=True)
        extract_zip_safely(
            str(prepared["zip_path"]),
            extract_dir,
            max_zip_files=int(prepared["max_zip_files"]),
            max_zip_uncompressed_bytes=int(prepared["max_zip_uncompressed_bytes"]),
        )
        payload: dict[str, Any] = {
            "folder_path": extract_dir,
            "data_types": [str(prepared["data_type"])],
            "project_name": prepared.get("project_name"),
            "output_dir": str(prepared["output_dir"]),
            "params": dict(prepared.get("params") or {}),
            "_upload_source": build_upload_source(
                zip_path=str(prepared["zip_path"]), source_archive_sha256=str(prepared["source_archive_sha256"]),
                artifact_root=run_root, input_root=extract_dir,
            ),
        }
        if cancel_check:
            payload["_cancel_check"] = cancel_check
        if progress_callback:
            payload["_progress_callback"] = progress_callback
        if prepared.get("_job_id"):
            payload["_job_id"] = prepared["_job_id"]
        if prepared.get("_job_owner"):
            payload["_job_owner"] = prepared["_job_owner"]
        result = process_folder(payload)
        if result.get("status") != "success":
            return result
        raw_result_payload = result.get("result")
        result_payload: dict[str, Any] = raw_result_payload if isinstance(raw_result_payload, dict) else {}
        raw_manifest = result_payload.get("manifest")
        manifest: dict[str, Any] = raw_manifest if isinstance(raw_manifest, dict) else {}
        run_id = _manifest_run_id(manifest)
        provenance = {
            "source_archive_path": str(prepared["zip_path"]),
            "source_archive_sha256": str(prepared["source_archive_sha256"]),
            "artifact_root": run_root,
            "artifact_owner": "application",
        }
        metadata_path = os.path.join(run_root, "upload_metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    **provenance,
                    "original_filename": str(prepared["original_filename"]),
                    "stored_at": datetime.now().isoformat(),
                    "run_id": run_id or None,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
        provenance["metadata_path"] = metadata_path
        if run_id:
            attach_run_provenance(
                run_id=run_id,
                source_archive_path=provenance["source_archive_path"],
                artifact_root=provenance["artifact_root"],
                artifact_owner=provenance["artifact_owner"],
            )
            attach_run_upload_source(run_id, source_archive_path=provenance["source_archive_path"], source_archive_sha256=provenance["source_archive_sha256"], artifact_root=run_root)
        result_payload["provenance"] = provenance
        keep_run = True
        return result
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        _finish_uploaded_source(run_root, keep=keep_run)


def dispatch_post(handler: Any, manager: Any) -> bool:
    if dispatch_replicates_post(handler, manager):
        return True
    if dispatch_tasks_post(handler, manager):
        return True
    if dispatch_recovery_post(handler, manager):
        return True
    if dispatch_runs_post(handler, manager):
        return True
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

    if path == "/api/v1/system/select-file":
        initial_path = None
        extensions = None
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
            if isinstance(payload, dict):
                initial_path = payload.get("initial_path")
                extensions = payload.get("extensions")
        except ValueError:
            pass
        result = select_file_dialog(
            initial_path=initial_path,
            extensions=extensions if isinstance(extensions, list) else None,
        )
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path == "/api/v1/system/select-files":
        initial_path = None
        extensions = None
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
            if isinstance(payload, dict):
                initial_path = payload.get("initial_path")
                extensions = payload.get("extensions")
        except ValueError:
            pass
        result = select_files_dialog(
            initial_path=initial_path,
            extensions=extensions if isinstance(extensions, list) else None,
        )
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path == "/api/v1/process/discover-inputs":
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        except ValueError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        result = discover_process_inputs(payload)
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

        result = delete_history_record(
            str((payload or {}).get("history_key") or ""),
            delete_artifacts=bool((payload or {}).get("delete_artifacts", True)),
        )
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
        result = create_project(
            name=name or "", description=description, tags=tags, color=color,
            default_template_name=payload.get("default_template_name", ""),
        )
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path.startswith("/api/v1/projects/") and path.endswith("/delete"):
        parts = path_parts(path)
        if len(parts) >= 5:
            project_id = parts[3]
            result = delete_project(project_id)
            handler._send_json(200 if result.get("status") == "success" else 404, result)
            return True

    if path.startswith("/api/v1/projects/") and path.endswith("/restore"):
        parts = path_parts(path)
        if len(parts) >= 5:
            result = restore_project(parts[3])
            handler._send_json(200 if result.get("status") == "success" else 409, result)
            return True

    if path.startswith("/api/v1/projects/") and path.endswith("/delete-permanent"):
        parts = path_parts(path)
        if len(parts) >= 5:
            try:
                payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
            except ValueError as exc:
                handler._send_json(400, {"status": "error", "message": str(exc)})
                return True
            result = permanently_delete_project(
                parts[3],
                delete_artifacts=bool((payload or {}).get("delete_artifacts", True)),
            )
            handler._send_json(200 if result.get("status") == "success" else 409, result)
            return True

    if path.startswith("/api/v1/projects/") and path.endswith("/update"):
        parts = path_parts(path)
        if len(parts) == 7 and parts[4] == "samples":
            try:
                payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
            except ValueError as exc:
                handler._send_json(400, {"status": "error", "message": str(exc)})
                return True
            result = update_project_sample(
                parts[3],
                parts[5],
                note=payload.get("note") if isinstance(payload, dict) else None,
                tags=payload.get("tags")
                if isinstance(payload, dict) and isinstance(payload.get("tags"), list)
                else None,
            )
            handler._send_json(200 if result.get("status") == "success" else 400, result)
            return True
        if len(parts) >= 5:
            project_id = parts[3]
            try:
                payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
            except ValueError as exc:
                handler._send_json(400, {"status": "error", "message": str(exc)})
                return True
            if "default_template_name" in payload and not isinstance(payload["default_template_name"], str):
                handler._send_json(400, {"status": "error", "message": "项目常用模板名称必须是字符串"})
                return True
            result = update_project(
                project_id,
                name=payload.get("name") if isinstance(payload, dict) else None,
                description=payload.get("description") if isinstance(payload, dict) else None,
                tags=payload.get("tags")
                if isinstance(payload, dict) and isinstance(payload.get("tags"), list)
                else None,
                color=payload.get("color") if isinstance(payload, dict) else None,
                status=payload.get("status") if isinstance(payload, dict) else None,
                default_template_name=payload.get("default_template_name"),
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
        log_event(
            _LOGGER,
            "llm.config.update.request",
            {
                "path": path,
                "provider": payload.get("provider"),
                "model": payload.get("model"),
                # NOTE: payload 中可能包含 api_key，不记录完整 payload
            },
        )
        result = update_provider(payload)
        log_event(
            _LOGGER,
            "llm.config.update.result",
            {"path": path, "status": result.get("status"), "provider": result.get("provider")},
            level=logging.INFO if result.get("status") == "success" else logging.WARNING,
        )
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path == "/api/v1/llm/models":
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        except ValueError:
            handler._send_json(400, {"status": "error", "code": "invalid_config", "message": "模型列表请求格式无效"})
            return True
        result = discover_provider_models(payload)
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path == "/api/v1/llm/test":
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        except ValueError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        result = check_provider_connection(payload)
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path == "/api/v1/agent/jobs":
        content_type = (handler.headers.get("Content-Type") or "").lower()
        if "multipart/form-data" in content_type:
            try:
                body = read_body_with_limit(handler, max_bytes=handler.MAX_UPLOAD_BODY_BYTES)
                fields, files = parse_multipart_form(body, content_type)
                prepared = _prepare_uploaded_zip_job(handler, fields, files)
            except ValueError as exc:
                handler._send_json(400, {"status": "error", "message": str(exc)})
                return True
            if manager._job_manager is None:
                finish_uploaded_run(str(prepared["run_root"]))
                handler._send_json(503, {"status": "error", "message": "AI job manager is unavailable"})
                return True
            payload = {
                "message": str(fields.get("message") or fields.get("instruction") or "").strip(),
                "conversation_id": fields.get("conversation_id"),
                "provider": fields.get("provider"),
                "model": fields.get("model"),
                "project_name": fields.get("project_name"),
                "data_type": str(fields.get("data_type") or "LSV").upper(),
                "prompt_prefix": fields.get("prompt_prefix"),
                "_prepared_upload": prepared,
            }
            try:
                job = manager._job_manager.submit_agent(payload)
            except Exception:
                finish_uploaded_run(str(prepared["run_root"]))
                raise
            handler._send_json(202, {"status": "success", "job": job, "job_id": job.get("job_id")})
            return True
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        except ValueError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        if manager._job_manager is None:
            handler._send_json(503, {"status": "error", "message": "AI job manager is unavailable"})
            return True
        if (
            not str(payload.get("message") or "").strip()
            and not payload.get("processing_result")
            and not str(payload.get("approval_id") or "").strip()
        ):
            handler._send_json(400, {"status": "error", "message": "message 字段不能为空"})
            return True
        job = manager._job_manager.submit_agent(payload)
        handler._send_json(202, {"status": "success", "job": job, "job_id": job.get("job_id")})
        return True

    if path.startswith("/api/v1/agent/jobs/") and path.endswith("/cancel"):
        parts = path_parts(path)
        if len(parts) >= 6:
            job_id = unquote(parts[4])
            job = get_database().get_processing_job(job_id)
            if not job or job.get("kind") != "agent":
                handler._send_json(404, {"status": "error", "message": "AI job not found"})
                return True
            if manager._job_manager is None:
                handler._send_json(503, {"status": "error", "message": "AI job manager is unavailable"})
                return True
            requested = manager._job_manager.cancel(job_id)
            handler._send_json(
                200 if requested else 409,
                {"status": "success", "job_id": job_id, "cancel_requested": True}
                if requested
                else {"status": "error", "message": "AI job is not cancellable", "job_id": job_id},
            )
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
                prompt_prefix=fields.get("prompt_prefix"),
                professional_context=None,
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
            prompt_prefix=payload.get("prompt_prefix"),
            professional_context=(
                payload.get("professional_context")
                if isinstance(payload.get("professional_context"), dict)
                else None
            ),
            approval_id=payload.get("approval_id"),
            approval_action=payload.get("approval_action"),
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

    if path == "/api/v1/process/jobs":
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        except ValueError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        if manager._job_manager is None:
            handler._send_json(503, {"status": "error", "message": "processing job manager is unavailable"})
            return True
        job = manager._job_manager.submit_process(payload)
        handler._send_json(202, {"status": "success", "job": job, "job_id": job.get("job_id")})
        return True

    if path.startswith("/api/v1/process/jobs/") and path.endswith("/cancel"):
        parts = path_parts(path)
        if len(parts) >= 6:
            job_id = unquote(parts[4])
            if manager._job_manager is None:
                handler._send_json(503, {"status": "error", "message": "processing job manager is unavailable"})
                return True
            requested = manager._job_manager.cancel(job_id)
            handler._send_json(
                200 if requested else 409,
                {"status": "success", "job_id": job_id, "cancel_requested": True}
                if requested
                else {"status": "error", "message": "job is not cancellable", "job_id": job_id},
            )
            return True

    if path == "/api/v1/process/preflight":
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        except ValueError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        result = preflight_process_folder(payload)
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path == "/api/v1/diagnostics/export":
        result = export_diagnostics()
        handler._send_json(200 if result.get("status") == "success" else 500, result)
        return True

    if path == "/api/v1/storage/cleanup":
        result = cleanup_orphaned_runs()
        handler._send_json(200, result)
        return True

    if path == "/api/v1/process/templates":
        try:
            payload = read_json(handler, handler.MAX_JSON_BODY_BYTES)
        except ValueError as exc:
            handler._send_json(400, {"status": "error", "message": str(exc)})
            return True
        result = save_process_template(
            name=payload.get("name") or "",
            state=payload.get("state") or {},
            overwrite=bool(payload.get("overwrite", False)),
        )
        handler._send_json(200 if result.get("status") == "success" else 400, result)
        return True

    if path.startswith("/api/v1/process/templates/") and path.endswith("/delete"):
        parts = path_parts(path)
        if len(parts) >= 6:
            template_name = unquote(parts[4])
            # Prevent path traversal in template name
            if ".." in template_name or "/" in template_name or "\\" in template_name:
                handler._send_json(400, {"status": "error", "message": "无效的模板名称"})
                return True
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
                {
                    "status": "success",
                    "message": "conversation renamed",
                    "conversation_id": conversation_id,
                    "title": title,
                },
            )
            return True

    return False
