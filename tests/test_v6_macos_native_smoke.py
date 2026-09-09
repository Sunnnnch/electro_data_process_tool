"""Check smoke isolation and real synthetic payload without pretending to run Cocoa."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_v6_project_templates import isolated_runtime as isolated_runtime

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("macos_native_smoke_contract", ROOT / "packaging/smoke_macos_desktop.py")
assert SPEC and SPEC.loader
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def test_native_smoke_refuses_non_macos_before_changing_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(SMOKE.sys, "platform", "win32")
    before = dict(SMOKE.os.environ)
    output = tmp_path / "never-created"
    with pytest.raises(RuntimeError, match="macOS"):
        SMOKE.run_smoke(output)
    assert not output.exists()
    assert dict(SMOKE.os.environ) == before


@pytest.mark.parametrize("existing", [False, True])
def test_native_smoke_refuses_existing_or_bundle_paths(tmp_path, existing):
    output = tmp_path / "previous" if existing else tmp_path / "ElectroChem.app" / "Contents" / "probe"
    if existing:
        output.mkdir()
        (output / "marker").write_text("preserve")
    with pytest.raises(ValueError):
        SMOKE.isolated_environment(output)
    if existing:
        assert (output / "marker").read_text() == "preserve"
    else:
        assert not output.exists()


def test_native_smoke_clears_inherited_per_file_and_webview_overrides(monkeypatch, tmp_path):
    environment = dict(SMOKE.os.environ)
    environment.update({"ELECTROCHEM_V6_HISTORY_FILE": "/original/private/history.json", "WEBVIEW2_USER_DATA_FOLDER": "/old/profile",
                        "ELECTROCHEM_V6_PORT": "8010", "ELECTROCHEM_OTHER_SECRET": "never-retain"})
    monkeypatch.setattr(SMOKE.os, "environ", environment)
    data = SMOKE.isolated_environment(tmp_path / "fresh")
    assert environment["ELECTROCHEM_V6_DATA_DIR"] == str(data)
    assert not any(name.startswith("WEBVIEW2") for name in environment)
    assert "ELECTROCHEM_OTHER_SECRET" not in environment and "ELECTROCHEM_V6_PORT" not in environment
    overrides = {name: value for name, value in environment.items() if name.startswith("ELECTROCHEM") and name.endswith("_FILE")}
    assert len(overrides) == 7
    assert all(Path(value).parent == data for value in overrides.values())
    assert environment["ELECTROCHEM_V6_KEEP_TEST_RUNTIME"] == "1"


def test_native_smoke_cv_payload_computes_real_history_and_outputs(isolated_runtime, tmp_path):
    from electrochem_v6.core.process_service import process_folder
    from electrochem_v6.core.system_service import register_allowed_dir
    from electrochem_v6.store.runtime import get_database

    data = tmp_path / "synthetic"
    data.mkdir()
    payload = SMOKE.synthetic_cv(data)
    input_path = Path(payload["input_files"][0]["path"])
    original_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
    register_allowed_dir(payload["folder_path"])
    result = process_folder(payload)
    assert result["status"] == "success", result
    records = get_database().get_all_history_records()
    assert len(records) == 1 and records[0]["type"] == "CV"
    outputs = result["result"]["processing"]["output_files"]
    paths = [Path(item["path"] if isinstance(item, dict) else item) for item in outputs]
    assert paths and any(path.suffix.lower() == ".png" for path in paths)
    assert all(path.is_file() and path.resolve().is_relative_to(data) for path in paths)
    persisted = SMOKE.verify_cv_result(result, data, input_path, original_hash)
    assert persisted["recipe_scan_rate_v_s"] == .05 and persisted["input_sha256_unchanged"]


@pytest.mark.parametrize("import_failure", [False, True])
def test_native_smoke_watchdog_covers_native_imports_and_always_closes(monkeypatch, tmp_path, import_failure):
    monkeypatch.setattr(SMOKE.sys, "platform", "darwin")
    monkeypatch.setattr(SMOKE.os, "environ", dict(SMOKE.os.environ))
    output = tmp_path / "watchdog-smoke"
    events, streams = [], []

    def arm(timeout, *, file, exit):
        assert timeout == 150 and exit is True
        assert Path(file.name) == output / "threads.log" and not file.closed
        streams.append(file)
        events.append("armed")

    def run(fresh_output, data, runtime_root):
        assert events == ["armed"]
        assert fresh_output == output and data == output / "data"
        assert json.loads((output / "report.json").read_text())["status"] == "initializing"
        events.append("native-imports-and-loop")
        if import_failure:
            raise RuntimeError("synthetic Cocoa import failed")
        return 0

    def cancel():
        assert not streams[0].closed
        events.append("cancelled")

    monkeypatch.setattr(SMOKE, "faulthandler", SimpleNamespace(dump_traceback_later=arm, cancel_dump_traceback_later=cancel))
    monkeypatch.setattr(SMOKE, "_run_isolated_smoke", run)
    assert SMOKE.run_smoke(output) == (1 if import_failure else 0)
    assert events == ["armed", "native-imports-and-loop", "cancelled"]
    assert streams[0].closed
    if import_failure:
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        assert report["status"] == "failed" and report["normal_exit"] is False
        assert report["error"] == "synthetic Cocoa import failed"
        assert "RuntimeError" in report["traceback"]


@pytest.mark.parametrize("native_error", [False, True])
def test_native_page_diagnostics_bypasses_eval_wrapper_and_preserves_nserror(monkeypatch, native_error):
    from types import ModuleType

    queued, scripts = [], []
    helper = ModuleType("PyObjCTools")
    helper.AppHelper = SimpleNamespace(callAfter=lambda callback: queued.append(callback) or callback())
    cocoa = ModuleType("webview.platforms.cocoa")
    expected = {"title": "ElectroChem", "desktop_ready": True, "eval_probe": {"error": "CSP rejected eval"}}
    error = SimpleNamespace(domain=lambda: "WKErrorDomain", code=lambda: 4, localizedDescription=lambda: "JavaScript exception")

    def evaluate(script, callback):
        scripts.append(script)
        callback(None if native_error else json.dumps(expected), error if native_error else None)

    cocoa.BrowserView = SimpleNamespace(instances={"owned-window": SimpleNamespace(webkit=SimpleNamespace(evaluateJavaScript_completionHandler_=evaluate))})
    monkeypatch.setitem(SMOKE.sys.modules, "PyObjCTools", helper)
    monkeypatch.setitem(SMOKE.sys.modules, "webview.platforms.cocoa", cocoa)
    window = SimpleNamespace(uid="owned-window")
    if native_error:
        with pytest.raises(RuntimeError, match="WKErrorDomain:4: JavaScript exception"):
            SMOKE.native_page_diagnostics(window)
    else:
        assert SMOKE.native_page_diagnostics(window) == expected
    assert len(queued) == 1 and scripts == ["JSON.stringify(" + SMOKE.PAGE_DIAGNOSTICS_SCRIPT + ")"]


def test_native_page_snapshot_can_read_ready_state_when_dynamic_eval_is_forbidden():
    node = shutil.which("node")
    if not node:
        pytest.skip("node executable is required for the page diagnostics contract")
    script = r"""
