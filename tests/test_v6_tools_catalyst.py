"""Tests for agent/tools_catalyst.py — pure-logic helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from electrochem_v6.agent.tools_catalyst import (
    _evaluate_lsv_performance,
    _generate_overall_assessment,
    tool_get_catalyst_info,
)

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _evaluate_lsv_performance                                              ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestEvaluateLsvPerformance:
    @pytest.mark.parametrize(
        "eta, expected_stars",
        [
            (0.05, "⭐⭐⭐⭐⭐"),    # < 0.10 → 卓越
            (0.09, "⭐⭐⭐⭐⭐"),
            (0.20, "⭐⭐⭐⭐"),       # < 0.30 → 优秀
            (0.35, "⭐⭐⭐"),          # < 0.40 → 良好
            (0.45, "⭐⭐"),             # < 0.50 → 一般
            (0.60, "⭐"),               # ≥ 0.50 → 需要改进
        ],
    )
    def test_rating_levels(self, eta: float, expected_stars: str):
        result = _evaluate_lsv_performance(eta=eta)
        assert result.startswith(expected_stars)

    def test_none_eta(self):
        assert _evaluate_lsv_performance() == "未知"

    def test_tafel_ignored(self):
        """Tafel slope doesn't affect rating currently."""
        r1 = _evaluate_lsv_performance(eta=0.20, tafel=40.0)
        r2 = _evaluate_lsv_performance(eta=0.20, tafel=120.0)
        assert r1 == r2


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _generate_overall_assessment                                           ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestGenerateOverallAssessment:
    def test_no_data(self):
        info = {"data_types_available": []}
        assert _generate_overall_assessment(info) == "无可用数据"

    def test_lsv_only(self):
        info = {
            "data_types_available": ["LSV"],
            "lsv": {"performance_level": "⭐⭐⭐⭐ 优秀"},
        }
        result = _generate_overall_assessment(info)
        assert "LSV" in result
        assert "优秀" in result

    def test_eis_low_rs(self):
        info = {
            "data_types_available": ["EIS"],
            "eis": {"Rs": 5.0},
        }
        result = _generate_overall_assessment(info)
        assert "良好" in result

    def test_eis_high_rs(self):
        info = {
            "data_types_available": ["EIS"],
            "eis": {"Rs": 20.0},
        }
        result = _generate_overall_assessment(info)
        assert "较高" in result

    def test_ecsa_large(self):
        info = {
            "data_types_available": ["ECSA"],
            "ecsa": {"ECSA": 5.0},
        }
        result = _generate_overall_assessment(info)
        assert "优秀" in result

    def test_ecsa_small(self):
        info = {
            "data_types_available": ["ECSA"],
            "ecsa": {"ECSA": 0.5},
        }
        result = _generate_overall_assessment(info)
        assert "一般" in result

    def test_combined_types(self):
        info = {
            "data_types_available": ["LSV", "EIS"],
            "lsv": {"performance_level": "⭐⭐⭐ 良好"},
            "eis": {"Rs": 5.0},
        }
        result = _generate_overall_assessment(info)
        assert "LSV" in result
        assert "EIS" in result

    def test_types_without_details(self):
        """Only CV available but no assessment logic for it."""
        info = {"data_types_available": ["CV"]}
        result = _generate_overall_assessment(info)
        assert "1种类型" in result

    def test_eis_no_rs(self):
        info = {
            "data_types_available": ["EIS"],
            "eis": {"Rs": None},
        }
        result = _generate_overall_assessment(info)
        # No Rs → EIS block skipped, falls to generic
        assert isinstance(result, str)

    def test_ecsa_no_value(self):
        info = {
            "data_types_available": ["ECSA"],
            "ecsa": {"ECSA": None},
        }
        result = _generate_overall_assessment(info)
        assert isinstance(result, str)


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  tool_get_catalyst_info (with mocked history manager)                   ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

def _make_record(sample: str, dtype: str, **results) -> dict:
    """Shorthand to build a history record."""
    return {
        "sample_name": sample,
        "type": dtype,
        "timestamp": "2026-01-01 12:00:00",
        "results": results,
    }


