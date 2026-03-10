"""
Generic HTTP client for OpenAI-compatible providers (DashScope, Moonshot, etc.).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Optional

import requests

from .base_client import BaseLLMClient


class OpenAICompatibleHTTPClient(BaseLLMClient):
    """Simple HTTP client that targets OpenAI-compatible chat completion endpoints."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout: int = 60,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        if not api_key:
            raise ValueError("API key is required for OpenAI-compatible client")
        if not base_url:
            raise ValueError("Base URL is required for OpenAI-compatible client")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key
        self.extra_headers = extra_headers or {}
        self.session = requests.Session()

    # ------------------------------------------------------------------ helpers
    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.extra_headers)
        return headers

    def _parse_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        choices = payload.get("choices") or []
        if not choices:
            return {"error": "Missing choices in response"}
        message = choices[0].get("message") or {}
        result: Dict[str, Any] = {
            "role": message.get("role", "assistant"),
            "content": message.get("content", ""),
        }
        tool_calls = message.get("tool_calls")
        if tool_calls:
            result["tool_calls"] = tool_calls
        return result

    # ------------------------------------------------------------------ API
    def chat(
        self,
        messages: List[Dict[str, Any]],
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
                data=json.dumps(payload, ensure_ascii=False),
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            return self._parse_message(data)
        except requests.RequestException as exc:
            return {"error": str(exc)}
        except ValueError as exc:
            return {"error": f"Invalid JSON: {exc}"}

    def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> Iterator[Dict[str, Any]]:
        raise NotImplementedError("Streaming is not implemented for OpenAI-compatible HTTP client")


__all__ = ["OpenAICompatibleHTTPClient"]
