"""Known-curve regression checks for assistant scientific recommendations."""

import json
from unittest.mock import patch

import numpy as np
import pytest

from electrochem_v6.agent.tools_analysis import tool_analyze_processing_results
from electrochem_v6.agent.tools_catalyst import tool_get_catalyst_info
from electrochem_v6.agent.tools_data import tool_analyze_data_characteristics
from electrochem_v6.agent.tools_projects import tool_auto_process_with_smart_params
from electrochem_v6.core.agent_scientific import metric_value, scientific_parameter_requirements
from electrochem_v6.core.processing_lsv_io import read_lsv_raw_data
from electrochem_v6.core.processing_lsv_metrics import compute_tafel_slope_mVdec
from electrochem_v6.store.runtime import reset_runtime


def source_params(**overrides):
    return {"area": 2.0, "potential_mode": "manual", "potential_offset": 0.0,
            "lsv_potential_column": 1, "lsv_current_column": 2, "lsv_potential_unit": "v",
            "lsv_current_unit": "a", "use_abs_current": True, "ir_compensation_enabled": False, **overrides}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    yield tmp_path
    reset_runtime()


def write_curve(folder, count=101, *, current_unit="a", potential_unit="v", reordered=False, resistance=0, sign=1):
    path = folder / "LSV_source.csv"
    density = np.geomspace(0.1, 100, count)
    volts = 0.06 * np.log10(density) + sign * density * 2 / 1000 * resistance
    currents = sign * density * 2 / {"a": 1000, "ma": 1, "ua": 0.001}[current_unit]
    potentials = volts * (1000 if potential_unit == "mv" else 1)
    rows = [f"{index};{p:.15g};{c:.15g}" if reordered else f"{p:.15g};{c:.15g}" for index, (p, c) in enumerate(zip(potentials, currents))]
    path.write_text("\n".join(rows), encoding="utf-8")
    return path, density


@pytest.mark.parametrize("unit", ["a", "ma", "ua"])
def test_complete_input_and_formal_parser_use_identical_normalization(workspace, unit):
    path, density = write_curve(workspace, 1205, current_unit=unit, potential_unit="mv", reordered=True)
    params = source_params(lsv_current_unit=unit, lsv_potential_unit="mv", lsv_potential_column=2, lsv_current_column=3)
    result = tool_analyze_data_characteristics(str(path), "LSV", params)
    assert result["success"], result
    assert result["recommendation_status"] == "candidates_available", result
    features = result["characteristics"]
    assert features["data_points"] == 1205  # Old path capped at 1000 and consumed the first row as header.
    assert features["current_density_range_mA_cm2"]["min"] == pytest.approx(density[0])
    assert features["current_density_range_mA_cm2"]["max"] == pytest.approx(density[-1])
    assert result["units"]["current_density"] == "mA/cm²"
    formal = read_lsv_raw_data(str(path), file_label=path.name, params=params)
    assert len(formal.current) == features["data_points"]
    for candidate in result["candidate_tafel_ranges"]:
        assert candidate["point_count"] >= 8
        assert candidate["log_span_decades"] >= 0.5
        assert candidate["slope_mV_dec"] == pytest.approx(60)
        assert candidate["slope_mV_dec"] == pytest.approx(compute_tafel_slope_mVdec(formal.potential, formal.current, candidate["tafel_range"]))
        assert candidate["rmse_V"] < 1e-10
        assert candidate["r2"] == pytest.approx(1)
    assert result["provenance"]["full_input_read"] is True
    assert "suggested_tafel_range" not in features
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("key", ["area", "lsv_current_unit", "lsv_potential_column", "potential_mode", "ir_compensation_enabled"])
def test_unknown_scientific_parameters_are_reported_not_guessed(workspace, key):
    path, _ = write_curve(workspace)
    params = source_params()
    del params[key]
    result = tool_analyze_data_characteristics(str(path), "LSV", params)
    assert result["recommendation_status"] == "needs_parameters"
    assert key in {item["key"] for item in result["missing_parameters"]}
    assert result["candidate_tafel_ranges"] == []
    assert key not in result["effective_params"]


