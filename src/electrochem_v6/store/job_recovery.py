"""Durable owner/request snapshots independent of the bounded job history."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ._json_utils import to_json_safe
from .runtime import get_database


def ensure_recovery_schema() -> None:
    with get_database().transaction() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS processing_recovery (
            job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, owner TEXT NOT NULL,
            payload TEXT NOT NULL, run_id TEXT, state TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS processing_recovery_claims (
            recovery_id TEXT PRIMARY KEY, resumed_job_id TEXT NOT NULL, created_at TEXT NOT NULL
        )""")


def _dump(value: Any) -> str:
    return json.dumps(to_json_safe(value), ensure_ascii=False, allow_nan=False)


def register_owned_job(job_id: str, *, kind: str, owner: dict[str, Any], payload: dict[str, Any], recovery_source: str | None = None, recovery_origin: dict[str, Any] | None = None) -> dict[str, Any]:
    """Persist the intent before scheduling; a crash cannot lose a queued request."""
    ensure_recovery_schema()
    now = datetime.now().isoformat()
    with get_database().transaction() as connection:
        if recovery_source:
            # SQLite's write lock spans validation and the claim, including
            # separate server instances with their own Python locks.
            connection.execute("BEGIN IMMEDIATE")
            claim = connection.execute("SELECT resumed_job_id FROM processing_recovery_claims WHERE recovery_id=?", (recovery_source,)).fetchone()
            if claim:
                return {"created": False, "job_id": claim["resumed_job_id"]}
            origin = recovery_origin or {}
            origin_job = origin.get("job_id")
            origin_run = origin.get("run_id")
            if not origin_job and not origin_run:
                raise ValueError("恢复来源未经预检")
            job = connection.execute("SELECT status FROM processing_jobs WHERE job_id=?", (origin_job,)).fetchone() if origin_job else None
            saved = connection.execute("SELECT owner, state FROM processing_recovery WHERE job_id=?", (origin_job,)).fetchone() if origin_job else None
            if job and job["status"] not in {"queued", "running", "interrupted"}:
                raise ValueError("原任务状态已变化，请刷新恢复列表；已完成任务不能再次恢复")
            if saved and json.loads(saved["owner"]) != origin.get("owner"):
                raise ValueError("原任务所属进程身份已变化，请重新预检")
            row = connection.execute("SELECT value FROM meta WHERE key=?", ("run_recipe:" + str(origin_run),)).fetchone() if origin_run else None
            run = json.loads(row["value"]) if row else None
            if origin_run and (not run or run.get("status") in {"success", "succeeded"}):
                raise ValueError("原运行已完成或已删除，请刷新恢复列表")
            if run and not saved and run.get("owner") != origin.get("owner"):
                raise ValueError("原运行所属进程身份已变化，请重新预检")
            if not job and not saved and not run:
                raise ValueError("原任务已不存在，请刷新恢复列表")
            connection.execute("INSERT INTO processing_recovery_claims VALUES (?, ?, ?)", (recovery_source, job_id, now))
        connection.execute("INSERT INTO processing_recovery VALUES (?, ?, ?, ?, NULL, 'queued', ?, ?)",
                           (job_id, kind, _dump(owner), _dump(payload if kind == "process" else {}), now, now))
    return {"created": True, "job_id": job_id}


def get_owned_job(job_id: str) -> dict[str, Any] | None:
    ensure_recovery_schema()
    with get_database().read() as connection:
        row = connection.execute("SELECT * FROM processing_recovery WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["owner"] = json.loads(item["owner"])
    item["payload"] = json.loads(item["payload"])
    return item


def list_owned_jobs() -> list[dict[str, Any]]:
    ensure_recovery_schema()
    with get_database().read() as connection:
        rows = connection.execute("SELECT * FROM processing_recovery ORDER BY created_at DESC").fetchall()
    return [{**dict(row), "owner": json.loads(row["owner"]), "payload": json.loads(row["payload"])} for row in rows]


def associate_job_run(job_id: str, run_id: str) -> None:
    ensure_recovery_schema()
    with get_database().transaction() as connection:
        connection.execute("UPDATE processing_recovery SET run_id=?, state='running', updated_at=? WHERE job_id=?",
                           (run_id, datetime.now().isoformat(), job_id))


def start_owned_job(job_id: str) -> None:
    ensure_recovery_schema()
    with get_database().transaction() as connection:
        connection.execute("UPDATE processing_recovery SET state='running', updated_at=? WHERE job_id=?",
                           (datetime.now().isoformat(), job_id))


def finish_owned_job(job_id: str, *, failed_submission: bool = False) -> None:
    ensure_recovery_schema()
    with get_database().transaction() as connection:
        connection.execute("DELETE FROM processing_recovery WHERE job_id=?", (job_id,))
        if failed_submission:
            connection.execute("DELETE FROM processing_recovery_claims WHERE resumed_job_id=?", (job_id,))


def recovery_claim(recovery_id: str) -> str | None:
    ensure_recovery_schema()
    with get_database().read() as connection:
        row = connection.execute("SELECT resumed_job_id FROM processing_recovery_claims WHERE recovery_id=?", (recovery_id,)).fetchone()
    return str(row["resumed_job_id"]) if row else None


def mark_job_interrupted(job_id: str, *, expected_owner: dict[str, Any]) -> bool:
    """Compare persisted ownership again before changing an active job."""
    ensure_recovery_schema()
    now = datetime.now().isoformat()
    with get_database().transaction() as connection:
        row = connection.execute("SELECT owner, state FROM processing_recovery WHERE job_id=?", (job_id,)).fetchone()
        if not row or json.loads(row["owner"]) != expected_owner:
            return False
        job = connection.execute("SELECT status FROM processing_jobs WHERE job_id=?", (job_id,)).fetchone()
        if job and job["status"] not in {"queued", "running", "interrupted"}:
            return False
        if row["state"] == "interrupted" and (not job or job["status"] == "interrupted"):
            return False
        connection.execute("UPDATE processing_recovery SET state='interrupted', updated_at=? WHERE job_id=?", (now, job_id))
        connection.execute("""UPDATE processing_jobs SET status='interrupted',
            error='owner process exited before completion', finished_at=?, updated_at=?
            WHERE job_id=? AND status IN ('queued', 'running')""", (now, now, job_id))
    return True


def mark_run_interrupted(run_id: str, *, expected_owner: dict[str, Any]) -> bool:
    now = datetime.now().isoformat()
    with get_database().transaction() as connection:
        row = connection.execute("SELECT value FROM meta WHERE key=?", ("run_recipe:" + run_id,)).fetchone()
        if not row:
            return False
        recipe = json.loads(row["value"])
        if recipe.get("owner") != expected_owner or recipe.get("status") != "running":
            return False
        keys = [str(item["record_key"]) for item in connection.execute("SELECT record_key FROM history_records WHERE run_id=? ORDER BY id", (run_id,))]
        recipe.update(status="interrupted", interruption_detected_at=now,
                      error="owner process exited before completion", record_keys=keys)
        connection.execute("UPDATE meta SET value=? WHERE key=?", (_dump(recipe), "run_recipe:" + run_id))
    return True
