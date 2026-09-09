"""Cocoa adapter for pywebview 4.4.1; all AppKit work stays on its main loop.

The pinned backend's application termination and Command-Q bypass closing
vetoes. Install the delegates before the first WKWebView is constructed, so
every ordinary exit goes through the shell's admitted-write/job drain.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from .branding import icon_path

_controller: Any = None
_key_monitor: Any = None


def _on_main(callback: Callable[[], Any], timeout: float | None = 10) -> Any:
    if threading.current_thread() is threading.main_thread():
        return callback()
    from PyObjCTools import AppHelper  # type: ignore[import-not-found]

    done = threading.Event()
    result: list[Any] = []
    errors: list[BaseException] = []

    def run():
        try:
            result.append(callback())
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    AppHelper.callAfter(run)
    if not done.wait(timeout):
        raise TimeoutError("The macOS window is not responding")
    if errors:
        raise errors[0]
    return result[0] if result else None


def show_message(title: str, message: str, buttons: tuple[str, ...] = ("好 / OK",), *, warning: bool = False) -> int:
    """Native prompts may be used before or during the AppKit loop, never Tk."""
    import AppKit  # type: ignore[import-not-found]

    def show():
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        if warning:
            alert.setAlertStyle_(AppKit.NSAlertStyleWarning)
        for button in buttons:
            alert.addButtonWithTitle_(button)
        return int(alert.runModal()) - int(AppKit.NSAlertFirstButtonReturn)

    return int(_on_main(show, timeout=None))


def close_choice(title: str) -> str:
    selected = show_message(title,
        "有任务或保存操作正在进行。退出前会等待安全完成。\nTasks or writes are active. Exit waits for a safe boundary.",
        ("继续使用 / Keep working", "完成后退出 / Wait and quit", "取消任务后退出 / Cancel tasks and quit"), warning=True)
    return {1: "wait", 2: "cancel"}.get(selected, "stay")


def _post_loop_wakeup(application: Any) -> None:
    import AppKit  # type: ignore[import-not-found]

    # stop: checks its flag after an NSEvent, not a callAfter/timer callback.
    # https://developer.apple.com/documentation/appkit/nsapplication/stop(_:)
    event = AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
        AppKit.NSApplicationDefined, AppKit.NSMakePoint(0, 0), 0, 0, 0, None, 0, 0, 0)
    if event is None:
        raise RuntimeError("Unable to wake the macOS application event loop")
    application.postEvent_atStart_(event, True)


def stop_event_loop() -> None:
    """Stop this process's Cocoa loop and wake it (failed isolated smoke only)."""
    import AppKit  # type: ignore[import-not-found]

    def stop():
        application = AppKit.NSApplication.sharedApplication()
        application.stop_(None)
        _post_loop_wakeup(application)

    _on_main(stop)


class MacController:
    def __init__(self, origin: str, request_exit: Callable[[], Any], activate: Callable[[], Any]) -> None:
        self.origin = origin
        self.request_exit = request_exit
        self.activate = activate
        self.dock_menu: Any = None
        self._exit_lock = threading.Lock()

    def quit(self) -> None:
        # Never evaluate JavaScript while Cocoa is waiting on a delegate result.
        if not self._exit_lock.acquire(blocking=False):
            return

        def run():
            try:
                self.activate()
                self.request_exit()
            finally:
                self._exit_lock.release()

        threading.Thread(target=run, daemon=True, name="electrochem-macos-quit").start()

    def reopen(self) -> None:
        threading.Thread(target=self.activate, daemon=True, name="electrochem-macos-open").start()

    def close(self) -> None:
        import AppKit  # type: ignore[import-not-found]

        def remove():
            global _key_monitor
            if _key_monitor is not None:
                AppKit.NSEvent.removeMonitor_(_key_monitor)
                _key_monitor = None

        _on_main(remove)

    def navigation(self, url: str, *, main_frame: bool, new_window: bool = False) -> bool:
        from .native import external_web_url, is_workbench_url

        if main_frame and not new_window and is_workbench_url(url, self.origin):
            return True
        if main_frame or new_window:
            try:
                target = external_web_url(url)
            except ValueError:
                return False
            # The privileged webview never follows external navigation.
            import webbrowser
            threading.Thread(target=webbrowser.open, args=(target,), daemon=True).start()
        return False


