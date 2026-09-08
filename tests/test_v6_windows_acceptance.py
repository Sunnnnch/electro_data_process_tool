"""Read-only safety gates for the dependency-free disposable-VM runner."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "packaging/acceptance/Invoke-WindowsAcceptance.ps1"


def _powershell(code, *, value=None):
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell:
        pytest.skip("PowerShell is required for the Windows acceptance safety contract")
    environment = {**os.environ, "ACCEPTANCE_SCRIPT": str(SCRIPT), "ACCEPTANCE_FIXTURE": json.dumps(value)}
    if os.name == "nt" and Path(shell).stem.lower() == "powershell":
        # Do not import PowerShell 7 bundled modules into the 5.1 test process.
        environment["PSModulePath"] = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/Modules")
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "RemoteSigned", "-Command",
         "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; Import-Module Microsoft.PowerShell.Utility; . $env:ACCEPTANCE_SCRIPT; " + code],
        env=environment,
        capture_output=True, text=True, encoding="utf-8-sig", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.fixture
def clean_fixture():
    return {
        "plan": {"schemaVersion": 1, "runId": "11111111-2222-3333-4444-555555555555",
                 "vmUuid": "11111111-2222-3333-4444-555555555555", "computerName": "DISPOSABLE-VM",
                 "osFamily": "Windows11", "scenario": "upgrade", "target": {"version": "7.0.1"},
                 "baseline": {"version": "6.0.20"}},
        "machine": {"computerName": "DISPOSABLE-VM", "vmUuid": "11111111-2222-3333-4444-555555555555",
                    "manufacturer": "Microsoft Corporation", "model": "Virtual Machine", "build": 22631,
                    "caption": "Microsoft Windows 11 Pro", "is64Bit": True, "is64BitProcess": True,
                    "processorArchitecture": "AMD64", "administrator": True, "developmentTools": [],
                    "inRepository": False, "codexProfilePresent": False, "dataProfilePresent": False,
                    "registrations": [], "runningApplications": [], "environmentOverrides": []},
    }


def test_clean_vm_gate_accepts_matching_identity_and_real_older_version(clean_fixture):
    assert _powershell("$f=ConvertFrom-Json $env:ACCEPTANCE_FIXTURE; ConvertTo-Json -InputObject @(Get-AcceptanceBlockers $f.plan $f.machine)", value=clean_fixture) == []


@pytest.mark.parametrize("field,value,expected", [
    ("vmUuid", "99999999-2222-3333-4444-555555555555", "vm_uuid_mismatch"),
    ("computerName", "DEVELOPMENT-PC", "computer_name_mismatch"),
    ("model", "Physical workstation", "not_a_recognized_disposable_vm"),
    ("administrator", False, "requires_vm_administrator"),
    ("processorArchitecture", "ARM64", "requires_x64_windows_and_powershell"),
    ("build", 19045, "unexpected_windows_version"),
    ("developmentTools", ["C:/Python312/python.exe"], "development_machine_or_tools_detected"),
    ("inRepository", True, "development_machine_or_tools_detected"),
    ("codexProfilePresent", True, "development_machine_or_tools_detected"),
    ("dataProfilePresent", True, "existing_user_data_must_not_be_touched"),
    ("registrations", [{"location": "C:/Program Files/ElectroChemV6"}], "existing_installation_must_not_be_touched"),
    ("runningApplications", [1234], "existing_application_must_not_be_touched"),
    ("environmentOverrides", ["ELECTROCHEM_V6_DATA_DIR"], "remove_test_environment_overrides_in_vm"),
])
def test_gate_blocks_real_machine_data_and_environment_hazards(clean_fixture, field, value, expected):
    clean_fixture["machine"][field] = value
    blockers = _powershell("$f=ConvertFrom-Json $env:ACCEPTANCE_FIXTURE; ConvertTo-Json -InputObject @(Get-AcceptanceBlockers $f.plan $f.machine)", value=clean_fixture)
    assert expected in blockers


@pytest.mark.parametrize("baseline", ["7.0.1", "7.0.2"])
def test_same_or_newer_binary_cannot_be_labelled_as_old_version_upgrade(clean_fixture, baseline):
    clean_fixture["plan"]["baseline"]["version"] = baseline
    blockers = _powershell("$f=ConvertFrom-Json $env:ACCEPTANCE_FIXTURE; ConvertTo-Json -InputObject @(Get-AcceptanceBlockers $f.plan $f.machine)", value=clean_fixture)
    assert "upgrade_requires_a_genuinely_older_version" in blockers


def test_missing_baseline_keeps_available_install_test_without_claiming_upgrade(clean_fixture):
    clean_fixture["plan"]["baseline"] = None
    assert _powershell("$f=ConvertFrom-Json $env:ACCEPTANCE_FIXTURE; ConvertTo-Json -InputObject @(Get-AcceptanceBlockers $f.plan $f.machine)", value=clean_fixture) == []


def test_default_preflight_never_reaches_process_or_filesystem_mutation(clean_fixture):
    result = _powershell("""
      $script:Fixture=ConvertFrom-Json $env:ACCEPTANCE_FIXTURE;
      function Get-AcceptanceMachine { return $script:Fixture.machine }
      function Start-Process { throw 'MUTATION: process launch' }
      function New-Item { throw 'MUTATION: filesystem write' }
      function Set-ItemProperty { throw 'MUTATION: registry write' }
      Invoke-WindowsAcceptance | ConvertTo-Json -Depth 10
    """, value=clean_fixture)
    assert result["status"] == "blocked"
    assert result["blockers"] == ["manifest_required"]
    assert result["installationAttempted"] is False


@pytest.mark.parametrize("status,allowed,expected", [
    ("NotSigned", False, False), ("NotSigned", True, True),
    ("HashMismatch", True, False), ("NotTrusted", True, False),
    ("Valid", False, True),
])
def test_unsigned_opt_in_never_accepts_invalid_signature(tmp_path, status, allowed, expected):
    # Mock Windows PE/signature providers only; the real file hash is checked.
    import hashlib

    installer = tmp_path / "fixture.exe"
    installer.write_bytes(b"acceptance signature-boundary fixture")
    fixture = {"spec": {"path": str(installer), "version": "7.0.1", "executableName": "ElectroChem.exe",
                        "sha256": hashlib.sha256(installer.read_bytes()).hexdigest(), "signerThumbprint": "EXPECTED"},
               "status": status, "allowed": allowed, "directory": str(tmp_path)}
    result = _powershell("""
      $script:Fixture=ConvertFrom-Json $env:ACCEPTANCE_FIXTURE;
      function Assert-NoReparsePath { }
      function Get-Item { [pscustomobject]@{Name='fixture.exe'; VersionInfo=[pscustomobject]@{ProductVersion='7.0.1'}} }
      function Get-AuthenticodeSignature { [pscustomobject]@{Status=$script:Fixture.status; SignerCertificate=[pscustomobject]@{Thumbprint='EXPECTED'}} }
      try { $r=Read-AcceptanceArtifact $script:Fixture.spec $script:Fixture.directory $script:Fixture.allowed; @{accepted=$true; unsigned=$r.unsigned} | ConvertTo-Json }
      catch { @{accepted=$false; message=$_.Exception.Message} | ConvertTo-Json }
    """, value=fixture)
    assert result["accepted"] is expected, result
    if expected:
        assert result["unsigned"] is (status == "NotSigned")


def test_runner_keeps_explicit_execution_no_force_cleanup_and_release_limitations():
    content = SCRIPT.read_text(encoding="utf-8-sig")
    assert "if (-not $Execute -or $PreflightOnly)" in content
    assert "DISPOSABLE-VM:" in content
    assert "formalReleaseEligible = $false" in content
    assert "upgradeStatus = 'not_run'; repairStatus = 'not_run'" in content
    assert "Get-AcceptanceNativeWindow $script:OwnedProcess.Id" in content and "WaitForExit(120000)" in content
    assert "owner == processId" in content and 'StartsWith("ElectroChem"' in content
    assert "Get-NetTCPConnection -LocalPort $port -State Listen" in content
    assert "Where-Object OwningProcess -ne $ProcessId" in content
    assert "Stop-Process" not in content and "Remove-Item" not in content
    assert "RegistryKey]::OpenBaseKey" in content and ".OpenSubKey($script:AppIdKey, $false)" in content
    assert "Uninstaller signature is invalid or differs from the candidate publisher" in content


@pytest.mark.parametrize("owners,expected", [([], False), ([1234], True), ([9999], False), ([1234, 9999], False)])
def test_socket_receipt_cannot_substitute_for_exclusive_listener_ownership(owners, expected):
    result = _powershell("""
      $script:Fixture=ConvertFrom-Json $env:ACCEPTANCE_FIXTURE;
      function Get-NetTCPConnection { foreach($owner in $script:Fixture.owners) { [pscustomobject]@{LocalAddress='127.0.0.1'; OwningProcess=$owner} } }
      @{owned=(Test-AcceptanceListenerOwner 'http://127.0.0.1:8010' 1234)} | ConvertTo-Json
    """, value={"owners": owners})
    assert result["owned"] is expected


def test_shared_port_blocks_api_before_any_request():
    result = _powershell("""
      $script:OwnedProcess=[pscustomobject]@{Id=1234;HasExited=$false};
      $script:Service=[pscustomobject]@{url='http://127.0.0.1:8010'};
      function Test-AcceptanceListenerOwner { return $false }
      function Invoke-RestMethod { throw 'REQUEST_SENT' }
      try { Invoke-AcceptanceApi '/api/v1/projects'; @{blocked=$false}|ConvertTo-Json }
      catch { @{blocked=$true; message=$_.Exception.Message}|ConvertTo-Json }
    """)
    assert result["blocked"] and "No API request was sent" in result["message"]


@pytest.mark.parametrize("status,signer,unsigned,expected", [
    ("Valid", "EXPECTED", False, True), ("Valid", "OTHER", False, False),
    ("NotSigned", None, False, False), ("NotSigned", None, True, True),
    ("HashMismatch", "EXPECTED", True, False),
])
def test_installed_binary_must_match_candidate_publisher(status, signer, unsigned, expected):
    result = _powershell("""
      $script:Fixture=ConvertFrom-Json $env:ACCEPTANCE_FIXTURE;
      function Assert-NoReparsePath { }
      function Test-Path { return $true }
      function Get-Item { [pscustomobject]@{VersionInfo=[pscustomobject]@{ProductVersion='7.0.1'}} }
      function Get-FileHash { [pscustomobject]@{Hash='fixture-hash'} }
      function Get-AuthenticodeSignature { [pscustomobject]@{Status=$script:Fixture.status;SignerCertificate=[pscustomobject]@{Thumbprint=$script:Fixture.signer}} }
      try { $null=Read-AcceptanceInstalledBinary 'C:\\test\\ElectroChem.exe' $script:Fixture.artifact; @{accepted=$true}|ConvertTo-Json }
      catch { @{accepted=$false;message=$_.Exception.Message}|ConvertTo-Json }
    """, value={"status": status, "signer": signer, "artifact": {"unsigned": unsigned, "version": "7.0.1", "signer": "EXPECTED"}})
    assert result["accepted"] is expected


@pytest.mark.parametrize("change,expected", [("none", True), ("empty_sample", False), ("missing_history", False), ("changed_result", False)])
def test_upgrade_checks_real_history_identity_and_metadata(change, expected):
    result = _powershell("""
      $script:Fixture=ConvertFrom-Json $env:ACCEPTANCE_FIXTURE;
      $script:After=$false;
      function Invoke-AcceptanceApi {
        param($Route)
        if ($Route.EndsWith('/samples')) { return @{samples=@(@{data_count=$(if($script:After -and $script:Fixture.change -eq 'empty_sample'){0}else{1});data_types=@('CV')})} }
        if ($Route.Contains('?')) { return @{records=$(if($script:After -and $script:Fixture.change -eq 'missing_history'){@()}else{@(@{record_key='record-1'})})} }
        return @{record=@{record_key='record-1';project_id='proj-1';type='CV';sample_name='CV';file_path='C:\\test\\CV.txt';results=@{peak=$(if($script:After -and $script:Fixture.change -eq 'changed_result'){2}else{1})};output_files=@('C:\\test\\CV.png')}}
      }
      $before=Get-AcceptanceHistorySnapshot 'proj-1'; $script:After=$true;
      try { Assert-AcceptanceHistorySnapshot $before 'proj-1'; @{accepted=$true}|ConvertTo-Json }
      catch { @{accepted=$false;message=$_.Exception.Message}|ConvertTo-Json }
    """, value={"change": change})
    assert result["accepted"] is expected


def test_powershell_script_keeps_utf8_bom_for_chinese_paths():
    assert SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")
