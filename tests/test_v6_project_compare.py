import os

import pytest

from electrochem_v6.core import project_compare


class _FakeHistoryManager:
    def __init__(self, records):
        self._records = records

    def get_all_records(self):
        return list(self._records)


def _lsv_record(sample_name, timestamp, *, archived=False):
    return {
        "timestamp": timestamp,
        "sample_name": sample_name,
        "file_name": f"LSV_{sample_name}",
        "type": "LSV",
        "status": "success",
        "project_id": "project-1",
        "project_name": "Compare Project",
        "archived": archived,
        "results": {
            "potential_at_10.0": 0.4,
            "potential_at_50.0": 0.5,
            "overpotential_at_10.0": 300.0,
            "overpotential_at_50.0": 410.0,
            "tafel_slope": 90.0,
        },
        "data": {
            "potential_original": [-0.3, -0.2, -0.1],
            "potential_compensated": [-0.29, -0.19, -0.09],
            "current": [1.0, 5.0, 10.0],
        },
    }


def test_get_project_lsv_target_currents_ignores_archived_by_default(monkeypatch):
    records = [
        _lsv_record("active", "2026-03-01 10:00:00"),
        _lsv_record("archived", "2026-03-01 11:00:00", archived=True),
    ]
    records[1]["results"] = {"potential_at_100.0": 0.8, "overpotential_at_100.0": 600.0}
    monkeypatch.setattr(project_compare, "get_history_store", lambda: _FakeHistoryManager(records))

    payload = project_compare.get_project_lsv_target_currents(project_id="project-1")

    assert payload["status"] == "success"
    assert payload["potential_target_currents"] == [10.0, 50.0]
    assert payload["overpotential_target_currents"] == [10.0, 50.0]
    assert payload["target_currents"] == [10.0, 50.0]


def test_build_project_lsv_compare_plot_and_latest_roundtrip(tmp_path, monkeypatch):
    records = [
        _lsv_record("sample-a", "2026-03-01 10:00:00"),
        _lsv_record("sample-b", "2026-03-01 10:05:00"),
    ]
    monkeypatch.setattr(project_compare, "get_history_store", lambda: _FakeHistoryManager(records))

    payload = project_compare.build_project_lsv_compare_plot(
        project_id="project-1",
        selected_samples=["sample-a", "sample-b"],
        output_dir=str(tmp_path),
    )

    assert payload["status"] == "success"
    plot = payload["plot"]
    assert plot["trace_count"] == 2
    assert plot["selected_samples"] == ["sample-a", "sample-b"]
    assert str(plot["image_data_url"]).startswith("data:image/png;base64,")
    assert os.path.exists(plot["plot_path"])

    latest = project_compare.get_latest_project_lsv_compare_plot(project_id="project-1", output_dir=str(tmp_path))

    assert latest["status"] == "success"
    assert latest["plot"]["file_name"] == plot["file_name"]
    assert str(latest["plot"]["image_data_url"]).startswith("data:image/png;base64,")


def test_build_project_lsv_compare_bar_uses_requested_target_current(tmp_path, monkeypatch):
    records = [
        _lsv_record("sample-a", "2026-03-01 10:00:00"),
        _lsv_record("sample-b", "2026-03-01 10:05:00"),
    ]
    monkeypatch.setattr(project_compare, "get_history_store", lambda: _FakeHistoryManager(records))

    payload = project_compare.build_project_lsv_compare_plot(
        project_id="project-1",
        selected_samples=["sample-a", "sample-b"],
        chart_type="bar",
        metric_key="potential_at_target",
        target_current=50,
        output_dir=str(tmp_path),
    )

    assert payload["status"] == "success"
    plot = payload["plot"]
    assert plot["chart_type"] == "bar"
    assert plot["target_current"] == pytest.approx(50.0)
    assert plot["metric_label"] == "E@50 (V)"
    assert os.path.exists(plot["plot_path"])
