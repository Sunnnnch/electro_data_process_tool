"""LSV iR-compensation source resolution and preflight helpers."""

from __future__ import annotations

import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .processing_lsv_calc import EIS_RELATIVE_IMAG_THRESHOLD, _filter_outliers
from .processing_registry import (
    IR_EXTRACTION_METHODS,
    IR_SEARCH_SCOPES,
    IR_SOURCE_EIS,
    IR_SOURCE_MANUAL,
    IR_VALIDATION_MODES,
)
from .processing_source_profile import split_table_row
from .utils import read_file_with_fallback_encodings

IR_COMPENSATION_FORMULA = "E_iR = E_measured - (j_mA_cm2 / 1000) * A_cm2 * Rs_ohm"

_TEXT_EXTENSIONS = {".txt", ".csv"}
_SKIPPED_DIRS = {".git", "__pycache__", ".pytest_cache", "electrochem_outputs", "user_data"}
_RESULT_MARKERS = (
    "processing_results",
    "quality_report",
    "_combined_",
    "combined_",
    "_summary",
    "_lsv.png",
    "_lsv_ir_compensated.png",
    "_eis_nyquist.png",
    "_eis_bode.png",
    "_results.csv",
)


@dataclass(frozen=True)
class IrExtractionResult:
    """Rs estimate together with enough evidence to audit the correction."""

    rs_ohm: float | None
    requested_method: str
    method_used: str | None
    validation_mode: str
    confidence: str
    point_count: int
    hf_point_count: int
    frequency_min_hz: float | None = None
    frequency_max_hz: float | None = None
    fit_r2: float | None = None
    intercept_condition_met: bool = False
    warnings: tuple[str, ...] = ()
    message: str = ""

    @property
    def accepted(self) -> bool:
        return self.rs_ohm is not None and math.isfinite(self.rs_ohm) and self.rs_ohm > 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_ir_validation_mode(params: Mapping[str, Any] | None) -> str:
    raw = str((params or {}).get("ir_validation_mode") or "strict").strip().lower()
    return raw if raw in IR_VALIDATION_MODES else "strict"


def _rejected_ir_result(
    *,
    method: str,
    validation_mode: str,
    point_count: int = 0,
    hf_point_count: int = 0,
    frequency_min_hz: float | None = None,
    frequency_max_hz: float | None = None,
    fit_r2: float | None = None,
    intercept_condition_met: bool = False,
    warnings: Sequence[str] = (),
    message: str,
) -> IrExtractionResult:
    return IrExtractionResult(
        rs_ohm=None,
        requested_method=method,
        method_used=None,
        validation_mode=validation_mode,
        confidence="rejected",
        point_count=point_count,
        hf_point_count=hf_point_count,
        frequency_min_hz=frequency_min_hz,
        frequency_max_hz=frequency_max_hz,
        fit_r2=fit_r2,
        intercept_condition_met=intercept_condition_met,
        warnings=tuple(str(item) for item in warnings),
        message=message,
    )


