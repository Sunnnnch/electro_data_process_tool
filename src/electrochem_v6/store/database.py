"""SQLite storage backend for v6 — replaces JSON file storage for better performance."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from electrochem_v6.store._json_utils import to_json_safe as _to_json_safe
from electrochem_v6.store.archive_metadata import RUN_ARCHIVE_ROOTS_PREFIX

_logger = logging.getLogger(__name__)

SCHEMA_VERSION = 6
DEFAULT_BACKUP_RETENTION = 5
DEFAULT_PROCESSING_JOB_RETENTION = 100
PROCESS_TEMPLATE_JSON_MIGRATION_KEY = "process_templates_json_migrated_v1"

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
    sample_id       TEXT,
    project_id      TEXT,
    run_id          TEXT,
    folder_path     TEXT,
    archived        INTEGER DEFAULT 0,
    results         TEXT DEFAULT '{}',
    output_files    TEXT DEFAULT '[]',
    summary_path    TEXT,
    source_archive_path TEXT,
    artifact_root   TEXT,
    artifact_owner  TEXT DEFAULT 'external',
    quality_summary TEXT DEFAULT '{}',
    data            TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_history_project ON history_records(project_id);
CREATE INDEX IF NOT EXISTS idx_history_type    ON history_records(type);
CREATE INDEX IF NOT EXISTS idx_history_run     ON history_records(run_id);
CREATE INDEX IF NOT EXISTS idx_history_cursor  ON history_records(timestamp DESC, id DESC);

CREATE TABLE IF NOT EXISTS history_metrics (
    record_key   TEXT NOT NULL,
    metric_key   TEXT NOT NULL,
    metric_value REAL NOT NULL,
    PRIMARY KEY (record_key, metric_key),
    FOREIGN KEY (record_key) REFERENCES history_records(record_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_history_metrics_lookup
    ON history_metrics(metric_key, metric_value, record_key);

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at  TEXT,
    updated_at  TEXT,
    status      TEXT DEFAULT 'active',
    tags        TEXT DEFAULT '[]',
    file_count  INTEGER DEFAULT 0,
    color       TEXT,
    default_template_name TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS project_samples (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    name        TEXT NOT NULL,
    batch_id    TEXT DEFAULT '',
    note        TEXT DEFAULT '',
    tags        TEXT DEFAULT '[]',
    created_at  TEXT,
    updated_at  TEXT,
    UNIQUE (project_id, name, batch_id)
);

CREATE INDEX IF NOT EXISTS idx_project_samples_project
    ON project_samples(project_id, updated_at DESC);

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

CREATE TABLE IF NOT EXISTS conversation_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    position        INTEGER NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    timestamp       TEXT,
    metadata        TEXT DEFAULT '{}',
    attachments     TEXT DEFAULT '[]',
    UNIQUE (conversation_id, position),
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_order
    ON conversation_messages(conversation_id, position);

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

CREATE TABLE IF NOT EXISTS processing_jobs (
    job_id            TEXT PRIMARY KEY,
    kind              TEXT NOT NULL DEFAULT 'process',
    status            TEXT NOT NULL,
    payload           TEXT DEFAULT '{}',
    result            TEXT DEFAULT '{}',
    error             TEXT,
    progress_current  INTEGER DEFAULT 0,
    progress_total    INTEGER DEFAULT 0,
    current_item      TEXT,
    cancel_requested  INTEGER DEFAULT 0,
    created_at        TEXT,
    started_at        TEXT,
    finished_at       TEXT,
    updated_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_processing_jobs_created
    ON processing_jobs(created_at DESC);
"""

# ── Schema migration SQL per version ──────────────────────────────────
# Add entries here when bumping SCHEMA_VERSION. Each key maps to a list
# of SQL statements that upgrade from the *previous* version.
_MIGRATIONS: Dict[int, List[str]] = {
    2: [
        """CREATE TABLE IF NOT EXISTS history_metrics (
               record_key TEXT NOT NULL,
               metric_key TEXT NOT NULL,
               metric_value REAL NOT NULL,
               PRIMARY KEY (record_key, metric_key),
               FOREIGN KEY (record_key) REFERENCES history_records(record_key) ON DELETE CASCADE
           )""",
        """CREATE INDEX IF NOT EXISTS idx_history_metrics_lookup
               ON history_metrics(metric_key, metric_value, record_key)""",
        """CREATE TABLE IF NOT EXISTS conversation_messages (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               conversation_id TEXT NOT NULL,
               position INTEGER NOT NULL,
               role TEXT NOT NULL,
               content TEXT NOT NULL,
               timestamp TEXT,
               metadata TEXT DEFAULT '{}',
               attachments TEXT DEFAULT '[]',
               UNIQUE (conversation_id, position),
               FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
           )""",
        """CREATE INDEX IF NOT EXISTS idx_conversation_messages_order
               ON conversation_messages(conversation_id, position)""",
    ],
    3: [
        "ALTER TABLE history_records ADD COLUMN source_archive_path TEXT",
        "ALTER TABLE history_records ADD COLUMN artifact_root TEXT",
        "ALTER TABLE history_records ADD COLUMN artifact_owner TEXT DEFAULT 'external'",
        "CREATE INDEX IF NOT EXISTS idx_history_cursor ON history_records(timestamp DESC, id DESC)",
        """CREATE TABLE IF NOT EXISTS processing_jobs (
               job_id TEXT PRIMARY KEY,
               kind TEXT NOT NULL DEFAULT 'process',
               status TEXT NOT NULL,
               payload TEXT DEFAULT '{}',
               result TEXT DEFAULT '{}',
               error TEXT,
               progress_current INTEGER DEFAULT 0,
               progress_total INTEGER DEFAULT 0,
               current_item TEXT,
               cancel_requested INTEGER DEFAULT 0,
               created_at TEXT,
               started_at TEXT,
               finished_at TEXT,
               updated_at TEXT
           )""",
        """CREATE INDEX IF NOT EXISTS idx_processing_jobs_created
               ON processing_jobs(created_at DESC)""",
    ],
    4: [
        "ALTER TABLE history_records ADD COLUMN sample_id TEXT",
        "CREATE INDEX IF NOT EXISTS idx_history_sample ON history_records(sample_id)",
        """CREATE TABLE IF NOT EXISTS project_samples (
               id TEXT PRIMARY KEY,
               project_id TEXT NOT NULL,
               name TEXT NOT NULL,
               note TEXT DEFAULT '',
               tags TEXT DEFAULT '[]',
               created_at TEXT,
               updated_at TEXT,
               UNIQUE (project_id, name)
           )""",
        """CREATE INDEX IF NOT EXISTS idx_project_samples_project
               ON project_samples(project_id, updated_at DESC)""",
    ],
    5: [
        # Data migration rebuilds project_samples and creates the project-name index.
        "SELECT 1",
    ],
    6: [
        "ALTER TABLE projects ADD COLUMN default_template_name TEXT NOT NULL DEFAULT ''",
    ],
}


def _json_dumps(obj: Any) -> str:
    return json.dumps(_to_json_safe(obj), ensure_ascii=False)


