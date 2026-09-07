"""Tests for split ECSA helper modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import _write_tsv, make_ecsa_rows
from electrochem_v6.core.processing_ecsa_calc import (
    EcsaFitResult,
    calculate_ecsa_fit,
    compute_deltaJ_for_file,
)
from electrochem_v6.core.processing_ecsa_history import build_ecsa_history_record
from electrochem_v6.core.processing_ecsa_io import (
    _ecsa_extract_v_from_content,
    _ecsa_extract_v_from_name,
    read_ecsa_cv_table,
)
from electrochem_v6.core.processing_ecsa_plot import plot_ecsa_result


def test_scan_rate_helpers_read_name_and_content():
    assert _ecsa_extract_v_from_name("sample_50mVs.txt") == pytest.approx(0.05)
    assert _ecsa_extract_v_from_name("ECSA_2.5mV_s.txt") == pytest.approx(0.0025)
    assert _ecsa_extract_v_from_name("ECSA_0.05V_s.csv") == pytest.approx(0.05)
    assert _ecsa_extract_v_from_content(["Scan Rate (V/s): 0.125\n"]) == pytest.approx(0.125)
    assert _ecsa_extract_v_from_content(["Scan Rate (mV/s): 2.5\n"]) == pytest.approx(0.0025)


def test_read_ecsa_cv_table_skips_header(tmp_path: Path):
    path = tmp_path / "ECSA20.txt"
    path.write_text("Potential\tCurrent\n0.0\t1e-5\n0.1\t2e-5\n", encoding="utf-8")

    table = read_ecsa_cv_table(str(path))

    assert table.potential.tolist() == pytest.approx([0.0, 0.1])
    assert table.current.tolist() == pytest.approx([1e-5, 2e-5])
    assert len(table.lines) == 3


def test_read_ecsa_cv_table_rejects_entire_row_when_later_column_is_invalid(tmp_path: Path):
    path = tmp_path / "ECSA20.txt"
    path.write_text(
        "Potential\tCurrent\n0.0\tbad\nnan\t2e-5\n0.1\t3e-5\n",
        encoding="utf-8",
    )

    table = read_ecsa_cv_table(str(path))

    assert table.potential.tolist() == pytest.approx([0.1])
    assert table.current.tolist() == pytest.approx([3e-5])


def test_read_ecsa_cv_table_supports_semicolon_delimiter(tmp_path: Path):
    path = tmp_path / "ECSA20.csv"
    path.write_text("Potential;Current\n0.0;1e-5\n0.1;2e-5\n", encoding="utf-8")

    table = read_ecsa_cv_table(str(path))

    assert table.potential.tolist() == pytest.approx([0.0, 0.1])
    assert table.current.tolist() == pytest.approx([1e-5, 2e-5])


def test_read_ecsa_cv_table_supports_custom_columns_and_units(tmp_path: Path):
    path = tmp_path / "ECSA20.txt"
    path.write_text("index\tPotential\tCurrent\n1\t100\t2\n2\t200\t3\n", encoding="utf-8")

    table = read_ecsa_cv_table(
        str(path),
        potential_column=1,
        current_column=2,
        potential_scale=0.001,
        current_scale=0.001,
    )

    assert table.potential.tolist() == pytest.approx([0.1, 0.2])
    assert table.current.tolist() == pytest.approx([0.002, 0.003])


def test_compute_deltaj_for_file_from_calc_module(tmp_path: Path):
    rows = make_ecsa_rows(scan_rate_Vs=0.05, Ev=0.10)
    path = _write_tsv(tmp_path / "ECSA50.txt", rows)

    scan_rate, delta_j = compute_deltaJ_for_file(str(path), Ev=0.10)

    assert scan_rate == pytest.approx(0.05)
    assert delta_j is not None
    assert delta_j > 0


def _write_exact_crossing_cycles(path: Path, *, unfinished_last_sweep: bool = False):
    potential = [-1, -.5, 0, .5, 1, .5, 0, -.5, -1, -.5, 0, .5, 1, .5, 0, -.5, -1]
    current = [.001, .001, .001, .001, 0, -.001, -.001, -.001, 0, .002, .002, .002, 0, -.002, -.002, -.002, 0]
    if unfinished_last_sweep:
        potential += [-.5, 0, .5]
        current += [.01, .01, .01]
    return _write_tsv(path, list(zip(potential, current)))


def test_ecsa_averages_last_two_distinct_cycles_at_exact_ev(tmp_path):
    path = _write_exact_crossing_cycles(tmp_path / "ECSA10.txt")
    scan_rate, delta_j = compute_deltaJ_for_file(str(path), Ev=0, last_n=2, avg_last_n=True)
    assert scan_rate == pytest.approx(.01)
    assert delta_j == pytest.approx(3.0)


def test_ecsa_does_not_pair_unfinished_sweep_with_previous_cycle(tmp_path):
    path = _write_exact_crossing_cycles(tmp_path / "ECSA10.txt", unfinished_last_sweep=True)
    assert compute_deltaJ_for_file(str(path), Ev=0, last_n=1)[1] == pytest.approx(4.0)


@pytest.mark.parametrize("last_n", [0, -1])
def test_ecsa_requires_positive_cycle_selection(tmp_path, last_n):
    path = _write_exact_crossing_cycles(tmp_path / "ECSA10.txt")
    with pytest.raises(ValueError, match="last_n"):
        compute_deltaJ_for_file(str(path), Ev=0, last_n=last_n)


@pytest.mark.parametrize("rates", [[.01, .01], [.01, .01 + 1e-18], [0, .01], [float("nan"), .01]])
def test_ecsa_rejects_degenerate_scan_rate_fit(rates):
    assert calculate_ecsa_fit(v_list=rates, dJ_list=[1, 1], area_cm2=1) is None


def test_ecsa_accepts_replicates_when_multiple_distinct_rates_exist():
    fit = calculate_ecsa_fit(v_list=[.01, .01, .02, .02], dJ_list=[.4, .4, .8, .8], area_cm2=1)
    assert fit is not None
    assert fit.cdl_mFcm2 == pytest.approx(20)


def test_calculate_ecsa_fit_returns_expected_metrics():
    fit = calculate_ecsa_fit(
        v_list=[0.02, 0.04, 0.06],
        dJ_list=[0.8, 1.6, 2.4],
        area_cm2=1.0,
        cs_value=40.0,
        cs_unit="µF/cm²",
    )

    assert fit is not None
    assert fit.slope_mFcm2 == pytest.approx(40.0)
    assert fit.cdl_mFcm2 == pytest.approx(20.0)
    assert fit.cs_mFcm2 == pytest.approx(0.04)
    assert fit.ecsa_cm2 == pytest.approx(500.0)
    assert fit.rf == pytest.approx(500.0)


def test_calculate_ecsa_fit_applies_geometric_area_only_to_ecsa():
    fit = calculate_ecsa_fit(
        v_list=[0.02, 0.04, 0.06],
        dJ_list=[0.8, 1.6, 2.4],
        area_cm2=0.5,
        cs_value=40.0,
        cs_unit="uF/cm2",
    )

    assert fit is not None
    assert fit.rf == pytest.approx(500.0)
    assert fit.ecsa_cm2 == pytest.approx(250.0)


@pytest.mark.parametrize(
    "area, cs_value",
    [(0.0, 40.0), (-1.0, 40.0), (1.0, 0.0), (1.0, -40.0)],
)
def test_calculate_ecsa_fit_rejects_nonphysical_area_or_specific_capacitance(area, cs_value):
    with pytest.raises(ValueError):
        calculate_ecsa_fit(
            v_list=[0.02, 0.04, 0.06],
            dJ_list=[0.8, 1.6, 2.4],
            area_cm2=area,
            cs_value=cs_value,
            cs_unit="uF/cm2",
        )


def test_plot_ecsa_result_writes_png(tmp_path: Path):
    fit = EcsaFitResult(
        slope_mFcm2=40.0,
        intercept=0.0,
        r2=1.0,
        cdl_mFcm2=20.0,
        cs_input=40.0,
        cs_unit="µF/cm²",
        cs_mFcm2=0.04,
        ecsa_cm2=500.0,
        rf=500.0,
    )

    out = plot_ecsa_result(
        sample_name="sample",
        output_dir=str(tmp_path),
        v_list=[0.02, 0.04, 0.06],
        dJ_list=[0.8, 1.6, 2.4],
        fit=fit,
        params={
            "ev": "0.10",
            "line_width": "2.0",
            "plot_grid": True,
            "xlabel": "Scan rate v (V/s)",
            "ylabel": "Delta J",
            "title": "ECSA of {sample} @ Ev={Ev:.3f} V",
        },
        font_name="DejaVu Sans",
        fontsize="12",
    )

    assert Path(out).exists()


def test_build_ecsa_history_record_attaches_project_name():
    class ProjectManager:
        def get_project(self, project_id):
            return {"id": project_id, "name": "demo"}

    fit = EcsaFitResult(
        slope_mFcm2=40.0,
        intercept=0.0,
        r2=1.0,
        cdl_mFcm2=20.0,
        cs_input=40.0,
        cs_unit="µF/cm²",
        cs_mFcm2=0.04,
        ecsa_cm2=500.0,
        rf=500.0,
    )
    record = build_ecsa_history_record(
        sample_name="sample",
        subfolder="sample",
        params={"project_id": "p1", "run_id": "r1"},
        fit=fit,
        scan_rates=[0.02, 0.04],
        project_manager=ProjectManager(),
    )

    assert record["type"] == "ECSA"
    assert record["project_name"] == "demo"
    assert record["run_id"] == "r1"
    assert record["results"]["scan_rates"] == 2
