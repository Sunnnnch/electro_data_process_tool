"""Safe accounting and cleanup for application-owned run artifacts."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Iterable

from electrochem_v6.config import user_config_dir
from electrochem_v6.core.artifact_lifecycle import artifact_storage_operation, upload_root_is_active
from electrochem_v6.store.runtime import get_database


def managed_runs_root() -> Path:
    return (user_config_dir() / "runs").resolve()


def _managed_path(value: Any) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw).expanduser().resolve()
        root = managed_runs_root()
        if path == root or os.path.commonpath([str(path), str(root)]) != str(root):
            return None
        return path
    except (OSError, RuntimeError, ValueError):
        return None


def _tree_size(path: Path) -> int:
    if path.is_file():
        try:
            return max(0, int(path.stat().st_size))
        except OSError:
            return 0
    total = 0
    for current, _dirs, files in os.walk(path, followlinks=False):
        for filename in files:
            try:
                candidate = Path(current) / filename
                if not candidate.is_symlink():
                    total += max(0, int(candidate.stat().st_size))
            except OSError:
                continue
    return total


def remove_managed_artifact_roots(roots: Iterable[str]) -> dict[str, Any]:
    with artifact_storage_operation():
        return _remove_managed_artifact_roots(roots)


def _remove_managed_artifact_roots(roots: Iterable[str]) -> dict[str, Any]:
    removed: list[str] = []
    skipped: list[str] = []
    bytes_reclaimed = 0
    database = get_database()
    for raw in dict.fromkeys(str(item) for item in roots if str(item).strip()):
        path = _managed_path(raw)
        if (
            path is None
            or upload_root_is_active(path)
            or database.count_artifact_root_references(str(path)) > 0
        ):
            skipped.append(raw)
            continue
        if not path.exists():
            continue
        size = _tree_size(path)
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError:
            skipped.append(str(path))
            continue
        removed.append(str(path))
        bytes_reclaimed += size
    return {
        "removed": removed,
        "skipped": skipped,
        "bytes_reclaimed": bytes_reclaimed,
    }


def storage_summary() -> dict[str, Any]:
    with artifact_storage_operation():
        return _storage_summary()


def _storage_summary() -> dict[str, Any]:
    database = get_database()
    referenced = {
        path
        for raw in database.get_managed_artifact_roots()
        if (path := _managed_path(raw)) is not None
    }
    referenced_existing = {path for path in referenced if path.exists()}
    candidates = set()
    for category in ("uploads", "replay_sources"):
        category_root = managed_runs_root() / category
        if category_root.is_dir():
            candidates.update(path.resolve() for path in category_root.iterdir() if path.is_dir())
    active = {path for path in candidates if upload_root_is_active(path)}
    orphaned = candidates - referenced - active
    return {
        "status": "success",
        "managed_root": str(managed_runs_root()),
        "referenced_runs": len(referenced_existing),
        "referenced_bytes": sum(_tree_size(path) for path in referenced_existing),
        "active_runs": len(active),
        "orphaned_runs": len(orphaned),
        "orphaned_bytes": sum(_tree_size(path) for path in orphaned),
        "orphaned_paths": sorted(str(path) for path in orphaned),
    }


def cleanup_orphaned_runs() -> dict[str, Any]:
    summary = storage_summary()
    cleanup = remove_managed_artifact_roots(summary.get("orphaned_paths") or [])
    return {"status": "success", **cleanup, "summary": storage_summary()}


__all__ = [
    "cleanup_orphaned_runs",
    "managed_runs_root",
    "remove_managed_artifact_roots",
    "storage_summary",
]
