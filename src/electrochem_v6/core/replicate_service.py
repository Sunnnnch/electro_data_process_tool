"""Explicit independent-experiment groups, conservative provenance, and sample SD."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import statistics
from collections.abc import Mapping
from html import escape
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from electrochem_v6.core.history_compare import history_metrics_for_display
from electrochem_v6.store import replicate_groups as store
from electrochem_v6.store.run_recipes import get_run_recipe
from electrochem_v6.store.runtime import get_database

MAX_MEMBERS = 100
_HASH = re.compile(r"^[a-fA-F0-9]{64}$")
_DIMENSIONLESS = {"CPE_n", "randles_r2", "RF", "R2", "r2", "fit_r2"}


def _path(value: Any) -> str:
    return str(value or "").replace("\\", "/").rstrip("/").casefold()


def _primary_inputs(record: Mapping[str, Any], recipe: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not recipe:
        return []
    references = [item for item in recipe.get("records") or [] if item.get("record_key") == record["record_key"]]
    paths = {_path(path) for item in references for path in item.get("input_paths") or []}
    if not paths and record.get("file_path"):
        paths.add(_path(record["file_path"]))
    inputs = [item for item in recipe.get("inputs") or [] if isinstance(item, dict)
              and item.get("role") in {"primary", "product_table", "signal"}]
    selected = [item for item in inputs if _path(item.get("path")) in paths]
    # Aggregated ECSA/COUPLED records may have a synthetic filename; the recipe
    # must explicitly identify their contributing files, never guess one file.
    return selected


def _source_identity(record: dict[str, Any]) -> dict[str, Any]:
    recipe = get_run_recipe(str(record.get("run_id") or "")) if record.get("run_id") else None
    inputs = _primary_inputs(record, recipe)
    references = [item for item in (recipe or {}).get("records") or [] if item.get("record_key") == record["record_key"]]
    required = {_path(path) for item in references for path in item.get("input_paths") or []}
    if not required and record.get("file_path"):
        required.add(_path(record["file_path"]))
    missing_paths = required - {_path(item.get("path")) for item in inputs}
    hashes = sorted({str(item["sha256"]).lower() for item in inputs if _HASH.fullmatch(str(item.get("sha256") or ""))})
    complete = bool(inputs) and not missing_paths and all(_HASH.fullmatch(str(item.get("sha256") or "")) for item in inputs)
    if (recipe or {}).get("source_integrity") not in {None, "", "verified"}:
        complete = False
    chain = []
    known_runs = set()
    current = recipe
    record_ancestors = {record["record_key"]}
    lineage_complete = True
    while current and len(chain) < 64:
        run_id = str(current.get("run_id") or "")
        if not run_id or run_id in {item.get("run_id") for item in chain}:
            lineage_complete = False
            break
        chain.append(current)
        known_runs.add(run_id)
        if current.get("parent_record_key"):
            record_ancestors.add(str(current["parent_record_key"]))
        parent = current.get("parent_run_id")
        if not parent:
            break
        known_runs.add(str(parent))
        current = get_run_recipe(str(parent))
        if current is None:
            lineage_complete = False
            break
    if len(chain) >= 64:
        lineage_complete = False
    root = chain[-1] if chain else None
    root_inputs = [item for item in (root or {}).get("inputs") or [] if isinstance(item, dict)
                   and item.get("role") in {"primary", "product_table", "signal"}]
    slots = []
    for item in inputs:
        candidates = [base for base in root_inputs if _path(base.get("path")) == _path(item.get("path"))
                      or (item.get("archive_member") and base.get("archive_member") == item.get("archive_member"))]
        if not candidates:
            name = PurePosixPath(_path(item.get("path"))).name
            candidates = [base for base in root_inputs if PurePosixPath(_path(base.get("path"))).name == name]
        if len(candidates) == 1:
            slots.append(_path(candidates[0].get("path")))
    return {
        "state": "verified" if complete and lineage_complete else "unverified",
        "hashes": hashes,
        "files": [{"file_name": item.get("file_name") or PurePosixPath(_path(item.get("path"))).name,
                   "path": item.get("path"), "sha256": item.get("sha256")} for item in inputs],
        "run_id": record.get("run_id"), "root_run_id": (root or {}).get("run_id"),
        "ancestor_run_ids": sorted(known_runs), "lineage_complete": lineage_complete,
        "missing_input_paths": sorted(missing_paths),
        "ancestor_record_keys": sorted(record_ancestors),
        "origin_slots": sorted(set(slots)), "slots_complete": bool(inputs) and len(slots) == len(inputs),
    }


def _same_source(left: dict[str, Any], right: dict[str, Any]) -> bool:
    a, b = left["source"], right["source"]
    if set(a["hashes"]) & set(b["hashes"]):
        return True
    if set(a["ancestor_record_keys"]) & set(b["ancestor_record_keys"]):
        return True
    if set(a["ancestor_run_ids"]) & set(b["ancestor_run_ids"]):
        if not a["lineage_complete"] or not b["lineage_complete"]:
            return True
        # Distinct files in one batch are allowed, but an ambiguous mapping
        # between a replay and its parent cannot assert a new independent run.
        if a["slots_complete"] and b["slots_complete"]:
            return bool(set(a["origin_slots"]) & set(b["origin_slots"]))
        if a["run_id"] != b["run_id"]:
            return True
        paths_a = {_path(item.get("path")) for item in a["files"]}
        paths_b = {_path(item.get("path")) for item in b["files"]}
        return bool(paths_a & paths_b) or not paths_a or not paths_b
    return False


def _analysis_conditions(members: list[dict[str, Any]], confirmation: str) -> dict[str, Any]:
    """Compare calculation conventions, without claiming physical conditions match."""
    snapshots = []
    for member in members:
        recipe = get_run_recipe(str(member.get("run_id") or "")) or {}
        params = recipe.get("params")
        params = params if isinstance(params, dict) else {}
        dtype, metrics = member["data_type"], member["metrics"]
        fields = set()
        if dtype == "LSV":
            fields.update(("area", "use_abs_current", "potential_mode", "potential_offset", "ir_compensation_enabled"))
            if params.get("potential_mode") == "formula_rhe":
                fields.update(("rhe_ph", "rhe_temperature_c", "reference_electrode_preset", "reference_electrode_potential"))
            if params.get("ir_compensation_enabled"):
                fields.update(("ir_source", "ir_manual_ohm", "ir_method"))
            if "tafel_slope" in metrics:
                fields.add("tafel_range")
            if any("overpotential" in key for key in metrics):
                fields.add("eq_potential")
        elif dtype == "ECSA":
            fields.update(("area", "ecsa_ev", "ecsa_last_n", "ecsa_avg_last_n", "ecsa_cs_value", "ecsa_cs_unit", "ecsa_use_abs_delta"))
        elif dtype == "CV":
            fields.add("area")
            if "charge_mC" in metrics:
                fields.add("cv_scan_rate_v_s")
            if "delta_ep_mV" in metrics or any("peak" in key for key in metrics):
                fields.update(("cv_peaks_enabled", "cv_peaks_smooth", "cv_peaks_min_height", "cv_peaks_min_dist", "cv_peaks_max"))
            if any(key.startswith("potential_") for key in metrics):
                fields.update(("potential_mode", "potential_offset"))
        elif dtype == "EIS":
            fields.add("eis_circuit_model")
        else:
            # Unknown modules require explicit review until their comparable
            # processing conventions are described here.
            fields.add("replicate_comparison_method")
        values = {key: params.get(key) for key in sorted(fields)}
        missing = sorted(key for key in fields if key not in params)
        snapshots.append({"record_key": member["record_key"], "name": member["name"],
                          "values": values, "missing": missing, "known": bool(params) and not missing})
    known = all(snapshot["known"] for snapshot in snapshots)
    all_fields = {key for snapshot in snapshots for key in snapshot["values"]}
    differences = [key for key in sorted(all_fields)
                   if len({json.dumps(snapshot["values"].get(key), sort_keys=True, ensure_ascii=False, default=str)
                           for snapshot in snapshots}) > 1]
    required = len(snapshots) > 1 and (not known or bool(differences))
    fingerprint = hashlib.sha256(json.dumps(snapshots, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return {"state": "unknown" if not known else "changed" if differences else "consistent",
            "requires_confirmation": required, "confirmed": bool(required and confirmation == fingerprint),
            "signature": fingerprint, "differences": differences, "members": snapshots}


def _keys(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(key, str) or not key.strip() for key in value):
        raise ValueError(f"{field} 必须为记录标识列表")
    if len(value) > MAX_MEMBERS or len(set(value)) != len(value):
        raise ValueError(f"{field} 不得重复，最多 {MAX_MEMBERS} 条")
    if not allow_empty and not value:
        raise ValueError("请先勾选要汇总的独立实验结果")
    return value


def _draft(project_id: str, payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    project = get_database().get_project(project_id)
    if project is None:
        raise LookupError("项目不存在或已永久删除")
    name = payload.get("name", (existing or {}).get("name", ""))
    if not isinstance(name, str) or len(name.strip()) > 128:
        raise ValueError("重复组名称必须为不超过 128 字的文本")
    record_keys = _keys(payload.get("record_keys", (existing or {}).get("record_keys", [])), "record_keys", allow_empty=False)
    deleted = set((existing or {}).get("deleted_record_keys") or [])
    for key in record_keys:
        if key in deleted:
            continue
        record = get_database().get_history_record(key)
        if record is None:
            if existing and key in existing["record_keys"]:
                deleted.add(key)
                continue
            raise LookupError("所选历史记录不存在或已删除")
        if record.get("project_id") != project_id:
            raise ValueError("只能汇总同一项目中的实验记录")
    confirmations = _keys(payload.get("independence_confirmed_keys", []), "independence_confirmed_keys")
    analysis_confirmation = payload.get("analysis_conditions_confirmation", "")
    if not isinstance(analysis_confirmation, str):
        raise ValueError("analysis_conditions_confirmation 必须为本次计算口径核对签名")
    if not set(confirmations) <= set(record_keys):
        raise ValueError("独立性确认必须对应当前组内的具体记录")
    exclusions = payload.get("exclusions", [])
    if not isinstance(exclusions, list) or len(exclusions) > MAX_MEMBERS:
        raise ValueError("exclusions 必须为排除项列表")
    reasons = {}
    for item in exclusions:
        if not isinstance(item, dict) or item.get("record_key") not in record_keys:
            raise ValueError("排除项必须对应当前组内的记录")
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
            raise ValueError("每项排除都必须填写原因（不超过 500 字）")
        if item["record_key"] in reasons:
            raise ValueError("排除项不可重复")
        reasons[item["record_key"]] = reason.strip()
    return {
        "group_id": (existing or {}).get("group_id", ""), "project_id": project_id,
        "project_name": project["name"], "name": name.strip(), "record_keys": record_keys,
        "exclusions": [{"record_key": key, "reason": reason} for key, reason in reasons.items()],
        "independence_confirmed_keys": confirmations,
        "analysis_conditions_confirmation": analysis_confirmation,
        "deleted_record_keys": sorted(deleted),
        "revision": (existing or {}).get("revision", 0),
    }


def summarize_group(group: dict[str, Any]) -> dict[str, Any]:
    reasons = {item["record_key"]: item["reason"] for item in group.get("exclusions") or []}
    confirmations = set(group.get("independence_confirmed_keys") or [])
    deleted = set(group.get("deleted_record_keys") or [])
    members, issues, warnings = [], [], []
    for key in group["record_keys"]:
        record = get_database().get_history_record(key) if key not in deleted else None
        if not record or record.get("project_id") != group["project_id"]:
            members.append({"record_key": key, "name": key, "status": "deleted", "included": False,
                            "reason": "原记录已删除或不再属于该项目", "metrics": {}, "source": {}})
            continue
        source = _source_identity(record)
        excluded = key in reasons
        confirmed = key in confirmations
        status = "excluded" if excluded else "unverified" if source["state"] != "verified" and not confirmed else "included"
        members.append({"record_key": key, "run_id": record.get("run_id"),
                        "name": record.get("sample_name") or record.get("file_name") or key,
                        "timestamp": record.get("timestamp"), "data_type": str(record.get("type") or "").upper(),
                        "archived": bool(record.get("archived")), "included": not excluded,
                        "status": status, "reason": reasons.get(key, ""), "independence_confirmed": confirmed,
                        "source": source, "metrics": history_metrics_for_display(record)})
        if status == "unverified":
            issues.append(f"{members[-1]['name']} 缺少完整来源证据，请逐条确认确为独立实验或排除")
    active = [member for member in members if member["included"]]
    types = {member["data_type"] for member in active}
    if len(types) > 1 or "" in types:
        issues.append("仅能汇总同一数据类型的独立实验")
    conflicts = []
    for index, left in enumerate(active):
        for right in active[index + 1:]:
            if _same_source(left, right):
                conflicts.append([left["record_key"], right["record_key"]])
                left["status"] = right["status"] = "same_source"
    if conflicts:
        issues.append("存在相同原始输入或同一复算谱系的版本；每个实验来源只能纳入一个版本，其余请排除并说明")
    if not active:
        issues.append("至少保留一项未排除的实验记录")
    data_type = next(iter(types)) if len(types) == 1 else ""
    conditions = _analysis_conditions(active, str(group.get("analysis_conditions_confirmation") or ""))
    if conditions["requires_confirmation"]:
        detail = "关键参数不同：" + ", ".join(conditions["differences"]) if conditions["differences"] else "部分记录未保存完整计算参数"
        warnings.append(detail + "；请核对电位基准、归一化及实验记录，确认所选指标可比较")
        if not conditions["confirmed"]:
            issues.append("计算口径不同或证据缺失，请查看参数并明确确认可比性")
    metrics = []
    metric_keys = sorted({key for member in members for key in member["metrics"]})
    for key in metric_keys:
        available = [member["metrics"][key] for member in members if key in member["metrics"]]
        selected = [member["metrics"][key] for member in active if key in member["metrics"]]
        units = {item["unit"] for item in selected}
        unit_unknown = units == {""} and key not in _DIMENSIONLESS
        dimension_mismatch = False
        if data_type == "EIS" and key == "CPE_Q":
            exponents = [member["metrics"].get("CPE_n", {}).get("value") for member in active
                         if member["metrics"].get(key, {}).get("value") is not None]
            dimension_mismatch = bool(exponents) and (None in exponents or len(set(exponents)) != 1)
        incompatible = len(units) > 1 or dimension_mismatch
        state = "unit_mismatch" if incompatible else "unit_unknown" if unit_unknown else "blocked" if issues else "ok"
        values = [item["value"] for item in selected if item["value"] is not None]
        valid = values if state == "ok" else []
        count = len(valid)
        try:
            mean = statistics.fmean(valid) if count else None
            sd = statistics.stdev(valid) if count > 1 else None
        except (OverflowError, ValueError):
            mean, sd = math.inf, None
        if any(value is not None and not math.isfinite(value) for value in (mean, sd)):
            state, mean, sd, count = "nonfinite", None, None, 0
        if state == "ok" and count == 0:
            state = "missing"
        elif state == "ok" and count == 1:
            state = "single"
        if incompatible:
            warnings.append(f"{available[0]['label']} 的单位或 CPE 指数量纲不同，仅展示各测量点，不汇总")
        elif unit_unknown:
            warnings.append(f"{available[0]['label']} 未记录可识别单位，不汇总")
        metrics.append({"key": key, "label": available[0]["label"], "unit": next(iter(units)) if len(units) == 1 else "",
                        "units": sorted(units), "status": state, "n": count, "measured_n": len(values),
                        "missing_n": len(active) - len(values), "mean": mean, "sample_sd": sd,
                        "points": [{"record_key": member["record_key"], "name": member["name"],
                                    "included": member["included"], "member_status": member["status"],
                                    "reason": member["reason"], "value": member["metrics"].get(key, {}).get("value"),
                                    "unit": member["metrics"].get(key, {}).get("unit")}
                                   for member in members]})
    if not any(member["source"].get("state") == "verified" for member in active) and active:
        warnings.append("来源证据不足，独立性依据用户逐条确认；软件未自动验证实验独立性")
    return {**group, "data_type": data_type, "members": members, "metrics": metrics,
            "included_n": len(active), "issues": list(dict.fromkeys(issues)), "warnings": warnings,
            "source_conflicts": conflicts, "can_save": not issues and bool(group.get("name")),
            "analysis_conditions": conditions,
            "statistic": "sample_standard_deviation_ddof_1"}


def preview_replicates(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    existing = store.get_replicate_group(str(payload.get("group_id") or "")) if payload.get("group_id") else None
    if existing and existing["project_id"] != project_id:
        raise ValueError("重复组不属于当前项目")
    return summarize_group(_draft(project_id, payload, existing))


def save_replicates(project_id: str, payload: dict[str, Any], *, group_id: str | None = None) -> dict[str, Any]:
    existing = store.get_replicate_group(group_id) if group_id else None
    if group_id and existing is None:
        raise LookupError("重复组不存在")
    if existing and existing["project_id"] != project_id:
        raise ValueError("重复组不属于当前项目")
    group = _draft(project_id, payload, existing)
    preview = summarize_group(group)
    if not preview["can_save"]:
        raise ValueError("；".join(preview["issues"]) or "请填写重复组名称")
    if existing and (not isinstance(payload.get("revision"), int) or isinstance(payload.get("revision"), bool)):
        raise ValueError("保存修改需提供重复组当前 revision")
    group["group_id"] = group_id or uuid4().hex
    return summarize_group(store.save_replicate_group(group, expected_revision=payload.get("revision") if existing else None))


def get_replicates(group_id: str) -> dict[str, Any]:
    group = store.get_replicate_group(group_id)
    if group is None or get_database().get_project(group["project_id"]) is None:
        raise LookupError("重复组或所属项目已删除")
    return summarize_group(group)


def list_replicates(project_id: str) -> list[dict[str, Any]]:
    if get_database().get_project(project_id) is None:
        raise LookupError("项目不存在")
    return [{key: group.get(key) for key in ("group_id", "project_id", "name", "updated_at", "revision", "record_keys")}
            for group in store.list_replicate_groups(project_id)]


def export_replicates_csv(group: dict[str, Any]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["group", "data_type", "metric", "unit", "record_key", "sample", "run_id", "timestamp", "value",
                     "included", "status", "exclusion_reason", "independence_confirmed", "source_sha256", "source_files",
                     "valid_n", "mean", "sample_sd_ddof_1", "metric_status", "analysis_conditions_confirmed",
                     "analysis_conditions_differences", "analysis_conditions"])
    members = {member["record_key"]: member for member in group["members"]}

    def cell(value: Any) -> Any:
        # Prevent spreadsheet formula interpretation of user-controlled labels.
        if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + value
        return value

    export_metrics = group["metrics"] or [{"key": "", "n": 0, "mean": None, "sample_sd": None, "status": "missing",
                                         "points": [{"record_key": member["record_key"], "name": member["name"],
                                                     "included": member["included"], "member_status": member["status"],
                                                     "reason": member["reason"], "value": None, "unit": None}
                                                    for member in group["members"]]}]
    for metric in export_metrics:
        for point in metric["points"]:
            member = members[point["record_key"]]
            row = [group["name"], group["data_type"], metric["key"], point["unit"], point["record_key"], point["name"],
                   member.get("run_id"), member.get("timestamp"), point["value"], point["included"], point["member_status"],
                   point["reason"], member.get("independence_confirmed", False), ";".join(member["source"].get("hashes", [])),
                   ";".join(str(item.get("path") or "") for item in member["source"].get("files", [])),
                   metric["n"], metric["mean"], metric["sample_sd"], metric["status"],
                   group.get("analysis_conditions", {}).get("confirmed", False),
                   ";".join(group.get("analysis_conditions", {}).get("differences", [])),
                   json.dumps(next((item for item in group.get("analysis_conditions", {}).get("members", [])
                                    if item["record_key"] == member["record_key"]), {}), ensure_ascii=False)]
            writer.writerow([cell(value) for value in row])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def replicate_metric_svg(group: dict[str, Any], metric_key: str) -> str:
    metric = next((item for item in group["metrics"] if item["key"] == metric_key), None)
    if metric is None:
        raise ValueError("请选择组内已有指标")
    if metric["status"] not in {"ok", "single"}:
        raise ValueError("该指标缺少有效值、来源证据或单位一致性，不能生成误差条")
    points = [point for point in metric["points"] if point["included"] and point["value"] is not None]
    mean, sd = metric["mean"], metric["sample_sd"]
    limits = [point["value"] for point in points] + [mean - (sd or 0), mean + (sd or 0)]
    if not all(math.isfinite(value) for value in limits):
        raise ValueError("误差条范围超出可绘制数值范围")
    low, high = min(limits), max(limits)
    scale = max(abs(low), abs(high), 1)
    low, high = low / scale, high / scale
    span = high - low or max(abs(low) * .1, 1 / scale)
    low, high = low - span * .15, high + span * .15
    y = lambda value: 300 - (value / scale - low) / (high - low) * 220  # noqa: E731
    text = lambda value: escape(str(value), quote=True)  # noqa: E731
    body = [f'<svg xmlns="http://www.w3.org/2000/svg" width="760" height="420" viewBox="0 0 760 420" role="img" aria-label="{text(group["name"])}">',
            '<rect width="760" height="420" fill="white"/>',
            '<g font-family="Arial, Microsoft YaHei, sans-serif" fill="#163444">',
            f'<text x="36" y="30" font-size="18">{text(group["name"][:48])}</text>',
            f'<text x="36" y="54" font-size="13">{text(metric["label"])} ({text(metric["unit"])}) · n={metric["n"]}</text>',
            '<path d="M100 80 V300 H710" stroke="#476779" fill="none"/>']
    for index in range(5):
        value = (low + (high - low) * index / 4) * scale
        body.append(f'<text x="92" y="{y(value)+4:.2f}" text-anchor="end" font-size="11">{value:.5g}</text>')
    for index, point in enumerate(points):
        x = 150 + index * 350 / max(1, len(points) - 1)
        body.append(f'<circle data-chart-series="measurement" cx="{x:.2f}" cy="{y(point["value"]):.2f}" r="5" fill="#236db4" stroke="#163444" stroke-width="1.5"><title>{text(point["name"])}: {point["value"]:.7g}</title></circle>')
        body.append(f'<text x="{x:.2f}" y="320" text-anchor="middle" font-size="11">{index+1}</text>')
    mean_y = y(mean)
    body.append(f'<polygon data-chart-series="mean" data-chart-marker="diamond" points="630,{mean_y - 7:.2f} 637,{mean_y:.2f} 630,{mean_y + 7:.2f} 623,{mean_y:.2f}" fill="#087856" stroke="#163444" stroke-width="1.5"/>')
    if sd is not None:
        top, bottom = y(mean + sd), y(mean - sd)
        body.append(f'<path data-chart-series="sample-sd" d="M630 {top:.2f} V{bottom:.2f} M618 {top:.2f} H642 M618 {bottom:.2f} H642" stroke="#087856" stroke-width="2"/>')
    body.extend(['<text x="630" y="320" text-anchor="middle" font-size="12">Mean ± sample SD</text>',
                 f'<text x="36" y="355" font-size="13">Mean={mean:.7g}; sample SD={sd if sd is not None else "undefined (n=1)"}</text>',
                  '<text x="36" y="379" font-size="12">Blue circles: experiments (CSV order). Green diamond: mean ± sample SD (ddof=1).</text>',
                 '<text x="36" y="400" font-size="12">Excluded/missing values omitted. SD is not SEM or a confidence interval.</text>', '</g></svg>'])
    return "".join(body)
