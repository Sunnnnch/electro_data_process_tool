"""Calculation helpers for EIS processing."""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

EIS_CIRCUIT_MODELS: dict[str, dict[str, Any]] = {
    "randles_rc": {
        "label": "Randles RC",
        "equivalent_circuit": "Rs + (Rct || Cdl)",
        "parameters": ("Rs", "Rct", "Cdl"),
        "assumptions": (
            "One charge-transfer time constant and an ideal double-layer capacitor.",
            "No diffusion (Warburg), inductive, porous-electrode, or distributed-time-constant element is included.",
        ),
    },
    "randles_cpe": {
        "label": "Randles CPE",
        "equivalent_circuit": "Rs + (Rct || CPE[Q,n])",
        "parameters": ("Rs", "Rct", "Q", "n"),
        "assumptions": (
            "One charge-transfer time constant with a constant-phase element for non-ideal capacitance.",
            "No diffusion (Warburg), inductive, porous-electrode, or additional time-constant element is included.",
            "Q has units S*s^n and must not be interpreted as capacitance unless n is sufficiently close to 1.",
        ),
    },
}


def _randles_impedance(freq_arr, Rs, Rct, Cdl):
    """Calculate impedance of ``Rs + (Rct || Cdl)``."""
    omega = 2.0 * np.pi * np.asarray(freq_arr, dtype=float)
    z_faradaic = Rct / (1.0 + 1j * omega * Rct * Cdl)
    return Rs + z_faradaic


def _randles_cpe_impedance(freq_arr, Rs, Rct, Q, n):
    """Calculate impedance of ``Rs + (Rct || CPE[Q,n])``."""
    omega = 2.0 * np.pi * np.asarray(freq_arr, dtype=float)
    admittance = (1.0 / Rct) + Q * np.power(1j * omega, n)
    return Rs + (1.0 / admittance)


def _validated_eis_arrays(freq, z_real, z_imag) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    freq_arr = np.asarray(freq, dtype=float)
    z_real_arr = np.asarray(z_real, dtype=float)
    z_imag_arr = np.asarray(z_imag, dtype=float)
    if freq_arr.ndim != 1 or z_real_arr.ndim != 1 or z_imag_arr.ndim != 1:
        return None
    if not (len(freq_arr) == len(z_real_arr) == len(z_imag_arr)) or len(freq_arr) < 4:
        return None
    if not (
        np.all(np.isfinite(freq_arr))
        and np.all(np.isfinite(z_real_arr))
        and np.all(np.isfinite(z_imag_arr))
        and np.all(freq_arr > 0)
    ):
        return None
    return freq_arr, z_real_arr, z_imag_arr


def _initial_values(freq: np.ndarray, z_real: np.ndarray, z_imag: np.ndarray) -> tuple[float, float, float]:
    rs0 = max(float(np.min(z_real)), 1e-12)
    rct0 = max(float(np.max(z_real) - np.min(z_real)), float(np.median(np.abs(z_real))) * 0.1, 1e-9)
    peak_index = int(np.argmax(np.abs(z_imag)))
    characteristic_frequency = max(float(freq[peak_index]), 1e-12)
    cdl0 = float(np.clip(1.0 / (2.0 * np.pi * characteristic_frequency * rct0), 1e-12, 1.0))
    return rs0, rct0, cdl0


