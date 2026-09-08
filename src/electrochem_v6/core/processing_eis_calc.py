"""Bounded equivalent-circuit fitting and local EIS uncertainty diagnostics.

Element conventions follow impedance.py's CPE and semi-infinite W definitions:
https://impedancepy.readthedocs.io/en/latest/circuit-elements.html
Local covariance uses the residual-scaled Jacobian linearization described by:
https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.curve_fit.html
Neither convergence nor local confidence intervals establish physical model validity.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Callable, Mapping, Sequence, cast

import numpy as np

_CPE_NOTE = "Q has units S*s^n and is not capacitance unless n = 1."
_NO_EXTRA_ELEMENTS = "No inductive, porous-electrode, or additional distributed relaxation element is included."
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
            _CPE_NOTE,
        ),
    },
    "randles_warburg_rc": {
        "label": "Randles RC + Warburg",
        "equivalent_circuit": "Rs + (Cdl || (Rct + W[sigma]))",
        "parameters": ("Rs", "Rct", "Cdl", "sigma"),
        "assumptions": (
            "Semi-infinite diffusion: Z_W = sigma*(1-j)/sqrt(2*pi*f); finite-length diffusion is not represented.",
            "The diffusion element is in series with Rct, inside the capacitive parallel branch.",
            _NO_EXTRA_ELEMENTS,
        ),
    },
    "randles_warburg_cpe": {
        "label": "Randles CPE + Warburg",
        "equivalent_circuit": "Rs + (CPE[Q,n] || (Rct + W[sigma]))",
        "parameters": ("Rs", "Rct", "Q", "n", "sigma"),
        "assumptions": (
            "Semi-infinite diffusion: Z_W = sigma*(1-j)/sqrt(2*pi*f); finite-length diffusion is not represented.",
            "The diffusion element is in series with Rct, inside the CPE parallel branch.",
            _NO_EXTRA_ELEMENTS,
            _CPE_NOTE,
        ),
    },
    "two_time_constants_rc": {
        "label": "Two time constants RC",
        "equivalent_circuit": "Rs + (R1 || C1) + (R2 || C2)",
        "parameters": ("Rs", "R1", "C1", "R2", "C2"),
        "assumptions": (
            "Two series-connected parallel RC branches, ordered by increasing tau = R*C.",
            "R1 and R2 identify mathematical branches, not a uniquely assigned charge-transfer resistance.",
            "No diffusion or inductive element is included.",
        ),
    },
    "two_time_constants_cpe": {
        "label": "Two time constants CPE",
        "equivalent_circuit": "Rs + (R1 || CPE[Q1,n1]) + (R2 || CPE[Q2,n2])",
        "parameters": ("Rs", "R1", "Q1", "n1", "R2", "Q2", "n2"),
        "assumptions": (
            "Two series-connected R/CPE branches, ordered by increasing tau = (R*Q)^(1/n).",
            "R1 and R2 identify mathematical branches, not a uniquely assigned charge-transfer resistance.",
            "No diffusion or inductive element is included.",
            _CPE_NOTE,
        ),
    },
}
for _model_info in EIS_CIRCUIT_MODELS.values():
    _model_info["parameter_units"] = {
        name: (
            "Ohm"
            if name.startswith("R")
            else "F"
            if name.startswith("C")
            else "dimensionless"
            if name.startswith("n")
            else "Ohm*s^-0.5"
            if name == "sigma"
            else f"S*s^n{name[1:]}"
        )
        for name in _model_info["parameters"]
    }

_MAX_NFEV = 800
_RANK_RTOL = 1e-8
_CONDITION_LIMIT = 1e6
_CORRELATION_LIMIT = 0.98


def _randles_impedance(freq_arr, Rs, Rct, Cdl):
    """Calculate impedance of ``Rs + (Rct || Cdl)``."""
    omega = 2.0 * np.pi * np.asarray(freq_arr, dtype=float)
    return Rs + Rct / (1.0 + 1j * omega * Rct * Cdl)


def _randles_cpe_impedance(freq_arr, Rs, Rct, Q, n):
    """Calculate impedance of ``Rs + (Rct || CPE[Q,n])``."""
    omega = 2.0 * np.pi * np.asarray(freq_arr, dtype=float)
    return Rs + Rct / (1.0 + Rct * Q * np.power(1j * omega, n))


def _impedance_and_jacobian(freq: np.ndarray, values: np.ndarray, model: str) -> tuple[np.ndarray, np.ndarray]:
    """Physical-coordinate analytic derivatives, including the Warburg topology."""
    jw = 2j * np.pi * freq
    z = np.full(freq.shape, values[0], dtype=complex)
    jac = np.zeros((len(freq), len(values)), dtype=complex)
    jac[:, 0] = 1.0
    cpe = model.endswith("cpe")
    double = model.startswith("two_")
    warburg = "warburg" in model
    width = 3 if cpe else 2
    for offset in [1, 1 + width] if double else [1]:
        resistance, capacitance = values[offset : offset + 2]
        exponent = values[offset + 2] if cpe else 1.0
        power = np.power(jw, exponent)
        faradaic = np.full(freq.shape, resistance, dtype=complex)
        if warburg:
            w_unit = (1.0 - 1j) / np.sqrt(2.0 * np.pi * freq)
            faradaic += values[-1] * w_unit
        denominator = 1.0 + capacitance * power * faradaic
        branch = faradaic / denominator
        inverse_squared = 1.0 / denominator**2
        z += branch
        jac[:, offset] = inverse_squared
        jac[:, offset + 1] = -(branch**2) * power
        if cpe:
            jac[:, offset + 2] = -(branch**2) * capacitance * power * np.log(jw)
        if warburg:
            jac[:, -1] = inverse_squared * w_unit
    return z, jac


def eis_circuit_impedance(freq, parameters: Mapping[str, float], *, model: str = "randles_rc") -> np.ndarray:
    """Evaluate a supported model with named physical parameters, in input order."""
    key = str(model).strip().lower()
    if key not in EIS_CIRCUIT_MODELS:
        raise ValueError(f"unsupported EIS circuit model: {model}")
    values = np.asarray([parameters[name] for name in EIS_CIRCUIT_MODELS[key]["parameters"]], dtype=float)
    return _impedance_and_jacobian(np.asarray(freq, dtype=float), values, key)[0]


def _validated_eis_arrays(freq, z_real, z_imag) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    try:
        arrays = tuple(np.asarray(item, dtype=float) for item in (freq, z_real, z_imag))
    except (TypeError, ValueError, OverflowError):
        return None
    if any(item.ndim != 1 for item in arrays):
        return None
    freq_arr, z_real_arr, z_imag_arr = arrays
    if not (len(freq_arr) == len(z_real_arr) == len(z_imag_arr)) or len(freq_arr) < 4:
        return None
    if not all(np.all(np.isfinite(item)) for item in arrays) or not np.all(freq_arr > 0):
        return None
    return freq_arr, z_real_arr, z_imag_arr


def _initial_values(freq: np.ndarray, z_real: np.ndarray, z_imag: np.ndarray) -> tuple[float, float, float]:
    rs0 = max(float(np.min(z_real)), 1e-12)
    rct0 = max(float(np.ptp(z_real)), float(np.median(np.abs(z_real))) * 0.1, 1e-9)
    peak = int(np.argmax(np.abs(z_imag)))
    cdl0 = float(np.clip(1.0 / (2.0 * np.pi * freq[peak] * rct0), 1e-12, 1.0))
    return rs0, rct0, cdl0


def _starting_points(freq: np.ndarray, z: np.ndarray, model: str) -> list[np.ndarray]:
    """Fixed, deterministic seeds span measured relaxation times; no random search."""
    rs, resistance, capacitance = _initial_values(freq, np.real(z), np.imag(z))
    tau_peak = resistance * capacitance
    times = 1.0 / (2.0 * np.pi * freq)
    log_times = np.log(times)
    cpe = model.endswith("cpe")
    double = model.startswith("two_")
    warburg = "warburg" in model

    def branch(r: float, tau: float, n: float) -> list[float]:
        return [r, tau**n / r, n] if cpe else [r, tau / r]

    starts = []
    if double:
        anchors = np.exp(np.quantile(log_times, [0.1, 0.35, 0.65, 0.9]))
        pairs = list(combinations(anchors, 2))
        pairs += [(tau_peak / 10.0, tau_peak), (tau_peak, tau_peak * 10.0)]
        for index, (fast, slow) in enumerate(pairs):
            fraction = 0.35 if index % 2 == 0 else 0.65
            starts.append(
                np.asarray(
                    [rs, *branch(resistance * fraction, fast, 0.85), *branch(resistance * (1 - fraction), slow, 0.85)]
                )
            )
        if cpe:
            for n in (0.65, 0.98):
                starts.append(
                    np.asarray(
                        [rs, *branch(resistance * 0.5, tau_peak / 5, n), *branch(resistance * 0.5, tau_peak * 5, n)]
                    )
                )
    elif warburg:
        # A low-frequency 1/sqrt(omega) slope is only an initializer, never a fitted diffusion estimate.
        count = max(2, len(freq) // 5)
        x = 1.0 / np.sqrt(2.0 * np.pi * freq[:count])
        dx = float(x[0] - x[-1])
        slope = float((np.real(z)[0] - np.real(z)[count - 1]) / dx) if dx > 0 else 0.0
        sigma = max(slope, float(np.max(np.abs(z))) * np.sqrt(2 * np.pi * freq[0]) * 0.05, 1e-12)
        anchors = [tau_peak, *np.exp(np.quantile(log_times, [0.2, 0.5, 0.8]))]
        for tau in anchors:
            for factor, n in ((0.25, 0.75), (0.8, 0.95)):
                starts.append(np.asarray([rs, *branch(resistance * factor, tau, n), sigma]))
    else:
        for factor in (0.1, 1.0, 10.0):
            for n in (0.65, 0.95) if cpe else (1.0,):
                starts.append(np.asarray([rs, *branch(resistance, tau_peak * factor, n)]))
    return starts


def _coordinate_system(model: str, scale: float, freq: np.ndarray):
    """Log coordinates for positive elements; a scaled linear Rs permits exact zero."""
    names = EIS_CIRCUIT_MODELS[model]["parameters"]
    lower, upper = [], []
    for name in names:
        if name == "Rs":
            limits = (0.0, 1e6)
        elif name.startswith("n"):
            limits = (0.3, 1.0)
        elif name.startswith("R"):
            limits = (math.log(max(scale * 1e-10, 1e-14)), math.log(max(scale * 1e6, 1.0)))
        elif name.startswith("C"):
            limits = (math.log(1e-14), math.log(1.0))
        elif name.startswith("Q"):
            limits = (math.log(1e-14), math.log(10.0))
        else:
            low = max(scale * math.sqrt(2 * np.pi * freq[0]) * 1e-10, 1e-14)
            high = max(scale * math.sqrt(2 * np.pi * freq[-1]) * 1e6, 1.0)
            limits = (math.log(low), math.log(high))
        lower.append(limits[0])
        upper.append(limits[1])

    def encode(values):
        return np.asarray(
            [
                value / scale if name == "Rs" else value if name.startswith("n") else np.log(value)
                for name, value in zip(names, values)
            ]
        )

    def decode(theta):
        return np.asarray(
            [
                value * scale if name == "Rs" else value if name.startswith("n") else np.exp(value)
                for name, value in zip(names, theta)
            ]
        )

    def derivative(values):
        return np.asarray(
            [scale if name == "Rs" else 1.0 if name.startswith("n") else value for name, value in zip(names, values)]
        )

    return np.asarray(lower), np.asarray(upper), encode, decode, derivative


def _branch_times(values: np.ndarray, model: str) -> list[float]:
    cpe = model.endswith("cpe")
    width = 3 if cpe else 2
    return [
        float((values[k] * values[k + 1]) ** (1.0 / values[k + 2] if cpe else 1.0))
        for k in ([1, 1 + width] if model.startswith("two_") else [1])
    ]


def _local_uncertainty(
    values: np.ndarray,
    jac: np.ndarray,
    residual: np.ndarray,
    *,
    model: str,
    theta: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    coordinate_derivative: np.ndarray,
    freq: np.ndarray,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Residual-scaled local intervals; deliberately unavailable for unstable fits."""
    from scipy.stats import t

    names = list(EIS_CIRCUIT_MODELS[model]["parameters"])
    count = len(names)
    dof = len(residual) - count
    norms = np.linalg.norm(jac, axis=0)
    safe_norms = np.where(norms > np.finfo(float).tiny, norms, 1.0)
    _, singular, vt = np.linalg.svd(jac / safe_norms, full_matrices=False)
    tolerance = float(singular[0] * _RANK_RTOL) if singular.size else 0.0
    rank = int(np.count_nonzero(singular > tolerance))
    condition = float(singular[0] / singular[-1]) if singular.size and singular[-1] > 0 else math.inf
    boundary = []
    for index, name in enumerate(names):
        distance = min(float(theta[index] - lower[index]), float(upper[index] - theta[index]))
        # Rs's remote upper safety bound must not turn ordinary small Rs into a boundary hit.
        tolerance_bound = 1e-7 if name == "Rs" else 1e-5 * max(1.0, float(upper[index] - lower[index]))
        if distance <= tolerance_bound:
            boundary.append(name)
    times = _branch_times(values, model)
    double = model.startswith("two_")
    branch_ratio = times[1] / times[0] if double else None
    branch_resistances = [values[1], values[4] if model.endswith("cpe") else values[3]] if double else []
    branch_weak = bool(double and min(branch_resistances) < sum(branch_resistances) * 1e-5)
    indistinguishable = bool(double and (float(branch_ratio or 0) < 3.0 or branch_weak or rank < count))
    reasons = []
    if rank < count:
        reasons.append("rank_deficient_jacobian")
    if not math.isfinite(condition) or condition > _CONDITION_LIMIT:
        reasons.append("ill_conditioned_jacobian")
    if boundary:
        reasons.append("parameter_at_bound")
    if dof <= 0:
        reasons.append("insufficient_residual_degrees_of_freedom")
    if indistinguishable:
        reasons.append("branches_indistinguishable")
    time_min = 1.0 / (2.0 * np.pi * float(np.max(freq)))
    time_max = 1.0 / (2.0 * np.pi * float(np.min(freq)))
    if any(tau < time_min or tau > time_max for tau in times):
        reasons.append("relaxation_outside_frequency_window")
    cannot_estimate = [reason for reason in reasons if reason != "relaxation_outside_frequency_window"]
    covariance = None
    correlations = []
    standard_errors = None
    if rank == count and dof > 0 and np.all(singular > 0):
        covariance_theta = ((vt.T / singular**2) @ vt) / np.outer(safe_norms, safe_norms)
        covariance_theta *= float(residual @ residual) / dof
        covariance = covariance_theta * np.outer(coordinate_derivative, coordinate_derivative)
        standard_errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))
        if not np.all(np.isfinite(standard_errors)):
            standard_errors = None
            cannot_estimate.append("nonfinite_covariance")
            reasons.append("nonfinite_covariance")
        else:
            for i, j in combinations(range(count), 2):
                divisor = standard_errors[i] * standard_errors[j]
                correlation = float(np.clip(covariance[i, j] / divisor, -1, 1)) if divisor > 0 else 0.0
                if abs(correlation) >= _CORRELATION_LIMIT:
                    correlations.append({"parameters": [names[i], names[j]], "correlation": correlation})
            if correlations:
                reasons.append("high_parameter_correlation")
    intervals = {}
    critical = float(t.ppf(0.975, dof)) if dof > 0 else math.nan
    for index, name in enumerate(names):
        estimable = not cannot_estimate and standard_errors is not None
        se = float(standard_errors[index]) if standard_errors is not None else None
        width = critical * se if estimable and se is not None else None
        intervals[name] = {
            "lower": float(values[index] - width) if width is not None else None,
            "upper": float(values[index] + width) if width is not None else None,
            "standard_error": se if estimable else None,
            "estimable": bool(estimable),
            "reason": "; ".join(cannot_estimate) if cannot_estimate else None,
        }
        if width is not None and width > abs(values[index]) and "wide_local_confidence_intervals" not in reasons:
            reasons.append("wide_local_confidence_intervals")
    diagnostics = {
        "jacobian_rank": rank,
        "parameter_count": count,
        "condition_number": condition if math.isfinite(condition) else None,
        "condition_number_is_infinite": not math.isfinite(condition),
        "jacobian_scaling": "unit-column-norm, weighted residual, log-positive/scaled-Rs coordinates",
        "rank_relative_tolerance": _RANK_RTOL,
        "condition_warning_threshold": _CONDITION_LIMIT,
        "boundary_parameters": boundary,
        "high_correlations": correlations,
        "correlation_warning_threshold": _CORRELATION_LIMIT,
        "branches_indistinguishable": indistinguishable,
        "time_constant_ratio": branch_ratio,
        "branch_resolution_rule": "review if tau2/tau1 < 3, a branch is negligible, or Jacobian is rank deficient"
        if double
        else None,
        "residual_degrees_of_freedom": dof,
        "ci_method": "approximate 95% local Student-t intervals from residual-scaled weighted Jacobian covariance",
        "ci_assumptions": (
            "Local linearization and independent, zero-mean residuals with common variance after weighting; "
            "modulus weights are empirical, not measured noise standard deviations. "
            "Intervals exclude model error, are not simultaneous, and may extend beyond physical bounds. "
            "Unavailable at parameter bounds, rank/conditioning failures, or unresolved double branches."
        ),
    }
    return intervals, diagnostics, reasons


