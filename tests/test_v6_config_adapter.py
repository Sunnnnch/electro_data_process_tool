"""Tests for llm/config_adapter.py — input validation branches."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from electrochem_v6.llm.config_adapter import check_provider_connection, get_masked_config, update_provider

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  get_masked_config                                                      ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestGetMaskedConfig:
    def test_returns_success(self, tmp_path: Path):
        cfg_file = tmp_path / "test_llm_cfg.json"
        cfg_file.write_text("{}", encoding="utf-8")
        with patch.dict("os.environ", {"ELECTROCHEM_V6_LLM_CONFIG_FILE": str(cfg_file)}):
            result = get_masked_config()
        assert result["status"] == "success"
        assert "models" in result
        assert "default_provider" in result

    def test_api_key_masked(self, tmp_path: Path):
        cfg_data = {
            "models": {
                "openai": {
                    "api_key": "sk-secret123",
                    "model": "gpt-4",
                    "base_url": "https://api.openai.com/v1",
                }
            }
        }
        cfg_file = tmp_path / "test_llm_cfg.json"
        cfg_file.write_text(json.dumps(cfg_data), encoding="utf-8")
        with patch.dict(
            "os.environ",
            {"ELECTROCHEM_V6_LLM_CONFIG_FILE": str(cfg_file), "USERPROFILE": str(tmp_path)},
            clear=True,
        ):
            result = get_masked_config()
        openai_cfg = result["models"].get("openai", {})
        assert openai_cfg.get("api_key") == ""
        assert openai_cfg.get("has_api_key") is True
        assert openai_cfg.get("api_key_source") == "saved"
        assert openai_cfg.get("api_key_env") == ""

    def test_api_key_source_env(self, tmp_path: Path):
        cfg_data = {
            "models": {
                "openai": {
                    "api_key": "sk-saved",
                    "model": "gpt-4",
                    "base_url": "https://api.openai.com/v1",
                }
            }
        }
        cfg_file = tmp_path / "test_llm_cfg.json"
        cfg_file.write_text(json.dumps(cfg_data), encoding="utf-8")
        with patch.dict(
            "os.environ",
            {
                "ELECTROCHEM_V6_LLM_CONFIG_FILE": str(cfg_file),
                "OPENAI_API_KEY": "sk-env",
                "USERPROFILE": str(tmp_path),
            },
            clear=True,
        ):
            result = get_masked_config()
        openai_cfg = result["models"].get("openai", {})
        assert openai_cfg.get("api_key") == ""
        assert openai_cfg.get("has_api_key") is True
        assert openai_cfg.get("api_key_source") == "env"
        assert openai_cfg.get("api_key_env") == "OPENAI_API_KEY"


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  update_provider                                                        ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestUpdateProvider:
    def _with_temp_config(self, tmp_path: Path):
        """Return a context-manager-like env dict for isolated config."""
        cfg_file = tmp_path / "test_llm_cfg.json"
        cfg_file.write_text("{}", encoding="utf-8")
        return {"ELECTROCHEM_V6_LLM_CONFIG_FILE": str(cfg_file)}

    def test_missing_provider(self, tmp_path: Path):
        env = self._with_temp_config(tmp_path)
        with patch.dict("os.environ", env):
            result = update_provider({})
        assert result["status"] == "error"
        assert "provider" in result["message"]

    def test_empty_provider(self, tmp_path: Path):
        env = self._with_temp_config(tmp_path)
        with patch.dict("os.environ", env):
            result = update_provider({"provider": ""})
        assert result["status"] == "error"

    def test_empty_base_url_rejected(self, tmp_path: Path):
        env = self._with_temp_config(tmp_path)
        with patch.dict("os.environ", env):
            result = update_provider({"provider": "openai", "base_url": ""})
        assert result["status"] == "error"
        assert "base_url" in result["message"]

    def test_empty_model_rejected(self, tmp_path: Path):
        env = self._with_temp_config(tmp_path)
        with patch.dict("os.environ", env):
            result = update_provider({"provider": "openai", "model": ""})
        assert result["status"] == "error"
        assert "model" in result["message"]

    def test_invalid_timeout(self, tmp_path: Path):
        env = self._with_temp_config(tmp_path)
        with patch.dict("os.environ", env):
            result = update_provider({"provider": "openai", "timeout": "abc"})
        assert result["status"] == "error"
        assert "timeout" in result["message"]

    def test_negative_timeout(self, tmp_path: Path):
        env = self._with_temp_config(tmp_path)
        with patch.dict("os.environ", env):
            result = update_provider({"provider": "openai", "timeout": "-5"})
        assert result["status"] == "error"

    def test_no_update_fields(self, tmp_path: Path):
        env = self._with_temp_config(tmp_path)
        with patch.dict("os.environ", env):
            result = update_provider({"provider": "openai"})
        assert result["status"] == "error"
        assert "更新" in result["message"]

    def test_valid_update(self, tmp_path: Path):
        env = self._with_temp_config(tmp_path)
        with patch.dict("os.environ", env):
            result = update_provider({
                "provider": "openai",
                "api_key": "sk-new-key",
                "timeout": "30",
            })
        assert result["status"] == "success"
        assert result["provider"] == "openai"
        assert result["config"]["api_key"] == ""  # masked
        assert result["config"]["has_api_key"] is True

    def test_provider_alias_resolved(self, tmp_path: Path):
        env = self._with_temp_config(tmp_path)
        with patch.dict("os.environ", env):
            result = update_provider({"provider": "dashscope", "api_key": "key123"})
        assert result["status"] == "success"
        assert result["provider"] == "qwen"  # alias resolved

    def test_save_failure_is_reported(self, tmp_path: Path):
        env = self._with_temp_config(tmp_path)
        with patch.dict("os.environ", env), patch(
            "electrochem_v6.llm.config.LLMConfig.save_config",
            return_value=False,
        ):
            result = update_provider({"provider": "openai", "model": "gpt-test"})

        assert result["status"] == "error"
        assert result["provider"] == "openai"
        assert "保存失败" in result["message"]


class TestProviderConnection:
    def test_missing_provider(self):
        result = check_provider_connection({})
        assert result["status"] == "error"
        assert "provider" in result["message"]

    def test_missing_api_key(self, tmp_path: Path):
        cfg_file = tmp_path / "test_llm_cfg.json"
        cfg_file.write_text("{}", encoding="utf-8")
        with patch.dict("os.environ", {"ELECTROCHEM_V6_LLM_CONFIG_FILE": str(cfg_file), "OPENAI_API_KEY": ""}):
            result = check_provider_connection({"provider": "openai"})
        assert result["status"] == "error"
        assert "API Key" in result["message"]

    def test_success_with_unsaved_api_key(self, tmp_path: Path):
        cfg_file = tmp_path / "test_llm_cfg.json"
        cfg_file.write_text("{}", encoding="utf-8")
        mock_client = MagicMock()
        mock_client.chat.return_value = {"role": "assistant", "content": "OK"}
        with patch.dict("os.environ", {"ELECTROCHEM_V6_LLM_CONFIG_FILE": str(cfg_file)}), patch(
            "electrochem_v6.llm.config_adapter.create_llm_client",
            return_value=mock_client,
        ):
            result = check_provider_connection(
                {
                    "provider": "openai",
                    "api_key": "sk-unsaved-key",
                    "model": "gpt-test",
                    "base_url": "https://example.test/v1",
                }
            )
        assert result["status"] == "success"
        assert result["provider"] == "openai"
        assert result["model"] == "gpt-test"
