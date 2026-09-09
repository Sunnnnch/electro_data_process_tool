"""macOS diagnostics test policy and real dependency failures without launching Cocoa."""
from __future__ import annotations

import ctypes
import errno
import json
import sys
from types import SimpleNamespace

import pytest

from electrochem_v6.desktop import environment as diagnostics


@pytest.fixture
def mac(monkeypatch, tmp_path):
    facts = {"system": "Darwin", "major": 13, "minor": 0, "macos_version": "13.0",
             "process_arch": "arm64", "native_arch": "arm64", "translated": False}
    runtime = {"available": True, "error": ""}
    monkeypatch.setattr(diagnostics, "_platform_facts", lambda: facts)
    monkeypatch.setattr(diagnostics, "_macos_runtime", lambda: runtime)
    monkeypatch.setattr(diagnostics, "_registry_versions", lambda: pytest.fail("macOS must not read Windows registry"))
    return facts, runtime, {"path": str(tmp_path / "data"), "mode": "environment"}


def test_mac_native_dependencies_and_report_have_no_windows_runtime_advice(mac, tmp_path):
    report = diagnostics.collect_environment_report(tmp_path, mac[2])
    assert report["can_start"] and report["can_use_embedded_window"]
    assert {row["id"] for row in report["checks"]} == {"os", "architecture", "wkwebview", "data_directory"}
    assert all(row["status"] == "pass" for row in report["checks"])
    text = diagnostics.format_environment_report(report)
    assert "macOS >= 13.0" in text and "WKWebView" in text
    assert "WebView2" not in text and ".NET" not in text
    assert report["support_policy"]["minimum_versions_vm_verified"] is False
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize(("major", "process", "native", "status", "can_start"), [
    (12, "arm64", "arm64", "pass", False), (13, "x64", "x64", "pass", True),
    (14, "x64", "arm64", "warn", True), (14, "x64", "unknown", "warn", True),
    (13, "x86", "x64", "fail", False), (0, "arm64", "arm64", "pass", False),
])
def test_mac_policy_version_and_emulated_architecture(mac, tmp_path, major, process, native, status, can_start):
    facts, _, location = mac
    facts.update(major=major, process_arch=process, native_arch=native)
    report = diagnostics.collect_environment_report(tmp_path, location)
    architecture = next(row for row in report["checks"] if row["id"] == "architecture")
    assert architecture["status"] == status
    assert report["can_start"] is can_start
    if status == "warn":
        assert "Rosetta" in architecture["remedy"]


def test_mac_bridge_load_failure_allows_browser_but_not_embedded_window(mac, tmp_path):
    mac[1].update(available=False, error="ImportError")
    report = diagnostics.collect_environment_report(tmp_path, mac[2])
    assert report["can_start"] and not report["can_use_embedded_window"]
    check = next(row for row in report["checks"] if row["id"] == "wkwebview")
    assert check["status"] == "warn" and "浏览器工作区" in check["remedy"]


def test_mac_diagnostics_never_probe_inside_bundle_even_with_supplied_location(mac, tmp_path, monkeypatch):
    mac[2]["path"] = str(tmp_path / "ElectroChem.app" / "Contents" / "data")
    monkeypatch.setattr(diagnostics, "_probe_directory", lambda *_: pytest.fail("Must reject before any write"))
    report = diagnostics.collect_environment_report(tmp_path, mac[2])
    assert not report["can_start"]
    assert ".app" in report["checks"][-1]["remedy"]
    assert not (tmp_path / "ElectroChem.app").exists()


