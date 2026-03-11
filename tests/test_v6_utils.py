"""Tests for electrochem_v6.core.utils module."""

import os

import pytest

from electrochem_v6.core.utils import (
    as_bool,
    as_float,
    as_int,
    read_file_with_fallback_encodings,
)

# ── as_float ───────────────────────────────────────────────────────────────

class TestAsFloat:
    def test_valid_string(self):
        assert as_float("3.14", 0.0) == pytest.approx(3.14)

    def test_int_input(self):
        assert as_float(42, 0.0) == 42.0

    def test_invalid_returns_default(self):
        assert as_float("abc", -1.0) == -1.0

    def test_none_returns_default(self):
        assert as_float(None, 5.5) == 5.5


# ── as_int ─────────────────────────────────────────────────────────────────

class TestAsInt:
    def test_valid(self):
        assert as_int("10", 0) == 10

    def test_float_string_truncates(self):
        assert as_int(3.9, 0) == 3

    def test_garbage(self):
        assert as_int("xyz", 99) == 99


# ── as_bool ────────────────────────────────────────────────────────────────

class TestAsBool:
    @pytest.mark.parametrize("val", ["1", "true", "True", "YES", "on", "y"])
    def test_truthy_strings(self, val):
        assert as_bool(val) is True

    @pytest.mark.parametrize("val", ["0", "false", "False", "NO", "off", "n", "", "none"])
    def test_falsy_strings(self, val):
        assert as_bool(val) is False

    def test_none_returns_default(self):
        assert as_bool(None, True) is True
        assert as_bool(None, False) is False

    def test_bool_passthrough(self):
        assert as_bool(True) is True
        assert as_bool(False) is False

    def test_numeric(self):
        assert as_bool(1) is True
        assert as_bool(0) is False
        assert as_bool(0.0) is False


# ── read_file_with_fallback_encodings ──────────────────────────────────────

class TestReadFileWithFallbackEncodings:
    def test_reads_utf8(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")
        lines = read_file_with_fallback_encodings(str(f))
        assert len(lines) == 3
        assert lines[0].strip() == "line1"

    def test_start_line_skips(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("header\nrow1\nrow2\n", encoding="utf-8")
        lines = read_file_with_fallback_encodings(str(f), start_line=2)
        assert len(lines) == 2
        assert lines[0].strip() == "row1"

    def test_gbk_fallback(self, tmp_path):
        f = tmp_path / "data.txt"
        # Write GBK-encoded Chinese text
        f.write_bytes("你好世界\n第二行\n".encode("gbk"))
        lines = read_file_with_fallback_encodings(str(f))
        assert lines is not None
        assert len(lines) == 2

    def test_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_file_with_fallback_encodings(str(tmp_path / "nope.txt"))

    def test_all_encodings_fail_returns_none(self, tmp_path):
        # Binary file that can't be decoded
        f = tmp_path / "binary.dat"
        f.write_bytes(bytes(range(128, 256)) * 10)
        # Use only a restrictive encoding list that will fail
        result = read_file_with_fallback_encodings(
            str(f), encodings=("ascii",)
        )
        assert result is None

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        lines = read_file_with_fallback_encodings(str(f))
        assert lines == []
