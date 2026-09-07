"""Typed assistant proposals; every execution remains a deliberate UI action."""

from __future__ import annotations

import hashlib
import json
import math
import ntpath
import posixpath
import re
import uuid
from contextvars import ContextVar
from copy import deepcopy
from typing import Any

from .request_context import tool_get_professional_mode_context

_STATE: ContextVar[dict[str, Any] | None] = ContextVar("assistant_action_cards", default=None)
ACTION_TOOL_NAMES = {"propose_parameter_changes", "prepare_record_comparison", "prepare_run_replay", "prepare_result_report"}


def start_action_collection():
    return _STATE.set({"cards": [], "recommendation": None})


def finish_action_collection(token) -> list[dict[str, Any]]:
    state = _STATE.get()
    cards = deepcopy(state["cards"]) if state else []
    _STATE.reset(token)
    return cards


def remember_recommendation(result: dict[str, Any]) -> None:
    state = _STATE.get()
    if state is not None:
        state["recommendation"] = deepcopy(result)


def _context() -> dict[str, Any]:
    return tool_get_professional_mode_context().get("context") or {}


def _card(kind: str, **values) -> dict[str, Any]:
    card = {"schema_version": 1, "id": uuid.uuid4().hex, "kind": kind, **values}
    state = _STATE.get()
    if state is None:
        return {"success": False, "error": "操作卡只能在当前会话请求中准备"}
    signature = json.dumps({key: value for key, value in card.items() if key != "id"}, sort_keys=True, ensure_ascii=False)
    for existing in state["cards"]:
        if json.dumps({key: value for key, value in existing.items() if key != "id"}, sort_keys=True, ensure_ascii=False) == signature:
            return {"success": True, "action_card": deepcopy(existing), "executed": False}
    if len(state["cards"]) >= 8:
        return {"success": False, "error": "单次回复最多准备 8 张操作卡"}
    state["cards"].append(card)
    return {"success": True, "action_card": deepcopy(card), "executed": False,
            "message": "操作卡已准备，尚未执行；请用户在界面查看并确认。"}


def _scope(project_id: str | None) -> dict[str, Any]:
    from electrochem_v6.store.runtime import get_database

    current = _context().get("action_context") or {}
    bound = str(current.get("project_id") or "")
    requested = str(project_id or bound)
    if not requested:
        raise ValueError("请先选择项目，或明确提供 project_id")
    if bound and requested != bound:
        raise ValueError("操作项目与当前选中的项目不同，请先切换项目再准备操作卡")
    project = get_database().get_project(requested)
    if not project:
        raise ValueError("项目不存在")
    return project


def _records(record_keys: list[str], project_id: str, *, count: int | None = None) -> list[dict[str, Any]]:
    from electrochem_v6.store.runtime import get_database

    if not isinstance(record_keys, list) or not record_keys or len(record_keys) > 200:
        raise ValueError("请选择 1 至 200 条明确的历史结果")
    if any(not isinstance(key, str) or not key.strip() for key in record_keys) or len(set(record_keys)) != len(record_keys):
        raise ValueError("历史记录标识无效或重复")
    if count is not None and len(record_keys) != count:
        raise ValueError(f"此操作需要恰好 {count} 条历史结果")
    selected = (_context().get("action_context") or {}).get("record_keys") or []
    if selected and set(record_keys) != set(selected):
        raise ValueError("操作记录与当前勾选结果不同，请重新选择或重新准备操作卡")
    records = []
    for key in record_keys:
        record = get_database().get_history_record(key)
        if not record or record.get("project_id") != project_id:
            raise ValueError("历史记录不存在或不属于指定项目")
        records.append(record)
    return records


def _brief(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in ("record_key", "run_id", "sample_name", "file_name", "timestamp", "type")}


