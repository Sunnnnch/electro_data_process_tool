"""CSP-preserving adapters for the pinned pywebview 4.4.1 Cocoa backend.

Only the Cocoa API generator and each owned window instance are adapted.
JavaScript source is submitted directly to WKWebView; page CSP stays unchanged.
"""
from __future__ import annotations

import json
import threading
from types import MethodType
from typing import Any

_TIMEOUT_SECONDS = 15.0
_DYNAMIC_FACTORY = "window.pywebview.api[funcName] = new Function(params, funcBody)"
_CLOSURE_FACTORY = """window.pywebview.api[funcName] = (function(name) {
    return function() {
        var id = (Math.random() + '').substring(2);
        var promise = new Promise(function(resolve, reject) {
            window.pywebview._checkValue(name, resolve, reject, id);
        });
        window.pywebview._bridge.call(name, arguments, id);
        return promise;
    };
})(funcName)"""


def csp_safe_api_script(script: str) -> str:
    """Keep the existing bridge protocol, replacing its one dynamic factory."""
    if not isinstance(script, str) or script.count(_DYNAMIC_FACTORY) != 1:
        raise RuntimeError("Unsupported pywebview Cocoa API generator: expected the single 4.4.1 dynamic factory")
    return script.replace(_DYNAMIC_FACTORY, _CLOSURE_FACTORY, 1)


def patch_cocoa_api_generator() -> None:
    # cocoa imports parse_api_js by value; replacing webview.util alone would
    # leave navigation-time injection on the old generator.
    from webview.platforms import cocoa  # type: ignore[import-not-found]

    original = cocoa.parse_api_js
    if getattr(original, "_electrochem_csp_safe", False):
        return

    def parse_api_js(*args: Any, **kwargs: Any) -> str:
        return csp_safe_api_script(original(*args, **kwargs))

    setattr(parse_api_js, "_electrochem_csp_safe", True)
    cocoa.parse_api_js = parse_api_js


def _error_text(error: Any) -> str:
    domain, code = str(error.domain()), int(error.code())
    description = str(error.localizedDescription())
    details = error.userInfo() if callable(getattr(error, "userInfo", None)) else {}
    message = str((details or {}).get("WKJavaScriptExceptionMessage", ""))
    line = (details or {}).get("WKJavaScriptExceptionLineNumber")
    suffix = f"; {message}" if message and message != description else ""
    if line is not None:
        suffix += f" (line {line})"
    return f"{domain}:{code}: {description}{suffix}"


def _python_result(result: Any) -> Any:
    if result is None:
        return None
    import Foundation  # type: ignore[import-not-found]

    # Foundation containers and NSNull are not reliably json.dumps-compatible.
    # Wrapping the result also permits scalar strings, numbers and booleans
    # without enabling JSON fragments or evaluating another page script.
    encoded, error = Foundation.NSJSONSerialization.dataWithJSONObject_options_error_([result], 0, None)
    if error is not None or encoded is None:
        reason = _error_text(error) if error is not None else "no JSON data"
        raise RuntimeError(f"WKWebView result serialization failed: {reason}")
    values = json.loads(bytes(encoded).decode("utf-8"))
    if not isinstance(values, list) or len(values) != 1:
        raise RuntimeError("WKWebView returned an invalid serialized result")
    return values[0]


def _evaluate_js(window: Any, script: str, callback: Any = None) -> Any:
    if callback is not None:
        raise NotImplementedError("The macOS CSP-safe evaluator does not support Python Promise callbacks")
    if not isinstance(script, str):
        raise TypeError("JavaScript source must be a string")
    if threading.current_thread() is threading.main_thread():
        raise RuntimeError("Synchronous WKWebView evaluation must run outside the Cocoa main thread")
    if not window.events.loaded.wait(_TIMEOUT_SECONDS):
        raise TimeoutError("The macOS workbench did not finish loading before JavaScript evaluation")
    from PyObjCTools import AppHelper  # type: ignore[import-not-found]
    from webview.platforms.cocoa import BrowserView  # type: ignore[import-not-found]

    done, abandoned = threading.Event(), threading.Event()
    results: list[Any] = []
    errors: list[BaseException] = []

    def completion(result: Any, error: Any) -> None:
        if abandoned.is_set() or done.is_set():
            return
        try:
            if error is not None:
                # WKError.javaScriptResultTypeIsUnsupported: side effects may
                # succeed while their Promise/undefined result cannot cross
                # the native boundary. Do not invent a successful value.
                if str(error.domain()) == "WKErrorDomain" and int(error.code()) == 5:
                    results.append(None)
                else:
                    raise RuntimeError(_error_text(error))
            else:
                results.append(_python_result(result))
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    def evaluate() -> None:
        if abandoned.is_set():
            return
        try:
            instance = BrowserView.instances.get(window.uid)
            if instance is None:
                raise RuntimeError("The macOS window closed before JavaScript evaluation")
            instance.webkit.evaluateJavaScript_completionHandler_(script, completion)
        except BaseException as exc:
            errors.append(exc)
            done.set()

    AppHelper.callAfter(evaluate)
    if not done.wait(_TIMEOUT_SECONDS):
        abandoned.set()
        raise TimeoutError("WKWebView JavaScript evaluation did not complete")
    if errors:
        raise errors[0]
    return results[0] if results else None


def install_window_evaluator(window: Any) -> None:
    """Patch only this application's owned window, never the global Window class."""
    window.evaluate_js = MethodType(_evaluate_js, window)
