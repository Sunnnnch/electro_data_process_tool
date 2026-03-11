"""Tests for store/history.py — pure functions and filter logic."""
from __future__ import annotations

from electrochem_v6.store.history import (
    _filter_records,
    _normalize_history_payload,
    _record_key,
)

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _normalize_history_payload                                             ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestNormalizeHistoryPayload:
    def test_list_input(self):
        result = _normalize_history_payload([{"a": 1}])
        assert result["records"] == [{"a": 1}]
        assert result["version"] == "1.0"

    def test_dict_with_records(self):
        result = _normalize_history_payload({"records": [{"b": 2}], "version": "2.0"})
        assert result["records"] == [{"b": 2}]
        assert result["version"] == "2.0"

    def test_dict_without_records(self):
        result = _normalize_history_payload({"foo": "bar"})
        assert result["records"] == []
        assert result["version"] == "1.0"

    def test_dict_records_not_list(self):
        result = _normalize_history_payload({"records": "oops"})
        assert result["records"] == []

    def test_non_dict_non_list(self):
        result = _normalize_history_payload(42)
        assert result["records"] == []

    def test_none_input(self):
        result = _normalize_history_payload(None)
        assert result["records"] == []


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _record_key                                                            ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestRecordKey:
    def test_full_record(self):
        rec = {"timestamp": "2024-01-01 12:00", "type": "LSV", "file_path": "/data/lsv.txt"}
        key = _record_key(rec)
        assert key == "2024-01-01 12:00|LSV|/data/lsv.txt"

    def test_file_name_fallback(self):
        rec = {"timestamp": "T1", "type": "CV", "file_name": "cv.txt"}
        assert _record_key(rec) == "T1|CV|cv.txt"

    def test_sample_name_fallback(self):
        rec = {"timestamp": "T1", "type": "EIS", "sample_name": "sample_A"}
        assert _record_key(rec) == "T1|EIS|sample_A"

    def test_empty_record(self):
        assert _record_key({}) == "||"


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _filter_records                                                        ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

SAMPLE_RECORDS = [
    {"timestamp": "T1", "type": "LSV", "project_id": "P1", "results": {"eta": 0.30}},
    {"timestamp": "T2", "type": "CV",  "project_id": "P1", "results": {"area": 1.5}},
    {"timestamp": "T3", "type": "EIS", "project_id": "P2", "results": {"Rs": 8.0}},
    {"timestamp": "T4", "type": "LSV", "project_id": "P1", "archived": True, "results": {"eta": 0.50}},
    {"timestamp": "T5", "type": "ECSA", "project_id": "P2", "results": {"Cdl": 0.02}},
]


class TestFilterRecords:
    def test_no_filter(self):
        # archived=False by default → T4 excluded
        result = _filter_records(SAMPLE_RECORDS)
        assert len(result) == 4

    def test_include_archived(self):
        result = _filter_records(SAMPLE_RECORDS, include_archived=True)
        assert len(result) == 5

    def test_by_project(self):
        result = _filter_records(SAMPLE_RECORDS, project_id="P1")
        types = {r["type"] for r in result}
        assert "EIS" not in types
        assert len(result) == 2  # T1, T2 (T4 archived)

    def test_by_project_with_archived(self):
        result = _filter_records(SAMPLE_RECORDS, project_id="P1", include_archived=True)
        assert len(result) == 3  # T1, T2, T4

    def test_by_data_type(self):
        result = _filter_records(SAMPLE_RECORDS, data_type="LSV")
        assert len(result) == 1  # T1 only (T4 archived)

    def test_by_data_type_case_insensitive(self):
        result = _filter_records(SAMPLE_RECORDS, data_type="lsv")
        assert len(result) == 1

    def test_metric_min(self):
        result = _filter_records(SAMPLE_RECORDS, metric_key="eta", metric_min=0.25)
        assert len(result) == 1  # T1 has eta=0.30

    def test_metric_max(self):
        result = _filter_records(SAMPLE_RECORDS, metric_key="Rs", metric_max=10.0)
        assert len(result) == 1  # T3 has Rs=8.0

    def test_metric_range(self):
        result = _filter_records(
            SAMPLE_RECORDS, metric_key="eta", metric_min=0.20, metric_max=0.40,
        )
        assert len(result) == 1

    def test_metric_key_missing(self):
        """Records without the metric key are excluded."""
        result = _filter_records(SAMPLE_RECORDS, metric_key="nonexistent", metric_min=0.0)
        assert len(result) == 0

    def test_non_dict_items_skipped(self):
        records = [{"type": "LSV", "timestamp": "T"}, "not a dict", 42]
        result = _filter_records(records)
        assert len(result) == 1

    def test_combined_filters(self):
        result = _filter_records(
            SAMPLE_RECORDS,
            project_id="P1",
            data_type="LSV",
            include_archived=True,
            metric_key="eta",
            metric_min=0.40,
        )
        assert len(result) == 1  # only T4 (eta=0.50, archived but included)
