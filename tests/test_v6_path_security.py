"""Tests for electrochem_v6.core.path_security module."""

import os
import pytest
from pathlib import Path

from electrochem_v6.core.path_security import (
    sanitize_filename,
    validate_path_within,
    is_safe_data_path,
    is_safe_image_path,
)


# ── sanitize_filename ──────────────────────────────────────────────────────

class TestSanitizeFilename:
    def test_normal_name(self):
        assert sanitize_filename("report.csv") == "report.csv"

    def test_strips_directory_components(self):
        assert sanitize_filename("../../etc/passwd") == "passwd"

    def test_strips_windows_path(self):
        assert sanitize_filename("C:\\Users\\hack\\evil.exe") == "evil.exe"

    def test_replaces_special_chars(self):
        result = sanitize_filename("file name@#$.txt")
        assert ".." not in result
        assert "/" not in result
        assert "\\" not in result

    def test_empty_returns_unknown(self):
        assert sanitize_filename("") == "unknown"

    def test_none_returns_unknown(self):
        assert sanitize_filename(None) == "unknown"  # type: ignore[arg-type]

    def test_dots_only(self):
        result = sanitize_filename("...")
        assert result == "unknown"

    def test_leading_dot_stripped(self):
        result = sanitize_filename(".hidden")
        assert not result.startswith(".")

    def test_traversal_with_encoded_slashes(self):
        result = sanitize_filename("..%2F..%2Fetc%2Fpasswd")
        assert "/" not in result
        assert "\\" not in result

    def test_unicode_name(self):
        result = sanitize_filename("数据_报告.csv")
        # Should not crash; result should be non-empty
        assert result and result != "unknown"


# ── validate_path_within ───────────────────────────────────────────────────

class TestValidatePathWithin:
    def test_valid_path(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("x")
        result = validate_path_within(str(f), tmp_path)
        assert result == f.resolve()

    def test_rejects_traversal(self, tmp_path):
        evil = str(tmp_path / ".." / ".." / "etc" / "passwd")
        with pytest.raises(ValueError, match="不在允许范围内"):
            validate_path_within(evil, tmp_path)

    def test_rejects_nonexistent(self, tmp_path):
        with pytest.raises(ValueError, match="不存在"):
            validate_path_within(str(tmp_path / "nope.csv"), tmp_path)

    def test_allows_nonexistent_when_flag_off(self, tmp_path):
        result = validate_path_within(
            str(tmp_path / "future.csv"), tmp_path, must_exist=False
        )
        assert result.name == "future.csv"

    def test_rejects_bad_extension(self, tmp_path):
        f = tmp_path / "evil.py"
        f.write_text("import os")
        with pytest.raises(ValueError, match="不允许的文件类型"):
            validate_path_within(str(f), tmp_path, allowed_extensions=[".csv", ".txt"])

    def test_accepts_good_extension(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b")
        result = validate_path_within(str(f), tmp_path, allowed_extensions=[".csv"])
        assert result.suffix == ".csv"


# ── is_safe_data_path / is_safe_image_path ────────────────────────────────

class TestSafePathCheckers:
    def test_safe_data_path(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("ok")
        assert is_safe_data_path(str(f), tmp_path) is True

    def test_unsafe_data_path_traversal(self, tmp_path):
        evil = str(tmp_path / ".." / ".." / "etc" / "passwd")
        assert is_safe_data_path(evil, tmp_path) is False

    def test_unsafe_data_path_extension(self, tmp_path):
        f = tmp_path / "script.py"
        f.write_text("x")
        assert is_safe_data_path(str(f), tmp_path) is False

    def test_safe_image_path(self, tmp_path):
        f = tmp_path / "plot.png"
        f.write_bytes(b"\x89PNG")
        assert is_safe_image_path(str(f), tmp_path) is True

    def test_unsafe_image_extension(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("ok")
        assert is_safe_image_path(str(f), tmp_path) is False
