"""Owner-verified interruption detection and preflighted recovery into new jobs."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from electrochem_v6.config import APP_VERSION
from electrochem_v6.core.process_owner import inspect_process_owner
from electrochem_v6.store.job_recovery import (
    finish_owned_job,
    list_owned_jobs,
    mark_job_interrupted,
    mark_run_interrupted,
    recovery_claim,
)
from electrochem_v6.store.runtime import get_database

_ACTIVE = {"queued", "running", "interrupted"}


def snapshot_queued_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Capture effective public parameters without doing file processing on enqueue."""
    from electrochem_v6.core.process_service import _build_gui_vars, _normalize_data_types
    from electrochem_v6.core.run_replay import _public_param_keys

    saved = {key: deepcopy(value) for key, value in payload.items()
             if not str(key).startswith("_") or key in {"_parent_run_id", "_parent_record_key", "_replay_expected_sources", "_replay_source_paths", "_upload_source"}}
    saved["_queued_app_version"] = APP_VERSION
    try:
        data_types = _normalize_data_types(saved)
        values = _build_gui_vars(data_types, saved)
        keys = _public_param_keys(data_types)
        saved.update(data_types=data_types, params={key: values[key] for key in keys if key in values})
        saved["_queued_parameter_keys"] = sorted(keys)
    except (ValueError, TypeError, KeyError):
        # Invalid requests can still be enqueued and return their normal error;
        # an old/incomplete snapshot is never presented as a captured recipe.
        saved["_queued_parameter_keys"] = []
    return saved


def snapshot_uploaded_request(prepared: dict[str, Any]) -> dict[str, Any]:
    """Persist only the upload's processing portion, never chat credentials."""
    from electrochem_v6.core.upload_recovery import PREPARED_UPLOAD_SNAPSHOT_KEYS

    safe = {key: deepcopy(prepared[key]) for key in PREPARED_UPLOAD_SNAPSHOT_KEYS if key in prepared}
    saved = snapshot_queued_request({"data_types": [str(safe.get("data_type") or "")],
                                     "params": safe.get("params") or {}, "project_name": safe.get("project_name")})
    safe["params"] = deepcopy(saved.get("params") or {})
    saved["_prepared_upload"] = safe
    return saved


def _saved_runs() -> dict[str, dict[str, Any]]:
    with get_database().read() as connection:
        rows = connection.execute("SELECT value FROM meta WHERE key LIKE 'run_recipe:%'").fetchall()
    runs = [json.loads(row["value"]) for row in rows]
    return {str(item["run_id"]): item for item in runs if isinstance(item, dict) and item.get("run_id")}


def reconcile_interrupted_work() -> dict[str, int]:
    """Only a missing/replaced OS process can change active work to interrupted."""
    changed_jobs = changed_runs = 0
    for owned in list_owned_jobs():
        job = get_database().get_processing_job(owned["job_id"])
        if job and job.get("status") not in _ACTIVE:
            finish_owned_job(owned["job_id"])
            continue
        if inspect_process_owner(owned.get("owner"))["state"] == "dead":
            changed_jobs += int(mark_job_interrupted(owned["job_id"], expected_owner=owned["owner"]))
    for run_id, recipe in _saved_runs().items():
        if recipe.get("status") == "running" and inspect_process_owner(recipe.get("owner"))["state"] == "dead":
            changed_runs += int(mark_run_interrupted(run_id, expected_owner=recipe["owner"]))
    return {"jobs": changed_jobs, "runs": changed_runs}


