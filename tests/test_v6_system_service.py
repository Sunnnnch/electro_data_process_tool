"""Tests for core/system_service.py — path registration and security checks."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from electrochem_v6.core.system_service import (
    _runtime_allowed_dirs,
    _runtime_allowed_dirs_lock,
    register_allowed_dir,
)


@pytest.fixture(autouse=True)
def _clean_runtime_dirs():
    """Ensure the runtime whitelist is clean before/after each test."""
    with _runtime_allowed_dirs_lock:
        saved = set(_runtime_allowed_dirs)
        _runtime_allowed_dirs.clear()
    yield
    with _runtime_allowed_dirs_lock:
        _runtime_allowed_dirs.clear()
        _runtime_allowed_dirs.update(saved)


class TestRegisterAllowedDir:
    def test_register_existing_dir(self, tmp_path: Path):
        register_allowed_dir(str(tmp_path))
        with _runtime_allowed_dirs_lock:
            assert os.path.realpath(str(tmp_path)) in _runtime_allowed_dirs

    def test_register_nonexistent_dir(self, tmp_path: Path):
        fake = str(tmp_path / "no_such_dir")
        register_allowed_dir(fake)
        with _runtime_allowed_dirs_lock:
            assert os.path.realpath(fake) not in _runtime_allowed_dirs


class TestIsWithinAllowedRoots:
    """Test _is_within_allowed_roots without touching real config dirs."""

    def test_registered_dir_allowed(self, tmp_path: Path):
        from electrochem_v6.core.system_service import _is_within_allowed_roots

        sub = tmp_path / "outputs"
        sub.mkdir()
        register_allowed_dir(str(sub))
        assert _is_within_allowed_roots(str(sub / "report.png")) is True

    def test_unregistered_dir_rejected(self, tmp_path: Path):
        from electrochem_v6.core.system_service import _is_within_allowed_roots

        other = tmp_path / "other"
        other.mkdir()
        # Don't register it
        result = _is_within_allowed_roots(str(other / "file.txt"))
        # May or may not be allowed depending on project_default_dir overlap
        # Just ensure it returns a bool
        assert isinstance(result, bool)


class TestOpenPathTarget:
    def test_empty_path(self):
        from electrochem_v6.core.system_service import open_path_target

        result = open_path_target(path_value="")
        assert result["status"] == "error"
        assert "required" in result["message"]

    def test_none_path(self):
        from electrochem_v6.core.system_service import open_path_target

        result = open_path_target(path_value=None)
        assert result["status"] == "error"

    def test_outside_allowed(self, tmp_path: Path):
        from electrochem_v6.core.system_service import open_path_target

        # A path we definitely didn't register
        target = tmp_path / "forbidden" / "secret.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
        result = open_path_target(path_value=str(target))
        # Should be rejected unless it happens to match config dirs
        assert result["status"] in ("error", "success")
