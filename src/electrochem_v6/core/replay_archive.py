"""Restore missing upload inputs from a verified archive without changing old outputs."""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from electrochem_v6.config import user_config_dir
from electrochem_v6.core.artifact_lifecycle import artifact_storage_operation
from electrochem_v6.core.processing_manifest import _file_identity


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _member_path(root: Path, member: Any) -> Path:
    name = str(member or "")
    relative = PurePosixPath(name)
    if not name or "\\" in name or ":" in name or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("历史 ZIP 输入映射包含非法路径")
    target = root.joinpath(*relative.parts).resolve()
    if not target.is_relative_to(root.resolve()) or target == root.resolve():
        raise ValueError("历史 ZIP 输入映射超出恢复目录")
    return target


def _limit(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _verify_members(root: Path, inputs: list[dict[str, Any]]) -> dict[str, str]:
    mapped = {}
    for item in inputs:
        path = _member_path(root, item["archive_member"])
        expected = item.get("sha256")
        if not expected or _file_identity(str(path)).get("sha256") != expected:
            raise ValueError(f"ZIP 恢复文件与历史指纹不符: {item.get('file_name') or item['archive_member']}")
        mapped[str(item["path"])] = str(path)
    return mapped


def restore_uploaded_sources(
    recipe: dict[str, Any], inputs: list[dict[str, Any]], *, relocations: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return automatic relocations only for missing archive inputs not relocated by the user.

    The application-owned content-addressed cache preserves archive-relative paths
    (including product tables' signal references). Every use rechecks input hashes.
    Cleanup and archive reads share the upload storage lock. Partial extractions are
    never published. Existing input files and historical output files are untouched.
    """
    result: dict[str, Any] = {"source_paths": {}, "folder_path": None, "warnings": []}
    explicit = {_path_key(path) for path in (relocations or {}) if isinstance(path, str)}
    missing = [item for item in inputs if item.get("archive_member")
               and _path_key(item["path"]) not in explicit and not Path(item["path"]).is_file()]
    if not missing or not recipe.get("source_archive_path"):
        return result
    digest = str(recipe.get("source_archive_sha256") or "")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("原 ZIP 缺少有效指纹，无法自动恢复；请重新定位原始文件")

    from electrochem_v6.core.process_service import _is_allowed_process_dir
    from electrochem_v6.server.request_utils import extract_zip_safely

    archive = Path(recipe["source_archive_path"]).resolve()
    if not _is_allowed_process_dir(str(archive.parent)):
        raise ValueError("原 ZIP 路径不在已允许范围内，请重新选择原始文件")
    cache_parent = (user_config_dir() / "runs" / "replay_sources").resolve()
    cache = cache_parent / digest
    data = cache / "data"
    with artifact_storage_operation():
        if not data.resolve().is_relative_to(cache_parent):
            raise ValueError("ZIP 恢复缓存路径超出应用目录")
        # A complete verified cache remains usable even if the original ZIP was removed.
        if data.is_dir():
            mapping = _verify_members(data, missing)
        else:
            if not archive.is_file():
                raise ValueError("原 ZIP 已丢失，无法恢复上传输入；请重新定位文件或重新上传")
            if _file_identity(str(archive)).get("sha256") != digest:
                raise ValueError("原 ZIP 内容已变化，不能作为原上传数据恢复；请重新上传以创建新运行")
            cache_parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix="restore_", dir=cache_parent)).resolve()
            try:
                restored = staging / "data"
                restored.mkdir()
                extract_zip_safely(
                    str(archive), str(restored),
                    max_zip_files=_limit("ELECTROCHEM_V6_MAX_ZIP_FILES", 5000),
                    max_zip_uncompressed_bytes=_limit("ELECTROCHEM_V6_MAX_ZIP_UNCOMP_BYTES", 500 * 1024 * 1024),
                )
                _verify_members(restored, missing)
                # Detect modification by an external writer while extraction was running.
                if _file_identity(str(archive)).get("sha256") != digest:
                    raise ValueError("原 ZIP 在恢复期间发生变化，请重新上传")
                if cache.is_dir():
                    # Restore a removed data subtree without replacing other retained files.
                    restored.rename(data)
                else:
                    staging.rename(cache)
                mapping = _verify_members(data, missing)
            except (zipfile.BadZipFile, RuntimeError) as exc:
                raise ValueError(f"无法恢复原 ZIP: {exc}") from exc
            finally:
                # Only the freshly created staging directory is eligible for removal.
                if staging.parent == cache_parent and staging.name.startswith("restore_") and staging.exists():
                    shutil.rmtree(staging)
        if recipe.get("run_id"):
            from electrochem_v6.store.run_recipes import update_run_recipe

            update_run_recipe(str(recipe["run_id"]), replay_cache_root=str(cache))
    result.update(source_paths=mapping, folder_path=str(data), warnings=[f"已从原上传 ZIP 的校验副本恢复 {len(mapping)} 个输入文件"])
    return result
