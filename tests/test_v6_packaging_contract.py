from pathlib import Path

from electrochem_v6.config import APP_NAME, APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_installer_version_is_injected_without_rewriting_source():
    installer = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8-sig")
    build = (ROOT / "packaging" / "build_installer.ps1").read_text(encoding="utf-8-sig")
    onedir = (ROOT / "packaging" / "build_onedir.ps1").read_text(encoding="utf-8-sig")

    assert '#define AppVersion "0.0.0-dev"' in installer
    assert f'#define AppVersion "{APP_VERSION}"' not in installer
    assert '"/DAppVersion=$AppVersion"' in build
    assert "Set-Content $issFile" not in onedir


def test_product_rename_keeps_upgrade_identity_and_limits_legacy_cleanup():
    installer = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8-sig")
    launcher = (ROOT / "packaging" / "electrochem_v6_launcher.py").read_text(encoding="utf-8-sig")
    spec = (ROOT / "packaging" / "electrochem_v6.spec").read_text(encoding="utf-8-sig")
    assert APP_NAME == "智能电化学数据处理软件"
    assert f'#define AppName "{APP_NAME}"' in installer
    assert 'APP_TITLE = f"ElectroChem｜{APP_NAME}"' in launcher
    assert 'AppId={{F0BB4C2E-6A85-4BB4-B2FE-4D7D56600101}' in installer
    assert 'DefaultDirName={autopf}\\ElectroChemV6' in installer
    assert '#define AppExeName "ElectroChem.exe"' in installer
    assert 'name="ElectroChem"' in spec
    assert 'AppUserModelID: "ElectroChem.Desktop"' in installer
    assert 'AppMutex=Local\\ElectroChemV6.Desktop' in installer
    assert 'UninstallDisplayName={#AppName}' in installer
    assert 'VersionInfoProductName={#AppName}' in installer
    assert 'VersionInfoDescription={#AppName}' in installer
    assert 'Tasks: desktopicon' in installer
    cleanup = installer.split("[InstallDelete]", 1)[1].split("\n[", 1)[0]
    entries = [line.strip() for line in cleanup.splitlines() if line.strip() and not line.lstrip().startswith(";")]
    # Restrict removal to known old links/executable; no wildcard or directory delete
    # can remove user data or unrelated shortcuts during an upgrade.
    assert entries == [
        'Type: files; Name: "{autoprograms}\\电化学数据处理软件.lnk"',
        'Type: files; Name: "{autodesktop}\\电化学数据处理软件.lnk"',
        'Type: files; Name: "{app}\\ElectroChemV6.exe"',
    ]


def test_official_installer_contract_requires_verified_signature_and_checksums():
    build = (ROOT / "packaging" / "build_installer.ps1").read_text(encoding="utf-8-sig")
    signing = (ROOT / "packaging" / "sign_windows_binary.ps1").read_text(encoding="utf-8-sig")
    workflows = "\n".join(
        (ROOT / path).read_text(encoding="utf-8-sig")
        for path in (".github/workflows/ci.yml", ".github/workflows/release.yml")
    )

    assert "[switch]$RequireSigning" in build
    assert "signtool" in signing.lower()
    assert "verify /pa /v" in signing
    assert "Get-FileHash" in build
    assert "-RequireSigning" in workflows
    assert "WINDOWS_SIGNING_CERT_BASE64" in workflows
    assert "Official Windows releases require WINDOWS_SIGNING_CERT_BASE64" in workflows
    assert "sign_windows_binary.ps1" in workflows
    assert "ZIP_CHECKSUM_PATH" in workflows
    assert "Required signed installer was not produced" in workflows
    assert "HAS_INSTALLER" not in workflows
    assert '"dist/ElectroChem/ElectroChem.exe"' in workflows
    assert '"ElectroChem-$ver-win64"' in workflows
    assert '"dist_installer/ElectroChem-Setup-$ver.exe"' in workflows
    assert "ElectroChemV6" not in workflows
