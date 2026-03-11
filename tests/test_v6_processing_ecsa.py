"""Tests for processing_ecsa.py — ECSA / Cdl / RF calculations."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

# conftest.py already handles matplotlib.use("Agg") and sys.path
from conftest import _write_tsv, make_ecsa_rows
from electrochem_v6.core.processing_ecsa import (
    _ecsa_extract_v_from_content,
    _ecsa_extract_v_from_name,
    _to_mF_per_cm2,
    compute_deltaJ_for_file,
    fit_deltaJ_vs_v,
    process_ecsa_for_subfolder,
)

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _ecsa_extract_v_from_name                                              ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestExtractVFromName:
    """Extract scan-rate from the file name."""

    @pytest.mark.parametrize(
        "filename, expected",
        [
            ("ECSA20.txt", 0.020),           # 20 mV/s
            ("ECSA100.csv", 0.100),
            ("ecsa_50.txt", 0.050),
            ("sample_40mVs.txt", 0.040),       # mVs no-slash variant
            ("sample_100mVs.txt", 0.100),      # mVs variant
            ("sample_0.05Vs.txt", 0.05),       # Vs notation
            ("random_file.txt", None),          # no scan-rate info
        ],
    )
    def test_various_patterns(self, filename: str, expected):
        result = _ecsa_extract_v_from_name(filename)
        if expected is None:
            assert result is None
        else:
            assert result == pytest.approx(expected, abs=1e-6)


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _ecsa_extract_v_from_content                                           ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestExtractVFromContent:
    """Extract scan-rate from file content lines."""

    def test_standard_header(self):
        lines = ["# metadata\n", "Scan Rate (V/s): 0.050\n", "0.0\t1e-5\n"]
        assert _ecsa_extract_v_from_content(lines) == pytest.approx(0.050)

    def test_equals_separator(self):
        lines = ["scan rate (V/s) = 0.100\n"]
        assert _ecsa_extract_v_from_content(lines) == pytest.approx(0.100)

    def test_no_match(self):
        lines = ["Potential\tCurrent\n", "0.0\t1.0\n"]
        assert _ecsa_extract_v_from_content(lines) is None


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _to_mF_per_cm2                                                         ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestToMFPerCm2:
    @pytest.mark.parametrize(
        "value, unit, expected",
        [
            (40.0, "mF/cm2", 40.0),
            (40.0, "mF/cm²", 40.0),
            (40.0, "mF", 40.0),
            (40.0, "uF/cm2", 0.040),
            (40.0, "μF/cm²", 0.040),
            (40.0, "uf", 0.040),
            (5.0, "unknown_unit", 5.0),    # fallback identity
        ],
    )
    def test_conversion(self, value, unit, expected):
        assert _to_mF_per_cm2(value, unit) == pytest.approx(expected, rel=1e-6)


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  fit_deltaJ_vs_v                                                        ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestFitDeltaJVsV:
    """Linear regression ΔJ = k·v + b."""

    def test_perfect_line(self):
        v = [0.02, 0.04, 0.06, 0.08, 0.10]
        dJ = [0.8, 1.6, 2.4, 3.2, 4.0]  # slope=40, intercept=0
        slope, intercept, r2 = fit_deltaJ_vs_v(v, dJ)
        assert slope == pytest.approx(40.0, rel=1e-4)
        assert intercept == pytest.approx(0.0, abs=0.01)
        assert r2 == pytest.approx(1.0, abs=1e-8)

    def test_with_offset(self):
        v = [0.02, 0.05, 0.10]
        dJ = [1.0 + 20 * vi for vi in v]  # slope=20, intercept=1
        slope, intercept, r2 = fit_deltaJ_vs_v(v, dJ)
        assert slope == pytest.approx(20.0, rel=1e-4)
        assert intercept == pytest.approx(1.0, abs=0.01)

    def test_too_few_points(self):
        assert fit_deltaJ_vs_v([0.02], [1.0]) == (None, None, None)

    def test_nan_filtered(self):
        v = [0.02, float("nan"), 0.06, 0.08]
        dJ = [0.8, 1.0, 2.4, 3.2]
        slope, _b, _r2 = fit_deltaJ_vs_v(v, dJ)
        assert slope is not None  # NaN row dropped, 3 points remain


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  compute_deltaJ_for_file                                                ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestComputeDeltaJForFile:
    """Integration-style: write a synthetic CV file, compute ΔJ."""

    @pytest.fixture()
    def ecsa_file(self, tmp_path: Path) -> Path:
        """Single ECSA file at 50 mV/s."""
        rows = make_ecsa_rows(scan_rate_Vs=0.050, Ev=0.10)
        return _write_tsv(tmp_path / "ECSA50.txt", rows)

    def test_returns_scan_rate_and_dJ(self, ecsa_file: Path):
        v, dJ = compute_deltaJ_for_file(str(ecsa_file), Ev=0.10)
        assert v == pytest.approx(0.050, abs=1e-4)
        assert dJ is not None
        assert dJ > 0

    def test_custom_area(self, ecsa_file: Path):
        v1, dJ1 = compute_deltaJ_for_file(str(ecsa_file), Ev=0.10, area_cm2=1.0)
        v2, dJ2 = compute_deltaJ_for_file(str(ecsa_file), Ev=0.10, area_cm2=2.0)
        # dJ is current-density → halved when area doubles
        assert dJ1 is not None and dJ2 is not None
        assert dJ1 == pytest.approx(dJ2 * 2, rel=0.1)

    def test_file_too_short(self, tmp_path: Path):
        short = tmp_path / "ECSA10.txt"
        short.write_text("0.0\t1e-5\n", encoding="utf-8")
        v, dJ = compute_deltaJ_for_file(str(short), Ev=0.10)
        # only 1 data point → can't find crossing pairs
        assert dJ is None

    def test_no_rate_in_name(self, tmp_path: Path):
        rows = make_ecsa_rows(scan_rate_Vs=0.020, Ev=0.10)
        fpath = _write_tsv(tmp_path / "unknown.txt", rows)
        v, dJ = compute_deltaJ_for_file(str(fpath), Ev=0.10)
        # filename doesn't encode scan-rate, no content header → v=None
        assert v is None


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  process_ecsa_for_subfolder (end-to-end)                                ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestProcessEcsaForSubfolder:
    """Full pipeline: multiple ECSA files → Cdl/ECSA/RF + PNG."""

    CDL_TRUE = 0.020  # mF/cm² used by make_ecsa_rows

    @pytest.fixture()
    def ecsa_folder(self, tmp_path: Path) -> Path:
        """Folder with 5 ECSA files at different scan-rates."""
        folder = tmp_path / "sample_A"
        folder.mkdir()
        for rate_mVs in [20, 40, 60, 80, 100]:
            rate_Vs = rate_mVs / 1000.0
            rows = make_ecsa_rows(scan_rate_Vs=rate_Vs, Ev=0.10, cdl_mFcm2=self.CDL_TRUE)
            _write_tsv(folder / f"ECSA{rate_mVs}.txt", rows)
        return folder

    def _default_params(self) -> tuple[dict, dict]:
        params = {
            "match_prefix": "ECSA",
            "match": "prefix",
            "ev": "0.10",
            "last_n": "1",
            "avg_last_n": False,
            "use_abs_delta": True,
            "cs_value": 40.0,
            "cs_unit": "µF/cm²",
            "line_width": "2.0",
            "plot_grid": True,
            "xlabel": "Scan rate v (V/s)",
            "ylabel": "ΔJ (mA/cm²)",
            "title": "ECSA of {sample} @ Ev={Ev:.3f} V",
        }
        common = {"area": "1.0", "fontsize": "12", "font": ""}
        return params, common

    def test_happy_path(self, ecsa_folder: Path):
        files = os.listdir(str(ecsa_folder))
        params, common = self._default_params()
        result = process_ecsa_for_subfolder(str(ecsa_folder), files, params, common)

        assert result is not None
        assert result["N_points"] == 5
        assert result["R2"] > 0.95
        # Cdl should be close to the synthetic value
        assert result["Cdl_mFcm2"] == pytest.approx(self.CDL_TRUE, rel=0.25)
        # PNG file generated
        assert Path(result["png"]).exists()

    def test_returns_rf(self, ecsa_folder: Path):
        files = os.listdir(str(ecsa_folder))
        params, common = self._default_params()
        result = process_ecsa_for_subfolder(str(ecsa_folder), files, params, common)
        assert result is not None
        assert "RF" in result
        assert result["RF"] > 0

    def test_no_matching_files(self, tmp_path: Path):
        folder = tmp_path / "empty_sample"
        folder.mkdir()
        (folder / "LSV_test.txt").write_text("0.0\t1e-5\n", encoding="utf-8")
        params, common = self._default_params()
        result = process_ecsa_for_subfolder(
            str(folder), os.listdir(str(folder)), params, common,
        )
        assert result is None

    def test_single_file_returns_none(self, tmp_path: Path):
        """Need ≥ 2 scan-rates for a fit."""
        folder = tmp_path / "one_file"
        folder.mkdir()
        rows = make_ecsa_rows(scan_rate_Vs=0.050, Ev=0.10, cdl_mFcm2=self.CDL_TRUE)
        _write_tsv(folder / "ECSA50.txt", rows)
        params, common = self._default_params()
        result = process_ecsa_for_subfolder(
            str(folder), os.listdir(str(folder)), params, common,
        )
        assert result is None  # only 1 point → can't fit
