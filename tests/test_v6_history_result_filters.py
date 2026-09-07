"""Full-database result search, inclusive date filters, and cursor contracts."""

from __future__ import annotations

from unittest.mock import MagicMock
from urllib.parse import urlencode

import pytest

from electrochem_v6.server.routes_get import dispatch_get
from electrochem_v6.store import history
from electrochem_v6.store.database import Database


@pytest.fixture
def db(tmp_path, monkeypatch):
    database = Database(str(tmp_path / "filtered-history.db"))
    monkeypatch.setattr(history, "get_database", lambda: database)
    yield database
    database.close_all()


def add_record(db, key, **overrides):
    record = {
        "timestamp": "2026-09-07 12:00:00",
        "type": "LSV",
        "sample_name": "NiFe",
        "file_name": f"{key}.txt",
        "file_path": f"D:/measurements/{key}.txt",
        "project_id": "project-a",
        "run_id": f"run-{key}",
        "results": {"potential_10": 0.35},
        "data": {"large_curve": list(range(50))},
    }
    record.update(overrides)
    db.add_history_record(record)


def request(**query):
    handler = MagicMock()
    handler.path = "/api/v1/history?" + urlencode(query)
    assert dispatch_get(handler)
    handler._send_json.assert_called_once()
    return handler._send_json.call_args.args


def test_search_filters_complete_database_before_count_and_cursor_limit(db):
    # Matching results are older than a complete unfiltered API page.
    for index in range(125):
        add_record(db, f"unrelated-{index}", timestamp="2026-09-08 00:00:00", sample_name="Other")
    for index in range(7):
        add_record(db, f"match-{index}")
    add_record(db, "archived", archived=True)
    add_record(db, "wrong-project", project_id="project-b")
    add_record(db, "wrong-type", type="CV")
    add_record(db, "too-old", timestamp="2026-09-06 23:59:59")
    filters = {
        "project": "project-a", "q": "nife", "type": "lsv",
        "date_from": "2026-09-07", "date_to": "2026-09-07", "limit": 3,
    }
    seen = []
    cursor = None
    while True:
        code, page = request(**filters, **({"cursor": cursor} if cursor else {}))
        assert code == 200
        assert page["status"] == "success"
        assert page["total"] == 7
        assert page["limit"] == 3
        assert all("data" not in record for record in page["records"])
        seen.extend(record["run_id"].removeprefix("run-") for record in page["records"])
        if not page["has_more"]:
            assert page["next_cursor"] is None
            break
        assert page["next_cursor"] and page["next_cursor"] != cursor
        cursor = page["next_cursor"]
    assert seen == [f"match-{index}" for index in range(6, -1, -1)]
    assert len(seen) == len(set(seen))
    code, archived = request(**filters, include_archived=1)
    assert code == 200
    assert archived["total"] == 8


def test_search_matches_sample_or_basename_but_not_parent_directory(db):
    add_record(db, "sample", sample_name="镍铁_% catalyst")
    add_record(db, "filename", sample_name="Other", file_name="测量_LSV.txt")
    add_record(db, "windows", sample_name="Other", file_name=None, file_path=r"D:\raw\fallback_LSV.txt")
    add_record(db, "posix", sample_name="Other", file_name="", file_path="/raw/fallback_CV.txt")
    add_record(db, "parent", sample_name="Other", file_name=None, file_path="/fallback_LSV/other.txt")
    assert [r["run_id"].removeprefix("run-") for r in db.filter_history(q=" 镍铁_% ")] == ["sample"]
    assert [r["run_id"].removeprefix("run-") for r in db.filter_history(q="测量_LSV")] == ["filename"]
    assert [r["run_id"].removeprefix("run-") for r in db.filter_history(q="fallback_LSV")] == ["windows"]
    assert [r["run_id"].removeprefix("run-") for r in db.filter_history(q="fallback_CV")] == ["posix"]


