"""Plotting helpers for LSV processing."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import matplotlib.pyplot as plt
import numpy as np

from .processing_common import apply_plot_font, save_current_figure, serialized_plotting
from .processing_lsv_metrics import fit_tafel_data
from .utils import as_int


@dataclass(frozen=True)
class LsvCurvePlotResult:
    """Result metadata produced while rendering an LSV curve."""

    image_path: str
    tafel_fit_data: dict[str, Any] | None = None


def _add_ext_segments(ext_segments: Sequence[tuple[Any, Any, str]]) -> None:
    for E_ext, I_ext, method in ext_segments:
        try:
            plt.plot(E_ext, I_ext, linestyle="--", linewidth=1.2, label=f"extrapolated: {method}")
        except Exception:
            continue


def _add_target_markers(
    target_currents: Sequence[float],
    target_potentials: Mapping[float, float],
) -> None:
    for target_current in target_currents:
        if target_current not in target_potentials:
            continue
        target_pot = target_potentials[target_current]
        plt.plot(
            target_pot,
            target_current,
            "ro",
            markersize=8,
            label=f"{target_current} mA/cm² @ {target_pot:.3f} V",
        )
        plt.annotate(
            f"{target_current} mA/cm²\n{target_pot:.3f} V",
            xy=(target_pot, target_current),
            xytext=(10, 10),
            textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="yellow", alpha=0.7),
            arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=0"),
        )


def _add_tafel_overlay(
    potential,
    current,
    params: Mapping[str, Any],
    *,
    logger: Any | None = None,
    ir_compensation: float | None = None,
) -> dict[str, Any] | None:
    if not params.get("tafel_enabled"):
        return None
    try:
        data = fit_tafel_data(potential, current, params.get("tafel_range", "1-10"), logger=logger)
        if data is None:
            return None
        label = "Tafel fit: {:.1f} mV/dec, R²={:.3f}".format(data["slope_mVdec"], data["r2"])
        plt.plot(data["E_fit"], data["I_fit"], "r-.", linewidth=1.5, label=label)
        plt.scatter(data["E_data"], data["I_data"], c="red", s=20, zorder=5, label="Tafel used points")
        if ir_compensation is not None:
            data["ir_compensation"] = ir_compensation
        return data
    except (ValueError, TypeError) as exc:
        if logger is not None:
            logger.debug("LSV Tafel overlay skipped: %s", exc)
        return None


@serialized_plotting
def plot_lsv_curve(
    *,
    potential,
    current,
    target_currents: Sequence[float],
    target_potentials: Mapping[float, float],
    ext_segments: Sequence[tuple[Any, Any, str]],
    params: Mapping[str, Any],
    title: str,
    image_path: str,
    font_name: str,
    curve_label: str = "LSV curve",
    logger: Any | None = None,
    enable_tafel_overlay: bool = False,
    ir_compensation: float | None = None,
) -> LsvCurvePlotResult:
    """Render an LSV curve image and return optional Tafel fit metadata."""
    plt.figure(figsize=(8, 6))
    apply_plot_font(plt, font_name)

    plt.plot(
        potential,
        current,
        color=params.get("line_color", "blue"),
        linewidth=params.get("line_width", 2.0),
        label=curve_label,
    )

    if ext_segments:
        _add_ext_segments(ext_segments)

    if params.get("mark_targets", True):
        _add_target_markers(target_currents, target_potentials)

    tafel_fit_data = None
    if enable_tafel_overlay:
        tafel_fit_data = _add_tafel_overlay(
            potential,
            current,
            params,
            logger=logger,
            ir_compensation=ir_compensation,
        )

    plt.xlabel(params["xlabel"])
    plt.ylabel(params["ylabel"])
    plt.title(title, fontname=font_name, fontsize=as_int(params.get("fontsize", 12), 12))
    if params.get("plot_grid", True):
        plt.grid(True, alpha=0.3)
    if (params.get("mark_targets", True) and target_potentials) or tafel_fit_data is not None:
        plt.legend()
    plt.tight_layout()
    save_current_figure(plt, image_path)

    return LsvCurvePlotResult(image_path=image_path, tafel_fit_data=tafel_fit_data)


@serialized_plotting
def export_lsv_tafel_plot(
    *,
    output_dir: str,
    sample_name: str,
    file_stem: str,
    params: Mapping[str, Any],
    font_name: str,
    tafel_fit_original: Mapping[str, Any] | None = None,
    tafel_fit_ir: Mapping[str, Any] | None = None,
    log_func: Any | None = None,
) -> str | None:
    """Export the standalone Tafel plot when fit data is available."""
    if not params.get("export_tafel_plot", False):
        if log_func is not None:
            log_func("未启用Tafel图导出功能")
        return None
    data = tafel_fit_ir or tafel_fit_original
    if data is None:
        if log_func is not None:
            log_func("警告：未找到可用的Tafel拟合数据！")
            log_func("请确保：1) 勾选了'计算Tafel斜率' 2) 如需准确结果，建议同时启用IR补偿功能")
        return None

    is_ir = tafel_fit_ir is not None
    if log_func is not None:
        if is_ir:
            log_func("找到IR补偿Tafel拟合数据，开始生成IR补偿Tafel图...")
        else:
            log_func("未找到IR补偿数据，使用原始数据生成Tafel图（建议启用IR补偿获得更准确结果）...")

    try:
        plt.figure(figsize=(8, 6))
        apply_plot_font(plt, font_name)

        log_j_data = np.log10(np.clip(data["I_data"], 1e-12, None))
        log_j_fit = np.log10(np.clip(data["I_fit"], 1e-12, None))
        label_prefix = "IR-compensated" if is_ir else "Original"
        plt.scatter(log_j_data, data["E_data"], c="blue", s=30, alpha=0.7, label=f"{label_prefix} Tafel data")
        plt.plot(
            log_j_fit,
            data["E_fit"],
            "r-",
            linewidth=2,
            label=f"Tafel fit: {data['slope_mVdec']:.1f} mV/dec, R²={data['r2']:.3f}",
        )
        plt.xlabel("log(j) [j in mA/cm²]")
        if is_ir:
            plt.ylabel("Potential (V, IR-compensated)")
            title = f'Tafel Plot (IR-compensated) - {sample_name}_{file_stem} (Rs={data["ir_compensation"]:.2f}Ω)'
            filename = f"{sample_name}_{file_stem}_Tafel_fit_IR.png"
        else:
            plt.ylabel("Potential (V)")
            title = f"Tafel Plot (Original Data) - {sample_name}_{file_stem}"
            filename = f"{sample_name}_{file_stem}_Tafel_fit.png"
        plt.title(title, fontname=font_name, fontsize=as_int(params.get("fontsize", 12), 12))
        if params.get("plot_grid", True):
            plt.grid(True, alpha=0.3)
        plt.legend()
        plt.tight_layout()
        output_path = os.path.join(output_dir, filename)
        save_current_figure(plt, output_path)
        if log_func is not None:
            log_func(f"Tafel拟合图已保存: {output_path}")
        return output_path
    except Exception as exc:
        if log_func is not None:
            log_func(f"导出Tafel图失败: {exc}")
        return None


@serialized_plotting
def plot_combined_lsv(
    series: Sequence[Mapping[str, Any]],
    *,
    output_path: str,
    params: Mapping[str, Any],
    font_name: str,
) -> str | None:
    """Render the optional all-sample LSV overlay used by batch runs."""
    valid = [item for item in series if item.get("potential") is not None and item.get("current") is not None]
    if not valid:
        return None
    plt.figure(figsize=(9, 6))
    apply_plot_font(plt, font_name)
    colors = plt.rcParams["axes.prop_cycle"].by_key().get("color", [])
    for index, item in enumerate(valid):
        color = colors[index % len(colors)] if colors else None
        plt.plot(
            item["potential"],
            item["current"],
            label=str(item.get("label") or item.get("file_stem") or f"series-{index + 1}"),
            linewidth=1.5,
            color=color,
        )
    plt.xlabel(str(params.get("lsv_xlabel") or params.get("xlabel") or "Potential (V)"))
    plt.ylabel(str(params.get("lsv_ylabel") or params.get("ylabel") or "Current Density (mA/cm2)"))
    plt.title("Combined LSV Curves")
    if params.get("plot_grid", True):
        plt.grid(True, alpha=0.3)
    plt.legend(fontsize=8, ncol=2)
    plt.tight_layout()
    save_current_figure(plt, output_path)
    return output_path


__all__ = ["LsvCurvePlotResult", "export_lsv_tafel_plot", "plot_combined_lsv", "plot_lsv_curve"]
