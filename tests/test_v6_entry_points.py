"""Tests for entry points: cli.py, app.py, processing_core_v6 helpers."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ── cli.py ──────────────────────────────────────────────────────────────

class TestCli:
    def test_cli_info(self):
        from electrochem_v6.cli import cli_info
        result = cli_info()
        assert result["status"] == "ok"
        assert "message" in result


# ── app.py ──────────────────────────────────────────────────────────────

class TestApp:
    def test_run_check(self):
        from electrochem_v6.app import run_check
        result = run_check()
        assert "ok" in result
        assert "app_name" in result
        assert "app_version" in result

    def test_check_no_license_refs(self):
        from electrochem_v6.app import _check_no_license_refs
        result = _check_no_license_refs()
        assert result["ok"] is True  # No license refs in pure v6
        assert result["hits"] == []


# ── processing_core_v6 helpers ──────────────────────────────────────────

class TestProcessingCoreHelpers:
    def test_setup_logger(self, tmp_path):
        from electrochem_v6.core.processing_core_v6 import setup_logger
        logger = setup_logger(log_dir=str(tmp_path))
        assert logger is not None
        assert logger.name == "ElectroChem"

    def test_get_logger(self):
        from electrochem_v6.core.processing_core_v6 import get_logger
        logger = get_logger()
        assert logger is not None

    def test_log(self):
        from electrochem_v6.core.processing_core_v6 import log
        # Should not raise
        log("test message")

    def test_sanitize_filename(self):
        from electrochem_v6.core.processing_core_v6 import _sanitize_filename
        result = _sanitize_filename("hello world")
        assert isinstance(result, str)
        assert "/" not in _sanitize_filename("a/b\\c")
        assert "\\" not in _sanitize_filename("a/b\\c")

    def test_contains_cjk(self):
        from electrochem_v6.core.processing_core_v6 import _contains_cjk
        assert _contains_cjk("你好") is True
        assert _contains_cjk("hello") is False
        assert _contains_cjk("hello世界") is True

    def test_matches_named_file(self):
        from electrochem_v6.core.processing_core_v6 import _matches_named_file
        assert _matches_named_file("LSV_data.txt", "LSV", "LSV") is True
        assert _matches_named_file("CV_test.csv", "LSV", "LSV") is False

    def test_resolve_plot_font(self):
        from electrochem_v6.core.processing_core_v6 import _resolve_plot_font
        font = _resolve_plot_font(None)
        assert isinstance(font, str)
        assert len(font) > 0

    def test_resolve_plot_font_preferred(self):
        from electrochem_v6.core.processing_core_v6 import _resolve_plot_font
        font = _resolve_plot_font("Arial")
        assert isinstance(font, str)


# ── Exception classes ─────────────────────────────────────────────────────

class TestExceptions:
    def test_exception_hierarchy(self):
        from electrochem_v6.core.processing_core_v6 import (
            DataProcessingError,
            DataQualityError,
            ElectroChemException,
            FileFormatError,
            ParameterError,
        )
        assert issubclass(DataProcessingError, ElectroChemException)
        assert issubclass(FileFormatError, ElectroChemException)
        assert issubclass(ParameterError, ElectroChemException)
        assert issubclass(DataQualityError, ElectroChemException)
        assert issubclass(ElectroChemException, Exception)
