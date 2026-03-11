"""
OpenAI GPT client implementation.
Supports GPT-4, GPT-4-turbo, and GPT-3.5.
"""

from typing import Any, Dict, Iterator, List, Optional

from .base_client import BaseLLMClient


class OpenAIClient(BaseLLMClient):
    """OpenAI客户端"""

    def __init__(self, api_key: str, model: str = "gpt-4-turbo-preview",
                 base_url: str = "https://api.openai.com/v1", timeout: int = 60):
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

        self.client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self.model = model

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
            return {"error": str(e), "type": type(e).__name__}

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

            for chunk in stream:
                yield self._parse_chunk(chunk)

        except Exception as e:
            yield {"error": str(e), "type": type(e).__name__}

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
        delta = chunk.choices[0].delta

        result = {}
        if delta.content:
            result["content"] = delta.content

        if hasattr(delta, 'tool_calls') and delta.tool_calls:
            result["tool_calls"] = delta.tool_calls

        return result


__all__ = ["OpenAIClient"]




