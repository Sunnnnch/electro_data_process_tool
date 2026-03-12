"""Processing service for v6 (JSON folder processing path)."""

from __future__ import annotations

import base64
import json
import math
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Optional

import matplotlib.pyplot as plt

from electrochem_v6.config import APP_NAME, APP_VERSION, get_quality_report_file
from electrochem_v6.core import processing_core_v6 as processing_core
from electrochem_v6.core.processing_compat import run_pipeline
from electrochem_v6.core.system_service import register_allowed_dir
from electrochem_v6.core.utils import as_bool as _as_bool
from electrochem_v6.core.utils import as_float as _as_float
from electrochem_v6.core.utils import as_int as _as_int
from electrochem_v6.store.history import attach_run_outputs
from electrochem_v6.store.legacy_runtime import get_history_manager_v6, get_project_manager_v6

SUPPORTED_DATA_TYPES = ("LSV", "CV", "EIS", "ECSA")
SUMMARY_SCHEMA_VERSION = "1.0"
REFERENCE_ELECTRODE_PRESETS = {
    "agcl_sat_kcl": 0.197,
    "agcl_3m_kcl": 0.210,
    "sce": 0.241,
    "hg_hgo_1m_koh": 0.098,
    "hg_hg2so4_sat": 0.640,
    "mse": 0.640,
    "rhe": 0.000,
}


def _payload_get(payload: Dict[str, Any], key: str, default: Any = None) -> Any:
    params = payload.get("params")
    if isinstance(params, dict) and key in params:
        return params.get(key)
    return payload.get(key, default)


def _potential_mode(payload: Dict[str, Any]) -> str:
    return str(_payload_get(payload, "potential_mode", "manual") or "manual").strip().lower()


def _resolve_reference_electrode_potential(payload: Dict[str, Any]) -> Optional[float]:
    direct_value = _payload_get(payload, "reference_electrode_potential")
    if direct_value not in (None, ""):
        try:
            return float(direct_value)
        except Exception:
            return None
    preset = str(_payload_get(payload, "reference_electrode_preset", "") or "").strip().lower()
    if preset in REFERENCE_ELECTRODE_PRESETS:
        return float(REFERENCE_ELECTRODE_PRESETS[preset])
    return None


def _resolve_potential_offset(payload: Dict[str, Any]) -> float:
    if _potential_mode(payload) == "formula_rhe":
        ref_value = _resolve_reference_electrode_potential(payload)
        ph_value = _as_float(_payload_get(payload, "rhe_ph", 0.0), 0.0)
        return float(ref_value or 0.0) + 0.0591 * ph_value
    return _as_float(_payload_get(payload, "potential_offset", _payload_get(payload, "offset", 0.0)), 0.0)


def _normalize_data_types(payload: Dict[str, Any]) -> list[str]:
    raw_types: list[str] = []

    data_types = payload.get("data_types")
    if isinstance(data_types, list):
        raw_types = [str(item).strip().upper() for item in data_types if str(item).strip()]
    elif isinstance(data_types, str):
        raw_types = [part.strip().upper() for part in data_types.split(",") if part.strip()]

    if not raw_types:
        data_type = payload.get("data_type")
        if isinstance(data_type, str) and data_type.strip():
            raw_types = [part.strip().upper() for part in data_type.split(",") if part.strip()]

    if not raw_types:
        raw_types = ["LSV"]

    normalized: list[str] = []
    for item in raw_types:
        if item not in normalized:
            normalized.append(item)

    invalid = [item for item in normalized if item not in SUPPORTED_DATA_TYPES]
    if invalid:
        raise ValueError(f"不支持的数据类型: {', '.join(invalid)}")
    return normalized


def _validate_numeric_param(
    payload: Dict[str, Any],
    key: str,
    *,
    label: str,
    min_value: float | None = None,
    max_value: float | None = None,
    integer_only: bool = False,
) -> str | None:
    value = _payload_get(payload, key)
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except Exception:
        return f"{label} 必须是数字 ({key})"
    if integer_only and int(number) != number:
        return f"{label} 必须是整数 ({key})"
    if min_value is not None and number < min_value:
        return f"{label} 不能小于 {min_value} ({key})"
    if max_value is not None and number > max_value:
        return f"{label} 不能大于 {max_value} ({key})"
    return None


