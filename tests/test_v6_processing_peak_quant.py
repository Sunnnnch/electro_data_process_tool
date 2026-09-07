from __future__ import annotations

import math

import numpy as np
import pytest

from electrochem_v6.core.processing_peak_quant import (
    PeakDefinition,
    PeakQuantificationOptions,
    _smoothed_for_detection,
    _trapezoid,
    quantify_peak,
    quantify_with_reference,
    read_signal_trace,
)


@pytest.mark.parametrize("legacy_name", [False, True])
def test_trapezoid_numpy_compatibility_preserves_nonuniform_signed_integral(monkeypatch, legacy_name):
    integration = getattr(np, "trapezoid", None) or getattr(np, "trapz")
    if legacy_name:
        monkeypatch.delattr(np, "trapezoid", raising=False)
        monkeypatch.setattr(np, "trapz", integration, raising=False)
    else:
        monkeypatch.setattr(np, "trapezoid", integration, raising=False)
        monkeypatch.delattr(np, "trapz", raising=False)
    x = np.array([0.0, 0.2, 1.4, 3.0])
    y = 2.0 * x + 1.0
    # Integral of 2x + 1 on [0, 3] is 12; reversing acquisition reverses its sign.
    assert _trapezoid(y, x) == pytest.approx(12.0)
    assert _trapezoid(y[::-1], x[::-1]) == pytest.approx(-12.0)


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_detection_smoothing_preserves_quadratic_signal_and_numpy_dtype(dtype):
    x = np.linspace(-1, 1, 31, dtype=dtype)
    y = 0.25 * x**2 + 2.0 * x + 3.0
    smoothed = _smoothed_for_detection(y)
    assert isinstance(smoothed, np.ndarray)
    assert smoothed.dtype == y.dtype
    assert smoothed.shape == y.shape
    np.testing.assert_allclose(smoothed, y, rtol=1e-6, atol=1e-6)


def _gaussian_area(x: np.ndarray, center: float, sigma: float, area: float) -> np.ndarray:
    return area * np.exp(-0.5 * ((x - center) / sigma) ** 2) / (sigma * math.sqrt(2.0 * math.pi))


def _shifted_trace() -> tuple[np.ndarray, np.ndarray]:
    x = np.linspace(0.0, 8.0, 16001)
    shift = 0.025
    y = 0.15 + 0.004 * x
    y += _gaussian_area(x, 6.30 + shift, 0.009, 2.0)
    y += _gaussian_area(x, 1.91 + shift, 0.010, 3.0)
    y += 0.0005 * np.sin(x * 171.0)
    return x, y


def test_reference_shift_moves_product_search_and_keeps_fixed_relative_window():
    x, y = _shifted_trace()
    reference = PeakDefinition("maleic_acid", 6.30, nuclei_count=2)
    acetate = PeakDefinition("acetate", 1.91, nuclei_count=3)

    reference_result, product_results, shift = quantify_with_reference(
        x,
        y,
        reference=reference,
        products=(acetate,),
    )

    product = product_results[0]
    assert reference_result.found_position == pytest.approx(6.325, abs=0.002)
    assert shift == pytest.approx(0.025, abs=0.002)
    assert product.aligned_expected_position == pytest.approx(1.935, abs=0.002)
    assert product.found_position == pytest.approx(1.935, abs=0.002)
    assert product.quantification_bounds[1] - product.quantification_bounds[0] == pytest.approx(0.10)
    assert product.area / reference_result.area == pytest.approx(1.5, rel=0.02)
    assert product.status == "pass"


def test_constrained_fit_returns_area_center_and_fit_quality():
    x, y = _shifted_trace()
    result = quantify_peak(
        x,
        y,
        PeakDefinition("acetate", 1.91, nuclei_count=3),
        aligned_expected_position=1.935,
        options=PeakQuantificationOptions(fit_enabled=True),
    )

    assert result.method == "pseudo_voigt_fit"
    assert result.found_position == pytest.approx(1.935, abs=0.002)
    assert result.area == pytest.approx(3.0, rel=0.05)
    assert result.fit_r2 is not None and result.fit_r2 > 0.99
    assert result.fit_parameters["width"] > 0


def test_read_signal_trace_sorts_descending_axis_and_ignores_header(tmp_path):
    path = tmp_path / "spectrum.csv"
    path.write_text(
        "ppm,intensity\n"
        "2.0,0.0\n"
        "1.8,1.0\n"
        "1.6,2.0\n"
        "1.4,3.0\n"
        "1.2,2.0\n"
        "1.0,1.0\n"
        "0.8,0.0\n",
        encoding="utf-8",
    )

    x, y = read_signal_trace(path)

    assert np.all(np.diff(x) > 0)
    assert x.tolist() == pytest.approx([0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0])
    assert y[np.argmax(y)] == pytest.approx(3.0)


def test_read_signal_trace_prefers_named_axes_over_numeric_index_column(tmp_path):
    path = tmp_path / "multi_column_spectrum.csv"
    path.write_text(
        "point,chemical_shift_ppm,intensity,unused\n"
        "1,2.0,0.0,10\n"
        "2,1.8,1.0,10\n"
        "3,1.6,2.0,10\n"
        "4,1.4,3.0,10\n"
        "5,1.2,2.0,10\n"
        "6,1.0,1.0,10\n"
        "7,0.8,0.0,10\n",
        encoding="utf-8",
    )

    x, y = read_signal_trace(path)

    assert x.tolist() == pytest.approx([0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0])
    assert y.tolist() == pytest.approx([0.0, 1.0, 2.0, 3.0, 2.0, 1.0, 0.0])
