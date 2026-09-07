"""Calculation helpers for CV processing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from .utils import as_bool, as_float, as_int


def _log_warning(logger: Any | None, message: str, *args: Any) -> None:
    if logger is None:
        return
    text = message % args if args else message
    if hasattr(logger, "warning"):
        logger.warning(message, *args)
    elif callable(logger):
        logger(text)


@dataclass(frozen=True)
class CvPeak:
    """A detected anodic or cathodic CV peak."""

    kind: str
    index: int
    potential: float
    current: float


@dataclass(frozen=True)
class CvMetrics:
    """Derived CV metrics used by plots and history records."""

    peaks: list[CvPeak]
    delta_ep: float | None = None
    charge_mC: float | None = None

    @property
    def delta_ep_mV(self) -> float | None:
        return round(self.delta_ep * 1000.0, 1) if self.delta_ep is not None else None

    @property
    def charge_mC_rounded(self) -> float | None:
        return round(self.charge_mC, 4) if self.charge_mC is not None else None


@dataclass(frozen=True)
class CvCycle:
    """One CV cycle returning to its starting potential after both sweep directions."""

    number: int
    start_index: int
    end_index: int
    potential: list[float]
    current: list[float]


def parse_cycle_selection(value: Any) -> list[int]:
    """Parse cycle selectors like ``1``, ``1,3`` or ``2-4`` into 1-based indexes."""
    text = str(value or "").strip()
    if not text:
        return []
    normalized = (
        text.replace("，", ",")
        .replace("、", ",")
        .replace("；", ",")
        .replace(";", ",")
        .replace("–", "-")
        .replace("—", "-")
    )
    selected: list[int] = []
    for part in normalized.split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            left, right = item.split("-", 1)
            try:
                start = int(left.strip())
                end = int(right.strip())
            except ValueError:
                continue
            if start <= 0 or end <= 0:
                continue
            if end < start:
                start, end = end, start
            for number in range(start, end + 1):
                if number not in selected:
                    selected.append(number)
            continue
        try:
            number = int(item)
        except ValueError:
            continue
        if number > 0 and number not in selected:
            selected.append(number)
    return selected


def _cycle_reversal_tolerance(values: np.ndarray, requested: Any = None) -> float:
    """Resolve a reversal hysteresis that suppresses one-point potential jitter."""
    requested_value = as_float(requested, 0.0)
    if requested_value > 0 and math.isfinite(requested_value):
        return requested_value
    span = float(np.ptp(values))
    if not math.isfinite(span) or span <= 0:
        return 0.0
    steps = np.abs(np.diff(values))
    steps = steps[np.isfinite(steps) & (steps > 0)]
    typical_step = float(np.median(steps)) if steps.size else 0.0
    return max(span * 0.002, min(typical_step * 1.5, span * 0.05))


def split_cv_cycles(
    potential: Sequence[float],
    current: Sequence[float],
    *,
    reversal_tolerance: Any = None,
    min_segment_points: Any = 3,
) -> list[CvCycle]:
    """Split full CV cycles using hysteretic potential-direction reversals."""
    if len(potential) != len(current) or len(potential) < 3:
        return []
    values = np.asarray(potential, dtype=float)
    if not np.all(np.isfinite(values)):
        return []
    tolerance = _cycle_reversal_tolerance(values, reversal_tolerance)
    if tolerance <= 0:
        return []
    minimum_points = max(2, as_int(min_segment_points, 3))

    turning_points: list[int] = []
    direction = 0
    segment_start = 0
    extreme_index = 0
    extreme_value = float(values[0])

    for idx in range(1, len(values)):
        value = float(values[idx])
        if direction == 0:
            delta = value - float(values[segment_start])
            if abs(delta) < tolerance:
                continue
            direction = 1 if delta > 0 else -1
            extreme_index = idx
            extreme_value = value
            continue

        if direction > 0:
            if value >= extreme_value:
                extreme_index = idx
                extreme_value = value
                continue
            reversed_enough = extreme_value - value >= tolerance
        else:
            if value <= extreme_value:
                extreme_index = idx
                extreme_value = value
                continue
            reversed_enough = value - extreme_value >= tolerance

        segment_is_long_enough = extreme_index - segment_start + 1 >= minimum_points
        if not reversed_enough or not segment_is_long_enough:
            continue
        turning_points.append(extreme_index)
        segment_start = extreme_index
        direction *= -1
        extreme_index = idx
        extreme_value = value

    if not turning_points:
        return []

    initial_potential = float(values[0])
    initial_direction = 1 if values[turning_points[0]] > initial_potential else -1
    starting_extreme = float(np.min(values) if initial_direction > 0 else np.max(values))
    starts_at_extreme = abs(initial_potential - starting_extreme) <= tolerance
    cycle_ends: list[int] = []
    if starts_at_extreme:
        # A window-boundary start closes after the outward and return sweeps.
        cycle_ends = turning_points[1::2]
        if len(turning_points) % 2 and abs(float(values[-1]) - initial_potential) <= tolerance:
            cycle_ends.append(len(values) - 1)
    else:
        # An interior start needs both reversals and the final return to E0.
        # Pairing only two sweep segments would stop at the second vertex and
        # silently omit the final part of the cycle.
        for offset in range(1, len(turning_points), 2):
            vertex = turning_points[offset]
            limit = turning_points[offset + 1] if offset + 1 < len(turning_points) else len(values) - 1
            closing = next(
                (idx for idx in range(vertex + 1, limit + 1)
                 if initial_direction * (float(values[idx]) - initial_potential) >= 0),
                None,
            )
            if closing is None and limit == len(values) - 1 and abs(float(values[-1]) - initial_potential) <= tolerance:
                closing = limit
            if closing is not None:
                cycle_ends.append(closing)

    cycles: list[CvCycle] = []
    cycle_number = 1
    start = 0
    for end in cycle_ends:
        if end <= start:
            continue
        cycles.append(
            CvCycle(
                number=cycle_number,
                start_index=start,
                end_index=end,
                potential=[float(item) for item in potential[start : end + 1]],
                current=[float(item) for item in current[start : end + 1]],
            )
        )
        cycle_number += 1
        start = end
    return cycles


def _smooth_current(current: np.ndarray, window: int) -> np.ndarray:
    if window < 1:
        window = 1
    if window % 2 == 0:
        window += 1
    if window <= 1:
        return current
    kernel = np.ones(window) / window
    return np.convolve(current, kernel, mode="same")


def detect_cv_peaks(
    potential: Sequence[float],
    current: Sequence[float],
    *,
    enabled: bool = False,
    smooth_window: Any = 5,
    min_height: Any = 1.0,
    min_distance: Any = 5,
    max_peaks: Any = 2,
    logger: Any | None = None,
) -> list[CvPeak]:
    """Detect major positive and negative CV peaks."""
    if not enabled:
        return []
    try:
        x = np.asarray(potential, dtype=float)
        y = np.asarray(current, dtype=float)
        if x.size < 3 or y.size < 3 or x.size != y.size:
            return []

        y_smooth = _smooth_current(y, as_int(smooth_window, 5))
        height = as_float(min_height, 1.0)
        distance = as_int(min_distance, 5)
        limit = max(0, as_int(max_peaks, 2))

        dy = np.diff(y_smooth)
        sign = np.sign(dy)
        zero_crossings = np.diff(sign)
        candidates_max = np.where(zero_crossings < 0)[0] + 1
        candidates_min = np.where(zero_crossings > 0)[0] + 1

        candidates: list[CvPeak] = []
        for idx in candidates_max:
            if 0 < idx < len(y_smooth) - 1 and y_smooth[idx] >= height:
                candidates.append(CvPeak("max", int(idx), float(x[idx]), float(y_smooth[idx])))
        for idx in candidates_min:
            if 0 < idx < len(y_smooth) - 1 and -y_smooth[idx] >= height:
                candidates.append(CvPeak("min", int(idx), float(x[idx]), float(y_smooth[idx])))

        candidates.sort(key=lambda peak: abs(peak.current), reverse=True)
        selected: list[CvPeak] = []
        for peak in candidates:
            if all(abs(peak.index - existing.index) >= distance for existing in selected):
                selected.append(peak)
            if len(selected) >= limit:
                break
        return selected
    except Exception as exc:
        _log_warning(logger, "CV peak detection failed; continuing: %s", exc)
        return []


def compute_delta_ep(potential: Sequence[float], peaks: Sequence[CvPeak]) -> float | None:
    """Calculate anodic/cathodic peak separation from detected peaks."""
    maxes = [peak for peak in peaks if peak.kind == "max"]
    mins = [peak for peak in peaks if peak.kind == "min"]
    if not maxes or not mins:
        return None
    try:
        return abs(float(potential[maxes[0].index]) - float(potential[mins[0].index]))
    except Exception:
        return None


def compute_charge_mC(
    potential: Sequence[float],
    current: Sequence[float],
    *,
    scan_rate_v_s: Any = None,
) -> float | None:
    """Integrate absolute current over elapsed time for a constant scan rate.

    CV files handled by this module contain potential and current, but no time
    vector.  For a constant scan rate, each time increment is
    ``abs(dE) / scan_rate``.  Current is expressed in mA, so ``mA * s`` is mC.
    A missing scan rate intentionally returns ``None`` instead of reporting the
    dimensionally incorrect curve area ``integral |I| dE`` as charge.
    """
    try:
        pot_arr = np.asarray(potential, dtype=float)
        cur_arr = np.asarray(current, dtype=float)
        scan_rate = as_float(scan_rate_v_s, 0.0)
        if pot_arr.size < 2 or cur_arr.size != pot_arr.size or scan_rate <= 0:
            return None
        finite = np.isfinite(pot_arr) & np.isfinite(cur_arr)
        pot_arr = pot_arr[finite]
        cur_arr = cur_arr[finite]
        if pot_arr.size < 2:
            return None
        elapsed_s = np.concatenate(
            ([0.0], np.cumsum(np.abs(np.diff(pot_arr)) / scan_rate))
        )
        trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz", None)
        if trapz is None:
            return None
        return float(trapz(np.abs(cur_arr), elapsed_s))
    except Exception:
        return None


def compute_cv_metrics(
    potential: Sequence[float],
    current: Sequence[float],
    params: Mapping[str, Any],
    *,
    logger: Any | None = None,
) -> CvMetrics:
    """Compute optional CV peak metrics and charge integration."""
    peaks_enabled = as_bool(params.get("peaks_enabled", False), False)
    peaks = detect_cv_peaks(
        potential,
        current,
        enabled=peaks_enabled,
        smooth_window=params.get("peaks_smooth", 5),
        min_height=params.get("peaks_min_height", 1.0),
        min_distance=params.get("peaks_min_dist", 5),
        max_peaks=params.get("peaks_max", 2),
        logger=logger,
    )
    return CvMetrics(
        peaks=peaks,
        delta_ep=compute_delta_ep(potential, peaks) if peaks_enabled else None,
        charge_mC=compute_charge_mC(
            potential,
            current,
            scan_rate_v_s=params.get("scan_rate_v_s", params.get("cv_scan_rate_v_s")),
        ),
    )


__all__ = [
    "CvMetrics",
    "CvPeak",
    "CvCycle",
    "compute_charge_mC",
    "compute_cv_metrics",
    "compute_delta_ep",
    "detect_cv_peaks",
    "parse_cycle_selection",
    "split_cv_cycles",
]
