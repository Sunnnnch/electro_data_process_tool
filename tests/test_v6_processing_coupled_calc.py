from __future__ import annotations

import pytest

from electrochem_v6.core.processing_coupled_calc import (
    FARADAY_CONSTANT_C_PER_MOL,
    calculate_coupled_product_results,
    calculate_faradaic_efficiency_pct,
    calculate_fe_selectivity_pct,
    calculate_selectivity_pct,
    coupled_results_to_processing_results,
)
from electrochem_v6.core.processing_coupled_models import CoupledCalculationError, ProductQuantification


def test_calculate_faradaic_efficiency_pct_uses_standard_formula():
    result = calculate_faradaic_efficiency_pct(
        product_moles=1.0e-6,
        electron_count=2,
        charge_coulomb=0.5,
    )

    assert result == pytest.approx(2 * FARADAY_CONSTANT_C_PER_MOL * 1.0e-6 / 0.5 * 100.0)


def test_calculate_faradaic_efficiency_rejects_invalid_denominator():
    with pytest.raises(CoupledCalculationError):
        calculate_faradaic_efficiency_pct(
            product_moles=1.0e-6,
            electron_count=2,
            charge_coulomb=0,
        )


def test_calculate_selectivity_pct_uses_product_moles():
    result = calculate_selectivity_pct({"H2": 2.0, "CO": 1.0})

    assert result["H2"] == pytest.approx(66.6666667)
    assert result["CO"] == pytest.approx(33.3333333)


def test_calculate_fe_selectivity_pct_uses_fe_share():
    result = calculate_fe_selectivity_pct({"H2": 40.0, "CO": 10.0})

    assert result == {"H2": pytest.approx(80.0), "CO": pytest.approx(20.0)}


def test_calculate_coupled_product_results_groups_by_sample():
    inputs = [
        ProductQuantification("sample-a", "H2", product_moles=2.0e-6, electron_count=2, charge_coulomb=1.0),
        ProductQuantification("sample-a", "CO", product_moles=1.0e-6, electron_count=2, charge_coulomb=1.0),
    ]

    results = calculate_coupled_product_results(inputs)

    by_product = {item.product_name: item for item in results}
    assert by_product["H2"].faradaic_efficiency_pct == pytest.approx(
        2 * FARADAY_CONSTANT_C_PER_MOL * 2.0e-6 / 1.0 * 100.0
    )
    assert by_product["H2"].product_selectivity_pct == pytest.approx(66.6666667)
    assert by_product["CO"].product_selectivity_pct == pytest.approx(33.3333333)


def test_calculate_coupled_product_results_rejects_duplicate_product_per_sample():
    inputs = [
        ProductQuantification("sample-a", "H2", product_moles=1.0e-6, electron_count=2, charge_coulomb=1.0),
        ProductQuantification("sample-a", "H2", product_moles=2.0e-6, electron_count=2, charge_coulomb=1.0),
    ]

    with pytest.raises(CoupledCalculationError):
        calculate_coupled_product_results(inputs)


def test_calculate_coupled_product_results_rejects_inconsistent_sample_charge():
    inputs = [
        ProductQuantification("sample-a", "H2", product_moles=1.0e-6, electron_count=2, charge_coulomb=1.0),
        ProductQuantification("sample-a", "CO", product_moles=1.0e-6, electron_count=2, charge_coulomb=2.0),
    ]

    with pytest.raises(CoupledCalculationError, match="inconsistent charge_coulomb"):
        calculate_coupled_product_results(inputs)


def test_coupled_results_to_processing_results_uses_metric_registry():
    calculated = calculate_coupled_product_results(
        [
            ProductQuantification(
                "sample-a",
                "H2",
                product_moles=2.0e-6,
                electron_count=2,
                charge_coulomb=1.0,
                metadata={"source_table": "products.csv"},
            )
        ]
    )

    normalized = coupled_results_to_processing_results(calculated, project_id="project-1", run_id="run-1")

    assert len(normalized) == 1
    result = normalized[0]
    assert result.data_type == "COUPLED"
    assert result.source is not None
    assert result.source.file_name == "H2"
    assert result.project_id == "project-1"
    metrics = {metric.key: metric for metric in result.metrics}
    assert metrics["faradaic_efficiency_pct"].unit == "%"
    assert metrics["faradaic_efficiency_pct"].metadata["definition_key"] == "coupled.faradaic_efficiency"
    assert metrics["faradaic_efficiency_pct"].metadata["product_name"] == "H2"
    assert metrics["faradaic_efficiency_pct"].metadata["formula_key"] == "coupled.faradaic_efficiency"
    assert "formula_key" not in metrics["charge_coulomb"].metadata
    assert "coupled.faradaic_efficiency" in result.metadata["formula_keys"]
    assert result.metadata["source_table"] == "products.csv"


def test_coupled_processing_result_marks_derived_charge_formula_only_when_used():
    calculated = calculate_coupled_product_results(
        [
            ProductQuantification(
                "sample-a",
                "H2",
                product_moles=1.0e-6,
                electron_count=2,
                charge_coulomb=0.6,
                metadata={"charge_source": "current_time"},
            )
        ]
    )

    normalized = coupled_results_to_processing_results(calculated)
    metrics = {metric.key: metric for metric in normalized[0].metrics}

    assert metrics["charge_coulomb"].metadata["formula_key"] == "coupled.charge_from_current_time"
