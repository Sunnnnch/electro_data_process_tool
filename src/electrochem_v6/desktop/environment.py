"""Small, offline desktop diagnostics; never import the processing engine.

Only explicitly selected platform facts are reported. Configuration contents,
environment dumps, access tokens, input files and logs are never collected.
The minimum versions below are release policy, not a claim of VM validation.
"""

from __future__ import annotations

import ctypes
import errno
import importlib
import json
import os
import platform
import re
import struct
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from electrochem_v6.config import APP_VERSION

from .data import macos_app_bundle, resolve_desktop_data_dir

MIN_WINDOWS_BUILD = 19045
MIN_WEBVIEW2_MAJOR = 120
MIN_DOTNET_RELEASE = 394802  # pywebview WinForms requires .NET Framework 4.6.2.
MIN_MACOS_VERSION = (13, 0)
WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW_RUNTIME_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"


def parse_version(value: Any) -> tuple[int, ...] | None:
    """Reject arbitrary registry text; accept only finite dotted version numbers."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,6}(?:\.\d{1,6}){1,3}", value.strip()):
        return None
    return tuple(int(part) for part in value.strip().split("."))


def _architecture(value: str) -> str:
    return {"amd64": "x64", "x86_64": "x64", "x64": "x64", "arm64": "arm64",
            "aarch64": "arm64", "x86": "x86", "i386": "x86", "i686": "x86"}.get(value.lower(), "unknown")


def _macos_translated() -> bool | None:
    """Apple's sysctl reports Rosetta; ENOENT means a native process on Intel."""
    try:
        function = ctypes.CDLL(None, use_errno=True).sysctlbyname
        function.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
                             ctypes.c_void_p, ctypes.c_size_t]
        function.restype = ctypes.c_int
        value = ctypes.c_int()
        size = ctypes.c_size_t(ctypes.sizeof(value))
        if function(b"sysctl.proc_translated", ctypes.byref(value), ctypes.byref(size), None, 0) != 0:
            return False if ctypes.get_errno() == errno.ENOENT else None
        return bool(value.value) if value.value in (0, 1) else None
    except (AttributeError, OSError):
        return None


def _platform_facts() -> dict[str, Any]:
    system = platform.system()
    system = system if system in {"Windows", "Linux", "Darwin"} else "Other"
    host = _architecture(platform.machine())
    process = "x86" if struct.calcsize("P") == 4 else host
    result = {"system": system, "major": 0, "minor": 0, "build": 0,
              "product_type": 0, "process_arch": process, "native_arch": host}
    if system == "Darwin":
        version = parse_version(platform.mac_ver()[0])
        translated = _macos_translated()
        result.update(major=version[0] if version else 0, minor=version[1] if version else 0,
                      patch=version[2] if version and len(version) > 2 else 0,
                      macos_version=".".join(map(str, version)) if version else None, translated=translated)
        if translated is True:
            result["native_arch"] = "arm64"
        elif process == "x64" and translated is None:
            result["native_arch"] = "unknown"
        return result
    if system != "Windows":
        return result
    version = sys.getwindowsversion()
    major, minor, build = getattr(version, "platform_version", version[:3])
    result.update(major=int(major), minor=int(minor), build=int(build),
                  product_type=int(getattr(version, "product_type", 0)))
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        fn = kernel.IsWow64Process2
        fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort), ctypes.POINTER(ctypes.c_ushort)]
        fn.restype = ctypes.c_bool
        process_machine, native_machine = ctypes.c_ushort(), ctypes.c_ushort()
        if fn(kernel.GetCurrentProcess(), ctypes.byref(process_machine), ctypes.byref(native_machine)):
            machines = {0x8664: "x64", 0xAA64: "arm64", 0x014C: "x86"}
            result["native_arch"] = machines.get(native_machine.value, "unknown")
            result["process_arch"] = machines.get(process_machine.value or native_machine.value, "unknown")
    except (AttributeError, OSError):
        # Older Windows may lack IsWow64Process2. Only accept known architecture names.
        result["native_arch"] = _architecture(os.environ.get("PROCESSOR_ARCHITEW6432", "")) if os.environ.get("PROCESSOR_ARCHITEW6432") else host
    return result


