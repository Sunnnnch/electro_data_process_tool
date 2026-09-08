"""Calculation helpers for ECSA processing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from .processing_ecsa_io import (
    _ecsa_extract_v_from_content,
    _ecsa_extract_v_from_name,
    _ecsa_read_cv_table,
)
from .utils import as_float


@dataclass(frozen=True)
class EcsaFitResult:
    """Fitted ECSA metrics derived from ΔJ versus scan rate."""

    slope_mFcm2: float
    intercept: float
    r2: float
    cdl_mFcm2: float
    cs_input: float
    cs_unit: str
    cs_mFcm2: float
    ecsa_cm2: float
    rf: float


def _ecsa_find_pairs(potential: np.ndarray, ev: float):
    up, down = [], []
    for idx in range(len(potential) - 1):
        e1, e2 = potential[idx], potential[idx + 1]
        # Half-open intervals assign an exact evaluation-potential sample to
        # one crossing, including a plateau at Ev, rather than to both edges.
        if e1 < ev <= e2:
            up.append((idx, idx + 1))
        elif e2 <= ev < e1:
            down.append((idx, idx + 1))
    return up, down


def _ecsa_interp_I(potential: np.ndarray, current: np.ndarray, pair, ev: float):
    left, right = pair
    e1, e2 = potential[left], potential[right]
    i1, i2 = current[left], current[right]
    if e2 == e1:
        return (i1 + i2) / 2.0
    fraction = (ev - e1) / (e2 - e1)
    return i1 + fraction * (i2 - i1)


def compute_deltaJ_for_file(
    filepath: str,
    Ev: float,
    last_n: int = 1,
    avg_last_n: bool = False,
    area_cm2: float = 1.0,
    use_abs_delta: bool = True,
    log_func: Any | None = None,
    *,
    potential_column: int = 0,
    current_column: int = 1,
    potential_scale: float = 1.0,
    current_scale: float = 1.0,
):
    """Compute scan rate and ΔJ for one ECSA CV file."""
    if last_n < 1:
        raise ValueError("last_n must be greater than zero")
    potential, current, lines = _ecsa_read_cv_table(
        filepath,
        potential_column=potential_column,
        current_column=current_column,
        potential_scale=potential_scale,
        current_scale=current_scale,
    )
    if potential.size < 3:
        return None, None

    scan_rate = _ecsa_extract_v_from_name(filepath)
    if scan_rate is None or scan_rate <= 0:
        scan_rate = _ecsa_extract_v_from_content(lines)
    if scan_rate is None or scan_rate <= 0:
        return None, None

    up, down = _ecsa_find_pairs(potential, Ev)
    if not up or not down:
        return scan_rate, None

    # Select complete pairs in acquisition order. An unfinished final sweep
    # must not be combined with the opposite branch of the previous cycle.
    crossings = sorted([(pair, 1) for pair in up] + [(pair, -1) for pair in down])
    cycle_pairs = []
    pending = None
    for pair, direction in crossings:
        if pending is None or pending[1] == direction:
            pending = (pair, direction)
            continue
        first_pair, first_direction = pending
        cycle_pairs.append((first_pair, pair) if first_direction > 0 else (pair, first_pair))
        pending = None
    if not cycle_pairs:
        return scan_rate, None

    if len(cycle_pairs) < last_n:
        if log_func is not None:
            try:
                log_func(f"ECSA cycle count is below last_n; using available complete pairs: cycles={len(cycle_pairs)}, last_n={last_n}")
            except Exception:
                pass

    selected_pairs = cycle_pairs[-last_n:]
    up_selected = [pair[0] for pair in selected_pairs]
    down_selected = [pair[1] for pair in selected_pairs]
    up_current = np.array([_ecsa_interp_I(potential, current, pair, Ev) for pair in up_selected], float)
    down_current = np.array([_ecsa_interp_I(potential, current, pair, Ev) for pair in down_selected], float)
    anodic = np.nanmean(up_current) if avg_last_n else up_current[-1]
    cathodic = np.nanmean(down_current) if avg_last_n else down_current[-1]
    area = float(area_cm2)
    if not np.isfinite(area) or area <= 0:
        raise ValueError("geometric electrode area must be a finite value greater than zero")
    ja = (anodic * 1000.0) / area
    jc = (cathodic * 1000.0) / area
    delta_j = ja - jc
    if use_abs_delta:
        delta_j = abs(delta_j)
    return scan_rate, float(delta_j)


def fit_deltaJ_vs_v(v_list, dJ_list):
    """Fit ΔJ = slope * scan_rate + intercept."""
    scan_rate = np.asarray(v_list, float)
    delta_j = np.asarray(dJ_list, float)
    if scan_rate.ndim != 1 or delta_j.ndim != 1 or scan_rate.shape != delta_j.shape:
        return None, None, None
    mask = np.isfinite(scan_rate) & np.isfinite(delta_j) & (scan_rate > 0)
    scan_rate = scan_rate[mask]
    delta_j = delta_j[mask]
    if scan_rate.size < 2:
        return None, None, None
    # Replicates at a single rate cannot identify both slope and intercept.
    # Also reject variation too small to distinguish from roundoff.
    spread = float(np.ptp(scan_rate))
    resolution = np.finfo(float).eps * float(np.max(np.abs(scan_rate))) * 32.0
    if spread <= resolution:
        return None, None, None
    slope, intercept = np.polyfit(scan_rate, delta_j, 1)
    if not np.isfinite(slope) or not np.isfinite(intercept):
        return None, None, None
    fitted = slope * scan_rate + intercept
    ss_res = float(np.sum((delta_j - fitted) ** 2))
    ss_tot = float(np.sum((delta_j - np.mean(delta_j)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return float(slope), float(intercept), float(r2)


def _to_mF_per_cm2(value: float, unit: str) -> float:
    """Normalize capacitance unit input to mF/cm2."""
    normalized = (unit or "").strip().lower()
    numeric_value = as_float(value, 0.0)
    if normalized in ["mf/cm2", "mf/cm²", "mf"]:
        return numeric_value
    if normalized in ["uf/cm2", "uf/cm²", "uf", "μf/cm2", "μf/cm²", "µf/cm2", "µf/cm²", "mu f/cm2"]:
        return numeric_value / 1000.0
    return numeric_value


def calculate_ecsa_fit(
    *,
    v_list: Sequence[float],
    dJ_list: Sequence[float],
    area_cm2: float,
    cs_value: Any = 40.0,
    cs_unit: str = "µF/cm²",
) -> EcsaFitResult | None:
    """Calculate Cdl, ECSA, and roughness factor from ΔJ data."""
    slope, intercept, r2 = fit_deltaJ_vs_v(v_list, dJ_list)
    if slope is None or intercept is None or r2 is None:
        return None

    finite_delta = np.asarray(dJ_list, dtype=float)
    finite_delta = finite_delta[np.isfinite(finite_delta)]
    resolution = np.finfo(float).eps * float(np.max(np.abs(finite_delta))) * 32.0
    if slope <= 0 or float(np.ptp(finite_delta)) <= resolution:
        raise ValueError(
            "ECSA requires a distinguishable positive DeltaJ-versus-scan-rate slope; "
            f"observed slope={slope:.12g} mF/cm2, intercept={intercept:.12g} mA/cm2, R2={r2:.12g}. "
            "Inspect the scan-rate series and evaluation potential; no Cdl, RF or ECSA is reported."
        )

    cdl_mFcm2 = slope / 2.0
    cs_input = as_float(cs_value, 40.0)
    cs_mFcm2 = _to_mF_per_cm2(cs_input, cs_unit)
    if not np.isfinite(area_cm2) or area_cm2 <= 0:
        raise ValueError("geometric electrode area must be a finite value greater than zero")
    if not np.isfinite(cs_mFcm2) or cs_mFcm2 <= 0:
        raise ValueError("specific capacitance must be a finite value greater than zero")
    # Both Cdl and Cs are areal capacitances.  Their ratio is therefore the
    # dimensionless roughness factor; ECSA is RF multiplied by geometric area.
    rf = cdl_mFcm2 / cs_mFcm2
    ecsa_cm2 = rf * area_cm2
    return EcsaFitResult(
        slope_mFcm2=slope,
        intercept=intercept,
        r2=r2,
        cdl_mFcm2=cdl_mFcm2,
        cs_input=cs_input,
        cs_unit=cs_unit,
        cs_mFcm2=cs_mFcm2,
        ecsa_cm2=ecsa_cm2,
        rf=rf,
    )


__all__ = [
    "EcsaFitResult",
    "_ecsa_find_pairs",
    "_ecsa_interp_I",
    "_to_mF_per_cm2",
    "calculate_ecsa_fit",
    "compute_deltaJ_for_file",
    "fit_deltaJ_vs_v",
]
