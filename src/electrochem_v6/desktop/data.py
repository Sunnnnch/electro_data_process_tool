"""Explicit desktop storage selection and reviewed, non-destructive data copying.

No UI, service, database singleton, or environment mutation occurs on import.
Migration preserves recorded absolute paths and fingerprints. It is a verified
copy of application state, not a promise that the original directory can go away.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
from contextlib import ExitStack, closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from platform import system as _platform_system
from typing import Any, Iterator, Mapping, MutableMapping

DATA_ENV = "ELECTROCHEM_V6_DATA_DIR"
MODE_ENV = "ELECTROCHEM_V6_DESKTOP_DATA_MODE"
RESOLVED_ENV = "ELECTROCHEM_V6_DESKTOP_DATA_RESOLVED_DIR"
_LEGACY_LLM_ENV = "ELECTROCHEM_V6_DESKTOP_LEGACY_LLM_FILE"
INSTANCE_LOCK = ".desktop-instance.lock"
_METADATA = {INSTANCE_LOCK, "desktop-instance.json", "desktop-service.json", "runtime_info.json", "desktop-state.json",
             "desktop-preferences.json", "desktop_preferences.json", "desktop_state.json", ".write_test"}
_SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
_RETENTION_NOTICE = "历史文件仍可能引用旧目录，请保留原目录；本次复制不会重写历史路径、原始输入、SHA-256 或记录标识。"


class DesktopDataError(ValueError):
    """An actionable storage-selection or migration error."""


def macos_app_bundle(path: str | os.PathLike[str]) -> Path | None:
    """Find an enclosing .app by its path, including when launched from MacOS/."""
    resolved = Path(path).expanduser().resolve()
    return next((candidate for candidate in (resolved, *resolved.parents)
                 if candidate.suffix.lower() == ".app"), None)


def _check_macos_data_path(path: Path) -> None:
    if _platform_system() == "Darwin" and macos_app_bundle(path) is not None:
        raise DesktopDataError("数据目录不能位于 .app 应用包内部，请选择应用包外的目录。 / Choose a data directory outside the .app bundle.")


def resolve_desktop_data_dir(
    runtime_root: str | os.PathLike[str], *, portable: bool | None = None,
    environ: Mapping[str, str] | None = None, home_dir: str | os.PathLike[str] | None = None,
) -> dict[str, str]:
    """Return a stable path/mode without creating directories or probing writes."""
    environment = os.environ if environ is None else environ
    explicit = str(environment.get(DATA_ENV) or "").strip()
    if explicit:
        path = str(Path(explicit).expanduser().resolve())
        _check_macos_data_path(Path(path))
        previous = str(environment.get(RESOLVED_ENV) or "")
        mode = str(environment.get(MODE_ENV) or "")
        retained = bool(previous and Path(previous).expanduser().resolve() == Path(path) and mode in {"user", "portable", "environment"})
        return {"path": path, "mode": mode if retained else "environment"}
    root = Path(runtime_root).expanduser().resolve()
    if portable is not None and not isinstance(portable, bool):
        raise DesktopDataError("portable 必须为布尔值或 None")
    if _platform_system() == "Darwin" and macos_app_bundle(root) is not None:
        if portable is True:
            raise DesktopDataError(".app 应用包不支持内部便携数据目录，请设置包外的数据目录。 / Portable data must be outside the .app bundle.")
        # A downloaded bundle can be read-only, translocated, or signed. Its
        # markers never opt the application into writes inside the bundle.
        portable = False
    if portable is None:
        if (root / "portable.marker").exists() and (root / "installed.marker").exists():
            raise DesktopDataError("portable.marker 与 installed.marker 同时存在，请修正客户端模式标记。")
        portable = (root / "portable.marker").is_file()
    if not isinstance(portable, bool):
        raise DesktopDataError("portable 必须为布尔值或 None")
    if portable:
        return {"path": str(root / "user_data"), "mode": "portable"}
    home = Path(home_dir).expanduser().resolve() if home_dir is not None else Path.home()
    directory = home / "Library" / "Application Support" / "ElectroChem" if _platform_system() == "Darwin" else home / ".electrochem" / "v6"
    _check_macos_data_path(directory)
    return {"path": str(directory), "mode": "user"}


def configure_desktop_environment(
    location: Mapping[str, str], *, environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Apply a resolved desktop location while preserving explicit per-file settings."""
    environment = os.environ if environ is None else environ
    path = Path(location["path"]).expanduser().resolve()
    existing = str(environment.get(DATA_ENV) or "").strip()
    mode = str(location["mode"])
    if existing and Path(existing).expanduser().resolve() != path:
        path, mode = Path(existing).expanduser().resolve(), "environment"
    _check_macos_data_path(path)
    if not existing:
        environment[DATA_ENV] = str(path)
    environment[MODE_ENV], environment[RESOLVED_ENV] = mode, str(path)
    # Existing CLI/v5 installations store provider settings one directory above
    # the v6 DB. Do not make them disappear when the desktop pins DATA_DIR.
    old_llm = path.parent / "llm_config.json"
    if _platform_system() == "Darwin":
        # The old CLI layout is adjacent to v6, never a generic file in
        # Application Support shared by unrelated applications.
        old_home = path.parents[2] if path.parts[-3:] == ("Library", "Application Support", "ElectroChem") else Path.home()
        old_llm = old_home / ".electrochem" / "llm_config.json"
    previous_llm = environment.get(_LEGACY_LLM_ENV)
    if (previous_llm and (path / "llm_config.json").is_file()
            and environment.get("ELECTROCHEM_V6_LLM_CONFIG_FILE") == previous_llm):
        # A reviewed migration may have just populated the target. Only undo
        # our own fallback, never a caller's explicit per-file override.
        environment.pop("ELECTROCHEM_V6_LLM_CONFIG_FILE", None)
        environment.pop(_LEGACY_LLM_ENV, None)
    if (mode == "user" and not (path / "llm_config.json").exists()
            and old_llm.is_file() and not environment.get("ELECTROCHEM_LLM_CONFIG_FILE")):
        if not environment.get("ELECTROCHEM_V6_LLM_CONFIG_FILE"):
            environment["ELECTROCHEM_V6_LLM_CONFIG_FILE"] = str(old_llm)
            environment[_LEGACY_LLM_ENV] = str(old_llm)
    return {"path": str(path), "mode": mode}


