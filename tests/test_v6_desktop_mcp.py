"""Desktop MCP discovery lifecycle, origin confinement and copyable UI settings."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from electrochem_v6.desktop.bridge import DesktopBridge
from electrochem_v6.desktop.data import _ignored
from electrochem_v6.desktop.mcp_integration import DesktopServiceDiscovery, client_configuration
from electrochem_v6.desktop.shell import DesktopShellApp
from electrochem_v6.store.runtime import reset_runtime
from test_v6_desktop_ui import desktop_browser as _desktop_browser

desktop_browser = _desktop_browser


def test_discovery_atomic_replacement_does_not_remove_new_owner(tmp_path):
    original = DesktopServiceDiscovery(tmp_path, 12001, "original-private-token")
    original.publish()
    successor = DesktopServiceDiscovery(tmp_path, 12002, "successor-private-token")
    successor.publish()
    original.close()
    assert json.loads(successor.path.read_text())["url"] == "http://127.0.0.1:12002"
    assert list(tmp_path.glob(".desktop-service-*.tmp")) == []
    successor.close()
    assert not successor.path.exists()
    assert _ignored(Path("desktop-service.json"))
    assert _ignored(Path(".desktop-service-crashed.tmp"))


def test_client_config_uses_console_companion_and_explicit_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("electrochem_v6.desktop.mcp_integration._platform_system", lambda: "Windows")
    root, data = tmp_path / "程序 with spaces", tmp_path / "数据"
    root.mkdir()
    companion = root / "ElectroChem-MCP.exe"
    companion.write_bytes(b"test-launcher")
    result = client_configuration(root, data, frozen=True)
    config = result["client_config"]["mcpServers"]["electrochem"]
    assert config == {"command": str(companion.resolve()), "args": ["--data-dir", str(data.resolve())]}
    assert result["read_only"] and result["available"]
    assert "token" not in json.dumps(result)
    writable = client_configuration(root, data, frozen=True, allow_write=True)
    assert writable["client_config"]["mcpServers"]["electrochem"]["args"][-1] == "--allow-write"
    assert not writable["read_only"]
    with pytest.raises(ValueError):
        client_configuration(root, data, allow_write="false")


def test_source_config_avoids_pythonw_missing_stdio(tmp_path):
    (tmp_path / "run_v6.py").write_text("", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_bytes(b"launcher")
    result = client_configuration(tmp_path, tmp_path / "data", frozen=False,
                                  executable=str(tmp_path / "pythonw.exe"))
    config = result["client_config"]["mcpServers"]["electrochem"]
    assert config["command"] == str(python.resolve())
    assert config["args"][:2] == [str((tmp_path / "run_v6.py").resolve()), "mcp"]
    assert result["available"]


def test_mcp_configuration_bridge_checks_workbench_origin(tmp_path):
    app = SimpleNamespace(runtime_root=tmp_path, data_dir=tmp_path, ui_url="http://127.0.0.1:8123/ui?desktop=1",
                          manager=SimpleNamespace(is_running=True), closing_mode=None,
                          window=SimpleNamespace(get_current_url=lambda: "https://example.org/"))
    bridge = DesktopBridge(app)
    with pytest.raises(ValueError, match="local workbench"):
        bridge.get_mcp_configuration()
    app.window.get_current_url = lambda: app.ui_url
    result = bridge.get_mcp_configuration()
    assert result["read_only"] and result["server_running"] and not result["closing"]


def test_running_shell_publishes_authenticated_service_and_cleans_on_exit(monkeypatch, tmp_path):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path))
    reset_runtime()
    app = DesktopShellApp(tmp_path, {"path": str(tmp_path), "mode": "environment"})
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        app.state.set("port", listener.getsockname()[1])
    connection = requests.Session()
    connection.trust_env = False

    def start():
        assert app._start_server()[0]
        metadata = json.loads((tmp_path / "desktop-service.json").read_text())
        url = metadata["url"] + "/api/v1/mcp/status"
        assert connection.get(url, timeout=3).status_code == 403
        assert connection.get(url, headers={"X-Electrochem-Session": "incorrect"}, timeout=3).status_code == 403
        headers = {"X-Electrochem-Session": metadata["session_token"]}
        status = connection.get(url, headers=headers, timeout=3).json()
        assert status["name"] == "electrochem-v6-api" and not status["closing"]
        assert "session_token" not in status
        app.manager.close_desktop_admission()
        assert connection.get(url, headers=headers, timeout=3).json()["closing"]
        return True

    monkeypatch.setattr(app, "_start_with_splash", start)
    monkeypatch.setattr(app, "_run_webview", lambda: True)
    try:
        assert app.run() == 0
        assert not (tmp_path / "desktop-service.json").exists()
        assert not app.manager.is_running
    finally:
        if app.manager and app.manager.is_running:
            app.manager.stop()
        if app._mcp_discovery:
            app._mcp_discovery.close()
        app.instance.close()
        connection.close()
        reset_runtime()


def test_mcp_ui_copies_scope_specific_config_and_respects_small_viewport(desktop_browser):
    open_page, *_ = desktop_browser
    page = open_page(width=600)
    page.evaluate("""() => {
      window.pywebview.api.get_mcp_configuration = async (allow) => ({
        status: 'success', available: true, server_running: true, closing: false,
        client_config: {mcpServers: {electrochem: {command: 'D:\\客户端\\ElectroChem-MCP.exe', args: ['--data-dir', 'D:\\数据', ...(allow ? ['--allow-write'] : [])]}}}
      });
      Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: async text => {window.copiedMCPConfig = text;}}});
    }""")
    page.click("#desktop-menu-open")
    page.click("#desktop-mcp")
    page.wait_for_function("() => document.querySelector('#mcp-client-config').value.length > 0")
    config = json.loads(page.locator("#mcp-client-config").input_value())
    assert "--allow-write" not in config["mcpServers"]["electrochem"]["args"]
    page.check("#mcp-allow-write")
    page.wait_for_function("() => document.querySelector('#mcp-client-config').value.includes('--allow-write')")
    page.click("#mcp-copy-config")
    assert "--allow-write" in json.loads(page.evaluate("window.copiedMCPConfig"))["mcpServers"]["electrochem"]["args"]
    assert page.locator("#mcp-settings-dialog").evaluate("node => node.getBoundingClientRect().right <= innerWidth")
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
    page.keyboard.press("Escape")
    page.wait_for_selector("#mcp-settings-dialog", state="detached")


def test_mcp_ui_missing_launcher_cannot_claim_copy_success(desktop_browser):
    open_page, *_ = desktop_browser
    page = open_page()
    page.evaluate("""() => {window.pywebview.api.get_mcp_configuration = async () => ({
      status: 'success', available: false, server_running: true, client_config: {mcpServers: {}}
    });}""")
    page.click("#desktop-menu-open")
    page.click("#desktop-mcp")
    page.wait_for_function("() => document.querySelector('#mcp-settings-status').textContent.includes('ElectroChem-MCP.exe')")
    assert page.locator("#mcp-copy-config").is_disabled()
