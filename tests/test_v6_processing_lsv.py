"""Tests for processing_lsv.py — LSV data processing functions."""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from electrochem_v6.core.processing_lsv import (
    interpolate_potential,
    parse_target_currents,
)


# ── interpolate_potential ──────────────────────────────────────────────────

class TestInterpolatePotential:
    def test_basic_interpolation(self):
        potential = [0.0, 0.5, 1.0, 1.5]
        current = [1.0, 10.0, 50.0, 100.0]
        result = interpolate_potential(potential, current, 10.0)
        assert result is not None
        assert abs(result - 0.5) < 1e-6

    def test_returns_none_below_range(self):
        potential = [0.0, 0.5, 1.0]
        current = [10.0, 20.0, 30.0]
        assert interpolate_potential(potential, current, 5.0) is None

    def test_returns_none_above_range(self):
        potential = [0.0, 0.5, 1.0]
        current = [10.0, 20.0, 30.0]
        assert interpolate_potential(potential, current, 50.0) is None

    def test_with_nan_values(self):
        potential = [0.0, float('nan'), 1.0, 1.5]
        current = [1.0, float('nan'), 50.0, 100.0]
        result = interpolate_potential(potential, current, 50.0)
        assert result is not None
        assert abs(result - 1.0) < 1e-6

    def test_with_numpy_arrays(self):
        p = np.array([0.0, 0.3, 0.6, 0.9, 1.2])
        c = np.array([0.5, 5.0, 15.0, 40.0, 80.0])
        result = interpolate_potential(p, c, 15.0)
        assert result is not None
        assert abs(result - 0.6) < 1e-6

    def test_too_few_points(self):
        assert interpolate_potential([1.0], [10.0], 10.0) is None

    def test_empty_arrays(self):
        assert interpolate_potential([], [], 10.0) is None

    def test_duplicate_currents(self):
        potential = [0.0, 0.4, 0.6, 1.0]
        current = [10.0, 10.0, 20.0, 30.0]
        result = interpolate_potential(potential, current, 10.0)
        assert result is not None
        # Average of 0.0 and 0.4 at current=10
        assert abs(result - 0.2) < 1e-6

    def test_exact_match(self):
        potential = [0.0, 0.5, 1.0]
        current = [10.0, 20.0, 30.0]
        result = interpolate_potential(potential, current, 20.0)
        assert result is not None
        assert abs(result - 0.5) < 1e-6

    def test_unsorted_input(self):
        potential = [1.0, 0.0, 0.5]
        current = [30.0, 10.0, 20.0]
        result = interpolate_potential(potential, current, 20.0)
        assert result is not None
        assert abs(result - 0.5) < 1e-6


# ── parse_target_currents ─────────────────────────────────────────────────

class TestParseTargetCurrents:
    def test_single_value(self):
        assert parse_target_currents("10") == [10.0]

    def test_multiple_values(self):
        result = parse_target_currents("10,100,50")
        assert result == [10.0, 50.0, 100.0]  # sorted

    def test_chinese_comma(self):
        result = parse_target_currents("10\uff0c50")
        assert result == [10.0, 50.0]

    def test_whitespace(self):
        result = parse_target_currents(" 10 , 20 , 30 ")
        assert result == [10.0, 20.0, 30.0]

    def test_none_input(self):
        assert parse_target_currents(None) == []

    def test_empty_string(self):
        assert parse_target_currents("") == []

    def test_deduplication(self):
        result = parse_target_currents("10,10,20")
        assert result == [10.0, 20.0]

    def test_float_values(self):
        result = parse_target_currents("1.5,2.5")
        assert result == [1.5, 2.5]

    def test_invalid_skipped(self):
        result = parse_target_currents("10,abc,20")
        assert 10.0 in result
        assert 20.0 in result


# ── process_lsv with real temp files ──────────────────────────────────────

