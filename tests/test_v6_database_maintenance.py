from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from electrochem_v6.store.database import SCHEMA_VERSION, Database, DatabaseVersionError
from electrochem_v6.store.database_maintenance import (
    backup_database,
    cleanup_preview,
    database_health,
    restore_database,
)


def _record(run_id: str, value: float) -> dict:
    return {
        "timestamp": f"2026-01-01 00:00:{run_id[-1]}",
        "type": "LSV",
        "file_path": f"/{run_id}.txt",
        "run_id": run_id,
        "results": {"tafel_slope": value},
    }


def test_schema_v1_upgrade_backfills_normalized_tables_and_creates_backup(tmp_path):
    path = tmp_path / "legacy.db"
    legacy = Database(str(path))
    legacy.add_history_record(_record("run-1", 82.0))
    legacy.append_message("legacy-chat", "user", "hello")
    with legacy.transaction() as connection:
        connection.execute(
            "UPDATE conversations SET messages=? WHERE conversation_id='legacy-chat'",
            (json.dumps([{"role": "user", "content": "hello"}]),),
        )
        connection.execute("DROP TABLE conversation_messages")
        connection.execute("DROP TABLE history_metrics")
        connection.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
    legacy.close()

    upgraded = Database(str(path))
    try:
        with upgraded.read() as connection:
            assert connection.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()[0] == str(SCHEMA_VERSION)
            assert connection.execute("SELECT COUNT(*) FROM history_metrics").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM conversation_messages").fetchone()[0] == 1
        assert upgraded.get_conversation("legacy-chat")["messages"][0]["content"] == "hello"
    finally:
        upgraded.close()
    assert list((tmp_path / "backups").glob(f"legacy.pre-schema-v1-to-v{SCHEMA_VERSION}.*.db"))


def test_unknown_database_without_schema_metadata_is_rejected(tmp_path):
    path = tmp_path / "unknown.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE history_records (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()
    with pytest.raises(DatabaseVersionError, match="metadata"):
        Database(str(path))


def test_schema_v5_upgrade_renames_legacy_duplicate_projects_and_enforces_unique_names(tmp_path):
    path = tmp_path / "duplicate-projects.db"
    database = Database(str(path))
    database.close()
    connection = sqlite3.connect(path)
    connection.execute("DROP INDEX idx_projects_name_nocase")
    connection.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
    connection.execute("INSERT INTO projects (id, name, status) VALUES ('p1', 'Demo', 'active')")
    connection.execute("INSERT INTO projects (id, name, status) VALUES ('p2', 'demo', 'archived')")
    connection.commit()
    connection.close()

    upgraded = Database(str(path))
    try:
        projects = upgraded.get_all_projects("all")
        assert {project["name"] for project in projects} == {"Demo", "demo (2)"}
        with pytest.raises(sqlite3.IntegrityError):
            with upgraded.transaction() as transaction:
                transaction.execute(
                    "INSERT INTO projects (id, name, status) VALUES ('p3', 'DEMO', 'active')"
                )
    finally:
        upgraded.close()


def test_backup_retention_and_health_report(tmp_path):
    path = tmp_path / "data.db"
    database = Database(str(path))
    database.add_history_record(_record("run-1", 81.0))
    database.create_backup(reason="one", keep=2)
    database.create_backup(reason="two", keep=2)
    database.create_backup(reason="three", keep=2)
    database.close()

    backups = list((tmp_path / "backups").glob("data.*.db"))
    assert len(backups) == 2
    health = database_health(str(path))
    assert health["ok"] is True
    assert health["schema_version"] == SCHEMA_VERSION
    assert health["counts"]["history"] == 1
    assert health["counts"]["indexed_metrics"] == 1


def test_restore_replaces_database_and_keeps_safety_backup(tmp_path):
    path = tmp_path / "restore.db"
    database = Database(str(path))
    database.add_history_record(_record("run-1", 81.0))
    database.close()
    backup = backup_database(str(path))["backup_path"]

    database = Database(str(path))
    database.add_history_record(_record("run-2", 99.0))
    database.close()

    result = restore_database(backup, str(path), confirmed=True)
    assert result["ok"] is True
    assert result["safety_backup"]
    assert Path(result["safety_backup"]).is_file()
    restored = Database(str(path))
    try:
        assert [item["run_id"] for item in restored.get_all_history_records()] == ["run-1"]
    finally:
        restored.close()


def test_restore_requires_confirmation(tmp_path):
    with pytest.raises(ValueError, match="confirmation"):
        restore_database(str(tmp_path / "backup.db"), str(tmp_path / "target.db"))


def test_cleanup_preview_is_read_only_and_separates_confidence(tmp_path):
    path = tmp_path / "cleanup.db"
    database = Database(str(path))
    database.create_project({"id": "p1", "name": "smoke_api"})
    database.create_project({"id": "p2", "name": "v6_report_example"})
    database.create_project({"id": "p3", "name": "Catalyst stability"})
    database.close()

    preview = cleanup_preview(str(path))
    assert preview["read_only"] is True
    assert [item["id"] for item in preview["high_confidence"]] == ["p1"]
    assert [item["id"] for item in preview["review_required"]] == ["p2"]
    database = Database(str(path))
    try:
        assert len(database.get_all_projects("all")) == 3
    finally:
        database.close()
