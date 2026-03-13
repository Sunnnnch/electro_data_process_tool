"""Tests for SQLite-backed wrapper classes in legacy_runtime.py."""

import json
import os
import threading

import pytest

# Force SQLite backend
os.environ["ELECTROCHEM_V6_STORAGE"] = "sqlite"


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    """Redirect all data files to tmp_path and reset singletons."""
    monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(tmp_path / "projects.json"))
    monkeypatch.setenv("ELECTROCHEM_V6_CONVERSATION_FILE", str(tmp_path / "conv.json"))
    monkeypatch.setenv("ELECTROCHEM_V6_TEMPLATE_FILE", str(tmp_path / "templates.json"))

    from electrochem_v6.store import legacy_runtime
    # Reset singleton so each test gets a fresh DB
    legacy_runtime._db_singleton = None
    yield
    legacy_runtime._db_singleton = None


# ── _get_db singleton ─────────────────────────────────────────────

def test_get_db_returns_same_instance():
    from electrochem_v6.store.legacy_runtime import _get_db
    db1 = _get_db()
    db2 = _get_db()
    assert db1 is db2


def test_get_db_thread_safe():
    from electrochem_v6.store.legacy_runtime import _get_db
    results = []

    def grab():
        results.append(id(_get_db()))

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # All threads should get the same singleton
    assert len(set(results)) == 1


# ── SqliteHistoryManager ──────────────────────────────────────────

class TestSqliteHistoryManager:
    def test_add_and_get_records(self):
        from electrochem_v6.store.legacy_runtime import SqliteHistoryManager
        mgr = SqliteHistoryManager()
        mgr.add_record({
            "timestamp": "2026-03-01 12:00:00",
            "type": "LSV",
            "file_name": "test.txt",
            "sample_name": "s1",
            "project_id": "p1",
            "results": {"overpotential_10": 320.0},
        })
        records = mgr.get_all_records()
        assert len(records) >= 1
        assert records[0]["sample_name"] == "s1"

    def test_filter_by_project(self):
        from electrochem_v6.store.legacy_runtime import SqliteHistoryManager
        mgr = SqliteHistoryManager()
        mgr.add_record({"timestamp": "2026-01-01", "type": "LSV", "sample_name": "a", "project_id": "p1"})
        mgr.add_record({"timestamp": "2026-01-02", "type": "CV", "sample_name": "b", "project_id": "p2"})
        filtered = mgr.db.filter_history(project_id="p1")
        assert all(r.get("project_id") == "p1" for r in filtered)

    def test_filter_by_type(self):
        from electrochem_v6.store.legacy_runtime import SqliteHistoryManager
        mgr = SqliteHistoryManager()
        mgr.add_record({"timestamp": "2026-01-01", "type": "LSV", "sample_name": "a"})
        mgr.add_record({"timestamp": "2026-01-02", "type": "CV", "sample_name": "b"})
        filtered = mgr.db.filter_history(data_type="CV")
        assert all(r.get("type") == "CV" for r in filtered)

    def test_empty_on_fresh_db(self):
        from electrochem_v6.store.legacy_runtime import SqliteHistoryManager
        mgr = SqliteHistoryManager()
        assert mgr.get_all_records() == []


# ── SqliteProjectManager ──────────────────────────────────────────

class TestSqliteProjectManager:
    def test_create_and_list(self):
        from electrochem_v6.store.legacy_runtime import SqliteProjectManager
        mgr = SqliteProjectManager()
        pid = mgr.create_project("Demo", description="test project")
        assert pid is not None
        projects = mgr.get_all_projects()
        assert len(projects) >= 1
        assert any(p["name"] == "Demo" for p in projects)

    def test_get_by_id(self):
        from electrochem_v6.store.legacy_runtime import SqliteProjectManager
        mgr = SqliteProjectManager()
        pid = mgr.create_project("FindMe")
        found = mgr.get_project(pid)
        assert found is not None
        assert found["name"] == "FindMe"

    def test_delete_project(self):
        from electrochem_v6.store.legacy_runtime import SqliteProjectManager
        mgr = SqliteProjectManager()
        pid = mgr.create_project("DeleteMe")
        mgr.delete_project(pid)
        assert mgr.get_project(pid) is None


# ── SqliteConversationManager ─────────────────────────────────────

class TestSqliteConversationManager:
    def test_append_and_get(self):
        from electrochem_v6.store.legacy_runtime import SqliteConversationManager
        mgr = SqliteConversationManager()
        # append_message with conversation_id=None creates a new conversation
        cid = mgr.append_message(None, role="user", content="Hello")
        assert cid
        conv = mgr.get_conversation(cid)
        assert conv is not None

    def test_list_conversations(self):
        from electrochem_v6.store.legacy_runtime import SqliteConversationManager
        mgr = SqliteConversationManager()
        mgr.append_message(None, role="user", content="Chat 1")
        mgr.append_message(None, role="user", content="Chat 2")
        result = mgr.list_conversations()
        assert isinstance(result, dict)
        items = result.get("items", [])
        assert len(items) >= 2


# ── JSON migration ────────────────────────────────────────────────

class TestJsonMigration:
    def test_migrate_corrupt_json(self, tmp_path):
        from electrochem_v6.store.legacy_runtime import _get_db
        corrupt = tmp_path / "corrupt_history.json"
        corrupt.write_text("{invalid json", encoding="utf-8")
        db = _get_db()
        # Should not crash, returns 0 migrated
        counts = db.migrate_from_json(history_file=str(corrupt))
        assert isinstance(counts, dict)

    def test_migrate_wrong_structure(self, tmp_path):
        from electrochem_v6.store.legacy_runtime import _get_db
        wrong = tmp_path / "wrong_history.json"
        wrong.write_text(json.dumps({"version": "1.0", "records": "not_a_list"}), encoding="utf-8")
        db = _get_db()
        counts = db.migrate_from_json(history_file=str(wrong))
        assert isinstance(counts, dict)