def _candidates() -> list[dict[str, Any]]:
    runs = _saved_runs()
    owned = {item["job_id"]: item for item in list_owned_jobs()}
    with get_database().read() as connection:
        rows = connection.execute("SELECT * FROM processing_jobs WHERE status IN ('queued','running','interrupted') ORDER BY created_at DESC").fetchall()
    jobs = {str(row["job_id"]): {**dict(row), "payload": json.loads(row["payload"] or "{}")} for row in rows}
    entries = []
    linked_runs = set()
    runs_by_job = {str(item["job_id"]): item for item in runs.values() if item.get("job_id")}
    for job_id in dict.fromkeys([*jobs, *owned]):
        saved, job = owned.get(job_id, {}), jobs.get(job_id, {})
        if (saved.get("kind") or job.get("kind")) != "process" and not (job.get("payload") or {}).get("_prepared_upload"):
            continue
        # A terminal row may still have a snapshot between completion and its
        # cleanup callback; it is not recoverable work.
        actual = get_database().get_processing_job(job_id)
        if actual and actual.get("status") not in _ACTIVE:
            continue
        run = runs.get(str(saved.get("run_id") or "")) or runs_by_job.get(job_id)
        if run:
            linked_runs.add(run["run_id"])
        payload = saved.get("payload") or job.get("payload") or {}
        if not saved and isinstance(payload.get("_prepared_upload"), dict):
            payload = snapshot_uploaded_request(payload["_prepared_upload"])
        owner = saved.get("owner") or (run or {}).get("owner")
        observation = inspect_process_owner(owner)
        if observation["state"] == "alive":
            continue
        entries.append({
            "recovery_id": "job:" + job_id, "job_id": job_id, "run_id": (run or {}).get("run_id"),
            "project_id": (run or {}).get("project_id") or payload.get("project_id"),
            "project_name": payload.get("project_name"), "kind": "process",
            "created_at": job.get("created_at") or saved.get("created_at"),
            "status": "interrupted" if observation["state"] == "dead" else "owner_unknown",
            "owner_state": observation["state"], "reason": observation["reason"],
            "requires_owner_confirmation": observation["state"] == "unknown",
            "can_prepare": (run or {}).get("status") not in {"success", "succeeded"},
            "_payload": payload, "_recipe": run, "_owner": owner,
        })
    for run_id, run in runs.items():
        if run_id in linked_runs or run.get("status") not in {"running", "interrupted"}:
            continue
        observation = inspect_process_owner(run.get("owner"))
        if observation["state"] == "alive":
            continue
        entries.append({
            "recovery_id": "run:" + run_id, "job_id": run.get("job_id"), "run_id": run_id,
            "project_id": run.get("project_id"), "kind": "process", "created_at": run.get("created_at"),
            "status": "interrupted" if observation["state"] == "dead" else "owner_unknown",
            "owner_state": observation["state"], "reason": observation["reason"],
            "requires_owner_confirmation": observation["state"] == "unknown", "can_prepare": True,
            "_payload": {}, "_recipe": run, "_owner": run.get("owner"),
        })
    return entries


def list_recovery_items(project_id: str | None = None) -> dict[str, Any]:
    reconcile_interrupted_work()
    entries = [item for item in _candidates() if (project_id is None or item.get("project_id") in {None, project_id})
               and not recovery_claim(item["recovery_id"])]
    project_names = {}
    for item in entries:
        identifier = item.get("project_id")
        if identifier:
            if identifier not in project_names:
                project_names[identifier] = (get_database().get_project(identifier) or {}).get("name")
            item["project_name"] = project_names[identifier] or item.get("project_name")
    return {"status": "success", "items": [{key: value for key, value in item.items() if not key.startswith("_")} for item in entries]}


def _find_candidate(recovery_id: str) -> dict[str, Any]:
    if not isinstance(recovery_id, str) or not recovery_id.startswith(("job:", "run:")):
        raise ValueError("recovery_id 必须指定一条恢复记录")
    reconcile_interrupted_work()
    for item in _candidates():
        if item["recovery_id"] == recovery_id or (item.get("run_id") and recovery_id == "run:" + item["run_id"]):
            return item
    raise ValueError("任务所属进程仍在运行，或没有可恢复的中断记录")


