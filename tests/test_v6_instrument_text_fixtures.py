"""Compatibility checks for representative exported instrument text tables.

These fixtures exercise supported text layouts and are not vendor certification
files or proprietary binary project files.
"""

from pathlib import Path

import pytest

from electrochem_v6.core.processing_cv_io import read_cv_raw_data
from electrochem_v6.core.processing_ecsa_io import (
    _ecsa_extract_v_from_content,
    read_ecsa_cv_table,
)
from electrochem_v6.core.processing_eis_io import read_eis_raw_data
from electrochem_v6.core.processing_lsv_io import read_lsv_raw_data
from electrochem_v6.core.processing_scan import resolve_data_start_line

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "instrument_text"


def test_tab_delimited_lsv_export_supports_custom_columns_and_units():
    path = FIXTURE_DIR / "tab_lsv_export.txt"
    start_line = resolve_data_start_line(str(path))

    raw = read_lsv_raw_data(
        str(path),
        file_label=path.name,
        params={
            "start_line": start_line,
            "lsv_potential_column": 3,
            "lsv_current_column": 4,
            "lsv_potential_unit": "mv",
            "lsv_current_unit": "ua",
            "use_abs_current": False,
        },
    )

    assert start_line == 4
    assert raw.potential == pytest.approx([-0.1, 0.0, 0.1, 0.2, 0.3])
    assert raw.current == pytest.approx([-0.05, 0.1, 0.25, 0.5, 0.9])


def test_semicolon_delimited_cv_export_supports_custom_columns():
    path = FIXTURE_DIR / "semicolon_cv_export.csv"
    start_line = resolve_data_start_line(str(path))

    raw = read_cv_raw_data(
        str(path),
        start_line=start_line,
        potential_column=1,
        current_column=2,
        potential_scale=1.0,
        current_scale=1.0,
    )

    assert raw is not None
    assert start_line == 4
    assert raw.potential == pytest.approx([-0.2, 0.0, 0.2, 0.0, -0.2])
    assert raw.current == pytest.approx([-0.5, 0.1, 0.8, -0.05, -0.45])


def test_comma_delimited_eis_export_normalizes_negative_imaginary_column():
    path = FIXTURE_DIR / "comma_eis_negative_imag_export.csv"
    start_line = resolve_data_start_line(str(path))

    raw = read_eis_raw_data(str(path), start_line=start_line, zimag_sign=-1.0)

    assert raw is not None
    assert start_line == 4
    assert raw.frequency == pytest.approx([100000, 10000, 1000, 100, 10])
    assert raw.z_real == pytest.approx([2.1, 2.5, 4.0, 7.2, 9.1])
    assert raw.z_imag == pytest.approx([-0.2, -0.8, -2.1, -3.0, -1.2])


def test_whitespace_ecsa_export_preserves_scan_rate_metadata():
    path = FIXTURE_DIR / "whitespace_ecsa_export.txt"

    raw = read_ecsa_cv_table(
        str(path),
        potential_column=1,
        current_column=2,
        current_scale=1e-3,
    )

    assert raw.potential.tolist() == pytest.approx([0.0, 0.05, 0.1, 0.05, 0.0])
    assert raw.current.tolist() == pytest.approx([0.0001, 0.0002, 0.0003, 0.00012, 0.00002])
    assert _ecsa_extract_v_from_content(raw.lines) == pytest.approx(0.05)