def _fit_diagnostics(
    z_data: np.ndarray, z_fit: np.ndarray, *, model: str, parameters: dict[str, float]
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
        "parameters": dict(parameters),
        "parameter_order": list(info["parameters"]),
        "model": model,
        "model_label": info["label"],
        "equivalent_circuit": info["equivalent_circuit"],
        "assumptions": list(info["assumptions"]),
        "parameter_units": dict(info["parameter_units"]),
        "r2": float(r2),
        "rmse_real_ohm": float(np.sqrt(np.mean(np.real(residual) ** 2))),
        "rmse_imag_ohm": float(np.sqrt(np.mean(np.imag(residual) ** 2))),
        "rmse_complex_ohm": rmse_complex,
        "normalized_rmse": rmse_complex / rms_signal if rms_signal > 0 else None,
        "data_points": int(len(z_data)),
        "z_fit_real": np.real(z_fit).tolist(),
        "z_fit_imag": np.imag(z_fit).tolist(),
        "residual_real_ohm": np.real(residual).tolist(),
        "residual_imag_ohm": np.imag(residual).tolist(),
        "residual_convention": "measured minus fitted impedance; imaginary part uses signed Z''",
    }


def fit_eis_circuit(
    freq,
    z_real,
    z_imag,
    *,
    model: str = "randles_rc",
    weighting: str = "uniform",
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any] | None:
    """Fit deterministic bounded starts; return convergence separately from reliability.

    Uniform minimizes sum |Zdata-Zfit|^2. Modulus minimizes that sum divided
    pointwise by max(|Zdata|, median(|Zdata|)*1e-6, 1e-12 Ohm)^2. The same
    point weight applies to real/imaginary components. No observations are dropped.
    """
    from scipy.optimize import least_squares

    model_key = str(model or "randles_rc").strip().lower()
    if model_key not in EIS_CIRCUIT_MODELS:
        raise ValueError(f"unsupported EIS circuit model: {model}")
    weight_key = str(weighting or "uniform").strip().lower()
    if weight_key not in {"uniform", "modulus"}:
        raise ValueError(f"unsupported EIS weighting: {weighting}")
    arrays = _validated_eis_arrays(freq, z_real, z_imag)
    if arrays is None:
        return None
    original_freq, original_real, original_imag = arrays
    order = np.lexsort((original_imag, original_real, original_freq))
    freq_arr = original_freq[order]
    z_data = original_real[order] + 1j * original_imag[order]
    scale = max(float(np.max(np.abs(z_data))), 1e-12)
    floor = max(float(np.median(np.abs(z_data))) * 1e-6, 1e-12)
    denominator = np.full(len(z_data), scale) if weight_key == "uniform" else np.maximum(np.abs(z_data), floor)
    was_cancelled = False

    def check():
        nonlocal was_cancelled
        if cancel_check is not None:
            try:
                cancel_check()
            except Exception:
                was_cancelled = True
                raise

    check()
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            lower, upper, encode, decode, derivative = _coordinate_system(model_key, scale, freq_arr)
            starts = _starting_points(freq_arr, z_data, model_key)
    except (ArithmeticError, ValueError):
        return None

    def residual(theta):
        check()
        values = decode(theta)
        z_fit, _ = _impedance_and_jacobian(freq_arr, values, model_key)
        delta = (z_fit - z_data) / denominator
        return np.concatenate([np.real(delta), np.imag(delta)])

    def jacobian(theta):
        values = decode(theta)
        _, physical_jac = _impedance_and_jacobian(freq_arr, values, model_key)
        transformed = physical_jac * derivative(values) / denominator[:, None]
        return np.concatenate([np.real(transformed), np.imag(transformed)], axis=0)

    best = None
    attempts = 0
    converged = 0
    total_nfev = 0
    for initial in starts:
        check()
        attempts += 1
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                theta0 = np.clip(encode(initial), lower + 1e-10, upper - 1e-10)
                fit = cast(Callable[..., Any], least_squares)(
                    residual,
                    theta0,
                    jac=jacobian,
                    bounds=(lower, upper),
                    x_scale="jac",
                    max_nfev=_MAX_NFEV,
                    ftol=1e-10,
                    xtol=1e-10,
                    gtol=1e-10,
                )
        except (ArithmeticError, ValueError, np.linalg.LinAlgError):
            if was_cancelled:
                raise
            continue
        total_nfev += int(fit.nfev)
        if fit.success and np.all(np.isfinite(fit.x)) and math.isfinite(float(fit.cost)):
            converged += 1
            if best is None or fit.cost < best.cost:
                best = fit
    check()
    if best is None:
        return None
    values = decode(best.x)
    if model_key.startswith("two_") and _branch_times(values, model_key)[0] > _branch_times(values, model_key)[1]:
        permutation = [0, 4, 5, 6, 1, 2, 3] if model_key.endswith("cpe") else [0, 3, 4, 1, 2]
        values = values[permutation]
    theta = encode(values)
    parameters = dict(zip(EIS_CIRCUIT_MODELS[model_key]["parameters"], map(float, values)))
    z_fit = eis_circuit_impedance(original_freq, parameters, model=model_key)
    result = _fit_diagnostics(original_real + 1j * original_imag, z_fit, model=model_key, parameters=parameters)
    try:
        ci, diagnostics, reasons = _local_uncertainty(
            values,
            jacobian(theta),
            residual(theta),
            model=model_key,
            theta=theta,
            lower=lower,
            upper=upper,
            coordinate_derivative=derivative(values),
            freq=freq_arr,
        )
    except (ArithmeticError, ValueError, np.linalg.LinAlgError):
        if was_cancelled:
            raise
        ci = {
            name: {
                "lower": None,
                "upper": None,
                "standard_error": None,
                "estimable": False,
                "reason": "uncertainty_computation_failed",
            }
            for name in parameters
        }
        diagnostics = {
            "jacobian_rank": None,
            "condition_number": None,
            "boundary_parameters": [],
            "high_correlations": [],
            "branches_indistinguishable": None,
        }
        reasons = ["uncertainty_computation_failed"]
    result.update(
        {
            "weighting": weight_key,
            "weighting_floor_ohm": floor if weight_key == "modulus" else None,
            "weighted_rmse": float(
                np.sqrt(
                    np.mean(
                        np.abs(
                            (z_data - eis_circuit_impedance(freq_arr, parameters, model=model_key))
                            / (denominator if weight_key == "modulus" else 1.0)
                        )
                        ** 2
                    )
                )
            ),
            "parameter_ci95": ci,
            "identifiability": diagnostics,
            "numerical_converged": True,
            "parameter_bounds": {
                name: {"lower": float(lo), "upper": float(hi)}
                for name, lo, hi in zip(parameters, decode(lower), decode(upper))
            },
            "review_required": bool(reasons),
            "review_reasons": reasons,
            "optimizer": {
                "method": "bounded deterministic multi-start least_squares (TRF), analytic Jacobian",
                "starts_attempted": attempts,
                "starts_converged": converged,
                "max_starts": len(starts),
                "max_nfev_per_start": _MAX_NFEV,
                "total_nfev": total_nfev,
                "winning_nfev": int(best.nfev),
                "termination_status": int(best.status),
                "message": str(best.message),
            },
        }
    )
    if model_key.startswith("two_"):
        times = _branch_times(values, model_key)
        result["time_constants_s"] = {"tau1": times[0], "tau2": times[1]}
        result["branch_order"] = "increasing_time_constant"
    return result


