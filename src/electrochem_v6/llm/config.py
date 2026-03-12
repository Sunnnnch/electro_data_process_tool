"""
LLM configuration management.
Handles API keys, model selection, and preferences.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

PROVIDER_ALIASES = {
    "dashscope": "qwen",
    "aliyun": "qwen",
    "ali": "qwen",
    "moonshot": "kimi",
    "moonshotai": "kimi",
    "moonshot_ai": "kimi",
    "kimi": "kimi",
    "openai-compatible": "openai",
    "azure": "openai",
}


class LLMConfig:
    """LLM configuration manager."""

    DEFAULT_CONFIG = {
        "default_model": "openai",
        "models": {
            "openai": {
                "api_key": "",
                "model": "gpt-4-turbo-preview",
                "base_url": "https://api.openai.com/v1",
                "timeout": 60,
                "display_name": "OpenAI",
                "supports_vision": True,
            },
            "deepseek": {
                "api_key": "",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com/v1",
                "timeout": 60,
                "display_name": "DeepSeek",
                "supports_vision": False,
            },
            "qwen": {
                "api_key": "",
                "model": "qwen-vl-max",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "timeout": 60,
                "display_name": "Qwen",
                "supports_vision": True,
            },
            "kimi": {
                "api_key": "",
                "model": "moonshot-v1-vision",
                "base_url": "https://api.moonshot.cn/v1",
                "timeout": 60,
                "display_name": "Kimi",
                "supports_vision": True,
            },
        },
        "vision": {
            "enabled": False,
            "provider": "openai",
            "api_key": "",
            "model": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
            "timeout": 60,
            "max_tokens": 800,
        },
        "agent": {
            "max_iterations": 10,
            "temperature": 0.7,
            "max_tokens": 4000,
        },
    }

    def __init__(self, config_file: str = "llm_config.json"):
        self.config_file = config_file
        self.config = self.load_config()

    def _env_config_path(self) -> Optional[Path]:
        for key in ("ELECTROCHEM_V6_LLM_CONFIG_FILE", "ELECTROCHEM_LLM_CONFIG_FILE"):
            raw = os.environ.get(key)
            if raw:
                return Path(raw).expanduser()
        return None

    def _user_config_path(self) -> Path:
        # Align with central config: user-level LLM config lives under ~/.electrochem/
        # (not ~/.electrochem/v6/) for backward compatibility with v5.
        from electrochem_v6.config import _llm_user_dir
        return _llm_user_dir() / self.config_file

    def _project_config_path(self) -> Path:
        return Path(self.config_file)

    def load_config(self) -> Dict:
        """Load config with precedence: env path > user dir > project default."""
        data: Dict = {}
        env_config = self._env_config_path()
        user_config = self._user_config_path()
        project_config = self._project_config_path()

        if env_config and env_config.exists():
            try:
                with open(env_config, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        elif user_config.exists():
            try:
                with open(user_config, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        elif project_config.exists():
            try:
                with open(project_config, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        return self._merge_with_defaults(data)

    def _merge_with_defaults(self, user_cfg: Dict) -> Dict:
        merged = copy.deepcopy(self.DEFAULT_CONFIG)
        if not user_cfg:
            return merged

        if isinstance(user_cfg.get("default_model"), str):
            merged["default_model"] = user_cfg["default_model"]

        user_models = user_cfg.get("models", {})
        if isinstance(user_models, dict):
            for key, cfg in user_models.items():
                if not isinstance(cfg, dict):
                    continue
                target = merged["models"].setdefault(key, {})
                target.update(cfg)

        if isinstance(user_cfg.get("vision"), dict):
            merged["vision"].update(user_cfg["vision"])
        if isinstance(user_cfg.get("agent"), dict):
            merged["agent"].update(user_cfg["agent"])

        return merged

    def save_config(self) -> bool:
        """Save config with precedence: env path > user dir."""
        try:
            env_config = self._env_config_path()
            if env_config:
                env_config.parent.mkdir(parents=True, exist_ok=True)
                config_path = env_config
            else:
                user_dir = Path.home() / ".electrochem"
                user_dir.mkdir(parents=True, exist_ok=True)
                config_path = user_dir / self.config_file
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def get_api_key(self, provider: Optional[str] = None) -> Optional[str]:
        provider = self.normalize_provider(provider)
        env_key = f"{provider.upper()}_API_KEY"
        if env_key in os.environ:
            return os.environ[env_key]
        return self.config.get("models", {}).get(provider, {}).get("api_key")

    def set_api_key(self, provider: str, api_key: str):
        self.update_model_entry(provider, {"api_key": api_key})

    def get_model_config(self, provider: Optional[str] = None) -> Dict:
        provider = self.normalize_provider(provider)
        defaults = copy.deepcopy(self.DEFAULT_CONFIG.get("models", {}).get(provider, {}))
        current = copy.deepcopy(self.config.get("models", {}).get(provider, {}))
        if defaults:
            defaults.update(current)
            return defaults
        return current

    def get_agent_config(self) -> Dict:
        return self.config.get("agent", self.DEFAULT_CONFIG["agent"])

    def update_model_entry(self, provider: str, data: Dict[str, Any]) -> None:
        provider = self.normalize_provider(provider)
        models = self.config.setdefault("models", {})
        defaults = copy.deepcopy(self.DEFAULT_CONFIG.get("models", {}).get(provider, {}))
        merged = defaults or {}
        merged.update(copy.deepcopy(models.get(provider, {})))
        merged.update(data)
        models[provider] = merged
        self.save_config()

    def is_vision_enabled(self) -> bool:
        vision_cfg = self.config.get("vision", self.DEFAULT_CONFIG["vision"])
        return bool(vision_cfg.get("enabled"))

    def get_vision_config(self) -> Dict:
        return self.config.get("vision", self.DEFAULT_CONFIG["vision"])

    def get_vision_api_key(self) -> Optional[str]:
        cfg = self.get_vision_config()
        provider = cfg.get("provider", "openai")
        env_key = f"{provider.upper()}_VISION_API_KEY"
        if env_key in os.environ:
            return os.environ[env_key]
        if cfg.get("api_key"):
            return cfg["api_key"]
        return self.get_api_key(provider)

    def list_models(self) -> Dict[str, Dict]:
        models = copy.deepcopy(self.DEFAULT_CONFIG.get("models", {}))
        user_models = self.config.get("models", {})
        if isinstance(user_models, dict):
            for key, cfg in user_models.items():
                if not isinstance(cfg, dict):
                    continue
                target = models.setdefault(key, {})
                target.update(cfg)
        return copy.deepcopy(models)

    def set_default_provider(self, provider: str) -> None:
        provider = self.normalize_provider(provider)
        self.config["default_model"] = provider
        self.save_config()

    def normalize_provider(self, provider: Optional[str]) -> str:
        base = provider or self.config.get("default_model", "openai")
        normalized = str(base or "").strip().lower() or "openai"
        return PROVIDER_ALIASES.get(normalized, normalized)


__all__ = ["LLMConfig"]

