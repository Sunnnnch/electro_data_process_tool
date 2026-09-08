"""SQLite runtime stores and database lifecycle management."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from electrochem_v6.config import (
    ensure_parent_dir,
    get_conversation_file,
    get_history_file,
    get_projects_file,
    get_templates_file,
)

from .database import Database

_logger = logging.getLogger(__name__)

_RUNTIME_LOCK = threading.RLock()
_DATABASE_INIT_LOCK = threading.Lock()
_database: Database | None = None
_history_store: HistoryStore | None = None
_project_store: ProjectStore | None = None
_conversation_store: ConversationStore | None = None


def _same_path(current: str, expected: Path) -> bool:
    try:
        return Path(current).resolve() == expected.resolve()
    except (OSError, ValueError):
        return str(current) == str(expected)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _database_path() -> Path:
    data_dir = ensure_parent_dir(get_history_file()).parent
    return data_dir / "electrochem_v6.db"


def _aggregate_lsv_summary(records: list[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: dict[str, list[Dict[str, Any]]] = {}
    for record in records:
        sample_name = str(
            record.get("sample_name") or record.get("file_name") or "Unknown"
        ).strip() or "Unknown"
        grouped.setdefault(sample_name, []).append(record)

    samples: list[Dict[str, Any]] = []
    for sample_name, items in grouped.items():
        potentials: list[float] = []
        overpotentials: list[float] = []
        tafel_slopes: list[float] = []
        latest_time = ""
        for item in items:
            latest_time = max(latest_time, str(item.get("timestamp") or ""))
            results = item.get("results") or {}
            if not isinstance(results, dict):
                continue
            for key, bucket in (
                ("potential_10", potentials),
                ("overpotential_10", overpotentials),
                ("tafel_slope", tafel_slopes),
            ):
                try:
                    if results.get(key) is not None:
                        bucket.append(float(results[key]))
                except (TypeError, ValueError):
                    continue
        samples.append(
            {
                "sample_name": sample_name,
                "potential_10": sum(potentials) / len(potentials) if potentials else None,
                "overpotential_10": (
                    sum(overpotentials) / len(overpotentials) if overpotentials else None
                ),
                "tafel_slope": sum(tafel_slopes) / len(tafel_slopes) if tafel_slopes else None,
                "record_count": len(items),
                "latest_time": latest_time,
            }
        )
    return {"samples": samples, "total_count": len(records)}


def reset_runtime() -> None:
    """Close all runtime connections and clear store singletons."""

    global _database, _history_store, _project_store, _conversation_store
    # Reset cannot race initialization and then lose a newly published instance.
    with _DATABASE_INIT_LOCK, _RUNTIME_LOCK:
        database = _database
        _database = None
        _history_store = None
        _project_store = None
        _conversation_store = None
    # Active DB contexts may need runtime stores before they can finish. Never
    # hold a singleton lock while waiting for their connection lifecycle lock.
    if database is not None:
        try:
            database.close_all()
        except Exception:
            _logger.exception("Failed to close SQLite runtime connections")


def get_database() -> Database:
    """Return the process database, importing legacy JSON once when needed."""

    global _database, _history_store, _project_store, _conversation_store
    db_path = _database_path()
    database = _database
    if database is not None and _same_path(database.path, db_path):
        return database

    previous_database = None
    try:
        with _DATABASE_INIT_LOCK:
            if _database is not None and _same_path(_database.path, db_path):
                return _database
            if _database is not None:
                previous_database = _database
                _database = None
                _history_store = None
                _project_store = None
                _conversation_store = None

            database = Database(str(db_path))
            if not database.is_migrated():
                history_file = get_history_file()
                projects_file = get_projects_file()
                conversations_file = get_conversation_file()
                templates_file: Path | None = get_templates_file()

                counts = database.migrate_from_json(
                    history_file=str(history_file) if history_file.exists() else None,
                    projects_file=str(projects_file) if projects_file.exists() else None,
                    conversations_file=(
                        str(conversations_file) if conversations_file.exists() else None
                    ),
                    templates_file=(
                        str(templates_file)
                        if templates_file is not None and templates_file.exists()
                        else None
                    ),
                )
                if counts.get("complete"):
                    _logger.info("Imported legacy JSON into SQLite: %s", counts)
                else:
                    _logger.error(
                        "Legacy JSON import did not complete and will retry next startup: %s",
                        counts,
                    )

            templates_file = get_templates_file()
            template_migration = database.migrate_process_templates_from_json(
                str(templates_file) if templates_file.exists() else None
            )
            if not template_migration.get("complete"):
                _logger.error(
                    "Process template JSON import did not complete and will retry next startup: %s",
                    template_migration,
                )
            elif template_migration.get("templates"):
                _logger.info("Imported current JSON templates into SQLite: %s", template_migration)

            repaired = database.repair_orphan_project_links()
            if repaired:
                _logger.warning(
                    "Recovered %d missing project references as archived projects: %s",
                    len(repaired),
                    repaired,
                )
            try:
                backup_path = database.ensure_periodic_backup(interval_hours=24)
                if backup_path:
                    _logger.info("Created automatic database backup: %s", backup_path)
            except Exception:
                _logger.exception("Automatic database backup failed")

            _database = database
            return database
    finally:
        # Path switches must not hold INIT while waiting on the old DB. An
        # active old context may itself need the newly selected runtime.
        if previous_database is not None:
            previous_database.close_all()


class HistoryStore:
    """History operations backed directly by the process database."""

    def __init__(self, database: Database | None = None) -> None:
        self.db = database or get_database()

    def get_all_records(self) -> list[Dict[str, Any]]:
        return self.db.get_all_history_records()

    def add_record(
        self,
        record: Dict[str, Any],
        data: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
        **extra_fields: Any,
    ) -> None:
        next_record = dict(record or {})
        next_record.setdefault("timestamp", _now_text())
        if isinstance(data, dict) and data:
            next_record["data"] = data
        if project_id:
            next_record["project_id"] = project_id
        next_record.update(
            {key: value for key, value in extra_fields.items() if value is not None}
        )
        self.db.add_history_record(next_record)

    def get_lsv_summary(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        return _aggregate_lsv_summary(self.db.get_lsv_records(project_id=project_id))


class ProjectStore:
    """Project operations backed directly by the process database."""

    PRESET_COLORS = [
        "#2196F3",
        "#03A9F4",
        "#00BCD4",
        "#4CAF50",
        "#8BC34A",
        "#009688",
        "#FF9800",
        "#FF5722",
        "#F44336",
    ]

    def __init__(self, database: Database | None = None) -> None:
        self.db = database or get_database()

    @staticmethod
    def _generate_project_id() -> str:
        return f"proj_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self.db.get_project(project_id)

    def get_default_project(self) -> Optional[str]:
        return self.db.get_default_project()

    def get_all_projects(self, status: str = "active") -> list[Dict[str, Any]]:
        return self.db.get_all_projects(status=status)

    def create_project(
        self,
        name: str,
        description: str = "",
        tags: Optional[list[str]] = None,
        color: Optional[str] = None,
        default_template_name: str = "",
    ) -> Optional[str]:
        clean_name = str(name or "").strip()
        if not clean_name:
            return None
        for project in self.get_all_projects("active"):
            if project.get("name") == clean_name:
                return str(project.get("id") or "")

        project_id = self._generate_project_id()
        now = _now_text()
        all_projects = self.db.get_all_projects("all")
        selected_color = color or self.PRESET_COLORS[
            len(all_projects) % len(self.PRESET_COLORS)
        ]
        self.db.create_project(
            {
                "id": project_id,
                "name": clean_name,
                "description": str(description or "").strip(),
                "created_at": now,
                "updated_at": now,
                "status": "active",
                "tags": list(tags or []),
                "file_count": 0,
                "color": selected_color,
                "default_template_name": default_template_name,
            }
        )
        if not self.db.get_default_project():
            self.db.set_default_project(project_id)
        return project_id

    def update_project(self, project_id: str, **kwargs: Any) -> bool:
        return self.db.update_project(project_id, **kwargs)

    def delete_project(self, project_id: str, delete_data: bool = False) -> bool:
        del delete_data
        default_project = self.db.get_default_project()
        deleted = self.db.delete_project(project_id)
        if deleted and default_project == project_id:
            remaining = self.db.get_all_projects("active")
            self.db.set_default_project(remaining[0]["id"] if remaining else None)
        return deleted

    def get_project_stats(self, project_id: str) -> Dict[str, Any]:
        return self.db.get_history_stats(project_id=project_id)


class ConversationStore:
    """Conversation operations backed directly by the process database."""

    def __init__(self, database: Database | None = None) -> None:
        self.db = database or get_database()

    def list_conversations(
        self,
        page: int = 1,
        page_size: int = 20,
        filters: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return self.db.list_conversations(
            page=page,
            page_size=page_size,
            filters=filters,
        )

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        return self.db.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str) -> bool:
        return self.db.delete_conversation(conversation_id)

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        clean_title = str(title or "").strip()
        return bool(clean_title) and self.db.rename_conversation(
            conversation_id, clean_title
        )

    def append_message(
        self,
        conversation_id: Optional[str],
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        attachments: Optional[list[Dict[str, Any]]] = None,
    ) -> str:
        clean_content = str(content or "").strip()
        if not clean_content:
            return str(conversation_id or "")
        return self.db.append_message(
            conversation_id=conversation_id,
            role=role,
            content=clean_content,
            metadata=metadata,
            attachments=attachments,
        )


def get_history_store() -> HistoryStore:
    global _history_store
    database = get_database()
    with _RUNTIME_LOCK:
        if _history_store is None or _history_store.db is not database:
            _history_store = HistoryStore(database)
        return _history_store


def get_project_store() -> ProjectStore:
    global _project_store
    database = get_database()
    with _RUNTIME_LOCK:
        if _project_store is None or _project_store.db is not database:
            _project_store = ProjectStore(database)
        return _project_store


def get_conversation_store() -> ConversationStore:
    global _conversation_store
    database = get_database()
    with _RUNTIME_LOCK:
        if _conversation_store is None or _conversation_store.db is not database:
            _conversation_store = ConversationStore(database)
        return _conversation_store


__all__ = [
    "ConversationStore",
    "HistoryStore",
    "ProjectStore",
    "get_conversation_store",
    "get_database",
    "get_history_store",
    "get_project_store",
    "reset_runtime",
]
