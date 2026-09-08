"""Reject invalid/off-policy prerequisite artifacts without installing anything."""

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def run_helper(tmp_path, code, **values):
    if os.name != "nt" or not POWERSHELL:
        pytest.skip("Windows PowerShell required")
    env = {**os.environ, "PREREQ_HELPER": str(ROOT / "packaging/installer_prerequisites.ps1")}
    env.update({f"PREREQ_{key}": str(value) for key, value in values.items()})
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
         "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
         ". $env:PREREQ_HELPER; " + code],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8-sig", timeout=30,
    )


@pytest.mark.parametrize("status,subject,valid", [
    ("Valid", "CN=Microsoft Corporation, O=Microsoft Corporation, C=US", True),
    ("NotSigned", "CN=Microsoft Corporation, O=Microsoft Corporation, C=US", False),
    ("HashMismatch", "CN=Microsoft Corporation, O=Microsoft Corporation, C=US", False),
    ("Valid", "CN=Microsoft Corporation, O=Someone Else, C=US", False),
    ("Valid", "CN=Vendor, O=Microsoft Corporation Impersonator, C=US", False),
])
def test_signature_policy(tmp_path, status, subject, valid):
    result = run_helper(tmp_path,
                        "$Signature=[pscustomobject]@{Status=$env:PREREQ_STATUS;SignerCertificate="
                        "[pscustomobject]@{Subject=$env:PREREQ_SUBJECT}}; "
                        "Assert-WebView2InstallerMetadata $Signature", STATUS=status, SUBJECT=subject)
    assert (result.returncode == 0) == valid, result.stderr


def test_real_unsigned_offline_file_is_rejected_without_execution(tmp_path):
    fixture = tmp_path / "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
    fixture.write_bytes(b"not a signed executable")
    result = run_helper(tmp_path, "Get-ValidatedWebView2Installer $env:PREREQ_PATH", PATH=fixture)
    assert result.returncode != 0
    assert "valid Microsoft Authenticode signature" in result.stderr
    assert fixture.read_bytes() == b"not a signed executable"


def test_dependency_inventory_rejects_incomplete_onedir(tmp_path):
    result = run_helper(tmp_path, "Get-InstallerDependencyInventory $env:PREREQ_PATH", PATH=tmp_path)
    assert result.returncode != 0
    assert "Missing packaged dependency: runtime-requirements.txt" in result.stderr


@pytest.fixture
def payload_reader():
    spec = importlib.util.spec_from_file_location("read_webview2_payload", ROOT / "packaging/read_webview2_payload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest(version="152.0.4191.66", *, app_id="{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", arch="X64", action="--msedgewebview"):
    filename = f"MicrosoftEdgeWebview_{arch}_{version}.exe"
    return (f'<response protocol="3.0"><app appid="{app_id}" status="ok"><updatecheck status="ok">'
            f'<manifest version="{version}"><packages><package name="{filename}" hash_sha256="{"a" * 64}"/>'
            f'</packages><actions><action run="{filename}" arguments="{action}"/></actions></manifest>'
            '</updatecheck></app></response>').encode()


def test_payload_version_comes_from_exact_webview_manifest(payload_reader):
    result = payload_reader.read_manifest_metadata(manifest())
    assert result["version"] == "152.0.4191.66"
    assert result["runtimePackage"] == "MicrosoftEdgeWebview_X64_152.0.4191.66.exe"
    assert result["versionSource"].startswith("signed-wrapper:")
    assert payload_reader.read_manifest_metadata(manifest("120.0.0.0"))["version"] == "120.0.0.0"


@pytest.mark.parametrize("payload", [
    manifest("119.0.100.1"), manifest("1.3.265.7"), manifest("152.0.bad.1"),
    manifest(app_id="{56EB18F8-B008-4CBD-B6D2-8C97FE7E9062}"),
    manifest(arch="ARM64"), manifest(action="--msedge"),
    b"MicrosoftEdgeWebview_X64_152.0.4191.66.exe", manifest() + manifest("153.0.1.2"),
])
def test_payload_identity_version_and_ambiguity_rejected(payload_reader, payload):
    with pytest.raises(ValueError):
        payload_reader.read_manifest_metadata(payload)


def test_payload_size_guard_before_pe_parsing(payload_reader, tmp_path, monkeypatch):
    source = tmp_path / "runtime.exe"
    source.write_bytes(b"")
    with pytest.raises(ValueError, match="file size"):
        payload_reader.inspect_payload(source)
    source.write_bytes(b"oversized")
    monkeypatch.setattr(payload_reader, "MAX_PAYLOAD", 4)
    with pytest.raises(ValueError, match="file size"):
        payload_reader.inspect_payload(source)


def test_offline_and_standard_output_names_are_separate():
    source = (ROOT / "packaging/installer.iss").read_text(encoding="utf-8-sig")
    assert "OutputBaseFilename=ElectroChem-Setup-{#AppVersion}-offline" in source
    assert "OutputBaseFilename=ElectroChem-Setup-{#AppVersion}\n" in source
    build = (ROOT / "packaging/build_installer.ps1").read_text(encoding="utf-8-sig")
    assert '"-offline"' in build
    assert "$InstallerPath.dependencies.json" in build
    assert '$ManifestPath.sha256' in build
    assert 'Get-FileHash -LiteralPath $ManifestPath' in build
    assert "GetSHA256OfFile" in source


def test_installer_support_policy_matches_environment_diagnostics():
    from electrochem_v6.desktop.environment import MIN_DOTNET_RELEASE, MIN_WEBVIEW2_MAJOR, MIN_WINDOWS_BUILD

    source = (ROOT / "packaging/installer.iss").read_text(encoding="utf-8-sig")
    assert f"MinVersion=10.0.{MIN_WINDOWS_BUILD}" in source
    assert f"MinimumWebView2Major = {MIN_WEBVIEW2_MAJOR};" in source
    assert MIN_DOTNET_RELEASE == 394802 and "IsDotNetInstalled(net462, 0)" in source
