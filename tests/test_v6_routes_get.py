"""Tests for routes_get.py — GET endpoint dispatching and helpers."""

from unittest.mock import MagicMock

from electrochem_v6.server.routes_get import _safe_int

# ── _safe_int ─────────────────────────────────────────────────────

class TestSafeInt:
    def test_valid_int(self):
        assert _safe_int("5", 10) == 5

    def test_default_on_invalid(self):
        assert _safe_int("abc", 10) == 10

    def test_clamp_low(self):
        assert _safe_int("-5", 10, lo=1, hi=100) == 1

    def test_clamp_high(self):
        assert _safe_int("99999", 10, lo=1, hi=100) == 100

    def test_none_input(self):
        assert _safe_int(None, 42) == 42

    def test_float_string_fails(self):
        assert _safe_int("3.14", 10) == 10

    def test_boundary_low(self):
        assert _safe_int("1", 10, lo=1) == 1

    def test_boundary_high(self):
        assert _safe_int("10000", 10, hi=10000) == 10000


# ── dispatch_get mock handler ─────────────────────────────────────

def _make_mock_handler(path, query=""):
    handler = MagicMock()
    handler.path = f"{path}?{query}" if query else path
    handler._send_json = MagicMock()
    handler._send_binary = MagicMock()
    return handler


class TestDispatchGet:
    def test_root_returns_api_list(self):
        from electrochem_v6.server.routes_get import dispatch_get
        handler = _make_mock_handler("/")
        result = dispatch_get(handler)
        assert result is True
        handler._send_json.assert_called_once()
        args = handler._send_json.call_args
        assert args[0][0] == 200

    def test_health_endpoint(self):
        from electrochem_v6.server.routes_get import dispatch_get
        handler = _make_mock_handler("/health")
        result = dispatch_get(handler)
        assert result is True
        handler._send_json.assert_called_once()
        code = handler._send_json.call_args[0][0]
        assert code == 200

    def test_unknown_path(self):
        from electrochem_v6.server.routes_get import dispatch_get
        handler = _make_mock_handler("/does-not-exist")
        result = dispatch_get(handler)
        assert result is False

    def test_history_endpoint(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "h.json"))
        monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(tmp_path / "p.json"))
        from electrochem_v6.server.routes_get import dispatch_get
        handler = _make_mock_handler("/api/v1/history")
        result = dispatch_get(handler)
        assert result is True
        handler._send_json.assert_called_once()

    def test_stats_endpoint(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "h.json"))
        monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(tmp_path / "p.json"))
        from electrochem_v6.server.routes_get import dispatch_get
        handler = _make_mock_handler("/api/v1/stats")
        result = dispatch_get(handler)
        assert result is True
        handler._send_json.assert_called_once()

    def test_quality_report_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELECTROCHEM_V6_QUALITY_REPORT_FILE", str(tmp_path / "qr.json"))
        from electrochem_v6.server.routes_get import dispatch_get
        handler = _make_mock_handler("/api/v1/quality-report/latest")
        result = dispatch_get(handler)
        assert result is True
        code = handler._send_json.call_args[0][0]
        # Should indicate error (no report file)
        body = handler._send_json.call_args[0][1]
        assert body.get("status") == "error" or code >= 400

    def test_projects_list(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(tmp_path / "p.json"))
        monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "h.json"))
        from electrochem_v6.server.routes_get import dispatch_get
        handler = _make_mock_handler("/api/v1/projects")
        result = dispatch_get(handler)
        assert result is True
        handler._send_json.assert_called_once()

    def test_llm_config_masked(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", str(tmp_path / "llm.json"))
        from electrochem_v6.server.routes_get import dispatch_get
        handler = _make_mock_handler("/api/v1/llm/config")
        result = dispatch_get(handler)
        assert result is True
        handler._send_json.assert_called_once()

    def test_templates_list(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELECTROCHEM_V6_TEMPLATE_FILE", str(tmp_path / "tpl.json"))
        from electrochem_v6.server.routes_get import dispatch_get
        handler = _make_mock_handler("/api/v1/process/templates")
        result = dispatch_get(handler)
        assert result is True
        handler._send_json.assert_called_once()

    def test_conversations_list(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ELECTROCHEM_V6_CONVERSATION_FILE", str(tmp_path / "conv.json"))
        from electrochem_v6.server.routes_get import dispatch_get
        handler = _make_mock_handler("/api/v1/agent/conversations")
        result = dispatch_get(handler)
        assert result is True
        handler._send_json.assert_called_once()
