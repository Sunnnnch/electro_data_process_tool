"""Build project archives from files explicitly referenced by run history."""

from __future__ import annotations

import io
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from electrochem_v6.config import user_config_dir

DEFAULT_MAX_ARCHIVE_FILES = 5000
DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 500 * 1024 * 1024


class ProjectArchiveLimitError(ValueError):
    """Raised when a project archive exceeds its configured resource budget."""


@dataclass(frozen=True)
class ProjectArchiveSummary:
    file_count: int
    skipped_files: tuple[str, ...]
    total_uncompressed_bytes: int


@dataclass(frozen=True)
class ProjectArchive:
    data: bytes
    file_count: int
    skipped_files: tuple[str, ...]
    total_uncompressed_bytes: int = 0


def _resolved_path(value: Any) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve()
    except (OSError, RuntimeError):
        return None


def _is_within(path: Path, roots: Iterable[Path]) -> bool:
    normalized_path = os.path.normcase(str(path))
    for root in roots:
        try:
            normalized_root = os.path.normcase(str(root))
            if os.path.commonpath([normalized_path, normalized_root]) == normalized_root:
                return True
        except (OSError, ValueError):
            continue
    return False


def _safe_component(value: Any, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    return (cleaned[:64] or fallback).strip("._") or fallback


def _unique_arcname(candidate: str, used: set[str]) -> str:
    normalized = candidate.replace("\\", "/")
    if normalized not in used:
        used.add(normalized)
        return normalized
    path = Path(normalized)
    parent = path.parent.as_posix()
    suffix = path.suffix
    stem = path.stem
    index = 2
    while True:
        filename = f"{stem}_{index}{suffix}"
        alternative = f"{parent}/{filename}" if parent != "." else filename
        if alternative not in used:
            used.add(alternative)
            return alternative
        index += 1


def _default_application_roots() -> tuple[Path, ...]:
    values = (
        user_config_dir(),
        Path(tempfile.gettempdir()) / "electrochem_v6",
    )
    return tuple(path.expanduser().resolve() for path in values)


def _record_archive_roots(record: Mapping[str, Any]) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Prefer validated run metadata; recover bounded paths for older records."""
    metadata = record.get("archive_roots")
    if isinstance(metadata, Mapping) and metadata.get("input_roots"):
        inputs = tuple(
            path for raw in metadata["input_roots"]
            if (path := _resolved_path(raw)) is not None and path.is_dir()
        )
        output = _resolved_path(metadata.get("output_root"))
        return inputs, (output,) if output is not None and output.is_dir() else ()

    data_root = _resolved_path(record.get("folder_path"))
    source = _resolved_path(record.get("file_path"))
    inputs = []
    if data_root is not None and data_root.is_dir():
        inputs.append(data_root)
    if source is not None and source.exists():
        inputs.append(source if source.is_dir() else source.parent)

    # Legacy builders omitted folder_path. Permit only the normal isolated
    # output subtree belonging to this run, not arbitrary output-file parents.
    outputs: set[Path] = set()
    run_token = str(record.get("run_id") or "")[:8]
    for raw in record.get("output_files") or ():
        output = _resolved_path(raw)
        if output is None or source is None or not source.exists() or not run_token:
            continue
        for parent in output.parents:
            if parent.parent.name != "electrochem_outputs":
                continue
            if not re.fullmatch(r"\d{8}_\d{6}_" + re.escape(run_token), parent.name):
                continue
            if _is_within(source, (parent.parent.parent,)):
                outputs.add(parent)
    return tuple(dict.fromkeys(inputs)), tuple(outputs)


def _write_archive_contents(
    archive: zipfile.ZipFile,
    records: Iterable[Mapping[str, Any]],
    *,
    application_roots: Iterable[str | os.PathLike[str]] | None = None,
    max_files: int = DEFAULT_MAX_ARCHIVE_FILES,
    max_uncompressed_bytes: int = DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES,
) -> ProjectArchiveSummary:
    """Populate an open ZIP while enforcing file-count and byte budgets."""

    if application_roots is None:
        trusted_application_roots = _default_application_roots()
    else:
        trusted_application_roots = tuple(
            path for raw in application_roots if (path := _resolved_path(raw)) is not None
        )

    file_limit = max(1, int(max_files))
    byte_limit = max(1, int(max_uncompressed_bytes))
    used_arcnames: set[str] = set()
    skipped: list[str] = []
    file_count = 0
    total_uncompressed_bytes = 0

    def add_file(path: Path, arcname: str) -> None:
        nonlocal file_count, total_uncompressed_bytes
        if file_count >= file_limit:
            raise ProjectArchiveLimitError(f"项目归档文件数超过限制 ({file_limit})")
        try:
            estimated_size = max(0, int(path.stat().st_size))
        except OSError as exc:
            raise ProjectArchiveLimitError(f"无法读取归档文件大小: {path}") from exc
        if total_uncompressed_bytes + estimated_size > byte_limit:
            raise ProjectArchiveLimitError(
                f"项目归档未压缩体积超过限制 ({byte_limit} bytes)"
            )
        archive.write(path, arcname)
        actual_size = max(0, int(archive.getinfo(arcname).file_size))
        total_uncompressed_bytes += actual_size
        if total_uncompressed_bytes > byte_limit:
            raise ProjectArchiveLimitError(
                f"项目归档未压缩体积超过限制 ({byte_limit} bytes)"
            )
        file_count += 1

    run_names: dict[str, str] = {}
    seen_results: dict[str, set[Path]] = {}
    seen_sources: dict[str, set[Path]] = {}
    for record_index, record in enumerate(records, start=1):
        run_id = str(record.get("run_id") or "").strip()
        group_key = f"run:{run_id}" if run_id else f"record:{record_index}"
        run_name = run_names.get(group_key)
        if run_name is None:
            run_index = len(run_names) + 1
            raw_run_id = str(record.get("run_id") or record.get("timestamp") or group_key)
            run_name = f"{run_index:04d}_{_safe_component(raw_run_id, f'run_{run_index}')}"
            run_names[group_key] = run_name
            seen_results[group_key] = set()
            seen_sources[group_key] = set()
        run_root = f"runs/{run_name}"

        data_roots, output_roots = _record_archive_roots(record)
        result_roots = (*data_roots, *output_roots, *trusted_application_roots)

        result_paths: list[Any] = []
        output_files = record.get("output_files")
        if isinstance(output_files, (list, tuple)):
            result_paths.extend(output_files)
        result_paths.append(record.get("summary_path"))
        for raw_path in result_paths:
            path = _resolved_path(raw_path)
            if path is None or path in seen_results[group_key]:
                continue
            if not path.is_file() or not _is_within(path, result_roots):
                skipped.append(str(path))
                continue
            seen_results[group_key].add(path)
            arcname = _unique_arcname(
                f"{run_root}/results/{_safe_component(path.name, 'result')}",
                used_arcnames,
            )
            add_file(path, arcname)

        source_candidates = (
            (record.get("source_archive_path"), (*data_roots, *trusted_application_roots), "upload"),
            (record.get("file_path"), data_roots, "source"),
        )
        for raw_path, allowed_roots, fallback in source_candidates:
            path = _resolved_path(raw_path)
            if path is None or path in seen_sources[group_key]:
                continue
            if not path.is_file() or not _is_within(path, allowed_roots):
                skipped.append(str(path))
                continue
            seen_sources[group_key].add(path)
            arcname = _unique_arcname(
                f"{run_root}/source/{_safe_component(path.name, fallback)}",
                used_arcnames,
            )
            add_file(path, arcname)

    summary = ProjectArchiveSummary(
        file_count=file_count,
        skipped_files=tuple(dict.fromkeys(skipped)),
        total_uncompressed_bytes=total_uncompressed_bytes,
    )
    archive.writestr(
        "archive_manifest.json",
        json.dumps(
            {
                "schema_version": "1.0",
                "file_count": summary.file_count,
                "total_uncompressed_bytes": summary.total_uncompressed_bytes,
                "skipped_files": list(summary.skipped_files),
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return summary


def write_project_archive(
    records: Iterable[Mapping[str, Any]],
    output_path: str | os.PathLike[str],
    *,
    application_roots: Iterable[str | os.PathLike[str]] | None = None,
    max_files: int = DEFAULT_MAX_ARCHIVE_FILES,
    max_uncompressed_bytes: int = DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES,
) -> ProjectArchiveSummary:
    """Atomically write a bounded project archive to disk."""

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{target.name}.partial")
    try:
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
            summary = _write_archive_contents(
                archive,
                records,
                application_roots=application_roots,
                max_files=max_files,
                max_uncompressed_bytes=max_uncompressed_bytes,
            )
        os.replace(partial, target)
        return summary
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def build_project_archive(
    records: Iterable[Mapping[str, Any]],
    *,
    application_roots: Iterable[str | os.PathLike[str]] | None = None,
    max_files: int = DEFAULT_MAX_ARCHIVE_FILES,
    max_uncompressed_bytes: int = DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES,
) -> ProjectArchive:
    """Return a bounded in-memory ZIP for callers that explicitly need bytes."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        summary = _write_archive_contents(
            archive,
            records,
            application_roots=application_roots,
            max_files=max_files,
            max_uncompressed_bytes=max_uncompressed_bytes,
        )

    return ProjectArchive(
        data=buffer.getvalue(),
        file_count=summary.file_count,
        skipped_files=summary.skipped_files,
        total_uncompressed_bytes=summary.total_uncompressed_bytes,
    )


__all__ = [
    "DEFAULT_MAX_ARCHIVE_FILES",
    "DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES",
    "ProjectArchive",
    "ProjectArchiveLimitError",
    "ProjectArchiveSummary",
    "build_project_archive",
    "write_project_archive",
]
