"""Plotting helpers for EIS processing."""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

import matplotlib.pyplot as plt
import numpy as np

from .processing_common import apply_plot_font, format_sample_title, save_current_figure, serialized_plotting
from .processing_eis_calc import compute_bode_arrays
from .utils import as_bool, as_float, as_int


def _fit_label(result):
    state = "not accepted" if result.get("accepted") is False else "review required" if result.get("review_required") else "fit"
    return f"{result.get('model_label', 'Circuit')} — {state} (R2={result.get('r2', 0):.4f})"


def _fit_color(result):
    return "#a45b00" if result.get("review_required") or result.get("accepted") is False else "#b52632"


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

    if randles_result and randles_result.get("z_fit_real"):
        fit_real = np.asarray(randles_result["z_fit_real"])
        fit_imag = np.asarray(randles_result["z_fit_imag"])
        fit_frequency = randles_result.get("frequency_hz")
        order = np.argsort(fit_frequency, kind="stable") if fit_frequency else np.arange(len(fit_real))
        plt.plot(
            fit_real[order],
            -fit_imag[order],
            "--",
            color=_fit_color(randles_result),
            linewidth=1.5,
            label=_fit_label(randles_result),
        )
        units = randles_result.get("parameter_units") or {}
        order = randles_result.get("parameter_order") or [key for key in ("Rs", "Rct", "Cdl", "Q", "n") if key in randles_result]
        annotation = "\n".join(f"{key}={randles_result[key]:.4g} {units.get(key, '')}" for key in order)
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
    fit_result: Mapping[str, Any] | None = None,
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
        label="Measured data (all points)",
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
        label="Measured data (all points)",
    )
    ax2.set_xlabel("Frequency (Hz)", fontname=font_name)
    ax2.set_ylabel("Phase (deg)", fontname=font_name)
    ax2.set_title(f"{base_title} - Phase", fontname=font_name, fontsize=as_int(params.get("fontsize", 12), 12))
    if as_bool(params.get("plot_grid", True), True):
        ax2.grid(True, alpha=0.3)

    if fit_result and fit_result.get("z_fit_real") and fit_result.get("frequency_hz"):
        fit_f = np.asarray(fit_result["frequency_hz"], dtype=float)
        order = np.argsort(fit_f, kind="stable")
        mag, phase = compute_bode_arrays(fit_result["z_fit_real"], fit_result["z_fit_imag"])
        color = _fit_color(fit_result)
        ax1.loglog(fit_f[order], np.asarray(mag)[order], "--", color=color, label=_fit_label(fit_result))
        ax2.semilogx(fit_f[order], np.asarray(phase)[order], "--", color=color, label="Circuit fit (selected frequencies)")
        ax1.legend(fontsize=8)
        ax2.legend(fontsize=8)

    plt.tight_layout()
    return save_current_figure(plt, os.path.join(output_dir, f"{sample_name}_{file_stem}_EIS_Bode.png"))


@serialized_plotting
def plot_eis_residuals(*, frequency: Sequence[float], fit_result: Mapping[str, Any] | None,
                       kk_validation: Mapping[str, Any] | None, params: Mapping[str, Any],
                       sample_name: str, file_stem: str, output_dir: str, font_name: str) -> str:
    """Show signed real/imaginary residuals, distinguishing Ohms from relative KK error."""
    rows = []
    if fit_result and fit_result.get("residual_real_ohm"):
        rows.append((fit_result, "residual_real_ohm", "residual_imag_ohm", 1.0,
                     "Measured - fit (Ohm)", _fit_label(fit_result)))
    if kk_validation and kk_validation.get("residual_real"):
        rows.append((kk_validation, "residual_real", "residual_imag", 100.0,
                     "KK residual / |Z| (%)", f"Lin-KK: {kk_validation.get('status')} (heuristic consistency check)"))
    if not rows:
        raise ValueError("No EIS residual values are available to plot")
    _fig, axes = plt.subplots(len(rows), 1, figsize=(9, 4 * len(rows)), squeeze=False)
    apply_plot_font(plt, font_name)
    f = np.asarray(frequency, dtype=float)
    order = np.argsort(f, kind="stable")
    for ax, (values, real_key, imag_key, scale, ylabel, title) in zip(axes[:, 0], rows):
        real = np.asarray(values[real_key], dtype=float) * scale
        imag = np.asarray(values[imag_key], dtype=float) * scale
        ax.semilogx(f[order], real[order], "o-", color="#245994", markersize=3, label="Real")
        ax.semilogx(f[order], imag[order], "s-", color="#a34c10", markersize=3, label="Imaginary")
        ax.axhline(0, color="#555555", linewidth=.8)
        ax.set_xlabel("Frequency (Hz) — selected interval")
        ax.set_ylabel(ylabel)
        ax.set_title(title, fontsize=10)
        ax.legend(fontsize=9)
        if as_bool(params.get("plot_grid", True), True):
            ax.grid(True, alpha=.25)
    plt.suptitle(f"{sample_name}/{file_stem} — EIS residual review", fontsize=12)
    plt.tight_layout()
    return save_current_figure(plt, os.path.join(output_dir, f"{sample_name}_{file_stem}_EIS_Residuals.png"))


__all__ = ["plot_eis_bode", "plot_eis_nyquist", "plot_eis_residuals"]
