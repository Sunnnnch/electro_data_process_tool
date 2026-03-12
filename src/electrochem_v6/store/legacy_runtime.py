"""Native v6 runtime managers for projects, history, and conversations.

Supports two storage backends:
- JSON files (legacy default)
- SQLite (new default, auto-migrates from JSON on first run)

Set environment variable ``ELECTROCHEM_V6_STORAGE=json`` to force the old
JSON backend.  Anything else (or unset) uses SQLite.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
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
)

_logger = logging.getLogger(__name__)

_RUNTIME_LOCK = threading.RLock()
_history_manager_singleton: Optional[Any] = None
_project_manager_singleton: Optional[Any] = None
_conversation_manager_singleton: Optional[Any] = None

_USE_SQLITE = os.environ.get("ELECTROCHEM_V6_STORAGE", "sqlite").strip().lower() != "json"


def _reset_singletons() -> None:
    """Reset all manager singletons and the database instance. For testing only."""
    global _history_manager_singleton, _project_manager_singleton
    global _conversation_manager_singleton, _db_singleton, _USE_SQLITE
    with _RUNTIME_LOCK:
        _history_manager_singleton = None
        _project_manager_singleton = None
        _conversation_manager_singleton = None
        _db_singleton = None
        _USE_SQLITE = os.environ.get("ELECTROCHEM_V6_STORAGE", "sqlite").strip().lower() != "json"


def _same_path(current: str, expected: Path) -> bool:
    try:
        return Path(current).resolve() == expected.resolve()
    except Exception:
        return str(current) == str(expected)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_json_dict(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return dict(default)


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    from electrochem_v6.store._json_utils import atomic_write_json
    atomic_write_json(path, payload)


class NativeHistoryManager:
    def __init__(self, history_file: str):
        self.history_file = str(ensure_parent_dir(Path(history_file)))
        self.lock = threading.RLock()
        self._ensure_history_file()

    def _ensure_history_file(self) -> None:
        path = Path(self.history_file)
        if not path.exists():
            _atomic_write_json(path, {"version": "1.0", "records": []})
            return
        payload = _load_json_dict(path, {"version": "1.0", "records": []})
        records = payload.get("records")
        if not isinstance(records, list):
            payload["records"] = []
        payload.setdefault("version", "1.0")
        _atomic_write_json(path, self._to_json_safe(payload))

    def _load_payload(self) -> Dict[str, Any]:
        payload = _load_json_dict(Path(self.history_file), {"version": "1.0", "records": []})
        records = payload.get("records")
        if not isinstance(records, list):
            payload["records"] = []
        payload.setdefault("version", "1.0")
        return payload

    def _to_json_safe(self, value: Any) -> Any:
        from electrochem_v6.store._json_utils import to_json_safe
        return to_json_safe(value)

    def _atomic_write_payload(self, payload: Dict[str, Any]) -> None:
        _atomic_write_json(Path(self.history_file), self._to_json_safe(payload))

    def get_all_records(self) -> list[Dict[str, Any]]:
        with self.lock:
            payload = self._load_payload()
            records = payload.get("records", [])
            return [item for item in records if isinstance(item, dict)]

    def add_record(
        self,
        record: Dict[str, Any],
        data: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
        **extra_fields: Any,
    ) -> None:
        with self.lock:
            payload = self._load_payload()
            next_record = dict(record or {})
            if "timestamp" not in next_record:
                next_record["timestamp"] = _now_text()
            if isinstance(data, dict) and data:
                next_record["data"] = data
            if project_id:
                next_record["project_id"] = project_id
            for key, value in extra_fields.items():
                if value is not None:
                    next_record[key] = value
            payload.setdefault("records", []).append(self._to_json_safe(next_record))
            self._atomic_write_payload(payload)

    def get_lsv_summary(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        records = [
            item
            for item in self.get_all_records()
            if str(item.get("type") or "").upper() == "LSV" and (not project_id or item.get("project_id") == project_id)
        ]

        grouped: dict[str, list[Dict[str, Any]]] = {}
        for record in records:
            sample_name = str(record.get("sample_name") or record.get("file_name") or "Unknown").strip() or "Unknown"
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
                    except Exception:
                        pass
            samples.append(
                {
                    "sample_name": sample_name,
                    "potential_10": (sum(potentials) / len(potentials)) if potentials else None,
                    "overpotential_10": (sum(overpotentials) / len(overpotentials)) if overpotentials else None,
                    "tafel_slope": (sum(tafel_slopes) / len(tafel_slopes)) if tafel_slopes else None,
                    "record_count": len(items),
                    "latest_time": latest_time,
                }
            )
        return {"samples": samples, "total_count": len(records)}


class NativeProjectManager:
    PRESET_COLORS = ["#2196F3", "#03A9F4", "#00BCD4", "#4CAF50", "#8BC34A", "#009688", "#FF9800", "#FF5722", "#F44336"]

    def __init__(self, projects_file: str):
        self.projects_file = str(ensure_parent_dir(Path(projects_file)))
        self.lock = threading.RLock()
        self._ensure_projects_file()

    def _ensure_projects_file(self) -> None:
        path = Path(self.projects_file)
        if not path.exists():
            _atomic_write_json(path, {"version": "1.0", "projects": [], "default_project": None})
            return
        payload = _load_json_dict(path, {"version": "1.0", "projects": [], "default_project": None})
        if not isinstance(payload.get("projects"), list):
            payload["projects"] = []
        payload.setdefault("version", "1.0")
        payload.setdefault("default_project", None)
        _atomic_write_json(path, payload)

    def _load_payload(self) -> Dict[str, Any]:
        payload = _load_json_dict(Path(self.projects_file), {"version": "1.0", "projects": [], "default_project": None})
        if not isinstance(payload.get("projects"), list):
            payload["projects"] = []
        payload.setdefault("version", "1.0")
        payload.setdefault("default_project", None)
        return payload

    def _save_payload(self, payload: Dict[str, Any]) -> None:
        _atomic_write_json(Path(self.projects_file), payload)

    def _generate_project_id(self) -> str:
        return f"proj_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            for project in self._load_payload().get("projects", []):
                if isinstance(project, dict) and project.get("id") == project_id:
                    return dict(project)
        return None

    def get_default_project(self) -> Optional[str]:
        with self.lock:
            payload = self._load_payload()
            default_project = payload.get("default_project")
            if isinstance(default_project, str) and default_project.strip():
                return default_project
            projects = payload.get("projects", [])
            if projects:
                first_id = str(projects[0].get("id") or "").strip()
                if first_id:
                    payload["default_project"] = first_id
                    self._save_payload(payload)
                    return first_id
        return None

    def get_all_projects(self, status: str = "active") -> list[Dict[str, Any]]:
        with self.lock:
            projects = [dict(item) for item in self._load_payload().get("projects", []) if isinstance(item, dict)]
        if status == "all":
            return projects
        return [item for item in projects if item.get("status", "active") == status]

    def create_project(self, name: str, description: str = "", tags: Optional[list[str]] = None, color: Optional[str] = None) -> Optional[str]:
        clean_name = str(name or "").strip()
        if not clean_name:
            return None
        with self.lock:
            payload = self._load_payload()
            for project in payload.get("projects", []):
                if isinstance(project, dict) and project.get("name") == clean_name and project.get("status", "active") == "active":
                    return str(project.get("id") or "")
            project_id = self._generate_project_id()
            now = _now_text()
            if not color:
                color = self.PRESET_COLORS[len(payload.get("projects", [])) % len(self.PRESET_COLORS)]
            project = {
                "id": project_id,
                "name": clean_name,
                "description": str(description or "").strip(),
                "created_at": now,
                "updated_at": now,
                "status": "active",
                "tags": list(tags or []),
                "file_count": 0,
                "color": color,
            }
            payload.setdefault("projects", []).append(project)
            if not payload.get("default_project"):
                payload["default_project"] = project_id
            self._save_payload(payload)
            return project_id

    def update_project(self, project_id: str, **kwargs: Any) -> bool:
        allowed = {"name", "description", "tags", "color", "status"}
        with self.lock:
            payload = self._load_payload()
            for project in payload.get("projects", []):
                if not isinstance(project, dict) or project.get("id") != project_id:
                    continue
                for key, value in kwargs.items():
                    if key in allowed:
                        project[key] = value
                project["updated_at"] = _now_text()
                self._save_payload(payload)
                return True
        return False

    def delete_project(self, project_id: str, delete_data: bool = False) -> bool:
        del delete_data
        with self.lock:
            payload = self._load_payload()
            projects = payload.get("projects", [])
            next_projects = [item for item in projects if isinstance(item, dict) and item.get("id") != project_id]
            if len(next_projects) == len(projects):
                return False
            payload["projects"] = next_projects
            if payload.get("default_project") == project_id:
                payload["default_project"] = next_projects[0].get("id") if next_projects else None
            self._save_payload(payload)
            return True

    def get_project_stats(self, project_id: str) -> Dict[str, Any]:
        hist_mgr = get_history_manager_v6()
        records = [item for item in hist_mgr.get_all_records() if item.get("project_id") == project_id]
        lsv_count = sum(1 for item in records if str(item.get("type") or "").upper() == "LSV")
        cv_count = sum(1 for item in records if str(item.get("type") or "").upper() == "CV")
        eis_count = sum(1 for item in records if str(item.get("type") or "").upper() == "EIS")
        ecsa_count = sum(1 for item in records if str(item.get("type") or "").upper() == "ECSA")
        return {
            "total_files": len(records),
            "lsv_count": lsv_count,
            "cv_count": cv_count,
            "eis_count": eis_count,
            "ecsa_count": ecsa_count,
        }


class NativeConversationManager:
    def __init__(self, storage_file: str):
        self.storage_file = str(ensure_parent_dir(Path(storage_file)))
        self.lock = threading.RLock()
        self._ensure_file()

    def _ensure_file(self) -> None:
        path = Path(self.storage_file)
        if not path.exists():
            _atomic_write_json(path, {"conversations": []})
            return
        payload = _load_json_dict(path, {"conversations": []})
        if not isinstance(payload.get("conversations"), list):
            payload["conversations"] = []
        _atomic_write_json(path, payload)

    def _load(self) -> Dict[str, Any]:
        payload = _load_json_dict(Path(self.storage_file), {"conversations": []})
        if not isinstance(payload.get("conversations"), list):
            payload["conversations"] = []
        return payload

    def _save(self, payload: Dict[str, Any]) -> None:
        _atomic_write_json(Path(self.storage_file), payload)

    def _find(self, conversation_id: str) -> tuple[Dict[str, Any], int]:
        payload = self._load()
        conversations = payload.get("conversations", [])
        for index, item in enumerate(conversations):
            if isinstance(item, dict) and item.get("conversation_id") == conversation_id:
                return payload, index
        return payload, -1

    def list_conversations(self, page: int = 1, page_size: int = 20, filters: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        filters = filters or {}
        keyword = str(filters.get("keyword") or "").strip().lower()
        project_name = str(filters.get("project_name") or "").strip().lower()
        data_type = str(filters.get("data_type") or "").strip().lower()
        provider_name = str(filters.get("provider") or "").strip().lower()
        with self.lock:
            conversations = [dict(item) for item in self._load().get("conversations", []) if isinstance(item, dict)]

        def _match(item: Dict[str, Any]) -> bool:
            if keyword:
                values = [item.get("title", ""), item.get("project_name", ""), item.get("last_message_excerpt", "")]
                if not any(keyword in str(value or "").lower() for value in values):
                    return False
            if project_name and project_name not in str(item.get("project_name") or "").lower():
                return False
            if data_type and data_type not in str(item.get("data_type") or "").lower():
                return False
            if provider_name and provider_name != str(item.get("provider") or "").lower():
                return False
            return True

        filtered = [item for item in conversations if _match(item)]
        filtered.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        total = len(filtered)
        safe_page = max(1, int(page))
        safe_page_size = max(1, int(page_size))
        start = (safe_page - 1) * safe_page_size
        items = filtered[start : start + safe_page_size]
        return {"items": items, "total": total, "page": safe_page, "page_size": safe_page_size}

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            payload, index = self._find(str(conversation_id or "").strip())
            if index < 0:
                return None
            item = payload["conversations"][index]
            return dict(item) if isinstance(item, dict) else None

    def delete_conversation(self, conversation_id: str) -> bool:
        with self.lock:
            payload, index = self._find(str(conversation_id or "").strip())
            if index < 0:
                return False
            del payload["conversations"][index]
            self._save(payload)
            return True

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        clean_title = str(title or "").strip()
        if not clean_title:
            return False
        with self.lock:
            payload, index = self._find(str(conversation_id or "").strip())
            if index < 0:
                return False
            item = payload["conversations"][index]
            if not isinstance(item, dict):
                return False
            item["title"] = clean_title
            item["updated_at"] = _now_text()
            self._save(payload)
            return True

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
        metadata = dict(metadata or {})
        attachments = list(attachments or [])
        now = _now_text()
        with self.lock:
            payload, index = self._find(str(conversation_id or "").strip())
            if index < 0:
                conversation_id = str(conversation_id or uuid.uuid4().hex)
                conversation = {
                    "conversation_id": conversation_id,
                    "title": metadata.get("title") or metadata.get("project_name") or "New Conversation",
                    "project_name": metadata.get("project_name"),
                    "data_type": metadata.get("data_type"),
                    "provider": metadata.get("provider"),
                    "model": metadata.get("model"),
                    "created_at": now,
                    "updated_at": now,
                    "messages": [],
                }
                payload.setdefault("conversations", []).append(conversation)
            else:
                conversation = payload["conversations"][index]
                conversation_id = str(conversation.get("conversation_id") or conversation_id or uuid.uuid4().hex)
            message = {
                "role": str(role or "user"),
                "content": clean_content,
                "timestamp": now,
                "metadata": metadata,
                "attachments": attachments,
            }
            conversation.setdefault("messages", []).append(message)
            conversation["updated_at"] = now
            conversation["last_message_excerpt"] = clean_content[:120]
            conversation["last_message_role"] = str(role or "user")
            if metadata.get("project_name"):
                conversation["project_name"] = metadata["project_name"]
            if metadata.get("data_type"):
                conversation["data_type"] = metadata["data_type"]
            if metadata.get("provider"):
                conversation["provider"] = metadata["provider"]
            if metadata.get("model"):
                conversation["model"] = metadata["model"]
            if metadata.get("title"):
                conversation["title"] = metadata["title"]
            self._save(payload)
            return conversation_id


# ╔══════════════════════════════════════════════════════════════════╗
# ║  SQLite-backed wrappers (same interface as JSON managers)        ║
# ╚══════════════════════════════════════════════════════════════════╝

_db_singleton: Optional[Any] = None


def _get_db() -> Any:
    """Return the global :class:`Database` singleton, auto-migrating JSON data on first use."""
    global _db_singleton
    if _db_singleton is not None:
        return _db_singleton
    from .database import Database

    db_dir = str(ensure_parent_dir(get_history_file()).parent)
    db_path = os.path.join(db_dir, "electrochem_v6.db")
    db = Database(db_path)

    if not db.is_migrated():
        history_f = str(get_history_file())
        projects_f = str(get_projects_file())
        conv_f = str(get_conversation_file())
        templates_f = None
        try:
            from electrochem_v6.config import get_templates_file
            templates_f = str(get_templates_file())
        except Exception:
            pass
        counts = db.migrate_from_json(
            history_file=history_f if os.path.exists(history_f) else None,
            projects_file=projects_f if os.path.exists(projects_f) else None,
            conversations_file=conv_f if os.path.exists(conv_f) else None,
            templates_file=templates_f if templates_f and os.path.exists(templates_f) else None,
        )
        _logger.info("Auto-migrated JSON → SQLite: %s", counts)

    _db_singleton = db
    return db


class SqliteHistoryManager:
    """Drop-in replacement for NativeHistoryManager backed by SQLite."""

    def __init__(self) -> None:
        self.db = _get_db()
        # Expose attributes that higher-level modules access directly
        self.history_file = str(ensure_parent_dir(get_history_file()))
        self.lock = threading.RLock()

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
        if "timestamp" not in next_record:
            next_record["timestamp"] = _now_text()
        if isinstance(data, dict) and data:
            next_record["data"] = data
        if project_id:
            next_record["project_id"] = project_id
        for key, value in extra_fields.items():
            if value is not None:
                next_record[key] = value
        self.db.add_history_record(next_record)

    def get_lsv_summary(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        records = self.db.get_lsv_records(project_id=project_id)

        grouped: dict[str, list[Dict[str, Any]]] = {}
        for record in records:
            sample_name = str(record.get("sample_name") or record.get("file_name") or "Unknown").strip() or "Unknown"
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
                    except Exception:
                        pass
            samples.append(
                {
                    "sample_name": sample_name,
                    "potential_10": (sum(potentials) / len(potentials)) if potentials else None,
                    "overpotential_10": (sum(overpotentials) / len(overpotentials)) if overpotentials else None,
                    "tafel_slope": (sum(tafel_slopes) / len(tafel_slopes)) if tafel_slopes else None,
                    "record_count": len(items),
                    "latest_time": latest_time,
                }
            )
        return {"samples": samples, "total_count": len(records)}

    # Compatibility shims for code that reaches into manager internals
    @staticmethod
    def _to_json_safe(value: Any) -> Any:
        from .database import _to_json_safe
        return _to_json_safe(value)

    def _atomic_write_payload(self, payload: Dict[str, Any]) -> None:
        """Compatibility shim — re-import records from a full payload dict."""
        pass  # SQLite is the source of truth; JSON writes are no-ops


class SqliteProjectManager:
    """Drop-in replacement for NativeProjectManager backed by SQLite."""

    PRESET_COLORS = ["#2196F3", "#03A9F4", "#00BCD4", "#4CAF50", "#8BC34A", "#009688", "#FF9800", "#FF5722", "#F44336"]

    def __init__(self) -> None:
        self.db = _get_db()
        self.projects_file = str(ensure_parent_dir(get_projects_file()))
        self.lock = threading.RLock()

    def _generate_project_id(self) -> str:
        return f"proj_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self.db.get_project(project_id)

    def get_default_project(self) -> Optional[str]:
        return self.db.get_default_project()

    def get_all_projects(self, status: str = "active") -> list[Dict[str, Any]]:
        return self.db.get_all_projects(status=status)

    def create_project(self, name: str, description: str = "", tags: Optional[list[str]] = None, color: Optional[str] = None) -> Optional[str]:
        clean_name = str(name or "").strip()
        if not clean_name:
            return None
        # Check for existing active project with same name
        for proj in self.get_all_projects("active"):
            if proj.get("name") == clean_name:
                return str(proj.get("id") or "")
        project_id = self._generate_project_id()
        now = _now_text()
        all_projects = self.db.get_all_projects("all")
        if not color:
            color = self.PRESET_COLORS[len(all_projects) % len(self.PRESET_COLORS)]
        project = {
            "id": project_id,
            "name": clean_name,
            "description": str(description or "").strip(),
            "created_at": now,
            "updated_at": now,
            "status": "active",
            "tags": list(tags or []),
            "file_count": 0,
            "color": color,
        }
        self.db.create_project(project)
        if not self.db.get_default_project():
            self.db.set_default_project(project_id)
        return project_id

    def update_project(self, project_id: str, **kwargs: Any) -> bool:
        return self.db.update_project(project_id, **kwargs)

    def delete_project(self, project_id: str, delete_data: bool = False) -> bool:
        del delete_data
        default = self.db.get_default_project()
        result = self.db.delete_project(project_id)
        if result and default == project_id:
            remaining = self.db.get_all_projects("active")
            self.db.set_default_project(remaining[0]["id"] if remaining else None)
        return result

    def get_project_stats(self, project_id: str) -> Dict[str, Any]:
        return self.db.get_history_stats(project_id=project_id)


class SqliteConversationManager:
    """Drop-in replacement for NativeConversationManager backed by SQLite."""

    def __init__(self) -> None:
        self.db = _get_db()
        self.storage_file = str(ensure_parent_dir(get_conversation_file()))
        self.lock = threading.RLock()

    def list_conversations(self, page: int = 1, page_size: int = 20, filters: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        return self.db.list_conversations(page=page, page_size=page_size, filters=filters)

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        return self.db.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str) -> bool:
        return self.db.delete_conversation(conversation_id)

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        clean_title = str(title or "").strip()
        if not clean_title:
            return False
        return self.db.rename_conversation(conversation_id, clean_title)

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


def get_history_manager_v6() -> SqliteHistoryManager | NativeHistoryManager:
    global _history_manager_singleton
    with _RUNTIME_LOCK:
        if _USE_SQLITE:
            if _history_manager_singleton is None or not isinstance(_history_manager_singleton, SqliteHistoryManager):
                _history_manager_singleton = SqliteHistoryManager()
            return _history_manager_singleton
        # JSON fallback
        history_path = ensure_parent_dir(get_history_file())
        current = _history_manager_singleton
        if current is None or not _same_path(getattr(current, "history_file", ""), history_path):
            _history_manager_singleton = NativeHistoryManager(str(history_path))
        assert isinstance(_history_manager_singleton, NativeHistoryManager)
        return _history_manager_singleton


def get_project_manager_v6() -> SqliteProjectManager | NativeProjectManager:
    global _project_manager_singleton
    with _RUNTIME_LOCK:
        if _USE_SQLITE:
            if _project_manager_singleton is None or not isinstance(_project_manager_singleton, SqliteProjectManager):
                _project_manager_singleton = SqliteProjectManager()
            return _project_manager_singleton
        # JSON fallback
        projects_path = ensure_parent_dir(get_projects_file())
        current = _project_manager_singleton
        if current is None or not _same_path(getattr(current, "projects_file", ""), projects_path):
            _project_manager_singleton = NativeProjectManager(str(projects_path))
        assert isinstance(_project_manager_singleton, NativeProjectManager)
        return _project_manager_singleton


def get_conversation_manager_v6() -> SqliteConversationManager | NativeConversationManager:
    global _conversation_manager_singleton
    with _RUNTIME_LOCK:
        if _USE_SQLITE:
            if _conversation_manager_singleton is None or not isinstance(_conversation_manager_singleton, SqliteConversationManager):
                _conversation_manager_singleton = SqliteConversationManager()
            return _conversation_manager_singleton
        # JSON fallback
        conversation_path = ensure_parent_dir(get_conversation_file())
        current = _conversation_manager_singleton
        if current is None or not _same_path(getattr(current, "storage_file", ""), conversation_path):
            _conversation_manager_singleton = NativeConversationManager(str(conversation_path))
        assert isinstance(_conversation_manager_singleton, NativeConversationManager)
        return _conversation_manager_singleton
