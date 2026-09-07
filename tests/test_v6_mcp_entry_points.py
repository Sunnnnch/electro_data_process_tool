"""Verify quiet entry routing and packaging without starting a desktop."""

from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
import types
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest

from electrochem_v6.config import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("entry", [
    ["run_v6.py", "mcp"],
    ["packaging/electrochem_mcp_launcher.py"],
    ["-m", "electrochem_v6.mcp_cli"],
])
def test_mcp_entry_help_is_quiet_without_starting_application(entry, tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "ELECTROCHEM_V6_DATA_DIR": str(tmp_path / "unused")}
    result = subprocess.run([sys.executable, *entry, "--help"], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("usage:")
    assert "--data-dir" in result.stdout and "--allow-write" in result.stdout and "--url" in result.stdout
    assert "already open" in result.stdout and "read-only" in result.stdout
    assert result.stderr == ""
    assert not (tmp_path / "unused").exists()


def test_version_no_longer_imports_processing_or_prints_font_setup(tmp_path):
    result = subprocess.run([sys.executable, "run_v6.py", "version"], cwd=ROOT,
                            env={**os.environ, "ELECTROCHEM_V6_DATA_DIR": str(tmp_path / "unused")},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0
    assert result.stdout.strip() == APP_VERSION
    assert result.stderr == ""
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize("entry", ["runner", "companion", "module"])
def test_mcp_dispatch_never_imports_gui_engine_or_store(entry, tmp_path):
    script = r'''
import builtins,json,runpy,sys,types
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'src'))
real_import=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.startswith(('electrochem_v6.core','electrochem_v6.server','electrochem_v6.store',
                        'electrochem_v6.desktop.shell','webview','tkinter','matplotlib','numpy')):
        raise AssertionError('MCP imported '+name)
    return real_import(name,*args,**kwargs)
builtins.__import__=guarded
stub=types.ModuleType('electrochem_v6.mcp.server')
def run_server(**kwargs):
    print(json.dumps(kwargs,default=str,ensure_ascii=False))
stub.run_server=run_server
sys.modules['electrochem_v6.mcp.server']=stub
entry,data=sys.argv[1:]
options=['--data-dir',data,'--url','http://127.0.0.1:9876','--allow-write']
if entry=='runner':
    sys.argv=['run_v6.py','mcp',*options]
    runpy.run_path('run_v6.py',run_name='__main__')
elif entry=='companion':
    sys.argv=['packaging/electrochem_mcp_launcher.py',*options]
    runpy.run_path(sys.argv[0],run_name='__main__')
else:
    sys.argv=['electrochem-mcp',*options]
    runpy.run_module('electrochem_v6.mcp_cli',run_name='__main__')
'''
    selected = tmp_path / "含空格 数据"
    result = subprocess.run([sys.executable, "-c", script, entry, str(selected)], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"base_url": "http://127.0.0.1:9876", "data_dir": str(selected), "allow_write": True}
    assert result.stderr == ""
    assert not selected.exists()


@pytest.mark.parametrize("mode", ["portable", "installed", "environment", "explicit"])
def test_cli_storage_selection_matches_desktop_and_defaults_to_read_only(monkeypatch, tmp_path, mode):
    from electrochem_v6 import mcp_cli
    from electrochem_v6.desktop.data import DATA_ENV

    root = tmp_path / "application"
    root.mkdir()
    chosen = tmp_path / "selected"
    monkeypatch.delenv(DATA_ENV, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    options = []
    if mode == "portable":
        (root / "portable.marker").touch()
        expected = root / "user_data"
    elif mode == "installed":
        (root / "installed.marker").touch()
        expected = tmp_path / "home/.electrochem/v6"
    elif mode == "environment":
        monkeypatch.setenv(DATA_ENV, str(chosen))
        expected = chosen
    else:
        monkeypatch.setenv(DATA_ENV, str(tmp_path / "other"))
        options = ["--data-dir", str(chosen)]
        expected = chosen
    calls = []
    server = types.ModuleType("electrochem_v6.mcp.server")
    server.run_server = lambda **kwargs: calls.append(kwargs)
    monkeypatch.setitem(sys.modules, server.__name__, server)
    streams = {name: io.StringIO() for name in ("stdin", "stdout", "stderr")}
    for name, stream in streams.items():
        monkeypatch.setattr(sys, name, stream)
    monkeypatch.setattr(mcp_cli, "_installer_guard", nullcontext)
    assert mcp_cli.main(options, runtime_root=root) == 0
    assert calls == [{"base_url": None, "data_dir": expected, "allow_write": False}]
    assert streams["stdout"].getvalue() == "" and streams["stderr"].getvalue() == ""
    assert not expected.exists()


def test_spec_separates_console_protocol_entry_from_windowed_gui():
    spec = ast.parse((ROOT / "packaging/electrochem_v6.spec").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(spec) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    executables = {
        next(ast.literal_eval(kw.value) for kw in call.keywords if kw.arg == "name"): call
        for call in calls if call.func.id == "EXE"
    }
    assert set(executables) == {"ElectroChem", "ElectroChem-MCP"}
    assert next(ast.literal_eval(kw.value) for kw in executables["ElectroChem"].keywords if kw.arg == "console") is False
    assert next(ast.literal_eval(kw.value) for kw in executables["ElectroChem-MCP"].keywords if kw.arg == "console") is True
    collection = next(call for call in calls if call.func.id == "COLLECT")
    assert {arg.id for arg in collection.args if isinstance(arg, ast.Name)} >= {"exe", "mcp_exe"}
    assert "electrochem_mcp_launcher.py" in ast.unparse(spec)


def test_distribution_signing_covers_both_executables_before_zip():
    for path in (".github/workflows/release.yml",):
        workflow = (ROOT / path).read_text(encoding="utf-8-sig")
        assert workflow.index('"dist/ElectroChem/ElectroChem-MCP.exe" -RequireSigning') < workflow.index("Compress-Archive")
    build = (ROOT / "packaging/build_installer.ps1").read_text(encoding="utf-8-sig")
    assert '@("ElectroChem.exe", "ElectroChem-MCP.exe")' in build
    assert "-RequireSigning:$RequireSigning" in build


@pytest.mark.skipif(os.name != "nt", reason="Windows installer lease")
def test_companion_installer_guard_releases_handle_even_when_transport_fails(monkeypatch):
    from electrochem_v6 import mcp_cli

    kernel = types.SimpleNamespace(CreateMutexW=Mock(return_value=42), CloseHandle=Mock(return_value=True))
    monkeypatch.setattr(mcp_cli.ctypes, "WinDLL", Mock(return_value=kernel))
    with pytest.raises(RuntimeError, match="transport stopped"):
        with mcp_cli._installer_guard():
            kernel.CreateMutexW.assert_called_once_with(None, False, "Local\\ElectroChemV6.Desktop")
            kernel.CloseHandle.assert_not_called()
            raise RuntimeError("transport stopped")
    kernel.CloseHandle.assert_called_once_with(42)
