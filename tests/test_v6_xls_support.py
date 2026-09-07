"""Read a genuine BIFF8 workbook and calculate the expected product results."""

from pathlib import Path

import pytest

from electrochem_v6.core.processing_coupled_calc import calculate_coupled_product_results
from electrochem_v6.core.processing_coupled_io import read_product_quantification_table


def test_legacy_xls_product_table_keeps_values_units_and_fe():
    source = Path(__file__).parent / "fixtures" / "coupled" / "products.xls"
    inputs = read_product_quantification_table(source, sheet_name="Products")
    assert len(inputs) == 2
    assert inputs[0].sample_name == "sample-a"
    assert inputs[0].product_moles == pytest.approx(2e-6)
    assert inputs[0].charge_coulomb == 1
    results = calculate_coupled_product_results(inputs)
    h2 = next(result for result in results if result.product_name == "H2")
    assert h2.faradaic_efficiency_pct == pytest.approx(38.594132848)
    assert h2.product_selectivity_pct == pytest.approx(200 / 3)