class TestProcessLsvFile:
    @pytest.fixture
    def lsv_data_dir(self, tmp_path):
        """Create a temp dir with a realistic LSV data file."""
        sample_dir = tmp_path / "sample1"
        sample_dir.mkdir()
        # Generate realistic LSV: exponential current vs potential
        lines = []
        for i in range(50):
            v = 0.0 + i * 0.03  # 0 to 1.47V
            i_A = 1e-6 * np.exp(5.0 * v)  # exponential I-V
            lines.append(f"{v:.6f}\t{i_A:.10f}")
        data = "\n".join(lines)
        (sample_dir / "LSV_test.txt").write_text(data, encoding="utf-8")
        return sample_dir

    def test_process_lsv_runs(self, lsv_data_dir):
        from electrochem_v6.core.processing_lsv import process_lsv

        params = {
            "start_line": "1",
            "offset": "0",
            "area": "1.0",
            "target_current": "10",
            "use_abs_current": True,
            "tafel_enabled": False,
            "overpotential_enabled": False,
            "onset_enabled": False,
            "halfwave_enabled": False,
            "ir_compensation_enabled": False,
            "lsv_line_color": "blue",
            "font_family": "",
            "font_size": "12",
            "plot_grid": False,
            "xlabel": "Potential (V)",
            "ylabel": "Current (mA/cm²)",
            "title": "LSV - {sample}",
            "fontsize": "12",
            "font": "",
            "line_color": "blue",
            "line_width": 2.0,
        }
        import matplotlib
        matplotlib.use("Agg")
        # Should not raise; result may vary based on data
        process_lsv(str(lsv_data_dir), "LSV_test.txt", params)

    def test_process_lsv_file_not_found(self, tmp_path):
        from electrochem_v6.core.processing_lsv import process_lsv
        from electrochem_v6.core.processing_core_v6 import FileFormatError

        params = {
            "start_line": "1",
            "offset": "0",
            "area": "1.0",
            "target_current": "10",
            "use_abs_current": True,
            "tafel_enabled": False,
            "overpotential_enabled": False,
            "onset_enabled": False,
            "halfwave_enabled": False,
            "ir_compensation_enabled": False,
            "lsv_line_color": "blue",
            "font_family": "",
            "font_size": "12",
            "plot_grid": False,
            "xlabel": "Potential (V)",
            "ylabel": "Current (mA/cm²)",
            "title": "LSV - {sample}",
            "fontsize": "12",
            "font": "",
            "line_color": "blue",
            "line_width": 2.0,
        }
        with pytest.raises((FileFormatError, FileNotFoundError, OSError)):
            process_lsv(str(tmp_path), "nonexistent.txt", params)


# ── _filter_outliers ──────────────────────────────────────────────────────

class TestFilterOutliers:
    def test_no_outliers(self):
        from electrochem_v6.core.processing_lsv import _filter_outliers

        real = [10.0, 11.0, 12.0, 13.0, 14.0]
        imag = [-1.0, -2.0, -3.0, -4.0, -5.0]
        r, im, _ = _filter_outliers(real, imag)
        assert len(r) == 5

    def test_with_outlier(self):
        from electrochem_v6.core.processing_lsv import _filter_outliers

        real = [10.0, 11.0, 12.0, 13.0, 14.0, 1000.0]
        imag = [-1.0, -2.0, -3.0, -4.0, -5.0, -500.0]
        r, im, _ = _filter_outliers(real, imag)
        assert len(r) < 6  # outlier removed

    def test_with_freq(self):
        from electrochem_v6.core.processing_lsv import _filter_outliers

        real = [10.0, 11.0, 12.0, 13.0, 14.0]
        imag = [-1.0, -2.0, -3.0, -4.0, -5.0]
        freq = [1e6, 1e5, 1e4, 1e3, 1e2]
        r, im, f = _filter_outliers(real, imag, freq)
        assert len(f) == 5


# ── potential_at_current ──────────────────────────────────────────────────

class TestPotentialAtCurrent:
    def test_within_range(self):
        from electrochem_v6.core.processing_lsv import potential_at_current

        potential = np.linspace(0, 1.5, 100)
        current = np.exp(5 * potential)  # exponential
        result = potential_at_current(potential, current, target_i=10.0)
        assert result is not None
        pot_val, fit_data = result
        assert isinstance(pot_val, float)
        assert 0.0 < pot_val < 1.5

    def test_large_target_extrapolation(self):
        from electrochem_v6.core.processing_lsv import potential_at_current

        potential = np.linspace(0, 0.5, 50)
        current = np.exp(3 * potential)
        result = potential_at_current(potential, current, target_i=1000.0)
        # May return None or extrapolated value
        if result is not None:
            pot_val, _ = result
            assert isinstance(pot_val, float)
