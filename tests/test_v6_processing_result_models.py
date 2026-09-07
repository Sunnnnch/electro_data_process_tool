from __future__ import annotations

import math

from electrochem_v6.core.processing_result_models import MetricValue, ProcessingResult, SourceFileRef


def test_processing_result_to_dict_normalizes_scalars():
    result = ProcessingResult(
        data_type="lsv",
        sample_name="sample-a",
        source=SourceFileRef(sample_name="sample-a", file_name="LSV_1.txt", data_type="LSV"),
        metrics=(
            MetricValue(key="potential_at_10", label="Potential@10", value=0.215, unit="V"),
            MetricValue(key="invalid_value", label="Invalid", value=math.nan),
        ),
        artifacts=("plot.png", ""),
        project_id="project-1",
        run_id="run-1",
        metadata={"source_csv": "LSV_results.csv"},
    )

    payload = result.to_dict()

    assert payload["data_type"] == "LSV"
    assert payload["source"]["file_name"] == "LSV_1.txt"
    assert payload["metrics"][0]["value"] == 0.215
    assert payload["metrics"][1]["value"] is None
    assert payload["artifacts"] == ["plot.png"]
    assert payload["metadata"] == {"source_csv": "LSV_results.csv"}


def test_processing_result_metric_map_uses_metric_keys():
    result = ProcessingResult(
        data_type="ECSA",
        sample_name="sample-a",
        metrics=(
            MetricValue(key="cdl_mfcm2", value=2.5),
            MetricValue(key="rf", value=1.2),
        ),
    )

    assert result.metric_map() == {"cdl_mfcm2": 2.5, "rf": 1.2}
