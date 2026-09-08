"""Compare two explicitly selected historical results without picking newer data."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from numbers import Real
from typing import Any

from electrochem_v6.core.processing_metric_registry import resolve_metric
from electrochem_v6.store.runtime import get_database

_TARGET = re.compile(r"^(potential|overpotential)_(?:at_)?([0-9]+(?:\.[0-9]+)?)$")
_COMMON = {"data_points": ("数据点数", "count")}
_METRICS = {
    "LSV": {
        "tafel_slope": ("Tafel 斜率", "mV/dec"),
        "ir_compensation": ("iR 补偿电阻", "Ω"),
        "equilibrium_potential": ("平衡电位", "V"),
    },
    "CV": {"delta_ep_mV": ("峰间距", "mV"), "charge_mC": ("积分电荷", "mC")},
    "EIS": {
        "Rs": ("溶液电阻 Rs", "Ω"),
        "Rct": ("电荷转移电阻 Rct", "Ω"),
        "Cdl": ("双电层电容 Cdl", "F"),
        "CPE_Q": ("CPE Q", "S·sⁿ"),
        "CPE_n": ("CPE n", ""),
        "randles_r2": ("拟合 R²", ""),
        "fit_rmse_ohm": ("拟合 RMSE", "Ω"),
        "sigma": ("Warburg σ", "Ω·s⁻½"),
        "R1": ("快支路 R1", "Ω"), "R2": ("慢支路 R2", "Ω"),
        "C1": ("快支路 C1", "F"), "C2": ("慢支路 C2", "F"),
        "Q1": ("快支路 Q1", "S·sⁿ¹"), "Q2": ("慢支路 Q2", "S·sⁿ²"),
        "n1": ("快支路 n1", ""), "n2": ("慢支路 n2", ""),
    },
    "ECSA": {
        "Cdl": ("面积归一化 Cdl", "mF/cm²"),
        "ECSA": ("电化学活性面积", "cm²"),
        "RF": ("粗糙度因子", ""),
        "R2": ("拟合 R²", ""),
        "scan_rates": ("扫速数据数量", "count"),
        "Cs_mFcm2": ("比电容 Cs", "mF/cm²"),
        "geometric_area_cm2": ("几何面积", "cm²"),
    },
}
_INTERNAL_PARAMS = {
    "run_id", "project_id", "input_root", "output_dir", "parent_run_id",
    "parent_record_key", "output_run_dir_enabled", "input_files", "folder_path",
}
_SECRET = re.compile(r"api.?key|secret|password|authorization|token", re.I)


def _json_value(value: Any) -> Any:
    """Keep comparison payloads finite, secret-free, and JSON serializable."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Real):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in value.items()
            if not _SECRET.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _numeric(value: Any) -> float | None:
    # bool is a subclass of int; feature flags are not measured quantities.
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _metric_info(data_type: str, key: str) -> tuple[str, str]:
    match = _TARGET.fullmatch(key) if data_type == "LSV" else None
    if match:
        kind, target = match.groups()
        return (f"{'E' if kind == 'potential' else 'η'}@{float(target):g} mA/cm²", "V" if kind == "potential" else "mV")
    known = _METRICS.get(data_type, {}).get(key) or _COMMON.get(key)
    if known:
        return known
    resolved = resolve_metric(data_type, key)
    return resolved.label, resolved.unit or ""