@pytest.mark.parametrize("area", [0, -1, float("nan"), float("inf")])
def test_invalid_area_cannot_fall_back_to_one(workspace, area):
    assert scientific_parameter_requirements("LSV", source_params(area=area))
    path, _ = write_curve(workspace)
    result = tool_analyze_data_characteristics(str(path), "LSV", source_params(area=area))
    assert result["recommendation_status"] == "needs_parameters"
    assert not result["candidate_tafel_ranges"]


def test_manual_ir_and_signed_current_match_processing_formula(workspace):
    path, _ = write_curve(workspace, resistance=7)
    params = source_params(ir_compensation_enabled=True, ir_source="manual", ir_manual_ohm=7)
    result = tool_analyze_data_characteristics(str(path), "LSV", params)
    assert result["recommendation_status"] == "candidates_available", result
    assert all(item["slope_mV_dec"] == pytest.approx(60) for item in result["candidate_tafel_ranges"])
    assert result["characteristics"]["ir_compensation"]["rs_ohm"] == 7


def test_negative_current_keeps_signed_ir_correction(workspace):
    path, _ = write_curve(workspace, resistance=0.01, sign=-1)
    result = tool_analyze_data_characteristics(str(path), "LSV", source_params(
        ir_compensation_enabled=True, ir_source="manual", ir_manual_ohm=0.01))
    assert result["recommendation_status"] == "candidates_available", result
    assert all(item["current_sign"] == -1 and item["slope_mV_dec"] == pytest.approx(60) for item in result["candidate_tafel_ranges"])
    signed = tool_analyze_data_characteristics(str(path), "LSV", source_params(use_abs_current=False))
    assert signed["recommendation_status"] == "insufficient_data"


def test_eis_source_units_and_rhe_conversion_use_the_formal_contract(workspace):
    from electrochem_v6.core.process_service import _resolve_potential_offset

    path, _ = write_curve(workspace, resistance=7)
    eis = workspace / "EIS_source.csv"
    eis.write_text("\n".join(f"{frequency};{0.007 + index * 0.00001};0" for index, frequency in enumerate([100, 80, 60, 40, 20, 10, 5, 2, 1, .5, .2, .1])), encoding="utf-8")
    params = source_params(ir_compensation_enabled=True, ir_source="eis", ir_eis_search_scope="specified_file",
        ir_eis_file=str(eis), ir_method="hf_intercept", ir_validation_mode="strict",
        ir_eis_frequency_column=1, ir_eis_zreal_column=2, ir_eis_zimag_column=3,
        ir_eis_frequency_unit="khz", ir_eis_impedance_unit="kohm", ir_eis_zimag_convention="z_imaginary",
        potential_mode="formula_rhe", rhe_ph=7, rhe_temperature_c=25, reference_electrode_preset="agcl_sat_kcl")
    result = tool_analyze_data_characteristics(str(path), "LSV", params)
    assert result["recommendation_status"] == "candidates_available", result
    assert result["characteristics"]["ir_compensation"]["rs_ohm"] == pytest.approx(7)
    assert result["provenance"]["dependencies"][0]["path"] == str(eis)
    expected_offset = _resolve_potential_offset({"params": params})
    assert result["effective_params"]["potential_offset"] == pytest.approx(expected_offset)
    assert all(item["slope_mV_dec"] == pytest.approx(60) and item["intercept_V"] == pytest.approx(expected_offset) for item in result["candidate_tafel_ranges"])


def test_candidates_do_not_merge_scans_or_extrapolate_configured_range(workspace):
    path, _ = write_curve(workspace)
    result = tool_analyze_data_characteristics(str(path), "LSV", source_params(tafel_range="5-5000"))
    assert all(item["range_mA_cm2"][1] <= 100 for item in result["candidate_tafel_ranges"])
    original = path.read_text()
    path.write_text(original + "\n" + "\n".join(reversed(original.splitlines())))
    result = tool_analyze_data_characteristics(str(path), "LSV", source_params())
    assert result["recommendation_status"] == "insufficient_data"
    assert result["candidate_tafel_ranges"] == []


