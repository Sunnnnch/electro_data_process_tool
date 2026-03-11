"""
Factory helpers for creating LLM clients based on configuration.
"""

from __future__ import annotations

from typing import Optional, Type

from .base_client import BaseLLMClient
from .config import LLMConfig
from .deepseek_client import DeepSeekClient
from .kimi_client import KimiClient
from .openai_client import OpenAIClient
from .openai_compatible_client import OpenAICompatibleHTTPClient
from .qwen_client import QwenClient


def create_llm_client(
    config: LLMConfig,
    provider: Optional[str] = None,
    model_override: Optional[str] = None,
) -> BaseLLMClient:
    """
    Create a chat client for the specified provider.

    Args:
        config: LLMConfig instance.
        provider: Optional provider key; falls back to config.default_model.
        model_override: Optional explicit model name.

    Returns:
        Configured OpenAI-compatible client.

    Raises:
        ValueError: if provider/config/API key is missing.
    """

    provider_key = config.normalize_provider(provider)
    model_cfg = config.get_model_config(provider_key)
    if not model_cfg:
        raise ValueError(f"未找到提供商配置: {provider_key}")

    api_key = config.get_api_key(provider_key)
    if not api_key:
        raise ValueError(f"未配置 {provider_key} API 密钥，请先更新 llm_config.json")

    model_name = model_override or model_cfg.get("model") or "gpt-4-turbo-preview"
    base_url = model_cfg.get("base_url")
    if not base_url and provider_key == "openai":
        base_url = "https://api.openai.com/v1"
    if not base_url:
        raise ValueError(f"{provider_key} 提供商必须配置 base_url")
    timeout = model_cfg.get("timeout", 60)
    extra_headers = model_cfg.get("extra_headers", {})

    client_cls: Type[BaseLLMClient]
    if provider_key == "openai":
        client_cls = OpenAIClient
    elif provider_key == "deepseek":
        client_cls = DeepSeekClient
    elif provider_key == "qwen":
        client_cls = QwenClient
    elif provider_key == "kimi":
        client_cls = KimiClient
    else:
        client_cls = OpenAICompatibleHTTPClient

    if client_cls is OpenAIClient:
        return client_cls(
            api_key=api_key,
            model=model_name,
            base_url=base_url,
            timeout=timeout,
        )

    if client_cls is DeepSeekClient:
        return client_cls(
            api_key=api_key,
            model=model_name,
            base_url=base_url,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    # OpenAICompatibleHTTPClient (and subclasses) share the same signature.
    return client_cls(
        api_key=api_key,
        model=model_name,
        base_url=base_url,
        timeout=timeout,
        extra_headers=extra_headers,  # pyright: ignore[reportCallIssue]
    )


__all__ = ["create_llm_client"]
