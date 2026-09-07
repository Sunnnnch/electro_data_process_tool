from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest

from electrochem_v6.core.processing_coupled_calc import FARADAY_CONSTANT_C_PER_MOL
from electrochem_v6.core.processing_fe_peak import (
    inspect_fe_peak_inputs,
    load_fe_peak_method,
    parse_fe_peak_method,
    process_fe_peak_file,
)


def _gaussian_area(x: np.ndarray, center: float, sigma: float, area: float) -> np.ndarray:
    return area * np.exp(-0.5 * ((x - center) / sigma) ** 2) / (sigma * math.sqrt(2.0 * math.pi))


def _write_method(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "method_id": "acetate-qnmr-v1",
                "analysis_method": "qnmr_internal_standard",
                "axis_unit": "ppm",
                "internal_standard": {
                    "name": "maleic_acid",
                    "expected_position": 6.30,
                    "nuclei_count": 2,
                    "concentration_mM": 100.0,
                    "volume_uL": 200.0,
                    "search_tolerance": 0.08,
                    "window_left": 0.05,
                    "window_right": 0.05,
                },
                "products": [
                    {
                        "name": "acetate",
                        "reaction_id": "ethanol_oxidation_to_acetate",
                        "electron_count": 4,
                        "expected_position": 1.91,
                        "nuclei_count": 3,
                        "search_tolerance": 0.08,
                        "window_left": 0.05,
                        "window_right": 0.05,
                    }
                ],
                "sample_defaults": {
                    "electrolyte_volume_mL": 20.0,
                    "sample_aliquot_volume_uL": 400.0,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_signal(path: Path, shift: float = 0.025) -> None:
    x = np.linspace(0.0, 8.0, 16001)
    y = 0.2 + 0.003 * x
    y += _gaussian_area(x, 6.30 + shift, 0.009, 2.0)
    y += _gaussian_area(x, 1.91 + shift, 0.010, 3.0)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ppm", "intensity"])
        writer.writerows(zip(x, y))


def _read_rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_load_fe_peak_method_keeps_reaction_specific_electron_count(tmp_path):
    method_file = tmp_path / "method.json"
    _write_method(method_file)

    method = load_fe_peak_method(method_file)

    assert method.method_id == "acetate-qnmr-v1"
    assert method.internal_standard.nuclei_count == pytest.approx(2)
    assert method.products[0].product_name == "acetate"
    assert method.products[0].electron_count == pytest.approx(4)
    assert method.products[0].reaction_id == "ethanol_oxidation_to_acetate"


def test_parse_fe_peak_method_accepts_panel_payload(tmp_path):
    method_file = tmp_path / "method.json"
    _write_method(method_file)
    payload = json.loads(method_file.read_text(encoding="utf-8"))

    method = parse_fe_peak_method(payload, source_name="panel")

    assert method.method_id == "acetate-qnmr-v1"
    assert method.internal_standard_concentration_mM == pytest.approx(100.0)
    assert method.products[0].electron_count == pytest.approx(4.0)


def test_load_fe_peak_method_rejects_overlapping_quantification_windows(tmp_path):
    method_file = tmp_path / "method.json"
    _write_method(method_file)
    payload = json.loads(method_file.read_text(encoding="utf-8"))
    payload["products"].append(
        {
            "name": "overlapping_product",
            "electron_count": 2,
            "expected_position": 1.94,
            "nuclei_count": 1,
            "search_tolerance": 0.08,
            "window_left": 0.05,
            "window_right": 0.05,
        }
    )
    method_file.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="quantification windows overlap"):
        load_fe_peak_method(method_file)


def test_process_fe_peak_file_quantifies_area_ratio_and_reuses_generic_fe(tmp_path):
    method_file = tmp_path / "method.json"
    signal_file = tmp_path / "sample-a.csv"
    measurements_file = tmp_path / "measurements.csv"
    output_dir = tmp_path / "out"
    _write_method(method_file)
    _write_signal(signal_file)
    expected_product_moles = 0.001
    charge = 4 * FARADAY_CONSTANT_C_PER_MOL * expected_product_moles
    measurements_file.write_text(
        "sample_name,signal_file,charge_C,potential_V_vs_RHE,replicate\n"
        f"sample-a,{signal_file.name},{charge},1.35,1\n",
        encoding="utf-8",
    )

    result = process_fe_peak_file(
        measurements_file,
        method_file,
        output_dir=output_dir,
    )

    calculated = result["results"][0]
    assert calculated.product_name == "acetate"
    assert calculated.product_moles == pytest.approx(expected_product_moles, rel=0.03)
    assert calculated.faradaic_efficiency_pct == pytest.approx(100.0, rel=0.03)
    assert Path(result["coupled_results_csv"]).exists()
    assert Path(result["fe_peak_diagnostics_csv"]).exists()
    assert Path(result["fe_peak_results_json"]).exists()

    diagnostics = _read_rows(Path(result["fe_peak_diagnostics_csv"]))
    assert float(diagnostics[0]["reference_shift"]) == pytest.approx(0.025, abs=0.002)
    assert float(diagnostics[0]["product_found_position"]) == pytest.approx(1.935, abs=0.002)
    assert diagnostics[0]["quantification_method"] == "fixed_window_integration"


def test_process_fe_peak_file_accepts_panel_method_without_json_file(tmp_path):
    method_file = tmp_path / "method.json"
    signal_file = tmp_path / "sample-a.csv"
    measurements_file = tmp_path / "measurements.csv"
    output_dir = tmp_path / "out"
    _write_method(method_file)
    method_payload = json.loads(method_file.read_text(encoding="utf-8"))
    _write_signal(signal_file)
    charge = 4 * FARADAY_CONSTANT_C_PER_MOL * 0.001
    measurements_file.write_text(
        "sample_name,signal_file,charge_C\n"
        f"sample-a,{signal_file.name},{charge}\n",
        encoding="utf-8",
    )

    result = process_fe_peak_file(
        measurements_file,
        method_payload=method_payload,
        output_dir=output_dir,
    )

    assert result["method_id"] == "acetate-qnmr-v1"
    assert result["results"][0].faradaic_efficiency_pct == pytest.approx(100.0, rel=0.03)


def test_inspect_fe_peak_inputs_reports_method_products_and_missing_files(tmp_path):
    method_file = tmp_path / "method.json"
    signal_file = tmp_path / "sample-a.csv"
    measurements_file = tmp_path / "measurements.csv"
    _write_method(method_file)
    _write_signal(signal_file)
    measurements_file.write_text(
        "sample_name,signal_file,charge_C\n"
        "sample-a,sample-a.csv,10\n",
        encoding="utf-8",
    )

    valid = inspect_fe_peak_inputs(measurements_file, method_file)
    signal_file.unlink()
    invalid = inspect_fe_peak_inputs(measurements_file, method_file)

    assert valid["ok"] is True
    assert valid["method_id"] == "acetate-qnmr-v1"
    assert valid["products"] == ["acetate"]
    assert valid["warnings"] == ["fewer_than_three_measurements"]
    assert invalid["ok"] is False
    assert "signal_file not found" in invalid["errors"][0]


def test_fe_peak_measurements_reject_signal_file_outside_allowed_root(tmp_path):
    data_dir = tmp_path / "data"
    outside_dir = tmp_path / "outside"
    data_dir.mkdir()
    outside_dir.mkdir()
    method_file = data_dir / "method.json"
    measurements_file = data_dir / "measurements.csv"
    signal_file = outside_dir / "sample-a.csv"
    _write_method(method_file)
    _write_signal(signal_file)
    measurements_file.write_text(
        "sample_name,signal_file,charge_C\n"
        f"sample-a,{signal_file},10\n",
        encoding="utf-8",
    )

    inspected = inspect_fe_peak_inputs(
        measurements_file,
        method_file,
        allowed_signal_roots=(data_dir,),
    )

    assert inspected["ok"] is False
    assert "outside the allowed data roots" in inspected["errors"][0]