def _link(path: Path) -> bool:
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _ignored(relative: Path) -> bool:
    return (len(relative.parts) == 1 and (relative.name in _METADATA or
            (relative.name.startswith(".desktop-service-") and relative.name.endswith(".tmp")))) or relative.name in {
        ".active-upload.lock", ".artifact-storage.lock",
    }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    files, issues = [], []
    if not root.exists():
        return files, issues
    if not root.is_dir() or _link(root):
        return [], [f"数据目录必须是实际目录，不能是链接: {root}"]
    for current, directories, names in os.walk(root, followlinks=False):
        for name in list(directories):
            path = Path(current) / name
            if _link(path):
                issues.append(f"迁移范围包含目录链接，须先明确处理: {path.relative_to(root)}")
                directories.remove(name)
        for name in sorted(names):
            path = Path(current) / name
            relative = path.relative_to(root)
            sidecar_suffix = next((suffix for suffix in ("-wal", "-shm", "-journal") if name.endswith(suffix)), "")
            database_name = name[:-len(sidecar_suffix)] if sidecar_suffix else ""
            is_sqlite_sidecar = bool(database_name and Path(database_name).suffix.lower() in _SQLITE_SUFFIXES)
            if _ignored(relative) or (is_sqlite_sidecar and sidecar_suffix == "-shm"):
                continue
            if _link(path) or not stat.S_ISREG(path.lstat().st_mode):
                issues.append(f"迁移范围包含链接或特殊文件: {relative}")
                continue
            # WAL is evidence used in the plan fingerprint but is never copied:
            # sqlite3.backup materializes its committed pages into the new DB.
            sidecar = is_sqlite_sidecar
            info = path.stat()
            files.append({"relative_path": relative.as_posix(), "size_bytes": info.st_size,
                          "sha256": _hash_file(path), "sqlite": path.suffix.lower() in _SQLITE_SUFFIXES,
                          "sidecar": sidecar})
    return sorted(files, key=lambda item: item["relative_path"]), issues