def evaluate_eis_circuit_fit(
    freq,
    z_real,
    z_imag,
    *,
    model: str = "randles_rc",
    min_r2: float = 0.5,
    weighting: str = "uniform",
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Retain the legacy R² gate while separately flagging parameter review."""
    threshold = float(min_r2)
    if not math.isfinite(threshold):
        raise ValueError("EIS min_r2 must be finite")
    threshold = float(np.clip(threshold, 0.0, 1.0))
    result = fit_eis_circuit(freq, z_real, z_imag, model=model, weighting=weighting, cancel_check=cancel_check)
    note = "The R2 threshold is only a numerical fit gate; it does not validate the circuit or physical parameter interpretation."
    if result is None:
        return {
            "model": model,
            "weighting": weighting,
            "accepted": False,
            "status": "fit_failed",
            "numerical_converged": False,
            "review_required": True,
            "review_reasons": ["fit_failed"],
            "rejection_reason": "optimizer failed or input did not contain at least four finite positive-frequency points",
            "acceptance_criterion": {"metric": "complex_r2", "minimum": threshold},
            "acceptance_note": note,
        }
    accepted = bool(math.isfinite(float(result["r2"])) and float(result["r2"]) >= threshold)
    result.update(
        {
            "accepted": accepted,
            "status": ("needs_review" if result["review_required"] else "accepted") if accepted else "rejected",
            "rejection_reason": None if accepted else f"complex R2 below {threshold:g}",
            "acceptance_criterion": {"metric": "complex_r2", "minimum": threshold},
            "acceptance_note": note,
        }
    )
    return result


def fit_randles(freq, z_real, z_imag):
    """Backward-compatible fit of the ideal Randles RC circuit."""
    return fit_eis_circuit(freq, z_real, z_imag, model="randles_rc")


def accepted_randles_fit(freq, z_real, z_imag, *, min_r2: float = 0.5):
    """Backward-compatible R²-gated ideal Randles fit; inspect review_required too."""
    result = evaluate_eis_circuit_fit(freq, z_real, z_imag, model="randles_rc", min_r2=min_r2)
    return result if result.get("accepted") else None


def compute_bode_arrays(z_real: Sequence[float], z_imag: Sequence[float]) -> tuple[list[float], list[float]]:
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
    "eis_circuit_impedance",
    "evaluate_eis_circuit_fit",
    "fit_eis_circuit",
    "fit_randles",
]
