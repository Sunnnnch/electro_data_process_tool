"""Only complete native-architecture macOS packages are offered as updates."""
from __future__ import annotations

import pytest

from electrochem_v6.desktop import environment, updates
from test_v6_desktop_updates import check, release


def mac_release(*, version="7.0.2", architectures=("arm64", "x64"), extensions=("dmg",)):
    raw = release("v" + version)
    for architecture in architectures:
        for extension in extensions:
            name = f"ElectroChem-{version}-macos-{architecture}.{extension}"
            raw["assets"].extend({"name": item, "state": "uploaded", "size": size,
                                  "browser_download_url": f"{updates.RELEASES_URL}/download/v{version}/{item}"}
                                 for item, size in ((name, 10000), (name + ".sha256", 100)))
    return raw


@pytest.fixture(autouse=True)
def mac_platform(monkeypatch):
    monkeypatch.setattr(updates, "_platform_system", lambda: "Darwin")
    monkeypatch.setattr(environment, "_platform_facts", lambda: {"native_arch": "arm64", "process_arch": "arm64"})


@pytest.mark.parametrize("architecture", ["arm64", "x64"])
def test_update_selects_native_mac_package_and_prefers_dmg(monkeypatch, architecture):
    monkeypatch.setattr(environment, "_platform_facts", lambda: {"native_arch": architecture})
    result, transport = check([mac_release(extensions=("zip", "dmg"))], "7.0.1")
    assert result["state"] == "update_available"
    assert result["installer_name"] == f"ElectroChem-7.0.2-macos-{architecture}.dmg"
    assert result["release_url"] == updates.RELEASES_URL and len(transport.calls) == 1
    assert "browser_download_url" not in result and "signature_verified" not in result


def test_rosetta_update_offers_arm64_native_instead_of_current_x64_process(monkeypatch):
    monkeypatch.setattr(environment, "_platform_facts", lambda: {
        "native_arch": "arm64", "process_arch": "x64", "translated": True})
    result, _ = check([mac_release()], "7.0.1")
    assert result["installer_name"] == "ElectroChem-7.0.2-macos-arm64.dmg"


def test_zip_is_available_when_matching_dmg_checksum_is_missing():
    raw = mac_release(extensions=("dmg", "zip"))
    raw["assets"] = [a for a in raw["assets"] if a["name"] != "ElectroChem-7.0.2-macos-arm64.dmg.sha256"]
    result, _ = check([raw], "7.0.1")
    assert result["installer_name"] == "ElectroChem-7.0.2-macos-arm64.zip"


def test_other_architecture_or_windows_assets_cannot_complete_mac_release():
    for raw in (release("v7.0.2"), mac_release(architectures=("x64",))):
        result, _ = check([raw], "7.0.1")
        assert result["state"] == "no_release" and not result["update_available"]
        assert "macOS arm64" in result["message"]


def test_unknown_host_architecture_never_guesses_a_package(monkeypatch):
    monkeypatch.setattr(environment, "_platform_facts", lambda: {"native_arch": "unknown"})
    result, _ = check([mac_release()], "7.0.1")
    assert result["state"] == "no_release" and result["installer_name"] is None


def test_latest_release_must_include_native_package_and_matching_checksum():
    result, _ = check([mac_release(version="7.0.3", architectures=("x64",)), mac_release()], "7.0.1")
    assert result["latest_version"] == "7.0.2"


def test_mac_asset_origin_validation_remains_strict():
    raw = mac_release()
    raw["assets"][-1]["browser_download_url"] = "https://github.com/other/repo/releases/download/v7.0.2/fake.sha256"
    result, _ = check([raw], "7.0.1")
    assert result["state"] == "invalid_response" and not result["update_available"]
