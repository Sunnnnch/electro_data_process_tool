"""Return traceable sample measurements without condition-free performance grades."""

from __future__ import annotations

from typing import Any, Dict

from electrochem_v6.core.agent_scientific import finite_number, metric_value
from electrochem_v6.core.history_compare import _json_value, history_metrics_for_display

_FIELDS = {
    "LSV": {"overpotential_10": ("overpotential_at_10", "mV"), "tafel_slope": ("tafel_slope", "mV/dec")},
    "EIS": {"Rs": ("Rs", "Ω"), "Rct": ("Rct", "Ω")},
    "ECSA": {"Cdl": ("Cdl", "mF/cm²"), "ECSA": ("ECSA", "cm²"), "RF": ("RF", "")},
}


def tool_get_catalyst_info(sample_name: str, include_details: bool = True, project_id: str | None = None) -> Dict:
    """Read saved measurements, preserving versions instead of treating them as replicates."""
    try:
        from electrochem_v6.store.runtime import get_history_store

        records = [record for record in get_history_store().get_all_records()
                   if record.get("sample_name") == sample_name and not record.get("archived")
                   and (project_id is None or record.get("project_id") == project_id)]
        if not records:
            return {"success": False, "message": f"未找到样品'{sample_name}'的任何数据"}
        projects = {record.get("project_id") for record in records}
        identities = {record.get("sample_id") for record in records if record.get("sample_id")}
        if len(projects) > 1 or len(identities) > 1:
            return {"success": False, "status": "needs_scope", "message": "同名样品属于多个项目或批次，请选择明确的样品记录。",
                    "candidates": [{"project_id": record.get("project_id"), "sample_id": record.get("sample_id"),
                                    "record_key": record.get("record_key"), "run_id": record.get("run_id")} for record in records]}
        records.sort(key=lambda record: (str(record.get("timestamp") or ""), str(record.get("record_key") or "")), reverse=True)
        info: dict[str, Any] = {"success": True, "sample_name": sample_name, "project_id": project_id,
                                "total_records": len(records), "data_types_available": [],
                                "limitations": ["记录数不是独立重复实验数；同一数据的复算版本未合并为实验均值。", "数值未经过实验条件可比性确认，不据此评定材料等级。"]}
        for dtype in ("LSV", "CV", "EIS", "ECSA", "COUPLED"):
            selected = [record for record in records if str(record.get("type", "")).upper() == dtype]
            if not selected:
                continue
            info["data_types_available"].append(dtype)
            latest = selected[0]
            fields = _FIELDS.get(dtype, {})
            section = {"record_count": len(selected), "latest_time": latest.get("timestamp"),
                       "record_key": latest.get("record_key"), "run_id": latest.get("run_id"),
                       "aggregation_method": "latest_record_no_replicate_aggregation",
                       "metrics": history_metrics_for_display(latest),
                       "units": {name: unit for name, (_key, unit) in fields.items()},
                       **{name: metric_value(latest, key, unit) for name, (key, unit) in fields.items()}}
            if dtype == "CV":
                section.update({key: (latest.get("results") or {}).get(key) for key in ("potential_range", "current_range", "data_points")})
            if include_details:
                section["all_measurements"] = [{"time": item.get("timestamp"), "record_key": item.get("record_key"),
                    "run_id": item.get("run_id"), "metrics": history_metrics_for_display(item),
                    **({"eta_10": metric_value(item, "overpotential_at_10", "mV"), "tafel": metric_value(item, "tafel_slope", "mV/dec")} if dtype == "LSV" else {})}
                    for item in selected]
            info[dtype.lower()] = section
        info["overall_assessment"] = _generate_overall_assessment(info)
        return _json_value(info)
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _evaluate_lsv_performance(eta: float | None = None, tafel: float | None = None) -> str:
    """Compatibility helper: an isolated value cannot establish a catalyst grade."""
    del tafel
    return "未知" if finite_number(eta) is None else "未评级：需要明确反应、归一化方式、补偿和可比实验条件。"


def _generate_overall_assessment(info: Dict) -> str:
    types = info.get("data_types_available") or []
    if not types:
        return "无可用数据"
    return f"有{len(types)}种类型的数据（{', '.join(types)}）；已展示明确记录的数值，尚未确认实验条件可比性，不生成综合性能等级。"


__all__ = ["tool_get_catalyst_info"]