def _macos_runtime() -> dict[str, Any]:
    """Import Cocoa bridges without creating NSApplication, windows, or WebView."""
    try:
        for name in ("objc", "Foundation", "AppKit", "Quartz", "Security", "PyObjCTools.AppHelper"):
            importlib.import_module(name)
        webkit = importlib.import_module("WebKit")
        if getattr(webkit, "WKWebView", None) is None:
            return {"available": False, "error": "WKWebViewUnavailable"}
        return {"available": True, "error": ""}
    except Exception as exc:
        # Incompatible Mach-O libraries must not be reported as usable. Do not
        # include exception text, which can contain local paths or settings.
        return {"available": False, "error": type(exc).__name__}


def _registry_versions() -> dict[str, Any]:
    """Read the stable Evergreen runtime in both hives and registry views."""
    import winreg

    found: list[tuple[int, ...]] = []
    inaccessible = False
    dotnet = 0
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_ID}",
                                    0, winreg.KEY_READ | view) as key:
                    parsed = parse_version(winreg.QueryValueEx(key, "pv")[0])
                    if parsed and parsed[0] > 0:
                        found.append(parsed)
            except FileNotFoundError:
                pass
            except OSError:
                inaccessible = True
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
                                0, winreg.KEY_READ | view) as key:
                value = winreg.QueryValueEx(key, "Release")[0]
                if isinstance(value, int) and 0 < value < 10_000_000:
                    dotnet = max(dotnet, value)
        except OSError:
            pass
    return {"webview2_version": ".".join(map(str, max(found))) if found else None,
            "registry_inaccessible": inaccessible, "dotnet_release": dotnet}


def _probe_directory(path: Path) -> None:
    """Create/read/remove only a unique probe and newly created empty parents."""
    created: list[Path] = []
    probe: Path | None = None
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    try:
        for directory in reversed(missing):
            try:
                directory.mkdir()
                created.append(directory)
            except FileExistsError:
                if not directory.is_dir():
                    raise
        descriptor, name = tempfile.mkstemp(prefix=".electrochem-envcheck-", suffix=".tmp", dir=path)
        probe = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(b"ElectroChem environment probe\n")
            stream.flush()
            os.fsync(stream.fileno())
        if probe.read_bytes() != b"ElectroChem environment probe\n":
            raise OSError(errno.EIO, "Probe read-back failed")
    finally:
        try:
            if probe is not None:
                probe.unlink(missing_ok=True)
        finally:
            for directory in reversed(created):
                try:
                    directory.rmdir()
                except OSError as exc:
                    # Concurrent application data is never removed recursively.
                    if exc.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                        raise


def _check(check_id: str, label: str, label_en: str, status: str, detail: str, detail_en: str,
           remedy: str = "", remedy_en: str = "") -> dict[str, str]:
    return dict(id=check_id, label=label, label_en=label_en, status=status, detail=detail,
                detail_en=detail_en, remedy=remedy, remedy_en=remedy_en)


def _summarize(report: dict[str, Any]) -> dict[str, Any]:
    states = {check["status"] for check in report["checks"]}
    report["can_start"] = "fail" not in states
    if not report["can_start"]:
        report["can_use_embedded_window"] = False
    report["summary"] = ("环境检查未通过，请处理下列问题。" if "fail" in states else
                         "环境检查完成，有需要注意的项目。" if "warn" in states else "环境检查通过。")
    report["summary_en"] = ("Environment checks failed. Resolve the issues below." if "fail" in states else
                            "Environment checks completed with warnings." if "warn" in states else "Environment checks passed.")
    return report


