"""State, native bridge boundaries and real cross-process desktop activation."""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from electrochem_v6.desktop.bridge import DesktopBridge, export_filename
from electrochem_v6.desktop.instance import SingleInstance
from electrochem_v6.desktop.native import external_web_url, is_workbench_url
from electrochem_v6.desktop.state import DesktopState, fit_window


def test_preferences_survive_restart_and_exclude_experiment_and_credentials(tmp_path):
    state = DesktopState(tmp_path)
    state.save_preferences({"local_storage": {"electrochem_v6_lang": "en", "llm_api_key": "never-store"},
        "workspace": {"tab": "project", "project_id": "p-1", "conversation_id": "c-1", "assistant_open": True,
                      "folder_path": "D:/measurements", "area": 99}, "api_key": "never-store"})
    restored = DesktopState(tmp_path).preferences()
    assert restored == {"local_storage": {"electrochem_v6_lang": "en"},
                        "workspace": {"tab": "project", "project_id": "p-1", "conversation_id": "c-1", "assistant_open": True}}
    assert "never-store" not in state.path.read_text()
    assert "measurements" not in state.path.read_text()


def test_window_returns_onscreen_after_monitor_removal_and_keeps_negative_monitor():
    former = {"x": 3000, "y": 200, "width": 1800, "height": 1100, "maximized": True}
    fitted = fit_window(former, [(0, 0, 1366, 728)])
    assert fitted == {"x": 0, "y": 0, "width": 1366, "height": 728, "maximized": True}
    second = fit_window({"x": -1800, "y": 20, "width": 1000, "height": 700}, [(-1920, 0, 0, 1080), (0, 0, 1920, 1080)])
    assert second["x"] == -1800


def test_real_second_process_activates_owner_and_does_not_start_backend(tmp_path):
    activated = threading.Event()
    owner = SingleInstance(tmp_path, activated.set)
    assert owner.acquire()
    child_code = """
import sys
from pathlib import Path
from electrochem_v6.desktop.instance import SingleInstance
instance = SingleInstance(Path(sys.argv[1]), lambda: None)
assert not instance.acquire()
assert instance.activate_existing(timeout=3)
print('activated')
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    try:
        child = subprocess.run([sys.executable, "-c", child_code, str(tmp_path)], env=environment,
                               capture_output=True, encoding="utf-8", timeout=10)
        assert child.returncode == 0, child.stderr
        assert child.stdout.strip() == "activated"
        assert activated.wait(1)
        metadata = json.loads(owner.metadata_path.read_text())
        activated.clear()
        with socket.create_connection(("127.0.0.1", metadata["port"]), timeout=1) as connection:
            connection.sendall(b'{"action":"activate","token":"wrong"}')
            assert connection.recv(256) == b""
        assert not activated.wait(0.1)
    finally:
        owner.close()
    replacement = SingleInstance(tmp_path, lambda: None)
    try:
        assert replacement.acquire(), "OS lock must be released after normal exit"
    finally:
        replacement.close()


@pytest.mark.parametrize("url", ["file:///C:/x.exe", "javascript:alert(1)", "https://user:password@example.org/", "https://example.org/\nrun"])
def test_native_links_reject_nonweb_schemes_and_embedded_credentials(url):
    with pytest.raises(ValueError):
        external_web_url(url)


def test_bridge_is_confined_to_workbench_and_save_uses_native_selection(tmp_path):
    target = tmp_path / "chosen.csv"
    window = SimpleNamespace(get_current_url=lambda: "http://127.0.0.1:8123/ui?desktop=1",
                             create_file_dialog=lambda *args, **kwargs: (str(target),))
    app = SimpleNamespace(window=window, ui_url="http://127.0.0.1:8123/ui?desktop=1", state=DesktopState(tmp_path))
    bridge = DesktopBridge(app)
    payload = base64.b64encode(b"potential,current\n0,1\n").decode()
    assert bridge.save_export(payload, "report.csv")["status"] == "success"
    assert target.read_bytes() == b"potential,current\n0,1\n"
    window.get_current_url = lambda: "https://example.org/"
    with pytest.raises(ValueError, match="local workbench"):
        bridge.save_export(payload, "report.csv")
    assert not is_workbench_url("http://127.0.0.1:8123/ui/static/help_manual.en.md", app.ui_url)
    assert not is_workbench_url("http://127.0.0.1:8124/ui", app.ui_url)


def test_export_cancel_does_not_write_or_fetch_unrelated_endpoints(tmp_path):
    window = SimpleNamespace(get_current_url=lambda: "http://127.0.0.1:8123/ui", create_file_dialog=lambda *a, **k: None)
    bridge = DesktopBridge(SimpleNamespace(window=window, ui_url="http://127.0.0.1:8123/ui"))
    assert bridge.save_export(base64.b64encode(b"data").decode(), "data.csv") == {"status": "cancelled"}
    for url in ("https://example.org/file.csv", "/api/v1/llm/config", "/ui/static/app.js", "//example.org/data.csv"):
        with pytest.raises(ValueError):
            bridge.save_download(url, "data.csv")
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(ValueError):
        export_filename("payload.exe")
    assert export_filename("../../report.csv") == "report.csv"


def test_native_close_preserves_latest_snapshot_and_waits_for_idle(monkeypatch, tmp_path):
    from electrochem_v6.desktop.shell import DesktopShellApp
    app = DesktopShellApp(tmp_path, {"path": str(tmp_path), "mode": "environment"})
    destroyed = threading.Event()
    snapshot = {"local_storage": {"electrochem_v6_lang": "en"}, "workspace": {"tab": "project"}}
    app.window = SimpleNamespace(evaluate_js=lambda script: json.dumps(snapshot) if "getPreferencesSnapshot" in script else None,
                                 destroy=destroyed.set)
    app.request_exit()
    assert destroyed.wait(2)
    assert DesktopState(tmp_path).preferences() == snapshot
    assert app._allow_close


def test_exit_waits_for_admitted_http_writes_and_rejects_new_ones(monkeypatch, tmp_path):
    import requests

    from electrochem_v6.server import http_server

    entered, release = threading.Event(), threading.Event()
    original_dispatch = http_server.dispatch_post

    def dispatch(handler, manager):
        if handler.path == "/test-desktop-write":
            entered.set()
            assert release.wait(5)
            (tmp_path / "finished.txt").write_text("committed")
            handler._send_json(200, {"status": "success"})
            return True
        return original_dispatch(handler, manager)

    monkeypatch.setattr(http_server, "dispatch_post", dispatch)
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        port = port_probe.getsockname()[1]
    manager = http_server.V6ServerManager(port=port)
    assert manager.start()[0]
    response = []
    worker = threading.Thread(target=lambda: response.append(requests.post(f"http://127.0.0.1:{port}/test-desktop-write", json={}, timeout=8)))
    try:
        worker.start()
        assert entered.wait(3)
        manager.close_desktop_admission()
        assert manager.desktop_active_writes() == 1
        denied = requests.post(f"http://127.0.0.1:{port}/test-desktop-write", json={}, timeout=2)
        assert denied.status_code == 503
        assert requests.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200
        assert not (tmp_path / "finished.txt").exists()
        release.set()
        worker.join(5)
        assert response[0].status_code == 200
        assert (tmp_path / "finished.txt").read_text() == "committed"
        assert manager.desktop_active_writes() == 0
    finally:
        release.set()
        worker.join(5)
        manager.stop()
