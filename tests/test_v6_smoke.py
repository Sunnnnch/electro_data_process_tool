"""Tests for smoke.py — helper functions and smoke run logic.

Tests cover: _read_json, _read_json_allow_error, _wait_health, run_smoke.
The server is *not* actually started; HTTP calls are mocked.
"""
from __future__ import annotations

import io
import json
from email.message import Message
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from electrochem_v6.smoke import (
    _read_json,
    _read_json_allow_error,
    _wait_health,
    run_smoke,
)

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _read_json                                                             ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestReadJson:
    """Unit tests for _read_json helper."""

    def _mock_urlopen(self, body: Dict[str, Any], status: int = 200):
        """Return a context-manager mock that behaves like urlopen."""
        resp = MagicMock()
        resp.status = status
        resp.read.return_value = json.dumps(body).encode("utf-8")
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    @patch("electrochem_v6.smoke.request.urlopen")
    def test_get_returns_status_and_body(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_urlopen({"status": "ok"})
        status, payload = _read_json("http://localhost:8010/health")
        assert status == 200
        assert payload == {"status": "ok"}

    @patch("electrochem_v6.smoke.request.urlopen")
    def test_post_with_payload(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_urlopen({"status": "success"})
        status, payload = _read_json(
            "http://localhost:8010/api/v1/projects",
            method="POST",
            payload={"name": "test"},
        )
        assert status == 200
        # Verify that a Request with data was created
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.data is not None


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _read_json_allow_error                                                 ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestReadJsonAllowError:
    """Unit tests for _read_json_allow_error — graceful error handling."""

    @patch("electrochem_v6.smoke.request.urlopen")
    def test_success_passthrough(self, mock_urlopen):
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = json.dumps({"ok": True}).encode()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp
        status, payload = _read_json_allow_error("http://x/api")
        assert status == 200
        assert payload["ok"] is True

    @patch("electrochem_v6.smoke._read_json")
    def test_http_error_json_body(self, mock_read):
        from urllib.error import HTTPError

        body = json.dumps({"status": "error", "message": "bad"}).encode()
        exc = HTTPError("http://x", 400, "Bad Request", Message(), io.BytesIO(body))
        mock_read.side_effect = exc
        status, payload = _read_json_allow_error("http://x/api")
        assert status == 400
        assert payload["message"] == "bad"

    @patch("electrochem_v6.smoke._read_json")
    def test_http_error_non_json_body(self, mock_read):
        from urllib.error import HTTPError

        exc = HTTPError("http://x", 500, "Error", Message(), io.BytesIO(b"not json"))
        mock_read.side_effect = exc
        status, payload = _read_json_allow_error("http://x/api")
        assert status == 500
        assert "not json" in payload.get("message", "")

    @patch("electrochem_v6.smoke._read_json")
    def test_json_decode_error(self, mock_read):
        mock_read.side_effect = json.JSONDecodeError("err", "", 0)
        status, payload = _read_json_allow_error("http://x/api")
        assert status == 200
        assert payload["status"] == "non_json"


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _wait_health                                                           ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestWaitHealth:
    @patch("electrochem_v6.smoke._read_json")
    def test_immediate_healthy(self, mock_read):
        mock_read.return_value = (200, {"status": "ok"})
        _wait_health("http://localhost:8010", timeout_s=1.0)  # Should not raise

    @patch("electrochem_v6.smoke._read_json")
    def test_timeout_raises(self, mock_read):
        mock_read.side_effect = ConnectionRefusedError("refused")
        with pytest.raises(RuntimeError, match="timeout"):
            _wait_health("http://localhost:8010", timeout_s=0.2)

    @patch("electrochem_v6.smoke._read_json")
    def test_eventually_healthy(self, mock_read):
        """First call fails, second succeeds."""
        mock_read.side_effect = [
            ConnectionRefusedError("not yet"),
            (200, {"status": "ok"}),
        ]
        _wait_health("http://localhost:8010", timeout_s=2.0)

    @patch("electrochem_v6.smoke._read_json")
    def test_non_ok_status_retries(self, mock_read):
        """Health returns 200 but status != ok → keep retrying."""
        mock_read.side_effect = [
            (200, {"status": "starting"}),
            (200, {"status": "ok"}),
        ]
        _wait_health("http://localhost:8010", timeout_s=2.0)


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  run_smoke (integration with mocked server)                             ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestRunSmoke:
    """Test run_smoke with fully mocked V6ServerManager and HTTP calls."""

    def _setup_mocks(self, mock_mgr_cls, mock_read, mock_read_err, mock_wait):
        """Configure mock server manager and HTTP helpers for happy path."""
        manager = MagicMock()
        manager.start.return_value = (True, "started")
        manager.stop.return_value = None
        mock_mgr_cls.return_value = manager

        # _wait_health succeeds
        mock_wait.return_value = None

        # All _read_json calls succeed
        mock_read.return_value = (200, {"status": "success"})

        # _read_json_allow_error calls
        mock_read_err.side_effect = [
            (404, {}),      # quality-report/latest → 404 ok
            (400, {}),      # process → 400 ok
            (400, {}),      # process-zip → 400 ok
            (200, {"status": "non_json"}),  # ui → 200 ok
        ]
        return manager

    @patch("electrochem_v6.smoke._wait_health")
    @patch("electrochem_v6.smoke._read_json_allow_error")
    @patch("electrochem_v6.smoke._read_json")
    @patch("electrochem_v6.smoke.V6ServerManager")
    def test_all_checks_pass(self, mock_mgr_cls, mock_read, mock_read_err, mock_wait):
        self._setup_mocks(mock_mgr_cls, mock_read, mock_read_err, mock_wait)
        result = run_smoke(port=19999)
        assert result["ok"] is True
        assert len(result["checks"]) == 8

    @patch("electrochem_v6.smoke.V6ServerManager")
    def test_start_failure(self, mock_mgr_cls):
        manager = MagicMock()
        manager.start.return_value = (False, "port in use")
        mock_mgr_cls.return_value = manager
        result = run_smoke(port=19999)
        assert result["ok"] is False
        assert result["stage"] == "start"

    @patch("electrochem_v6.smoke._wait_health")
    @patch("electrochem_v6.smoke._read_json_allow_error")
    @patch("electrochem_v6.smoke._read_json")
    @patch("electrochem_v6.smoke.V6ServerManager")
    def test_one_check_fails(self, mock_mgr_cls, mock_read, mock_read_err, mock_wait):
        manager = self._setup_mocks(mock_mgr_cls, mock_read, mock_read_err, mock_wait)
        # Override first _read_json to return 500
        mock_read.side_effect = [
            (500, {"status": "error"}),   # projects_get → fail
            (200, {"status": "success"}),  # projects_post
            (200, {"status": "success"}),  # llm_config_get
            (200, {"status": "success"}),  # history_get
        ]
        result = run_smoke(port=19999)
        assert result["ok"] is False  # one check failed
        manager.stop.assert_called_once()

    @patch("electrochem_v6.smoke._wait_health")
    @patch("electrochem_v6.smoke._read_json")
    @patch("electrochem_v6.smoke.V6ServerManager")
    def test_exception_during_checks(self, mock_mgr_cls, mock_read, mock_wait):
        manager = MagicMock()
        manager.start.return_value = (True, "ok")
        mock_mgr_cls.return_value = manager
        mock_wait.return_value = None
        mock_read.side_effect = Exception("network error")
        result = run_smoke(port=19999)
        assert result["ok"] is False
        assert result["stage"] == "exception"
        manager.stop.assert_called_once()

    @patch("electrochem_v6.smoke._wait_health")
    @patch("electrochem_v6.smoke._read_json")
    @patch("electrochem_v6.smoke.V6ServerManager")
    def test_http_error_during_checks(self, mock_mgr_cls, mock_read, mock_wait):
        from urllib.error import HTTPError

        manager = MagicMock()
        manager.start.return_value = (True, "ok")
        mock_mgr_cls.return_value = manager
        mock_wait.return_value = None
        mock_read.side_effect = HTTPError(
            "http://x", 503, "Service Unavailable", Message(), io.BytesIO(b"down")
        )
        result = run_smoke(port=19999)
        assert result["ok"] is False
        assert result["stage"] == "http"
        assert result["code"] == 503
        manager.stop.assert_called_once()