def extract_rs_from_eis(
    filepath: str,
    *,
    start_line: int = 1,
    method: str = "auto",
    hf_points: int = 10,
    validation_mode: str = "strict",
    frequency_column: int = 0,
    zreal_column: int = 1,
    zimag_column: int = 2,
    frequency_scale: float = 1.0,
    impedance_scale: float = 1.0,
    zimag_sign: float = 1.0,
) -> IrExtractionResult:
    """Estimate solution resistance from the EIS high-frequency region.

    Strict mode rejects an automatic estimate when neither a credible near-axis
    point nor a valid linear intercept is available. Lenient mode preserves the
    historical high-frequency-mean fallback but marks it as low confidence.
    """

    method_key = str(method or "auto").strip().lower()
    if method_key not in IR_EXTRACTION_METHODS:
        method_key = "auto"
    validation_key = str(validation_mode or "strict").strip().lower()
    if validation_key not in IR_VALIDATION_MODES:
        validation_key = "strict"

    try:
        columns = [int(frequency_column), int(zreal_column), int(zimag_column)]
        frequency_factor = float(frequency_scale)
        scale = float(impedance_scale)
        imag_sign = float(zimag_sign)
    except (TypeError, ValueError):
        return _rejected_ir_result(
            method=method_key,
            validation_mode=validation_key,
            message="EIS 列索引或阻抗单位换算无效。",
        )
    if (
        min(columns) < 0
        or not math.isfinite(frequency_factor)
        or frequency_factor <= 0
        or not math.isfinite(scale)
        or scale <= 0
        or imag_sign not in (-1.0, 1.0)
    ):
        return _rejected_ir_result(
            method=method_key,
            validation_mode=validation_key,
            message="EIS 列索引必须大于等于 0，阻抗换算系数必须大于 0。",
        )

    try:
        lines = read_file_with_fallback_encodings(filepath, start_line=max(1, int(start_line)))
    except (OSError, ValueError) as exc:
        return _rejected_ir_result(
            method=method_key,
            validation_mode=validation_key,
            message=f"无法读取 EIS 文件: {exc}",
        )
    if lines is None:
        return _rejected_ir_result(
            method=method_key,
            validation_mode=validation_key,
            message="无法使用支持的编码读取 EIS 文件。",
        )

    frequencies: list[float] = []
    z_real: list[float] = []
    z_imag: list[float] = []
    required_columns = max(columns) + 1
    for line in lines:
        parts = split_table_row(line)
        if len(parts) < required_columns:
            continue
        try:
            frequency = float(parts[columns[0]]) * frequency_factor
            real = float(parts[columns[1]]) * scale
            imag = float(parts[columns[2]]) * scale * imag_sign
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(item) for item in (frequency, real, imag)) or frequency <= 0:
            continue
        frequencies.append(frequency)
        z_real.append(real)
        z_imag.append(imag)

    point_count = len(z_real)
    if point_count < 2:
        return _rejected_ir_result(
            method=method_key,
            validation_mode=validation_key,
            point_count=point_count,
            message="EIS 有效数据点不足，至少需要 2 个频率/阻抗点。",
        )

    try:
        requested_hf_points = int(hf_points)
    except (TypeError, ValueError):
        requested_hf_points = 10
    requested_hf_points = max(3, requested_hf_points)
    high_freq_indices = sorted(
        range(point_count), key=lambda index: frequencies[index], reverse=True
    )[: min(requested_hf_points, point_count)]
    hf_real, hf_imag, hf_freq = _filter_outliers(
        [z_real[index] for index in high_freq_indices],
        [z_imag[index] for index in high_freq_indices],
        [frequencies[index] for index in high_freq_indices],
    )
    hf_count = len(hf_real)
    frequency_min = min(hf_freq) if hf_freq else None
    frequency_max = max(hf_freq) if hf_freq else None
    if hf_count < 2:
        return _rejected_ir_result(
            method=method_key,
            validation_mode=validation_key,
            point_count=point_count,
            hf_point_count=hf_count,
            frequency_min_hz=frequency_min,
            frequency_max_hz=frequency_max,
            message="EIS 高频区经异常值过滤后数据点不足。",
        )

    nearest_index = min(range(hf_count), key=lambda index: abs(hf_imag[index]))
    nearest_rs = float(hf_real[nearest_index])
    imag_span = max(abs(min(z_imag)), abs(max(z_imag)))
    imag_threshold = EIS_RELATIVE_IMAG_THRESHOLD * imag_span if imag_span > 0 else EIS_RELATIVE_IMAG_THRESHOLD
    intercept_condition = abs(hf_imag[nearest_index]) <= imag_threshold

    fit_candidate: float | None = None
    fit_r2: float | None = None
    fit_is_valid = False
    if hf_count >= 3:
        x = np.asarray(hf_real, dtype=float)
        y = np.asarray(hf_imag, dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        predicted = slope * x + intercept
        residual_sum = float(np.sum((y - predicted) ** 2))
        total_sum = float(np.sum((y - float(np.mean(y))) ** 2))
        fit_r2 = 1.0 if total_sum <= 1e-24 and residual_sum <= 1e-24 else (
            1.0 - residual_sum / total_sum if total_sum > 1e-24 else 0.0
        )
        if abs(float(slope)) > 1e-12:
            candidate = float(-intercept / slope)
            x_min = min(hf_real)
            x_max = max(hf_real)
            span = max(x_max - x_min, max(abs(x_min), 1.0) * 0.05)
            fit_candidate = candidate
            fit_is_valid = (
                math.isfinite(candidate)
                and candidate > 0
                and x_min - span <= candidate <= x_max
                and fit_r2 is not None
                and fit_r2 >= 0.90
            )

    common = {
        "requested_method": method_key,
        "validation_mode": validation_key,
        "point_count": point_count,
        "hf_point_count": hf_count,
        "frequency_min_hz": frequency_min,
        "frequency_max_hz": frequency_max,
        "fit_r2": fit_r2,
        "intercept_condition_met": intercept_condition,
    }

    if method_key in {"auto", "hf_intercept"} and intercept_condition and nearest_rs > 0:
        return IrExtractionResult(
            rs_ohm=nearest_rs,
            method_used="hf_intercept",
            confidence="high",
            message="高频区存在接近实轴的测量点。",
            **common,
        )

    if method_key in {"auto", "linear_fit"} and fit_is_valid and fit_candidate is not None:
        return IrExtractionResult(
            rs_ohm=fit_candidate,
            method_used="linear_fit",
            confidence="medium",
            message="由高频区线性拟合获得实轴截距。",
            **common,
        )

    hf_mean = float(np.mean(np.asarray(hf_real, dtype=float)))
    fallback_warning = "高频数据未形成可信实轴截距，Rs 仅由高频 Z' 均值估计。"
    if method_key == "hf_mean":
        return IrExtractionResult(
            rs_ohm=hf_mean if math.isfinite(hf_mean) and hf_mean > 0 else None,
            method_used="hf_mean",
            confidence="low",
            warnings=(fallback_warning,),
            message="用户明确选择了高频均值法。",
            **common,
        )

    if validation_key == "lenient" and math.isfinite(hf_mean) and hf_mean > 0:
        return IrExtractionResult(
            rs_ohm=hf_mean,
            method_used="hf_mean_fallback",
            confidence="low",
            warnings=(fallback_warning,),
            message="宽松模式已采用历史兼容的高频均值回退。",
            **common,
        )

    reason = (
        "高频截距条件不满足，严格模式拒绝自动 iR 补偿。"
        if method_key in {"auto", "hf_intercept"}
        else "高频线性拟合未达到 R²、截距范围或数据点要求，严格模式拒绝 iR 补偿。"
    )
    return _rejected_ir_result(
        method=method_key,
        validation_mode=validation_key,
        point_count=point_count,
        hf_point_count=hf_count,
        frequency_min_hz=frequency_min,
        frequency_max_hz=frequency_max,
        fit_r2=fit_r2,
        intercept_condition_met=intercept_condition,
        warnings=(fallback_warning,),
        message=reason,
    )


def normalize_ir_source(params: Mapping[str, Any] | None) -> str:
    values = params or {}
    raw = str(values.get("ir_source") or "").strip().lower()
    if raw in {"manual", "manual_rs", "rs"}:
        return IR_SOURCE_MANUAL
    if raw in {"eis", "auto", "auto_eis", "eis_auto"}:
        return IR_SOURCE_EIS
    # Compatibility with templates created before source and method were split.
    if str(values.get("ir_method") or "").strip().lower() == "manual":
        return IR_SOURCE_MANUAL
    return IR_SOURCE_EIS


def normalize_ir_search_scope(params: Mapping[str, Any] | None) -> str:
    raw = str((params or {}).get("ir_eis_search_scope") or "same_dir").strip().lower()
    aliases = {
        "same": "same_dir",
        "local": "same_dir",
        "same_folder": "same_dir",
        "root_fallback": "same_then_root",
        "recursive": "recursive_root",
        "all": "recursive_root",
        "file": "specified_file",
        "specified": "specified_file",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in IR_SEARCH_SCOPES else "same_dir"


def normalize_ir_extraction_method(params: Mapping[str, Any] | None) -> str:
    raw = str((params or {}).get("ir_method") or "auto").strip().lower()
    return raw if raw in IR_EXTRACTION_METHODS else "auto"


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def extract_lsv_sample_token(lsv_path: str) -> str:
    stem = Path(lsv_path).stem
    stem = re.sub(
        r"(?i)^(lsv|polarization|scan|lsvscan|lsvdata)[_\-\s]*",
        "",
        stem,
    )
    stem = re.sub(
        r"(?i)(?:[_\-\s]*(lsv|polarization|scan|lsvscan|lsvdata))+$",
        "",
        stem,
    ).strip("_- ")
    return _normalize_token(stem)


def _matches_named_file(filename: str, mode: str, pattern: str) -> bool:
    name = str(filename or "")
    mode_key = str(mode or "prefix").strip().lower()
    raw_pattern = str(pattern or "").strip()
    if not name or not raw_pattern:
        return False
    lower_name = name.lower()
    lower_pattern = raw_pattern.lower()
    if mode_key == "prefix":
        return lower_name.startswith(lower_pattern)
    if mode_key == "suffix":
        return (
            lower_name.endswith(lower_pattern)
            or lower_name.endswith(lower_pattern + ".txt")
            or lower_name.endswith(lower_pattern + ".csv")
        )
    if mode_key == "contains":
        return lower_pattern in lower_name
    if mode_key == "regex":
        try:
            return re.search(raw_pattern, name, flags=re.IGNORECASE) is not None
        except re.error:
            return False
    return lower_name.startswith(lower_pattern)


def _is_candidate_file(path: str, *, lsv_path: str) -> bool:
    if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(lsv_path)):
        return False
    if Path(path).suffix.lower() not in _TEXT_EXTENSIONS:
        return False
    lower_name = os.path.basename(path).lower()
    return not any(marker in lower_name for marker in _RESULT_MARKERS)


def _direct_candidates(directory: str, *, lsv_path: str) -> list[str]:
    if not os.path.isdir(directory):
        return []
    paths = [
        os.path.abspath(os.path.join(directory, name))
        for name in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, name))
    ]
    return sorted(
        (path for path in paths if _is_candidate_file(path, lsv_path=lsv_path)),
        key=lambda value: value.lower(),
    )


