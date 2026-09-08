"""Reference spectra and failure boundaries for finite-band KK screening."""

from __future__ import annotations

import json

import numpy as np
import pytest

from electrochem_v6.core.processing_eis_validation import validate_eis_kk


def _spectrum(kind: str, count: int = 80) -> tuple[np.ndarray, np.ndarray]:
    frequency = np.logspace(-1, 5, count)
    omega = 2 * np.pi * frequency
    rc = 7 + 85 / (1 + 1j * omega * 85 * 1e-5)
    if kind == "rc":
        impedance = rc
    elif kind == "cpe":
        impedance = 7 + 1 / (1 / 85 + 3e-5 * (1j * omega) ** 0.82)
    elif kind == "semi_infinite_diffusion":
        impedance = rc + 20 / np.sqrt(1j * omega)
    elif kind == "finite_diffusion":
        diffusion_argument = np.sqrt(1j * omega * 0.7)
        # tanh(x+ix) is indistinguishable from 1 for large positive x;
        # using that limit avoids an irrelevant complex-tanh overflow warning.
        hyperbolic = np.ones_like(diffusion_argument)
        resolved = diffusion_argument.real < 20
        hyperbolic[resolved] = np.tanh(diffusion_argument[resolved])
        impedance = rc + 40 * hyperbolic / diffusion_argument
    else:
        raise AssertionError(kind)
    return frequency, impedance


