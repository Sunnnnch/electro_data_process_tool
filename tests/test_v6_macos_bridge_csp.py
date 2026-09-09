"""Actual CSP browser contracts plus bounded native-completion adapter tests."""
from __future__ import annotations

import json
import sys
import threading
from types import SimpleNamespace

import pytest

from electrochem_v6.desktop import mac_bridge


def in_worker(function):
    values, errors = [], []

    def run():
        try:
            values.append(function())
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(2)
    assert not thread.is_alive(), "Native evaluation did not release its waiting thread"
    if errors:
        raise errors[0]
    return values[0] if values else None


@pytest.fixture
def native_completion(monkeypatch):
    loaded = threading.Event()
    loaded.set()
    window = SimpleNamespace(uid="owned", events=SimpleNamespace(loaded=loaded))
    state = {"value": None, "error": None, "scripts": [], "defer": False, "completion": None}

    def evaluate(script, completion):
        state["scripts"].append(script)
        state["completion"] = completion
        if not state["defer"]:
            completion(state["value"], state["error"])

    class JSONSerialization:
        @staticmethod
        def dataWithJSONObject_options_error_(value, options, error):
            assert isinstance(value, list) and len(value) == 1 and options == 0 and error is None
            return json.dumps(value, ensure_ascii=False).encode("utf-8"), None

    monkeypatch.setitem(sys.modules, "Foundation", SimpleNamespace(NSJSONSerialization=JSONSerialization))
    monkeypatch.setitem(sys.modules, "PyObjCTools", SimpleNamespace(AppHelper=SimpleNamespace(callAfter=lambda callback: callback())))
    monkeypatch.setitem(sys.modules, "webview.platforms.cocoa", SimpleNamespace(BrowserView=SimpleNamespace(instances={
        window.uid: SimpleNamespace(webkit=SimpleNamespace(evaluateJavaScript_completionHandler_=evaluate))})))
    monkeypatch.setattr(mac_bridge, "_TIMEOUT_SECONDS", 0.1)
    mac_bridge.install_window_evaluator(window)
    return window, state


@pytest.mark.parametrize("value", [None, True, 13, 4.5, "Chinese中文\\quotes\"", {"nested": [None, False, {"a": 3}]}, [1, "2"]])
def test_native_result_types_and_raw_script_are_preserved(native_completion, value):
    window, state = native_completion
    state["value"] = value
    script = "window.one = 1; window.two = 2; ({sum: window.one + window.two})"
    assert in_worker(lambda: window.evaluate_js(script)) == value
    assert state["scripts"] == [script]


def test_javascript_error_is_raised_with_location_and_never_masks_code_four(native_completion):
    window, state = native_completion
    state["error"] = SimpleNamespace(domain=lambda: "WKErrorDomain", code=lambda: 4,
        localizedDescription=lambda: "JavaScript exception", userInfo=lambda: {"WKJavaScriptExceptionMessage": "boom", "WKJavaScriptExceptionLineNumber": 7})
    with pytest.raises(RuntimeError, match=r"WKErrorDomain:4: JavaScript exception; boom \(line 7\)"):
        in_worker(lambda: window.evaluate_js("throw new Error('boom')"))


def test_only_webkit_unsupported_result_maps_to_none(native_completion):
    window, state = native_completion
    state["error"] = SimpleNamespace(domain=lambda: "WKErrorDomain", code=lambda: 5)
    assert in_worker(lambda: window.evaluate_js("Promise.resolve(1)")) is None
    state["error"] = SimpleNamespace(domain=lambda: "OtherDomain", code=lambda: 5, localizedDescription=lambda: "failure")
    with pytest.raises(RuntimeError, match="OtherDomain:5"):
        in_worker(lambda: window.evaluate_js("1"))


