"""Local MCP discovery and transport boundaries, using actual loopback HTTP."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from electrochem_v6.mcp.client import ElectroChemClient, MCPClientError, validate_base_url


@contextmanager
def fake_api(*, name="electrochem-v6-api", token="test-secret-credential-123456"):
    state = {"name": name, "token": token, "closing": False, "calls": [], "redirect": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            supplied = self.headers.get("X-Electrochem-Session")
            state["calls"].append((self.path, supplied))
            if state["redirect"]:
                self.send_response(302)
                self.send_header("Location", "http://example.invalid/never-request")
                self.end_headers()
                return
            if self.path == "/api/v1/mcp/status":
                status = 200 if supplied == state["token"] else 403
                value = {"status": "success" if status == 200 else "error", "name": state["name"],
                         "closing": state["closing"], "message": str(state["token"])}
            elif self.path == "/":
                status, value = 200, {"name": state["name"], "status": "running"}
            else:
                status, value = 200, {"status": "success", "projects": [{"id": state["name"]}],
                                     "session_token": state["token"], "nested": {"api_key": "private"}}
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        worker.join(5)


def descriptor(path, url, token):
    path.mkdir(parents=True, exist_ok=True)
    (path / "desktop-service.json").write_text(json.dumps({"version": 1, "pid": 1234, "url": url, "session_token": token}), encoding="utf-8")


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:8010", "http://example.com", "http://127.1:8010", "http://2130706433",
    "http://127.0.0.1.evil.example", "http://user:secret@127.0.0.1", "http://localhost:0",
    "http://localhost:65536", "http://localhost:8010/api", "http://localhost?next=anything",
    "http://localhost/#fragment", " http://localhost", "http://localhost\n",
])
def test_only_literal_loopback_origins_are_accepted(url):
    with pytest.raises(MCPClientError, match="loopback|port"):
        validate_base_url(url)


def test_discovery_rereads_restart_identity_and_never_returns_tokens(tmp_path):
    with fake_api() as (first, old), fake_api(token="replacement-secret-234567") as (second, new):
        descriptor(tmp_path, first, old["token"])
        client = ElectroChemClient(data_dir=tmp_path)
        result = client.connect().request("GET", "/api/v1/projects")
        assert result["session_token"] == "[redacted]"
        assert result["nested"]["api_key"] == "[redacted]"
        assert old["calls"] == [("/api/v1/mcp/status", old["token"]), ("/api/v1/projects", old["token"])]
        descriptor(tmp_path, second, new["token"])
        result = client.connect().request("GET", "/api/v1/projects")
        assert len(old["calls"]) == 2
        assert new["calls"][0] == ("/api/v1/mcp/status", new["token"])
        assert new["token"] not in json.dumps(result)
        descriptor(tmp_path, second, old["token"])
        with pytest.raises(MCPClientError) as failure:
            client.connect()
        assert failure.value.code == "http_403"
        assert old["token"] not in json.dumps(failure.value.payload())
        # The server must not disclose a replacement token in authentication errors.
        assert new["token"] not in json.dumps(failure.value.payload())


def test_missing_malformed_discovery_and_wrong_service_fail_closed(tmp_path):
    client = ElectroChemClient(data_dir=tmp_path)
    with pytest.raises(MCPClientError, match="Open ElectroChem"):
        client.connect()
    (tmp_path / "desktop-service.json").write_text('{"session_token":"do-not-print"}', encoding="utf-8")
    with pytest.raises(MCPClientError) as invalid:
        client.connect()
    assert invalid.value.code == "invalid_discovery"
    assert "do-not-print" not in str(invalid.value)
    with fake_api(name="other-application") as (url, _state):
        with pytest.raises(MCPClientError, match="does not identify"):
            ElectroChemClient(base_url=url).connect()


def test_explicit_url_bypasses_proxy_and_refuses_redirect_and_arbitrary_routes(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    with fake_api() as (url, state):
        client = ElectroChemClient(base_url=url.replace("127.0.0.1", "localhost"))
        connection = client.connect()
        assert state["calls"] == [("/", None)]
        for method, path in (("GET", "/api/v1/llm/config"), ("POST", "/api/v1/history/delete"), ("GET", "http://example.invalid")):
            with pytest.raises(MCPClientError, match="not available"):
                connection.request(method, path)
        state["redirect"] = True
        with pytest.raises(MCPClientError) as error:
            client.connect()
        assert error.value.code == "redirect_refused"


def test_closing_desktop_still_allows_polling_but_blocks_new_posts(tmp_path):
    with fake_api() as (url, state):
        descriptor(tmp_path, url, state["token"])
        state["closing"] = True
        connection = ElectroChemClient(data_dir=tmp_path).connect()
        assert connection.request("GET", "/api/v1/tasks/task-1")["status"] == "success"
        with pytest.raises(MCPClientError) as error:
            connection.request("POST", "/api/v1/process/jobs", payload={})
        assert error.value.code == "desktop_closing"


def test_stopped_service_returns_actionable_error(tmp_path):
    with fake_api() as (url, state):
        descriptor(tmp_path, url, state["token"])
    with pytest.raises(MCPClientError) as error:
        ElectroChemClient(data_dir=tmp_path, timeout=0.5).connect()
    assert error.value.code == "service_unavailable"
