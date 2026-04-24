"""ECSA processing helpers extracted from the shared processing core."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import matplotlib.pyplot as plt
import numpy as np

from . import processing_core_v6 as core

CHINESE_FONT = core.CHINESE_FONT
natural_sort_key = core.natural_sort_key
_matches_named_file = core._matches_named_file
_resolve_plot_font = core._resolve_plot_font
HISTORY_MANAGER_AVAILABLE = core.HISTORY_MANAGER_AVAILABLE
PROJECT_MANAGER_AVAILABLE = core.PROJECT_MANAGER_AVAILABLE
get_history_manager = core.get_history_manager
get_project_manager = core.get_project_manager
log = core.log

def _ecsa_read_text_lines(filepath: str):
    encodings = ['utf-8', 'gbk', 'gb2312', 'ascii', 'latin-1', 'cp1252']
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return f.readlines()
        except (UnicodeDecodeError, UnicodeError):
            continue
    # Last resort: lossy read with latin-1 (never fails)
    with open(filepath, 'r', encoding='latin-1') as f:
        return f.readlines()

def _ecsa_extract_v_from_content(lines):
    pat = re.compile(r"scan\s*rate\s*\(\s*V/s\s*\)\s*[:=]\s*([0-9.+-eE]+)", re.IGNORECASE)
    for ln in lines:
        m = pat.search(ln)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None

def _normalize_token(value: str) -> str:
    return re.sub(r'[^a-z0-9]', '', value.lower())

def _extract_sample_token(lsv_filename: str) -> Optional[str]:
    """Derive a sample identifier from the LSV file name."""
    stem = Path(lsv_filename).stem
    stem = re.sub(r'(?i)(?:[_\-\s]*(lsv|polarization|scan|lsvscan|lsvdata))+$', '', stem).strip('_- ')
    token = _normalize_token(stem)
    return token or None

def _match_eis_by_sample(files_in_folder: List[str], sample_token: str) -> Optional[str]:
    """Try to locate an EIS file whose name contains the same sample token."""
    if not sample_token:
        return None
    best_candidate = None
    for f in files_in_folder:
        lower = f.lower()
        if not (lower.endswith('.txt') or lower.endswith('.csv')):
            continue
        stem_token = _normalize_token(Path(f).stem)
        if sample_token in stem_token and 'eis' in stem_token:
            if stem_token.endswith(sample_token + 'eis') or stem_token.endswith('eis' + sample_token):
                return f
            if best_candidate is None:
                best_candidate = f
    return best_candidate

def _ecsa_extract_v_from_name(filename: str):
    name = os.path.basename(filename)
    m = re.search(r"ECSA[^0-9]*([0-9]+)\b", name, re.IGNORECASE)
    if m:
        return float(m.group(1))/1000.0
    m = re.search(r"([0-9]+)\s*mV\s*/?s", name, re.IGNORECASE)
    if m:
        return float(m.group(1))/1000.0
    m = re.search(r"([0-9.]+)\s*V\s*/?s", name, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None

def _ecsa_read_cv_table(filepath: str):
    lines = _ecsa_read_text_lines(filepath)
    start_idx = None
    for i, ln in enumerate(lines):
        ll = ln.lower()
        if 'potential' in ll and 'current' in ll:
            start_idx = i+1
            break
    if start_idx is None:
        start_idx = 0
    E, I = [], []
    for ln in lines[start_idx:]:
        s = ln.strip().replace(',', ' ').split()
        if len(s) >= 2:
            try:
                e = float(s[0]); i = float(s[1])
                E.append(e); I.append(i)
            except Exception:
                continue
    return np.asarray(E, float), np.asarray(I, float), lines

def _ecsa_find_pairs(E: np.ndarray, Ev: float):
    up, dn = [], []
    for k in range(len(E)-1):
        e1, e2 = E[k], E[k+1]
        if (e1 - Ev)*(e2 - Ev) <= 0 and e1 != e2:
            if e2 > e1: up.append((k,k+1))
            elif e2 < e1: dn.append((k,k+1))
    return up, dn

def _ecsa_interp_I(E: np.ndarray, I: np.ndarray, pair, Ev: float):
    i, j = pair
    e1, e2 = E[i], E[j]; i1, i2 = I[i], I[j]
    if e2 == e1: return (i1+i2)/2.0
    t = (Ev-e1)/(e2-e1)
    return i1 + t*(i2-i1)

def compute_deltaJ_for_file(filepath: str, Ev: float, last_n: int = 1, avg_last_n: bool = False,
                             area_cm2: float = 1.0, use_abs_delta: bool = True):
    E, I, lines = _ecsa_read_cv_table(filepath)
    if E.size < 3: return None, None
    v = _ecsa_extract_v_from_name(filepath)
    if v is None: v = _ecsa_extract_v_from_content(lines)
    if v is None or v <= 0: return None, None
    up, dn = _ecsa_find_pairs(E, Ev)
    if not up or not dn: return v, None
    if len(up) < last_n or len(dn) < last_n:
        try:
            log(f"ECSA循环数不足，使用可用圈数: up={len(up)}, dn={len(dn)}, last_n={last_n}")
        except Exception:
            pass
    up_sel = up[-last_n:]; dn_sel = dn[-last_n:]
    up_I = np.array([_ecsa_interp_I(E, I, p, Ev) for p in up_sel], float)
    dn_I = np.array([_ecsa_interp_I(E, I, p, Ev) for p in dn_sel], float)
    Ia = np.nanmean(up_I) if avg_last_n else up_I[-1]
    Ic = np.nanmean(dn_I) if avg_last_n else dn_I[-1]
    Ja = (Ia*1000.0)/max(area_cm2,1e-9)
    Jc = (Ic*1000.0)/max(area_cm2,1e-9)
    dJ = Ja - Jc
    if use_abs_delta: dJ = abs(dJ)
    return v, float(dJ)

def fit_deltaJ_vs_v(v_list, dJ_list):
    v = np.asarray(v_list,float); j = np.asarray(dJ_list,float)
    m = np.isfinite(v) & np.isfinite(j)
    v, j = v[m], j[m]
    if v.size < 2: return None, None, None
    k,b = np.polyfit(v, j, 1)
    yhat = k*v + b
    ss_res = float(np.sum((j-yhat)**2)); ss_tot = float(np.sum((j-np.mean(j))**2))
    r2 = 1.0 - ss_res/ss_tot if ss_tot>0 else 1.0
    return float(k), float(b), float(r2)

def _to_mF_per_cm2(value: float, unit: str) -> float:
    u = (unit or '').strip().lower()
    if u in ['mf/cm2','mf/cm²','mf']: return float(value)
    if u in ['uf/cm2','uf/cm²','uf','μf/cm2','μf/cm²','mu f/cm2']: return float(value)/1000.0
    return float(value)

def process_ecsa_for_subfolder(subfolder: str, files: list, params: dict, common: dict):
    prefix = params.get('match_prefix','ECSA'); mode = params.get('match','prefix')
    candidates = []
    for f in files:
        fl = f.lower()
        if not (fl.endswith('.txt') or fl.endswith('.csv')): continue
        if _matches_named_file(f, mode, prefix):
            candidates.append(f)
    if not candidates: return None

    Ev = float(params.get('ev',0.10)); last_n=int(params.get('last_n',1))
    avg_last_n=bool(params.get('avg_last_n',False)); area=float(common.get('area',1.0))
    use_abs = bool(params.get('use_abs_delta',True))

    v_list, dJ_list = [], []
    for f in sorted(candidates, key=natural_sort_key):
        fp = os.path.join(subfolder, f)
        v, dJ = compute_deltaJ_for_file(fp, Ev, last_n, avg_last_n, area, use_abs)
        if v is not None and dJ is not None:
            v_list.append(v); dJ_list.append(dJ)
    if len(v_list) < 2: return None

    slope, intercept, r2 = fit_deltaJ_vs_v(v_list, dJ_list)
    if slope is None: return None

    cdl_mFcm2 = slope/2.0
    cs_mFcm2 = _to_mF_per_cm2(params.get('cs_value',40.0), params.get('cs_unit','µF/cm²'))
    if cs_mFcm2 <= 0: cs_mFcm2 = 40.0/1000.0
    ecsa_cm2 = cdl_mFcm2 / cs_mFcm2
    rf = ecsa_cm2 / max(area,1e-9)
    output_dir = str(params.get("output_dir") or subfolder)
    os.makedirs(output_dir, exist_ok=True)

    # 绘图（与现有风格保持一致）
    plt.figure(figsize=(7.5,5.8))
    font_to_use = _resolve_plot_font(common.get('font', CHINESE_FONT))
    plt.rcParams['font.sans-serif'] = [font_to_use]
    plt.rcParams['axes.unicode_minus'] = False
    plt.scatter(v_list, dJ_list, s=40)
    xs = np.linspace(min(v_list), max(v_list), 100); ys = slope*xs + intercept
    plt.plot(xs, ys, linewidth=float(params.get('line_width',2.0)))
    plt.xlabel(params.get('xlabel','Scan rate v (V/s)'))
    plt.ylabel(params.get('ylabel','ΔJ (mA/cm²)'))
    subname = os.path.basename(subfolder)
    title = params.get('title','ECSA of {sample} @ Ev={Ev:.3f} V').format(sample=subname, Ev=Ev)
    plt.title(title, fontname=font_to_use, fontsize=int(common.get('fontsize',12)))
    if params.get('plot_grid', True):
        plt.grid(True, alpha=0.3)
    txt = (f"slope = {slope:.4f} mF/cm²\n"
           f"Cdl = slope/2 = {cdl_mFcm2:.4f} mF/cm²\n"
           f"Cs = {params.get('cs_value',40.0)} {params.get('cs_unit','µF/cm²')}\n"
           f"ECSA = {ecsa_cm2:.3f} cm²\nRF = {rf:.3f}\nR² = {r2:.4f}")
    plt.annotate(txt, xy=(0.02,0.98), xycoords='axes fraction', va='top',
                 bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.7))
    plt.tight_layout()
    out_png = os.path.join(output_dir, f"{subname}_ECSA.png")
    plt.savefig(out_png, dpi=300, bbox_inches='tight')
    plt.close()

    # ✅ 添加：保存ECSA历史记录
    if HISTORY_MANAGER_AVAILABLE:
        try:
            history_mgr = get_history_manager()

            record = {
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'sample_name': subname,
                'file_name': 'ECSA',
                'file_path': subfolder,
                'type': 'ECSA',
                'status': 'success',
                'results': {
                    'Cdl': float(cdl_mFcm2),  # type: ignore[arg-type]
                    'ECSA': float(ecsa_cm2),  # type: ignore[arg-type]
                    'RF': float(rf),  # type: ignore[arg-type]
                    'R2': float(r2),  # type: ignore[arg-type]
                    'scan_rates': len(v_list)
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
            log(f"ECSA历史记录已保存: {subname}")

        except Exception as e:
            log(f"保存ECSA历史记录失败: {e}")

    return {'sample': subname, 'Ev': Ev, 'n_used': last_n, 'avg_last_n': avg_last_n, 'N_points': len(v_list),
            'slope_mFcm2': slope, 'intercept': intercept, 'R2': r2, 'Cdl_mFcm2': cdl_mFcm2,
            'Cs_input': float(params.get('cs_value',40.0)), 'Cs_unit': params.get('cs_unit','µF/cm²'),
            'Cs_mFcm2': cs_mFcm2, 'ECSA_cm2': ecsa_cm2, 'RF': rf, 'png': out_png}
