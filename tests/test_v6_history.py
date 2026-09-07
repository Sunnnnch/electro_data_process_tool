"""Tests for the SQLite-backed history service adapter."""

from __future__ import annotations

import electrochem_v6.store.history as history


class FakeDatabase:
    def __init__(self) -> None:
        self.filter_kwargs = None
        self.stats_kwargs = None
        self.update_result = 1
        self.update_calls = []
        self.attach_kwargs = None

    def filter_history(self, **kwargs):
        self.filter_kwargs = kwargs
        return [
            {"timestamp": "2026-07-22 10:00:00", "type": "LSV", "project_id": "P1"},
            {"timestamp": "2026-07-21 10:00:00", "type": "CV", "project_id": "P1"},
        ]

    def get_history_stats(self, **kwargs):
        self.stats_kwargs = kwargs
        return {"total": 2, "by_type": {"LSV": 1, "CV": 1}}

    def update_history_by_key(self, history_key, action):
        self.update_calls.append((history_key, action))
        return self.update_result

    def attach_run_outputs(self, **kwargs):
        self.attach_kwargs = kwargs
        return 2


def test_list_history_forwards_sqlite_filters(monkeypatch):
    database = FakeDatabase()
    monkeypatch.setattr(history, "get_database", lambda: database)

    response = history.list_history(
        project_id="P1",
        limit=25,
        include_archived=True,
        metric_key="eta",
        metric_min=0.1,
        metric_max=0.5,
        data_type="LSV",
    )

    assert response["status"] == "success"
    assert len(response["records"]) == 2
    assert database.filter_kwargs == {
        "project_id": "P1",
        "include_archived": True,
        "data_type": "LSV",
        "metric_key": "eta",
        "metric_min": 0.1,
        "metric_max": 0.5,
        "limit": 25,
    }


def test_stats_and_project_report_use_public_database_contract(monkeypatch):
    database = FakeDatabase()
    monkeypatch.setattr(history, "get_database", lambda: database)

    stats = history.get_stats(project_id="P1", include_archived=False)
    report = history.build_project_report(" P1 ", include_archived=True)

    assert stats == {
        "status": "success",
        "data": {"total": 2, "by_type": {"LSV": 1, "CV": 1}},
    }
    assert report["status"] == "success"
    assert report["report"]["project_id"] == "P1"
    assert report["report"]["generated_at"] == "2026-07-22 10:00:00"
    assert report["report"]["stats"]["total"] == 2
    assert database.stats_kwargs == {"project_id": "P1", "include_archived": True}


def test_history_update_rejects_empty_and_reports_not_found(monkeypatch):
    database = FakeDatabase()
    monkeypatch.setattr(history, "get_database", lambda: database)

    assert history.archive_history_record(" ")["status"] == "error"
    database.update_result = 0
    missing = history.delete_history_record("missing")

    assert missing == {
        "status": "error",
        "message": "history record not found",
        "updated": 0,
    }
    assert database.update_calls == [("missing", "delete")]


def test_archive_and_delete_forward_actions(monkeypatch):
    database = FakeDatabase()
    monkeypatch.setattr(history, "get_database", lambda: database)

    archived = history.archive_history_record("run-a")
    deleted = history.delete_history_record("run-b")

    assert archived == {"status": "success", "updated": 1, "action": "archive"}
    assert deleted == {"status": "success", "updated": 1, "action": "delete"}
    assert database.update_calls == [("run-a", "archive"), ("run-b", "delete")]


def test_attach_run_outputs_normalizes_files(monkeypatch):
    database = FakeDatabase()
    monkeypatch.setattr(history, "get_database", lambda: database)

    response = history.attach_run_outputs(
        run_id=" run-1 ",
        output_files=[" result.csv ", "", "plot.png"],
        summary_path="summary.json",
        quality_summary={"passed": 2},
    )

    assert response == {"status": "success", "updated": 2}
    assert database.attach_kwargs == {
        "run_id": "run-1",
        "output_files": ["result.csv", "plot.png"],
        "summary_path": "summary.json",
        "quality_summary": {"passed": 2},
    }
    assert history.attach_run_outputs(run_id="", output_files=[])["status"] == "error"


def test_project_report_requires_project_id():
    assert history.build_project_report(" ") == {
        "status": "error",
        "message": "missing project id",
    }
