import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
REPO = ROOT.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from electrochem_v6.config import resolve_data_path, user_config_dir  # noqa: E402
from electrochem_v6.llm.config import LLMConfig  # noqa: E402
from electrochem_v6.store.legacy_runtime import (  # noqa: E402
    get_conversation_manager_v6,
    get_history_manager_v6,
    get_project_manager_v6,
)


def test_v6_data_path_precedence_env_user_project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir(parents=True, exist_ok=True)
    project.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(project)
    monkeypatch.delenv("ELECTROCHEM_V6_PROJECTS_FILE", raising=False)

    user_file = home / ".electrochem" / "v6" / "projects.json"
    project_file = project / "projects.json"
    user_file.parent.mkdir(parents=True, exist_ok=True)
    user_file.write_text("{}", encoding="utf-8")
    project_file.write_text("{}", encoding="utf-8")

    assert resolve_data_path("projects") == user_file

    user_file.unlink()
    assert resolve_data_path("projects") == project_file

    env_file = tmp_path / "env" / "projects_override.json"
    monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(env_file))
    assert resolve_data_path("projects") == env_file


def test_v6_shared_data_dir_override(tmp_path, monkeypatch):
    target = tmp_path / "portable_data"
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(target))
    monkeypatch.delenv("ELECTROCHEM_V6_PROJECTS_FILE", raising=False)

    assert user_config_dir() == target
    assert resolve_data_path("projects") == target / "projects.json"
    assert resolve_data_path("history") == target / "processing_history.json"


def test_v6_legacy_managers_follow_resolved_paths(tmp_path, monkeypatch):
    p1 = tmp_path / "a" / "projects.json"
    h1 = tmp_path / "a" / "history.json"
    c1 = tmp_path / "a" / "conv.json"
    monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(p1))
    monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(h1))
    monkeypatch.setenv("ELECTROCHEM_V6_CONVERSATION_FILE", str(c1))

    pm = get_project_manager_v6()
    hm = get_history_manager_v6()
    cm = get_conversation_manager_v6()
    assert Path(pm.projects_file).resolve() == p1.resolve()
    assert Path(hm.history_file).resolve() == h1.resolve()
    assert Path(cm.storage_file).resolve() == c1.resolve()

    p2 = tmp_path / "b" / "projects.json"
    monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(p2))
    pm2 = get_project_manager_v6()
    assert Path(pm2.projects_file).resolve() == p2.resolve()


def test_llm_config_precedence_env_user_project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir(parents=True, exist_ok=True)
    project.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(project)

    user_cfg = home / ".electrochem" / "llm_config.json"
    user_cfg.parent.mkdir(parents=True, exist_ok=True)
    user_cfg.write_text(json.dumps({"default_model": "qwen"}, ensure_ascii=False), encoding="utf-8")

    proj_cfg = project / "llm_config.json"
    proj_cfg.write_text(json.dumps({"default_model": "deepseek"}, ensure_ascii=False), encoding="utf-8")

    env_cfg = tmp_path / "env" / "llm_config.json"
    env_cfg.parent.mkdir(parents=True, exist_ok=True)
    env_cfg.write_text(json.dumps({"default_model": "kimi"}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", str(env_cfg))

    cfg = LLMConfig()
    assert cfg.config.get("default_model") == "kimi"

    monkeypatch.delenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", raising=False)
    cfg = LLMConfig()
    assert cfg.config.get("default_model") == "qwen"

    user_cfg.unlink()
    cfg = LLMConfig()
    assert cfg.config.get("default_model") == "deepseek"


def test_llm_config_save_prefers_env_path(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    target = tmp_path / "cfg" / "v6_llm.json"
    monkeypatch.setenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", str(target))

    cfg = LLMConfig()
    cfg.config["default_model"] = "openai"
    assert cfg.save_config() is True
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload.get("default_model") == "openai"
