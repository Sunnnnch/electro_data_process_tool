"""Tests for split EIS helper modules."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from electrochem_v6.core.processing_eis_calc import (
    _randles_cpe_impedance,
    _randles_impedance,
    accepted_randles_fit,
    compute_bode_arrays,
    evaluate_eis_circuit_fit,
)
from electrochem_v6.core.processing_eis_history import build_eis_history_record
from electrochem_v6.core.processing_eis_io import parse_eis_lines, read_eis_raw_data
from electrochem_v6.core.processing_eis_plot import plot_eis_bode, plot_eis_nyquist


def _demo_eis_vectors():
    freq = np.logspace(-1, 5, 40)
    z = _randles_impedance(freq, Rs=10.0, Rct=100.0, Cdl=1e-5)
    return freq.tolist(), z.real.tolist(), z.imag.tolist()


def _plot_params():
    return {
        "xlabel": "Z' (Ohm)",
        "ylabel": "-Z'' (Ohm)",
        "title": "EIS - {sample}",
        "fontsize": "12",
        "line_color": "blue",
        "line_width": 2.0,
        "plot_grid": True,
    }


def test_parse_eis_lines_skips_invalid_rows():
    raw = parse_eis_lines(["Freq Zr Zi\n", "1000\t10\t-5\n", "100,11,-4\n"])

    assert raw.frequency == [1000.0, 100.0]
    assert raw.z_real == [10.0, 11.0]
    assert raw.z_imag == [-5.0, -4.0]
    assert raw.parse_errors == 1


def test_parse_eis_lines_rejects_entire_row_when_later_column_is_invalid():
    raw = parse_eis_lines(["100 bad -5", "10 2 inf", "1 3 -1"])

    assert raw.frequency == pytest.approx([1.0])
    assert raw.z_real == pytest.approx([3.0])
    assert raw.z_imag == pytest.approx([-1.0])
    assert raw.parse_errors == 2


def test_parse_eis_lines_supports_custom_columns_and_units():
    raw = parse_eis_lines(
        ["unused 1 -0.5 0.01\n"],
        frequency_column=3,
        zreal_column=1,
        zimag_column=2,
        frequency_scale=1000.0,
        impedance_scale=1000.0,
    )

    assert raw.frequency == pytest.approx([10.0])
    assert raw.z_real == pytest.approx([1000.0])
    assert raw.z_imag == pytest.approx([-500.0])


def test_parse_eis_lines_supports_semicolon_and_negative_zimag_input():
    raw = parse_eis_lines(["1000;10;5"], zimag_sign=-1.0)

    assert raw.frequency == pytest.approx([1000.0])
    assert raw.z_real == pytest.approx([10.0])
    assert raw.z_imag == pytest.approx([-5.0])


def test_read_eis_raw_data_respects_start_line(tmp_path: Path):
    path = tmp_path / "EIS_demo.txt"
    path.write_text("header\n1000\t10\t-5\n100\t11\t-4\n", encoding="utf-8")

    raw = read_eis_raw_data(str(path), start_line=2)

    assert raw is not None
    assert raw.frequency == [1000.0, 100.0]


def test_compute_bode_arrays_returns_magnitude_and_phase():
    z_mag, z_phase = compute_bode_arrays([3.0], [4.0])

    assert z_mag == pytest.approx([5.0])
    assert z_phase == pytest.approx([53.1301023542])


def test_accepted_randles_fit_keeps_good_fit():
    freq, z_real, z_imag = _demo_eis_vectors()

    result = accepted_randles_fit(freq, z_real, z_imag)

    assert result is not None
    assert result["Rs"] == pytest.approx(10.0, abs=1.0)
    assert result["r2"] > 0.99


def test_randles_cpe_fit_reports_model_parameters_and_residuals():
    freq = np.logspace(-1, 5, 60)
    z = _randles_cpe_impedance(freq, Rs=7.0, Rct=85.0, Q=3e-5, n=0.82)

    result = evaluate_eis_circuit_fit(
        freq,
        z.real,
        z.imag,
        model="randles_cpe",
        min_r2=0.99,
    )

    assert result["accepted"] is True
    assert result["equivalent_circuit"] == "Rs + (Rct || CPE[Q,n])"
    assert result["Rs"] == pytest.approx(7.0, rel=0.05)
    assert result["Rct"] == pytest.approx(85.0, rel=0.05)
    assert result["n"] == pytest.approx(0.82, abs=0.03)
    assert result["normalized_rmse"] < 1e-4
    assert result["acceptance_criterion"] == {"metric": "complex_r2", "minimum": 0.99}


def test_circuit_fit_rejection_preserves_reason_and_threshold():
    result = evaluate_eis_circuit_fit([1, 2, 3], [1, 2, 3], [-1, -1, -1], min_r2=0.9)

    assert result["accepted"] is False
    assert result["status"] == "fit_failed"
    assert result["rejection_reason"]
    assert result["acceptance_criterion"]["minimum"] == pytest.approx(0.9)


def test_plot_eis_nyquist_and_bode_write_pngs(tmp_path: Path):
    freq, z_real, z_imag = _demo_eis_vectors()

    nyquist = plot_eis_nyquist(
        z_real=z_real,
        z_imag=z_imag,
        params=_plot_params(),
        sample_name="sample",
        file_stem="EIS_demo",
        output_dir=str(tmp_path),
        font_name="DejaVu Sans",
        randles_result=None,
    )
    bode = plot_eis_bode(
        frequency=freq,
        z_real=z_real,
        z_imag=z_imag,
        params=_plot_params(),
        sample_name="sample",
        file_stem="EIS_demo",
        output_dir=str(tmp_path),
        font_name="DejaVu Sans",
    )

    assert Path(nyquist).exists()
    assert Path(bode).exists()


def test_build_eis_history_record_uses_randles_and_project_name():
    class ProjectManager:
        def get_project(self, project_id):
            return {"id": project_id, "name": "demo"}

    record = build_eis_history_record(
        sample_name="sample",
        file_stem="EIS_demo",
        file_path="EIS_demo.txt",
        params={"project_id": "p1", "run_id": "r1"},
        frequency=[1000.0, 100.0],
        z_real=[10.0, 20.0],
        randles_result={"Rs": 10.0, "Rct": 50.0, "Cdl": 1e-5, "r2": 0.99},
        project_manager=ProjectManager(),
    )

    assert record["type"] == "EIS"
    assert record["run_id"] == "r1"
    assert record["project_name"] == "demo"
    assert record["results"]["Rs"] == pytest.approx(10.0)
    assert record["results"]["randles_r2"] == pytest.approx(0.99)
