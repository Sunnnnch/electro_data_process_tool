"""Opt-in real Cocoa/WKWebView smoke in a newly created synthetic workspace.

Run on a logged-in macOS desktop, never against an installed user's data. The
frozen launcher may call run_smoke explicitly; ordinary launch has no test hooks.
"""

from __future__ import annotations

import argparse
import faulthandler
import hashlib
import json
import math
import os
import platform
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

PAGE_DIAGNOSTICS_SCRIPT = r"""(function () {
    function probe(read) {
        try { return read(); }
        catch (error) { return {name: String(error && error.name || 'Error'), error: String(error && error.message || error)}; }
    }
    function text(selector) {
        var node = document.querySelector(selector);
        return node ? String(node.innerText || node.textContent || '').slice(0, 1000) : null;
    }
    function pageCspProbe() {
        // Native/CDP evaluation may also bypass CSP in an injected script.
        // This probe is diagnostic only; HTTP policy is checked separately.
        var key = '__electrochemSmokeCsp_' + Math.random().toString(36).slice(2);
        var script = document.createElement('script');
        script.textContent = 'window[' + JSON.stringify(key) + '] = (function () {' +
            'function attempt(read) { try { return {value:read()}; } catch (error) {' +
            'return {name:String(error.name), error:String(error.message)}; } }' +
            'return {eval:attempt(function () { return (0,eval)("1 + 1"); }),' +
            'construct:attempt(function () { return new Function("return 2")(); })}; })();';
        try {
            document.head.appendChild(script);
            return window[key] || {error:'The temporary page CSP probe did not execute'};
        } finally {
            script.remove();
            delete window[key];
        }
    }
    var csp = pageCspProbe();
    var desktop = window.ElectrochemDesktop;
    var modules = ['ElectrochemApi', 'ElectrochemDesktop', 'ElectrochemTheme', 'ElectrochemPalette',
        'ElectrochemAppearance', 'ElectrochemProjectPage', 'ElectrochemProcessResultPage'];
    return {
        url: String(location.href), title: document.title,
        doctype: document.doctype && document.doctype.name, compat_mode: document.compatMode,
        ready_state: document.readyState, user_agent: navigator.userAgent,
        application_started: probe(function () { return typeof applicationStarted === 'undefined' ? null : applicationStarted; }),
        startup_state: probe(function () { return typeof startupState === 'undefined' ? null : startupState; }),
        desktop_bootstrap_pending: probe(function () { return typeof desktopBootstrapPending === 'undefined' ? null : desktopBootstrapPending; }),
        desktop_attribute: document.documentElement.dataset.desktop || null,
        desktop_requested: probe(function () { return desktop ? desktop.requested() : null; }),
        desktop_enabled: probe(function () { return desktop ? desktop.isEnabled() : null; }),
        desktop_ready: probe(function () { return desktop ? desktop.isReady() : null; }),
        bridge_present: Boolean(window.pywebview),
        eval_probe: csp.eval || csp, function_probe: csp.construct || csp,
        csp_probe_context: 'native-injected script; diagnostic only, may inherit native permissions',
        bridge_methods: window.pywebview && window.pywebview.api ? Object.keys(window.pywebview.api).sort() : [],
        startup_error: text('#app-startup-error'), desktop_overlay: text('#desktop-startup'),
        body_text: document.body ? String(document.body.innerText || '').slice(0, 1000) : null,
        modules: modules.map(function (name) { return {name: name, present: Boolean(window[name])}; }),
        required_modules: probe(function () {
            return typeof startupModules === 'undefined' ? null : startupModules.map(function (entry) {
                return {file: entry.file, name: entry.name || null, ready: startupModuleReady(entry)};
            });
        }),
        scripts: Array.from(document.scripts).map(function (script) {
            return {src: script.src, type: script.type, async: script.async, defer: script.defer};
        }),
        resources: performance.getEntriesByType('resource').filter(function (entry) {
            return entry.initiatorType === 'script' || entry.initiatorType === 'fetch';
        }).slice(-100).map(function (entry) {
            return {url: entry.name, type: entry.initiatorType, duration_ms: Math.round(entry.duration),
                response_status: typeof entry.responseStatus === 'number' ? entry.responseStatus : null};
        })
    };
})()"""


