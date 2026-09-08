"""Independent circuit benchmarks and uncertainty/identifiability regressions."""

from __future__ import annotations

import json

import numpy as np
import pytest

from electrochem_v6.core.processing_eis_calc import (
    EIS_CIRCUIT_MODELS,
    eis_circuit_impedance,
    evaluate_eis_circuit_fit,
    fit_eis_circuit,
)

PARAMETERS = {
    "randles_rc": {"Rs": 7.0, "Rct": 80.0, "Cdl": 2e-5},
    "randles_cpe": {"Rs": 7.0, "Rct": 80.0, "Q": 3e-5, "n": 0.82},
    "randles_warburg_rc": {"Rs": 7.0, "Rct": 80.0, "Cdl": 2e-5, "sigma": 12.0},
    "randles_warburg_cpe": {"Rs": 7.0, "Rct": 80.0, "Q": 3e-5, "n": 0.82, "sigma": 12.0},
    "two_time_constants_rc": {"Rs": 7.0, "R1": 30.0, "C1": 1e-5, "R2": 100.0, "C2": 3e-3},
    "two_time_constants_cpe": {"Rs": 7.0, "R1": 30.0, "Q1": 3e-5, "n1": 0.9, "R2": 100.0, "Q2": 2e-3, "n2": 0.75},
}


def analytic_spectrum(frequency, model, parameters):
    """An independent admittance/Euler-form oracle, not production forward helpers."""
    omega = 2 * np.pi * np.asarray(frequency)
    z = np.full(len(omega), parameters["Rs"], dtype=complex)
    double = model.startswith("two_")
    for suffix in ["1", "2"] if double else [""]:
        resistance = parameters["R" + suffix] if double else parameters["Rct"]
        if model.endswith("cpe"):
            n = parameters["n" + suffix]
            y_c = parameters["Q" + suffix] * omega**n * (np.cos(n * np.pi / 2) + 1j * np.sin(n * np.pi / 2))
        else:
            y_c = 1j * omega * parameters["C" + suffix if double else "Cdl"]
        z_f = np.full(len(omega), resistance, dtype=complex)
        if "warburg" in model:
            z_f += parameters["sigma"] * np.sqrt(1 / omega) * (1 - 1j)
        z += 1 / (y_c + 1 / z_f)
    return z


@pytest.mark.parametrize("weighting", ["uniform", "modulus"])
@pytest.mark.parametrize("model", list(PARAMETERS))
def test_independent_analytic_spectra_recover_all_six_circuits(model, weighting):
    f = np.logspace(-3, 6, 100)
    truth = PARAMETERS[model]
    z = analytic_spectrum(f, model, truth)
    result = evaluate_eis_circuit_fit(f, z.real, z.imag, model=model, weighting=weighting, min_r2=0.999)
    assert result["numerical_converged"] is True
    assert result["accepted"] is True
    assert result["parameters"] == pytest.approx(truth, rel=1e-5, abs=1e-12)
    assert result["normalized_rmse"] < 1e-8
    assert set(result["parameter_units"]) == set(truth) == set(result["parameter_ci95"])
    assert result["parameter_order"] == list(EIS_CIRCUIT_MODELS[model]["parameters"])
    assert result["optimizer"]["max_starts"] <= 10
    assert result["optimizer"]["total_nfev"] <= result["optimizer"]["max_starts"] * 800
    assert result["identifiability"]["jacobian_rank"] == len(truth)
    np.testing.assert_allclose(eis_circuit_impedance(f, truth, model=model), z, rtol=2e-14)
    json.dumps(result, allow_nan=False)
    if "warburg" in model:
        assert result["parameter_units"]["sigma"] == "Ohm*s^-0.5"
    if model.startswith("two_"):
        assert "Rct" not in result
        assert "Rct" not in result["parameters"]
        assert result["time_constants_s"]["tau1"] < result["time_constants_s"]["tau2"]


