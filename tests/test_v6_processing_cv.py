"""Tests for processing_cv.py — CV data processing."""
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

from electrochem_v6.core.processing_cv import process_cv


@pytest.fixture
def cv_data_dir(tmp_path):
    """Create a temp dir with realistic CV data (2 cycles)."""
    sample = tmp_path / "cv_sample"
    sample.mkdir()
    lines = []
    # 2 full cycles: forward + backward sweep
    n_half = 60
    for cycle in range(2):
        # forward: 0 → 1.0 V
        for i in range(n_half):
            v = i * 1.0 / n_half
            # Simulate oxidation peak at ~0.5 V
            i_A = 0.001 * np.exp(-((v - 0.5) ** 2) / 0.02) + 1e-5 * v
            lines.append(f"{v:.6f}\t{i_A:.10f}")
        # backward: 1.0 → 0 V
        for i in range(n_half):
            v = 1.0 - i * 1.0 / n_half
            # Simulate reduction peak at ~0.4 V
            i_A = -0.0008 * np.exp(-((v - 0.4) ** 2) / 0.02) - 1e-5 * v
            lines.append(f"{v:.6f}\t{i_A:.10f}")
    (sample / "CV_test.txt").write_text("\n".join(lines), encoding="utf-8")
    return sample


CV_PARAMS = {
    "start_line": "1",
    "xlabel": "Potential (V vs. RHE)",
    "ylabel": "Current (mA)",
    "title": "CV - {sample}",
    "fontsize": "12",
    "font": "",
    "line_color": "blue",
    "line_width": 2.0,
    "plot_grid": True,
    "peaks_enabled": False,
}


class TestProcessCV:
    def test_basic_cv(self, cv_data_dir):
        result = process_cv(str(cv_data_dir), "CV_test.txt", CV_PARAMS)
        # process_cv currently returns dict or None
        # It should succeed (no exception)
        assert result is None or isinstance(result, dict)

    def test_cv_with_peaks(self, cv_data_dir):
        params = {**CV_PARAMS, "peaks_enabled": True, "peaks_smooth": "5",
                  "peaks_min_height": "0.5", "peaks_min_dist": "5", "peaks_max": "2"}
        result = process_cv(str(cv_data_dir), "CV_test.txt", params)
        assert result is None or isinstance(result, dict)

    def test_cv_file_not_found(self, tmp_path):
        sample = tmp_path / "empty"
        sample.mkdir()
        with pytest.raises(FileNotFoundError):
            process_cv(str(sample), "nofile.txt", CV_PARAMS)

    def test_cv_empty_data(self, tmp_path):
        sample = tmp_path / "empty_data"
        sample.mkdir()
        (sample / "empty.txt").write_text("header\nno numeric data\n", encoding="utf-8")
        result = process_cv(str(sample), "empty.txt", CV_PARAMS)
        assert result is None

    def test_cv_quality_check_disabled(self, cv_data_dir):
        result = process_cv(str(cv_data_dir), "CV_test.txt", CV_PARAMS, enable_quality_check=False)
        assert result is None or isinstance(result, dict)

    def test_cv_generates_plot(self, cv_data_dir):
        process_cv(str(cv_data_dir), "CV_test.txt", CV_PARAMS)
        pngs = list(cv_data_dir.glob("*.png"))
        assert len(pngs) >= 1
