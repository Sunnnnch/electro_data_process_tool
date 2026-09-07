"""Project-level LSV comparison helpers."""

from __future__ import annotations

import base64
import json
import math
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional

import matplotlib.pyplot as plt

from electrochem_v6.config import user_config_dir
from electrochem_v6.core.processing_common import serialized_plotting
from electrochem_v6.core.processing_response import dedupe_keep_order
from electrochem_v6.store._json_utils import atomic_write_json
from electrochem_v6.store.runtime import get_history_store


def _safe_file_part(value: str, fallback: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_\-.]+", "_", str(value or "").strip())
    clean = clean.strip("._")
    return clean or fallback


def _compare_plot_dir(output_dir: Optional[str] = None) -> str:
    if output_dir:
        target_dir = os.path.abspath(output_dir)
    else:
        target_dir = str(user_config_dir() / "project_reports" / "compare_plots")
    os.makedirs(target_dir, exist_ok=True)
    return target_dir


def _normalize_target_current_value(target_current: Any) -> float:
    try:
        value = float(target_current)
    except Exception as exc:
        raise ValueError("target_current must be numeric") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError("target_current must be > 0")
    return value


def _format_target_current_text(target_current: Any) -> str:
    value = _normalize_target_current_value(target_current)
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6g}"


def _compare_plot_suffix(chart_type: str, metric_key: str, target_current: Any = None) -> str:
    mode = str(chart_type or "overlay").strip().lower()
    safe_metric = str(metric_key or "overpotential_10").strip().lower()
    if mode != "bar":
        return "overlay"
    if safe_metric in {"potential_at_target", "overpotential_at_target"}:
        current_text = _format_target_current_text(target_current or 10.0).replace(".", "_")
        return f"bar_{_safe_file_part(safe_metric, 'metric')}_{current_text}"
    return f"bar_{_safe_file_part(safe_metric, 'metric')}"


def _encode_image_data_url(path: str) -> str:
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")


def _pick_latest_lsv_records(
    *,
    project_id: str,
    include_archived: bool,
    selected_samples: list[str],
) -> tuple[list[Dict[str, Any]], list[str]]:
    hist_mgr = get_history_store()
    records = hist_mgr.get_all_records()
    selected_set = {item for item in selected_samples if item}
    warnings: list[str] = []
    picked: dict[str, Dict[str, Any]] = {}

    def _record_sort_key(record: Dict[str, Any]) -> str:
        return str(record.get("timestamp") or "")

    filtered = [
        item
        for item in records
        if isinstance(item, dict)
        and item.get("project_id") == project_id
        and str(item.get("type") or "").upper() == "LSV"
        and (include_archived or not bool(item.get("archived", False)))
    ]
    filtered.sort(key=_record_sort_key, reverse=True)

    for record in filtered:
        sample_name = str(record.get("sample_name") or "").strip()
        if not sample_name:
            continue
        if selected_set and sample_name not in selected_set:
            continue
        if sample_name in picked:
            continue
        picked[sample_name] = record

    if not selected_samples:
        return list(picked.values())[:5], warnings

    ordered: list[Dict[str, Any]] = []
    for name in selected_samples:
        record = picked.get(name)
        if record:
            ordered.append(record)
        else:
            warnings.append(f"样品 {name} 没有可用的 LSV 历史记录")
    return ordered, warnings


def _collect_project_lsv_target_currents(
    *,
    project_id: str,
    include_archived: bool,
) -> tuple[list[float], list[float]]:
    hist_mgr = get_history_store()
    records = hist_mgr.get_all_records()
    potential_values: set[float] = set()
    overpotential_values: set[float] = set()

    for item in records:
        if not isinstance(item, dict):
            continue
        if item.get("project_id") != project_id:
            continue
        if str(item.get("type") or "").upper() != "LSV":
            continue
        if not include_archived and bool(item.get("archived", False)):
            continue
        results = item.get("results") or {}
        if not isinstance(results, dict):
            continue
        for key, value in results.items():
            try:
                numeric = float(value)
            except Exception:
                continue
            if not math.isfinite(numeric):
                continue
            key_text = str(key or "")
            if key_text.startswith("potential_at_"):
                try:
                    potential_values.add(float(key_text[len("potential_at_") :]))
                except Exception:
                    continue
            elif key_text.startswith("overpotential_at_"):
                try:
                    overpotential_values.add(float(key_text[len("overpotential_at_") :]))
                except Exception:
                    continue

    return sorted(potential_values), sorted(overpotential_values)


