"""Tests for the improved auto_detect_data_start() function.

Covers whitespace / tab / comma / semicolon delimiters, BOM markers,
comment styles, header rows, edge cases, and resolve_data_start_line().
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for _p in (str(ROOT), str(SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from electrochem_v6.core.processing_pipeline import (
    auto_detect_data_start,
    resolve_data_start_line,
)


# ── helpers ────────────────────────────────────────────────────────────────


def _write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


# ── basic whitespace-delimited ────────────────────────────────────────────


def test_pure_whitespace_data(tmp_path):
    """Pure numeric data with whitespace delimiter → line 1."""
    fp = _write(
        tmp_path / "data.txt",
        "0.1  0.002\n0.2  0.003\n0.3  0.004\n0.4  0.005\n",
    )
    assert auto_detect_data_start(fp) == 1


def test_header_then_whitespace_data(tmp_path):
    """Two header lines + data → line 3."""
    fp = _write(
        tmp_path / "data.txt",
        "Instrument: CHI660E\nDate: 2024-01-01\n0.1 0.002\n0.2 0.003\n0.3 0.004\n",
    )
    assert auto_detect_data_start(fp) == 3


# ── comma-delimited CSV ──────────────────────────────────────────────────


def test_csv_with_header(tmp_path):
    """CSV with one header row → line 2."""
    fp = _write(
        tmp_path / "data.csv",
        "Potential,Current\n0.1,0.002\n0.2,0.003\n0.3,0.004\n",
    )
    assert auto_detect_data_start(fp) == 2


def test_csv_pure_data(tmp_path):
    """CSV with no header → line 1."""
    fp = _write(
        tmp_path / "data.csv",
        "0.1,0.002\n0.2,0.003\n0.3,0.004\n0.4,0.005\n",
    )
    assert auto_detect_data_start(fp) == 1


def test_csv_multiple_headers(tmp_path):
    """CSV with multiple header/comment lines."""
    fp = _write(
        tmp_path / "data.csv",
        "# Experiment 1\nPotential,Current,Time\n0.1,0.002,1.0\n0.2,0.003,2.0\n0.3,0.004,3.0\n",
    )
    assert auto_detect_data_start(fp) == 3


# ── tab-delimited TSV ────────────────────────────────────────────────────


def test_tsv_with_comments(tmp_path):
    """TSV with comment lines → data starts after comments."""
    fp = _write(
        tmp_path / "data.txt",
        "# comment line 1\n# comment line 2\n0.1\t0.002\n0.2\t0.003\n0.3\t0.004\n",
    )
    assert auto_detect_data_start(fp) == 3


def test_tsv_pure_data(tmp_path):
    """TSV with no header → line 1."""
    fp = _write(
        tmp_path / "data.tsv",
        "0.1\t0.002\n0.2\t0.003\n0.3\t0.004\n0.4\t0.005\n",
    )
    assert auto_detect_data_start(fp) == 1


# ── semicolon-delimited ──────────────────────────────────────────────────


def test_semicolon_delimited(tmp_path):
    """European-style semicolon-delimited data."""
    fp = _write(
        tmp_path / "data.csv",
        "Header1;Header2\n0.1;0.002\n0.2;0.003\n0.3;0.004\n",
    )
    assert auto_detect_data_start(fp) == 2


# ── BOM handling ─────────────────────────────────────────────────────────


def test_bom_marker(tmp_path):
    """UTF-8 BOM at start of file should not affect detection."""
    fp = tmp_path / "bom.csv"
    fp.write_bytes(b"\xef\xbb\xbf0.1,0.002\n0.2,0.003\n0.3,0.004\n0.4,0.005\n")
    assert auto_detect_data_start(str(fp)) == 1


def test_bom_with_header(tmp_path):
    """UTF-8 BOM + header row."""
    fp = tmp_path / "bom.csv"
    fp.write_bytes(b"\xef\xbb\xbfPotential,Current\n0.1,0.002\n0.2,0.003\n0.3,0.004\n")
    assert auto_detect_data_start(str(fp)) == 2


# ── comment styles ───────────────────────────────────────────────────────


def test_percent_comments(tmp_path):
    """MATLAB-style % comments."""
    fp = _write(
        tmp_path / "data.txt",
        "% MATLAB data export\n% Date: today\n0.1 0.002\n0.2 0.003\n0.3 0.004\n",
    )
    assert auto_detect_data_start(fp) == 3


def test_exclamation_comments(tmp_path):
    """Exclamation mark comments (some instruments)."""
    fp = _write(
        tmp_path / "data.txt",
        "! Instrument header\n! Settings\n0.1 0.002\n0.2 0.003\n0.3 0.004\n",
    )
    assert auto_detect_data_start(fp) == 3


def test_single_quote_comments(tmp_path):
    """Single-quote comments (Origin/VBA style)."""
    fp = _write(
        tmp_path / "data.txt",
        "' Origin export\n' Column headers: V, A\n0.1 0.002\n0.2 0.003\n0.3 0.004\n",
    )
    assert auto_detect_data_start(fp) == 3


def test_colon_header_lines(tmp_path):
    """Colon-prefixed metadata lines."""
    fp = _write(
        tmp_path / "data.txt",
        ":Header: data\n:Date: today\n0.1 0.002\n0.2 0.003\n0.3 0.004\n",
    )
    assert auto_detect_data_start(fp) == 3


# ── edge cases ───────────────────────────────────────────────────────────


def test_empty_file(tmp_path):
    """Empty file → fallback to line 1."""
    fp = _write(tmp_path / "empty.txt", "")
    assert auto_detect_data_start(fp) == 1


def test_only_comments(tmp_path):
    """File with only comments → fallback to line 1."""
    fp = _write(tmp_path / "comments.txt", "# comment 1\n# comment 2\n# comment 3\n")
    assert auto_detect_data_start(fp) == 1


def test_single_column(tmp_path):
    """File with single column → needs ≥2 columns so fallback to 1."""
    fp = _write(tmp_path / "single.txt", "0.1\n0.2\n0.3\n0.4\n")
    assert auto_detect_data_start(fp) == 1


def test_mixed_headers_and_blank_lines(tmp_path):
    """Headers, blank lines, then data."""
    fp = _write(
        tmp_path / "data.txt",
        "Header info\n\n# another comment\n\n0.1 0.002\n0.2 0.003\n0.3 0.004\n",
    )
    assert auto_detect_data_start(fp) == 5


def test_typical_chi_instrument_file(tmp_path):
    """Simulate a typical CHI instrument export with ~20 header lines."""
    header_lines = [f"Header line {i}" for i in range(20)]
    data_lines = [f"{0.01*i:.4f}\t{1e-6*i:.10f}" for i in range(50)]
    fp = _write(
        tmp_path / "chi_data.txt",
        "\n".join(header_lines + data_lines) + "\n",
    )
    assert auto_detect_data_start(fp) == 21


# ── resolve_data_start_line (simplified) ─────────────────────────────────


def test_resolve_always_auto_detects(tmp_path):
    """resolve_data_start_line always calls auto_detect."""
    fp = _write(
        tmp_path / "data.txt",
        "Header\n0.1 0.002\n0.2 0.003\n0.3 0.004\n",
    )
    # Called without params
    result = resolve_data_start_line(str(fp))
    assert result == 2
    # Called with params (backward compat) – still auto-detects
    result2 = resolve_data_start_line(str(fp), {})
    assert result2 == 2


def test_gbk_encoded_file(tmp_path):
    """GBK-encoded file with Chinese header."""
    fp = tmp_path / "gbk_data.txt"
    content = "电化学数据\n电位\t电流\n0.1\t0.002\n0.2\t0.003\n0.3\t0.004\n"
    fp.write_bytes(content.encode("gbk"))
    assert auto_detect_data_start(str(fp)) == 3


# ── column count consistency ─────────────────────────────────────────────


def test_numeric_header_different_col_count(tmp_path):
    """All lines are valid numeric data; detector accepts the first 3 consecutive."""
    fp = _write(
        tmp_path / "data.txt",
        # 3 lines of 2-col numeric
        "22 3\n15 7\n8 2\n"
        # then 3-col numeric data
        "0.1 0.002 1.0\n0.2 0.003 2.0\n0.3 0.004 3.0\n0.4 0.005 4.0\n",
    )
    # Both 2-col and 3-col lines are valid numeric data; first 3 match at line 1
    assert auto_detect_data_start(fp) == 1


def test_numeric_header_same_col_count_accepted(tmp_path):
    """If header and data have the same column count, accept the first match."""
    fp = _write(
        tmp_path / "data.txt",
        # header + data both 2-col numeric
        "0.1 0.002\n0.2 0.003\n0.3 0.004\n0.4 0.005\n0.5 0.006\n",
    )
    assert auto_detect_data_start(fp) == 1


def test_short_file_no_verification(tmp_path):
    """Short file with exactly 3 data lines — no extra lines for verification."""
    fp = _write(
        tmp_path / "data.txt",
        "Header\n0.1 0.002\n0.2 0.003\n0.3 0.004\n",
    )
    assert auto_detect_data_start(fp) == 2

