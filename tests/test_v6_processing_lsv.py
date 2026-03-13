"""Tests for processing_lsv.py — LSV data processing functions."""

import numpy as np
import pytest

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
        from electrochem_v6.core.processing_core_v6 import FileFormatError
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


# ── _parse_tafel_range ────────────────────────────────────────────────────

class TestParseTafelRange:
    def test_normal_range(self):
        from electrochem_v6.core.processing_lsv import _parse_tafel_range
        assert _parse_tafel_range("1-10") == (1.0, 10.0)

    def test_float_range(self):
        from electrochem_v6.core.processing_lsv import _parse_tafel_range
        assert _parse_tafel_range("0.5-5.0") == (0.5, 5.0)

    def test_none_input(self):
        from electrochem_v6.core.processing_lsv import _parse_tafel_range
        assert _parse_tafel_range(None) is None

    def test_empty_string(self):
        from electrochem_v6.core.processing_lsv import _parse_tafel_range
        assert _parse_tafel_range("") is None

    def test_single_value(self):
        from electrochem_v6.core.processing_lsv import _parse_tafel_range
        result = _parse_tafel_range("5")
        assert result == (5.0, 5.0)

    def test_invalid_text(self):
        from electrochem_v6.core.processing_lsv import _parse_tafel_range
        assert _parse_tafel_range("abc") is None

    def test_chinese_comma_treated_as_text(self):
        from electrochem_v6.core.processing_lsv import _parse_tafel_range
        # Chinese comma is replaced, then split on '-'
        result = _parse_tafel_range("1，10")
        # No '-', so lo=hi="1,10" which is invalid
        assert result is None

    def test_whitespace(self):
        from electrochem_v6.core.processing_lsv import _parse_tafel_range
        assert _parse_tafel_range(" 2 - 8 ") == (2.0, 8.0)


# ── interpolate_multiple_potentials ───────────────────────────────────────

class TestInterpolateMultiplePotentials:
    def test_multiple_targets(self):
        from electrochem_v6.core.processing_lsv import interpolate_multiple_potentials
        potential = [0.0, 0.5, 1.0, 1.5]
        current = [1.0, 10.0, 50.0, 100.0]
        results = interpolate_multiple_potentials(potential, current, [10.0, 50.0])
        assert 10.0 in results
        assert 50.0 in results
        assert abs(results[10.0] - 0.5) < 1e-6
        assert abs(results[50.0] - 1.0) < 1e-6

    def test_out_of_range_target_skipped(self):
        from electrochem_v6.core.processing_lsv import interpolate_multiple_potentials
        potential = [0.0, 0.5, 1.0]
        current = [10.0, 20.0, 30.0]
        results = interpolate_multiple_potentials(potential, current, [5.0, 20.0, 50.0])
        assert 20.0 in results
        assert 5.0 not in results
        assert 50.0 not in results

    def test_empty_targets(self):
        from electrochem_v6.core.processing_lsv import interpolate_multiple_potentials
        results = interpolate_multiple_potentials([0.0, 1.0], [10.0, 20.0], [])
        assert results == {}


# ── process_lsv advanced features ─────────────────────────────────────────

class TestProcessLsvAdvanced:
    @pytest.fixture
    def lsv_dir(self, tmp_path):
        """Create temp dir with a realistic LSV data file (50 points)."""
        sample_dir = tmp_path / "sample_adv"
        sample_dir.mkdir()
        lines = []
        for i in range(50):
            v = 0.0 + i * 0.03
            i_A = 1e-6 * np.exp(5.0 * v)
            lines.append(f"{v:.6f}\t{i_A:.10f}")
        (sample_dir / "LSV_adv.txt").write_text("\n".join(lines), encoding="utf-8")
        return sample_dir

    def _base_params(self, **overrides):
        params = {
            "start_line": "1", "offset": "0", "area": "1.0",
            "target_current": "10", "use_abs_current": True,
            "tafel_enabled": False, "overpotential_enabled": False,
            "onset_enabled": False, "halfwave_enabled": False,
            "ir_compensation_enabled": False, "lsv_line_color": "blue",
            "font_family": "", "font_size": "12", "plot_grid": False,
            "xlabel": "Potential (V)", "ylabel": "Current (mA/cm²)",
            "title": "LSV - {sample}", "fontsize": "12", "font": "",
            "line_color": "blue", "line_width": 2.0,
        }
        params.update(overrides)
        return params

    def test_tafel_enabled(self, lsv_dir):
        from electrochem_v6.core.processing_lsv import process_lsv
        params = self._base_params(tafel_enabled=True, tafel_range="1-100")
        result = process_lsv(str(lsv_dir), "LSV_adv.txt", params)
        assert result is not None

    def test_overpotential_enabled(self, lsv_dir):
        from electrochem_v6.core.processing_lsv import process_lsv
        params = self._base_params(overpotential_enabled=True, eq_potential="1.23")
        result = process_lsv(str(lsv_dir), "LSV_adv.txt", params)
        assert result is not None

    def test_onset_enabled(self, lsv_dir):
        from electrochem_v6.core.processing_lsv import process_lsv
        params = self._base_params(onset_enabled=True, onset_current="1.0")
        result = process_lsv(str(lsv_dir), "LSV_adv.txt", params)
        assert result is not None

    def test_halfwave_enabled(self, lsv_dir):
        from electrochem_v6.core.processing_lsv import process_lsv
        params = self._base_params(halfwave_enabled=True)
        result = process_lsv(str(lsv_dir), "LSV_adv.txt", params)
        assert result is not None

    def test_multiple_target_currents(self, lsv_dir):
        from electrochem_v6.core.processing_lsv import process_lsv
        params = self._base_params(target_current="10,100")
        result = process_lsv(str(lsv_dir), "LSV_adv.txt", params)
        assert result is not None
        row = result.get("result_row") if isinstance(result, dict) else result
        # Multiple targets should produce a longer result row
        assert row is not None

    def test_collect_series(self, lsv_dir):
        from electrochem_v6.core.processing_lsv import process_lsv
        collector = []
        params = self._base_params(collect_series=collector)
        process_lsv(str(lsv_dir), "LSV_adv.txt", params)
        assert len(collector) >= 1
        assert "potential" in collector[0]
        assert "current" in collector[0]

    def test_all_features_combined(self, lsv_dir):
        from electrochem_v6.core.processing_lsv import process_lsv
        params = self._base_params(
            tafel_enabled=True, tafel_range="1-100",
            overpotential_enabled=True, eq_potential="1.23",
            onset_enabled=True, onset_current="1.0",
            halfwave_enabled=True,
            target_current="10,50",
        )
        result = process_lsv(str(lsv_dir), "LSV_adv.txt", params)
        assert result is not None

    def test_export_detail_excel(self, lsv_dir):
        from electrochem_v6.core.processing_lsv import process_lsv
        params = self._base_params(
            export_detail=True, export_format="xlsx",
        )
        result = process_lsv(str(lsv_dir), "LSV_adv.txt", params)
        assert result is not None
        # Check xlsx file was created
        import glob
        xlsx_files = glob.glob(str(lsv_dir / "*.xlsx"))
        assert len(xlsx_files) >= 1
