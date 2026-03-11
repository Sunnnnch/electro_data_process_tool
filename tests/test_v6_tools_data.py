"""Tests for agent/tools_data.py — file scanning, preview, analysis."""
from __future__ import annotations

from pathlib import Path

import pytest

from electrochem_v6.agent.tools_data import (
    tool_analyze_data_characteristics,
    tool_preview_data_file,
    tool_scan_data_folder,
)

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  tool_scan_data_folder                                                  ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestScanDataFolder:
    @pytest.fixture()
    def data_folder(self, tmp_path: Path) -> Path:
        sub = tmp_path / "sample_A"
        sub.mkdir()
        (sub / "LSV_test.txt").write_text("0.0\t1e-5\n0.1\t2e-5\n", encoding="utf-8")
        (sub / "CV_data.csv").write_text("0.0,1e-5\n", encoding="utf-8")
        (sub / "EIS_scan.txt").write_text("1000\t10\t-5\n", encoding="utf-8")
        (sub / "ECSA50.txt").write_text("0.0\t1e-5\n", encoding="utf-8")
        (sub / "random.txt").write_text("hello\n", encoding="utf-8")
        (sub / "image.png").write_bytes(b"\x89PNG\r\n")
        return tmp_path

    def test_basic_scan(self, data_folder: Path):
        result = tool_scan_data_folder(str(data_folder))
        assert result["success"] is True
        assert result["total_files"] == 5  # only .txt/.csv
        by_type = result["statistics"]["by_type"]
        assert by_type.get("LSV", 0) >= 1
        assert by_type.get("CV", 0) >= 1
        assert by_type.get("EIS", 0) >= 1
        assert by_type.get("ECSA", 0) >= 1
        assert by_type.get("Unknown", 0) >= 1

    def test_nonexistent_folder(self):
        result = tool_scan_data_folder("/nonexistent/path/xyz")
        assert result["success"] is False

    def test_empty_folder(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = tool_scan_data_folder(str(empty))
        assert result["success"] is True
        assert result["total_files"] == 0


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  tool_preview_data_file                                                 ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestPreviewDataFile:
    def test_normal_txt(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("Potential\tCurrent\n0.0\t1e-5\n0.1\t2e-5\n", encoding="utf-8")
        result = tool_preview_data_file(str(f), lines=10)
        assert result["success"] is True
        assert result["has_header"] is True
        assert result["detected_type"] == "LSV/CV"

    def test_eis_detection(self, tmp_path: Path):
        f = tmp_path / "eis.csv"
        f.write_text("Frequency\tZ_real\tZ_imag\n1000\t10\t-5\n", encoding="utf-8")
        result = tool_preview_data_file(str(f))
        assert result["detected_type"] == "EIS"

    def test_unsupported_extension(self, tmp_path: Path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00\x01\x02")
        result = tool_preview_data_file(str(f))
        assert result["success"] is False
        assert "不支持" in result["error"]

    def test_file_not_found(self):
        result = tool_preview_data_file("/nonexistent/file.txt")
        assert result["success"] is False


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  tool_analyze_data_characteristics                                      ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestAnalyzeDataCharacteristics:
    def test_lsv_analysis(self, tmp_path: Path):
        f = tmp_path / "lsv.txt"
        lines = ["potential\tcurrent"]
        for i in range(50):
            v = i * 0.02
            c = 0.001 * v  # simple linear
            lines.append(f"{v}\t{c}")
        f.write_text("\n".join(lines), encoding="utf-8")
        result = tool_analyze_data_characteristics(str(f), "LSV")
        assert result["success"] is True
        assert "characteristics" in result
        assert result["characteristics"]["data_start_line"] >= 1

    def test_invalid_file(self):
        result = tool_analyze_data_characteristics("/nonexistent/file.txt", "LSV")
        assert result["success"] is False
