"""Deterministic peak location and quantification for one-dimensional signals."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from scipy.signal import find_peaks, savgol_filter


class PeakQuantificationError(ValueError):
    """Raised when a signal or peak cannot be quantified reliably."""


@dataclass(frozen=True)
class PeakDefinition:
    """Method-level definition of one quantitative signal."""

    name: str
    expected_position: float
    nuclei_count: float = 1.0
    search_tolerance: float = 0.08
    window_left: float = 0.05
    window_right: float = 0.05
    polarity: str = "positive"

    def with_overrides(
        self,
        *,
        search_tolerance: float | None = None,
        window_left: float | None = None,
        window_right: float | None = None,
    ) -> "PeakDefinition":
        return replace(
            self,
            search_tolerance=self.search_tolerance if search_tolerance is None else float(search_tolerance),
            window_left=self.window_left if window_left is None else float(window_left),
            window_right=self.window_right if window_right is None else float(window_right),
        )


@dataclass(frozen=True)
class PeakQuantificationOptions:
    """Batch-level behavior shared by reference and product peaks."""

    auto_locate: bool = True
    reference_align: bool = True
    fit_enabled: bool = False
    min_detection_snr: float = 3.0
    min_quantification_snr: float = 10.0
    ambiguity_ratio: float = 0.85
    search_tolerance_override: float | None = None
    window_left_override: float | None = None
    window_right_override: float | None = None


@dataclass(frozen=True)
class PeakMeasurement:
    """Traceable result for one located and quantified peak."""

    name: str
    expected_position: float
    aligned_expected_position: float
    found_position: float
    search_bounds: tuple[float, float]
    quantification_bounds: tuple[float, float]
    area: float
    height: float
    snr: float
    candidate_count: int
    ambiguous: bool
    method: str
    status: str
    warnings: tuple[str, ...] = ()
    fit_r2: float | None = None
    fit_parameters: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "expected_position": self.expected_position,
            "aligned_expected_position": self.aligned_expected_position,
            "found_position": self.found_position,
            "position_shift": self.found_position - self.expected_position,
            "search_min": self.search_bounds[0],
            "search_max": self.search_bounds[1],
            "quantification_min": self.quantification_bounds[0],
            "quantification_max": self.quantification_bounds[1],
            "area": self.area,
            "height": self.height,
            "snr": self.snr,
            "candidate_count": self.candidate_count,
            "ambiguous": self.ambiguous,
            "method": self.method,
            "status": self.status,
            "warnings": list(self.warnings),
            "fit_r2": self.fit_r2,
            "fit_parameters": dict(self.fit_parameters),
        }


def _positive_float(value: Any, name: str) -> float:
    try:
        number = float(value)
    except Exception as exc:
        raise PeakQuantificationError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or number <= 0:
        raise PeakQuantificationError(f"{name} must be greater than 0")
    return number


def _trapezoid(y: np.ndarray, x: np.ndarray) -> float:
    function = getattr(np, "trapezoid", None)
    if function is None:
        # NumPy 1.x exposes trapz; newer NumPy releases remove that name.
        function = getattr(np, "trapz")
    return float(function(y, x))


def _read_delimited_frame(
    signal_path: Path,
    *,
    encoding: str,
    header: int | None,
) -> pd.DataFrame:
    frame = pd.read_csv(
        signal_path,
        sep=None,
        engine="python",
        header=header,
        comment="#",
        encoding=encoding,
    )
    if frame.shape[1] >= 2:
        return frame
    return pd.read_csv(
        signal_path,
        sep=r"[,;\t\s]+",
        engine="python",
        header=header,
        comment="#",
        encoding=encoding,
    )


def _signal_column_score(value: Any, *, axis: str) -> int:
    text = str(value or "").strip().lower()
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)
    exact = {
        "x": {"x", "ppm", "chemicalshift", "retentiontime", "time", "frequency", "wavenumber", "potential", "化学位移", "保留时间", "时间"},
        "y": {"y", "intensity", "signal", "response", "abundance", "absorbance", "current", "强度", "信号", "响应", "电流"},
    }
    tokens = {
        "x": ("ppm", "chemicalshift", "shift", "retentiontime", "frequency", "wavenumber", "potential", "time", "化学位移", "保留时间", "时间"),
        "y": ("intensity", "signal", "response", "abundance", "absorbance", "current", "detector", "强度", "信号", "响应", "电流"),
    }
    if compact in exact[axis]:
        return 100
    return max((60 - index for index, token in enumerate(tokens[axis]) if token in compact), default=0)


def _named_signal_pair(frame: pd.DataFrame) -> pd.DataFrame | None:
    x_candidates = sorted(
        ((_signal_column_score(column, axis="x"), index) for index, column in enumerate(frame.columns)),
        reverse=True,
    )
    y_candidates = sorted(
        ((_signal_column_score(column, axis="y"), index) for index, column in enumerate(frame.columns)),
        reverse=True,
    )
    for x_score, x_index in x_candidates:
        if x_score <= 0:
            break
        for y_score, y_index in y_candidates:
            if y_score <= 0:
                break
            if x_index == y_index:
                continue
            pair = frame.iloc[:, [x_index, y_index]].apply(pd.to_numeric, errors="coerce").dropna()
            if len(pair) >= 7:
                return pair
    return None


def read_signal_trace(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Read the two best numeric columns from a CSV/TSV/TXT signal export."""
    signal_path = Path(path)
    if not signal_path.is_file():
        raise PeakQuantificationError(f"signal file not found: {signal_path}")

    pair: pd.DataFrame | None = None
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            pair = _named_signal_pair(
                _read_delimited_frame(signal_path, encoding=encoding, header=0)
            )
            if pair is not None:
                break
        except UnicodeDecodeError as exc:
            last_error = exc
        except Exception as exc:
            last_error = exc

    if pair is None:
        frames: list[pd.DataFrame] = []
        for encoding in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
            try:
                frames.append(_read_delimited_frame(signal_path, encoding=encoding, header=None))
                break
            except UnicodeDecodeError as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc
        if not frames:
            raise PeakQuantificationError(f"failed to read signal file {signal_path}: {last_error}")

        numeric = frames[0].apply(pd.to_numeric, errors="coerce")
        best: tuple[int, int, int] | None = None
        columns = list(range(numeric.shape[1]))
        for left_index, left in enumerate(columns):
            for right in columns[left_index + 1 :]:
                count = int((numeric.iloc[:, left].notna() & numeric.iloc[:, right].notna()).sum())
                if best is None or count > best[0]:
                    best = (count, left, right)
        if best is None or best[0] < 7:
            raise PeakQuantificationError(f"signal file requires at least 7 numeric x/y rows: {signal_path}")
        pair = numeric.iloc[:, [best[1], best[2]]].dropna()

    assert pair is not None
    x = pair.iloc[:, 0].to_numpy(dtype=float)
    y = pair.iloc[:, 1].to_numpy(dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]
    y = y[finite]
    if x.size < 7:
        raise PeakQuantificationError(f"signal file requires at least 7 finite x/y rows: {signal_path}")

    order = np.argsort(x, kind="mergesort")
    x = x[order]
    y = y[order]
    unique_x, inverse = np.unique(x, return_inverse=True)
    if unique_x.size != x.size:
        sums = np.bincount(inverse, weights=y)
        counts = np.bincount(inverse)
        x = unique_x
        y = sums / counts
    if x.size < 7 or float(x[-1] - x[0]) <= 0:
        raise PeakQuantificationError(f"signal x axis is not usable: {signal_path}")
    return x, y


