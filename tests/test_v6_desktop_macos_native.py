"""Pinned Cocoa lifecycle contracts; actual AppKit smoke also runs on macOS CI."""

from __future__ import annotations

import sys
import threading
from types import SimpleNamespace

import pytest

from electrochem_v6.desktop import mac_native, native, shell


class ObjCObject:
    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return self


class Menu(ObjCObject):
    def initWithTitle_(self, title):
        self.title = title
        self.items = []
        return self

    def addItemWithTitle_action_keyEquivalent_(self, title, action, key):
        item = SimpleNamespace(title=title, action=action, key=key, setTarget_=lambda value: None)
        self.items.append(item)
        return item


def rect(x, y, width, height):
    return SimpleNamespace(origin=SimpleNamespace(x=x, y=y), size=SimpleNamespace(width=width, height=height))


@pytest.fixture
def cocoa(monkeypatch):
    calls, monitors, pending = [], [], []
    application = SimpleNamespace(
        setActivationPolicy_=lambda value: calls.append(("policy", value)),
        unhide_=lambda value: calls.append(("unhide", value)),
        activateIgnoringOtherApps_=lambda value: calls.append(("activate", value)),
        setApplicationIconImage_=lambda value: calls.append(("icon", value)),
    )
    screens = [SimpleNamespace(frame=lambda: rect(0, 0, 1440, 900), visibleFrame=lambda: rect(0, 60, 1440, 815)),
               SimpleNamespace(frame=lambda: rect(-1280, 0, 1280, 800), visibleFrame=lambda: rect(-1280, 0, 1280, 800))]
    appkit = SimpleNamespace(
        NSObject=ObjCObject, NSMenu=Menu, NSApplication=SimpleNamespace(sharedApplication=lambda: application),
        NSApplicationActivationPolicyRegular=0, NSTerminateCancel=0, NSCommandKeyMask=1 << 20, NSKeyDownMask=1 << 10,
        NSURLSessionAuthChallengePerformDefaultHandling=1,
        NSEvent=SimpleNamespace(
            addLocalMonitorForEventsMatchingMask_handler_=lambda mask, handler: monitors.append((mask, handler)) or handler,
            removeMonitor_=lambda handler: calls.append(("remove-monitor", handler)),
        ),
        NSScreen=SimpleNamespace(screens=lambda: screens),
        NSAppearanceNameDarkAqua="DarkAqua", NSAppearanceNameAqua="Aqua",
        NSAppearance=SimpleNamespace(appearanceNamed_=lambda name: name),
        NSColor=SimpleNamespace(colorWithSRGBRed_green_blue_alpha_=lambda *channels: channels, windowBackgroundColor=lambda: "system"),
        NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: SimpleNamespace(accessibilityDisplayShouldIncreaseContrast=lambda: False)),
    )
    view = SimpleNamespace(
        AppDelegate=type("OriginalAppDelegate", (ObjCObject,), {}),
        BrowserDelegate=type("OriginalBrowserDelegate", (ObjCObject,), {}),
        WindowDelegate=type("OriginalWindowDelegate", (ObjCObject,), {}),
        WebKitHost=type("OriginalWebKitHost", (ObjCObject,), {}),
        instances={}, app=application, pyobjc_method_signature=lambda value: value,
    )
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "WebKit", SimpleNamespace(WKNavigationActionPolicyAllow=1, WKNavigationActionPolicyCancel=0))
    monkeypatch.setitem(sys.modules, "objc", SimpleNamespace(signature=lambda value: lambda function: function))
    monkeypatch.setitem(sys.modules, "PyObjCTools", SimpleNamespace(AppHelper=SimpleNamespace(callAfter=lambda callback, *args: pending.append((callback, args)))))
    monkeypatch.setitem(sys.modules, "webview.platforms.cocoa", SimpleNamespace(BrowserView=view))
    monkeypatch.setattr(mac_native, "_controller", None)
    monkeypatch.setattr(mac_native, "_key_monitor", None)
    return SimpleNamespace(appkit=appkit, view=view, calls=calls, monitors=monitors, pending=pending, application=application)


