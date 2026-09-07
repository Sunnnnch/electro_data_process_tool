"""System-level utilities for v6 (desktop-only helpers)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Set

__all__ = [
    "register_allowed_dir",
    "select_file_dialog",
    "select_files_dialog",
    "select_folder_dialog",
    "open_path_target",
]

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
        # User explicitly chose this folder via dialog → register as allowed
        register_allowed_dir(selected)
        return {"status": "success", "folder_path": selected}
    except Exception as exc:
        return {"status": "error", "message": f"打开文件夹选择器失败: {exc}"}
    finally:
        try:
            if root is not None:
                root.destroy()
        except Exception:
            pass


def select_file_dialog(
    initial_path: Optional[str] = None,
    extensions: Optional[list[str]] = None,
) -> Dict[str, Any]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        return {"status": "error", "message": f"当前环境不支持文件选择对话框: {exc}"}

    normalized_extensions = []
    for item in extensions or [".txt", ".csv"]:
        suffix = str(item or "").strip().lower()
        if suffix and not suffix.startswith("."):
            suffix = "." + suffix
        if suffix and suffix not in normalized_extensions:
            normalized_extensions.append(suffix)
    if not normalized_extensions:
        normalized_extensions = [".txt", ".csv"]

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        initial = os.path.abspath(os.path.expanduser(str(initial_path or os.getcwd())))
        default_dir = initial if os.path.isdir(initial) else os.path.dirname(initial)
        if not os.path.isdir(default_dir):
            default_dir = os.getcwd()
        patterns = " ".join(f"*{suffix}" for suffix in normalized_extensions)
        selected = filedialog.askopenfilename(
            initialdir=default_dir,
            title="选择 EIS 数据文件",
            filetypes=[("EIS data", patterns), ("All files", "*.*")],
        )
        if not selected:
            return {"status": "error", "message": "未选择文件"}
        selected = os.path.abspath(selected)
        if Path(selected).suffix.lower() not in set(normalized_extensions):
            return {"status": "error", "message": "所选文件格式不受支持"}
        register_allowed_dir(os.path.dirname(selected))
        return {"status": "success", "file_path": selected}
    except Exception as exc:
        return {"status": "error", "message": f"打开文件选择器失败: {exc}"}
    finally:
        try:
            if root is not None:
                root.destroy()
        except Exception:
            pass


def select_files_dialog(
    initial_path: Optional[str] = None,
    extensions: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """Open the native picker for one or more primary data files."""

    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        return {"status": "error", "message": f"当前环境不支持文件选择对话框: {exc}"}

    normalized_extensions: list[str] = []
    for item in extensions or [".txt", ".csv"]:
        suffix = str(item or "").strip().lower()
        if suffix and not suffix.startswith("."):
            suffix = "." + suffix
        if suffix and suffix not in normalized_extensions:
            normalized_extensions.append(suffix)
    if not normalized_extensions:
        normalized_extensions = [".txt", ".csv"]

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        initial = os.path.abspath(os.path.expanduser(str(initial_path or os.getcwd())))
        default_dir = initial if os.path.isdir(initial) else os.path.dirname(initial)
        if not os.path.isdir(default_dir):
            default_dir = os.getcwd()
        patterns = " ".join(f"*{suffix}" for suffix in normalized_extensions)
        selected_items = filedialog.askopenfilenames(
            initialdir=default_dir,
            title="选择电化学数据文件（可多选）",
            filetypes=[("Electrochemical data", patterns), ("All files", "*.*")],
        )
        if not selected_items:
            return {"status": "error", "message": "未选择文件"}

        allowed_suffixes = set(normalized_extensions)
        selected_paths: list[str] = []
        seen: set[str] = set()
        for raw_path in selected_items:
            selected = os.path.abspath(str(raw_path))
            if Path(selected).suffix.lower() not in allowed_suffixes:
                return {
                    "status": "error",
                    "message": f"所选文件格式不受支持: {os.path.basename(selected)}",
                }
            key = os.path.normcase(os.path.realpath(selected))
            if key in seen:
                continue
            seen.add(key)
            selected_paths.append(selected)
            register_allowed_dir(os.path.dirname(selected))
        return {
            "status": "success",
            "file_paths": selected_paths,
            "count": len(selected_paths),
        }
    except Exception as exc:
        return {"status": "error", "message": f"打开文件选择器失败: {exc}"}
    finally:
        try:
            if root is not None:
                root.destroy()
        except Exception:
            pass


def _is_within_allowed_roots(path: str) -> bool:
    """Check that *path* is under a known data directory or a runtime-registered directory."""
    from electrochem_v6.config import project_default_dir, user_config_dir

    resolved = os.path.normcase(os.path.realpath(path))
    allowed_roots = [
        os.path.normcase(os.path.realpath(str(user_config_dir()))),
        os.path.normcase(os.path.realpath(str(project_default_dir()))),
        os.path.normcase(os.path.realpath(os.path.join(str(project_default_dir()), "user_data"))),
        os.path.normcase(os.path.realpath(os.path.join(str(project_default_dir()), "reports"))),
        os.path.normcase(os.path.realpath(os.path.join(str(project_default_dir()), "project_reports"))),
    ]
    # Include directories registered at runtime (from processing results)
    with _runtime_allowed_dirs_lock:
        allowed_roots.extend(os.path.normcase(d) for d in _runtime_allowed_dirs)
    return any(resolved == root or resolved.startswith(root + os.sep) for root in allowed_roots)


def _is_path_in_history_outputs(path: str) -> bool:
    """Check if *path* belongs to a directory that contains known output files from processing history."""
    try:
        from electrochem_v6.store.runtime import get_database

        resolved = os.path.realpath(path)
        known_dirs = set(get_database().get_history_output_dirs())

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
