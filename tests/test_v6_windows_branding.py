"""Validate public Windows names and real PE resources without installing an app."""

import json
import os
import runpy
import shutil
import subprocess
from pathlib import Path

import pytest

from electrochem_v6.config import APP_NAME, APP_VERSION

ROOT = Path(__file__).resolve().parents[1]
BRANDING = runpy.run_path(str(ROOT / "packaging/windows_version.py"))["branding_metadata"]
PACK_PYTHON = ROOT / "packaging/.venv-pack/Scripts/python.exe"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
ISCC = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Inno Setup 6/ISCC.exe"


def test_resource_metadata_uses_product_name_and_separate_version():
    metadata = BRANDING(ROOT / "src/electrochem_v6/config.py")
    assert metadata["strings"]["ProductName"] == APP_NAME
    assert metadata["strings"]["FileDescription"] == APP_NAME
    assert metadata["strings"]["OriginalFilename"] == "ElectroChem.exe"
    assert metadata["strings"]["ProductVersion"] == APP_VERSION
    assert "V6" not in metadata["strings"]["ProductName"]


def test_resource_metadata_reads_constants_without_importing_configuration(tmp_path):
    config = tmp_path / "config.py"
    config.write_text("APP_NAME = 'Test app'\nAPP_VERSION = '7.1.2-rc.1'\nraise RuntimeError('must not execute')", encoding="utf-8")
    metadata = BRANDING(config)
    assert metadata["file_version"] == (7, 1, 2, 0)
    assert metadata["prerelease"] is True


@pytest.mark.parametrize("version", ["not-a-version", "6.0", "6.0.70000"])
def test_resource_metadata_rejects_invalid_windows_versions(tmp_path, version):
    config = tmp_path / "config.py"
    config.write_text(f"APP_NAME = 'Test app'\nAPP_VERSION = {version!r}", encoding="utf-8")
    with pytest.raises(ValueError):
        BRANDING(config)


@pytest.mark.skipif(os.name != "nt" or not PACK_PYTHON.exists() or not POWERSHELL, reason="Windows packaging environment required")
@pytest.mark.parametrize("executable_name", ["ElectroChem.exe", "ElectroChem-MCP.exe"])
def test_real_windows_file_properties_match_branding(tmp_path, executable_name):
    # Only copy the PyInstaller bootloader and edit its PE resource. Never execute
    # it, build the application, or write installation/registry state.
    executable = tmp_path / executable_name
    script = """
import pathlib,shutil,sys
import PyInstaller
from PyInstaller.utils.win32.versioninfo import write_version_info_to_executable
sys.path.insert(0, sys.argv[1])
from windows_version import create_version_info
bootloader=pathlib.Path(PyInstaller.__file__).parent/'bootloader/Windows-64bit-intel/runw.exe'
shutil.copyfile(bootloader,sys.argv[3])
write_version_info_to_executable(sys.argv[3],create_version_info(pathlib.Path(sys.argv[2]),executable_name=pathlib.Path(sys.argv[3]).name))
"""
    result = subprocess.run([str(PACK_PYTHON), "-I", "-c", script, str(ROOT / "packaging"),
                             str(ROOT / "src/electrochem_v6/config.py"), str(executable)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
                             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                             "(Get-Item -LiteralPath $env:BRANDING_TEST_EXE).VersionInfo | "
                             "Select-Object ProductName,FileDescription,ProductVersion,OriginalFilename | ConvertTo-Json -Compress"],
                            env={**os.environ, "BRANDING_TEST_EXE": str(executable)},
                            capture_output=True, text=True, encoding="utf-8-sig", timeout=20)
    assert result.returncode == 0, result.stderr
    properties = json.loads(result.stdout)
    description = APP_NAME if executable_name == "ElectroChem.exe" else f"{APP_NAME} MCP"
    assert properties == {"ProductName": APP_NAME, "FileDescription": description,
                          "ProductVersion": APP_VERSION, "OriginalFilename": executable_name}


@pytest.mark.parametrize("offline", [False, True])
@pytest.mark.skipif(os.name != "nt" or not ISCC.exists(), reason="Inno compiler required")
def test_installer_upgrade_script_compiles_without_installing(tmp_path, offline):
    source_dir = tmp_path / "input"
    source_dir.mkdir()
    fixture = source_dir / "sample.bin"
    fixture.write_text("compile-only fixture", encoding="utf-8")
    source = (ROOT / "packaging/installer.iss").read_text(encoding="utf-8-sig")
    source = source.replace(r"assets\app_icon.ico", str(ROOT / "packaging/assets/app_icon.ico"))
    source = source.replace(r"OutputDir=..\dist_installer", f"OutputDir={tmp_path / 'output'}")
    script = tmp_path / "installer.iss"
    script.write_text(source, encoding="utf-8-sig")
    command = [str(ISCC), "/O-", "/Q", f"/DAppVersion={APP_VERSION}", f"/DAppSourceDir={source_dir}"]
    if offline:
        command.append(f"/DWebView2OfflineInstaller={fixture}")
    result = subprocess.run([*command, str(script)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.rglob("*.exe"))