def test_cocoa_quit_delegate_command_q_and_dock_share_safe_exit(cocoa):
    quit_requested, reopened = threading.Event(), threading.Event()
    host = cocoa.view.WebKitHost
    controller = mac_native.prepare_cocoa("http://127.0.0.1:8010/ui", quit_requested.set, reopened.set)
    delegate = cocoa.view.AppDelegate()
    assert delegate.applicationShouldTerminate_(cocoa.application) == 0
    assert quit_requested.wait(1)
    assert reopened.is_set()
    assert cocoa.view.WebKitHost is host, "4.4.1 host super() references must keep their original class"
    assert len(cocoa.monitors) == 1
    quit_requested.clear()
    event = SimpleNamespace(modifierFlags=lambda: 1 << 20, charactersIgnoringModifiers=lambda: "q")
    assert cocoa.monitors[0][1](event) is None
    assert quit_requested.wait(1)
    ordinary = SimpleNamespace(modifierFlags=lambda: 1 << 20, charactersIgnoringModifiers=lambda: "c")
    assert cocoa.monitors[0][1](ordinary) is ordinary
    reopened.clear()
    assert delegate.applicationShouldHandleReopen_hasVisibleWindows_(cocoa.application, False)
    assert reopened.wait(1)
    menu = delegate.applicationDockMenu_(None)
    assert [item.action for item in menu.items] == ["openWorkspace:", "quitWorkspace:"]
    assert delegate.applicationDockMenu_(None) is menu
    controller.close()
    assert ("remove-monitor", cocoa.monitors[0][1]) in cocoa.calls


def test_cocoa_preparation_requires_main_thread_and_installs_only_once(cocoa):
    errors = []

    def worker():
        try:
            mac_native.prepare_cocoa("http://127.0.0.1:8010/ui", lambda: None, lambda: None)
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(1)
    assert len(errors) == 1 and "main thread" in str(errors[0])
    mac_native.prepare_cocoa("http://127.0.0.1:8010/ui", lambda: None, lambda: None)
    delegate = cocoa.view.AppDelegate
    mac_native.prepare_cocoa("http://127.0.0.1:8011/ui", lambda: None, lambda: None)
    assert cocoa.view.AppDelegate is delegate
    assert len(cocoa.monitors) == 1


@pytest.mark.parametrize("url,main,new,expected", [
    ("http://127.0.0.1:8010/ui?desktop=1", True, False, True),
    ("http://127.0.0.1:8010/ui/", True, False, True),
    ("http://127.0.0.1:8010/ui", False, False, False),
    ("file:///etc/passwd", True, False, False),
    ("javascript:alert(1)", True, False, False),
    ("https://example.org/", False, False, False),
])
def test_cocoa_navigation_confines_bridge_and_blocks_subframes(url, main, new, expected, monkeypatch):
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda *args: pytest.fail("must not open this navigation"))
    controller = mac_native.MacController("http://127.0.0.1:8010/ui", lambda: None, lambda: None)
    assert controller.navigation(url, main_frame=main, new_window=new) is expected


def test_cocoa_delegate_external_navigation_opens_system_browser_and_keeps_default_tls(cocoa, monkeypatch):
    import webbrowser
    opened = threading.Event()
    urls = []
    monkeypatch.setattr(webbrowser, "open", lambda url: urls.append(url) or opened.set())
    mac_native.prepare_cocoa("http://127.0.0.1:8010/ui", lambda: None, lambda: None)
    delegate = cocoa.view.BrowserDelegate()
    action = SimpleNamespace(targetFrame=lambda: None,
        request=lambda: SimpleNamespace(URL=lambda: SimpleNamespace(absoluteString=lambda: "https://example.org/docs")))
    decisions = []

    def handler(value):
        decisions.append(value)

    handler.__block_signature__ = None
    delegate.webView_decidePolicyForNavigationAction_decisionHandler_(None, action, handler)
    assert decisions == [0]
    assert opened.wait(1) and urls == ["https://example.org/docs"]
    challenges = []
    delegate.webView_didReceiveAuthenticationChallenge_completionHandler_(None, object(), lambda *args: challenges.append(args))
    assert challenges == [(1, None)], "never unconditionally trust a server certificate"


