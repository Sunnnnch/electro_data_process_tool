"""CV processing helpers extracted from the shared processing core."""
from __future__ import annotations

import os
from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd

from . import processing_core_v6 as core
from .processing_quality import DataQualityChecker

_resolve_plot_font = core._resolve_plot_font
HISTORY_MANAGER_AVAILABLE = core.HISTORY_MANAGER_AVAILABLE
PROJECT_MANAGER_AVAILABLE = core.PROJECT_MANAGER_AVAILABLE
get_history_manager = core.get_history_manager
get_project_manager = core.get_project_manager
log = core.log

def process_cv(subfolder, file, params, enable_quality_check=True):
    """处理CV数据文件"""
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
        print(f"无法读取CV文件 {filepath}，尝试了所有编码格式")
        return

    potential, current = [], []
    for line in lines:
        parts = line.strip().replace(',', ' ').split()
        if len(parts) >= 2:
            try:
                potential.append(float(parts[0]))
                current.append(float(parts[1]) * 1000)
            except:
                continue

    if not potential or not current:
        return

    cv_quality_report = None
    if enable_quality_check:
        try:
            df = pd.DataFrame({
                'Potential': potential,
                'Current': current,
            })
            display_name = f"{subname}/{file}" if subname else file
            cv_quality_report = DataQualityChecker.check_cv_data(
                df,
                display_name,
                config=params.get('quality_config'),
            )
        except Exception as exc:
            log(f"CV质量检查异常（继续处理）: {exc}")

    plt.figure(figsize=(8, 6))
    # 设置当前图形的中文字体支持
    font_to_use = _resolve_plot_font(params.get('font'))
    plt.rcParams['font.sans-serif'] = [font_to_use]
    plt.rcParams['axes.unicode_minus'] = False

    plt.plot(potential, current,
             color=params.get('line_color', 'blue'),
             linewidth=params.get('line_width', 2.0))
    plt.xlabel(params['xlabel'])
    plt.ylabel(params['ylabel'])
    # 使用支持中文的字体
    font_to_use = _resolve_plot_font(params.get('font'))
    plt.title(params['title'].replace("{sample}", subname),
              fontname=font_to_use, fontsize=int(params['fontsize']))
    if params.get('plot_grid', True):
        plt.grid(True, alpha=0.3)
    # 峰值检测（可选，基础版）
    if params.get('peaks_enabled'):
        import numpy as _np
        x = _np.asarray(potential, dtype=float)
        y = _np.asarray(current, dtype=float)
        try:
            w = int(params.get('peaks_smooth', 5))
            if w < 1: w = 1
            if w % 2 == 0: w += 1
            if w > 1:
                k = _np.ones(w) / w
                y_s = _np.convolve(y, k, mode='same')
            else:
                y_s = y
            min_h = float(params.get('peaks_min_height', 1.0))
            min_dist = int(params.get('peaks_min_dist', 5))
            max_n = int(params.get('peaks_max', 2))
            # 简单极大/极小点检测
            dy = _np.diff(y_s)
            sgn = _np.sign(dy)
            zc = _np.diff(sgn)
            cand_max = _np.where(zc < 0)[0] + 1
            cand_min = _np.where(zc > 0)[0] + 1
            peaks = []
            for idx in cand_max:
                if 0 < idx < len(y_s)-1 and y_s[idx] >= min_h:
                    peaks.append(('max', idx, y_s[idx]))
            for idx in cand_min:
                if 0 < idx < len(y_s)-1 and -y_s[idx] >= min_h:
                    peaks.append(('min', idx, y_s[idx]))
            # 依据绝对电流排序并应用最小点距
            peaks.sort(key=lambda t: abs(t[2]), reverse=True)
            sel = []
            for p in peaks:
                if all(abs(p[1]-q[1]) >= min_dist for q in sel):
                    sel.append(p)
                if len(sel) >= max_n:
                    break
            # 标注
            for kind, idxp, yp in sel:
                xp = x[idxp]
                color = 'red' if kind=='max' else 'green'
                marker = '^' if kind=='max' else 'v'
                try:
                    plt.plot([xp],[yp], marker=marker, color=color, markersize=8)
                    plt.annotate(f"{kind}: {yp:.1f} mA\nE={xp:.3f} V",
                                 xy=(xp, yp), xytext=(10,10), textcoords='offset points',
                                 bbox=dict(boxstyle='round,pad=0.2', fc='white', alpha=0.7))
                except Exception:
                    pass
        except Exception:
            pass

    plt.tight_layout()
    # 避免覆盖：包含源文件名
    plt.savefig(os.path.join(subfolder, f"{subname}_{file_stem}_CV.png"), dpi=300, bbox_inches='tight')
    plt.close()
    
    # ✅ 添加：保存CV历史记录
    if HISTORY_MANAGER_AVAILABLE:
        try:
            history_mgr = get_history_manager()
            
            # 构建历史记录
            record = {
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'sample_name': subname,
                'file_name': file_stem,
                'file_path': filepath,
                'type': 'CV',
                'status': 'success',
                'results': {
                    'data_points': len(potential),
                    'potential_range': f"{min(potential):.3f} - {max(potential):.3f} V",
                    'current_range': f"{min(current):.2f} - {max(current):.2f} mA"
                }
            }
            if params.get('run_id'):
                record['run_id'] = params.get('run_id')
            
            # 尝试添加项目信息
            if 'project_id' in params and params['project_id']:
                record['project_id'] = params['project_id']
                
                # 获取项目名称
                if PROJECT_MANAGER_AVAILABLE:
                    try:
                        proj_mgr = get_project_manager()
                        proj = proj_mgr.get_project(params['project_id'])
                        if proj:
                            record['project_name'] = proj['name']
                    except:
                        pass
            
            history_mgr.add_record(record)
            log(f"CV历史记录已保存: {subname}/{file_stem}")
            
        except Exception as e:
            log(f"保存CV历史记录失败: {e}")

    return {
        'quality_report': cv_quality_report,
    }
