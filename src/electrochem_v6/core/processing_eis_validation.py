"""Bounded, finite-band linear Kramers--Kronig screening for EIS spectra.

This is an independent matrix implementation of the RC expansion described in
Schönleber et al., Electrochimica Acta 131 (2014), 20--27,
https://doi.org/10.1016/j.electacta.2014.01.034. The public impedance.py reference
implementation and its MIT licence were consulted:
https://impedancepy.readthedocs.io/en/latest/_modules/impedance/validation.html
https://github.com/ECSHackWeek/impedance.py/blob/main/LICENSE
No impedance.py code or dependency is incorporated here.

The RC time constants are fixed on a logarithmic grid. Series resistance,
inductance and inverse capacitance are additional linear basis terms. Signed
coefficients are intentional: this is a consistency expansion, not an identified
physical circuit. Unlike stopping at the first low mu, bounded order selection
requires small residuals as well; a coarse, under-resolved grid can also have low
mu. All thresholds are explicitly heuristic, not statistical confidence limits.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

_THRESHOLDS = {
    "normalized_rms_max": 0.02,
    "max_residual_max": 0.05,
    "mu_min": 0.85,
    "minimum_unique_frequencies": 10,
    "minimum_frequency_span_decades": 2.0,
    "maximum_frequency_span_decades": 12.0,
    "maximum_input_points": 20000,
    "maximum_fit_points": 600,
    "maximum_rc_order": 30,
    "relative_modulus_floor": 1e-12,
    "maximum_scaled_condition_number": 1e12,
}
_LIMITATIONS = (
    "A consistent result supports finite-band KK consistency; it does not prove a physical circuit, "
    "linearity, causality or stationarity independently.",
    "The residual and mu thresholds are screening heuristics, not confidence intervals or universal acceptance limits.",
    "Finite bandwidth, noise, edge effects and insufficient relaxation-time resolution can require review "
    "even for KK-consistent data.",
    "RC expansion coefficients, including signed weights and the series L/C terms, are diagnostic basis "
    "coefficients and must not be reported as identified circuit parameters.",
)


def _empty_result() -> dict[str, Any]:
    return {
        "method": "lin_kk",
        "method_version": 1,
        "status": "unavailable",
        "reason": "invalid_input",
        "order": None,
        "mu": None,
        "frequency_hz": [],
        "z_fit_real": [],
        "z_fit_imag": [],
        "residual_real": [],
        "residual_imag": [],
        "normalized_rms": None,
        "max_residual": None,
        "data_points": 0,
        "unique_frequencies": 0,
        "frequency_span_decades": None,
        "thresholds": {**_THRESHOLDS, "kind": "heuristic"},
        "selection": {},
        "notes": [],
        "limitations": list(_LIMITATIONS),
        "method_description": "Modulus-weighted complex linear least squares of R0 + sum[Rk/(1+j*omega*tau_k)] "
        "+ j*omega*L + 1/(j*omega*C), with log-spaced fixed tau_k spanning the measured frequency band. "
        "Choose the smallest bounded order meeting residual and RC-mass heuristics; otherwise retain the minimum-RMS fit for review.",
        "reference": "Schönleber et al. (2014), doi:10.1016/j.electacta.2014.01.034",
        "residual_definition": "(Z_measured - Z_KK) / max(|Z_measured|, relative_modulus_floor * impedance_scale)",
        "rms_definition": "sqrt(mean(residual_real**2 + residual_imag**2)) over every supplied point",
    }


def kk_validation_metadata() -> dict[str, Any]:
    """Return independent method metadata for saved calculation snapshots."""
    description = _empty_result()
    return {key: description[key] for key in (
        "method", "method_version", "method_description", "thresholds", "limitations",
        "reference", "residual_definition", "rms_definition",
    )}


def _basis(log_frequency: NDArray[np.float64], low: float, high: float, order: int) -> NDArray[np.complex128]:
    # Scaling L and inverse C by the band edges avoids mixing huge/small SI
    # columns. The fitted subspace is unchanged by these column scalings.
    characteristic_logs = np.linspace(high, low, order)
    omega_tau = np.exp(log_frequency[:, None] - characteristic_logs[None, :])
    return np.column_stack(
        (
            np.ones(len(log_frequency), dtype=np.complex128),
            1.0 / (1.0 + 1j * omega_tau),
            1j * np.exp(log_frequency - high),
            -1j * np.exp(low - log_frequency),
        )
    )


def _residual_summary(residual: NDArray[np.complex128]) -> tuple[float, float]:
    magnitudes = np.abs(residual)
    return float(np.sqrt(np.mean(magnitudes**2))), float(np.max(magnitudes))


def _residuals_within_limits(rms: float, maximum: float) -> bool:
    return rms <= _THRESHOLDS["normalized_rms_max"] and maximum <= _THRESHOLDS["max_residual_max"]


def _fit_order(
    log_f: NDArray[np.float64], z: NDArray[np.complex128], modulus: NDArray[np.float64], order: int
) -> dict[str, Any] | None:
    basis = _basis(log_f, float(log_f.min()), float(log_f.max()), order)
    weighted = basis / modulus[:, None]
    matrix = np.vstack((weighted.real, weighted.imag))
    target = np.concatenate((z.real / modulus, z.imag / modulus))
    column_scale = np.linalg.norm(matrix, axis=0)
    try:
        scaled_coefficients, _, rank, singular_values = np.linalg.lstsq(
            matrix / column_scale, target, rcond=1e-12
        )
    except np.linalg.LinAlgError:
        return None
    if rank != matrix.shape[1] or not np.all(np.isfinite(scaled_coefficients)):
        return None
    condition = float(singular_values[0] / singular_values[-1])
    if condition > _THRESHOLDS["maximum_scaled_condition_number"]:
        return None
    coefficients = scaled_coefficients / column_scale
    residual = (z - basis @ coefficients) / modulus
    if not np.all(np.isfinite(residual)):
        return None
    rms, maximum = _residual_summary(residual)
    weights = coefficients[1 : order + 1]
    positive_mass = float(np.sum(weights[weights > 0]))
    negative_mass = float(-np.sum(weights[weights < 0]))
    # A pure series C or L can have effectively zero RC mass. Mu is undefined
    # there, rather than a numerical division being evidence against the data.
    negligible_mass = positive_mass + negative_mass <= 1e-10
    mu = 1.0 - negative_mass / positive_mass if positive_mass > 1e-14 and not negligible_mass else None
    stable_mass = negligible_mass or (mu is not None and mu >= _THRESHOLDS["mu_min"])
    return {
        "order": order,
        "coefficients": coefficients,
        "mu": mu,
        "stable_mass": stable_mass,
        "normalized_rms": rms,
        "max_residual": maximum,
        "condition_number": condition,
    }


def validate_eis_kk(freq, z_real, z_imag) -> dict[str, Any]:
    """Return JSON-safe KK screening diagnostics without modifying input data.

    Frequencies are Hz and impedance components share a consistent unit. Returned
    curves and residuals retain the caller's order, including duplicate points.
    Large spectra are deterministically subsampled for fitting only; every point
    still contributes to the final residual criteria.
    """
    result = _empty_result()
    try:
        frequency = np.asarray(freq, dtype=float)
        real = np.asarray(z_real, dtype=float)
        imag = np.asarray(z_imag, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return result
    if frequency.ndim != 1 or real.ndim != 1 or imag.ndim != 1 or not (frequency.size == real.size == imag.size):
        result["reason"] = "mismatched_or_non_vector_input"
        return result
    count = int(frequency.size)
    result["data_points"] = count
    if count > _THRESHOLDS["maximum_input_points"]:
        result["reason"] = "input_point_limit_exceeded"
        return result
    if not (np.all(np.isfinite(frequency)) and np.all(np.isfinite(real)) and np.all(np.isfinite(imag))):
        result["reason"] = "non_finite_input"
        return result
    if np.any(frequency <= 0):
        result["reason"] = "non_positive_frequency"
        return result
    unique_count = int(np.unique(frequency).size)
    result["unique_frequencies"] = unique_count
    if unique_count < _THRESHOLDS["minimum_unique_frequencies"]:
        result["reason"] = "insufficient_unique_frequencies"
        return result
    log_frequency = np.log(frequency)
    low, high = float(log_frequency.min()), float(log_frequency.max())
    decades = (high - low) / np.log(10.0)
    result["frequency_span_decades"] = float(decades)
    if decades < _THRESHOLDS["minimum_frequency_span_decades"] - 1e-12:
        result["reason"] = "frequency_band_too_narrow"
        return result
    if decades > _THRESHOLDS["maximum_frequency_span_decades"] + 1e-12:
        result["reason"] = "frequency_span_exceeds_resolution_limit"
        return result
    impedance_scale = max(float(np.max(np.abs(real))), float(np.max(np.abs(imag))))
    if impedance_scale == 0:
        result["reason"] = "constant_impedance"
        return result
    z = real / impedance_scale + 1j * (imag / impedance_scale)
    if float(np.max(np.abs(z - z[0]))) <= 64.0 * np.finfo(float).eps:
        result["reason"] = "constant_impedance"
        return result
    modulus = np.maximum(np.abs(z), _THRESHOLDS["relative_modulus_floor"])
    guarded_count = int(np.count_nonzero(np.abs(z) < _THRESHOLDS["relative_modulus_floor"]))
    if guarded_count:
        result["notes"].append(f"The relative modulus floor was used at {guarded_count} near-zero impedance points.")

    # Tie ordering by measured values makes deterministic subsampling invariant
    # to input order even when frequencies are repeated with different readings.
    sorted_indices = np.lexsort((imag, real, frequency))
    fit_count = min(count, int(_THRESHOLDS["maximum_fit_points"]))
    selected_ranks = np.linspace(0, count - 1, fit_count, dtype=int)
    fit_indices = sorted_indices[selected_ranks]
    fit_logs, fit_z, fit_modulus = log_frequency[fit_indices], z[fit_indices], modulus[fit_indices]
    fit_unique_count = int(np.unique(frequency[fit_indices]).size)
    maximum_order = min(int(_THRESHOLDS["maximum_rc_order"]), fit_unique_count // 2)
    selection = {
        "strategy": "smallest_order_with_small_residuals_and_stable_rc_mass_else_minimum_rms",
        "subsampling": "frequency_sorted_even_index_with_endpoints; ties sorted by real then imaginary impedance",
        "input_points": count,
        "fit_points": fit_count,
        "fit_unique_frequencies": fit_unique_count,
        "fit_indices": fit_indices.tolist(),
        "subsampled": fit_count < count,
        "residual_evaluation_points": count,
        "maximum_order": maximum_order,
        "candidates": [],
    }
    result["selection"] = selection
    if fit_unique_count < _THRESHOLDS["minimum_unique_frequencies"]:
        result["reason"] = "insufficient_unique_frequencies_after_bounded_sampling"
        return result
    best: dict[str, Any] | None = None
    for order in range(3, maximum_order + 1):
        candidate = _fit_order(fit_logs, fit_z, fit_modulus, order)
        if candidate is None:
            continue
        selection["candidates"].append({key: value for key, value in candidate.items() if key != "coefficients"})
        if best is None or candidate["normalized_rms"] < best["normalized_rms"]:
            best = candidate
        if candidate["stable_mass"] and _residuals_within_limits(candidate["normalized_rms"], candidate["max_residual"]):
            best = candidate
            break
    if best is None:
        result["reason"] = "no_numerically_resolved_linear_fit"
        return result
    z_fit = _basis(log_frequency, low, high, best["order"]) @ best["coefficients"]
    residual = (z - z_fit) / modulus
    with np.errstate(over="ignore", invalid="ignore"):
        fitted_real, fitted_imag = z_fit.real * impedance_scale, z_fit.imag * impedance_scale
    if not (np.all(np.isfinite(residual)) and np.all(np.isfinite(fitted_real)) and np.all(np.isfinite(fitted_imag))):
        result["reason"] = "predicted_impedance_outside_numeric_range"
        return result
    rms, maximum = _residual_summary(residual)
    within_limits = _residuals_within_limits(rms, maximum)
    status = "consistent" if within_limits and best["stable_mass"] else "review"
    reason = "residuals_within_heuristic_limits"
    if not within_limits:
        reason = "residuals_exceed_heuristic_limits"
    elif not best["stable_mass"]:
        reason = "rc_order_stability_requires_review"
    result.update(
        {
            "status": status,
            "reason": reason,
            "order": best["order"],
            "mu": best["mu"],
            "frequency_hz": frequency.tolist(),
            "z_fit_real": fitted_real.tolist(),
            "z_fit_imag": fitted_imag.tolist(),
            "residual_real": residual.real.tolist(),
            "residual_imag": residual.imag.tolist(),
            "normalized_rms": rms,
            "max_residual": maximum,
        }
    )
    if best["mu"] is None:
        result["notes"].append("Mu is undefined when the RC mass is negligible or lacks a positive component; inspect the residuals.")
    if not best["stable_mass"]:
        result["notes"].append("The fitted RC expansion has substantial negative mass; order stability needs review.")
    if selection["subsampled"]:
        result["notes"].append(f"Fitting used {fit_count} deterministic points; residual criteria include all {count} input points.")
    return result


__all__ = ["kk_validation_metadata", "validate_eis_kk"]