def _fit_diagnostics(
    z_data: np.ndarray,
    z_fit: np.ndarray,
    *,
    model: str,
    parameters: dict[str, float],
) -> dict[str, Any]:
    residual = z_data - z_fit
    ss_res = float(np.sum(np.abs(residual) ** 2))
    ss_tot = float(np.sum(np.abs(z_data - np.mean(z_data)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    rmse_complex = float(np.sqrt(np.mean(np.abs(residual) ** 2)))
    rms_signal = float(np.sqrt(np.mean(np.abs(z_data) ** 2)))
    info = EIS_CIRCUIT_MODELS[model]
    return {
        **parameters,
        "model": model,
        "model_label": info["label"],
        "equivalent_circuit": info["equivalent_circuit"],
        "assumptions": list(info["assumptions"]),
        "parameter_units": {
            "Rs": "Ohm",
            "Rct": "Ohm",
            **({"Cdl": "F"} if model == "randles_rc" else {"Q": "S*s^n", "n": "dimensionless"}),
        },
        "r2": float(r2),
        "rmse_real_ohm": float(np.sqrt(np.mean(np.real(residual) ** 2))),
        "rmse_imag_ohm": float(np.sqrt(np.mean(np.imag(residual) ** 2))),
        "rmse_complex_ohm": rmse_complex,
        "normalized_rmse": rmse_complex / rms_signal if rms_signal > 0 else None,
        "data_points": int(len(z_data)),
        "z_fit_real": np.real(z_fit).tolist(),
        "z_fit_imag": np.imag(z_fit).tolist(),
    }


def fit_eis_circuit(freq, z_real, z_imag, *, model: str = "randles_rc") -> dict[str, Any] | None:
    """Fit a supported equivalent circuit and return parameters plus residual diagnostics."""
    from scipy.optimize import least_squares

    model_key = str(model or "randles_rc").strip().lower()
    if model_key not in EIS_CIRCUIT_MODELS:
        raise ValueError(f"unsupported EIS circuit model: {model}")
    arrays = _validated_eis_arrays(freq, z_real, z_imag)
    if arrays is None:
        return None
    freq_arr, z_real_arr, z_imag_arr = arrays
    z_data = z_real_arr + 1j * z_imag_arr
    rs0, rct0, cdl0 = _initial_values(freq_arr, z_real_arr, z_imag_arr)

    if model_key == "randles_rc":
        initial = np.asarray([rs0, rct0, cdl0], dtype=float)
        lower = np.asarray([0.0, 0.0, 1e-12])
        upper = np.asarray([np.inf, np.inf, 1.0])

        def impedance(values):
            return _randles_impedance(freq_arr, *values)

    else:
        initial = np.asarray([rs0, rct0, cdl0, 0.9], dtype=float)
        lower = np.asarray([0.0, 0.0, 1e-12, 0.3])
        upper = np.asarray([np.inf, np.inf, 10.0, 1.0])

        def impedance(values):
            return _randles_cpe_impedance(freq_arr, *values)

    def residual(values):
        delta = impedance(values) - z_data
        return np.concatenate([delta.real, delta.imag])

    try:
        fit = least_squares(
            residual,
            initial,
            bounds=(lower, upper),
            x_scale="jac",
            max_nfev=20000,
        )
    except Exception:
        return None
    if not fit.success or not np.all(np.isfinite(fit.x)):
        return None
    names = EIS_CIRCUIT_MODELS[model_key]["parameters"]
    parameters = {name: float(value) for name, value in zip(names, fit.x)}
    z_fit = impedance(fit.x)
    return _fit_diagnostics(z_data, z_fit, model=model_key, parameters=parameters)


def evaluate_eis_circuit_fit(
    freq,
    z_real,
    z_imag,
    *,
    model: str = "randles_rc",
    min_r2: float = 0.5,
) -> dict[str, Any]:
    """Fit a model and retain an explicit accepted/rejected status and criterion."""
    threshold = float(np.clip(min_r2, 0.0, 1.0))
    result = fit_eis_circuit(freq, z_real, z_imag, model=model)
    if result is None:
        return {
            "model": model,
            "accepted": False,
            "status": "fit_failed",
            "rejection_reason": "optimizer failed or input did not contain at least four finite positive-frequency points",
            "acceptance_criterion": {"metric": "complex_r2", "minimum": threshold},
        }
    accepted = bool(math.isfinite(float(result["r2"])) and float(result["r2"]) >= threshold)
    result.update(
        {
            "accepted": accepted,
            "status": "accepted" if accepted else "rejected",
            "rejection_reason": None if accepted else f"complex R2 below {threshold:g}",
            "acceptance_criterion": {"metric": "complex_r2", "minimum": threshold},
        }
    )
    return result


def fit_randles(freq, z_real, z_imag):
    """Backward-compatible fit of the ideal Randles RC circuit."""
    return fit_eis_circuit(freq, z_real, z_imag, model="randles_rc")


def accepted_randles_fit(freq, z_real, z_imag, *, min_r2: float = 0.5):
    """Backward-compatible accepted-only ideal Randles fit."""
    result = evaluate_eis_circuit_fit(freq, z_real, z_imag, model="randles_rc", min_r2=min_r2)
    return result if result.get("accepted") else None


def compute_bode_arrays(
    z_real: Sequence[float],
    z_imag: Sequence[float],
) -> tuple[list[float], list[float]]:
    """Calculate impedance magnitude and phase arrays for Bode plots."""
    z_mag = [float(np.sqrt(real**2 + imag**2)) for real, imag in zip(z_real, z_imag)]
    z_phase = [float(np.arctan2(imag, real) * 180.0 / np.pi) for real, imag in zip(z_real, z_imag)]
    return z_mag, z_phase


__all__ = [
    "EIS_CIRCUIT_MODELS",
    "_randles_cpe_impedance",
    "_randles_impedance",
    "accepted_randles_fit",
    "compute_bode_arrays",
    "evaluate_eis_circuit_fit",
    "fit_eis_circuit",
    "fit_randles",
]