def test_no_completion_times_out_and_late_callback_cannot_poison_next_call(native_completion):
    window, state = native_completion
    state["defer"] = True
    with pytest.raises(TimeoutError, match="did not complete"):
        in_worker(lambda: window.evaluate_js("1"))
    old_completion = state["completion"]
    old_completion("late", None)
    state.update(defer=False, value={"current": True})
    assert in_worker(lambda: window.evaluate_js("({current: true})")) == {"current": True}


def test_callbacks_and_main_thread_evaluation_are_explicitly_rejected(native_completion):
    window, state = native_completion
    with pytest.raises(NotImplementedError, match="Promise callbacks"):
        in_worker(lambda: window.evaluate_js("1", callback=lambda result: None))
    with pytest.raises(RuntimeError, match="outside the Cocoa main thread"):
        window.evaluate_js("1")
    assert not state["scripts"]


def test_generator_fails_closed_when_pinned_factory_changes():
    with pytest.raises(RuntimeError, match="single 4.4.1"):
        mac_bridge.csp_safe_api_script("no expected factory")
    with pytest.raises(RuntimeError):
        mac_bridge.csp_safe_api_script(mac_bridge._DYNAMIC_FACTORY * 2)


def test_actual_pinned_bridge_factory_and_return_values_work_under_http_csp():
    from playwright.sync_api import sync_playwright
    from webview.js import api

    api_script = api.src % {"token": "synthetic", "platform": "cocoa", "uid": "owned",
                            "func_list": [{"func": "echo", "params": ["first", "second"]}, {"func": "reject", "params": []}],
                            "js_api_endpoint": ""}
    safe_script = mac_bridge.csp_safe_api_script(api_script)
    csp = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' blob:;"
    # The same header is emitted by the real HTTP application; this routed
    # test page has no desktop API beyond a synthetic protocol recorder.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            recorder = "window.bridgeCalls=[]; window.webkit={messageHandlers:{jsBridge:{postMessage: function(payload){ window.bridgeCalls.push(JSON.parse(payload)); }}}};"
            contract = r"""(async () => {
                let evalRejected = false, functionRejected = false;
                try { eval('1 + 1'); } catch (_) { evalRejected = true; }
                try { new Function('return 1')(); } catch (_) { functionRejected = true; }
                const p = pywebview.api.echo('中文\\\"', {n:1});
                const failed = pywebview.api.reject().then(() => null, error => ({name:error.name,message:error.message}));
                const a = bridgeCalls[0], b = bridgeCalls[1];
                pywebview._returnValues[a[0]][a[2]] = {value:JSON.stringify({a:a[1]['0'], b:a[1]['1']})};
                pywebview._returnValues[b[0]][b[2]] = {isError:true,value:JSON.stringify({name:'ValueError',message:'review input',stack:'synthetic'})};
                window.contractResult = {evalRejected,functionRejected,value:await p,error:await failed,names:bridgeCalls.map(x=>x[0]),remaining:Object.keys(pywebview._returnValues.echo).length};
            })()"""
            # Parser-executed scripts are essential: CDP Runtime.evaluate
            # (also used by add_script_tag) can bypass unsafe-eval CSP checks.
            document = '<!doctype html><html><head><meta charset="utf-8"></head><body>' + "".join(
                "<script>" + source + "</script>" for source in (recorder, safe_script, contract)
            ) + "</body></html>"
            page.route("http://electrochem.test/**", lambda route: route.fulfill(
                status=200, content_type="text/html", headers={"Content-Security-Policy": csp}, body=document))
            response = page.goto("http://electrochem.test/")
            assert response and response.headers["content-security-policy"] == csp and "unsafe-eval" not in csp
            page.wait_for_function("window.contractResult !== undefined")
            result = page.evaluate("window.contractResult")
            assert result["evalRejected"] and result["functionRejected"]
            assert result["value"] == {"a": '中文\\"', "b": {"n": 1}}
            assert result["error"] == {"name": "ValueError", "message": "review input"}
            assert result["names"] == ["echo", "reject"] and result["remaining"] == 0
        finally:
            browser.close()