def _append_macos_checks(report: dict[str, Any], facts: Mapping[str, Any]) -> None:
    checks = report["checks"]
    supported = (facts["major"], facts["minor"]) >= MIN_MACOS_VERSION
    version = facts.get("macos_version") or "unknown"
    checks.append(_check("os", "操作系统", "Operating system", "pass" if supported else "fail",
        f"macOS {version}", f"macOS {version}",
        "客户端需要 macOS 13 或更新版本；无法确定版本时请先检查系统信息。" if not supported else "",
        "The client requires macOS 13 or newer; check system information if its version is unknown." if not supported else ""))
    process, native = facts["process_arch"], facts["native_arch"]
    arch_status = "fail" if process not in {"arm64", "x64"} else "pass" if process == native else "warn"
    checks.append(_check("architecture", "运行架构", "Architecture", arch_status,
        f"程序 {process} / 本机 {native}", f"Process {process} / native {native}",
        "请使用 Apple Silicon arm64 或 Intel x64 客户端。" if arch_status == "fail" else
        "当前运行于 Rosetta 或未确认的架构；建议使用匹配本机架构的安装包，兼容运行尚未验证。" if arch_status == "warn" else "",
        "Use the Apple Silicon arm64 or Intel x64 client." if arch_status == "fail" else
        "Running under Rosetta or on an unidentified architecture; prefer the native package. Emulated operation has not been validated." if arch_status == "warn" else ""))
    runtime = _macos_runtime()
    runtime_ok = runtime["available"]
    checks.append(_check("wkwebview", "桌面浏览器组件", "Desktop browser component", "pass" if runtime_ok else "warn",
        "系统 WKWebView 与 PyObjC 桥接组件可加载。" if runtime_ok else f"WKWebView 桥接组件不可用（{runtime['error']}）。",
        "The system WKWebView and PyObjC bridges can be loaded." if runtime_ok else f"WKWebView bridge is unavailable ({runtime['error']}).",
        "下载匹配芯片的完整 macOS 应用包；源码运行请安装 macOS 依赖。暂可使用浏览器工作区。" if not runtime_ok else "",
        "Download the complete macOS app for your chip, or install the macOS requirements when running from source. Use the browser workspace in the meantime." if not runtime_ok else ""))
    report["web_engine"] = "WKWebView"
    report["webview2_version"] = None
    report["can_use_embedded_window"] = supported and arch_status != "fail" and runtime_ok


