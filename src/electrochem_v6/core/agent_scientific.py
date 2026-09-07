"""Evidence-based assistant analysis using the same input and unit contracts as processing."""

from __future__ import annotations

import math
import os
from typing import Any, Mapping

import numpy as np

from electrochem_v6.core.history_compare import _json_value, history_metrics_for_display
from electrochem_v6.core.processing_manifest import _file_identity
from electrochem_v6.core.processing_registry import processing_parameter_schema

MIN_CANDIDATE_POINTS = 8
MIN_CANDIDATE_LOG_SPAN = 0.5


def finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def scientific_parameter_requirements(data_type: str, params: Mapping[str, Any]) -> list[dict[str, str]]:
    """Require measured/selected scientific inputs before adding software defaults."""
    dtype = str(data_type).upper()
    values = dict(params)
    keys = []
    if dtype in {"LSV", "CV", "ECSA"}:
        prefix = dtype.lower()
        keys += [f"{prefix}_{field}" for field in ("potential_column", "current_column", "potential_unit", "current_unit")]
    if dtype in {"LSV", "ECSA"}:
        keys += ["area"]
    if dtype == "LSV":
        keys += ["use_abs_current", "ir_compensation_enabled", "potential_mode"]
        if values.get("potential_mode") == "formula_rhe":
            keys += ["rhe_ph", "rhe_temperature_c", "reference_electrode_preset"]
            if values.get("reference_electrode_preset") == "custom":
                keys += ["reference_electrode_potential"]
        elif values.get("potential_mode") == "manual":
            keys += ["potential_offset"]
        if values.get("ir_compensation_enabled") in (True, "true", "True", 1):
            keys += ["ir_source"]
            if values.get("ir_source") == "manual":
                keys += ["ir_manual_ohm"]
            elif values.get("ir_source") == "eis":
                keys += ["ir_eis_search_scope", "ir_method", "ir_validation_mode"]
                keys += [f"ir_eis_{key}" for key in ("frequency_column", "zreal_column", "zimag_column", "frequency_unit", "impedance_unit", "zimag_convention")]
                if values.get("ir_eis_search_scope") == "specified_file":
                    keys += ["ir_eis_file"]
    if dtype == "EIS":
        keys += [f"eis_{field}" for field in ("frequency_column", "zreal_column", "zimag_column", "frequency_unit", "impedance_unit", "zimag_convention")]
    if dtype == "ECSA":
        keys += ["ecsa_ev", "ecsa_last_n", "ecsa_avg_last_n", "ecsa_cs_value", "ecsa_cs_unit", "ecsa_use_abs_delta"]
    if dtype == "COUPLED":
        keys += ["coupled_input_mode", "coupled_products_file"]
    labels = {item["key"]: item.get("label", item["key"]) for item in processing_parameter_schema([dtype])["parameters"]}
    missing = []
    for key in dict.fromkeys(keys):
        value = values.get(key)
        reason = None
        if value is None or value == "":
            reason = "需要来自实验记录、已确认界面或保存配方的明确值，不能由助手猜测。"
        elif key in {"area", "ecsa_cs_value", "ir_manual_ohm"} and (finite_number(value) is None or float(value) <= 0):
            reason = "必须是大于零的有限数值。"
        if reason:
            missing.append({"key": key, "label": str(labels.get(key, key)), "reason": reason})
    return missing


def metric_value(record: Mapping[str, Any], key: str, unit: str) -> float | None:
    """Read a canonical metric, converting explicitly recorded compatible units."""
    item = history_metrics_for_display(record).get(key)
    if not item or item["value"] is None:
        return None
    source_unit = item.get("unit", "")
    factor = 1.0 if source_unit == unit else {("V", "mV"): 1000.0, ("mV", "V"): 0.001}.get((source_unit, unit))
    return finite_number(item["value"] * factor) if factor is not None else None