def _recursive_candidates(root: str, *, lsv_path: str) -> list[str]:
    candidates: list[str] = []
    if not os.path.isdir(root):
        return candidates
    for current, dirs, files in os.walk(root):
        dirs[:] = [item for item in dirs if item.lower() not in _SKIPPED_DIRS]
        for filename in files:
            path = os.path.abspath(os.path.join(current, filename))
            if _is_candidate_file(path, lsv_path=lsv_path):
                candidates.append(path)
    return sorted(candidates, key=lambda value: value.lower())


def _sample_score(path: str, sample_token: str, rule_matches: bool) -> int:
    if not sample_token:
        return 0
    stem_token = _normalize_token(Path(path).stem)
    if sample_token not in stem_token:
        return 0
    has_eis_marker = "eis" in stem_token
    if not has_eis_marker and not rule_matches:
        return 0
    if stem_token in {sample_token + "eis", "eis" + sample_token}:
        return 4
    if stem_token.endswith(sample_token + "eis") or stem_token.endswith("eis" + sample_token):
        return 3
    return 2 if has_eis_marker else 1


def _location_score(path: str, *, lsv_dir: str, input_root: str) -> int:
    parent = os.path.normcase(os.path.abspath(os.path.dirname(path)))
    if parent == os.path.normcase(os.path.abspath(lsv_dir)):
        return 3
    if parent == os.path.normcase(os.path.abspath(input_root)):
        return 2
    return 1


