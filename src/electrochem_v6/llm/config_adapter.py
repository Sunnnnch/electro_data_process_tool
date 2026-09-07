"""LLM configuration adapter for v6."""

from __future__ import annotations

import os
from typing import Any, Dict

from electrochem_v6.llm.config import LLMConfig
from electrochem_v6.llm.error_utils import sanitize_llm_error
from electrochem_v6.llm.factory import create_llm_client


def _api_key_meta(cfg: LLMConfig, provider: str, entry: Dict[str, Any] | None = None) -> Dict[str, Any]:
    provider = cfg.normalize_provider(provider)
    env_key = f"{provider.upper()}_API_KEY"
    env_present = env_key in os.environ
    env_value = str(os.environ.get(env_key) or "").strip()
    saved_value = str((entry or {}).get("api_key") or "").strip()
    if env_present and env_value:
        source = "env"
    elif saved_value:
        source = "saved"
    elif env_present:
        source = "env_empty"
    else:
        source = "none"
    return {
        "has_api_key": bool(str(cfg.get_api_key(provider) or "").strip()),
        "api_key_source": source,
        "api_key_env": env_key if env_present else "",
    }


def get_masked_config() -> Dict[str, Any]:
    cfg = LLMConfig()
    models = cfg.list_models()
    sanitized = {}
    if isinstance(models, dict):
        for provider, entry in models.items():
            if not isinstance(entry, dict):
                continue
            safe_entry = dict(entry)
            safe_entry["api_key"] = ""
            safe_entry.update(_api_key_meta(cfg, provider, entry))
            sanitized[provider] = safe_entry
    return {
        "status": "success",
        "default_provider": cfg.normalize_provider(cfg.config.get("default_model", "openai")),
        "models": sanitized,
    }


def update_provider(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_provider = payload.get("provider")
    if raw_provider is None or not str(raw_provider).strip():
        return {"status": "error", "message": "provider 字段不能为空"}
    cfg = LLMConfig()
    provider = cfg.normalize_provider(str(raw_provider).strip())
    update_fields: Dict[str, Any] = {}
    for field in ("api_key", "base_url", "model", "display_name", "timeout"):
        if field not in payload or payload[field] is None:
            continue
        value = payload[field]
        if isinstance(value, str):
            value = value.strip()
        if field in ("base_url", "model") and isinstance(value, str) and not value:
            return {"status": "error", "message": f"{field} 不能为空"}
        if field == "timeout":
            try:
                value = int(value)
            except (TypeError, ValueError):
                return {"status": "error", "message": "timeout 必须是正整数"}
            if value <= 0:
                return {"status": "error", "message": "timeout 必须是正整数"}
        update_fields[field] = value
    if not update_fields:
        return {"status": "error", "message": "没有需要更新的字段"}

    if not cfg.update_model_entry(provider, update_fields):
        return {
            "status": "error",
            "message": "AI 配置保存失败，请检查数据目录是否可写",
            "provider": provider,
        }
    model_cfg = cfg.get_model_config(provider)
    model_cfg["api_key"] = ""
    model_cfg.update(_api_key_meta(cfg, provider, cfg.get_model_config(provider)))
    return {"status": "success", "provider": provider, "config": model_cfg}


def check_provider_connection(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_provider = payload.get("provider")
    if raw_provider is None or not str(raw_provider).strip():
        return {"status": "error", "message": "provider 字段不能为空"}

    cfg = LLMConfig()
    provider = cfg.normalize_provider(str(raw_provider).strip())
    model_cfg = cfg.get_model_config(provider) or {}

    for field in ("api_key", "base_url", "model", "timeout"):
        if field not in payload or payload[field] is None:
            continue
        value = payload[field]
        if isinstance(value, str):
            value = value.strip()
        if field == "api_key" and not value:
            continue
        if field in ("base_url", "model") and isinstance(value, str) and not value:
            return {"status": "error", "message": f"{field} 不能为空"}
        if field == "timeout":
            try:
                value = int(value)
            except (TypeError, ValueError):
                return {"status": "error", "message": "timeout 必须是正整数"}
            if value <= 0:
                return {"status": "error", "message": "timeout 必须是正整数"}
        model_cfg[field] = value

    api_key = str(model_cfg.get("api_key") or cfg.get_api_key(provider) or "").strip()
    if not api_key:
        return {"status": "error", "message": f"未配置 {provider} API Key"}
    model_cfg["api_key"] = api_key
    cfg.config.setdefault("models", {})[provider] = model_cfg

    try:
        client = create_llm_client(
            cfg,
            provider=provider,
            model_override=str(model_cfg.get("model") or "").strip() or None,
        )
        response = client.chat(
            [{"role": "user", "content": "请只回复 OK，用于连接测试。"}],
            temperature=0,
            max_tokens=16,
        )
    except Exception as exc:
        return {"status": "error", "message": sanitize_llm_error(exc), "provider": provider}

    if not response or response.get("error"):
        return {
            "status": "error",
            "message": sanitize_llm_error((response or {}).get("error") or "模型未返回有效响应"),
            "provider": provider,
            "model": model_cfg.get("model"),
        }
    return {
        "status": "success",
        "message": "连接测试通过",
        "provider": provider,
        "model": model_cfg.get("model"),
    }