def test_appkit_window_updates_are_dispatched_to_main_loop(cocoa):
    observed, result, errors = [], [], []

    def worker():
        try:
            result.append(mac_native._on_main(lambda: observed.append(threading.current_thread()) or "done"))
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=worker)
    thread.start()
    deadline = threading.Event()
    for _ in range(100):
        if cocoa.pending:
            break
        deadline.wait(.01)
    assert observed == []
    callback, args = cocoa.pending.pop()
    callback(*args)
    thread.join(1)
    assert not thread.is_alive() and not errors
    assert result == ["done"] and observed == [threading.main_thread()]


@pytest.mark.parametrize("high_contrast", [False, True])
def test_cocoa_titlebar_uses_theme_and_preserves_native_controls(cocoa, high_contrast):
    changes = []
    window = SimpleNamespace(uid="master")
    cocoa.view.instances["master"] = SimpleNamespace(window=SimpleNamespace(
        setAppearance_=lambda value: changes.append(("appearance", value)),
        setTitlebarAppearsTransparent_=lambda value: changes.append(("transparent", value)),
        setBackgroundColor_=lambda value: changes.append(("background", value)),
    ))
    appearance = {"dark": True, "caption_color": "#102C3C", "text_color": "#EDF2F7", "high_contrast": high_contrast}
    result = mac_native.set_window_appearance(window, appearance)
    assert changes == [("appearance", None if high_contrast else "DarkAqua"), ("transparent", not high_contrast),
                       ("background", "system" if high_contrast else (16 / 255, 44 / 255, 60 / 255, 1.0))]
    assert result["applied"]["text_color"] is False
    assert result["high_contrast"] is high_contrast


def test_cocoa_activation_unminimizes_and_work_areas_use_top_left_coordinates(cocoa):
    cocoa.view.instances["master"] = SimpleNamespace(window=SimpleNamespace(
        isMiniaturized=lambda: True, deminiaturize_=lambda value: cocoa.calls.append(("restore", value)),
        makeKeyAndOrderFront_=lambda value: cocoa.calls.append(("front", value)),
    ))
    mac_native.activate_window(SimpleNamespace(uid="master"))
    assert [call[0] for call in cocoa.calls] == ["restore", "front", "unhide", "activate"]
    assert mac_native.monitor_work_areas() == [(0, 25, 1440, 840), (-1280, 100, 0, 900)]


class WindowEvent(threading.Event):
    def __init__(self):
        super().__init__()
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


def test_macos_shell_selects_cocoa_before_window_without_tk_or_tray_loop(cocoa, monkeypatch, tmp_path):
    monkeypatch.setattr(shell.platform, "system", lambda: "Darwin")
    monkeypatch.setenv("PYWEBVIEW_GUI", "qt")
    monkeypatch.setenv("KDE_FULL_SESSION", "1")
    app = shell.DesktopShellApp(tmp_path, {"path": str(tmp_path), "mode": "user"})
    app.ui_url = "http://127.0.0.1:8010/ui?desktop=1"
    calls = []
    window = SimpleNamespace(events=SimpleNamespace(**{name: WindowEvent() for name in
        ("closing", "closed", "resized", "moved", "maximized", "restored", "loaded", "shown")}),
        hide=lambda: calls.append("hide"))

    def create_window(*args, **kwargs):
        assert app._mac_controller is not None
        calls.append("create")
        return window

    def start(callback, **kwargs):
        import os
        assert "gui" not in kwargs and not kwargs["debug"]
        assert "PYWEBVIEW_GUI" not in os.environ and "KDE_FULL_SESSION" not in os.environ
        assert threading.current_thread() is threading.main_thread()
        calls.append("start")

    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(create_window=create_window, start=start))
    monkeypatch.setitem(sys.modules, "tkinter", None)
    monkeypatch.setitem(sys.modules, "pystray", None)
    monkeypatch.setattr(app, "_start_server", lambda: (True, "ready"))
    assert app._start_with_splash()
    assert app._run_webview()
    assert calls == ["create", "start"]
    import os
    assert os.environ["PYWEBVIEW_GUI"] == "qt" and os.environ["KDE_FULL_SESSION"] == "1"
    app._start_tray()
    assert app._tray is None and app._tray_ready.is_set()
    assert app.hide_to_tray() == {"status": "success"}
    assert app._hidden and calls[-1] == "hide"
    assert app.get_state()["background_target"] == "dock"