def _resolve_candidates(
    candidates: Sequence[str],
    *,
    lsv_path: str,
    input_root: str,
    match_mode: str,
    match_pattern: str,
) -> dict[str, Any]:
    sample_token = extract_lsv_sample_token(lsv_path)
    lsv_dir = os.path.dirname(lsv_path)
    scored: list[tuple[tuple[int, int, int, int], str]] = []
    for path in candidates:
        rule_matches = _matches_named_file(os.path.basename(path), match_mode, match_pattern)
        sample_score = _sample_score(path, sample_token, rule_matches)
        if sample_score <= 0 and not rule_matches:
            continue
        score = (
            1 if sample_score > 0 else 0,
            sample_score,
            _location_score(path, lsv_dir=lsv_dir, input_root=input_root),
            1 if rule_matches else 0,
        )
        scored.append((score, path))

    if not scored:
        return {"status": "missing", "candidates": []}

    best_score = max(score for score, _path in scored)
    best_paths = sorted(
        (path for score, path in scored if score == best_score),
        key=lambda value: value.lower(),
    )
    all_matches = sorted((path for _score, path in scored), key=lambda value: value.lower())
    if len(best_paths) > 1:
        return {
            "status": "ambiguous",
            "candidates": best_paths,
            "all_matches": all_matches,
        }
    return {
        "status": "matched",
        "eis_file": best_paths[0],
        "candidates": best_paths,
        "all_matches": all_matches,
    }


