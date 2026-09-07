"""Tests for LSV history helper payloads."""

from __future__ import annotations

import pytest

from electrochem_v6.core.processing_lsv_history import (
    add_lsv_history_record,
    build_lsv_history_data,
    build_lsv_history_record,
)


def test_build_lsv_history_record_contains_searchable_metrics():
    record = build_lsv_history_record(
        sample_name="sample",
        file_stem="LSV_demo",
        file_path="/data/LSV_demo.txt",
        params={"run_id": "run-1"},
        target_potentials_original={10.0: 0.412, 50.0: 0.6},
        target_overpotentials_original={10.0: 320.0},
        overpotential_enabled=True,
        equilibrium_potential=0.092,
        slope_mVdec=88.0,
        ir_compensation=5.0,
    )

    assert record["type"] == "LSV"
    assert record["run_id"] == "run-1"
    assert record["results"]["potential_10"] == pytest.approx(0.412)
    assert record["results"]["potential_at_50.0"] == pytest.approx(0.6)
    assert record["results"]["overpotential_10"] == pytest.approx(320.0)
    assert record["results"]["tafel_slope"] == pytest.approx(88.0)
    assert record["results"]["ir_compensation"] == pytest.approx(5.0)


def test_build_lsv_history_data_serializes_sequences_to_lists():
    data = build_lsv_history_data(
        potential=(0.1, 0.2),
        potential_compensated=(0.09, 0.18),
        current=(1.0, 2.0),
        target_currents=(10.0,),
        ir_compensation=5.0,
        tafel_fit_original={"r2": 0.99},
    )

    assert data["potential_original"] == [0.1, 0.2]
    assert data["potential_compensated"] == [0.09, 0.18]
    assert data["current"] == [1.0, 2.0]
    assert data["target_currents"] == [10.0]


def test_add_lsv_history_record_supports_legacy_signature():
    class LegacyHistory:
        def __init__(self):
            self.records = []

        def add_record(self, record):
            self.records.append(record)

    hist = LegacyHistory()
    record = {"type": "LSV"}

    add_lsv_history_record(hist, record, data={"x": 1}, project_id="p1")

    assert hist.records == [record]
