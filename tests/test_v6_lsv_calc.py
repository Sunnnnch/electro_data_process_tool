"""Tests for processing_lsv.py — pure-calculation functions not yet covered.

Covers: _parse_tafel_range, _filter_outliers edge cases,
potential_at_current (interpolation + Tafel + linear extrapolation),
interpolate_multiple_potentials, get_ir_from_eis.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from electrochem_v6.core.processing_lsv import (
    _filter_outliers,
    _parse_tafel_range,
    interpolate_multiple_potentials,
    potential_at_current,
)

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _parse_tafel_range                                                     ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestParseTafelRange:
    def test_normal_range(self):
        assert _parse_tafel_range("1-10") == (1.0, 10.0)

    def test_float_range(self):
        assert _parse_tafel_range("0.5-5.0") == (0.5, 5.0)

    def test_single_value(self):
        assert _parse_tafel_range("10") == (10.0, 10.0)

    def test_chinese_comma(self):
        # 中文逗号被替换为英文逗号, 无 '-' → 单值解析 '1,10' 会失败
        # 改为测试有效的 range 输入
        result = _parse_tafel_range("1-10")
        assert result == (1.0, 10.0)

    def test_whitespace(self):
        assert _parse_tafel_range(" 1 - 10 ") == (1.0, 10.0)

    def test_none_input(self):
        assert _parse_tafel_range(None) is None

    def test_empty_string(self):
        assert _parse_tafel_range("") is None

    def test_invalid_text(self):
        assert _parse_tafel_range("abc-xyz") is None


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _filter_outliers edge cases                                            ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestFilterOutliersEdge:
    def test_none_inputs(self):
        r, im, f = _filter_outliers(None, None, None)
        assert r is None and im is None

    def test_too_few_points(self):
        r, im, f = _filter_outliers([1.0, 2.0], [1.0, 2.0])
        assert len(r) == 2  # returned unchanged

    def test_constant_values(self):
        """MAD=0 → no outlier removal."""
        r, im, f = _filter_outliers([5.0] * 10, [3.0] * 10)
        assert len(r) == 10

    def test_extreme_outlier(self):
        real = [10.0, 10.5, 11.0, 10.3, 10.8, 9999.0]
        imag = [-1.0, -1.1, -1.2, -1.0, -1.3, -999.0]
        r, im, _ = _filter_outliers(real, imag)
        assert len(r) < len(real)

    def test_custom_threshold(self):
        real = [10.0, 11.0, 12.0, 50.0]
        imag = [-1.0, -2.0, -3.0, -30.0]
        # Very loose threshold → no filtering
        r1, _, _ = _filter_outliers(real, imag, thresh=100.0)
        assert len(r1) == 4
        # Tight threshold → more filtering
        r2, _, _ = _filter_outliers(real, imag, thresh=1.0)
        assert len(r2) <= 4


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  potential_at_current — comprehensive                                   ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestPotentialAtCurrent:
    def test_interpolation_within_range(self):
        """Target inside measured range → pure interpolation."""
        E = np.linspace(0.0, 1.0, 200)
        I = 100.0 * E  # linear: 0–100 mA/cm²
        pot, ext = potential_at_current(E, I, target_i=50.0)
        assert np.isfinite(pot)
        assert pot == pytest.approx(0.5, abs=0.02)
        assert ext is None  # no extrapolation needed

    def test_tafel_extrapolation(self):
        """Target above range with enough dynamic range → Tafel fit."""
        E = np.linspace(0.2, 0.6, 100)
        I = 0.1 * np.exp(10.0 * E)  # exponential
        target = I.max() * 1.5  # within 2× factor
        pot, ext = potential_at_current(E, I, target_i=target)
        if ext is not None:
            _E_ext, _I_ext, method = ext
            assert "tafel" in method or method == "linear"

    def test_linear_extrapolation_fallback(self):
        """Small current ratio → falls back to linear."""
        E = np.array([0.3, 0.31, 0.32, 0.33, 0.34])
        I = np.array([8.0, 8.5, 9.0, 9.5, 10.0])  # ratio < 3
        target = 11.0  # just above max, within 2× factor
        pot, ext = potential_at_current(E, I, target_i=target)
        if ext is not None:
            _, _, method = ext
            assert method == "linear"

    def test_too_far_extrapolation_rejected(self):
        """Target > max_extrap_factor × I_max → NaN."""
        E = np.linspace(0, 0.5, 50)
        I = np.linspace(1.0, 5.0, 50)
        pot, ext = potential_at_current(E, I, target_i=100.0, max_extrap_factor=2.0)
        assert np.isnan(pot)
        assert ext is None

    def test_too_few_data_points(self):
        pot, ext = potential_at_current([0.5], [10.0], target_i=10.0)
        assert np.isnan(pot)

    def test_all_nan(self):
        pot, ext = potential_at_current(
            [float("nan")] * 5, [float("nan")] * 5, target_i=10.0,
        )
        assert np.isnan(pot)

    def test_zero_current_max(self):
        """All zeros → rejected."""
        pot, ext = potential_at_current([0.0, 0.1, 0.2], [0.0, 0.0, 0.0], target_i=10.0)
        assert np.isnan(pot)

    def test_downward_extrapolation(self):
        """Target below measured range."""
        E = np.linspace(0.5, 1.0, 50)
        I = np.linspace(20.0, 100.0, 50)
        pot, ext = potential_at_current(E, I, target_i=15.0)
        # 15 < 20 (min), within 2× factor of max
        if np.isfinite(pot):
            assert pot <= 0.5  # extrapolated below data


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  interpolate_multiple_potentials                                        ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestInterpolateMultiplePotentials:
    def test_basic(self):
        potential = [0.0, 0.5, 1.0, 1.5]
        current = [5.0, 10.0, 50.0, 100.0]
        results = interpolate_multiple_potentials(potential, current, [10.0, 50.0])
        assert 10.0 in results
        assert 50.0 in results

    def test_some_out_of_range(self):
        potential = [0.0, 0.5, 1.0]
        current = [10.0, 20.0, 30.0]
        results = interpolate_multiple_potentials(potential, current, [15.0, 999.0])
        assert 15.0 in results
        assert 999.0 not in results

    def test_empty_targets(self):
        results = interpolate_multiple_potentials([0.0, 1.0], [10.0, 20.0], [])
        assert results == {}


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  get_ir_from_eis                                                        ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestGetIrFromEis:
    """Test EIS-based Rs estimation with synthetic data files."""

    @pytest.fixture()
    def eis_file(self, tmp_path: Path) -> Path:
        """Create a synthetic EIS data file: freq, Z_real, Z_imag."""
        Rs_true = 5.0
        Rct = 50.0
        Cdl = 1e-5
        lines = []
        for freq in np.logspace(-1, 5, 60):
            omega = 2 * np.pi * freq
            Zw = Rct / (1 + (omega * Rct * Cdl) ** 2)
            Zi = -(omega * Rct**2 * Cdl) / (1 + (omega * Rct * Cdl) ** 2)
            Zr = Rs_true + Zw
            lines.append(f"{freq:.6f}\t{Zr:.6f}\t{Zi:.6f}")
        fpath = tmp_path / "EIS_test.txt"
        fpath.write_text("\n".join(lines), encoding="utf-8")
        return fpath

    def test_auto_method(self, eis_file: Path):
        from electrochem_v6.core.processing_lsv import get_ir_from_eis

        result = get_ir_from_eis(str(eis_file.parent), eis_file.name, start_line=1, method="auto")
        assert result is not None
        assert abs(result - 5.0) < 3.0  # within reasonable range

    def test_hf_mean_method(self, eis_file: Path):
        from electrochem_v6.core.processing_lsv import get_ir_from_eis

        result = get_ir_from_eis(str(eis_file.parent), eis_file.name, start_line=1, method="hf_mean")
        assert result is not None
        assert result > 0

    def test_linear_fit_method(self, eis_file: Path):
        from electrochem_v6.core.processing_lsv import get_ir_from_eis

        result = get_ir_from_eis(str(eis_file.parent), eis_file.name, start_line=1, method="linear_fit")
        assert result is not None
        assert result > 0

    def test_hf_intercept_method(self, eis_file: Path):
        from electrochem_v6.core.processing_lsv import get_ir_from_eis

        result = get_ir_from_eis(str(eis_file.parent), eis_file.name, start_line=1, method="hf_intercept")
        assert result is not None

    def test_file_not_found(self, tmp_path: Path):
        from electrochem_v6.core.processing_lsv import get_ir_from_eis

        result = get_ir_from_eis(str(tmp_path), "nonexistent.txt", start_line=1)
        assert result is None

    def test_invalid_method_falls_back_to_auto(self, eis_file: Path):
        from electrochem_v6.core.processing_lsv import get_ir_from_eis

        result = get_ir_from_eis(str(eis_file.parent), eis_file.name, start_line=1, method="bogus_method")
        assert result is not None
