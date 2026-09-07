"""Desktop window, local service lifetime, tray, and reviewed startup migration."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from electrochem_v6.config import APP_NAME, APP_VERSION

from .branding import icon_path
from .bridge import DesktopBridge
from .data import (
    configure_desktop_environment,
    has_desktop_data,
    inspect_data_migration,
    legacy_data_candidates,
    migrate_desktop_data,
    resolve_desktop_data_dir,
)
from .instance import SingleInstance
from .mcp_integration import DesktopServiceDiscovery
from .native import (
    activate_window,
    clean_window_appearance,
    configure_process_identity,
    external_web_url,
    install_window_branding,
    install_windows_hooks,
    monitor_work_areas,
    set_window_appearance,
)
from .state import DesktopState, fit_window

APP_TITLE = f"ElectroChem｜{APP_NAME}"
WEBVIEW_RUNTIME_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
_logger = logging.getLogger(__name__)


def _set_tk_icon(root: Any) -> None:
    try:
        root.iconbitmap(default=str(icon_path()))
    except Exception:
        _logger.debug("Native startup icon unavailable", exc_info=True)


class DesktopShellApp:
    def __init__(self, runtime_root: Path, location: dict[str, str] | None = None) -> None:
        self.runtime_root = Path(runtime_root).resolve()
        self.location = location or resolve_desktop_data_dir(self.runtime_root)
        self.data_dir = Path(self.location["path"])
        self.state = DesktopState(self.data_dir)
        self.instance = SingleInstance(self.data_dir, self._activate)
        self.manager: Any = None
        self.window: Any = None
        self.port: int | None = None
        self.ui_url = ""
        self.webview_error = ""
        self.closing_mode: str | None = None
        self.migration_notice = ""
        self._mcp_discovery: DesktopServiceDiscovery | None = None
        self._tray: Any = None
        self._tray_ready = threading.Event()
        self._closed = threading.Event()
        self._allow_close = False
        self._hidden = False
        self._want_focus = False
        self._close_lock = threading.RLock()
        self._window_lock = threading.RLock()
        self._normal_window = fit_window(self.state.get("window"), monitor_work_areas())
        self._maximized = bool(self._normal_window["maximized"])
        self._native_ready = False
        self._fallback_root: Any = None
        default_appearance = {"dark": False, "caption_color": "#EDF2F7", "text_color": "#102C3C", "high_contrast": False}
        try:
            self._window_appearance = clean_window_appearance(self.state.get("window_appearance", default_appearance))
        except ValueError:
            self._window_appearance = default_appearance

    def run(self) -> int:
        configure_process_identity()
        if not self.instance.acquire():
            if not self.instance.activate_existing():
                self._show_error("客户端正在启动或暂时无法响应，请稍后再次打开。已有实例保持运行。")
                return 1
            return 0
        try:
            if not self._start_with_splash():
                return 1
            if not self._run_webview():
                self._run_browser_fallback()
            return 0
        finally:
            self._closed.set()
            if self._tray:
                self._tray.stop()
            try:
                if self.manager:
                    self.manager.stop()
            finally:
                if self._mcp_discovery:
                    self._mcp_discovery.close()
                self.instance.close()

    def _start_server(self) -> tuple[bool, str]:
        from electrochem_v6.core.system_service import register_allowed_dir
        from electrochem_v6.server import V6ServerManager
        receipt = self.data_dir / "desktop-migration.json"
        if receipt.is_file():
            try:
                for root in json.loads(receipt.read_text(encoding="utf-8")).get("legacy_read_roots", []):
                    register_allowed_dir(root)
            except (ValueError, OSError):
                _logger.warning("Could not read migration receipt", exc_info=True)
        preferred = self.state.get("port", 8010)
        ports = list(dict.fromkeys([preferred, *range(8010, 8020)]))
        last_error = "Unable to start local processing service"
        for port in ports:
            if not isinstance(port, int) or not 1024 <= port <= 65535:
                continue
            manager = V6ServerManager(port=port)
            ok, message = manager.start()
            if not ok:
                last_error = message
                continue
            self.manager, self.port = manager, port
            self.ui_url = f"http://127.0.0.1:{port}/ui?desktop=1"
            self.state.set("port", port)
            (self.data_dir / "runtime_info.json").write_text(json.dumps({
                "pid": os.getpid(), "port": port, "ui_url": self.ui_url, "data_dir": str(self.data_dir),
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "client": "desktop",
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            self._mcp_discovery = DesktopServiceDiscovery(self.data_dir, port, manager.session_token)
            self._mcp_discovery.publish()
            return True, message
        return False, last_error

    def _start_with_splash(self) -> bool:
        import tkinter as tk
        from tkinter import ttk
        splash = tk.Tk()
        splash.title(APP_TITLE)
        _set_tk_icon(splash)
        splash.geometry("520x180")
        splash.resizable(False, False)
        splash.protocol("WM_DELETE_WINDOW", lambda: None)
        ttk.Label(splash, text="ElectroChem", font=("Microsoft YaHei", 20, "bold")).pack(pady=(24, 6))
        ttk.Label(splash, text="正在启动本地工作区… / Starting your local workspace…").pack()
        progress = ttk.Progressbar(splash, mode="indeterminate", length=440)
        progress.pack(pady=18)
        progress.start()
        result: list[tuple[bool, str]] = []

        def start():
            try:
                result.append(self._start_server())
            except Exception as exc:
                _logger.exception("Desktop startup failed")
                result.append((False, str(exc)))

        worker = threading.Thread(target=start, daemon=True)
        worker.start()
        while worker.is_alive():
            splash.update()
            time.sleep(0.02)
        splash.destroy()
        ok, message = result[0]
        if not ok:
            self._show_error(message)
        return ok

    def _run_webview(self) -> bool:
        try:
            import webview  # type: ignore[import-not-found]
            rectangle = self._normal_window
            self.window = webview.create_window(
                APP_TITLE, self.ui_url, js_api=DesktopBridge(self),
                width=rectangle["width"], height=rectangle["height"], x=rectangle["x"], y=rectangle["y"],
                min_size=(min(960, rectangle["width"]), min(640, rectangle["height"])),
                maximized=rectangle["maximized"], confirm_close=False, text_select=True,
                background_color=self._window_appearance["caption_color"],
            )
            self.window.events.closing += self._on_closing
            self.window.events.closed += self._closed.set
            self.window.events.resized += self._on_resized
            self.window.events.moved += self._on_moved
            self.window.events.maximized += self._on_maximized
            self.window.events.restored += self._on_restored
            self.window.events.loaded += self._on_loaded
            self.window.events.shown += self._on_shown
            storage = self.data_dir / "webview"
            storage.mkdir(parents=True, exist_ok=True)
            webview.start(self._on_started, gui="edgechromium", debug=False,
                          private_mode=False, storage_path=str(storage))
            return True
        except Exception as exc:
            self.webview_error = str(exc)
            _logger.exception("Desktop WebView failed")
            self.window = None
            return False

    def _on_started(self) -> None:
        if not self.window.events.loaded.wait(30):
            return
        try:
            install_windows_hooks(self.window, self.ui_url, self._receive_files, self.open_link)
            self._native_ready = True
        except Exception:
            _logger.exception("Native window integration could not initialize")
        self._on_shown()
        self._start_tray()
        if self._want_focus:
            self._activate()
        self._emit("electrochem:desktop-state", self.get_state())
        threading.Thread(target=self._watch_tasks, daemon=True, name="electrochem-desktop-tasks").start()

    def _on_shown(self) -> None:
        try:
            install_window_branding(self.window)
            with self._window_lock:
                set_window_appearance(self.window, self._window_appearance)
        except Exception:
            _logger.debug("Native window branding deferred", exc_info=True)

    def set_window_appearance(self, value: Any) -> dict[str, Any]:
        appearance = clean_window_appearance(value)
        with self._window_lock:
            if appearance != self._window_appearance:
                self.state.set("window_appearance", appearance)
                self._window_appearance = appearance
            try:
                return set_window_appearance(self.window, appearance)
            except Exception:
                _logger.debug("Native title bar styling unavailable", exc_info=True)
                return {"status": "unsupported", "appearance": appearance}

    def _on_loaded(self) -> None:
        if self.closing_mode:
            self._emit("electrochem:desktop-state", self.get_state())

    def _start_tray(self) -> None:
        try:
            import pystray  # type: ignore[import-not-found]
            from PIL import Image
            with Image.open(icon_path("png")) as source:
                picture = source.copy()
            self._tray = pystray.Icon("ElectroChem", picture, APP_TITLE,
                menu=pystray.Menu(
                    pystray.MenuItem("打开工作区 / Open", lambda _icon, _item: self._activate(), default=True),
                    pystray.MenuItem("退出 / Exit", lambda _icon, _item: self._request_exit_from_tray()),
                ))

            def ready(icon):
                icon.visible = True
                self._tray_ready.set()

            threading.Thread(target=self._tray.run, args=(ready,), daemon=True, name="electrochem-tray").start()
            self._tray_ready.wait(3)
        except Exception:
            _logger.exception("System tray unavailable")
            self._tray = None

    def _watch_tasks(self) -> None:
        previous = 0
        while not self._closed.wait(1):
            active = self._closing_state()["active_count"]
            if self._tray and self._tray_ready.is_set():
                self._tray.title = f"ElectroChem · {active} 个运行任务 / active tasks"
                if self._hidden and previous and not active:
                    self._tray.notify("任务已结束，打开工作区查看结果。 / Tasks finished. Open the workspace to review results.", "ElectroChem")
            previous = active

    def _activate(self) -> None:
        self._want_focus = True
        if self.window:
            try:
                activate_window(self.window)
                self._hidden = False
                self._want_focus = False
            except Exception:
                _logger.debug("Window activation deferred until ready", exc_info=True)

    def hide_to_tray(self) -> dict[str, Any]:
        if not self._tray_ready.is_set():
            return {"status": "error", "message": "系统托盘不可用，请使用最小化保留后台任务。 / Tray unavailable; minimize the window."}
        self.window.hide()
        self._hidden = True
        return {"status": "success"}

    def _request_exit_from_tray(self) -> None:
        self._activate()
        self.request_exit()

    def _runner(self):
        return self.manager._job_manager if self.manager else None

    def _closing_state(self) -> dict[str, Any]:
        runner = self._runner()
        tasks = runner.active_jobs() if runner else []
        writes = self.manager.desktop_active_writes() if self.manager else 0
        if writes:
            tasks.append({"job_id": "desktop-writes", "kind": "process", "status": "running",
                          "stage": f"正在完成 {writes} 个保存操作 / Finishing {writes} write operation(s)",
                          "cancellable": False, "cancel_requested": False})
        return {"waiting": bool(self.closing_mode), "mode": self.closing_mode, "tasks": tasks,
                "active_count": len(tasks), "protected_count": sum(not item["cancellable"] and not item["cancel_requested"] for item in tasks)}

    def get_state(self) -> dict[str, Any]:
        return {"status": "success", "version": APP_VERSION, "data_dir": str(self.data_dir),
                "data_mode": self.location["mode"], "preferences": self.state.preferences(),
                "tray_available": self._tray_ready.is_set(), "native_file_drop": self._native_ready,
                "migration_notice": self.migration_notice, "closing": self._closing_state()}

    def _on_closing(self) -> bool:
        if self._allow_close:
            return True
        # WinForms waits for this callback; JavaScript must run after it returns.
        threading.Thread(target=self.request_exit, daemon=True).start()
        return False

    def request_exit(self) -> None:
        with self._close_lock:
            # Capture the last UI edit even if its normal debounce has not fired.
            if self.window:
                try:
                    snapshot = self.window.evaluate_js("window.ElectrochemDesktop && ElectrochemDesktop.isReady() ? JSON.stringify(ElectrochemDesktop.getPreferencesSnapshot()) : null")
                    if isinstance(snapshot, str):
                        self.state.save_preferences(json.loads(snapshot))
                except Exception:
                    _logger.warning("Unable to capture final UI preferences", exc_info=True)
            state = self._closing_state()
            if state["waiting"]:
                self._emit("electrochem:desktop-state", self.get_state())
            elif not state["active_count"]:
                self.resolve_close("wait")
            else:
                self._emit("electrochem:desktop-close", state)

    def resolve_close(self, action: str) -> dict[str, Any]:
        if action not in {"stay", "background", "wait", "cancel"}:
            return {"status": "error", "message": "Unknown exit action"}
        with self._close_lock:
            if self.closing_mode:
                return {"status": "success", "closing": self._closing_state()}
            if action == "stay":
                return {"status": "success"}
            if action == "background":
                return self.hide_to_tray()
            self.closing_mode = action
            if self.manager:
                self.manager.close_desktop_admission()
            self._emit("electrochem:desktop-state", self.get_state())
            threading.Thread(target=self._finish_exit, daemon=True, name="electrochem-exit").start()
            return {"status": "success", "closing": self._closing_state()}

    def _finish_exit(self) -> None:
        # An admitted request may still be reading its body before submitting a
        # job. Drain these requests before closing the executor's admission, so
        # accepted work cannot become a 500 response during an ordinary exit.
        while self.manager and self.manager.desktop_active_writes():
            if self._closed.is_set():
                return
            self._emit("electrochem:desktop-state", self.get_state())
            self._closed.wait(0.4)
        runner = self._runner()
        if runner:
            runner.begin_desktop_exit(cancel=self.closing_mode == "cancel")
        while not self._closed.is_set():
            if not self._closing_state()["active_count"]:
                self._allow_close = True
                if self.window:
                    self.window.destroy()
                elif self._fallback_root:
                    self._fallback_root.after(0, self._fallback_root.destroy)
                return
            self._emit("electrochem:desktop-state", self.get_state())
            self._closed.wait(0.4)

    def _emit(self, event: str, detail: Any) -> None:
        if self.window and not self._closed.is_set():
            try:
                self.window.evaluate_js(f"window.dispatchEvent(new CustomEvent({json.dumps(event)}, {{detail:{json.dumps(detail, ensure_ascii=False)}}}));")
            except Exception:
                _logger.debug("Desktop event unavailable: %s", event, exc_info=True)

    def _on_moved(self, x: int, y: int) -> None:
        if not self._maximized:
            with self._window_lock:
                self._normal_window.update(x=int(x), y=int(y), maximized=False)
                self.state.set("window", self._normal_window)

    def _on_resized(self, width: int, height: int) -> None:
        if not self._maximized and width >= 640 and height >= 480:
            with self._window_lock:
                self._normal_window.update(width=int(width), height=int(height), maximized=False)
                self.state.set("window", self._normal_window)

    def _on_maximized(self) -> None:
        self._maximized = True
        self.state.set("window", {**self._normal_window, "maximized": True})

    def _on_restored(self) -> None:
        self._maximized = False
        self.state.set("window", {**self._normal_window, "maximized": False})

    @staticmethod
    def validate_input_files(paths: Any) -> list[str]:
        from electrochem_v6.core.system_service import register_allowed_dir
        if not isinstance(paths, (list, tuple)) or len(paths) > 1000:
            raise ValueError("Select at most 1000 data files")
        selected = []
        for value in paths:
            path = Path(str(value)).resolve()
            if path.is_file() and path.suffix.lower() in {".txt", ".csv"}:
                register_allowed_dir(str(path.parent))
                selected.append(str(path))
        return list(dict.fromkeys(selected))

    def _receive_files(self, paths: list[str]) -> None:
        if not self.closing_mode:
            validated = self.validate_input_files(paths)
            if validated:
                self._emit("electrochem:desktop-files", {"paths": validated})

    @staticmethod
    def open_link(url: str) -> None:
        webbrowser.open(external_web_url(url))

    def get_migration_plan(self) -> dict[str, Any]:
        candidates = []
        for candidate in legacy_data_candidates(self.runtime_root, target_dir=self.data_dir):
            plan = inspect_data_migration(candidate["path"], self.data_dir)
            candidates.append({"source_id": hashlib.sha256(candidate["path"].encode()).hexdigest()[:16],
                "label": "旧版客户端数据 / Previous desktop data", "source_dir": candidate["path"],
                "target_dir": str(self.data_dir), "can_migrate": plan["can_migrate"],
                "reason": "；".join(plan["issues"]), "files_count": plan["file_count"],
                "total_bytes": plan["size_bytes"], "requires_source_retention": True})
        return {"status": "success", "candidates": candidates, "requires_restart": True}

    def queue_migration(self, source_id: str) -> dict[str, Any]:
        candidate = next((item for item in self.get_migration_plan()["candidates"] if item["source_id"] == source_id), None)
        if not candidate or not candidate["can_migrate"]:
            return {"status": "error", "message": "当前工作区已有数据或旧程序仍在运行，不能覆盖。请保留原目录并在首次启动的迁移向导中处理。"}
        self.state.set("pending_migration", source_id)
        return {"status": "success", "message": "已记录，退出并重新打开客户端后会展示迁移确认。"}

    def _run_browser_fallback(self) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk
        root = tk.Tk()
        self._fallback_root = root
        root.title(APP_TITLE)
        _set_tk_icon(root)
        root.geometry("620x320")
        body = ttk.Frame(root, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="桌面窗口暂不可用 / Desktop component unavailable", font=("Microsoft YaHei", 13, "bold")).pack(anchor="w")
        ttk.Label(body, text="可安装 Microsoft WebView2 后重试，或暂用浏览器工作区。\nInstall WebView2 and retry, or use the browser workspace.", wraplength=570).pack(anchor="w", pady=12)
        ttk.Label(body, text=self.webview_error[:300], wraplength=570).pack(anchor="w")
        ttk.Button(body, text="打开浏览器工作区 / Open browser", command=lambda: webbrowser.open(self.ui_url.split("?", 1)[0])).pack(anchor="w", pady=(12, 4))
        ttk.Button(body, text="安装 WebView2 / Get WebView2", command=lambda: self.open_link(WEBVIEW_RUNTIME_URL)).pack(anchor="w", pady=4)

        def close():
            if self.closing_mode:
                return
            if self._closing_state()["active_count"]:
                choice = messagebox.askyesnocancel(APP_TITLE, "有任务正在运行。\n是：等待完成后退出；否：取消可取消任务后退出；取消：继续使用。\nYes: wait; No: cancel tasks then exit; Cancel: keep working.", parent=root)
                if choice is None:
                    return
                self.resolve_close("wait" if choice else "cancel")
            else:
                self.resolve_close("wait")

        root.protocol("WM_DELETE_WINDOW", close)
        ttk.Button(body, text="退出 / Exit", command=close).pack(anchor="e", pady=8)
        root.mainloop()

    @staticmethod
    def _show_error(message: str) -> None:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        _set_tk_icon(root)
        try:
            messagebox.showerror(APP_TITLE, message)
        finally:
            root.destroy()


def _review_first_start_migration(runtime_root: Path, location: dict[str, str]) -> str:
    if location["mode"] != "user" or has_desktop_data(location["path"]):
        return ""
    candidates = legacy_data_candidates(runtime_root, target_dir=location["path"])
    if not candidates:
        return ""
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    _set_tk_icon(root)
    try:
        candidate = candidates[0]
        plan = inspect_data_migration(candidate["path"], location["path"])
        text = f"发现旧版客户端数据：\n{candidate['path']}\n\n目标：\n{location['path']}\n\n共 {plan['file_count']} 个文件。复制后历史文件仍可能引用旧目录，请保留原目录。\n\nFound previous desktop data. Keep the old folder after copying."
        if plan["requires_source_confirmation"]:
            if not messagebox.askyesno(APP_TITLE, text + "\n\n请确认旧程序已完全关闭。 / Is the previous application fully closed?", parent=root):
                return "未迁移旧数据；原目录保持不变。"
            plan = inspect_data_migration(candidate["path"], location["path"], confirm_source_stopped=True)
        if not plan["can_migrate"]:
            messagebox.showwarning(APP_TITLE, text + "\n\n" + "；".join(plan["issues"]), parent=root)
            return "旧数据未复制；请检查原目录及进程状态。"
        if not messagebox.askyesno(APP_TITLE, text + "\n\n现在复制到新工作区？ / Copy now?", parent=root):
            return "未迁移旧数据；原目录保持不变。"
        result = migrate_desktop_data(candidate["path"], location["path"], expected_plan_id=plan["plan_id"], confirm_source_stopped=True)
        configure_desktop_environment(location)
        return f"已复制 {result['file_count']} 个旧版数据文件。历史仍可能引用旧目录，请保留。"
    finally:
        root.destroy()


def run_desktop(runtime_root: Path) -> int:
    try:
        configure_process_identity()
        location = configure_desktop_environment(resolve_desktop_data_dir(runtime_root))
        notice = _review_first_start_migration(runtime_root, location)
        app = DesktopShellApp(runtime_root, location)
        app.migration_notice = notice
        return app.run()
    except Exception as exc:
        _logger.exception("Desktop client failed")
        DesktopShellApp._show_error(str(exc))
        return 1
