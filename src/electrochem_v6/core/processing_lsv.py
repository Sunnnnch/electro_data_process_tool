"""LSV processing helpers extracted from the shared processing core."""
from __future__ import annotations

import os
from datetime import datetime

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import processing_core_v6 as core
from .processing_pipeline import _as_bool
from .processing_quality import DataQualityChecker
from .utils import read_file_with_fallback_encodings

# ── Module-level constants ─────────────────────────────────────────────────
# Outlier detection (MAD-based)
MAD_Z_SCORE_CONSTANT = 0.6745
MAD_OUTLIER_THRESHOLD = 3.5

# Fitting defaults
MIN_FITTING_POINTS = 3
TAFEL_RANGE_RATIO_MIN = 3.0
MAX_EXTRAPOLATION_FACTOR = 2.0
EXTRAPOLATION_LINE_POINTS = 50

# Current unit conversion
A_TO_MA = 1000.0

# Half-wave potential defaults
HALFWAVE_PERCENTILE = 95
HALFWAVE_FRACTION = 0.5

# EIS high-frequency thresholds for Tafel-region selection
HF_THRESHOLD_UP = 0.7   # upper extrapolation direction
HF_THRESHOLD_DOWN = 0.3  # lower extrapolation direction

# Relative threshold for imaginary impedance filtering (1% of range)
EIS_RELATIVE_IMAG_THRESHOLD = 0.01

# Software version stamp embedded in detail exports
SOFTWARE_VERSION = "2.3.2"

get_logger = core.get_logger
_resolve_plot_font = core._resolve_plot_font
_matches_named_file = core._matches_named_file
log = core.log
HISTORY_MANAGER_AVAILABLE = core.HISTORY_MANAGER_AVAILABLE
PROJECT_MANAGER_AVAILABLE = core.PROJECT_MANAGER_AVAILABLE
get_history_manager = core.get_history_manager
get_project_manager = core.get_project_manager
_extract_sample_token = core._extract_sample_token
_match_eis_by_sample = core._match_eis_by_sample

def interpolate_potential(potential, current, target_current):
    """
    Robustly interpolate potential at a given target current density.
    - Sorts by current to satisfy monotonic x for interpolation.
    - Handles negative targets.
    - Returns None if target lies outside observed range.
    """
    import numpy as _np
    p = _np.asarray(potential, dtype=float)
    c = _np.asarray(current, dtype=float)

    mask = _np.isfinite(p) & _np.isfinite(c)
    p, c = p[mask], c[mask]
    if c.size < 2:
        return None

    order = _np.argsort(c)
    c_sorted = c[order]
    p_sorted = p[order]

    if target_current < c_sorted.min() or target_current > c_sorted.max():
        return None

    # Deduplicate currents by averaging potentials at same current
    uniq_c, inv_idx = _np.unique(c_sorted, return_inverse=True)
    if uniq_c.size != c_sorted.size:
        sums = _np.zeros_like(uniq_c, dtype=float)
        counts = _np.zeros_like(uniq_c, dtype=int)
        for idx, pot in zip(inv_idx, p_sorted):
            sums[idx] += pot
            counts[idx] += 1
        uniq_p = sums / _np.maximum(counts, 1)
        return float(_np.interp(target_current, uniq_c, uniq_p))

    return float(_np.interp(target_current, c_sorted, p_sorted))

def parse_target_currents(target_current_str):
    """Parse target current string like '10,100'."""
    if target_current_str is None:
        return []
    try:
        current_strs = [
            s.strip()
            for s in str(target_current_str).replace('\uff0c', ',').split(',')
            if s.strip()
        ]
        currents = []
        for current_str in current_strs:
            try:
                current = float(current_str)
                if current > 0:
                    currents.append(current)
            except ValueError:
                continue
        return sorted(list(set(currents)))
    except (ValueError, TypeError):
        return []

def _parse_tafel_range(raw_value):
    """Parse Tafel range string like '1-10' -> (1.0, 10.0)."""
    if raw_value is None:
        return None
    text = str(raw_value).replace('，', ',').replace(' ', '')
    if not text:
        return None
    if '-' in text:
        parts = text.split('-', 1)
        lo_text, hi_text = parts[0], parts[1]
    else:
        lo_text, hi_text = text, text
    try:
        lo = float(lo_text)
        hi = float(hi_text)
    except (ValueError, TypeError):
        return None
    return (lo, hi)

def _filter_outliers(real_vals, imag_vals, freq_vals=None, thresh=MAD_OUTLIER_THRESHOLD):
    """Filter outliers in high-frequency region using MAD.

    Returns (real_vals, imag_vals, freq_vals) with outliers removed.
    """
    if real_vals is None or imag_vals is None:
        return real_vals, imag_vals, freq_vals
    if len(real_vals) < 3 or len(imag_vals) < 3:
        return real_vals, imag_vals, freq_vals
    import numpy as _np

    def _mask(vals):
        v = _np.asarray(vals, dtype=float)
        med = _np.nanmedian(v)
        mad = _np.nanmedian(_np.abs(v - med))
        if mad <= 0:
            return _np.ones_like(v, dtype=bool)
        z = MAD_Z_SCORE_CONSTANT * (v - med) / mad
        return _np.abs(z) <= thresh

    mask = _mask(real_vals) & _mask(imag_vals)
    if mask.sum() < 2:
        return real_vals, imag_vals, freq_vals

    real_f = [v for v, m in zip(real_vals, mask) if m]
    imag_f = [v for v, m in zip(imag_vals, mask) if m]
    if freq_vals is not None:
        freq_f = [v for v, m in zip(freq_vals, mask) if m]
    else:
        freq_f = None
    return real_f, imag_f, freq_f

def interpolate_multiple_potentials(potential, current, target_currents):
    """计算多个目标电流对应的电位"""
    results = {}
    for target in target_currents:
        result = interpolate_potential(potential, current, target)
        if result is not None:
            results[target] = result
    return results