@pytest.mark.parametrize("model", list(PARAMETERS)[2:])
def test_seeded_relative_noise_new_models_recovers_parameters_and_local_intervals(model):
    f = np.logspace(-3, 6, 120)
    truth = PARAMETERS[model]
    z = analytic_spectrum(f, model, truth)
    rng = np.random.default_rng(1701)
    z_noisy = z + np.abs(z) * 0.001 * (rng.normal(size=len(f)) + 1j * rng.normal(size=len(f)))
    result = evaluate_eis_circuit_fit(f, z_noisy.real, z_noisy.imag, model=model, weighting="modulus")
    assert result["accepted"]
    assert result["parameters"] == pytest.approx(truth, rel=0.035)
    assert result["normalized_rmse"] < 0.003
    for name, expected in truth.items():
        ci = result["parameter_ci95"][name]
        assert ci["estimable"] and ci["reason"] is None
        assert ci["lower"] < result[name] < ci["upper"]
        # Four-SE check tests sensible scale without claiming simultaneous 95% coverage.
        assert abs(result[name] - expected) < 4 * ci["standard_error"]
    assert "empirical" in result["identifiability"]["ci_assumptions"]


def test_local_covariance_agrees_with_independent_finite_difference_information():
    from scipy.stats import t

    f = np.logspace(-2, 5, 90)
    p = PARAMETERS["randles_rc"]
    z = analytic_spectrum(f, "randles_rc", p)
    rng = np.random.default_rng(83)
    measured = z + 0.25 * (rng.normal(size=len(f)) + 1j * rng.normal(size=len(f)))
    result = fit_eis_circuit(f, measured.real, measured.imag)
    assert result is not None
    columns = []
    for name, value in result["parameters"].items():
        delta = max(abs(value) * 1e-5, 1e-12)
        left, right = dict(result["parameters"]), dict(result["parameters"])
        left[name] -= delta
        right[name] += delta
        column = (analytic_spectrum(f, "randles_rc", right) - analytic_spectrum(f, "randles_rc", left)) / (2 * delta)
        columns.append(np.r_[column.real, column.imag])
    jac = np.column_stack(columns)
    residual = measured - analytic_spectrum(f, "randles_rc", result["parameters"])
    dof = 2 * len(f) - 3
    covariance = np.linalg.inv(jac.T @ jac) * np.sum(np.abs(residual) ** 2) / dof
    for index, name in enumerate(result["parameters"]):
        interval = result["parameter_ci95"][name]
        se = np.sqrt(covariance[index, index])
        assert interval["standard_error"] == pytest.approx(se, rel=2e-5)
        assert interval["upper"] == pytest.approx(result[name] + t.ppf(0.975, dof) * se, rel=1e-7)


@pytest.mark.parametrize("model", ["two_time_constants_rc", "two_time_constants_cpe"])
def test_swapped_branches_sort_parameters_intervals_and_correlation_names(model):
    f = np.logspace(-3, 6, 100)
    p = dict(PARAMETERS[model])
    for letter in ["R", "Q", "n"] if model.endswith("cpe") else ["R", "C"]:
        p[letter + "1"], p[letter + "2"] = p[letter + "2"], p[letter + "1"]
    z = analytic_spectrum(f, model, p)
    rng = np.random.default_rng(52)
    noisy = z + 0.01 * (rng.normal(size=len(f)) + 1j * rng.normal(size=len(f)))
    result = fit_eis_circuit(f[::-1], noisy.real[::-1], noisy.imag[::-1], model=model)
    assert result is not None
    assert result["parameters"] == pytest.approx(PARAMETERS[model], rel=0.01)
    for name in p:
        ci = result["parameter_ci95"][name]
        assert ci["lower"] < result[name] < ci["upper"]
    for pair in result["identifiability"]["high_correlations"]:
        assert set(pair["parameters"]).issubset(p)
    np.testing.assert_allclose(result["residual_real_ohm"], noisy.real[::-1] - np.asarray(result["z_fit_real"]))
    np.testing.assert_allclose(result["residual_imag_ohm"], noisy.imag[::-1] - np.asarray(result["z_fit_imag"]))


@pytest.mark.parametrize("model", ["two_time_constants_rc", "two_time_constants_cpe"])
def test_single_relaxation_cannot_be_claimed_as_two_identifiable_branches(model):
    f = np.logspace(-3, 6, 80)
    z = 7 + 80 / (1 + 2j * np.pi * f * 0.01)
    result = evaluate_eis_circuit_fit(f, z.real, z.imag, model=model)
    assert result["accepted"] and result["numerical_converged"]
    assert result["status"] == "needs_review"
    assert result["identifiability"]["branches_indistinguishable"]
    assert "branches_indistinguishable" in result["review_reasons"]
    assert all(not ci["estimable"] and ci["lower"] is None and ci["reason"] for ci in result["parameter_ci95"].values())
    json.dumps(result, allow_nan=False)