def _ir_potential(path: str, potential, signed_current, values: dict[str, Any], input_root: str):
    from electrochem_v6.core.process_service import _is_allowed_process_dir
    from electrochem_v6.core.processing_lsv_calc import apply_ir_compensation
    from electrochem_v6.core.processing_lsv_ir import extract_rs_from_eis, resolve_lsv_eis_match
    from electrochem_v6.core.processing_scan import resolve_data_start_line
    from electrochem_v6.core.processing_source_profile import (
        FREQUENCY_TO_HZ,
        IMPEDANCE_TO_OHM,
        column_number_to_index,
        imaginary_convention,
        unit_scale,
    )

    if not values["ir_compensation_enabled"]:
        return potential, {"enabled": False}, []
    match = resolve_lsv_eis_match(path, input_root, values)
    if match["status"] not in {"manual", "matched"}:
        raise ValueError(match["message"])
    sources = []
    if match["status"] == "manual":
        rs, diagnostics = match["rs_ohm"], match
    else:
        eis_path = match["eis_file"]
        if not _is_allowed_process_dir(os.path.dirname(eis_path)):
            raise ValueError("EIS 来源不在允许范围内")
        source_identity = _file_identity(eis_path)
        raw_start = values.get("ir_eis_start_line")
        start = resolve_data_start_line(eis_path) if raw_start in (None, "", "auto") else int(raw_start)
        frequency_scale = unit_scale(values["ir_eis_frequency_unit"], default="hz", supported=FREQUENCY_TO_HZ)[1]
        impedance_scale = unit_scale(values["ir_eis_impedance_unit"], default="ohm", supported=IMPEDANCE_TO_OHM)[1]
        sign = imaginary_convention(values["ir_eis_zimag_convention"])[1]
        result = extract_rs_from_eis(eis_path, start_line=start, method=values["ir_method"],
                                    hf_points=values.get("ir_linear_points", 10), validation_mode=values["ir_validation_mode"],
                                    frequency_column=column_number_to_index(values["ir_eis_frequency_column"], default=1, label="frequency"),
                                    zreal_column=column_number_to_index(values["ir_eis_zreal_column"], default=2, label="real"),
                                    zimag_column=column_number_to_index(values["ir_eis_zimag_column"], default=3, label="imaginary"),
                                    frequency_scale=frequency_scale, impedance_scale=impedance_scale, zimag_sign=sign)
        rs, diagnostics = result.rs_ohm, result.to_dict()
        if _file_identity(eis_path).get("sha256") != source_identity.get("sha256"):
            raise ValueError("EIS 输入在分析期间发生变化，请重新分析")
        sources.append({"path": eis_path, "role": "ir_eis", **source_identity})
        if rs is None or not math.isfinite(rs) or rs <= 0:
            raise ValueError(result.message)
    adjusted = apply_ir_compensation(potential, signed_current, area_cm2=values["area"], resistance_ohm=rs)
    return np.asarray(adjusted), {"enabled": True, "rs_ohm": rs, "diagnostics": diagnostics}, sources


