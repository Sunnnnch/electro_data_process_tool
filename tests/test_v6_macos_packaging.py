"""Read real format-conversion outputs and malformed/native deployment metadata."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import struct
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
from build_macos import make_icon
from macos_support import artifact_prefix, check_macho, read_app_version, read_macho


def macho(*, cpu=0x0100000C, major=13, command_length=24) -> bytes:
    command = struct.pack("<6I", 0x32, command_length, 1, major << 16, 15 << 16, 0)
    return struct.pack("<8I", 0xFEEDFACF, cpu, 0, 2, 1, len(command), 0, 0) + command


def test_accepts_matching_thin_architecture_and_macos_13(tmp_path):
    path = tmp_path / "ElectroChem"
    path.write_bytes(macho())
    assert check_macho(path, "arm64", executable=True) == [{"architecture": "arm64", "minimum_macos": (13, 0, 0)}]
    path.write_bytes(macho(cpu=0x01000007, major=10))
    assert check_macho(path, "x86_64", executable=True)[0]["minimum_macos"] == (10, 0, 0)


@pytest.mark.parametrize("payload,arch", [(macho(major=14), "arm64"), (macho(), "x86_64"),
                                           (macho(command_length=4096), "arm64"), (macho()[:35], "arm64"),
                                           (b"not an executable", "arm64"), (b"\xce\xfa\xed\xfe", "arm64")])
def test_rejects_wrong_architecture_newer_os_or_malformed_executable(tmp_path, payload, arch):
    path = tmp_path / "candidate"
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        check_macho(path, arch, executable=True)


def test_universal_library_allowed_but_main_executable_must_be_native_thin(tmp_path):
    path = tmp_path / "library.dylib"
    first, second = macho(), macho(cpu=0x01000007, major=10)
    header = struct.pack(">II", 0xCAFEBABE, 2)
    header += struct.pack(">IIIII", 0x0100000C, 0, 48, len(first), 0)
    header += struct.pack(">IIIII", 0x01000007, 0, 48 + len(first), len(second), 0)
    path.write_bytes(header + first + second)
    assert len(check_macho(path, "arm64")) == 2
    with pytest.raises(ValueError, match="architecture"):
        check_macho(path, "arm64", executable=True)
    path.write_bytes(struct.pack(">II", 0xCAFEBABE, 0xFFFFFFFF))
    with pytest.raises(ValueError, match="slice count"):
        read_macho(path)


def test_version_and_names_follow_current_source_and_do_not_claim_universal():
    from electrochem_v6.config import APP_VERSION
    assert read_app_version(ROOT) == APP_VERSION
    assert artifact_prefix(APP_VERSION, "x86_64") == f"ElectroChem-{APP_VERSION}-macos-x64"
    assert artifact_prefix(APP_VERSION, "arm64") == f"ElectroChem-{APP_VERSION}-macos-arm64"
    with pytest.raises(ValueError):
        artifact_prefix(APP_VERSION, "universal2")


def test_icns_conversion_preserves_approved_icon_pixels(tmp_path):
    source = ROOT / "src/electrochem_v6/desktop/assets/app_icon.png"
    output = tmp_path / "icon.icns"
    original_bytes = source.read_bytes()
    make_icon(source, output)
    with Image.open(output) as converted, Image.open(source) as original:
        assert converted.format == "ICNS" and converted.size == (1024, 1024)
        expected = original.convert("RGBA")
        expected.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        assert converted.convert("RGBA").tobytes() == expected.tobytes()
    assert source.read_bytes() == original_bytes


def test_mac_launcher_import_has_no_runtime_side_effects(monkeypatch):
    for key in tuple(sys.modules):
        if key.startswith("macos_launcher_test"):
            monkeypatch.delitem(sys.modules, key)
    spec = importlib.util.spec_from_file_location("macos_launcher_test", ROOT / "packaging/electrochem_macos_launcher.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.main)


def test_build_refuses_non_native_platform_without_touching_output(tmp_path, monkeypatch):
    import build_macos
    monkeypatch.setattr(build_macos.sys, "platform", "win32")
    destination = tmp_path / "out"
    with pytest.raises(ValueError, match="native macOS"):
        build_macos.build(ROOT, destination, "arm64")
    assert not destination.exists()


def test_candidate_mcp_exercise_matches_real_source_api(tmp_path, monkeypatch):
    from verify_macos import exercise_mcp, isolated_environment

    from electrochem_v6.core import system_service
    from electrochem_v6.desktop.mcp_integration import DesktopServiceDiscovery
    from electrochem_v6.server.http_server import V6ServerManager
    from electrochem_v6.store.runtime import reset_runtime

    environment = isolated_environment(tmp_path)
    data = tmp_path / "data"
    monkeypatch.setattr(system_service, "_runtime_allowed_dirs", set())
    system_service.register_allowed_dir(str(tmp_path))
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(data))
    for key in ("PROJECTS", "HISTORY", "CONVERSATION", "TEMPLATE", "QUALITY_REPORT", "LOG", "LLM_CONFIG"):
        monkeypatch.delenv(f"ELECTROCHEM_V6_{key}_FILE", raising=False)
    reset_runtime()
    manager = V6ServerManager(port=0)
    assert manager.start()[0]
    discovery = DesktopServiceDiscovery(data, manager.port, manager.session_token)
    discovery.publish()
    try:
        result = asyncio.run(exercise_mcp(Path(sys.executable), data, tmp_path, environment,
                                         prefix_args=(str(ROOT / "packaging/electrochem_mcp_launcher.py"),)))
        assert result["read_only_handshake"] == result["synthetic_cv"] == "passed"
        assert result["record_count"] == 1 and result["data_points"] == 242
        assert result["charge_mC"] == pytest.approx(40.0)
    finally:
        discovery.close()
        runner = manager._job_manager
        manager.stop()
        if runner:
            runner._executor.shutdown(wait=True)
        reset_runtime()


@pytest.mark.parametrize("change", [{"execution_mode": "source"}, {"normal_exit": False}, {"version": "0.0.0"},
                                     {"entrypoint": "/different/app"}, {"data_dir": "/different/data"}, {"checks": []}])
def test_native_report_cannot_substitute_source_or_incomplete_run(tmp_path, change):
    from verify_macos import validate_native_smoke_report
    app = tmp_path / "ElectroChem.app"
    main = app / "Contents/MacOS/ElectroChem"
    output = tmp_path / "frozen-native-smoke"
    output.mkdir()
    path = output / "report.json"
    expected = ["owned_service", "real_wkwebview", "js_native_bridge", "dock_background_and_reopen",
                "privileged_navigation_blocked", "command_q_safe_cancel", "native_terminate_waits", "real_cv_and_normal_exit"]
    report = {"schema_version": 1, "status": "passed", "normal_exit": True, "execution_mode": "frozen", "version": "7.0.1",
              "architecture": "arm64", "entrypoint": str(main), "data_dir": str(output / "data"),
              "checks": [{"id": name, "status": "passed"} for name in expected]}
    path.write_text(json.dumps(report), encoding="utf-8")
    assert validate_native_smoke_report(path, main, "7.0.1", "arm64")["status"] == "passed"
    path.write_text(json.dumps({**report, **change}), encoding="utf-8")
    with pytest.raises(RuntimeError):
        validate_native_smoke_report(path, main, "7.0.1", "arm64")