def _extract_lsv_series(record: Dict[str, Any]) -> tuple[Optional[list[float]], Optional[list[float]], Optional[str]]:
    data = record.get("data") or {}
    if not isinstance(data, dict):
        sample_name = str(record.get("sample_name") or record.get("file_name") or "-").strip() or "-"
        return None, None, f"样品 {sample_name} 缺少可绘制的历史曲线，请重新处理一次最新数据"

    current_values = data.get("current")
    potential_values = data.get("potential_compensated")
    if not isinstance(potential_values, list) or len(potential_values) < 2:
        potential_values = data.get("potential_original")
    if not isinstance(current_values, list) or not isinstance(potential_values, list):
        sample_name = str(record.get("sample_name") or record.get("file_name") or "-").strip() or "-"
        return None, None, f"样品 {sample_name} 缺少可绘制的历史曲线，请重新处理一次最新数据"

    pairs: list[tuple[float, float]] = []
    for potential_item, current_item in zip(potential_values, current_values):
        try:
            pot = float(potential_item)
            cur = float(current_item)
        except Exception:
            continue
        if not (math.isfinite(pot) and math.isfinite(cur)):
            continue
        pairs.append((pot, cur))

    if len(pairs) < 2:
        sample_name = str(record.get("sample_name") or record.get("file_name") or "-").strip() or "-"
        return None, None, f"样品 {sample_name} 的历史曲线数据不足，无法生成叠加图"

    pairs.sort(key=lambda item: item[0])
    potential = [item[0] for item in pairs]
    current = [item[1] for item in pairs]
    return potential, current, None


def _find_target_metric_value(results: Dict[str, Any], prefix: str, target_current: float) -> Optional[float]:
    target = float(target_current)
    for key, value in results.items():
        key_text = str(key or "")
        if not key_text.startswith(prefix):
            continue
        suffix = key_text[len(prefix) :]
        try:
            current_value = float(suffix)
        except Exception:
            continue
        if abs(current_value - target) > 1e-6:
            continue
        try:
            numeric = float(value)
        except Exception:
            continue
        if math.isfinite(numeric):
            return numeric
    return None


def get_project_lsv_target_currents(
    *,
    project_id: str,
    include_archived: bool = False,
) -> Dict[str, Any]:
    safe_project_id = str(project_id or "").strip()
    if not safe_project_id:
        return {"status": "error", "message": "missing project id"}
    potential_values, overpotential_values = _collect_project_lsv_target_currents(
        project_id=safe_project_id,
        include_archived=include_archived,
    )
    merged_values = sorted(set(potential_values) | set(overpotential_values))
    return {
        "status": "success",
        "project_id": safe_project_id,
        "target_currents": merged_values,
        "potential_target_currents": potential_values,
        "overpotential_target_currents": overpotential_values,
    }


def _extract_lsv_metric(
    record: Dict[str, Any],
    metric_key: str,
    target_current: Any = 10.0,
) -> tuple[Optional[float], Optional[str], Optional[str], Optional[float]]:
    results = record.get("results") or {}
    if not isinstance(results, dict):
        return None, None, None, None
    sample_name = str(record.get("sample_name") or record.get("file_name") or "-").strip() or "-"
    metric = str(metric_key or "overpotential_10").strip().lower()
    try:
        target_value = _normalize_target_current_value(target_current)
    except ValueError:
        target_value = 10.0
    target_text = _format_target_current_text(target_value)
    if metric == "tafel_slope":
        value = results.get("tafel_slope")
        label = "Tafel slope (mV/dec)"
        warning = f"样品 {sample_name} 缺少 Tafel 指标"
    elif metric in {"potential_10", "potential_at_target"}:
        value = (
            results.get("potential_10")
            if metric == "potential_10" and abs(target_value - 10.0) < 1e-6
            else _find_target_metric_value(results, "potential_at_", target_value)
        )
        label = f"E@{target_text} (V)"
        warning = f"样品 {sample_name} 缺少 E@{target_text} 指标"
    else:
        value = (
            results.get("overpotential_10")
            if metric == "overpotential_10" and abs(target_value - 10.0) < 1e-6
            else _find_target_metric_value(results, "overpotential_at_", target_value)
        )
        label = f"η@{target_text} (mV)"
        warning = f"样品 {sample_name} 缺少 η@{target_text} 指标"
    try:
        num = float(value)  # type: ignore[arg-type]
    except Exception:
        return None, label, warning, target_value
    if not math.isfinite(num):
        return None, label, warning, target_value
    return num, label, None, target_value


