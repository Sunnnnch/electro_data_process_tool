"""Centralised path validation helpers to prevent directory traversal attacks."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, Sequence

# Default allowed extensions for data files
_DATA_FILE_EXTENSIONS = frozenset({".txt", ".csv", ".xlsx", ".xls", ".json", ".zip"})

# Default allowed image extensions
_IMAGE_FILE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp"})


def sanitize_filename(name: str) -> str:
    """Convert arbitrary user-provided name to a filesystem-safe base name.

    Strips directory separators and traversal sequences, then restricts to
    alphanumeric, underscore, hyphen, and dot characters.

    Returns ``"unknown"`` for empty inputs.
    """
    if not name:
        return "unknown"
    # Take only the basename to strip any directory components
    base = os.path.basename(name)
    # Remove anything that isn't safe
    safe = re.sub(r"[^A-Za-z0-9_.\-]+", "_", base)
    # Prevent hidden files or bare dots
    safe = safe.lstrip(".")
    return safe or "unknown"


def validate_path_within(
    user_path: str,
    allowed_root: str | Path,
    *,
    must_exist: bool = True,
    allowed_extensions: Optional[Sequence[str]] = None,
) -> Path:
    """Resolve *user_path* and ensure it stays under *allowed_root*.

    Raises :class:`ValueError` when the path escapes the allowed root, has a
    disallowed extension, or (when *must_exist* is True) does not exist.
    """
    root = Path(allowed_root).resolve()
    try:
        resolved = Path(user_path).resolve()
    except (OSError, ValueError) as exc:
        raise ValueError(f"路径无法解析: {user_path}") from exc

    # Ensure the resolved path is under the allowed root
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(f"路径不在允许范围内: {user_path}")

    if must_exist and not resolved.exists():
        raise ValueError(f"路径不存在: {user_path}")

    if allowed_extensions is not None:
        ext = resolved.suffix.lower()
        if ext not in allowed_extensions:
            raise ValueError(f"不允许的文件类型: {ext}")

    return resolved


def is_safe_data_path(user_path: str, allowed_root: str | Path) -> bool:
    """Return True when *user_path* is inside *allowed_root* and looks like a data file."""
    try:
        validate_path_within(user_path, allowed_root, must_exist=True, allowed_extensions=_DATA_FILE_EXTENSIONS)
        return True
    except ValueError:
        return False


def is_safe_image_path(image_path: str, allowed_root: str | Path) -> bool:
    """Return True when *image_path* is inside *allowed_root* and is an image."""
    try:
        validate_path_within(image_path, allowed_root, must_exist=True, allowed_extensions=_IMAGE_FILE_EXTENSIONS)
        return True
    except ValueError:
        return False
