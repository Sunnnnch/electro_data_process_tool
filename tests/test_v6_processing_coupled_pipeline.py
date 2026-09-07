from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest

import electrochem_v6.core.process_service as process_service
from electrochem_v6.core.processing_coupled import process_coupled_products_file
from electrochem_v6.core.processing_module_orchestrator import run_module_pipeline


def _write_products_csv(path: Path) -> None:
    path.write_text(
        "sample,product,product_moles,n,charge\n"
        "sample-a,H2,0.000002,2,1.0\n"
        "sample-a,CO,0.000001,2,1.0\n",
        encoding="utf-8",
    )


def _write_products_current_time_csv(path: Path) -> None:
    path.write_text(
        "sample,product,product_moles,n,current_mA,time_s\n"
        "sample-a,H2,0.000002,2,10,100\n"
        "sample-a,CO,0.000001,2,10,100\n",
        encoding="utf-8",
    )


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_peak_method(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "method_id": "pipeline-qnmr-v1",
                "analysis_method": "qnmr_internal_standard",
                "axis_unit": "ppm",
                "internal_standard": {
                    "name": "reference",
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
            }
        ),
        encoding="utf-8",
    )


def _write_peak_signal(path: Path, shift: float = 0.025) -> None:
    x = np.linspace(0.0, 8.0, 16001)

    def gaussian(center: float, sigma: float, area: float) -> np.ndarray:
        return area * np.exp(-0.5 * ((x - center) / sigma) ** 2) / (
            sigma * math.sqrt(2.0 * math.pi)
        )

    y = 0.2 + 0.003 * x
    y += gaussian(6.30 + shift, 0.009, 2.0)
    y += gaussian(1.91 + shift, 0.010, 3.0)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ppm", "intensity"])
        writer.writerows(zip(x, y))


def test_process_coupled_products_file_exports_wide_csv(tmp_path):
    products = tmp_path / "products.csv"
    output_dir = tmp_path / "out"
    _write_products_csv(products)

    result = process_coupled_products_file(products, output_dir=output_dir)

    output_csv = Path(result["coupled_results_csv"])
    assert result["quality_reports"][0]["total_sample_fe_pct"] > 0
    rows = _read_csv_rows(output_csv)
    assert output_csv.exists()
    assert result["rows"] == 2
    assert rows[0]["sample_name"] == "sample-a"
    assert rows[0]["product_name"] == "H2"
    assert rows[0]["faradaic_efficiency_pct"]


def test_product_table_quality_report_warns_when_total_fe_exceeds_100(tmp_path):
    products = tmp_path / "products.csv"
    products.write_text(
        "sample,product,product_moles,n,charge\n"
        "sample-a,H2,0.000010,2,1.0\n",
        encoding="utf-8",
    )

    result = process_coupled_products_file(products, output_dir=tmp_path / "out")

    assert result["quality_reports"][0]["warnings"] == ["total_fe_above_100_pct"]


def test_product_table_pipeline_converts_mmol_before_export_and_quality_checks(tmp_path):
    products = tmp_path / "products.csv"
    products.write_text(
        "sample,product,Product Moles (mmol),n,Charge (C)\nA,H2,0.000001,2,1\n",
        encoding="utf-8",
    )
    result = run_module_pipeline(
        str(tmp_path),
        {"coupled_products_file": str(products), "output_dir": str(tmp_path / "out")},
        data_types=["COUPLED"],
    )
    rows = _read_csv_rows(Path(result["coupled_results_csv"]))
    assert float(rows[0]["product_moles"]) == pytest.approx(1e-9)
    assert float(rows[0]["faradaic_efficiency_pct"]) == pytest.approx(0.019297066424)
    assert result["quality_reports"][0]["total_sample_fe_pct"] == pytest.approx(0.019297066424)


