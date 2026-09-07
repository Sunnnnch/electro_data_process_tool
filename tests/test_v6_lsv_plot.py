"""Tests for LSV plotting helpers."""

from __future__ import annotations

import matplotlib
import numpy as np

from electrochem_v6.core.processing_lsv_plot import plot_lsv_curve

matplotlib.use("Agg")


def test_plot_lsv_curve_writes_image_and_tafel_data(tmp_path):
    potential = np.linspace(0.2, 0.8, 80)
    current = np.linspace(1.0, 20.0, 80)
    image_path = tmp_path / "lsv.png"

    result = plot_lsv_curve(
        potential=potential,
        current=current,
        target_currents=[10.0],
        target_potentials={10.0: 0.5},
        ext_segments=[],
        params={
            "line_color": "blue",
            "line_width": 2.0,
            "mark_targets": True,
            "tafel_enabled": True,
            "tafel_range": "1-20",
            "xlabel": "Potential (V)",
            "ylabel": "Current (mA/cm2)",
            "fontsize": "12",
            "plot_grid": True,
        },
        title="LSV",
        image_path=str(image_path),
        font_name="DejaVu Sans",
        enable_tafel_overlay=True,
    )

    assert image_path.exists()
    assert image_path.stat().st_size > 0
    assert result.image_path == str(image_path)
    assert result.tafel_fit_data is not None
    assert result.tafel_fit_data["slope_mVdec"] == result.tafel_fit_data["slope_mVdec"]