def _discover_data(root: Path, *, first_only: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    """Read directory entries and sizes only; discovery never opens file contents."""
    files: list[dict[str, Any]] = []
    issues: list[str] = []
    try:
        if _link(root) or not root.is_dir():
            return [], [f"数据目录必须是实际目录，不能是链接: {root}"]
    except FileNotFoundError:
        return [], []
    except OSError as exc:
        return [], [f"无法读取数据目录: {root}: {exc}"]
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    relative = Path(entry.path).relative_to(root)
                    try:
                        info = entry.stat(follow_symlinks=False)
                        linked = stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)
                        if linked:
                            issues.append(f"迁移范围包含链接，须先明确处理: {relative}")
                        elif stat.S_ISDIR(info.st_mode):
                            pending.append(Path(entry.path))
                        elif _ignored(relative) or (entry.name.endswith("-shm") and Path(entry.name[:-4]).suffix.lower() in _SQLITE_SUFFIXES):
                            continue
                        elif stat.S_ISREG(info.st_mode):
                            files.append({"relative_path": relative.as_posix(), "size_bytes": info.st_size})
                        else:
                            issues.append(f"迁移范围包含特殊文件: {relative}")
                    except OSError as exc:
                        issues.append(f"无法读取数据文件信息: {relative}: {exc}")
                    if first_only and (files or issues):
                        return files, issues
        except OSError as exc:
            issues.append(f"无法读取数据目录: {directory}: {exc}")
            if first_only:
                return files, issues
    return files, issues


def has_desktop_data(path: str | os.PathLike[str]) -> bool:
    """Short-circuit on any non-metadata file or issue, without hashing contents."""
    files, issues = _discover_data(Path(path).expanduser().absolute(), first_only=True)
    return bool(files or issues)


def legacy_data_candidates(
    runtime_root: str | os.PathLike[str], *, target_dir: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None, home_dir: str | os.PathLike[str] | None = None,
) -> list[dict[str, Any]]:
    root = Path(runtime_root).expanduser().resolve()
    target = Path(target_dir).expanduser().resolve() if target_dir is not None else Path(
        resolve_desktop_data_dir(root, environ=environ, home_dir=home_dir)["path"])
    locations = [root / "user_data"]
    if _platform_system() == "Darwin":
        home = Path(home_dir).expanduser().resolve() if home_dir is not None else Path.home()
        locations.append(home / ".electrochem" / "v6")
    candidates = []
    for legacy in dict.fromkeys(locations):
        if legacy == target:
            continue
        files, issues = _discover_data(legacy)
        if files or issues:
            candidates.append({"path": str(legacy), "target_dir": str(target), "file_count": len(files),
                               "size_bytes": sum(item["size_bytes"] for item in files), "issues": issues,
                               "requires_source_retention": True, "notice": _RETENTION_NOTICE})
    return candidates


@contextmanager
def desktop_data_lock(path: str | os.PathLike[str], *, create: bool = True) -> Iterator[None]:
    """Same byte-zero OS lock used by the desktop's single-instance owner."""
    root = Path(path)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    lock = root / INSTANCE_LOCK
    if not create and not lock.exists():
        yield
        return
    with lock.open("a+b" if create else "r+b") as stream:
        if lock.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise DesktopDataError(f"数据目录正在被客户端或迁移占用: {root}") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _readonly_database(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)


def _owner_state(owner: Any, *, allow_pid_only: bool = False) -> dict[str, Any]:
    from electrochem_v6.core.process_owner import _probe_process, inspect_process_owner

    if isinstance(owner, dict) and owner.get("host_id") and owner.get("start_token"):
        return inspect_process_owner(owner)
    if allow_pid_only and isinstance(owner, dict):
        try:
            # A live bare PID is conservatively blocking: its birth cannot be
            # proved from old metadata. Missing PIDs are verifiably stopped.
            return _probe_process(int(owner["pid"]))
        except (KeyError, TypeError, ValueError):
            pass
    return {"state": "unknown", "reason": "owner_identity_missing"}


