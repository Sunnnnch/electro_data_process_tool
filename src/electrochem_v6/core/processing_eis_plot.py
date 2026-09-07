"""Plotting helpers for EIS processing."""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

import matplotlib.pyplot as plt

from .processing_common import apply_plot_font, format_sample_title, save_current_figure, serialized_plotting
from .processing_eis_calc import compute_bode_arrays
from .utils import as_bool, as_float, as_int


@serialized_plotting
def plot_eis_nyquist(
    *,
    z_real: Sequence[float],
    z_imag: Sequence[float],
    params: Mapping[str, Any],
    sample_name: str,
    file_stem: str,
    output_dir: str,
    font_name: str,
    randles_result: Mapping[str, Any] | None = None,
) -> str:
    """Render the Nyquist plot."""
    plt.figure(figsize=(8, 6))
    apply_plot_font(plt, font_name)
    z_imag_neg = [-val for val in z_imag]
    plt.plot(
        z_real,
        z_imag_neg,
        marker="o",
        color=params.get("line_color", "blue"),
        linewidth=as_float(params.get("line_width", 2.0), 2.0),
        markersize=4,
        label="Measured data",
    )

    if randles_result:
        plt.plot(
            randles_result["z_fit_real"],
            [-v for v in randles_result["z_fit_imag"]],
            "--",
            color="red",
            linewidth=1.5,
            label=f"{randles_result.get('model_label', 'Circuit')} fit (R2={randles_result['r2']:.4f})",
        )
        annotation = (
            f"Rs={randles_result['Rs']:.2f} Ohm\n"
            f"Rct={randles_result['Rct']:.2f} Ohm\n"
        )
        if randles_result.get("model") == "randles_cpe":
            annotation += f"Q={randles_result['Q']:.2e} S*s^n\nn={randles_result['n']:.3f}"
        else:
            annotation += f"Cdl={randles_result['Cdl']:.2e} F"
        plt.annotate(
            annotation,
            xy=(0.97, 0.97),
            xycoords="axes fraction",
            ha="right",
            va="top",
            fontsize=9,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", alpha=0.8),
        )
        plt.legend(fontsize=9)

    plt.xlabel(params["xlabel"])
    plt.ylabel(params["ylabel"])
    plt.title(
        format_sample_title(params["title"], sample_name),
        fontname=font_name,
        fontsize=as_int(params.get("fontsize", 12), 12),
    )
    if as_bool(params.get("plot_grid", True), True):
        plt.grid(True, alpha=0.3)
    plt.axis("equal")
    plt.tight_layout()
    return save_current_figure(plt, os.path.join(output_dir, f"{sample_name}_{file_stem}_EIS_Nyquist.png"))


@serialized_plotting
def plot_eis_bode(
    *,
    frequency: Sequence[float],
    z_real: Sequence[float],
    z_imag: Sequence[float],
    params: Mapping[str, Any],
    sample_name: str,
    file_stem: str,
    output_dir: str,
    font_name: str,
) -> str:
    """Render the Bode magnitude/phase plot."""
    z_mag, z_phase = compute_bode_arrays(z_real, z_imag)
    _fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 10))
    apply_plot_font(plt, font_name)
    line_width = as_float(params.get("line_width", 2.0), 2.0)
    base_title = format_sample_title(params["title"], sample_name)

    ax1.loglog(
        frequency,
        z_mag,
        marker="o",
        color=params.get("line_color", "blue"),
        linewidth=line_width,
        markersize=4,
    )
    ax1.set_xlabel("Frequency (Hz)", fontname=font_name)
    ax1.set_ylabel("|Z| (Ohm)", fontname=font_name)
    ax1.set_title(f"{base_title} - Magnitude", fontname=font_name, fontsize=as_int(params.get("fontsize", 12), 12))
    if as_bool(params.get("plot_grid", True), True):
        ax1.grid(True, alpha=0.3)

    ax2.semilogx(
        frequency,
        z_phase,
        marker="o",
        color=params.get("line_color", "blue"),
        linewidth=line_width,
        markersize=4,
    )
    ax2.set_xlabel("Frequency (Hz)", fontname=font_name)
    ax2.set_ylabel("Phase (deg)", fontname=font_name)
    ax2.set_title(f"{base_title} - Phase", fontname=font_name, fontsize=as_int(params.get("fontsize", 12), 12))
    if as_bool(params.get("plot_grid", True), True):
        ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    return save_current_figure(plt, os.path.join(output_dir, f"{sample_name}_{file_stem}_EIS_Bode.png"))


__all__ = ["plot_eis_bode", "plot_eis_nyquist"]
