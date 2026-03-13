"""
DeepSeek client implementation compatible with BaseLLMClient.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Optional

import requests

from .base_client import BaseLLMClient


class DeepSeekClient(BaseLLMClient):
    """HTTP client for DeepSeek chat models."""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com/v1",
        timeout: int = 60,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        if not api_key:
            raise ValueError("DeepSeek API key is required")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key
        self.extra_headers = extra_headers or {}
        self.session = requests.Session()

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.extra_headers)
        return headers

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            response = self.session.post(
                f"{self.base_url}/chat/completions",
                headers=self._build_headers(),
                data=json.dumps(payload),
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            return {"error": str(exc)}
        except ValueError as exc:
            return {"error": f"Invalid JSON: {exc}"}
        if "choices" not in data or not data["choices"]:
            return {"error": "DeepSeek response missing choices"}

        message = data["choices"][0].get("message", {})
        result: Dict[str, Any] = {
            "role": message.get("role", "assistant"),
            "content": message.get("content", ""),
        }
        if message.get("tool_calls"):
            result["tool_calls"] = message["tool_calls"]
        return result

    def stream_chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> Iterator[Dict[str, Any]]:
        raise NotImplementedError("DeepSeek streaming API is not implemented")


__all__ = ["DeepSeekClient"]