def test_run_module_pipeline_exports_coupled_and_unified_results(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    folder = tmp_path / "data"
    output_dir = tmp_path / "out"
    folder.mkdir()
    products = folder / "products.csv"
    _write_products_csv(products)

    result = run_module_pipeline(
        str(folder),
        {
            "coupled_products_file": str(products),
            "output_dir": str(output_dir),
            "run_id": "run-1",
            "project_id": "project-1",
        },
        data_types=["COUPLED"],
    )

    coupled_csv = Path(result["coupled_results_csv"])
    processing_csv = Path(result["processing_results_csv"])
    assert coupled_csv.exists()
    assert processing_csv.exists()
    assert result["matched_counts"]["COUPLED"] == 1
    assert len(result["processing_results"]) == 2
    assert all(item["data_type"] == "COUPLED" for item in result["processing_results"])

    processing_rows = _read_csv_rows(processing_csv)
    assert any(row["data_type"] == "COUPLED" for row in processing_rows)
    assert any(row["metric_key"] == "faradaic_efficiency_pct" for row in processing_rows)

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["coupled"]["csv"] == str(coupled_csv)
    assert summary["coupled"]["rows"] == 2
    assert summary["processing_results"]["csv"] == str(processing_csv)


def test_process_folder_requires_explicit_data_type_for_coupled_input(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(process_service, "attach_run_outputs", lambda **_kwargs: {"status": "success", "updated": 0})
    folder = tmp_path / "data"
    folder.mkdir()
    products = folder / "products.csv"
    _write_products_csv(products)

    result = process_service.process_folder(
        {
            "folder_path": str(folder),
            "coupled_products_file": str(products),
        }
    )

    assert result["status"] == "error"
    assert "data_types" in result["message"]


def test_process_folder_accepts_fe_data_type_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(process_service, "attach_run_outputs", lambda **_kwargs: {"status": "success", "updated": 0})
    folder = tmp_path / "data"
    folder.mkdir()
    products = folder / "products.csv"
    _write_products_csv(products)

    result = process_service.process_folder(
        {
            "folder_path": str(folder),
            "data_types": ["FE"],
            "params": {
                "coupled_input_mode": "product_table",
                "coupled_products_file": str(products),
                "coupled_peak_method_file": "stale-missing-method.json",
            },
        }
    )

    assert result["status"] == "success"
    assert result["result"]["data_types"] == ["COUPLED"]


def test_process_folder_accepts_coupled_current_time_charge_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(process_service, "attach_run_outputs", lambda **_kwargs: {"status": "success", "updated": 0})
    folder = tmp_path / "data"
    folder.mkdir()
    products = folder / "products_current_time.csv"
    _write_products_current_time_csv(products)

    result = process_service.process_folder(
        {
            "folder_path": str(folder),
            "data_types": ["COUPLED"],
            "params": {"coupled_products_file": str(products)},
        }
    )

    assert result["status"] == "success"
    output_files = result["result"]["processing"]["output_files"]
    coupled_csv = next(Path(item) for item in output_files if str(item).endswith("coupled_results.csv"))
    rows = _read_csv_rows(coupled_csv)
    assert rows[0]["charge_coulomb"] == "1.0"
    assert float(rows[0]["faradaic_efficiency_pct"]) > 0


def test_process_folder_runs_peak_based_fe_with_preflight_and_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(process_service, "attach_run_outputs", lambda **_kwargs: {"status": "success", "updated": 0})
    folder = tmp_path / "peak_fe"
    folder.mkdir()
    method = folder / "method.json"
    signal = folder / "sample-a.csv"
    measurements = folder / "measurements.csv"
    _write_peak_method(method)
    _write_peak_signal(signal)
    charge = 4 * 96485.33212 * 0.001
    measurements.write_text(
        "sample_name,signal_file,charge_C\n"
        f"sample-a,{signal.name},{charge}\n",
        encoding="utf-8",
    )
    payload = {
        "folder_path": str(folder),
        "data_types": ["COUPLED"],
        "params": {
            "coupled_input_mode": "peak_analysis",
            "coupled_products_file": str(measurements),
            "coupled_peak_method_file": str(method),
            "fe_peak_auto_locate": True,
            "fe_peak_reference_align": True,
            "fe_peak_fit_enabled": False,
        },
    }

    preflight = process_service.preflight_process_folder(payload)
    result = process_service.process_folder(payload)

    assert preflight["status"] == "success"
    assert preflight["preflight"]["runnable"] is True
    assert preflight["preflight"]["coupled_peak"]["method_id"] == "pipeline-qnmr-v1"
    assert result["status"] == "success"
    body = result["result"]
    output_files = body["processing"]["output_files"]
    assert any(str(item).endswith("fe_peak_diagnostics.csv") for item in output_files)
    assert any(str(item).endswith("fe_peak_results.json") for item in output_files)
    coupled_csv = next(Path(item) for item in output_files if str(item).endswith("coupled_results.csv"))
    result_rows = _read_csv_rows(coupled_csv)
    assert float(result_rows[0]["faradaic_efficiency_pct"]) == pytest.approx(100.0, rel=0.03)
    summary = json.loads(Path(body["summary_path"]).read_text(encoding="utf-8"))
    assert summary["coupled"]["input_mode"] == "peak_analysis"
    assert summary["coupled"]["peak_diagnostics_csv"].endswith("fe_peak_diagnostics.csv")


def test_process_folder_runs_peak_based_fe_from_panel_method(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(process_service, "attach_run_outputs", lambda **_kwargs: {"status": "success", "updated": 0})
    folder = tmp_path / "panel_peak_fe"
    folder.mkdir()
    method_file = folder / "method.json"
    signal = folder / "sample-a.csv"
    measurements = folder / "measurements.csv"
    _write_peak_method(method_file)
    method_payload = json.loads(method_file.read_text(encoding="utf-8"))
    method_file.unlink()
    _write_peak_signal(signal)
    charge = 4 * 96485.33212 * 0.001
    measurements.write_text(
        "sample_name,signal_file,charge_C\n"
        f"sample-a,{signal.name},{charge}\n",
        encoding="utf-8",
    )
    payload = {
        "folder_path": str(folder),
        "data_types": ["COUPLED"],
        "params": {
            "coupled_input_mode": "peak_analysis",
            "coupled_products_file": str(measurements),
            "coupled_peak_method_source": "panel",
            "coupled_peak_method": method_payload,
        },
    }

    preflight = process_service.preflight_process_folder(payload)
    result = process_service.process_folder(payload)

    assert preflight["status"] == "success"
    assert preflight["preflight"]["coupled_peak"]["method_source"] == "panel"
    assert preflight["preflight"]["runnable"] is True
    assert result["status"] == "success"
    assert any(
        str(item).endswith("fe_peak_results.json")
        for item in result["result"]["processing"]["output_files"]
    )
