"""Application service for folder-based electrochemical processing."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from electrochem_v6.config import APP_NAME, APP_VERSION, get_quality_report_file, user_config_dir
from electrochem_v6.core.job_control import (
    ProcessingCancelledError,
    check_cancelled,
    report_progress,
)
from electrochem_v6.core.processing_coupled import (
    normalize_coupled_input_mode,
    normalize_coupled_peak_method_source,
)
from electrochem_v6.core.processing_fe_peak import inspect_fe_peak_inputs, parse_fe_peak_method
from electrochem_v6.core.processing_lsv_ir import (
    normalize_ir_source,
)
from electrochem_v6.core.processing_manifest import build_run_manifest, write_run_manifest
from electrochem_v6.core.processing_module_contract import ModuleRunContext
from electrochem_v6.core.processing_module_orchestrator import run_module_pipeline
from electrochem_v6.core.processing_module_runtime import get_processing_module_registry
from electrochem_v6.core.processing_preflight import add_coupled_preflight, finalize_preflight_scan
from electrochem_v6.core.processing_registry import (
    FILE_MATCH_MODULE_SPECS,
    REFERENCE_ELECTRODE_PRESET_VALUES,
    SUPPORTED_DATA_TYPES,
    GuiParamSpec,
    enabled_by_gui_vars,
    enabled_flags_for_data_types,
    get_match_config,
    gui_param_specs_for,
    normalize_data_type,
    parameter_defaults_for,
    processing_parameter_schema,
)
from electrochem_v6.core.processing_response import (
    build_process_error_result,
    build_process_success_result,
)
from electrochem_v6.core.processing_response import (
    collect_output_files as _collect_output_files,
)
from electrochem_v6.core.processing_response import (
    has_data_output_file as _has_data_output_file,
)
from electrochem_v6.core.processing_response import (
    processing_stats as _processing_stats,
)
from electrochem_v6.core.processing_run_report import write_run_report, write_run_report_html
from electrochem_v6.core.processing_scan import (
    matches_named_file,
    processable_files,
)
from electrochem_v6.core.processing_scan import (
    scan_process_inputs as _scan_pipeline_inputs,
)
from electrochem_v6.core.processing_scan import (
    scan_selected_inputs as _scan_selected_inputs,
)
from electrochem_v6.core.project_compare import (
    build_project_lsv_compare_plot as _build_project_lsv_compare_plot,
)
from electrochem_v6.core.project_compare import (
    get_latest_project_lsv_compare_plot as _get_latest_project_lsv_compare_plot,
)
from electrochem_v6.core.project_compare import (
    get_project_lsv_target_currents as _get_project_lsv_target_currents,
)
from electrochem_v6.core.project_report import export_project_report as _export_project_report
from electrochem_v6.core.run_replay import capture_run_recipe, finish_run_recipe
from electrochem_v6.core.system_service import register_allowed_dir
from electrochem_v6.core.utils import as_bool as _as_bool
from electrochem_v6.core.utils import as_float as _as_float
from electrochem_v6.core.utils import as_int as _as_int
from electrochem_v6.store._json_utils import atomic_write_json as _atomic_write_json
from electrochem_v6.store.archive_metadata import (
    discard_unused_run_archive_roots,
    register_run_archive_roots,
)
from electrochem_v6.store.history import attach_run_outputs
from electrochem_v6.store.run_recipes import get_run_recipe, update_run_recipe
from electrochem_v6.store.runtime import get_database

SUMMARY_SCHEMA_VERSION = "1.0"
PROCESSING_PARAMETER_DEFAULTS = parameter_defaults_for()


def _parameter_default(key: str, fallback: Any = None) -> Any:
    return PROCESSING_PARAMETER_DEFAULTS.get(key, fallback)


def _run_selected_modules(folder_path: str, gui_vars: Dict[str, Any]) -> Dict[str, Any]:
    """Execute selected processing modules through the runtime registry."""
    selected = gui_vars.get("_selected_data_types")
    if not isinstance(selected, (list, tuple)) or not selected:
        selected = [data_type for data_type, enabled in enabled_by_gui_vars(gui_vars).items() if enabled]
    return run_module_pipeline(folder_path, gui_vars, data_types=selected)


def _payload_get(payload: Dict[str, Any], key: str, default: Any = None) -> Any:
    params = payload.get("params")
    if isinstance(params, dict) and key in params:
        return params.get(key)
    return payload.get(key, default)


def _potential_mode(payload: Dict[str, Any]) -> str:
    default = _parameter_default("potential_mode", "")
    return str(_payload_get(payload, "potential_mode", default) or default).strip().lower()


def _resolve_reference_electrode_potential(payload: Dict[str, Any]) -> Optional[float]:
    direct_value = _payload_get(payload, "reference_electrode_potential")
    if direct_value not in (None, ""):
        try:
            return float(direct_value)
        except Exception:
            return None
    default_preset = _parameter_default("reference_electrode_preset", "")
    preset = str(_payload_get(payload, "reference_electrode_preset", default_preset) or default_preset).strip().lower()
    if preset in REFERENCE_ELECTRODE_PRESET_VALUES:
        return float(REFERENCE_ELECTRODE_PRESET_VALUES[preset])
    return None


def _resolve_potential_offset(payload: Dict[str, Any]) -> float:
    if _potential_mode(payload) == "formula_rhe":
        ref_value = _resolve_reference_electrode_potential(payload)
        default_ph = _parameter_default("rhe_ph", 0.0)
        ph_value = _as_float(_payload_get(payload, "rhe_ph", default_ph), default_ph or 0.0)
        default_temperature = _parameter_default("rhe_temperature_c", 25.0)
        temperature_c = _as_float(
            _payload_get(payload, "rhe_temperature_c", default_temperature),
            default_temperature,
        )
        # Nernst slope for H+/H2: 2.303 * R * T / F (V per pH unit).
        slope_v_per_ph = 2.303 * 8.31446261815324 * (temperature_c + 273.15) / 96485.33212
        return float(ref_value or 0.0) + slope_v_per_ph * ph_value
    default_offset = _parameter_default("potential_offset", 0.0)
    return _as_float(_payload_get(payload, "potential_offset", default_offset), default_offset)


def _potential_conversion_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
    mode = _potential_mode(payload)
    offset = _resolve_potential_offset(payload)
    if mode != "formula_rhe":
        return {
            "mode": "manual",
            "offset_v": offset,
            "formula": "E_converted = E_measured + offset",
        }
    default_ph = _parameter_default("rhe_ph", 0.0)
    ph_value = _as_float(_payload_get(payload, "rhe_ph", default_ph), default_ph or 0.0)
    default_temperature = _parameter_default("rhe_temperature_c", 25.0)
    temperature_c = _as_float(
        _payload_get(payload, "rhe_temperature_c", default_temperature),
        default_temperature,
    )
    slope_v_per_ph = 2.303 * 8.31446261815324 * (temperature_c + 273.15) / 96485.33212
    return {
        "mode": "formula_rhe",
        "offset_v": offset,
        "reference_electrode_potential_v_vs_she": _resolve_reference_electrode_potential(payload),
        "reference_electrode_preset": _payload_get(payload, "reference_electrode_preset"),
        "ph": ph_value,
        "temperature_c": temperature_c,
        "nernst_slope_v_per_ph": slope_v_per_ph,
        "formula": "E_RHE = E_measured + E_ref(vs SHE) + 2.303*R*T/F*pH",
        "assumptions": [
            "Reference-electrode preset potentials are nominal values versus SHE.",
            "The pH term follows the ideal Nernst equation; activity and junction-potential effects are not corrected.",
        ],
    }


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
        raise ValueError("至少选择一种处理方式 (data_types)")

    runtime = get_processing_module_registry()
    normalized: list[str] = []
    for item in raw_types:
        item = runtime.normalize_type(normalize_data_type(item))
        if item not in normalized:
            normalized.append(item)
    try:
        return runtime.validate_data_types(normalized, default_all=False)
    except KeyError as exc:
        invalid = [item for item in normalized if item not in runtime.supported_data_types()]
        detail = ", ".join(invalid) if invalid else str(exc)
        raise ValueError(f"不支持的数据类型: {detail}") from exc


def _normalize_input_files(
    payload: Dict[str, Any],
    data_types: list[str],
) -> dict[str, list[str]] | None:
    """Validate an optional explicit primary-file selection.

    ``None`` means the legacy folder-discovery mode.  A mapping means the
    caller explicitly chose the files and the pipeline must not discover
    additional primary inputs from the surrounding folders.
    """

    if "input_files" not in payload:
        return None
    raw_items = payload.get("input_files")
    if not isinstance(raw_items, list):
        raise ValueError("input_files 必须是数组")
    if len(raw_items) > 2000:
        raise ValueError("一次最多选择 2000 个数据文件")

    runtime = get_processing_module_registry()
    primary_types = [item for item in data_types if item != "COUPLED"]
    files_by_type: dict[str, list[str]] = {item: [] for item in primary_types}
    seen: dict[str, str] = {}
    for raw_item in raw_items:
        if isinstance(raw_item, str):
            if len(primary_types) != 1:
                raise ValueError("多处理方式下，每个 input_files 项都必须指定 data_type")
            path_value = raw_item
            data_type = primary_types[0]
            enabled = True
        elif isinstance(raw_item, dict):
            enabled = _as_bool(raw_item.get("enabled", True), True)
            if not enabled:
                continue
            path_value = raw_item.get("path")
            data_type = runtime.normalize_type(str(raw_item.get("data_type") or "").strip().upper())
        else:
            raise ValueError("input_files 中的项目必须是文件路径或对象")
        if not str(path_value or "").strip():
            raise ValueError("input_files 中存在空文件路径")
        if not data_type:
            raise ValueError(f"未指定文件处理类型: {path_value}")
        if data_type == "COUPLED":
            raise ValueError("COUPLED 文件请在定量数据区域选择，不作为主数据文件加入")
        if data_type not in data_types:
            raise ValueError(f"文件类型 {data_type} 未在本次处理方式中启用")

        file_path = os.path.abspath(os.path.expanduser(str(path_value)))
        if not os.path.isfile(file_path):
            raise ValueError(f"所选文件不存在: {file_path}")
        if Path(file_path).suffix.lower() not in {".txt", ".csv"}:
            raise ValueError(f"主数据文件格式不受支持: {os.path.basename(file_path)}")
        if not processable_files([os.path.basename(file_path)]):
            raise ValueError(f"不能选择处理结果作为输入: {os.path.basename(file_path)}")
        parent = os.path.dirname(file_path)
        if not _is_allowed_process_dir(parent):
            raise ValueError(f"所选文件不在允许范围内: {file_path}")

        key = os.path.normcase(os.path.realpath(file_path))
        previous_type = seen.get(key)
        if previous_type and previous_type != data_type:
            raise ValueError(
                f"同一文件不能同时分配给 {previous_type} 和 {data_type}: {file_path}"
            )
        if previous_type:
            continue
        seen[key] = data_type
        files_by_type.setdefault(data_type, []).append(file_path)
        register_allowed_dir(parent)

    if primary_types and not any(files_by_type.values()):
        raise ValueError("至少选择一个已启用的数据文件")
    return files_by_type


def _resolve_processing_folder(
    payload: Dict[str, Any],
    selected_files: dict[str, list[str]] | None,
) -> str:
    folder_path = str(payload.get("folder_path") or "").strip()
    if not folder_path and selected_files is not None:
        first_file = next(
            (item for values in selected_files.values() for item in values),
            "",
        )
        if first_file:
            folder_path = os.path.dirname(first_file)
    if not folder_path:
        raise ValueError("请先选择数据文件或文件夹")
    folder_path = os.path.abspath(os.path.expanduser(folder_path))
    if not os.path.isdir(folder_path):
        raise ValueError(f"文件夹不存在: {folder_path}")
    if not _is_allowed_process_dir(folder_path):
        raise ValueError("路径不在允许范围内")
    return folder_path


def _scan_processing_inputs(
    folder_path: str,
    gui_vars: Dict[str, Any],
    selected_files: dict[str, list[str]] | None,
) -> Dict[str, Any]:
    if selected_files is None:
        return _scan_pipeline_inputs(folder_path, gui_vars)
    return _scan_selected_inputs(folder_path, selected_files, gui_vars)


def _filename_type_hint(filename: str) -> str:
    upper_name = os.path.basename(str(filename or "")).upper()
    for data_type in ("ECSA", "EIS", "LSV", "CV"):
        if re.search(rf"(^|[^A-Z0-9]){data_type}([^A-Z0-9]|$)", upper_name):
            return data_type
    return ""


def discover_process_inputs(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Discover selectable primary inputs without running full preflight."""

    if not isinstance(payload, dict):
        return {"status": "error", "message": "request payload must be a JSON object"}
    match_types = [spec.key for spec in FILE_MATCH_MODULE_SPECS]
    discovery_payload = {"params": payload.get("params") if isinstance(payload.get("params"), dict) else {}}
    gui_vars = _build_gui_vars(match_types, discovery_payload)
    gui_vars["recursive_scan"] = _as_bool(payload.get("recursive_scan", False), False)
    match_config = {data_type: get_match_config(gui_vars, spec) for data_type, spec in (
        (spec.key, spec) for spec in FILE_MATCH_MODULE_SPECS
    )}

    raw_file_paths = payload.get("file_paths")
    source_mode = "files" if isinstance(raw_file_paths, list) else "folder"
    folder_path = str(payload.get("folder_path") or "").strip()
    if source_mode == "files":
        if not raw_file_paths:
            return {"status": "error", "message": "未选择文件"}
        if len(raw_file_paths) > 2000:
            return {"status": "error", "message": "一次最多选择 2000 个数据文件"}
        file_paths: list[str] = []
        seen: set[str] = set()
        for raw_path in raw_file_paths:
            file_path = os.path.abspath(os.path.expanduser(str(raw_path or "")))
            if not os.path.isfile(file_path):
                return {"status": "error", "message": f"所选文件不存在: {file_path}"}
            if Path(file_path).suffix.lower() not in {".txt", ".csv"}:
                return {"status": "error", "message": f"文件格式不受支持: {file_path}"}
            if not _is_allowed_process_dir(os.path.dirname(file_path)):
                return {"status": "error", "message": f"所选文件不在允许范围内: {file_path}"}
            key = os.path.normcase(os.path.realpath(file_path))
            if key in seen:
                continue
            seen.add(key)
            file_paths.append(file_path)
        if not folder_path and file_paths:
            folder_path = os.path.dirname(file_paths[0])
    else:
        try:
            folder_path = _resolve_processing_folder(payload, None)
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}
        scan = _scan_pipeline_inputs(folder_path, gui_vars)
        file_paths = [str(item) for item in scan.get("all_files") or []]

    preferred_types: list[str] = []
    for raw_type in payload.get("data_types") or []:
        normalized = str(raw_type or "").strip().upper()
        if normalized in match_types and normalized not in preferred_types:
            preferred_types.append(normalized)

    candidates: list[dict[str, Any]] = []
    for file_path in file_paths:
        filename = os.path.basename(file_path)
        matched_types = [
            data_type
            for data_type, (mode, pattern) in match_config.items()
            if matches_named_file(filename, mode, pattern)
        ]
        suggested_type = matched_types[0] if matched_types else _filename_type_hint(filename)
        if not suggested_type and source_mode == "files" and len(preferred_types) == 1:
            suggested_type = preferred_types[0]
        candidates.append(
            {
                "path": file_path,
                "name": filename,
                "folder": os.path.dirname(file_path),
                "matched_types": matched_types,
                "suggested_type": suggested_type,
                "status": "conflict" if len(matched_types) > 1 else ("recognized" if suggested_type else "unrecognized"),
                "size": os.path.getsize(file_path),
                "modified_at": os.path.getmtime(file_path),
            }
        )
    return {
        "status": "success",
        "source_mode": source_mode,
        "folder_path": os.path.abspath(folder_path) if folder_path else "",
        "files": candidates,
        "count": len(candidates),
    }