@pytest.mark.parametrize("search", ["%", "_", "\\", "' OR 1=1 --"])
def test_search_wildcards_and_sql_syntax_are_literal(db, search):
    add_record(db, "match", sample_name=f"prefix {search} suffix")
    add_record(db, "unrelated", sample_name="prefix arbitrary suffix")
    code, page = request(q=search)
    assert code == 200
    assert page["total"] == 1
    assert [record["run_id"].removeprefix("run-") for record in page["records"]] == ["match"]
    assert db.filter_history_page()["total"] == 2


def test_date_bounds_include_entire_days_and_both_timestamp_formats(db):
    dates = {
        "before": "2026-09-06T23:59:59.999999",
        "start": "2026-09-07 00:00:00",
        "start-iso": "2026-09-07T00:00:00+08:00",
        "end": "2026-09-08 23:59:59.999999",
        "end-iso": "2026-09-08T23:59:59.999999+08:00",
        "after": "2026-09-09 00:00:00",
        "undated": None,
    }
    for key, timestamp in dates.items():
        add_record(db, key, timestamp=timestamp)
    page = db.filter_history_page(date_from="2026-09-07", date_to="2026-09-08")
    assert {record["run_id"].removeprefix("run-") for record in page["records"]} == {"start", "start-iso", "end", "end-iso"}
    assert page["total"] == 4
    assert db.filter_history_page(date_from="2026-09-09")["total"] == 1
    assert db.filter_history_page(date_to="2026-09-06")["total"] == 1


@pytest.mark.parametrize("filters", [
    {"date_from": "2026-9-01"},
    {"date_from": "20260901"},
    {"date_from": "2026-W36-1"},
    {"date_from": "2026-02-29"},
    {"date_to": "2026-09-07T23:59:59"},
    {"date_to": "not-a-date"},
    {"date_from": "2026-09-08", "date_to": "2026-09-07"},
])
def test_invalid_dates_and_reversed_range_return_400(db, filters):
    add_record(db, "existing")
    code, page = request(**filters)
    assert code == 400
    assert page["status"] == "error"
    assert "date_" in page["message"]
    assert page["records"] == []
    assert history.list_history(**filters)["status"] == "error"


def test_filters_compose_with_existing_metric_archival_and_project_filters(db):
    add_record(db, "in-range", archived=True)
    add_record(db, "wrong-metric", archived=True, results={"potential_10": 0.9})
    add_record(db, "wrong-project", archived=True, project_id="project-b")
    filters = {
        "project_id": "project-a", "include_archived": True, "q": "NiFe", "data_type": "LSV",
        "date_from": "2026-09-07", "date_to": "2026-09-07",
        "metric_key": "potential_10", "metric_min": 0.3, "metric_max": 0.4,
    }
    page = history.list_history_page(**filters)
    full = history.list_history(**filters, limit=None)
    assert page["status"] == full["status"] == "success"
    assert page["total"] == 1
    assert [record["run_id"].removeprefix("run-") for record in page["records"]] == ["in-range"]
    assert [record["run_id"].removeprefix("run-") for record in full["records"]] == ["in-range"]


def test_omitted_and_empty_filters_preserve_existing_api_contract(db):
    add_record(db, "first")
    add_record(db, "second", type="CV")
    add_record(db, "archived", archived=True)
    original_code, original = request(project="project-a", limit=1)
    empty_code, empty = request(project="project-a", limit=1, q="  ", date_from="", date_to="")
    assert original_code == empty_code == 200
    assert original == empty
    assert original["total"] == 2
    assert original["has_more"] is True
    code, page = request(project="project-a", q="absent")
    assert code == 200
    assert page["records"] == []
    assert page["total"] == 0
    assert page["has_more"] is False
    assert page["next_cursor"] is None


def test_filtered_page_rejects_invalid_cursor(db):
    code, page = request(q="NiFe", cursor="invalid")
    assert code == 400
    assert page["status"] == "error"
    assert "cursor" in page["message"]