def estimate_noise_sigma(y: np.ndarray) -> float:
    """Estimate point noise robustly from first differences."""
    values = np.asarray(y, dtype=float)
    if values.size < 3:
        return 0.0
    differences = np.diff(values)
    median = float(np.median(differences))
    mad = float(np.median(np.abs(differences - median)))
    sigma = 1.4826 * mad / math.sqrt(2.0)
    if not math.isfinite(sigma) or sigma <= 0:
        sigma = float(np.std(differences) / math.sqrt(2.0))
    return sigma if math.isfinite(sigma) and sigma > 0 else 0.0


def _baseline_correct(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    edge_count = max(2, min(12, int(math.ceil(x.size * 0.12))))
    edge_indices = np.concatenate((np.arange(edge_count), np.arange(x.size - edge_count, x.size)))
    edge_x = x[edge_indices]
    edge_y = y[edge_indices]
    if np.ptp(edge_x) <= 0:
        baseline = np.full_like(y, float(np.median(edge_y)))
    else:
        slope, intercept = np.polyfit(edge_x, edge_y, 1)
        baseline = slope * x + intercept
    return y - baseline, baseline


def _oriented(values: np.ndarray, polarity: str) -> np.ndarray:
    normalized = str(polarity or "positive").strip().lower()
    if normalized == "negative":
        return -values
    if normalized != "positive":
        raise PeakQuantificationError(f"unsupported peak polarity: {polarity}")
    return values


def _smoothed_for_detection(values: np.ndarray) -> np.ndarray:
    if values.size < 7:
        return values
    window = min(11, values.size if values.size % 2 else values.size - 1)
    if window < 5:
        return values
    return np.asarray(savgol_filter(values, window_length=window, polyorder=min(2, window - 2), mode="interp"))


def _locate_peak(
    x: np.ndarray,
    y: np.ndarray,
    *,
    expected_position: float,
    tolerance: float,
    polarity: str,
    noise_sigma: float,
    options: PeakQuantificationOptions,
) -> tuple[float, int, bool, tuple[float, float]]:
    search_min = expected_position - tolerance
    search_max = expected_position + tolerance
    mask = (x >= search_min) & (x <= search_max)
    if int(mask.sum()) < 5:
        raise PeakQuantificationError(
            f"search window {search_min:.6g}..{search_max:.6g} contains fewer than 5 points"
        )
    search_x = x[mask]
    oriented = _oriented(y[mask], polarity)
    corrected, _baseline = _baseline_correct(search_x, oriented)
    detection_signal = _smoothed_for_detection(corrected)
    dynamic_span = max(0.0, float(np.max(detection_signal) - np.min(detection_signal)))
    prominence_floor = max(noise_sigma * options.min_detection_snr, dynamic_span * 0.01)
    candidates, properties = find_peaks(detection_signal, prominence=prominence_floor)
    if candidates.size == 0:
        candidates = np.asarray([int(np.argmax(detection_signal))], dtype=int)
        prominences = np.asarray([max(0.0, float(detection_signal[candidates[0]]))])
    else:
        prominences = np.asarray(properties.get("prominences"), dtype=float)

    scores: list[tuple[float, int]] = []
    for candidate, prominence in zip(candidates, prominences):
        distance_fraction = abs(float(search_x[candidate]) - expected_position) / max(tolerance, 1e-12)
        score = float(prominence) / (1.0 + 0.35 * distance_fraction)
        scores.append((score, int(candidate)))
    scores.sort(key=lambda item: item[0], reverse=True)
    chosen = scores[0]
    ambiguous = len(scores) > 1 and scores[1][0] >= chosen[0] * options.ambiguity_ratio
    return float(search_x[chosen[1]]), len(scores), ambiguous, (search_min, search_max)


def _pseudo_voigt(
    x: np.ndarray,
    area: float,
    center: float,
    width: float,
    eta: float,
    intercept: float,
    slope: float,
) -> np.ndarray:
    width = max(float(width), np.finfo(float).eps)
    gaussian = np.exp(-0.5 * ((x - center) / width) ** 2) / (width * math.sqrt(2.0 * math.pi))
    lorentzian = (width / math.pi) / ((x - center) ** 2 + width**2)
    return area * ((1.0 - eta) * gaussian + eta * lorentzian) + intercept + slope * (x - center)


def _fit_peak(x: np.ndarray, oriented_y: np.ndarray, initial_center: float) -> tuple[float, float, float, dict[str, float]]:
    corrected, baseline = _baseline_correct(x, oriented_y)
    initial_area = max(_trapezoid(corrected, x), float(np.max(corrected)) * max(np.ptp(x) / 5.0, 1e-12))
    step = float(np.median(np.diff(x)))
    span = float(np.ptp(x))
    initial_width = max(abs(step) * 2.0, span / 12.0)
    baseline_center = float(np.interp(initial_center, x, baseline))
    baseline_slope = float((baseline[-1] - baseline[0]) / span) if span > 0 else 0.0
    parameters, _covariance = curve_fit(
        _pseudo_voigt,
        x,
        oriented_y,
        p0=[initial_area, initial_center, initial_width, 0.5, baseline_center, baseline_slope],
        bounds=(
            [0.0, float(x[0]), max(abs(step) * 0.25, 1e-12), 0.0, -np.inf, -np.inf],
            [np.inf, float(x[-1]), max(span, abs(step)), 1.0, np.inf, np.inf],
        ),
        maxfev=30000,
    )
    predicted = _pseudo_voigt(x, *parameters)
    residual_sum = float(np.sum((oriented_y - predicted) ** 2))
    total_sum = float(np.sum((oriented_y - np.mean(oriented_y)) ** 2))
    r2 = 1.0 - residual_sum / total_sum if total_sum > 0 else 1.0
    area, center, width, eta, intercept, slope = [float(item) for item in parameters]
    return area, center, r2, {
        "width": width,
        "eta": eta,
        "baseline_intercept": intercept,
        "baseline_slope": slope,
    }


def quantify_peak(
    x: np.ndarray,
    y: np.ndarray,
    definition: PeakDefinition,
    *,
    aligned_expected_position: float | None = None,
    options: PeakQuantificationOptions | None = None,
    noise_sigma: float | None = None,
) -> PeakMeasurement:
    """Locate and quantify one peak using a method-locked relative window."""
    settings = options or PeakQuantificationOptions()
    method = definition.with_overrides(
        search_tolerance=settings.search_tolerance_override,
        window_left=settings.window_left_override,
        window_right=settings.window_right_override,
    )
    _positive_float(method.nuclei_count, "nuclei_count")
    tolerance = _positive_float(method.search_tolerance, "search_tolerance")
    window_left = _positive_float(method.window_left, "window_left")
    window_right = _positive_float(method.window_right, "window_right")
    expected = float(
        method.expected_position if aligned_expected_position is None else aligned_expected_position
    )
    noise = estimate_noise_sigma(y) if noise_sigma is None else max(0.0, float(noise_sigma))

    if settings.auto_locate:
        center, candidate_count, ambiguous, search_bounds = _locate_peak(
            x,
            y,
            expected_position=expected,
            tolerance=tolerance,
            polarity=method.polarity,
            noise_sigma=noise,
            options=settings,
        )
    else:
        center = expected
        candidate_count = 0
        ambiguous = False
        search_bounds = (expected - tolerance, expected + tolerance)

    quant_min = center - window_left
    quant_max = center + window_right
    mask = (x >= quant_min) & (x <= quant_max)
    if int(mask.sum()) < 7:
        raise PeakQuantificationError(
            f"{method.name}: quantification window {quant_min:.6g}..{quant_max:.6g} contains fewer than 7 points"
        )
    peak_x = x[mask]
    oriented_y = _oriented(y[mask], method.polarity)
    corrected, _baseline = _baseline_correct(peak_x, oriented_y)
    height = max(0.0, float(np.max(corrected)))
    snr = math.inf if noise <= 0 and height > 0 else (height / noise if noise > 0 else 0.0)

    fit_r2: float | None = None
    fit_parameters: dict[str, float] = {}
    if settings.fit_enabled:
        try:
            area, center, fit_r2, fit_parameters = _fit_peak(peak_x, oriented_y, center)
        except Exception as exc:
            raise PeakQuantificationError(f"{method.name}: constrained peak fit failed: {exc}") from exc
        quantification_method = "pseudo_voigt_fit"
    else:
        area = _trapezoid(corrected, peak_x)
        quantification_method = "fixed_window_integration"
    if not math.isfinite(area) or area <= 0:
        raise PeakQuantificationError(f"{method.name}: quantified peak area must be greater than 0")
    if snr < settings.min_detection_snr:
        raise PeakQuantificationError(
            f"{method.name}: peak SNR {snr:.3g} is below detection threshold {settings.min_detection_snr:.3g}"
        )

    warnings: list[str] = []
    if snr < settings.min_quantification_snr:
        warnings.append("below_quantification_snr")
    if ambiguous:
        warnings.append("ambiguous_candidates")
    if fit_r2 is not None and fit_r2 < 0.95:
        warnings.append("poor_fit")
    status = "warning" if warnings else "pass"
    return PeakMeasurement(
        name=method.name,
        expected_position=float(method.expected_position),
        aligned_expected_position=expected,
        found_position=float(center),
        search_bounds=search_bounds,
        quantification_bounds=(quant_min, quant_max),
        area=float(area),
        height=height,
        snr=float(snr),
        candidate_count=candidate_count,
        ambiguous=ambiguous,
        method=quantification_method,
        status=status,
        warnings=tuple(warnings),
        fit_r2=fit_r2,
        fit_parameters=fit_parameters,
    )


def quantify_with_reference(
    x: np.ndarray,
    y: np.ndarray,
    *,
    reference: PeakDefinition,
    products: tuple[PeakDefinition, ...],
    options: PeakQuantificationOptions | None = None,
) -> tuple[PeakMeasurement, tuple[PeakMeasurement, ...], float]:
    """Quantify a reference peak first, then apply its offset to product peaks."""
    settings = options or PeakQuantificationOptions()
    noise = estimate_noise_sigma(y)
    reference_result = quantify_peak(x, y, reference, options=settings, noise_sigma=noise)
    shift = (
        reference_result.found_position - reference.expected_position
        if settings.reference_align
        else 0.0
    )
    product_results = tuple(
        quantify_peak(
            x,
            y,
            product,
            aligned_expected_position=product.expected_position + shift,
            options=settings,
            noise_sigma=noise,
        )
        for product in products
    )
    all_results = (reference_result, *product_results)
    for left_index, left in enumerate(all_results):
        for right in all_results[left_index + 1 :]:
            overlap_min = max(left.quantification_bounds[0], right.quantification_bounds[0])
            overlap_max = min(left.quantification_bounds[1], right.quantification_bounds[1])
            if overlap_max > overlap_min + np.finfo(float).eps:
                raise PeakQuantificationError(
                    f"quantification windows overlap after peak location: {left.name} and {right.name}"
                )
    return reference_result, product_results, float(shift)


__all__ = [
    "PeakDefinition",
    "PeakMeasurement",
    "PeakQuantificationError",
    "PeakQuantificationOptions",
    "estimate_noise_sigma",
    "quantify_peak",
    "quantify_with_reference",
    "read_signal_trace",
]
