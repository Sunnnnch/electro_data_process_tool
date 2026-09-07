"""Data scanning, preview and analysis tools for AI agent.

These tools allow the AI to autonomously explore data folders,
preview file contents, and analyze data characteristics.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict


def _is_agent_path_allowed(path: str) -> bool:
    """Check that *path* is within directories the user can reasonably access.

    Reuses the same rules as the HTTP processing endpoint so that the agent
    can access any path the user themselves could submit via the UI, but
    cannot be tricked (e.g. via prompt-injection) into reading sensitive
    system files like ~/.ssh/id_rsa.
    """
    from electrochem_v6.core.process_service import _is_allowed_process_dir
    resolved = os.path.realpath(path)
    # For files, check the parent directory
    check_dir = resolved if os.path.isdir(resolved) else os.path.dirname(resolved)
    return _is_allowed_process_dir(check_dir)


__all__ = [
    "tool_scan_data_folder",
    "tool_preview_data_file",
    "tool_analyze_data_characteristics",
]

_logger = logging.getLogger(__name__)


def tool_scan_data_folder(folder_path: str) -> Dict:
    """扫描数据文件夹，返回文件列表和统计信息。"""
    try:
        resolved = os.path.realpath(folder_path)
        if not os.path.isdir(resolved):
            return {"success": False, "error": f"文件夹不存在: {folder_path}"}
        if not _is_agent_path_allowed(resolved):
            return {"success": False, "error": "路径不在允许范围内"}
        folder_path = resolved

        files_info = []

        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if file.endswith((".txt", ".csv")):
                    file_path = os.path.join(root, file)

                    file_upper = file.upper()
                    if "LSV" in file_upper or "TAFEL" in file_upper:
                        detected_type = "LSV"
                    elif "CV" in file_upper:
                        detected_type = "CV"
                    elif "EIS" in file_upper:
                        detected_type = "EIS"
                    elif "ECSA" in file_upper:
                        detected_type = "ECSA"
                    else:
                        detected_type = "Unknown"

                    files_info.append(
                        {
                            "file_name": file,
                            "file_path": file_path,
                            "detected_type": detected_type,
                            "folder": os.path.basename(root),
                            "size_kb": round(os.path.getsize(file_path) / 1024, 2),
                        }
                    )

        by_type: Dict[str, int] = {}
        for f in files_info:
            ftype = f["detected_type"]
            by_type[ftype] = by_type.get(ftype, 0) + 1

        MAX_RETURNED_FILES = 30

        return {
            "success": True,
            "folder_path": folder_path,
            "total_files": len(files_info),
            "files": files_info[:MAX_RETURNED_FILES],
            "statistics": {
                "total": len(files_info),
                "by_type": by_type,
                "folders": len(set(f["folder"] for f in files_info)),
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_preview_data_file(file_path: str, lines: int = 20) -> Dict:
    """预览数据文件前 N 行。"""
    try:
        resolved = os.path.realpath(file_path)
        ext = os.path.splitext(resolved)[1].lower()
        if ext not in (".txt", ".csv", ".xlsx", ".xls", ".json"):
            return {"success": False, "error": f"不支持的文件类型: {ext}"}
        file_path = resolved
        if not os.path.exists(file_path):
            return {"success": False, "error": f"文件不存在: {file_path}"}
        if not _is_agent_path_allowed(file_path):
            return {"success": False, "error": "路径不在允许范围内"}

        encodings = ["utf-8", "gbk", "gb2312", "latin-1"]
        preview_lines = None

        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    preview_lines = [f.readline().strip() for _ in range(lines)]
                break
            except Exception:
                continue

        if preview_lines is None:
            return {"success": False, "error": "无法读取文件(编码问题)"}

        content_str = "\n".join(preview_lines)
        has_potential = "potential" in content_str.lower()
        has_current = "current" in content_str.lower()
        has_freq = "freq" in content_str.lower()

        if has_freq:
            detected_type = "EIS"
        elif has_potential and has_current:
            detected_type = "LSV/CV"
        else:
            detected_type = "Unknown"

        return {
            "success": True,
            "file_path": file_path,
            "preview_lines": preview_lines,
            "detected_type": detected_type,
            "has_header": has_potential or has_current,
            "line_count_preview": len(preview_lines),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_analyze_data_characteristics(file_path: str, data_type: str, params: Dict[str, Any] | None = None, run_id: str | None = None) -> Dict:
    """Analyze complete inputs under explicitly supplied or recorded scientific settings."""
    try:
        resolved = os.path.realpath(file_path)
        if not _is_agent_path_allowed(resolved):
            return {"success": False, "error": "路径不在允许范围内"}
        if not os.path.isfile(resolved):
            return {"success": False, "error": f"文件不存在: {file_path}"}
        if os.path.splitext(resolved)[1].lower() not in {".txt", ".csv"}:
            return {"success": False, "error": "特征分析仅支持正式解析器可读取的 TXT/CSV 文件"}
        if params is not None and not isinstance(params, dict):
            return {"success": False, "error": "params 必须是对象"}
        if str(data_type).upper() != "LSV":
            return {"success": True, "schema_version": "1.0", "file_path": resolved, "data_type": data_type,
                    "recommendation_status": "not_supported", "characteristics": {}, "candidate_tafel_ranges": [],
                    "missing_parameters": [], "limitations": ["目前候选参数分析仅支持 LSV；其他类型请使用正式处理预检，不能套用 LSV 建议。"]}
        from electrochem_v6.core.agent_scientific import analyze_lsv_source
        return analyze_lsv_source(resolved, params, run_id)
    except Exception as exc:
        return {"success": False, "error": str(exc), "candidate_tafel_ranges": []}