def native_page_diagnostics(window: Any) -> dict[str, Any]:
    # Bypass pinned Window.evaluate_js's eval wrapper: CSP may forbid that
    # wrapper, while Cocoa silently converts the resulting NSError to None.
    from PyObjCTools import AppHelper  # type: ignore[import-not-found]
    from webview.platforms.cocoa import BrowserView  # type: ignore[import-not-found]

    done, values, failures = threading.Event(), [], []

    def completed(result, error):
        try:
            if error is not None:
                raise RuntimeError(f"WKWebView diagnostic NSError {error.domain()}:{error.code()}: {error.localizedDescription()}")
            values.append(json.loads(str(result)))
        except BaseException as error:
            failures.append(error)
        finally:
            done.set()

    def evaluate():
        try:
            native = BrowserView.instances[window.uid].webkit
            native.evaluateJavaScript_completionHandler_("JSON.stringify(" + PAGE_DIAGNOSTICS_SCRIPT + ")", completed)
        except BaseException as error:
            failures.append(error)
            done.set()

    AppHelper.callAfter(evaluate)
    if not done.wait(15):
        raise TimeoutError("WKWebView direct page diagnostics did not respond")
    if failures:
        raise failures[0]
    return values[0]


def verify_page_policy(url: str) -> dict[str, Any]:
    origin = urlsplit(url)
    request = Request(url, headers={"Origin": f"{origin.scheme}://{origin.netloc}"})
    with urlopen(request, timeout=10) as response:
        assert response.geturl() == url, "The owned workbench unexpectedly redirected"
        policy = response.headers.get("Content-Security-Policy", "")
    directives = [value.strip().split() for value in policy.split(";") if value.strip()]
    scripts = next((parts[1:] for parts in directives if parts[0] == "script-src"), [])
    assert "'self'" in scripts and "'unsafe-eval'" not in scripts, policy
    return {"script_src": scripts, "unsafe_eval_allowed": False}


def isolated_environment(output: Path) -> Path:
    output = output.expanduser().resolve()
    if output.exists():
        raise ValueError("The smoke output directory must be new; existing data is never reused")
    if any(part.lower().endswith(".app") for part in output.parts):
        raise ValueError("Smoke output must be outside an application bundle")
    output.mkdir(parents=True, exist_ok=False)
    data = output / "data"
    data.mkdir()
    for key in list(os.environ):
        if key.upper().startswith(("ELECTROCHEM", "WEBVIEW2")):
            del os.environ[key]
    os.environ["ELECTROCHEM_V6_DATA_DIR"] = str(data)
    os.environ["ELECTROCHEM_V6_KEEP_TEST_RUNTIME"] = "1"
    for name, filename in {"HISTORY": "history.json", "PROJECTS": "projects.json", "CONVERSATION": "conversations.json",
                           "TEMPLATE": "templates.json", "QUALITY_REPORT": "quality.json", "LLM_CONFIG": "llm.json", "LOG": "server.log"}.items():
        os.environ[f"ELECTROCHEM_V6_{name}_FILE"] = str(data / filename)
    return data


def synthetic_cv(data: Path) -> dict[str, Any]:
    inputs = data / "synthetic-inputs"
    inputs.mkdir()
    path = inputs / "CV_synthetic.csv"
    rows = []
    for _cycle in range(2):
        for index in range(70):
            potential = index / 69
            current = .0007 * math.exp(-(potential - .52) ** 2 / .017) + .000025 * potential
            rows.append(f"{potential:.9f},{current:.12f}")
        for index in range(70):
            potential = 1 - index / 69
            current = -.0006 * math.exp(-(potential - .37) ** 2 / .019) - .00002 * potential
            rows.append(f"{potential:.9f},{current:.12f}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return {"folder_path": str(inputs), "data_types": ["CV"], "input_files": [{"data_type": "CV", "path": str(path)}],
            "project_name": "macOS synthetic native smoke", "params": {"cv_scan_rate_v_s": .05}}


def wait_for(predicate: Callable[[], Any], description: str, timeout: float = 30) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.1)
    raise TimeoutError(description)


