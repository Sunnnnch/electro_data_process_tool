"""EIS processing helpers extracted from the shared processing core."""
from __future__ import annotations

import os
from datetime import datetime

import matplotlib.pyplot as plt
import numpy as np

from . import processing_core_v6 as core
from .utils import read_file_with_fallback_encodings

_resolve_plot_font = core._resolve_plot_font
HISTORY_MANAGER_AVAILABLE = core.HISTORY_MANAGER_AVAILABLE
PROJECT_MANAGER_AVAILABLE = core.PROJECT_MANAGER_AVAILABLE
get_history_manager = core.get_history_manager
get_project_manager = core.get_project_manager
log = core.log


def _randles_impedance(freq_arr, Rs, Rct, Cdl):
    """Calculate impedance of simplified Randles circuit: Rs + Rct/(1 + j*w*Rct*Cdl)."""
    omega = 2.0 * np.pi * freq_arr
    Z_faradaic = Rct / (1.0 + 1j * omega * Rct * Cdl)
    Z_total = Rs + Z_faradaic
    return Z_total


def fit_randles(freq, z_real, z_imag):
    """Fit simplified Randles circuit (Rs + Rct||Cdl) to EIS data.

    Returns dict with Rs, Rct, Cdl and fitted Z arrays, or None on failure.
    """
    from scipy.optimize import curve_fit

    freq_arr = np.asarray(freq, dtype=float)
    z_real_arr = np.asarray(z_real, dtype=float)
    z_imag_arr = np.asarray(z_imag, dtype=float)

    # Stack real and imaginary parts for fitting
    z_data = np.concatenate([z_real_arr, z_imag_arr])

    def _model(freq_repeated, Rs, Rct, Cdl):
        n = len(freq_repeated) // 2
        f = freq_repeated[:n]
        Z = _randles_impedance(f, Rs, Rct, Cdl)
        return np.concatenate([Z.real, Z.imag])

    freq_stack = np.concatenate([freq_arr, freq_arr])

    # Initial guesses
    Rs0 = float(np.min(z_real_arr))
    Rct0 = float(np.max(z_real_arr) - np.min(z_real_arr))
    if Rct0 <= 0:
        Rct0 = 1.0
    Cdl0 = 1e-5

    try:
        popt, _ = curve_fit(
            _model, freq_stack, z_data,
            p0=[Rs0, Rct0, Cdl0],
            bounds=([0, 0, 1e-12], [np.inf, np.inf, 1.0]),
            maxfev=10000,
        )
    except Exception:
        return None

    Rs_fit, Rct_fit, Cdl_fit = popt
    Z_fit = _randles_impedance(freq_arr, Rs_fit, Rct_fit, Cdl_fit)

    # R² goodness-of-fit
    z_complex = z_real_arr + 1j * z_imag_arr
    ss_res = np.sum(np.abs(z_complex - Z_fit) ** 2)
    ss_tot = np.sum(np.abs(z_complex - np.mean(z_complex)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return {
        'Rs': float(Rs_fit),
        'Rct': float(Rct_fit),
        'Cdl': float(Cdl_fit),
        'r2': float(r2),
        'z_fit_real': Z_fit.real.tolist(),
        'z_fit_imag': Z_fit.imag.tolist(),
    }

def process_eis(subfolder, file, params):
    """处理EIS数据文件 - v3.0.4: 支持奈奎斯特图和波特图"""
    filepath = os.path.join(subfolder, file)
    subname = os.path.basename(subfolder)
    file_stem = os.path.splitext(os.path.basename(file))[0]
    output_dir = str(params.get("output_dir") or subfolder)
    os.makedirs(output_dir, exist_ok=True)

    lines = read_file_with_fallback_encodings(filepath, start_line=int(params['start_line']))

    if lines is None:
        log(f"无法读取EIS文件 {filepath}，尝试了所有编码格式")
        return

    # v3.0.4: 读取频率、实阻抗和虚阻抗数据
    freq, z_real, z_imag = [], [], []
    for line in lines:
        parts = line.strip().replace(',', ' ').split()
        if len(parts) >= 3:
            try:
                freq.append(float(parts[0]))     # 频率 Hz
                z_real.append(float(parts[1]))   # Z' 实阻抗
                z_imag.append(float(parts[2]))   # Z'' 虚阻抗
            except (ValueError, TypeError):
                continue

    if not z_real or not z_imag or not freq:
        return

    # 设置当前图形的中文字体支持
    font_to_use = _resolve_plot_font(params.get('font'))
    plt.rcParams['font.sans-serif'] = [font_to_use]
    plt.rcParams['axes.unicode_minus'] = False

    # v3.0.4: 根据用户选择绘制图形
    plot_nyquist = params.get('plot_nyquist', True)
    plot_bode = params.get('plot_bode', False)
    randles_fit_enabled = params.get('randles_fit', False)

    # Attempt Randles fit if enabled
    randles_result = None
    if randles_fit_enabled:
        try:
            randles_result = fit_randles(freq, z_real, z_imag)
            if randles_result and randles_result['r2'] < 0.5:
                log(f"Randles fit R²={randles_result['r2']:.3f} 过低，丢弃拟合结果")
                randles_result = None
        except Exception as exc:
            log(f"Randles 拟合失败 {file}: {exc}")

    if plot_nyquist:
        # 绘制奈奎斯特图
        plt.figure(figsize=(8, 6))
        z_imag_neg = [-val for val in z_imag]  # 标准Nyquist图（上半圆）
        plt.plot(z_real, z_imag_neg, marker='o',
                 color=params.get('line_color', 'blue'),
                 linewidth=params.get('line_width', 2.0),
                 markersize=4, label='实测数据')

        # Overlay Randles fit curve on Nyquist plot
        if randles_result:
            plt.plot(randles_result['z_fit_real'],
                     [-v for v in randles_result['z_fit_imag']],
                     '--', color='red', linewidth=1.5,
                     label=f"Randles fit (R²={randles_result['r2']:.4f})")
            annotation = (
                f"Rs={randles_result['Rs']:.2f} Ω\n"
                f"Rct={randles_result['Rct']:.2f} Ω\n"
                f"Cdl={randles_result['Cdl']:.2e} F"
            )
            plt.annotate(annotation, xy=(0.97, 0.97), xycoords='axes fraction',
                         ha='right', va='top', fontsize=9,
                         bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow', alpha=0.8))
            plt.legend(fontsize=9)

        plt.xlabel(params['xlabel'])
        plt.ylabel(params['ylabel'])
        plt.title(params['title'].replace("{sample}", subname),
                  fontname=font_to_use, fontsize=int(params['fontsize']))
        if params.get('plot_grid', True):
            plt.grid(True, alpha=0.3)
        plt.axis('equal')  # 等比例坐标轴，更好地显示圆弧
        plt.tight_layout()
        try:
            plt.savefig(os.path.join(output_dir, f"{subname}_{file_stem}_EIS_Nyquist.png"), dpi=300, bbox_inches='tight')
        finally:
            plt.close()

    if plot_bode:
        # 绘制波特图（幅值图和相位图）
        import numpy as np

        # 计算阻抗模长和相位
        z_mag = [np.sqrt(real**2 + imag**2) for real, imag in zip(z_real, z_imag)]
        z_phase = [np.arctan2(imag, real) * 180 / np.pi for real, imag in zip(z_real, z_imag)]

        # 创建包含两个子图的图形
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 10))

        # 幅值图 (上方)
        ax1.loglog(freq, z_mag, marker='o',
                   color=params.get('line_color', 'blue'),
                   linewidth=params.get('line_width', 2.0),
                   markersize=4)
        ax1.set_xlabel('频率 (Hz)', fontname=font_to_use)
        ax1.set_ylabel('|Z| (Ω)', fontname=font_to_use)
        ax1.set_title(f"{params['title'].replace('{sample}', subname)} - 幅值图",
                      fontname=font_to_use, fontsize=int(params['fontsize']))
        if params.get('plot_grid', True):
            ax1.grid(True, alpha=0.3)

        # 相位图 (下方)
        ax2.semilogx(freq, z_phase, marker='o',
                     color=params.get('line_color', 'blue'),
                     linewidth=params.get('line_width', 2.0),
                     markersize=4)
        ax2.set_xlabel('频率 (Hz)', fontname=font_to_use)
        ax2.set_ylabel('相位 (°)', fontname=font_to_use)
        ax2.set_title(f"{params['title'].replace('{sample}', subname)} - 相位图",
                      fontname=font_to_use, fontsize=int(params['fontsize']))
        if params.get('plot_grid', True):
            ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        try:
            plt.savefig(os.path.join(output_dir, f"{subname}_{file_stem}_EIS_Bode.png"), dpi=300, bbox_inches='tight')
        finally:
            plt.close()

    # ✅ 添加：保存EIS历史记录
    if HISTORY_MANAGER_AVAILABLE:
        try:
            history_mgr = get_history_manager()

            # 计算Rs（如果IR补偿启用）
            Rs = None
            Rct = None
            Cdl = None
            if randles_result:
                Rs = randles_result['Rs']
                Rct = randles_result['Rct']
                Cdl = randles_result['Cdl']
            elif params.get('ir_enabled'):
                if len(z_real) > 0:
                    Rs = min(z_real)

            # 构建历史记录
            record = {
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'sample_name': subname,
                'file_name': file_stem,
                'file_path': filepath,
                'type': 'EIS',
                'status': 'success',
                'results': {
                    'Rs': float(Rs) if Rs is not None else None,
                    'Rct': float(Rct) if Rct is not None else None,
                    'Cdl': float(Cdl) if Cdl is not None else None,
                    'randles_r2': float(randles_result['r2']) if randles_result else None,
                    'frequency_range': f"{min(freq):.2e} - {max(freq):.2e} Hz",
                    'data_points': len(freq)
                }
            }
            if params.get('run_id'):
                record['run_id'] = params.get('run_id')

            # 添加项目信息
            if 'project_id' in params and params['project_id']:
                record['project_id'] = params['project_id']

                if PROJECT_MANAGER_AVAILABLE:
                    try:
                        proj_mgr = get_project_manager()
                        proj = proj_mgr.get_project(params['project_id'])
                        if proj:
                            record['project_name'] = proj['name']
                    except Exception:
                        pass

            history_mgr.add_record(record)
            log(f"EIS历史记录已保存: {subname}/{file_stem}")

        except Exception as e:
            log(f"保存EIS历史记录失败: {e}")
