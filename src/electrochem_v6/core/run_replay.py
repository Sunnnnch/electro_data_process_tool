"""Capture processing recipes and build explicit, source-checked replay requests."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import platform
from datetime import datetime
from pathlib import Path
from typing import Any

from electrochem_v6.config import APP_VERSION
from electrochem_v6.core.processing_formula import FORMULA_SCHEMA_VERSION
from electrochem_v6.core.processing_manifest import _file_identity
from electrochem_v6.core.processing_registry import SUPPORTED_DATA_TYPES, processing_parameter_schema
from electrochem_v6.store.run_recipes import get_run_recipe, save_run_recipe, update_run_recipe
from electrochem_v6.store.runtime import get_database

RECIPE_SCHEMA_VERSION = "1.0"


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _public_param_keys(data_types: list[str]) -> set[str]:
    from electrochem_v6.core.processing_module_runtime import get_processing_module_registry

    keys = {str(item["key"]) for item in processing_parameter_schema(
        [item for item in data_types if item in SUPPORTED_DATA_TYPES]
    )["parameters"]}
    registry = get_processing_module_registry()
    for dtype in data_types:
        keys.update(registry.get_spec(dtype).parameter_keys)
    return keys


def collect_run_inputs(preflight: dict[str, Any], params: dict[str, Any], folder_path: str, data_types: list[str]) -> list[dict[str, Any]]:
    """Capture every primary file and external iR/peak-analysis dependency."""
    files: dict[tuple[str, str], dict[str, Any]] = {}

    def add(path: Any, dtype: str, role: str, for_path: str | None = None) -> None:
        if not str(path or "").strip():
            return
        path = str(Path(str(path)).expanduser().resolve())
        key = (_path_key(path), role)
        if key not in files:
            files[key] = {"path": path, "file_name": os.path.basename(path), "data_type": dtype, "role": role, "for_paths": []}
        if for_path and for_path not in files[key]["for_paths"]:
            files[key]["for_paths"].append(str(Path(for_path).resolve()))

    for dtype, detail in (preflight.get("by_type") or {}).items():
        if dtype not in data_types or dtype == "COUPLED":
            continue
        for path in detail.get("files") or detail.get("examples") or []:
            add(path, dtype, "primary")
    for item in (preflight.get("ir_compensation") or {}).get("items") or []:
        add(item.get("eis_file"), "EIS", "ir_eis", item.get("lsv_file"))
    if "COUPLED" in data_types:
        add(params.get("coupled_products_file"), "COUPLED", "product_table")
        if params.get("coupled_input_mode") == "peak_analysis":
            from electrochem_v6.core.processing_coupled import normalize_coupled_peak_method_source
            from electrochem_v6.core.processing_fe_peak import read_fe_peak_measurements, resolve_fe_peak_method

            method_source = normalize_coupled_peak_method_source(params.get("coupled_peak_method_source"), method_payload=params.get("coupled_peak_method"))
            method_file = params.get("coupled_peak_method_file") if method_source == "file" else None
            method_payload = params.get("coupled_peak_method") if method_source != "file" else None
            add(method_file, "COUPLED", "peak_method")
            method = resolve_fe_peak_method(method_file, method_payload=method_payload)
            sheet = params.get("coupled_products_sheet", 0)
            if isinstance(sheet, str) and sheet.isdigit():
                sheet = int(sheet)
            for row in read_fe_peak_measurements(params["coupled_products_file"], method=method, sheet_name=sheet, allowed_signal_roots=(folder_path,)):
                add(row.signal_file, "COUPLED", "signal")
    return [{**item, **_file_identity(item["path"])} for item in files.values()]


def _engine_identity() -> dict[str, Any]:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("processing*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    dependencies = {}
    for package in ("numpy", "pandas", "scipy"):
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = "unavailable"
    return {"python_version": platform.python_version(), "dependencies": dependencies, "algorithm_sha256": digest.hexdigest()}


def capture_run_recipe(*, run_id: str, project_id: str | None, payload: dict[str, Any], params: dict[str, Any], data_types: list[str], folder_path: str, output_dir: str, preflight: dict[str, Any]) -> dict[str, Any]:
    from electrochem_v6.core.process_owner import current_process_owner
    from electrochem_v6.store.job_recovery import associate_job_run

    inputs = collect_run_inputs(preflight, params, folder_path, data_types)
    expected = payload.get("_replay_expected_sources")
    if isinstance(expected, dict):
        actual = {_path_key(item["path"]): item.get("sha256") for item in inputs}
        if actual != {_path_key(path): fingerprint for path, fingerprint in expected.items()}:
            raise ValueError("复算输入或依赖在预检后发生变化，请重新预检")
    recipe = {
        "schema_version": RECIPE_SCHEMA_VERSION, "run_id": run_id, "project_id": project_id,
        "created_at": datetime.now().isoformat(), "status": "running", "data_types": list(data_types),
        "params": {key: value for key, value in params.items() if key in _public_param_keys(data_types)},
        "parameter_schema_keys": sorted(_public_param_keys(data_types)),
        "folder_path": folder_path, "output_dir": output_dir, "inputs": inputs,
        "parent_run_id": payload.get("_parent_run_id"), "parent_record_key": payload.get("_parent_record_key"),
        "app_version": APP_VERSION, "formula_schema_version": FORMULA_SCHEMA_VERSION,
        "engine": _engine_identity(), "manifest": {}, "records": [], "record_keys": [],
        "source_integrity": "verified" if all(item.get("sha256") for item in inputs) else "unverified",
        "owner": current_process_owner(), "job_id": payload.get("_job_id"),
        "recovered_from_job_id": payload.get("_recovered_from_job_id"),
    }
    parent = get_run_recipe(str(recipe["parent_run_id"])) if recipe["parent_run_id"] else None
    upload = payload.get("_upload_source")
    if isinstance(upload, dict) and upload.get("source_archive_path"):
        members = {_path_key(str(path)): member for path, member in (upload.get("archive_members") or {}).items()}
        for item in inputs:
            if _path_key(item["path"]) in members:
                item["archive_member"] = members[_path_key(item["path"])]
        for key in ("source_archive_path", "source_archive_sha256", "artifact_root", "artifact_owner"):
            recipe[key] = upload.get(key)
    if parent and parent.get("source_archive_path"):
        source_paths = payload.get("_replay_source_paths") or {}
        members = {
            (_path_key(str(source_paths.get(item["path"], item["path"]))), item.get("sha256")): item["archive_member"]
            for item in parent.get("inputs") or [] if item.get("archive_member")
        }
        for item in inputs:
            member = members.get((_path_key(item["path"]), item.get("sha256")))
            if member:
                item["archive_member"] = member
        for key in ("source_archive_path", "source_archive_sha256", "artifact_root"):
            recipe[key] = parent.get(key)
        cache_root = parent.get("replay_cache_root")
        if cache_root and any(Path(item["path"]).resolve().is_relative_to(Path(cache_root).resolve()) for item in inputs):
            recipe["replay_cache_root"] = cache_root
    save_run_recipe(recipe)
    if recipe.get("job_id"):
        associate_job_run(str(recipe["job_id"]), run_id)
    return recipe


def finish_run_recipe(run_id: str, *, status: str, manifest: dict[str, Any] | None = None, error: str | None = None) -> dict[str, Any] | None:
    recipe = get_run_recipe(run_id)
    if not recipe:
        return None
    inputs = recipe.get("inputs") or []
    changed = [item["path"] for item in inputs if _file_identity(item["path"]).get("sha256") != item.get("sha256")]
    with get_database().read() as connection:
        rows = connection.execute("SELECT record_key, type, file_path, sample_name, sample_id FROM history_records WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
    records = []
    for row in rows:
        record = dict(row)
        primary = [item for item in inputs if item["role"] == "primary" and item["data_type"] == record["type"] and (
            _path_key(item["path"]) == _path_key(record["file_path"] or "") or
            (record["type"] == "ECSA" and _path_key(os.path.dirname(item["path"])) == _path_key(record["file_path"] or "")))]
        record["input_paths"] = [item["path"] for item in primary]
        records.append(record)
    updates: dict[str, Any] = {"status": status, "error": error, "finished_at": datetime.now().isoformat(), "records": records, "record_keys": [item["record_key"] for item in records]}
    if changed:
        updates.update(source_integrity="changed_during_processing", changed_during_processing=changed)
    if manifest is not None:
        updates["manifest"] = manifest
    return update_run_recipe(run_id, **updates)


def build_replay_plan(run_id: str, options: dict[str, Any] | None = None, *, allow_running_origin: bool = False) -> dict[str, Any]:
    """Return a reviewable draft; rebuilding this plan is required at submission."""
    from electrochem_v6.core.process_service import (
        _build_gui_vars,
        _is_allowed_process_dir,
        preflight_process_folder,
    )

    options = dict(options or {})
    recipe = get_run_recipe(run_id)
    if recipe is None:
        raise LookupError("这次历史运行未保存完整配方，无法可靠恢复参数；请重新选择原始数据")
    overrides = options.get("params") or {}
    relocations = options.get("source_paths") or {}
    if not isinstance(overrides, dict) or not isinstance(relocations, dict):
        raise ValueError("params 和 source_paths 必须是对象")
    allow_changed = options.get("allow_changed_sources") is True
    data_types = list(recipe.get("data_types") or [])
    issues: list[str] = []
    warnings: list[str] = []
    record_key = str(options.get("record_key") or "").strip() or None
    inputs = list(recipe.get("inputs") or [])
    if recipe.get("schema_version") != RECIPE_SCHEMA_VERSION or not recipe.get("params") or not inputs:
        issues.append("历史配方缺少完整参数或输入清单，不能自动补用当前默认值")
    if recipe.get("status") == "running" and not allow_running_origin:
        issues.append("原运行尚未完成，请等待结束后再复算")
    if recipe.get("history_partially_deleted") and not record_key:
        issues.append("整次运行已有删除结果，请选择保留的历史记录复算")
    if record_key:
        selected = next((item for item in recipe.get("records") or [] if item.get("record_key") == record_key), None)
        if selected is None:
            issues.append("指定历史记录不属于这次运行")
        elif selected.get("type") == "COUPLED":
            issues.append("COUPLED 依赖整张定量表及其关联文件，请选择整次运行复算")
        else:
            data_types = [selected["type"]]
            selected_paths = {_path_key(path) for path in selected.get("input_paths") or []}
            if not selected_paths:
                issues.append("该历史记录缺少实际输入文件映射，不能按单条复算")
            inputs = [item for item in inputs if (
                item["role"] == "primary" and _path_key(item["path"]) in selected_paths
            ) or (
                selected["type"] == "LSV" and item["role"] == "ir_eis" and (
                    not item.get("for_paths") or any(_path_key(path) in selected_paths for path in item["for_paths"])
                )
            )]
            if selected["type"] == "ECSA":
                warnings.append(f"这条 ECSA 结果将使用该样品的 {len(selected_paths)} 个扫速文件共同复算")
    keys = _public_param_keys(data_types)
    new_keys = keys - set(recipe.get("parameter_schema_keys") or recipe.get("params") or {})
    unspecified_new = sorted(new_keys - set(overrides))
    if unspecified_new:
        issues.append("当前版本新增了处理参数，请明确填写后再复算，不能自动套用新默认值: " + ", ".join(unspecified_new))
    unknown = sorted(set(overrides) - keys)
    if unknown:
        issues.append("无法识别的处理参数: " + ", ".join(unknown))
    original_params = {key: value for key, value in recipe.get("params", {}).items() if key in keys}
    params = {**original_params, **{key: value for key, value in overrides.items() if key in keys}}
    # A replay is always a new run, even when the original disabled isolation.
    params.pop("output_dir", None)
    params["output_run_dir_enabled"] = True
    restored_folder = None
    try:
        from electrochem_v6.core.replay_archive import restore_uploaded_sources

        restored = restore_uploaded_sources(recipe, inputs, relocations=relocations)
        relocations = {**restored["source_paths"], **relocations}
        restored_folder = restored["folder_path"]
        warnings.extend(restored["warnings"])
    except (OSError, ValueError) as exc:
        issues.append(f"无法恢复上传来源: {exc}")
    known_paths = {_path_key(item["path"]): item for item in inputs}
    path_map: dict[str, str] = {}
    for old, new in relocations.items():
        if not isinstance(old, str) or not isinstance(new, str) or not new.strip():
            raise ValueError("source_paths 必须将原文件路径映射到非空的新路径")
        if _path_key(old) not in known_paths:
            issues.append(f"无法重新定位未记录的输入: {old}")
            continue
        path_map[_path_key(old)] = str(Path(new).expanduser().resolve())
    checks = []
    for item in inputs:
        resolved = str(path_map.get(_path_key(item["path"]), item["path"]))
        if not _is_allowed_process_dir(os.path.dirname(resolved)):
            issues.append(f"输入路径不在已允许范围内: {resolved}")
            identity: dict[str, Any] = {}
        else:
            identity = _file_identity(resolved)
        expected = item.get("sha256")
        current = identity.get("sha256")
        state = "missing" if not identity.get("exists") else "unverified" if not expected or not current else "unchanged" if current == expected else "changed"
        checks.append({**item, "resolved_path": resolved, "state": state, "expected_sha256": expected, "current_sha256": current})
        if state == "missing":
            issues.append(f"缺少输入文件: {item['file_name']}。请重新定位原件或重新上传数据")
        elif state == "unverified":
            issues.append(f"输入文件缺少可验证指纹: {item['file_name']}")
    changed = any(item["state"] == "changed" for item in checks)
    if changed and not allow_changed:
        issues.append("输入内容已变化；确认使用更新后的数据后才能开始，将保留与旧运行的区别")
    if recipe.get("source_integrity") == "changed_during_processing":
        warnings.append("原运行期间输入发生过变化，无法保证其结果对应完整一致的原始数据")
    if recipe.get("source_archive_path") and any(item["state"] == "missing" for item in checks):
        warnings.append("此上传运行的临时解压目录已失效。当前需重新上传原 ZIP，或重新定位其中全部输入；不会忽略缺失依赖")
    for key in ("ir_eis_file", "coupled_products_file", "coupled_peak_method_file"):
        if params.get(key):
            params[key] = path_map.get(_path_key(str(params[key])), params[key])
    primary = [{"path": item["resolved_path"], "data_type": item["data_type"]} for item in checks if item["role"] == "primary"]
    folder = str(restored_folder or recipe.get("folder_path") or "")
    if not os.path.isdir(folder):
        candidate = primary[0]["path"] if primary else next((item["resolved_path"] for item in checks if item["role"] == "product_table"), "")
        if candidate:
            folder = os.path.dirname(candidate)
    project = get_database().get_project(str(recipe["project_id"])) if recipe.get("project_id") else None
    if recipe.get("project_id") and (not project or project.get("status") != "active"):
        issues.append("所属项目已归档或删除，请先恢复项目后再复算")
    payload: dict[str, Any] = {"folder_path": folder, "data_types": data_types, "input_files": primary, "params": params}
    if project:
        payload["project_id"] = project["id"]
    preflight = None
    if not issues:
        inspected = preflight_process_folder(payload)
        if inspected.get("status") != "success":
            issues.append(str(inspected.get("message") or "复算预检失败"))
        else:
            preflight = inspected.get("preflight") or {}
            warnings.extend(str(item) for item in preflight.get("warnings") or [])
            if int(preflight.get("selected_matched") or 0) <= 0:
                issues.append("预检未找到可处理的数据")
            ir_info = preflight.get("ir_compensation")
            if isinstance(ir_info, dict) and not ir_info.get("ok"):
                issues.append("iR 依赖未通过预检")
            try:
                gui = _build_gui_vars(data_types, payload)
                actual_inputs = collect_run_inputs(preflight, gui, folder, data_types)
                current_paths = {_path_key(item["path"]): item.get("sha256") for item in actual_inputs}
                expected_paths = {_path_key(item["resolved_path"]): item["current_sha256"] for item in checks}
                if current_paths != expected_paths:
                    issues.append("修改后的参数会改变输入依赖，或自动配对与历史不一致；请在处理页明确选择完整数据后创建新运行")
            except (OSError, ValueError) as exc:
                issues.append(f"无法验证完整输入依赖: {exc}")
    if recipe.get("app_version") != APP_VERSION or recipe.get("engine", {}) != _engine_identity():
        warnings.append("本次使用当前计算版本重新处理；软件或依赖与原运行不同，结果可能存在差异")
    parameter_changes = [{"key": key, "before": original_params.get(key), "after": value}
                         for key, value in params.items() if key != "output_run_dir_enabled" and value != original_params.get(key)]
    payload.update(
        _parent_run_id=run_id, _parent_record_key=record_key,
        _replay_expected_sources={item["resolved_path"]: item["current_sha256"] for item in checks},
        _replay_source_paths={item["path"]: item["resolved_path"] for item in checks},
    )
    return {
        "run_id": run_id, "record_key": record_key, "scope": "record" if record_key else "run",
        "data_types": data_types, "params": params, "input_files": primary, "source_checks": checks,
        "parameter_changes": parameter_changes, "can_replay": not issues,
        "requires_changed_confirmation": changed and not allow_changed, "issues": list(dict.fromkeys(issues)),
        "warnings": warnings, "source_app_version": recipe.get("app_version"), "current_app_version": APP_VERSION,
        "preflight": preflight, "payload": payload,
    }
