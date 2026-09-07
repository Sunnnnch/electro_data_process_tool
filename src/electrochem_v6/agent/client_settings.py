"""Resolve effective client settings and compare them without retaining secrets."""

from __future__ import annotations

import hashlib
import json

from electrochem_v6.llm.config import LLMConfig


def resolve_client_settings(
    config: LLMConfig,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[str, str, str]:
    provider_key = config.normalize_provider(provider or config.config.get("default_model", "openai"))
    entry = config.get_model_config(provider_key) or {}
    model_name = model or entry.get("model") or "gpt-4o"
    effective = {
        "provider": provider_key,
        "model": model_name,
        "api_key": config.get_api_key(provider_key),
        "base_url": entry.get("base_url"),
        "timeout": entry.get("timeout", 60),
        "extra_headers": entry.get("extra_headers", {}),
    }
    signature = hashlib.sha256(
        json.dumps(effective, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return provider_key, model_name, signature
