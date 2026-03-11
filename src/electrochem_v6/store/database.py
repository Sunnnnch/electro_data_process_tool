"""SQLite storage backend for v6 — replaces JSON file storage for better performance."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

_logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS history_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    record_key      TEXT UNIQUE,
    timestamp       TEXT,
    type            TEXT,
    file_path       TEXT,
    file_name       TEXT,
    sample_name     TEXT,
    project_id      TEXT,
    run_id          TEXT,
    folder_path     TEXT,
    archived        INTEGER DEFAULT 0,
    results         TEXT DEFAULT '{}',
    output_files    TEXT DEFAULT '[]',
    summary_path    TEXT,
    quality_summary TEXT DEFAULT '{}',
    data            TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_history_project ON history_records(project_id);
CREATE INDEX IF NOT EXISTS idx_history_type    ON history_records(type);
CREATE INDEX IF NOT EXISTS idx_history_run     ON history_records(run_id);

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at  TEXT,
    updated_at  TEXT,
    status      TEXT DEFAULT 'active',
    tags        TEXT DEFAULT '[]',
    file_count  INTEGER DEFAULT 0,
    color       TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id      TEXT PRIMARY KEY,
    title                TEXT,
    project_name         TEXT,
    data_type            TEXT,
    provider             TEXT,
    model                TEXT,
    created_at           TEXT,
    updated_at           TEXT,
    last_message_excerpt TEXT,
    last_message_role    TEXT,
    messages             TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS process_templates (
    name       TEXT PRIMARY KEY,
    builtin    INTEGER DEFAULT 0,
    updated_at TEXT,
    state      TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS projects_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _to_json_safe(value: Any) -> Any:
    """Convert non-serialisable types to JSON-friendly values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "tolist"):
        try:
            return _to_json_safe(value.tolist())
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return _to_json_safe(value.item())
        except Exception:
            pass
    if hasattr(value, "as_posix"):
        try:
            return value.as_posix()
        except Exception:
            pass
    return str(value)


def _json_dumps(obj: Any) -> str:
    return json.dumps(_to_json_safe(obj), ensure_ascii=False)


