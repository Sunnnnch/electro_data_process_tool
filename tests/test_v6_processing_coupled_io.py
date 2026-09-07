from __future__ import annotations

import pandas as pd
import pytest

from electrochem_v6.core.processing_coupled_calc import (
    calculate_coupled_product_results,
    coupled_results_to_processing_results,
)
from electrochem_v6.core.processing_coupled_io import (
    normalize_table_column_name,
    product_quantifications_from_dataframe,
    read_product_quantification_table,
)
from electrochem_v6.core.processing_coupled_models import CoupledCalculationError


def test_normalize_table_column_name_strips_units_and_punctuation():
    assert normalize_table_column_name("Sample Name") == "sample_name"
    assert normalize_table_column_name("Product Moles (mol)") == "product_moles"
    assert normalize_table_column_name("Charge (C)") == "charge"


@pytest.mark.parametrize("unit, scale", [("mol", 1), ("mmol", 1e-3), ("µmol", 1e-6), ("μmol", 1e-6), ("nmol", 1e-9)])
def test_product_table_normalizes_explicit_amount_and_charge_units(unit, scale):
    rows = product_quantifications_from_dataframe(pd.DataFrame([
        {"sample": "A", "product": "H2", f"Product Moles ({unit})": 2, "n": 2, "Charge [mC]": 1000}
    ]))
    assert rows[0].product_moles == pytest.approx(2 * scale)
    assert rows[0].charge_coulomb == pytest.approx(1)


def test_product_table_normalizes_declared_current_and_time_units():
    rows = product_quantifications_from_dataframe(pd.DataFrame([
        {"sample": "A", "product": "H2", "product_moles": 1e-6, "n": 2, "Current (mA)": -10, "Time (min)": 2}
    ]))
    assert rows[0].charge_coulomb == pytest.approx(1.2)
    assert rows[0].metadata["current_ampere"] == pytest.approx(-0.01)
    assert rows[0].metadata["electrolysis_time_s"] == pytest.approx(120)


@pytest.mark.parametrize("column, error", [
    ("Product Moles (mg)", "unsupported unit"),
    ("Product Moles (mmol) [mol]", "conflicting units"),
    ("amount_mol (mmol)", "conflicting unit suffix"),
])
def test_product_table_rejects_invalid_or_conflicting_amount_units(column, error):
    with pytest.raises(CoupledCalculationError, match=error):
        product_quantifications_from_dataframe(pd.DataFrame([
            {"sample": "A", "product": "H2", column: 1, "n": 2, "charge": 1}
        ]))


@pytest.mark.parametrize("fields", [
    {"Product Moles (mol)": 1e-6, "Product Moles (mmol)": 1e-3, "charge": 1},
    {"product_moles": 1e-6, "moles": 1e-6, "charge": 1},
    {"product_moles": 1e-6, "current_A": 0.01, "current_mA": 10, "time_s": 100},
    {"product_moles": 1e-6, "current_A": 0.01, "time_s": 100, "time_min": 2},
])
def test_product_table_rejects_competing_columns(fields):
    with pytest.raises(CoupledCalculationError, match="ambiguous"):
        product_quantifications_from_dataframe(pd.DataFrame([{"sample": "A", "product": "H2", "n": 2, **fields}]))


@pytest.mark.parametrize("fields", [
    {"charge_coulomb (mC)": 1000},
    {"current_mA (A)": 0.01, "time_s": 100},
    {"current_mA": 10, "time_s (min)": 2},
])
def test_product_table_rejects_unit_suffix_conflicts(fields):
    with pytest.raises(CoupledCalculationError, match="conflicting unit suffix"):
        product_quantifications_from_dataframe(pd.DataFrame([
            {"sample": "A", "product": "H2", "product_moles": 1e-6, "n": 2, **fields}
        ]))


@pytest.mark.parametrize("fields, error", [
    ({"Charge (Ah)": 1}, "unsupported unit"),
    ({"Current (mV)": 10, "Time (s)": 100}, "unsupported unit"),
    ({"Current (A)": 1, "Time (h)": 1e308}, "must be finite"),
])
def test_product_table_rejects_unsupported_dimensions_and_conversion_overflow(fields, error):
    with pytest.raises(CoupledCalculationError, match=error):
        product_quantifications_from_dataframe(pd.DataFrame([
            {"sample": "A", "product": "H2", "product_moles": 1e-6, "n": 2, **fields}
        ]))


