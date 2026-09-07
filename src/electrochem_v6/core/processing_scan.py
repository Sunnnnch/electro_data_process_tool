"""Input discovery, filename matching, and data-start detection."""

from __future__ import annotations

import os
import re
from itertools import islice
from typing import Any, Mapping, Sequence

from electrochem_v6.core.processing_lsv_ir import build_lsv_ir_preflight
from electrochem_v6.core.processing_registry import (
    FILE_MATCH_MODULE_SPECS,
    enabled_by_gui_vars,
    get_match_config,
)
from electrochem_v6.core.processing_source_profile import split_table_row
from electrochem_v6.core.utils import as_bool, iter_file_with_fallback_encodings


def natural_sort_key(value: Any) -> list[Any]:
    """Return a key that sorts embedded numbers numerically."""

    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", str(value))
    ]


def matches_named_file(filename: str, mode: str, pattern: str) -> bool:
    """Return whether a filename matches a configured strategy."""

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


def _detect_delimiter(lines: Sequence[str], max_probe: int = 50) -> str | None:
    candidates = {"\t": 0, ",": 0, ";": 0}
    comment_prefixes = ("#", "//", "%", "'", "!", ":")
    probed = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(comment_prefixes):
            continue
        for separator in candidates:
            if separator in line:
                candidates[separator] += 1
        probed += 1
        if probed >= max_probe:
            break
    if not probed:
        return None
    best_separator, best_count = max(candidates.items(), key=lambda item: item[1])
    return best_separator if best_count >= probed * 0.4 else None


def _split_line(line: str, delimiter: str | None) -> list[str]:
    return split_table_row(line, delimiter)


def auto_detect_data_start(file_path: str, encodings: Sequence[str] | None = None) -> int:
    """Detect the first numeric data line and return its one-based index."""

    supported_encodings = encodings or ("utf-8", "utf-8-sig", "gbk", "latin-1")
    lines = list(
        islice(
            iter_file_with_fallback_encodings(file_path, encodings=supported_encodings),
            10000,
        )
    )
    if not lines:
        return 1
    if lines[0].startswith("\ufeff"):
        lines[0] = lines[0][1:]

    delimiter = _detect_delimiter(lines)
    comment_prefixes = ("#", "//", "%", "'", "!", ":")
    consecutive = 0
    for index, raw in enumerate(lines):
        line = raw.strip()
        if not line or line.startswith(comment_prefixes):
            consecutive = 0
            continue
        parts = _split_line(line, delimiter)
        if len(parts) < 2:
            consecutive = 0
            continue
        try:
            float(parts[0])
            float(parts[1])
        except ValueError:
            consecutive = 0
            continue
        consecutive += 1
        if consecutive >= 3:
            return max(1, index - consecutive + 2)
    return 1


def resolve_data_start_line(file_path: str, params: dict[str, Any] | None = None) -> int:
    """Resolve the input start line; currently always uses auto-detection."""

    del params
    return auto_detect_data_start(file_path)


def _is_result_file(filename: str) -> bool:
    lower_name = filename.lower()
    patterns = (
        "_results.csv",
        "results.csv",
        "_combined_",
        "combined_",
        "_quality_report",
        "quality_report",
        "_summary",
        "_lsv.png",
        "_lsv_ir_compensated.png",
        "_cv.png",
        "_eis_nyquist.png",
        "_eis_bode.png",
        "_ecsa.png",
        "_tafel_fit.png",
        "_tafel_fit_ir.png",
    )
    return any(pattern in lower_name for pattern in patterns)


def _is_skipped_scan_dir(dirname: str) -> bool:
    return str(dirname or "").strip().lower() in {
        ".git",
        "__pycache__",
        ".pytest_cache",
        "electrochem_outputs",
        "user_data",
    }


def build_work_units(folder_path: str, *, recursive: bool = False) -> list[tuple[str, list[str]]]:
    """Build deterministic directory/file work units for scanning and legacy runs."""

    root_path = os.path.abspath(folder_path)
    work_units: list[tuple[str, list[str]]] = []
    if recursive:
        for root, dirs, files in os.walk(root_path):
            dirs[:] = [item for item in dirs if not _is_skipped_scan_dir(item)]
            existing = [item for item in files if os.path.isfile(os.path.join(root, item))]
            existing.sort(key=natural_sort_key)
            work_units.append((root, existing))
        return work_units

    entries = os.listdir(root_path)
    directories = [
        item
        for item in entries
        if os.path.isdir(os.path.join(root_path, item)) and not _is_skipped_scan_dir(item)
    ]
    directories.sort(key=natural_sort_key)
    root_files = [item for item in entries if os.path.isfile(os.path.join(root_path, item))]
    root_files.sort(key=natural_sort_key)
    work_units.append((root_path, root_files))
    for directory in directories:
        subfolder = os.path.join(root_path, directory)
        files = [
            item
            for item in os.listdir(subfolder)
            if os.path.isfile(os.path.join(subfolder, item))
        ]
        files.sort(key=natural_sort_key)
        work_units.append((subfolder, files))
    return work_units


def processable_files(
    files: Sequence[str],
    *,
    preview_mode: bool = False,
    preview_limit: int = 2,
) -> list[str]:
    """Remove generated result files and optionally limit preview inputs."""

    file_list = list(files)
    if preview_mode:
        file_list = [
            item for item in file_list if item.lower().endswith((".txt", ".csv"))
        ][:preview_limit]
    return [item for item in file_list if not _is_result_file(item)]


