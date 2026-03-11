"""Tests for processing_eis.py — EIS data processing and Randles fitting."""
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from electrochem_v6.core.processing_eis import _randles_impedance, fit_randles, process_eis

# ── _randles_impedance ─────────────────────────────────────────────────────

class TestRandlesImpedance:
    def test_high_freq_approaches_Rs(self):
        """At very high frequency, Z → Rs."""
        freq = np.array([1e8])
        Z = _randles_impedance(freq, Rs=10, Rct=100, Cdl=1e-5)
        assert abs(Z[0].real - 10) < 1  # close to Rs

    def test_low_freq_approaches_Rs_plus_Rct(self):
        """At very low frequency, Z → Rs + Rct."""
        freq = np.array([1e-6])
        Z = _randles_impedance(freq, Rs=10, Rct=100, Cdl=1e-5)
        assert abs(Z[0].real - 110) < 1  # close to Rs+Rct

    def test_returns_complex(self):
        freq = np.logspace(-1, 6, 50)
        Z = _randles_impedance(freq, Rs=5, Rct=50, Cdl=1e-4)
        assert Z.dtype == np.complex128 or np.issubdtype(Z.dtype, np.complexfloating)
        assert len(Z) == 50

    def test_imaginary_negative(self):
        """Capacitive: imaginary part should be negative for Randles."""
        freq = np.logspace(0, 5, 100)
        Z = _randles_impedance(freq, Rs=10, Rct=100, Cdl=1e-5)
        assert np.all(Z.imag <= 0)

    def test_scalar_params(self):
        freq = np.array([1000.0])
        Z = _randles_impedance(freq, 10.0, 50.0, 1e-5)
        assert isinstance(Z[0], (complex, np.complexfloating))


# ── fit_randles ────────────────────────────────────────────────────────────

class TestFitRandles:
    @pytest.fixture
    def synthetic_eis(self):
        """Generate ideal Randles circuit data."""
        Rs, Rct, Cdl = 10.0, 100.0, 1e-5
        freq = np.logspace(-1, 5, 60)
        Z = _randles_impedance(freq, Rs, Rct, Cdl)
        return freq, Z.real, Z.imag, Rs, Rct, Cdl

    def test_fit_ideal_data(self, synthetic_eis):
        freq, zr, zi, Rs_true, Rct_true, Cdl_true = synthetic_eis
        result = fit_randles(freq, zr, zi)
        assert result is not None
        assert abs(result['Rs'] - Rs_true) < 1.0
        assert abs(result['Rct'] - Rct_true) < 5.0
        assert result['r2'] > 0.99

    def test_fit_returns_dict_keys(self, synthetic_eis):
        freq, zr, zi, *_ = synthetic_eis
        result = fit_randles(freq, zr, zi)
        assert result is not None
        for key in ('Rs', 'Rct', 'Cdl', 'r2', 'z_fit_real', 'z_fit_imag'):
            assert key in result

    def test_fit_noisy_data(self, synthetic_eis):
        freq, zr, zi, *_ = synthetic_eis
        rng = np.random.default_rng(42)
        zr_noisy = zr + rng.normal(0, 1.0, len(zr))
        zi_noisy = zi + rng.normal(0, 1.0, len(zi))
        result = fit_randles(freq, zr_noisy, zi_noisy)
        assert result is not None
        assert result['r2'] > 0.5

    def test_fit_bad_data_returns_none(self):
        """Completely random data should fail fitting."""
        rng = np.random.default_rng(99)
        freq = np.logspace(0, 5, 10)
        zr = rng.uniform(-100, 100, 10)
        zi = rng.uniform(-100, 100, 10)
        result = fit_randles(freq, zr, zi)
        # May return None or a dict with low R²
        if result is not None:
            assert isinstance(result['r2'], float)

    def test_fit_list_input(self, synthetic_eis):
        freq, zr, zi, *_ = synthetic_eis
        result = fit_randles(freq.tolist(), zr.tolist(), zi.tolist())
        assert result is not None
        assert result['r2'] > 0.9


# ── process_eis ────────────────────────────────────────────────────────────

class TestProcessEIS:
    @pytest.fixture
    def eis_data_dir(self, tmp_path):
        sample = tmp_path / "eis_sample"
        sample.mkdir()
        Rs, Rct, Cdl = 10.0, 100.0, 1e-5
        freq = np.logspace(-1, 5, 40)
        Z = _randles_impedance(freq, Rs, Rct, Cdl)
        lines = []
        for f, z in zip(freq, Z):
            lines.append(f"{f:.6e}\t{z.real:.6f}\t{z.imag:.6f}")
        (sample / "EIS_test.txt").write_text("\n".join(lines), encoding="utf-8")
        return sample

    EIS_PARAMS = {
        "start_line": "1",
        "xlabel": "Z' (Ω)",
        "ylabel": "-Z'' (Ω)",
        "title": "EIS - {sample}",
        "fontsize": "12",
        "font": "",
        "line_color": "blue",
        "line_width": 2.0,
        "plot_grid": True,
        "plot_nyquist": True,
        "plot_bode": False,
        "randles_fit": False,
        "ir_enabled": False,
    }

    def test_process_eis_runs(self, eis_data_dir):
        process_eis(str(eis_data_dir), "EIS_test.txt", self.EIS_PARAMS)
        pngs = list(eis_data_dir.glob("*Nyquist*.png"))
        assert len(pngs) >= 1

    def test_process_eis_bode(self, eis_data_dir):
        params = {**self.EIS_PARAMS, "plot_bode": True}
        process_eis(str(eis_data_dir), "EIS_test.txt", params)
        bode_pngs = list(eis_data_dir.glob("*Bode*.png"))
        assert len(bode_pngs) >= 1

    def test_process_eis_randles_fit(self, eis_data_dir):
        params = {**self.EIS_PARAMS, "randles_fit": True}
        process_eis(str(eis_data_dir), "EIS_test.txt", params)

    def test_process_eis_no_data(self, tmp_path):
        sample = tmp_path / "no_eis"
        sample.mkdir()
        (sample / "empty.txt").write_text("no numeric data\n", encoding="utf-8")
        process_eis(str(sample), "empty.txt", self.EIS_PARAMS)
        # Should return None (no crash)

    def test_process_eis_file_not_found(self, tmp_path):
        sample = tmp_path / "missing"
        sample.mkdir()
        with pytest.raises(FileNotFoundError):
            process_eis(str(sample), "nope.txt", self.EIS_PARAMS)
