"""Tests for the SQLite storage backend (database.py)."""

import json
import os
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Force SQLite backend for these tests
os.environ["ELECTROCHEM_V6_STORAGE"] = "sqlite"

from electrochem_v6.store.database import Database, _to_json_safe, _json_dumps, _json_loads


# ── Helpers ───────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


def _sample_record(**overrides):
    base = {
        "timestamp": "2026-03-01 12:00:00",
        "type": "LSV",
        "file_path": "/data/test.txt",
        "file_name": "test.txt",
        "sample_name": "sample_a",
        "project_id": "proj_1",
        "run_id": "run_1",
        "status": "success",
        "results": {"overpotential_10": 320.5, "tafel_slope": 85.0},
    }
    base.update(overrides)
    return base


# ── Schema & Init ─────────────────────────────────────────────────

def test_database_creates_file(tmp_path):
    db_path = str(tmp_path / "sub" / "test.db")
    db = Database(db_path)
    assert os.path.exists(db_path)


def test_schema_version_recorded(db):
    with db.read() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    assert row is not None
    assert row["value"] == "1"


def test_tables_exist(db):
    with db.read() as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    for expected in ("meta", "history_records", "projects", "conversations", "process_templates"):
        assert expected in tables


# ── History CRUD ──────────────────────────────────────────────────

def test_add_and_get_history_record(db):
    db.add_history_record(_sample_record())
    records = db.get_all_history_records()
    assert len(records) == 1
    rec = records[0]
    assert rec["sample_name"] == "sample_a"
    assert rec["type"] == "LSV"
    assert rec["results"]["overpotential_10"] == 320.5


def test_history_record_key_dedup(db):
    """Same timestamp+type+file_path should replace, not duplicate."""
    db.add_history_record(_sample_record())
    db.add_history_record(_sample_record(sample_name="sample_updated"))
    records = db.get_all_history_records()
    assert len(records) == 1
    assert records[0]["sample_name"] == "sample_updated"


def test_filter_history_by_project(db):
    db.add_history_record(_sample_record(project_id="proj_a"))
    db.add_history_record(_sample_record(project_id="proj_b", file_path="/other.txt", timestamp="2026-03-01 13:00:00"))
    result = db.filter_history(project_id="proj_a")
    assert len(result) == 1
    assert result[0]["project_id"] == "proj_a"


def test_filter_history_by_type(db):
    db.add_history_record(_sample_record(type="LSV"))
    db.add_history_record(_sample_record(type="CV", file_path="/cv.txt", timestamp="2026-03-02 01:00:00"))
    result = db.filter_history(data_type="cv")
    assert len(result) == 1
    assert result[0]["type"] == "CV"


def test_filter_history_archived_excluded_by_default(db):
    db.add_history_record(_sample_record(archived=True))
    assert len(db.filter_history()) == 0
    assert len(db.filter_history(include_archived=True)) == 1


def test_filter_history_metric_range(db):
    db.add_history_record(_sample_record(results={"tafel_slope": 80.0}))
    db.add_history_record(_sample_record(
        results={"tafel_slope": 120.0},
        file_path="/b.txt",
        timestamp="2026-03-02 02:00:00",
    ))
    result = db.filter_history(metric_key="tafel_slope", metric_max=100.0)
    assert len(result) == 1
    assert result[0]["results"]["tafel_slope"] == 80.0


def test_filter_history_limit(db):
    for i in range(10):
        db.add_history_record(_sample_record(
            file_path=f"/f{i}.txt",
            timestamp=f"2026-03-01 {10+i}:00:00",
        ))
    assert len(db.filter_history(limit=3)) == 3


def test_archive_and_delete_history(db):
    db.add_history_record(_sample_record())
    key = f"2026-03-01 12:00:00|LSV|/data/test.txt"
    assert db.update_history_by_key(key, "archive") == 1
    assert db.get_all_history_records()[0]["archived"] is True

    assert db.update_history_by_key(key, "delete") == 1
    assert len(db.get_all_history_records()) == 0


def test_attach_run_outputs(db):
    db.add_history_record(_sample_record(run_id="run_x"))
    affected = db.attach_run_outputs(
        run_id="run_x",
        output_files=["/out/plot.png", "/out/data.csv"],
        summary_path="/out/summary.json",
        quality_summary={"score": 0.95},
    )
    assert affected == 1
    rec = db.get_all_history_records()[0]
    assert rec["output_files"] == ["/out/plot.png", "/out/data.csv"]
    assert rec["summary_path"] == "/out/summary.json"
    assert rec["quality_summary"]["score"] == 0.95


def test_get_lsv_records(db):
    db.add_history_record(_sample_record(type="LSV"))
    db.add_history_record(_sample_record(type="CV", file_path="/cv.txt", timestamp="2026-03-02 01:00:00"))
    lsv = db.get_lsv_records()
    assert len(lsv) == 1
    assert lsv[0]["type"] == "LSV"


