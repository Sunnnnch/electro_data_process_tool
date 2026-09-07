# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_submodules, copy_metadata


ROOT = Path.cwd()
PACKAGING_DIR = ROOT / "packaging"
SRC_DIR = ROOT / "src"
ICON_FILE = PACKAGING_DIR / "assets" / "app_icon.ico"
STATIC_DIR = SRC_DIR / "electrochem_v6" / "ui" / "static"
DESKTOP_ASSETS_DIR = SRC_DIR / "electrochem_v6" / "desktop" / "assets"

sys.path.insert(0, str(PACKAGING_DIR))
from windows_version import create_version_info

VERSION_INFO = create_version_info(SRC_DIR / "electrochem_v6" / "config.py")

hiddenimports = [
    "clr_loader",
    "pythonnet",
    "pystray._win32",
]
hiddenimports += collect_submodules("electrochem_v6")
hiddenimports += collect_submodules("webview")
hiddenimports += collect_submodules("clr_loader")
hiddenimports += collect_submodules("xlrd")

datas = [
    (str(STATIC_DIR), "electrochem_v6/ui/static"),
    (str(DESKTOP_ASSETS_DIR), "electrochem_v6/desktop/assets"),
]

# FastMCP uses package version metadata, JSON Schema registry resources, and
# AnyIO's runtime-selected asyncio backend. Keep these in the shared onedir.
mcp_hiddenimports = ["anyio._backends._asyncio"] + collect_submodules("mcp.server.fastmcp")
mcp_datas = copy_metadata("mcp", recursive=True)

excludes = [
    "pytest",
    "playwright",
    "IPython",
    "jupyter",
    "notebook",
    "tkinter.test",
]

a = Analysis(
    [str(PACKAGING_DIR / "electrochem_v6_launcher.py")],
    pathex=[str(ROOT), str(SRC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(PACKAGING_DIR / "runtime_data_dir_hook.py")],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ElectroChem",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=str(ICON_FILE),
    version=VERSION_INFO,
)

mcp_analysis = Analysis(
    [str(PACKAGING_DIR / "electrochem_mcp_launcher.py")],
    pathex=[str(ROOT), str(SRC_DIR)],
    binaries=[],
    datas=mcp_datas,
    hiddenimports=mcp_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

mcp_exe = EXE(
    PYZ(mcp_analysis.pure),
    mcp_analysis.scripts,
    [],
    exclude_binaries=True,
    name="ElectroChem-MCP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    argv_emulation=False,
    icon=str(ICON_FILE),
    version=create_version_info(SRC_DIR / "electrochem_v6" / "config.py", executable_name="ElectroChem-MCP.exe"),
)

coll = COLLECT(
    exe,
    mcp_exe,
    a.binaries,
    a.datas,
    mcp_analysis.binaries,
    mcp_analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ElectroChem",
)