const vm = require('vm');
const desktop = {requested:()=>true, isEnabled:()=>true, isReady:()=>true};
const context = vm.createContext({
  location:{href:'http://127.0.0.1:49000/ui?desktop=1'}, navigator:{userAgent:'synthetic'},
  window:{ElectrochemDesktop:desktop, pywebview:{api:{get_state:()=>{}}, token:'never-collect'}},
  document:{title:'ElectroChem', doctype:{name:'html'}, compatMode:'CSS1Compat', readyState:'complete',
    documentElement:{dataset:{desktop:'ready'}}, body:{innerText:'x'.repeat(1200)},
    querySelector:()=>null, scripts:[{src:'/ui/static/app.js',type:'',async:false,defer:false}]},
  performance:{getEntriesByType:()=>[{name:'/health',initiatorType:'fetch',duration:12.4}]}
}, {codeGeneration:{strings:false,wasm:false}});
let removed = 0;
context.document.createElement = () => ({textContent:'', remove:()=>{removed++;}});
context.document.head = {appendChild:(script)=>vm.runInContext(script.textContent,context)};
vm.runInContext('let applicationStarted = true; let desktopBootstrapPending = false; let startupState = "ready";',context);
const result = vm.runInContext(DIAGNOSTIC, context);
if (removed !== 1 || Object.keys(context.window).some(key=>key.startsWith('__electrochemSmokeCsp_'))) throw Error('probe leaked');
process.stdout.write(JSON.stringify(result));
""".replace("DIAGNOSTIC", json.dumps(SMOKE.PAGE_DIAGNOSTICS_SCRIPT))
    completed = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10, check=False)
    assert completed.returncode == 0, completed.stderr
    page = json.loads(completed.stdout)
    assert page["application_started"] and page["desktop_ready"]
    assert page["desktop_bootstrap_pending"] is False and page["startup_state"] == "ready"
    assert "error" in page["eval_probe"] and page["bridge_methods"] == ["get_state"]
    assert len(page["body_text"]) == 1000 and "never-collect" not in completed.stdout
    assert page["scripts"][0]["src"] == "/ui/static/app.js"


@pytest.mark.parametrize("policy,valid", [
    ("default-src 'self'; script-src 'self' 'unsafe-inline'; connect-src 'self';", True),
    ("", False),
    ("script-src 'self' 'unsafe-inline' 'unsafe-eval';", False),
])
def test_native_smoke_requires_real_workbench_policy_without_unsafe_eval(monkeypatch, policy, valid):
    from contextlib import nullcontext

    url = "http://127.0.0.1:49123/ui?desktop=1"

    def respond(request, *, timeout):
        assert request.full_url == url and request.get_header("Origin") == "http://127.0.0.1:49123"
        assert timeout == 10
        return nullcontext(SimpleNamespace(geturl=lambda: url, headers={"Content-Security-Policy": policy}))

    monkeypatch.setattr(SMOKE, "urlopen", respond)
    if valid:
        assert SMOKE.verify_page_policy(url) == {"script_src": ["'self'", "'unsafe-inline'"], "unsafe_eval_allowed": False}
    else:
        with pytest.raises(AssertionError):
            SMOKE.verify_page_policy(url)
