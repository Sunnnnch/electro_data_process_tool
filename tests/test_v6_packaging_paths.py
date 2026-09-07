"""Exercise real PowerShell guards only in disposable test directories."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
pytestmark = pytest.mark.skipif(os.name != "nt" or not POWERSHELL, reason="Windows PowerShell guards")


def run_guard(tmp_path, command, **variables):
    env = dict(os.environ)
    env.update({f"BUILD_TEST_{key}": str(value) for key, value in variables.items()})
    env["BUILD_TEST_HELPER"] = str(ROOT / "packaging/build_paths.ps1")
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
         "$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest; "
         "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
         ". $env:BUILD_TEST_HELPER; " + command],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8-sig", timeout=20,
    )


def test_build_cleanup_removes_only_the_expected_directory(tmp_path):
    target = tmp_path / "build/ElectroChemV6"
    target.mkdir(parents=True)
    (target / "owned.txt").write_text("test")
    sibling = tmp_path / "build/another-project.txt"
    sibling.write_text("keep")
    result = run_guard(tmp_path,
                       "Remove-CheckedBuildDirectory $env:BUILD_TEST_ROOT $env:BUILD_TEST_TARGET 'build\\ElectroChemV6'",
                       ROOT=tmp_path, TARGET=target)
    assert result.returncode == 0, result.stderr
    assert not target.exists()
    assert sibling.read_text() == "keep"


def test_build_cleanup_preserves_portable_data_even_inside_its_output(tmp_path):
    target = tmp_path / "dist/ElectroChem"
    data = target / "user_data"
    data.mkdir(parents=True)
    history = data / "processing_history.json"
    history.write_text('[{"record_id":"keep"}]')
    result = run_guard(tmp_path,
                       "Remove-CheckedBuildDirectory $env:BUILD_TEST_ROOT $env:BUILD_TEST_TARGET 'dist\\ElectroChem'",
                       ROOT=tmp_path, TARGET=target)
    assert result.returncode != 0
    assert "Refusing to remove portable user_data" in result.stderr
    assert history.read_text() == '[{"record_id":"keep"}]'


@pytest.mark.parametrize("target_relative", [".", "build", "build/other", "../outside"])
def test_build_cleanup_rejects_unexpected_targets_without_mutation(tmp_path, target_relative):
    root = tmp_path / "repo"
    root.mkdir()
    keep = root / "important.txt"
    keep.write_text("keep")
    result = run_guard(tmp_path,
                       "Remove-CheckedBuildDirectory $env:BUILD_TEST_ROOT $env:BUILD_TEST_TARGET 'build\\ElectroChemV6'",
                       ROOT=root, TARGET=root / target_relative)
    assert result.returncode != 0
    assert "Refusing unexpected build path" in result.stderr
    assert keep.read_text() == "keep"


@pytest.mark.parametrize("location", ["ancestor", "inside"])
def test_build_cleanup_rejects_junctions_and_preserves_destination(tmp_path, location):
    root = tmp_path / "repo"
    root.mkdir()
    destination = tmp_path / "unrelated"
    destination.mkdir()
    keep = destination / "important.txt"
    keep.write_text("keep")
    if location == "ancestor":
        link = root / "build"
    else:
        (root / "build/ElectroChemV6").mkdir(parents=True)
        link = root / "build/ElectroChemV6/link"
    result = run_guard(tmp_path,
                       "New-Item -ItemType Junction -Path $env:BUILD_TEST_LINK -Target $env:BUILD_TEST_DEST | Out-Null; "
                       "Remove-CheckedBuildDirectory $env:BUILD_TEST_ROOT $env:BUILD_TEST_TARGET 'build\\ElectroChemV6'",
                       ROOT=root, TARGET=root / "build/ElectroChemV6", LINK=link, DEST=destination)
    assert result.returncode != 0
    assert "reparse point" in result.stderr
    assert keep.read_text() == "keep"


def test_build_scripts_parse_without_execution(tmp_path):
    result = run_guard(tmp_path,
                       "$ParseErrors = $null; $ParseTokens = $null; "
                       "Get-ChildItem -LiteralPath $env:BUILD_TEST_PACKAGING -Filter '*.ps1' | ForEach-Object { "
                       "[void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$ParseTokens, [ref]$ParseErrors); "
                       "if ($ParseErrors) { throw ($ParseErrors | Out-String) } }",
                       PACKAGING=ROOT / "packaging")
    assert result.returncode == 0, result.stderr


def test_installer_prerequisites_markers_and_non_destructive_running_guard():
    installer = (ROOT / "packaging/installer.iss").read_text(encoding="utf-8-sig")
    build = (ROOT / "packaging/build_installer.ps1").read_text(encoding="utf-8-sig")
    onedir = (ROOT / "packaging/build_onedir.ps1").read_text(encoding="utf-8-sig")
    assert "AppMutex=Local\\ElectroChemV6.Desktop" in installer
    assert "CloseApplications=no" in installer
    assert "RestartApplications=no" in installer
    assert "HasRuntimeAt(HKLM32) or HasRuntimeAt(HKCU32)" in installer
    assert "#ifdef WebView2OfflineInstaller" in installer
    assert "Get-AuthenticodeSignature" in build and "O=Microsoft Corporation" in build
    assert "ELECTROCHEM_ISCC_PATH" in build and "[string]$IsccPath" in build
    assert 'Excludes: "user_data\\*,portable.marker,installed.marker"' in installer
    assert "DeleteFile(PortableMarker)" in installer
    assert "SaveStringToFile(ExpandConstant('{app}\\installed.marker')" in installer
    assert "portable.marker" in onedir
    assert "sys.version_info[:2] == (3, 12)" in onedir
    assert '"pip==25.3"' in onedir
    assert "taskkill" not in installer.lower() and "Stop-Process" not in build


@pytest.mark.parametrize("root_name", ["../outside", "dist/../src", "dist/new", "dist\\new", "src", ".", "D:\\outside", "/tmp/output"])
def test_distribution_root_rejects_arbitrary_paths_before_writing(tmp_path, root_name):
    keep = tmp_path / "important.txt"
    keep.write_text("keep")
    result = run_guard(tmp_path,
                       "Assert-DistributionRoot $env:BUILD_TEST_ROOT $env:BUILD_TEST_NAME",
                       ROOT=tmp_path, NAME=root_name)
    assert result.returncode != 0
    assert "Expected a repository distribution root" in result.stderr
    assert list(tmp_path.iterdir()) == [keep]


def test_isolated_distribution_cleanup_keeps_original_portable_data_at_its_path(tmp_path):
    original = tmp_path / "dist/ElectroChem/user_data"
    original.mkdir(parents=True)
    keep = original / "history.txt"
    keep.write_text("user history")
    staged = tmp_path / "dist_mcp_theme/ElectroChem"
    staged.mkdir(parents=True)
    (staged / "old-build.exe").write_bytes(b"stale build")
    result = run_guard(tmp_path,
                       "$Output = Assert-DistributionRoot $env:BUILD_TEST_ROOT 'dist_mcp_theme'; "
                       "Remove-CheckedBuildDirectory $env:BUILD_TEST_ROOT (Join-Path $Output 'ElectroChem') 'dist_mcp_theme\\ElectroChem'",
                       ROOT=tmp_path)
    assert result.returncode == 0, result.stderr
    assert not staged.exists()
    assert keep.read_text() == "user history"


def test_distribution_root_rejects_junction_without_touching_destination(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    destination = tmp_path / "outside"
    destination.mkdir()
    keep = destination / "history.txt"
    keep.write_text("user history")
    result = run_guard(tmp_path,
                       "New-Item -ItemType Junction -Path $env:BUILD_TEST_LINK -Target $env:BUILD_TEST_DEST | Out-Null; "
                       "Assert-DistributionRoot $env:BUILD_TEST_ROOT 'dist_mcp_theme'",
                       ROOT=root, LINK=root / "dist_mcp_theme", DEST=destination)
    assert result.returncode != 0
    assert "reparse point" in result.stderr
    assert keep.read_text() == "user history"
