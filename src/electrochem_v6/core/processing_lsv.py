"""LSV processing helpers extracted from the shared processing core."""
from __future__ import annotations

import math
import os

import pandas as pd

from electrochem_v6.config import APP_VERSION as SOFTWARE_VERSION

from . import processing_core_v6 as core
from .processing_common import build_file_context
from .processing_lsv_calc import (
    _filter_outliers,
    _parse_tafel_range,
    apply_ir_compensation,
    interpolate_multiple_potentials,
    interpolate_potential,
    parse_target_currents,
    potential_at_current,
)
from .processing_lsv_export import export_lsv_detail
from .processing_lsv_history import (
    add_lsv_history_record,
    build_lsv_history_data,
    build_lsv_history_record,
)
from .processing_lsv_io import read_lsv_raw_data
from .processing_lsv_ir import (
    IR_COMPENSATION_FORMULA,
    extract_rs_from_eis,
    normalize_ir_extraction_method,
    normalize_ir_source,
    normalize_ir_validation_mode,
    resolve_lsv_eis_match,
)
from .processing_lsv_metrics import (
    build_lsv_result_row,
    compute_optional_metrics,
    compute_overpotentials,
    compute_target_potentials,
    parse_float_param,
)
from .processing_lsv_plot import export_lsv_tafel_plot, plot_lsv_curve
from .processing_quality import DataQualityChecker
from .processing_source_profile import (
    FREQUENCY_TO_HZ,
    IMPEDANCE_TO_OHM,
    column_number_to_index,
    imaginary_convention,
    unit_scale,
)
from .utils import as_bool as _as_bool

get_logger = core.get_logger
_resolve_plot_font = core._resolve_plot_font
log = core.log
HISTORY_MANAGER_AVAILABLE = core.HISTORY_MANAGER_AVAILABLE
PROJECT_MANAGER_AVAILABLE = core.PROJECT_MANAGER_AVAILABLE
get_history_manager = core.get_history_manager
get_project_manager = core.get_project_manager

__all__ = [
    "_filter_outliers",
    "_parse_tafel_range",
    "apply_ir_compensation",
    "get_ir_from_eis",
    "interpolate_multiple_potentials",
    "interpolate_potential",
    "parse_target_currents",
    "potential_at_current",
    "process_lsv",
]

