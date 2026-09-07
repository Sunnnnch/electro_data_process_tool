import pytest

from electrochem_v6.config import user_config_dir
from electrochem_v6.core.storage_service import cleanup_orphaned_runs
from electrochem_v6.store.history import delete_history_record
from electrochem_v6.store.projects import permanently_delete_project
from electrochem_v6.store.run_recipes import get_run_recipe, save_run_recipe
from electrochem_v6.store.runtime import get_database, reset_runtime


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    yield get_database()
    reset_runtime()


def test_recipe_only_fe_and_replay_cache_are_preserved_then_removed_with_project(runtime):
    runtime.create_project({"id": "fe", "name": "FE", "status": "archived"})
    upload = user_config_dir() / "runs/uploads/original"
    cache = user_config_dir() / "runs/replay_sources/restored"
    orphan = user_config_dir() / "runs/replay_sources/unused"
    for path in (upload, cache, orphan):
        path.mkdir(parents=True)
        (path / "input.txt").write_text("data")
    save_run_recipe({"run_id": "fe-only", "project_id": "fe", "data_types": ["COUPLED"],
                     "artifact_root": str(upload), "replay_cache_root": str(cache), "record_keys": []})
    cleanup_orphaned_runs()
    assert upload.exists() and cache.exists() and not orphan.exists()
    result = permanently_delete_project("fe")
    assert result["status"] == "success"
    assert get_run_recipe("fe-only") is None
    assert not upload.exists() and not cache.exists()


def test_shared_cache_is_retained_for_other_project(runtime):
    for project in ("one", "two"):
        runtime.create_project({"id": project, "name": project, "status": "archived"})
    cache = user_config_dir() / "runs/replay_sources/shared"
    cache.mkdir(parents=True)
    for project in ("one", "two"):
        save_run_recipe({"run_id": project, "project_id": project, "replay_cache_root": str(cache)})
    permanently_delete_project("one")
    assert cache.is_dir() and get_run_recipe("two")
    permanently_delete_project("two")
    assert not cache.exists()


def test_deleted_history_is_removed_from_recipe_and_last_delete_reclaims_run(runtime):
    root = user_config_dir() / "runs/uploads/results"
    root.mkdir(parents=True)
    keys = []
    for name in ("a", "b"):
        runtime.add_history_record({"timestamp": "2026-09-07", "type": "CV", "file_path": name,
                                    "project_id": "project", "run_id": "run", "artifact_root": str(root),
                                    "artifact_owner": "application", "results": {"charge_mC": 1}})
    keys = [item["record_key"] for item in runtime.get_all_history_records()]
    save_run_recipe({"run_id": "run", "project_id": "project", "data_types": ["CV"],
                     "artifact_root": str(root), "record_keys": keys,
                     "records": [{"record_key": key} for key in keys]})
    assert delete_history_record(keys[0], delete_artifacts=True)["status"] == "success"
    recipe = get_run_recipe("run")
    assert recipe["record_keys"] == [keys[1]]
    assert recipe["records"] == [{"record_key": keys[1]}]
    assert recipe["history_partially_deleted"] and recipe["deleted_record_keys"] == [keys[0]]
    assert root.exists()
    assert delete_history_record(keys[1], delete_artifacts=True)["status"] == "success"
    assert get_run_recipe("run") is None
    assert not root.exists()
