"""System-level utilities for v6 (desktop-only helpers)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Any, Dict, Optional, Set

# ── dynamic runtime whitelist for open-path operations ──────────────
_runtime_allowed_dirs_lock = threading.Lock()
_runtime_allowed_dirs: Set[str] = set()


def register_allowed_dir(directory: str) -> None:
    """Register a directory as allowed for open-path operations.

    Called after successful data processing so that the output folder
    can be opened / revealed by the user from the UI.
    """
    resolved = os.path.realpath(directory)
    if os.path.isdir(resolved):
        with _runtime_allowed_dirs_lock:
            _runtime_allowed_dirs.add(resolved)


def select_folder_dialog(initial_dir: Optional[str] = None) -> Dict[str, Any]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        return {"status": "error", "message": f"当前环境不支持文件夹对话框: {exc}"}

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        default_dir = initial_dir if initial_dir and os.path.isdir(initial_dir) else os.getcwd()
        selected = filedialog.askdirectory(initialdir=default_dir, title="选择数据文件夹")
        if not selected:
            return {"status": "error", "message": "未选择文件夹"}
        return {"status": "success", "folder_path": selected}
    except Exception as exc:
        return {"status": "error", "message": f"打开文件夹选择器失败: {exc}"}
    finally:
        try:
            if root is not None:
                root.destroy()
        except Exception:
            pass


def _is_within_allowed_roots(path: str) -> bool:
    """Check that *path* is under a known data directory or a runtime-registered directory."""
    from electrochem_v6.config import project_default_dir, user_config_dir

    resolved = os.path.realpath(path)
    allowed_roots = [
        os.path.realpath(str(user_config_dir())),
        os.path.realpath(str(project_default_dir())),
        os.path.realpath(os.path.join(str(project_default_dir()), "user_data")),
        os.path.realpath(os.path.join(str(project_default_dir()), "reports")),
        os.path.realpath(os.path.join(str(project_default_dir()), "project_reports")),
    ]
    # Include directories registered at runtime (from processing results)
    with _runtime_allowed_dirs_lock:
        allowed_roots.extend(_runtime_allowed_dirs)
    return any(resolved == root or resolved.startswith(root + os.sep) for root in allowed_roots)


def _is_path_in_history_outputs(path: str) -> bool:
    """Check if *path* belongs to a directory that contains known output files from processing history."""
    try:
        from electrochem_v6.store.legacy_runtime import _USE_SQLITE
        resolved = os.path.realpath(path)

        if _USE_SQLITE:
            from electrochem_v6.store.legacy_runtime import _get_db
            db = _get_db()
            known_dirs = set(db.get_history_output_dirs())
        else:
            from electrochem_v6.store.legacy_runtime import get_history_manager_v6
            hist_mgr = get_history_manager_v6()
            records = hist_mgr.get_all_records()
            known_dirs: set[str] = set()
            for record in records:
                if not isinstance(record, dict):
                    continue
                for output_file in (record.get("output_files") or []):
                    output_path = str(output_file).strip()
                    if output_path:
                        known_dirs.add(os.path.realpath(os.path.dirname(output_path)))
                folder = str(record.get("folder_path") or "").strip()
                if folder:
                    known_dirs.add(os.path.realpath(folder))

        # Register them for future fast lookups
        for d in known_dirs:
            if os.path.isdir(d):
                register_allowed_dir(d)
        return any(resolved == d or resolved.startswith(d + os.sep) for d in known_dirs)
    except Exception:
        return False


def open_path_target(path_value: Optional[str] = None, reveal_only: bool = False) -> Dict[str, Any]:
    target = str(path_value or "").strip()
    if not target:
        return {"status": "error", "message": "path is required"}
    normalized = os.path.abspath(target)
    if not _is_within_allowed_roots(normalized) and not _is_path_in_history_outputs(normalized):
        return {"status": "error", "message": "path is outside allowed directories"}
    if reveal_only:
        open_target = normalized if os.path.isdir(normalized) else os.path.dirname(normalized)
    else:
        open_target = normalized
    if not open_target or not os.path.exists(open_target):
        return {"status": "error", "message": "path not found"}
    try:
        if os.name == "nt":
            os.startfile(open_target)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", open_target])
        else:
            subprocess.Popen(["xdg-open", open_target])
        return {"status": "success", "path": normalized, "opened": open_target}
    except Exception as exc:
        return {"status": "error", "message": f"open path failed: {exc}"}
