"""Metric calculation helpers for LSV processing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from .processing_lsv_calc import _parse_tafel_range, parse_target_currents, potential_at_current
from .utils import as_bool, as_float


@dataclass(frozen=True)
class LsvTargetPotentialResult:
    """Target-current potential values plus extrapolation plot segments."""

    potentials: dict[float, float]
    ext_segments: list[tuple[Any, Any, str]]


@dataclass(frozen=True)
class LsvOptionalMetrics:
    """Optional LSV metrics controlled by UI/user parameters."""

    onset_potential: float | None = None
    onset_overpotential_mV: float | None = None
    halfwave_potential: float | None = None
    tafel_slope_mVdec: float | None = None


def _finite_or_none(value: float) -> float | None:
    try:
        return None if value != value else float(value)
    except Exception:
        return None


def parse_float_param(value: Any, default: float = 0.0) -> float:
    """Parse a numeric parameter with a stable fallback."""
    return as_float(value, default)


def compute_target_potentials(
    potential,
    current,
    target_currents: Sequence[float],
    *,
    min_pts: int = 3,
    tafel_ratio: float = 3.0,
    max_extrap_factor: float = 2.0,
) -> LsvTargetPotentialResult:
    """Calculate potentials at target current densities."""
    potentials: dict[float, float] = {}
    ext_segments: list[tuple[Any, Any, str]] = []
    for target_current in target_currents:
        target_potential, ext = potential_at_current(
            potential,
            current,
            target_i=target_current,
            min_pts=min_pts,
            tafel_ratio=tafel_ratio,
            max_extrap_factor=max_extrap_factor,
        )
        if not np.isnan(target_potential):
            potentials[target_current] = target_potential
        if ext is not None:
            ext_segments.append(ext)
    return LsvTargetPotentialResult(potentials=potentials, ext_segments=ext_segments)


def compute_overpotentials(
    target_potentials: Mapping[float, float],
    equilibrium_potential: float,
) -> dict[float, float]:
    """Calculate absolute overpotentials in mV for target potentials."""
    overpotentials: dict[float, float] = {}
    for target_current, target_potential in target_potentials.items():
        try:
            overpotentials[target_current] = abs((float(target_potential) - equilibrium_potential) * 1000.0)
        except Exception:
            continue
    return overpotentials


def compute_onset_potential(potential, current, onset_current: Any = "1.0") -> float | None:
    """Calculate onset potential at the configured current threshold."""
    try:
        target_current = float(str(onset_current).replace(",", "."))
    except Exception:
        target_current = 1.0
    onset, _ = potential_at_current(
        potential,
        current,
        target_i=target_current,
        min_pts=3,
        tafel_ratio=3.0,
        max_extrap_factor=2.0,
    )
    return _finite_or_none(onset)


def compute_halfwave_potential(potential, current, halfwave_current: Any = None) -> float | None:
    """Calculate half-wave potential using explicit current or half of the 95th percentile current."""
    try:
        text = (halfwave_current or "").strip()
        if text:
            target_current = float(text)
        else:
            target_current = 0.5 * float(np.nanpercentile(np.asarray(current, dtype=float), 95))
    except Exception:
        return None
    if target_current <= 0:
        return None
    halfwave, _ = potential_at_current(
        potential,
        current,
        target_i=target_current,
        min_pts=3,
        tafel_ratio=3.0,
        max_extrap_factor=2.0,
    )
    return _finite_or_none(halfwave)


def compute_tafel_slope_mVdec(
    potential,
    current,
    tafel_range: Any = "1-10",
    *,
    logger: Any | None = None,
) -> float | None:
    """Calculate Tafel slope in mV/dec for the configured current range."""
    try:
        parsed_range = _parse_tafel_range(tafel_range)
        if not parsed_range:
            if logger is not None:
                logger.warning("Invalid Tafel range: %s", tafel_range)
            raise ValueError("invalid tafel_range")
        lo, hi = parsed_range
        I = np.asarray(current, dtype=float)
        E = np.asarray(potential, dtype=float)
        mask = np.isfinite(I) & np.isfinite(E) & (I > 0) & (I >= min(lo, hi)) & (I <= max(lo, hi))
        if mask.sum() < 3:
            return None
        x = np.log10(np.clip(I[mask], 1e-12, None))
        y = E[mask]
        b, _a = np.polyfit(x, y, 1)
        return float(b * 1000.0)
    except Exception:
        return None


def compute_optional_metrics(
    *,
    params: Mapping[str, Any],
    potential,
    current,
    potential_for_tafel=None,
    equilibrium_potential: float = 0.0,
    overpotential_enabled: bool = False,
    logger: Any | None = None,
) -> LsvOptionalMetrics:
    """Calculate optional metrics enabled by user parameters."""
    onset_potential = None
    onset_overpotential = None
    if params.get("onset_enabled"):
        onset_potential = compute_onset_potential(potential, current, params.get("onset_current", "1.0"))
        if overpotential_enabled and onset_potential is not None:
            onset_overpotential = abs((onset_potential - equilibrium_potential) * 1000.0)

    halfwave_potential = None
    if params.get("halfwave_enabled"):
        halfwave_potential = compute_halfwave_potential(potential, current, params.get("halfwave_current"))

    tafel_slope = None
    if params.get("tafel_enabled"):
        tafel_potential = potential_for_tafel if potential_for_tafel is not None else potential
        tafel_slope = compute_tafel_slope_mVdec(
            tafel_potential,
            current,
            params.get("tafel_range", "1-10"),
            logger=logger,
        )

    return LsvOptionalMetrics(
        onset_potential=onset_potential,
        onset_overpotential_mV=onset_overpotential,
        halfwave_potential=halfwave_potential,
        tafel_slope_mVdec=tafel_slope,
    )


def build_lsv_result_row(
    *,
    sample_name: str,
    file_stem: str,
    target_currents: Sequence[float],
    target_potentials_original: Mapping[float, float],
    target_potentials_compensated: Mapping[float, float] | None = None,
    ir_compensation: float | None = None,
    ir_columns_enabled: bool = False,
    target_overpotentials_original: Mapping[float, float] | None = None,
    overpotential_enabled: bool = False,
    optional_metrics: LsvOptionalMetrics | None = None,
    onset_enabled: bool = False,
    halfwave_enabled: bool = False,
    tafel_enabled: bool = False,
) -> list[Any]:
    """Build the LSV summary row in the same order expected by the CSV writer."""
    row: list[Any] = [sample_name, file_stem]
    for target_current in target_currents:
        row.append(target_potentials_original.get(target_current, None))

    compensated_targets = target_potentials_compensated or {}
    if ir_columns_enabled:
        for target_current in target_currents:
            row.append(compensated_targets.get(target_current, None))
        row.append(ir_compensation)

    if overpotential_enabled:
        overpotentials = target_overpotentials_original or {}
        for target_current in target_currents:
            row.append(overpotentials.get(target_current, None))

    metrics = optional_metrics or LsvOptionalMetrics()
    if onset_enabled:
        row.append(metrics.onset_potential)
        if overpotential_enabled:
            row.append(metrics.onset_overpotential_mV)
    if halfwave_enabled:
        row.append(metrics.halfwave_potential)
    if tafel_enabled:
        row.append(metrics.tafel_slope_mVdec)
    return row


def build_lsv_result_columns(params: Mapping[str, Any]) -> list[str]:
    """Build LSV summary columns in the same order as ``build_lsv_result_row``."""
    target_currents = parse_target_currents(params.get("target_current", params.get("lsv_target_current", "10"))) or [10.0]
    columns = ["Sample_Name", "File_Name"]
    for target_current in target_currents:
        label = f"Potential@{target_current}mA/cm2"
        if as_bool(params.get("ir_compensation_enabled", False), False):
            label = f"{label}(Original)"
        columns.append(label)

    if as_bool(params.get("ir_compensation_enabled", False), False):
        for target_current in target_currents:
            columns.append(f"Potential@{target_current}mA/cm2(IR_compensated)")
        columns.append("R_solution(Ohm)")

    if as_bool(params.get("overpotential_enabled", False), False):
        try:
            eqv = float(params.get("eq_potential", 0.0))
        except Exception:
            eqv = 0.0
        for target_current in target_currents:
            columns.append(f"Overpotential@{target_current}mA/cm2(mV)@Eq={eqv}V")

    if as_bool(params.get("onset_enabled", False), False):
        try:
            onset_j = float(str(params.get("onset_current", "1.0")).replace(",", "."))
        except Exception:
            onset_j = 1.0
        columns.append(f"OnsetPotential@{onset_j}mA/cm2(V)")
        if as_bool(params.get("overpotential_enabled", False), False):
            try:
                eqv = float(params.get("eq_potential", 0.0))
            except Exception:
                eqv = 0.0
            columns.append(f"OnsetOverpotential(mV)@Eq={eqv}V")

    if as_bool(params.get("halfwave_enabled", False), False):
        columns.append("HalfWavePotential(V)")
    if as_bool(params.get("tafel_enabled", False), False):
        columns.append("TafelSlope(mV/dec)")
    return columns


__all__ = [
    "LsvOptionalMetrics",
    "LsvTargetPotentialResult",
    "build_lsv_result_row",
    "build_lsv_result_columns",
    "compute_halfwave_potential",
    "compute_onset_potential",
    "compute_optional_metrics",
    "compute_overpotentials",
    "compute_tafel_slope_mVdec",
    "compute_target_potentials",
    "parse_float_param",
]
