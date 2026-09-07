"""Tests for LSV export helpers."""

from __future__ import annotations

import pandas as pd
import pytest

from electrochem_v6.core.processing_lsv_export import build_lsv_detail_records, export_lsv_detail


def test_build_lsv_detail_records_with_ir_compensation():
    raw_records, target_records = build_lsv_detail_records(
        potential=[0.1, 0.2],
        current=[1.0, 2.0],
        current_signed=[-1.0, 2.0],
        potential_compensated=[0.09, 0.18],
        target_potentials_original={10.0: 0.5},
        target_potentials_compensated={10.0: 0.45},
        ir_compensation=5.0,
    )

    assert raw_records[0]["Potential_IRComp(V)"] == pytest.approx(0.09)
    assert raw_records[0]["IR_Ohm"] == pytest.approx(5.0)
    assert target_records == [
        {
            "Target_Current(mA/cm2)": 10.0,
            "Potential_Orig(V)": 0.5,
            "Potential_IRComp(V)": 0.45,
            "IR_Ohm": 5.0,
        }
    ]


def test_export_lsv_detail_writes_xlsx(tmp_path):
    export_lsv_detail(
        output_dir=str(tmp_path),
        file_stem="LSV_demo",
        sample_name="sample",
        source_file="LSV_demo.txt",
        params={"area": "1.0", "ir_method": "auto"},
        target_currents=[10.0],
        potential=[0.1, 0.2],
        current=[1.0, 2.0],
        current_signed=[1.0, 2.0],
        target_potentials_original={10.0: 0.5},
        software_version="test",
    )

    out = tmp_path / "LSV_demo.xlsx"
    assert out.exists()
    sheets = pd.read_excel(out, sheet_name=None)
    assert set(sheets) == {"raw", "targets", "info"}