def _validated_params(params: dict[str, Any], data_types: list[str]) -> dict[str, Any]:
    from electrochem_v6.core.processing_registry import processing_parameter_schema

    if not isinstance(params, dict) or not params or len(params) > 80:
        raise ValueError("请提供明确的参数修改")
    schema = {item["key"]: item for item in processing_parameter_schema(data_types)["parameters"]}
    for key, value in params.items():
        spec = schema.get(key)
        if (not spec or key.startswith("_") or key in {"recursive_scan", "output_run_dir_enabled"}
                or any(part in key for part in ("file", "path", "directory", "folder", "prefix", "suffix", "match"))):
            raise ValueError(f"操作卡不能修改输入来源或不支持的参数: {key}")
        kind = spec.get("value_type")
        if value is None:
            if spec.get("default") is not None or spec.get("required"):
                raise ValueError(f"参数不能为空: {key}")
            continue
        if kind in {"number", "integer"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"参数必须是有限数值: {key}")
            if kind == "integer" and int(value) != value:
                raise ValueError(f"参数必须是整数: {key}")
            for boundary, invalid in (("min_value", lambda bound: value < bound), ("max_value", lambda bound: value > bound)):
                if spec.get(boundary) is not None and invalid(spec[boundary]):
                    raise ValueError(f"参数超出允许范围: {key}")
        elif kind == "boolean" and not isinstance(value, bool):
            raise ValueError(f"参数必须是布尔值: {key}")
        elif kind == "string" and not isinstance(value, str):
            raise ValueError(f"参数必须是文本: {key}")
        elif kind not in {"number", "integer", "boolean", "string"}:
            raise ValueError(f"操作卡暂不支持此参数类型: {key}")
        if spec.get("options") and value not in spec["options"]:
            raise ValueError(f"参数选项无效: {key}")
    return schema


def input_path_signature(path: str | None) -> str:
    """Match the UI's absolute-path digest without exposing paths in its context.

    Windows drive/UNC paths are case insensitive and use forward slashes. POSIX
    paths keep case. This identifies a selected path; it is not a content hash.
    """
    if not isinstance(path, str) or not path:
        raise ValueError("候选分析缺少可核对的原始输入路径")
    if re.match(r"^[A-Za-z]:[/\\]", path) or path.startswith(("\\\\", "//")):
        normalized = ntpath.normpath(path).replace("\\", "/").lower()
    elif posixpath.isabs(path):
        normalized = posixpath.normpath(path)
    else:
        raise ValueError("候选分析输入必须使用绝对路径")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _verify_recommendation_source(context: dict[str, Any], recommendation: dict[str, Any]) -> None:
    action_context = context.get("action_context")
    signatures = action_context.get("input_path_signatures") if isinstance(action_context, dict) else None
    if (not isinstance(signatures, list) or not signatures
            or any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item) for item in signatures)):
        raise ValueError("当前请求缺少可核对的已选输入签名，请重新选择数据并生成 Tafel 建议卡")
    provenance = recommendation.get("provenance")
    path = provenance.get("path") if isinstance(provenance, dict) else None
    if input_path_signature(path) not in signatures:
        raise ValueError("候选 Tafel 区间来自其他输入，请先分析当前选中的原始文件")