@pytest.mark.parametrize("kind", ["rc", "cpe", "semi_infinite_diffusion", "finite_diffusion"])
def test_causal_reference_spectra_have_small_kk_residuals(kind):
    frequency, impedance = _spectrum(kind)
    result = validate_eis_kk(frequency, impedance.real, impedance.imag)

    assert result["status"] == "consistent", result
    assert result["normalized_rms"] <= result["thresholds"]["normalized_rms_max"]
    assert result["max_residual"] <= result["thresholds"]["max_residual_max"]
    assert 3 <= result["order"] <= 30
    assert len(result["frequency_hz"]) == len(frequency)
    predicted = np.array(result["z_fit_real"]) + 1j * np.array(result["z_fit_imag"])
    expected_residual = (impedance - predicted) / abs(impedance)
    assert result["residual_real"] == pytest.approx(expected_residual.real)
    assert result["residual_imag"] == pytest.approx(expected_residual.imag)
    assert "does not prove a physical circuit" in " ".join(result["limitations"])
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("damage", ["oscillating_imaginary", "reversed_imaginary_sign", "single_corrupted_point"])
def test_inconsistent_measurements_request_review(damage):
    frequency, impedance = _spectrum("rc")
    if damage == "oscillating_imaginary":
        impedance = impedance.real + 1j * impedance.imag * (1 + 0.6 * np.sin(np.linspace(0, 10 * np.pi, len(frequency))))
    elif damage == "reversed_imaginary_sign":
        impedance = impedance.conjugate()
    else:
        impedance[len(frequency) // 2] += 70j
    result = validate_eis_kk(frequency, impedance.real, impedance.imag)

    assert result["status"] == "review"
    assert result["reason"] == "residuals_exceed_heuristic_limits"
    assert result["normalized_rms"] > 0.02 or result["max_residual"] > 0.05
    json.dumps(result, allow_nan=False)


def test_input_order_frequency_scaling_and_impedance_units_do_not_change_diagnosis():
    frequency, impedance = _spectrum("cpe")
    expected = validate_eis_kk(frequency, impedance.real, impedance.imag)
    shuffled = np.random.default_rng(37).permutation(len(frequency))
    for scale in (1e-9, 1e3, 1e9):
        actual = validate_eis_kk(frequency[shuffled] * 1000, impedance.real[shuffled] * scale, impedance.imag[shuffled] * scale)
        assert actual["status"] == expected["status"]
        assert actual["order"] == expected["order"]
        assert actual["normalized_rms"] == pytest.approx(expected["normalized_rms"], abs=1e-10)
        assert actual["frequency_hz"] == pytest.approx(frequency[shuffled] * 1000)
        assert actual["residual_real"] == pytest.approx(np.array(expected["residual_real"])[shuffled], abs=1e-10)
        assert actual["z_fit_imag"] == pytest.approx(np.array(expected["z_fit_imag"])[shuffled] * scale, rel=1e-9)


@pytest.mark.parametrize(
    ("frequency", "real", "imag", "reason"),
    [
        ([], [], [], "insufficient_unique_frequencies"),
        ([1, 10, 100], [1, 2, 3], [-1, -2, -1], "insufficient_unique_frequencies"),
        (np.ones(20), np.arange(20), -np.ones(20), "insufficient_unique_frequencies"),
        (np.logspace(1, 1.2, 20), np.arange(20), -np.ones(20), "frequency_band_too_narrow"),
        (np.logspace(-1, 5, 20), np.ones(20), -np.ones(20), "constant_impedance"),
        (np.logspace(-1, 5, 20), np.zeros(20), np.zeros(20), "constant_impedance"),
        (np.logspace(-1, 5, 20), 1 + np.arange(20) * 1e-16, -np.ones(20), "constant_impedance"),
        ([-1, 1, 10], [1, 2, 3], [-1, -2, -1], "non_positive_frequency"),
        ([0, 1, 10], [1, 2, 3], [-1, -2, -1], "non_positive_frequency"),
        ([1, float("nan"), 10], [1, 2, 3], [-1, -2, -1], "non_finite_input"),
        ([1, 2, 10], [1, float("inf"), 3], [-1, -2, -1], "non_finite_input"),
        ([1, 2], [1, 2, 3], [-1, -2, -1], "mismatched_or_non_vector_input"),
        ([[1, 2]], [1, 2], [-1, -2], "mismatched_or_non_vector_input"),
        (["bad"], [1], [-1], "invalid_input"),
        (np.logspace(-10, 10, 30), np.arange(30), -np.ones(30), "frequency_span_exceeds_resolution_limit"),
    ],
)
def test_unassessable_input_has_explicit_json_safe_reason(frequency, real, imag, reason):
    result = validate_eis_kk(frequency, real, imag)

    assert result["status"] == "unavailable"
    assert result["reason"] == reason
    assert result["order"] is None
    assert result["normalized_rms"] is None
    assert result["residual_real"] == []
    json.dumps(result, allow_nan=False)


def test_bounded_sampling_keeps_every_point_in_final_residual_check():
    frequency, impedance = _spectrum("cpe", count=1201)
    normal = validate_eis_kk(frequency, impedance.real, impedance.imag)
    assert normal["status"] == "consistent"
    selected = normal["selection"]["fit_indices"]
    assert len(selected) == 600
    assert selected[0] == 0 and selected[-1] == 1200
    skipped = sorted(set(range(len(frequency))) - set(selected))
    outlier_index = skipped[len(skipped) // 2]
    impedance[outlier_index] += 100j
    damaged = validate_eis_kk(frequency, impedance.real, impedance.imag)

    assert damaged["status"] == "review"
    assert damaged["selection"]["fit_indices"] == selected
    assert damaged["selection"]["residual_evaluation_points"] == len(frequency)
    assert len(damaged["residual_real"]) == len(frequency)
    assert abs(complex(damaged["residual_real"][outlier_index], damaged["residual_imag"][outlier_index])) > 0.05


def test_repeated_measurements_are_not_averaged_away_or_counted_as_unique():
    frequency, impedance = _spectrum("rc")
    repeated_frequency = np.repeat(frequency, 2)
    repeated_impedance = np.repeat(impedance, 2)
    repeated_impedance[41] += 100j
    result = validate_eis_kk(repeated_frequency, repeated_impedance.real, repeated_impedance.imag)

    assert result["status"] == "review"
    assert result["unique_frequencies"] == len(frequency)
    assert len(result["residual_real"]) == 2 * len(frequency)
    assert result["selection"]["maximum_order"] <= len(frequency) // 2


def test_solver_work_is_bounded_and_threshold_results_are_independent(monkeypatch):
    frequency, impedance = _spectrum("cpe", count=601)
    original = np.linalg.lstsq
    shapes = []

    def observed(matrix, target, **kwargs):
        shapes.append(matrix.shape)
        return original(matrix, target, **kwargs)

    monkeypatch.setattr(np.linalg, "lstsq", observed)
    result = validate_eis_kk(frequency, impedance.real, impedance.imag)
    assert result["status"] == "consistent"
    assert 1 <= len(shapes) <= 28
    assert all(rows <= 1200 and columns <= 33 for rows, columns in shapes)
    result["thresholds"]["mu_min"] = 0
    assert validate_eis_kk(frequency, impedance.real, impedance.imag)["thresholds"]["mu_min"] == 0.85
    oversized = validate_eis_kk(np.ones(20001), np.ones(20001), np.ones(20001))
    assert oversized["status"] == "unavailable"
    assert oversized["reason"] == "input_point_limit_exceeded"
