from __future__ import annotations

from electrochem_v6.core.processing_metric_registry import (
    get_metric_definition,
    list_metric_definitions,
    normalize_metric_key,
    resolve_metric,
)


def test_normalize_metric_key_handles_common_units():
    assert normalize_metric_key("Potential@10mA/cm²(IR_compensated)") == "potential_at_10ma_cm2_ir_compensated"
    assert normalize_metric_key("Cs_μF/cm²") == "cs_uf_cm2"
    assert normalize_metric_key("R_solution(Ω)") == "r_solution_ohm"


def test_resolve_lsv_dynamic_potential_metric():
    metric = resolve_metric("LSV", "Potential@10mA/cm²(IR_compensated)")

    assert metric.key == "potential_at_10ma_cm2_ir_compensated"
    assert metric.unit == "V"
    assert metric.method == "IR compensated"
    assert metric.definition_key == "lsv.potential_at_current"
    assert metric.metadata["target_current_mA_cm2"] == 10.0


def test_resolve_lsv_overpotential_metric_extracts_equilibrium_potential():
    metric = resolve_metric("LSV", "Overpotential@10mA/cm²(mV)@Eq=1.23V")

    assert metric.unit == "mV"
    assert metric.definition_key == "lsv.overpotential_at_current"
    assert metric.metadata["target_current_mA_cm2"] == 10.0
    assert metric.metadata["equilibrium_potential_V"] == 1.23


def test_resolve_ecsa_static_metric():
    metric = resolve_metric("ECSA", "Cdl_mFcm2")

    assert metric.key == "cdl_mfcm2"
    assert metric.unit == "mF/cm2"
    assert metric.definition_key == "ecsa.double_layer_capacitance"
    assert metric.category == "capacitance"


def test_resolve_cv_static_metric():
    metric = resolve_metric("CV", "charge_mC")

    assert metric.key == "charge_mc"
    assert metric.unit == "mC"
    assert metric.definition_key == "cv.charge"
    assert metric.category == "charge"


def test_resolve_eis_static_metric():
    metric = resolve_metric("EIS", "Rs")

    assert metric.key == "rs"
    assert metric.unit == "ohm"
    assert metric.definition_key == "eis.solution_resistance"
    assert metric.category == "fit"


def test_metric_registry_lists_definitions_by_data_type():
    lsv_items = list_metric_definitions("LSV")

    assert get_metric_definition("lsv.tafel_slope") is not None
    assert lsv_items
    assert all(item.data_type == "LSV" for item in lsv_items)


def test_resolve_coupled_metric_definitions():
    metric = resolve_metric("COUPLED", "faradaic_efficiency_pct")

    assert metric.key == "faradaic_efficiency_pct"
    assert metric.unit == "%"
    assert metric.definition_key == "coupled.faradaic_efficiency"
    assert metric.category == "efficiency"
