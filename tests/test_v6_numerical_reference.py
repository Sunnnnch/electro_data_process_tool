"""Versioned numerical regression checks for core electrochemical calculations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from electrochem_v6.core.processing_coupled_calc import calculate_coupled_product_results
from electrochem_v6.core.processing_coupled_models import ProductQuantification
from electrochem_v6.core.processing_cv_calc import compute_charge_mC, split_cv_cycles
from electrochem_v6.core.processing_ecsa_calc import calculate_ecsa_fit
from electrochem_v6.core.processing_eis_calc import fit_randles
from electrochem_v6.core.processing_lsv_calc import apply_ir_compensation
from electrochem_v6.core.processing_lsv_io import parse_lsv_lines
from electrochem_v6.core.processing_lsv_metrics import (
    compute_overpotentials,
    compute_tafel_slope_mVdec,
    compute_target_potentials,
)

REFERENCE_FILE = Path(__file__).parent / "reference_data" / "electrochem_reference_v1.json"


@pytest.fixture(scope="module")
def reference_cases() -> dict[str, Any]:
    payload = json.loads(REFERENCE_FILE.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    return payload["cases"]


def test_lsv_reference_case(reference_cases: dict[str, Any]) -> None:
    case = reference_cases["lsv"]
    params = case["parameters"]
    expected = case["expected"]
    tolerance = case["absolute_tolerance"]
    lines = [
        f"{potential:.17g} {current:.17g}\n"
        for potential, current in zip(case["raw_potential_v"], case["raw_current_a"])
    ]

    raw = parse_lsv_lines(
        lines,
        offset=params["potential_offset_v"],
        area=params["area_cm2"],
        use_abs_current=False,
    )
    assert raw.potential == pytest.approx(expected["potential_v"], abs=tolerance)
    assert raw.current_signed == pytest.approx(
        expected["current_density_ma_cm2"], abs=tolerance
    )

    targets = compute_target_potentials(
        raw.potential,
        raw.current,
        [params["target_current_ma_cm2"]],
    ).potentials
    target_potential = targets[params["target_current_ma_cm2"]]
    assert target_potential == pytest.approx(expected["target_potential_v"], abs=tolerance)

    overpotentials = compute_overpotentials(targets, params["equilibrium_potential_v"])
    assert overpotentials[params["target_current_ma_cm2"]] == pytest.approx(
        expected["target_overpotential_mv"], abs=tolerance
    )
    assert compute_tafel_slope_mVdec(
        raw.potential,
        raw.current,
        params["tafel_range"],
    ) == pytest.approx(expected["tafel_slope_mv_dec"], abs=tolerance)

    compensated = apply_ir_compensation(
        raw.potential,
        raw.current_signed,
        area_cm2=params["area_cm2"],
        resistance_ohm=params["resistance_ohm"],
    )
    assert compensated == pytest.approx(
        expected["ir_compensated_potential_v"], abs=tolerance
    )
    compensated_targets = compute_target_potentials(
        compensated,
        raw.current,
        [params["target_current_ma_cm2"]],
    ).potentials
    assert compensated_targets[params["target_current_ma_cm2"]] == pytest.approx(
        expected["ir_target_potential_v"], abs=tolerance
    )


def test_cv_reference_case(reference_cases: dict[str, Any]) -> None:
    case = reference_cases["cv"]
    expected = case["expected"]
    tolerance = case["absolute_tolerance"]

    charge = compute_charge_mC(
        case["potential_v"],
        case["current_ma"],
        scan_rate_v_s=case["scan_rate_v_s"],
    )
    cycles = split_cv_cycles(case["potential_v"], case["current_ma"])

    assert charge == pytest.approx(expected["charge_mc"], abs=tolerance)
    assert len(cycles) == expected["cycle_count"]


def test_eis_reference_case(reference_cases: dict[str, Any]) -> None:
    case = reference_cases["eis"]
    expected = case["expected"]
    tolerance = case["relative_tolerance"]

    fit = fit_randles(case["frequency_hz"], case["z_real_ohm"], case["z_imag_ohm"])

    assert fit is not None
    assert fit["Rs"] == pytest.approx(expected["rs_ohm"], rel=tolerance)
    assert fit["Rct"] == pytest.approx(expected["rct_ohm"], rel=tolerance)
    assert fit["Cdl"] == pytest.approx(expected["cdl_f"], rel=tolerance)
    assert fit["r2"] >= expected["minimum_r2"]


def test_ecsa_reference_case(reference_cases: dict[str, Any]) -> None:
    case = reference_cases["ecsa"]
    params = case["parameters"]
    expected = case["expected"]
    tolerance = case["absolute_tolerance"]

    fit = calculate_ecsa_fit(
        v_list=case["scan_rate_v_s"],
        dJ_list=case["delta_j_ma_cm2"],
        area_cm2=params["area_cm2"],
        cs_value=params["cs_value"],
        cs_unit=params["cs_unit"],
    )

    assert fit is not None
    assert fit.slope_mFcm2 == pytest.approx(expected["slope_mf_cm2"], abs=tolerance)
    assert fit.intercept == pytest.approx(expected["intercept"], abs=tolerance)
    assert fit.r2 == pytest.approx(expected["r2"], abs=tolerance)
    assert fit.cdl_mFcm2 == pytest.approx(expected["cdl_mf_cm2"], abs=tolerance)
    assert fit.cs_mFcm2 == pytest.approx(expected["cs_mf_cm2"], abs=tolerance)
    assert fit.rf == pytest.approx(expected["rf"], abs=tolerance)
    assert fit.ecsa_cm2 == pytest.approx(expected["ecsa_cm2"], abs=tolerance)


def test_fe_reference_case(reference_cases: dict[str, Any]) -> None:
    case = reference_cases["fe"]
    expected = case["expected"]
    tolerance = case["absolute_tolerance"]
    inputs = [
        ProductQuantification(
            sample_name=case["sample_name"],
            product_name=product["name"],
            product_moles=product["product_moles"],
            electron_count=product["electron_count"],
            charge_coulomb=case["charge_coulomb"],
        )
        for product in case["products"]
    ]

    results = calculate_coupled_product_results(inputs)
    by_product = {result.product_name: result for result in results}
    assert set(by_product) == set(expected)
    for product_name, expected_values in expected.items():
        result = by_product[product_name]
        assert result.faradaic_efficiency_pct == pytest.approx(
            expected_values["faradaic_efficiency_pct"], abs=tolerance
        )
        assert result.product_selectivity_pct == pytest.approx(
            expected_values["product_selectivity_pct"], abs=tolerance
        )
        assert result.fe_selectivity_pct == pytest.approx(
            expected_values["fe_selectivity_pct"], abs=tolerance
        )
