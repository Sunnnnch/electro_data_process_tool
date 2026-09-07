"""Small, explicitly scoped preferences shared across desktop WebView origins."""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

STORAGE_KEYS = {"electrochem_v6_appearance", "electrochem_v6_theme", "electrochem_v6_lang"}


def clean_preferences(value: Any) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    storage = value.get("local_storage", {})
    result: dict[str, Any] = {"local_storage": {}, "workspace": {}}
    if isinstance(storage, dict):
        for key in STORAGE_KEYS:
            item = storage.get(key)
            if isinstance(item, str) and len(item) <= 8192:
                result["local_storage"][key] = item
    workspace = value.get("workspace", {})
    if isinstance(workspace, dict):
        if workspace.get("tab") in {"pro", "project"}:
            result["workspace"]["tab"] = workspace["tab"]
        for key in ("project_id", "conversation_id"):
            item = workspace.get(key)
            if isinstance(item, str) and len(item) <= 128:
                result["workspace"][key] = item
        if isinstance(workspace.get("assistant_open"), bool):
            result["workspace"]["assistant_open"] = workspace["assistant_open"]
    return result


def fit_window(value: Any, monitors: list[tuple[int, int, int, int]] | None = None) -> dict[str, Any]:
    """Retain a usable normal rectangle, including after a monitor is removed."""
    value = value if isinstance(value, dict) else {}
    monitors = monitors or [(0, 0, 1920, 1080)]

    def integer(key: str, default: int) -> int:
        try:
            return int(value.get(key, default))
        except (TypeError, ValueError, OverflowError):
            return default

    x, y = integer("x", monitors[0][0] + 40), integer("y", monitors[0][1] + 40)
    monitor = next((m for m in monitors if m[0] <= x < m[2] - 80 and m[1] <= y < m[3] - 80), monitors[0])
    left, top, right, bottom = monitor
    width = min(max(960, integer("width", 1480)), max(640, right - left))
    height = min(max(640, integer("height", 960)), max(480, bottom - top))
    return {"x": max(left, min(x, right - width)), "y": max(top, min(y, bottom - height)),
            "width": width, "height": height, "maximized": bool(value.get("maximized", False))}


class DesktopState:
    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "desktop-state.json"
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        try:
            if self.path.stat().st_size <= 128 * 1024:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data = loaded
        except (OSError, ValueError):
            pass

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return json.loads(json.dumps(self._data.get(key, default)))

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            updated = {**self._data, key: value}
            raw = json.dumps(updated, ensure_ascii=False, indent=2)
            if len(raw.encode("utf-8")) > 128 * 1024:
                raise ValueError("desktop preferences are too large")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_text(raw, encoding="utf-8")
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
            self._data = updated

    def preferences(self) -> dict[str, Any]:
        return clean_preferences(self.get("preferences", {}))

    def save_preferences(self, value: Any) -> dict[str, Any]:
        cleaned = clean_preferences(value)
        self.set("preferences", cleaned)
        return cleaned
