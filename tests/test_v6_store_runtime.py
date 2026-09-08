"""Tests for SQLite runtime stores and legacy JSON import."""

import json
import threading

import pytest


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    """Redirect all data files to tmp_path and reset singletons."""
    monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "history.json"))
    monkeypatch.setenv("ELECTROCHEM_V6_PROJECTS_FILE", str(tmp_path / "projects.json"))
    monkeypatch.setenv("ELECTROCHEM_V6_CONVERSATION_FILE", str(tmp_path / "conv.json"))
    monkeypatch.setenv("ELECTROCHEM_V6_TEMPLATE_FILE", str(tmp_path / "templates.json"))

    from electrochem_v6.store.runtime import reset_runtime

    reset_runtime()
    yield
    reset_runtime()


# Database singleton

def test_get_database_returns_same_instance():
    from electrochem_v6.store.runtime import get_database

    db1 = get_database()
    db2 = get_database()
    assert db1 is db2


def test_get_database_thread_safe():
    from electrochem_v6.store.runtime import get_database

    results = []

    def grab():
        results.append(id(get_database()))

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # All threads should get the same singleton
    assert len(set(results)) == 1


def test_reset_runtime_waits_for_database_initialization(monkeypatch):
    from electrochem_v6.store import runtime

    created = threading.Event()
    publish = threading.Event()
    reset_started = threading.Event()
    reset_done = threading.Event()
    databases = []
    errors = []
    original_database = runtime.Database

    def delayed_database(path):
        database = original_database(path)
        databases.append(database)
        created.set()
        assert publish.wait(10)
        return database

    monkeypatch.setattr(runtime, "Database", delayed_database)

    def initialize():
        try:
            runtime.get_database()
        except Exception as exc:
            errors.append(exc)

    def reset():
        reset_started.set()
        runtime.reset_runtime()
        reset_done.set()

    initializer = threading.Thread(target=initialize)
    resetter = threading.Thread(target=reset)
    initializer.start()
    try:
        assert created.wait(10)
        resetter.start()
        assert reset_started.wait(10)
        assert not reset_done.wait(0.2), "reset lost a database still being initialized"
    finally:
        publish.set()
        initializer.join(10)
        if resetter.ident is not None:
            resetter.join(10)
    assert not initializer.is_alive() and not resetter.is_alive()
    assert errors == []
    assert reset_done.is_set() and runtime._database is None
    assert databases and databases[0]._connections == set()


def test_reset_releases_singleton_locks_before_closing_connections(monkeypatch):
    from electrochem_v6.store import runtime

    database = runtime.get_database()
    closing = threading.Event()
    release_close = threading.Event()
    replacement_ready = threading.Event()
    replacements = []
    errors = []
    original_close = database.close_all

    def delayed_close():
        closing.set()
        assert release_close.wait(30)
        original_close()

    monkeypatch.setattr(database, "close_all", delayed_close)

    def get_replacement():
        try:
            replacements.append(runtime.get_history_store().db)
            replacement_ready.set()
        except Exception as exc:
            errors.append(exc)

    resetter = threading.Thread(target=runtime.reset_runtime)
    reader = threading.Thread(target=get_replacement)
    resetter.start()
    try:
        assert closing.wait(10)
        reader.start()
        assert replacement_ready.wait(10), "connection close held the runtime singleton locks"
        assert replacements[0] is not database
    finally:
        release_close.set()
        resetter.join(10)
        if reader.ident is not None:
            reader.join(10)
    assert not resetter.is_alive() and not reader.is_alive()
    assert errors == []
    assert runtime.get_database() is replacements[0]


def test_path_switch_releases_init_lock_before_waiting_for_old_read(tmp_path, monkeypatch):
    from electrochem_v6.store import runtime

    database = runtime.get_database()
    old_read_started = threading.Event()
    close_attempted = threading.Event()
    init_lock_available = []
    replacements = []
    errors = []
    original_close = database.close_all

    def close_after_publication():
        # Detect an inverted lock before calling close, so the old code fails
        # deterministically instead of deadlocking the pytest process.
        available = runtime._DATABASE_INIT_LOCK.acquire(blocking=False)
        if available:
            runtime._DATABASE_INIT_LOCK.release()
        init_lock_available.append(available)
        close_attempted.set()
        assert available, "path switch waited on DB while holding INIT"
        original_close()

    monkeypatch.setattr(database, "close_all", close_after_publication)

    def old_reader():
        try:
            with database.read() as connection:
                assert connection.execute("SELECT 1").fetchone()[0] == 1
                old_read_started.set()
                assert close_attempted.wait(10)
                if init_lock_available == [False]:
                    return
                replacements.append(runtime.get_database())
                assert connection.execute("SELECT 2").fetchone()[0] == 2
        except Exception as exc:
            errors.append(exc)

    def switch_path():
        try:
            replacements.append(runtime.get_database())
        except Exception as exc:
            errors.append(exc)

    reader = threading.Thread(target=old_reader)
    switcher = threading.Thread(target=switch_path)
    reader.start()
    try:
        assert old_read_started.wait(10)
        monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "new-runtime" / "history.json"))
        switcher.start()
    finally:
        if switcher.ident is not None:
            switcher.join(10)
        close_attempted.set()
        reader.join(10)
    assert not reader.is_alive() and not switcher.is_alive()
    assert errors == []
    assert init_lock_available == [True]
    assert len(replacements) == 2 and replacements[0] is replacements[1]
    assert replacements[0] is not database
    assert database._connections == set()


