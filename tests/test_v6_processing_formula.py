import numpy as np
import pytest

from electrochem_v6.core.processing_formula import FORMULA_SCHEMA_VERSION, formula_catalog, formulas_for_run


def test_formula_catalog_describes_coupled_fe_equations():
    formulas = {item["key"]: item for item in formula_catalog()}

    assert formulas["coupled.faradaic_efficiency"]["expression"] == "FE_i = z_i * F * n_i / Q_total * 100%"
    assert formulas["coupled.product_selectivity"]["result_unit"] == "%"
    assert "Q_total" in {item["symbol"] for item in formulas["coupled.faradaic_efficiency"]["variables"]}


def test_formulas_for_run_filters_rhe_formula_by_parameter_mode():
    lsv_manual = {item["key"] for item in formulas_for_run(["LSV"], {"potential_mode": "manual"})}
    lsv_rhe = {item["key"] for item in formulas_for_run(["LSV"], {"potential_mode": "formula_rhe"})}
    lsv_ir = {
        item["key"]
        for item in formulas_for_run(
            ["LSV"],
            {"potential_mode": "manual", "ir_compensation_enabled": True},
        )
    }
    coupled = {item["key"] for item in formulas_for_run(["COUPLED"], {})}
    coupled_peak = {
        item["key"]
        for item in formulas_for_run(["COUPLED"], {"coupled_input_mode": "peak_analysis"})
    }
    coupled_peak_fit = {
        item["key"]
        for item in formulas_for_run(
            ["COUPLED"],
            {
                "coupled_input_mode": "peak_analysis",
                "fe_peak_fit_enabled": True,
                "fe_peak_reference_align": False,
            },
        )
    }
    cv_without_rate = {item["key"] for item in formulas_for_run(["CV"], {})}
    cv_with_rate = {
        item["key"]
        for item in formulas_for_run(["CV"], {"cv_scan_rate_v_s": 0.05})
    }

    assert "common.rhe_conversion" not in lsv_manual
    assert "common.rhe_conversion" in lsv_rhe
    assert "lsv.ir_compensation" not in lsv_manual
    assert "lsv.ir_compensation" in lsv_ir
    assert "coupled.faradaic_efficiency" in coupled
    assert "coupled.qnmr_product_amount" not in coupled
    assert "coupled.peak_reference_alignment" not in coupled
    assert "coupled.qnmr_product_amount" in coupled_peak
    assert "coupled.peak_reference_alignment" in coupled_peak
    assert "coupled.fixed_window_peak_area" in coupled_peak
    assert "coupled.pseudo_voigt_peak_area" not in coupled_peak
    assert "coupled.fixed_window_peak_area" not in coupled_peak_fit
    assert "coupled.pseudo_voigt_peak_area" in coupled_peak_fit
    assert "coupled.peak_reference_alignment" not in coupled_peak_fit
    assert "cv.absolute_charge" not in cv_without_rate
    assert "cv.absolute_charge" in cv_with_rate


def test_manual_lsv_has_core_formulas_and_only_enabled_tafel_fitting():
    plain = {item["key"] for item in formulas_for_run(["LSV"], {})}
    assert plain == {"lsv.current_density", "lsv.manual_potential_offset", "lsv.target_potential"}
    enabled = {item["key"] for item in formulas_for_run(["LSV"], {"tafel_enabled": "true"})}
    assert enabled == plain | {"lsv.tafel_fit"}
    disabled = {item["key"] for item in formulas_for_run(["LSV"], {"tafel_enabled": "false"})}
    assert disabled == plain
    rhe = {item["key"] for item in formulas_for_run(["LSV"], {"potential_mode": "formula_rhe"})}
    assert "common.rhe_conversion" in rhe and "lsv.manual_potential_offset" not in rhe
    assert not any(item["key"].startswith("lsv.") for item in formulas_for_run(["CV"], {}))