def _queued_plan(candidate: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    from electrochem_v6.core.process_service import (
        _build_gui_vars,
        _normalize_data_types,
        _normalize_input_files,
        _resolve_processing_folder,
        preflight_process_folder,
    )
    from electrochem_v6.core.processing_manifest import _file_identity
    from electrochem_v6.core.run_replay import _path_key, _public_param_keys, collect_run_inputs

    saved = deepcopy(candidate["_payload"])
    if isinstance(saved.get("_prepared_upload"), dict):
        from electrochem_v6.core.upload_recovery import prepare_queued_upload_recovery

        upload = prepare_queued_upload_recovery(saved["_prepared_upload"], options.get("source_paths"))
        if upload.get("issues"):
            return {"can_recover": False, "issues": upload["issues"], "warnings": upload.get("warnings") or [],
                    "source_checks": upload.get("source_checks") or [], "params": saved.get("params") or {}}
        ordinary = {**saved, **upload["payload"]}
        ordinary.pop("_prepared_upload", None)
        plain_options = {key: value for key, value in options.items() if key != "source_paths"}
        plan = _queued_plan({**candidate, "_payload": ordinary}, plain_options)
        plan["source_checks"] = [*(upload.get("source_checks") or []), *(plan.get("source_checks") or [])]
        plan["warnings"] = [*(upload.get("warnings") or []), *plan["warnings"]]
        return plan
    data_types = _normalize_data_types(saved)
    keys = _public_param_keys(data_types)
    overrides, relocations = options.get("params") or {}, options.get("source_paths") or {}
    if not isinstance(overrides, dict) or not isinstance(relocations, dict):
        raise ValueError("params 和 source_paths 必须是对象")
    if set(overrides) - keys:
        raise ValueError("无法识别的处理参数: " + ", ".join(sorted(set(overrides) - keys)))
    issues, warnings = [], []
    params = {**(saved.get("params") or {}), **overrides}
    known_keys = set(saved.get("_queued_parameter_keys") or [])
    if known_keys and keys - known_keys - set(overrides):
        issues.append("当前版本新增参数，请明确填写后再恢复: " + ", ".join(sorted(keys - known_keys - set(overrides))))
    if not known_keys:
        warnings.append("旧排队请求未保存完整参数快照；恢复将使用当前版本预检后的设置。")
    params.pop("output_dir", None)
    params.pop("run_id", None)
    params["output_run_dir_enabled"] = True
    folder = str(saved.get("folder_path") or "")
    selected = deepcopy(saved.get("input_files"))
    expected = saved.get("_replay_expected_sources") or {}
    original_sources: dict[str, str] = {str(path): "input" for path in expected}
    known_paths = {folder, *expected}
    if isinstance(selected, list):
        for item in selected:
            if isinstance(item, dict) and item.get("enabled") is False:
                continue
            path = str(item.get("path") or "") if isinstance(item, dict) else str(item)
            known_paths.add(path)
            if path:
                original_sources[path] = "primary"
    for key, role in (("ir_eis_file", "ir_eis"), ("coupled_products_file", "product_table"), ("coupled_peak_method_file", "peak_method")):
        if params.get(key):
            known_paths.add(str(params[key]))
            original_sources[str(params[key])] = role
    for old, new in relocations.items():
        if old not in known_paths or not isinstance(new, str) or not new.strip():
            raise ValueError("只能重新定位保存的输入文件或原始目录")
    folder = str(relocations.get(folder, folder))
    if isinstance(selected, list):
        selected = [{**item, "path": relocations.get(item.get("path"), item.get("path"))} if isinstance(item, dict)
                    else relocations.get(item, item) for item in selected]
    for key in ("ir_eis_file", "coupled_products_file", "coupled_peak_method_file"):
        if params.get(key):
            params[key] = relocations.get(params[key], params[key])
    payload = {key: value for key, value in saved.items() if not key.startswith("_") and key not in {"output_dir", "run_id"}}
    payload.update(folder_path=folder, data_types=data_types, params=params)
    if selected is not None:
        payload["input_files"] = selected
    # Keep original path keys even when validation fails or sources are moved
    # repeatedly; those keys are the stable relocation contract used by the UI.
    checks, preflight = [], None
    for original, role in original_sources.items():
        resolved = str(relocations.get(original, original))
        identity = _file_identity(resolved)
        previous = expected.get(original)
        current = identity.get("sha256")
        state = "missing" if not current else "current" if not previous else "unchanged" if previous == current else "changed"
        checks.append({**identity, "path": original, "resolved_path": resolved, "role": role,
                       "file_name": Path(original).name, "expected_sha256": previous,
                       "current_sha256": current, "state": state})
    if folder and not os.path.isdir(folder):
        issues.append("原始数据目录不可用；请明确重新定位目录后预检")
        checks.append({"path": str(saved.get("folder_path") or ""), "resolved_path": folder,
                       "file_name": Path(folder).name, "role": "input_directory", "state": "missing"})
    if not issues:
        result = preflight_process_folder(payload)
        if result.get("status") != "success":
            issues.append(str(result.get("message") or "恢复预检失败"))
        else:
            preflight = result.get("preflight") or {}
            folder = _resolve_processing_folder(payload, _normalize_input_files(payload, data_types))
            payload["folder_path"] = folder
            if int(preflight.get("selected_matched") or 0) <= 0:
                issues.append("预检未找到可处理的数据")
            if isinstance(preflight.get("ir_compensation"), dict) and not preflight["ir_compensation"].get("ok"):
                issues.append("iR 依赖未通过预检")
            warnings.extend(str(item) for item in preflight.get("warnings") or [])
            values = _build_gui_vars(data_types, payload)
            inputs = collect_run_inputs(preflight, values, folder, data_types)
            old_expected = {_path_key(str(relocations.get(path, path))): fingerprint for path, fingerprint in expected.items()}
            originals_by_resolved = {_path_key(str(relocations.get(path, path))): path for path in original_sources}
            checks = []
            for source in inputs:
                previous = old_expected.get(_path_key(source["path"]))
                state = "missing" if not source.get("sha256") else "current" if not previous else "unchanged" if previous == source["sha256"] else "changed"
                checks.append({**source, "path": originals_by_resolved.get(_path_key(source["path"]), source["path"]),
                               "resolved_path": source["path"], "expected_sha256": previous,
                               "current_sha256": source.get("sha256"), "state": state})
            if any(item["state"] == "missing" for item in checks):
                issues.append("存在无法读取或验证的输入文件")
            if expected and set(old_expected) != {_path_key(item["path"]) for item in inputs}:
                issues.append("恢复预检发现输入集合与已保存请求不同，请在处理页重新明确选择数据")
            payload["params"] = {key: values[key] for key in keys if key in values}
            payload["params"]["output_run_dir_enabled"] = True
            payload["params"].pop("output_dir", None)
            payload["_replay_expected_sources"] = {item["path"]: item["sha256"] for item in inputs}
    changed = any(item["state"] == "changed" for item in checks)
    if changed and options.get("allow_changed_sources") is not True:
        issues.append("输入内容已变化；请明确确认后重新预检")
    if not expected:
        warnings.append("原任务排队时尚未保存输入指纹；已列出本次实际输入，恢复会生成新的运行。")
    if saved.get("_parent_run_id"):
        payload["_parent_run_id"] = saved["_parent_run_id"]
    if saved.get("_parent_record_key"):
        payload["_parent_record_key"] = saved["_parent_record_key"]
    if saved.get("_upload_source"):
        payload["_upload_source"] = saved["_upload_source"]
    return {"can_recover": not issues, "issues": issues, "warnings": warnings, "preflight": preflight,
            "params": payload["params"], "data_types": data_types, "input_files": selected or [], "source_checks": checks,
            "requires_changed_confirmation": changed and options.get("allow_changed_sources") is not True,
            "source_app_version": saved.get("_queued_app_version"), "current_app_version": APP_VERSION, "payload": payload}


def build_recovery_plan(recovery_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = dict(options or {})
    candidate = _find_candidate(recovery_id)
    base = {key: value for key, value in candidate.items() if not key.startswith("_")}
    if not candidate["can_prepare"]:
        return {**base, "can_recover": False, "issues": ["这次运行已经保存完成结果，请查看原运行；不需要恢复处理"], "warnings": []}
    if recovery_claim(candidate["recovery_id"]):
        return {**base, "can_recover": False, "issues": ["这条记录已经恢复，请查看新任务"], "warnings": []}
    if candidate["requires_owner_confirmation"] and options.get("confirm_owner_stopped") is not True:
        return {**base, "can_recover": False, "issues": ["缺少可核实的原进程身份；请先确认原程序已关闭，再重新预检。原任务状态不会被自动改写。"], "warnings": []}
    recipe = candidate.get("_recipe")
    if recipe:
        from electrochem_v6.core.run_replay import build_replay_plan

        plan = build_replay_plan(recipe["run_id"], options, allow_running_origin=candidate["requires_owner_confirmation"])
        plan["can_recover"] = plan["can_replay"]
    else:
        plan = _queued_plan(candidate, options)
    if candidate.get("job_id") and "payload" in plan:
        plan["payload"]["_recovered_from_job_id"] = candidate["job_id"]
    if candidate["requires_owner_confirmation"]:
        plan.setdefault("warnings", []).append("原进程状态由用户确认；原记录保留不变，本次创建独立运行。")
    result = {**base, **plan, "recovery_id": candidate["recovery_id"]}
    fingerprint = {key: result.get(key) for key in ("recovery_id", "params", "data_types", "source_checks")}
    result["preflight_token"] = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return result


def resume_recovery(recovery_id: str, options: dict[str, Any], manager: Any) -> dict[str, Any]:
    claimed = recovery_claim(recovery_id)
    if claimed:
        job = get_database().get_processing_job(claimed)
        return {"status": "success", "job_id": claimed, "job": job or {"job_id": claimed, "status": "interrupted"}, "already_resumed": True}
    plan = build_recovery_plan(recovery_id, options)
    payload = plan.pop("payload", None)
    if not plan["can_recover"] or not payload:
        return {"status": "error", "message": "; ".join(plan.get("issues") or []), "plan": plan}
    if options.get("preflight_token") and options["preflight_token"] != plan.get("preflight_token"):
        return {"status": "error", "message": "来源或有效参数在预检后发生变化，请重新核对预检结果", "plan": {**plan, "can_recover": False}}
    # File parsing can take time. A legacy owner may finish while its user is
    # reviewing recovery, so re-observe it after preflight and before claiming.
    current = _find_candidate(plan["recovery_id"])
    if not current["can_prepare"]:
        return {"status": "error", "message": "原运行已经完成，请查看原结果", "plan": {**plan, "can_recover": False}}
    origin = {"job_id": current.get("job_id"), "run_id": current.get("run_id"), "owner": current.get("_owner")}
    job = manager.submit_process(payload, recovery_source=plan["recovery_id"], recovery_origin=origin)
    return {"status": "success", "job_id": job["job_id"], "job": job, "plan": plan}
