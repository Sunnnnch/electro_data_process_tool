"""
DashScope / Qwen client built on the OpenAI-compatible HTTP helper.
"""

from __future__ import annotations

from typing import Dict, Optional

from .openai_compatible_client import OpenAICompatibleHTTPClient


class QwenClient(OpenAICompatibleHTTPClient):
    """Client for Alibaba DashScope / Qwen OpenAI-compatible endpoints."""

    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def __init__(
        self,
        api_key: str,
        model: str = "qwen-vl-max",
        base_url: Optional[str] = None,
        timeout: int = 60,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url or self.DEFAULT_BASE_URL,
            timeout=timeout,
            extra_headers=extra_headers,
        )


__all__ = ["QwenClient"]