def _add_runtime_extension_preflight(
    scan: Dict[str, Any],
    *,
    folder_path: str,
    gui_vars: Dict[str, Any],
    data_types: list[str],
) -> Dict[str, Any]:
    """Add preflight details for runtime modules outside the built-in schema."""

    extension_types = [item for item in data_types if item not in SUPPORTED_DATA_TYPES]
    if not extension_types:
        return scan

    runtime = get_processing_module_registry()
    context = ModuleRunContext(
        folder_path=os.path.abspath(folder_path),
        params=dict(gui_vars),
        project_id=str(gui_vars.get("project_id") or "") or None,
        run_id=str(gui_vars.get("run_id") or "") or None,
        output_dir=str(gui_vars.get("output_dir") or "") or None,
    )
    updated = dict(scan or {})
    by_type = dict(updated.get("by_type") or {})
    warnings = [str(item) for item in updated.get("warnings") or []]
    selected_matched = int(updated.get("selected_matched") or 0)

    for data_type in extension_types:
        try:
            detail = runtime.preflight_module(data_type, context)
        except Exception as exc:
            detail = {
                "data_type": data_type,
                "runner": "module",
                "runnable": False,
                "status": "check",
                "matched": 0,
                "files": [],
                "param_errors": [str(exc)],
            }
        files = [str(item) for item in detail.get("files") or []]
        matched = int(detail.get("matched") or 0)
        param_errors = [str(item) for item in detail.get("param_errors") or []]
        by_type[data_type] = {
            "enabled": True,
            "matched": matched,
            "files": files,
            "examples": files[:5],
            "runner": detail.get("runner"),
            "status": detail.get("status"),
            "param_errors": param_errors,
        }
        selected_matched += matched
        if matched <= 0:
            warnings.append(f"{data_type} 未匹配到文件")
        warnings.extend(f"{data_type}: {message}" for message in param_errors)

    updated["by_type"] = by_type
    updated["selected_matched"] = selected_matched
    updated["warnings"] = list(dict.fromkeys(warnings))
    return updated


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
    if not math.isfinite(number):
        return f"{label} 必须是有限数字 ({key})"
    if integer_only and int(number) != number:
        return f"{label} 必须是整数 ({key})"
    if min_value is not None and number < min_value:
        return f"{label} 不能小于 {min_value} ({key})"
    if max_value is not None and number > max_value:
        return f"{label} 不能大于 {max_value} ({key})"
    return None


