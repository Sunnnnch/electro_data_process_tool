"""Plotting helpers for ECSA processing."""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

import matplotlib.pyplot as plt
import numpy as np

from .processing_common import apply_plot_font, format_sample_title, save_current_figure, serialized_plotting
from .processing_ecsa_calc import EcsaFitResult
from .utils import as_bool, as_float, as_int


@serialized_plotting
def plot_ecsa_result(
    *,
    sample_name: str,
    output_dir: str,
    v_list: Sequence[float],
    dJ_list: Sequence[float],
    fit: EcsaFitResult,
    params: Mapping[str, Any],
    font_name: str,
    fontsize: Any = 12,
) -> str:
    """Render ECSA ΔJ versus scan-rate plot."""
    plt.figure(figsize=(7.5, 5.8))
    apply_plot_font(plt, font_name)
    plt.scatter(v_list, dJ_list, s=40)
    xs = np.linspace(min(v_list), max(v_list), 100)
    ys = fit.slope_mFcm2 * xs + fit.intercept
    plt.plot(xs, ys, linewidth=as_float(params.get("line_width", 2.0), 2.0))
    plt.xlabel(params.get("xlabel", "Scan rate v (V/s)"))
    plt.ylabel(params.get("ylabel", "ΔJ (mA/cm²)"))
    title = format_sample_title(
        params.get("title", "ECSA of {sample} @ Ev={Ev:.3f} V"),
        sample_name,
        Ev=as_float(params.get("ev", 0.10), 0.10),
    )
    plt.title(title, fontname=font_name, fontsize=as_int(fontsize, 12))
    if as_bool(params.get("plot_grid", True), True):
        plt.grid(True, alpha=0.3)

    annotation = (
        f"slope = {fit.slope_mFcm2:.4f} mF/cm²\n"
        f"Cdl = slope/2 = {fit.cdl_mFcm2:.4f} mF/cm²\n"
        f"Cs = {fit.cs_input} {fit.cs_unit}\n"
        f"ECSA = {fit.ecsa_cm2:.3f} cm²\n"
        f"RF = {fit.rf:.3f}\n"
        f"R² = {fit.r2:.4f}"
    )
    plt.annotate(
        annotation,
        xy=(0.02, 0.98),
        xycoords="axes fraction",
        va="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7),
    )
    plt.tight_layout()
    out_png = os.path.join(output_dir, f"{sample_name}_ECSA.png")
    return save_current_figure(plt, out_png)


__all__ = ["plot_ecsa_result"]
