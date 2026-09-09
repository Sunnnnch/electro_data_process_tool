"""Offline diagnostics must explain unsupported setups without touching user data."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from electrochem_v6.desktop import environment as diagnostics
from electrochem_v6.desktop import shell
from electrochem_v6.desktop.bridge import DesktopBridge


@pytest.fixture
def supported(monkeypatch, tmp_path):
    facts = {"system": "Windows", "major": 10, "minor": 0, "build": 19045,
             "product_type": 1, "process_arch": "x64", "native_arch": "x64"}
    runtime = {"webview2_version": "120.0.2210.0", "registry_inaccessible": False, "dotnet_release": 533325}
    monkeypatch.setattr(diagnostics, "_platform_facts", lambda: dict(facts))
    monkeypatch.setattr(diagnostics, "_registry_versions", lambda: dict(runtime))
    location = {"path": str(tmp_path / "data"), "mode": "environment"}
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", location["path"])
    return facts, runtime, location


def _checks(report):
    return {check["id"]: check for check in report["checks"]}


@pytest.mark.parametrize(("value", "expected"), [
    ("120.0.2210.55", (120, 0, 2210, 55)), (" 152.0 ", (152, 0)),
    ("119.9999.9", (119, 9999, 9)), ("0.0.0.0", (0, 0, 0, 0)),
    (None, None), (120, None), ("120", None), ("120.0 beta", None),
    ("9999999.0", None), ("120.0\nsecret", None), ("120.0.0.0.0", None),
])
def test_version_parser_keeps_only_numeric_versions(value, expected):
    assert diagnostics.parse_version(value) == expected


def test_supported_report_probes_and_removes_new_empty_directories(supported, tmp_path):
    *_, location = supported
    location["path"] = str(tmp_path / "new" / "nested")
    report = diagnostics.collect_environment_report(tmp_path, location)
    assert report["can_start"] and report["can_use_embedded_window"]
    assert {item["status"] for item in report["checks"]} == {"pass"}
    assert not (tmp_path / "new").exists()
    assert report["support_policy"]["minimum_versions_vm_verified"] is False


@pytest.mark.parametrize(("system", "major", "build"), [
    ("Windows", 10, 19044), ("Windows", 6, 9600), ("Linux", 0, 0), ("Darwin", 0, 0),
])
def test_unsupported_os_has_actionable_failure(supported, tmp_path, system, major, build):
    facts, _, location = supported
    facts.update(system=system, major=major, build=build)
    report = diagnostics.collect_environment_report(tmp_path, location)
    assert not report["can_start"] and not report["can_use_embedded_window"]
    assert _checks(report)["os"]["status"] == "fail"
    assert ("13" if system == "Darwin" else "19045") in _checks(report)["os"]["remedy"]


@pytest.mark.parametrize(("process", "native", "expected"), [
    ("x86", "x64", "fail"), ("arm64", "arm64", "fail"),
    ("x64", "arm64", "warn"), ("x64", "unknown", "warn"), ("x64", "x64", "pass"),
])
def test_architecture_distinguishes_process_and_native_emulation(supported, tmp_path, process, native, expected):
    facts, _, location = supported
    facts.update(process_arch=process, native_arch=native)
    report = diagnostics.collect_environment_report(tmp_path, location)
    check = _checks(report)["architecture"]
    assert check["status"] == expected
    assert report["can_start"] is (expected != "fail")
    if expected == "warn":
        assert "尚未验证" in check["remedy"]


@pytest.mark.parametrize(("version", "expected"), [
    (None, "warn"), ("119.9999.9.9", "warn"), ("120.0.0.0", "pass"), ("152.1.2.3", "pass"),
])
def test_runtime_minimum_controls_embedded_window_not_browser_fallback(supported, tmp_path, version, expected):
    _, runtime, location = supported
    runtime["webview2_version"] = version
    report = diagnostics.collect_environment_report(tmp_path, location)
    assert report["can_start"]
    assert _checks(report)["webview2"]["status"] == expected
    assert report["can_use_embedded_window"] is (expected == "pass")
    if expected == "warn":
        assert "浏览器工作区" in _checks(report)["webview2"]["remedy"]


def test_dotnet_missing_and_server_are_honest_warnings(supported, tmp_path):
    facts, runtime, location = supported
    facts["product_type"] = 3
    runtime["dotnet_release"] = 0
    report = diagnostics.collect_environment_report(tmp_path, location)
    assert report["can_start"] and not report["can_use_embedded_window"]
    assert _checks(report)["os"]["status"] == "warn"
    assert _checks(report)["dotnet"]["status"] == "warn"


def test_probe_preserves_user_files_and_existing_directories(supported, tmp_path):
    *_, location = supported
    data = Path(location["path"])
    (data / "logs").mkdir(parents=True)
    (data / "webview").mkdir()
    originals = {data / "projects.json": b"saved project", data / ".write_test": b"user-owned",
                 data / "logs" / "private.log": b"secret logged by another app"}
    for path, content in originals.items():
        path.write_bytes(content)
    before = {str(path.relative_to(data)): path.stat().st_mtime_ns for path in data.rglob("*") if path.is_file()}
    report = diagnostics.collect_environment_report(tmp_path, location)
    assert report["can_start"]
    assert {str(path.relative_to(data)): path.stat().st_mtime_ns for path in data.rglob("*") if path.is_file()} == before
    assert all(path.read_bytes() == content for path, content in originals.items())
    assert not list(data.rglob(".electrochem-envcheck-*"))
    assert "secret logged" not in diagnostics.format_environment_report(report)


def test_denied_probe_explains_permissions_without_echoing_exception(supported, tmp_path, monkeypatch):
    *_, location = supported
    def denied(*args, **kwargs):
        raise PermissionError(13, "API_KEY=must-not-appear")
    monkeypatch.setattr(diagnostics.tempfile, "mkstemp", denied)
    report = diagnostics.collect_environment_report(tmp_path, location)
    check = _checks(report)["data_directory"]
    assert check["status"] == "fail" and "权限" in check["remedy"]
    assert not report["can_start"]
    assert "EACCES" in check["detail"]
    assert "must-not-appear" not in json.dumps(report)
    assert not Path(location["path"]).exists()


def test_data_path_is_a_file_is_not_changed(supported, tmp_path):
    *_, location = supported
    data = Path(location["path"])
    data.write_bytes(b"real data")
    report = diagnostics.collect_environment_report(tmp_path, location)
    assert not report["can_start"]
    assert data.read_bytes() == b"real data"


def test_conflicting_mode_markers_are_a_reported_failure(supported, tmp_path, monkeypatch):
    monkeypatch.delenv("ELECTROCHEM_V6_DATA_DIR")
    (tmp_path / "portable.marker").touch()
    (tmp_path / "installed.marker").touch()
    report = diagnostics.collect_environment_report(tmp_path)
    assert not report["can_start"]
    assert "模式标记" in _checks(report)["data_directory"]["remedy"]
    assert report["data_dir"] == ""


def test_report_never_collects_secrets_and_startup_payloads(supported, tmp_path, monkeypatch):
    *_, location = supported
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-collect-env-secret")
    monkeypatch.setenv("ELECTROCHEM_V6_LLM_CONFIG_FILE", "do-not-collect-config-path")
    report = diagnostics.collect_environment_report(tmp_path, location)
    report = diagnostics.with_startup_failure(report, "service", RuntimeError("do-not-collect-exception-secret"))
    text = diagnostics.format_environment_report(report)
    assert "do-not-collect" not in text + json.dumps(report)
    assert "RuntimeError" in text
    assert not report["can_start"]


@pytest.mark.skipif(os.name != "nt", reason="Uses the Windows registry API")
def test_registry_scans_both_hives_and_views_and_ignores_bad_values(monkeypatch):
    import winreg
    visited = []
    class Key:
        def __init__(self, identity): self.identity = identity
        def __enter__(self): return self
        def __exit__(self, *args): return False
    def open_key(hive, path, reserved, access):
        visited.append((hive, path, access))
        return Key((hive, path, access))
    def read(key, name):
        hive, path, access = key.identity
        if name == "Release":
            return 533325, winreg.REG_DWORD
        if hive == winreg.HKEY_CURRENT_USER:
            return "secret token is not a version", winreg.REG_SZ
        return ("121.0.1.0" if access & winreg.KEY_WOW64_32KEY else "152.0.0.0"), winreg.REG_SZ
    monkeypatch.setattr(winreg, "OpenKey", open_key)
    monkeypatch.setattr(winreg, "QueryValueEx", read)
    result = diagnostics._registry_versions()
    assert result["webview2_version"] == "152.0.0.0"
    assert result["dotnet_release"] == 533325
    assert len(visited) == 6
    assert "secret" not in json.dumps(result)


def test_bridge_checks_origin_before_any_diagnostics(supported, tmp_path, monkeypatch):
    *_, location = supported
    calls = []
    original = diagnostics.collect_environment_report
    monkeypatch.setattr(diagnostics, "collect_environment_report", lambda *args: calls.append(args) or original(*args))
    window = SimpleNamespace(get_current_url=lambda: "https://example.org/")
    app = SimpleNamespace(window=window, ui_url="http://127.0.0.1:8123/ui", runtime_root=tmp_path, location=location)
    bridge = DesktopBridge(app)
    with pytest.raises(ValueError, match="local workbench"):
        bridge.get_environment_report()
    assert not calls
    window.get_current_url = lambda: app.ui_url
    result = bridge.get_environment_report()
    assert result["status"] == "success" and result["report"]["schema_version"] == 1
    assert result["report_text"] == diagnostics.format_environment_report(result["report"])


def test_startup_failure_stops_before_configuration_migration_or_server(supported, tmp_path, monkeypatch):
    facts, *_ = supported
    facts["build"] = 19044
    shown = []
    monkeypatch.setattr(shell, "configure_process_identity", lambda: None)
    monkeypatch.setattr(shell, "show_environment_report", shown.append)
    monkeypatch.setattr(shell, "configure_desktop_environment", lambda *args: pytest.fail("must not configure"))
    monkeypatch.setattr(shell, "_review_first_start_migration", lambda *args: pytest.fail("must not migrate"))
    monkeypatch.setattr(shell.DesktopShellApp, "run", lambda *args: pytest.fail("must not start"))
    assert shell.run_desktop(tmp_path) == 1
    assert len(shown) == 1 and not shown[0]["can_start"]


def test_existing_client_activates_before_diagnostics_or_migration(supported, tmp_path, monkeypatch):
    *_, location = supported
    data = Path(location["path"])
    data.mkdir()
    (data / "desktop-instance.json").write_text("{}")
    activated = []
    monkeypatch.setattr(shell, "configure_process_identity", lambda: None)
    monkeypatch.setattr(shell.SingleInstance, "activate_existing", lambda self, timeout: activated.append(timeout) or True)
    monkeypatch.setattr(shell, "collect_environment_report", lambda *args: pytest.fail("should activate first"))
    monkeypatch.setattr(shell, "_review_first_start_migration", lambda *args: pytest.fail("must not migrate"))
    assert shell.run_desktop(tmp_path) == 0
    assert activated == [0.2]


def test_successful_launch_has_no_diagnostic_dialog_and_closes_owned_lease(supported, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(shell, "configure_process_identity", lambda: None)
    monkeypatch.setattr(shell, "show_environment_report", lambda *args: pytest.fail("unexpected diagnostic dialog"))
    monkeypatch.setattr(shell, "_review_first_start_migration", lambda *args: calls.append("migration") or "")
    monkeypatch.setattr(shell.SingleInstance, "acquire", lambda *args: calls.append("acquire") or True)
    monkeypatch.setattr(shell.SingleInstance, "close", lambda *args: calls.append("close"))
    monkeypatch.setattr(shell.DesktopShellApp, "_start_with_splash", lambda *args: calls.append("service") or True)
    monkeypatch.setattr(shell.DesktopShellApp, "_run_webview", lambda *args: calls.append("webview") or True)
    assert shell.run_desktop(tmp_path) == 0
    assert calls == ["migration", "acquire", "service", "webview", "close"]


def test_outdated_runtime_uses_browser_and_releases_lease(supported, tmp_path, monkeypatch):
    _, runtime, _ = supported
    runtime["webview2_version"] = "119.0.0.0"
    calls = []
    monkeypatch.setattr(shell, "configure_process_identity", lambda: None)
    monkeypatch.setattr(shell, "show_environment_report", lambda *args: pytest.fail("unexpected diagnostic dialog"))
    monkeypatch.setattr(shell, "_review_first_start_migration", lambda *args: "")
    monkeypatch.setattr(shell.SingleInstance, "acquire", lambda *args: True)
    monkeypatch.setattr(shell.SingleInstance, "close", lambda *args: calls.append("close"))
    monkeypatch.setattr(shell.DesktopShellApp, "_start_with_splash", lambda *args: True)
    monkeypatch.setattr(shell.DesktopShellApp, "_run_browser_fallback", lambda *args: calls.append("browser"))
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(create_window=lambda *args, **kwargs: pytest.fail("must not start old runtime")))
    assert shell.run_desktop(tmp_path) == 0
    assert calls == ["browser", "close"]


def test_cli_file_export_never_overwrites_existing_report(supported, tmp_path, capsys):
    destination = tmp_path / "diagnostics.json"
    assert diagnostics.run_environment_check(tmp_path, json_output=True, output_path=destination) == 0
    saved = destination.read_bytes()
    assert json.loads(saved)["schema_version"] == 1
    assert diagnostics.run_environment_check(tmp_path, output_path=destination) == 2
    assert destination.read_bytes() == saved
    assert "FileExistsError" in capsys.readouterr().err


def test_windowed_cli_shows_report_if_no_export_path(supported, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(diagnostics, "show_environment_report", shown.append)
    assert diagnostics.run_environment_check(tmp_path, windowed=True) == 0
    assert shown[0]["can_start"]


def test_source_cli_stays_lightweight_and_reports_json_without_service(tmp_path):
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, ELECTROCHEM_V6_DATA_DIR=str(tmp_path / "isolated"), PYTHONUTF8="1")
    command = [sys.executable, str(root / "run_v6.py"), "environment-check", "--json"]
    child = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert child.returncode in {0, 1}, child.stderr
    report = json.loads(child.stdout)
    assert report["data_dir"] == str(tmp_path / "isolated")
    assert not (tmp_path / "isolated").exists()
    code = "import sys; from electrochem_v6.desktop.environment import collect_environment_report; assert not ({'numpy','scipy','matplotlib','electrochem_v6.server','webview'} & set(sys.modules))"
    child = subprocess.run([sys.executable, "-c", code], cwd=root, env=dict(environment, PYTHONPATH=str(root / "src")),
                           capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert child.returncode == 0, child.stderr


def test_frozen_entrypoint_exposes_environment_flag_without_importing_shell(supported, tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "packaging" / "electrochem_v6_launcher.py"
    spec = importlib.util.spec_from_file_location("diagnostic_launcher_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    destination = tmp_path / "frozen-report.json"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", ["ElectroChem.exe", "--environment-check", "--json", "--output", str(destination)])
    assert module.main() == 0
    assert json.loads(destination.read_text(encoding="utf-8"))["can_start"]


@pytest.mark.parametrize("clipboard_fails", [False, True])
def test_native_report_copy_reports_clipboard_failure_and_selects_text(supported, tmp_path, monkeypatch, clipboard_fails):
    import tkinter as tk
    from tkinter import ttk

    report = diagnostics.collect_environment_report(tmp_path, supported[2])
    buttons, configured, selected, copied = [], [], [], []
    class Widget:
        def __init__(self, *args, **kwargs):
            self.options = kwargs
            if "command" in kwargs and "Copy report" in kwargs.get("text", ""):
                buttons.append(kwargs["command"])
        def __getattr__(self, name):
            return lambda *args, **kwargs: None
        def configure(self, **kwargs): configured.append(kwargs)
        def tag_add(self, *args): selected.append(args)
        def clipboard_clear(self):
            if clipboard_fails:
                raise tk.TclError("busy")
        def clipboard_append(self, value): copied.append(value)
    for name in ("Tk", "Text"):
        monkeypatch.setattr(tk, name, Widget)
    for name in ("Frame", "Label", "Scrollbar", "Button"):
        monkeypatch.setattr(ttk, name, Widget)
    diagnostics.show_environment_report(report)
    assert len(buttons) == 1
    buttons[0]()
    if clipboard_fails:
        assert not copied and selected == [("sel", "1.0", "end-1c")]
        assert "Ctrl+C" in configured[-1]["text"]
    else:
        assert copied == [diagnostics.format_environment_report(report)]
        assert configured[-1]["text"] == "已复制 / Copied"


def test_splash_failure_retains_errno_but_does_not_leak_exception_text(supported, tmp_path, monkeypatch):
    import tkinter as tk
    from tkinter import ttk

    app = shell.DesktopShellApp(tmp_path, supported[2])
    app.environment_report = diagnostics.collect_environment_report(tmp_path, supported[2])
    class Widget:
        def __init__(self, *args, **kwargs): pass
        def __getattr__(self, name): return lambda *args, **kwargs: None
    monkeypatch.setattr(tk, "Tk", Widget)
    monkeypatch.setattr(ttk, "Label", Widget)
    monkeypatch.setattr(ttk, "Progressbar", Widget)
    def denied(): raise PermissionError(13, "private-api-token-in-error")
    monkeypatch.setattr(app, "_start_server", denied)
    shown = []
    monkeypatch.setattr(shell, "show_environment_report", shown.append)
    assert not app._start_with_splash()
    text = diagnostics.format_environment_report(shown[0])
    assert "EACCES" in text
    assert "private-api-token-in-error" not in text


def test_first_start_migration_can_take_its_real_locks_before_desktop_lease(supported, tmp_path, monkeypatch):
    import tkinter as tk
    from tkinter import messagebox

    *_, location = supported
    location["mode"] = "user"
    source = tmp_path / "old-client" / "user_data"
    source.mkdir(parents=True)
    original = b'{"sample":"original experiment"}'
    (source / "projects.json").write_bytes(original)
    target = Path(location["path"])
    class Window:
        def __getattr__(self, name): return lambda *args, **kwargs: None
    monkeypatch.setattr(tk, "Tk", Window)
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: True)
    monkeypatch.setattr(messagebox, "showwarning", lambda *args, **kwargs: pytest.fail("migration must be allowed"))
    monkeypatch.setattr(shell, "configure_process_identity", lambda: None)
    monkeypatch.setattr(shell, "resolve_desktop_data_dir", lambda *args: dict(location))
    monkeypatch.setattr(shell, "legacy_data_candidates", lambda *args, **kwargs: [{"path": str(source)}])
    monkeypatch.setattr(shell, "show_environment_report", lambda *args: pytest.fail("unexpected startup failure"))
    original_acquire = shell.SingleInstance.acquire
    def acquire(instance):
        assert (target / "projects.json").read_bytes() == original
        return original_acquire(instance)
    monkeypatch.setattr(shell.SingleInstance, "acquire", acquire)
    monkeypatch.setattr(shell.DesktopShellApp, "_start_with_splash", lambda *args: True)
    monkeypatch.setattr(shell.DesktopShellApp, "_run_webview", lambda *args: True)
    assert shell.run_desktop(tmp_path) == 0
    assert (source / "projects.json").read_bytes() == original
    assert (target / "projects.json").read_bytes() == original
    assert (target / "desktop-migration.json").is_file()
    assert not (target / "desktop-instance.json").exists()
