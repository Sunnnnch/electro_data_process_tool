"""Tests for the SQLite storage backend (database.py)."""

import json
import os
import sqlite3
import threading
from pathlib import Path

import pytest

# Force SQLite backend for these tests
from electrochem_v6.store.database import SCHEMA_VERSION, Database, _json_loads, _to_json_safe

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
    Database(db_path)  # side-effect: creates file
    assert os.path.exists(db_path)


def test_schema_version_recorded(db):
    with db.read() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    assert row is not None
    assert row["value"] == str(SCHEMA_VERSION)


def test_schema_v3_migration_links_existing_history_to_samples(tmp_path):
    db_path = tmp_path / "legacy-v3.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta (key, value) VALUES ('schema_version', '3');
        CREATE TABLE history_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_key TEXT UNIQUE,
            timestamp TEXT,
            type TEXT,
            file_path TEXT,
            file_name TEXT,
            sample_name TEXT,
            project_id TEXT,
            run_id TEXT,
            folder_path TEXT,
            archived INTEGER DEFAULT 0,
            results TEXT DEFAULT '{}',
            output_files TEXT DEFAULT '[]',
            summary_path TEXT,
            source_archive_path TEXT,
            artifact_root TEXT,
            artifact_owner TEXT DEFAULT 'external',
            quality_summary TEXT DEFAULT '{}',
            data TEXT DEFAULT '{}'
        );
        INSERT INTO history_records
            (record_key, timestamp, type, file_path, file_name, sample_name, project_id, run_id)
        VALUES
            ('legacy-record', '2026-08-01 10:00:00', 'LSV', 'D:/raw/a.txt', 'a.txt', 'A', 'p1', 'r1');
        """
    )
    conn.commit()
    conn.close()

    migrated = Database(str(db_path))
    with migrated.read() as check:
        version = check.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        history = check.execute("SELECT sample_id FROM history_records").fetchone()
        sample = check.execute("SELECT id, project_id, name FROM project_samples").fetchone()
    assert version == str(SCHEMA_VERSION)
    assert sample["project_id"] == "p1"
    assert sample["name"] == "A"
    assert history["sample_id"] == sample["id"]


def test_tables_exist(db):
    with db.read() as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    for expected in (
        "meta",
        "history_records",
        "history_metrics",
        "projects",
        "project_samples",
        "conversations",
        "conversation_messages",
        "process_templates",
        "processing_jobs",
    ):
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


def test_ambiguous_legacy_history_key_cannot_delete_multiple_runs(db):
    first = _sample_record(run_id="run_1")
    second = _sample_record(run_id="run_2")
    db.add_history_record(first)
    db.add_history_record(second)
    legacy_key = f"{first['timestamp']}|{first['type']}|{first['file_path']}"

    assert db.update_history_by_key(legacy_key, "delete") == 0
    records = db.get_all_history_records()
    assert {record["run_id"] for record in records} == {"run_1", "run_2"}

    exact_key = next(record["record_key"] for record in records if record["run_id"] == "run_1")
    assert db.update_history_by_key(exact_key, "delete") == 1
    assert [record["run_id"] for record in db.get_all_history_records()] == ["run_2"]


def test_filter_history_by_project(db):
    db.add_history_record(_sample_record(project_id="proj_a"))
    db.add_history_record(_sample_record(project_id="proj_b", file_path="/other.txt", timestamp="2026-03-01 13:00:00"))
    result = db.filter_history(project_id="proj_a")
    assert len(result) == 1
    assert result[0]["project_id"] == "proj_a"


def test_sample_note_and_tags_are_shared_across_linked_raw_records(db):
    db.add_history_record(_sample_record(file_path="/raw/sample_a_lsv.txt", run_id="run_lsv"))
    db.add_history_record(
        _sample_record(
            file_path="/raw/sample_a_cv.txt",
            file_name="sample_a_cv.txt",
            run_id="run_cv",
            type="CV",
        )
    )

    samples = db.list_project_samples("proj_1")
    assert len(samples) == 1
    sample = samples[0]
    assert sample["name"] == "sample_a"
    assert sample["data_count"] == 2
    assert set(sample["data_types"]) == {"LSV", "CV"}

    assert db.update_project_sample(
        "proj_1",
        sample["id"],
        note="0.5 M KOH，负载量 0.2 mg/cm²",
        tags=["对照组", "重复实验"],
    )
    records = db.filter_history(project_id="proj_1")
    assert {record["sample_id"] for record in records} == {sample["id"]}
    assert {record["sample_note"] for record in records} == {"0.5 M KOH，负载量 0.2 mg/cm²"}
    assert all(record["sample_tags"] == ["对照组", "重复实验"] for record in records)


def test_same_sample_name_in_different_source_folders_gets_separate_notes(db):
    db.add_history_record(
        _sample_record(file_path="/batch-a/sample_a_lsv.txt", run_id="run-a")
    )
    db.add_history_record(
        _sample_record(file_path="/batch-b/sample_a_lsv.txt", run_id="run-b")
    )

    samples = db.list_project_samples("proj_1")
    assert len(samples) == 2
    assert {sample["batch_id"].replace("\\", "/") for sample in samples} == {
        "/batch-a",
        "/batch-b",
    }
    assert len({sample["id"] for sample in samples}) == 2


def test_filter_history_without_limit_returns_more_than_api_page_cap(db):
    for index in range(505):
        db.add_history_record(
            _sample_record(
                timestamp=f"2026-03-01 12:{index // 60:02d}:{index % 60:02d}",
                file_path=f"/data/{index}.txt",
                run_id=f"run_{index}",
            )
        )

    assert len(db.filter_history(project_id="proj_1", limit=500)) == 500
    assert len(db.filter_history(project_id="proj_1", limit=None)) == 505


def test_history_page_uses_stable_cursor_and_omits_heavy_data(db):
    for index in range(5):
        db.add_history_record(
            _sample_record(
                timestamp="2026-03-01 12:00:00",
                file_path=f"/data/{index}.txt",
                run_id=f"run_{index}",
                data={"raw": list(range(100))},
            )
        )

    first = db.filter_history_page(project_id="proj_1", limit=2)
    assert first["total"] == 5
    assert first["has_more"] is True
    assert first["next_cursor"]
    assert len(first["records"]) == 2
    assert all("data" not in record for record in first["records"])

    second = db.filter_history_page(
        project_id="proj_1",
        limit=2,
        cursor=first["next_cursor"],
    )
    assert len(second["records"]) == 2
    assert {
        record["record_key"] for record in first["records"]
    }.isdisjoint(record["record_key"] for record in second["records"])


def test_history_page_rejects_invalid_cursor(db):
    db.add_history_record(_sample_record())
    with pytest.raises(ValueError, match="cursor"):
        db.filter_history_page(cursor="not-a-valid-cursor")


def test_history_detail_and_archive_iterator_preserve_provenance(db):
    db.add_history_record(
        _sample_record(
            run_id="run_provenance",
            data={"potential": [0.1, 0.2]},
            output_files=["/managed/result.png"],
        )
    )
    assert db.attach_run_provenance(
        "run_provenance",
        source_archive_path="/managed/source/upload.zip",
        artifact_root="/managed/run_provenance",
    ) == 1
    key = db.get_all_history_records()[0]["record_key"]

    detail = db.get_history_record(key)
    assert detail is not None
    assert detail["data"]["potential"] == [0.1, 0.2]
    assert detail["source_archive_path"].endswith("upload.zip")

    exported = list(db.iter_history_archive_records(project_id="proj_1", batch_size=1))
    assert len(exported) == 1
    assert exported[0]["source_archive_path"].endswith("upload.zip")
    assert "data" not in exported[0]


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


def test_metric_filter_is_applied_before_limit(db):
    db.add_history_record(_sample_record(
        timestamp="2025-01-01 00:00:00",
        file_path="/matching.txt",
        run_id="matching",
        results={"tafel_slope": 75.0},
    ))
    for i in range(120):
        db.add_history_record(_sample_record(
            timestamp=f"2026-03-{(i % 28) + 1:02d} 12:{i % 60:02d}:00",
            file_path=f"/newer-{i}.txt",
            run_id=f"newer-{i}",
            results={"tafel_slope": 150.0},
        ))
    result = db.filter_history(metric_key="tafel_slope", metric_max=100.0, limit=10)
    assert [record["run_id"] for record in result] == ["matching"]


def test_history_records_without_run_id_do_not_overwrite_distinct_results(db):
    first = _sample_record(run_id=None, results={"tafel_slope": 80.0})
    second = _sample_record(run_id=None, results={"tafel_slope": 90.0})
    db.add_history_record(first)
    db.add_history_record(second)
    assert len(db.get_all_history_records()) == 2


def test_archive_and_delete_history(db):
    db.add_history_record(_sample_record())
    key = "2026-03-01 12:00:00|LSV|/data/test.txt|run_1"
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
    db.add_history_record(_sample_record(type="COUPLED", file_path="/products.csv", timestamp="2026-03-04 01:00:00"))
    stats = db.get_history_stats()
    assert stats["total_files"] == 4
    assert stats["lsv_count"] == 1
    assert stats["cv_count"] == 1
    assert stats["eis_count"] == 1
    assert stats["ecsa_count"] == 0
    assert stats["coupled_count"] == 1


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
    assert db.get_project("p1")["status"] == "archived"
    assert db.get_all_projects("active") == []


def test_delete_project_preserves_linked_history(db):
    db.create_project({"id": "p1", "name": "With History"})
    db.add_history_record(_sample_record(project_id="p1"))
    assert db.delete_project("p1")
    assert db.filter_history(project_id="p1")


def test_repair_orphan_project_links(db):
    db.add_history_record(_sample_record(project_id="missing-project"))
    assert db.repair_orphan_project_links() == ["missing-project"]
    recovered = db.get_project("missing-project")
    assert recovered is not None
    assert recovered["status"] == "archived"
    assert "recovered" in recovered["tags"]


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


def test_messages_are_stored_as_rows_not_rewritten_json_blob(db):
    db.append_message("conv_1", "user", "Q1")
    db.append_message("conv_1", "assistant", "A1")
    with db.read() as conn:
        blob = conn.execute(
            "SELECT messages FROM conversations WHERE conversation_id='conv_1'"
        ).fetchone()[0]
        message_count = conn.execute(
            "SELECT COUNT(*) FROM conversation_messages WHERE conversation_id='conv_1'"
        ).fetchone()[0]
    assert blob == "[]"
    assert message_count == 2


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
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM conversation_messages").fetchone()[0] == 0


def test_delete_conversation_removes_linked_agent_jobs_only(db):
    db.append_message("conv_1", "user", "data")
    db.create_processing_job(
        "agent-old",
        kind="agent",
        payload={"conversation_id": "conv_1", "message": "secret"},
    )
    db.update_processing_job(
        "agent-old",
        status="succeeded",
        result={"conversation_id": "conv_1", "agent_reply": "answer"},
    )
    db.create_processing_job("process-keep", kind="process", payload={"folder_path": "/data"})

    assert db.delete_conversation("conv_1")
    assert db.get_processing_job("agent-old") is None
    assert db.get_processing_job("process-keep") is not None


def test_prune_processing_jobs_keeps_newest_terminal_rows_and_active_work(db):
    for index in range(5):
        job_id = f"done-{index}"
        db.create_processing_job(job_id, kind="agent", payload={})
        db.update_processing_job(job_id, status="succeeded")
    db.create_processing_job("active", kind="agent", payload={})
    db.update_processing_job("active", status="running")

    assert db.prune_processing_jobs(kind="agent", keep=2) == 3
    jobs = db.list_processing_jobs(limit=20)
    assert {job["job_id"] for job in jobs} == {"done-3", "done-4", "active"}


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


def test_concurrent_template_writes_do_not_lose_distinct_templates(db):
    errors = []
    start = threading.Event()

    def writer(index):
        start.wait(timeout=1)
        try:
            assert db.save_process_template(f"T{index}", {"index": index})
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    assert {item["name"] for item in db.list_process_templates()} == {
        f"T{index}" for index in range(8)
    }


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


def test_current_template_json_migration_overwrites_stale_user_copy_once(db, tmp_path):
    template_file = tmp_path / "process_templates.json"
    db.save_process_template("Current", {"values": {"plot-font-size": "12"}})
    template_file.write_text(
        json.dumps(
            {
                "templates": [
                    {
                        "name": "Current",
                        "builtin": False,
                        "updated_at": "2026-07-22 12:00:00",
                        "state": {"values": {"plot-font-size": "18"}},
                    },
                    {
                        "name": "Builtin",
                        "builtin": True,
                        "state": {"selected_types": ["LSV"]},
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = db.migrate_process_templates_from_json(str(template_file))

    assert report == {
        "complete": True,
        "already_migrated": False,
        "templates": 1,
        "ignored": 1,
        "errors": [],
    }
    saved = next(item for item in db.list_process_templates() if item["name"] == "Current")
    assert saved["state"]["values"]["plot-font-size"] == "18"

    template_file.write_text(
        json.dumps(
            {
                "templates": [
                    {
                        "name": "Current",
                        "state": {"values": {"plot-font-size": "24"}},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    second = db.migrate_process_templates_from_json(str(template_file))
    assert second["already_migrated"] is True
    saved = next(item for item in db.list_process_templates() if item["name"] == "Current")
    assert saved["state"]["values"]["plot-font-size"] == "18"


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
    assert counts["complete"] is False
    assert not db.is_migrated()


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


def test_migrate_legacy_duplicate_project_names_preserves_both_projects(db, tmp_path):
    projects_file = tmp_path / "projects.json"
    projects_file.write_text(
        json.dumps(
            {
                "projects": [
                    {"id": "p1", "name": "Demo", "status": "active"},
                    {"id": "p2", "name": "demo", "status": "archived"},
                ]
            }
        ),
        encoding="utf-8",
    )

    report = db.migrate_from_json(projects_file=str(projects_file))

    assert report["complete"] is True
    assert report["projects"] == 2
    assert report["renamed_projects"] == [{"id": "p2", "from": "demo", "to": "demo (2)"}]
    assert {project["id"] for project in db.get_all_projects("all")} == {"p1", "p2"}


def test_migrate_invalid_item_is_atomic_and_not_marked_complete(db, tmp_path):
    history_file = tmp_path / "history.json"
    history_file.write_text(json.dumps({
        "records": [
            {"timestamp": "2026-01-01", "type": "LSV", "file_path": "/a.txt"},
            "invalid-record",
        ],
    }), encoding="utf-8")
    report = db.migrate_from_json(history_file=str(history_file))
    assert report["complete"] is False
    assert report["skipped"]["history"] == 1
    assert db.get_all_history_records() == []
    assert not db.is_migrated()


def test_migrate_conversation_messages_to_normalized_table(db, tmp_path):
    conversation_file = tmp_path / "conversations.json"
    conversation_file.write_text(json.dumps({
        "conversations": [{
            "conversation_id": "legacy-conversation",
            "title": "Legacy",
            "messages": [
                {"role": "user", "content": "question"},
                {"role": "assistant", "content": "answer"},
            ],
        }],
    }), encoding="utf-8")
    report = db.migrate_from_json(conversations_file=str(conversation_file))
    assert report["complete"] is True
    assert [item["content"] for item in db.get_conversation("legacy-conversation")["messages"]] == [
        "question",
        "answer",
    ]


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