def test_get_history_stats(db):
    db.add_history_record(_sample_record(type="LSV"))
    db.add_history_record(_sample_record(type="CV", file_path="/cv.txt", timestamp="2026-03-02 01:00:00"))
    db.add_history_record(_sample_record(type="EIS", file_path="/eis.txt", timestamp="2026-03-03 01:00:00"))
    stats = db.get_history_stats()
    assert stats["total_files"] == 3
    assert stats["lsv_count"] == 1
    assert stats["cv_count"] == 1
    assert stats["eis_count"] == 1
    assert stats["ecsa_count"] == 0


def test_get_history_output_dirs(db):
    db.add_history_record(_sample_record(
        output_files=["/data/output/plot.png"],
        folder_path="/data/raw",
    ))
    dirs = db.get_history_output_dirs()
    assert any("output" in d for d in dirs) or any("raw" in d for d in dirs)


# ── Projects CRUD ─────────────────────────────────────────────────

def test_create_and_get_project(db):
    db.create_project({
        "id": "p1",
        "name": "Test Project",
        "description": "desc",
        "created_at": "2026-03-01",
        "tags": ["tag1"],
    })
    proj = db.get_project("p1")
    assert proj is not None
    assert proj["name"] == "Test Project"
    assert proj["tags"] == ["tag1"]


def test_get_all_projects_filters_status(db):
    db.create_project({"id": "p1", "name": "Active", "status": "active"})
    db.create_project({"id": "p2", "name": "Archived", "status": "archived"})
    active = db.get_all_projects(status="active")
    assert len(active) == 1
    assert active[0]["name"] == "Active"
    all_projects = db.get_all_projects(status="all")
    assert len(all_projects) == 2


def test_update_project(db):
    db.create_project({"id": "p1", "name": "Old"})
    assert db.update_project("p1", name="New", description="updated")
    proj = db.get_project("p1")
    assert proj["name"] == "New"
    assert proj["description"] == "updated"


def test_delete_project(db):
    db.create_project({"id": "p1", "name": "To Delete"})
    assert db.delete_project("p1")
    assert db.get_project("p1") is None


def test_default_project(db):
    db.create_project({"id": "p1", "name": "First", "status": "active"})
    db.create_project({"id": "p2", "name": "Second", "status": "active"})
    db.set_default_project("p2")
    assert db.get_default_project() == "p2"


def test_default_project_fallback_to_first(db):
    db.create_project({"id": "p1", "name": "Only", "status": "active"})
    assert db.get_default_project() == "p1"


# ── Conversations ─────────────────────────────────────────────────

def test_append_and_get_conversation(db):
    cid = db.append_message(
        conversation_id="conv_1",
        role="user",
        content="Hello",
        metadata={"project_name": "Test", "provider": "openai", "model": "gpt-4"},
    )
    assert cid == "conv_1"
    conv = db.get_conversation("conv_1")
    assert conv is not None
    assert len(conv["messages"]) == 1
    assert conv["messages"][0]["content"] == "Hello"
    assert conv["project_name"] == "Test"


def test_append_message_creates_new_conversation(db):
    cid = db.append_message(None, "user", "First message")
    assert cid  # auto-generated id
    conv = db.get_conversation(cid)
    assert conv is not None


def test_append_message_updates_existing(db):
    db.append_message("conv_1", "user", "Q1")
    db.append_message("conv_1", "assistant", "A1")
    conv = db.get_conversation("conv_1")
    assert len(conv["messages"]) == 2
    assert conv["last_message_role"] == "assistant"


def test_list_conversations_pagination(db):
    for i in range(5):
        db.append_message(f"c{i}", "user", f"Message {i}")
    result = db.list_conversations(page=1, page_size=2)
    assert result["total"] == 5
    assert len(result["items"]) == 2
    assert result["page"] == 1


def test_list_conversations_keyword_filter(db):
    db.append_message("c1", "user", "hello world", metadata={"title": "Greeting"})
    db.append_message("c2", "user", "goodbye", metadata={"title": "Farewell"})
    result = db.list_conversations(filters={"keyword": "greeting"})
    assert result["total"] == 1


def test_delete_conversation(db):
    db.append_message("conv_1", "user", "data")
    assert db.delete_conversation("conv_1")
    assert db.get_conversation("conv_1") is None


def test_rename_conversation(db):
    db.append_message("conv_1", "user", "data")
    assert db.rename_conversation("conv_1", "New Title")
    conv = db.get_conversation("conv_1")
    assert conv["title"] == "New Title"


# ── Process Templates ─────────────────────────────────────────────