@serialized_plotting
def build_project_lsv_compare_plot(
    *,
    project_id: str,
    selected_samples: list[str] | None = None,
    include_archived: bool = False,
    chart_type: str = "overlay",
    metric_key: str = "overpotential_10",
    target_current: Any = 10.0,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    safe_project_id = str(project_id or "").strip()
    if not safe_project_id:
        return {"status": "error", "message": "missing project id"}

    requested_samples = dedupe_keep_order([str(item).strip() for item in (selected_samples or []) if str(item).strip()])
    latest_records, warnings = _pick_latest_lsv_records(
        project_id=safe_project_id,
        include_archived=include_archived,
        selected_samples=requested_samples,
    )
    if not latest_records:
        return {"status": "error", "message": "没有可用于生成叠加图的 LSV 历史记录"}

    project_name = str((latest_records[0] or {}).get("project_name") or safe_project_id)
    target_dir = _compare_plot_dir(output_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = str(chart_type or "overlay").strip().lower()
    safe_metric = str(metric_key or "overpotential_10").strip().lower()
    normalized_target_current = _normalize_target_current_value(target_current)
    suffix = _compare_plot_suffix(mode, safe_metric, normalized_target_current)
    file_name = f"{_safe_file_part(safe_project_id, 'project')}_lsv_compare_{suffix}_{timestamp}.png"
    plot_path = os.path.join(target_dir, file_name)
    selected_names: list[str] = []
    value_count = 0
    metric_label = None

    if mode == "bar":
        bar_items: list[dict[str, Any]] = []
        for record in latest_records:
            sample_name = str(record.get("sample_name") or record.get("file_name") or "-").strip() or "-"
            value, label, warning, normalized_target_current = _extract_lsv_metric(
                record,
                safe_metric,
                normalized_target_current,
            )
            if label:
                metric_label = label
            if value is None:
                warnings.append(warning or f"样品 {sample_name} 缺少该指标，已跳过")
                continue
            bar_items.append({"sample_name": sample_name, "value": value})
        if not bar_items:
            return {"status": "error", "message": "没有可用于生成柱状图的有效指标", "warnings": warnings}
        if safe_metric in {"overpotential_10", "tafel_slope", "potential_10"}:
            bar_items.sort(key=lambda item: item["value"])
        selected_names = [item["sample_name"] for item in bar_items]
        value_count = len(bar_items)
        plt.figure(figsize=(9.2, 6.2))
        positions = list(range(len(bar_items)))
        values = [item["value"] for item in bar_items]
        labels = [item["sample_name"] for item in bar_items]
        bars = plt.bar(positions, values, color="#2b6f8a", edgecolor="#18485c", linewidth=0.8)
        plt.xticks(positions, labels, rotation=25, ha="right")
        plt.ylabel(metric_label or safe_metric)
        plt.xlabel("Sample")
        plt.title(f"LSV Metric Comparison - {project_name}")
        plt.grid(True, axis="y", alpha=0.22)
        for bar, value in zip(bars, values):
            plt.text(bar.get_x() + bar.get_width() / 2.0, value, f"{value:.3f}", ha="center", va="bottom", fontsize=8)
        plt.tight_layout()
        plt.savefig(plot_path, dpi=220, bbox_inches="tight")
        plt.close()
    else:
        series_items: list[dict[str, Any]] = []
        for record in latest_records:
            potential, current, warning = _extract_lsv_series(record)
            if warning:
                warnings.append(warning)
                continue
            series_items.append(
                {
                    "sample_name": str(record.get("sample_name") or record.get("file_name") or "-").strip() or "-",
                    "timestamp": str(record.get("timestamp") or ""),
                    "potential": potential,
                    "current": current,
                }
            )

        if not series_items:
            return {"status": "error", "message": "历史记录缺少可绘制的曲线数据，请重新处理后再试", "warnings": warnings}

        if len(series_items) > 8:
            warnings.append("叠加图最多显示 8 个样品，已自动截取前 8 个")
            series_items = series_items[:8]
        selected_names = [item["sample_name"] for item in series_items]
        value_count = len(series_items)
        plt.figure(figsize=(9.2, 6.2))
        for item in series_items:
            plt.plot(item["potential"], item["current"], linewidth=1.8, label=str(item["sample_name"]))
        plt.xlabel("Potential (V)")
        plt.ylabel("Current (mA/cm²)")
        plt.title(f"LSV Overlay - {project_name}")
        plt.grid(True, alpha=0.25)
        plt.legend(loc="best", fontsize=9)
        plt.tight_layout()
        plt.savefig(plot_path, dpi=220, bbox_inches="tight")
        plt.close()

    plot_payload = {
        "plot_path": plot_path,
        "file_name": file_name,
        "trace_count": value_count,
        "selected_samples": selected_names,
        "chart_type": "bar" if mode == "bar" else "overlay",
        "metric_key": safe_metric,
        "metric_label": metric_label,
        "target_current": normalized_target_current,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "warnings": warnings,
    }

    meta_path = os.path.splitext(plot_path)[0] + ".json"
    try:
        atomic_write_json(meta_path, {"status": "success", "project_id": safe_project_id, "plot": plot_payload})
    except Exception:
        pass

    try:
        image_data_url = _encode_image_data_url(plot_path)
    except Exception as exc:
        return {"status": "error", "message": f"叠加图已生成但读取失败: {exc}", "path": plot_path}

    plot_payload["image_data_url"] = image_data_url
    return {
        "status": "success",
        "project_id": safe_project_id,
        "plot": plot_payload,
    }


def get_latest_project_lsv_compare_plot(
    *,
    project_id: str,
    chart_type: str = "overlay",
    metric_key: str = "overpotential_10",
    target_current: Any = 10.0,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    safe_project_id = str(project_id or "").strip()
    if not safe_project_id:
        return {"status": "error", "message": "missing project id"}
    target_dir = _compare_plot_dir(output_dir)
    normalized_target_current = _normalize_target_current_value(target_current)
    suffix = _compare_plot_suffix(chart_type, metric_key, normalized_target_current)
    prefix = f"{_safe_file_part(safe_project_id, 'project')}_lsv_compare_{suffix}_"

    candidates: list[tuple[float, str, Optional[str]]] = []
    for name in os.listdir(target_dir):
        if not name.startswith(prefix):
            continue
        full_path = os.path.join(target_dir, name)
        if os.path.isfile(full_path) and name.lower().endswith(".json"):
            try:
                candidates.append((os.path.getmtime(full_path), full_path, "json"))
            except Exception:
                continue
        elif os.path.isfile(full_path) and name.lower().endswith(".png"):
            try:
                candidates.append((os.path.getmtime(full_path), full_path, "png"))
            except Exception:
                continue
    if not candidates:
        for name in os.listdir(target_dir):
            if not name.lower().endswith(".json"):
                continue
            full_path = os.path.join(target_dir, name)
            if not os.path.isfile(full_path):
                continue
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                plot = payload.get("plot") or {}
                if payload.get("project_id") != safe_project_id:
                    continue
                if str(plot.get("chart_type") or "overlay").strip().lower() != str(chart_type or "overlay").strip().lower():
                    continue
                if str(plot.get("metric_key") or "overpotential_10").strip().lower() != str(metric_key or "overpotential_10").strip().lower():
                    continue
                if abs(float(plot.get("target_current") or normalized_target_current) - normalized_target_current) > 1e-6:
                    continue
                candidates.append((os.path.getmtime(full_path), full_path, "json"))
            except Exception:
                continue
    if not candidates:
        return {"status": "error", "message": "no saved compare plot"}

    candidates.sort(key=lambda item: item[0], reverse=True)
    latest_path, kind = candidates[0][1], candidates[0][2]

    if kind == "json":
        try:
            with open(latest_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            plot = payload.get("plot") or {}
            plot_path = str(plot.get("plot_path") or "").strip()
            if not plot_path or not os.path.exists(plot_path):
                return {"status": "error", "message": "saved compare plot file missing"}
            plot["image_data_url"] = _encode_image_data_url(plot_path)
            return {"status": "success", "project_id": safe_project_id, "plot": plot}
        except Exception as exc:
            return {"status": "error", "message": f"load compare plot failed: {exc}"}

    png_path = latest_path
    try:
        image_data_url = _encode_image_data_url(png_path)
    except Exception as exc:
        return {"status": "error", "message": f"load compare plot failed: {exc}"}
    return {
        "status": "success",
        "project_id": safe_project_id,
        "plot": {
            "plot_path": png_path,
            "file_name": os.path.basename(png_path),
            "image_data_url": image_data_url,
            "trace_count": None,
            "selected_samples": [],
            "chart_type": "bar" if str(chart_type or "").strip().lower() == "bar" else "overlay",
            "metric_key": str(metric_key or "overpotential_10").strip().lower(),
            "metric_label": None,
            "target_current": normalized_target_current,
            "generated_at": datetime.fromtimestamp(os.path.getmtime(png_path)).strftime("%Y-%m-%d %H:%M:%S"),
            "warnings": [],
        },
    }
