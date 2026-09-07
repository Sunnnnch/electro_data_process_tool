"""Pure calculation helpers for LSV processing."""

from __future__ import annotations

from typing import Iterable, Sequence, overload

import numpy as np

MAD_Z_SCORE_CONSTANT = 0.6745
MAD_OUTLIER_THRESHOLD = 3.5

MIN_FITTING_POINTS = 3
TAFEL_RANGE_RATIO_MIN = 3.0
MAX_EXTRAPOLATION_FACTOR = 2.0
EXTRAPOLATION_LINE_POINTS = 50

A_TO_MA = 1000.0

HALFWAVE_PERCENTILE = 95
HALFWAVE_FRACTION = 0.5

HF_THRESHOLD_UP = 0.7
HF_THRESHOLD_DOWN = 0.3

EIS_RELATIVE_IMAG_THRESHOLD = 0.01


def apply_ir_compensation(
    potential_v,
    current_density_ma_cm2,
    *,
    area_cm2: float,
    resistance_ohm: float,
) -> list[float]:
    """Apply ``E_iR = E - (j / 1000) * A * Rs`` to an LSV curve."""

    potential = np.asarray(potential_v, dtype=float)
    current_density = np.asarray(current_density_ma_cm2, dtype=float)
    if potential.ndim != 1 or current_density.ndim != 1:
        raise ValueError("potential and current density must be one-dimensional")
    if potential.shape != current_density.shape:
        raise ValueError("potential and current density must have the same length")
    compensated = potential - (current_density / A_TO_MA) * float(area_cm2) * float(
        resistance_ohm
    )
    return compensated.astype(float).tolist()


def interpolate_potential(potential, current, target_current):
    """Interpolate the potential at a target current density."""
    p = np.asarray(potential, dtype=float)
    c = np.asarray(current, dtype=float)

    mask = np.isfinite(p) & np.isfinite(c)
    p, c = p[mask], c[mask]
    if c.size < 2:
        return None

    order = np.argsort(c)
    c_sorted = c[order]
    p_sorted = p[order]

    if target_current < c_sorted.min() or target_current > c_sorted.max():
        return None

    uniq_c, inv_idx = np.unique(c_sorted, return_inverse=True)
    if uniq_c.size != c_sorted.size:
        sums = np.zeros_like(uniq_c, dtype=float)
        counts = np.zeros_like(uniq_c, dtype=int)
        for idx, pot in zip(inv_idx, p_sorted):
            sums[idx] += pot
            counts[idx] += 1
        uniq_p = sums / np.maximum(counts, 1)
        return float(np.interp(target_current, uniq_c, uniq_p))

    return float(np.interp(target_current, c_sorted, p_sorted))


def parse_target_currents(target_current_str):
    """Parse a comma-separated target-current string such as ``10,100``."""
    if target_current_str is None:
        return []
    try:
        current_strs = [
            s.strip()
            for s in str(target_current_str).replace("\uff0c", ",").split(",")
            if s.strip()
        ]
        currents = []
        for current_str in current_strs:
            try:
                current = float(current_str)
                if current > 0:
                    currents.append(current)
            except ValueError:
                continue
        return sorted(set(currents))
    except (ValueError, TypeError):
        return []