def collect_environment_report(runtime_root: Path, location: Mapping[str, str] | None = None) -> dict[str, Any]:
    facts = _platform_facts()
    checks = []
    report: dict[str, Any] = {"schema_version": 1, "app_version": APP_VERSION,
        "python_version": platform.python_version(), "distribution": "packaged" if getattr(sys, "frozen", False) else "source",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "support_policy": {"minimum_windows_build": MIN_WINDOWS_BUILD, "minimum_webview2_major": MIN_WEBVIEW2_MAJOR,
                           "desktop_architecture": "arm64 / x64" if facts["system"] == "Darwin" else "x64",
                           "minimum_macos_version": ".".join(map(str, MIN_MACOS_VERSION)),
                           "macos_architectures": ["arm64", "x64"], "minimum_versions_vm_verified": False},
        "platform": facts, "data_dir": "", "data_mode": "unknown", "checks": checks,
        "privacy_note": "仅包含版本、架构和数据目录检查；不收集密钥、配置内容、实验数据或完整环境变量。",
        "privacy_note_en": "Contains versions, architecture and data-directory checks only; no keys, configuration contents, experiment data or environment dumps."}
    if facts["system"] == "Darwin":
        _append_macos_checks(report, facts)
    else:
        windows = facts["system"] == "Windows"
        supported_os = windows and facts["major"] >= 10 and facts["build"] >= MIN_WINDOWS_BUILD
        detail = (f"Windows {facts['major']}.{facts['minor']}，内部版本 {facts['build']}" if windows else facts["system"])
        checks.append(_check("os", "操作系统", "Operating system", "pass" if supported_os else "fail", detail, detail,
            "当前客户端支持策略为 Windows 10 22H2（19045）或更新版本；其他系统请等待适配。" if not supported_os else "",
            "The current desktop policy requires Windows 10 22H2 (19045) or newer; other systems are not supported." if not supported_os else ""))
        if supported_os and facts["product_type"] != 1:
            checks[-1].update(status="warn", remedy="Windows Server 或无法确认的系统类型未做桌面适配验证。",
                             remedy_en="Windows Server or an unidentified edition has not been validated for desktop use.")
        process, native = facts["process_arch"], facts["native_arch"]
        arch_status = "fail" if process != "x64" else "pass" if native == "x64" else "warn"
        checks.append(_check("architecture", "运行架构", "Architecture", arch_status,
            f"程序 {process} / 本机 {native}", f"Process {process} / native {native}",
            "请使用 64 位 Windows 和 x64 客户端。" if arch_status == "fail" else "ARM 或未知架构上的 x64 兼容运行尚未验证。" if arch_status == "warn" else "",
            "Use 64-bit Windows and the x64 desktop client." if arch_status == "fail" else "x64 emulation on ARM or an unknown architecture has not been validated." if arch_status == "warn" else ""))
        runtime = _registry_versions() if windows else {"webview2_version": None, "registry_inaccessible": False, "dotnet_release": 0}
        version = parse_version(runtime["webview2_version"])
        runtime_ok = bool(version and version[0] >= MIN_WEBVIEW2_MAJOR)
        runtime_detail = (f"Microsoft WebView2 {runtime['webview2_version']}" if version else
                          "无法读取 WebView2 注册信息。" if runtime["registry_inaccessible"] else "未检测到稳定版 WebView2 Runtime。")
        runtime_detail_en = (runtime_detail if version else "Cannot read WebView2 registration." if runtime["registry_inaccessible"] else "Stable WebView2 Runtime was not detected.")
        checks.append(_check("webview2", "桌面浏览器组件", "Desktop browser component", "pass" if runtime_ok else "warn",
            runtime_detail, runtime_detail_en,
            f"安装或更新 Microsoft WebView2 Runtime 至 {MIN_WEBVIEW2_MAJOR} 或更新版本；本次可使用浏览器工作区。离线电脑请使用离线完整安装包。" if not runtime_ok else "",
            f"Install or update Microsoft WebView2 Runtime to {MIN_WEBVIEW2_MAJOR} or newer. Use the browser workspace in the meantime; use the complete offline installer on disconnected computers." if not runtime_ok else ""))
        net_ok = runtime["dotnet_release"] >= MIN_DOTNET_RELEASE
        checks.append(_check("dotnet", ".NET Framework", ".NET Framework", "pass" if net_ok else "warn",
            f"Release {runtime['dotnet_release']}" if net_ok else "未检测到可用的 .NET Framework 4.6.2 或更新版本。",
            f"Release {runtime['dotnet_release']}" if net_ok else ".NET Framework 4.6.2 or newer was not detected.",
            "通过 Windows 更新修复或安装 .NET Framework；本次可使用浏览器工作区。" if not net_ok else "",
            "Repair or install .NET Framework through Windows Update; use the browser workspace in the meantime." if not net_ok else ""))
        report["webview2_version"] = runtime["webview2_version"]
        report["can_use_embedded_window"] = supported_os and arch_status != "fail" and runtime_ok and net_ok
    try:
        selected = dict(location) if location is not None else resolve_desktop_data_dir(runtime_root)
        data_dir = Path(selected["path"]).expanduser().resolve()
        if facts["system"] == "Darwin" and macos_app_bundle(data_dir) is not None:
            raise ValueError("Data must be outside an application bundle")
        report["data_dir"] = str(data_dir)
        report["data_mode"] = selected["mode"] if selected["mode"] in {"user", "portable", "environment"} else "unknown"
        _probe_directory(data_dir)
        # Existing dedicated child directories can have different ACLs.
        for child in ("logs", "webview"):
            if (data_dir / child).exists():
                _probe_directory(data_dir / child)
        checks.append(_check("data_directory", "数据目录", "Data directory", "pass",
            "唯一临时文件的写入、读取和清理成功。", "Unique temporary-file write, read and cleanup succeeded."))
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        error_number = getattr(exc, "errno", None)
        code = errno.errorcode.get(error_number, type(exc).__name__) if isinstance(error_number, int) else type(exc).__name__
        checks.append(_check("data_directory", "数据目录", "Data directory", "fail",
            f"无法选择或写入数据目录（{code}）。", f"Cannot select or write the data directory ({code}).",
            "请使用 .app 应用包外的数据目录，并检查磁盘空间、账户权限与自定义目录设置。" if facts["system"] == "Darwin" else
            "检查目录是否存在、磁盘空间和当前账户权限。便携版请解压到可写目录；修正自定义数据目录或冲突的模式标记后重试。",
            "Use a data directory outside the .app bundle; check free space, permissions and custom directory settings." if facts["system"] == "Darwin" else
            "Check the directory, free disk space and account permissions. Extract the portable edition to a writable folder; correct a custom data directory or conflicting mode markers, then retry."))
    return _summarize(report)


