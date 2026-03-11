"""EIS processing helpers extracted from the shared processing core."""
from __future__ import annotations

import os
from datetime import datetime

import matplotlib.pyplot as plt

from . import processing_core_v6 as core

_resolve_plot_font = core._resolve_plot_font
HISTORY_MANAGER_AVAILABLE = core.HISTORY_MANAGER_AVAILABLE
PROJECT_MANAGER_AVAILABLE = core.PROJECT_MANAGER_AVAILABLE
get_history_manager = core.get_history_manager
get_project_manager = core.get_project_manager
log = core.log

def process_eis(subfolder, file, params):
    """处理EIS数据文件 - v3.0.4: 支持奈奎斯特图和波特图"""
    filepath = os.path.join(subfolder, file)
    subname = os.path.basename(subfolder)
    file_stem = os.path.splitext(os.path.basename(file))[0]

    encodings = ['utf-8', 'gbk', 'gb2312', 'ascii', 'latin-1', 'cp1252']
    lines = None

    for encoding in encodings:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                lines = f.readlines()[int(params['start_line']) - 1:]
            break
        except UnicodeDecodeError:
            continue

    if lines is None:
        print(f"无法读取EIS文件 {filepath}，尝试了所有编码格式")
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
    
    if plot_nyquist:
        # 绘制奈奎斯特图
        plt.figure(figsize=(8, 6))
        z_imag_neg = [-val for val in z_imag]  # 标准Nyquist图（上半圆）
        plt.plot(z_real, z_imag_neg, marker='o',
                 color=params.get('line_color', 'blue'),
                 linewidth=params.get('line_width', 2.0),
                 markersize=4)
        plt.xlabel(params['xlabel'])
        plt.ylabel(params['ylabel'])
        plt.title(params['title'].replace("{sample}", subname),
                  fontname=font_to_use, fontsize=int(params['fontsize']))
        if params.get('plot_grid', True):
            plt.grid(True, alpha=0.3)
        plt.axis('equal')  # 等比例坐标轴，更好地显示圆弧
        plt.tight_layout()
        plt.savefig(os.path.join(subfolder, f"{subname}_{file_stem}_EIS_Nyquist.png"), dpi=300, bbox_inches='tight')
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
        plt.savefig(os.path.join(subfolder, f"{subname}_{file_stem}_EIS_Bode.png"), dpi=300, bbox_inches='tight')
        plt.close()
    
    # ✅ 添加：保存EIS历史记录
    if HISTORY_MANAGER_AVAILABLE:
        try:
            history_mgr = get_history_manager()
            
            # 计算Rs（如果IR补偿启用）
            Rs = None
            Rct = None
            if params.get('ir_enabled'):
                # 简单估算Rs（高频实部）
                if len(z_real) > 0:
                    Rs = min(z_real)  # 高频端的实阻抗近似为Rs
            
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