def test_lsv_formula_units_and_conditional_rules_match_real_calculations():
    from electrochem_v6.core.processing_lsv_calc import potential_at_current
    from electrochem_v6.core.processing_lsv_io import parse_lsv_lines
    from electrochem_v6.core.processing_lsv_metrics import compute_tafel_slope_mVdec

    formulas = {item["key"]: item for item in formula_catalog()}
    assert formulas["lsv.current_density"]["result_unit"] == "mA/cm2"
    assert formulas["lsv.manual_potential_offset"]["result_unit"] == "V"
    assert formulas["lsv.target_potential"]["result_unit"] == "V"
    assert formulas["lsv.tafel_fit"]["result_unit"] == "mV/dec"
    raw = parse_lsv_lines(["200 -4"], area=2, offset=.3, potential_scale=.001, current_scale=1, use_abs_current=True)
    assert raw.potential == pytest.approx([.5])
    assert raw.current == pytest.approx([2])
    assert raw.current_signed == pytest.approx([-2])
    signed = parse_lsv_lines(["0.2 -0.004"], area=2, use_abs_current=False)
    assert signed.current == pytest.approx([-2])

    interpolation, branch = potential_at_current([.1, .2, .4], [1, 5, 20], target_i=10)
    assert interpolation == pytest.approx(.2 + (10 - 5) * (.4 - .2) / (20 - 5))
    assert branch is None
    linear, branch = potential_at_current([.1, .15, .2], [10, 15, 20], target_i=25)
    assert linear == pytest.approx(.25) and branch[2] == "linear"
    currents = np.array([1, 10, 30])
    potentials = .5 + .06 * np.log10(currents)
    logarithmic, branch = potential_at_current(potentials, currents, target_i=45)
    assert logarithmic == pytest.approx(.5 + .06 * np.log10(45)) and branch[2].startswith("tafel")
    outside_guard, branch = potential_at_current(potentials, currents, target_i=61)
    assert np.isnan(outside_guard) and branch is None
    assert compute_tafel_slope_mVdec(potentials, currents, "1-30") == pytest.approx(60)
    assert compute_tafel_slope_mVdec(-potentials, currents, "1-30") == pytest.approx(-60)
    assert compute_tafel_slope_mVdec(potentials, currents, "1-10") is None


def test_new_lsv_pipeline_persists_formulas_without_rewriting_old_recipe(tmp_path, monkeypatch):
    from electrochem_v6.core.process_service import process_folder
    from electrochem_v6.store.run_recipes import get_run_recipe, save_run_recipe
    from electrochem_v6.store.runtime import get_database, reset_runtime

    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    try:
        save_run_recipe({"run_id": "old-recipe", "manifest": {"calculation": {"formula_schema_version": "1.2", "formulas": []}}})
        folder = tmp_path / "data"
        folder.mkdir()
        currents = np.geomspace(1, 100, 25)
        potentials = .6 + .12 * np.log10(currents)
        (folder / "LSV_formula.txt").write_text("Potential Current\n" + "\n".join(
            f"{potential} {current * 2 / 1000}" for potential, current in zip(potentials, currents)
        ))
        result = process_folder({"folder_path": str(folder), "data_types": ["LSV"], "params": {
            "potential_mode": "manual", "potential_offset": .25, "area": 2,
            "tafel_enabled": True, "tafel_range": "1-10", "ir_compensation_enabled": False,
        }})
        assert result["status"] == "success", result
        manifest = result["result"]["manifest"]
        assert manifest["calculation"]["formula_schema_version"] == FORMULA_SCHEMA_VERSION == "1.4"
        assert {item["key"] for item in manifest["calculation"]["formulas"]} == {
            "lsv.current_density", "lsv.manual_potential_offset", "lsv.target_potential", "lsv.tafel_fit",
        }
        recipe = get_run_recipe(manifest["run"]["run_id"])
        record = get_database().get_history_record(recipe["record_keys"][0])
        assert record["results"]["tafel_slope"] == pytest.approx(120)
        assert recipe["manifest"]["calculation"] == manifest["calculation"]
        old = get_run_recipe("old-recipe")["manifest"]["calculation"]
        assert old == {"formula_schema_version": "1.2", "formulas": []}
    finally:
        reset_runtime()


@pytest.mark.parametrize("model", [
    "randles_rc", "randles_cpe", "randles_warburg_rc", "randles_warburg_cpe",
    "two_time_constants_rc", "two_time_constants_cpe",
])
def test_eis_snapshot_contains_only_selected_model_with_exact_units_and_run_controls(model):
    from electrochem_v6.core.processing_eis_calc import EIS_CIRCUIT_MODELS

    formulas = formulas_for_run(["EIS"], {
        "eis_randles_fit": True, "eis_circuit_model": model, "eis_kk_check": False,
        "eis_fit_weighting": "modulus", "eis_fit_frequency_min_hz": "0.5",
        "eis_fit_frequency_max_hz": 20000, "eis_fit_min_r2": .95,
    })
    assert len(formulas) == 1
    formula = formulas[0]
    assert formula["key"] == f"eis.{model}"
    metadata = formula["metadata"]
    assert metadata["equivalent_circuit"] == EIS_CIRCUIT_MODELS[model]["equivalent_circuit"]
    assert metadata["weighting"] == "modulus"
    assert "median(abs(Z_data))*1e-6" in metadata["objective"]
    assert metadata["frequency_window"] == {
        "requested_min_hz": .5, "requested_max_hz": 20000, "interval": "closed", "unit": "Hz",
        "empty_bound": "all available frequencies on that side", "source_data_modified": False,
    }
    assert metadata["acceptance_criterion"]["minimum"] == .95
    variables = {item["symbol"]: item for item in formula["variables"]}
    assert variables["f"]["unit"] == "Hz"
    for parameter, unit in metadata["parameter_units"].items():
        assert variables[parameter]["unit"] == unit
    if "warburg" in model:
        assert "Z_W = sigma*(1-j)/sqrt(omega)" in formula["expression"]
        assert "1/(Rct + Z_W)" in formula["expression"]
        assert variables["sigma"]["unit"] == "Ohm*s^-0.5"
    if model.startswith("two_"):
        assert "Rct" not in variables
        assert "tau1 <= tau2" in formula["expression"]
        assert variables["R1"]["unit"] == variables["R2"]["unit"] == "Ohm"
    assert "not simultaneous" in " ".join(formula["assumptions"])