def test_macos_background_cannot_hide_without_a_dock_controller(cocoa, monkeypatch, tmp_path):
    monkeypatch.setattr(shell.platform, "system", lambda: "Darwin")
    app = shell.DesktopShellApp(tmp_path, {"path": str(tmp_path), "mode": "user"})
    app.window = SimpleNamespace(hide=lambda: pytest.fail("must remain recoverable"))
    app._start_tray()
    assert not app._tray_ready.is_set()
    assert app.hide_to_tray()["status"] == "error"


def test_macos_command_quit_keeps_active_work_until_selected_wait_finishes(cocoa, monkeypatch, tmp_path):
    monkeypatch.setattr(shell.platform, "system", lambda: "Darwin")
    app = shell.DesktopShellApp(tmp_path, {"path": str(tmp_path), "mode": "user"})
    requested, destroyed, draining = threading.Event(), threading.Event(), threading.Event()
    jobs = [{"job_id": "synthetic", "kind": "process", "status": "running", "cancellable": True, "cancel_requested": False}]
    runner = SimpleNamespace(active_jobs=lambda: list(jobs), begin_desktop_exit=lambda cancel: draining.set())
    app.manager = SimpleNamespace(_job_manager=runner, desktop_active_writes=lambda: 0, close_desktop_admission=lambda: None)
    app.window = SimpleNamespace(evaluate_js=lambda script: None, destroy=destroyed.set)
    monkeypatch.setattr(app, "_activate", lambda: None)
    monkeypatch.setattr(app, "_emit", lambda event, detail: requested.set() if event == "electrochem:desktop-close" else None)
    mac_native.prepare_cocoa(app.ui_url, app.request_exit, app._activate)
    try:
        assert cocoa.view.AppDelegate().applicationShouldTerminate_(cocoa.application) == 0
        assert requested.wait(1)
        assert not destroyed.is_set() and app.closing_mode is None
        assert app.resolve_close("wait")["status"] == "success"
        assert draining.wait(1) and not destroyed.is_set()
        jobs.clear()
        assert destroyed.wait(2) and app._allow_close
    finally:
        app._closed.set()


def test_macos_exit_before_page_ready_uses_native_decision_without_js_deadlock(cocoa, monkeypatch, tmp_path):
    monkeypatch.setattr(shell.platform, "system", lambda: "Darwin")
    app = shell.DesktopShellApp(tmp_path, {"path": str(tmp_path), "mode": "user"})
    app.window = SimpleNamespace(events=SimpleNamespace(loaded=threading.Event()),
        evaluate_js=lambda script: pytest.fail("WKWebView has not loaded"))
    monkeypatch.setattr(app, "_closing_state", lambda: {"waiting": False, "active_count": 1})
    choices = []
    monkeypatch.setattr(mac_native, "close_choice", lambda title: "stay")
    monkeypatch.setattr(app, "resolve_close", lambda action: choices.append(action))
    app.request_exit()
    assert choices == ["stay"]


def test_macos_native_dispatch_does_not_import_dotnet(cocoa, monkeypatch):
    monkeypatch.setattr(native.platform, "system", lambda: "Darwin")
    calls = []
    monkeypatch.setattr(mac_native, "activate_window", lambda window: calls.append("activate"))
    monkeypatch.setattr(mac_native, "install_window_branding", lambda window: calls.append("brand"))
    monkeypatch.setattr(mac_native, "set_window_appearance", lambda window, value: calls.append(value) or {"status": "success"})
    assert native.configure_process_identity()
    native.activate_window(object())
    native.install_window_branding(object())
    assert native.set_window_appearance(object(), {"dark": False, "high_contrast": False,
        "caption_color": "#abcdef", "text_color": "#123456"})["status"] == "success"
    assert calls[:2] == ["activate", "brand"]
    assert calls[2]["caption_color"] == "#ABCDEF"
