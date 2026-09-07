"""
OpenAI GPT client implementation.
Supports GPT-4, GPT-4-turbo, and GPT-3.5.
"""

import threading
from typing import Any, Dict, Iterator, List, Optional

from .base_client import BaseLLMClient
from .error_utils import sanitize_llm_error


class OpenAIClient(BaseLLMClient):
    """OpenAI客户端"""

    def __init__(self, api_key: str, model: str = "gpt-4-turbo-preview",
                 base_url: str = "https://api.openai.com/v1", timeout: int = 60,
                 extra_headers: Optional[Dict[str, str]] = None):
        """
        初始化OpenAI客户端

        Args:
            api_key: OpenAI API密钥
            model: 模型名称（gpt-4-turbo-preview, gpt-4, gpt-3.5-turbo）
            base_url: API地址（支持自定义或代理）
            timeout: 超时时间（秒）
        """
        try:
            import openai
            self.openai = openai
        except ImportError:
            raise ImportError("需要安装openai库：pip install openai")

        self.client = openai.OpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout,
            default_headers=extra_headers or {},
        )
        self.model = model
        self._stream_lock = threading.Lock()
        self._active_stream = None

    def cancel_active_stream(self) -> None:
        """Close the current streaming HTTP response, if any."""
        with self._stream_lock:
            stream = self._active_stream
        close = getattr(stream, "close", None)
        if callable(close):
            close()

    def chat(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None,
             temperature: float = 0.7, max_tokens: int = 4000) -> Dict[str, Any]:
        """发送对话请求"""
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }

            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = self.client.chat.completions.create(**kwargs)
            return self._parse_response(response)

        except Exception as e:
            return {"error": sanitize_llm_error(e), "type": type(e).__name__}

    def stream_chat(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None,
                    temperature: float = 0.7, max_tokens: int = 4000) -> Iterator[Dict[str, Any]]:
        """流式对话请求"""
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True
            }

            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            stream = self.client.chat.completions.create(**kwargs)
            with self._stream_lock:
                self._active_stream = stream
            try:
                for chunk in stream:
                    yield self._parse_chunk(chunk)
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
                with self._stream_lock:
                    if self._active_stream is stream:
                        self._active_stream = None

        except Exception as e:
            yield {"error": sanitize_llm_error(e), "type": type(e).__name__}

    def _parse_response(self, response) -> Dict[str, Any]:
        """解析响应"""
        message = response.choices[0].message

        result = {
            "role": "assistant",
            "content": message.content or "",
        }

        # 检查工具调用
        if hasattr(message, 'tool_calls') and message.tool_calls:
            result["tool_calls"] = []
            for tool_call in message.tool_calls:
                result["tool_calls"].append({
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments
                    }
                })

        return result

    def _parse_chunk(self, chunk) -> Dict[str, Any]:
        """解析流式响应块"""
        if not getattr(chunk, "choices", None):
            return {}
        delta = chunk.choices[0].delta

        result = {}
        if delta.content:
            result["content"] = delta.content

        if hasattr(delta, 'tool_calls') and delta.tool_calls:
            result["tool_calls"] = []
            for tool_call in delta.tool_calls:
                function = getattr(tool_call, "function", None)
                result["tool_calls"].append({
                    "index": int(getattr(tool_call, "index", 0) or 0),
                    "id": getattr(tool_call, "id", None),
                    "type": getattr(tool_call, "type", None),
                    "function": {
                        "name": getattr(function, "name", None) if function is not None else None,
                        "arguments": getattr(function, "arguments", None) if function is not None else None,
                    },
                })

        return result


__all__ = ["OpenAIClient"]
