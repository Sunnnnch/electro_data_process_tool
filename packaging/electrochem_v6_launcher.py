"""Desktop launcher for the packaged v6 build.

This launcher starts the local HTTP service and opens the workbench inside an
embedded desktop WebView shell. If WebView startup fails, it falls back to the
system browser so the app remains usable.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _bootstrap_paths() -> None:
    if getattr(sys, "frozen", False):
        return
    root = _runtime_root()
    src = root / "src"
    for path in (src, root):
        raw = str(path)
        if raw not in sys.path:
            sys.path.insert(0, raw)


def _configure_runtime_data_dir() -> None:
    if os.environ.get("ELECTROCHEM_V6_DATA_DIR"):
        return
    data_dir = _runtime_root() / "user_data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        os.environ["ELECTROCHEM_V6_DATA_DIR"] = str(data_dir)
    except Exception:
        # Fall back to the default user directory defined in config.py.
        return


_configure_runtime_data_dir()
_bootstrap_paths()

import tkinter as tk
from tkinter import messagebox

from electrochem_v6.config import APP_VERSION, user_config_dir
from electrochem_v6.server import V6ServerManager

APP_TITLE = f"电化学数据处理软件 V{APP_VERSION}"
APP_SUBTITLE = "默认采用桌面工作台模式；若内嵌壳启动失败，会自动回退到浏览器模式。"
CANDIDATE_PORTS = (8010, 8011, 8012, 8013, 8014, 8015)
WINDOW_SIZE = (1480, 960)
MIN_WINDOW_SIZE = (1180, 760)


def _default_runtime_payloads() -> dict[str, object]:
    return {
        "projects.json": {"version": "1.0", "projects": [], "default_project": None},
        "processing_history.json": {"version": "1.0", "records": []},
        "conversation_history.json": {"conversations": [], "messages": {}},
        "process_templates.json": {"templates": []},
        "latest_quality_report.json": {},
    }


def _normalize_runtime_file(target: Path, payload: object) -> None:
    if not target.exists():
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    if target.name == "processing_history.json" and isinstance(existing, list):
        target.write_text(
            json.dumps({"version": "1.0", "records": existing}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class DesktopShellApp:
    def __init__(self) -> None:
        self.manager: Optional[V6ServerManager] = None
        self.port: Optional[int] = None
        self.ui_url = ""
        self.webview_error: Optional[str] = None

    def run(self) -> int:
        ok, message = self._start_server()
        if not ok:
            self._show_error(message)
            return 1
        if self._run_webview():
            return 0
        self._run_browser_fallback()
        return 0

    def _start_server(self) -> tuple[bool, str]:
        last_error = "未知错误"
        for port in CANDIDATE_PORTS:
            manager = V6ServerManager(port=port)
            ok, message = manager.start()
            if not ok:
                last_error = message
                continue
            if not self._wait_for_health(port):
                manager.stop()
                last_error = f"服务启动后健康检查失败: {port}"
                continue
            self.manager = manager
            self.port = port
            self.ui_url = f"http://127.0.0.1:{port}/ui"
            self._initialize_runtime_files()
            return True, message
        return False, last_error

    def _wait_for_health(self, port: int, timeout_sec: float = 15.0) -> bool:
        deadline = time.time() + timeout_sec
        url = f"http://127.0.0.1:{port}/health"
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1.5) as response:
                    if response.status == 200:
                        return True
            except Exception:
                time.sleep(0.25)
        return False

    def _run_webview(self) -> bool:
        try:
            import webview  # type: ignore
        except Exception as exc:
            self.webview_error = f"无法加载桌面壳组件: {exc}"
            return False

        try:
            window = webview.create_window(
                f"{APP_TITLE}  [{self.port}]",
                self.ui_url,
                width=WINDOW_SIZE[0],
                height=WINDOW_SIZE[1],
                min_size=MIN_WINDOW_SIZE,
                confirm_close=True,
                text_select=True,
            )
            window.events.closed += self._on_window_closed
            webview.start(gui="edgechromium", debug=False)
            return True
        except Exception as exc:
            self.webview_error = f"桌面壳启动失败: {exc}"
            self._stop_server()
            return False

    def _run_browser_fallback(self) -> None:
        root = tk.Tk()
        root.title(f"{APP_TITLE}  [{self.port}]")
        root.geometry("520x240")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", lambda: self._on_fallback_exit(root))

        outer = tk.Frame(root, padx=16, pady=16)
        outer.pack(fill="both", expand=True)

        tk.Label(outer, text=APP_TITLE, font=("Microsoft YaHei", 14, "bold")).pack(anchor="w")
        tk.Label(outer, text=APP_SUBTITLE, justify="left", wraplength=480).pack(anchor="w", pady=(8, 12))
        if self.webview_error:
            tk.Label(
                outer,
                text=f"桌面壳不可用，已回退为浏览器模式。\n原因: {self.webview_error}",
                justify="left",
                wraplength=480,
                fg="#b45309",
            ).pack(anchor="w", pady=(0, 12))

        tk.Label(outer, text=f"服务端口: {self.port}", anchor="w", justify="left").pack(fill="x", pady=2)
        tk.Label(outer, text=f"界面地址: {self.ui_url}", anchor="w", justify="left", wraplength=480).pack(fill="x", pady=2)
        tk.Label(
            outer,
            text=f"数据目录: {user_config_dir()}",
            anchor="w",
            justify="left",
            wraplength=480,
        ).pack(fill="x", pady=2)

        button_row = tk.Frame(outer)
        button_row.pack(fill="x", pady=(16, 0))
        tk.Button(button_row, text="打开界面", width=12, command=self._open_ui).pack(side="left")
        tk.Button(button_row, text="打开数据目录", width=12, command=self._open_data_dir).pack(side="left", padx=(8, 0))
        tk.Button(button_row, text="退出", width=10, command=lambda: self._on_fallback_exit(root)).pack(side="right")

        self._open_ui()
        root.mainloop()

    def _show_error(self, message: str) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            messagebox.showerror(APP_TITLE, message)
        finally:
            root.destroy()

    def _open_ui(self) -> None:
        if self.ui_url:
            webbrowser.open(self.ui_url)

    def _initialize_runtime_files(self) -> None:
        data_dir = user_config_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        for filename, payload in _default_runtime_payloads().items():
            _normalize_runtime_file(data_dir / filename, payload)
        logs_dir = data_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        runtime_info = {
            "pid": os.getpid(),
            "port": self.port,
            "ui_url": self.ui_url,
            "data_dir": str(data_dir),
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        (data_dir / "runtime_info.json").write_text(
            json.dumps(runtime_info, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _open_data_dir(self) -> None:
        data_dir = user_config_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(data_dir))  # type: ignore[attr-defined]
        except Exception as exc:
            self._show_error(f"无法打开目录:\n{data_dir}\n\n{exc}")

    def _on_window_closed(self) -> None:
        self._stop_server()

    def _on_fallback_exit(self, root: tk.Tk) -> None:
        self._stop_server()
        root.destroy()

    def _stop_server(self) -> None:
        if not self.manager:
            return
        try:
            self.manager.stop()
        except Exception:
            pass
        finally:
            self.manager = None
            self.port = None
            self.ui_url = ""


def main() -> int:
    app = DesktopShellApp()
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