@pytest.mark.parametrize(("machine", "translated", "native"), [
    ("arm64", False, "arm64"), ("x86_64", False, "x64"),
    ("x86_64", True, "arm64"), ("x86_64", None, "unknown"),
])
def test_mac_platform_facts_parse_product_version_and_rosetta(monkeypatch, machine, translated, native):
    monkeypatch.setattr(diagnostics.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(diagnostics.platform, "machine", lambda: machine)
    monkeypatch.setattr(diagnostics.platform, "mac_ver", lambda: ("14.5.1", ("", "", ""), machine))
    monkeypatch.setattr(diagnostics, "_macos_translated", lambda: translated)
    facts = diagnostics._platform_facts()
    assert (facts["major"], facts["minor"], facts["patch"]) == (14, 5, 1)
    assert facts["native_arch"] == native and facts["translated"] is translated


@pytest.mark.parametrize(("return_code", "value", "error", "expected"), [
    (0, 1, 0, True), (0, 0, 0, False), (-1, 0, errno.ENOENT, False),
    (-1, 0, errno.EACCES, None), (0, 5, 0, None),
])
def test_apple_rosetta_sysctl_handles_native_absent_and_failed_probes(monkeypatch, return_code, value, error, expected):
    class Function:
        def __call__(self, name, result, size, incoming, length):
            assert name == b"sysctl.proc_translated" and incoming is None and length == 0
            ctypes.cast(result, ctypes.POINTER(ctypes.c_int))[0] = value
            ctypes.set_errno(error)
            return return_code
    monkeypatch.setattr(diagnostics.ctypes, "CDLL", lambda *a, **kw: SimpleNamespace(sysctlbyname=Function()))
    assert diagnostics._macos_translated() is expected


@pytest.mark.parametrize("failure", [None, "WebKit", "Quartz", "PyObjCTools.AppHelper", "missing_class"])
def test_mac_runtime_probes_actual_framework_imports_without_echoing_secrets(monkeypatch, failure):
    calls = []
    def import_module(name):
        calls.append(name)
        if name == failure:
            raise ImportError("private-key-must-not-appear")
        return SimpleNamespace() if failure == "missing_class" else SimpleNamespace(WKWebView=object())
    monkeypatch.setattr(diagnostics.importlib, "import_module", import_module)
    result = diagnostics._macos_runtime()
    assert result["available"] is (failure is None)
    assert "private-key" not in json.dumps(result)
    assert "webview" not in calls and "NSApplication" not in calls
    if failure is None:
        assert {"objc", "AppKit", "Foundation", "Quartz", "Security", "WebKit", "PyObjCTools.AppHelper"} <= set(calls)


@pytest.mark.parametrize("copy_success", [True, False])
def test_mac_native_diagnostic_copy_reports_actual_clipboard_outcome(mac, tmp_path, monkeypatch, copy_success):
    from electrochem_v6.desktop import mac_native

    report = diagnostics.collect_environment_report(tmp_path, mac[2])
    dialogs, copied = [], []
    class Pasteboard:
        def clearContents(self): pass
        def setString_forType_(self, value, kind):
            copied.append((value, kind))
            return copy_success
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(
        NSPasteboard=SimpleNamespace(generalPasteboard=Pasteboard), NSPasteboardTypeString="plain-text"))
    def show(title, message, buttons, **kwargs):
        dialogs.append((title, message, buttons))
        return 1 if len(dialogs) == 1 else 0
    monkeypatch.setattr(mac_native, "show_message", show)
    monkeypatch.setattr(mac_native, "_on_main", lambda operation: operation())
    monkeypatch.setattr(diagnostics, "_show_tk_report", lambda *a, **kw: pytest.fail("Cocoa must not create Tk"))
    diagnostics.show_environment_report(report)
    assert copied == [(diagnostics.format_environment_report(report), "plain-text")]
    assert ("已复制" if copy_success else "暂不可用") in dialogs[1][1]


@pytest.mark.parametrize(("cocoa_loaded", "on_main", "fallback"), [(True, True, False), (False, False, False), (False, True, True)])
def test_mac_diagnostics_tk_fallback_only_before_cocoa_on_main(mac, tmp_path, monkeypatch, capsys, cocoa_loaded, on_main, fallback):
    report = diagnostics.collect_environment_report(tmp_path, mac[2])
    if cocoa_loaded:
        monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace())
    else:
        monkeypatch.delitem(sys.modules, "AppKit", raising=False)
    def unavailable(*_args): raise ImportError("private-import-detail")
    monkeypatch.setattr(diagnostics, "_show_macos_report", unavailable)
    marker = object()
    monkeypatch.setattr(diagnostics.threading, "main_thread", lambda: marker)
    monkeypatch.setattr(diagnostics.threading, "current_thread", lambda: marker if on_main else object())
    calls = []
    monkeypatch.setattr(diagnostics, "_show_tk_report", lambda *a, **kw: calls.append(True))
    diagnostics.show_environment_report(report)
    assert bool(calls) is fallback
    assert "private-import-detail" not in capsys.readouterr().err
