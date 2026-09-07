"""Project template references survive edits, missing templates and storage upgrades."""

from __future__ import annotations

import json
import socket
import sqlite3
from urllib import error, request

import pytest

from electrochem_v6.server import V6ServerManager
from electrochem_v6.store.database import SCHEMA_VERSION, Database
from electrochem_v6.store.database_maintenance import backup_database, restore_database
from electrochem_v6.store.projects import create_project, list_projects, update_project
from electrochem_v6.store.runtime import get_database, reset_runtime


@pytest.fixture
def isolated_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path))
    for variable, filename in (
        ("ELECTROCHEM_V6_PROJECTS_FILE", "projects.json"),
        ("ELECTROCHEM_V6_HISTORY_FILE", "history.json"),
        ("ELECTROCHEM_V6_CONVERSATION_FILE", "conversations.json"),
        ("ELECTROCHEM_V6_TEMPLATE_FILE", "templates.json"),
    ):
        monkeypatch.setenv(variable, str(tmp_path / filename))
    reset_runtime()
    yield tmp_path
    reset_runtime()


def _http(url, payload=None):
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    outgoing = request.Request(
        url, data=encoded, headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with request.urlopen(outgoing, timeout=5) as response:
            return response.status, json.load(response)
    except error.HTTPError as response:
        return response.code, json.load(response)


def test_project_template_routes_persist_validate_and_keep_deleted_reference(isolated_runtime):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    manager = V6ServerManager(port=port)
    assert manager.start()[0]
    base = f"http://127.0.0.1:{port}/api/v1"
    try:
        code, created = _http(f"{base}/projects", {
            "name": "模板关联项目", "default_template_name": " LSV_常用模板 ",
        })
        assert code == 200
        project_id = created["project_id"]
        assert created["project"]["default_template_name"] == "LSV_常用模板"
        update_url = f"{base}/projects/{project_id}/update"
        for invalid in (None, False, 7, [], {"name": "LSV_常用模板"}, "missing-template"):
            code, rejected = _http(update_url, {"name": "must not change", "default_template_name": invalid})
            assert code == 400
            assert rejected["status"] == "error"
            assert get_database().get_project(project_id)["name"] == "模板关联项目"
            code, _ = _http(f"{base}/projects", {"name": "must not create", "default_template_name": invalid})
            assert code == 400

        code, edited = _http(update_url, {"description": "普通编辑保留关联"})
        assert code == 200
        assert edited["project"]["default_template_name"] == "LSV_常用模板"
        assert _http(f"{base}/process/templates", {
            "name": "custom-cv", "state": {"selected_types": ["CV"], "values": {"pro-area": "2"}},
        })[0] == 200
        assert _http(update_url, {"default_template_name": "custom-cv"})[0] == 200
        assert _http(f"{base}/process/templates/custom-cv/delete", {})[0] == 200
        code, listed = _http(f"{base}/projects")
        assert code == 200
        assert listed["projects"][0]["default_template_name"] == "custom-cv"
        assert _http(update_url, {"description": "可以保留已失效关联", "default_template_name": "custom-cv"})[0] == 200
        assert _http(f"{base}/projects", {"name": "new missing ref", "default_template_name": "custom-cv"})[0] == 400
        code, unlinked = _http(update_url, {"default_template_name": ""})
        assert code == 200
        assert unlinked["project"]["default_template_name"] == ""
        assert len(list_projects()["projects"]) == 1
    finally:
        manager.stop()


def test_template_reference_survives_runtime_restart_and_archiving(isolated_runtime):
    created = create_project("稳定关联", default_template_name="EIS_常用模板")
    project_id = created["project_id"]
    assert update_project(project_id, status="archived")["project"]["default_template_name"] == "EIS_常用模板"
    reset_runtime()
    stored = get_database().get_project(project_id)
    assert stored["default_template_name"] == "EIS_常用模板"
    assert stored["status"] == "archived"
    assert update_project(project_id, status="active")["project"]["default_template_name"] == "EIS_常用模板"


def test_schema_v5_upgrade_adds_empty_template_reference_and_preserves_data(tmp_path):
    path = tmp_path / "legacy.db"
    database = Database(str(path))
    database.create_project({"id": "legacy", "name": "Older project", "description": "keep me"})
    database.close_all()
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE projects DROP COLUMN default_template_name")
        connection.execute("UPDATE meta SET value='5' WHERE key='schema_version'")
    migrated = Database(str(path))
    try:
        project = migrated.get_project("legacy")
        assert project["description"] == "keep me"
        assert project["default_template_name"] == ""
        with migrated.read() as connection:
            assert connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(SCHEMA_VERSION)
        assert migrated.quick_check()["ok"]
    finally:
        migrated.close_all()
    assert list((tmp_path / "backups").glob(f"legacy.pre-schema-v5-to-v{SCHEMA_VERSION}.*.db"))


def test_project_json_migration_and_database_backup_keep_template_reference(tmp_path):
    project_json = tmp_path / "projects.json"
    project_json.write_text(json.dumps({"projects": [
        {"id": "old", "name": "No association"},
        {"id": "linked", "name": "Linked", "default_template_name": "custom-existing"},
        {"id": "missing", "name": "Missing template", "default_template_name": "deleted-template"},
    ]}), encoding="utf-8")
    templates_json = tmp_path / "templates.json"
    templates_json.write_text(json.dumps({"templates": [
        {"name": "custom-existing", "state": {"selected_types": ["LSV"]}},
    ]}), encoding="utf-8")
    path = tmp_path / "source.db"
    database = Database(str(path))
    try:
        migrated = database.migrate_from_json(projects_file=str(project_json), templates_file=str(templates_json))
        assert migrated["complete"]
        assert migrated["projects"] == 3
        original = {project["id"]: project["default_template_name"] for project in database.get_all_projects("all")}
        assert original == {"old": "", "linked": "custom-existing", "missing": "deleted-template"}
    finally:
        database.close_all()
    backup = backup_database(str(path))["backup_path"]
    restored_path = tmp_path / "restored.db"
    assert restore_database(backup, str(restored_path), confirmed=True)["ok"]
    restored = Database(str(restored_path))
    try:
        assert {project["id"]: project["default_template_name"] for project in restored.get_all_projects("all")} == original
        assert restored.list_process_templates()[0]["name"] == "custom-existing"
    finally:
        restored.close_all()


def test_project_json_migration_rejects_nonstring_template_reference(tmp_path):
    source = tmp_path / "invalid-projects.json"
    source.write_text(json.dumps({"projects": [
        {"id": "invalid", "name": "Invalid reference", "default_template_name": {"name": "template"}},
    ]}), encoding="utf-8")
    database = Database(str(tmp_path / "destination.db"))
    try:
        result = database.migrate_from_json(projects_file=str(source))
        assert result["complete"] is False
        assert any("default_template_name must be a string" in message for message in result["errors"])
        assert database.get_all_projects("all") == []
    finally:
        database.close_all()
