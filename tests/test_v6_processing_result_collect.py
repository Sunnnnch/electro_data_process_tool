from __future__ import annotations

import pandas as pd

from electrochem_v6.core.processing_result_collect import (
    collect_results_by_sample,
    make_metric_key,
    processing_results_from_ecsa_dataframe,
    processing_results_from_lsv_dataframe,
)


def test_make_metric_key_returns_ascii_identifier():
    assert make_metric_key("Potential@10mA/cm2(IR_compensated)") == "potential_at_10ma_cm2_ir_compensated"


def test_processing_results_from_lsv_dataframe_maps_identity_and_units():
    df = pd.DataFrame(
        [
            {
                "Sample_Name": "sample-a",
                "File_Name": "LSV_1.txt",
                "Potential@10mA/cm2": 0.215,
                "TafelSlope(mV/dec)": 68.5,
                "empty": "",
            }
        ]
    )

    results = processing_results_from_lsv_dataframe(df, project_id="project-1", run_id="run-1")

    assert len(results) == 1
    result = results[0]
    assert result.sample_name == "sample-a"
    assert result.source is not None
    assert result.source.file_name == "LSV_1.txt"
    assert result.project_id == "project-1"
    metrics = {metric.key: metric for metric in result.metrics}
    assert metrics["potential_at_10ma_cm2"].value == 0.215
    assert metrics["potential_at_10ma_cm2"].unit == "V"
    assert metrics["potential_at_10ma_cm2"].metadata["definition_key"] == "lsv.potential_at_current"
    assert metrics["tafelslope_mv_dec"].unit == "mV/dec"
    assert metrics["tafelslope_mv_dec"].metadata["category"] == "kinetics"
    assert "empty" not in metrics


def test_processing_results_from_ecsa_dataframe_maps_artifact_and_metrics():
    df = pd.DataFrame(
        [
            {
                "sample": "sample-a",
                "Ev": 0.1,
                "N_points": 4,
                "Cdl_mFcm2": 2.4,
                "ECSA_cm2": 0.6,
                "RF": 1.2,
                "png": "sample-a_ECSA.png",
            }
        ]
    )

    results = processing_results_from_ecsa_dataframe(df, metadata={"source_csv": "ECSA_results.csv"})

    assert len(results) == 1
    result = results[0]
    assert result.data_type == "ECSA"
    assert result.artifacts == ("sample-a_ECSA.png",)
    assert result.metadata == {"source_csv": "ECSA_results.csv"}
    metrics = {metric.key: metric for metric in result.metrics}
    assert metrics["cdl_mfcm2"].value == 2.4
    assert metrics["cdl_mfcm2"].unit == "mF/cm2"
    assert metrics["cdl_mfcm2"].metadata["definition_key"] == "ecsa.double_layer_capacitance"
    assert metrics["ecsa_cm2"].unit == "cm2"


def test_collect_results_by_sample_groups_multiple_data_types():
    lsv = processing_results_from_lsv_dataframe(
        pd.DataFrame([{"Sample_Name": "sample-a", "File_Name": "LSV_1.txt", "Potential@10mA/cm2": 0.2}])
    )[0]
    ecsa = processing_results_from_ecsa_dataframe(
        pd.DataFrame([{"sample": "sample-a", "Cdl_mFcm2": 2.4, "png": "plot.png"}])
    )[0]

    grouped = collect_results_by_sample([lsv, ecsa])

    assert list(grouped) == ["sample-a"]
    assert [item.data_type for item in grouped["sample-a"]] == ["LSV", "ECSA"]
