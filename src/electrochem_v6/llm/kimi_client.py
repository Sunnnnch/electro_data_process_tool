"""
Moonshot / Kimi client built on the OpenAI-compatible HTTP helper.
"""

from __future__ import annotations

from typing import Dict, Optional

from .openai_compatible_client import OpenAICompatibleHTTPClient


class KimiClient(OpenAICompatibleHTTPClient):
    """Client for Moonshot / Kimi OpenAI-compatible endpoints."""

    DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"

    def __init__(
        self,
        api_key: str,
        model: str = "moonshot-v1-vision",
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


__all__ = ["KimiClient"]
