"""Windows version resources from the canonical product name and version.

Read constants with AST instead of importing application configuration during a
build. PyInstaller is imported only when creating the Windows resource object.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


def branding_metadata(config_path: Path, *, executable_name: str = "ElectroChem.exe") -> dict:
    if executable_name not in {"ElectroChem.exe", "ElectroChem-MCP.exe"}:
        raise ValueError("Unknown ElectroChem executable")
    values = {}
    for statement in ast.parse(config_path.read_text(encoding="utf-8-sig")).body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            if isinstance(target, ast.Name) and target.id in {"APP_NAME", "APP_VERSION"}:
                values[target.id] = ast.literal_eval(statement.value)
    name, version = values.get("APP_NAME"), values.get("APP_VERSION")
    if not isinstance(name, str) or not name.strip() or not isinstance(version, str):
        raise ValueError("APP_NAME and APP_VERSION must be nonempty string constants")
    match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?", version)
    if not match:
        raise ValueError("APP_VERSION must be a semantic version")
    components = tuple(int(match[index]) for index in (1, 2, 3)) + (0,)
    if any(number > 65535 for number in components):
        raise ValueError("Windows version components must fit in 16 bits")
    return {
        "file_version": components,
        "prerelease": bool(match[4]),
        "strings": {
            "CompanyName": "Sun",
            "FileDescription": name if executable_name == "ElectroChem.exe" else f"{name} MCP",
            "FileVersion": version,
            "InternalName": Path(executable_name).stem,
            "OriginalFilename": executable_name,
            "ProductName": name,
            "ProductVersion": version,
        },
    }


def create_version_info(config_path: Path, *, executable_name: str = "ElectroChem.exe"):
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    metadata = branding_metadata(config_path, executable_name=executable_name)
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=metadata["file_version"], prodvers=metadata["file_version"],
            mask=0x3F, flags=0x2 if metadata["prerelease"] else 0,
            OS=0x40004, fileType=0x1, subtype=0, date=(0, 0),
        ),
        kids=[
            StringFileInfo([StringTable("080404B0", [StringStruct(key, value) for key, value in metadata["strings"].items()])]),
            VarFileInfo([VarStruct("Translation", [0x0804, 1200])]),
        ],
    )
