"""Tests for split CV helper modules."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from electrochem_v6.core.processing_cv_calc import (
    CvPeak,
    compute_charge_mC,
    compute_cv_metrics,
    detect_cv_peaks,
    parse_cycle_selection,
    split_cv_cycles,
)
from electrochem_v6.core.processing_cv_history import build_cv_history_record
from electrochem_v6.core.processing_cv_io import parse_cv_lines, read_cv_raw_data
from electrochem_v6.core.processing_cv_plot import plot_cv_curve


def _demo_cv_vectors(cycles: int = 1) -> tuple[list[float], list[float]]:
    potential: list[float] = []
    current: list[float] = []
    n_half = 60
    for _ in range(cycles):
        for i in range(n_half):
            v = i / n_half
            i_a = 0.001 * np.exp(-((v - 0.5) ** 2) / 0.02) + 1e-5 * v
            potential.append(v)
            current.append(float(i_a * 1000.0))
        for i in range(n_half):
            v = 1.0 - i / n_half
            i_a = -0.0008 * np.exp(-((v - 0.4) ** 2) / 0.02) - 1e-5 * v
            potential.append(v)
            current.append(float(i_a * 1000.0))
    return potential, current


def test_parse_cv_lines_scales_current_and_skips_invalid_rows():
    raw = parse_cv_lines(["Potential Current\n", "0.1\t0.001\n", "0.2,0.002\n"])

    assert raw.potential == [0.1, 0.2]
    assert raw.current == pytest.approx([1.0, 2.0])
    assert raw.parse_errors == 1


def test_parse_cv_lines_rejects_entire_row_when_later_column_is_invalid():
    raw = parse_cv_lines(["0.1 bad", "nan 0.002", "0.2 0.003"])

    assert raw.potential == pytest.approx([0.2])
    assert raw.current == pytest.approx([3.0])
    assert raw.parse_errors == 2


def test_parse_cv_lines_supports_semicolon_delimiter():
    raw = parse_cv_lines(["0.1;0.001", "0.2;0.002"])

    assert raw.potential == pytest.approx([0.1, 0.2])
    assert raw.current == pytest.approx([1.0, 2.0])


def test_parse_cv_lines_supports_custom_columns_and_units():
    raw = parse_cv_lines(
        ["ignored 100 2\n", "ignored 200 3\n"],
        potential_column=1,
        current_column=2,
        potential_scale=0.001,
        current_scale=1.0,
    )

    assert raw.potential == pytest.approx([0.1, 0.2])
    assert raw.current == pytest.approx([2.0, 3.0])


def test_read_cv_raw_data_respects_start_line(tmp_path: Path):
    path = tmp_path / "CV_demo.txt"
    path.write_text("header\n0.1\t0.001\n0.2\t0.002\n", encoding="utf-8")

    raw = read_cv_raw_data(str(path), start_line=2)

    assert raw is not None
    assert raw.potential == [0.1, 0.2]


def test_detect_cv_peaks_and_delta_ep():
    potential, current = _demo_cv_vectors(cycles=1)

    peaks = detect_cv_peaks(
        potential,
        current,
        enabled=True,
        smooth_window="5",
        min_height="0.5",
        min_distance="5",
        max_peaks="4",
    )
    metrics = compute_cv_metrics(
        potential,
        current,
        {
            "peaks_enabled": True,
            "peaks_smooth": "5",
            "peaks_min_height": "0.5",
            "peaks_min_dist": "5",
            "peaks_max": "4",
        },
    )

    assert {peak.kind for peak in peaks} == {"max", "min"}
    assert metrics.delta_ep_mV == pytest.approx(100.0)


def test_compute_charge_mC_uses_absolute_current():
    assert compute_charge_mC(
        [0.0, 1.0, 0.0],
        [-1.0, 1.0, -1.0],
        scan_rate_v_s=1.0,
    ) == pytest.approx(2.0)


def test_compute_charge_mC_requires_scan_rate_instead_of_mislabeling_curve_area():
    assert compute_charge_mC([0.0, 1.0], [-1.0, 1.0]) is None
    assert compute_charge_mC([0.0, 1.0], [-1.0, 1.0], scan_rate_v_s=0) is None


def test_parse_cycle_selection_supports_lists_and_ranges():
    assert parse_cycle_selection("1,3,2-4") == [1, 3, 2, 4]
    assert parse_cycle_selection("4-2") == [2, 3, 4]
    assert parse_cycle_selection("") == []


def test_split_cv_cycles_detects_full_cycles():
    potential, current = _demo_cv_vectors(cycles=2)

    cycles = split_cv_cycles(potential, current)

    assert [cycle.number for cycle in cycles] == [1, 2]
    assert cycles[0].start_index == 0
    assert cycles[0].end_index > cycles[0].start_index
    assert len(cycles[0].potential) == len(cycles[0].current)


def test_split_cv_cycles_ignores_single_point_potential_jitter():
    potential, current = _demo_cv_vectors(cycles=2)
    potential.insert(13, potential[12] - 0.001)
    current.insert(13, current[12])

    cycles = split_cv_cycles(potential, current)

    assert [cycle.number for cycle in cycles] == [1, 2]


def test_split_cv_cycles_respects_explicit_hysteresis_and_segment_length():
    potential, current = _demo_cv_vectors(cycles=2)

    cycles = split_cv_cycles(
        potential,
        current,
        reversal_tolerance=0.05,
        min_segment_points=20,
    )

    assert len(cycles) == 2


@pytest.mark.parametrize("direction", [1, -1])
def test_split_cv_cycles_preserves_full_interior_start_cycle(direction):
    potential = [direction * value for value in [0, .5, 1, .5, 0, -.5, -1, -.5, 0]]
    cycles = split_cv_cycles(potential, [1] * len(potential))
    assert len(cycles) == 1
    assert cycles[0].start_index == 0
    assert cycles[0].end_index == 8
    assert cycles[0].potential == potential
    assert compute_charge_mC(cycles[0].potential, cycles[0].current, scan_rate_v_s=1) == pytest.approx(4)


def test_split_cv_cycles_uses_same_phase_boundaries_for_multiple_interior_cycles():
    single = [0, .5, 1, .5, 0, -.5, -1, -.5, 0]
    potential = single + single[1:]
    cycles = split_cv_cycles(potential, list(range(len(potential))))
    assert [(cycle.start_index, cycle.end_index) for cycle in cycles] == [(0, 8), (8, 16)]
    assert cycles[0].potential == cycles[1].potential == single
    assert cycles[1].current == list(range(8, 17))


@pytest.mark.parametrize("potential", [[0, .5, 1, .5, 0, -.5, -1, -.5], [0, .5, 1, .5]])
def test_split_cv_cycles_does_not_label_an_unfinished_sweep_as_full(potential):
    assert split_cv_cycles(potential, [1] * len(potential)) == []


def test_plot_cv_curve_writes_png(tmp_path: Path):
    potential = [0.0, 0.5, 1.0]
    current = [0.0, 1.0, 0.0]

    out = plot_cv_curve(
        potential=potential,
        current=current,
        peaks=[CvPeak("max", 1, 0.5, 1.0)],
        delta_ep=None,
        params={
            "xlabel": "Potential (V)",
            "ylabel": "Current (mA)",
            "title": "CV - {sample}",
            "fontsize": "12",
            "line_color": "blue",
            "line_width": 2.0,
            "plot_grid": True,
        },
        sample_name="sample",
        file_stem="CV_demo",
        output_dir=str(tmp_path),
        font_name="DejaVu Sans",
    )

    assert Path(out).exists()


def test_build_cv_history_record_attaches_project_name():
    class ProjectManager:
        def get_project(self, project_id):
            return {"id": project_id, "name": "demo"}

    record = build_cv_history_record(
        sample_name="sample",
        file_stem="CV_demo",
        file_path="CV_demo.txt",
        params={"project_id": "p1", "run_id": "r1"},
        potential=[0.0, 1.0],
        current=[-1.0, 2.0],
        delta_ep_mV=100.0,
        charge_mC=1.5,
        project_manager=ProjectManager(),
    )

    assert record["type"] == "CV"
    assert record["project_name"] == "demo"
    assert record["run_id"] == "r1"
    assert record["results"]["delta_ep_mV"] == pytest.approx(100.0)