def _json_loads(text: Optional[str], default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


class Database:
    """Thread-safe SQLite database with WAL mode and connection-per-thread."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._local = threading.local()
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._get_conn()
        with self._lock:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @contextmanager
    def read(self) -> Generator[sqlite3.Connection, None, None]:
        yield self._get_conn()

    def _init_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(_CREATE_TABLES_SQL)
        cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
        row = cur.fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            conn.commit()

    # ── History ────────────────────────────────────────────────────

    def add_history_record(self, record: Dict[str, Any]) -> None:
        safe = _to_json_safe(record)
        file_value = safe.get("file_path") or safe.get("file_name") or safe.get("sample_name") or ""
        record_key = f"{safe.get('timestamp', '')}|{safe.get('type', '')}|{file_value}"
        with self.transaction() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO history_records
                   (record_key, timestamp, type, file_path, file_name, sample_name,
                    project_id, run_id, folder_path, archived, results, output_files,
                    summary_path, quality_summary, data)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record_key,
                    safe.get("timestamp"),
                    safe.get("type"),
                    safe.get("file_path"),
                    safe.get("file_name"),
                    safe.get("sample_name"),
                    safe.get("project_id"),
                    safe.get("run_id"),
                    safe.get("folder_path"),
                    1 if safe.get("archived") else 0,
                    _json_dumps(safe.get("results", {})),
                    _json_dumps(safe.get("output_files", [])),
                    safe.get("summary_path"),
                    _json_dumps(safe.get("quality_summary", {})),
                    _json_dumps(safe.get("data", {})),
                ),
            )

    def get_all_history_records(self) -> List[Dict[str, Any]]:
        with self.read() as conn:
            rows = conn.execute("SELECT * FROM history_records ORDER BY timestamp DESC").fetchall()
        return [self._row_to_history_dict(row) for row in rows]

    def filter_history(
        self,
        *,
        project_id: Optional[str] = None,
        include_archived: bool = False,
        data_type: Optional[str] = None,
        metric_key: Optional[str] = None,
        metric_min: Optional[float] = None,
        metric_max: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        conditions: List[str] = []
        params: List[Any] = []
        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)
        if not include_archived:
            conditions.append("archived = 0")
        if data_type:
            conditions.append("UPPER(type) = ?")
            params.append(data_type.strip().upper())

        where = " AND ".join(conditions) if conditions else "1=1"
        safe_limit = max(1, min(int(limit), 500))
        sql = f"SELECT * FROM history_records WHERE {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(safe_limit)

        with self.read() as conn:
            rows = conn.execute(sql, params).fetchall()

        records = [self._row_to_history_dict(row) for row in rows]

        # Apply metric filtering in Python (JSON field queries)
        if metric_key and (metric_min is not None or metric_max is not None):
            filtered = []
            for rec in records:
                results = rec.get("results") or {}
                val = results.get(metric_key)
                if val is None:
                    continue
                try:
                    fval = float(val)
                except (ValueError, TypeError):
                    continue
                if metric_min is not None and fval < metric_min:
                    continue
                if metric_max is not None and fval > metric_max:
                    continue
                filtered.append(rec)
            records = filtered

        return records

    def update_history_by_key(self, record_key: str, action: str) -> int:
        with self.transaction() as conn:
            if action == "archive":
                cur = conn.execute(
                    "UPDATE history_records SET archived=1 WHERE record_key=?", (record_key,)
                )
                return cur.rowcount
            elif action == "delete":
                cur = conn.execute(
                    "DELETE FROM history_records WHERE record_key=?", (record_key,)
                )
                return cur.rowcount
        return 0

    def attach_run_outputs(
        self,
        run_id: str,
        output_files: List[str],
        summary_path: Optional[str] = None,
        quality_summary: Optional[Dict[str, Any]] = None,
    ) -> int:
        safe_files = _json_dumps(output_files)
        with self.transaction() as conn:
            if summary_path and quality_summary is not None:
                cur = conn.execute(
                    "UPDATE history_records SET output_files=?, summary_path=?, quality_summary=? WHERE run_id=?",
                    (safe_files, summary_path, _json_dumps(quality_summary), run_id),
                )
            elif summary_path:
                cur = conn.execute(
                    "UPDATE history_records SET output_files=?, summary_path=? WHERE run_id=?",
                    (safe_files, summary_path, run_id),
                )
            else:
                cur = conn.execute(
                    "UPDATE history_records SET output_files=? WHERE run_id=?",
                    (safe_files, run_id),
                )
            return cur.rowcount

    def get_lsv_records(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        conditions = ["UPPER(type) = 'LSV'"]
        params: List[Any] = []
        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)
        where = " AND ".join(conditions)
        with self.read() as conn:
            rows = conn.execute(f"SELECT * FROM history_records WHERE {where}", params).fetchall()
        return [self._row_to_history_dict(row) for row in rows]

    def get_history_stats(
        self, project_id: Optional[str] = None, include_archived: bool = False
    ) -> Dict[str, int]:
        conditions: List[str] = []
        params: List[Any] = []
        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)
        if not include_archived:
            conditions.append("archived = 0")
        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN UPPER(type)='LSV' THEN 1 ELSE 0 END) as lsv_count,
                SUM(CASE WHEN UPPER(type)='CV' THEN 1 ELSE 0 END) as cv_count,
                SUM(CASE WHEN UPPER(type)='EIS' THEN 1 ELSE 0 END) as eis_count,
                SUM(CASE WHEN UPPER(type)='ECSA' THEN 1 ELSE 0 END) as ecsa_count
            FROM history_records WHERE {where}
        """
        with self.read() as conn:
            row = conn.execute(sql, params).fetchone()
        return {
            "total_files": row["total"] or 0,
            "lsv_count": row["lsv_count"] or 0,
            "cv_count": row["cv_count"] or 0,
            "eis_count": row["eis_count"] or 0,
            "ecsa_count": row["ecsa_count"] or 0,
        }

    def get_history_output_dirs(self) -> List[str]:
        """Return distinct directories from history output_files and folder_path for open-path allowlisting."""
        dirs: set[str] = set()
        with self.read() as conn:
            rows = conn.execute("SELECT output_files, folder_path FROM history_records").fetchall()
        for row in rows:
            folder = row["folder_path"]
            if folder:
                dirs.add(os.path.realpath(folder))
            for f in _json_loads(row["output_files"], []):
                p = str(f).strip()
                if p:
                    dirs.add(os.path.realpath(os.path.dirname(p)))
        return list(dirs)

    def _row_to_history_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        for key in row.keys():
            d[key] = row[key]
        d["results"] = _json_loads(d.get("results"), {})
        d["output_files"] = _json_loads(d.get("output_files"), [])
        d["quality_summary"] = _json_loads(d.get("quality_summary"), {})
        d["data"] = _json_loads(d.get("data"), {})
        d["archived"] = bool(d.get("archived"))
        d.pop("id", None)
        return d

    # ── Projects ──────────────────────────────────────────────────

    def create_project(self, project: Dict[str, Any]) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO projects
                   (id, name, description, created_at, updated_at, status, tags, file_count, color)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    project["id"],
                    project["name"],
                    project.get("description", ""),
                    project.get("created_at"),
                    project.get("updated_at"),
                    project.get("status", "active"),
                    _json_dumps(project.get("tags", [])),
                    project.get("file_count", 0),
                    project.get("color"),
                ),
            )

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self.read() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return self._row_to_project_dict(row) if row else None

    def get_all_projects(self, status: str = "active") -> List[Dict[str, Any]]:
        with self.read() as conn:
            if status == "all":
                rows = conn.execute("SELECT * FROM projects").fetchall()
            else:
                rows = conn.execute("SELECT * FROM projects WHERE status=?", (status,)).fetchall()
        return [self._row_to_project_dict(row) for row in rows]

    def update_project(self, project_id: str, **kwargs: Any) -> bool:
        allowed = {"name", "description", "tags", "color", "status"}
        sets: List[str] = []
        params: List[Any] = []
        for key, value in kwargs.items():
            if key in allowed:
                if key == "tags":
                    sets.append(f"{key}=?")
                    params.append(_json_dumps(value))
                else:
                    sets.append(f"{key}=?")
                    params.append(value)
        if not sets:
            return False
        sets.append("updated_at=?")
        params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        params.append(project_id)
        with self.transaction() as conn:
            cur = conn.execute(
                f"UPDATE projects SET {', '.join(sets)} WHERE id=?", params
            )
            return cur.rowcount > 0

    def delete_project(self, project_id: str) -> bool:
        with self.transaction() as conn:
            cur = conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            return cur.rowcount > 0

    def get_default_project(self) -> Optional[str]:
        with self.read() as conn:
            row = conn.execute(
                "SELECT value FROM projects_meta WHERE key='default_project'"
            ).fetchone()
            if row and row["value"]:
                return row["value"]
            first = conn.execute("SELECT id FROM projects WHERE status='active' LIMIT 1").fetchone()
            return first["id"] if first else None

    def set_default_project(self, project_id: Optional[str]) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO projects_meta (key, value) VALUES ('default_project', ?)",
                (project_id,),
            )

    def _row_to_project_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        for key in row.keys():
            d[key] = row[key]
        d["tags"] = _json_loads(d.get("tags"), [])
        return d

    # ── Conversations ─────────────────────────────────────────────

    def list_conversations(
        self,
        page: int = 1,
        page_size: int = 20,
        filters: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        filters = filters or {}
        conditions: List[str] = []
        params: List[Any] = []

        keyword = str(filters.get("keyword") or "").strip().lower()
        if keyword:
            conditions.append(
                "(LOWER(title) LIKE ? OR LOWER(project_name) LIKE ? OR LOWER(last_message_excerpt) LIKE ?)"
            )
            params.extend([f"%{keyword}%"] * 3)

        project_name = str(filters.get("project_name") or "").strip().lower()
        if project_name:
            conditions.append("LOWER(project_name) LIKE ?")
            params.append(f"%{project_name}%")

        data_type = str(filters.get("data_type") or "").strip().lower()
        if data_type:
            conditions.append("LOWER(data_type) LIKE ?")
            params.append(f"%{data_type}%")

        provider_name = str(filters.get("provider") or "").strip().lower()
        if provider_name:
            conditions.append("LOWER(provider) = ?")
            params.append(provider_name)

        where = " AND ".join(conditions) if conditions else "1=1"
        count_sql = f"SELECT COUNT(*) as cnt FROM conversations WHERE {where}"
        with self.read() as conn:
            total = conn.execute(count_sql, params).fetchone()["cnt"]

        safe_page = max(1, int(page))
        safe_page_size = max(1, int(page_size))
        offset = (safe_page - 1) * safe_page_size

        sql = f"""SELECT * FROM conversations WHERE {where}
                  ORDER BY updated_at DESC LIMIT ? OFFSET ?"""
        params.extend([safe_page_size, offset])
        with self.read() as conn:
            rows = conn.execute(sql, params).fetchall()

        items = [self._row_to_conversation_dict(row, include_messages=False) for row in rows]
        return {"items": items, "total": total, "page": safe_page, "page_size": safe_page_size}

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        with self.read() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE conversation_id=?", (conversation_id,)
            ).fetchone()
        return self._row_to_conversation_dict(row, include_messages=True) if row else None

    def delete_conversation(self, conversation_id: str) -> bool:
        with self.transaction() as conn:
            cur = conn.execute(
                "DELETE FROM conversations WHERE conversation_id=?", (conversation_id,)
            )
            return cur.rowcount > 0

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.transaction() as conn:
            cur = conn.execute(
                "UPDATE conversations SET title=?, updated_at=? WHERE conversation_id=?",
                (title, now, conversation_id),
            )
            return cur.rowcount > 0

    def append_message(
        self,
        conversation_id: Optional[str],
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        import uuid

        metadata = dict(metadata or {})
        attachments = list(attachments or [])
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cid = str(conversation_id or "").strip() or uuid.uuid4().hex

        message = {
            "role": str(role or "user"),
            "content": content,
            "timestamp": now,
            "metadata": metadata,
            "attachments": attachments,
        }

        with self.transaction() as conn:
            row = conn.execute(
                "SELECT messages FROM conversations WHERE conversation_id=?", (cid,)
            ).fetchone()

            if row is None:
                messages = [message]
                conn.execute(
                    """INSERT INTO conversations
                       (conversation_id, title, project_name, data_type, provider, model,
                        created_at, updated_at, last_message_excerpt, last_message_role, messages)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        cid,
                        metadata.get("title") or metadata.get("project_name") or "New Conversation",
                        metadata.get("project_name"),
                        metadata.get("data_type"),
                        metadata.get("provider"),
                        metadata.get("model"),
                        now,
                        now,
                        content[:120],
                        str(role or "user"),
                        _json_dumps(messages),
                    ),
                )
            else:
                messages = _json_loads(row["messages"], [])
                messages.append(message)
                updates = {
                    "updated_at": now,
                    "last_message_excerpt": content[:120],
                    "last_message_role": str(role or "user"),
                    "messages": _json_dumps(messages),
                }
                if metadata.get("project_name"):
                    updates["project_name"] = metadata["project_name"]
                if metadata.get("data_type"):
                    updates["data_type"] = metadata["data_type"]
                if metadata.get("provider"):
                    updates["provider"] = metadata["provider"]
                if metadata.get("model"):
                    updates["model"] = metadata["model"]
                if metadata.get("title"):
                    updates["title"] = metadata["title"]

                set_clause = ", ".join(f"{k}=?" for k in updates)
                params = list(updates.values()) + [cid]
                conn.execute(
                    f"UPDATE conversations SET {set_clause} WHERE conversation_id=?",
                    params,
                )
        return cid

    def _row_to_conversation_dict(
        self, row: sqlite3.Row, include_messages: bool = True
    ) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        for key in row.keys():
            if key == "messages" and not include_messages:
                continue
            d[key] = row[key]
        if include_messages:
            d["messages"] = _json_loads(d.get("messages"), [])
        return d

    # ── Process Templates ─────────────────────────────────────────

    def list_process_templates(self) -> List[Dict[str, Any]]:
        with self.read() as conn:
            rows = conn.execute("SELECT * FROM process_templates WHERE builtin=0 ORDER BY name").fetchall()
        return [self._row_to_template_dict(row) for row in rows]

    def save_process_template(self, name: str, state: Dict[str, Any], overwrite: bool = False) -> bool:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT builtin FROM process_templates WHERE name=?", (name,)
            ).fetchone()
            if existing and existing["builtin"]:
                return False
            if existing and not overwrite:
                return False
            conn.execute(
                "INSERT OR REPLACE INTO process_templates (name, builtin, updated_at, state) VALUES (?,0,?,?)",
                (name, now, _json_dumps(state)),
            )
        return True

    def delete_process_template(self, name: str) -> bool:
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT builtin FROM process_templates WHERE name=?", (name,)
            ).fetchone()
            if not existing or existing["builtin"]:
                return False
            cur = conn.execute(
                "DELETE FROM process_templates WHERE name=? AND builtin=0", (name,)
            )
            return cur.rowcount > 0

    def _row_to_template_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "name": row["name"],
            "builtin": bool(row["builtin"]),
            "updated_at": row["updated_at"],
            "state": _json_loads(row["state"], {}),
        }

    # ── Migration from JSON ───────────────────────────────────────

    def migrate_from_json(
        self,
        history_file: Optional[str] = None,
        projects_file: Optional[str] = None,
        conversations_file: Optional[str] = None,
        templates_file: Optional[str] = None,
    ) -> Dict[str, int]:
        """Import existing JSON data into SQLite. Idempotent — skips already-imported records."""
        counts: Dict[str, int] = {"history": 0, "projects": 0, "conversations": 0, "templates": 0}

        if history_file and os.path.exists(history_file):
            counts["history"] = self._migrate_history_json(history_file)

        if projects_file and os.path.exists(projects_file):
            counts["projects"] = self._migrate_projects_json(projects_file)

        if conversations_file and os.path.exists(conversations_file):
            counts["conversations"] = self._migrate_conversations_json(conversations_file)

        if templates_file and os.path.exists(templates_file):
            counts["templates"] = self._migrate_templates_json(templates_file)

        # Mark migration as complete
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('json_migrated', ?)",
                (datetime.now().isoformat(),),
            )

        _logger.info("SQLite migration complete: %s", counts)
        return counts

    def is_migrated(self) -> bool:
        with self.read() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='json_migrated'").fetchone()
            return row is not None

    def _migrate_history_json(self, filepath: str) -> int:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return 0
        records = payload.get("records") if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            return 0
        count = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            try:
                self.add_history_record(record)
                count += 1
            except Exception as exc:
                _logger.debug("Skipped history record during migration: %s", exc)
        return count

    def _migrate_projects_json(self, filepath: str) -> int:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return 0
        projects = payload.get("projects", []) if isinstance(payload, dict) else []
        if not isinstance(projects, list):
            return 0
        default_project = payload.get("default_project") if isinstance(payload, dict) else None
        count = 0
        for project in projects:
            if not isinstance(project, dict) or not project.get("id"):
                continue
            try:
                self.create_project(project)
                count += 1
            except Exception as exc:
                _logger.debug("Skipped project during migration: %s", exc)
        if default_project:
            self.set_default_project(default_project)
        return count

    def _migrate_conversations_json(self, filepath: str) -> int:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return 0
        conversations = payload.get("conversations", []) if isinstance(payload, dict) else []
        if not isinstance(conversations, list):
            return 0
        count = 0
        for conv in conversations:
            if not isinstance(conv, dict):
                continue
            cid = conv.get("conversation_id")
            if not cid:
                continue
            try:
                with self.transaction() as conn:
                    conn.execute(
                        """INSERT OR IGNORE INTO conversations
                           (conversation_id, title, project_name, data_type, provider, model,
                            created_at, updated_at, last_message_excerpt, last_message_role, messages)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            cid,
                            conv.get("title"),
                            conv.get("project_name"),
                            conv.get("data_type"),
                            conv.get("provider"),
                            conv.get("model"),
                            conv.get("created_at"),
                            conv.get("updated_at"),
                            conv.get("last_message_excerpt"),
                            conv.get("last_message_role"),
                            _json_dumps(conv.get("messages", [])),
                        ),
                    )
                count += 1
            except Exception as exc:
                _logger.debug("Skipped conversation during migration: %s", exc)
        return count

    def _migrate_templates_json(self, filepath: str) -> int:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return 0
        templates = payload.get("templates", []) if isinstance(payload, dict) else []
        if not isinstance(templates, list):
            return 0
        count = 0
        for tpl in templates:
            if not isinstance(tpl, dict):
                continue
            name = str(tpl.get("name") or "").strip()
            state = tpl.get("state")
            if not name or not isinstance(state, dict):
                continue
            if tpl.get("builtin"):
                continue  # builtins are added from code, not from JSON
            try:
                with self.transaction() as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO process_templates (name, builtin, updated_at, state) VALUES (?,0,?,?)",
                        (name, tpl.get("updated_at", ""), _json_dumps(state)),
                    )
                count += 1
            except Exception as exc:
                _logger.debug("Skipped template during migration: %s", exc)
        return count
