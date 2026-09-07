"""Windows-specific adaptation for the pinned pywebview EdgeChromium backend."""

from __future__ import annotations

import ctypes
import re
import threading
from typing import Any, Callable
from urllib.parse import urlsplit

from .branding import APP_USER_MODEL_ID, icon_path


def configure_process_identity() -> bool:
    """Give source and frozen windows the same stable Windows taskbar identity."""
    try:
        set_identity = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_identity.argtypes = [ctypes.c_wchar_p]
        set_identity.restype = ctypes.c_long
        return set_identity(APP_USER_MODEL_ID) == 0
    except (AttributeError, OSError):
        return False


def clean_window_appearance(value: Any) -> dict[str, Any]:
    """Only resolved colors and boolean modes cross the native appearance bridge."""
    if not isinstance(value, dict):
        raise ValueError("Window appearance must be an object")
    result = {}
    for key in ("dark", "high_contrast"):
        if not isinstance(value.get(key), bool):
            raise ValueError(f"{key} must be a boolean")
        result[key] = value[key]
    for key in ("caption_color", "text_color"):
        color = value.get(key)
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError(f"{key} must be a six-digit RGB color")
        result[key] = color.upper()
    return result


def _colorref(color: str) -> int:
    red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return red | (green << 8) | (blue << 16)


def apply_dwm_appearance(hwnd: int, value: Any, *, system_high_contrast: bool = False) -> dict[str, Any]:
    """Ask DWM to paint native captions; unsupported attributes degrade independently.

    Reference: Microsoft's DWMWINDOWATTRIBUTE and Win32 theme documentation.
    Native caption controls, hit testing and Snap Layouts remain owned by Windows.
    """
    appearance = clean_window_appearance(value)
    high_contrast = system_high_contrast or appearance["high_contrast"]
    applied = {"dark": False, "caption_color": False, "text_color": False}
    try:
        setter = ctypes.windll.dwmapi.DwmSetWindowAttribute
        setter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
        setter.restype = ctypes.c_long
        attributes = (
            ("dark", 20, int(appearance["dark"] and not high_contrast)),
            ("caption_color", 35, 0xFFFFFFFF if high_contrast else _colorref(appearance["caption_color"])),
            ("text_color", 36, 0xFFFFFFFF if high_contrast else _colorref(appearance["text_color"])),
        )
        for name, attribute, number in attributes:
            encoded = ctypes.c_uint32(number)
            applied[name] = setter(ctypes.c_void_p(hwnd), attribute, ctypes.byref(encoded), ctypes.sizeof(encoded)) == 0
        # Repaint the non-client frame without changing position, focus or size.
        redraw = ctypes.windll.user32.RedrawWindow
        redraw.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
        redraw.restype = ctypes.c_int
        redraw(ctypes.c_void_p(hwnd), None, None, 0x0001 | 0x0100 | 0x0400)
    except (AttributeError, OSError):
        pass
    return {"status": "success" if any(applied.values()) else "unsupported",
            "appearance": appearance, "high_contrast": high_contrast, "applied": applied}


def set_window_appearance(window: Any, value: Any) -> dict[str, Any]:
    appearance = clean_window_appearance(value)
    from System import Action  # type: ignore[import-not-found]
    from System.Windows.Forms import SystemInformation  # type: ignore[import-not-found]
    from webview.platforms.winforms import BrowserView  # type: ignore[import-not-found]

    form = BrowserView.instances[window.uid]
    result: dict[str, Any] = {"status": "unavailable"}

    def apply():
        if not form.IsDisposed:
            result.update(apply_dwm_appearance(int(form.Handle.ToInt64()), appearance,
                                              system_high_contrast=bool(SystemInformation.HighContrast)))

    form.Invoke(Action(apply))
    return result


def install_window_branding(window: Any) -> None:
    from System import Action  # type: ignore[import-not-found]
    from System.Drawing import Icon  # type: ignore[import-not-found]
    from webview.platforms.winforms import BrowserView  # type: ignore[import-not-found]

    form = BrowserView.instances[window.uid]

    def apply():
        if form.IsDisposed or getattr(form, "_electrochem_icon", None) is not None:
            return
        picture = Icon(str(icon_path()), 32, 32)
        form.Icon = picture
        form.ShowIcon = True
        form._electrochem_icon = picture

        def release(_sender, _args):
            picture.Dispose()
            form._electrochem_icon = None

        form.FormClosed += release
        form._electrochem_brand_delegates = (release,)

    form.Invoke(Action(apply))