def _source_owners(source: Path) -> list[dict[str, Any]]:
    owners = []
    for filename in ("runtime_info.json", "desktop-instance.json"):
        path = source / filename
        if path.is_file():
            try:
                value = _read_json(path)
                owner = value.get("owner", value)
                owners.append({"source": filename, **_owner_state(owner, allow_pid_only=True)})
            except (OSError, ValueError, AttributeError):
                owners.append({"source": filename, "state": "unknown", "reason": "unreadable_owner_metadata"})
    database = source / "electrochem_v6.db"
    if database.is_file():
        try:
            with closing(_readonly_database(database)) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                known_jobs = set()
                if "processing_recovery" in tables:
                    for job, raw in connection.execute("SELECT job_id, owner FROM processing_recovery WHERE state IN ('queued','running')"):
                        known_jobs.add(job)
                        owners.append({"source": f"job:{job}", **_owner_state(json.loads(raw))})
                if "processing_jobs" in tables:
                    for (job,) in connection.execute("SELECT job_id FROM processing_jobs WHERE status IN ('queued','running')"):
                        if job not in known_jobs:
                            owners.append({"source": f"job:{job}", "state": "unknown", "reason": "legacy_job_without_owner"})
                if "meta" in tables:
                    for key, raw in connection.execute("SELECT key,value FROM meta WHERE key LIKE 'run_recipe:%'"):
                        recipe = json.loads(raw)
                        if isinstance(recipe, dict) and recipe.get("status") in {"queued", "running"}:
                            owners.append({"source": key, **_owner_state(recipe.get("owner"))})
        except (OSError, ValueError, sqlite3.Error) as exc:
            owners.append({"source": "database", "state": "unknown", "reason": f"owner_read_failed:{type(exc).__name__}"})
    return owners or [{"source": "legacy", "state": "unknown", "reason": "owner_metadata_missing"}]


def inspect_data_migration(
    source_dir: str | os.PathLike[str], target_dir: str | os.PathLike[str], *,
    confirm_source_stopped: bool = False, _locks_held: bool = False,
) -> dict[str, Any]:
    """Build a reviewable, content-bound copy plan; never initialize application stores."""
    source, target = (Path(path).expanduser().resolve() for path in (source_dir, target_dir))
    issues = []
    if source == target or source in target.parents or target in source.parents:
        issues.append("源目录与目标目录不能相同或互相包含。")
    if not source.is_dir():
        issues.append("原数据目录不存在。")
    # Opening a WAL-mode DB read-only can create empty coordination sidecars.
    # Inventory after closing those reads so a fresh plan does not invalidate
    # itself merely by inspecting its persisted owners.
    owners = _source_owners(source)
    files, file_issues = _inventory(source)
    target_files, target_issues = _inventory(target)
    issues.extend(file_issues + target_issues)
    if not files:
        issues.append("原目录没有可迁移数据。")
    if target_files:
        issues.append("目标已有应用数据，不能自动合并或覆盖。请保留现有数据并选择另一目标。")
    if not _locks_held:
        for root in (source, target):
            try:
                with desktop_data_lock(root, create=False):
                    pass
            except OSError as exc:
                issues.append(f"无法核对数据目录锁: {root}: {exc}")
            except DesktopDataError as exc:
                issues.append(str(exc))
    alive = any(item["state"] == "alive" for item in owners)
    unknown = any(item["state"] == "unknown" for item in owners)
    if alive:
        issues.append("原数据仍由活跃进程使用，请先关闭原程序及其处理任务。")
    if unknown and not confirm_source_stopped:
        issues.append("无法核实旧进程身份；请先确认原程序和任务均已关闭，再明确确认迁移。")
    identity = {"source_dir": str(source), "target_dir": str(target), "files": files, "target_files": target_files,
                "issues": file_issues + target_issues}
    plan_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {"source_dir": str(source), "target_dir": str(target), "plan_id": plan_id,
            "can_migrate": not issues, "issues": issues, "warnings": [_RETENTION_NOTICE],
            "requires_source_retention": True, "requires_source_confirmation": unknown,
            "source_state": "alive" if alive else "unknown" if unknown else "stopped", "owners": owners,
            "files": files, "file_count": sum(not item["sidecar"] for item in files),
            "size_bytes": sum(item["size_bytes"] for item in files),
            "preserves": ["record_keys", "input_sha256", "absolute_paths", "original_files"],
            "target_conflicts": [item["relative_path"] for item in target_files]}


