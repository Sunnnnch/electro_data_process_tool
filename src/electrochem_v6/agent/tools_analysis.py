"""
Analysis tools for AI agent - Quality reports and intelligent summaries.
智能分析工具 - 质量报告读取和智能总结。
"""

import glob
import json
import os
from datetime import datetime
from typing import Dict


def tool_read_quality_report(report_type: str = "latest") -> Dict:
    """读取质量检测报告"""
    try:
        # 查找所有质量报告文件
        reports = glob.glob("**/quality_report.json", recursive=True)

        if not reports:
            return {
                "success": False,
                "message": "未找到质量报告。可能原因:尚未处理数据或数据质量检测未启用"
            }

        # 获取最新的报告
        latest_report = max(reports, key=os.path.getmtime)

        with open(latest_report, 'r', encoding='utf-8') as f:
            report_data = json.load(f)

        # 提取关键信息
        quality_summary = report_data.get('quality_summary', {})
        files = report_data.get('files', [])

        # 分类文件
        passed_files = [f for f in files if f.get('is_valid', True) and not f.get('warnings')]
        warning_files = [f for f in files if f.get('is_valid', True) and f.get('warnings')]
        failed_files = [f for f in files if not f.get('is_valid', False)]

        return {
            "success": True,
            "report_path": latest_report,
            "timestamp": datetime.fromtimestamp(os.path.getmtime(latest_report)).strftime("%Y-%m-%d %H:%M:%S"),
            "summary": {
                "total_files": quality_summary.get('total_files', len(files)),
                "passed": quality_summary.get('passed', len(passed_files)),
                "warnings": quality_summary.get('warnings', len(warning_files)),
                "failed": quality_summary.get('failed', len(failed_files))
            },
            "passed_files": [f.get('filename') for f in passed_files[:10]],
            "warning_files": [
                {
                    "file": f.get('filename'),
                    "warnings": f.get('warnings', [])[:3]  # 只返回前3个警告
                } for f in warning_files[:5]
            ],
            "failed_files": [
                {
                    "file": f.get('filename'),
                    "issues": f.get('issues', [])[:3]
                } for f in failed_files[:5]
            ]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_analyze_processing_results(include_quality: bool = True, include_performance: bool = True) -> Dict:
    """综合分析处理结果"""
    try:
        analysis = {"success": True, "components": {}}

        # 1. 质量分析
        if include_quality:
            quality = tool_read_quality_report()
            analysis['components']['quality'] = quality

        # 2. 性能分析
        if include_performance:
            from electrochem_v6.agent.tool_executor import tool_query_lsv_summary
            lsv_data = tool_query_lsv_summary(top_n=10)

            if lsv_data.get('success') and lsv_data.get('samples'):
                samples = lsv_data['samples']

                # 计算统计信息
                eta_values = [s.get('overpotential_10') for s in samples if s.get('overpotential_10') is not None]

                if eta_values:
                    import statistics
                    performance_stats = {
                        "best_eta": min(eta_values),
                        "avg_eta": statistics.mean(eta_values),
                        "std_eta": statistics.stdev(eta_values) if len(eta_values) > 1 else 0,
                        "excellent_count": len([v for v in eta_values if v < 0.30]),
                        "good_count": len([v for v in eta_values if 0.30 <= v < 0.40]),
                    }

                    analysis['components']['performance'] = {
                        "success": True,
                        "total_samples": len(samples),
                        "top_3": samples[:3],
                        "statistics": performance_stats
                    }

        # 3. 生成综合建议
        suggestions = []

        # 质量建议
        if include_quality and analysis['components'].get('quality', {}).get('success'):
            q = analysis['components']['quality']['summary']
            if q['failed'] > 0:
                suggestions.append(f"有{q['failed']}个文件处理失败,建议检查数据格式")
            if q['warnings'] > 0:
                suggestions.append(f"有{q['warnings']}个文件有警告,建议查看详细报告")

        # 性能建议
        if include_performance and analysis['components'].get('performance', {}).get('success'):
            p = analysis['components']['performance']['statistics']
            if p['excellent_count'] > 0:
                suggestions.append(f"发现{p['excellent_count']}个性能优秀的样品(η@10<0.30V),建议重点关注")
            if p['std_eta'] > 0.1:
                suggestions.append(f"性能分散度较大(σ={p['std_eta']:.3f}V),建议分析制备条件差异")

        analysis['suggestions'] = suggestions

        return analysis

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


__all__ = ["tool_read_quality_report", "tool_analyze_processing_results"]