def test_failed_path_switch_still_closes_previous_database_outside_init_lock(tmp_path, monkeypatch):
    from electrochem_v6.store import runtime

    database = runtime.get_database()
    original_close = database.close_all
    closed = []

    def fail_initialization(_path):
        raise RuntimeError("new database unavailable")

    def close_without_init_lock():
        assert runtime._DATABASE_INIT_LOCK.acquire(blocking=False)
        runtime._DATABASE_INIT_LOCK.release()
        original_close()
        closed.append(True)

    monkeypatch.setattr(database, "close_all", close_without_init_lock)
    monkeypatch.setattr(runtime, "Database", fail_initialization)
    monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "new-runtime" / "history.json"))
    with pytest.raises(RuntimeError, match="new database unavailable"):
        runtime.get_database()
    assert closed == [True]
    assert database._connections == set()
    assert runtime._database is None


# History store

class TestHistoryStore:
    def test_add_and_get_records(self):
        from electrochem_v6.store.runtime import HistoryStore

        mgr = HistoryStore()
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
        from electrochem_v6.store.runtime import HistoryStore

        mgr = HistoryStore()
        mgr.add_record({"timestamp": "2026-01-01", "type": "LSV", "sample_name": "a", "project_id": "p1"})
        mgr.add_record({"timestamp": "2026-01-02", "type": "CV", "sample_name": "b", "project_id": "p2"})
        filtered = mgr.db.filter_history(project_id="p1")
        assert all(r.get("project_id") == "p1" for r in filtered)

    def test_filter_by_type(self):
        from electrochem_v6.store.runtime import HistoryStore

        mgr = HistoryStore()
        mgr.add_record({"timestamp": "2026-01-01", "type": "LSV", "sample_name": "a"})
        mgr.add_record({"timestamp": "2026-01-02", "type": "CV", "sample_name": "b"})
        filtered = mgr.db.filter_history(data_type="CV")
        assert all(r.get("type") == "CV" for r in filtered)

    def test_empty_on_fresh_db(self):
        from electrochem_v6.store.runtime import HistoryStore

        mgr = HistoryStore()
        assert mgr.get_all_records() == []


# Project store

class TestProjectStore:
    def test_create_and_list(self):
        from electrochem_v6.store.runtime import ProjectStore

        mgr = ProjectStore()
        pid = mgr.create_project("Demo", description="test project")
        assert pid is not None
        projects = mgr.get_all_projects()
        assert len(projects) >= 1
        assert any(p["name"] == "Demo" for p in projects)

    def test_get_by_id(self):
        from electrochem_v6.store.runtime import ProjectStore

        mgr = ProjectStore()
        pid = mgr.create_project("FindMe")
        found = mgr.get_project(pid)
        assert found is not None
        assert found["name"] == "FindMe"

    def test_delete_project(self):
        from electrochem_v6.store.runtime import ProjectStore

        mgr = ProjectStore()
        pid = mgr.create_project("DeleteMe")
        mgr.delete_project(pid)
        assert mgr.get_project(pid)["status"] == "archived"
        assert all(project["id"] != pid for project in mgr.get_all_projects("active"))


# Conversation store

class TestConversationStore:
    def test_append_and_get(self):
        from electrochem_v6.store.runtime import ConversationStore

        mgr = ConversationStore()
        # append_message with conversation_id=None creates a new conversation
        cid = mgr.append_message(None, role="user", content="Hello")
        assert cid
        conv = mgr.get_conversation(cid)
        assert conv is not None

    def test_list_conversations(self):
        from electrochem_v6.store.runtime import ConversationStore

        mgr = ConversationStore()
        mgr.append_message(None, role="user", content="Chat 1")
        mgr.append_message(None, role="user", content="Chat 2")
        result = mgr.list_conversations()
        assert isinstance(result, dict)
        items = result.get("items", [])
        assert len(items) >= 2


# ── JSON migration ────────────────────────────────────────────────

class TestJsonMigration:
    def test_migrate_corrupt_json(self, tmp_path):
        from electrochem_v6.store.database import Database
        corrupt = tmp_path / "corrupt_history.json"
        corrupt.write_text("{invalid json", encoding="utf-8")
        db = Database(str(tmp_path / "corrupt.db"))
        # Should not crash, returns 0 migrated
        counts = db.migrate_from_json(history_file=str(corrupt))
        assert isinstance(counts, dict)
        assert counts["complete"] is False
        assert counts["errors"]
        assert not db.is_migrated()

    def test_migrate_wrong_structure(self, tmp_path):
        from electrochem_v6.store.database import Database
        wrong = tmp_path / "wrong_history.json"
        wrong.write_text(json.dumps({"version": "1.0", "records": "not_a_list"}), encoding="utf-8")
        db = Database(str(tmp_path / "wrong.db"))
        counts = db.migrate_from_json(history_file=str(wrong))
        assert isinstance(counts, dict)
        assert counts["complete"] is False
        assert counts["errors"]
        assert not db.is_migrated()
