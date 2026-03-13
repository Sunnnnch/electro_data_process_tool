"""Pipeline orchestration and data-start helpers for v6 processing.

Parallelism architecture
~~~~~~~~~~~~~~~~~~~~~~~~
The pipeline processes *work_units* (sub-directories) sequentially by default.
Set the environment variable ``ELECTROCHEM_V6_PARALLEL_WORKERS`` to an integer
> 1 to process multiple sub-directories concurrently via
``concurrent.futures.ThreadPoolExecutor``.

**Limitation**: matplotlib's *pyplot* module maintains global "current figure"
state which is not thread-safe.  ``_PIPELINE_LOCK`` serialises all
``core.process_*()`` calls that use pyplot, so the actual speedup comes from
overlapping I/O (file scanning, parameter construction, data loading) across
threads while one thread holds the lock for plotting.

To achieve full CPU-parallel processing, the individual processing modules
(``processing_lsv``, ``processing_cv``, etc.) should be refactored to use the
OOP matplotlib API (``Figure()`` / ``Axes``) instead of ``pyplot``.
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from electrochem_v6.core.utils import as_bool as _as_bool

# ── parallel processing configuration ────────────────────────────────────
_MAX_PARALLEL_WORKERS = max(1, int(os.environ.get("ELECTROCHEM_V6_PARALLEL_WORKERS", "1")))
_PIPELINE_LOCK = threading.Lock()


def natural_sort_key(s):
    import re
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', str(s))]


def auto_detect_data_start(file_path: str, encodings: Optional[Sequence[str]] = None) -> int:
    """Auto-detect the first data line (1-based) in a text file."""
    encodings = encodings or ['utf-8', 'gbk', 'latin-1']
    lines: List[str] = []
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as handle:
                lines = handle.readlines()
            break
        except UnicodeDecodeError:
            continue
    if not lines:
        return 22

    min_consecutive = 3
    consecutive = 0
    data_start = None
    for idx, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            consecutive = 0
            continue
        if line.startswith(('#', '//', '%')):
            consecutive = 0
            continue
        parts = line.split()
        if len(parts) < 2:
            consecutive = 0
            continue
        try:
            float(parts[0])
            float(parts[1])
            consecutive += 1
            if consecutive >= min_consecutive:
                data_start = idx - consecutive + 1 + 1
                break
        except ValueError:
            consecutive = 0
    if data_start is None:
        return 22
    return max(1, data_start)


def resolve_data_start_line(file_path: str, params: Dict[str, Any]) -> int:
    if _as_bool(params.get('auto_detect_start', True)):
        return auto_detect_data_start(file_path)
    manual = params.get('manual_start_line')
    if manual is not None:
        try:
            return max(1, int(manual))
        except (TypeError, ValueError):
            pass
    return 22


class NumpyEncoder(json.JSONEncoder):
    """自定义 JSON 编码器，处理 NumPy 数据类型"""
    def default(self, o):  # type: ignore[override]
        if isinstance(o, (np.integer,)):  # type: ignore[arg-type]
            return int(o)
        elif isinstance(o, (np.floating,)):  # type: ignore[arg-type]
            return float(o)
        elif isinstance(o, np.ndarray):
            return o.tolist()
        return super().default(o)


def _atomic_write(path: str, payload: Any) -> None:
    """Write JSON atomically via temp-file + rename to prevent corruption."""
    import tempfile
    target = os.path.abspath(path)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _is_result_file(filename: str) -> bool:
    """Check if *filename* matches common result / output file patterns."""
    lower_name = filename.lower()
    result_patterns = [
        '_results.csv',
        'results.csv',
        '_combined_',
        'combined_',
        '_quality_report',
        'quality_report',
        '_summary',
    ]
    return any(pattern in lower_name for pattern in result_patterns)


def run_pipeline(
    folder_path: str,
    gui_vars: Optional[Dict[str, Any]] = None,
    *,
    callbacks: Optional[Dict[str, Callable[..., None]]] = None,
    resolve_start_line: Optional[Callable[[str], int]] = None,
) -> Dict[str, Any]:
    """Execute the full processing pipeline for a data folder."""
    from . import processing_core_v6 as core
    logger = core.get_logger()
    callbacks = callbacks or {}
    gui_vars = dict(gui_vars or {})
    folder_path = os.path.abspath(folder_path)
    project_id = gui_vars.get('project_id')

    status_cb = callbacks.get('status')
    stage_cb = callbacks.get('stage')
    progress_cb = callbacks.get('progress')

    def emit_status(message: str) -> None:
        msg = str(message)
        if status_cb:
            try:
                status_cb(msg)
            except Exception:
                pass
        else:
            core.log(msg)

    def emit_stage(stage: str, percent: int) -> None:
        if stage_cb:
            try:
                stage_cb(stage, int(percent))
            except TypeError:
                try:
                    stage_cb(stage)
                except Exception:
                    pass
            except Exception:
                pass

    def emit_progress(percent: int) -> None:
        pct = int(max(0, min(100, percent)))
        if progress_cb:
            try:
                progress_cb(pct)
            except Exception:
                pass

    if not os.path.isdir(folder_path):
        raise FileNotFoundError(f"Folder not found: {folder_path}")

    # Normalise shared defaults
    try:
        area = float(gui_vars.get('area', gui_vars.get('area_cm2', 1.0) or 1.0))
    except Exception:
        area = 1.0
    gui_vars['area'] = gui_vars['area_cm2'] = area
    try:
        gui_vars['potential_offset'] = float(gui_vars.get('potential_offset', 0.0) or 0.0)
    except Exception:
        gui_vars['potential_offset'] = 0.0
    font_family = gui_vars.get('font_family') or gui_vars.get('font') or core.CHINESE_FONT
    gui_vars['font_family'] = font_family
    try:
        gui_vars['font_size'] = int(gui_vars.get('font_size', gui_vars.get('fontsize', 12)) or 12)
    except Exception:
        gui_vars['font_size'] = 12

    if resolve_start_line is None:
        def _resolver(path: str) -> int:
            return resolve_data_start_line(path, gui_vars)
    else:
        def _resolver(path: str) -> int:
            return resolve_start_line(path)

    emit_status("初始化...")
    emit_stage("读取", 0)

    entries = os.listdir(folder_path)
    dirs = [d for d in entries if os.path.isdir(os.path.join(folder_path, d))]
    dirs.sort(key=natural_sort_key)
    work_units: List[Tuple[str, List[str]]] = []
    root_files = [f for f in entries if os.path.isfile(os.path.join(folder_path, f))]
    root_files.sort(key=natural_sort_key)
    work_units.append((folder_path, root_files))
    for d in dirs:
        sub = os.path.join(folder_path, d)
        files = os.listdir(sub)
        files.sort(key=natural_sort_key)
        work_units.append((sub, files))

    total = max(1, len(work_units))

    lsv_enabled = _as_bool(gui_vars.get('lsv_enabled', False))
    cv_enabled = _as_bool(gui_vars.get('cv_enabled', False))
    eis_enabled = _as_bool(gui_vars.get('eis_enabled', False))
    ecsa_enabled = _as_bool(gui_vars.get('ecsa_enabled', False))

    preview_mode = _as_bool(gui_vars.get('preview_mode', False))
    try:
        preview_limit = int(gui_vars.get('preview_limit', 2) or 2)
    except Exception:
        preview_limit = 2
    preview_limit = max(1, preview_limit)

    collect_series = [] if (lsv_enabled and (_as_bool(gui_vars.get('lsv_combine_all', False)) or _as_bool(gui_vars.get('lsv_export_data', False)))) else None

    results_lsv: List[List[Any]] = []
    results_ecsa: List[List[Any]] = []
    saved_msgs: List[str] = []
    quality_reports: List[Dict[str, Any]] = []  # 收集所有质量检测报告
    skipped_errors: List[Dict[str, str]] = []  # 收集跳过的错误文件
    out_path_lsv: Optional[str] = None
    out_ecsa: Optional[str] = None
    combined_path: Optional[str] = None

    # ── define per-workunit processor (closure captures outer vars) ────
    def _process_one_workunit(
        idx: int, sub: str, files: List[str],
    ) -> None:
        """Process a single work-unit (sub-directory)."""
        file_list = list(files)
        if preview_mode:
            file_list = [f for f in file_list if f.lower().endswith(('.txt', '.csv'))][:preview_limit]
        file_list = [f for f in file_list if not _is_result_file(f)]

        emit_status(f"正在处理: {os.path.basename(sub) or os.path.basename(folder_path)}")
        emit_stage("读取", int((idx / total) * 60))

        # 统计待处理文件数，用于报告进度
        file_count = len(file_list)
        processed_in_sub = 0

        if lsv_enabled:
            match_mode = (gui_vars.get('lsv_match') or 'prefix').lower()
            prefix = gui_vars.get('lsv_prefix', 'LSV')
            for file in file_list:
                fl = file.lower()
                if not fl.endswith(('.txt', '.csv')):
                    continue
                if core._matches_named_file(file, match_mode, prefix):
                    file_path = os.path.join(sub, file)
                    dynamic_start_line = _resolver(file_path)
                    params = {
                        'start_line': str(dynamic_start_line),
                        'offset': gui_vars.get('potential_offset', 0.0),
                        'area': gui_vars.get('area', area),
                        'project_id': project_id,
                        'run_id': gui_vars.get('run_id'),
                        'xlabel': gui_vars.get('lsv_xlabel', 'Potential (V)'),
                        'ylabel': gui_vars.get('lsv_ylabel', 'Current Density (mA/cm²)'),
                        'title': gui_vars.get('lsv_title', 'LSV of {sample}'),
                        'font': gui_vars.get('font_family', font_family),
                        'fontsize': gui_vars.get('font_size', 12),
                        'target_current': gui_vars.get('lsv_target_current', '10'),
                        'line_color': gui_vars.get('lsv_line_color', 'blue'),
                        'line_width': gui_vars.get('lsv_line_width', 2.0),
                        'mark_targets': _as_bool(gui_vars.get('lsv_mark_targets', True), True),
                        'use_abs_current': _as_bool(gui_vars.get('use_abs_current', True), True),
                        'ir_compensation_enabled': _as_bool(gui_vars.get('ir_compensation_enabled', False)),
                        'eis_match': gui_vars.get('eis_match', 'prefix'),
                        'eis_prefix': gui_vars.get('eis_prefix', 'EIS'),
                        'eis_start_line': gui_vars.get('eis_start_line', '22'),
                        'tafel_enabled': _as_bool(gui_vars.get('tafel_enabled', False)),
                        'tafel_range': gui_vars.get('tafel_range', '1-10'),
                        'export_tafel_plot': _as_bool(gui_vars.get('export_tafel_plot', False)),
                        'ir_method': gui_vars.get('ir_method', 'auto'),
                        'ir_linear_points': gui_vars.get('ir_linear_points', 10),
                        'overpotential_enabled': _as_bool(gui_vars.get('overpotential_enabled', False)),
                        'onset_enabled': _as_bool(gui_vars.get('onset_enabled', False)),
                        'onset_current': gui_vars.get('onset_current', '1.0'),
                        'eq_potential': gui_vars.get('eq_potential', 0.0),
                        'halfwave_enabled': _as_bool(gui_vars.get('halfwave_enabled', False)),
                        'halfwave_current': gui_vars.get('halfwave_current', ''),
                        'collect_series': collect_series,
                        'label_mode': gui_vars.get('lsv_label_mode', 'subfolder'),
                        'plot_grid': _as_bool(gui_vars.get('plot_grid', True), True),
                        'export_detail': _as_bool(gui_vars.get('lsv_export_data', False)),
                        'ir_manual_ohm': gui_vars.get('ir_manual_ohm', 0.0),
                        'quality_config': {
                            'min_points_issue': gui_vars.get('lsv_quality_min_points_issue'),
                            'min_points_warning': gui_vars.get('lsv_quality_min_points_warning'),
                            'outlier_ratio_warning_pct': gui_vars.get('lsv_quality_outlier_warning_pct'),
                            'min_potential_span_warning': gui_vars.get('lsv_quality_min_potential_span'),
                            'noise_warning': gui_vars.get('lsv_quality_noise_warning'),
                            'noise_critical': gui_vars.get('lsv_quality_noise_critical'),
                            'jump_ratio_warning': gui_vars.get('lsv_quality_jump_warning'),
                            'jump_ratio_critical': gui_vars.get('lsv_quality_jump_critical'),
                            'local_variation_factor': gui_vars.get('lsv_quality_local_variation_factor'),
                        },
                    }
                    # 获取质量检测选项
                    enable_qc = _as_bool(gui_vars.get('lsv_quality_check', True), True)
                    processed_in_sub += 1
                    emit_status(f"LSV ({processed_in_sub}/{file_count}): {file}")
                    try:
                        with _PIPELINE_LOCK:
                            result = core.process_lsv(sub, file, params, project_id=project_id, enable_quality_check=enable_qc)
                    except Exception as exc:
                        core.log(f"LSV 处理跳过 {file}: {exc}")
                        skipped_errors.append({"file": os.path.join(sub, file), "type": "LSV", "error": str(exc)})
                        result = None
                    if result:
                        quality_report = None
                        # 新格式：result 是字典，包含 result_row 和 quality_report
                        if isinstance(result, dict):
                            result_row = result.get('result_row', [])
                            if result_row:
                                results_lsv.append(result_row)
                            quality_report = result.get('quality_report')
                            if quality_report:
                                logger.info(f"收集到质量报告: {file} - {quality_report.get('quality_level')}")
                        else:
                            # 兼容旧格式（直接是 result_row）
                            results_lsv.append(result)
                            logger.warning(f"使用旧格式返回值: {file}")

                        if not quality_report:
                            logger.warning(f"未找到质量报告: {file}，使用默认“合格”占位")
                            sample_name = os.path.basename(sub) or os.path.basename(folder_path)
                            quality_report = {
                                'filename': f"{sample_name}/{file}" if sample_name else file,
                                'is_valid': True,
                                'warnings': [],
                                'issues': [],
                                'quality_level': 'normal',
                                'recommendation': 'none',
                            }
                        quality_reports.append(quality_report)

        if cv_enabled:
            match_mode = (gui_vars.get('cv_match') or 'prefix').lower()
            prefix = gui_vars.get('cv_prefix', 'CV')
            for file in file_list:
                fl = file.lower()
                if not fl.endswith(('.txt', '.csv')):
                    continue
                if core._matches_named_file(file, match_mode, prefix):
                    file_path = os.path.join(sub, file)
                    dynamic_start_line = _resolver(file_path)
                    params = {
                        'start_line': str(dynamic_start_line),
                        'project_id': project_id,
                        'run_id': gui_vars.get('run_id'),
                        'xlabel': gui_vars.get('cv_xlabel', 'Potential (V)'),
                        'ylabel': gui_vars.get('cv_ylabel', 'Current (mA)'),
                        'title': gui_vars.get('cv_title', 'CV of {sample}'),
                        'font': gui_vars.get('font_family', font_family),
                        'fontsize': gui_vars.get('font_size', 12),
                        'line_color': gui_vars.get('cv_line_color', 'blue'),
                        'line_width': gui_vars.get('cv_line_width', 2.0),
                        'plot_grid': _as_bool(gui_vars.get('plot_grid', True), True),
                        'peaks_enabled': _as_bool(gui_vars.get('cv_peaks_enabled', False)),
                        'peaks_smooth': gui_vars.get('cv_peaks_smooth', 5),
                        'peaks_min_height': gui_vars.get('cv_peaks_min_height', 1.0),
                        'peaks_min_dist': gui_vars.get('cv_peaks_min_dist', 5),
                        'peaks_max': gui_vars.get('cv_peaks_max', 2),
                        'quality_config': {
                            'min_points_warning': gui_vars.get('cv_quality_min_points_warning'),
                            'cycle_completion_tolerance': gui_vars.get('cv_quality_cycle_tolerance'),
                        },
                    }
                    enable_qc = _as_bool(gui_vars.get('cv_quality_check', True), True)
                    processed_in_sub += 1
                    emit_status(f"CV ({processed_in_sub}/{file_count}): {file}")
                    try:
                        with _PIPELINE_LOCK:
                            try:
                                result = core.process_cv(sub, file, params, enable_quality_check=enable_qc)
                            except TypeError:
                                result = core.process_cv(sub, file, params)
                    except Exception as exc:
                        core.log(f"CV 处理跳过 {file}: {exc}")
                        skipped_errors.append({"file": os.path.join(sub, file), "type": "CV", "error": str(exc)})
                        result = None
                    if isinstance(result, dict):
                        quality_report = result.get('quality_report')
                        if quality_report:
                            quality_reports.append(quality_report)

        if eis_enabled:
            match_mode = (gui_vars.get('eis_match') or 'prefix').lower()
            prefix = gui_vars.get('eis_prefix', 'EIS')
            for file in file_list:
                fl = file.lower()
                if not fl.endswith(('.txt', '.csv')):
                    continue
                if core._matches_named_file(file, match_mode, prefix):
                    file_path = os.path.join(sub, file)
                    dynamic_start_line = _resolver(file_path)
                    params = {
                        'start_line': str(dynamic_start_line),
                        'project_id': project_id,
                        'run_id': gui_vars.get('run_id'),
                        'xlabel': gui_vars.get('eis_xlabel', "Z' (Ω)"),
                        'ylabel': gui_vars.get('eis_ylabel', "-Z'' (Ω)"),
                        'title': gui_vars.get('eis_title', 'EIS of {sample}'),
                        'font': gui_vars.get('font_family', font_family),
                        'fontsize': gui_vars.get('font_size', 12),
                        'line_color': gui_vars.get('eis_line_color', 'blue'),
                        'line_width': gui_vars.get('eis_line_width', 2.0),
                        'plot_grid': _as_bool(gui_vars.get('plot_grid', True), True),
                        'plot_nyquist': _as_bool(gui_vars.get('plot_nyquist', True), True),
                        'plot_bode': _as_bool(gui_vars.get('plot_bode', False)),
                        'randles_fit': _as_bool(gui_vars.get('eis_randles_fit', False)),
                    }
                    try:
                        processed_in_sub += 1
                        emit_status(f"EIS ({processed_in_sub}/{file_count}): {file}")
                        with _PIPELINE_LOCK:
                            core.process_eis(sub, file, params)
                    except Exception as exc:
                        core.log(f"EIS 处理跳过 {file}: {exc}")
                        skipped_errors.append({"file": os.path.join(sub, file), "type": "EIS", "error": str(exc)})

        if ecsa_enabled:
            ecsa_params = {
                'match': gui_vars.get('ecsa_match', 'prefix'),
                'match_prefix': gui_vars.get('ecsa_prefix', 'ECSA'),
                'project_id': project_id,
                'run_id': gui_vars.get('run_id'),
                'ev': gui_vars.get('ecsa_ev', 0.10),
                'last_n': gui_vars.get('ecsa_last_n', 1),
                'avg_last_n': _as_bool(gui_vars.get('ecsa_avg_last_n', False)),
                'cs_value': gui_vars.get('ecsa_cs_value', 40.0),
                'cs_unit': gui_vars.get('ecsa_cs_unit', 'µF/cm²'),
                'xlabel': gui_vars.get('ecsa_xlabel', 'Scan rate v (V/s)'),
                'ylabel': gui_vars.get('ecsa_ylabel', 'ΔJ (mA/cm²)'),
                'title': gui_vars.get('ecsa_title', 'ECSA of {sample} @ Ev={Ev:.3f} V'),
                'line_width': gui_vars.get('ecsa_line_width', 2.0),
                'use_abs_delta': _as_bool(gui_vars.get('ecsa_use_abs_delta', True), True),
            }
            common = {
                'area': gui_vars.get('area', area),
                'font': gui_vars.get('font_family', font_family),
                'fontsize': gui_vars.get('font_size', 12),
            }
            try:
                with _PIPELINE_LOCK:
                    ecsa_res = core.process_ecsa_for_subfolder(sub, file_list, ecsa_params, common)
            except Exception as exc:
                core.log(f"ECSA 处理跳过 {sub}: {exc}")
                skipped_errors.append({"file": sub, "type": "ECSA", "error": str(exc)})
                ecsa_res = None
            if ecsa_res:
                results_ecsa.append(ecsa_res)  # type: ignore[arg-type]

        emit_stage("分析", int(((idx + 1) / total) * 85))
        emit_progress(int(((idx + 1) / total) * 100))

    # ── execute work-units (serial or parallel) ──────────────────────
    _n_workers = min(_MAX_PARALLEL_WORKERS, len(work_units))
    if _n_workers > 1:
        with ThreadPoolExecutor(max_workers=_n_workers) as pool:
            futures = {
                pool.submit(_process_one_workunit, idx, sub, list(files)): idx
                for idx, (sub, files) in enumerate(work_units)
            }
            for future in as_completed(futures):
                future.result()  # propagate exceptions from worker threads
    else:
        for idx, (sub, files) in enumerate(work_units):
            _process_one_workunit(idx, sub, list(files))

    if lsv_enabled and results_lsv:
        emit_status("正在汇总导出 LSV 结果...")
        emit_stage("导出", 86)
        target_currents = core.parse_target_currents(gui_vars.get('lsv_target_current', '10')) or [10.0]
        columns = ['Sample_Name', 'File_Name']
        if target_currents:
            if _as_bool(gui_vars.get('ir_compensation_enabled', False)):
                for tc in target_currents:
                    columns.extend([
                        f"Potential@{tc}mA/cm²(Original)",
                        f"Potential@{tc}mA/cm²(IR_compensated)"
                    ])
            else:
                for tc in target_currents:
                    columns.append(f"Potential@{tc}mA/cm²")
        if _as_bool(gui_vars.get('ir_compensation_enabled', False)):
            columns.append("R_solution(Ω)")
        if _as_bool(gui_vars.get('overpotential_enabled', False)):
            try:
                eqv = float(gui_vars.get('eq_potential', 0.0))
            except Exception:
                eqv = 0.0
            for tc in target_currents:
                columns.append(f"Overpotential@{tc}mA/cm²(mV)@Eq={eqv}V")
        if _as_bool(gui_vars.get('onset_enabled', False)):
            try:
                onset_j = float(str(gui_vars.get('onset_current', '1.0')).replace(',', '.'))
            except Exception:
                onset_j = 1.0
            columns.append(f"OnsetPotential@{onset_j}mA/cm²(V)")
            if _as_bool(gui_vars.get('overpotential_enabled', False)):
                try:
                    eqv = float(gui_vars.get('eq_potential', 0.0))
                except Exception:
                    eqv = 0.0
                columns.append(f"OnsetOverpotential(mV)@Eq={eqv}V")
        if _as_bool(gui_vars.get('halfwave_enabled', False)):
            columns.append("HalfWavePotential(V)")
        if _as_bool(gui_vars.get('tafel_enabled', False)):
            columns.append("TafelSlope(mV/dec)")
        df = pd.DataFrame(results_lsv, columns=columns)  # type: ignore[arg-type]
        try:
            df['__skey'] = df['Sample_Name'].map(natural_sort_key)
            df['__fkey'] = df['File_Name'].map(natural_sort_key)
            df = df.sort_values(by=['__skey', '__fkey'], kind='mergesort').drop(columns=['__skey', '__fkey'])
        except Exception:
            pass
        name_lsv = gui_vars.get('csv_filename', 'LSV_results.csv')
        if preview_mode:
            base, ext = os.path.splitext(name_lsv)
            name_lsv = f"{base}_preview{ext or '.csv'}"
        out_path_lsv = os.path.join(folder_path, name_lsv)
        df.to_csv(out_path_lsv, index=False, encoding='utf-8-sig')
        saved_msgs.append(f"LSV结果: {out_path_lsv}")

        if _as_bool(gui_vars.get('lsv_combine_all', False)) and collect_series:
            try:
                import matplotlib.pyplot as _plt
                _plt.figure(figsize=(9, 6))
                colors = _plt.rcParams['axes.prop_cycle'].by_key().get('color', [])
                for idx, series in enumerate(collect_series):
                    color = colors[idx % len(colors)] if colors else None
                    _plt.plot(series['potential'], series['current'], label=series['label'], linewidth=1.5, color=color)
                _plt.xlabel(gui_vars.get('lsv_xlabel', 'Potential (V)'))
                _plt.ylabel(gui_vars.get('lsv_ylabel', 'Current Density (mA/cm²)'))
                _plt.title('Combined LSV Curves')
                if _as_bool(gui_vars.get('plot_grid', True), True):
                    _plt.grid(True, alpha=0.3)
                _plt.legend(fontsize=8, ncol=2)
                _plt.tight_layout()
                combined_path = os.path.join(folder_path, 'LSV_combined.png')
                _plt.savefig(combined_path, dpi=300, bbox_inches='tight')
                _plt.close()
                saved_msgs.append(f"LSV汇总图: {combined_path}")
            except Exception as exc:
                core.log(f'生成LSV汇总图失败: {exc}')

    if ecsa_enabled and results_ecsa:
        emit_status("正在导出 ECSA 结果...")
        emit_stage("导出", 92)
        df_ecsa = pd.DataFrame(results_ecsa, columns=[  # type: ignore[arg-type]
            'sample', 'Ev', 'n_used', 'avg_last_n', 'N_points', 'slope_mFcm2', 'intercept', 'R2',
            'Cdl_mFcm2', 'Cs_input', 'Cs_unit', 'Cs_mFcm2', 'ECSA_cm2', 'RF', 'png'
        ])
        try:
            df_ecsa['__skey'] = df_ecsa['sample'].map(natural_sort_key)
            df_ecsa = df_ecsa.sort_values(by=['__skey'], kind='mergesort').drop(columns=['__skey'])
        except Exception:
            pass
        ecsa_name = gui_vars.get('ecsa_csv_filename', 'ECSA_results.csv')
        if preview_mode:
            base, ext = os.path.splitext(ecsa_name)
            ecsa_name = f"{base}_preview{ext or '.csv'}"
        out_ecsa = os.path.join(folder_path, ecsa_name)
        df_ecsa.to_csv(out_ecsa, index=False, encoding='utf-8-sig')
        saved_msgs.append(f"ECSA结果: {out_ecsa}")

    summary_path = None
    quality_report_path = None
    quality_summary: Dict[str, Any] = {}
    try:
        # 生成质量报告统计
        quality_levels = {}
        recommendations = {}

        # 统计质量等级和建议分布
        for report in quality_reports:
            level = report.get('quality_level', 'unknown')
            quality_levels[level] = quality_levels.get(level, 0) + 1

            recommendation = report.get('recommendation', 'unknown')
            recommendations[recommendation] = recommendations.get(recommendation, 0) + 1

        # 过滤：只保留有问题的数据（有警告或问题的文件）
        problem_reports = [
            r for r in quality_reports
            if r.get('warnings') or r.get('issues') or not r.get('is_valid', True)
        ]

        quality_summary = {
            'total_files': len(quality_reports),
            'passed': sum(1 for r in quality_reports if r.get('is_valid', True)),
            'failed': sum(1 for r in quality_reports if not r.get('is_valid', True)),
            'warnings': sum(1 for r in quality_reports if r.get('warnings')),
            'skipped': len(skipped_errors),
            'quality_levels': quality_levels,
            'recommendations': recommendations,
            'files': problem_reports
        }

        # Persist latest quality summary for HTTP access
        try:
            from electrochem_v6.config import ensure_parent_dir, get_quality_report_file
            latest_report_path = str(ensure_parent_dir(get_quality_report_file()))
            with open(latest_report_path, 'w', encoding='utf-8') as handle:
                json.dump({
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "data": quality_summary,
                }, handle, ensure_ascii=False, indent=2, cls=NumpyEncoder)
        except Exception:
            pass

        # 保存详细质量报告
        if quality_reports:
            quality_report_path = os.path.join(folder_path, 'quality_report.json')
            _atomic_write(quality_report_path, quality_summary)
            saved_msgs.append(f"质量报告: {quality_report_path}")

        summary = {
            'version': '3.0.4',
            'folder': folder_path,
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'lsv': {
                'csv': out_path_lsv,
                'rows': int(len(results_lsv)) if isinstance(results_lsv, list) else 0,
            },
            'ecsa': {
                'csv': out_ecsa,
                'rows': int(len(results_ecsa)) if isinstance(results_ecsa, list) else 0,
            },
            'combined_lsv_png': combined_path,
            'messages': saved_msgs,
            'quality_report': quality_report_path,
            'quality_summary': quality_summary,
        }
        summary_path = os.path.join(folder_path, 'summary.json')
        _atomic_write(summary_path, summary)
        saved_msgs.append(summary_path)
        emit_stage("报告", 100)
    except PermissionError as exc:
        core.log(f'写入结果文件失败（权限不足）: {exc}')
        raise PermissionError(
            f"无法写入目录 {folder_path}，请检查该目录是否为只读、"
            f"文件是否被其他程序占用，或更换一个可写的数据目录后重试。"
        ) from exc
    except Exception as exc:
        core.log(f'写入 summary.json 失败: {exc}')

    emit_progress(100)
    return {
        'messages': saved_msgs,
        'lsv_csv': out_path_lsv,
        'ecsa_csv': out_ecsa,
        'combined_lsv_png': combined_path,
        'summary_path': summary_path,
        'quality_report_path': quality_report_path,
        'quality_reports': quality_reports,
        'quality_summary': quality_summary if 'quality_summary' in locals() else {},
        'skipped_errors': skipped_errors,
        'results_lsv': results_lsv,
        'results_ecsa': results_ecsa,
    }