def _validate_payload(payload: Dict[str, Any], data_types: list[str]) -> str | None:
    raw_params = payload.get("params")
    if raw_params is not None and not isinstance(raw_params, dict):
        return "params 必须是 JSON 对象"
    if isinstance(raw_params, dict):
        schema_types = [item for item in data_types if item in SUPPORTED_DATA_TYPES]
        allowed_keys = {
            str(parameter["key"])
            for parameter in processing_parameter_schema(schema_types)["parameters"]
        }
        runtime = get_processing_module_registry()
        for data_type in data_types:
            allowed_keys.update(runtime.get_spec(data_type).parameter_keys)
        unknown_keys = sorted(
            str(key) for key in raw_params if not isinstance(key, str) or key not in allowed_keys
        )
        if unknown_keys:
            return f"不支持的处理参数: {', '.join(unknown_keys)}"

    selected = set(data_types)
    schema_types = [item for item in data_types if item in SUPPORTED_DATA_TYPES]
    for parameter in processing_parameter_schema(schema_types)["parameters"]:
        source_key = str(parameter["key"])
        value = _payload_get(payload, source_key)
        if value in (None, ""):
            if parameter.get("required") and parameter.get("default") in (None, ""):
                return f"{parameter.get('label') or source_key} 不能为空 ({source_key})"
            continue
        options = parameter.get("options") or []
        allowed = {str(item).casefold() for item in options}
        if allowed and str(value).casefold() not in allowed:
            choices = ", ".join(str(item) for item in options)
            return f"{parameter.get('label') or source_key} 不支持该选项: {value}; 可选值: {choices} ({source_key})"
        value_type = parameter.get("value_type")
        if value_type in {"integer", "number"}:
            message = _validate_numeric_param(
                payload,
                source_key,
                label=str(parameter.get("label") or source_key),
                min_value=parameter.get("min_value"),
                max_value=parameter.get("max_value"),
                integer_only=value_type == "integer",
            )
            if message:
                return message
    if _potential_mode(payload) == "formula_rhe":
        if _payload_get(payload, "rhe_ph") in (None, ""):
            return "pH 不能为空 (rhe_ph)"
        ref_value = _resolve_reference_electrode_potential(payload)
        if ref_value is None or not math.isfinite(ref_value):
            return "参比电极电位不能为空 (reference_electrode_potential)"
    overpotential_default = bool(_parameter_default("overpotential_enabled", False))
    if "LSV" in selected and _as_bool(
        _payload_get(payload, "overpotential_enabled", overpotential_default),
        overpotential_default,
    ):
        eq_value = _payload_get(payload, "eq_potential")
        if eq_value in (None, ""):
            return "平衡电位不能为空 (eq_potential)"
        message = _validate_numeric_param(payload, "eq_potential", label="平衡电位")
        if message:
            return message
    ir_enabled_default = bool(_parameter_default("ir_compensation_enabled", False))
    if "LSV" in selected and _as_bool(
        _payload_get(payload, "ir_compensation_enabled", ir_enabled_default),
        ir_enabled_default,
    ):
        ir_values = {
            "ir_source": _payload_get(payload, "ir_source"),
            "ir_method": _payload_get(payload, "ir_method"),
        }
        source = normalize_ir_source(ir_values)
        if source == "manual":
            raw_rs = _payload_get(payload, "ir_manual_ohm")
            try:
                manual_rs = float(raw_rs)
            except Exception:
                return "手动 Rs 必须是有效数字 (ir_manual_ohm)"
            if not math.isfinite(manual_rs) or manual_rs <= 0:
                return "手动 Rs 必须大于 0 Ohm (ir_manual_ohm)"
        else:
            default_scope = _parameter_default("ir_eis_search_scope", "")
            scope = str(_payload_get(payload, "ir_eis_search_scope", default_scope) or default_scope).strip().lower()
            if scope == "specified_file" and not str(_payload_get(payload, "ir_eis_file") or "").strip():
                return "指定 EIS 文件不能为空 (ir_eis_file)"
            default_match = _parameter_default("ir_eis_match", "")
            match_mode = str(_payload_get(payload, "ir_eis_match", default_match) or default_match).strip().lower()
            default_pattern = _parameter_default("ir_eis_pattern", "")
            pattern = str(_payload_get(payload, "ir_eis_pattern", default_pattern) or default_pattern).strip()
            if scope != "specified_file" and not pattern:
                return "EIS 文件匹配规则不能为空 (ir_eis_pattern)"
            if match_mode == "regex":
                try:
                    re.compile(pattern)
                except re.error as exc:
                    return f"EIS 正则表达式无效: {exc} (ir_eis_pattern)"
    if "COUPLED" in selected:
        try:
            coupled_mode = normalize_coupled_input_mode(
                _payload_get(payload, "coupled_input_mode", _parameter_default("coupled_input_mode"))
            )
        except ValueError as exc:
            return str(exc)
        if coupled_mode == "peak_analysis":
            method_payload = _payload_get(payload, "coupled_peak_method")
            try:
                method_source = normalize_coupled_peak_method_source(
                    _payload_get(
                        payload,
                        "coupled_peak_method_source",
                        _parameter_default("coupled_peak_method_source"),
                    ),
                    method_payload=method_payload if isinstance(method_payload, dict) else None,
                )
            except ValueError as exc:
                return str(exc)
            if method_source == "panel":
                if not isinstance(method_payload, dict):
                    return "Panel peak method is required (coupled_peak_method)"
                try:
                    parse_fe_peak_method(method_payload, source_name="panel")
                except ValueError as exc:
                    return f"Invalid panel peak method: {exc}"
            if method_source == "file" and not str(_payload_get(payload, "coupled_peak_method_file") or "").strip():
                return "峰分析方法文件不能为空 (coupled_peak_method_file)"
            default_detection_snr = _parameter_default("fe_peak_min_detection_snr", 0.0)
            detection_snr = _as_float(
                _payload_get(payload, "fe_peak_min_detection_snr", default_detection_snr),
                default_detection_snr,
            )
            default_quantification_snr = _parameter_default("fe_peak_min_quantification_snr", 0.0)
            quantification_snr = _as_float(
                _payload_get(payload, "fe_peak_min_quantification_snr", default_quantification_snr),
                default_quantification_snr,
            )
            if quantification_snr < detection_snr:
                return "定量 SNR 阈值不能低于检出 SNR 阈值"
    return None