def propose_parameter_changes(changes: list[dict[str, Any]]) -> dict[str, Any]:
    context = _context()
    before = context.get("parameters")
    data_types = context.get("data_types") or []
    if not isinstance(before, dict) or not data_types or context.get("configuration_warning"):
        raise ValueError("当前专业模式参数不可用，请先检查设置")
    if not isinstance(changes, list) or not changes or any(not isinstance(item, dict) for item in changes):
        raise ValueError("请提供参数、建议值和理由")
    values = {str(item.get("key") or ""): item.get("value") for item in changes}
    if len(values) != len(changes):
        raise ValueError("参数修改不能重复")
    schema = _validated_params(values, data_types)
    from electrochem_v6.core.agent_scientific import scientific_parameter_requirements

    effective = {**before, **values}
    missing = [item for dtype in data_types for item in scientific_parameter_requirements(dtype, effective)]
    if missing:
        return {"success": False, "recommendation_status": "needs_parameters", "missing_parameters": missing,
                "error": "缺少实验条件，请先补全；尚未生成可应用的参数卡"}
    recommendation_info = None
    if "tafel_range" in values:
        recommendation = (_STATE.get() or {}).get("recommendation") or {}
        numbers = [float(item) for item in re.findall(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", str(values["tafel_range"]))]
        candidates = recommendation.get("candidate_tafel_ranges") or []
        if recommendation.get("recommendation_status") != "candidates_available" or not any(numbers == item.get("range_mA_cm2") for item in candidates):
            raise ValueError("请先用当前实验条件分析数据，再从已验证的候选 Tafel 区间准备操作卡")
        _verify_recommendation_source(context, recommendation)
        suggested_params = recommendation.get("effective_params") or {}
        if any(key in effective and effective[key] != value for key, value in suggested_params.items() if key != "tafel_range"):
            raise ValueError("候选 Tafel 区间的实验条件与本次修改不同，请重新分析")
        provenance = recommendation.get("provenance") or {}
        recommendation_info = {
            "scope": "single_input",
            "provenance": {"file_name": ntpath.basename(provenance["path"]), "sha256": provenance.get("sha256")},
            "limitations": [str(item) for item in recommendation.get("limitations") or []],
        }
    rows = []
    for item in changes:
        key = item["key"]
        reason = str(item.get("reason") or "").strip()
        if not reason or len(reason) > 2000:
            raise ValueError("每项参数建议都需要简明理由")
        if before.get(key) != values[key]:
            rows.append({"key": key, "before": before.get(key), "after": values[key], "reason": reason, "label": schema[key]["label"]})
    if not rows:
        raise ValueError("建议值与当前值相同")
    guard = {key: deepcopy(context.get(key)) for key in ("parameters", "data_types", "data_source", "action_context")}
    extra = {}
    if recommendation_info:
        provenance = recommendation_info["provenance"]
        digest = str(provenance.get("sha256") or "未记录")[:12]
        extra = {"recommendation": recommendation_info, "preview": {"warnings": [
            f"候选分析范围：{provenance['file_name']}（SHA-256 {digest}），仅此一个输入文件。",
            "专业模式的参数由当前批次所选文件共享；应用后请重新预检并核对每个文件。",
            *recommendation_info["limitations"],
        ]}}
    return _card("parameter_changes", changes=rows, data_types=data_types, context_guard=guard,
                 project_id=(context.get("action_context") or {}).get("project_id"), record_keys=[], run_id=None, **extra)


def prepare_record_comparison(record_keys: list[str], project_id: str | None = None) -> dict[str, Any]:
    from electrochem_v6.core.history_compare import compare_history_records

    project = _scope(project_id)
    records = _records(record_keys, project["id"], count=2)
    result = compare_history_records(left_record_key=record_keys[0], right_record_key=record_keys[1], project_id=project["id"])
    if result.get("status") != "success":
        raise ValueError(result.get("message") or "无法比较所选结果")
    comparison = result["comparison"]
    return _card("compare_records", project_id=project["id"], project_name=project["name"], record_keys=record_keys,
                 run_id=None, records=[_brief(item) for item in records],
                 preview={key: comparison.get(key) for key in ("metrics", "parameter_changes", "warnings")})


def prepare_run_replay(run_id: str, record_key: str | None = None, project_id: str | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    from electrochem_v6.core.run_replay import build_replay_plan
    from electrochem_v6.store.run_recipes import get_run_recipe

    project = _scope(project_id)
    recipe = get_run_recipe(str(run_id))
    if not recipe or recipe.get("project_id") != project["id"]:
        raise ValueError("运行不存在或不属于指定项目")
    bound_run = (_context().get("action_context") or {}).get("run_id")
    if bound_run and bound_run != run_id:
        raise ValueError("复算运行与当前结果不同，请先选择目标运行")
    if record_key:
        records = _records([record_key], project["id"], count=1)
        if records[0].get("run_id") != run_id:
            raise ValueError("结果记录不属于指定运行")
    if params:
        _validated_params(params, recipe.get("data_types") or [])
    options = {**({"record_key": record_key} if record_key else {}), **({"params": params} if params else {})}
    plan = build_replay_plan(run_id, options)
    return _card("replay_run", project_id=project["id"], project_name=project["name"], run_id=run_id,
                 record_keys=[record_key] if record_key else [], params=params or {},
                 preview={key: plan.get(key) for key in ("can_replay", "issues", "warnings", "parameter_changes")})


def prepare_result_report(record_keys: list[str], project_id: str | None = None) -> dict[str, Any]:
    from electrochem_v6.store.history import build_project_report

    project = _scope(project_id)
    records = _records(record_keys, project["id"])
    report = build_project_report(project["id"], record_keys=record_keys, include_archived=True)
    if report.get("status") != "success":
        raise ValueError(report.get("message") or "所选结果无法生成报告")
    return _card("report_records", project_id=project["id"], project_name=project["name"], record_keys=record_keys,
                 run_id=None, records=[_brief(item) for item in records], preview={"record_count": len(records), "format": "html"})


def completed_result_card(result: Any) -> dict[str, Any] | None:
    from electrochem_v6.store.run_recipes import get_run_recipe

    if not isinstance(result, dict):
        return None
    nested = result.get("result")
    body = nested if isinstance(nested, dict) else result
    manifest = body.get("manifest")
    manifest = manifest if isinstance(manifest, dict) else {}
    run = manifest.get("run")
    run = run if isinstance(run, dict) else {}
    run_id = body.get("run_id") or run.get("run_id")
    recipe = get_run_recipe(str(run_id)) if run_id else None
    if not recipe or recipe.get("status") not in {"success", "succeeded"}:
        return None
    return {"schema_version": 1, "id": uuid.uuid4().hex, "kind": "open_results", "project_id": recipe.get("project_id"),
            "run_id": run_id, "record_keys": list(recipe.get("record_keys") or [])}
