from __future__ import annotations

import csv

from electrochem_v6.core.processing_result_export import (
    build_processing_result_records,
    export_processing_results_csv,
)
from electrochem_v6.core.processing_result_models import MetricValue, ProcessingResult, SourceFileRef


def test_build_processing_result_records_creates_long_rows():
    result = ProcessingResult(
        data_type="LSV",
        sample_name="sample-a",
        source=SourceFileRef(sample_name="sample-a", file_name="LSV_1.txt", path="data/LSV_1.txt"),
        metrics=(
            MetricValue(
                key="potential_at_10",
                label="Potential@10",
                value=0.215,
                unit="V",
                metadata={"definition_key": "lsv.potential_at_current"},
            ),
            MetricValue(key="tafel_slope", label="TafelSlope", value=68.5, unit="mV/dec"),
        ),
        artifacts=("plot.png",),
        metadata={"source_csv": "LSV_results.csv"},
    )

    rows = build_processing_result_records([result])

    assert len(rows) == 2
    assert rows[0]["sample_name"] == "sample-a"
    assert rows[0]["file_name"] == "LSV_1.txt"
    assert rows[0]["metric_key"] == "potential_at_10"
    assert rows[0]["artifacts"] == "plot.png"
    assert "lsv.potential_at_current" in rows[0]["metric_metadata"]
    assert "LSV_results.csv" in rows[0]["metadata"]


def test_export_processing_results_csv_writes_header_and_rows(tmp_path):
    result = ProcessingResult(
        data_type="ECSA",
        sample_name="sample-a",
        metrics=(MetricValue(key="cdl_mfcm2", label="Cdl_mFcm2", value=2.4, unit="mF/cm2"),),
    )
    output_path = tmp_path / "nested" / "processing_results.csv"

    returned = export_processing_results_csv([result], str(output_path))

    assert returned == str(output_path)
    with open(output_path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["sample_name"] == "sample-a"
    assert rows[0]["data_type"] == "ECSA"
    assert rows[0]["metric_key"] == "cdl_mfcm2"