def _coerce_gui_param_value(value: Any, spec: GuiParamSpec) -> Any:
    if spec.empty_as_default and value in (None, ""):
        value = spec.default
    if value is None and spec.default is None:
        return None
    if spec.value_type == "bool":
        return _as_bool(value, bool(spec.default))
    if spec.value_type == "int":
        return _as_int(value, int(spec.default))
    if spec.value_type == "float":
        fallback = float(spec.default) if spec.default is not None else 0.0
        return _as_float(value, fallback)
    if spec.value_type == "str":
        return str(value)
    return value


def _apply_gui_param_specs(gui_vars: Dict[str, Any], data_types: list[str], payload: Dict[str, Any]) -> None:
    for spec in gui_param_specs_for(data_types):
        value = _payload_get(payload, spec.key, spec.default)
        gui_vars[spec.key] = _coerce_gui_param_value(value, spec)


def _build_gui_vars(data_types: list[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    schema_types = [item for item in data_types if item in SUPPORTED_DATA_TYPES]
    gui_vars: Dict[str, Any] = parameter_defaults_for(schema_types, include_common=True)
    area_default = float(gui_vars["area"])
    gui_vars.update(
        {
            "area": _as_float(
                _payload_get(payload, "area", area_default),
                area_default,
            ),
            "potential_mode": _potential_mode(payload),
            "potential_offset": _resolve_potential_offset(payload),
            "potential_conversion": _potential_conversion_metadata(payload),
        }
    )
    gui_vars.update(enabled_flags_for_data_types(data_types))
    _apply_gui_param_specs(gui_vars, data_types, payload)

    extra_params = payload.get("params")
    if isinstance(extra_params, dict):
        for key, value in extra_params.items():
            if key not in gui_vars:
                gui_vars[key] = value
    return gui_vars


def _build_no_data_output_message(data_types: list[str], pipeline_result: Dict[str, Any]) -> str:
    matched_counts = pipeline_result.get("matched_counts") if isinstance(pipeline_result, dict) else {}
    matched_total = 0
    if isinstance(matched_counts, dict):
        for value in matched_counts.values():
            try:
                matched_total += int(value)
            except Exception:
                continue

    skipped = pipeline_result.get("skipped_errors", []) if isinstance(pipeline_result, dict) else []
    skipped_count = len(skipped) if isinstance(skipped, list) else 0
    prefix = "没有生成任何 CSV/PNG/XLSX 数据结果文件"
    selected = ", ".join(data_types) if data_types else "-"

    if matched_total <= 0:
        return (
            f"{prefix}。已选择数据类型: {selected}，但没有匹配到可处理的 .txt/.csv 文件。"
            "请检查数据类型勾选、匹配方式/前缀后缀、文件扩展名，以及数据文件是否在所选目录或一级子目录中。"
        )

    if skipped_count:
        first = skipped[0] if isinstance(skipped[0], dict) else {}
        first_file = os.path.basename(str(first.get("file") or "")) if isinstance(first, dict) else ""
        first_error = str(first.get("error") or "") if isinstance(first, dict) else ""
        detail = f"首个跳过文件: {first_file}" if first_file else "存在被跳过的文件"
        if first_error:
            detail = f"{detail}，原因: {first_error}"
        return f"{prefix}。匹配到 {matched_total} 个文件，但有 {skipped_count} 个文件处理失败或被跳过。{detail}"

    return (
        f"{prefix}。匹配到 {matched_total} 个文件，但没有产出有效结果。"
        "请检查文件内容是否为数值列、自动识别起始行是否能定位到数据区；ECSA 至少需要同一样品下两个以上扫速文件。"
    )


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
    summary_obj["mode"] = "v6_standard"
    summary_obj["folder"] = folder_path
    if pipeline_result.get("output_dir"):
        summary_obj["output_dir"] = pipeline_result.get("output_dir")
    if pipeline_result.get("recursive_scan") is not None:
        summary_obj["recursive_scan"] = bool(pipeline_result.get("recursive_scan"))
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


def _run_output_dir(folder_path: str, run_id: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_run = re.sub(r"[^0-9A-Za-z_\-.]+", "_", str(run_id or ""))[:8] or uuid.uuid4().hex[:8]
    target = os.path.join(folder_path, "electrochem_outputs", f"{stamp}_{safe_run}")
    os.makedirs(target, exist_ok=True)
    return target


def _path_is_within(path_value: str, root_value: str) -> bool:
    try:
        path = os.path.normcase(os.path.realpath(os.path.abspath(path_value)))
        root = os.path.normcase(os.path.realpath(os.path.abspath(root_value)))
        return os.path.commonpath([path, root]) == root
    except Exception:
        return False


def _resolve_explicit_output_dir(folder_path: str, output_dir_value: Any) -> str | None:
    raw = str(output_dir_value or "").strip()
    if not raw:
        return None
    target = os.path.abspath(os.path.expanduser(raw))
    allowed_roots = [
        os.path.abspath(folder_path),
        os.path.abspath(str(user_config_dir())),
        os.path.abspath(os.path.join(tempfile.gettempdir(), "electrochem_v6")),
    ]
    if not any(_path_is_within(target, root) for root in allowed_roots):
        raise ValueError("输出目录不在允许范围内")
    return target


def _resolve_product_table_path(folder_path: str, table_path_value: Any) -> str | None:
    raw = str(table_path_value or "").strip()
    if not raw:
        return None
    target = os.path.expanduser(raw)
    if not os.path.isabs(target):
        target = os.path.join(folder_path, target)
    target = os.path.abspath(target)
    if not os.path.isfile(target):
        raise ValueError(f"产品定量表不存在: {target}")
    parent = os.path.dirname(target) or folder_path
    if not _is_allowed_process_dir(parent):
        raise ValueError("产品定量表路径不在允许范围内")
    return target


def _resolve_coupled_peak_method_path(folder_path: str, method_path_value: Any) -> str | None:
    raw = str(method_path_value or "").strip()
    if not raw:
        return None
    target = os.path.expanduser(raw)
    if not os.path.isabs(target):
        target = os.path.join(folder_path, target)
    target = os.path.abspath(target)
    if not os.path.isfile(target):
        raise ValueError(f"峰分析方法文件不存在: {target}")
    if Path(target).suffix.lower() != ".json":
        raise ValueError("峰分析方法文件必须是 .json")
    parent = os.path.dirname(target) or folder_path
    if not _is_allowed_process_dir(parent):
        raise ValueError("峰分析方法文件路径不在允许范围内")
    return target


def _coupled_preflight_inputs(
    folder_path: str,
    gui_vars: Dict[str, Any],
) -> tuple[str, str | None, str | None, Dict[str, Any] | None]:
    input_mode = normalize_coupled_input_mode(gui_vars.get("coupled_input_mode"))
    product_table = _resolve_product_table_path(folder_path, gui_vars.get("coupled_products_file"))
    method_file = None
    method_payload = gui_vars.get("coupled_peak_method")
    method_source = normalize_coupled_peak_method_source(
        gui_vars.get("coupled_peak_method_source"),
        method_payload=method_payload if isinstance(method_payload, dict) else None,
    )
    if input_mode == "peak_analysis":
        if method_source == "file":
            method_file = _resolve_coupled_peak_method_path(
                folder_path,
                gui_vars.get("coupled_peak_method_file"),
            )
    inspection: Dict[str, Any] | None = None
    has_method = bool(method_file) if method_source == "file" else isinstance(method_payload, dict)
    if input_mode == "peak_analysis" and product_table and has_method:
        sheet_name = gui_vars.get("coupled_products_sheet", 0)
        if isinstance(sheet_name, str) and sheet_name.strip().isdigit():
            sheet_name = int(sheet_name.strip())
        inspection = inspect_fe_peak_inputs(
            product_table,
            method_file if method_source == "file" else None,
            method_payload=method_payload if method_source == "panel" else None,
            sheet_name=sheet_name,
            allowed_signal_roots=(folder_path,),
        )
        inspection["method_source"] = method_source
    return input_mode, product_table, method_file, inspection


def _resolve_ir_eis_file_path(folder_path: str, gui_vars: Dict[str, Any]) -> str | None:
    if not _as_bool(gui_vars.get("ir_compensation_enabled", False), False):
        return None
    if normalize_ir_source(gui_vars) != "eis":
        return None
    if str(gui_vars.get("ir_eis_search_scope") or "same_dir").strip().lower() != "specified_file":
        return None
    raw = str(gui_vars.get("ir_eis_file") or "").strip()
    if not raw:
        raise ValueError("指定 EIS 文件不能为空")
    target = os.path.expanduser(raw)
    if not os.path.isabs(target):
        target = os.path.join(folder_path, target)
    target = os.path.abspath(target)
    if not os.path.isfile(target):
        raise ValueError(f"指定的 EIS 文件不存在: {target}")
    if Path(target).suffix.lower() not in {".txt", ".csv"}:
        raise ValueError("指定的 EIS 文件必须是 .txt 或 .csv")
    parent = os.path.dirname(target) or folder_path
    if not _is_allowed_process_dir(parent):
        raise ValueError("指定的 EIS 文件不在允许范围内")
    return target


def preflight_process_folder(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {"status": "error", "message": "request payload must be a JSON object"}
    try:
        data_types = _normalize_data_types(payload)
        selected_files = _normalize_input_files(payload, data_types)
        folder_path = _resolve_processing_folder(payload, selected_files)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    validation_error = _validate_payload(payload, data_types)
    if validation_error:
        return {"status": "error", "message": validation_error}
    gui_vars = _build_gui_vars(data_types, payload)
    gui_vars["_selected_data_types"] = list(data_types)
    if selected_files is not None:
        gui_vars["_selected_files_by_type"] = selected_files
    gui_vars["input_root"] = os.path.abspath(folder_path)
    try:
        ir_eis_file = _resolve_ir_eis_file_path(folder_path, gui_vars)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    if ir_eis_file:
        gui_vars["ir_eis_file"] = ir_eis_file
        register_allowed_dir(os.path.dirname(ir_eis_file))
    try:
        coupled_mode, product_table, peak_method_file, peak_inspection = _coupled_preflight_inputs(
            folder_path,
            gui_vars,
        )
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    if product_table:
        gui_vars["coupled_products_file"] = product_table
    if peak_method_file:
        gui_vars["coupled_peak_method_file"] = peak_method_file
    recursive_default = bool(gui_vars.get("recursive_scan", False))
    gui_vars["recursive_scan"] = _as_bool(
        _payload_get(payload, "recursive_scan", recursive_default),
        recursive_default,
    )
    scan = finalize_preflight_scan(
        _add_runtime_extension_preflight(
            add_coupled_preflight(
                _scan_processing_inputs(folder_path, gui_vars, selected_files),
                gui_vars.get("coupled_products_file"),
                input_mode=coupled_mode,
                peak_method_path=peak_method_file,
                peak_inspection=peak_inspection,
            ),
            folder_path=folder_path,
            gui_vars=gui_vars,
            data_types=data_types,
        ),
        data_types=data_types,
    )
    return {"status": "success", "data_types": data_types, "preflight": scan}


# Directories under user home that should never be processed (credentials / secrets)
_HOME_SENSITIVE_DIRS = frozenset(
    {
        ".ssh",
        ".gnupg",
        ".gpg",
        ".aws",
        ".azure",
        ".kube",
        ".password-store",
        ".docker",
    }
)


def _is_allowed_process_dir(folder_path: str) -> bool:
    """Check *folder_path* is under an allowed root for data processing.

    Allowed roots:
    - current working directory tree
    - user home directory tree (excluding sensitive subdirectories)
    - any directory previously registered at runtime (via register_allowed_dir)
    """
    from electrochem_v6.core.system_service import _is_within_allowed_roots

    resolved = os.path.normcase(os.path.realpath(folder_path))
    # Always allow subdirs of cwd
    cwd_root = os.path.normcase(os.path.realpath(os.getcwd()))
    if resolved == cwd_root or resolved.startswith(cwd_root + os.sep):
        return True
    # Allow subdirs of home, but block sensitive directories
    home_root = os.path.normcase(os.path.realpath(os.path.expanduser("~")))
    if resolved == home_root or resolved.startswith(home_root + os.sep):
        rel = resolved[len(home_root) + len(os.sep) :] if resolved != home_root else ""
        first_component = rel.split(os.sep)[0] if rel else ""
        if first_component and first_component.lower() in {d.lower() for d in _HOME_SENSITIVE_DIRS}:
            return False
        return True
    # Fall back to the existing runtime whitelist
    return _is_within_allowed_roots(resolved)


def process_folder(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {"status": "error", "message": "request payload must be a JSON object"}
    runtime_payload = dict(payload)
    context: dict[str, str] = {}
    runtime_payload["_recipe_run_context"] = context
    try:
        result = _process_folder_impl(runtime_payload)
        if context.get("run_id"):
            recipe = get_run_recipe(context["run_id"])
            if recipe and recipe.get("status") == "running":
                finish_run_recipe(context["run_id"], status="failed", error=str(result.get("message") or "processing did not complete"))
        return result
    except ProcessingCancelledError as exc:
        if context.get("run_id"):
            finish_run_recipe(context["run_id"], status="cancelled", error=str(exc))
        raise
    except Exception as exc:
        if context.get("run_id"):
            finish_run_recipe(context["run_id"], status="failed", error=str(exc))
        raise


def _process_folder_impl(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {"status": "error", "message": "request payload must be a JSON object"}
    cancel_check = payload.get("_cancel_check")
    progress_callback = payload.get("_progress_callback")
    check_cancelled({"_cancel_check": cancel_check})
    try:
        data_types = _normalize_data_types(payload)
        selected_files = _normalize_input_files(payload, data_types)
        folder_path = _resolve_processing_folder(payload, selected_files)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    # User submitted this folder or chose its files via a native dialog.
    register_allowed_dir(folder_path)

    validation_error = _validate_payload(payload, data_types)
    if validation_error:
        return {"status": "error", "message": validation_error}

    gui_vars = _build_gui_vars(data_types, payload)
    if callable(cancel_check):
        gui_vars["_cancel_check"] = cancel_check
    if callable(progress_callback):
        gui_vars["_progress_callback"] = progress_callback
    gui_vars["_selected_data_types"] = list(data_types)
    if selected_files is not None:
        gui_vars["_selected_files_by_type"] = selected_files
    gui_vars["input_root"] = os.path.abspath(folder_path)
    project_name = payload.get("project_name")
    explicit_project_id = str(payload.get("project_id") or "").strip()
    if explicit_project_id:
        project = get_database().get_project(explicit_project_id)
        if not project or project.get("status") != "active":
            return build_process_error_result("指定项目已归档或不存在，请先恢复项目或选择有效项目")
        project_id = explicit_project_id
    elif str(project_name or "").strip():
        project_id = _resolve_project_id(project_name)
    else:
        project_id = get_database().get_default_project()
    if str(project_name or "").strip() and not project_id:
        return build_process_error_result(
            f"项目“{str(project_name).strip()}”无法使用；它可能已归档或与现有项目重名，请先在项目管理中恢复或重命名。"
        )
    run_id = uuid.uuid4().hex
    payload["_recipe_run_context"]["run_id"] = run_id
    gui_vars["run_id"] = run_id
    recursive_default = bool(gui_vars.get("recursive_scan", False))
    gui_vars["recursive_scan"] = _as_bool(
        _payload_get(payload, "recursive_scan", recursive_default),
        recursive_default,
    )
    output_run_dir_default = bool(gui_vars.get("output_run_dir_enabled", True))
    isolated_output = _as_bool(
        _payload_get(payload, "output_run_dir_enabled", output_run_dir_default),
        output_run_dir_default,
    )
    try:
        output_dir = _resolve_explicit_output_dir(folder_path, _payload_get(payload, "output_dir"))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    try:
        ir_eis_file = _resolve_ir_eis_file_path(folder_path, gui_vars)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    if ir_eis_file:
        gui_vars["ir_eis_file"] = ir_eis_file
        register_allowed_dir(os.path.dirname(ir_eis_file))
    try:
        coupled_mode, product_table, peak_method_file, peak_inspection = _coupled_preflight_inputs(
            folder_path,
            gui_vars,
        )
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    if product_table:
        gui_vars["coupled_products_file"] = product_table
        register_allowed_dir(os.path.dirname(product_table))
    if peak_method_file:
        gui_vars["coupled_peak_method_file"] = peak_method_file
        register_allowed_dir(os.path.dirname(peak_method_file))
    if not output_dir and isolated_output:
        output_dir = _run_output_dir(folder_path, run_id)
    if output_dir:
        gui_vars["output_dir"] = output_dir
    if project_id:
        gui_vars["project_id"] = project_id

    preflight_payload = finalize_preflight_scan(
        _add_runtime_extension_preflight(
            add_coupled_preflight(
                _scan_processing_inputs(folder_path, gui_vars, selected_files),
                gui_vars.get("coupled_products_file"),
                input_mode=coupled_mode,
                peak_method_path=peak_method_file,
                peak_inspection=peak_inspection,
            ),
            folder_path=folder_path,
            gui_vars=gui_vars,
            data_types=data_types,
        ),
        data_types=data_types,
    )
    progress_total = max(1, int(preflight_payload.get("selected_matched") or 0))
    gui_vars["_progress_state"] = {"current": 0, "total": progress_total}
    report_progress(gui_vars, current=0, total=progress_total, item="preflight")
    check_cancelled(gui_vars)
    if int(preflight_payload.get("selected_matched") or 0) <= 0:
        return build_process_error_result(
            _build_no_data_output_message(
                data_types,
                {
                    "matched_counts": {
                        k: v.get("matched", 0) for k, v in (preflight_payload.get("by_type") or {}).items()
                    }
                },
            ),
            result={
                "preflight": preflight_payload,
                "processing": {"output_files": []},
            },
        )
    ir_preflight = preflight_payload.get("ir_compensation")
    if isinstance(ir_preflight, dict) and not bool(ir_preflight.get("ok")):
        ir_warnings = ir_preflight.get("warnings") if isinstance(ir_preflight.get("warnings"), list) else []
        message = str(ir_warnings[0]) if ir_warnings else "iR 补偿的 EIS 配对未通过预检"
        return build_process_error_result(
            f"iR 补偿预检未通过: {message}",
            result={
                "preflight": preflight_payload,
                "processing": {"output_files": []},
            },
        )

    input_roots = [folder_path]
    if selected_files is not None:
        input_roots.extend(os.path.dirname(path) for paths in selected_files.values() for path in paths)
    register_run_archive_roots(
        run_id,
        input_root=folder_path,
        input_roots=input_roots,
        output_root=output_dir or folder_path,
    )
    try:
        recipe = capture_run_recipe(
            run_id=run_id, project_id=project_id, payload=payload, params=gui_vars,
            data_types=data_types, folder_path=folder_path, output_dir=output_dir or folder_path,
            preflight=preflight_payload,
        )
    except (OSError, ValueError) as exc:
        discard_unused_run_archive_roots(run_id)
        return build_process_error_result(f"无法固定本次处理来源: {exc}")
    try:
        result = _run_selected_modules(folder_path, gui_vars)
    except ProcessingCancelledError:
        raise
    except Exception as exc:
        return build_process_error_result(f"\u5904\u7406\u5931\u8d25: {exc}")
    finally:
        discard_unused_run_archive_roots(run_id)
    if not isinstance(result, dict):
        return build_process_error_result(
            f"processing pipeline returned unexpected payload type: {type(result).__name__}"
        )

    check_cancelled(gui_vars)
    report_progress(gui_vars, current=progress_total, total=progress_total, item="finalizing")
    gui_vars.pop("_cancel_check", None)
    gui_vars.pop("_progress_callback", None)
    gui_vars.pop("_progress_state", None)

    normalized_summary, normalized_summary_path = _rewrite_summary_for_v6(
        folder_path=folder_path,
        data_types=data_types,
        project_id=project_id,
        pipeline_result=result,
    )
    output_files = _collect_output_files(result)
    if not _has_data_output_file(output_files):
        return build_process_error_result(
            _build_no_data_output_message(data_types, result),
            result={
                "summary_path": normalized_summary_path or result.get("summary_path"),
                "processing": {"output_files": output_files},
                "quality_summary": result.get("quality_summary", {}),
                "skipped_errors": result.get("skipped_errors", []),
                "preflight": preflight_payload,
                "raw": result,
            },
        )
    summary_path = normalized_summary_path or result.get("summary_path")
    response_output_dir = str(result.get("output_dir") or output_dir or folder_path)
    finished_recipe = finish_run_recipe(run_id, status="succeeded") or recipe
    manifest = build_run_manifest(
        app_name=APP_NAME,
        app_version=APP_VERSION,
        run_id=run_id,
        project_id=project_id,
        data_types=data_types,
        params=gui_vars,
        preflight=preflight_payload,
        output_files=output_files,
        output_dir=response_output_dir,
        summary_path=summary_path,
        processing=_processing_stats(result, output_files),
        quality_summary=result.get("quality_summary", {}),
        skipped_errors=result.get("skipped_errors", []),
        raw_result=result,
        input_files=recipe["inputs"],
    )
    manifest["parameters"] = recipe["params"]
    manifest["inputs"]["integrity"] = finished_recipe.get("source_integrity")
    manifest["inputs"]["changed_during_processing"] = finished_recipe.get("changed_during_processing", [])
    manifest["engine"] = recipe["engine"]
    manifest["replay"] = {"parent_run_id": recipe.get("parent_run_id"), "parent_record_key": recipe.get("parent_record_key")}
    run_report_path = os.path.join(response_output_dir, "run_report.md")
    manifest["outputs"]["run_report_path"] = run_report_path
    try:
        result["run_report_path"] = write_run_report(manifest, output_dir=response_output_dir)
        if run_report_path not in output_files:
            output_files.append(run_report_path)
            manifest["outputs"]["output_files"] = list(output_files)
    except Exception as exc:
        manifest["run_report_error"] = str(exc)

    run_report_html_path = os.path.join(response_output_dir, "run_report.html")
    manifest["outputs"]["run_report_html_path"] = run_report_html_path
    try:
        result["run_report_html_path"] = write_run_report_html(manifest, output_dir=response_output_dir)
        if run_report_html_path not in output_files:
            output_files.append(run_report_html_path)
            manifest["outputs"]["output_files"] = list(output_files)
    except Exception as exc:
        manifest["run_report_html_error"] = str(exc)

    try:
        manifest_path = write_run_manifest(manifest, output_dir=response_output_dir)
        result["run_manifest_path"] = manifest_path
        manifest["outputs"]["run_manifest_path"] = manifest_path
        if manifest_path not in output_files:
            output_files.append(manifest_path)
            manifest["outputs"]["output_files"] = list(output_files)
    except Exception as exc:
        manifest["write_error"] = str(exc)

    try:
        attach_run_outputs(
            run_id=run_id,
            output_files=output_files,
            summary_path=normalized_summary_path or result.get("summary_path"),
            quality_summary=result.get("quality_summary", {}),
        )
    except Exception:
        # Processing already succeeded; history attachment must not turn a
        # valid result into a failed run when local storage is unavailable.
        pass

    # Register the data folder so that "open file / open dir" works in the UI
    register_allowed_dir(folder_path)
    if response_output_dir:
        register_allowed_dir(response_output_dir)

    update_run_recipe(run_id, manifest=manifest, output_files=output_files, output_dir=response_output_dir)

    return build_process_success_result(
        summary=f"\u5df2\u5904\u7406 {', '.join(data_types)} \u6570\u636e",
        data_types=data_types,
        project_id=project_id,
        summary_path=summary_path,
        output_files=output_files,
        output_dir=response_output_dir,
        preflight=preflight_payload,
        quality_summary=result.get("quality_summary", {}),
        skipped_errors=result.get("skipped_errors", []),
        summary_json=normalized_summary,
        raw=result,
        manifest=manifest,
    )


def get_project_lsv_target_currents(
    *,
    project_id: str,
    include_archived: bool = False,
) -> Dict[str, Any]:
    return _get_project_lsv_target_currents(project_id=project_id, include_archived=include_archived)


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
    return _build_project_lsv_compare_plot(
        project_id=project_id,
        selected_samples=selected_samples,
        include_archived=include_archived,
        chart_type=chart_type,
        metric_key=metric_key,
        target_current=target_current,
        output_dir=output_dir,
    )


def get_latest_project_lsv_compare_plot(
    *,
    project_id: str,
    chart_type: str = "overlay",
    metric_key: str = "overpotential_10",
    target_current: Any = 10.0,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    return _get_latest_project_lsv_compare_plot(
        project_id=project_id,
        chart_type=chart_type,
        metric_key=metric_key,
        target_current=target_current,
        output_dir=output_dir,
    )


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


def export_diagnostics() -> Dict[str, Any]:
    from electrochem_v6.config import (
        get_conversation_file,
        get_history_file,
        get_log_file,
        get_projects_file,
        get_templates_file,
        project_default_dir,
    )

    try:
        diag_dir = user_config_dir() / "diagnostics"
        diag_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        diag_dir = Path(tempfile.gettempdir()) / "electrochem_v6" / "diagnostics"
        try:
            diag_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {"status": "error", "message": f"导出诊断包失败: {exc}"}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = diag_dir / f"electrochem_diagnostics_{timestamp}.zip"
    manifest = {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cwd": os.getcwd(),
        "user_config_dir": str(user_config_dir()),
        "project_default_dir": str(project_default_dir()),
        "env": {
            "ELECTROCHEM_V6_DATA_DIR": os.environ.get("ELECTROCHEM_V6_DATA_DIR", ""),
        },
    }
    candidates = [
        get_quality_report_file(),
        get_projects_file(),
        get_history_file(),
        get_templates_file(),
        get_conversation_file(),
        get_log_file(),
        user_config_dir() / "runtime_info.json",
        user_config_dir() / "logs" / "electrochem.log",
        Path(tempfile.gettempdir()) / "electrochem_v6" / "logs" / "v6_server.log",
        Path(tempfile.gettempdir()) / "electrochem_v6" / "logs" / "electrochem.log",
    ]
    added: list[str] = []
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for path in candidates:
                try:
                    p = Path(path)
                    if p.exists() and p.is_file():
                        arcname = f"runtime/{p.name}"
                        zf.write(p, arcname)
                        added.append(str(p))
                except Exception:
                    continue
    except Exception as exc:
        return {"status": "error", "message": f"导出诊断包失败: {exc}"}
    register_allowed_dir(str(diag_dir))
    return {
        "status": "success",
        "path": str(zip_path),
        "file_name": zip_path.name,
        "included_files": added,
    }


def export_project_report(
    *,
    project: Dict[str, Any],
    report_data: Dict[str, Any],
    output_dir: str,
) -> Dict[str, Any]:
    return _export_project_report(project=project, report_data=report_data, output_dir=output_dir)