def tafel_candidates(potential, current, signed_current, configured_range: Any = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Return supported intervals in source order; never identify an optimal range."""
    from electrochem_v6.core.processing_lsv_calc import _parse_tafel_range
    from electrochem_v6.core.processing_lsv_metrics import compute_tafel_slope_mVdec

    finite = np.isfinite(potential) & np.isfinite(current) & np.isfinite(signed_current)
    differences = np.diff(np.asarray(potential)[finite])
    nonzero = differences[np.abs(differences) > 1e-12]
    if len(nonzero) and np.any(nonzero > 0) and np.any(nonzero < 0):
        return [], ["电位包含多个扫描方向；当前处理器的电流范围不能唯一选择分支，需先明确单一扫描分支。"]
    positive = np.asarray(current)[finite & (current > 0)]
    if len(positive) < MIN_CANDIDATE_POINTS:
        return [], ["正电流密度有效点不足；不能据此提出 Tafel 候选区间。"]
    lower, upper = float(np.min(positive)), float(np.max(positive))
    if math.log10(upper / lower) < MIN_CANDIDATE_LOG_SPAN:
        return [], ["已测电流密度跨度不足，无法形成候选区间。"]
    ranges = []
    configured = _parse_tafel_range(configured_range)
    if configured:
        ranges.append(tuple(sorted(configured)))
    for start in np.arange(math.log10(lower), math.log10(upper) - MIN_CANDIDATE_LOG_SPAN + 1e-9, 0.5):
        ranges.append((10.0 ** float(start), min(upper, 10.0 ** float(start + 1.0))))
    candidates, seen = [], set()
    for lo, hi in ranges:
        # Round inwards so the displayed/action range matches this exact mask.
        lo, hi = float(f"{lo:.12g}"), float(f"{hi:.12g}")
        if lo < lower * (1 - 1e-10) or hi > upper * (1 + 1e-10) or lo <= 0 or hi <= lo:
            continue
        mask = finite & (current > 0) & (current >= lo) & (current <= hi)
        indices = np.flatnonzero(mask)
        if len(indices) < MIN_CANDIDATE_POINTS or np.any(np.diff(indices) != 1):
            continue
        signs = np.sign(np.asarray(signed_current)[indices])
        if np.any(signs != signs[0]):
            continue
        if (int(indices[0]), int(indices[-1])) in seen:
            continue
        seen.add((int(indices[0]), int(indices[-1])))
        x, y = np.log10(np.asarray(current)[indices]), np.asarray(potential)[indices]
        span = float(np.ptp(x))
        if span < MIN_CANDIDATE_LOG_SPAN:
            continue
        slope = compute_tafel_slope_mVdec(potential, current, f"{lo:.12g}-{hi:.12g}")
        if slope is None:
            continue
        intercept = float(np.mean(y) - slope / 1000.0 * np.mean(x))
        residual = y - (slope / 1000.0 * x + intercept)
        total = float(np.sum((y - np.mean(y)) ** 2))
        r2 = finite_number(1 - float(np.sum(residual ** 2)) / total) if total > 0 else None
        candidates.append({"range_mA_cm2": [lo, hi], "tafel_range": f"{lo:.12g}-{hi:.12g}",
                           "point_count": len(indices), "log_span_decades": span, "slope_mV_dec": slope,
                           "intercept_V": intercept, "r2": r2, "rmse_V": float(np.sqrt(np.mean(residual ** 2))),
                           "max_abs_residual_V": float(np.max(np.abs(residual))),
                           "selected_index_ranges": [[int(indices[0]), int(indices[-1])]], "index_basis": "zero_based_parsed_rows_inclusive",
                           "current_sign": int(signs[0]), "requires_review": True,
                           "limitations": ["点数与跨度只是计算筛选条件；线性拟合不能证明动力学控制，也不代表最优区间。"]})
        if len(candidates) >= 5:
            break
    return candidates, [] if candidates else ["没有同时满足有效点数、实际跨度和单分支要求的候选区间。"]


def analyze_lsv_source(path: str, params: Mapping[str, Any] | None = None, run_id: str | None = None) -> dict[str, Any]:
    from electrochem_v6.core.process_service import _build_gui_vars, _validate_payload
    from electrochem_v6.core.processing_lsv_io import read_lsv_raw_data
    from electrochem_v6.core.processing_scan import resolve_data_start_line
    from electrochem_v6.core.run_replay import _path_key, _public_param_keys
    from electrochem_v6.store.run_recipes import get_run_recipe

    supplied = dict(params or {})
    recipe = None
    if run_id:
        recipe = get_run_recipe(run_id)
        if not recipe or not any(_path_key(item["path"]) == _path_key(path) for item in recipe.get("inputs") or []):
            raise ValueError("该文件不属于指定运行，不能套用其配方")
        supplied = {**(recipe.get("params") or {}), **supplied}
    keys = _public_param_keys(["LSV"])
    supplied = {key: value for key, value in supplied.items() if key in keys}
    start_line = int(supplied.get("start_line") or resolve_data_start_line(path))
    identity = _file_identity(path)
    response = {"schema_version": "1.0", "success": True, "file_path": path, "data_type": "LSV",
                "characteristics": {"data_start_line": start_line}, "missing_parameters": scientific_parameter_requirements("LSV", supplied),
                "effective_params": supplied, "candidate_tafel_ranges": [],
                "provenance": {"path": path, **identity, "run_id": run_id, "parameter_source": "saved_recipe_with_explicit_overrides" if recipe else "explicit_parameters"},
                "units": {"potential": "V", "current_density": "mA/cm²", "tafel_slope": "mV/dec"},
                "limitations": ["不会从曲线猜测电解液、反应类型或参比；不据此评定催化剂等级。", "候选区间需要结合噪声、传质与实验条件人工复核。"]}
    if recipe:
        old = next(item for item in recipe.get("inputs") or [] if _path_key(item["path"]) == _path_key(path))
        state = "unverified" if not old.get("sha256") else "unchanged" if old["sha256"] == identity.get("sha256") else "changed"
        response["provenance"]["recipe_input_state"] = state
        if state != "unchanged":
            response["limitations"].append("当前输入与原运行的指纹不一致或无法核对；旧配方仅作为参数来源，本次分析不代表旧运行结果。")
    if response["missing_parameters"]:
        response["effective_params"] = _json_value(supplied)
        response["recommendation_status"] = "needs_parameters"
        return response
    payload = {"params": supplied, "data_types": ["LSV"]}
    error = _validate_payload(payload, ["LSV"])
    if error:
        raise ValueError(error)
    values = _build_gui_vars(["LSV"], payload)
    values["start_line"], values["offset"] = start_line, values["potential_offset"]
    raw = read_lsv_raw_data(path, file_label=os.path.basename(path), params=values)
    potential, current, signed = (np.asarray(item, float) for item in (raw.potential, raw.current, raw.current_signed))
    original_potential = potential.copy()
    potential, ir, dependencies = _ir_potential(path, potential, signed, values, (recipe or {}).get("folder_path") or os.path.dirname(path))
    finite = np.isfinite(potential) & np.isfinite(current) & np.isfinite(signed)
    response["effective_params"] = {key: values[key] for key in keys if key in values}
    response["provenance"].update(parser="read_lsv_raw_data", full_input_read=True, dependencies=dependencies)
    response["characteristics"].update(data_points=len(current), finite_points=int(np.count_nonzero(finite)),
        rejected_nonfinite_points=int(np.count_nonzero(~finite)), parse_errors=raw.parse_errors, ir_compensation=ir,
        current_density_range_mA_cm2={"min": float(np.min(current[finite])), "max": float(np.max(current[finite]))} if np.any(finite) else None,
        potential_range_V={"min": float(np.min(potential[finite])), "max": float(np.max(potential[finite]))} if np.any(finite) else None)
    # Scan direction is a property of the acquired potential, before iR correction.
    raw_diffs = np.diff(original_potential[np.isfinite(original_potential)])
    if np.any(raw_diffs > 1e-12) and np.any(raw_diffs < -1e-12):
        candidates, limitations = [], ["原始电位有多扫描方向，当前范围参数无法唯一选择分支。"]
    else:
        candidates, limitations = tafel_candidates(potential, current, signed, supplied.get("tafel_range"))
    if _file_identity(path).get("sha256") != identity.get("sha256"):
        raise ValueError("输入文件在分析期间发生变化，请重新分析")
    response["candidate_tafel_ranges"] = candidates
    response["limitations"].extend(limitations)
    response["recommendation_status"] = "candidates_available" if candidates else "insufficient_data"
    response["candidate_policy"] = {"minimum_points": MIN_CANDIDATE_POINTS, "minimum_log_span_decades": MIN_CANDIDATE_LOG_SPAN, "ordering": "configured_interval_then_ascending_current", "physical_validity_verified": False}
    return _json_value(response)