def test_repeated_frequency_is_rank_deficient_even_when_optimizer_converges():
    f = np.full(15, 100.0)
    z = analytic_spectrum(f, "randles_cpe", PARAMETERS["randles_cpe"])
    result = fit_eis_circuit(f, z.real, z.imag, model="randles_cpe")
    assert result is not None and result["review_required"]
    assert result["identifiability"]["jacobian_rank"] <= 2
    assert "rank_deficient_jacobian" in result["review_reasons"]
    assert not any(ci["estimable"] for ci in result["parameter_ci95"].values())


def test_cpe_exponent_at_ideal_capacitor_boundary_does_not_get_interior_ci():
    f = np.logspace(-2, 5, 80)
    z = analytic_spectrum(f, "randles_rc", PARAMETERS["randles_rc"])
    result = evaluate_eis_circuit_fit(f, z.real, z.imag, model="randles_cpe")
    assert result["accepted"] and result["status"] == "needs_review"
    assert "n" in result["identifiability"]["boundary_parameters"]
    assert not result["parameter_ci95"]["n"]["estimable"]
    assert "parameter_at_bound" in result["parameter_ci95"]["n"]["reason"]


def test_modulus_weighting_improves_relative_fit_with_large_diffusion_tail_noise():
    f = np.logspace(-5, 5, 130)
    p = {"Rs": 7.0, "Rct": 80.0, "Cdl": 2e-5, "sigma": 100.0}
    z = analytic_spectrum(f, "randles_warburg_rc", p)
    rng = np.random.default_rng(913)
    measured = z + 0.025 * np.abs(z) * (rng.normal(size=len(f)) + 1j * rng.normal(size=len(f)))
    fits = {
        weight: fit_eis_circuit(f, measured.real, measured.imag, model="randles_warburg_rc", weighting=weight)
        for weight in ("uniform", "modulus")
    }
    errors = {}
    for weight, result in fits.items():
        assert result is not None
        fitted = np.asarray(result["z_fit_real"]) + 1j * np.asarray(result["z_fit_imag"])
        errors[weight] = float(np.mean(np.abs((fitted - z) / z) ** 2))
    assert errors["modulus"] < errors["uniform"] * 0.5


def test_modulus_zero_impedance_floor_and_payload_are_finite():
    f = np.logspace(-2, 5, 60)
    z = analytic_spectrum(f, "randles_rc", PARAMETERS["randles_rc"])
    z[0] = 0
    result = evaluate_eis_circuit_fit(f, z.real, z.imag, weighting="modulus")
    if result["numerical_converged"]:
        assert result["weighting_floor_ohm"] > 0
        assert np.isfinite(result["weighted_rmse"])
    json.dumps(result, allow_nan=False)


def test_multistart_is_deterministic_and_frequency_order_invariant():
    f = np.logspace(-3, 6, 85)
    z = analytic_spectrum(f, "two_time_constants_cpe", PARAMETERS["two_time_constants_cpe"])
    first = fit_eis_circuit(f, z.real, z.imag, model="two_time_constants_cpe")
    again = fit_eis_circuit(f, z.real, z.imag, model="two_time_constants_cpe")
    order = np.random.default_rng(33).permutation(len(f))
    shuffled = fit_eis_circuit(f[order], z.real[order], z.imag[order], model="two_time_constants_cpe")
    assert first is not None and again is not None and shuffled is not None
    assert first["parameters"] == again["parameters"] == shuffled["parameters"]
    assert first["optimizer"] == again["optimizer"]
    np.testing.assert_allclose(np.asarray(first["z_fit_real"])[order], shuffled["z_fit_real"])


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_cancel_exception_is_never_converted_to_failed_fit(error_type):
    f = np.logspace(-3, 6, 100)
    z = analytic_spectrum(f, "two_time_constants_cpe", PARAMETERS["two_time_constants_cpe"])
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 7:
            raise error_type("cancelled by caller")

    with pytest.raises(error_type, match="cancelled by caller"):
        evaluate_eis_circuit_fit(f, z.real, z.imag, model="two_time_constants_cpe", cancel_check=cancel)
    assert calls == 7