def potential_at_current(potential_V, current_mAcm2, target_i=10.0,
                         min_pts=MIN_FITTING_POINTS, tafel_ratio=TAFEL_RANGE_RATIO_MIN, max_extrap_factor=MAX_EXTRAPOLATION_FACTOR):
    """计算在电流密度 i=target_i (mA/cm²) 时的电位 E (V)。
    逻辑：
      1) 若曲线覆盖目标电流 -> 线性插值；
      2) 否则外推：优先 Tafel (E = a + b·log10(i))，不满足则线性 E–i；
      3) 保护：至少 min_pts 点；Tafel 拟合区间需满足 i_max/i_min ≥ tafel_ratio；
               仅允许把目标电流外推到测得 i_max 的 max_extrap_factor 倍以内。
    返回：
      (E10, ext)，E10 为 float (不可得则为 np.nan)；
      ext 为 (E_ext_array, I_ext_array, method_str) 或 None，用于绘图虚线。
    """
    import numpy as np
    E = np.asarray(potential_V, dtype=float)
    I = np.asarray(current_mAcm2, dtype=float)

    mask = np.isfinite(E) & np.isfinite(I)
    E, I = E[mask], I[mask]
    if E.size < 2:
        return np.nan, None

    # 按电流升序
    order = np.argsort(I)
    I, E = I[order], E[order]

    # 目标太远：拒绝外推（避免“拍脑袋”）
    if I.max() <= 0 or target_i > I.max() * float(max_extrap_factor):
        try:
            import numpy as _np
            return _np.nan, None
        except Exception:
            return float('nan'), None

    # 覆盖 -> 插值
    if (I.min() <= target_i) and (I.max() >= target_i):
        E10 = float(np.interp(target_i, I, E))
        return E10, None

    # 外推
    going_up = target_i > I.max()
    if going_up:
        thr = max(1.0, HF_THRESHOLD_UP * I.max())
        sel = np.where(I >= thr)[0]
        if sel.size < min_pts:
            sel = np.arange(max(0, len(I) - min_pts), len(I))
    else:
        thr = HF_THRESHOLD_DOWN * I.min()
        sel = np.where(I <= thr)[0]
        if sel.size < min_pts:
            sel = np.arange(0, min(min_pts, len(I)))

    I_sel, E_sel = I[sel], E[sel]

    use_tafel = (
            (I_sel > 0).all() and
            (sel.size >= min_pts) and
            (I_sel.max() / max(I_sel.min(), 1e-9) >= float(tafel_ratio))
    )

    if use_tafel:
        x = np.log10(np.clip(I_sel, 1e-12, None))
        b, a = np.polyfit(x, E_sel, 1)  # E = a + b*log10(i)
        E10 = float(a + b * np.log10(max(target_i, 1e-12)))
        i0 = I_sel.max() if going_up else target_i
        i1 = target_i if going_up else I_sel.min()
        i_ext = np.linspace(i0, i1, EXTRAPOLATION_LINE_POINTS)
        E_ext = a + b * np.log10(np.clip(i_ext, 1e-12, None))
        method = f"tafel (b={b:.3f} V/dec)"
    else:
        m, c = np.polyfit(I_sel, E_sel, 1)  # E = m*i + c
        E10 = float(m * target_i + c)
        i0 = I_sel.max() if going_up else target_i
        i1 = target_i if going_up else I_sel.min()
        i_ext = np.linspace(i0, i1, EXTRAPOLATION_LINE_POINTS)
        E_ext = m * i_ext + c
        method = "linear"

    # 再次保护：外推幅度过大则返回 NaN
    if (max(target_i, I.max()) / max(1e-12, min(I_sel.max(), target_i))) > float(max_extrap_factor):
        try:
            import numpy as _np
            return _np.nan, None
        except Exception:
            return float('nan'), None

    return E10, (E_ext, i_ext, method)

