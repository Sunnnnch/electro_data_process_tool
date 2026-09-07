"""Desktop storage and migration tests operate only on isolated temporary roots."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from electrochem_v6.desktop import data


def _write(path: Path, value: str = "original") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan(source: Path, target: Path):
    return data.inspect_data_migration(source, target, confirm_source_stopped=True)


def _migrate(source: Path, target: Path):
    plan = _plan(source, target)
    assert plan["can_migrate"], plan
    return data.migrate_desktop_data(source, target, expected_plan_id=plan["plan_id"], confirm_source_stopped=True)


def test_source_and_installed_modes_keep_existing_user_root_without_writes(tmp_path):
    runtime, home = tmp_path / "application", tmp_path / "home"
    source = data.resolve_desktop_data_dir(runtime, environ={}, home_dir=home)
    assert source == {"path": str(home / ".electrochem" / "v6"), "mode": "user"}
    assert not runtime.exists() and not home.exists()
    _write(runtime / "installed.marker", "installed")
    _write(runtime / "user_data" / "old.json", "legacy")
    assert data.resolve_desktop_data_dir(runtime, environ={}, home_dir=home) == source
    assert (runtime / "user_data" / "old.json").read_text() == "legacy"


def test_portable_requires_marker_and_environment_always_wins(tmp_path):
    runtime = tmp_path / "application"
    _write(runtime / "portable.marker", "portable")
    assert data.resolve_desktop_data_dir(runtime, environ={}) == {"path": str(runtime / "user_data"), "mode": "portable"}
    assert data.resolve_desktop_data_dir(runtime, portable=False, environ={}, home_dir=tmp_path)["mode"] == "user"
    _write(runtime / "installed.marker", "installed")
    with pytest.raises(data.DesktopDataError, match="同时存在"):
        data.resolve_desktop_data_dir(runtime, environ={})
    external = tmp_path / "explicit"
    assert data.resolve_desktop_data_dir(runtime, environ={data.DATA_ENV: str(external)}) == {"path": str(external), "mode": "environment"}


def test_environment_preserves_user_llm_configuration_and_explicit_overrides(tmp_path):
    home = tmp_path / "home"
    old_llm = _write(home / ".electrochem" / "llm_config.json", '{"models":{}}')
    location = data.resolve_desktop_data_dir(tmp_path / "app", environ={}, home_dir=home)
    environment = {"ELECTROCHEM_V6_HISTORY_FILE": "existing-history.json"}
    data.configure_desktop_environment(location, environ=environment)
    assert environment[data.DATA_ENV] == location["path"]
    assert environment["ELECTROCHEM_V6_LLM_CONFIG_FILE"] == str(old_llm)
    assert environment["ELECTROCHEM_V6_HISTORY_FILE"] == "existing-history.json"
    explicit = {"ELECTROCHEM_V6_LLM_CONFIG_FILE": "explicit.json"}
    data.configure_desktop_environment(location, environ=explicit)
    assert explicit["ELECTROCHEM_V6_LLM_CONFIG_FILE"] == "explicit.json"
    _write(Path(location["path"]) / "llm_config.json", "migrated")
    environment = {}
    data.configure_desktop_environment(location, environ=environment)
    assert "ELECTROCHEM_V6_LLM_CONFIG_FILE" not in environment


def test_repeated_hook_resolution_retains_mode_but_honors_changed_external_directory(tmp_path):
    root, home = tmp_path / "app", tmp_path / "home"
    environment = {}
    original = data.resolve_desktop_data_dir(root, environ=environment, home_dir=home)
    data.configure_desktop_environment(original, environ=environment)
    assert data.resolve_desktop_data_dir(root, environ=environment, home_dir=home) == original
    _write(root / "portable.marker")
    environment = {}
    portable = data.resolve_desktop_data_dir(root, environ=environment, home_dir=home)
    data.configure_desktop_environment(portable, environ=environment)
    assert data.resolve_desktop_data_dir(root, environ=environment, home_dir=home) == portable
    environment[data.DATA_ENV] = str(tmp_path / "override")
    assert data.resolve_desktop_data_dir(root, environ=environment, home_dir=home)["mode"] == "environment"


def test_configuration_after_migration_prefers_new_file_only_over_internal_fallback(tmp_path):
    home = tmp_path / "home"
    old_llm = _write(home / ".electrochem" / "llm_config.json", "{}")
    location = data.resolve_desktop_data_dir(tmp_path / "app", environ={}, home_dir=home)
    environment = {}
    data.configure_desktop_environment(location, environ=environment)
    assert environment["ELECTROCHEM_V6_LLM_CONFIG_FILE"] == str(old_llm)
    _write(Path(location["path"]) / "llm_config.json", '{"migrated":true}')
    data.configure_desktop_environment(location, environ=environment)
    assert "ELECTROCHEM_V6_LLM_CONFIG_FILE" not in environment
    environment["ELECTROCHEM_V6_LLM_CONFIG_FILE"] = "user-selected.json"
    data.configure_desktop_environment(location, environ=environment)
    assert environment["ELECTROCHEM_V6_LLM_CONFIG_FILE"] == "user-selected.json"


def test_discovery_ignores_desktop_metadata_and_does_not_move_legacy_data(tmp_path):
    root, target = tmp_path / "app", tmp_path / "user"
    source = root / "user_data"
    _write(source / "desktop-state.json", "{}")
    _write(source / data.INSTANCE_LOCK, "0")
    assert data.legacy_data_candidates(root, target_dir=target) == []
    original = _write(source / "llm_config.json", '{"models":{}}')
    candidates = data.legacy_data_candidates(root, target_dir=target)
    assert len(candidates) == 1 and candidates[0]["path"] == str(source)
    assert candidates[0]["requires_source_retention"]
    assert original.exists() and not target.exists()


def test_discovery_only_stats_and_short_circuits_without_hashing(tmp_path, monkeypatch):
    root, target = tmp_path / "app", tmp_path / "user"
    source = root / "user_data"
    _write(source / "desktop-state.json", "{}")
    config = _write(source / "llm_config.json", '{"models":{}}')
    profile = _write(source / "webviewprofile" / "Cache" / "large-entry", "cached content")
    artifact = _write(source / "managed" / "outputs" / "plot.svg", "<svg/>")

    def no_hash(_path):
        pytest.fail("Startup/candidate discovery must not hash file contents")

    monkeypatch.setattr(data, "_hash_file", no_hash)
    original_scandir = data.os.scandir

    def no_profile_scan(path):
        assert Path(path) != source / "webviewprofile", "Existence discovery must stop at the root config file"
        return original_scandir(path)

    with monkeypatch.context() as local:
        local.setattr(data.os, "scandir", no_profile_scan)
        assert data.has_desktop_data(source)
    candidate, = data.legacy_data_candidates(root, target_dir=target)
    assert candidate["file_count"] == 3
    assert candidate["size_bytes"] == sum(path.stat().st_size for path in (config, profile, artifact))
    assert not candidate["issues"]
    config.unlink()
    profile.unlink()
    assert data.has_desktop_data(source)  # Nested managed output is data without a DB/config.
    assert not data.has_desktop_data(target)
    assert not target.exists()


def test_unknown_owner_requires_explicit_confirmation_and_live_pid_cannot_be_overridden(tmp_path):
    source, target = tmp_path / "old", tmp_path / "new"
    _write(source / "projects.json", "{}")
    unknown = data.inspect_data_migration(source, target)
    assert unknown["requires_source_confirmation"] and not unknown["can_migrate"]
    assert _plan(source, target)["can_migrate"]
    _write(source / "runtime_info.json", json.dumps({"pid": os.getpid()}))
    live = _plan(source, target)
    assert live["source_state"] == "alive" and not live["can_migrate"]
    with pytest.raises(data.DesktopDataError, match="活跃进程"):
        data.migrate_desktop_data(source, target, expected_plan_id=live["plan_id"], confirm_source_stopped=True)


def test_owned_queued_job_blocks_even_without_runtime_metadata(tmp_path):
    from electrochem_v6.core.process_owner import current_process_owner

    source, target = tmp_path / "old", tmp_path / "new"
    source.mkdir()
    with closing(sqlite3.connect(source / "electrochem_v6.db")) as connection:
        connection.execute("CREATE TABLE processing_recovery(job_id TEXT,owner TEXT,state TEXT)")
        connection.execute("INSERT INTO processing_recovery VALUES (?,?,?)", ("queued", json.dumps(current_process_owner()), "queued"))
        connection.commit()
    plan = _plan(source, target)
    assert plan["source_state"] == "alive" and not plan["can_migrate"]


def test_plan_requires_fresh_content_and_never_overwrites_target(tmp_path):
    source, target = tmp_path / "old", tmp_path / "new"
    original = _write(source / "projects.json", "{}")
    plan = _plan(source, target)
    original.write_text('{"changed":true}')
    with pytest.raises(data.DesktopDataError, match="预检后发生变化"):
        data.migrate_desktop_data(source, target, expected_plan_id=plan["plan_id"], confirm_source_stopped=True)
    conflict = _write(target / "projects.json", "keep me")
    assert not _plan(source, target)["can_migrate"]
    assert conflict.read_text() == "keep me"


@pytest.mark.parametrize("overlap", ["same", "nested_target", "nested_source"])
def test_migration_rejects_overlapping_directories(tmp_path, overlap):
    source = tmp_path / "old"
    _write(source / "projects.json", "{}")
    target = source if overlap == "same" else source / "child" if overlap == "nested_target" else tmp_path
    assert not _plan(source, target)["can_migrate"]
    with pytest.raises(data.DesktopDataError, match="互相包含"):
        data.migrate_desktop_data(source, target, expected_plan_id="unused", confirm_source_stopped=True)


def test_sqlite_backup_includes_committed_wal_and_preserves_original_files(tmp_path):
    source, target = tmp_path / "old", tmp_path / "new"
    source.mkdir()
    database = source / "electrochem_v6.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE records(value TEXT)")
        connection.execute("INSERT INTO records VALUES ('committed in WAL')")
        connection.commit()
        assert Path(str(database) + "-wal").stat().st_size > 0
        original = _write(source / "runs" / "uploaded" / "source" / "input.zip", "source archive bytes")
        cache = _write(source / "replay_sources" / "hash" / "data" / "CV.txt", "0 0\n1 1\n")
        before = {str(path): _digest(path) for path in (database, original, cache)}
        _write(target / "desktop-state.json", '{"theme":"dark"}')
        result = _migrate(source, target)
        assert result["requires_source_retention"]
        assert result["legacy_read_roots"] == [str(source)]
        with closing(sqlite3.connect(target / database.name)) as migrated:
            assert migrated.execute("SELECT value FROM records").fetchall() == [("committed in WAL",)]
            assert migrated.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert not (target / (database.name + "-wal")).exists()
        assert (target / "desktop-state.json").read_text() == '{"theme":"dark"}'
        assert all(_digest(Path(path)) == digest for path, digest in before.items())
        assert (target / original.relative_to(source)).read_bytes() == original.read_bytes()
        assert (target / cache.relative_to(source)).read_bytes() == cache.read_bytes()


def test_corrupt_database_is_not_published_and_source_is_untouched(tmp_path):
    source, target = tmp_path / "old", tmp_path / "new"
    invalid = _write(source / "electrochem_v6.db", "not a sqlite database")
    before = invalid.read_bytes()
    plan = _plan(source, target)
    with pytest.raises(sqlite3.DatabaseError):
        data.migrate_desktop_data(source, target, expected_plan_id=plan["plan_id"], confirm_source_stopped=True)
    assert not data.has_desktop_data(target)
    assert invalid.read_bytes() == before
    assert not list(tmp_path.glob(".electrochem-migration-*"))


def test_source_mutation_during_copy_aborts_before_publication(tmp_path, monkeypatch):
    source, target = tmp_path / "old", tmp_path / "new"
    original = _write(source / "projects.json", "{}")
    copy = data.shutil.copy2

    def racing_copy(origin, destination):
        result = copy(origin, destination)
        original.write_text('{"new":1}')
        return result

    monkeypatch.setattr(data.shutil, "copy2", racing_copy)
    plan = _plan(source, target)
    with pytest.raises(data.DesktopDataError, match="复制期间"):
        data.migrate_desktop_data(source, target, expected_plan_id=plan["plan_id"], confirm_source_stopped=True)
    assert not data.has_desktop_data(target)
    assert original.read_text() == '{"new":1}'


def test_os_lock_prevents_second_process_migration(tmp_path):
    source, target = tmp_path / "old", tmp_path / "new"
    _write(source / "projects.json", "{}")
    code = "from electrochem_v6.desktop.data import inspect_data_migration; import sys; p=inspect_data_migration(sys.argv[1],sys.argv[2],confirm_source_stopped=True); assert not p['can_migrate']; assert any('占用' in i for i in p['issues'])"
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONIOENCODING": "utf-8"}
    with data.desktop_data_lock(source):
        completed = subprocess.run([sys.executable, "-c", code, str(source), str(target)], env=environment, capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr


def test_migration_honors_real_desktop_instance_lock_on_both_directories(tmp_path):
    from electrochem_v6.desktop.instance import SingleInstance

    source, target = tmp_path / "old", tmp_path / "new"
    _write(source / "projects.json", "{}")
    for directory in (source, target):
        instance = SingleInstance(directory, lambda: None)
        assert instance.acquire()
        try:
            plan = _plan(source, target)
            assert not plan["can_migrate"]
            assert any("占用" in issue for issue in plan["issues"])
            with pytest.raises(data.DesktopDataError, match="占用"):
                data.migrate_desktop_data(source, target, expected_plan_id=plan["plan_id"], confirm_source_stopped=True)
        finally:
            instance.close()


def test_absolute_signal_table_and_manifest_are_byte_identical_after_copy(tmp_path):
    source, target = tmp_path / "old", tmp_path / "new"
    signal = _write(source / "inputs" / "signal.csv", "ppm,intensity\n1,2\n2,3\n")
    table = _write(source / "inputs" / "measurements.csv", f'sample_name,signal_file,charge_C\nA,"{signal}",1\n')
    manifest = _write(source / "runs" / "run_manifest.json", json.dumps({"inputs": [{"path": str(table), "sha256": _digest(table)}, {"path": str(signal), "sha256": _digest(signal)}]}))
    receipt = _migrate(source, target)
    assert receipt["requires_source_retention"]
    for path in (table, signal, manifest):
        assert (target / path.relative_to(source)).read_bytes() == path.read_bytes()
    saved = json.loads((target / "desktop-migration.json").read_text(encoding="utf-8"))
    assert saved["legacy_read_roots"] == [str(source)]
    assert str(signal) in (target / table.relative_to(source)).read_text()


def test_real_recipe_report_and_replay_keep_exact_history_and_input_fingerprints(tmp_path, monkeypatch):
    from electrochem_v6.core.process_service import process_folder
    from electrochem_v6.core.reproducible_report_service import build_run_report_document
    from electrochem_v6.core.run_replay import build_replay_plan
    from electrochem_v6.store.run_recipes import get_run_recipe
    from electrochem_v6.store.runtime import get_database, reset_runtime

    source, target = tmp_path / "legacy", tmp_path / "user"
    monkeypatch.setenv(data.DATA_ENV, str(source))
    for name in ("PROJECTS", "HISTORY", "CONVERSATION", "TEMPLATE", "QUALITY_REPORT", "LOG", "LLM_CONFIG"):
        monkeypatch.delenv(f"ELECTROCHEM_V6_{name}_FILE", raising=False)
    reset_runtime()
    try:
        primary = _write(source / "owned_inputs" / "CV_original.txt", "\n".join(f"{point / 30} {point / 30000}" for point in range(31)))
        processed = process_folder({"folder_path": str(primary.parent), "input_files": [{"path": str(primary), "data_type": "CV"}], "project_name": "Migration test", "data_types": ["CV"], "params": {"cv_scan_rate_v_s": 0.05}})
        assert processed["status"] == "success", processed
        run_id = processed["result"]["manifest"]["run"]["run_id"]
        recipe = get_run_recipe(run_id)
        assert recipe is not None
        original_recipe = json.dumps(recipe, sort_keys=True)
        record_key = recipe["record_keys"][0]
        original_record = get_database().get_history_record(record_key)
        outputs = {path: _digest(Path(path)) for path in recipe["output_files"] if Path(path).is_file()}
        reset_runtime()
        result = _migrate(source, target)
        monkeypatch.setenv(data.DATA_ENV, str(target))
        migrated = get_run_recipe(run_id)
        assert migrated is not None and json.dumps(migrated, sort_keys=True) == original_recipe
        assert get_database().get_history_record(record_key) == original_record
        assert migrated["inputs"][0]["sha256"] == _digest(primary)
        assert result["requires_source_retention"]
        document = build_run_report_document(migrated["manifest"])
        assert document["summary"] and document["figures"]
        replay = build_replay_plan(run_id, {"record_key": record_key})
        assert replay["can_replay"], replay
        assert all(item["state"] == "unchanged" for item in replay["source_checks"])
        assert all(_digest(Path(path)) == digest for path, digest in outputs.items())
        assert (target / primary.relative_to(source)).read_bytes() == primary.read_bytes()
    finally:
        reset_runtime()


def test_packaged_hook_uses_explicit_policy_without_creation_or_per_file_reset(tmp_path, monkeypatch):
    import runpy

    root = tmp_path / "app"
    monkeypatch.setattr(sys, "executable", str(root / "ElectroChemV6.exe"))
    monkeypatch.setenv(data.DATA_ENV, str(tmp_path / "explicit"))
    monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "history.db"))
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "packaging/runtime_data_dir_hook.py"))
    assert os.environ[data.DATA_ENV] == str(tmp_path / "explicit")
    assert os.environ["ELECTROCHEM_V6_HISTORY_FILE"] == str(tmp_path / "history.db")
    assert not root.exists()