def test_eis_fitting_and_kk_switches_are_independent_and_snapshot_method_does_not_drift():
    from electrochem_v6.core.processing_eis_validation import kk_validation_metadata, validate_eis_kk

    assert formulas_for_run(["EIS"], {}) == []
    assert formulas_for_run(["EIS"], {"eis_randles_fit": "false", "eis_kk_check": "false"}) == []
    params = {"eis_randles_fit": False, "eis_circuit_model": "two_time_constants_cpe", "eis_kk_check": True}
    kk_only = formulas_for_run(["EIS"], params)
    assert [item["key"] for item in kk_only] == ["eis.lin_kk_validation"]
    metadata = kk_only[0]["metadata"]
    assert metadata["method_description"] == kk_validation_metadata()["method_description"]
    assert metadata["thresholds"] == validate_eis_kk([], [], [])["thresholds"]
    assert metadata["frequency_window"]["requested_min_hz"] is None
    assert "Modulus-weighted" in metadata["method_description"]
    assert "weighting" not in metadata  # The circuit's uniform/modulus control does not change the KK method.
    both = formulas_for_run(["EIS"], {**params, "eis_randles_fit": True})
    assert {item["key"] for item in both} == {"eis.two_time_constants_cpe", "eis.lin_kk_validation"}
    assert both[0]["metadata"]["weighting"] == "uniform"
    assert not any(item["key"].startswith("eis.") for item in formulas_for_run(["LSV"], params))

    metadata["thresholds"]["normalized_rms_max"] = 99
    both[0]["metadata"]["parameter_units"]["Rs"] = "corrupted"
    fresh = formulas_for_run(["EIS"], {**params, "eis_randles_fit": True})
    assert fresh[0]["metadata"]["parameter_units"]["Rs"] == "Ohm"
    assert fresh[-1]["metadata"]["thresholds"]["normalized_rms_max"] == .02


def test_new_eis_pipeline_saves_selected_formula_and_leaves_legacy_snapshot_unchanged(tmp_path, monkeypatch):
    from electrochem_v6.core.process_service import process_folder
    from electrochem_v6.store.run_recipes import get_run_recipe, save_run_recipe
    from electrochem_v6.store.runtime import reset_runtime

    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    try:
        old_calculation = {"formula_schema_version": "1.3", "formulas": []}
        save_run_recipe({"run_id": "legacy-eis", "manifest": {"calculation": old_calculation}})
        folder = tmp_path / "data"
        folder.mkdir()
        frequency = np.logspace(-1, 5, 60)
        omega = 2 * np.pi * frequency
        impedance = 7 + 1 / (1j * omega * 1e-5 + 1 / (85 + 20 * (1 - 1j) / np.sqrt(omega)))
        (folder / "EIS_formula.txt").write_text("Frequency Zreal Zimag\n" + "\n".join(
            f"{f:.17g} {z.real:.17g} {z.imag:.17g}" for f, z in zip(frequency, impedance)
        ))
        response = process_folder({"folder_path": str(folder), "data_types": ["EIS"], "params": {
            "eis_randles_fit": True, "eis_circuit_model": "randles_warburg_rc", "eis_kk_check": True,
            "eis_fit_weighting": "modulus", "eis_fit_frequency_min_hz": .1, "eis_fit_frequency_max_hz": 100000,
            "plot_nyquist": False, "plot_bode": False,
        }})
        assert response["status"] == "success", response
        manifest = response["result"]["manifest"]
        calculation = manifest["calculation"]
        assert calculation["formula_schema_version"] == FORMULA_SCHEMA_VERSION == "1.4"
        assert {item["key"] for item in calculation["formulas"]} == {"eis.randles_warburg_rc", "eis.lin_kk_validation"}
        snapshot = get_run_recipe(manifest["run"]["run_id"])
        assert snapshot["manifest"]["calculation"] == calculation
        assert get_run_recipe("legacy-eis")["manifest"]["calculation"] == old_calculation
    finally:
        reset_runtime()
