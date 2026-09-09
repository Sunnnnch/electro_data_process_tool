"""Check smoke isolation and real synthetic payload without pretending to run Cocoa."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

from test_v6_project_templates import isolated_runtime as isolated_runtime

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("macos_native_smoke_contract", ROOT / "packaging/smoke_macos_desktop.py")
assert SPEC and SPEC.loader
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def test_native_smoke_refuses_non_macos_before_changing_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(SMOKE.sys, "platform", "win32")
    before = dict(SMOKE.os.environ)
    output = tmp_path / "never-created"
    with pytest.raises(RuntimeError, match="macOS"):
        SMOKE.run_smoke(output)
    assert not output.exists()
    assert dict(SMOKE.os.environ) == before


@pytest.mark.parametrize("existing", [False, True])
def test_native_smoke_refuses_existing_or_bundle_paths(tmp_path, existing):
    output = tmp_path / "previous" if existing else tmp_path / "ElectroChem.app" / "Contents" / "probe"
    if existing:
        output.mkdir()
        (output / "marker").write_text("preserve")
    with pytest.raises(ValueError):
        SMOKE.isolated_environment(output)
    if existing:
        assert (output / "marker").read_text() == "preserve"
    else:
        assert not output.exists()


def test_native_smoke_clears_inherited_per_file_and_webview_overrides(monkeypatch, tmp_path):
    environment = dict(SMOKE.os.environ)
    environment.update({"ELECTROCHEM_V6_HISTORY_FILE": "/original/private/history.json", "WEBVIEW2_USER_DATA_FOLDER": "/old/profile",
                        "ELECTROCHEM_V6_PORT": "8010", "ELECTROCHEM_OTHER_SECRET": "never-retain"})
    monkeypatch.setattr(SMOKE.os, "environ", environment)
    data = SMOKE.isolated_environment(tmp_path / "fresh")
    assert environment["ELECTROCHEM_V6_DATA_DIR"] == str(data)
    assert not any(name.startswith("WEBVIEW2") for name in environment)
    assert "ELECTROCHEM_OTHER_SECRET" not in environment and "ELECTROCHEM_V6_PORT" not in environment
    overrides = {name: value for name, value in environment.items() if name.startswith("ELECTROCHEM") and name.endswith("_FILE")}
    assert len(overrides) == 7
    assert all(Path(value).parent == data for value in overrides.values())
    assert environment["ELECTROCHEM_V6_KEEP_TEST_RUNTIME"] == "1"


def test_native_smoke_cv_payload_computes_real_history_and_outputs(isolated_runtime, tmp_path):
    from electrochem_v6.core.process_service import process_folder
    from electrochem_v6.core.system_service import register_allowed_dir
    from electrochem_v6.store.runtime import get_database

    data = tmp_path / "synthetic"
    data.mkdir()
    payload = SMOKE.synthetic_cv(data)
    input_path = Path(payload["input_files"][0]["path"])
    original_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
    register_allowed_dir(payload["folder_path"])
    result = process_folder(payload)
    assert result["status"] == "success", result
    records = get_database().get_all_history_records()
    assert len(records) == 1 and records[0]["type"] == "CV"
    outputs = result["result"]["processing"]["output_files"]
    paths = [Path(item["path"] if isinstance(item, dict) else item) for item in outputs]
    assert paths and any(path.suffix.lower() == ".png" for path in paths)
    assert all(path.is_file() and path.resolve().is_relative_to(data) for path in paths)
    persisted = SMOKE.verify_cv_result(result, data, input_path, original_hash)
    assert persisted["recipe_scan_rate_v_s"] == .05 and persisted["input_sha256_unchanged"]
