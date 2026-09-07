import json
from pathlib import Path

from electrochem_v6.config import resolve_data_path, user_config_dir
from electrochem_v6.llm.config import LLMConfig
from electrochem_v6.store.runtime import (
    get_conversation_store,
    get_history_store,
    get_project_store,
)


def test_v6_data_path_precedence_env_user_project(tmp_path, monkeypatch):
    monkeypatch.delenv("ELECTROCHEM_V6_DATA_DIR", raising=False)
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


def test_v6_runtime_stores_follow_resolved_database_path(tmp_path, monkeypatch):
    p1 = tmp_path / "a" / "projects.json"
    h1 = tmp_path / "a" / "history.json"
    c1 = tmp_path / "a" / "conv.json"
    monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(p1))
    monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(h1))
    monkeypatch.setenv("ELECTROCHEM_V6_CONVERSATION_FILE", str(c1))

    pm = get_project_store()
    hm = get_history_store()
    cm = get_conversation_store()
    expected_db = (h1.parent / "electrochem_v6.db").resolve()
    assert Path(pm.db.path).resolve() == expected_db
    assert Path(hm.db.path).resolve() == expected_db
    assert Path(cm.db.path).resolve() == expected_db

    p2 = tmp_path / "b" / "projects.json"
    h2 = tmp_path / "b" / "history.json"
    monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(p2))
    monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(h2))
    pm2 = get_project_store()
    assert Path(pm2.db.path).resolve() == (h2.parent / "electrochem_v6.db").resolve()


def test_llm_config_precedence_env_user_project(tmp_path, monkeypatch):
    monkeypatch.delenv("ELECTROCHEM_V6_DATA_DIR", raising=False)
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


def test_llm_config_save_uses_portable_data_dir(tmp_path, monkeypatch):
    target = tmp_path / "portable_data"
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(target))
    monkeypatch.delenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", raising=False)

    cfg = LLMConfig()
    cfg.config["default_model"] = "deepseek"

    assert cfg.save_config() is True
    config_file = target / "llm_config.json"
    assert config_file.exists()
    assert json.loads(config_file.read_text(encoding="utf-8"))["default_model"] == "deepseek"


def test_llm_config_update_rolls_back_when_persistence_fails(tmp_path, monkeypatch):
    target = tmp_path / "llm_config.json"
    monkeypatch.setenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", str(target))
    cfg = LLMConfig()
    before = cfg.get_model_config("openai")
    monkeypatch.setattr(cfg, "save_config", lambda: False)

    assert cfg.update_model_entry("openai", {"model": "not-persisted"}) is False
    assert cfg.get_model_config("openai") == before