def verify_cv_result(result: dict[str, Any], data: Path, input_path: Path, expected_hash: str) -> dict[str, Any]:
    from electrochem_v6.store.run_recipes import get_run_recipe
    from electrochem_v6.store.runtime import get_database

    assert result["status"] == "success", result
    records = get_database().get_all_history_records()
    assert len(records) == 1 and records[0]["type"] == "CV", records
    outputs = result["result"]["processing"]["output_files"]
    paths = [Path(item["path"] if isinstance(item, dict) else item) for item in outputs]
    assert paths and any(path.suffix.lower() == ".png" for path in paths)
    assert all(path.is_file() and path.resolve().is_relative_to(data) for path in paths)
    assert hashlib.sha256(input_path.read_bytes()).hexdigest() == expected_hash
    recipe = get_run_recipe(result["result"]["manifest"]["run"]["run_id"])
    assert recipe and recipe["status"] == "succeeded"
    assert recipe["params"]["cv_scan_rate_v_s"] == .05
    assert len(recipe["inputs"]) == 1
    assert Path(recipe["inputs"][0]["path"]).resolve() == input_path.resolve()
    assert recipe["inputs"][0]["sha256"] == expected_hash
    return {"history_records": len(records), "output_files": len(paths), "run_id": recipe["run_id"],
            "recipe_scan_rate_v_s": recipe["params"]["cv_scan_rate_v_s"], "input_sha256_unchanged": True}


def run_smoke(output_dir: Path, runtime_root: Path | None = None) -> int:
    if sys.platform != "darwin":
        raise RuntimeError("The native Cocoa smoke must run on macOS with an active desktop session")
    output = output_dir.expanduser().resolve()
    data = isolated_environment(output)
    (output / "report.json").write_text(json.dumps({"schema_version": 1, "status": "initializing", "normal_exit": False,
        "data_dir": str(data), "pid": os.getpid()}), encoding="utf-8")
    # Explicit synthetic smoke only: native imports and Cocoa callbacks can
    # deadlock before Python's ordinary timeouts or finally blocks can run.
    with (output / "threads.log").open("w", encoding="utf-8") as thread_log:
        faulthandler.dump_traceback_later(150, file=thread_log, exit=True)
        try:
            return _run_isolated_smoke(output, data, runtime_root)
        except Exception as error:
            report_path = output / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report.update(status="failed", normal_exit=False, error=str(error), traceback=traceback.format_exc())
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 1
        finally:
            faulthandler.cancel_dump_traceback_later()


