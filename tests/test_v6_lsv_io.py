"""Tests for LSV input parsing helpers."""

from __future__ import annotations

import pytest

from electrochem_v6.core.processing_core_v6 import DataProcessingError, FileFormatError
from electrochem_v6.core.processing_lsv_io import parse_lsv_lines, read_lsv_raw_data


def test_parse_lsv_lines_converts_offset_area_and_abs_current():
    raw = parse_lsv_lines(
        ["0.10\t-0.002", "bad row", "0.20,0.003"],
        start_line=2,
        offset=0.1,
        area=2.0,
        use_abs_current=True,
    )

    assert raw.potential == pytest.approx([0.20, 0.30])
    assert raw.current_signed == pytest.approx([-1.0, 1.5])
    assert raw.current == pytest.approx([1.0, 1.5])
    assert raw.parse_errors == 1


def test_parse_lsv_lines_can_keep_signed_current():
    raw = parse_lsv_lines(
        ["0.0\t-0.001", "0.1\t0.002"],
        area=1.0,
        use_abs_current=False,
    )

    assert raw.current_signed == pytest.approx([-1.0, 2.0])
    assert raw.current == pytest.approx([-1.0, 2.0])


def test_parse_lsv_lines_supports_semicolon_columns_and_units():
    raw = parse_lsv_lines(
        ["unused;100;2", "unused;200;3"],
        potential_column=1,
        current_column=2,
        potential_scale=0.001,
        current_scale=1.0,
        potential_unit="mv",
        current_unit="ma",
        area=2.0,
    )

    assert raw.potential == pytest.approx([0.1, 0.2])
    assert raw.current == pytest.approx([1.0, 1.5])
    assert raw.potential_column == 2
    assert raw.current_column == 3
    assert raw.potential_unit == "mv"
    assert raw.current_unit == "ma"


def test_read_lsv_raw_data_uses_start_line(tmp_path):
    path = tmp_path / "LSV_demo.txt"
    path.write_text("Potential Current\n0.1 0.001\n0.2 0.002\n", encoding="utf-8")

    raw = read_lsv_raw_data(
        str(path),
        file_label=path.name,
        params={"start_line": "2", "offset": "0", "area": "1.0", "use_abs_current": True},
    )

    assert raw.potential == pytest.approx([0.1, 0.2])
    assert raw.current == pytest.approx([1.0, 2.0])


def test_read_lsv_raw_data_applies_configured_columns_and_units(tmp_path):
    path = tmp_path / "LSV_custom.csv"
    path.write_text("index;Potential_mV;Current_mA\n1;100;2\n2;200;3\n", encoding="utf-8")

    raw = read_lsv_raw_data(
        str(path),
        file_label=path.name,
        params={
            "start_line": 2,
            "area": 2.0,
            "lsv_potential_column": 2,
            "lsv_current_column": 3,
            "lsv_potential_unit": "mv",
            "lsv_current_unit": "ma",
        },
    )

    assert raw.potential == pytest.approx([0.1, 0.2])
    assert raw.current == pytest.approx([1.0, 1.5])


def test_read_lsv_raw_data_raises_when_no_valid_rows(tmp_path):
    path = tmp_path / "LSV_bad.txt"
    path.write_text("not data\nalso bad\n", encoding="utf-8")

    with pytest.raises(DataProcessingError):
        read_lsv_raw_data(
            str(path),
            file_label=path.name,
            params={"start_line": "1", "offset": "0", "area": "1.0"},
        )


def test_read_lsv_raw_data_raises_for_missing_file(tmp_path):
    missing = tmp_path / "missing.txt"

    with pytest.raises(FileFormatError):
        read_lsv_raw_data(
            str(missing),
            file_label=missing.name,
            params={"start_line": "1", "offset": "0", "area": "1.0"},
        )
