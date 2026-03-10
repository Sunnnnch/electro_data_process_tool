"""LLM configuration adapter for v6."""

from __future__ import annotations

from typing import Any, Dict

from electrochem_v6.llm.config import LLMConfig


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
            safe_entry["has_api_key"] = bool(str(cfg.get_api_key(provider) or "").strip())
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

    cfg.update_model_entry(provider, update_fields)
    model_cfg = cfg.get_model_config(provider)
    model_cfg["api_key"] = ""
    model_cfg["has_api_key"] = bool(str(cfg.get_api_key(provider) or "").strip())
    return {"status": "success", "provider": provider, "config": model_cfg}
