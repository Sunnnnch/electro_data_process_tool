"""Exercise signing policy and real Inno callbacks without creating certificates."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
ISCC = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Inno Setup 6/ISCC.exe"
pytestmark = pytest.mark.skipif(os.name != "nt" or not POWERSHELL, reason="Windows signing workflow")


def signing_command(tmp_path, code, **variables):
    env = {**os.environ, "SIGNING_HELPER": str(ROOT / "packaging/windows_signing.ps1"),
           "SIGNING_SCRIPT": str(ROOT / "packaging/sign_windows_binary.ps1"),
           "ELECTROCHEM_SIGN_CERT_SHA1": "", "ELECTROCHEM_SIGNTOOL_PATH": ""}
    env.update({f"SIGNING_{key}": str(value) for key, value in variables.items()})
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
         "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
         ". $env:SIGNING_HELPER; " + code],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8-sig", timeout=30,
    )


@pytest.mark.parametrize("required", [False, True])
def test_no_certificate_never_mutates_binary(tmp_path, required):
    target = tmp_path / "unsigned.exe"
    original = b"not an executable; must not be changed"
    target.write_bytes(original)
    code = "& $env:SIGNING_SCRIPT -Path $env:SIGNING_TARGET"
    if required:
        code += " -RequireSigning"
    result = signing_command(tmp_path, code, TARGET=target)
    assert (result.returncode != 0) == required, result.stderr
    assert target.read_bytes() == original
    if required:
        assert "Signing is required" in result.stderr


@pytest.mark.parametrize("status,thumbprint,accepted", [
    ("Valid", "A" * 40, True), ("NotSigned", "A" * 40, False),
    ("HashMismatch", "A" * 40, False), ("Valid", "B" * 40, False),
])
def test_verified_signature_must_match_selected_publisher(tmp_path, status, thumbprint, accepted):
    result = signing_command(tmp_path,
                             "$Signature=[pscustomobject]@{Status=$env:SIGNING_STATUS;SignerCertificate="
                             "[pscustomobject]@{Thumbprint=$env:SIGNING_THUMBPRINT}}; "
                             "Assert-PublisherSignature $Signature ('A'*40)",
                             STATUS=status, THUMBPRINT=thumbprint)
    assert (result.returncode == 0) == accepted, result.stderr


def test_explicit_signtool_path_wins_and_unsigned_tool_is_rejected(tmp_path):
    tool = tmp_path / "signtool.exe"
    tool.write_bytes(b"not Microsoft SignTool")
    result = signing_command(tmp_path,
                             "$env:ELECTROCHEM_SIGNTOOL_PATH=$env:SIGNING_TOOL; "
                             "Get-VerifiedSignTool $env:SIGNING_MISSING", TOOL=tool, MISSING=tmp_path / "missing.exe")
    assert result.returncode != 0 and "does not exist" in result.stderr
    result = signing_command(tmp_path, "$env:ELECTROCHEM_SIGNTOOL_PATH=$env:SIGNING_TOOL; Get-VerifiedSignTool", TOOL=tool)
    assert result.returncode != 0 and "valid Microsoft Authenticode signature" in result.stderr
    assert tool.read_bytes() == b"not Microsoft SignTool"


def test_signing_receipt_identifies_and_hashes_verified_uninstaller(tmp_path):
    target = tmp_path / "uninst.e32.tmp"
    target.write_bytes(b"unit test payload, never executed or represented as actually signed")
    result = signing_command(tmp_path,
                             "$Signature=[pscustomobject]@{Status='Valid';SignerCertificate="
                             "[pscustomobject]@{Thumbprint=('A'*40);Subject='Test-only metadata'}}; "
                             "Write-PublisherSigningReceipt $env:SIGNING_TARGET $env:SIGNING_DIR $Signature",
                             TARGET=target, DIR=tmp_path)
    assert result.returncode == 0, result.stderr
    receipts = list(tmp_path.glob("uninstaller-*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8-sig"))
    assert receipt["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert receipt["role"] == "uninstaller" and receipt["filename"] == target.name


@pytest.mark.skipif(not ISCC.exists(), reason="Inno compiler required")
def test_real_inno_uninstaller_callback_preserves_literal_paths_and_propagates_failure(tmp_path):
    # Spaces, dollar placeholders, semicolon, ampersand and apostrophe must stay
    # literal through Python argv -> ISCC substitution -> PowerShell -File.
    folder = tmp_path / "sign $f $q &' literal; path"
    folder.mkdir()
    receipt_dir = folder / "receipts $f"
    receipt_dir.mkdir()
    callback = folder / "callback $q.ps1"
    callback.write_text(
        "param([string]$Path,[switch]$RequireSigning,[string]$ReceiptDirectory,[string]$SignToolPath)\n"
        "@{target=$Path;required=[bool]$RequireSigning;receipts=$ReceiptDirectory;tool=$SignToolPath} | "
        "ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'received.json') -Encoding utf8\n"
        "exit 37\n", encoding="utf-8-sig",
    )
    placeholder_tool = folder / "signtool.exe"
    command = signing_command(tmp_path,
                              "New-InnoPublisherSignCommand $env:SIGNING_HOST $env:SIGNING_CALLBACK "
                              "$env:SIGNING_RECEIPTS $env:SIGNING_TOOL | ConvertTo-Json -Compress",
                              HOST=POWERSHELL, CALLBACK=callback, RECEIPTS=receipt_dir, TOOL=placeholder_tool)
    assert command.returncode == 0, command.stderr
    sign_template = json.loads(command.stdout)
    assert "-File" in sign_template and "-Command" not in sign_template and "cmd.exe" not in sign_template
    source_dir = folder / "input"
    source_dir.mkdir()
    (source_dir / "sample.bin").write_bytes(b"compile-only data")
    source = (ROOT / "packaging/installer.iss").read_text(encoding="utf-8-sig")
    source = source.replace(r"assets\app_icon.ico", str(ROOT / "packaging/assets/app_icon.ico"))
    script = folder / "installer.iss"
    script.write_text(source, encoding="utf-8-sig")
    result = subprocess.run(
        [str(ISCC), "/Q", "/DAppVersion=7.0.1", "/DPublisherSigning", f"/DAppSourceDir={source_dir}",
         f"/O{folder / 'output'}", f"/Selectrochem_publisher={sign_template}", str(script)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert "0x25" in result.stderr  # callback exit 37 must stop compilation
    receipt = json.loads((folder / "received.json").read_text(encoding="utf-8-sig"))
    assert Path(receipt["target"]).name == "uninst.e32.tmp"
    assert receipt["required"] is True
    assert receipt["receipts"] == str(receipt_dir)
    assert receipt["tool"] == str(placeholder_tool)
    assert not list((folder / "output").glob("ElectroChem-Setup-*.exe"))