def _run_isolated_smoke(output: Path, data: Path, runtime_root: Path | None = None) -> int:
    runtime = runtime_root or Path(__file__).resolve().parents[1]
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(runtime / "src"))
    import AppKit  # type: ignore[import-not-found]
    from PyObjCTools import AppHelper  # type: ignore[import-not-found]
    from webview.platforms.cocoa import BrowserView  # type: ignore[import-not-found]

    from electrochem_v6.config import APP_VERSION
    from electrochem_v6.core.process_service import process_folder
    from electrochem_v6.core.system_service import register_allowed_dir
    from electrochem_v6.desktop import mac_native
    from electrochem_v6.desktop.data import configure_desktop_environment
    from electrochem_v6.desktop.shell import DesktopShellApp
    from electrochem_v6.server import V6ServerManager
    from electrochem_v6.store.runtime import get_database, reset_runtime

    report: dict[str, Any] = {"schema_version": 1, "status": "running", "normal_exit": False,
        "version": APP_VERSION, "architecture": platform.machine(), "pid": os.getpid(), "data_dir": str(data),
        "entrypoint": str(Path(sys.executable).resolve()), "execution_mode": "frozen" if getattr(sys, "frozen", False) else "source",
        "checks": [], "manual_checks": {"native_picker_user_selection": "not_run", "Gatekeeper": "not_run", "macOS_13_and_14": "not_run"}}
    report_lock = threading.RLock()
    released, entered, orchestration_done = threading.Event(), threading.Event(), threading.Event()
    errors: list[str] = []

    def save():
        with report_lock:
            temporary = output / "report.json.tmp"
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(output / "report.json")

    def check(name: str, detail: Any):
        with report_lock:
            report["checks"].append({"id": name, "status": "passed", "detail": detail})
            save()

    def fail(error: BaseException):
        with report_lock:
            errors.append(str(error))
            report["status"] = "failed"
            if "error" not in report:
                report["error"] = str(error)
                report["traceback"] = traceback.format_exc()
            else:
                report["secondary_errors"] = errors[1:]
            save()

    save()
    payload = synthetic_cv(data)
    input_path = Path(payload["input_files"][0]["path"])
    report["input_sha256"] = hashlib.sha256(input_path.read_bytes()).hexdigest()
    configure_desktop_environment({"path": str(data), "mode": "environment"})
    reset_runtime()
    register_allowed_dir(str(input_path.parent))
    assert get_database().get_all_history_records() == []

    class SmokeShell(DesktopShellApp):
        smoke_runner: Any = None

        def _start_server(self):
            # Kernel-assigned private port: no existing desktop listener is used.
            self.manager = V6ServerManager(port=0)
            success, message = self.manager.start()
            if success:
                self.smoke_runner = self.manager._job_manager
                self.port = self.manager.port
                self.ui_url = f"http://127.0.0.1:{self.port}/ui?desktop=1"
                assert self.manager._server.server_address == ("127.0.0.1", self.port)
                check("owned_service", {"pid": os.getpid(), "port": self.port})
                check("owned_page_csp", verify_page_policy(self.ui_url))
            return success, message

        def _run_browser_fallback(self):
            raise AssertionError("Browser fallback cannot pass native WKWebView verification")

        def _js(self, script):
            # pywebview 4.4.1's evaluate_js has no native timeout. Keep a failed
            # bridge call from trapping the orchestration worker indefinitely.
            done, values, failures = threading.Event(), [], []

            def evaluate():
                try:
                    values.append(self.window.evaluate_js(script))
                except BaseException as error:
                    failures.append(error)
                finally:
                    done.set()

            threading.Thread(target=evaluate, daemon=True).start()
            if not done.wait(15):
                raise TimeoutError("WKWebView JavaScript did not respond")
            if failures:
                raise failures[0]
            return values[0] if values else None

        def _page_diagnostics(self, stage):
            # This page belongs to the fresh synthetic runtime. Record no
            # storage values, bridge token, request headers or script bodies.
            try:
                detail = native_page_diagnostics(self.window)
            except BaseException as error:
                detail = {"evaluation_error": str(error)}
            with report_lock:
                report.setdefault("page_diagnostics", []).append({"stage": stage, "detail": detail})
                save()
            return detail

        def _on_started(self):
            try:
                super()._on_started()
                self._page_diagnostics("after_native_started")
                wait_for(lambda: self._js("Boolean(typeof applicationStarted !== 'undefined' && applicationStarted && window.ElectrochemDesktop && ElectrochemDesktop.isReady())"),
                         "WKWebView workbench initialization")
                page_state = self._page_diagnostics("workbench_ready")
                assert page_state["application_started"] and page_state["desktop_ready"], page_state
                metadata = self._js("({title:document.title, heading:document.querySelector('.brand-title').textContent, error:Boolean(document.querySelector('#app-startup-error'))})")
                assert "ElectroChem" in metadata["title"] and "ElectroChem" in metadata["heading"] and not metadata["error"], metadata
                assert self.window.gui.renderer == "wkwebview"
                check("real_wkwebview", metadata)
                self._js("window.__nativeSmokeBridge = null; window.pywebview.api.get_state().then(value => { window.__nativeSmokeBridge = value; });")
                bridge = wait_for(lambda: self._js("window.__nativeSmokeBridge"), "JS bridge get_state")
                assert bridge["status"] == "success" and Path(bridge["data_dir"]).resolve() == data
                assert bridge["background_target"] == "dock"
                check("js_native_bridge", {"status": bridge["status"], "background_target": bridge["background_target"]})

                native_window = BrowserView.instances[self.window.uid].window
                assert self.hide_to_tray()["status"] == "success"
                wait_for(lambda: mac_native._on_main(lambda: not native_window.isVisible()), "Dock background hide")
                mac_native._on_main(lambda: BrowserView.app.delegate().applicationShouldHandleReopen_hasVisibleWindows_(BrowserView.app, False))
                wait_for(lambda: mac_native._on_main(native_window.isVisible), "Dock reopening")
                check("dock_background_and_reopen", "hidden window became visible through the native application delegate")

                # Real WK navigation is cancelled before the bridge can leave
                # /ui. Observe external handoff without launching another app.
                before = self.window.get_current_url()
                decision = threading.Event()
                original_navigation = self._mac_controller.navigation
                target = self.ui_url.split("/ui", 1)[0] + "/native-smoke-blocked"
                handoffs = []
                original_open = webbrowser.open

                def observed_navigation(url, **kwargs):
                    allowed = original_navigation(url, **kwargs)
                    if str(url) == target:
                        assert not allowed
                        decision.set()
                    return allowed

                try:
                    webbrowser.open = lambda url, *args, **kwargs: handoffs.append(url) or True
                    self._mac_controller.navigation = observed_navigation
                    self._js("window.location.href = " + json.dumps(target) + ";")
                    assert decision.wait(5), "WKNavigationDelegate did not see the attempted navigation"
                    wait_for(lambda: handoffs, "external navigation handoff", timeout=5)
                    assert self.window.get_current_url() == before
                    assert handoffs == [target]
                finally:
                    webbrowser.open = original_open
                    self._mac_controller.navigation = original_navigation
                check("privileged_navigation_blocked", "WKNavigationDelegate cancelled non-workbench navigation; local page retained and external handoff observed")

                def held_process(request):
                    entered.set()
                    if not released.wait(60):
                        raise TimeoutError("Smoke did not release the synthetic computation")
                    return process_folder(request)

                self.manager._job_manager._process_runner = held_process
                self._js("window.__nativeSmokeJob = null; ElectrochemApi.fetch('/api/v1/process/jobs', {method:'POST', headers:{'Content-Type':'application/json'}, body:"
                         + json.dumps(json.dumps(payload)) + "}).then(response => response.json()).then(value => {window.__nativeSmokeJob = value;});")
                submitted = wait_for(lambda: self._js("window.__nativeSmokeJob"), "real CV job submission")
                assert submitted["status"] == "success" and submitted.get("job_id"), submitted
                report["job_id"] = submitted["job_id"]
                assert entered.wait(5)
                save()

                def command_q():
                    event = AppKit.NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
                        AppKit.NSKeyDown, AppKit.NSMakePoint(0, 0), AppKit.NSCommandKeyMask, 0,
                        native_window.windowNumber(), None, "q", "q", False, 12)
                    assert event is not None
                    BrowserView.app.postEvent_atStart_(event, False)

                mac_native._on_main(command_q)
                wait_for(lambda: self._js("Boolean(document.querySelector('#desktop-close-dialog')?.open)"), "Command-Q safe close dialog")
                assert not self._allow_close and self.manager._job_manager.active_jobs()
                self._js("document.querySelector('#desktop-close-stay').click();")
                wait_for(lambda: self._js("!document.querySelector('#desktop-close-dialog').open"), "stay after Command-Q")
                check("command_q_safe_cancel", "real Command-Q event opened the task dialog; Keep working preserved running work")

                mac_native._on_main(lambda: BrowserView.app.terminate_(None))
                wait_for(lambda: self._js("Boolean(document.querySelector('#desktop-close-dialog')?.open)"), "native application Quit safe close dialog")
                assert not self._allow_close and self.manager._job_manager.active_jobs()
                self._js("document.querySelector('#desktop-close-wait').click();")
                wait_for(lambda: self.closing_mode == "wait", "JS bridge close decision")
                assert not self._allow_close and not self._closed.is_set()
                check("native_terminate_waits", "NSApp.terminate was vetoed; JS bridge selected wait while the job remained active")
                released.set()
            except BaseException as error:
                fail(error)
                self._page_diagnostics("failed")
                released.set()
                # This is a failed isolated test, never a claimed normal exit.
                # Stop its own Cocoa loop to preserve the failure report; the
                # shell finally block still closes the owned local service.
                AppHelper.callAfter(mac_native.stop_event_loop)
            finally:
                orchestration_done.set()

    app = SmokeShell(runtime, {"path": str(data), "mode": "environment"})
    try:
        result = app.run()
        assert orchestration_done.wait(5), "Native smoke worker did not complete"
        assert result == 0 and not errors, errors
        assert app._allow_close and app._closed.is_set() and app.manager and not app.manager.is_running
        job = get_database().get_processing_job(report["job_id"])
        assert job and job["status"] == "succeeded", job
        computed = verify_cv_result(job["result"], data, input_path, report["input_sha256"])
        check("real_cv_and_normal_exit", {"job_status": job["status"], **computed, "service_stopped": True, "window_closed": True})
        report["status"] = "passed"
        report["normal_exit"] = True
        return 0
    except BaseException as error:
        fail(error)
        return 1
    finally:
        released.set()
        if app.manager and app.manager.is_running:
            app.manager.stop()
        if app.smoke_runner is not None:
            # A failed GUI check may stop Cocoa while the synthetic runner is
            # still finishing. Join its callbacks before releasing SQLite.
            app.smoke_runner._executor.shutdown(wait=True)
        reset_runtime()
        save()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="new directory for synthetic runtime and report.json")
    args = parser.parse_args(argv)
    return run_smoke(args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