def resolve_lsv_eis_match(
    lsv_path: str,
    input_root: str | None,
    params: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Resolve the EIS source used to compensate one LSV file."""

    values = dict(params or {})
    lsv_path = os.path.abspath(lsv_path)
    root = os.path.abspath(str(input_root or values.get("input_root") or os.path.dirname(lsv_path)))
    source = normalize_ir_source(values)
    scope = normalize_ir_search_scope(values)
    match_mode = str(values.get("ir_eis_match") or values.get("eis_match") or "prefix").strip().lower()
    match_pattern = str(values.get("ir_eis_pattern") or values.get("eis_prefix") or "EIS").strip()
    base: dict[str, Any] = {
        "source": source,
        "scope": scope,
        "lsv_file": lsv_path,
        "sample_token": extract_lsv_sample_token(lsv_path),
        "match_mode": match_mode,
        "match_pattern": match_pattern,
        "extraction_method": normalize_ir_extraction_method(values),
        "validation_mode": normalize_ir_validation_mode(values),
        "formula": IR_COMPENSATION_FORMULA,
    }

    if source == IR_SOURCE_MANUAL:
        try:
            manual_rs = float(values.get("ir_manual_ohm") or 0)
        except Exception:
            manual_rs = None
        if manual_rs is None or not math.isfinite(manual_rs) or manual_rs <= 0:
            return {
                **base,
                "scope": None,
                "extraction_method": "manual",
                "status": "invalid",
                "rs_ohm": manual_rs,
                "message": "手动 Rs 必须是大于 0 的有限数值。",
                "candidates": [],
            }
        return {
            **base,
            "scope": None,
            "extraction_method": "manual",
            "status": "manual",
            "rs_ohm": manual_rs,
            "message": "使用手动 Rs，不搜索 EIS 文件。",
            "candidates": [],
        }

    if match_mode not in {"prefix", "suffix", "contains", "regex"}:
        return {
            **base,
            "status": "invalid",
            "message": f"不支持的 EIS 匹配方式: {match_mode}",
            "candidates": [],
        }
    if match_mode == "regex":
        try:
            re.compile(match_pattern)
        except re.error as exc:
            return {
                **base,
                "status": "invalid",
                "message": f"EIS 正则表达式无效: {exc}",
                "candidates": [],
            }
    if not match_pattern and scope != "specified_file":
        return {
            **base,
            "status": "invalid",
            "message": "EIS 文件匹配规则不能为空。",
            "candidates": [],
        }

    if scope == "specified_file":
        raw_path = str(values.get("ir_eis_file") or "").strip()
        if not raw_path:
            return {
                **base,
                "status": "invalid",
                "message": "请选择用于 iR 补偿的 EIS 文件。",
                "candidates": [],
            }
        target = os.path.expanduser(raw_path)
        if not os.path.isabs(target):
            target = os.path.join(root, target)
        target = os.path.abspath(target)
        if not os.path.isfile(target) or Path(target).suffix.lower() not in _TEXT_EXTENSIONS:
            return {
                **base,
                "status": "invalid",
                "message": f"指定的 EIS 文件不存在或格式不受支持: {target}",
                "candidates": [target],
            }
        if os.path.normcase(target) == os.path.normcase(lsv_path):
            return {
                **base,
                "status": "invalid",
                "message": "指定的 EIS 文件不能与 LSV 文件相同。",
                "candidates": [target],
            }
        return {
            **base,
            "status": "matched",
            "eis_file": target,
            "candidates": [target],
            "all_matches": [target],
            "message": "已使用指定 EIS 文件。",
        }

    lsv_dir = os.path.dirname(lsv_path)
    candidate_groups: list[list[str]]
    if scope == "same_dir":
        candidate_groups = [_direct_candidates(lsv_dir, lsv_path=lsv_path)]
    elif scope == "same_then_root":
        candidates = _direct_candidates(lsv_dir, lsv_path=lsv_path)
        if os.path.normcase(os.path.abspath(lsv_dir)) != os.path.normcase(root):
            candidates.extend(_direct_candidates(root, lsv_path=lsv_path))
        candidate_groups = [list(dict.fromkeys(candidates))]
    else:
        candidate_groups = [_recursive_candidates(root, lsv_path=lsv_path)]

    for candidates in candidate_groups:
        resolved = _resolve_candidates(
            candidates,
            lsv_path=lsv_path,
            input_root=root,
            match_mode=match_mode,
            match_pattern=match_pattern,
        )
        if resolved["status"] == "missing":
            continue
        if resolved["status"] == "ambiguous":
            names = ", ".join(os.path.basename(path) for path in resolved["candidates"][:5])
            return {
                **base,
                **resolved,
                "message": f"LSV 对应多个同优先级 EIS 文件，请收紧匹配规则: {names}",
            }
        return {
            **base,
            **resolved,
            "message": f"已匹配 EIS 文件: {os.path.basename(resolved['eis_file'])}",
        }

    return {
        **base,
        "status": "missing",
        "message": f"未找到与 {os.path.basename(lsv_path)} 对应的 EIS 文件。",
        "candidates": [],
    }


def build_lsv_ir_preflight(
    input_root: str,
    lsv_files: Sequence[str],
    params: Mapping[str, Any] | None,
) -> dict[str, Any]:
    values = dict(params or {})
    source = normalize_ir_source(values)
    scope = None if source == IR_SOURCE_MANUAL else normalize_ir_search_scope(values)
    items = [resolve_lsv_eis_match(path, input_root, values) for path in lsv_files]
    status_counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    ok_statuses = {"matched", "manual"}
    warnings = [
        str(item.get("message") or "iR 补偿配置需要检查")
        for item in items
        if item.get("status") not in ok_statuses
    ]
    return {
        "enabled": True,
        "source": source,
        "scope": scope,
        "validation_mode": normalize_ir_validation_mode(values),
        "formula": IR_COMPENSATION_FORMULA,
        "ok": bool(items) and not warnings,
        "matched": sum(1 for item in items if item.get("status") in ok_statuses),
        "total": len(items),
        "status_counts": status_counts,
        "items": items,
        "warnings": warnings,
    }


__all__ = [
    "IR_COMPENSATION_FORMULA",
    "IR_EXTRACTION_METHODS",
    "IR_VALIDATION_MODES",
    "IR_SEARCH_SCOPES",
    "IR_SOURCE_EIS",
    "IR_SOURCE_MANUAL",
    "IrExtractionResult",
    "build_lsv_ir_preflight",
    "extract_rs_from_eis",
    "extract_lsv_sample_token",
    "normalize_ir_extraction_method",
    "normalize_ir_search_scope",
    "normalize_ir_source",
    "normalize_ir_validation_mode",
    "resolve_lsv_eis_match",
]
