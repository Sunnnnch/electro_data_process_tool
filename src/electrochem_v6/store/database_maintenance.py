"""Operational checks, backup, restore, and cleanup previews for SQLite storage."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from electrochem_v6.config import ensure_parent_dir, get_history_file

from .database import Database, DatabaseIntegrityError


def get_database_path(path: Optional[str] = None) -> Path:
    if path:
        return Path(path).expanduser().resolve()
    data_dir = ensure_parent_dir(get_history_file()).parent
    return (data_dir / "electrochem_v6.db").resolve()


def _sqlite_quick_check(path: Path) -> List[str]:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    connection = sqlite3.connect(str(path), timeout=10)
    try:
        return [str(row[0]) for row in connection.execute("PRAGMA quick_check").fetchall()]
    finally:
        connection.close()


def _verified_online_copy(source: Path, destination: Path) -> None:
    source_check = _sqlite_quick_check(source)
    if source_check != ["ok"]:
        raise DatabaseIntegrityError(f"source database integrity check failed: {source_check}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    partial.unlink(missing_ok=True)
    source_connection = sqlite3.connect(str(source), timeout=10)
    target_connection = sqlite3.connect(str(partial), timeout=10)
    failed = False
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
        copied_check = [
            str(row[0]) for row in target_connection.execute("PRAGMA quick_check").fetchall()
        ]
        if copied_check != ["ok"]:
            raise DatabaseIntegrityError(f"copied database integrity check failed: {copied_check}")
    except Exception:
        failed = True
        raise
    finally:
        target_connection.close()
        source_connection.close()
        if failed:
            partial.unlink(missing_ok=True)
    os.replace(partial, destination)


def list_database_backups(path: Optional[str] = None) -> List[Dict[str, Any]]:
    database_path = get_database_path(path)
    backup_dir = database_path.parent / "backups"
    if not backup_dir.is_dir():
        return []
    items = sorted(
        backup_dir.glob(f"{database_path.stem}.*.db"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return [
        {
            "path": str(item),
            "size_bytes": item.stat().st_size,
            "modified_at": datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
        }
        for item in items
    ]


def database_health(path: Optional[str] = None) -> Dict[str, Any]:
    database_path = get_database_path(path)
    database = Database(str(database_path))
    try:
        report = database.quick_check()
        with database.read() as connection:
            schema_row = connection.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            counts = {
                "history": connection.execute("SELECT COUNT(*) FROM history_records").fetchone()[0],
                "projects": connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                "conversations": connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
                "messages": connection.execute(
                    "SELECT COUNT(*) FROM conversation_messages"
                ).fetchone()[0],
                "templates": connection.execute("SELECT COUNT(*) FROM process_templates").fetchone()[0],
                "indexed_metrics": connection.execute(
                    "SELECT COUNT(*) FROM history_metrics"
                ).fetchone()[0],
            }
            orphan_rows = connection.execute(
                """SELECT hr.project_id, COUNT(*) AS history_count
                   FROM history_records AS hr
                   LEFT JOIN projects AS p ON p.id=hr.project_id
                   WHERE hr.project_id IS NOT NULL
                     AND TRIM(hr.project_id) != ''
                     AND p.id IS NULL
                   GROUP BY hr.project_id ORDER BY hr.project_id"""
            ).fetchall()
            legacy_blobs = connection.execute(
                "SELECT COUNT(*) FROM conversations WHERE messages IS NOT NULL AND messages NOT IN ('', '[]')"
            ).fetchone()[0]
        report.update(
            {
                "schema_version": int(schema_row["value"]) if schema_row else None,
                "size_bytes": database_path.stat().st_size if database_path.exists() else 0,
                "counts": counts,
                "orphan_projects": [
                    {"project_id": row["project_id"], "history_count": row["history_count"]}
                    for row in orphan_rows
                ],
                "legacy_conversation_blobs": legacy_blobs,
                "backups": list_database_backups(str(database_path)),
            }
        )
        report["ok"] = bool(report["ok"] and not orphan_rows)
        return report
    finally:
        database.close()


def backup_database(
    path: Optional[str] = None,
    *,
    backup_dir: Optional[str] = None,
    keep: int = 5,
) -> Dict[str, Any]:
    database = Database(str(get_database_path(path)))
    try:
        backup_path = database.create_backup(
            reason="manual",
            backup_dir=backup_dir,
            keep=keep,
        )
        return {
            "ok": True,
            "database_path": database.path,
            "backup_path": backup_path,
            "quick_check": _sqlite_quick_check(Path(backup_path)),
        }
    finally:
        database.close()


def restore_database(
    backup_path: str,
    path: Optional[str] = None,
    *,
    confirmed: bool = False,
) -> Dict[str, Any]:
    if not confirmed:
        raise ValueError("restore requires explicit confirmation")
    source = Path(backup_path).expanduser().resolve()
    target = get_database_path(path)
    if source == target:
        raise ValueError("backup path and target database path must differ")
    if _sqlite_quick_check(source) != ["ok"]:
        raise DatabaseIntegrityError("backup database failed integrity check")

    from .runtime import reset_runtime

    reset_runtime()
    safety_backup: Optional[Path] = None
    if target.is_file():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        safety_backup = target.parent / "backups" / f"{target.stem}.pre-restore.{timestamp}.db"
        _verified_online_copy(target, safety_backup)

    restored = target.with_name(target.name + ".restore")
    _verified_online_copy(source, restored)
    for sidecar in (Path(str(target) + "-wal"), Path(str(target) + "-shm")):
        sidecar.unlink(missing_ok=True)
    os.replace(restored, target)

    restored_database = Database(str(target))
    try:
        check = restored_database.quick_check()
    finally:
        restored_database.close()
        reset_runtime()
    if not check["ok"]:
        raise DatabaseIntegrityError(f"restored database failed integrity check: {check}")
    return {
        "ok": True,
        "database_path": str(target),
        "source_backup": str(source),
        "safety_backup": str(safety_backup) if safety_backup else None,
        "integrity": check,
    }


_HIGH_CONFIDENCE_TEST_NAME = re.compile(
    r"^(?:(?:smoke|pytest|test|stress|tmp|temporary)(?:$|[_\-\s])|"
    r"v6_(?:test_[0-9a-f]{8}(?:_edited)?|report_[0-9a-f]{8}|smoke_project)$)",
    re.IGNORECASE,
)
_REVIEW_TEST_NAME = re.compile(r"^(?:v6[_\-]|demo(?:$|[_\-\s]))", re.IGNORECASE)


def cleanup_preview(path: Optional[str] = None) -> Dict[str, Any]:
    """List likely generated projects without changing any user data."""
    database = Database(str(get_database_path(path)))
    try:
        with database.read() as connection:
            rows = connection.execute(
                """SELECT p.id, p.name, p.status, p.created_at, p.updated_at,
                          COUNT(hr.id) AS history_count
                   FROM projects AS p
                   LEFT JOIN history_records AS hr ON hr.project_id=p.id
                   GROUP BY p.id ORDER BY p.updated_at DESC, p.id"""
            ).fetchall()
        high_confidence: List[Dict[str, Any]] = []
        review: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            name = str(item.get("name") or "").strip()
            if _HIGH_CONFIDENCE_TEST_NAME.search(name):
                item["reason"] = "name matches a test/smoke/stress prefix"
                high_confidence.append(item)
            elif _REVIEW_TEST_NAME.search(name):
                item["reason"] = "name resembles a generated v6/demo project; review manually"
                review.append(item)
        return {
            "ok": True,
            "database_path": database.path,
            "read_only": True,
            "high_confidence": high_confidence,
            "review_required": review,
            "candidate_count": len(high_confidence) + len(review),
        }
    finally:
        database.close()