def external_web_url(url: Any) -> str:
    value = str(url or "").strip()
    if len(value) > 8192 or any(ord(ch) < 32 for ch in value):
        raise ValueError("Invalid web address")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only HTTP and HTTPS links can be opened")
    return value


def is_workbench_url(url: str, origin: str) -> bool:
    target, expected = urlsplit(url), urlsplit(origin)
    return (target.scheme, target.netloc) == (expected.scheme, expected.netloc) and target.path in {"/ui", "/ui/"}


def monitor_work_areas() -> list[tuple[int, int, int, int]]:
    try:
        from ctypes import wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

        areas = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

        def collect(handle, _dc, _rect, _data):
            info = MonitorInfo()
            info.size = ctypes.sizeof(info)
            if ctypes.windll.user32.GetMonitorInfoW(ctypes.c_void_p(handle), ctypes.byref(info)):
                rect = info.work
                areas.append((rect.left, rect.top, rect.right, rect.bottom))
            return True

        ctypes.windll.user32.EnumDisplayMonitors(None, None, callback_type(collect), 0)
        return areas
    except (AttributeError, OSError):
        return []


def install_windows_hooks(window: Any, origin: str, on_files: Callable, open_link: Callable) -> dict[str, bool]:
    """Keep the privileged bridge in the workbench and accept native file drops.

    This adapter deliberately targets our pinned pywebview 4.4 WinForms API.
    The rest of the application does not depend on backend-private objects.
    """
    from System import Action  # type: ignore[import-not-found]
    from System.Windows.Forms import DataFormats, DragDropEffects  # type: ignore[import-not-found]
    from webview.platforms.winforms import BrowserView  # type: ignore[import-not-found]

    form = BrowserView.instances[window.uid]
    result = {"navigation": False, "file_drop": False}

    def setup():
        control = form.browser.web_view
        core = control.CoreWebView2

        def navigate(_sender, args):
            target = str(args.Uri)
            if not is_workbench_url(target, origin):
                args.Cancel = True
                try:
                    external_web_url(target)
                except ValueError:
                    return
                threading.Thread(target=open_link, args=(target,), daemon=True).start()

        def new_window(_sender, args):
            args.Handled = True
            try:
                target = external_web_url(str(args.Uri))
            except ValueError:
                return
            threading.Thread(target=open_link, args=(target,), daemon=True).start()

        def frame_navigation(_sender, args):
            args.Cancel = True

        core.NavigationStarting += navigate
        core.FrameNavigationStarting += frame_navigation
        core.NewWindowRequested -= form.browser.on_new_window_request
        core.NewWindowRequested += new_window
        result["navigation"] = True

        def drag_enter(_sender, args):
            if args.Data.GetDataPresent(DataFormats.FileDrop):
                args.Effect = DragDropEffects.Copy

        def drag_drop(_sender, args):
            if args.Data.GetDataPresent(DataFormats.FileDrop):
                paths = [str(item) for item in args.Data.GetData(DataFormats.FileDrop)]
                threading.Thread(target=on_files, args=(paths,), daemon=True).start()

        for target in (form, control):
            target.AllowDrop = True
            target.DragEnter += drag_enter
            target.DragDrop += drag_drop
        # Keep delegates rooted for the lifetime of the native form.
        form._electrochem_delegates = (navigate, new_window, frame_navigation, drag_enter, drag_drop)
        result["file_drop"] = True

    form.Invoke(Action(setup))
    return result


def activate_window(window: Any) -> None:
    window.show()
    try:
        from System import Action  # type: ignore[import-not-found]
        from System.Windows.Forms import FormWindowState  # type: ignore[import-not-found]
        from webview.platforms.winforms import BrowserView  # type: ignore[import-not-found]
        form = BrowserView.instances[window.uid]

        def activate():
            if form.WindowState == FormWindowState.Minimized:
                form.WindowState = FormWindowState.Normal
            form.Activate()

        form.Invoke(Action(activate))
    except (ImportError, AttributeError, KeyError):
        pass
