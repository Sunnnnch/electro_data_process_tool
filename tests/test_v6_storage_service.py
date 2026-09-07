from electrochem_v6.config import user_config_dir
from electrochem_v6.core.storage_service import cleanup_orphaned_runs, storage_summary
from electrochem_v6.store.history import delete_history_record
from electrochem_v6.store.projects import permanently_delete_project
from electrochem_v6.store.runtime import get_database, reset_runtime


def _record(*, project_id, run_id, artifact_root):
    return {
        "timestamp": "2026-08-23 10:00:00",
        "type": "EIS",
        "file_path": f"/input/{run_id}.txt",
        "project_id": project_id,
        "run_id": run_id,
        "artifact_root": str(artifact_root),
        "artifact_owner": "application",
        "results": {"rs": 2.0},
    }


def test_storage_cleanup_only_removes_unreferenced_managed_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    referenced = user_config_dir() / "runs" / "uploads" / "referenced"
    orphaned = user_config_dir() / "runs" / "uploads" / "orphaned"
    referenced.mkdir(parents=True)
    orphaned.mkdir(parents=True)
    (referenced / "result.bin").write_bytes(b"1234")
    (orphaned / "result.bin").write_bytes(b"56789")
    database = get_database()
    database.add_history_record(_record(project_id="p1", run_id="r1", artifact_root=referenced))

    summary = storage_summary()
    assert summary["referenced_runs"] == 1
    assert summary["orphaned_runs"] == 1
    cleanup = cleanup_orphaned_runs()
    assert cleanup["bytes_reclaimed"] == 5
    assert referenced.is_dir()
    assert not orphaned.exists()
    reset_runtime()


def test_deleting_last_history_record_can_reclaim_managed_run(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    run_root = user_config_dir() / "runs" / "uploads" / "history-run"
    run_root.mkdir(parents=True)
    (run_root / "result.txt").write_text("result", encoding="utf-8")
    database = get_database()
    database.add_history_record(_record(project_id="p1", run_id="r2", artifact_root=run_root))
    key = database.get_all_history_records()[0]["record_key"]

    result = delete_history_record(key, delete_artifacts=True)
    assert result["status"] == "success"
    assert result["artifact_cleanup"]["removed"] == [str(run_root.resolve())]
    assert not run_root.exists()
    reset_runtime()


def test_permanent_project_delete_requires_archive_and_removes_managed_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    run_root = user_config_dir() / "runs" / "uploads" / "project-run"
    run_root.mkdir(parents=True)
    (run_root / "result.txt").write_text("result", encoding="utf-8")
    database = get_database()
    database.create_project({"id": "p-delete", "name": "Delete Me", "status": "active"})
    database.add_history_record(_record(project_id="p-delete", run_id="r3", artifact_root=run_root))

    blocked = permanently_delete_project("p-delete")
    assert blocked["status"] == "error"
    database.update_project("p-delete", status="archived")
    result = permanently_delete_project("p-delete")
    assert result["status"] == "success"
    assert result["deleted"] == {"projects": 1, "history_records": 1}
    assert database.get_project("p-delete") is None
    assert database.filter_history(project_id="p-delete", include_archived=True) == []
    assert not run_root.exists()
    reset_runtime()


def test_permanent_project_delete_reports_incomplete_artifact_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    run_root = user_config_dir() / "runs" / "uploads" / "locked-run"
    run_root.mkdir(parents=True)
    database = get_database()
    database.create_project({"id": "p-locked", "name": "Locked", "status": "archived"})
    database.add_history_record(_record(project_id="p-locked", run_id="r4", artifact_root=run_root))
    monkeypatch.setattr(
        "electrochem_v6.store.projects.remove_managed_artifact_roots",
        lambda _roots: {"removed": [], "skipped": [str(run_root)], "bytes_reclaimed": 0},
    )

    result = permanently_delete_project("p-locked")

    assert result["status"] == "success"
    assert result["artifact_cleanup_complete"] is False
    assert result["artifact_cleanup"]["skipped"] == [str(run_root)]
    assert database.get_project("p-locked") is None
    reset_runtime()
