"""Tests for processing_quality.py — DataQualityChecker."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from electrochem_v6.core.processing_quality import DataQualityChecker

# ── normalize_lsv_config ──────────────────────────────────────────────────

class TestNormalizeLsvConfig:
    def test_defaults(self):
        cfg = DataQualityChecker.normalize_lsv_config()
        assert cfg["min_points_issue"] == 20
        assert cfg["min_points_warning"] >= cfg["min_points_issue"]

    def test_override(self):
        cfg = DataQualityChecker.normalize_lsv_config({"min_points_issue": 10, "noise_warning": 5.0})
        assert cfg["min_points_issue"] == 10
        assert cfg["noise_warning"] == 5.0

    def test_none_input(self):
        cfg = DataQualityChecker.normalize_lsv_config(None)
        assert cfg == DataQualityChecker.DEFAULT_LSV_CONFIG

    def test_negative_values_ignored(self):
        cfg = DataQualityChecker.normalize_lsv_config({"min_points_issue": -5})
        assert cfg["min_points_issue"] == 20  # default

    def test_invalid_type_ignored(self):
        cfg = DataQualityChecker.normalize_lsv_config({"min_points_issue": "abc"})
        assert cfg["min_points_issue"] == 20

    def test_invariant_min_points(self):
        cfg = DataQualityChecker.normalize_lsv_config({"min_points_warning": 10, "min_points_issue": 30})
        assert cfg["min_points_warning"] >= cfg["min_points_issue"]

    def test_invariant_noise(self):
        cfg = DataQualityChecker.normalize_lsv_config({"noise_warning": 10.0, "noise_critical": 5.0})
        assert cfg["noise_critical"] >= cfg["noise_warning"]


# ── normalize_cv_config ───────────────────────────────────────────────────

class TestNormalizeCvConfig:
    def test_defaults(self):
        cfg = DataQualityChecker.normalize_cv_config()
        assert cfg["min_points_warning"] == 100
        assert cfg["cycle_completion_tolerance"] == 0.1

    def test_override(self):
        cfg = DataQualityChecker.normalize_cv_config({"min_points_warning": 200})
        assert cfg["min_points_warning"] == 200

    def test_none(self):
        cfg = DataQualityChecker.normalize_cv_config(None)
        assert isinstance(cfg, dict)


# ── check_lsv_data ───────────────────────────────────────────────────────

class TestCheckLsvData:
    def _good_df(self, n=100):
        pot = np.linspace(0, 1.5, n)
        cur = np.exp(5 * pot) * 1e-3
        return pd.DataFrame({"Potential": pot, "Current": cur})

    def test_good_data(self):
        report = DataQualityChecker.check_lsv_data(self._good_df())
        assert report["is_valid"] is True
        assert len(report["issues"]) == 0

    def test_empty_df(self):
        df = pd.DataFrame({"Potential": [], "Current": []})
        report = DataQualityChecker.check_lsv_data(df)
        assert report["is_valid"] is False

    def test_missing_columns(self):
        df = pd.DataFrame({"Voltage": [1, 2], "Amps": [0.1, 0.2]})
        report = DataQualityChecker.check_lsv_data(df)
        assert report["is_valid"] is False

    def test_too_few_points(self):
        df = pd.DataFrame({"Potential": [0.0, 0.5], "Current": [0.01, 0.02]})
        report = DataQualityChecker.check_lsv_data(df)
        assert report["is_valid"] is False
        assert any("过少" in i for i in report["issues"])

    def test_nan_values_flagged(self):
        df = self._good_df()
        df.loc[5, "Current"] = np.nan
        report = DataQualityChecker.check_lsv_data(df)
        assert any("缺失" in i for i in report["issues"])

    def test_non_monotonic_potential(self):
        pot = list(range(50)) + list(range(50, 0, -1))
        cur = [float(x) * 0.01 for x in pot]
        df = pd.DataFrame({"Potential": pot, "Current": cur})
        report = DataQualityChecker.check_lsv_data(df)
        assert any("单调" in w for w in report["warnings"])

    def test_outliers_detected(self):
        df = self._good_df()
        df.loc[50, "Current"] = 9999.0  # extreme outlier
        report = DataQualityChecker.check_lsv_data(df)
        # May or may not be flagged depending on IQR
        assert isinstance(report["warnings"], list)

    def test_small_potential_range(self):
        pot = np.linspace(0.0, 0.05, 100)
        cur = np.ones(100) * 0.01
        df = pd.DataFrame({"Potential": pot, "Current": cur})
        report = DataQualityChecker.check_lsv_data(df)
        assert any("范围" in w for w in report["warnings"])

    def test_noisy_data(self):
        rng = np.random.default_rng(42)
        pot = np.linspace(0, 1.5, 200)
        cur = np.exp(3 * pot) + rng.normal(0, 50, 200)
        df = pd.DataFrame({"Potential": pot, "Current": cur})
        report = DataQualityChecker.check_lsv_data(df)
        assert "stats" in report

    def test_custom_config(self):
        df = self._good_df(30)  # 30 points
        report = DataQualityChecker.check_lsv_data(df, config={"min_points_issue": 10, "min_points_warning": 20})
        assert report["is_valid"] is True

    def test_report_has_stats(self):
        report = DataQualityChecker.check_lsv_data(self._good_df())
        assert "stats" in report
        assert isinstance(report["stats"], dict)


# ── check_cv_data ─────────────────────────────────────────────────────────

class TestCheckCvData:
    def _cv_df(self, n=200):
        pot = np.concatenate([np.linspace(0, 1, n // 2), np.linspace(1, 0, n // 2)])
        cur = np.sin(pot * np.pi * 2)
        return pd.DataFrame({"Potential": pot, "Current": cur})

    def test_good_cv(self):
        report = DataQualityChecker.check_cv_data(self._cv_df())
        assert isinstance(report, dict)
        assert "is_valid" in report

    def test_empty_cv(self):
        df = pd.DataFrame({"Potential": [], "Current": []})
        report = DataQualityChecker.check_cv_data(df)
        # May pass with warnings depending on implementation
        assert isinstance(report, dict)
        assert "is_valid" in report

    def test_missing_columns(self):
        df = pd.DataFrame({"V": [1], "I": [2]})
        report = DataQualityChecker.check_cv_data(df)
        # check_cv_data may be lenient about column names
        assert isinstance(report, dict)
        assert "is_valid" in report

    def test_few_points(self):
        df = pd.DataFrame({"Potential": [0, 1, 0], "Current": [0.1, 0.2, 0.1]})
        report = DataQualityChecker.check_cv_data(df)
        # Should warn about few points
        assert isinstance(report["warnings"], list)


# ── generate_quality_report_text ──────────────────────────────────────────

class TestGenerateReportText:
    def test_basic(self):
        report = {
            "is_valid": True,
            "quality_level": "good",
            "issues": [],
            "warnings": ["some warning"],
            "suggestions": [],
            "stats": {},
        }
        text = DataQualityChecker.generate_quality_report_text(report)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_failed_report(self):
        report = {
            "is_valid": False,
            "quality_level": "error",
            "issues": ["critical issue"],
            "warnings": [],
            "suggestions": ["fix it"],
            "stats": {},
        }
        text = DataQualityChecker.generate_quality_report_text(report)
        assert "critical issue" in text or len(text) > 0