def _validate_payload(payload: Dict[str, Any], data_types: list[str]) -> str | None:
    rules = [
        ("font_size", "字号", 6.0, 72.0, True),
        ("area", "电极面积", 0.000001, None, False),
        ("potential_offset", "电位偏移", -100.0, 100.0, False),
        ("lsv_line_width", "LSV线宽", 0.1, 10.0, False),
        ("cv_line_width", "CV线宽", 0.1, 10.0, False),
        ("eis_line_width", "EIS线宽", 0.1, 10.0, False),
        ("ecsa_line_width", "ECSA线宽", 0.1, 10.0, False),
        ("ir_manual_ohm", "手动电阻", 0.0, None, False),
        ("ir_linear_points", "线性拟合点数", 2.0, 1000.0, True),
        ("cv_peaks_smooth", "平滑窗口", 1.0, 999.0, True),
        ("cv_peaks_min_height", "最小峰高", 0.0, None, False),
        ("cv_peaks_min_dist", "最小峰间距", 1.0, 10000.0, True),
        ("cv_peaks_max", "最大峰数", 1.0, 1000.0, True),
        ("ecsa_ev", "ECSA Ev", 0.000001, None, False),
        ("ecsa_last_n", "ECSA最后N圈", 1.0, 10000.0, True),
        ("ecsa_cs_value", "ECSA比电容", 0.000001, None, False),
    ]
    enabled_by_type = {
        "lsv_line_width": "LSV",
        "cv_line_width": "CV",
        "eis_line_width": "EIS",
        "ecsa_line_width": "ECSA",
        "ir_manual_ohm": "LSV",
        "ir_linear_points": "LSV",
        "cv_peaks_smooth": "CV",
        "cv_peaks_min_height": "CV",
        "cv_peaks_min_dist": "CV",
        "cv_peaks_max": "CV",
        "ecsa_ev": "ECSA",
        "ecsa_last_n": "ECSA",
        "ecsa_cs_value": "ECSA",
    }
    selected = set(data_types)
    for key, label, min_value, max_value, integer_only in rules:
        dtype = enabled_by_type.get(key)
        if dtype and dtype not in selected:
            continue
        message = _validate_numeric_param(
            payload,
            key,
            label=label,
            min_value=min_value,
            max_value=max_value,
            integer_only=integer_only,
        )
        if message:
            return message
    if _potential_mode(payload) == "formula_rhe":
        ph_message = _validate_numeric_param(payload, "rhe_ph", label="pH", min_value=0.0, max_value=14.0)
        if ph_message:
            return ph_message
        ref_value = _resolve_reference_electrode_potential(payload)
        if ref_value is None:
            return "参比电极电位不能为空 (reference_electrode_potential)"
        if ref_value < -2.0 or ref_value > 2.0:
            return "参比电极电位超出范围 (reference_electrode_potential)"
    else:
        offset_message = _validate_numeric_param(
            payload,
            "potential_offset",
            label="电位偏移",
            min_value=-100.0,
            max_value=100.0,
        )
        if offset_message:
            return offset_message
    if "LSV" in selected and _as_bool(_payload_get(payload, "overpotential_enabled", False), False):
        eq_value = _payload_get(payload, "eq_potential")
        if eq_value in (None, ""):
            return "平衡电位不能为空 (eq_potential)"
        message = _validate_numeric_param(payload, "eq_potential", label="平衡电位")
        if message:
            return message
    return None


