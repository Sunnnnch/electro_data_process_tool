"""Native selections must work without creating Tk on macOS HTTP workers."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from electrochem_v6.core import system_service
from electrochem_v6.desktop.bridge import DesktopBridge


@pytest.fixture
def native_picker(tmp_path, monkeypatch):
    selected = tmp_path / "实验 data.csv"
    selected.write_text("0,1\n", encoding="utf-8")
    calls, registered = [], []
    window = SimpleNamespace(get_current_url=lambda: "http://127.0.0.1:8123/ui?desktop=1")
    def dialog(kind, **options):
        calls.append((kind, options))
        return (str(tmp_path if kind == 20 else selected),)
    window.create_file_dialog = dialog
    app = SimpleNamespace(window=window, ui_url="http://127.0.0.1:8123/ui?desktop=1",
                          data_dir=tmp_path, closing_mode=None)
    monkeypatch.setattr(system_service, "register_allowed_dir", registered.append)
    return DesktopBridge(app), app, calls, registered, selected


def test_folder_and_file_dialogs_use_webview_and_preserve_response_contract(native_picker):
    bridge, app, calls, registered, selected = native_picker
    assert bridge.select_folder()["folder_path"] == str(app.data_dir)
    assert bridge.select_file(str(selected), ["csv"])["file_path"] == str(selected)
    assert bridge.select_files("", [".csv", ".txt"]) == {
        "status": "success", "file_paths": [str(selected)], "count": 1,
    }
    assert [call[0] for call in calls] == [20, 10, 10]
    assert [call[1]["allow_multiple"] for call in calls] == [False, False, True]
    assert calls[1][1]["directory"] == str(app.data_dir)
    assert calls[1][1]["file_types"] == ("Data (*.csv)",)
    assert registered == [str(app.data_dir)] * 3


@pytest.mark.parametrize("method", ["select_folder", "select_file", "select_files"])
def test_native_picker_rejects_external_page_before_showing_dialog(native_picker, method):
    bridge, app, calls, registered, _ = native_picker
    app.window.get_current_url = lambda: "https://example.com/"
    with pytest.raises(ValueError, match="local workbench"):
        getattr(bridge, method)()
    assert not calls and not registered


def test_native_picker_cancellation_and_exit_do_not_register_paths(native_picker):
    bridge, app, calls, registered, _ = native_picker
    app.window.create_file_dialog = lambda *args, **kwargs: None
    assert bridge.select_file()["status"] == "error"
    app.closing_mode = "wait"
    assert bridge.select_folder()["status"] == "error"
    assert not registered and not calls


def test_native_picker_rejects_injected_filters_and_unexpected_selection(native_picker):
    bridge, app, calls, registered, selected = native_picker
    with pytest.raises(ValueError, match="extension"):
        bridge.select_file("", ["csv);*"])
    assert not calls
    with pytest.raises(ValueError, match="file type"):
        bridge.select_file("", [".txt"])
    app.window.create_file_dialog = lambda *args, **kwargs: (str(selected), str(selected))
    with pytest.raises(ValueError, match="Unexpected"):
        bridge.select_file()
    assert not registered


def test_open_data_folder_uses_the_existing_platform_opener(native_picker, monkeypatch):
    bridge, app, _, registered, _ = native_picker
    opened = []
    def open_target(path):
        opened.append(path)
        return {"status": "success", "opened": path}
    monkeypatch.setattr(system_service, "open_path_target", open_target)
    assert bridge.open_data_dir()["opened"] == str(app.data_dir)
    assert opened == registered == [str(app.data_dir)]


@pytest.mark.parametrize("method", ["select_folder_dialog", "select_file_dialog", "select_files_dialog"])
def test_macos_browser_picker_does_not_initialize_tk_on_an_http_thread(monkeypatch, method):
    monkeypatch.setattr(sys, "platform", "darwin")
    outputs = []
    worker = threading.Thread(target=lambda: outputs.append(getattr(system_service, method)()))
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert outputs[0]["status"] == "error"
    assert "desktop app" in outputs[0]["message"]


def test_plotting_can_choose_an_installed_macos_cjk_font(monkeypatch):
    from electrochem_v6.core import processing_core_v6 as plotting
    monkeypatch.setattr(plotting, "_AVAILABLE_FONT_NAMES", {"DejaVu Sans", "PingFang SC"})
    monkeypatch.setattr(plotting, "_font_supports_text", lambda name, text: name == "PingFang SC")
    assert plotting._resolve_plot_font("DejaVu Sans", fallback="missing", text="样品") == "PingFang SC"


def test_frozen_mac_config_defaults_outside_bundle_and_rejects_per_file_bundle_overrides(monkeypatch, tmp_path):
    from electrochem_v6 import config
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("ELECTROCHEM_V6_DATA_DIR", raising=False)
    outside = tmp_path / "Library/Application Support/ElectroChem"
    assert config.user_config_dir() == outside
    assert config.project_default_dir() == outside
    monkeypatch.setenv("ELECTROCHEM_V6_LOG_FILE", str(tmp_path / "ElectroChem.app/Contents/log.txt"))
    with pytest.raises(ValueError, match="outside the .app"):
        config.get_log_file()
    monkeypatch.setenv("ELECTROCHEM_V6_LOG_FILE", str(tmp_path / "custom/log.txt"))
    assert config.get_log_file() == tmp_path / "custom/log.txt"


def test_system_api_uses_native_selection_and_never_retries_denied_native_actions():
    from test_v6_ui_playwright import _launch_chromium, _sync_playwright_factory
    source = Path(__file__).resolve().parents[1] / "src/electrochem_v6/ui/static/system_api.js"
    with _sync_playwright_factory()() as playwright:
        browser = _launch_chromium(playwright)
        try:
            page = browser.new_page()
            page.set_content("<html><body></body></html>")
            page.evaluate("""() => {
              window.httpCalls = []; window.nativeCalls = [];
              window.ElectrochemApi = {fetch: (...args) => {httpCalls.push(args); return Promise.resolve(new Response('{}'));}};
              window.pywebview = {api: {
                select_folder: (value) => {nativeCalls.push(['folder', value]); return Promise.resolve({status:'success', folder_path:'/tmp/实验'});},
                select_file: () => Promise.reject(new Error('origin rejected')),
                select_files: () => Promise.resolve({status:'error', message:'cancelled'})
              }};
            }""")
            page.add_script_tag(path=str(source))
            assert page.evaluate("async () => (await (await ElectrochemSystemApi.selectFolder('/tmp')).json()).folder_path") == "/tmp/实验"
            assert page.evaluate("async () => (await ElectrochemSystemApi.selectFiles()).status") == 400
            assert page.evaluate("async () => {try {await ElectrochemSystemApi.selectFile();} catch(e) {return e.message;}}") == "origin rejected"
            assert page.evaluate("httpCalls.length") == 0
            page.evaluate("delete window.pywebview")
            page.evaluate("async () => await ElectrochemSystemApi.selectFolder('/tmp')")
            assert page.evaluate("httpCalls[0][0]") == "/api/v1/system/select-folder"
        finally:
            browser.close()
