"""Tests for electrochem_v6.core.path_security module."""

import os
from pathlib import Path

import pytest

from electrochem_v6.core.path_security import (
    is_safe_data_path,
    is_safe_image_path,
    sanitize_filename,
    validate_path_within,
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


# ── open_path_target whitelist ─────────────────────────────────────────────

from electrochem_v6.core.system_service import (
    _is_within_allowed_roots,
    _runtime_allowed_dirs,
    _runtime_allowed_dirs_lock,
    open_path_target,
    register_allowed_dir,
)


class TestOpenPathTargetWhitelist:
    def test_rejects_system_path(self):
        result = open_path_target("C:\\Windows\\System32")
        assert result["status"] == "error"
        assert "outside allowed" in result["message"]

    def test_rejects_traversal(self):
        result = open_path_target("../../../../etc/passwd")
        assert result["status"] == "error"
        # Should be blocked by whitelist or "not found", never succeed
        assert result["status"] != "success"

    def test_rejects_empty(self):
        result = open_path_target("")
        assert result["status"] == "error"

    def test_rejects_none(self):
        result = open_path_target(None)
        assert result["status"] == "error"

    def test_allowed_roots_accepts_user_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "electrochem_v6.config.project_default_dir",
            lambda: tmp_path,
        )
        ud = tmp_path / "user_data"
        ud.mkdir()
        assert _is_within_allowed_roots(str(ud)) is True

    def test_allowed_roots_rejects_external(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "electrochem_v6.config.project_default_dir",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "electrochem_v6.config.user_config_dir",
            lambda: tmp_path / "cfg",
        )
        assert _is_within_allowed_roots("C:\\Windows\\System32") is False

    def test_no_path_leakage_in_error(self):
        result = open_path_target("C:\\Windows\\System32\\notepad.exe")
        # Error message must NOT contain the full normalized path
        assert "C:\\Windows" not in result.get("message", "")

    def test_register_allowed_dir_enables_access(self, tmp_path, monkeypatch):
        """Runtime-registered directories should pass the whitelist check."""
        monkeypatch.setattr("electrochem_v6.config.project_default_dir", lambda: tmp_path / "proj")
        monkeypatch.setattr("electrochem_v6.config.user_config_dir", lambda: tmp_path / "cfg")
        output_dir = tmp_path / "output_results"
        output_dir.mkdir()
        # Before registration — rejected
        assert _is_within_allowed_roots(str(output_dir)) is False
        # After registration — accepted
        register_allowed_dir(str(output_dir))
        assert _is_within_allowed_roots(str(output_dir)) is True
        # Cleanup
        with _runtime_allowed_dirs_lock:
            _runtime_allowed_dirs.discard(os.path.realpath(str(output_dir)))

    def test_register_allowed_dir_ignores_nonexistent(self, tmp_path):
        """Non-existent directories should NOT be registered."""
        fake = str(tmp_path / "does_not_exist")
        register_allowed_dir(fake)
        with _runtime_allowed_dirs_lock:
            assert os.path.realpath(fake) not in _runtime_allowed_dirs

    def test_open_path_target_succeeds_for_allowed_dir(self, tmp_path, monkeypatch):
        """open_path_target should succeed for dirs under project_default_dir."""
        monkeypatch.setattr("electrochem_v6.config.project_default_dir", lambda: tmp_path)
        monkeypatch.setattr("electrochem_v6.config.user_config_dir", lambda: tmp_path / "cfg")
        target_dir = tmp_path / "user_data"
        target_dir.mkdir()
        # Patch os.startfile to avoid actually opening a window
        monkeypatch.setattr(os, "startfile", lambda p: None, raising=False)
        result = open_path_target(str(target_dir))
        assert result["status"] == "success"
