"""ECSA processing orchestration and compatibility exports."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from . import processing_core_v6 as core
from .processing_common import ensure_output_dir
from .processing_ecsa_calc import (
    _ecsa_find_pairs,
    _ecsa_interp_I,
    _to_mF_per_cm2,
    calculate_ecsa_fit,
    compute_deltaJ_for_file,
    fit_deltaJ_vs_v,
)
from .processing_ecsa_history import add_ecsa_history_record, build_ecsa_history_record
from .processing_ecsa_io import (
    _ecsa_extract_v_from_content,
    _ecsa_extract_v_from_name,
    _ecsa_read_cv_table,
    _ecsa_read_text_lines,
)
from .processing_ecsa_plot import plot_ecsa_result
from .processing_source_profile import (
    CURRENT_TO_A,
    POTENTIAL_TO_V,
    column_number_to_index,
    unit_scale,
)
from .utils import as_bool, as_float, as_int

CHINESE_FONT = core.CHINESE_FONT
natural_sort_key = core.natural_sort_key
_matches_named_file = core._matches_named_file
_resolve_plot_font = core._resolve_plot_font
HISTORY_MANAGER_AVAILABLE = core.HISTORY_MANAGER_AVAILABLE
PROJECT_MANAGER_AVAILABLE = core.PROJECT_MANAGER_AVAILABLE
get_history_manager = core.get_history_manager
get_project_manager = core.get_project_manager
log = core.log


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _extract_sample_token(lsv_filename: str) -> Optional[str]:
    """Derive a sample identifier from the LSV file name."""
    stem = Path(lsv_filename).stem
    stem = re.sub(r"(?i)(?:[_\-\s]*(lsv|polarization|scan|lsvscan|lsvdata))+$", "", stem).strip("_- ")
    token = _normalize_token(stem)
    return token or None


def _match_eis_by_sample(files_in_folder: list[str], sample_token: str) -> Optional[str]:
    """Try to locate an EIS file whose name contains the same sample token."""
    if not sample_token:
        return None
    best_candidate = None
    for filename in files_in_folder:
        lower = filename.lower()
        if not (lower.endswith(".txt") or lower.endswith(".csv")):
            continue
        stem_token = _normalize_token(Path(filename).stem)
        if sample_token in stem_token and "eis" in stem_token:
            if stem_token.endswith(sample_token + "eis") or stem_token.endswith("eis" + sample_token):
                return filename
            if best_candidate is None:
                best_candidate = filename
    return best_candidate


def _select_ecsa_candidates(files: list, *, mode: str, prefix: str) -> list[str]:
    candidates: list[str] = []
    for filename in files:
        lower = str(filename).lower()
        if not (lower.endswith(".txt") or lower.endswith(".csv")):
            continue
        if _matches_named_file(filename, mode, prefix):
            candidates.append(filename)
    return candidates


def process_ecsa_for_subfolder(subfolder: str, files: list, params: dict, common: dict):
    """Process all ECSA CV files in one sample folder."""
    prefix = params.get("match_prefix", "ECSA")
    mode = params.get("match", "prefix")
    candidates = _select_ecsa_candidates(files, mode=mode, prefix=prefix)
    if not candidates:
        return None

    ev = as_float(params.get("ev", 0.10), 0.10)
    last_n = as_int(params.get("last_n", 1), 1)
    avg_last_n = as_bool(params.get("avg_last_n", False), False)
    area = as_float(common.get("area", 1.0), 1.0)
    use_abs = as_bool(params.get("use_abs_delta", True), True)
    potential_column = column_number_to_index(
        params.get("ecsa_potential_column", 1), default=1, label="ECSA potential column"
    )
    current_column = column_number_to_index(
        params.get("ecsa_current_column", 2), default=2, label="ECSA current column"
    )
    potential_unit, potential_scale = unit_scale(
        params.get("ecsa_potential_unit"), default="v", supported=POTENTIAL_TO_V
    )
    current_unit, current_scale = unit_scale(
        params.get("ecsa_current_unit"), default="a", supported=CURRENT_TO_A
    )

    v_list: list[float] = []
    dJ_list: list[float] = []
    for filename in sorted(candidates, key=natural_sort_key):
        filepath = os.path.join(subfolder, filename)
        scan_rate, delta_j = compute_deltaJ_for_file(
            filepath,
            ev,
            last_n,
            avg_last_n,
            area,
            use_abs,
            log_func=log,
            potential_column=potential_column,
            current_column=current_column,
            potential_scale=potential_scale,
            current_scale=current_scale,
        )
        if scan_rate is not None and delta_j is not None:
            v_list.append(scan_rate)
            dJ_list.append(delta_j)
    if len(v_list) < 2:
        return None

    fit = calculate_ecsa_fit(
        v_list=v_list,
        dJ_list=dJ_list,
        area_cm2=area,
        cs_value=params.get("cs_value", 40.0),
        cs_unit=params.get("cs_unit", "µF/cm²"),
    )
    if fit is None:
        log("ECSA fit skipped: at least two finite, distinguishable positive scan rates are required.")
        return None

    assumptions = {
        "method": "double_layer_capacitance_scan_rate_fit",
        "delta_current_definition": "DeltaJ = abs(J_anodic - J_cathodic)",
        "cdl_formula": "Cdl_areal = slope(DeltaJ vs scan_rate) / 2",
        "ecsa_formula": "ECSA = (Cdl_areal / Cs_areal) * geometric_area",
        "roughness_factor_formula": "RF = Cdl_areal / Cs_areal",
        "evaluation_potential_v": ev,
        "geometric_area_cm2": area,
        "specific_capacitance_input": fit.cs_input,
        "specific_capacitance_unit": fit.cs_unit,
        "specific_capacitance_normalized_mf_cm2": fit.cs_mFcm2,
        "current_normalization": "input current converted to A then divided by geometric area",
        "scan_rate_unit": "V/s",
        "limitations": [
            "Specific capacitance Cs depends on material, electrolyte, potential window, surface state, and temperature.",
            "The result is model-dependent and is not a direct geometric surface measurement.",
            "A linear non-faradaic DeltaJ-scan-rate relation is assumed at the selected evaluation potential.",
        ],
    }

    output_dir = ensure_output_dir(params.get("output_dir"), subfolder)
    sample_name = os.path.basename(subfolder)
    font_to_use = _resolve_plot_font(common.get("font", CHINESE_FONT))
    out_png = plot_ecsa_result(
        sample_name=sample_name,
        output_dir=output_dir,
        v_list=v_list,
        dJ_list=dJ_list,
        fit=fit,
        params=params,
        font_name=font_to_use,
        fontsize=common.get("fontsize", 12),
    )

    if HISTORY_MANAGER_AVAILABLE:
        try:
            history_mgr = get_history_manager()
            project_manager = get_project_manager() if PROJECT_MANAGER_AVAILABLE else None
            record = build_ecsa_history_record(
                sample_name=sample_name,
                subfolder=subfolder,
                params=params,
                fit=fit,
                scan_rates=v_list,
                project_manager=project_manager,
            )
            add_ecsa_history_record(
                history_mgr,
                record,
                log_func=log,
                sample_name=sample_name,
            )
        except Exception as exc:
            log(f"Failed to save ECSA history record: {exc}")

    return {
        "sample": sample_name,
        "Ev": ev,
        "n_used": last_n,
        "avg_last_n": avg_last_n,
        "N_points": len(v_list),
        "slope_mFcm2": fit.slope_mFcm2,
        "intercept": fit.intercept,
        "R2": fit.r2,
        "Cdl_mFcm2": fit.cdl_mFcm2,
        "Cs_input": fit.cs_input,
        "Cs_unit": fit.cs_unit,
        "Cs_mFcm2": fit.cs_mFcm2,
        "ECSA_cm2": fit.ecsa_cm2,
        "RF": fit.rf,
        "assumptions": assumptions,
        "source_profile": {
            "potential_column": potential_column + 1,
            "current_column": current_column + 1,
            "potential_unit": potential_unit,
            "current_unit": current_unit,
            "normalized_potential_unit": "V",
            "normalized_current_unit": "A",
        },
        "png": out_png,
    }


__all__ = [
    "_ecsa_extract_v_from_content",
    "_ecsa_extract_v_from_name",
    "_ecsa_find_pairs",
    "_ecsa_interp_I",
    "_ecsa_read_cv_table",
    "_ecsa_read_text_lines",
    "_extract_sample_token",
    "_match_eis_by_sample",
    "_normalize_token",
    "_to_mF_per_cm2",
    "calculate_ecsa_fit",
    "compute_deltaJ_for_file",
    "fit_deltaJ_vs_v",
    "process_ecsa_for_subfolder",
]