def get_ir_from_eis(subfolder, eis_filename, start_line, method="auto", hf_points=10):
    """Compatibility wrapper returning the accepted Rs value only.

    New processing code should call :func:`extract_rs_from_eis` directly so
    that confidence, fit quality, and rejection reasons remain available.
    """

    filepath = os.path.join(subfolder, eis_filename)
    result = extract_rs_from_eis(
        filepath,
        start_line=start_line,
        method=method,
        hf_points=hf_points,
        validation_mode="strict",
    )
    rs_ohm = result.rs_ohm
    if not result.accepted or rs_ohm is None:
        log(f"EIS Rs extraction rejected for {filepath}: {result.message}")
        return None
    for warning in result.warnings:
        log(f"EIS Rs extraction warning for {filepath}: {warning}")
    log(
        f"EIS Rs={rs_ohm:.3f} Ohm "
        f"(method={result.method_used}, confidence={result.confidence})"
    )
    return float(rs_ohm)


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
    ctx = build_file_context(subfolder, file, params)
    filepath = ctx.filepath
    subname = ctx.sample_name
    file_stem = ctx.file_stem
    output_dir = ctx.output_dir

    logger.info(f"开始处理LSV文件: {file} (样品: {subname})")

    # 初始化Tafel拟合数据存储变量
    tafel_fit_data_original = None
    tafel_fit_data_ir = None
    slope_mVdec = None  # 初始化 Tafel 斜率变量，避免未启用时引用错误
    lsv_quality_report = None  # 初始化质量报告变量，确保始终存在

    raw_lsv = read_lsv_raw_data(filepath, file_label=file, params=params, logger=logger)
    potential = raw_lsv.potential
    current = raw_lsv.current
    current_signed = raw_lsv.current_signed
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

    # iR compensation source selection and provenance.
    ir_compensation = 0.0
    potential_compensated = None
    ir_resolution = None
    ir_diagnostics = None
    ir_source_profile = None
    extraction_method = None
    if params.get('ir_compensation_enabled', False):
        logger.info("开始 iR 补偿处理...")
        source = normalize_ir_source(params)
        extraction_method = normalize_ir_extraction_method(params)
        if source == "manual":
            try:
                ir_compensation = float(params.get('ir_manual_ohm', 0) or 0)
            except Exception as exc:
                raise ValueError("手动 Rs 必须是有效数字") from exc
            if not math.isfinite(ir_compensation) or ir_compensation <= 0:
                raise ValueError("手动 Rs 必须大于 0 Ohm")
            ir_resolution = resolve_lsv_eis_match(
                filepath,
                params.get('input_root') or subfolder,
                params,
            )
            logger.info(f"采用手动 Rs: {ir_compensation:.3f} Ohm")
        else:
            ir_resolution = resolve_lsv_eis_match(
                filepath,
                params.get('input_root') or subfolder,
                params,
            )
            if ir_resolution.get("status") != "matched":
                raise ValueError(str(ir_resolution.get("message") or "未找到可用的 EIS 文件"))
            eis_path = str(ir_resolution.get("eis_file") or "")
            logger.info(f"使用 EIS 文件提取 Rs: {eis_path}")
            raw_eis_start_line = params.get('ir_eis_start_line')
            if raw_eis_start_line in (None, "", "auto"):
                eis_start_line = core.resolve_data_start_line(eis_path)
            else:
                eis_start_line = max(1, int(raw_eis_start_line))
            validation_mode = normalize_ir_validation_mode(params)
            frequency_column = column_number_to_index(
                params.get('ir_eis_frequency_column', params.get('eis_frequency_column', 1)),
                default=1,
                label="iR EIS frequency column",
            )
            zreal_column = column_number_to_index(
                params.get('ir_eis_zreal_column', params.get('eis_zreal_column', 2)),
                default=2,
                label="iR EIS Z-real column",
            )
            zimag_column = column_number_to_index(
                params.get('ir_eis_zimag_column', params.get('eis_zimag_column', 3)),
                default=3,
                label="iR EIS Z-imaginary column",
            )
            frequency_unit, frequency_scale = unit_scale(
                params.get('ir_eis_frequency_unit', params.get('eis_frequency_unit')),
                default="hz",
                supported=FREQUENCY_TO_HZ,
            )
            impedance_unit, impedance_scale = unit_scale(
                params.get('ir_eis_impedance_unit', params.get('eis_impedance_unit')),
                default="ohm",
                supported=IMPEDANCE_TO_OHM,
            )
            zimag_convention, zimag_sign = imaginary_convention(
                params.get(
                    'ir_eis_zimag_convention',
                    params.get('eis_zimag_convention', 'z_imaginary'),
                )
            )
            ir_source_profile = {
                'frequency_column': frequency_column + 1,
                'zreal_column': zreal_column + 1,
                'zimag_column': zimag_column + 1,
                'frequency_unit': frequency_unit,
                'impedance_unit': impedance_unit,
                'zimag_convention': zimag_convention,
                'normalized_frequency_unit': 'Hz',
                'normalized_impedance_unit': 'Ohm',
            }
            ir_diagnostics = extract_rs_from_eis(
                eis_path,
                start_line=eis_start_line,
                method=extraction_method,
                hf_points=params.get('ir_linear_points', 10),
                validation_mode=validation_mode,
                frequency_column=frequency_column,
                zreal_column=zreal_column,
                zimag_column=zimag_column,
                frequency_scale=frequency_scale,
                impedance_scale=impedance_scale,
                zimag_sign=zimag_sign,
            )
            ir_value = ir_diagnostics.rs_ohm
            if ir_value is None or not math.isfinite(float(ir_value)) or ir_value <= 0:
                raise ValueError(
                    f"无法从 EIS 文件提取可信 Rs: {eis_path}; {ir_diagnostics.message}"
                )
            ir_compensation = float(ir_value)
            params['ir_eis_start_line_resolved'] = eis_start_line
            params['ir_validation_mode_resolved'] = validation_mode
            params['ir_extraction_method_resolved'] = ir_diagnostics.method_used
            params['ir_extraction_diagnostics'] = ir_diagnostics.to_dict()
            for warning in ir_diagnostics.warnings:
                logger.warning(f"{file}: {warning}")
            logger.info(f"成功获取 Rs: {ir_compensation:.3f} Ohm")

        area_cm2 = float(params.get('area', 1.0))
        potential_compensated = apply_ir_compensation(
            potential,
            current_signed,
            area_cm2=area_cm2,
            resistance_ohm=ir_compensation,
        )
        params['ir_source_resolved'] = source
        if source != "eis":
            params['ir_extraction_method_resolved'] = "manual"
            params['ir_validation_mode_resolved'] = "user_provided"
        params['ir_eis_search_scope_resolved'] = ir_resolution.get('scope') if ir_resolution else None
        params['ir_eis_file_resolved'] = ir_resolution.get('eis_file') if ir_resolution else None
        params['ir_compensation_ohm'] = ir_compensation
        params['ir_compensation_formula'] = IR_COMPENSATION_FORMULA

    # 计算多个目标电流对应的电位（覆盖则插值；不足则稳健外推）
    original_targets = compute_target_potentials(potential, current, target_currents)
    target_potentials_original = original_targets.potentials
    ext_segments_original = original_targets.ext_segments

    target_potentials_compensated = {}
    ext_segments_compensated = []
    if potential_compensated is not None:
        compensated_targets = compute_target_potentials(potential_compensated, current, target_currents)
        target_potentials_compensated = compensated_targets.potentials
        ext_segments_compensated = compensated_targets.ext_segments

    overpotential_enabled = _as_bool(params.get('overpotential_enabled', False))
    eqv = parse_float_param(params.get('eq_potential', 0.0), 0.0)
    target_overpotentials_original = (
        compute_overpotentials(target_potentials_original, eqv)
        if overpotential_enabled
        else {}
    )

    font_to_use = _resolve_plot_font(
        params.get('font'),
        text=f"{params.get('title', '')} 频率 相位 幅值 图",
    )
    title = params['title'].replace("{sample}", subname)
    original_plot = plot_lsv_curve(
        potential=potential,
        current=current,
        target_currents=target_currents,
        target_potentials=target_potentials_original,
        ext_segments=ext_segments_original,
        params=params,
        title=title,
        image_path=os.path.join(output_dir, f"{subname}_{file_stem}_LSV.png"),
        font_name=font_to_use,
        curve_label='LSV curve',
        logger=logger,
        enable_tafel_overlay=bool(params.get('tafel_enabled') and potential_compensated is None),
    )
    tafel_fit_data_original = original_plot.tafel_fit_data

    # 如果进行了IR补偿，绘制补偿后的LSV曲线
    if potential_compensated is not None:
        font_to_use = _resolve_plot_font(params.get('font'))
        title_compensated = params['title'].replace("{sample}", subname) + f" (IR: {ir_compensation:.2f}Ω)"
        ir_plot = plot_lsv_curve(
            potential=potential_compensated,
            current=current,
            target_currents=target_currents,
            target_potentials=target_potentials_compensated,
            ext_segments=ext_segments_compensated,
            params=params,
            title=title_compensated,
            image_path=os.path.join(output_dir, f"{subname}_{file_stem}_LSV_IR_compensated.png"),
            font_name=font_to_use,
            curve_label='IR compensated LSV curve',
            logger=logger,
            enable_tafel_overlay=bool(params.get('tafel_enabled')),
            ir_compensation=ir_compensation,
        )
        tafel_fit_data_ir = ir_plot.tafel_fit_data


    optional_metrics = compute_optional_metrics(
        params=params,
        potential=potential,
        current=current,
        potential_for_tafel=potential_compensated if potential_compensated is not None else potential,
        equilibrium_potential=eqv,
        overpotential_enabled=overpotential_enabled,
        logger=logger,
    )
    slope_mVdec = optional_metrics.tafel_slope_mVdec
    result_row = build_lsv_result_row(
        sample_name=subname,
        file_stem=file_stem,
        target_currents=target_currents,
        target_potentials_original=target_potentials_original,
        target_potentials_compensated=target_potentials_compensated,
        ir_compensation=ir_compensation,
        ir_columns_enabled=bool(potential_compensated is not None or params.get('ir_compensation_enabled', False)),
        target_overpotentials_original=target_overpotentials_original,
        overpotential_enabled=overpotential_enabled,
        optional_metrics=optional_metrics,
        onset_enabled=bool(params.get('onset_enabled')),
        halfwave_enabled=bool(params.get('halfwave_enabled')),
        tafel_enabled=bool(params.get('tafel_enabled')),
    )

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
                'targets_comp': target_potentials_compensated if potential_compensated is not None else {},
                'ir': ir_compensation if potential_compensated is not None else None,
            })
        except Exception:
            pass

    if params.get('export_detail'):
        try:
            export_lsv_detail(
                output_dir=output_dir,
                file_stem=file_stem,
                sample_name=subname,
                source_file=file,
                params=params,
                target_currents=target_currents,
                potential=potential,
                current=current,
                current_signed=current_signed,
                target_potentials_original=target_potentials_original,
                target_potentials_compensated=target_potentials_compensated if potential_compensated is not None else {},
                potential_compensated=potential_compensated,
                ir_compensation=ir_compensation if potential_compensated is not None else None,
                software_version=SOFTWARE_VERSION,
            )
        except Exception:
            pass

    if params.get('export_tafel_plot', False):
        log("开始导出Tafel图...")
    export_lsv_tafel_plot(
        output_dir=output_dir,
        sample_name=subname,
        file_stem=file_stem,
        params=params,
        font_name=font_to_use,
        tafel_fit_original=tafel_fit_data_original,
        tafel_fit_ir=tafel_fit_data_ir,
        log_func=log,
    )

    if HISTORY_MANAGER_AVAILABLE:
        try:
            history_mgr = get_history_manager()
            record = build_lsv_history_record(
                sample_name=subname,
                file_stem=file_stem,
                file_path=filepath,
                params=params,
                target_potentials_original=target_potentials_original,
                target_overpotentials_original=target_overpotentials_original,
                overpotential_enabled=overpotential_enabled,
                equilibrium_potential=eqv,
                slope_mVdec=slope_mVdec,
                ir_compensation=ir_compensation,
            )

            if not project_id and PROJECT_MANAGER_AVAILABLE:
                proj_mgr = get_project_manager()
                project_id = proj_mgr.get_default_project()
                log(f"未指定项目，使用默认项目: {project_id}")

            record_data = build_lsv_history_data(
                potential=potential,
                potential_compensated=potential_compensated,
                current=current,
                target_currents=target_currents,
                ir_compensation=ir_compensation,
                tafel_fit_original=tafel_fit_data_original,
                tafel_fit_ir=tafel_fit_data_ir,
            )
            add_lsv_history_record(history_mgr, record, data=record_data, project_id=project_id)
        except Exception as e:
            log(f"保存LSV历史记录失败: {e}")

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
        'quality_report': lsv_quality_report,
        'source_profile': {
            'potential_column': raw_lsv.potential_column,
            'current_column': raw_lsv.current_column,
            'potential_unit': raw_lsv.potential_unit,
            'current_unit': raw_lsv.current_unit,
            'normalized_potential_unit': 'V',
            'normalized_current_unit': 'mA/cm2',
        },
        'ir_provenance': {
            'enabled': bool(params.get('ir_compensation_enabled', False)),
            'lsv_file': filepath,
            'source': params.get('ir_source_resolved'),
            'method': params.get('ir_extraction_method_resolved'),
            'requested_method': extraction_method if params.get('ir_compensation_enabled', False) else None,
            'validation_mode': params.get('ir_validation_mode_resolved'),
            'scope': params.get('ir_eis_search_scope_resolved'),
            'eis_file': params.get('ir_eis_file_resolved'),
            'eis_start_line': params.get('ir_eis_start_line_resolved'),
            'rs_ohm': ir_compensation if potential_compensated is not None else None,
            'confidence': (
                ir_diagnostics.confidence
                if ir_diagnostics is not None
                else ('user_provided' if potential_compensated is not None else None)
            ),
            'fit_r2': ir_diagnostics.fit_r2 if ir_diagnostics is not None else None,
            'hf_point_count': ir_diagnostics.hf_point_count if ir_diagnostics is not None else None,
            'warnings': list(ir_diagnostics.warnings) if ir_diagnostics is not None else [],
            'message': ir_diagnostics.message if ir_diagnostics is not None else None,
            'source_profile': ir_source_profile,
            'formula': params.get('ir_compensation_formula'),
        },
    }
