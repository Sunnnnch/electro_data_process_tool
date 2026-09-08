"""Scientific fits must distinguish valid data from unidentifiable models."""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import numpy as np
import pytest

from electrochem_v6.core.process_service import process_folder
from electrochem_v6.core.processing_ecsa_calc import calculate_ecsa_fit, compute_deltaJ_for_file
from electrochem_v6.core.processing_lsv_metrics import compute_tafel_slope_mVdec, fit_tafel_data
from electrochem_v6.core.reproducible_report_service import export_run_report
from electrochem_v6.store.history import build_project_report
from electrochem_v6.store.run_recipes import get_run_recipe
from electrochem_v6.store.runtime import get_database, reset_runtime


@pytest.fixture
def scientific_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    for key in ("PROJECTS", "HISTORY", "CONVERSATION", "TEMPLATE", "QUALITY_REPORT", "LOG", "LLM_CONFIG"):
        monkeypatch.delenv(f"ELECTROCHEM_V6_{key}_FILE", raising=False)
    reset_runtime()
    yield tmp_path
    reset_runtime()


@pytest.mark.parametrize("current,fit_range", [
    ([1.0] * 4, "0.1-100"),
    ([10.0] * 4, "1-100"),
    ([10.0, np.nextafter(10.0, 11.0), 10.0, 10.0], "1-100"),
    ([1e-13, 2e-13, 3e-13, 4e-13], "0.00000000000001-1"),
])
def test_tafel_rejects_unresolved_log_current_span(current, fit_range):
    assert compute_tafel_slope_mVdec([0.0, 0.3, 0.6, 0.9], current, fit_range) is None
    assert fit_tafel_data([0.0, 0.3, 0.6, 0.9], current, fit_range) is None


@pytest.mark.parametrize("potential", [
    [0.5] * 4, [0.0] * 4, [0.5, np.nextafter(0.5, 1.0), 0.5, 0.5],
])
def test_tafel_rejects_constant_potential_instead_of_perfect_r_squared(potential):
    assert fit_tafel_data(potential, [1, 2, 5, 10], "1-10") is None
    assert compute_tafel_slope_mVdec(potential, [1, 2, 5, 10], "1-10") is None


@pytest.mark.parametrize("slope", [0.12, -0.12])
def test_identifiable_tafel_fit_preserves_signed_analytical_slope(slope):
    current = np.logspace(0, 2, 40)
    potential = 0.3 + slope * np.log10(current)
    fitted = fit_tafel_data(potential, current, "1-100")
    assert fitted is not None
    assert fitted["slope_mVdec"] == pytest.approx(slope * 1000, abs=1e-9)
    assert fitted["r2"] == pytest.approx(1.0)
    assert fitted["E_fit"] == pytest.approx(potential)


def test_tafel_pipeline_omits_plateau_slope_and_marks_low_fit_quality(scientific_runtime):
    folder = scientific_runtime / "lsv"
    folder.mkdir()
    (folder / "LSV_plateau.txt").write_text("\n".join(f"{i / 100:.6f}\t0.01" for i in range(101)), encoding="utf-8")
    (folder / "LSV_nonlinear.txt").write_text("\n".join(f"{i / 100:.6f}\t{0.001 + i * 0.00019:.8f}" for i in range(101)), encoding="utf-8")
    (folder / "LSV_fixed_potential.txt").write_text("\n".join(f"0.5\t{0.001 + i * 0.00019:.8f}" for i in range(101)), encoding="utf-8")
    response = process_folder({"folder_path": str(folder), "data_types": ["LSV"], "project_name": "Degenerate fit review",
                               "params": {"tafel_enabled": True, "tafel_range": "1-100", "area": 1.0}})
    assert response["status"] == "success", response
    result = response["result"]
    records = {item["source"]["file_name"]: item for item in result["manifest"]["processing_results"]}
    plateau = [item for item in records["LSV_plateau"]["metrics"] if "tafel" in item["key"]]
    assert not plateau or all(item["value"] is None for item in plateau)
    fixed_potential = [item for item in records["LSV_fixed_potential"]["metrics"] if "tafel" in item["key"]]
    assert not fixed_potential or all(item["value"] is None for item in fixed_potential)
    assert any(item["value"] is not None for item in records["LSV_nonlinear"]["metrics"] if "tafel" in item["key"])
    reports = result["manifest"]["quality_reports"]
    assert len(reports) == 3
    assert {item["stats"]["tafel_fit"]["status"] for item in reports} == {"unavailable", "low_r2"}
    assert all(item["quality_level"] != "good" and item["recommendation"] != "ready_to_use" for item in reports)
    with Path(result["summary_json"]["lsv"]["csv"]).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert next(row for row in rows if row["file_name"] == "LSV_plateau")["tafelslope_mv_dec"] == ""
    # The service attaches final quality after module execution. Reopen the
    # database and read the project/report path, not just the current response.
    run_id = result["manifest"]["run"]["run_id"]
    reset_runtime()
    recipe = get_run_recipe(run_id)
    assert recipe is not None and len(recipe["record_keys"]) == 3
    for record_key in recipe["record_keys"]:
        record = get_database().get_history_record(record_key)
        assert record["quality_summary"]["quality_levels"].get("good", 0) == 0
        assert record["quality_summary"]["recommendations"].get("ready_to_use", 0) == 0
        assert record["quality_summary"]["warnings"] >= 3
        if record["file_name"] in {"LSV_plateau", "LSV_fixed_potential"}:
            assert "tafel_slope" not in record["results"]
    project = build_project_report(result["project_id"])
    assert len(project["report"]["records"]) == 3
    assert all(record["quality_summary"]["warnings"] >= 3 for record in project["report"]["records"])
    report = export_run_report(run_id, output_dir=str(scientific_runtime / "saved-report"))
    rendered = Path(report["markdown_path"]).read_text(encoding="utf-8")
    assert "Tafel 未计算" in rendered and "拟合质量偏低" in rendered