def prepare_cocoa(origin: str, request_exit: Callable[[], Any], activate: Callable[[], Any]) -> MacController:
    """Patch only our three pinned backend classes, before creating any window."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Cocoa must initialize on the main thread")
    import AppKit  # type: ignore[import-not-found]
    import objc  # type: ignore[import-not-found]
    import WebKit  # type: ignore[import-not-found]
    from webview.platforms.cocoa import BrowserView  # type: ignore[import-not-found]

    from .mac_bridge import patch_cocoa_api_generator

    patch_cocoa_api_generator()
    global _controller
    _controller = MacController(origin, request_exit, activate)
    if not getattr(BrowserView, "_electrochem_adapted", False):
        class ElectroChemAppDelegate(BrowserView.AppDelegate):
            def applicationShouldTerminate_(self, _app):
                _controller.quit()
                return AppKit.NSTerminateCancel

            @objc.signature(b"Z@:@Z")
            def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, _visible):
                _controller.reopen()
                return True

            def openWorkspace_(self, _sender):
                _controller.reopen()

            def quitWorkspace_(self, _sender):
                _controller.quit()

            @objc.signature(b"@@:@")
            def applicationDockMenu_(self, _sender):
                if _controller.dock_menu is None:
                    menu = AppKit.NSMenu.alloc().initWithTitle_("ElectroChem")
                    for title, action in (("打开工作区 / Open workspace", "openWorkspace:"), ("退出 / Quit", "quitWorkspace:")):
                        item = menu.addItemWithTitle_action_keyEquivalent_(title, action, "")
                        item.setTarget_(self)
                    _controller.dock_menu = menu
                return _controller.dock_menu

        class ElectroChemBrowserDelegate(BrowserView.BrowserDelegate):
            def webView_decidePolicyForNavigationAction_decisionHandler_(self, _view, action, handler):
                if not handler.__block_signature__:
                    handler.__block_signature__ = BrowserView.pyobjc_method_signature(b"v@i")
                frame = action.targetFrame()
                allowed = _controller.navigation(str(action.request().URL().absoluteString()),
                    main_frame=bool(frame and frame.isMainFrame()), new_window=frame is None)
                handler(getattr(WebKit, "WKNavigationActionPolicyAllow", 1) if allowed else getattr(WebKit, "WKNavigationActionPolicyCancel", 0))

            def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(self, _view, _config, action, _features):
                _controller.navigation(str(action.request().URL().absoluteString()), main_frame=False, new_window=True)
                return None

            def webView_didReceiveAuthenticationChallenge_completionHandler_(self, _view, _challenge, handler):
                # Do not inherit 4.4.1's unconditional trust of server certificates.
                handler(AppKit.NSURLSessionAuthChallengePerformDefaultHandling, None)

        class ElectroChemWindowDelegate(BrowserView.WindowDelegate):
            def windowWillClose_(self, notification):
                # Preserve WKWebView release, window registry and closed events.
                # The pinned parent calls stop_ only after the last window closes.
                objc.super(ElectroChemWindowDelegate, self).windowWillClose_(notification)
                if not BrowserView.instances:
                    _post_loop_wakeup(BrowserView.app)

            def windowDidMove_(self, notification):
                instance = BrowserView.get_instance("window", notification.object())
                if instance:
                    frame = instance.window.frame()
                    screen = AppKit.NSScreen.screens()[0].frame()
                    top = screen.origin.y + screen.size.height
                    instance.pywebview_window.events.moved.set(int(frame.origin.x), int(top - frame.origin.y - frame.size.height))

        BrowserView.AppDelegate = ElectroChemAppDelegate
        BrowserView.BrowserDelegate = ElectroChemBrowserDelegate
        BrowserView.WindowDelegate = ElectroChemWindowDelegate
        setattr(BrowserView, "_electrochem_adapted", True)
    BrowserView.app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    global _key_monitor
    if _key_monitor is None:
        def key_event(event):
            if event.modifierFlags() & AppKit.NSCommandKeyMask and str(event.charactersIgnoringModifiers()).lower() == "q":
                _controller.quit()
                return None
            return event

        # A *local* event monitor requires no accessibility/Input Monitoring
        # permission. It prevents 4.4.1 WebKitHost.keyDown_ from calling stop_.
        # Replacing WebKitHost itself would break its class-bound super() calls.
        _key_monitor = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(AppKit.NSKeyDownMask, key_event)
        if _key_monitor is None:
            raise RuntimeError("Unable to install the safe macOS quit handler")
    return _controller


def activate_window(window: Any) -> None:
    from webview.platforms.cocoa import BrowserView  # type: ignore[import-not-found]

    def activate():
        native = BrowserView.instances[window.uid].window
        if native.isMiniaturized():
            native.deminiaturize_(None)
        native.makeKeyAndOrderFront_(None)
        BrowserView.app.unhide_(None)
        BrowserView.app.activateIgnoringOtherApps_(True)

    _on_main(activate)


def install_window_branding(_window: Any) -> None:
    import AppKit  # type: ignore[import-not-found]

    def apply():
        image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(icon_path("png")))
        if image is not None:
            AppKit.NSApplication.sharedApplication().setApplicationIconImage_(image)

    _on_main(apply)


def set_window_appearance(window: Any, appearance: dict[str, Any]) -> dict[str, Any]:
    import AppKit  # type: ignore[import-not-found]
    from webview.platforms.cocoa import BrowserView  # type: ignore[import-not-found]

    def apply():
        native = BrowserView.instances[window.uid].window
        high_contrast = bool(appearance["high_contrast"] or AppKit.NSWorkspace.sharedWorkspace().accessibilityDisplayShouldIncreaseContrast())
        name = AppKit.NSAppearanceNameDarkAqua if appearance["dark"] else AppKit.NSAppearanceNameAqua
        native.setAppearance_(None if high_contrast else AppKit.NSAppearance.appearanceNamed_(name))
        native.setTitlebarAppearsTransparent_(not high_contrast)
        if high_contrast:
            color = AppKit.NSColor.windowBackgroundColor()
        else:
            red, green, blue = (int(appearance["caption_color"][index:index + 2], 16) / 255 for index in (1, 3, 5))
            color = AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(red, green, blue, 1.0)
        native.setBackgroundColor_(color)
        # AppKit owns traffic-light controls and accessible title text contrast.
        return {"status": "success", "appearance": appearance, "high_contrast": high_contrast,
                "applied": {"dark": True, "caption_color": not high_contrast, "text_color": False}}

    return _on_main(apply)


def monitor_work_areas() -> list[tuple[int, int, int, int]]:
    import AppKit  # type: ignore[import-not-found]

    def collect():
        screens = AppKit.NSScreen.screens()
        if not screens:
            return []
        primary = screens[0].frame()
        top = primary.origin.y + primary.size.height
        areas = []
        for screen in screens:
            frame = screen.visibleFrame()
            areas.append((int(frame.origin.x), int(top - frame.origin.y - frame.size.height),
                          int(frame.origin.x + frame.size.width), int(top - frame.origin.y)))
        return areas

    return _on_main(collect)


def run_browser_fallback(shell: Any) -> None:
    """Keep a visible native service control when WKWebView cannot start."""
    import webbrowser
    from types import SimpleNamespace

    import AppKit  # type: ignore[import-not-found]
    from PyObjCTools import AppHelper  # type: ignore[import-not-found]

    from .environment import collect_environment_report, format_environment_report
    from .shell import APP_TITLE

    application = AppKit.NSApplication.sharedApplication()
    application.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)

    def activate():
        _on_main(lambda: application.activateIgnoringOtherApps_(True))

    controller = MacController(shell.ui_url, shell.request_exit, activate)
    global _controller
    _controller = controller
    shell._mac_controller = controller

    class ElectroChemFallbackDelegate(AppKit.NSObject):
        def applicationShouldTerminate_(self, _application):
            controller.quit()
            return AppKit.NSTerminateCancel

    delegate = ElectroChemFallbackDelegate.alloc().init()
    application.setDelegate_(delegate)
    shell._fallback_root = SimpleNamespace(after=lambda _delay, callback: AppHelper.callAfter(callback),
                                           destroy=application.abortModal, activate=activate)
    try:
        while not shell._allow_close and not shell._closed.is_set():
            choice = show_message(APP_TITLE,
                "macOS 桌面窗口暂不可用，可暂用浏览器工作区。保留此控制窗口以管理本地服务。\n"
                "The macOS window is unavailable. Use the browser workspace and keep this service control open.\n\n"
                + shell.webview_error[:300],
                ("打开浏览器 / Open browser", "复制环境诊断 / Copy diagnostics", "退出 / Quit"), warning=True)
            if shell._allow_close:
                break
            if choice == 0:
                webbrowser.open(shell.ui_url.split("?", 1)[0])
            elif choice == 1:
                report = format_environment_report(collect_environment_report(shell.runtime_root, shell.location))
                pasteboard = AppKit.NSPasteboard.generalPasteboard()
                pasteboard.clearContents()
                if not pasteboard.setString_forType_(report, AppKit.NSPasteboardTypeString):
                    show_message(APP_TITLE, "复制失败，请重试。 / Could not copy diagnostics. Please retry.", warning=True)
            else:
                controller.quit()
    finally:
        application.setDelegate_(None)
        shell._fallback_root = None