def with_startup_failure(report: Mapping[str, Any], phase: str, error: BaseException) -> dict[str, Any]:
    """Append a safe error identifier, never an exception's potentially secret payload."""
    result = dict(report)
    result["checks"] = list(report["checks"])
    error_number = getattr(error, "errno", None)
    code = errno.errorcode.get(error_number, type(error).__name__) if isinstance(error_number, int) else type(error).__name__
    if phase == "report_export":
        result["checks"].append(_check("report_export", "诊断导出", "Diagnostic export", "fail",
            f"无法创建诊断文件（{code}）。", f"Cannot create the diagnostic file ({code}).",
            "请使用可写目录中的新文件名；不会覆盖已有文件。",
            "Choose a new filename in a writable directory; existing files are never overwritten."))
        return _summarize(result)
    label = "本地服务" if phase == "service" else "客户端启动"
    result["checks"].append(_check("startup", label, "Local service" if phase == "service" else "Desktop startup", "fail",
        f"启动未完成（{code}）。", f"Startup did not complete ({code}).",
        "重启客户端；若仍失败，请复制此诊断并检查本机端口限制、安装完整性和目录权限。",
        "Restart the client. If the problem persists, copy this report and check local port restrictions, installation integrity and directory permissions."))
    return _summarize(result)


def format_environment_report(report: Mapping[str, Any]) -> str:
    policy = (f"macOS >= {'.'.join(map(str, MIN_MACOS_VERSION))}; arm64 / x64; WKWebView + PyObjC"
              if report["platform"]["system"] == "Darwin" else
              f"Windows build >= {MIN_WINDOWS_BUILD}; x64; WebView2 >= {MIN_WEBVIEW2_MAJOR}")
    lines = [f"ElectroChem {report['app_version']} — 环境诊断 / Environment diagnostics",
             str(report["generated_at"]), str(report["summary"]), str(report["summary_en"]),
             f"Python {report['python_version']} / {report['distribution']}",
             f"数据目录 / Data directory: {report['data_dir'] or '(unresolved)'} ({report['data_mode']})",
             f"支持策略 / Support policy: {policy}",
             "最低版本尚需独立系统验收 / Minimum versions still require independent system validation.", ""]
    for check in report["checks"]:
        lines.append(f"[{check['status'].upper()}] {check['label']} / {check['label_en']}: {check['detail']}")
        if check["detail_en"] != check["detail"]:
            lines.append(f"  {check['detail_en']}")
        if check["remedy"]:
            lines.extend((f"  {check['remedy']}", f"  {check['remedy_en']}"))
    lines.extend(("", report["privacy_note"], report["privacy_note_en"]))
    return "\n".join(lines)


def _show_macos_report(report: Mapping[str, Any]) -> None:
    from .mac_native import _on_main, show_message

    appkit = importlib.import_module("AppKit")
    full_text = format_environment_report(report)
    details = "\n".join(f"[{item['status'].upper()}] {item['label']} / {item['label_en']}: {item['detail']}"
                        for item in report["checks"])
    message = f"{report['summary']}\n{report['summary_en']}\n\n{details}"
    while show_message("ElectroChem — 环境诊断 / Environment diagnostics", message,
                       ("关闭 / Close", "复制完整诊断 / Copy report"), warning=not report["can_start"]) == 1:
        def copy():
            pasteboard = appkit.NSPasteboard.generalPasteboard()
            pasteboard.clearContents()
            return bool(pasteboard.setString_forType_(full_text, appkit.NSPasteboardTypeString))
        try:
            copied = _on_main(copy)
        except Exception:
            copied = False
        message = ("已复制完整诊断。 / Full report copied." if copied else
                   "剪贴板暂不可用，请重试。 / Clipboard unavailable; try again.") + "\n\n" + details


