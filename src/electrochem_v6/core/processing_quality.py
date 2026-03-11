"""Quality checking helpers for v6 processing."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from . import processing_core_v6 as core


class DataQualityChecker:
    """Data quality validation and checking utilities."""

    DEFAULT_LSV_CONFIG: Dict[str, Any] = {
        "min_points_issue": 20,
        "min_points_warning": 50,
        "outlier_ratio_warning_pct": 10.0,
        "min_potential_span_warning": 0.1,
        "noise_warning": 3.0,
        "noise_critical": 7.0,
        "jump_ratio_warning": 0.10,
        "jump_ratio_critical": 0.20,
        "local_variation_factor": 8.0,
    }
    DEFAULT_CV_CONFIG: Dict[str, Any] = {
        "min_points_warning": 100,
        "cycle_completion_tolerance": 0.1,
    }

    @classmethod
    def normalize_lsv_config(cls, raw_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Merge user-supplied LSV quality thresholds with defaults."""
        config = dict(cls.DEFAULT_LSV_CONFIG)
        if not isinstance(raw_config, dict):
            return config

        for key, default_value in cls.DEFAULT_LSV_CONFIG.items():
            raw_value = raw_config.get(key)
            if raw_value in (None, ""):
                continue
            try:
                parsed = float(raw_value)
            except (TypeError, ValueError):
                continue
            if parsed < 0:
                continue
            if isinstance(default_value, int):
                parsed = int(parsed)
            config[key] = parsed

        config["min_points_warning"] = max(
            int(config["min_points_warning"]),
            int(config["min_points_issue"]),
        )
        config["noise_critical"] = max(
            float(config["noise_critical"]),
            float(config["noise_warning"]),
        )
        config["jump_ratio_critical"] = max(
            float(config["jump_ratio_critical"]),
            float(config["jump_ratio_warning"]),
        )
        config["local_variation_factor"] = max(float(config["local_variation_factor"]), 1.0)
        return config

    @classmethod
    def normalize_cv_config(cls, raw_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Merge user-supplied CV quality thresholds with defaults."""
        config = dict(cls.DEFAULT_CV_CONFIG)
        if not isinstance(raw_config, dict):
            return config

        for key, default_value in cls.DEFAULT_CV_CONFIG.items():
            raw_value = raw_config.get(key)
            if raw_value in (None, ""):
                continue
            try:
                parsed = float(raw_value)
            except (TypeError, ValueError):
                continue
            if parsed < 0:
                continue
            if isinstance(default_value, int):
                parsed = int(parsed)
            config[key] = parsed

        config["min_points_warning"] = max(int(config["min_points_warning"]), 1)
        config["cycle_completion_tolerance"] = max(float(config["cycle_completion_tolerance"]), 0.0)
        return config

    @staticmethod
    def check_lsv_data(
        df: pd.DataFrame,
        file_name: str = "",
        source_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Check LSV data quality and return detailed report.

        Args:
            df: DataFrame with 'Potential' and 'Current' columns
            file_name: Name of the file being checked (for logging)
            source_path: Optional absolute/relative path to original file (for plot placement)

        Returns:
            Dictionary containing:
                - is_valid: bool - whether data passes critical checks
                - issues: List[str] - critical issues that prevent processing
                - warnings: List[str] - non-critical quality concerns
                - stats: Dict - data statistics
                - suggestions: List[str] - recommendations for data cleaning
        """
        logger = core.get_logger()
        issues = []
        warnings = []
        suggestions = []
        quality_config = DataQualityChecker.normalize_lsv_config(config)

        try:
            # Check required columns
            if 'Potential' not in df.columns or 'Current' not in df.columns:
                issues.append("缺少必需列: 'Potential' 和/或 'Current'")
                return {
                    'is_valid': False,
                    'issues': issues,
                    'warnings': warnings,
                    'stats': {},
                    'suggestions': ["确保CSV文件包含 'Potential' 和 'Current' 列"]
                }

            # Check for empty data
            if len(df) == 0:
                issues.append("数据为空")
                return {
                    'is_valid': False,
                    'issues': issues,
                    'warnings': warnings,
                    'stats': {},
                    'suggestions': ["检查文件是否包含有效数据行"]
                }

            # Check for missing values
            null_potential = df['Potential'].isnull().sum()
            null_current = df['Current'].isnull().sum()
            if null_potential > 0 or null_current > 0:
                issues.append(f"发现缺失值: Potential({null_potential}), Current({null_current})")
                suggestions.append("使用线性插值填补缺失值: df.interpolate(method='linear')")

            # Check data point count
            data_points = len(df)
            min_points_issue = int(quality_config["min_points_issue"])
            min_points_warning = int(quality_config["min_points_warning"])
            if data_points < min_points_issue:
                issues.append(f"数据点过少 ({data_points}点)，至少需要{min_points_issue}点")
            elif data_points < min_points_warning:
                warnings.append(f"数据点较少 ({data_points}点)，建议 ≥{min_points_warning}点以获得更好分析结果")

            # Check potential monotonicity
            is_monotonic = df['Potential'].is_monotonic_increasing or df['Potential'].is_monotonic_decreasing
            if not is_monotonic:
                warnings.append("电位不单调变化，可能影响Tafel分析")
                suggestions.append("检查数据是否按电位扫描顺序排列")

            # Check for current outliers (using IQR method)
            Q1 = df['Current'].quantile(0.25)
            Q3 = df['Current'].quantile(0.75)
            IQR = Q3 - Q1
            outliers = df[(df['Current'] < Q1 - 3*IQR) | (df['Current'] > Q3 + 3*IQR)]
            if len(outliers) > 0:
                outlier_ratio = len(outliers) / len(df) * 100
                if outlier_ratio > float(quality_config["outlier_ratio_warning_pct"]):
                    warnings.append(f"发现 {len(outliers)} 个电流异常值 ({outlier_ratio:.1f}%)")
                    suggestions.append("考虑使用中位数绝对偏差(MAD)方法过滤异常值")

            # Check potential range
            pot_min, pot_max = df['Potential'].min(), df['Potential'].max()
            pot_range = pot_max - pot_min
            if pot_range < float(quality_config["min_potential_span_warning"]):
                warnings.append(f"电位扫描范围过小 ({pot_range:.3f}V)，建议 >0.2V")

            # Check for duplicate potential values
            duplicates = df['Potential'].duplicated().sum()
            if duplicates > 0:
                warnings.append(f"发现 {duplicates} 个重复的电位值")
                suggestions.append("检查数据采集设置或考虑平均处理重复值")

            # ===== 新增：数据抖动检测 =====
            noise_analysis = {}

            # 1. 二阶导数噪声水平检测（对LSV指数曲线更准确）
            if data_points >= 4:
                # 使用二阶导数（加速度）来检测噪声
                current_diff = np.diff(df['Current'].to_numpy())
                second_diff = np.diff(current_diff)

                # 计算相对噪声水平（归一化）
                second_diff_std = np.std(second_diff)
                current_range = df['Current'].max() - df['Current'].min()

                if current_range > 0:
                    # 归一化的噪声水平（相对于电流范围）
                    noise_level = second_diff_std / (current_range / data_points)
                else:
                    noise_level = 0

                noise_analysis['noise_level'] = float(noise_level)
                noise_analysis['second_derivative_std'] = float(second_diff_std)

                # 判断噪声水平（调整后的阈值）
                if noise_level > float(quality_config["noise_critical"]):
                    issues.append(f"数据剧烈抖动(噪声水平={noise_level:.2f})，建议丢弃并重新测量")
                    suggestions.append("可能原因：电极接触不良、电解液搅拌过度、扫描速度过快或电磁干扰")
                    noise_analysis['noise_severity'] = 'critical'
                elif noise_level > float(quality_config["noise_warning"]):
                    warnings.append(f"数据有明显抖动(噪声水平={noise_level:.2f})，建议平滑处理后使用")
                    suggestions.append("建议：降低扫描速度、检查电极连接、避免电解液气泡")
                    noise_analysis['noise_severity'] = 'warning'
                else:
                    noise_analysis['noise_severity'] = 'good'

            # 2. 连续突变点检测（基于变化率的稳定性）
            if data_points >= 5:
                current_diff = np.diff(df['Current'].to_numpy())

                # 计算差分的变化（二阶差分）
                diff_of_diff = np.diff(current_diff)

                # 使用标准差检测异常波动
                # 如果二阶差分的标准差相对于一阶差分的中位数过大，说明有突变
                diff_median = np.median(np.abs(current_diff))
                diff_of_diff_std = np.std(diff_of_diff)

                if diff_median > 1e-10:
                    fluctuation_ratio = diff_of_diff_std / diff_median

                    # 检测显著的突变点（超过3个标准差）
                    if len(diff_of_diff) > 0:
                        ddiff_mean = np.mean(diff_of_diff)
                        ddiff_std = np.std(diff_of_diff)
                        if ddiff_std > 1e-10:
                            outliers = np.abs(diff_of_diff - ddiff_mean) > 3 * ddiff_std
                            jump_count = int(np.sum(outliers))
                            jump_ratio = jump_count / len(diff_of_diff)
                        else:
                            jump_count = 0
                            jump_ratio = 0
                    else:
                        jump_count = 0
                        jump_ratio = 0
                else:
                    fluctuation_ratio = 0
                    jump_count = 0
                    jump_ratio = 0

                noise_analysis['jump_count'] = jump_count
                noise_analysis['jump_ratio'] = float(jump_ratio)
                noise_analysis['fluctuation_ratio'] = float(fluctuation_ratio)

                # 判断突变点比例
                if jump_ratio > float(quality_config["jump_ratio_critical"]):
                    issues.append(f"发现{jump_count}个突变点(占{jump_ratio:.1%})，数据不稳定，建议丢弃")
                    noise_analysis['jump_severity'] = 'critical'
                elif jump_ratio > float(quality_config["jump_ratio_warning"]):
                    warnings.append(f"发现{jump_count}个突变点(占{jump_ratio:.1%})，存在毛刺")
                    suggestions.append("建议：使用Savitzky-Golay滤波或移动平均平滑")
                    noise_analysis['jump_severity'] = 'warning'
                else:
                    noise_analysis['jump_severity'] = 'good'

            # 3. 局部波动检测（定位问题区域）
            if data_points >= 10:
                window_size = min(5, data_points // 4)
                local_variations = []

                for i in range(len(df) - window_size):
                    local_diff = np.diff(df['Current'].iloc[i:i+window_size].values)
                    local_var = np.std(local_diff)
                    local_variations.append(local_var)

                if local_variations:
                    max_variation = max(local_variations)
                    avg_variation = np.mean(local_variations)

                    noise_analysis['max_local_variation'] = float(max_variation)
                    noise_analysis['avg_local_variation'] = float(avg_variation)

                    if avg_variation > 0 and max_variation > float(quality_config["local_variation_factor"]) * avg_variation:
                        max_idx = local_variations.index(max_variation)
                        issue_position = f"数据点{max_idx}~{max_idx+window_size}附近"
                        warnings.append(f"存在局部剧烈抖动区域({issue_position})")
                        suggestions.append(f"建议：检查{issue_position}的原始数据，考虑删除或替换该区域")
                        noise_analysis['local_issue'] = True
                        noise_analysis['issue_position'] = [max_idx, max_idx + window_size]
                    else:
                        noise_analysis['local_issue'] = False

            # 综合判断严重程度
            if 'noise_severity' in noise_analysis and 'jump_severity' in noise_analysis:
                critical_count = sum([
                    1 for s in [noise_analysis['noise_severity'], noise_analysis['jump_severity']]
                    if s == 'critical'
                ])
                warning_count = sum([
                    1 for s in [noise_analysis['noise_severity'], noise_analysis['jump_severity']]
                    if s == 'warning'
                ])

                if critical_count >= 2:
                    noise_analysis['overall_quality'] = 'poor'
                    noise_analysis['recommendation'] = 'discard'
                elif critical_count >= 1 or warning_count >= 2:
                    noise_analysis['overall_quality'] = 'fair'
                    noise_analysis['recommendation'] = 'use_with_caution'
                elif warning_count >= 1:
                    noise_analysis['overall_quality'] = 'acceptable'
                    noise_analysis['recommendation'] = 'smooth_before_use'
                else:
                    noise_analysis['overall_quality'] = 'good'
                    noise_analysis['recommendation'] = 'ready_to_use'

            # Compile statistics
            stats = {
                'data_points': data_points,
                'potential_range': (float(pot_min), float(pot_max)),
                'potential_span': float(pot_range),
                'current_range': (float(df['Current'].min()), float(df['Current'].max())),
                'current_mean': float(df['Current'].mean()),
                'current_std': float(df['Current'].std()),
                'missing_values': null_potential + null_current,
                'outlier_count': len(outliers),
                'is_monotonic': is_monotonic,
                'noise_analysis': noise_analysis,
                'quality_config': quality_config,
            }

            plot_required = noise_analysis and (
                noise_analysis.get('overall_quality') in {'fair', 'poor'}
                or noise_analysis.get('noise_severity') in {'critical', 'warning'}
                or noise_analysis.get('jump_severity') in {'critical', 'warning'}
                or noise_analysis.get('local_issue') is True
            )
            if plot_required:
                custom_dir = None
                if source_path:
                    try:
                        custom_dir = Path(source_path).resolve().parent / "diagnostic_plots"
                    except Exception:
                        custom_dir = None
                plot_path = core.save_waveform_plot(df, file_name, noise_analysis, base_dir=custom_dir)
                if plot_path:
                    noise_analysis['plot_path'] = plot_path
                    stats['noise_plot_path'] = plot_path
                    vision_result = core.run_vision_analysis(plot_path, file_name, noise_analysis)
                    if vision_result:
                        noise_analysis['vision_analysis'] = vision_result
                        stats['vision_analysis'] = vision_result

            is_valid = len(issues) == 0

            # Log quality check results
            if is_valid:
                logger.info(f"✓ 数据质量检查通过: {file_name} ({data_points}点)")
                if warnings:
                    logger.warning(f"质量警告 [{file_name}]: {'; '.join(warnings[:2])}")
            else:
                logger.error(f"✗ 数据质量检查失败: {file_name} - {'; '.join(issues)}")

            # 计算质量等级和建议
            quality_level = "good"  # 默认等级
            recommendation = "ready_to_use"  # 默认建议

            if issues:
                quality_level = "poor"
                recommendation = "discard"
            elif len(warnings) >= 3:
                quality_level = "poor"
                recommendation = "use_with_caution"
            elif len(warnings) == 2:
                quality_level = "fair"
                recommendation = "smooth_before_use"
            elif len(warnings) == 1:
                quality_level = "acceptable"
                recommendation = "ready_to_use"

            # 生成时间戳
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            return {
                'filename': file_name,
                'timestamp': timestamp,
                'is_valid': is_valid,
                'quality_level': quality_level,
                'recommendation': recommendation,
                'issues': issues,
                'warnings': warnings,
                'suggestions': suggestions,
                'stats': stats
            }

        except Exception as e:
            logger.error(f"数据质量检查异常: {file_name} - {str(e)}")
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return {
                'filename': file_name,
                'timestamp': timestamp,
                'is_valid': False,
                'quality_level': 'error',
                'recommendation': 'discard',
                'issues': [f"质量检查失败: {str(e)}"],
                'warnings': [],
                'suggestions': ["检查数据格式是否正确"],
                'stats': {}
            }

    @staticmethod
    def check_cv_data(
        df: pd.DataFrame,
        file_name: str = "",
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Check CV (Cyclic Voltammetry) data quality.

        Args:
            df: DataFrame with voltage/current data
            file_name: Name of the file being checked

        Returns:
            Quality report dictionary
        """
        logger = core.get_logger()
        issues = []
        warnings = []
        suggestions = []
        quality_config = DataQualityChecker.normalize_cv_config(config)

        try:
            # CV specific checks
            min_points_warning = int(quality_config["min_points_warning"])
            if len(df) < min_points_warning:
                warnings.append(f"CV数据点较少 ({len(df)}点)，建议 ≥{min_points_warning}点")

            # Check for cycle completion (data should return near starting point)
            if len(df) > 10:
                start_pot = df.iloc[0]['Potential'] if 'Potential' in df.columns else df.iloc[0].iloc[0]
                end_pot = df.iloc[-1]['Potential'] if 'Potential' in df.columns else df.iloc[-1].iloc[0]
                tolerance = float(quality_config["cycle_completion_tolerance"])
                if abs(start_pot - end_pot) > tolerance:
                    warnings.append(f"CV循环不完整: 起始({start_pot:.3f}V) vs 终止({end_pot:.3f}V)")
                    suggestions.append("检查扫描参数确保完成完整循环")

            stats = {
                'file_name': file_name,
                'data_points': len(df),
                'quality_config': quality_config,
                'is_valid': len(issues) == 0
            }

            return {
                'is_valid': len(issues) == 0,
                'issues': issues,
                'warnings': warnings,
                'stats': stats,
                'suggestions': suggestions
            }

        except Exception as e:
            logger.error(f"CV数据质量检查异常: {file_name} - {str(e)}")
            return {
                'is_valid': False,
                'issues': [f"质量检查失败: {str(e)}"],
                'warnings': [],
                'stats': {},
                'suggestions': []
            }


    @staticmethod
    def generate_quality_report_text(report: Dict[str, Any]) -> str:
        """生成人类可读的详细质量检测报告（文本格式）

        Args:
            report: check_lsv_data() 返回的报告字典

        Returns:
            格式化的文本报告
        """
        lines = []
        lines.append("=" * 80)
        lines.append("  电化学数据质量检测报告")
        lines.append("  Electrochemical Data Quality Detection Report")
        lines.append("=" * 80)

        stats = report.get('stats', {})
        file_name = stats.get('file_name', 'unknown')
        is_valid = report.get('is_valid', False)

        # 文件基本信息
        lines.append(f"\n📄 文件名称: {file_name}")
        lines.append(f"📊 数据点数: {stats.get('data_points', 0)}")

        if 'potential_range' in stats:
            pot_range = stats['potential_range']
            lines.append(f"⚡ 电位范围: {pot_range[0]:.3f} ~ {pot_range[1]:.3f} V (跨度: {stats.get('potential_span', 0):.3f} V)")

        if 'current_range' in stats:
            cur_range = stats['current_range']
            lines.append(f"🔌 电流范围: {cur_range[0]:.3f} ~ {cur_range[1]:.3f} mA/cm²")

        # 整体质量评估
        lines.append(f"\n{'─' * 80}")
        if is_valid:
            lines.append("🟢 整体评估: 通过质量检查")
        else:
            lines.append("🔴 整体评估: 未通过质量检查")

        # 噪声分析（重点）
        noise_analysis = stats.get('noise_analysis', {})
        quality_config = DataQualityChecker.normalize_lsv_config(stats.get('quality_config'))
        if noise_analysis:
            lines.append(f"\n{'─' * 80}")
            lines.append("🔍 数据抖动分析（Noise Analysis）")
            lines.append(f"{'─' * 80}")

            # 综合质量评级
            quality = noise_analysis.get('overall_quality', 'unknown')
            recommendation = noise_analysis.get('recommendation', 'unknown')

            quality_labels = {
                'good': '✅ 优秀 (Good)',
                'acceptable': '✔️ 可接受 (Acceptable)',
                'fair': '⚠️ 一般 (Fair)',
                'poor': '❌ 差 (Poor)'
            }

            recommendation_labels = {
                'ready_to_use': '可直接使用',
                'smooth_before_use': '建议平滑后使用',
                'use_with_caution': '谨慎使用，需仔细检查',
                'discard': '建议丢弃并重新测量'
            }

            lines.append(f"\n  数据质量等级: {quality_labels.get(quality, quality)}")
            lines.append(f"  处理建议: {recommendation_labels.get(recommendation, recommendation)}")

            # 详细指标
            lines.append("\n  【指标1：二阶导数噪声水平】")
            if 'noise_level' in noise_analysis:
                noise_level = noise_analysis['noise_level']
                noise_severity = noise_analysis.get('noise_severity', 'unknown')
                lines.append(f"    噪声水平: {noise_level:.3f}")
                lines.append(f"    二阶导数标准差: {noise_analysis.get('second_derivative_std', 0):.6f}")

                if noise_severity == 'critical':
                    lines.append(f"    状态: ❌ 严重抖动 (noise_level > {quality_config['noise_critical']})")
                elif noise_severity == 'warning':
                    lines.append(f"    状态: ⚠️ 明显抖动 (noise_level > {quality_config['noise_warning']})")
                else:
                    lines.append(f"    状态: ✅ 平滑 (noise_level ≤ {quality_config['noise_warning']})")

            lines.append("\n  【指标2：突变点检测（MAD方法）】")
            if 'jump_count' in noise_analysis:
                jump_count = noise_analysis['jump_count']
                jump_ratio = noise_analysis['jump_ratio']
                jump_severity = noise_analysis.get('jump_severity', 'unknown')
                lines.append(f"    突变点数量: {jump_count}")
                lines.append(f"    突变点比例: {jump_ratio:.2%}")

                if jump_severity == 'critical':
                    lines.append(f"    状态: ❌ 频繁突变 (ratio > {quality_config['jump_ratio_critical']:.0%})")
                elif jump_severity == 'warning':
                    lines.append(f"    状态: ⚠️ 存在毛刺 (ratio > {quality_config['jump_ratio_warning']:.0%})")
                else:
                    lines.append(f"    状态: ✅ 稳定 (ratio ≤ {quality_config['jump_ratio_warning']:.0%})")

            lines.append("\n  【指标3：局部波动分析】")
            if 'max_local_variation' in noise_analysis:
                max_var = noise_analysis['max_local_variation']
                avg_var = noise_analysis['avg_local_variation']
                has_issue = noise_analysis.get('local_issue', False)
                lines.append(f"    最大局部波动: {max_var:.6f}")
                lines.append(f"    平均局部波动: {avg_var:.6f}")

                if has_issue:
                    issue_pos = noise_analysis.get('issue_position', [])
                    lines.append("    状态: ⚠️ 存在局部剧烈抖动")
                    if issue_pos:
                        lines.append(f"    问题位置: 数据点 {issue_pos[0]} ~ {issue_pos[1]}")
                else:
                    lines.append("    状态: ✅ 各区域波动均匀")

            plot_path = noise_analysis.get('plot_path')
            if plot_path:
                lines.append("")
                lines.append(f"  诊断图像: {plot_path}")

        # 致命问题
        if report.get('issues'):
            lines.append(f"\n{'─' * 80}")
            lines.append("❌ 致命问题（Critical Issues - 阻止处理）:")
            lines.append(f"{'─' * 80}")
            for i, issue in enumerate(report['issues'], 1):
                lines.append(f"  {i}. {issue}")

        # 警告
        if report.get('warnings'):
            lines.append(f"\n{'─' * 80}")
            lines.append("⚠️  质量警告（Warnings - 不阻止处理）:")
            lines.append(f"{'─' * 80}")
            for i, warning in enumerate(report['warnings'], 1):
                lines.append(f"  {i}. {warning}")

        # 改进建议
        if report.get('suggestions'):
            lines.append(f"\n{'─' * 80}")
            lines.append("💡 改进建议（Suggestions）:")
            lines.append(f"{'─' * 80}")
            for i, suggestion in enumerate(report['suggestions'], 1):
                lines.append(f"  {i}. {suggestion}")

        # 可能原因分析
        if not is_valid or (noise_analysis and noise_analysis.get('overall_quality') in ['fair', 'poor']):
            lines.append(f"\n{'─' * 80}")
            lines.append("🔬 数据抖动可能原因:")
            lines.append(f"{'─' * 80}")
            lines.append("  • 电极接触不良或松动")
            lines.append("  • 电解液中存在气泡或搅拌过度")
            lines.append("  • 电位扫描速度过快")
            lines.append("  • 仪器接地不良或受电磁干扰")
            lines.append("  • 参比电极老化或电位不稳定")
            lines.append("  • 环境温度波动")

            lines.append("\n🔧 改进措施:")
            lines.append(f"{'─' * 80}")
            lines.append("  • 检查并重新连接电极，确保接触良好")
            lines.append("  • 降低扫描速度（例如从 50 mV/s 降至 10 mV/s）")
            lines.append("  • 静置电解液，排除气泡")
            lines.append("  • 检查仪器接地和屏蔽")
            lines.append("  • 更换参比电极或重新标定")
            lines.append("  • 在恒温环境下测量")

        # 其他统计信息
        lines.append(f"\n{'─' * 80}")
        lines.append("📈 其他统计信息:")
        lines.append(f"{'─' * 80}")
        lines.append(f"  电流均值: {stats.get('current_mean', 0):.3f} mA/cm²")
        lines.append(f"  电流标准差: {stats.get('current_std', 0):.3f}")
        lines.append(f"  电位单调性: {'是' if stats.get('is_monotonic', False) else '否'}")
        lines.append(f"  异常值数量: {stats.get('outlier_count', 0)}")
        lines.append(f"  缺失值数量: {stats.get('missing_values', 0)}")

        lines.append(f"\n{'=' * 80}")
        lines.append(f"报告生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"{'=' * 80}\n")

        return '\n'.join(lines)

