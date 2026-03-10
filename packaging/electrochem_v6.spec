# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


ROOT = Path.cwd()
PACKAGING_DIR = ROOT / "packaging"
SRC_DIR = ROOT / "src"
ICON_FILE = PACKAGING_DIR / "assets" / "app_icon.ico"
STATIC_DIR = SRC_DIR / "electrochem_v6" / "ui" / "static"

hiddenimports = [
    "processing_core",
]
hiddenimports += collect_submodules("electrochem_v6")
hiddenimports += collect_submodules("webview")

datas = [
    (str(STATIC_DIR), "electrochem_v6/ui/static"),
]

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
    name="ElectroChemV6",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=str(ICON_FILE),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ElectroChemV6",
)