def show_environment_report(report: Mapping[str, Any], *, parent: Any = None) -> None:
    """Use Cocoa on macOS; Tk is only a pre-Cocoa main-thread fallback."""
    if report["platform"]["system"] == "Darwin":
        try:
            _show_macos_report(report)
            return
        except Exception:
            if "AppKit" in sys.modules or threading.current_thread() is not threading.main_thread():
                # Starting a second GUI toolkit after Cocoa, or Tk from a
                # worker, is unsafe. The CLI's --output remains available.
                if sys.stderr is not None:
                    print(format_environment_report(report), file=sys.stderr)
                return
    try:
        _show_tk_report(report, parent=parent)
    except Exception:
        if report["platform"]["system"] != "Darwin":
            raise
        if sys.stderr is not None:
            print(format_environment_report(report), file=sys.stderr)


def _show_tk_report(report: Mapping[str, Any], *, parent: Any = None) -> None:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Toplevel(parent) if parent is not None else tk.Tk()
    root.title("ElectroChem — 环境诊断 / Environment diagnostics")
    root.geometry("780x560")
    root.minsize(520, 360)
    body = ttk.Frame(root, padding=16)
    body.pack(fill="both", expand=True)
    family = "Helvetica" if report["platform"]["system"] == "Darwin" else "Microsoft YaHei"
    ttk.Label(body, text=report["summary"], font=(family, 12, "bold")).pack(anchor="w", pady=(0, 10))
    area = ttk.Frame(body)
    area.pack(fill="both", expand=True)
    text = tk.Text(area, wrap="word", height=18, font=(family, 10))
    scrollbar = ttk.Scrollbar(area, command=text.yview)
    text.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)
    report_text = format_environment_report(report)
    text.insert("1.0", report_text)
    text.configure(state="disabled")
    status = ttk.Label(body, text="")
    status.pack(anchor="w")
    controls = ttk.Frame(body)
    controls.pack(fill="x", pady=(8, 0))

    def copy() -> None:
        try:
            root.clipboard_clear()
            root.clipboard_append(report_text)
            root.update()
            status.configure(text="已复制 / Copied")
        except tk.TclError:
            text.tag_add("sel", "1.0", "end-1c")
            text.focus_set()
            shortcut = "Command+C" if report["platform"]["system"] == "Darwin" else "Ctrl+C"
            status.configure(text=f"剪贴板暂不可用，已选中文本，请按 {shortcut} 重试。 / Clipboard unavailable; text selected. Retry with {shortcut}.")

    ttk.Button(controls, text="复制诊断 / Copy report", command=copy).pack(side="left")
    ttk.Button(controls, text="关闭 / Close", command=root.destroy).pack(side="right")
    if parent is None:
        root.mainloop()
    else:
        root.transient(parent)
        root.wait_window()


def run_environment_check(runtime_root: Path, *, json_output: bool = False,
                          output_path: Path | None = None, windowed: bool = False) -> int:
    report = collect_environment_report(runtime_root)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) if json_output else format_environment_report(report)
    if output_path is not None:
        # An explicit filename is required and existing reports are never overwritten.
        try:
            with Path(output_path).open("x", encoding="utf-8") as stream:
                stream.write(rendered + "\n")
        except OSError as exc:
            failure = with_startup_failure(report, "report_export", exc)
            if windowed:
                show_environment_report(failure)
            elif sys.stderr is not None:
                print(f"Cannot create diagnostic output: {type(exc).__name__}", file=sys.stderr)
            return 2
    elif windowed:
        show_environment_report(report)
    else:
        print(rendered)
    return 0 if report["can_start"] else 1
