"""Native v6 runtime managers for projects, history, and conversations."""

from __future__ import annotations

import json
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

_RUNTIME_LOCK = threading.RLock()
_history_manager_singleton: Optional["NativeHistoryManager"] = None
_project_manager_singleton: Optional["NativeProjectManager"] = None
_conversation_manager_singleton: Optional["NativeConversationManager"] = None


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
    target = ensure_parent_dir(path)
    fd, tmp_path = tempfile.mkstemp(prefix=f"{target.stem}_", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(target))
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


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
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): self._to_json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._to_json_safe(item) for item in value]
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "tolist"):
            try:
                return self._to_json_safe(value.tolist())
            except Exception:
                pass
        if hasattr(value, "item"):
            try:
                return self._to_json_safe(value.item())
            except Exception:
                pass
        if hasattr(value, "as_posix"):
            try:
                return value.as_posix()
            except Exception:
                pass
        return str(value)

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

    def _find(self, conversation_id: str) -> tuple[Dict[str, Any], int] | tuple[None, int]:
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


def get_history_manager_v6():
    global _history_manager_singleton
    with _RUNTIME_LOCK:
        history_path = ensure_parent_dir(get_history_file())
        current = _history_manager_singleton
        if current is None or not _same_path(getattr(current, "history_file", ""), history_path):
            _history_manager_singleton = NativeHistoryManager(str(history_path))
        return _history_manager_singleton


def get_project_manager_v6():
    global _project_manager_singleton
    with _RUNTIME_LOCK:
        projects_path = ensure_parent_dir(get_projects_file())
        current = _project_manager_singleton
        if current is None or not _same_path(getattr(current, "projects_file", ""), projects_path):
            _project_manager_singleton = NativeProjectManager(str(projects_path))
        return _project_manager_singleton


def get_conversation_manager_v6():
    global _conversation_manager_singleton
    with _RUNTIME_LOCK:
        conversation_path = ensure_parent_dir(get_conversation_file())
        current = _conversation_manager_singleton
        if current is None or not _same_path(getattr(current, "storage_file", ""), conversation_path):
            _conversation_manager_singleton = NativeConversationManager(str(conversation_path))
        return _conversation_manager_singleton
