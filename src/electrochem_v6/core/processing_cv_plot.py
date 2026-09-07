"""Plotting helpers for CV processing."""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

import matplotlib.pyplot as plt

from .processing_common import apply_plot_font, format_sample_title, save_current_figure, serialized_plotting
from .processing_cv_calc import CvPeak
from .utils import as_bool, as_float, as_int


def _add_peak_annotations(peaks: Sequence[CvPeak]) -> None:
    for peak in peaks:
        color = "red" if peak.kind == "max" else "green"
        marker = "^" if peak.kind == "max" else "v"
        try:
            plt.plot([peak.potential], [peak.current], marker=marker, color=color, markersize=8)
            plt.annotate(
                f"{peak.kind}: {peak.current:.1f} mA\nE={peak.potential:.3f} V",
                xy=(peak.potential, peak.current),
                xytext=(10, 10),
                textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.7),
            )
        except Exception:
            continue


def _add_delta_ep_annotation(delta_ep: float | None) -> None:
    if delta_ep is None:
        return
    try:
        plt.annotate(
            f"ΔEp = {delta_ep * 1000:.1f} mV",
            xy=(0.03, 0.03),
            xycoords="axes fraction",
            fontsize=10,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", alpha=0.8),
        )
    except Exception:
        pass


@serialized_plotting
def plot_cv_curve(
    *,
    potential: Sequence[float],
    current: Sequence[float],
    peaks: Sequence[CvPeak],
    delta_ep: float | None,
    params: Mapping[str, Any],
    sample_name: str,
    file_stem: str,
    output_dir: str,
    font_name: str,
) -> str:
    """Render a CV curve image."""
    plt.figure(figsize=(8, 6))
    apply_plot_font(plt, font_name)
    plt.plot(
        potential,
        current,
        color=params.get("line_color", "blue"),
        linewidth=as_float(params.get("line_width", 2.0), 2.0),
    )
    plt.xlabel(params["xlabel"])
    plt.ylabel(params["ylabel"])
    plt.title(
        format_sample_title(params["title"], sample_name),
        fontname=font_name,
        fontsize=as_int(params.get("fontsize", 12), 12),
    )
    if as_bool(params.get("plot_grid", True), True):
        plt.grid(True, alpha=0.3)
    _add_peak_annotations(peaks)
    _add_delta_ep_annotation(delta_ep)
    plt.tight_layout()
    return save_current_figure(plt, os.path.join(output_dir, f"{sample_name}_{file_stem}_CV.png"))


__all__ = ["plot_cv_curve"]