def test_sparse_or_nonfinite_data_cannot_supply_fit(workspace):
    path, _ = write_curve(workspace, count=7)
    result = tool_analyze_data_characteristics(str(path), "LSV", source_params())
    assert result["recommendation_status"] == "insufficient_data"
    path.write_text(path.read_text() + "\nNaN;1\ninf;2\n")
    result = tool_analyze_data_characteristics(str(path), "LSV", source_params())
    assert result["characteristics"]["rejected_nonfinite_points"] == 2
    json.dumps(result, allow_nan=False)


def test_history_units_zero_and_nonfinite_values_are_explicit(workspace):
    assert metric_value({"type": "LSV", "results": {"overpotential_10": 250}}, "overpotential_at_10", "mV") == 250
    assert metric_value({"type": "LSV", "results": {"overpotential_10": {"value": 0.25, "unit": "V"}}}, "overpotential_at_10", "mV") == 250
    samples = [{"overpotential_10": value} for value in [0, 200, 400, None, float("nan"), float("inf")]]
    with patch("electrochem_v6.agent.tool_executor.tool_query_lsv_summary", return_value={"success": True, "samples": samples}) as query:
        result = tool_analyze_processing_results(include_quality=False)
    assert query.call_args.kwargs["top_n"] == 0
    stats = result["components"]["performance"]["statistics"]
    assert stats["unit"] == "mV" and stats["minimum"] == 0
    assert stats["mean"] == 200 and stats["finite_value_count"] == 3
    assert "excellent_count" not in stats and "best_eta" not in stats
    json.dumps(result, allow_nan=False)


def test_catalyst_versions_are_not_averaged_and_zero_is_kept(workspace):
    records = [{"sample_name": "A", "type": "LSV", "timestamp": timestamp, "record_key": timestamp,
                "run_id": timestamp, "results": {"overpotential_10": value, "tafel_slope": 0}}
               for timestamp, value in [("2026-01-01", 100), ("2026-01-02", 0)]]
    with patch("electrochem_v6.store.runtime.get_history_store") as store:
        store.return_value.get_all_records.return_value = records
        result = tool_get_catalyst_info("A")
    assert result["lsv"]["overpotential_10"] == 0
    assert result["lsv"]["units"]["overpotential_10"] == "mV"
    assert result["lsv"]["aggregation_method"] == "latest_record_no_replicate_aggregation"
    assert result["lsv"]["record_key"] == "2026-01-02"
    assert "performance_level" not in result["lsv"]


def test_automatic_processing_blocks_unknown_area_and_preserves_explicit_settings(workspace):
    path, _ = write_curve(workspace)
    with patch("electrochem_v6.core.process_service.process_folder") as process:
        blocked = tool_auto_process_with_smart_params(str(path.parent), "LSV")
        assert blocked["status"] == "needs_parameters"
        process.assert_not_called()
    params = source_params(area=4, potential_offset=0, tafel_enabled=False)
    result = tool_auto_process_with_smart_params(str(path.parent), "LSV", extra_gui_params=params, target_current="1")
    assert result["success"], result
    assert result["parameters"]["electrode_area"] == 4
    assert result["parameters"]["potential_offset"] == 0
    assert result["run_id"]


def test_saved_recipe_parameters_require_source_membership(workspace):
    path, _ = write_curve(workspace)
    result = tool_auto_process_with_smart_params(str(path.parent), "LSV", extra_gui_params=source_params(), target_current="1")
    recommended = tool_analyze_data_characteristics(str(path), "LSV", run_id=result["run_id"])
    assert recommended["recommendation_status"] == "candidates_available", recommended
    assert recommended["provenance"]["recipe_input_state"] == "unchanged"
    path.write_text(path.read_text() + "\n", encoding="utf-8")
    changed = tool_analyze_data_characteristics(str(path), "LSV", run_id=result["run_id"])
    assert changed["provenance"]["recipe_input_state"] == "changed"
    other = workspace / "LSV_other.csv"
    other.write_bytes(path.read_bytes())
    assert not tool_analyze_data_characteristics(str(other), "LSV", run_id=result["run_id"])["success"]