def test_save_and_list_templates(db):
    assert db.save_process_template("My Template", {"selected_types": ["LSV"]})
    templates = db.list_process_templates()
    assert len(templates) == 1
    assert templates[0]["name"] == "My Template"
    assert templates[0]["state"]["selected_types"] == ["LSV"]


def test_template_overwrite(db):
    db.save_process_template("T1", {"v": 1})
    assert not db.save_process_template("T1", {"v": 2}, overwrite=False)
    assert db.save_process_template("T1", {"v": 2}, overwrite=True)
    t = db.list_process_templates()[0]
    assert t["state"]["v"] == 2


def test_delete_template(db):
    db.save_process_template("T1", {"v": 1})
    assert db.delete_process_template("T1")
    assert len(db.list_process_templates()) == 0


def test_cannot_delete_builtin_template(db):
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO process_templates (name, builtin, updated_at, state) VALUES (?,1,?,?)",
            ("Builtin", "", "{}"),
        )
    assert not db.delete_process_template("Builtin")


# ── JSON Migration ────────────────────────────────────────────────

def test_migrate_from_json_history(db, tmp_path):
    history_file = tmp_path / "history.json"
    history_file.write_text(json.dumps({
        "version": "1.0",
        "records": [
            {"timestamp": "2026-01-01", "type": "LSV", "file_path": "/a.txt",
             "file_name": "a.txt", "sample_name": "s1", "status": "success"},
            {"timestamp": "2026-01-02", "type": "CV", "file_path": "/b.txt",
             "file_name": "b.txt", "sample_name": "s2", "status": "success"},
        ],
    }), encoding="utf-8")

    counts = db.migrate_from_json(history_file=str(history_file))
    assert counts["history"] == 2
    assert len(db.get_all_history_records()) == 2
    assert db.is_migrated()


def test_migrate_from_json_projects(db, tmp_path):
    projects_file = tmp_path / "projects.json"
    projects_file.write_text(json.dumps({
        "projects": [
            {"id": "p1", "name": "Proj A", "status": "active"},
            {"id": "p2", "name": "Proj B", "status": "active"},
        ],
        "default_project": "p2",
    }), encoding="utf-8")

    counts = db.migrate_from_json(projects_file=str(projects_file))
    assert counts["projects"] == 2
    assert db.get_default_project() == "p2"


def test_migrate_missing_file_returns_zero(db, tmp_path):
    counts = db.migrate_from_json(history_file=str(tmp_path / "nonexistent.json"))
    assert counts["history"] == 0


def test_migrate_idempotent(db, tmp_path):
    history_file = tmp_path / "history.json"
    history_file.write_text(json.dumps({
        "records": [
            {"timestamp": "2026-01-01", "type": "LSV", "file_path": "/a.txt",
             "file_name": "a.txt", "sample_name": "s1"},
        ],
    }), encoding="utf-8")
    db.migrate_from_json(history_file=str(history_file))
    db.migrate_from_json(history_file=str(history_file))
    # INSERT OR REPLACE means no duplicates
    assert len(db.get_all_history_records()) == 1


# ── Thread safety ─────────────────────────────────────────────────

def test_concurrent_writes(db):
    errors = []

    def writer(n):
        try:
            for i in range(20):
                db.add_history_record(_sample_record(
                    file_path=f"/thread{n}/f{i}.txt",
                    timestamp=f"2026-03-0{n % 9 + 1} {10+i}:00:00",
                ))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread errors: {errors}"
    records = db.get_all_history_records()
    assert len(records) == 80  # 4 threads × 20 records


# ── Transaction rollback ──────────────────────────────────────────

def test_transaction_rollback_on_error(db):
    db.add_history_record(_sample_record())
    try:
        with db.transaction() as conn:
            conn.execute("DELETE FROM history_records")
            raise ValueError("force rollback")
    except ValueError:
        pass
    assert len(db.get_all_history_records()) == 1


# ── _to_json_safe helpers ─────────────────────────────────────────

def test_to_json_safe_numpy_array():
    try:
        import numpy as np
        arr = np.array([1.0, 2.0, 3.0])
        result = _to_json_safe(arr)
        assert result == [1.0, 2.0, 3.0]
    except ImportError:
        pytest.skip("numpy not installed")


def test_to_json_safe_path():
    result = _to_json_safe(Path("/data/output"))
    assert isinstance(result, str)
    assert "data" in result


def test_to_json_safe_nested():
    data = {"a": [1, {"b": Path("/x")}], "c": None}
    result = _to_json_safe(data)
    assert result["a"][1]["b"]  # converted to string
    assert result["c"] is None


def test_json_loads_fallback():
    assert _json_loads(None, []) == []
    assert _json_loads("", {}) == {}
    assert _json_loads("not json", "default") == "default"
    assert _json_loads('{"a": 1}') == {"a": 1}
