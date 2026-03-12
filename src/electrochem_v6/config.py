"""Central config for v6 refactor."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

APP_NAME = "电化学数据处理与智能分析软件"
APP_VERSION = "6.0.12"

# v6 design choice: no activation required.
ENABLE_LICENSE = False


_FILE_KEYS: Dict[str, tuple[str, str]] = {
    "projects": ("ELECTROCHEM_V6_PROJECTS_FILE", "projects.json"),
    "history": ("ELECTROCHEM_V6_HISTORY_FILE", "processing_history.json"),
    "conversations": ("ELECTROCHEM_V6_CONVERSATION_FILE", "conversation_history.json"),
    "templates": ("ELECTROCHEM_V6_TEMPLATE_FILE", "process_templates.json"),
    "quality_report": ("ELECTROCHEM_V6_QUALITY_REPORT_FILE", "latest_quality_report.json"),
    "log_file": ("ELECTROCHEM_V6_LOG_FILE", "v6_server.log"),
    # Keep user-level compatibility with existing v5/v6 LLM config location.
    "llm_config": ("ELECTROCHEM_V6_LLM_CONFIG_FILE", "llm_config.json"),
}


def _shared_data_dir() -> Path | None:
    raw = os.environ.get("ELECTROCHEM_V6_DATA_DIR")
    if not raw:
        return None
    return Path(raw).expanduser()


def user_config_dir() -> Path:
    shared = _shared_data_dir()
    if shared is not None:
        return shared
    return Path.home() / ".electrochem" / "v6"


def project_default_dir() -> Path:
    shared = _shared_data_dir()
    if shared is not None:
        return shared
    # In frozen (packaged) mode, use the exe's directory instead of cwd
    # so that data paths remain stable regardless of launch location.
    if getattr(__import__('sys'), 'frozen', False):
        import sys
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _llm_user_dir() -> Path:
    shared = _shared_data_dir()
    if shared is not None:
        return shared
    return Path.home() / ".electrochem"


def _ensure_key(kind: str) -> tuple[str, str]:
    if kind not in _FILE_KEYS:
        raise KeyError(f"unsupported config file kind: {kind}")
    return _FILE_KEYS[kind]


def _env_path(kind: str) -> Path | None:
    env_key, _ = _ensure_key(kind)
    raw = os.environ.get(env_key)
    if not raw:
        return None
    return Path(raw).expanduser()


def _user_path(kind: str) -> Path:
    _, filename = _ensure_key(kind)
    if kind == "llm_config":
        return _llm_user_dir() / filename
    return user_config_dir() / filename


def _project_path(kind: str) -> Path:
    _, filename = _ensure_key(kind)
    return project_default_dir() / filename


def resolve_data_path(kind: str, *, for_write: bool = False) -> Path:
    """Resolve path using priority: env > user dir > project default."""
    env_path = _env_path(kind)
    if env_path is not None:
        return env_path

    user_path = _user_path(kind)
    project_path = _project_path(kind)

    if _shared_data_dir() is not None:
        return user_path

    if user_path.exists():
        return user_path
    if project_path.exists():
        return project_path

    # When none exists, default to user dir to avoid polluting arbitrary cwd.
    return user_path


def ensure_parent_dir(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_projects_file() -> Path:
    return resolve_data_path("projects", for_write=True)


def get_history_file() -> Path:
    return resolve_data_path("history", for_write=True)


def get_conversation_file() -> Path:
    return resolve_data_path("conversations", for_write=True)


def get_templates_file() -> Path:
    return resolve_data_path("templates", for_write=True)


def get_quality_report_file() -> Path:
    return resolve_data_path("quality_report", for_write=False)


def get_llm_config_file() -> Path:
    return resolve_data_path("llm_config", for_write=True)


def get_log_file() -> Path:
    path = resolve_data_path("log_file", for_write=True)
    # Put default logs under a dedicated user-level logs directory.
    if path.name == "v6_server.log" and path.parent == user_config_dir():
        return user_config_dir() / "logs" / path.name
    return path
