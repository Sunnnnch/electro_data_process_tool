from __future__ import annotations

import os

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")

from electrochem_v6.core import process_service
from electrochem_v6.core.processing_lsv_ir import (
    IR_COMPENSATION_FORMULA,
    build_lsv_ir_preflight,
    extract_lsv_sample_token,
    extract_rs_from_eis,
    resolve_lsv_eis_match,
)


def _write_text(path, text="0 0\n1 1\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _ir_params(**overrides):
    params = {
        "ir_source": "eis",
        "ir_eis_search_scope": "same_dir",
        "ir_eis_match": "prefix",
        "ir_eis_pattern": "EIS",
        "ir_method": "auto",
    }
    params.update(overrides)
    return params


def test_extract_lsv_sample_token_supports_prefix_and_suffix_names():
    assert extract_lsv_sample_token("LSV_sample-01.txt") == "sample01"
    assert extract_lsv_sample_token("sample-01_LSV.csv") == "sample01"


def test_strict_ir_extraction_rejects_untrusted_mean_fallback(tmp_path):
    eis = _write_text(
        tmp_path / "EIS_flat.txt",
        "100000 2 -5\n10000 3 -5\n1000 4 -5\n100 5 -5\n",
    )

    result = extract_rs_from_eis(str(eis), validation_mode="strict")

    assert result.accepted is False
    assert result.confidence == "rejected"
    assert "严格模式" in result.message


def test_lenient_ir_extraction_marks_mean_fallback_low_confidence(tmp_path):
    eis = _write_text(
        tmp_path / "EIS_flat.txt",
        "100000 2 -5\n10000 3 -5\n1000 4 -5\n100 5 -5\n",
    )

    result = extract_rs_from_eis(str(eis), validation_mode="lenient")

    assert result.accepted is True
    assert result.rs_ohm == pytest.approx(3.5)
    assert result.method_used == "hf_mean_fallback"
    assert result.confidence == "low"
    assert result.warnings


def test_resolver_can_fall_back_from_lsv_folder_to_selected_root(tmp_path):
    lsv = _write_text(tmp_path / "sample" / "LSV_sample.txt")
    eis = _write_text(tmp_path / "EIS_sample.txt")

    same_dir = resolve_lsv_eis_match(str(lsv), str(tmp_path), _ir_params())
    fallback = resolve_lsv_eis_match(
        str(lsv),
        str(tmp_path),
        _ir_params(ir_eis_search_scope="same_then_root"),
    )

    assert same_dir["status"] == "missing"
    assert fallback["status"] == "matched"
    assert fallback["eis_file"] == os.path.abspath(eis)


def test_resolver_can_search_selected_root_recursively(tmp_path):
    lsv = _write_text(tmp_path / "sample" / "LSV_sample.txt")
    eis = _write_text(tmp_path / "impedance" / "nested" / "EIS_sample.txt")

    resolved = resolve_lsv_eis_match(
        str(lsv),
        str(tmp_path),
        _ir_params(ir_eis_search_scope="recursive_root"),
    )

    assert resolved["status"] == "matched"
    assert resolved["eis_file"] == os.path.abspath(eis)


def test_resolver_rejects_equal_priority_eis_candidates(tmp_path):
    lsv = _write_text(tmp_path / "sample" / "LSV_sample.txt")
    _write_text(tmp_path / "EIS_sample_a.txt")
    _write_text(tmp_path / "EIS_sample_b.txt")

    resolved = resolve_lsv_eis_match(
        str(lsv),
        str(tmp_path),
        _ir_params(ir_eis_search_scope="same_then_root"),
    )

    assert resolved["status"] == "ambiguous"
    assert len(resolved["candidates"]) == 2


def test_resolver_supports_specified_file_and_manual_source(tmp_path):
    lsv = _write_text(tmp_path / "LSV_sample.txt")
    eis = _write_text(tmp_path / "custom" / "measurement.csv")

    specified = resolve_lsv_eis_match(
        str(lsv),
        str(tmp_path),
        _ir_params(ir_eis_search_scope="specified_file", ir_eis_file=str(eis)),
    )
    manual = resolve_lsv_eis_match(
        str(lsv),
        str(tmp_path),
        _ir_params(ir_source="manual", ir_manual_ohm=3.2),
    )

    assert specified["status"] == "matched"
    assert specified["eis_file"] == os.path.abspath(eis)
    assert manual["status"] == "manual"
    assert manual["scope"] is None
    assert manual["extraction_method"] == "manual"
    assert manual["rs_ohm"] == pytest.approx(3.2)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", 0, -1])
def test_manual_source_rejects_non_finite_or_non_positive_rs(tmp_path, value):
    lsv = _write_text(tmp_path / "LSV_sample.txt")

    resolved = resolve_lsv_eis_match(
        str(lsv),
        str(tmp_path),
        _ir_params(ir_source="manual", ir_manual_ohm=value),
    )

    assert resolved["status"] == "invalid"


def test_preflight_exposes_each_lsv_to_eis_pairing(tmp_path):
    first = _write_text(tmp_path / "a" / "LSV_alpha.txt")
    second = _write_text(tmp_path / "b" / "LSV_beta.txt")
    _write_text(tmp_path / "EIS_alpha.txt")
    _write_text(tmp_path / "EIS_beta.txt")

    result = build_lsv_ir_preflight(
        str(tmp_path),
        [str(first), str(second)],
        _ir_params(ir_eis_search_scope="same_then_root"),
    )

    assert result["ok"] is True
    assert result["matched"] == 2
    assert result["formula"] == IR_COMPENSATION_FORMULA
    assert {os.path.basename(item["eis_file"]) for item in result["items"]} == {
        "EIS_alpha.txt",
        "EIS_beta.txt",
    }


def test_process_preflight_reports_root_fallback_pairing(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    root = tmp_path / "data"
    _write_text(root / "sample" / "LSV_sample.txt")
    eis = _write_text(root / "EIS_sample.txt")

    result = process_service.preflight_process_folder(
        {
            "folder_path": str(root),
            "data_types": ["LSV"],
            "params": {
                "lsv_match": "prefix",
                "lsv_prefix": "LSV",
                "ir_compensation_enabled": True,
                **_ir_params(ir_eis_search_scope="same_then_root"),
            },
        }
    )

    assert result["status"] == "success"
    preflight = result["preflight"]
    assert preflight["runnable"] is True
    pairing = preflight["ir_compensation"]["items"][0]
    assert pairing["status"] == "matched"
    assert pairing["eis_file"] == os.path.abspath(eis)


def test_process_folder_blocks_ambiguous_eis_before_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    root = tmp_path / "data"
    _write_text(root / "sample" / "LSV_sample.txt")
    _write_text(root / "EIS_sample_a.txt")
    _write_text(root / "EIS_sample_b.txt")

    def _unexpected_run(*_args, **_kwargs):
        raise AssertionError("pipeline must not run when EIS pairing is ambiguous")

    monkeypatch.setattr(process_service, "_run_selected_modules", _unexpected_run)

    result = process_service.process_folder(
        {
            "folder_path": str(root),
            "data_types": ["LSV"],
            "params": {
                "lsv_match": "prefix",
                "lsv_prefix": "LSV",
                "ir_compensation_enabled": True,
                **_ir_params(ir_eis_search_scope="same_then_root"),
            },
        }
    )

    assert result["status"] == "error"
    pairing = result["result"]["preflight"]["ir_compensation"]["items"][0]
    assert pairing["status"] == "ambiguous"
    assert len(pairing["candidates"]) == 2


def test_process_folder_applies_root_eis_and_records_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(process_service, "attach_run_outputs", lambda **_kwargs: {"status": "success"})
    root = tmp_path / "run"
    sample_dir = root / "sample"
    lsv_lines = []
    for index in range(50):
        potential = index * 0.03
        current_a = 1e-6 * np.exp(5.0 * potential)
        lsv_lines.append(f"{potential:.6f}\t{current_a:.10f}")
    _write_text(sample_dir / "LSV_sample.txt", "\n".join(lsv_lines))
    eis = _write_text(
        root / "EIS_sample.txt",
        "100000 2.0 0.01\n10000 2.2 -0.10\n1000 2.8 -0.50\n100 4.0 -1.20\n",
    )

    result = process_service.process_folder(
        {
            "folder_path": str(root),
            "data_types": ["LSV"],
            "params": {
                "lsv_match": "prefix",
                "lsv_prefix": "LSV",
                "lsv_quality_check": False,
                "ir_compensation_enabled": True,
                **_ir_params(ir_eis_search_scope="same_then_root"),
            },
        }
    )

    assert result["status"] == "success"
    ir_info = result["result"]["manifest"]["calculation"]["ir_compensation"]
    assert ir_info["ok"] is True
    assert ir_info["results"][0]["eis_file"] == os.path.abspath(eis)
    assert ir_info["results"][0]["rs_ohm"] > 0
    formula_keys = {item["key"] for item in result["result"]["manifest"]["calculation"]["formulas"]}
    assert "lsv.ir_compensation" in formula_keys


def test_process_lsv_manual_source_does_not_read_eis(tmp_path, monkeypatch):
    from electrochem_v6.core import processing_lsv

    sample_dir = tmp_path / "sample"
    lines = []
    for index in range(50):
        potential = index * 0.03
        current_a = 1e-6 * np.exp(5.0 * potential)
        lines.append(f"{potential:.6f}\t{current_a:.10f}")
    _write_text(sample_dir / "LSV_sample.txt", "\n".join(lines))
    _write_text(sample_dir / "EIS_sample.txt", "1000 2 -0.1\n100 3 -1\n")
    monkeypatch.setattr(
        processing_lsv,
        "get_ir_from_eis",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("EIS should not be read")),
    )

    result = processing_lsv.process_lsv(
        str(sample_dir),
        "LSV_sample.txt",
        {
            "start_line": "0",
            "offset": 0,
            "area": 1.0,
            "target_current": "10",
            "use_abs_current": True,
            "tafel_enabled": False,
            "overpotential_enabled": False,
            "onset_enabled": False,
            "halfwave_enabled": False,
            "ir_compensation_enabled": True,
            "ir_source": "manual",
            "ir_manual_ohm": 2.5,
            "input_root": str(tmp_path),
            "output_dir": str(tmp_path / "out"),
            "font": "",
            "fontsize": 12,
            "plot_grid": False,
            "xlabel": "Potential (V)",
            "ylabel": "Current (mA/cm2)",
            "title": "LSV - {sample}",
            "line_color": "blue",
            "line_width": 2.0,
        },
        enable_quality_check=False,
    )

    assert result["ir_provenance"]["source"] == "manual"
    assert result["ir_provenance"]["rs_ohm"] == pytest.approx(2.5)


def test_process_lsv_auto_detects_eis_start_line_independently(tmp_path, monkeypatch):
    from electrochem_v6.core import processing_lsv

    sample_dir = tmp_path / "sample"
    lsv_lines = ["metadata", "potential current"]
    for index in range(50):
        potential = index * 0.03
        current_a = 1e-6 * np.exp(5.0 * potential)
        lsv_lines.append(f"{potential:.6f}\t{current_a:.10f}")
    _write_text(sample_dir / "LSV_sample.txt", "\n".join(lsv_lines))
    _write_text(
        sample_dir / "EIS_sample.txt",
        "instrument metadata\nfrequency zreal zimag\n100000 2.0 0.01\n10000 2.2 -0.1\n1000 2.8 -0.5\n",
    )
    result = processing_lsv.process_lsv(
        str(sample_dir),
        "LSV_sample.txt",
        {
            "start_line": "3",
            "offset": 0,
            "area": 1.0,
            "target_current": "10",
            "use_abs_current": True,
            "tafel_enabled": False,
            "overpotential_enabled": False,
            "onset_enabled": False,
            "halfwave_enabled": False,
            "ir_compensation_enabled": True,
            **_ir_params(),
            "input_root": str(tmp_path),
            "output_dir": str(tmp_path / "out"),
            "font": "",
            "fontsize": 12,
            "plot_grid": False,
            "xlabel": "Potential (V)",
            "ylabel": "Current (mA/cm2)",
            "title": "LSV - {sample}",
            "line_color": "blue",
            "line_width": 2.0,
        },
        enable_quality_check=False,
    )

    assert result["ir_provenance"]["eis_start_line"] == 3
    assert result["ir_provenance"]["confidence"] in {"high", "medium"}
