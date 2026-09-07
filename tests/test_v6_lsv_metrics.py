"""Tests for focused LSV metric helpers."""

from __future__ import annotations

import numpy as np
import pytest

from electrochem_v6.core.processing_lsv_metrics import (
    LsvOptionalMetrics,
    build_lsv_result_columns,
    build_lsv_result_row,
    compute_halfwave_potential,
    compute_optional_metrics,
    compute_overpotentials,
    compute_tafel_slope_mVdec,
    compute_target_potentials,
    parse_float_param,
)


def test_parse_float_param_uses_default_for_invalid_values():
    assert parse_float_param("1.23", 0.0) == pytest.approx(1.23)
    assert parse_float_param("bad", 0.42) == pytest.approx(0.42)


def test_compute_target_potentials_keeps_valid_targets_only():
    potential = np.linspace(0.0, 1.0, 101)
    current = 20.0 * potential

    result = compute_target_potentials(potential, current, [10.0, 80.0])

    assert result.potentials[10.0] == pytest.approx(0.5)
    assert 80.0 not in result.potentials


def test_compute_overpotentials_returns_absolute_millivolts():
    result = compute_overpotentials({10.0: 0.82, 50.0: 1.18}, equilibrium_potential=1.0)

    assert result[10.0] == pytest.approx(180.0)
    assert result[50.0] == pytest.approx(180.0)


def test_compute_halfwave_potential_uses_95th_percentile_when_target_is_blank():
    potential = np.linspace(0.0, 1.0, 101)
    current = 20.0 * potential

    result = compute_halfwave_potential(potential, current, "")

    assert result == pytest.approx(0.475)


def test_compute_optional_metrics_calculates_enabled_metrics():
    potential = np.linspace(0.0, 1.0, 101)
    current = 20.0 * potential

    metrics = compute_optional_metrics(
        params={
            "onset_enabled": True,
            "onset_current": "10",
            "halfwave_enabled": True,
            "halfwave_current": "5",
            "tafel_enabled": False,
        },
        potential=potential,
        current=current,
        equilibrium_potential=0.1,
        overpotential_enabled=True,
    )

    assert metrics.onset_potential == pytest.approx(0.5)
    assert metrics.onset_overpotential_mV == pytest.approx(400.0)
    assert metrics.halfwave_potential == pytest.approx(0.25)
    assert metrics.tafel_slope_mVdec is None


def test_compute_tafel_slope_returns_millivolts_per_decade():
    current = np.logspace(0.0, 2.0, 80)
    potential = 0.2 + 0.12 * np.log10(current)

    slope = compute_tafel_slope_mVdec(potential, current, "1-100")

    assert slope == pytest.approx(120.0)


def test_build_lsv_result_row_preserves_configured_column_slots():
    row = build_lsv_result_row(
        sample_name="sample-a",
        file_stem="LSV_001",
        target_currents=[10.0, 50.0],
        target_potentials_original={10.0: 0.5},
        target_potentials_compensated={10.0: 0.45},
        ir_compensation=5.0,
        ir_columns_enabled=True,
        target_overpotentials_original={10.0: 400.0},
        overpotential_enabled=True,
        optional_metrics=LsvOptionalMetrics(
            onset_potential=0.2,
            onset_overpotential_mV=800.0,
            halfwave_potential=None,
            tafel_slope_mVdec=120.0,
        ),
        onset_enabled=True,
        halfwave_enabled=True,
        tafel_enabled=True,
    )

    assert row == [
        "sample-a",
        "LSV_001",
        0.5,
        None,
        0.45,
        None,
        5.0,
        400.0,
        None,
        0.2,
        800.0,
        None,
        120.0,
    ]


def test_build_lsv_result_columns_matches_row_order_for_multiple_ir_targets():
    columns = build_lsv_result_columns(
        {
            "target_current": "10,50",
            "ir_compensation_enabled": True,
            "overpotential_enabled": True,
            "eq_potential": 1.23,
            "onset_enabled": True,
            "onset_current": "1.0",
            "halfwave_enabled": True,
            "tafel_enabled": True,
        }
    )

    assert columns == [
        "Sample_Name",
        "File_Name",
        "Potential@10.0mA/cm2(Original)",
        "Potential@50.0mA/cm2(Original)",
        "Potential@10.0mA/cm2(IR_compensated)",
        "Potential@50.0mA/cm2(IR_compensated)",
        "R_solution(Ohm)",
        "Overpotential@10.0mA/cm2(mV)@Eq=1.23V",
        "Overpotential@50.0mA/cm2(mV)@Eq=1.23V",
        "OnsetPotential@1.0mA/cm2(V)",
        "OnsetOverpotential(mV)@Eq=1.23V",
        "HalfWavePotential(V)",
        "TafelSlope(mV/dec)",
    ]
