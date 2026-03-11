"""
Vision-capable LLM client for analyzing waveform plots.
Supports OpenAI-compatible Responses API.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Dict, Optional


class VisionClient:
    """Simple wrapper around OpenAI (or compatible) multimodal endpoints."""

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1", timeout: int = 60):
        try:
            import openai
        except ImportError as exc:  # pragma: no cover
            raise ImportError("需要安装 openai 库方可使用视觉模型：pip install openai") from exc

        self._openai = openai
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self.model = model
        self.timeout = timeout

    def analyze_image(self, image_path: str, prompt: str, max_tokens: int = 800) -> Dict:
        """Send an image + prompt to the multimodal model."""
        try:
            payload = self._build_payload(image_path, prompt)
        except Exception as exc:
            return {"success": False, "error": f"无法读取图像: {exc}"}

        try:
            response = self.client.responses.create(
                model=self.model,
                input=[payload],
                max_output_tokens=max_tokens,
            )
            output_text = self._extract_text(response)
            return {
                "success": True,
                "result": output_text,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "type": exc.__class__.__name__}

    def _build_payload(self, image_path: str, prompt: str) -> Dict:
        resolved = Path(image_path).resolve()
        suffix = resolved.suffix.lower().lstrip(".") or "png"
        if suffix not in ("png", "jpg", "jpeg", "gif", "bmp", "webp"):
            raise ValueError(f"不支持的图像格式: {suffix}")
        if not resolved.is_file():
            raise FileNotFoundError(f"图像文件不存在: {image_path}")
        image_bytes = resolved.read_bytes()
        mime = f"image/{'jpeg' if suffix in ['jpg', 'jpeg'] else suffix}"
        data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"

        content = []
        if prompt:
            content.append({"type": "input_text", "text": prompt})
        content.append({"type": "input_image", "image_url": data_url})
        return {"role": "user", "content": content}

    def _extract_text(self, response) -> str:
        try:
            if hasattr(response, "output_text"):
                text = getattr(response, "output_text")
                if text:
                    return "\n".join(text) if isinstance(text, list) else str(text)
            outputs = getattr(response, "output", None) or []
            collected = []
            for item in outputs:
                content = getattr(item, "content", None)
                if not content and isinstance(item, dict):
                    content = item.get("content")
                if not content:
                    collected.append(str(item))
                    continue
                for chunk in content:
                    text = None
                    if hasattr(chunk, "text"):
                        text = chunk.text
                    elif isinstance(chunk, dict):
                        text = chunk.get("text")
                    if text:
                        collected.append(text)
            if collected:
                return "\n".join(filter(None, collected))
            return ""
        except Exception:
            try:
                return response.choices[0].message.content  # type: ignore[attr-defined]
            except Exception:
                return ""


__all__ = ["VisionClient"]

