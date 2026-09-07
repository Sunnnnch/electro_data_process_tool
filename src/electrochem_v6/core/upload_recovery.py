"""Persist upload provenance before processing and rebuild queued ZIP inputs."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from electrochem_v6.config import user_config_dir
from electrochem_v6.core.artifact_lifecycle import artifact_storage_operation
from electrochem_v6.core.processing_manifest import _file_identity

PREPARED_UPLOAD_SNAPSHOT_KEYS = (
    "run_root", "zip_path", "source_archive_sha256", "data_type", "project_name",
    "params", "max_zip_files", "max_zip_uncompressed_bytes", "original_filename",
)


def build_upload_source(
    *, zip_path: str, source_archive_sha256: str, artifact_root: str, input_root: str,
) -> dict[str, Any]:
    """Describe the entire extracted tree before any generated files are present."""
    archive = Path(zip_path).resolve()
    if _file_identity(str(archive)).get("sha256") != source_archive_sha256:
        raise ValueError("上传 ZIP 在排队或解压期间发生变化，请重新上传")
    root = Path(input_root).resolve()
    members = {}
    for item in root.rglob("*"):
        if item.is_file():
            target = item.resolve()
            if not target.is_relative_to(root):
                raise ValueError("ZIP 解压输入超出临时目录")
            members[str(target)] = target.relative_to(root).as_posix()
    return {
        "source_archive_path": str(archive), "source_archive_sha256": source_archive_sha256,
        "artifact_root": str(Path(artifact_root).resolve()), "artifact_owner": "application",
        "input_root": str(root), "archive_members": members,
    }


def _upload_root(value: Any) -> Path:
    root = Path(str(value or "")).resolve()
    parents = (
        (user_config_dir() / "runs" / "uploads").resolve(),
        (Path(tempfile.gettempdir()) / "electrochem_v6" / "runs" / "uploads").resolve(),
    )
    if root.parent not in parents:
        raise ValueError("上传恢复目录不在应用上传存储范围内")
    return root


def _verify_cached_inputs(data: Path, manifest: dict[str, Any]) -> dict[str, str]:
    members = manifest.get("members")
    if not isinstance(members, dict) or not members:
        raise ValueError("上传恢复缓存缺少输入指纹，请重新上传")
    result = {}
    for member, expected in members.items():
        target = (data / member).resolve()
        if not target.is_relative_to(data.resolve()) or target == data.resolve():
            raise ValueError("上传恢复缓存包含越界输入")
        if _file_identity(str(target)).get("sha256") != expected:
            raise ValueError(f"上传恢复缓存输入已变化或丢失，请重新上传: {member}")
        result[str(target)] = member
    # Generated runs stay below electrochem_outputs; other added files must not
    # silently become new inputs during a later preflight.
    for path in data.rglob("*"):
        if path.is_file() and "electrochem_outputs" not in path.relative_to(data).parts:
            if str(path.resolve()) not in result:
                raise ValueError("上传恢复缓存出现额外输入，请重新上传")
    return result


def prepare_queued_upload_recovery(
    prepared: dict[str, Any], source_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Restore a saved ZIP request without submitting work or reusing old outputs.

    Only an unchanged original archive, or an explicitly relocated identical copy,
    can supply queued inputs. Extraction is atomic and caches are verified on reuse.
    The caller still performs normal processing preflight and owns job submission.
    """
    result: dict[str, Any] = {"payload": None, "source_checks": [], "warnings": [], "issues": []}
    original = str(prepared.get("zip_path") or "")
    resolved = original
    digest = str(prepared.get("source_archive_sha256") or "")
    check = {"path": original, "resolved_path": resolved, "file_name": Path(original).name,
             "role": "source_archive", "state": "unverified", "expected_sha256": digest,
             "current_sha256": None}
    result["source_checks"].append(check)
    try:
        if source_paths is not None and (not isinstance(source_paths, dict) or any(
            not isinstance(key, str) or not isinstance(value, str) or not value.strip()
            for key, value in source_paths.items()
        )):
            raise ValueError("source_paths 必须是原路径到新路径的映射")
        paths = source_paths or {}
        original_key = os.path.normcase(os.path.realpath(original))
        for path, replacement in paths.items():
            if os.path.normcase(os.path.realpath(path)) == original_key:
                resolved = str(Path(replacement).expanduser().resolve())
        check["resolved_path"] = resolved
        if not original or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("原上传 ZIP 缺少有效来源指纹，请重新上传")
        root = _upload_root(prepared.get("run_root"))
        from electrochem_v6.core.process_service import _is_allowed_process_dir
        from electrochem_v6.server.request_utils import extract_zip_safely

        archive = Path(resolved).resolve()
        if not _is_allowed_process_dir(str(archive.parent)):
            raise ValueError("原 ZIP 路径不在已允许范围内，请重新选择原始 ZIP")
        cache = root / "recovery_sources" / digest
        data = cache / "data"
        if not data.resolve().is_relative_to(root):
            raise ValueError("上传恢复缓存目录超出原上传目录")
        with artifact_storage_operation():
            current = _file_identity(str(archive)).get("sha256")
            check.update(current_sha256=current, state="missing" if not current else "unchanged" if current == digest else "changed")
            if not current:
                raise ValueError("原上传 ZIP 已丢失；请重新定位同一 ZIP 或重新上传")
            if current != digest:
                raise ValueError("原上传 ZIP 内容已变化；请重新上传以创建新运行")
            manifest_path = cache / "inputs.json"
            if data.exists():
                if not manifest_path.is_file():
                    raise ValueError("上传恢复缓存不完整，请重新上传")
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("source_archive_sha256") != digest:
                    raise ValueError("上传恢复缓存来源不匹配，请重新上传")
                members = _verify_cached_inputs(data, manifest)
            else:
                cache.parent.mkdir(parents=True, exist_ok=True)
                staging = Path(tempfile.mkdtemp(prefix="queued_", dir=cache.parent)).resolve()
                try:
                    extracted = staging / "data"
                    extracted.mkdir()
                    extract_zip_safely(str(archive), str(extracted),
                                       max_zip_files=int(prepared["max_zip_files"]),
                                       max_zip_uncompressed_bytes=int(prepared["max_zip_uncompressed_bytes"]))
                    source = build_upload_source(zip_path=str(archive), source_archive_sha256=digest,
                                                 artifact_root=str(root), input_root=str(extracted))
                    manifest = {"source_archive_sha256": digest, "members": {
                        member: _file_identity(path).get("sha256") for path, member in source["archive_members"].items()
                    }}
                    (staging / "inputs.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
                    if cache.exists():
                        raise ValueError("上传恢复缓存不完整，请重新上传")
                    staging.rename(cache)
                    members = _verify_cached_inputs(data, manifest)
                finally:
                    if staging.parent == cache.parent.resolve() and staging.name.startswith("queued_") and staging.exists():
                        shutil.rmtree(staging)
            if _file_identity(str(archive)).get("sha256") != digest:
                raise ValueError("原上传 ZIP 在恢复期间发生变化，请重新上传")
        params = dict(prepared.get("params") or {})
        for key in ("output_dir", "run_id"):
            params.pop(key, None)
        params["output_run_dir_enabled"] = True
        result["payload"] = {
            "folder_path": str(data), "data_types": [str(prepared["data_type"]).upper()],
            "project_name": prepared.get("project_name"), "params": params,
            "_upload_source": {
                "source_archive_path": str(archive), "source_archive_sha256": digest,
                "artifact_root": str(root), "artifact_owner": "application", "input_root": str(data),
                "archive_members": members,
            },
        }
        result["warnings"].append("已从校验一致的原上传 ZIP 恢复排队输入；本次处理将创建新的运行和输出目录。")
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError) as exc:
        result["issues"].append(str(exc))
    return result
