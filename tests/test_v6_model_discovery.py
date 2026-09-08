"""Model discovery uses fake credentials and isolated providers; never run inference."""

from __future__ import annotations

import gzip
import json
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests
from urllib3.exceptions import ProtocolError, ReadTimeoutError

import electrochem_v6.llm.model_discovery as discovery
from electrochem_v6.server import V6ServerManager
from electrochem_v6.store.runtime import reset_runtime
from test_v6_ui_playwright import _get_free_port, _launch_chromium, _sync_playwright_factory


@pytest.fixture
def provider_server():
    calls = []
    control = {"status": 200, "body": {"data": [{"id": "chat-small"}, {"id": "chat-large"}, {"id": "chat-small"}]}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            key = self.headers.get("Authorization", "")
            calls.append({"path": self.path, "key": key, "method": "GET", "accept_encoding": self.headers.get("Accept-Encoding")})
            status = control["status"]
            body = control["body"]
            if key == "Bearer fake-slow":
                body = {"data": [{"id": "old-response"}]}
                time.sleep(1.6)
            if key == "Bearer fake-new":
                body = {"data": [{"id": "new-response"}]}
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if 300 <= status < 400:
                self.send_header("Location", "/should-not-follow")
            if not control.get("omit_length"):
                self.send_header("Content-Length", str(len(raw)))
            if control.get("encoding"):
                self.send_header("Content-Encoding", control["encoding"])
            self.end_headers()
            try:
                if control.get("trickle"):
                    for value in raw:
                        self.wfile.write(bytes([value]))
                        self.wfile.flush()
                        time.sleep(0.05)
                else:
                    self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", calls, control
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.fixture
def isolated_config(monkeypatch, tmp_path, provider_server):
    base, _, _ = provider_server
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    config_file = tmp_path / "llm.json"
    config_file.write_text(json.dumps({"default_model": "openai", "models": {
        name: {"api_key": "", "model": "manual-model", "base_url": base, "timeout": 60}
        for name in ("openai", "deepseek", "qwen", "kimi")
    }}), encoding="utf-8")
    monkeypatch.setenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", str(config_file))
    for name in ("OPENAI", "DEEPSEEK", "QWEN", "KIMI", "DASHSCOPE", "MOONSHOT"):
        monkeypatch.delenv(name + "_API_KEY", raising=False)
    return config_file


def test_discovery_reads_only_and_never_persists_entered_key(isolated_config, provider_server):
    base, calls, _ = provider_server
    before = isolated_config.read_bytes()
    result = discovery.discover_provider_models({"provider": "openai", "base_url": base, "api_key": "fake-unsaved"})
    assert result == {"status": "success", "models": ["chat-large", "chat-small"], "truncated": False}
    assert calls == [{"path": "/v1/models", "key": "Bearer fake-unsaved", "method": "GET", "accept_encoding": "gzip, deflate"}]
    assert isolated_config.read_bytes() == before


@pytest.mark.parametrize(("status", "code"), [(401, "unauthorized"), (403, "unauthorized"), (404, "unsupported"),
    (405, "unsupported"), (429, "rate_limited"), (500, "unavailable"), (302, "redirect")])
def test_discovery_errors_do_not_echo_secrets(isolated_config, provider_server, status, code):
    _, calls, control = provider_server
    control.update(status=status, body={"error": "provider echoed fake-private-key"})
    result = discovery.discover_provider_models({"provider": "kimi", "api_key": "fake-private-key"})
    assert result["code"] == code
    assert "fake-private-key" not in json.dumps(result)
    assert len(calls) == 1


@pytest.mark.parametrize("base", ["http://example.com/v1", "https://user:pass@example.com/v1", "https://example.com/v1?key=fake",
    "https://example.com/v1#fragment", "file:///tmp", "https://example.com\\@localhost/v1", "https://example.com:invalid/v1"])
def test_discovery_rejects_unsafe_or_invalid_bases(isolated_config, provider_server, base):
    result = discovery.discover_provider_models({"provider": "openai", "api_key": "fake-key", "base_url": base})
    assert result["code"] == "invalid_url"
    assert provider_server[1] == []


def test_saved_key_stays_on_its_configured_origin(isolated_config, provider_server, monkeypatch):
    base, calls, _ = provider_server
    monkeypatch.setenv("OPENAI_API_KEY", "fake-saved")
    assert discovery.discover_provider_models({"provider": "openai", "base_url": "https://other.example/v1"})["code"] == "endpoint_changed"
    assert calls == []
    assert discovery.discover_provider_models({"provider": "openai", "base_url": base})["status"] == "success"
    assert calls[-1]["key"] == "Bearer fake-saved"
    discovery.discover_provider_models({"provider": "openai", "base_url": base, "api_key": "fake-entered"})
    assert calls[-1]["key"] == "Bearer fake-entered"


@pytest.mark.parametrize("body", [b"not json", {"models": []}, {"data": {}}, b"x" * (discovery.MAX_RESPONSE_BYTES + 1)],
                         ids=["non-json", "missing-data", "invalid-data", "oversized"])
def test_invalid_or_oversized_catalogue_is_actionable(isolated_config, provider_server, body):
    provider_server[2]["body"] = body
    assert discovery.discover_provider_models({"provider": "qwen", "api_key": "fake-key"})["code"] == "invalid_response"


def test_missing_key_empty_models_and_timeout(isolated_config, provider_server, monkeypatch):
    assert discovery.discover_provider_models({"provider": "openai"})["code"] == "missing_key"
    assert not provider_server[1]
    provider_server[2]["body"] = {"data": [None, {"id": "fake-key"}, {"id": 1}, {"id": "bad\nmodel"}]}
    assert discovery.discover_provider_models({"provider": "openai", "api_key": "fake-key"})["models"] == []
    def timeout(*args, **kwargs):
        raise requests.Timeout("fake-key upstream echoed secret")
    monkeypatch.setattr(requests.Session, "get", timeout)
    result = discovery.discover_provider_models({"provider": "openai", "api_key": "fake-key"})
    assert result["code"] == "timeout"
    assert "fake-key" not in json.dumps(result)


def test_slow_byte_stream_cannot_bypass_total_deadline(isolated_config, provider_server, monkeypatch):
    provider_server[2]["trickle"] = True
    monkeypatch.setattr(discovery, "MAX_DISCOVERY_SECONDS", 0.2)
    started = time.monotonic()
    result = discovery.discover_provider_models({"provider": "openai", "api_key": "fake-key"})
    assert result["code"] == "timeout"
    assert time.monotonic() - started < 1.5


def test_oversized_content_length_is_rejected_before_reading_slow_body(isolated_config, provider_server):
    provider_server[2].update(body=b"x" * (discovery.MAX_RESPONSE_BYTES + 1), trickle=True)
    started = time.monotonic()
    assert discovery.discover_provider_models({"provider": "openai", "api_key": "fake-key"})["code"] == "invalid_response"
    assert time.monotonic() - started < 1.5


def test_oversized_response_without_length_is_rejected_efficiently(isolated_config, provider_server):
    provider_server[2].update(body=b"x" * (discovery.MAX_RESPONSE_BYTES + 1), omit_length=True)
    started = time.monotonic()
    assert discovery.discover_provider_models({"provider": "openai", "api_key": "fake-key"})["code"] == "invalid_response"
    assert time.monotonic() - started < 5


def test_large_valid_catalogue_remains_fast_under_coverage(isolated_config, provider_server):
    provider_server[2].update(body={"data": [{"id": f"model-{index}-" + "a" * 200} for index in range(2000)]}, omit_length=True)
    started = time.monotonic()
    result = discovery.discover_provider_models({"provider": "openai", "api_key": "fake-key"})
    assert result["status"] == "success" and len(result["models"]) == 2000
    assert time.monotonic() - started < 5


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_compressed_catalogues_use_bounded_incremental_decoding(isolated_config, provider_server, encoding):
    raw = json.dumps({"data": [{"id": "compressed-chat"}]}).encode()
    compress = gzip.compress if encoding == "gzip" else zlib.compress
    provider_server[2].update(body=compress(raw), encoding=encoding)
    result = discovery.discover_provider_models({"provider": "openai", "api_key": "fake-key"})
    assert result["models"] == ["compressed-chat"]
    provider_server[2]["body"] = compress(b"x" * (discovery.MAX_RESPONSE_BYTES + 1))
    assert discovery.discover_provider_models({"provider": "openai", "api_key": "fake-key"})["code"] == "invalid_response"
    provider_server[2]["body"] = compress(raw)[:-4]
    assert discovery.discover_provider_models({"provider": "openai", "api_key": "fake-key"})["code"] == "invalid_response"


def test_slow_compressed_headers_cannot_hide_extra_network_reads(isolated_config, provider_server, monkeypatch):
    raw = json.dumps({"data": [{"id": "compressed-chat"}]}).encode()
    provider_server[2].update(body=gzip.compress(raw), encoding="gzip", trickle=True)
    monkeypatch.setattr(discovery, "MAX_DISCOVERY_SECONDS", 0.2)
    started = time.monotonic()
    assert discovery.discover_provider_models({"provider": "openai", "api_key": "fake-key"})["code"] == "timeout"
    assert time.monotonic() - started < 1.5


@pytest.mark.parametrize(("error", "code"), [(ReadTimeoutError(None, "/models", "fake-key"), "timeout"),
                                            (ProtocolError("fake-key"), "network")])
def test_raw_read_errors_are_mapped_without_leaking_key(isolated_config, provider_server, monkeypatch, error, code):
    original_get = requests.Session.get
    def get(*args, **kwargs):
        response = original_get(*args, **kwargs)
        def read(*_args, **_kwargs):
            raise error
        response.raw.read1 = read
        return response
    monkeypatch.setattr(requests.Session, "get", get)
    result = discovery.discover_provider_models({"provider": "openai", "api_key": "fake-key"})
    assert result["code"] == code and "fake-key" not in json.dumps(result)


@pytest.fixture
def discovery_page(isolated_config, provider_server):
    reset_runtime()
    manager = V6ServerManager(port=_get_free_port())
    ok, message = manager.start()
    assert ok, message
    try:
        with _sync_playwright_factory()() as playwright:
            browser = _launch_chromium(playwright)
            page = browser.new_page(viewport={"width": 1400, "height": 1050})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{manager.port}/ui", wait_until="networkidle")
            page.evaluate("openAISettingsPanel()")
            yield page
            assert not errors
            browser.close()
    finally:
        manager.stop()
        reset_runtime()


def test_key_paste_discovers_models_with_manual_selection_and_no_save(discovery_page, isolated_config, provider_server):
    page = discovery_page
    before = isolated_config.read_bytes()
    page.locator("#llm-api-key").fill("fake-paste")
    page.wait_for_function("() => document.querySelector('#llm-model-options').options.length === 3")
    page.locator("#llm-model-options").click()
    page.keyboard.press("Escape")
    page.wait_for_timeout(800)
    assert len(provider_server[1]) == 1
    assert page.locator("#llm-model-options option").count() == 3
    assert page.locator("#llm-model").input_value() == "manual-model"
    assert "不在列表" in page.locator("#llm-model-status").inner_text()
    page.select_option("#llm-model-options", "chat-small")
    assert page.locator("#llm-model").input_value() == "chat-small"
    page.locator("#llm-model").fill("custom-manual")
    assert page.locator("#llm-model-options").input_value() == ""
    assert isolated_config.read_bytes() == before
    assert all(call["method"] == "GET" and call["path"] == "/v1/models" for call in provider_server[1])


def test_model_discovery_debounces_and_discards_stale_results(discovery_page, provider_server):
    page = discovery_page
    page.locator("#llm-api-key").fill("fake-intermediate")
    page.wait_for_timeout(100)
    page.locator("#llm-api-key").fill("fake-slow")
    page.wait_for_function("() => document.querySelector('#llm-model-refresh').disabled")
    page.locator("#llm-api-key").fill("fake-new")
    page.wait_for_function("() => document.querySelector('#llm-model-options').textContent.includes('new-response')")
    page.wait_for_timeout(1100)
    assert "old-response" not in page.locator("#llm-model-options").text_content()
    assert [call["key"] for call in provider_server[1]] == ["Bearer fake-slow", "Bearer fake-new"]


def test_provider_and_base_changes_refresh_without_reusing_draft_key(discovery_page, provider_server):
    page = discovery_page
    page.locator("#llm-api-key").fill("fake-openai-draft")
    page.select_option("#llm-provider", "deepseek")
    assert page.locator("#llm-api-key").input_value() == ""
    page.wait_for_timeout(800)
    assert provider_server[1] == []
    page.locator("#llm-api-key").fill("fake-deepseek-draft")
    page.wait_for_function("() => document.querySelector('#llm-model-options').options.length === 3")
    page.locator("#llm-base-url").fill(provider_server[0] + "/gateway")
    page.wait_for_function("() => document.querySelector('#llm-model-options').options.length === 3")
    assert provider_server[1][-1]["path"] == "/v1/gateway/models"


def test_unsupported_then_manual_refresh_and_empty_results(discovery_page, provider_server):
    page = discovery_page
    provider_server[2]["status"] = 404
    page.locator("#llm-api-key").fill("fake-key")
    page.wait_for_function("() => document.querySelector('#llm-model-status').textContent.includes('未提供兼容')")
    assert page.locator("#llm-model-options").is_hidden()
    page.locator("#llm-model").fill("still-valid-manual")
    provider_server[2].update(status=200, body={"data": []})
    page.click("#llm-model-refresh")
    page.wait_for_function("() => document.querySelector('#llm-model-status').textContent.includes('空列表')")
    assert page.locator("#llm-model").input_value() == "still-valid-manual"


def test_saved_key_is_fetched_on_open_and_not_during_hidden_config_load(discovery_page, provider_server, monkeypatch):
    page = discovery_page
    page.evaluate("closeAISettingsPanel()")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-saved")
    page.evaluate("loadLLMConfig()")
    page.wait_for_timeout(800)
    assert not provider_server[1]
    page.evaluate("openAISettingsPanel()")
    page.wait_for_function("() => document.querySelector('#llm-model-options').options.length === 3")
    assert provider_server[1][0]["key"] == "Bearer fake-saved"
