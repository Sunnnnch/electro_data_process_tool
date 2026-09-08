"""EIS diagnostics must survive unit conversion, artifact export, history and reports."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from electrochem_v6.core import processing_eis as pipeline
from electrochem_v6.core import reproducible_report_service as reports
from electrochem_v6.core.history_compare import build_history_comparison
from electrochem_v6.core.job_control import ProcessingCancelledError


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    frequency = np.logspace(-1, 5, 61)
    omega = 2 * np.pi * frequency
    # Independent analytic two-RC spectrum, with well-separated time constants.
    impedance = 8 + 40 / (1 + 1j * omega * 40 * 2e-5) + 120 / (1 + 1j * omega * 120 * .002)
    source = tmp_path / "EIS_double.txt"
    source.write_text("\n".join(f"{f / 1000:.16g}\t{z.real / 1000:.16g}\t{-z.imag / 1000:.16g}"
                                for f, z in zip(frequency, impedance)), encoding="utf-8")
    records = []
    class History:
        def add_record(self, record):
            records.append(record)
    monkeypatch.setattr(pipeline, "HISTORY_MANAGER_AVAILABLE", True)
    monkeypatch.setattr(pipeline, "PROJECT_MANAGER_AVAILABLE", False)
    monkeypatch.setattr(pipeline, "get_history_manager", lambda: History())
    params = {"start_line": 1, "xlabel": "Z real (Ohm)", "ylabel": "-Z imag (Ohm)",
              "title": "{sample}", "font": "DejaVu Sans", "plot_nyquist": False,
              "plot_bode": False, "plot_eis_residuals": False, "eis_randles_fit": True,
              "eis_circuit_model": "two_time_constants_rc", "eis_kk_check": True,
              "eis_frequency_unit": "khz", "eis_impedance_unit": "kohm",
              "eis_zimag_convention": "negative_z_imaginary", "run_id": "eis-test",
              "output_dir": str(tmp_path / "outputs")}
    return source, frequency, impedance, params, records


def run_experiment(experiment, **changes):
    source, _, _, params, _ = experiment
    return pipeline.process_eis(str(source.parent), source.name, {**params, **changes})


def artifact(result, suffix):
    return next(Path(path) for path in result["artifacts"] if path.endswith(suffix))


def test_closed_hz_window_preserves_source_and_aligned_diagnostics(experiment):
    source, frequency, impedance, _, records = experiment
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    result = run_experiment(experiment, eis_fit_frequency_min_hz=1, eis_fit_frequency_max_hz=10000,
                            eis_fit_weighting="modulus")
    saved = json.loads(artifact(result, "Diagnostics.json").read_text(encoding="utf-8"))
    selection, fit = saved["frequency_selection"], saved["fit"]
    expected = np.flatnonzero((frequency >= 1) & (frequency <= 10000))
    assert selection["selected_indices"] == expected.tolist()
    assert selection["selected_points"] == 41 and selection["total_points"] == 61
    assert selection["actual_min_hz"] == 1 and selection["actual_max_hz"] == 10000
    assert fit["accepted"] and fit["weighting"] == "modulus"
    assert fit["parameters"]["R1"] == pytest.approx(40, rel=1e-4)
    assert fit["parameters"]["R2"] == pytest.approx(120, rel=1e-4)
    assert "Rct" not in fit["parameters"]
    assert all(value["estimable"] for value in fit["parameter_ci95"].values())
    assert len(fit["residual_real_ohm"]) == saved["kk"]["selection"]["input_points"] == 41
    with artifact(result, "Residuals.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [int(row["parsed_point_index"]) for row in rows] == expected.tolist()
    np.testing.assert_allclose([float(row["z_imag_ohm"]) for row in rows], impedance.imag[expected])
    np.testing.assert_allclose([float(row["fit_residual_real_ohm"]) for row in rows], fit["residual_real_ohm"])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original
    assert records[0]["results"]["Rct"] is None
    assert records[0]["results"]["data_points"] == 61
    assert records[0]["eis_analysis"] == saved
    assert records[0]["quality_summary"] == result["quality_report"]


def test_kk_only_exports_no_invented_circuit_parameters(experiment):
    result = run_experiment(experiment, eis_randles_fit=False, plot_eis_residuals=True)
    saved = json.loads(artifact(result, "Diagnostics.json").read_text(encoding="utf-8"))
    assert saved["fit"] is None
    assert saved["kk"]["status"] == "consistent"
    assert result["randles_result"] is None
    assert all(metric.key not in {"eis.rs", "eis.r1", "eis.rct"} for metric in result["processing_result"].metrics)
    assert artifact(result, "Residuals.png").is_file()


def test_empty_window_reports_failure_without_changing_raw_point_count(experiment):
    result = run_experiment(experiment, eis_fit_frequency_min_hz=1e9, plot_eis_residuals=True)
    saved = json.loads(artifact(result, "Diagnostics.json").read_text(encoding="utf-8"))
    assert saved["fit"]["accepted"] is False
    assert saved["kk"]["status"] == "unavailable"
    assert saved["frequency_selection"]["selected_points"] == 0
    assert saved["frequency_selection"]["total_points"] == 61
    assert result["quality_report"]["quality_level"] == "warning"
    assert not any(path.endswith("Residuals.png") for path in result["artifacts"])
    assert len(artifact(result, "Residuals.csv").read_text(encoding="utf-8-sig").splitlines()) == 1


def test_all_three_plots_and_run_history_reports_show_saved_diagnostics(experiment):
    result = run_experiment(experiment, plot_nyquist=True, plot_bode=True, plot_eis_residuals=True)
    for suffix in ("Nyquist.png", "Bode.png", "Residuals.png"):
        with Image.open(artifact(result, suffix)) as image:
            assert image.width >= 800 and image.height >= 600
    normalized = result["processing_result"].to_dict()
    manifest = {"run": {"run_id": "eis-test", "data_types": ["EIS"]},
                "parameters": experiment[3], "processing_results": [normalized]}
    report = reports.render_report_markdown(reports.build_run_report_document(manifest))
    record = experiment[4][0]
    history_report = reports.render_report_markdown(reports.build_project_report_document(
        project={"name": "EIS project"}, report_data={"records": [record]}))
    for text in (report, history_report):
        assert "two_time_constants_rc" in text
        assert "局部近似 95%" in text and "KK 一致性诊断" in text
        assert "归一化 RMS" in text and "R1" in text and "C2" in text
    # No current diagnostic is fabricated into legacy records that lack it.
    old = reports.render_report_markdown(reports.build_run_report_document({"processing_results": [
        {"data_type": "EIS", "sample_name": "old", "metrics": [], "metadata": {}}]}))
    assert "KK 一致性诊断" not in old and "局部近似 95%" not in old


@pytest.mark.parametrize("minimum,maximum", [(0, None), (-1, None), (float("nan"), None),
                                           (None, float("inf")), (100, 1)])
def test_invalid_frequency_window_is_rejected(minimum, maximum):
    with pytest.raises(ValueError):
        pipeline.select_eis_frequency([1, 10, 100], [1, 2, 3], [-1, -2, -3],
            {"eis_fit_frequency_min_hz": minimum, "eis_fit_frequency_max_hz": maximum})


@pytest.mark.parametrize("new_n", [.9, None])
def test_double_cpe_comparison_keeps_q_dimensions_and_model_changes_visible(new_n):
    left = {"type": "EIS", "project_id": "p", "record_key": "left",
            "results": {"Q1": .001, "n1": .8, "R1": 10, "circuit_model": "two_time_constants_cpe"}}
    right = {**left, "record_key": "right", "results": {**left["results"], "Q1": .002, "n1": new_n, "R1": 20}}
    comparison = build_history_comparison(left, right)
    metrics = {item["key"]: item for item in comparison["metrics"]}
    assert metrics["Q1"]["delta"] is None and metrics["Q1"]["status"] == "unit_mismatch"
    assert metrics["R1"]["delta"] == 10 and metrics["R1"]["unit"] == "Ω"


def test_cancellation_is_never_exported_as_fit_failure(experiment, monkeypatch):
    def cancel(*args, **kwargs):
        raise ProcessingCancelledError("cancel during fit")
    monkeypatch.setattr(pipeline, "evaluate_eis_circuit_fit", cancel)
    with pytest.raises(ProcessingCancelledError, match="during fit"):
        run_experiment(experiment, _cancel_check=lambda: False)
    assert not experiment[4]
    assert not list(Path(experiment[3]["output_dir"]).glob("*Diagnostics.json"))