def scan_process_inputs(
    folder_path: str,
    gui_vars: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Scan a processing folder and summarize matches for enabled modules."""

    params = dict(gui_vars or {})
    root_path = os.path.abspath(folder_path)
    recursive = as_bool(params.get("recursive_scan", False), False)
    preview_mode = as_bool(params.get("preview_mode", False), False)
    try:
        preview_limit = max(1, int(params.get("preview_limit", 2) or 2))
    except (TypeError, ValueError):
        preview_limit = 2

    work_units = build_work_units(root_path, recursive=recursive)
    selected = enabled_by_gui_vars(params, matchable_only=True)
    match_config = {
        spec.key: get_match_config(params, spec)
        for spec in FILE_MATCH_MODULE_SPECS
    }
    by_type: dict[str, dict[str, Any]] = {
        data_type: {
            "matched": 0,
            "examples": [],
            "files": [],
            "match": match_config[data_type][0],
            "pattern": match_config[data_type][1],
        }
        for data_type in selected
    }
    workunit_items: list[dict[str, Any]] = []
    total_text_files = 0
    all_files: list[str] = []

    for subfolder, files in work_units:
        candidates = processable_files(
            files,
            preview_mode=preview_mode,
            preview_limit=preview_limit,
        )
        text_files = [
            item for item in candidates if item.lower().endswith((".txt", ".csv"))
        ]
        total_text_files += len(text_files)
        all_files.extend(os.path.join(subfolder, filename) for filename in text_files)
        unit_counts = {data_type: 0 for data_type in selected}
        for filename in text_files:
            for data_type, enabled in selected.items():
                if not enabled:
                    continue
                mode, pattern = match_config[data_type]
                if not matches_named_file(filename, mode, pattern):
                    continue
                unit_counts[data_type] += 1
                info = by_type[data_type]
                info["matched"] += 1
                full_path = os.path.join(subfolder, filename)
                info["files"].append(full_path)
                if len(info["examples"]) < 5:
                    info["examples"].append(full_path)
        workunit_items.append(
            {
                "folder": subfolder,
                "text_files": len(text_files),
                "matched": {key: value for key, value in unit_counts.items() if value},
            }
        )

    selected_total = sum(
        int(info["matched"])
        for data_type, info in by_type.items()
        if selected.get(data_type)
    )
    warnings = [
        f"{data_type} 未匹配到文件"
        for data_type, enabled in selected.items()
        if enabled and int(by_type[data_type]["matched"]) == 0
    ]
    result: dict[str, Any] = {
        "folder_path": root_path,
        "recursive": recursive,
        "work_units": len(work_units),
        "text_files": total_text_files,
        "selected_matched": selected_total,
        "all_files": all_files,
        "by_type": by_type,
        "workunit_items": workunit_items[:100],
        "warnings": warnings,
    }
    if selected.get("LSV") and as_bool(params.get("ir_compensation_enabled", False), False):
        ir_preflight = build_lsv_ir_preflight(
            root_path,
            by_type.get("LSV", {}).get("files", []),
            params,
        )
        result["ir_compensation"] = ir_preflight
        result["warnings"].extend(ir_preflight.get("warnings", []))
    return result


def scan_selected_inputs(
    folder_path: str,
    files_by_type: Mapping[str, Sequence[str]],
    gui_vars: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a preflight scan from an explicit, already selected file set.

    Unlike :func:`scan_process_inputs`, this function never discovers extra
    files from the surrounding directories.  Preflight and execution can
    therefore operate on the exact same input list.
    """

    params = dict(gui_vars or {})
    root_path = os.path.abspath(folder_path)
    normalized: dict[str, list[str]] = {}
    all_files: list[str] = []
    seen_all: set[str] = set()
    for raw_type, values in (files_by_type or {}).items():
        data_type = str(raw_type or "").strip().upper()
        if not data_type:
            continue
        normalized[data_type] = []
        seen_type: set[str] = set()
        for raw_path in values or ():
            file_path = os.path.abspath(str(raw_path))
            key = os.path.normcase(os.path.realpath(file_path))
            if key in seen_type:
                continue
            seen_type.add(key)
            normalized[data_type].append(file_path)
            if key not in seen_all:
                seen_all.add(key)
                all_files.append(file_path)

    by_type: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for data_type, files in normalized.items():
        by_type[data_type] = {
            "enabled": True,
            "matched": len(files),
            "examples": files[:5],
            "files": files,
            "match": "explicit",
            "pattern": "user_selection",
        }
        if not files:
            warnings.append(f"{data_type} 未选择文件")

    grouped: dict[str, dict[str, int]] = {}
    for data_type, files in normalized.items():
        for file_path in files:
            parent = os.path.dirname(file_path)
            grouped.setdefault(parent, {})
            grouped[parent][data_type] = grouped[parent].get(data_type, 0) + 1
    workunit_items = [
        {
            "folder": parent,
            "text_files": sum(counts.values()),
            "matched": counts,
        }
        for parent, counts in sorted(grouped.items(), key=lambda item: natural_sort_key(item[0]))
    ]
    result: dict[str, Any] = {
        "folder_path": root_path,
        "recursive": False,
        "selection_mode": "explicit",
        "work_units": len(workunit_items),
        "text_files": len(all_files),
        "selected_matched": sum(len(files) for files in normalized.values()),
        "all_files": all_files,
        "by_type": by_type,
        "workunit_items": workunit_items[:100],
        "warnings": warnings,
    }
    lsv_files = normalized.get("LSV", [])
    if lsv_files and as_bool(params.get("ir_compensation_enabled", False), False):
        ir_preflight = build_lsv_ir_preflight(root_path, lsv_files, params)
        result["ir_compensation"] = ir_preflight
        result["warnings"].extend(ir_preflight.get("warnings", []))
    return result


__all__ = [
    "auto_detect_data_start",
    "build_work_units",
    "matches_named_file",
    "natural_sort_key",
    "processable_files",
    "resolve_data_start_line",
    "scan_process_inputs",
    "scan_selected_inputs",
]