def _parse_tafel_range(raw_value):
    """Parse a Tafel current range string such as ``1-10``."""
    if raw_value is None:
        return None
    text = (
        str(raw_value)
        .replace("\uff0d", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace(" ", "")
    )
    if not text:
        return None
    if "-" in text:
        lo_text, hi_text = text.split("-", 1)
    else:
        lo_text, hi_text = text, text
    try:
        lo = float(lo_text)
        hi = float(hi_text)
    except (ValueError, TypeError):
        return None
    return (lo, hi)


_NumericValues = Sequence[float] | np.ndarray


@overload
def _filter_outliers(
    real_vals: _NumericValues, imag_vals: _NumericValues, freq_vals: _NumericValues,
    thresh: float = MAD_OUTLIER_THRESHOLD,
) -> tuple[_NumericValues, _NumericValues, _NumericValues]: ...


@overload
def _filter_outliers(
    real_vals: _NumericValues, imag_vals: _NumericValues, freq_vals: None = None,
    thresh: float = MAD_OUTLIER_THRESHOLD,
) -> tuple[_NumericValues, _NumericValues, None]: ...


@overload
def _filter_outliers(
    real_vals: _NumericValues | None, imag_vals: _NumericValues | None,
    freq_vals: _NumericValues | None = None, thresh: float = MAD_OUTLIER_THRESHOLD,
) -> tuple[_NumericValues | None, _NumericValues | None, _NumericValues | None]: ...


def _filter_outliers(
    real_vals: _NumericValues | None, imag_vals: _NumericValues | None,
    freq_vals: _NumericValues | None = None, thresh: float = MAD_OUTLIER_THRESHOLD,
) -> tuple[_NumericValues | None, _NumericValues | None, _NumericValues | None]:
    """Filter EIS high-frequency outliers with a MAD-based mask."""
    if real_vals is None or imag_vals is None:
        return real_vals, imag_vals, freq_vals
    if len(real_vals) < 3 or len(imag_vals) < 3:
        return real_vals, imag_vals, freq_vals

    def _mask(vals):
        v = np.asarray(vals, dtype=float)
        med = np.nanmedian(v)
        mad = np.nanmedian(np.abs(v - med))
        if mad <= 0:
            return np.ones_like(v, dtype=bool)
        z = MAD_Z_SCORE_CONSTANT * (v - med) / mad
        return np.abs(z) <= thresh

    mask = _mask(real_vals) & _mask(imag_vals)
    if mask.sum() < 2:
        return real_vals, imag_vals, freq_vals

    real_f = [v for v, m in zip(real_vals, mask) if m]
    imag_f = [v for v, m in zip(imag_vals, mask) if m]
    if freq_vals is not None:
        freq_f = [v for v, m in zip(freq_vals, mask) if m]
    else:
        freq_f = None
    return real_f, imag_f, freq_f


def interpolate_multiple_potentials(potential, current, target_currents: Iterable[float]):
    """Calculate potentials for multiple target current densities."""
    results = {}
    for target in target_currents:
        result = interpolate_potential(potential, current, target)
        if result is not None:
            results[target] = result
    return results


def potential_at_current(
    potential_V,
    current_mAcm2,
    target_i=10.0,
    min_pts=MIN_FITTING_POINTS,
    tafel_ratio=TAFEL_RANGE_RATIO_MIN,
    max_extrap_factor=MAX_EXTRAPOLATION_FACTOR,
):
    """Return potential at a target current using interpolation or guarded extrapolation."""
    E = np.asarray(potential_V, dtype=float)
    I = np.asarray(current_mAcm2, dtype=float)

    mask = np.isfinite(E) & np.isfinite(I)
    E, I = E[mask], I[mask]
    if E.size < 2:
        return np.nan, None

    order = np.argsort(I)
    I, E = I[order], E[order]

    if I.max() <= 0 or target_i > I.max() * float(max_extrap_factor):
        return np.nan, None

    if (I.min() <= target_i) and (I.max() >= target_i):
        E_target = float(np.interp(target_i, I, E))
        return E_target, None

    going_up = target_i > I.max()
    if going_up:
        threshold = max(1.0, HF_THRESHOLD_UP * I.max())
        selected = np.where(I >= threshold)[0]
        if selected.size < min_pts:
            selected = np.arange(max(0, len(I) - min_pts), len(I))
    else:
        threshold = HF_THRESHOLD_DOWN * I.min()
        selected = np.where(I <= threshold)[0]
        if selected.size < min_pts:
            selected = np.arange(0, min(min_pts, len(I)))

    I_sel, E_sel = I[selected], E[selected]

    use_tafel = (
        (I_sel > 0).all()
        and (selected.size >= min_pts)
        and (I_sel.max() / max(I_sel.min(), 1e-9) >= float(tafel_ratio))
    )

    if use_tafel:
        x = np.log10(np.clip(I_sel, 1e-12, None))
        b, a = np.polyfit(x, E_sel, 1)
        E_target = float(a + b * np.log10(max(target_i, 1e-12)))
        i0 = I_sel.max() if going_up else target_i
        i1 = target_i if going_up else I_sel.min()
        i_ext = np.linspace(i0, i1, EXTRAPOLATION_LINE_POINTS)
        E_ext = a + b * np.log10(np.clip(i_ext, 1e-12, None))
        method = f"tafel (b={b:.3f} V/dec)"
    else:
        m, c = np.polyfit(I_sel, E_sel, 1)
        E_target = float(m * target_i + c)
        i0 = I_sel.max() if going_up else target_i
        i1 = target_i if going_up else I_sel.min()
        i_ext = np.linspace(i0, i1, EXTRAPOLATION_LINE_POINTS)
        E_ext = m * i_ext + c
        method = "linear"

    if (max(target_i, I.max()) / max(1e-12, min(I_sel.max(), target_i))) > float(max_extrap_factor):
        return np.nan, None

    return E_target, (E_ext, i_ext, method)


__all__ = [
    "A_TO_MA",
    "EIS_RELATIVE_IMAG_THRESHOLD",
    "HALFWAVE_FRACTION",
    "HALFWAVE_PERCENTILE",
    "MAD_OUTLIER_THRESHOLD",
    "MAD_Z_SCORE_CONSTANT",
    "MAX_EXTRAPOLATION_FACTOR",
    "MIN_FITTING_POINTS",
    "TAFEL_RANGE_RATIO_MIN",
    "_filter_outliers",
    "_parse_tafel_range",
    "apply_ir_compensation",
    "interpolate_multiple_potentials",
    "interpolate_potential",
    "parse_target_currents",
    "potential_at_current",
]
