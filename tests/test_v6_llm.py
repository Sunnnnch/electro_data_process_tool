"""Tests for LLM client layer — factory, config, openai_client."""
import json
import sys
from unittest.mock import MagicMock

import pytest

from electrochem_v6.llm.base_client import BaseLLMClient
from electrochem_v6.llm.config import LLMConfig

# ── LLMConfig ──────────────────────────────────────────────────────────────

class TestLLMConfig:
    def test_default_config_loads(self, tmp_path, monkeypatch):
        """Config loads defaults when no file exists."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", raising=False)
        monkeypatch.delenv("ELECTROCHEM_LLM_CONFIG_FILE", raising=False)
        cfg = LLMConfig(config_file="nonexistent.json")
        assert cfg.config["default_model"] == "openai"
        assert "openai" in cfg.config["models"]

    def test_custom_config_file(self, tmp_path, monkeypatch):
        custom = {
            "default_model": "deepseek",
            "models": {
                "deepseek": {"api_key": "sk-test", "model": "deepseek-chat"}
            },
        }
        cfg_path = tmp_path / "custom_llm.json"
        cfg_path.write_text(json.dumps(custom), encoding="utf-8")
        monkeypatch.setenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", str(cfg_path))
        cfg = LLMConfig()
        assert cfg.config["default_model"] == "deepseek"
        assert cfg.get_api_key("deepseek") == "sk-test"

    def test_get_api_key_from_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("OPENAI_API_KEY", "env-key-123")
        monkeypatch.delenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", raising=False)
        monkeypatch.delenv("ELECTROCHEM_LLM_CONFIG_FILE", raising=False)
        cfg = LLMConfig(config_file="nope.json")
        assert cfg.get_api_key("openai") == "env-key-123"

    def test_normalize_provider_aliases(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", raising=False)
        monkeypatch.delenv("ELECTROCHEM_LLM_CONFIG_FILE", raising=False)
        cfg = LLMConfig(config_file="nope.json")
        assert cfg.normalize_provider("dashscope") == "qwen"
        assert cfg.normalize_provider("moonshot") == "kimi"

    def test_get_model_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", raising=False)
        monkeypatch.delenv("ELECTROCHEM_LLM_CONFIG_FILE", raising=False)
        cfg = LLMConfig(config_file="nope.json")
        mc = cfg.get_model_config("openai")
        assert mc["model"] == "gpt-4-turbo-preview"

    def test_get_agent_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", raising=False)
        monkeypatch.delenv("ELECTROCHEM_LLM_CONFIG_FILE", raising=False)
        cfg = LLMConfig(config_file="nope.json")
        ac = cfg.get_agent_config()
        assert ac["max_iterations"] == 10

    def test_save_config(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "save_test.json"
        monkeypatch.setenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", str(cfg_path))
        cfg = LLMConfig()
        assert cfg.save_config() is True
        assert cfg_path.exists()

    def test_update_model_entry(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "update_test.json"
        monkeypatch.setenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", str(cfg_path))
        cfg = LLMConfig()
        cfg.update_model_entry("openai", {"model": "gpt-4o"})
        assert cfg.config["models"]["openai"]["model"] == "gpt-4o"

    def test_is_vision_enabled(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", raising=False)
        monkeypatch.delenv("ELECTROCHEM_LLM_CONFIG_FILE", raising=False)
        cfg = LLMConfig(config_file="nope.json")
        # Default has vision.enabled = False
        assert cfg.is_vision_enabled() is False


# ── BaseLLMClient (abstract) ──────────────────────────────────────────────

class ConcreteClient(BaseLLMClient):
    """Minimal concrete implementation for testing."""

    def __init__(self, model="test-model"):
        self._model = model

    def chat(self, messages, tools=None, temperature=0.7, max_tokens=4000):
        return {"role": "assistant", "content": "test reply"}

    def stream_chat(self, messages, tools=None, temperature=0.7, max_tokens=4000):
        yield {"role": "assistant", "content": "chunk1"}

    def get_model_name(self):
        return self._model


class TestBaseLLMClient:
    def test_concrete_chat(self):
        c = ConcreteClient()
        result = c.chat([{"role": "user", "content": "hi"}])
        assert result["content"] == "test reply"

    def test_concrete_stream(self):
        c = ConcreteClient()
        chunks = list(c.stream_chat([{"role": "user", "content": "hi"}]))
        assert len(chunks) == 1

    def test_get_model_name(self):
        c = ConcreteClient("my-model")
        assert c.get_model_name() == "my-model"

    def test_test_connection(self):
        c = ConcreteClient()
        assert c.test_connection() is True


# ── factory.create_llm_client ─────────────────────────────────────────────

class TestFactory:
    def test_missing_provider_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", raising=False)
        monkeypatch.delenv("ELECTROCHEM_LLM_CONFIG_FILE", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from electrochem_v6.llm.factory import create_llm_client

        cfg = LLMConfig(config_file="nope.json")
        with pytest.raises(ValueError):
            create_llm_client(cfg, provider="openai")

    def test_missing_api_key(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", raising=False)
        monkeypatch.delenv("ELECTROCHEM_LLM_CONFIG_FILE", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from electrochem_v6.llm.factory import create_llm_client

        cfg = LLMConfig(config_file="nope.json")
        with pytest.raises(ValueError):
            create_llm_client(cfg, provider="openai")

    def test_creates_openai_client(self, tmp_path, monkeypatch):
        """With mocked openai import, factory should instantiate OpenAIClient."""
        cfg_data = {
            "default_model": "openai",
            "models": {
                "openai": {
                    "api_key": "sk-fake",
                    "model": "gpt-4",
                    "base_url": "https://api.openai.com/v1",
                }
            },
        }
        cfg_path = tmp_path / "llm.json"
        cfg_path.write_text(json.dumps(cfg_data), encoding="utf-8")
        monkeypatch.setenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", str(cfg_path))

        # Mock openai module
        mock_openai = MagicMock()
        monkeypatch.setitem(sys.modules, "openai", mock_openai)

        from electrochem_v6.llm.factory import create_llm_client
        from electrochem_v6.llm.openai_client import OpenAIClient

        cfg = LLMConfig()
        client = create_llm_client(cfg, provider="openai")
        assert isinstance(client, OpenAIClient)