@pytest.mark.parametrize(
    "frequency, real, imaginary",
    [
        ([1, 2, 3], [1, 2, 3], [0, 0, 0]),
        ([1, 2, 3, 0], [1, 2, 3, 4], [0, 0, 0, 0]),
        ([1, 2, 3, 4], [1, 2, 3, np.nan], [0, 0, 0, 0]),
        ([1, 2, 3, 4], [1, 2, 3], [0, 0, 0, 0]),
        ([1, 2, 3, "bad"], [1, 2, 3, 4], [0, 0, 0, 0]),
        ([[1, 2, 3, 4]], [[1, 2, 3, 4]], [[0, 0, 0, 0]]),
    ],
)
def test_invalid_scientific_arrays_fail_explicitly(frequency, real, imaginary):
    result = evaluate_eis_circuit_fit(frequency, real, imaginary, model="two_time_constants_cpe")
    assert not result["numerical_converged"] and result["status"] == "fit_failed"
    assert result["rejection_reason"]


def test_unknown_model_or_weight_cannot_silently_fall_back():
    f = [1, 10, 100, 1000]
    with pytest.raises(ValueError, match="model"):
        fit_eis_circuit(f, f, f, model="unsupported")
    with pytest.raises(ValueError, match="weighting"):
        fit_eis_circuit(f, f, f, weighting="automatic")
    with pytest.raises(ValueError, match="model"):
        eis_circuit_impedance(f, {}, model="unsupported")


@pytest.mark.parametrize("model", list(PARAMETERS))
@pytest.mark.parametrize("factor", [1e-2, 1e3])
def test_impedance_rescaling_retains_resolved_circuit_across_orders_of_magnitude(model, factor):
    f = np.logspace(-3, 6, 90)
    p = {
        name: (
            value * factor
            if name.startswith("R") or name == "sigma"
            else value / factor
            if name.startswith(("C", "Q"))
            else value
        )
        for name, value in PARAMETERS[model].items()
    }
    z = analytic_spectrum(f, model, p)
    result = fit_eis_circuit(f, z.real, z.imag, model=model, weighting="modulus")
    assert result is not None
    assert result["parameters"] == pytest.approx(p, rel=1e-4, abs=1e-14)
    assert result["normalized_rmse"] < 1e-7
    for name, limits in result["parameter_bounds"].items():
        assert limits["lower"] <= result[name] <= limits["upper"]


def test_wrong_inductive_data_is_rejected_despite_numerical_convergence():
    f = np.logspace(-2, 4, 70)
    z = 8 + 2j * np.pi * f * 0.005
    result = evaluate_eis_circuit_fit(f, z.real, z.imag, min_r2=0.8)
    assert result["numerical_converged"]
    assert not result["accepted"] and result["status"] == "rejected"
    assert "complex R2 below" in result["rejection_reason"]
    assert result["acceptance_criterion"] == {"metric": "complex_r2", "minimum": 0.8}
    assert "does not validate" in result["acceptance_note"]


def test_optimizer_budget_exhaustion_is_not_reported_as_convergence(monkeypatch):
    from types import SimpleNamespace

    import scipy.optimize

    def exhausted(fun, x0, **kwargs):
        return SimpleNamespace(success=False, x=x0, cost=1.0, nfev=kwargs["max_nfev"])

    monkeypatch.setattr(scipy.optimize, "least_squares", exhausted)
    f = np.logspace(-3, 6, 60)
    z = analytic_spectrum(f, "randles_rc", PARAMETERS["randles_rc"])
    result = evaluate_eis_circuit_fit(f, z.real, z.imag)
    assert result["status"] == "fit_failed"
    assert not result["accepted"] and not result["numerical_converged"]


def test_circuit_outside_capacitance_safety_bound_reports_limit_not_precise_ci():
    f = np.logspace(-3, 6, 90)
    truth = {"Rs": 0.007, "R1": 0.03, "C1": 0.01, "R2": 0.1, "C2": 3.0}
    z = analytic_spectrum(f, "two_time_constants_rc", truth)
    result = evaluate_eis_circuit_fit(f, z.real, z.imag, model="two_time_constants_rc", weighting="modulus")
    assert result["numerical_converged"] and result["review_required"]
    assert "C2" in result["identifiability"]["boundary_parameters"]
    assert result["parameter_bounds"]["C2"]["upper"] == 1.0
    assert not result["parameter_ci95"]["C2"]["estimable"]


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_r2_threshold_is_rejected_before_fitting(threshold):
    f = np.logspace(-2, 5, 60)
    z = analytic_spectrum(f, "randles_rc", PARAMETERS["randles_rc"])
    with pytest.raises(ValueError, match="min_r2 must be finite"):
        evaluate_eis_circuit_fit(f, z.real, z.imag, min_r2=threshold)