def _build_gui_vars(data_types: list[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    selected = set(data_types)
    gui_vars: Dict[str, Any] = {
        "auto_detect_start": _as_bool(_payload_get(payload, "auto_detect_start", True), True),
        "area": _as_float(_payload_get(payload, "area", _payload_get(payload, "electrode_area", 1.0)), 1.0),
        "potential_mode": _potential_mode(payload),
        "potential_offset": _resolve_potential_offset(payload),
        "plot_grid": _as_bool(_payload_get(payload, "plot_grid", True), True),
        "use_abs_current": _as_bool(_payload_get(payload, "use_abs_current", True), True),
        "lsv_enabled": "LSV" in selected,
        "cv_enabled": "CV" in selected,
        "eis_enabled": "EIS" in selected,
        "ecsa_enabled": "ECSA" in selected,
    }

    target_current = _payload_get(payload, "target_current")
    tafel_range = _payload_get(payload, "tafel_range")
    lsv_tafel_enabled = _as_bool(_payload_get(payload, "tafel_enabled", bool(tafel_range)), bool(tafel_range))

    if "LSV" in selected:
        gui_vars.update(
            {
                "lsv_target_current": target_current or "10,100",
                "tafel_enabled": lsv_tafel_enabled,
                "tafel_range": tafel_range or "1-10",
                "lsv_match": str(_payload_get(payload, "lsv_match", "prefix")),
                "lsv_prefix": str(_payload_get(payload, "lsv_prefix", "LSV")),
                "eis_match": str(_payload_get(payload, "eis_match", "prefix")),
                "eis_prefix": str(_payload_get(payload, "eis_prefix", "EIS")),
                "lsv_mark_targets": _as_bool(_payload_get(payload, "lsv_mark_targets", True), True),
                "lsv_export_data": _as_bool(_payload_get(payload, "lsv_export_data", False), False),
                "lsv_combine_all": _as_bool(_payload_get(payload, "lsv_combine_all", False), False),
                "export_tafel_plot": _as_bool(_payload_get(payload, "export_tafel_plot", False), False),
                "ir_compensation_enabled": _as_bool(_payload_get(payload, "ir_compensation_enabled", False), False),
                "ir_method": str(_payload_get(payload, "ir_method", "auto")),
                "ir_manual_ohm": _as_float(_payload_get(payload, "ir_manual_ohm", 0.0), 0.0),
                "ir_linear_points": _as_int(_payload_get(payload, "ir_linear_points", 10), 10),
                "overpotential_enabled": _as_bool(_payload_get(payload, "overpotential_enabled", False), False),
                "onset_enabled": _as_bool(_payload_get(payload, "onset_enabled", False), False),
                "onset_current": str(_payload_get(payload, "onset_current", "1.0")),
                "eq_potential": _as_float(_payload_get(payload, "eq_potential", 0.0), 0.0),
                "halfwave_enabled": _as_bool(_payload_get(payload, "halfwave_enabled", False), False),
                "halfwave_current": str(_payload_get(payload, "halfwave_current", "")),
            }
        )

    if "CV" in selected:
        gui_vars.update(
            {
                "cv_match": str(_payload_get(payload, "cv_match", "prefix")),
                "cv_prefix": str(_payload_get(payload, "cv_prefix", "CV")),
                "cv_peaks_enabled": _as_bool(_payload_get(payload, "cv_peaks_enabled", False), False),
                "cv_peaks_smooth": _as_int(_payload_get(payload, "cv_peaks_smooth", 5), 5),
                "cv_peaks_min_height": _as_float(_payload_get(payload, "cv_peaks_min_height", 1.0), 1.0),
                "cv_peaks_min_dist": _as_int(_payload_get(payload, "cv_peaks_min_dist", 5), 5),
                "cv_peaks_max": _as_int(_payload_get(payload, "cv_peaks_max", 2), 2),
            }
        )

    if "EIS" in selected:
        gui_vars.update(
            {
                "eis_match": str(_payload_get(payload, "eis_match", "prefix")),
                "eis_prefix": str(_payload_get(payload, "eis_prefix", "EIS")),
                "plot_nyquist": _as_bool(_payload_get(payload, "plot_nyquist", True), True),
                "plot_bode": _as_bool(_payload_get(payload, "plot_bode", False), False),
                "eis_randles_fit": _as_bool(_payload_get(payload, "eis_randles_fit", False), False),
            }
        )

    if "ECSA" in selected:
        gui_vars.update(
            {
                "ecsa_match": str(_payload_get(payload, "ecsa_match", "prefix")),
                "ecsa_prefix": str(_payload_get(payload, "ecsa_prefix", "ECSA")),
                "ecsa_ev": _as_float(_payload_get(payload, "ecsa_ev", 0.10), 0.10),
                "ecsa_last_n": _as_int(_payload_get(payload, "ecsa_last_n", 1), 1),
                "ecsa_avg_last_n": _as_bool(_payload_get(payload, "ecsa_avg_last_n", False), False),
                "ecsa_cs_value": _as_float(_payload_get(payload, "ecsa_cs_value", 40.0), 40.0),
                "ecsa_cs_unit": str(_payload_get(payload, "ecsa_cs_unit", "uF/cm2")),
                "ecsa_use_abs_delta": _as_bool(_payload_get(payload, "ecsa_use_abs_delta", True), True),
            }
        )

    extra_params = payload.get("params")
    if isinstance(extra_params, dict):
        for key, value in extra_params.items():
            if key not in gui_vars:
                gui_vars[key] = value
    return gui_vars


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_json_safe(v) for v in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _to_json_safe(item())
        except Exception:
            pass
    return str(value)


def _atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    tmp_path = f"{path}.tmp"
    safe_payload = _to_json_safe(payload)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(safe_payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _collect_output_files(pipeline_result: Dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in ("summary_path", "quality_report_path", "lsv_csv", "ecsa_csv", "combined_lsv_png"):
        value = pipeline_result.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    for msg in pipeline_result.get("messages", []):
        if isinstance(msg, str):
            text = msg.strip()
            if text and os.path.exists(text):
                candidates.append(text)
    unique = _dedupe_keep_order(candidates)
    if unique:
        return unique
    # Fallback to raw messages for compatibility with old readers.
    return [str(msg) for msg in pipeline_result.get("messages", []) if str(msg).strip()]


def _rewrite_summary_for_v6(
    *,
    folder_path: str,
    data_types: list[str],
    project_id: Optional[str],
    pipeline_result: Dict[str, Any],
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    summary_path = pipeline_result.get("summary_path")
    if not (isinstance(summary_path, str) and summary_path.strip()):
        candidate = os.path.join(folder_path, "summary.json")
        summary_path = candidate if os.path.exists(candidate) else None
    if not summary_path:
        return None, None

    summary_obj: Dict[str, Any] = {}
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            parsed = json.load(f)
            if isinstance(parsed, dict):
                summary_obj = dict(parsed)
    except Exception:
        summary_obj = {}

    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    legacy_version = summary_obj.get("version")
    quality_summary = pipeline_result.get("quality_summary")

    summary_obj["version"] = APP_VERSION
    if legacy_version and legacy_version != APP_VERSION:
        summary_obj["pipeline_version"] = str(legacy_version)
    summary_obj["app_name"] = APP_NAME
    summary_obj["app_version"] = APP_VERSION
    summary_obj["summary_schema_version"] = SUMMARY_SCHEMA_VERSION
    summary_obj["mode"] = "v6_no_license"
    summary_obj["folder"] = folder_path
    summary_obj["generated_at"] = str(summary_obj.get("generated_at") or summary_obj.get("timestamp") or now_text)
    summary_obj["timestamp"] = str(summary_obj.get("timestamp") or summary_obj["generated_at"])
    summary_obj["data_type"] = data_types[0] if data_types else str(summary_obj.get("data_type") or "LSV")
    summary_obj["data_types"] = data_types or list(summary_obj.get("data_types") or [summary_obj["data_type"]])
    if project_id:
        summary_obj["project_id"] = project_id
    if isinstance(quality_summary, dict):
        summary_obj["quality_summary"] = quality_summary

    summary_obj["processing"] = {
        "output_files": _collect_output_files(pipeline_result),
        "quality_summary": summary_obj.get("quality_summary") or {},
    }
    # Compatibility helper for historical readers.
    summary_obj["history"] = {
        "timestamp": summary_obj.get("timestamp"),
        "data_type": summary_obj.get("data_type"),
        "data_types": summary_obj.get("data_types"),
        "project_id": summary_obj.get("project_id"),
    }

    try:
        _atomic_write_json(summary_path, summary_obj)
    except Exception:
        return summary_obj, summary_path

    return summary_obj, summary_path


def _resolve_project_id(project_name: Optional[str]) -> Optional[str]:
    if not project_name:
        return None
    from electrochem_v6.store.projects import get_or_create_project_id_by_name

    return get_or_create_project_id_by_name(project_name, description="v6 process api auto-created")


@contextmanager
def _bind_v6_runtime_managers():
    original_history_flag = getattr(processing_core, "HISTORY_MANAGER_AVAILABLE", False)
    original_project_flag = getattr(processing_core, "PROJECT_MANAGER_AVAILABLE", False)
    original_history_getter = getattr(processing_core, "get_history_manager", None)
    original_project_getter = getattr(processing_core, "get_project_manager", None)
    processing_core.HISTORY_MANAGER_AVAILABLE = True
    processing_core.PROJECT_MANAGER_AVAILABLE = True
    processing_core.get_history_manager = get_history_manager_v6
    processing_core.get_project_manager = get_project_manager_v6
    try:
        yield
    finally:
        processing_core.HISTORY_MANAGER_AVAILABLE = original_history_flag
        processing_core.PROJECT_MANAGER_AVAILABLE = original_project_flag
        processing_core.get_history_manager = original_history_getter
        processing_core.get_project_manager = original_project_getter


def _is_allowed_process_dir(folder_path: str) -> bool:
    """Check *folder_path* is under an allowed root for data processing.

    Allowed roots:
    - current working directory tree
    - user home directory tree
    - any directory previously registered at runtime (via register_allowed_dir)
    """
    from electrochem_v6.core.system_service import _is_within_allowed_roots

    resolved = os.path.realpath(folder_path)
    # Always allow subdirs of cwd and user home
    cwd_root = os.path.realpath(os.getcwd())
    home_root = os.path.realpath(os.path.expanduser("~"))
    if resolved == cwd_root or resolved.startswith(cwd_root + os.sep):
        return True
    if resolved == home_root or resolved.startswith(home_root + os.sep):
        return True
    # Fall back to the existing runtime whitelist
    return _is_within_allowed_roots(resolved)


def process_folder(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {"status": "error", "message": "request payload must be a JSON object"}
    folder_path = str(payload.get("folder_path") or "").strip()
    if not folder_path:
        return {"status": "error", "message": "folder_path 不能为空"}
    if not os.path.isdir(folder_path):
        return {"status": "error", "message": f"文件夹不存在: {folder_path}"}

    # ── path security: reject traversal / disallowed directories ──
    if not _is_allowed_process_dir(folder_path):
        return {"status": "error", "message": "路径不在允许范围内，拒绝处理"}

    # User submitted this folder for processing → treat as explicit consent
    register_allowed_dir(folder_path)

    try:
        data_types = _normalize_data_types(payload)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    validation_error = _validate_payload(payload, data_types)
    if validation_error:
        return {"status": "error", "message": validation_error}

    gui_vars = _build_gui_vars(data_types, payload)
    project_name = payload.get("project_name")
    project_id = _resolve_project_id(project_name)
    run_id = uuid.uuid4().hex
    gui_vars["run_id"] = run_id
    if project_id:
        gui_vars["project_id"] = project_id

    try:
        with _bind_v6_runtime_managers():
            result = run_pipeline(folder_path, gui_vars)
    except Exception as exc:
        return {"status": "error", "message": f"处理失败: {exc}"}
    if not isinstance(result, dict):
        return {
            "status": "error",
            "message": f"processing pipeline returned unexpected payload type: {type(result).__name__}",
        }

    normalized_summary, normalized_summary_path = _rewrite_summary_for_v6(
        folder_path=folder_path,
        data_types=data_types,
        project_id=project_id,
        pipeline_result=result,
    )
    output_files = _collect_output_files(result)
    attach_run_outputs(
        run_id=run_id,
        output_files=output_files,
        summary_path=normalized_summary_path or result.get("summary_path"),
        quality_summary=result.get("quality_summary", {}),
    )

    # Register the data folder so that "open file / open dir" works in the UI
    register_allowed_dir(folder_path)

    return {
        "status": "success",
        "result": {
            "summary": f"已处理 {', '.join(data_types)} 数据",
            "data_type": data_types[0],
            "data_types": data_types,
            "project_id": project_id,
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "summary_path": normalized_summary_path or result.get("summary_path"),
            "processing": {
                "output_files": output_files,
            },
            "quality_summary": result.get("quality_summary", {}),
            "skipped_errors": result.get("skipped_errors", []),
            "summary_json": normalized_summary,
            "raw": result,
        },
    }


def _safe_file_part(value: str, fallback: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_\-.]+", "_", str(value or "").strip())
    clean = clean.strip("._")
    return clean or fallback


def _compare_plot_dir(output_dir: Optional[str] = None) -> str:
    target_dir = os.path.abspath(output_dir or os.path.join(os.getcwd(), "project_reports", "compare_plots"))
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
    hist_mgr = get_history_manager_v6()
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
    hist_mgr = get_history_manager_v6()
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


def _extract_lsv_metric(record: Dict[str, Any], metric_key: str, target_current: Any = 10.0) -> tuple[Optional[float], Optional[str], Optional[str], Optional[float]]:
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
        value = results.get("overpotential_10") if metric == "overpotential_10" and abs(target_value - 10.0) < 1e-6 else _find_target_metric_value(results, "overpotential_at_", target_value)
        label = f"η@{target_text} (mV)"
        warning = f"样品 {sample_name} 缺少 η@{target_text} 指标"
    try:
        num = float(value)  # type: ignore[arg-type]
    except Exception:
        return None, label, warning, target_value
    if not math.isfinite(num):
        return None, label, warning, target_value
    return num, label, None, target_value


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

    requested_samples = _dedupe_keep_order([str(item).strip() for item in (selected_samples or []) if str(item).strip()])
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
            value, label, warning, normalized_target_current = _extract_lsv_metric(record, safe_metric, normalized_target_current)
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
        _atomic_write_json(meta_path, {"status": "success", "project_id": safe_project_id, "plot": plot_payload})
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


def get_latest_quality_report() -> Dict[str, Any]:
    report_path = get_quality_report_file()
    if not report_path.exists():
        return {"status": "error", "message": "未找到最新质量报告"}
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return {"status": "error", "message": f"读取质量报告失败: {exc}"}
    return {
        "status": "success",
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "generated_at": data.get("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "data": data.get("data"),
    }


def export_project_report(
    *,
    project: Dict[str, Any],
    report_data: Dict[str, Any],
    output_dir: str,
) -> Dict[str, Any]:
    project_name = str((project or {}).get("name") or "project").strip() or "project"
    safe_name = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in project_name)
    target_dir = os.path.abspath(output_dir)
    os.makedirs(target_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(target_dir, f"{safe_name}_project_report_{timestamp}.md")

    stats = (report_data or {}).get("stats") or {}
    records = (report_data or {}).get("recent_records") or []
    lines = [
        f"# {project_name} 项目报告",
        "",
        f"- 项目ID: {project.get('id', '-')}",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 项目说明: {project.get('description', '-') or '-'}",
        f"- 标签: {', '.join(project.get('tags', []) or []) or '-'}",
        "",
        "## 统计摘要",
        "",
        f"- 总记录: {stats.get('total_files', 0)}",
        f"- LSV: {stats.get('lsv_count', 0)}",
        f"- CV: {stats.get('cv_count', 0)}",
        f"- EIS: {stats.get('eis_count', 0)}",
        f"- ECSA: {stats.get('ecsa_count', 0)}",
        "",
        "## 最近历史",
        "",
    ]
    if records:
        for item in records:
            sample = item.get("sample_name") or item.get("file_name") or item.get("file_path") or "-"
            lines.extend(
                [
                    f"### {sample}",
                    f"- 类型: {item.get('type', '-')}",
                    f"- 时间: {item.get('timestamp', '-')}",
                    f"- 状态: {item.get('status', '-')}",
                    f"- 源文件: {item.get('file_path', '-')}",
                ]
            )
            output_files = item.get("output_files") or []
            if output_files:
                lines.append("- 结果文件:")
                for path_item in output_files[:10]:
                    lines.append(f"  - {path_item}")
            results = item.get("results") or {}
            if isinstance(results, dict) and results:
                lines.append("- 关键指标:")
                for key, value in list(results.items())[:10]:
                    lines.append(f"  - {key}: {value}")
            lines.append("")
    else:
        lines.append("- 暂无历史记录")
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return {"status": "success", "path": path, "file_name": os.path.basename(path)}