def get_ir_from_eis(subfolder, eis_filename, start_line, method='auto', hf_points=10):
    """Get Rs from EIS by estimating the high-frequency x-axis intercept.

    method:
      - auto: prefer HF intercept, otherwise HF mean
      - hf_intercept: HF intercept only
      - hf_mean: HF mean only
      - linear_fit: fit Z'' = a*Z' + b, use x-intercept -b/a
    """
    try:
        filepath = os.path.join(subfolder, eis_filename)
        if not os.path.exists(filepath):
            log(f"EIS文件不存在: {filepath}")
            return None

        # 尝试多种编码读取
        lines = read_file_with_fallback_encodings(filepath, start_line=int(start_line))

        if lines is None:
            log(f"无法读取文件 {filepath}, 所有编码均失败")
            return None

        z_real, z_imag, frequencies = [], [], []
        for line_num, line in enumerate(lines):
            parts = line.strip().replace(',', ' ').split()
            if len(parts) >= 3:
                try:
                    freq = float(parts[0])
                    real = float(parts[1])
                    imag = float(parts[2])
                    frequencies.append(freq)
                    z_real.append(real)
                    z_imag.append(imag)
                except ValueError as e:
                    log(f"第{line_num + int(start_line)}行数据解析失败: {line.strip()}, 错误: {e}")
                    continue

        if not z_real or not z_imag:
            log(f"EIS文件 {eis_filename} 中未提取到有效数据")
            return None

        log(f"成功读取 {len(z_real)} 个EIS数据点")
        log(f"Z'范围: {min(z_real):.3f} ~ {max(z_real):.3f} Ω")
        log(f"Z''范围: {min(z_imag):.3f} ~ {max(z_imag):.3f} Ω")

        method_key = (method or 'auto').strip().lower()
        supported_methods = {'auto', 'hf_intercept', 'hf_mean', 'linear_fit'}
        if method_key not in supported_methods:
            method_key = 'auto'

        # 全局最小虚部作为初始IR值
        min_imag_index = min(range(len(z_imag)), key=lambda i: abs(z_imag[i]))
        ir_value = z_real[min_imag_index]
        log(f"全局最小虚部: Z'={ir_value:.3f}Ω, Z''={z_imag[min_imag_index]:.3f}Ω")

        # 高频区数据筛选与分析
        if frequencies:
            log(f"频率范围: {min(frequencies):.2f} ~ {max(frequencies):.2f} Hz")
            try:
                hf_n = int(hf_points) if hf_points is not None else 0
            except Exception:
                hf_n = 0
            if hf_n <= 0:
                hf_n = max(3, len(frequencies) // 5)
            n_points = min(max(3, hf_n), len(frequencies))
            high_freq_indices = sorted(range(len(frequencies)), key=lambda i: frequencies[i], reverse=True)[:n_points]

            high_freq_real = [z_real[i] for i in high_freq_indices]
            high_freq_imag = [z_imag[i] for i in high_freq_indices]
            high_freq_freqs = [frequencies[i] for i in high_freq_indices]
            high_freq_real, high_freq_imag, high_freq_freqs = _filter_outliers(
                high_freq_real, high_freq_imag, high_freq_freqs
            )

            if not high_freq_real or not high_freq_imag or not high_freq_freqs:
                log("高频区数据经异常值过滤后为空, 使用全局初始IR值")
            else:
                log(
                    f"高频区筛选出 {len(high_freq_real)} 个数据点, "
                    f"频率范围: {min(high_freq_freqs):.2f} ~ {max(high_freq_freqs):.2f} Hz")

                min_imag_idx_in_high_freq = min(range(len(high_freq_imag)), key=lambda i: abs(high_freq_imag[i]))
                high_freq_ir_value = high_freq_real[min_imag_idx_in_high_freq]
                log(f"高频区最小虚部: Z'={high_freq_ir_value:.3f}Ω")

                z_imag_range = max(abs(min(z_imag)), abs(max(z_imag)))
                threshold = EIS_RELATIVE_IMAG_THRESHOLD * z_imag_range if z_imag_range > 0 else EIS_RELATIVE_IMAG_THRESHOLD

                if method_key == 'hf_intercept':
                    if abs(high_freq_imag[min_imag_idx_in_high_freq]) < threshold:
                        ir_value = high_freq_ir_value
                        log(f"高频截距法: Z'={ir_value:.3f}Ω")
                    else:
                        log("高频截距法: 虚部偏大, 不满足截距条件")
                elif method_key == 'hf_mean':
                    ir_value = sum(high_freq_real) / len(high_freq_real)
                    log(f"高频均值法: Z'均值={ir_value:.3f}Ω")
                elif method_key == 'linear_fit':
                    if len(high_freq_real) >= 2:
                        import numpy as _np
                        x = _np.asarray(high_freq_real, dtype=float)
                        y = _np.asarray(high_freq_imag, dtype=float)
                        a, b = _np.polyfit(x, y, 1)
                        if abs(a) > 1e-12:
                            candidate = float(-b / a)
                            x_min, x_max = min(high_freq_real), max(high_freq_real)
                            if candidate < x_min or candidate > x_max:
                                ir_value = sum(high_freq_real) / len(high_freq_real)
                                log(f"线性拟合外推超出范围, 回退均值法: {ir_value:.3f}Ω")
                            else:
                                ir_value = candidate
                                log(f"线性拟合截距法: Z'={ir_value:.3f}Ω")
                        else:
                            ir_value = sum(high_freq_real) / len(high_freq_real)
                            log(f"线性拟合斜率接近零, 回退均值法: {ir_value:.3f}Ω")
                    else:
                        log("线性拟合所需数据点不足")
                else:
                    if abs(high_freq_imag[min_imag_idx_in_high_freq]) < threshold:
                        ir_value = high_freq_ir_value
                        log(f"自动法(截距): Z'={ir_value:.3f}Ω")
                    else:
                        ir_value = sum(high_freq_real) / len(high_freq_real)
                        log(f"自动法(均值): Z'均值={ir_value:.3f}Ω")

        log(f"最终确定IR值: {ir_value:.3f}Ω")
        return ir_value

    except Exception as e:
        log(f"读取EIS文件失败: {e}")
        return None

def process_lsv(subfolder, file, params, project_id=None, enable_quality_check=True):
    """处理LSV数据文件，包含数据质量检查和详细错误处理
    
    Args:
        subfolder: 子文件夹路径
        file: 文件名
        params: 参数字典
        project_id: 项目ID（可选）
        enable_quality_check: 是否启用数据质量检查（默认True）
    """
    logger = get_logger()
    filepath = os.path.join(subfolder, file)
    subname = os.path.basename(subfolder)
    file_stem = os.path.splitext(os.path.basename(file))[0]
    
    logger.info(f"开始处理LSV文件: {file} (样品: {subname})")

    # 初始化Tafel拟合数据存储变量
    tafel_fit_data_original = None
    tafel_fit_data_ir = None
    slope_mVdec = None  # 初始化 Tafel 斜率变量，避免未启用时引用错误
    lsv_quality_report = None  # 初始化质量报告变量，确保始终存在

    # 尝试多种编码格式读取文件
    try:
        lines = read_file_with_fallback_encodings(filepath, start_line=int(params['start_line']))
    except (FileNotFoundError, OSError) as e:
        logger.error(f"文件读取失败: {filepath} - {e}")
        raise FileFormatError(f"无法读取LSV文件: {file} - {e}")

    if lines is None:
        logger.error(f"所有编码格式均无法读取文件: {filepath}")
        raise FileFormatError(f"无法读取LSV文件 {file}，尝试了所有编码格式")

    # 解析数据
    potential, current, current_signed = [], [], []
    parse_errors = 0
    for line_num, line in enumerate(lines, start=int(params['start_line'])):
        parts = line.strip().replace(',', ' ').split()
        if len(parts) >= 2:
            try:
                pot = float(parts[0]) + float(params['offset'])
                i_A = float(parts[1])
                cur_signed = i_A * A_TO_MA / float(params['area'])
                cur_used = abs(cur_signed) if params.get('use_abs_current', True) else cur_signed
                potential.append(pot)
                current_signed.append(cur_signed)
                current.append(cur_used)
            except ValueError as e:
                parse_errors += 1
                if parse_errors <= 5:  # 只记录前5个错误避免日志爆炸
                    logger.debug(f"第{line_num}行数据解析失败: {line.strip()}")
                continue
            except Exception as e:
                logger.warning(f"第{line_num}行处理异常: {str(e)}")
                continue

    if parse_errors > 0:
        logger.info(f"共 {parse_errors} 行数据解析失败（已跳过）")

    if not potential or not current:
        logger.error(f"未能从文件中提取有效数据: {file}")
        raise DataProcessingError(f"LSV文件 {file} 中未找到有效数据点")

    # 创建DataFrame进行质量检查
    if enable_quality_check:
        try:
            df = pd.DataFrame({
                'Potential': potential,
                'Current': current
            })
            
            # 执行数据质量检查（使用 子文件夹/文件名 格式）
            display_name = f"{subname}/{file}" if subname else file
            quality_report = DataQualityChecker.check_lsv_data(
                df,
                display_name,
                source_path=filepath,
                config=params.get('quality_config'),
            )
            
            # 保存质量报告供后续汇总使用（无论是否有效）
            lsv_quality_report = quality_report
            
            # 如果有严重问题，记录警告（但不中断处理）
            if not quality_report['is_valid']:
                logger.warning(f"LSV数据质量较差: {file}")
                for issue in quality_report['issues']:
                    logger.warning(f"  - {issue}")
                # 不再抛出异常，允许继续处理
            
            # 记录警告信息
            if quality_report['warnings']:
                logger.warning(f"LSV数据质量警告: {file}")
                for warning in quality_report['warnings']:
                    logger.warning(f"  - {warning}")
            
            # 记录统计信息
            stats = quality_report['stats']
            logger.info(
                f"数据统计: {stats['data_points']}点, "
                f"电位范围: {stats['potential_range'][0]:.3f}~{stats['potential_range'][1]:.3f}V"
            )
            
        except Exception as e:
            logger.warning(f"数据质量检查过程异常（继续处理）: {str(e)}")
    else:
        logger.info("LSV数据质量检查已禁用")
        lsv_quality_report = None  # 未进行检查


    # 解析多个目标电流密度
    try:
        target_currents = parse_target_currents(params['target_current'])
        if not target_currents:
            target_currents = [10.0]  # 默认值
            logger.info("未指定目标电流，使用默认值: 10.0 mA/cm²")
    except Exception as e:
        logger.warning(f"解析目标电流失败，使用默认值: {str(e)}")
        target_currents = [10.0]

    # IR补偿处理
    ir_compensation = 0
    potential_compensated = None
    if params.get('ir_compensation_enabled', False):
        logger.info("开始IR补偿处理...")
        try:
            files_in_folder = os.listdir(subfolder)
            eis_file = None

            sample_token = _extract_sample_token(file)
            if sample_token:
                matched = _match_eis_by_sample(files_in_folder, sample_token)
                if matched:
                    eis_file = matched
                    logger.info(f"按照样品名匹配到EIS文件: {matched} (token={sample_token})")

            if not eis_file:
                for f in files_in_folder:
                    if not (f.lower().endswith('.txt') or f.lower().endswith('.csv')):
                        continue

                    if _matches_named_file(f, params.get('eis_match', 'prefix'), params.get('eis_prefix', 'EIS')):
                        eis_file = f
                        break

            if eis_file:
                logger.info(f"找到EIS文件: {eis_file}")
                try:
                    ir_value = get_ir_from_eis(
                        subfolder, eis_file, 
                        params['eis_start_line'], 
                        params.get('ir_method', 'auto'), 
                        params.get('ir_linear_points', 10)
                    )
                    if ir_value is not None and ir_value > 0:
                        ir_compensation = ir_value
                        logger.info(f"✓ 成功获取IR值: {ir_compensation:.3f}Ω")
                        potential_compensated = [
                            pot - ((cur_sig / 1000) * float(params.get('area', 1.0))) * ir_compensation 
                            for pot, cur_sig in zip(potential, current_signed)
                        ]
                    else:
                        logger.warning(f"IR值无效: {ir_value}")
                except Exception as e:
                    logger.error(f"从EIS文件提取IR值失败: {str(e)}")
            else:
                logger.warning(
                    f"未找到EIS文件（匹配方式: {params['eis_match']}, "
                    f"前缀/后缀: {params['eis_prefix']}）"
                )
        except Exception as e:
            logger.error(f"IR补偿处理异常: {str(e)}")

    # 兜底：若 EIS 未取得有效 Rs 且存在手动 Rs（且启用IR）
    try:
        if params.get('ir_compensation_enabled', False):
            try:
                manual_rs = float(params.get('ir_manual_ohm', 0) or 0)
            except Exception:
                manual_rs = 0.0
            if (not ir_compensation or ir_compensation <= 0) and (manual_rs and manual_rs > 0):
                ir_compensation = manual_rs
                potential_compensated = [
                    pot - ((cur_sig / 1000) * float(params.get('area', 1.0))) * ir_compensation 
                    for pot, cur_sig in zip(potential, current_signed)
                ]
                logger.info(f"采用手动Rs兜底: {ir_compensation:.3f}Ω")
    except Exception as e:
        logger.warning(f"手动Rs兜底处理异常: {str(e)}")
    
    # 计算多个目标电流对应的电位（覆盖则插值；不足则稳健外推）
    target_potentials_original = {}
    ext_segments_original = []
    for target_current in target_currents:
        E10, ext = potential_at_current(potential, current, target_i=target_current,
                                        min_pts=3, tafel_ratio=3.0, max_extrap_factor=2.0)
        if E10 == E10:  # not NaN
            target_potentials_original[target_current] = E10
        if ext is not None:
            ext_segments_original.append(ext)

    target_potentials_compensated = {}
    ext_segments_compensated = []
    if potential_compensated is not None:
        for target_current in target_currents:
            E10c, extc = potential_at_current(potential_compensated, current, target_i=target_current,
                                              min_pts=3, tafel_ratio=3.0, max_extrap_factor=2.0)
            if E10c == E10c:
                target_potentials_compensated[target_current] = E10c
            if extc is not None:
                ext_segments_compensated.append(extc)

    overpotential_enabled = _as_bool(params.get('overpotential_enabled', False))
    try:
        eqv = float(params.get('eq_potential', 0.0))
    except Exception:
        eqv = 0.0
    target_overpotentials_original = {}
    if overpotential_enabled:
        for target_current, target_pot in target_potentials_original.items():
            try:
                target_overpotentials_original[target_current] = abs((float(target_pot) - eqv) * 1000.0)
            except Exception:
                pass

    # 绘制原始LSV曲线
    plt.figure(figsize=(8, 6))
    # 设置当前图形的中文字体支持
    font_to_use = _resolve_plot_font(
        params.get('font'),
        text=f"{params.get('title', '')} 频率 相位 幅值 图",
    )
    plt.rcParams['font.sans-serif'] = [font_to_use]
    plt.rcParams['axes.unicode_minus'] = False

    plt.plot(potential, current,
             color=params.get('line_color', 'blue'),
             linewidth=params.get('line_width', 2.0),
             label='LSV curve')

    # 外推段虚线（如有）
    if ext_segments_original:
        for (E_ext, I_ext, how) in ext_segments_original:
            try:
                plt.plot(E_ext, I_ext, linestyle='--', linewidth=1.2, label=f'extrapolated: {how}')
            except Exception:
                pass

    # 标出目标电流密度对应的点
    if params.get('mark_targets', True):
        for target_current in target_currents:
            if target_current in target_potentials_original:
                target_pot = target_potentials_original[target_current]
                plt.plot(target_pot, target_current, 'ro', markersize=8,
                         label=f'{target_current} mA/cm² @ {target_pot:.3f} V')
                # 添加文本标注
                plt.annotate(f'{target_current} mA/cm²\n{target_pot:.3f} V',
                             xy=(target_pot, target_current),
                             xytext=(10, 10), textcoords='offset points',
                             bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7),
                             arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))

    # 叠加 Tafel 拟合与高亮点（原始）
    tafel_fit_data_original = None  # 存储Tafel拟合数据以便导出
    try:
        if params.get('tafel_enabled') and (potential_compensated is None):  # 恢复原始逻辑
            import numpy as _np
            I_all = _np.asarray(current, dtype=float)
            E_all = _np.asarray(potential, dtype=float)
            tafel_range = _parse_tafel_range(params.get('tafel_range','1-10'))
            if not tafel_range:
                logger.warning("Invalid Tafel range: %s", params.get('tafel_range'))
                raise ValueError('invalid tafel_range')
            lo, hi = tafel_range
            mask = _np.isfinite(I_all) & _np.isfinite(E_all) & (I_all>0) & (I_all>=min(lo,hi)) & (I_all<=max(lo,hi))
            if mask.sum() >= 3:
                x = _np.log10(_np.clip(I_all[mask], 1e-12, None))
                y = E_all[mask]
                b, a = _np.polyfit(x, y, 1)
                ss_res = float(_np.sum((y - (a + b*x))**2))
                ss_tot = float(_np.sum((y - _np.mean(y))**2))
                r2 = (1.0 - ss_res/max(1e-12, ss_tot))
                order = _np.argsort(I_all[mask])
                I_fit = I_all[mask][order]
                E_fit = a + b*_np.log10(_np.clip(I_fit, 1e-12, None))
                lbl = "Tafel fit: {:.1f} mV/dec, R²={:.3f}".format(float(b*1000.0), float(r2))
                # 主图坐标为 E 横轴、I 纵轴
                plt.plot(E_fit, I_fit, 'r-.', linewidth=1.5, label=lbl)
                plt.scatter(E_all[mask], I_all[mask], c='red', s=20, zorder=5, label='Tafel used points')
                # 保存Tafel数据用于独立图导出
                tafel_fit_data_original = {
                    'I_data': I_all[mask],
                    'E_data': E_all[mask], 
                    'I_fit': I_fit,
                    'E_fit': E_fit,
                    'slope_mVdec': float(b*1000.0),
                    'r2': float(r2),
                    'range': (lo, hi)
                }
    except (ValueError, TypeError) as exc:
        logger.debug("Tafel拟合跳过: %s", exc)
    plt.xlabel(params['xlabel'])
    plt.ylabel(params['ylabel'])
    title = params['title'].replace("{sample}", subname)
    # 使用支持中文的字体，如果用户指定了字体且支持中文则使用用户指定的，否则使用系统中文字体
    font_to_use = _resolve_plot_font(params.get('font'))
    plt.title(title, fontname=font_to_use, fontsize=int(params['fontsize']))
    if params.get('plot_grid', True):
        if params.get('plot_grid', True):
            plt.grid(True, alpha=0.3)
    if params.get('mark_targets', True) and target_potentials_original:
        plt.legend()
    plt.tight_layout()
    # 避免同一文件夹内多文件相互覆盖：在文件名中加入源文件名
    try:
        plt.savefig(os.path.join(subfolder, f"{subname}_{file_stem}_LSV.png"), dpi=300, bbox_inches='tight')
    finally:
        plt.close()

    # 如果进行了IR补偿，绘制补偿后的LSV曲线
    if potential_compensated is not None:
        plt.figure(figsize=(8, 6))
        # 设置当前图形的中文字体支持
        font_to_use = _resolve_plot_font(params.get('font'))
        plt.rcParams['font.sans-serif'] = [font_to_use]
        plt.rcParams['axes.unicode_minus'] = False
        plt.plot(potential_compensated, current,
                 color=params.get('line_color', 'blue'),
                 linewidth=params.get('line_width', 2.0),
                 label='IR compensated LSV curve')

        # 外推段虚线（如有）
        if ext_segments_compensated:
            for (E_ext, I_ext, how) in ext_segments_compensated:
                try:
                    plt.plot(E_ext, I_ext, linestyle='--', linewidth=1.2, label=f'extrapolated: {how}')
                except Exception:
                    pass

        # 标出目标电流密度对应的点
        if params.get('mark_targets', True):
            for target_current in target_currents:
                if target_current in target_potentials_compensated:
                    target_pot = target_potentials_compensated[target_current]
                    plt.plot(target_pot, target_current, 'ro', markersize=8,
                             label=f'{target_current} mA/cm² @ {target_pot:.3f} V')
                    # 添加文本标注
                    plt.annotate(f'{target_current} mA/cm²\n{target_pot:.3f} V',
                                 xy=(target_pot, target_current),
                                 xytext=(10, 10), textcoords='offset points',
                                 bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7),
                                 arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))

        # 叠加 Tafel 拟合与高亮点（IR 补偿）
        tafel_fit_data_ir = None  # 存储IR补偿Tafel拟合数据以便导出
        try:
            if params.get('tafel_enabled') and (potential_compensated is not None):
                import numpy as _np
                I_all = _np.asarray(current, dtype=float)
                E_all = _np.asarray(potential_compensated, dtype=float)
                tafel_range = _parse_tafel_range(params.get('tafel_range','1-10'))
                if not tafel_range:
                    logger.warning("Invalid Tafel range: %s", params.get('tafel_range'))
                    raise ValueError('invalid tafel_range')
                lo, hi = tafel_range
                mask = _np.isfinite(I_all) & _np.isfinite(E_all) & (I_all>0) & (I_all>=min(lo,hi)) & (I_all<=max(lo,hi))
                if mask.sum() >= 3:
                    x = _np.log10(_np.clip(I_all[mask], 1e-12, None))
                    y = E_all[mask]
                    b, a = _np.polyfit(x, y, 1)
                    ss_res = float(_np.sum((y - (a + b*x))**2))
                    ss_tot = float(_np.sum((y - _np.mean(y))**2))
                    r2 = (1.0 - ss_res/max(1e-12, ss_tot))
                    order = _np.argsort(I_all[mask])
                    I_fit = I_all[mask][order]
                    E_fit = a + b*_np.log10(_np.clip(I_fit, 1e-12, None))
                    lbl = "Tafel fit: {:.1f} mV/dec, R²={:.3f}".format(float(b*1000.0), float(r2))
                    # 绘图坐标与主体一致：横轴 E(V)，纵轴 I(mA/cm²)
                    plt.plot(E_fit, I_fit, 'r-.', linewidth=1.5, label=lbl)
                    plt.scatter(E_all[mask], I_all[mask], c='red', s=20, zorder=5, label='Tafel used points')
                    # 保存IR补偿Tafel数据用于独立图导出
                    tafel_fit_data_ir = {
                        'I_data': I_all[mask],
                        'E_data': E_all[mask], 
                        'I_fit': I_fit,
                        'E_fit': E_fit,
                        'slope_mVdec': float(b*1000.0),
                        'r2': float(r2),
                        'range': (lo, hi),
                        'ir_compensation': ir_compensation
                    }
        except (ValueError, TypeError) as exc:
            logger.debug("IR补偿Tafel拟合跳过: %s", exc)
        plt.xlabel(params['xlabel'])
        plt.ylabel(params['ylabel'])
        title_compensated = params['title'].replace("{sample}", subname) + f" (IR: {ir_compensation:.2f}Ω)"
        # 使用支持中文的字体
        font_to_use = _resolve_plot_font(params.get('font'))
        plt.title(title_compensated, fontname=font_to_use, fontsize=int(params['fontsize']))
        if params.get('plot_grid', True):
            if params.get('plot_grid', True):
                plt.grid(True, alpha=0.3)
        if params.get('mark_targets', True) and target_potentials_compensated:
            plt.legend()
        plt.tight_layout()
        try:
            plt.savefig(os.path.join(subfolder, f"{subname}_{file_stem}_LSV_IR_compensated.png"), dpi=300, bbox_inches='tight')
        finally:
            plt.close()

        # 准备返回结果：包含所有目标电流密度的数据（不重复写入Rs）
        result_row = [subname, file_stem]
        # 先写所有原始电位
        for target_current in target_currents:
            original_pot = target_potentials_original.get(target_current, None)
            result_row.append(original_pot)
        # 再写所有IR补偿后的电位
        for target_current in target_currents:
            compensated_pot = target_potentials_compensated.get(target_current, None)
            result_row.append(compensated_pot)
        # 最后写单列 Rs
        result_row.append(ir_compensation)
        if overpotential_enabled:
            for target_current in target_currents:
                result_row.append(target_overpotentials_original.get(target_current, None))
        # 可选指标：起始电位/半波电位/Tafel
        if params.get('onset_enabled'):
            try:
                j_on = float(str(params.get('onset_current','1.0')).replace(',','.'))
            except Exception:
                j_on = 1.0
            E_on, _ = potential_at_current(potential, current, target_i=j_on,
                                           min_pts=3, tafel_ratio=3.0, max_extrap_factor=2.0)
            if E_on != E_on:
                E_on = None
            result_row.append(E_on)
            if overpotential_enabled:
                eta_mV = None if E_on is None else abs((E_on - eqv) * 1000.0)
                result_row.append(eta_mV)
        # Half-wave potential
        if params.get('halfwave_enabled'):
            try:
                hw_text = (params.get('halfwave_current') or '').strip()
                if hw_text:
                    j_half = float(hw_text)
                else:
                    import numpy as _np
                    j_half = 0.5 * float(_np.nanpercentile(_np.asarray(current, dtype=float), 95))
            except Exception:
                j_half = None
            if j_half is not None and j_half > 0:
                E_half, _ = potential_at_current(potential, current, target_i=j_half,
                                                 min_pts=3, tafel_ratio=3.0, max_extrap_factor=2.0)
                if E_half != E_half:
                    E_half = None
                result_row.append(E_half)
            else:
                result_row.append(None)
        # Tafel slope（若启用IR补偿，则使用补偿后的电位进行拟合）
        if params.get('tafel_enabled'):
            try:
                tafel_range = _parse_tafel_range(params.get('tafel_range','1-10'))
                if not tafel_range:
                    logger.warning("Invalid Tafel range: %s", params.get('tafel_range'))
                    raise ValueError('invalid tafel_range')
                lo, hi = tafel_range
                import numpy as _np
                I = _np.asarray(current, dtype=float)
                # 使用 IR 补偿后的电位（若可用），否则使用原始电位
                E_src = potential_compensated if (potential_compensated is not None) else potential
                E = _np.asarray(E_src, dtype=float)
                mask = _np.isfinite(I) & _np.isfinite(E) & (I>0) & (I>=min(lo,hi)) & (I<=max(lo,hi))
                if mask.sum() >= 3:
                    x = _np.log10(_np.clip(I[mask], 1e-12, None))
                    y = E[mask]
                    b, a = _np.polyfit(x, y, 1)
                    slope_mVdec = float(b * 1000.0)
                else:
                    slope_mVdec = None
            except Exception:
                slope_mVdec = None
            result_row.append(slope_mVdec)
        # 收集序列
        if params.get('collect_series') is not None:
            label_mode = params.get('label_mode','subfolder')
            series_label = file_stem if label_mode=='filename' else subname
            try:
                params['collect_series'].append({
                    'subname': subname,
                    'file_stem': file_stem,
                    'label': series_label,
                    'potential': potential,
                    'current': current,
                    'potential_comp': potential_compensated,
                    'current_signed': current_signed,
                    'targets_orig': target_potentials_original,
                    'targets_comp': target_potentials_compensated,
                    'ir': ir_compensation
                })
            except Exception:
                pass
        # per-file 明细导出
        if params.get('export_detail'):
            try:
                raw_records = []
                # build raw
                for idx,(pot,cur,cur_sig) in enumerate(zip(potential,current,current_signed)):
                    rec = {
                        'Potential(V)': pot,
                        'Current(mA/cm2)': cur,
                        'CurrentSigned(mA/cm2)': cur_sig
                    }
                    if potential_compensated is not None:
                        rec['Potential_IRComp(V)'] = potential_compensated[idx]
                    rec['IR_Ohm'] = ir_compensation
                    raw_records.append(rec)
                tgt_records = []
                for tc,orig_p in target_potentials_original.items():
                    rec = {
                        'Target_Current(mA/cm2)': tc,
                        'Potential_Orig(V)': orig_p,
                        'Potential_IRComp(V)': target_potentials_compensated.get(tc) if target_potentials_compensated else None,
                        'IR_Ohm': ir_compensation
                    }
                    tgt_records.append(rec)
                out_xlsx = os.path.join(subfolder, f"{file_stem}.xlsx")
                try:
                    with pd.ExcelWriter(out_xlsx, engine='openpyxl') as writer:
                        pd.DataFrame(raw_records).to_excel(writer, sheet_name='raw', index=False)
                        pd.DataFrame(tgt_records).to_excel(writer, sheet_name='targets', index=False)
                        # info sheet
                        info_rows = [
                            {'Key':'SoftwareVersion','Value': SOFTWARE_VERSION},
                            {'Key':'GeneratedAt','Value': datetime.now().isoformat(timespec='seconds')},
                            {'Key':'Sample','Value': subname},
                            {'Key':'SourceFile','Value': file},
                            {'Key':'Area_cm2','Value': params.get('area')},
                            {'Key':'IR_Method','Value': params.get('ir_method')},
                            {'Key':'IR_Ohm','Value': ir_compensation},
                            {'Key':'Targets(mA/cm2)','Value': ','.join([str(t) for t in target_currents])},
                        ]
                        pd.DataFrame(info_rows).to_excel(writer, sheet_name='info', index=False)
                except Exception:
                    # fallback csv
                    pd.DataFrame(raw_records).to_csv(os.path.join(subfolder, f"{file_stem}_raw.csv"), index=False, encoding='utf-8-sig')
                    pd.DataFrame(tgt_records).to_csv(os.path.join(subfolder, f"{file_stem}_targets.csv"), index=False, encoding='utf-8-sig')
            except Exception:
                pass
        
        # Tafel拟合图导出（如果启用）
        if params.get('export_tafel_plot', False):
            log(f"开始导出Tafel图...")
            import numpy as _np  # 用于log计算
            
            # 优先导出IR补偿Tafel图（推荐使用）
            if tafel_fit_data_ir is not None:
                log("找到IR补偿Tafel拟合数据，开始生成IR补偿Tafel图...")
                try:
                    plt.figure(figsize=(8, 6))
                    plt.rcParams['font.sans-serif'] = [font_to_use]
                    plt.rcParams['axes.unicode_minus'] = False
                    
                    # 绘制IR补偿数据点（在拟合范围内）- 传统Tafel图格式
                    data = tafel_fit_data_ir
                    # 计算log(j)用于X轴
                    log_j_data = _np.log10(_np.clip(data['I_data'], 1e-12, None))
                    log_j_fit = _np.log10(_np.clip(data['I_fit'], 1e-12, None))
                    
                    plt.scatter(log_j_data, data['E_data'], c='blue', s=30, alpha=0.7, label='IR-compensated Tafel data')
                    
                    # 绘制Tafel拟合线
                    plt.plot(log_j_fit, data['E_fit'], 'r-', linewidth=2, 
                            label=f"Tafel fit: {data['slope_mVdec']:.1f} mV/dec, R²={data['r2']:.3f}")
                    
                    plt.xlabel('log(j) [j in mA/cm²]')
                    plt.ylabel('Potential (V, IR-compensated)')
                    plt.title(f'Tafel Plot (IR-compensated) - {subname}_{file_stem} (Rs={data["ir_compensation"]:.2f}Ω)', 
                             fontname=font_to_use, fontsize=int(params['fontsize']))
                    if params.get('plot_grid', True):
                        plt.grid(True, alpha=0.3)
                    plt.legend()
                    plt.tight_layout()
                    tafel_ir_path = os.path.join(subfolder, f"{subname}_{file_stem}_Tafel_fit_IR.png")
                    plt.savefig(tafel_ir_path, dpi=300, bbox_inches='tight')
                    plt.close()
                    log(f"IR补偿Tafel拟合图已保存: {tafel_ir_path}")
                except Exception as e:
                    log(f"导出IR补偿Tafel图失败: {e}")
            elif tafel_fit_data_original is not None:
                log("未找到IR补偿数据，使用原始数据生成Tafel图（建议启用IR补偿获得更准确结果）...")
                try:
                    plt.figure(figsize=(8, 6))
                    plt.rcParams['font.sans-serif'] = [font_to_use]
                    plt.rcParams['axes.unicode_minus'] = False
                    
                    # 绘制原始数据点（在拟合范围内）- 传统Tafel图格式
                    data = tafel_fit_data_original
                    # 计算log(j)用于X轴
                    log_j_data = _np.log10(_np.clip(data['I_data'], 1e-12, None))
                    log_j_fit = _np.log10(_np.clip(data['I_fit'], 1e-12, None))
                    
                    plt.scatter(log_j_data, data['E_data'], c='blue', s=30, alpha=0.7, label='Original Tafel data')
                    
                    # 绘制Tafel拟合线
                    plt.plot(log_j_fit, data['E_fit'], 'r-', linewidth=2, 
                            label=f"Tafel fit: {data['slope_mVdec']:.1f} mV/dec, R²={data['r2']:.3f}")
                    
                    plt.xlabel('log(j) [j in mA/cm²]')
                    plt.ylabel('Potential (V)')
                    plt.title(f'Tafel Plot (Original Data) - {subname}_{file_stem}', fontname=font_to_use, fontsize=int(params['fontsize']))
                    if params.get('plot_grid', True):
                        plt.grid(True, alpha=0.3)
                    plt.legend()
                    plt.tight_layout()
                    tafel_path = os.path.join(subfolder, f"{subname}_{file_stem}_Tafel_fit.png")
                    plt.savefig(tafel_path, dpi=300, bbox_inches='tight')
                    plt.close()
                    log(f"原始数据Tafel拟合图已保存: {tafel_path}")
                except Exception as e:
                    log(f"导出原始Tafel图失败: {e}")
            else:
                log("警告：未找到可用的Tafel拟合数据！")
                log("请确保：1) 勾选了'计算Tafel斜率' 2) 如需准确结果，建议同时启用IR补偿功能")
        else:
            log("未启用Tafel图导出功能")

        # 保存处理历史记录
        if HISTORY_MANAGER_AVAILABLE:
            try:
                history_mgr = get_history_manager()
                record = {
                    'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'sample_name': subname,
                    'file_name': file_stem,
                    'file_path': filepath,
                    'type': 'LSV',
                    'status': 'success',
                    'results': {}
                }
                if params.get('run_id'):
                    record['run_id'] = params.get('run_id')

                if target_potentials_original:
                    for tc, pot in target_potentials_original.items():
                        record['results'][f'potential_at_{tc}'] = pot
                    if overpotential_enabled:
                        for tc, eta in target_overpotentials_original.items():
                            record['results'][f'overpotential_at_{tc}'] = eta
                if 10.0 in target_potentials_original:
                    record['results']['potential_10'] = target_potentials_original[10.0]
                    if overpotential_enabled:
                        record['results']['overpotential_10'] = target_overpotentials_original.get(10.0)
                        record['results']['equilibrium_potential'] = eqv
                        record['results']['overpotential_enabled'] = True
                if slope_mVdec is not None:
                    record['results']['tafel_slope'] = slope_mVdec
                if ir_compensation:
                    record['results']['ir_compensation'] = ir_compensation

                if not project_id and PROJECT_MANAGER_AVAILABLE:
                    proj_mgr = get_project_manager()
                    project_id = proj_mgr.get_default_project()
                    log(f"未指定项目，使用默认项目: {project_id}")

                record_data = {
                    'potential_compensated': list(potential_compensated) if potential_compensated is not None else None,
                    'potential_original': list(potential),
                    'current': list(current),
                    'target_currents': target_currents,
                    'ir_compensation': ir_compensation,
                    'tafel_fit_original': tafel_fit_data_original,
                    'tafel_fit_ir': tafel_fit_data_ir,
                }

                try:
                    history_mgr.add_record(
                        record,
                        data=record_data,
                        project_id=project_id
                    )
                except TypeError:
                    try:
                        history_mgr.add_record(
                            record,
                            project_id=project_id
                        )
                    except TypeError:
                        history_mgr.add_record(record)
            except Exception as e:
                log(f"保存LSV历史记录失败: {e}")

        # Tafel R² validation: warn if fit quality is low
        _tafel_data = tafel_fit_data_ir or tafel_fit_data_original
        if _tafel_data and _tafel_data.get('r2') is not None:
            _r2 = _tafel_data['r2']
            if _r2 < 0.99 and lsv_quality_report is not None:
                msg = f"Tafel 拟合 R²={_r2:.4f} < 0.99，拟合质量偏低，请检查拟合区间"
                if 'warnings' in lsv_quality_report:
                    lsv_quality_report['warnings'].append(msg)
                else:
                    lsv_quality_report['warnings'] = [msg]
                logger.warning(f"{file}: {msg}")

        return {
            'result_row': result_row,
            'quality_report': lsv_quality_report
        }

    else:
        # 准备返回结果：只有原始数据
        result_row = [subname, file_stem]
        for target_current in target_currents:
            original_pot = target_potentials_original.get(target_current, None)
            result_row.extend([original_pot])
        # 若 GUI 启用了 IR 补偿但未得到补偿值，也需要补齐占位列以匹配 CSV 头
        # 若启用 IR 补偿但未得到补偿值，需要补齐占位列以匹配 CSV 表头
        if params.get('ir_compensation_enabled', False):
            for _ in target_currents:
                result_row.append(None)  # IR 补偿电位占位
            result_row.append(None)      # Rs 占位
        if overpotential_enabled:
            for target_current in target_currents:
                result_row.append(target_overpotentials_original.get(target_current, None))
        # 可选指标：与上面顺序保持一致
        if params.get('onset_enabled'):
            try:
                j_on = float(str(params.get('onset_current','1.0')).replace(',','.'))
            except Exception:
                j_on = 1.0
            E_on, _ = potential_at_current(potential, current, target_i=j_on,
                                           min_pts=3, tafel_ratio=3.0, max_extrap_factor=2.0)
            if E_on != E_on:
                E_on = None
            result_row.append(E_on)
            if overpotential_enabled:
                eta_mV = None if E_on is None else abs((E_on - eqv) * 1000.0)
                result_row.append(eta_mV)
            try:
                hw_text = (params.get('halfwave_current') or '').strip()
                if hw_text:
                    j_half = float(hw_text)
                else:
                    import numpy as _np
                    j_half = 0.5 * float(_np.nanpercentile(_np.asarray(current, dtype=float), 95))
            except Exception:
                j_half = None
            if j_half is not None and j_half > 0:
                E_half, _ = potential_at_current(potential, current, target_i=j_half,
                                                 min_pts=3, tafel_ratio=3.0, max_extrap_factor=2.0)
                if E_half != E_half:
                    E_half = None
                result_row.append(E_half)
            else:
                result_row.append(None)
        if params.get('tafel_enabled'):
            try:
                tafel_range = _parse_tafel_range(params.get('tafel_range','1-10'))
                if not tafel_range:
                    logger.warning("Invalid Tafel range: %s", params.get('tafel_range'))
                    raise ValueError('invalid tafel_range')
                lo, hi = tafel_range
                import numpy as _np
                I = _np.asarray(current, dtype=float)
                E = _np.asarray(potential, dtype=float)
                mask = _np.isfinite(I) & _np.isfinite(E) & (I>0) & (I>=min(lo,hi)) & (I<=max(lo,hi))
                if mask.sum() >= 3:
                    x = _np.log10(_np.clip(I[mask], 1e-12, None))
                    y = E[mask]
                    b, a = _np.polyfit(x, y, 1)
                    slope_mVdec = float(b * 1000.0)
                else:
                    slope_mVdec = None
            except Exception:
                slope_mVdec = None
            result_row.append(slope_mVdec)
        if params.get('collect_series') is not None:
            label_mode = params.get('label_mode','subfolder')
            series_label = file_stem if label_mode=='filename' else subname
            try:
                params['collect_series'].append({
                    'subname': subname,
                    'file_stem': file_stem,
                    'label': series_label,
                    'potential': potential,
                    'current': current,
                    'potential_comp': None,
                    'current_signed': current_signed,
                    'targets_orig': target_potentials_original,
                    'targets_comp': {},
                    'ir': None
                })
            except Exception:
                pass
        if params.get('export_detail'):
            try:
                raw_records = []
                for pot,cur,cur_sig in zip(potential,current,current_signed):
                    raw_records.append({
                        'Potential(V)': pot,
                        'Current(mA/cm2)': cur,
                        'CurrentSigned(mA/cm2)': cur_sig,
                        'IR_Ohm': None
                    })
                tgt_records = []
                for tc,orig_p in target_potentials_original.items():
                    tgt_records.append({
                        'Target_Current(mA/cm2)': tc,
                        'Potential_Orig(V)': orig_p,
                        'Potential_IRComp(V)': None,
                        'IR_Ohm': None
                    })
                out_xlsx = os.path.join(subfolder, f"{file_stem}.xlsx")
                try:
                    with pd.ExcelWriter(out_xlsx, engine='openpyxl') as writer:
                        pd.DataFrame(raw_records).to_excel(writer, sheet_name='raw', index=False)
                        pd.DataFrame(tgt_records).to_excel(writer, sheet_name='targets', index=False)
                        info_rows = [
                            {'Key':'SoftwareVersion','Value': SOFTWARE_VERSION},
                            {'Key':'GeneratedAt','Value': datetime.now().isoformat(timespec='seconds')},
                            {'Key':'Sample','Value': subname},
                            {'Key':'SourceFile','Value': file},
                            {'Key':'Area_cm2','Value': params.get('area')},
                            {'Key':'IR_Method','Value': params.get('ir_method')},
                            {'Key':'IR_Ohm','Value': None},
                            {'Key':'Targets(mA/cm2)','Value': ','.join([str(t) for t in target_currents])},
                        ]
                        pd.DataFrame(info_rows).to_excel(writer, sheet_name='info', index=False)
                except Exception:
                    pd.DataFrame(raw_records).to_csv(os.path.join(subfolder, f"{file_stem}_raw.csv"), index=False, encoding='utf-8-sig')
                    pd.DataFrame(tgt_records).to_csv(os.path.join(subfolder, f"{file_stem}_targets.csv"), index=False, encoding='utf-8-sig')
            except Exception:
                pass
        
        # 保存处理历史记录
        if HISTORY_MANAGER_AVAILABLE:
            try:
                history_mgr = get_history_manager()
                record = {
                    'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'sample_name': subname,
                    'file_name': file_stem,
                    'file_path': filepath,
                    'type': 'LSV',
                    'status': 'success',
                    'results': {}
                }
                if params.get('run_id'):
                    record['run_id'] = params.get('run_id')
                
                # 写入关键指标到 results
                if target_potentials_original:
                    for tc, pot in target_potentials_original.items():
                        record['results'][f'potential_at_{tc}'] = pot
                    if overpotential_enabled:
                        for tc, eta in target_overpotentials_original.items():
                            record['results'][f'overpotential_at_{tc}'] = eta
                
                # 记录 10 mA/cm² 对应电位与过电位
                if 10.0 in target_potentials_original:
                    record['results']['potential_10'] = target_potentials_original[10.0]
                    if overpotential_enabled:
                        record['results']['overpotential_10'] = target_overpotentials_original.get(10.0)
                        record['results']['equilibrium_potential'] = eqv
                        record['results']['overpotential_enabled'] = True
                
                # 记录 Tafel 斜率
                if slope_mVdec is not None:
                    record['results']['tafel_slope'] = slope_mVdec
                
                # 记录 IR 补偿值
                if ir_compensation:
                    record['results']['ir_compensation'] = ir_compensation
                
                # 如果没有提供 project_id，则使用默认项目
                if not project_id and PROJECT_MANAGER_AVAILABLE:
                    proj_mgr = get_project_manager()
                    project_id = proj_mgr.get_default_project()
                    log(f"未指定项目，使用默认项目: {project_id}")

                record_data = {
                    'potential_compensated': list(potential_compensated) if potential_compensated is not None else None,
                    'potential_original': list(potential),
                    'current': list(current),
                    'target_currents': target_currents,
                    'ir_compensation': ir_compensation,
                    'tafel_fit_original': tafel_fit_data_original,
                    'tafel_fit_ir': tafel_fit_data_ir,
                }
                
                try:
                    history_mgr.add_record(
                        record,
                        data=record_data,
                        project_id=project_id
                    )
                except TypeError:
                    try:
                        history_mgr.add_record(
                            record,
                            project_id=project_id
                        )
                    except TypeError:
                        history_mgr.add_record(record)
            except Exception as e:
                log(f"写入 LSV 历史记录失败: {e}")
                log(f"保存LSV历史记录失败: {e}")
        
        # 返回结果：包含数据行和质量报告
        return {
            'result_row': result_row,
            'quality_report': lsv_quality_report  # 已在函数开始处初始化，必定存在
        }
