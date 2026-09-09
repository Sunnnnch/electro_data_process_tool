# -*- mode: python ; coding: utf-8 -*-
import os
import platform
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(ROOT / "packaging"))
sys.path.insert(0, str(SRC))
from macos_support import read_app_version

ARCH = os.environ.get("ELECTROCHEM_MACOS_ARCH", "")
if sys.platform != "darwin" or ARCH not in {"arm64", "x86_64"} or platform.machine() != ARCH:
    raise SystemExit("Build each macOS architecture with its native Python; cross/universal builds are unsupported.")
VERSION = read_app_version(ROOT)
ICON = os.environ["ELECTROCHEM_MACOS_ICON"]
EXCLUDES = ["pytest", "playwright", "IPython", "jupyter", "notebook", "tkinter.test",
            "clr", "clr_loader", "pythonnet", "webview.platforms.winforms", "webview.platforms.edgechromium",
            "webview.platforms.cef", "webview.platforms.qt", "webview.platforms.gtk", "webview.platforms.android",
            "pystray._win32", "pystray._xorg", "pystray._gtk", "pystray._appindicator",
            "PyQt5", "PyQt6", "PySide2", "PySide6", "gi"]
DATAS = [(str(SRC / "electrochem_v6/ui/static"), "electrochem_v6/ui/static"),
         (str(SRC / "electrochem_v6/desktop/assets"), "electrochem_v6/desktop/assets")]
HIDDEN = collect_submodules("electrochem_v6") + collect_submodules("xlrd")
HIDDEN += ["webview.platforms.cocoa", "pystray._darwin", "objc", "AppKit", "Foundation", "WebKit", "Security", "Quartz", "PyObjCTools.AppHelper", "smoke_macos_desktop"]
a = Analysis([str(ROOT / "packaging/electrochem_macos_launcher.py")], pathex=[str(ROOT), str(SRC), str(ROOT / "packaging")],
             datas=DATAS, binaries=[], hiddenimports=HIDDEN, hookspath=[], hooksconfig={},
             runtime_hooks=[str(ROOT / "packaging/runtime_macos_hook.py")], excludes=EXCLUDES, noarchive=False)
exe = EXE(PYZ(a.pure), a.scripts, [], exclude_binaries=True, name="ElectroChem", console=False,
          debug=False, strip=False, upx=False, argv_emulation=False, target_arch=ARCH, codesign_identity=None)
m = Analysis([str(ROOT / "packaging/electrochem_mcp_launcher.py")], pathex=[str(ROOT), str(SRC)], binaries=[],
             datas=copy_metadata("mcp", recursive=True),
             hiddenimports=["anyio._backends._asyncio"] + collect_submodules("mcp.server.fastmcp"),
             hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=EXCLUDES, noarchive=False)
mcp = EXE(PYZ(m.pure), m.scripts, [], exclude_binaries=True, name="ElectroChem-MCP", console=True,
          debug=False, strip=False, upx=False, argv_emulation=False, target_arch=ARCH, codesign_identity=None)
collection = COLLECT(exe, mcp, a.binaries, a.datas, m.binaries, m.datas, strip=False, upx=False, name="ElectroChem")
app = BUNDLE(collection, name="ElectroChem.app", icon=ICON, bundle_identifier="org.electrochem.desktop",
             version=VERSION, info_plist={"CFBundleDisplayName": "ElectroChem", "CFBundleShortVersionString": VERSION,
                 "CFBundleVersion": VERSION, "LSMinimumSystemVersion": "13.0", "NSHighResolutionCapable": True,
                 "NSRequiresAquaSystemAppearance": False,
                 "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True}})