def history_metrics_for_display(record: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return deduplicated numeric historical metrics with recorded/module units."""
    output: dict[str, dict[str, Any]] = {}
    values = record.get("results") or {}
    if not isinstance(values, Mapping):
        return output
    data_type = str(record.get("type") or "").upper()
    # Explicit target keys take precedence over legacy potential_10 aliases.
    for raw_key in sorted(values, key=lambda key: ("_at_" in str(key), str(key))):
        key = str(raw_key)
        value = values[raw_key]
        if isinstance(value, bool) or isinstance(value, (list, tuple)):
            continue
        explicit_unit = None
        if isinstance(value, Mapping):
            if "value" not in value:
                continue
            explicit_unit = str(value.get("unit") or "")
            value = value["value"]
        # Preserve null numeric measurements, but omit descriptive strings.
        if value is not None and _numeric(value) is None and not isinstance(value, Real):
            continue
        match = _TARGET.fullmatch(key) if data_type == "LSV" else None
        if match:
            key = f"{match[1]}_at_{float(match[2]):g}"
        label, unit = _metric_info(data_type, key)
        if key == "Cs_input":
            unit = str(values.get("Cs_unit") or "")
        output[key] = {"value": _numeric(value), "label": label, "unit": explicit_unit if explicit_unit is not None else unit}
    return output


def _params(recipe: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not recipe or not isinstance(recipe.get("params"), Mapping):
        return None
    return {
        str(key): _json_value(value)
        for key, value in recipe["params"].items()
        if not str(key).startswith("_")
        and key not in _INTERNAL_PARAMS
        and not _SECRET.search(str(key))
    }


def _changes(left: Mapping[str, Any], right: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {"key": key, "before": left.get(key), "after": right.get(key),
         "before_present": key in left, "after_present": key in right}
        for key in sorted(set(left) | set(right))
        if key not in left or key not in right or left[key] != right[key]
    ]


def _brief(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _json_value(record.get(key))
        for key in ("record_key", "run_id", "project_id", "sample_name", "file_name", "file_path", "timestamp", "type", "status")
    }


def _record_sources(recipe: Mapping[str, Any] | None, record: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    if not recipe or not isinstance(recipe.get("inputs"), list):
        return None
    record_ref = next(
        (item for item in recipe.get("records") or []
         if isinstance(item, Mapping) and item.get("record_key") == record.get("record_key")),
        None,
    )
    paths = set(record_ref.get("input_paths") or []) if record_ref else {record.get("file_path")}
    sources = [
        item for item in recipe["inputs"] if isinstance(item, Mapping)
        and (item.get("path") in paths or paths.intersection(item.get("for_paths") or []))
    ]
    if not sources or any(not item.get("sha256") for item in sources):
        return None
    return [{key: item.get(key) for key in ("path", "file_name", "role", "sha256")} for item in sources]


def build_history_comparison(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    left_recipe: Mapping[str, Any] | None = None,
    right_recipe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic left-to-right comparison; deltas mean right minus left."""
    data_type = str(left.get("type") or "").upper()
    if not data_type or data_type != str(right.get("type") or "").upper():
        raise ValueError("请选择两条相同数据类型的历史记录")
    if left.get("project_id") != right.get("project_id"):
        raise ValueError("请选择同一项目中的两条历史记录")
    warnings: list[str] = []
    left_metrics, right_metrics = history_metrics_for_display(left), history_metrics_for_display(right)
    metrics = []
    for key in sorted(set(left_metrics) | set(right_metrics)):
        old, new = left_metrics.get(key), right_metrics.get(key)
        before, after = old.get("value") if old else None, new.get("value") if new else None
        info = new or old or {}
        units_match = not old or not new or old["unit"] == new["unit"]
        if data_type == "EIS" and key in {"CPE_Q", "Q1", "Q2"} and old and new:
            exponent_key = {"CPE_Q": "CPE_n", "Q1": "n1", "Q2": "n2"}[key]
            old_n = left_metrics.get(exponent_key, {}).get("value")
            new_n = right_metrics.get(exponent_key, {}).get("value")
            if old_n is None or new_n is None or old_n != new_n:
                units_match = False
                warnings.append(f"CPE 指数不同或未记录，无法确认 Q 的量纲相同，{key} 仅并列展示，不计算差值")
        valid = before is not None and after is not None and units_match
        delta = after - before if before is not None and after is not None and units_match else None
        if delta is not None and not math.isfinite(delta):
            delta = None
        relative = delta / abs(before) * 100 if delta is not None and before else None
        if relative is not None and not math.isfinite(relative):
            relative = None
        status = "unit_mismatch" if not units_match else "missing" if not valid else "unchanged" if delta == 0 else "changed"
        if not units_match:
            warnings.append(f"{key} 的单位不同，未计算差值")
        metrics.append({
            "key": key, "label": info.get("label", key), "unit": info.get("unit", ""),
            "left_unit": old.get("unit") if old else None, "right_unit": new.get("unit") if new else None,
            "left": before, "right": after, "delta": delta,
            "relative_change_percent": relative, "status": status,
        })
    left_params, right_params = _params(left_recipe), _params(right_recipe)
    if data_type == "EIS" and (left.get("results") or {}).get("circuit_model") != (right.get("results") or {}).get("circuit_model"):
        warnings.append("EIS 电路模型不同；同名参数未必代表同一物理过程，请结合电路和拟合诊断复核")
    parameters_known = left_params is not None and right_params is not None
    if not parameters_known:
        warnings.append("部分历史未保留完整参数；无法确认两次处理的设置是否相同")
    if left.get("sample_name") != right.get("sample_name"):
        warnings.append("所选记录的样品名称不同，请结合实验条件解读差异")
    if left.get("file_path") != right.get("file_path"):
        warnings.append("所选记录的来源路径不同；此对比不会将其自动视为同一份原始数据")
    left_sources, right_sources = _record_sources(left_recipe, left), _record_sources(right_recipe, right)
    sources_state = "unknown"
    if left_sources is not None and right_sources is not None:
        left_fingerprints = sorted((str(item["role"]), item["sha256"]) for item in left_sources)
        right_fingerprints = sorted((str(item["role"]), item["sha256"]) for item in right_sources)
        sources_state = "unchanged" if left_fingerprints == right_fingerprints else "changed"
        if sources_state == "changed":
            warnings.append("两次处理的原始数据或辅助输入指纹不同，结果差异可能同时来自数据变化")
    versions = {
        "left_app": (left_recipe or {}).get("app_version"),
        "right_app": (right_recipe or {}).get("app_version"),
        "left_formula": (left_recipe or {}).get("formula_schema_version"),
        "right_formula": (right_recipe or {}).get("formula_schema_version"),
        "left_engine": _json_value((left_recipe or {}).get("engine")),
        "right_engine": _json_value((right_recipe or {}).get("engine")),
    }
    if versions["left_app"] and versions["right_app"] and versions["left_app"] != versions["right_app"]:
        warnings.append("两次处理的软件版本不同，计算实现可能发生变化")
    if versions["left_formula"] and versions["right_formula"] and versions["left_formula"] != versions["right_formula"]:
        warnings.append("两次处理的公式版本不同")
    if versions["left_engine"] and versions["right_engine"] and versions["left_engine"] != versions["right_engine"]:
        warnings.append("两次处理的计算代码或运行依赖不同")
    raw_left_results, raw_right_results = left.get("results"), right.get("results")
    left_results = raw_left_results if isinstance(raw_left_results, Mapping) else {}
    right_results = raw_right_results if isinstance(raw_right_results, Mapping) else {}
    method_changes = _changes(
        {key: value for key, value in left_results.items() if isinstance(value, (str, bool))},
        {key: value for key, value in right_results.items() if isinstance(value, (str, bool))},
    )
    if any(item["key"] in {"circuit_model", "equivalent_circuit", "method", "Cs_unit"} for item in method_changes):
        warnings.append("结果的模型、方法或输入单位存在差异，请同时核对参数")
    quality_left, quality_right = _json_value(left.get("quality_summary") or {}), _json_value(right.get("quality_summary") or {})
    return {
        "left": _brief(left), "right": _brief(right), "data_type": data_type,
        "delta_direction": "right_minus_left", "metrics": metrics,
        "parameters_known": parameters_known,
        "parameter_changes": _changes(left_params or {}, right_params or {}) if parameters_known else [],
        "method_changes": _json_value(method_changes), "versions": versions,
        "sources": {"state": sources_state, "left": left_sources, "right": right_sources},
        "quality": {"left": quality_left, "right": quality_right, "changed": quality_left != quality_right},
        "warnings": warnings,
    }


def compare_history_records(
    *, left_record_key: str, right_record_key: str, project_id: str | None = None,
) -> dict[str, Any]:
    """Read exact records from SQLite; never scan by sample name or timestamp."""
    if not isinstance(left_record_key, str) or not isinstance(right_record_key, str):
        return {"status": "error", "message": "请选择两条历史记录"}
    left_key, right_key = left_record_key.strip(), right_record_key.strip()
    if not left_key or not right_key or left_key == right_key:
        return {"status": "error", "message": "请选择两条不同的历史记录"}
    db = get_database()
    left, right = db.get_history_record(left_key), db.get_history_record(right_key)
    if left is None or right is None:
        return {"status": "error", "message": "所选历史记录不存在或已被删除"}
    if project_id is not None and (left.get("project_id") != project_id or right.get("project_id") != project_id):
        return {"status": "error", "message": "所选记录不属于当前项目"}
    from electrochem_v6.store.run_recipes import get_run_recipe

    try:
        comparison = build_history_comparison(
            left, right,
            left_recipe=get_run_recipe(str(left.get("run_id") or "")),
            right_recipe=get_run_recipe(str(right.get("run_id") or "")),
        )
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    return {"status": "success", "comparison": comparison}
