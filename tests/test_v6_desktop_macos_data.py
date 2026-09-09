"""macOS storage and MCP launch locations never write inside application bundles."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from electrochem_v6.desktop import data, mcp_integration


@pytest.fixture(autouse=True)
def mac_platform(monkeypatch):
    monkeypatch.setattr(data, "_platform_system", lambda: "Darwin")
    monkeypatch.setattr(mcp_integration, "_platform_system", lambda: "Darwin")


@pytest.mark.parametrize("relative", ["", "Contents", "Contents/MacOS"])
def test_bundle_defaults_to_application_support_even_with_portable_marker(tmp_path, relative):
    bundle = tmp_path / "Applications" / "ElectroChem.app"
    runtime = bundle / relative
    runtime.mkdir(parents=True)
    (runtime / "portable.marker").touch()
    (runtime / "installed.marker").touch()
    home = tmp_path / "user"
    result = data.resolve_desktop_data_dir(runtime, environ={}, home_dir=home)
    assert result == {"path": str(home / "Library/Application Support/ElectroChem"), "mode": "user"}
    assert not home.exists() and not (runtime / "user_data").exists()
    assert data.macos_app_bundle(runtime) == bundle


def test_source_macos_default_and_explicit_external_data_remain_stable(tmp_path):
    home, root = tmp_path / "home", tmp_path / "checkout"
    location = data.resolve_desktop_data_dir(root, environ={}, home_dir=home)
    assert location["path"] == str(home / "Library/Application Support/ElectroChem")
    env = {}
    data.configure_desktop_environment(location, environ=env)
    assert data.resolve_desktop_data_dir(root, environ=env, home_dir=home) == location
    external = tmp_path / "external disk" / "实验数据"
    env[data.DATA_ENV] = str(external)
    assert data.resolve_desktop_data_dir(tmp_path / "ElectroChem.app/Contents/MacOS", environ=env) == {
        "path": str(external), "mode": "environment"}
    assert not home.exists() and not external.exists()


@pytest.mark.parametrize("relative", ["", "Contents", "Contents/MacOS/user_data"])
def test_explicit_bundle_data_is_rejected_before_environment_mutation(tmp_path, relative):
    root = tmp_path / "ElectroChem.app"
    env = {data.DATA_ENV: str(root / relative)}
    before = dict(env)
    with pytest.raises(data.DesktopDataError, match=".app"):
        data.resolve_desktop_data_dir(root, environ=env)
    with pytest.raises(data.DesktopDataError, match=".app"):
        data.configure_desktop_environment({"path": str(tmp_path / "external"), "mode": "user"}, environ=env)
    assert env == before and not root.exists()


def test_bundle_explicit_portable_flag_rejected_but_external_override_is_respected(tmp_path):
    root = tmp_path / "ElectroChem.app/Contents/MacOS"
    with pytest.raises(data.DesktopDataError, match="便携"):
        data.resolve_desktop_data_dir(root, portable=True, environ={})
    with pytest.raises(data.DesktopDataError, match="portable"):
        data.resolve_desktop_data_dir(root, portable="yes", environ={})
    external = str(tmp_path / "external")
    assert data.resolve_desktop_data_dir(root, portable=True, environ={data.DATA_ENV: external})["path"] == external


def test_symlink_cannot_hide_internal_app_data(tmp_path):
    internal = tmp_path / "ElectroChem.app/Contents/data"
    internal.mkdir(parents=True)
    link = tmp_path / "external-link"
    try:
        link.symlink_to(internal, target_is_directory=True)
    except OSError:
        pytest.skip("Symbolic links are not permitted on this host")
    with pytest.raises(data.DesktopDataError, match=".app"):
        data.resolve_desktop_data_dir(tmp_path, environ={data.DATA_ENV: str(link)})
    assert list(internal.iterdir()) == []


def test_legacy_mac_directory_is_only_offered_for_reviewed_migration(tmp_path):
    home = tmp_path / "home"
    legacy = home / ".electrochem/v6"
    legacy.mkdir(parents=True)
    original = legacy / "projects.json"
    original.write_bytes(b'{"existing":"project"}')
    unrelated = home / "Library/Application Support/llm_config.json"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b'{"other":"application"}')
    root = tmp_path / "ElectroChem.app/Contents/MacOS"
    target = data.resolve_desktop_data_dir(root, environ={}, home_dir=home)
    candidates = data.legacy_data_candidates(root, environ={}, home_dir=home)
    assert len(candidates) == 1 and candidates[0]["path"] == str(legacy)
    assert candidates[0]["requires_source_retention"] and candidates[0]["target_dir"] == target["path"]
    environment = {}
    data.configure_desktop_environment(target, environ=environment)
    assert "ELECTROCHEM_V6_LLM_CONFIG_FILE" not in environment
    assert original.read_bytes() == b'{"existing":"project"}'
    assert unrelated.read_bytes() == b'{"other":"application"}'
    assert not Path(target["path"]).exists()


@pytest.mark.parametrize("relative", ["", "Contents", "Contents/MacOS"])
def test_mcp_configuration_resolves_executable_in_macos_bundle(tmp_path, relative):
    bundle = tmp_path / "Applications with spaces" / "ElectroChem.app"
    executable = bundle / "Contents/MacOS/ElectroChem-MCP"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"stand-in only; never executed")
    executable.chmod(0o755)
    directory = tmp_path / "中文 data"
    result = mcp_integration.client_configuration(bundle / relative, directory, frozen=True, allow_write=True)
    config = result["client_config"]["mcpServers"]["electrochem"]
    assert config == {"command": str(executable), "args": ["--data-dir", str(directory), "--allow-write"]}
    assert result["available"] and not result["read_only"]
    assert "token" not in json.dumps(result) and not directory.exists()


def test_non_executable_mcp_companion_is_unavailable(tmp_path, monkeypatch):
    companion = tmp_path / "ElectroChem-MCP"
    companion.write_bytes(b"not executable")
    monkeypatch.setattr(mcp_integration.os, "access", lambda path, mode: mode != os.X_OK)
    assert not mcp_integration.client_configuration(tmp_path, tmp_path / "data", frozen=True)["available"]
