"""System-level utilities for v6 (desktop-only helpers)."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Dict, Optional


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


def open_path_target(path_value: Optional[str] = None, reveal_only: bool = False) -> Dict[str, Any]:
    target = str(path_value or "").strip()
    if not target:
        return {"status": "error", "message": "path is required"}
    normalized = os.path.abspath(target)
    if reveal_only:
        open_target = normalized if os.path.isdir(normalized) else os.path.dirname(normalized)
    else:
        open_target = normalized
    if not open_target or not os.path.exists(open_target):
        return {"status": "error", "message": f"path not found: {normalized}"}
    try:
        if os.name == "nt":
            os.startfile(open_target)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", open_target])
        else:
            subprocess.Popen(["xdg-open", open_target])
        return {"status": "success", "path": normalized, "opened": open_target}
    except Exception as exc:
        return {"status": "error", "message": f"open path failed: {exc}", "path": normalized}
