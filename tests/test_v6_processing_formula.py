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
        assert manifest["calculation"]["formula_schema_version"] == FORMULA_SCHEMA_VERSION == "1.3"
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