def _copy_database(source: Path, target: Path) -> None:
    with closing(_readonly_database(source)) as original, closing(sqlite3.connect(target)) as copied:
        original.backup(copied)
        result = copied.execute("PRAGMA integrity_check").fetchall()
        if result != [("ok",)]:
            raise DesktopDataError(f"SQLite 完整性校验失败: {source.name}")


def migrate_desktop_data(
    source_dir: str | os.PathLike[str], target_dir: str | os.PathLike[str], *,
    expected_plan_id: str, confirm_source_stopped: bool = False,
) -> dict[str, Any]:
    """Copy a reviewed snapshot into an empty target; retain all original paths/files.

    Both source and destination use the desktop instance lock. Metadata is
    published last; partial staging never becomes an application data directory.
    Existing desktop preferences are left intact. A source mutation aborts before
    publication even when an old CLI process did not participate in desktop locks.
    """
    source, target = (Path(path).expanduser().resolve() for path in (source_dir, target_dir))
    if source == target or source in target.parents or target in source.parents:
        raise DesktopDataError("源目录与目标目录不能相同或互相包含。")
    if not source.is_dir():
        raise DesktopDataError("原数据目录不存在。")
    if not expected_plan_id:
        raise DesktopDataError("请先检查并确认迁移计划。")
    with ExitStack() as stack:
        for root in sorted((source, target), key=str):
            stack.enter_context(desktop_data_lock(root))
        plan = inspect_data_migration(source, target, confirm_source_stopped=confirm_source_stopped, _locks_held=True)
        if plan["plan_id"] != expected_plan_id:
            raise DesktopDataError("数据在预检后发生变化，请重新检查迁移计划。")
        if not plan["can_migrate"]:
            raise DesktopDataError("；".join(plan["issues"]))
        staging = Path(tempfile.mkdtemp(prefix=".electrochem-migration-", dir=target.parent))
        published = []
        try:
            copied = []
            for item in plan["files"]:
                if item["sidecar"]:
                    continue
                relative = Path(item["relative_path"])
                origin, destination = source / relative, staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if item["sqlite"]:
                    _copy_database(origin, destination)
                else:
                    shutil.copy2(origin, destination)
                    if _hash_file(destination) != item["sha256"]:
                        raise DesktopDataError(f"复制校验失败: {relative}")
                copied.append({"relative_path": item["relative_path"], "sha256": _hash_file(destination),
                               "sqlite_backup": item["sqlite"]})
            checked = inspect_data_migration(source, target, confirm_source_stopped=confirm_source_stopped, _locks_held=True)
            if checked["plan_id"] != plan["plan_id"] or not checked["can_migrate"]:
                raise DesktopDataError("复制期间原数据或进程状态变化，请关闭原程序并重新预检。")
            receipt = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                       "source_dir": str(source), "target_dir": str(target), "plan_id": plan["plan_id"],
                       "requires_source_retention": True, "notice": _RETENTION_NOTICE, "files": copied,
                       "legacy_read_roots": [str(source)]}
            # The application is not started until this completes. Each rename
            # is on the target filesystem; failures roll back only our own items.
            for child in staging.iterdir():
                destination = target / child.name
                if destination.exists():
                    raise DesktopDataError(f"目标出现新文件，停止复制: {destination.name}")
                child.rename(destination)
                published.append(destination)
            (target / "desktop-migration.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"status": "success", **receipt, "file_count": len(copied), "legacy_read_roots": [str(source)]}
        except BaseException:
            # No source, preexisting target file, or arbitrary computed path is removed.
            for path in reversed(published):
                if path.parent == target:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink(missing_ok=True)
            raise
        finally:
            if staging.parent == target.parent and staging.name.startswith(".electrochem-migration-"):
                shutil.rmtree(staging, ignore_errors=True)


__all__ = ["DesktopDataError", "resolve_desktop_data_dir", "configure_desktop_environment",
           "legacy_data_candidates", "has_desktop_data", "inspect_data_migration", "migrate_desktop_data",
           "desktop_data_lock"]
