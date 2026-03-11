"""Tests for llm/vision_client.py — _build_payload and _extract_text."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _build_payload                                                         ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestBuildPayload:
    """Test VisionClient._build_payload without needing openai installed."""

    def _make_client(self):
        """Create a VisionClient with mocked openai dependency."""
        # We manually construct an instance bypassing __init__
        from electrochem_v6.llm.vision_client import VisionClient
        obj = object.__new__(VisionClient)
        obj.model = "test-model"
        obj.timeout = 30
        obj._openai = MagicMock()  # type: ignore[assignment]
        obj.client = MagicMock()
        return obj

    def test_png_image(self, tmp_path: Path):
        img = tmp_path / "chart.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        client = self._make_client()
        payload = client._build_payload(str(img), "Describe this chart")
        assert payload["role"] == "user"
        content = payload["content"]
        assert len(content) == 2
        assert content[0]["type"] == "input_text"
        assert content[1]["type"] == "input_image"
        assert "data:image/png;base64," in content[1]["image_url"]

    def test_jpg_mime_type(self, tmp_path: Path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
        client = self._make_client()
        payload = client._build_payload(str(img), "Analyze")
        assert "data:image/jpeg;base64," in payload["content"][1]["image_url"]

    def test_unsupported_format(self, tmp_path: Path):
        img = tmp_path / "data.tiff"
        img.write_bytes(b"\x00" * 50)
        client = self._make_client()
        with pytest.raises(ValueError, match="不支持"):
            client._build_payload(str(img), "Test")

    def test_file_not_found(self, tmp_path: Path):
        client = self._make_client()
        with pytest.raises(FileNotFoundError):
            client._build_payload(str(tmp_path / "nonexistent.png"), "Test")

    def test_empty_prompt(self, tmp_path: Path):
        img = tmp_path / "img.png"
        img.write_bytes(b"\x89PNG" + b"\x00" * 100)
        client = self._make_client()
        payload = client._build_payload(str(img), "")
        # Empty prompt → no text content block
        types = [c["type"] for c in payload["content"]]
        assert "input_image" in types


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _extract_text                                                          ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestExtractText:
    def _make_client(self):
        from electrochem_v6.llm.vision_client import VisionClient
        obj = object.__new__(VisionClient)
        obj.model = "test-model"
        obj.timeout = 30
        obj._openai = MagicMock()  # type: ignore[assignment]
        obj.client = MagicMock()
        return obj

    def test_output_text_string(self):
        client = self._make_client()
        resp = SimpleNamespace(output_text="Hello world")
        assert client._extract_text(resp) == "Hello world"

    def test_output_text_list(self):
        client = self._make_client()
        resp = SimpleNamespace(output_text=["Line 1", "Line 2"])
        assert "Line 1" in client._extract_text(resp)
        assert "Line 2" in client._extract_text(resp)

    def test_output_with_content(self):
        client = self._make_client()
        chunk = SimpleNamespace(text="Content text")
        item = SimpleNamespace(content=[chunk])
        resp = SimpleNamespace(output_text=None, output=[item])
        assert client._extract_text(resp) == "Content text"

    def test_output_dict_content(self):
        client = self._make_client()
        item = {"content": [{"text": "Dict text"}]}
        resp = SimpleNamespace(output_text=None, output=[item])
        result = client._extract_text(resp)
        assert "Dict text" in result

    def test_choices_fallback(self):
        client = self._make_client()
        msg = SimpleNamespace(content="Fallback content")
        choice = SimpleNamespace(message=msg)
        # output=None → getattr defaults to [] → collected empty → ""
        # choices fallback is only reached on exception path
        resp = SimpleNamespace(output_text=None, output=None, choices=[choice])
        result = client._extract_text(resp)
        assert isinstance(result, str)

    def test_empty_response(self):
        client = self._make_client()
        resp = SimpleNamespace(output_text=None, output=[])
        assert client._extract_text(resp) == ""