class TestToolGetCatalystInfo:
    """Integration tests for tool_get_catalyst_info using mocked storage."""

    PATCH_TARGET = "electrochem_v6.store.legacy_runtime.get_history_manager_v6"

    @patch(PATCH_TARGET)
    def test_no_records_found(self, mock_hist):
        mgr = MagicMock()
        mgr.get_all_records.return_value = []
        mock_hist.return_value = mgr

        result = tool_get_catalyst_info("unknown-sample")
        assert result["success"] is False
        assert "未找到" in result["message"]

    @patch(PATCH_TARGET)
    def test_lsv_only(self, mock_hist):
        mgr = MagicMock()
        mgr.get_all_records.return_value = [
            _make_record("Cat-A", "LSV", overpotential_10=0.28, tafel_slope=68),
            _make_record("Cat-A", "LSV", overpotential_10=0.30, tafel_slope=72),
        ]
        mock_hist.return_value = mgr

        result = tool_get_catalyst_info("Cat-A")
        assert result["success"] is True
        assert result["total_records"] == 2
        assert "LSV" in result["data_types_available"]
        lsv = result["lsv"]
        assert lsv["record_count"] == 2
        assert lsv["overpotential_10"] == pytest.approx(0.29)
        assert lsv["tafel_slope"] == pytest.approx(70.0)
        assert "all_measurements" in lsv  # include_details=True by default

    @patch(PATCH_TARGET)
    def test_lsv_without_details(self, mock_hist):
        mgr = MagicMock()
        mgr.get_all_records.return_value = [
            _make_record("Cat-A", "LSV", overpotential_10=0.25, tafel_slope=60),
        ]
        mock_hist.return_value = mgr

        result = tool_get_catalyst_info("Cat-A", include_details=False)
        assert result["success"] is True
        assert "all_measurements" not in result["lsv"]

    @patch(PATCH_TARGET)
    def test_all_data_types(self, mock_hist):
        mgr = MagicMock()
        mgr.get_all_records.return_value = [
            _make_record("Cat-B", "LSV", overpotential_10=0.30, tafel_slope=70),
            _make_record("Cat-B", "CV", potential_range="0-1V", current_range="0-5mA", data_points=200),
            _make_record("Cat-B", "EIS", Rs=5.0, Rct=50.0),
            _make_record("Cat-B", "ECSA", Cdl=0.03, ECSA=2.5, RF=12.5),
        ]
        mock_hist.return_value = mgr

        result = tool_get_catalyst_info("Cat-B")
        assert result["success"] is True
        assert set(result["data_types_available"]) == {"LSV", "CV", "EIS", "ECSA"}
        assert result["cv"]["record_count"] == 1
        assert result["eis"]["Rs"] == pytest.approx(5.0)
        assert result["eis"]["Rct"] == pytest.approx(50.0)
        assert result["ecsa"]["Cdl"] == pytest.approx(0.03)
        assert result["ecsa"]["ECSA"] == pytest.approx(2.5)
        assert result["ecsa"]["RF"] == pytest.approx(12.5)
        assert "overall_assessment" in result

    @patch(PATCH_TARGET)
    def test_filters_by_sample_name(self, mock_hist):
        mgr = MagicMock()
        mgr.get_all_records.return_value = [
            _make_record("Cat-A", "LSV", overpotential_10=0.20),
            _make_record("Cat-B", "LSV", overpotential_10=0.40),
        ]
        mock_hist.return_value = mgr

        result_a = tool_get_catalyst_info("Cat-A")
        assert result_a["total_records"] == 1
        assert result_a["lsv"]["overpotential_10"] == pytest.approx(0.20)

    @patch(PATCH_TARGET)
    def test_eis_multiple_averages(self, mock_hist):
        mgr = MagicMock()
        mgr.get_all_records.return_value = [
            _make_record("Cat-C", "EIS", Rs=4.0, Rct=40.0),
            _make_record("Cat-C", "EIS", Rs=6.0, Rct=60.0),
        ]
        mock_hist.return_value = mgr

        result = tool_get_catalyst_info("Cat-C")
        assert result["eis"]["Rs"] == pytest.approx(5.0)
        assert result["eis"]["Rct"] == pytest.approx(50.0)

    @patch(PATCH_TARGET)
    def test_ecsa_averages(self, mock_hist):
        mgr = MagicMock()
        mgr.get_all_records.return_value = [
            _make_record("Cat-D", "ECSA", Cdl=0.02, ECSA=2.0, RF=10.0),
            _make_record("Cat-D", "ECSA", Cdl=0.04, ECSA=4.0, RF=20.0),
        ]
        mock_hist.return_value = mgr

        result = tool_get_catalyst_info("Cat-D")
        assert result["ecsa"]["Cdl"] == pytest.approx(0.03)
        assert result["ecsa"]["ECSA"] == pytest.approx(3.0)
        assert result["ecsa"]["RF"] == pytest.approx(15.0)

    @patch(PATCH_TARGET)
    def test_exception_returns_error(self, mock_hist):
        mock_hist.side_effect = RuntimeError("storage broken")
        result = tool_get_catalyst_info("Cat-E")
        assert result["success"] is False
        assert "storage broken" in result["error"]
        assert "traceback" in result

    @patch(PATCH_TARGET)
    def test_missing_results_keys(self, mock_hist):
        """Records with empty results should not crash averaging."""
        mgr = MagicMock()
        mgr.get_all_records.return_value = [
            _make_record("Cat-F", "LSV"),  # no overpotential_10 or tafel_slope
        ]
        mock_hist.return_value = mgr

        result = tool_get_catalyst_info("Cat-F")
        assert result["success"] is True
        assert result["lsv"]["overpotential_10"] is None
        assert result["lsv"]["tafel_slope"] is None