def _json_loads(text: Optional[str], default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


class DatabaseIntegrityError(RuntimeError):
    """Raised when SQLite reports a damaged database."""


class DatabaseVersionError(RuntimeError):
    """Raised when the database schema is newer than this application."""


class Database:
    """Thread-safe SQLite database with WAL mode and connection-per-thread."""

    def __init__(self, db_path: str):
        self._db_path = os.path.abspath(db_path)
        self._preexisting = os.path.exists(self._db_path) and os.path.getsize(self._db_path) > 0
        self._local = threading.local()
        self._lock = threading.RLock()
        self._connections: set[sqlite3.Connection] = set()
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.execute("SELECT 1")
            except sqlite3.ProgrammingError:
                conn = None
                self._local.conn = None
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=10, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.create_function(
                "history_basename", 1,
                lambda value: str(value or "").replace("\\", "/").rsplit("/", 1)[-1],
                deterministic=True,
            )
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
            with self._lock:
                self._connections.add(conn)
        return conn

    def close(self) -> None:
        """Close the connection for the current thread (if any)."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            with self._lock:
                self._connections.discard(conn)
            self._local.conn = None

    def close_all(self) -> None:
        """Close every connection created by this instance, including worker threads."""
        with self._lock:
            connections = list(self._connections)
            self._connections.clear()
            for connection in connections:
                try:
                    connection.close()
                except Exception:
                    pass
            self._local.conn = None

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

    def quick_check(self) -> Dict[str, Any]:
        """Return a compact SQLite integrity report."""
        with self.read() as conn:
            messages = [str(row[0]) for row in conn.execute("PRAGMA quick_check").fetchall()]
            foreign_key_rows = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        return {
            "ok": messages == ["ok"] and foreign_key_rows == 0,
            "messages": messages,
            "foreign_key_errors": foreign_key_rows,
            "path": self._db_path,
        }

    @property
    def path(self) -> str:
        return self._db_path

    def create_backup(
        self,
        *,
        reason: str = "manual",
        backup_dir: str | None = None,
        keep: int = DEFAULT_BACKUP_RETENTION,
    ) -> str:
        """Create and verify an online SQLite backup, then prune old backups."""
        safe_reason = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(reason or "manual"))
        target_dir = Path(backup_dir) if backup_dir else Path(self._db_path).parent / "backups"
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target = target_dir / f"{Path(self._db_path).stem}.{safe_reason}.{timestamp}.db"
        partial = target.with_suffix(".partial")

        with self._lock:
            source = self._get_conn()
            destination = sqlite3.connect(str(partial))
            failed = False
            try:
                source.backup(destination)
                check = [str(row[0]) for row in destination.execute("PRAGMA quick_check").fetchall()]
                if check != ["ok"]:
                    raise DatabaseIntegrityError(f"backup integrity check failed: {check}")
                destination.commit()
            except Exception:
                failed = True
                raise
            finally:
                destination.close()
                if failed:
                    partial.unlink(missing_ok=True)
            os.replace(partial, target)

        retention = max(1, int(keep))
        pattern = f"{Path(self._db_path).stem}.*.db"
        backups = sorted(target_dir.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
        for stale in backups[retention:]:
            try:
                stale.unlink()
            except OSError:
                _logger.warning("Failed to prune old database backup %s", stale)
        return str(target)

    def ensure_periodic_backup(self, *, interval_hours: int = 24) -> Optional[str]:
        """Create at most one rolling automatic backup per interval."""
        if not self._preexisting:
            return None
        with self.read() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key='last_automatic_backup_at'"
            ).fetchone()
        if row and row["value"]:
            try:
                elapsed = datetime.now() - datetime.fromisoformat(str(row["value"]))
                if elapsed.total_seconds() < max(1, int(interval_hours)) * 3600:
                    return None
            except ValueError:
                pass
        backup_path = self.create_backup(reason="automatic")
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO meta (key, value) VALUES ('last_automatic_backup_at', ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (datetime.now().isoformat(),),
            )
        return backup_path

    @staticmethod
    def _numeric_metrics(results: Any) -> Dict[str, float]:
        if not isinstance(results, dict):
            return {}
        metrics: Dict[str, float] = {}
        for key, value in results.items():
            if isinstance(value, bool):
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric):
                metrics[str(key)] = numeric
        return metrics

    @classmethod
    def _replace_history_metrics(
        cls,
        conn: sqlite3.Connection,
        record_key: str,
        results: Any,
    ) -> None:
        conn.execute("DELETE FROM history_metrics WHERE record_key=?", (record_key,))
        metrics = cls._numeric_metrics(results)
        if metrics:
            conn.executemany(
                "INSERT INTO history_metrics (record_key, metric_key, metric_value) VALUES (?,?,?)",
                [(record_key, key, value) for key, value in metrics.items()],
            )

    @staticmethod
    def _insert_conversation_message(
        conn: sqlite3.Connection,
        conversation_id: str,
        position: int,
        message: Dict[str, Any],
    ) -> None:
        conn.execute(
            """INSERT OR IGNORE INTO conversation_messages
               (conversation_id, position, role, content, timestamp, metadata, attachments)
               VALUES (?,?,?,?,?,?,?)""",
            (
                conversation_id,
                position,
                str(message.get("role") or "user"),
                str(message.get("content") or ""),
                message.get("timestamp"),
                _json_dumps(message.get("metadata", {})),
                _json_dumps(message.get("attachments", [])),
            ),
        )

    @staticmethod
    def _project_sample_id(
        project_id: Any,
        sample_name: Any,
        batch_id: Any = None,
    ) -> str:
        identity = (
            f"{str(project_id or '').strip()}\0{str(sample_name or '').strip()}"
            f"\0{str(batch_id or '').strip()}"
        )
        return f"sample_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"

    @staticmethod
    def _sample_batch_identity(record: Dict[str, Any]) -> str:
        explicit = str(record.get("sample_batch_id") or "").strip()
        if explicit:
            return explicit
        folder_path = str(record.get("folder_path") or "").strip()
        if folder_path:
            return os.path.normcase(os.path.normpath(folder_path))
        source_archive = str(record.get("source_archive_path") or "").strip()
        if source_archive:
            return os.path.normcase(os.path.normpath(source_archive))
        file_path = str(record.get("file_path") or "").strip()
        if file_path:
            parent = os.path.dirname(file_path) or file_path
            return os.path.normcase(os.path.normpath(parent))
        return str(record.get("run_id") or "").strip()

    @classmethod
    def _ensure_project_sample(
        cls,
        conn: sqlite3.Connection,
        *,
        project_id: Any,
        sample_name: Any,
        batch_id: Any = None,
        timestamp: Any = None,
    ) -> Optional[str]:
        safe_project_id = str(project_id or "").strip()
        safe_name = str(sample_name or "").strip()
        safe_batch_id = str(batch_id or "").strip()
        if not safe_project_id or not safe_name:
            return None
        row = conn.execute(
            "SELECT id FROM project_samples WHERE project_id=? AND name=? AND batch_id=?",
            (safe_project_id, safe_name, safe_batch_id),
        ).fetchone()
        if row:
            return str(row["id"])
        sample_id = cls._project_sample_id(safe_project_id, safe_name, safe_batch_id)
        now = str(timestamp or "").strip() or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT OR IGNORE INTO project_samples
               (id, project_id, name, batch_id, note, tags, created_at, updated_at)
               VALUES (?, ?, ?, ?, '', '[]', ?, ?)""",
            (sample_id, safe_project_id, safe_name, safe_batch_id, now, now),
        )
        row = conn.execute(
            "SELECT id FROM project_samples WHERE project_id=? AND name=? AND batch_id=?",
            (safe_project_id, safe_name, safe_batch_id),
        ).fetchone()
        return str(row["id"]) if row else sample_id

    @classmethod
    def _migrate_project_samples_to_batches(cls, conn: sqlite3.Connection) -> None:
        """Split legacy sample notes by processing run while preserving their content."""

        legacy_rows = conn.execute("SELECT * FROM project_samples").fetchall()
        legacy = {
            (str(row["project_id"]), str(row["name"])): row
            for row in legacy_rows
        }
        conn.execute("DROP TABLE IF EXISTS project_samples_v5")
        conn.execute(
            """CREATE TABLE project_samples_v5 (
                   id TEXT PRIMARY KEY,
                   project_id TEXT NOT NULL,
                   name TEXT NOT NULL,
                   batch_id TEXT DEFAULT '',
                   note TEXT DEFAULT '',
                   tags TEXT DEFAULT '[]',
                   created_at TEXT,
                   updated_at TEXT,
                   UNIQUE (project_id, name, batch_id)
               )"""
        )

        history_rows = conn.execute(
            """SELECT record_key, project_id, sample_name, run_id, folder_path,
                      file_path, source_archive_path, timestamp
               FROM history_records
               WHERE project_id IS NOT NULL AND TRIM(project_id) != ''
                 AND sample_name IS NOT NULL AND TRIM(sample_name) != ''"""
        ).fetchall()
        migrated_keys: set[tuple[str, str, str]] = set()
        for row in history_rows:
            project_id = str(row["project_id"])
            sample_name = str(row["sample_name"])
            batch_id = cls._sample_batch_identity(dict(row))
            source = legacy.get((project_id, sample_name))
            sample_id = cls._project_sample_id(project_id, sample_name, batch_id)
            key = (project_id, sample_name, batch_id)
            if key not in migrated_keys:
                created_at = source["created_at"] if source is not None else row["timestamp"]
                updated_at = source["updated_at"] if source is not None else created_at
                conn.execute(
                    """INSERT INTO project_samples_v5
                       (id, project_id, name, batch_id, note, tags, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sample_id,
                        project_id,
                        sample_name,
                        batch_id,
                        source["note"] if source is not None else "",
                        source["tags"] if source is not None else "[]",
                        created_at,
                        updated_at,
                    ),
                )
                migrated_keys.add(key)
            conn.execute(
                "UPDATE history_records SET sample_id=? WHERE record_key=?",
                (sample_id, row["record_key"]),
            )

        for source in legacy_rows:
            key = (str(source["project_id"]), str(source["name"]), "")
            if key in migrated_keys:
                continue
            conn.execute(
                """INSERT OR IGNORE INTO project_samples_v5
                   (id, project_id, name, batch_id, note, tags, created_at, updated_at)
                   VALUES (?, ?, ?, '', ?, ?, ?, ?)""",
                (
                    cls._project_sample_id(key[0], key[1], ""),
                    key[0],
                    key[1],
                    source["note"],
                    source["tags"],
                    source["created_at"],
                    source["updated_at"],
                ),
            )

        conn.execute("DROP TABLE project_samples")
        conn.execute("ALTER TABLE project_samples_v5 RENAME TO project_samples")
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_project_samples_project
               ON project_samples(project_id, updated_at DESC)"""
        )

    @staticmethod
    def _deduplicate_project_names(conn: sqlite3.Connection) -> None:
        """Make legacy project names case-insensitively unique without losing projects."""

        rows = conn.execute(
            """SELECT id, name FROM projects
               ORDER BY COALESCE(created_at, ''), id"""
        ).fetchall()
        occupied = {str(row["name"] or "").strip().casefold() for row in rows}
        retained: set[str] = set()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for row in rows:
            project_id = str(row["id"])
            original = str(row["name"] or "").strip() or "未命名项目"
            normalized = original.casefold()
            if normalized not in retained:
                retained.add(normalized)
                if original != str(row["name"] or ""):
                    conn.execute(
                        "UPDATE projects SET name=?, updated_at=? WHERE id=?",
                        (original, now, project_id),
                    )
                continue
            suffix = 2
            while True:
                marker = f" ({suffix})"
                candidate = f"{original[: max(1, 128 - len(marker))]}{marker}"
                candidate_key = candidate.casefold()
                if candidate_key not in occupied:
                    break
                suffix += 1
            occupied.add(candidate_key)
            retained.add(candidate_key)
            conn.execute(
                "UPDATE projects SET name=?, updated_at=? WHERE id=?",
                (candidate, now, project_id),
            )

    def _run_data_migration(self, conn: sqlite3.Connection, version: int) -> None:
        if version == 5:
            self._migrate_project_samples_to_batches(conn)
            self._deduplicate_project_names(conn)
            conn.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_name_nocase
                   ON projects(name COLLATE NOCASE)"""
            )
            return
        if version == 4:
            rows = conn.execute(
                """SELECT DISTINCT project_id, sample_name, MIN(timestamp) AS first_seen
                   FROM history_records
                   WHERE project_id IS NOT NULL AND TRIM(project_id) != ''
                     AND sample_name IS NOT NULL AND TRIM(sample_name) != ''
                   GROUP BY project_id, sample_name"""
            ).fetchall()
            for row in rows:
                sample_id = self._ensure_project_sample(
                    conn,
                    project_id=row["project_id"],
                    sample_name=row["sample_name"],
                    batch_id="",
                    timestamp=row["first_seen"],
                )
                conn.execute(
                    """UPDATE history_records SET sample_id=?
                       WHERE project_id=? AND sample_name=?""",
                    (sample_id, row["project_id"], row["sample_name"]),
                )
            return
        if version != 2:
            return
        rows = conn.execute("SELECT record_key, results FROM history_records").fetchall()
        for row in rows:
            raw_results = row["results"]
            try:
                results = json.loads(raw_results) if raw_results else {}
            except (json.JSONDecodeError, TypeError) as exc:
                raise DatabaseIntegrityError(
                    f"history record {row['record_key']} has invalid results JSON"
                ) from exc
            if not isinstance(results, dict):
                raise DatabaseIntegrityError(
                    f"history record {row['record_key']} results must be an object"
                )
            self._replace_history_metrics(conn, str(row["record_key"]), results)

        conversations = conn.execute(
            "SELECT conversation_id, messages FROM conversations"
        ).fetchall()
        for row in conversations:
            raw_messages = row["messages"]
            try:
                messages = json.loads(raw_messages) if raw_messages else []
            except (json.JSONDecodeError, TypeError) as exc:
                raise DatabaseIntegrityError(
                    f"conversation {row['conversation_id']} has invalid messages JSON"
                ) from exc
            if not isinstance(messages, list):
                raise DatabaseIntegrityError(
                    f"conversation {row['conversation_id']} messages must be a list"
                )
            for position, message in enumerate(messages):
                if not isinstance(message, dict):
                    raise DatabaseIntegrityError(
                        f"conversation {row['conversation_id']} message #{position} must be an object"
                    )
                self._insert_conversation_message(
                    conn,
                    str(row["conversation_id"]),
                    position,
                    message,
                )
            conn.execute(
                "UPDATE conversations SET messages='[]' WHERE conversation_id=?",
                (str(row["conversation_id"]),),
            )

    def _init_schema(self) -> None:
        conn = self._get_conn()
        current = 0
        if self._preexisting:
            check = [str(row[0]) for row in conn.execute("PRAGMA quick_check").fetchall()]
            if check != ["ok"]:
                raise DatabaseIntegrityError(f"database integrity check failed: {check}")
            app_tables_exist = conn.execute(
                """SELECT 1 FROM sqlite_master
                   WHERE type='table'
                     AND name IN ('history_records', 'projects', 'conversations', 'process_templates')
                   LIMIT 1"""
            ).fetchone()
            meta_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
            ).fetchone()
            if meta_exists:
                row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                if row is not None:
                    try:
                        current = int(row["value"])
                    except (TypeError, ValueError) as exc:
                        raise DatabaseVersionError("invalid database schema version") from exc
                elif app_tables_exist:
                    raise DatabaseVersionError("database schema version is missing")
            elif app_tables_exist:
                raise DatabaseVersionError("database metadata table is missing")
            if current > SCHEMA_VERSION:
                raise DatabaseVersionError(
                    f"database schema v{current} is newer than supported v{SCHEMA_VERSION}"
                )
            if current < SCHEMA_VERSION:
                self.create_backup(reason=f"pre-schema-v{current}-to-v{SCHEMA_VERSION}")

        conn.executescript(_CREATE_TABLES_SQL)
        if current == 0:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_sample ON history_records(sample_id)"
            )
            conn.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_name_nocase
                   ON projects(name COLLATE NOCASE)"""
            )
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            conn.commit()
            return

        if current < SCHEMA_VERSION:
            for ver in range(current + 1, SCHEMA_VERSION + 1):
                statements = _MIGRATIONS.get(ver)
                if not statements:
                    raise DatabaseVersionError(f"missing migration for schema v{ver}")
                with self.transaction() as migration_conn:
                    for sql in statements:
                        try:
                            migration_conn.execute(sql)
                        except sqlite3.OperationalError as exc:
                            duplicate_column = (
                                sql.lstrip().upper().startswith("ALTER TABLE")
                                and "duplicate column name" in str(exc).lower()
                            )
                            if not duplicate_column:
                                raise
                            _logger.info("Schema v%s column already exists; continuing idempotent migration", ver)
                    self._run_data_migration(migration_conn, ver)
                    migration_conn.execute(
                        "UPDATE meta SET value=? WHERE key='schema_version'",
                        (str(ver),),
                    )

    # ── History ────────────────────────────────────────────────────

    @staticmethod
    def _history_record_key(safe: Dict[str, Any]) -> str:
        file_value = safe.get("file_path") or safe.get("file_name") or safe.get("sample_name") or ""
        run_id = safe.get("run_id")
        if run_id:
            return f"{safe.get('timestamp', '')}|{safe.get('type', '')}|{file_value}|{run_id}"
        identity = _json_dumps(safe).encode("utf-8")
        digest = hashlib.sha256(identity).hexdigest()[:16]
        return f"{safe.get('timestamp', '')}|{safe.get('type', '')}|{file_value}|{digest}"

    @classmethod
    def _upsert_history_record(
        cls,
        conn: sqlite3.Connection,
        safe: Dict[str, Any],
    ) -> str:
        safe = dict(safe)
        # This metadata is written by the validated processing entrypoint, never
        # taken from an imported history record's arbitrary output paths.
        roots_row = conn.execute(
            "SELECT value FROM meta WHERE key=?",
            (RUN_ARCHIVE_ROOTS_PREFIX + str(safe.get("run_id") or ""),),
        ).fetchone()
        if roots_row:
            roots = _json_loads(roots_row["value"], {})
            if roots.get("input_root"):
                safe["folder_path"] = roots["input_root"]
        linked_sample_id = cls._ensure_project_sample(
            conn,
            project_id=safe.get("project_id"),
            sample_name=safe.get("sample_name"),
            batch_id=cls._sample_batch_identity(safe),
            timestamp=safe.get("timestamp"),
        )
        if linked_sample_id:
            safe["sample_id"] = linked_sample_id
        record_key = cls._history_record_key(safe)
        known_fields = {
            "timestamp",
            "type",
            "file_path",
            "file_name",
            "sample_name",
            "sample_id",
            "project_id",
            "run_id",
            "folder_path",
            "archived",
            "results",
            "output_files",
            "summary_path",
            "source_archive_path",
            "artifact_root",
            "artifact_owner",
            "quality_summary",
            "data",
        }
        stored_data = {
            "__history_payload_v2__": {
                "data": safe.get("data", {}),
                "extra": {key: value for key, value in safe.items() if key not in known_fields},
            }
        }
        conn.execute(
            """INSERT INTO history_records
               (record_key, timestamp, type, file_path, file_name, sample_name, sample_id,
                project_id, run_id, folder_path, archived, results, output_files,
                summary_path, source_archive_path, artifact_root, artifact_owner,
                quality_summary, data)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(record_key) DO UPDATE SET
                 timestamp=excluded.timestamp,
                 type=excluded.type,
                 file_path=excluded.file_path,
                 file_name=excluded.file_name,
                 sample_name=excluded.sample_name,
                 sample_id=excluded.sample_id,
                 project_id=excluded.project_id,
                 run_id=excluded.run_id,
                 folder_path=excluded.folder_path,
                 archived=excluded.archived,
                 results=excluded.results,
                 output_files=excluded.output_files,
                 summary_path=excluded.summary_path,
                 source_archive_path=excluded.source_archive_path,
                 artifact_root=excluded.artifact_root,
                 artifact_owner=excluded.artifact_owner,
                 quality_summary=excluded.quality_summary,
                 data=excluded.data""",
            (
                record_key,
                safe.get("timestamp"),
                safe.get("type"),
                safe.get("file_path"),
                safe.get("file_name"),
                safe.get("sample_name"),
                safe.get("sample_id"),
                safe.get("project_id"),
                safe.get("run_id"),
                safe.get("folder_path"),
                1 if safe.get("archived") else 0,
                _json_dumps(safe.get("results", {})),
                _json_dumps(safe.get("output_files", [])),
                safe.get("summary_path"),
                safe.get("source_archive_path"),
                safe.get("artifact_root"),
                safe.get("artifact_owner", "external"),
                _json_dumps(safe.get("quality_summary", {})),
                _json_dumps(stored_data),
            ),
        )
        cls._replace_history_metrics(conn, record_key, safe.get("results", {}))
        return record_key

    def add_history_record(self, record: Dict[str, Any]) -> None:
        safe = _to_json_safe(record)
        with self.transaction() as conn:
            self._upsert_history_record(conn, safe)

    def get_all_history_records(self) -> List[Dict[str, Any]]:
        with self.read() as conn:
            rows = conn.execute(
                """SELECT hr.*, ps.note AS sample_note, ps.tags AS sample_tags
                   FROM history_records AS hr
                   LEFT JOIN project_samples AS ps ON ps.id=hr.sample_id
                   ORDER BY hr.timestamp DESC"""
            ).fetchall()
        return [self._row_to_history_dict(row) for row in rows]

    @staticmethod
    def _encode_history_cursor(timestamp: Any, row_id: Any) -> str:
        payload = json.dumps(
            {"timestamp": str(timestamp or ""), "id": int(row_id)},
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_history_cursor(cursor: str) -> tuple[str, int]:
        raw = str(cursor or "").strip()
        if not raw:
            raise ValueError("history cursor is empty")
        try:
            padded = raw + "=" * (-len(raw) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
            timestamp = str(payload["timestamp"])
            row_id = int(payload["id"])
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("history cursor is invalid") from exc
        if row_id < 1:
            raise ValueError("history cursor is invalid")
        return timestamp, row_id

    @staticmethod
    def _history_filter_conditions(
        *,
        project_id: Optional[str] = None,
        include_archived: bool = False,
        data_type: Optional[str] = None,
        metric_key: Optional[str] = None,
        metric_min: Optional[float] = None,
        metric_max: Optional[float] = None,
        q: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> tuple[List[str], List[Any]]:
        conditions: List[str] = []
        params: List[Any] = []
        dates: Dict[str, str] = {}
        for name, value in (("date_from", date_from), ("date_to", date_to)):
            raw = str(value or "").strip()
            if not raw:
                continue
            try:
                parsed_date = date.fromisoformat(raw)
            except ValueError as exc:
                raise ValueError(f"{name} must be a valid YYYY-MM-DD date") from exc
            if len(raw) != 10 or parsed_date.isoformat() != raw:
                raise ValueError(f"{name} must be a valid YYYY-MM-DD date")
            dates[name] = raw
        if dates.get("date_from") and dates.get("date_to") and dates["date_from"] > dates["date_to"]:
            raise ValueError("date_from must not be later than date_to")
        if project_id:
            conditions.append("hr.project_id = ?")
            params.append(project_id)
        if not include_archived:
            conditions.append("hr.archived = 0")
        if data_type:
            conditions.append("UPPER(hr.type) = ?")
            params.append(data_type.strip().upper())
        search = str(q or "").strip()
        if search:
            pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            conditions.append(
                r"(COALESCE(hr.sample_name, '') LIKE ? ESCAPE '\' OR "
                r"history_basename(COALESCE(NULLIF(hr.file_name, ''), hr.file_path, '')) LIKE ? ESCAPE '\')"
            )
            params.extend((pattern, pattern))
        # History stores local wall-clock timestamps, both ISO T and space
        # separated. Compare their calendar date without UTC conversion.
        for name, operator in (("date_from", ">="), ("date_to", "<=")):
            if name in dates:
                conditions.append(f"SUBSTR(hr.timestamp, 1, 10) {operator} ?")
                params.append(dates[name])
        if metric_key and (metric_min is not None or metric_max is not None):
            metric_conditions = ["hm.record_key = hr.record_key", "hm.metric_key = ?"]
            params.append(str(metric_key))
            if metric_min is not None:
                metric_conditions.append("hm.metric_value >= ?")
                params.append(float(metric_min))
            if metric_max is not None:
                metric_conditions.append("hm.metric_value <= ?")
                params.append(float(metric_max))
            conditions.append(
                "EXISTS (SELECT 1 FROM history_metrics AS hm WHERE "
                + " AND ".join(metric_conditions)
                + ")"
            )
        return conditions, params

    def filter_history(
        self,
        *,
        project_id: Optional[str] = None,
        include_archived: bool = False,
        data_type: Optional[str] = None,
        metric_key: Optional[str] = None,
        metric_min: Optional[float] = None,
        metric_max: Optional[float] = None,
        limit: Optional[int] = 100,
        q: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        conditions, params = self._history_filter_conditions(
            project_id=project_id,
            include_archived=include_archived,
            data_type=data_type,
            metric_key=metric_key,
            metric_min=metric_min,
            metric_max=metric_max,
            q=q,
            date_from=date_from,
            date_to=date_to,
        )

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""SELECT hr.*, ps.note AS sample_note, ps.tags AS sample_tags
                  FROM history_records AS hr
                  LEFT JOIN project_samples AS ps ON ps.id=hr.sample_id
                  WHERE {where} ORDER BY hr.timestamp DESC"""
        if limit is not None:
            safe_limit = max(1, min(int(limit), 500))
            sql += " LIMIT ?"
            params.append(safe_limit)

        with self.read() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_history_dict(row) for row in rows]

    def filter_history_page(
        self,
        *,
        project_id: Optional[str] = None,
        include_archived: bool = False,
        data_type: Optional[str] = None,
        metric_key: Optional[str] = None,
        metric_min: Optional[float] = None,
        metric_max: Optional[float] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
        q: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return a lightweight keyset-paginated history page."""

        conditions, params = self._history_filter_conditions(
            project_id=project_id,
            include_archived=include_archived,
            data_type=data_type,
            metric_key=metric_key,
            metric_min=metric_min,
            metric_max=metric_max,
            q=q,
            date_from=date_from,
            date_to=date_to,
        )
        base_where = " AND ".join(conditions) if conditions else "1=1"
        page_conditions = list(conditions)
        page_params = list(params)
        if cursor:
            cursor_timestamp, cursor_id = self._decode_history_cursor(cursor)
            page_conditions.append(
                "(COALESCE(hr.timestamp, '') < ? OR "
                "(COALESCE(hr.timestamp, '') = ? AND hr.id < ?))"
            )
            page_params.extend((cursor_timestamp, cursor_timestamp, cursor_id))
        page_where = " AND ".join(page_conditions) if page_conditions else "1=1"
        safe_limit = max(1, min(int(limit), 100))
        columns = """hr.id, hr.record_key, hr.timestamp, hr.type, hr.file_path,
                     hr.file_name, hr.sample_name, hr.sample_id, hr.project_id, hr.run_id,
                     hr.folder_path, hr.archived, hr.results, hr.output_files,
                     hr.summary_path, hr.source_archive_path, hr.artifact_root,
                     hr.artifact_owner, hr.quality_summary,
                     ps.note AS sample_note, ps.tags AS sample_tags"""
        sql = f"""SELECT {columns}
                  FROM history_records AS hr
                  LEFT JOIN project_samples AS ps ON ps.id=hr.sample_id
                  WHERE {page_where}
                  ORDER BY COALESCE(hr.timestamp, '') DESC, hr.id DESC
                  LIMIT ?"""
        page_params.append(safe_limit + 1)
        with self.read() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS total FROM history_records AS hr WHERE {base_where}",
                params,
            ).fetchone()
            rows = conn.execute(sql, page_params).fetchall()
        has_more = len(rows) > safe_limit
        page_rows = rows[:safe_limit]
        records = [self._row_to_history_summary(row) for row in page_rows]
        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            next_cursor = self._encode_history_cursor(last["timestamp"], last["id"])
        return {
            "records": records,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total": int(total_row["total"] if total_row else 0),
            "limit": safe_limit,
        }

    def get_history_record(self, record_key: str) -> Optional[Dict[str, Any]]:
        with self.read() as conn:
            row = conn.execute(
                """SELECT hr.*, ps.note AS sample_note, ps.tags AS sample_tags
                   FROM history_records AS hr
                   LEFT JOIN project_samples AS ps ON ps.id=hr.sample_id
                   WHERE hr.record_key=?""",
                (str(record_key),),
            ).fetchone()
        return self._row_to_history_dict(row) if row else None

    def iter_history_archive_records(
        self,
        *,
        project_id: str,
        include_archived: bool = False,
        batch_size: int = 200,
    ) -> Generator[Dict[str, Any], None, None]:
        """Yield only path metadata needed by project ZIP export."""

        conditions, params = self._history_filter_conditions(
            project_id=project_id,
            include_archived=include_archived,
        )
        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""SELECT id, record_key, timestamp, type, file_path, file_name,
                         sample_name, project_id, run_id, folder_path, archived,
                         output_files, summary_path, source_archive_path,
                         artifact_root, artifact_owner,
                         (SELECT value FROM meta
                          WHERE key='run_archive_roots:' || hr.run_id) AS archive_roots
                  FROM history_records AS hr
                  WHERE {where}
                  ORDER BY COALESCE(timestamp, '') DESC, id DESC"""
        with self.read() as conn:
            query = conn.execute(sql, params)
            while True:
                rows = query.fetchmany(max(1, min(int(batch_size), 1000)))
                if not rows:
                    break
                for row in rows:
                    record = self._row_to_history_summary(row)
                    record["archive_roots"] = _json_loads(record.get("archive_roots"), {})
                    yield record

    def update_history_by_key(self, record_key: str, action: str) -> int:
        with self.transaction() as conn:
            if action == "delete" and not conn.in_transaction:
                conn.execute("BEGIN IMMEDIATE")
            matched_key = str(record_key)
            exact = conn.execute(
                "SELECT record_key FROM history_records WHERE record_key=?",
                (matched_key,),
            ).fetchone()
            if exact is None:
                legacy_rows = conn.execute(
                    """SELECT record_key FROM history_records
                       WHERE timestamp || '|' || type || '|' ||
                         COALESCE(NULLIF(file_path, ''), NULLIF(file_name, ''),
                                  NULLIF(sample_name, ''), '') = ?
                       LIMIT 2""",
                    (matched_key,),
                ).fetchall()
                if len(legacy_rows) != 1:
                    if len(legacy_rows) > 1:
                        _logger.warning("Refusing ambiguous legacy history key: %s", matched_key)
                    return 0
                matched_key = str(legacy_rows[0]["record_key"])

            if action == "archive":
                cur = conn.execute(
                    "UPDATE history_records SET archived=1 WHERE record_key=?", (matched_key,)
                )
                return cur.rowcount
            elif action == "delete":
                from electrochem_v6.store.replicate_groups import mark_deleted_replicate_records

                mark_deleted_replicate_records(conn, [matched_key])
                deleted_row = conn.execute("SELECT run_id FROM history_records WHERE record_key=?", (matched_key,)).fetchone()
                cur = conn.execute(
                    "DELETE FROM history_records WHERE record_key=?", (matched_key,)
                )
                if deleted_row and deleted_row["run_id"]:
                    recipe_key = "run_recipe:" + str(deleted_row["run_id"])
                    recipe_row = conn.execute("SELECT value FROM meta WHERE key=?", (recipe_key,)).fetchone()
                    recipe = _json_loads(recipe_row["value"], {}) if recipe_row else {}
                    if isinstance(recipe, dict) and recipe:
                        remaining = conn.execute("SELECT record_key FROM history_records WHERE run_id=?", (deleted_row["run_id"],)).fetchall()
                        remaining_keys = {row["record_key"] for row in remaining}
                        if not remaining_keys and "COUPLED" not in (recipe.get("data_types") or []):
                            conn.execute("DELETE FROM meta WHERE key=?", (recipe_key,))
                        else:
                            recipe["history_partially_deleted"] = True
                            recipe["deleted_record_keys"] = list(dict.fromkeys([*(recipe.get("deleted_record_keys") or []), matched_key]))
                            recipe["records"] = [item for item in recipe.get("records") or [] if item.get("record_key") in remaining_keys]
                            recipe["record_keys"] = [key for key in recipe.get("record_keys") or [] if key in remaining_keys]
                            conn.execute("UPDATE meta SET value=? WHERE key=?", (_json_dumps(recipe), recipe_key))
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

    def attach_run_provenance(
        self,
        run_id: str,
        *,
        source_archive_path: Optional[str] = None,
        artifact_root: Optional[str] = None,
        artifact_owner: str = "application",
    ) -> int:
        """Attach stable source and managed-artifact metadata to a completed run."""

        with self.transaction() as conn:
            cur = conn.execute(
                """UPDATE history_records
                   SET source_archive_path=?, artifact_root=?, artifact_owner=?
                   WHERE run_id=?""",
                (
                    source_archive_path,
                    artifact_root,
                    str(artifact_owner or "application"),
                    str(run_id),
                ),
            )
            return cur.rowcount

    @staticmethod
    def _pending_upload_roots(conn: sqlite3.Connection, project_id: Optional[str] = None) -> set[str]:
        # Queued uploads have a durable request but no run recipe yet. An exited
        # owner's lease no longer protects their archive from storage maintenance.
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='processing_recovery'").fetchone():
            return set()
        roots: set[str] = set()
        for row in conn.execute("SELECT payload FROM processing_recovery WHERE kind='process'"):
            payload = _json_loads(row["payload"], {})
            if not isinstance(payload, dict) or (project_id is not None and payload.get("project_id") != project_id):
                continue
            prepared = payload.get("_prepared_upload")
            source = payload.get("_upload_source")
            if isinstance(prepared, dict) and prepared.get("run_root"):
                roots.add(str(prepared["run_root"]))
            if isinstance(source, dict) and source.get("artifact_root"):
                roots.add(str(source["artifact_root"]))
        return roots

    def get_managed_artifact_roots(self, project_id: Optional[str] = None) -> List[str]:
        conditions = ["artifact_owner='application'", "artifact_root IS NOT NULL", "TRIM(artifact_root)!=''"]
        params: List[Any] = []
        if project_id:
            conditions.append("project_id=?")
            params.append(str(project_id))
        with self.read() as conn:
            rows = conn.execute(
                f"""SELECT DISTINCT artifact_root FROM history_records
                    WHERE {' AND '.join(conditions)} ORDER BY artifact_root""",
                params,
            ).fetchall()
            recipe_rows = conn.execute("SELECT value FROM meta WHERE key LIKE 'run_recipe:%'").fetchall()
            pending_roots = self._pending_upload_roots(conn, project_id)
        roots = {str(row["artifact_root"]) for row in rows} | pending_roots
        for row in recipe_rows:
            recipe = _json_loads(row["value"], {})
            if isinstance(recipe, dict) and (project_id is None or recipe.get("project_id") == project_id):
                for key in ("artifact_root", "replay_cache_root"):
                    if recipe.get(key):
                        roots.add(str(recipe[key]))
        return sorted(roots)

    def count_artifact_root_references(self, artifact_root: str) -> int:
        with self.read() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM history_records WHERE artifact_root=?",
                (str(artifact_root),),
            ).fetchone()
            recipe_rows = conn.execute("SELECT value FROM meta WHERE key LIKE 'run_recipe:%'").fetchall()
            pending_roots = self._pending_upload_roots(conn)
        references = int(row["total"] if row else 0) + int(str(artifact_root) in pending_roots)
        for recipe_row in recipe_rows:
            recipe = _json_loads(recipe_row["value"], {})
            if isinstance(recipe, dict) and str(artifact_root) in {
                str(recipe.get("artifact_root") or ""), str(recipe.get("replay_cache_root") or ""),
            }:
                references += 1
        return references

    def get_lsv_records(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        conditions = ["UPPER(hr.type) = 'LSV'"]
        params: List[Any] = []
        if project_id:
            conditions.append("hr.project_id = ?")
            params.append(project_id)
        where = " AND ".join(conditions)
        with self.read() as conn:
            rows = conn.execute(
                f"""SELECT hr.*, ps.note AS sample_note, ps.tags AS sample_tags
                    FROM history_records AS hr
                    LEFT JOIN project_samples AS ps ON ps.id=hr.sample_id
                    WHERE {where}""",
                params,
            ).fetchall()
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
                SUM(CASE WHEN UPPER(type)='ECSA' THEN 1 ELSE 0 END) as ecsa_count,
                SUM(CASE WHEN UPPER(type)='COUPLED' THEN 1 ELSE 0 END) as coupled_count
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
            "coupled_count": row["coupled_count"] or 0,
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
        if "sample_tags" in d:
            d["sample_tags"] = _json_loads(d.get("sample_tags"), [])
        stored_data = _json_loads(d.get("data"), {})
        envelope = stored_data.get("__history_payload_v2__") if isinstance(stored_data, dict) else None
        if isinstance(envelope, dict):
            d["data"] = envelope.get("data", {})
            extra = envelope.get("extra", {})
            if isinstance(extra, dict):
                for key, value in extra.items():
                    if key not in d:
                        d[key] = value
        else:
            d["data"] = stored_data
        d["archived"] = bool(d.get("archived"))
        d.pop("id", None)
        return d

    @staticmethod
    def _row_to_history_summary(row: sqlite3.Row) -> Dict[str, Any]:
        d = {key: row[key] for key in row.keys()}
        d["results"] = _json_loads(d.get("results"), {})
        d["output_files"] = _json_loads(d.get("output_files"), [])
        d["quality_summary"] = _json_loads(d.get("quality_summary"), {})
        if "sample_tags" in d:
            d["sample_tags"] = _json_loads(d.get("sample_tags"), [])
        d["archived"] = bool(d.get("archived"))
        d["detail_available"] = True
        d.pop("id", None)
        return d

    # ── Project samples ───────────────────────────────────────────

    @staticmethod
    def _row_to_project_sample_dict(row: sqlite3.Row) -> Dict[str, Any]:
        item = {key: row[key] for key in row.keys()}
        item["tags"] = _json_loads(item.get("tags"), [])
        raw_types = str(item.get("data_types") or "")
        item["data_types"] = [value for value in raw_types.split(",") if value]
        item["data_count"] = int(item.get("data_count") or 0)
        return item

    def list_project_samples(
        self,
        project_id: str,
        *,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        archived_join = "" if include_archived else "AND hr.archived=0"
        with self.read() as conn:
            rows = conn.execute(
                f"""SELECT ps.*,
                           COUNT(hr.record_key) AS data_count,
                           MAX(hr.timestamp) AS latest_at,
                           GROUP_CONCAT(DISTINCT UPPER(hr.type)) AS data_types
                    FROM project_samples AS ps
                    LEFT JOIN history_records AS hr
                      ON hr.sample_id=ps.id {archived_join}
                    WHERE ps.project_id=?
                    GROUP BY ps.id
                    ORDER BY COALESCE(latest_at, ps.updated_at, ps.created_at) DESC, ps.name""",
                (str(project_id),),
            ).fetchall()
        return [self._row_to_project_sample_dict(row) for row in rows]

    def get_project_sample(self, project_id: str, sample_id: str) -> Optional[Dict[str, Any]]:
        with self.read() as conn:
            row = conn.execute(
                "SELECT * FROM project_samples WHERE project_id=? AND id=?",
                (str(project_id), str(sample_id)),
            ).fetchone()
        return self._row_to_project_sample_dict(row) if row else None

    def update_project_sample(
        self,
        project_id: str,
        sample_id: str,
        *,
        note: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        sets: List[str] = []
        params: List[Any] = []
        if note is not None:
            sets.append("note=?")
            params.append(str(note))
        if tags is not None:
            sets.append("tags=?")
            params.append(_json_dumps(tags))
        if not sets:
            return False
        sets.append("updated_at=?")
        params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        params.extend((str(project_id), str(sample_id)))
        with self.transaction() as conn:
            cur = conn.execute(
                f"UPDATE project_samples SET {', '.join(sets)} WHERE project_id=? AND id=?",
                params,
            )
        return cur.rowcount > 0

    # ── Projects ──────────────────────────────────────────────────

    def create_project(self, project: Dict[str, Any]) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO projects
                   (id, name, description, created_at, updated_at, status, tags, file_count, color,
                    default_template_name)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
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
                    project.get("default_template_name") or "",
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
        allowed = {"name", "description", "tags", "color", "status", "default_template_name"}
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

    def delete_project(self, project_id: str, *, hard: bool = False) -> bool:
        with self.transaction() as conn:
            if hard:
                from electrochem_v6.store.replicate_groups import cleanup_project_replicates

                if not conn.in_transaction:
                    conn.execute("BEGIN IMMEDIATE")
                cleanup_project_replicates(conn, project_id)
                cur = conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            else:
                cur = conn.execute(
                    "UPDATE projects SET status='archived', updated_at=? WHERE id=? AND status!='archived'",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), project_id),
                )
            return cur.rowcount > 0

    def purge_project(self, project_id: str) -> Dict[str, int]:
        """Permanently remove a project and its linked history in one transaction."""

        with self.transaction() as conn:
            from electrochem_v6.store.replicate_groups import cleanup_project_replicates

            if not conn.in_transaction:
                conn.execute("BEGIN IMMEDIATE")
            cleanup_project_replicates(conn, str(project_id))
            history_row = conn.execute(
                "SELECT COUNT(*) AS total FROM history_records WHERE project_id=?",
                (str(project_id),),
            ).fetchone()
            conn.execute("DELETE FROM history_records WHERE project_id=?", (str(project_id),))
            conn.execute("DELETE FROM project_samples WHERE project_id=?", (str(project_id),))
            recipe_rows = conn.execute("SELECT key, value FROM meta WHERE key LIKE 'run_recipe:%'").fetchall()
            for row in recipe_rows:
                recipe = _json_loads(row["value"], {})
                if isinstance(recipe, dict) and recipe.get("project_id") == project_id:
                    conn.execute("DELETE FROM meta WHERE key=?", (row["key"],))
            project_cur = conn.execute("DELETE FROM projects WHERE id=?", (str(project_id),))
            conn.execute(
                "UPDATE projects_meta SET value=NULL WHERE key='default_project' AND value=?",
                (str(project_id),),
            )
        return {
            "projects": max(0, project_cur.rowcount),
            "history_records": int(history_row["total"] if history_row else 0),
        }

    def get_default_project(self) -> Optional[str]:
        with self.transaction() as conn:
            row = conn.execute(
                """SELECT pm.value
                   FROM projects_meta AS pm
                   JOIN projects AS p ON p.id = pm.value AND p.status='active'
                   WHERE pm.key='default_project'"""
            ).fetchone()
            if row and row["value"]:
                return str(row["value"])
            first = conn.execute(
                "SELECT id FROM projects WHERE status='active' ORDER BY created_at, id LIMIT 1"
            ).fetchone()
            fallback = str(first["id"]) if first else None
            conn.execute(
                """INSERT INTO projects_meta (key, value) VALUES ('default_project', ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (fallback,),
            )
            return fallback

    def set_default_project(self, project_id: Optional[str]) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO projects_meta (key, value) VALUES ('default_project', ?)",
                (project_id,),
            )

    def repair_orphan_project_links(self) -> List[str]:
        """Create archived project tombstones for history that references missing projects."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.transaction() as conn:
            rows = conn.execute(
                """SELECT DISTINCT hr.project_id
                   FROM history_records AS hr
                   LEFT JOIN projects AS p ON p.id = hr.project_id
                   WHERE hr.project_id IS NOT NULL
                     AND TRIM(hr.project_id) != ''
                     AND p.id IS NULL
                   ORDER BY hr.project_id"""
            ).fetchall()
            project_ids = [str(row["project_id"]) for row in rows]
            for project_id in project_ids:
                conn.execute(
                    """INSERT INTO projects
                       (id, name, description, created_at, updated_at, status, tags, file_count, color)
                       VALUES (?,?,?,?,?,'archived',?,0,?)""",
                    (
                        project_id,
                        f"Recovered project {project_id[:12]}",
                        "Automatically restored because history records reference this missing project.",
                        now,
                        now,
                        _json_dumps(["recovered", "missing-project"]),
                        "#78909C",
                    ),
                )
        return project_ids

    def _row_to_project_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        for key in row.keys():
            d[key] = row[key]
        d["tags"] = _json_loads(d.get("tags"), [])
        d["default_template_name"] = str(d.get("default_template_name") or "")
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
            if row is None:
                return None
            message_rows = conn.execute(
                """SELECT role, content, timestamp, metadata, attachments
                   FROM conversation_messages
                   WHERE conversation_id=? ORDER BY position""",
                (conversation_id,),
            ).fetchall()
        conversation = self._row_to_conversation_dict(row, include_messages=False)
        if message_rows:
            conversation["messages"] = [self._row_to_message_dict(item) for item in message_rows]
        else:
            conversation["messages"] = _json_loads(row["messages"], [])
        return conversation

    def delete_conversation(self, conversation_id: str) -> bool:
        cid = str(conversation_id or "").strip()
        with self.transaction() as conn:
            cur = conn.execute(
                "DELETE FROM conversations WHERE conversation_id=?", (cid,)
            )
            job_rows = conn.execute(
                "SELECT job_id, payload, result FROM processing_jobs WHERE kind='agent'"
            ).fetchall()
            stale_job_ids: list[str] = []
            for row in job_rows:
                payload = _json_loads(row["payload"], {})
                result = _json_loads(row["result"], {})
                result_conversation = result.get("conversation") if isinstance(result, dict) else None
                linked_ids = {
                    str(payload.get("conversation_id") or "")
                    if isinstance(payload, dict)
                    else "",
                    str(result.get("conversation_id") or "")
                    if isinstance(result, dict)
                    else "",
                    str(result_conversation.get("conversation_id") or "")
                    if isinstance(result_conversation, dict)
                    else "",
                }
                if cid in linked_ids:
                    stale_job_ids.append(str(row["job_id"]))
            if stale_job_ids:
                conn.executemany(
                    "DELETE FROM processing_jobs WHERE job_id=?",
                    [(job_id,) for job_id in stale_job_ids],
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
                "SELECT conversation_id FROM conversations WHERE conversation_id=?", (cid,)
            ).fetchone()

            if row is None:
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
                        "[]",
                    ),
                )
            else:
                updates = {
                    "updated_at": now,
                    "last_message_excerpt": content[:120],
                    "last_message_role": str(role or "user"),
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
            conn.execute(
                """INSERT INTO conversation_messages
                   (conversation_id, position, role, content, timestamp, metadata, attachments)
                   SELECT ?, COALESCE(MAX(position), -1) + 1, ?, ?, ?, ?, ?
                   FROM conversation_messages WHERE conversation_id=?""",
                (
                    cid,
                    message["role"],
                    message["content"],
                    message["timestamp"],
                    _json_dumps(message["metadata"]),
                    _json_dumps(message["attachments"]),
                    cid,
                ),
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
        else:
            d.pop("messages", None)
        return d

    @staticmethod
    def _row_to_message_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "role": row["role"],
            "content": row["content"],
            "timestamp": row["timestamp"],
            "metadata": _json_loads(row["metadata"], {}),
            "attachments": _json_loads(row["attachments"], []),
        }

    # ── Background processing jobs ────────────────────────────────

    def create_processing_job(
        self,
        job_id: str,
        *,
        kind: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO processing_jobs
                   (job_id, kind, status, payload, result, progress_current,
                    progress_total, cancel_requested, created_at, updated_at)
                   VALUES (?, ?, 'queued', ?, '{}', 0, 0, 0, ?, ?)""",
                (str(job_id), str(kind or "process"), _json_dumps(payload), now, now),
            )
        return self.get_processing_job(job_id) or {}

    def update_processing_job(self, job_id: str, **updates: Any) -> bool:
        allowed = {
            "status",
            "payload",
            "result",
            "error",
            "progress_current",
            "progress_total",
            "current_item",
            "cancel_requested",
            "started_at",
            "finished_at",
        }
        values = {key: value for key, value in updates.items() if key in allowed}
        if not values:
            return False
        for json_field in ("payload", "result"):
            if json_field in values:
                values[json_field] = _json_dumps(values[json_field] or {})
        if "cancel_requested" in values:
            values["cancel_requested"] = int(bool(values["cancel_requested"]))
        values["updated_at"] = datetime.now().isoformat()
        assignments = ", ".join(f"{key}=?" for key in values)
        params = [*values.values(), str(job_id)]
        with self.transaction() as conn:
            cur = conn.execute(
                f"UPDATE processing_jobs SET {assignments} WHERE job_id=?",
                params,
            )
            return cur.rowcount > 0

    def get_processing_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self.read() as conn:
            row = conn.execute(
                "SELECT * FROM processing_jobs WHERE job_id=?",
                (str(job_id),),
            ).fetchone()
        return self._row_to_processing_job(row) if row else None

    def list_processing_jobs(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with self.read() as conn:
            rows = conn.execute(
                """SELECT * FROM processing_jobs
                   ORDER BY COALESCE(created_at, '') DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
        return [self._row_to_processing_job(row) for row in rows]

    def prune_processing_jobs(
        self,
        *,
        kind: Optional[str] = None,
        keep: int = DEFAULT_PROCESSING_JOB_RETENTION,
    ) -> int:
        """Keep only the newest terminal jobs, never deleting queued/running work."""

        safe_keep = max(0, int(keep))
        params: list[Any] = []
        conditions = ["status NOT IN ('queued', 'running')"]
        if kind:
            conditions.append("kind=?")
            params.append(str(kind))
        where = " AND ".join(conditions)
        with self.transaction() as conn:
            rows = conn.execute(
                f"""SELECT job_id FROM processing_jobs
                    WHERE {where}
                    ORDER BY COALESCE(created_at, '') DESC, job_id DESC""",
                params,
            ).fetchall()
            stale = [str(row["job_id"]) for row in rows[safe_keep:]]
            if stale:
                conn.executemany(
                    "DELETE FROM processing_jobs WHERE job_id=?",
                    [(job_id,) for job_id in stale],
                )
        return len(stale)

    def request_processing_job_cancel(self, job_id: str) -> bool:
        now = datetime.now().isoformat()
        with self.transaction() as conn:
            cur = conn.execute(
                """UPDATE processing_jobs
                   SET cancel_requested=1, updated_at=?
                   WHERE job_id=? AND status IN ('queued', 'running')""",
                (now, str(job_id)),
            )
            return cur.rowcount > 0

    def interrupt_active_processing_jobs(self) -> int:
        now = datetime.now().isoformat()
        with self.transaction() as conn:
            cur = conn.execute(
                """UPDATE processing_jobs
                   SET status='interrupted', error='application restarted before completion',
                       finished_at=?, updated_at=?
                   WHERE status IN ('queued', 'running')""",
                (now, now),
            )
            return cur.rowcount

    @staticmethod
    def _row_to_processing_job(row: sqlite3.Row) -> Dict[str, Any]:
        item = {key: row[key] for key in row.keys()}
        item["payload"] = _json_loads(item.get("payload"), {})
        item["result"] = _json_loads(item.get("result"), {})
        item["cancel_requested"] = bool(item.get("cancel_requested"))
        item["progress_current"] = int(item.get("progress_current") or 0)
        item["progress_total"] = int(item.get("progress_total") or 0)
        return item

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

    def migrate_process_templates_from_json(self, templates_file: Optional[str]) -> Dict[str, Any]:
        """Import the last JSON-backed template state exactly once.

        Earlier releases copied templates into SQLite during the general JSON
        migration but continued writing the JSON file afterwards.  This
        dedicated marker lets the first SQLite-only release import that newer
        file even when ``json_migrated`` is already present.
        """

        report: Dict[str, Any] = {
            "complete": False,
            "already_migrated": False,
            "templates": 0,
            "ignored": 0,
            "errors": [],
        }
        with self.read() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key=?",
                (PROCESS_TEMPLATE_JSON_MIGRATION_KEY,),
            ).fetchone()
        if row is not None:
            report["complete"] = True
            report["already_migrated"] = True
            return report

        normalized: list[Dict[str, Any]] = []
        source = str(templates_file or "").strip()
        if source:
            if not os.path.isfile(source):
                report["errors"].append(f"templates: file not found: {source}")
                return report
            try:
                with open(source, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except Exception as exc:
                report["errors"].append(f"templates: cannot read JSON: {exc}")
                return report
            templates = payload.get("templates") if isinstance(payload, dict) else None
            if not isinstance(templates, list):
                report["errors"].append("templates: expected a templates list")
                return report
            for index, template in enumerate(templates):
                if isinstance(template, dict) and template.get("builtin"):
                    report["ignored"] += 1
                    continue
                if (
                    not isinstance(template, dict)
                    or not str(template.get("name") or "").strip()
                    or not isinstance(template.get("state"), dict)
                ):
                    report["errors"].append(
                        f"templates: template #{index} has an invalid name or state"
                    )
                    continue
                normalized.append(_to_json_safe(template))
            if report["errors"]:
                return report

        audit = {
            "migrated_at": datetime.now().isoformat(),
            "source": source or None,
            "templates": len(normalized),
        }
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key=?",
                (PROCESS_TEMPLATE_JSON_MIGRATION_KEY,),
            ).fetchone()
            if row is not None:
                report["complete"] = True
                report["already_migrated"] = True
                return report
            for template in normalized:
                cursor = conn.execute(
                    """INSERT INTO process_templates (name, builtin, updated_at, state)
                       VALUES (?,0,?,?)
                       ON CONFLICT(name) DO UPDATE SET
                           updated_at=excluded.updated_at,
                           state=excluded.state
                       WHERE process_templates.builtin=0""",
                    (
                        str(template["name"]).strip(),
                        str(template.get("updated_at") or ""),
                        _json_dumps(template["state"]),
                    ),
                )
                report["templates"] += max(0, cursor.rowcount)
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                (PROCESS_TEMPLATE_JSON_MIGRATION_KEY, _json_dumps(audit)),
            )
        report["complete"] = True
        return report

    # ── Migration from JSON ───────────────────────────────────────

    def migrate_from_json(
        self,
        history_file: Optional[str] = None,
        projects_file: Optional[str] = None,
        conversations_file: Optional[str] = None,
        templates_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate and atomically import legacy JSON files into SQLite."""
        report: Dict[str, Any] = {
            "history": 0,
            "projects": 0,
            "conversations": 0,
            "templates": 0,
            "complete": False,
            "errors": [],
            "skipped": {"history": 0, "projects": 0, "conversations": 0, "templates": 0},
            "ignored": {"templates": 0},
            "renamed_projects": [],
        }
        errors: List[str] = report["errors"]
        skipped: Dict[str, int] = report["skipped"]
        ignored: Dict[str, int] = report["ignored"]
        supplied = {
            "history": history_file,
            "projects": projects_file,
            "conversations": conversations_file,
            "templates": templates_file,
        }
        payloads: Dict[str, Any] = {}

        for source, filepath in supplied.items():
            if not filepath:
                continue
            if not os.path.isfile(filepath):
                errors.append(f"{source}: file not found: {filepath}")
                continue
            try:
                with open(filepath, "r", encoding="utf-8") as handle:
                    payloads[source] = json.load(handle)
            except Exception as exc:
                errors.append(f"{source}: cannot read JSON: {exc}")

        normalized: Dict[str, Any] = {
            "history": [],
            "projects": [],
            "conversations": [],
            "templates": [],
            "default_project": None,
        }

        if "history" in payloads:
            payload = payloads["history"]
            records = payload.get("records") if isinstance(payload, dict) else payload
            if not isinstance(records, list):
                errors.append("history: expected a records list")
            else:
                for index, record in enumerate(records):
                    if not isinstance(record, dict):
                        skipped["history"] += 1
                        errors.append(f"history: record #{index} is not an object")
                    else:
                        normalized["history"].append(_to_json_safe(record))

        if "projects" in payloads:
            payload = payloads["projects"]
            projects = payload.get("projects") if isinstance(payload, dict) else None
            if not isinstance(projects, list):
                errors.append("projects: expected a projects list")
            else:
                normalized["default_project"] = payload.get("default_project")
                occupied_names = {
                    str(item.get("name") or "").strip().casefold()
                    for item in self.get_all_projects("all")
                }
                for index, project in enumerate(projects):
                    if (
                        not isinstance(project, dict)
                        or not str(project.get("id") or "").strip()
                        or not str(project.get("name") or "").strip()
                    ):
                        skipped["projects"] += 1
                        errors.append(f"projects: project #{index} is missing id or name")
                    else:
                        if not isinstance(project.get("default_template_name", ""), str):
                            skipped["projects"] += 1
                            errors.append(f"projects: project #{index} default_template_name must be a string")
                            continue
                        safe_project = _to_json_safe(project)
                        safe_project["default_template_name"] = project.get("default_template_name", "").strip()
                        original_name = str(safe_project.get("name") or "").strip()
                        candidate = original_name
                        suffix = 2
                        while candidate.casefold() in occupied_names:
                            marker = f" ({suffix})"
                            candidate = f"{original_name[: max(1, 128 - len(marker))]}{marker}"
                            suffix += 1
                        if candidate != original_name:
                            report["renamed_projects"].append(
                                {
                                    "id": str(safe_project.get("id") or ""),
                                    "from": original_name,
                                    "to": candidate,
                                }
                            )
                        safe_project["name"] = candidate
                        occupied_names.add(candidate.casefold())
                        normalized["projects"].append(safe_project)

        if "conversations" in payloads:
            payload = payloads["conversations"]
            conversations = payload.get("conversations") if isinstance(payload, dict) else None
            if not isinstance(conversations, list):
                errors.append("conversations: expected a conversations list")
            else:
                for index, conversation in enumerate(conversations):
                    messages = conversation.get("messages", []) if isinstance(conversation, dict) else None
                    if (
                        not isinstance(conversation, dict)
                        or not str(conversation.get("conversation_id") or "").strip()
                        or not isinstance(messages, list)
                        or any(not isinstance(message, dict) for message in messages)
                    ):
                        skipped["conversations"] += 1
                        errors.append(
                            f"conversations: conversation #{index} has an invalid id or messages list"
                        )
                    else:
                        normalized["conversations"].append(_to_json_safe(conversation))

        if "templates" in payloads:
            payload = payloads["templates"]
            templates = payload.get("templates") if isinstance(payload, dict) else None
            if not isinstance(templates, list):
                errors.append("templates: expected a templates list")
            else:
                for index, template in enumerate(templates):
                    if isinstance(template, dict) and template.get("builtin"):
                        ignored["templates"] += 1
                        continue
                    if (
                        not isinstance(template, dict)
                        or not str(template.get("name") or "").strip()
                        or not isinstance(template.get("state"), dict)
                    ):
                        skipped["templates"] += 1
                        errors.append(f"templates: template #{index} has an invalid name or state")
                    else:
                        normalized["templates"].append(_to_json_safe(template))

        if errors:
            _logger.warning("JSON migration validation failed: %s", errors)
            return report

        existing_sources = [path for path in supplied.values() if path and os.path.isfile(path)]
        if existing_sources:
            report["backup_path"] = self.create_backup(reason="pre-json-migration")

        try:
            with self.transaction() as conn:
                for record in normalized["history"]:
                    record_key = self._history_record_key(record)
                    existed = conn.execute(
                        "SELECT 1 FROM history_records WHERE record_key=?", (record_key,)
                    ).fetchone()
                    self._upsert_history_record(conn, record)
                    if existed is None:
                        report["history"] += 1

                for project in normalized["projects"]:
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO projects
                           (id, name, description, created_at, updated_at, status, tags, file_count, color,
                            default_template_name)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
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
                            project.get("default_template_name") or "",
                        ),
                    )
                    report["projects"] += max(0, cur.rowcount)

                default_project = normalized["default_project"]
                if default_project:
                    conn.execute(
                        """INSERT INTO projects_meta (key, value) VALUES ('default_project', ?)
                           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                        (default_project,),
                    )

                for conversation in normalized["conversations"]:
                    cid = str(conversation["conversation_id"])
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO conversations
                           (conversation_id, title, project_name, data_type, provider, model,
                            created_at, updated_at, last_message_excerpt, last_message_role, messages)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            cid,
                            conversation.get("title"),
                            conversation.get("project_name"),
                            conversation.get("data_type"),
                            conversation.get("provider"),
                            conversation.get("model"),
                            conversation.get("created_at"),
                            conversation.get("updated_at"),
                            conversation.get("last_message_excerpt"),
                            conversation.get("last_message_role"),
                            "[]",
                        ),
                    )
                    report["conversations"] += max(0, cur.rowcount)
                    for position, message in enumerate(conversation.get("messages", [])):
                        self._insert_conversation_message(conn, cid, position, message)

                for template in normalized["templates"]:
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO process_templates
                           (name, builtin, updated_at, state) VALUES (?,0,?,?)""",
                        (
                            str(template["name"]).strip(),
                            template.get("updated_at", ""),
                            _json_dumps(template["state"]),
                        ),
                    )
                    report["templates"] += max(0, cur.rowcount)

                audit = {
                    "migrated_at": datetime.now().isoformat(),
                    "counts": {key: report[key] for key in ("history", "projects", "conversations", "templates")},
                    "sources": [str(path) for path in existing_sources],
                }
                conn.execute(
                    """INSERT INTO meta (key, value) VALUES ('json_migrated', ?)
                       ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                    (_json_dumps(audit),),
                )
        except Exception as exc:
            errors.append(f"transaction failed: {exc}")
            _logger.exception("JSON migration transaction failed")
            return report

        report["complete"] = True
        _logger.info("SQLite migration complete: %s", report)
        return report

    def is_migrated(self) -> bool:
        with self.read() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='json_migrated'").fetchone()
            return row is not None