def test_product_quantifications_from_dataframe_accepts_aliases_and_metadata():
    df = pd.DataFrame(
        [
            {
                "sample": "sample-a",
                "product": "H2",
                "product_moles": 1.2e-6,
                "n": 2,
                "Charge (C)": 0.8,
                "detector": "GC",
            },
            {
                "sample": "",
                "product": "",
                "product_moles": None,
                "n": None,
                "Charge (C)": None,
                "detector": None,
            },
        ]
    )

    rows = product_quantifications_from_dataframe(df, source_path="products.csv")

    assert len(rows) == 1
    row = rows[0]
    assert row.sample_name == "sample-a"
    assert row.product_name == "H2"
    assert row.product_moles == pytest.approx(1.2e-6)
    assert row.electron_count == pytest.approx(2)
    assert row.charge_coulomb == pytest.approx(0.8)
    assert row.metadata["source_table"] == "products.csv"
    assert row.metadata["source_row"] == 2
    assert row.metadata["detector"] == "GC"


def test_product_quantifications_from_dataframe_derives_charge_from_current_time():
    df = pd.DataFrame(
        [
            {
                "sample": "sample-a",
                "product": "H2",
                "product_moles": 1.2e-6,
                "n": 2,
                "current_mA": -10.0,
                "time_s": 150,
            },
        ]
    )

    rows = product_quantifications_from_dataframe(df)

    assert len(rows) == 1
    assert rows[0].charge_coulomb == pytest.approx(1.5)
    assert rows[0].metadata["charge_source"] == "current_time"
    assert rows[0].metadata["current_ampere"] == pytest.approx(-0.01)
    assert rows[0].metadata["electrolysis_time_s"] == pytest.approx(150)


def test_product_quantifications_from_dataframe_requires_core_columns():
    df = pd.DataFrame([{"sample": "sample-a", "product": "H2"}])

    with pytest.raises(CoupledCalculationError, match="missing required"):
        product_quantifications_from_dataframe(df)


def test_product_quantifications_from_dataframe_requires_charge_or_current_time():
    df = pd.DataFrame(
        [
            {
                "sample_name": "sample-a",
                "product_name": "H2",
                "product_moles": 1.0e-6,
                "electron_count": 2,
                "current_mA": 10.0,
            }
        ]
    )

    with pytest.raises(CoupledCalculationError, match="charge_coulomb or current/time"):
        product_quantifications_from_dataframe(df)


def test_product_quantifications_from_dataframe_reports_bad_numeric_row():
    df = pd.DataFrame(
        [
            {
                "sample_name": "sample-a",
                "product_name": "H2",
                "product_moles": "bad",
                "electron_count": 2,
                "charge_coulomb": 1.0,
            }
        ]
    )

    with pytest.raises(CoupledCalculationError, match="row 2: product_moles must be numeric"):
        product_quantifications_from_dataframe(df)


def test_read_product_quantification_table_reads_csv(tmp_path):
    path = tmp_path / "products.csv"
    path.write_text(
        "sample_name,product_name,product_moles,electron_count,charge_coulomb\n"
        "sample-a,H2,0.000001,2,1.0\n",
        encoding="utf-8",
    )

    rows = read_product_quantification_table(path)

    assert len(rows) == 1
    assert rows[0].sample_name == "sample-a"
    assert rows[0].metadata["source_table"] == str(path)


def test_read_product_quantification_table_reads_excel(tmp_path):
    path = tmp_path / "products.xlsx"
    pd.DataFrame(
        [
            {
                "sample_name": "sample-a",
                "product_name": "CO",
                "product_moles": 2.0e-6,
                "electron_count": 2,
                "charge_coulomb": 1.5,
            }
        ]
    ).to_excel(path, index=False)

    rows = read_product_quantification_table(path)

    assert len(rows) == 1
    assert rows[0].product_name == "CO"


def test_read_table_then_calculate_and_convert_to_processing_results(tmp_path):
    path = tmp_path / "products.csv"
    path.write_text(
        "sample,product,product_moles,n,charge\n"
        "sample-a,H2,0.000002,2,1.0\n"
        "sample-a,CO,0.000001,2,1.0\n",
        encoding="utf-8",
    )

    quantified = read_product_quantification_table(path)
    calculated = calculate_coupled_product_results(quantified)
    normalized = coupled_results_to_processing_results(calculated)

    assert len(normalized) == 2
    h2_result = next(item for item in normalized if item.source and item.source.file_name == "H2")
    metrics = {metric.key: metric for metric in h2_result.metrics}
    assert metrics["product_selectivity_pct"].value == pytest.approx(66.6666667)
    assert metrics["faradaic_efficiency_pct"].metadata["definition_key"] == "coupled.faradaic_efficiency"


def test_read_table_derives_charge_then_calculates_fe(tmp_path):
    path = tmp_path / "products.csv"
    path.write_text(
        "sample,product,product_moles,n,current_mA,time_min\n"
        "sample-a,H2,0.000002,2,10,2\n",
        encoding="utf-8",
    )

    quantified = read_product_quantification_table(path)
    calculated = calculate_coupled_product_results(quantified)

    assert quantified[0].charge_coulomb == pytest.approx(1.2)
    assert calculated[0].faradaic_efficiency_pct == pytest.approx(2 * 96485.33212 * 0.000002 / 1.2 * 100.0)
