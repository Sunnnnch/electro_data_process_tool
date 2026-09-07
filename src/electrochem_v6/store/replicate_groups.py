"""Durable replicate selections; measured values remain in the history store."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from .runtime import get_database

PREFIX = "replicate_group:"


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_replicate_group(group_id: str) -> dict[str, Any] | None:
    with get_database().read() as connection:
        row = connection.execute("SELECT value FROM meta WHERE key=?", (PREFIX + group_id,)).fetchone()
    return json.loads(row["value"]) if row else None


def list_replicate_groups(project_id: str) -> list[dict[str, Any]]:
    with get_database().read() as connection:
        rows = connection.execute("SELECT value FROM meta WHERE key LIKE ?", (PREFIX + "%",)).fetchall()
    groups = [json.loads(row["value"]) for row in rows]
    return sorted((item for item in groups if item.get("project_id") == project_id),
                  key=lambda item: item.get("updated_at", ""), reverse=True)


def save_replicate_group(group: dict[str, Any], *, expected_revision: int | None = None) -> dict[str, Any]:
    """Check parent/record liveness under the same write lock as the group save."""
    with get_database().transaction() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if not connection.execute("SELECT id FROM projects WHERE id=?", (group["project_id"],)).fetchone():
            raise LookupError("项目已删除")
        row = connection.execute("SELECT value FROM meta WHERE key=?", (PREFIX + group["group_id"],)).fetchone()
        old = json.loads(row["value"]) if row else None
        if expected_revision is not None and (old is None or old.get("revision", 1) != expected_revision):
            raise ValueError("重复组已被其他操作修改，请重新打开后再保存")
        removed = set((old or {}).get("deleted_record_keys") or [])
        removed.update(group.get("deleted_record_keys") or [])
        for key in group["record_keys"]:
            if key in removed:
                continue
            record = connection.execute("SELECT project_id FROM history_records WHERE record_key=?", (key,)).fetchone()
            if record is None or record["project_id"] != group["project_id"]:
                raise ValueError("所选记录已删除或移出项目，请重新打开重复组")
        saved = {**group, "deleted_record_keys": sorted(removed),
                 "created_at": (old or {}).get("created_at") or _now(), "updated_at": _now(),
                 "revision": int((old or {}).get("revision", 0)) + 1}
        connection.execute("INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)", (PREFIX + saved["group_id"], _dump(saved)))
    return saved


def delete_replicate_group(group_id: str) -> bool:
    with get_database().transaction() as connection:
        return connection.execute("DELETE FROM meta WHERE key=?", (PREFIX + group_id,)).rowcount > 0


def cleanup_project_replicates(connection: Any, project_id: str) -> int:
    """Called inside permanent project deletion's transaction."""
    removed = 0
    for row in connection.execute("SELECT key,value FROM meta WHERE key LIKE ?", (PREFIX + "%",)).fetchall():
        if json.loads(row["value"]).get("project_id") == project_id:
            removed += connection.execute("DELETE FROM meta WHERE key=?", (row["key"],)).rowcount
    return removed


def mark_deleted_replicate_records(connection: Any, record_keys: Sequence[str]) -> int:
    """Tombstone references, so reimporting an old key never silently restores n."""
    keys = set(record_keys)
    changed = 0
    if not keys:
        return 0
    for row in connection.execute("SELECT key,value FROM meta WHERE key LIKE ?", (PREFIX + "%",)).fetchall():
        group = json.loads(row["value"])
        affected = set(group.get("record_keys") or []) & keys
        if not affected:
            continue
        group["deleted_record_keys"] = sorted(set(group.get("deleted_record_keys") or []) | affected)
        group["independence_confirmed_keys"] = [key for key in group.get("independence_confirmed_keys") or [] if key not in affected]
        group["revision"] = int(group.get("revision", 1)) + 1
        group["updated_at"] = _now()
        connection.execute("UPDATE meta SET value=? WHERE key=?", (_dump(group), row["key"]))
        changed += 1
    return changed