@pytest.mark.parametrize("delta", [[3, 2, 1], [1, 1, 1], [0, 0, 0]])
def test_ecsa_rejects_nonpositive_or_unresolved_capacitance_with_fit_diagnostics(delta):
    with pytest.raises(ValueError, match="positive DeltaJ.*observed slope=.*R2="):
        calculate_ecsa_fit(v_list=[0.02, 0.04, 0.06], dJ_list=delta, area_cm2=1, cs_value=50, cs_unit="uF/cm2")


def _write_ecsa(path, delta, *, polarity=1, reverse=False):
    rows = []
    for _ in range(2):
        rows.extend((i * 0.2 / 60, polarity * delta / 2000) for i in range(61))
        rows.extend((i * 0.2 / 60, -polarity * delta / 2000) for i in range(59, -1, -1))
    if reverse:
        rows.reverse()
    path.write_text("\n".join(f"{e:.10f}\t{i:.10f}" for e, i in rows), encoding="utf-8")


@pytest.mark.parametrize("polarity", [-1, 1])
@pytest.mark.parametrize("reverse", [False, True])
def test_ecsa_positive_capacitance_survives_polarity_and_sweep_order(tmp_path, polarity, reverse):
    rates, deltas = [], []
    for rate, delta in ((20, 1), (40, 2), (60, 3)):
        path = tmp_path / f"ECSA{rate}.txt"
        _write_ecsa(path, delta, polarity=polarity, reverse=reverse)
        scan_rate, measured_delta = compute_deltaJ_for_file(str(path), Ev=0.1, use_abs_delta=True)
        rates.append(scan_rate)
        deltas.append(measured_delta)
    fitted = calculate_ecsa_fit(v_list=rates, dJ_list=deltas, area_cm2=1, cs_value=50, cs_unit="uF/cm2")
    assert fitted is not None
    assert fitted.cdl_mFcm2 == pytest.approx(25)
    assert fitted.ecsa_cm2 == pytest.approx(500)


def test_ecsa_pipeline_preserves_sources_and_reports_rejected_negative_fit(scientific_runtime):
    folder = scientific_runtime / "ecsa"
    folder.mkdir()
    for rate, delta in ((20, 3), (40, 2), (60, 1)):
        _write_ecsa(folder / f"ECSA{rate}.txt", delta)
    originals = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.glob("*.txt")}
    response = process_folder({"folder_path": str(folder), "data_types": ["ECSA"],
                               "params": {"ecsa_ev": 0.1, "ecsa_cs_value": 50, "ecsa_cs_unit": "uF/cm2", "area": 1}})
    assert response["status"] == "error"
    result = response["result"]
    assert not result["raw"]["processing_results"]
    report = result["raw"]["quality_reports"][0]
    assert report["is_valid"] is False and report["quality_level"] == "error"
    assert "slope=-50" in report["issues"][0] and "R2=1" in report["issues"][0]
    assert result["quality_summary"]["failed"] == 1
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == expected for path, expected in originals.items())
