"""Docstring"""
# Fixed problematic line
# Fixed problematic line
"""Docstring"""

import json
import logging
import os
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional
from .tools_analysis import tool_read_quality_report, tool_analyze_processing_results
from .tools_catalyst import tool_get_catalyst_info
from electrochem_v6.llm.config import LLMConfig
from electrochem_v6.llm.vision_client import VisionClient

_logger = logging.getLogger(__name__)


def execute_tool(tool_name: str, arguments: str | Dict[str, Any]) -> Dict:
    """
    Execute tool function
    
    Args:
        tool_name: Tool name
        arguments: Arguments (JSON string or dict)
    
    Returns:
        Result dict
    """
    # 解析参数
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            return {"success": False, "error": "参数解析失败"}
    else:
        args = arguments
    
    # 路由到具体函?
    tool_map = {
        # 基础工具
        "query_lsv_summary": tool_query_lsv_summary,
        "find_best_catalysts": tool_find_best_catalysts,
        "compare_catalysts": tool_compare_catalysts,
        "get_current_project_summary": tool_get_current_project_summary,
        "get_current_project_history": tool_get_current_project_history,
        "get_current_compare_selection": tool_get_current_compare_selection,
        
        # 增强工具(让AI能自主分析)
        "scan_data_folder": tool_scan_data_folder,
        "preview_data_file": tool_preview_data_file,
        "analyze_data_characteristics": tool_analyze_data_characteristics,
        "auto_process_with_smart_params": tool_auto_process_with_smart_params,
        
        # 管理工具
        "create_project": tool_create_project,
        "get_processing_history": tool_get_processing_history,
        
        # 智能分析工具
        "read_quality_report": tool_read_quality_report,
        "analyze_processing_results": tool_analyze_processing_results,
        
        # 催化剂中心工?
        "get_catalyst_info": tool_get_catalyst_info,

        # 视觉诊断
        "analyze_waveform_image": tool_analyze_waveform_image,
    }
    
    if tool_name in tool_map:
        try:
            return tool_map[tool_name](**args)
        except Exception as e:
            return {"success": False, "error": f"工具执行失败: {str(e)}"}
    else:
        return {"success": False, "error": f"未知工具: {tool_name}"}


# ============== 基础工具实现 ==============

def tool_query_lsv_summary(project_id: str = None, sort_by: str = "eta", top_n: int = None) -> Dict:
    """Docstring"""
    try:
        from electrochem_v6.store.legacy_runtime import get_history_manager_v6

        hist_mgr = get_history_manager_v6()
        
        # ?关键修复:识?all"字符串并转换为None
        if project_id and project_id.lower() in ['all', 'none', '']:
            project_id = None
        
        # 查询数据
        if project_id:
            summary = hist_mgr.get_lsv_summary(project_id=project_id)
        else:
            # 查询所有项?
            summary = hist_mgr.get_lsv_summary()
        
        samples = summary.get('samples', [])
        
        # 调试信息
        _logger.debug("tool_query_lsv_summary: project_id=%s, 原始samples数量 = %d", project_id, len(samples))
        
        # 排序
        if sort_by == "tafel":
            samples = sorted(samples, key=lambda x: x.get('tafel_slope', 999))
        else:
            samples = sorted(samples, key=lambda x: x.get('overpotential_10', 999))
        
        # 限制数量
        if top_n:
            samples = samples[:top_n]
        
        return {
            "success": True,
            "total_samples": len(summary.get('samples', [])),
            "returned_samples": len(samples),
            "samples": samples
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_find_best_catalysts(project_id: str = None, count: int = 5) -> Dict:
    """找出最优催化剂(修复:project_id可选)"""
    # ?修复:project_id设为可选,None时查询所有项?
    result = tool_query_lsv_summary(project_id=project_id, sort_by="eta", top_n=count)
    
    # 调试信息
    _logger.debug("tool_find_best_catalysts: result=%s", result)
    
    if result.get('success'):
        samples = result.get('samples', [])
        
        # ?修复:检查samples而不是returned_samples
        if len(samples) == 0:
            return {
                "success": False,
                "message": "数据库中没有找到LSV记录。可能原因:1) 尚未处理任何LSV数据 2) 数据未正确保存到历史记录",
                "suggestion": "Please check data processing tab for LSV data"
            }
        
        return {
            "success": True,
            "count": len(samples),
            "total_in_database": result.get('total_samples', len(samples)),
            "best_catalysts": samples
        }
    else:
        return result


def tool_compare_catalysts(sample_names: List[str]) -> Dict:
    """对比催化剂性能"""
    try:
        from electrochem_v6.store.legacy_runtime import get_history_manager_v6

        hist_mgr = get_history_manager_v6()
        all_records = hist_mgr.get_all_records()
        
        # 查找指定样品
        comparison = []
        for name in sample_names:
            for record in all_records:
                if record.get('sample_name') == name and record.get('type') == 'LSV':
                    results = record.get('results', {})
                    comparison.append({
                        "sample_name": name,
                        "overpotential_10": results.get('overpotential_10'),
                        "tafel_slope": results.get('tafel_slope'),
                        "project": record.get('project_name', 'Unknown')
                    })
                    break
        
        if comparison:
            # 找出最?
            best_eta_sample = min(comparison, key=lambda x: x.get('overpotential_10', 999))
            
            return {
                "success": True,
                "comparison": comparison,
                "best_catalyst": best_eta_sample['sample_name'],
                "best_overpotential": best_eta_sample['overpotential_10']
            }
        else:
            return {"success": False, "error": "未找到指定样品的数据"}
            
    except Exception as e:
        return {"success": False, "error": str(e)}


def _resolve_v6_project(project_id: str = None, project_name: str = None) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    from electrochem_v6.store.projects import list_projects

    projects = list_projects(status="active").get("projects") or []
    clean_id = str(project_id or "").strip()
    clean_name = str(project_name or "").strip()

    if clean_id:
        found = next((item for item in projects if str(item.get("id") or "").strip() == clean_id), None)
        return found, None if found else f"未找到项目ID: {clean_id}"

    if clean_name:
        found = next((item for item in projects if str(item.get("name") or "").strip() == clean_name), None)
        if found:
            return found, None
        lowered = clean_name.casefold()
        found = next((item for item in projects if str(item.get("name") or "").strip().casefold() == lowered), None)
        return found, None if found else f"未找到项目名称: {clean_name}"

    return None, "请提供 project_id 或 project_name"


def _simplify_v6_history_record(record: Dict[str, Any]) -> Dict[str, Any]:
    results = record.get("results") if isinstance(record.get("results"), dict) else {}
    output_files = record.get("output_files") if isinstance(record.get("output_files"), list) else []
    return {
        "timestamp": record.get("timestamp"),
        "type": record.get("type"),
        "sample_name": record.get("sample_name"),
        "status": record.get("status"),
        "file_name": record.get("file_name"),
        "project_name": record.get("project_name"),
        "summary_path": record.get("summary_path"),
        "output_file_count": len([item for item in output_files if str(item or "").strip()]),
        "results": {
            "overpotential_10": results.get("overpotential_10"),
            "potential_10": results.get("potential_10"),
            "potential_at_10.0": results.get("potential_at_10.0"),
            "tafel_slope": results.get("tafel_slope"),
        },
    }


def _simplify_v6_compare_row(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sample_name": item.get("sample_name"),
        "overpotential_10": item.get("overpotential_10"),
        "potential_10": item.get("potential_10"),
        "tafel_slope": item.get("tafel_slope"),
        "record_count": item.get("record_count"),
        "latest_time": item.get("latest_time"),
    }


def tool_get_current_project_summary(project_id: str = None, project_name: str = None) -> Dict:
    try:
        from electrochem_v6.store.history import get_stats, list_history
        from electrochem_v6.store.projects import get_lsv_summary

        project, err = _resolve_v6_project(project_id=project_id, project_name=project_name)
        if not project:
            return {"success": False, "error": err or "项目不存在"}

        pid = str(project.get("id") or "")
        stats = (get_stats(project_id=pid, include_archived=False).get("data") or {})
        history = (list_history(project_id=pid, limit=5, include_archived=False).get("records") or [])
        lsv = (get_lsv_summary(project_id=pid, page=1, page_size=5, sort_by="eta").get("lsv_summary") or {})
        return {
            "success": True,
            "project": {
                "id": project.get("id"),
                "name": project.get("name"),
                "description": project.get("description"),
                "updated_at": project.get("updated_at"),
            },
            "stats": stats,
            "recent_history": [_simplify_v6_history_record(item) for item in history[:5]],
            "top_lsv_samples": [_simplify_v6_compare_row(item) for item in (lsv.get("samples") or [])[:5]],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_get_current_project_history(
    project_id: str = None,
    project_name: str = None,
    record_type: str = None,
    limit: int = 10,
) -> Dict:
    try:
        from electrochem_v6.store.history import list_history

        project, err = _resolve_v6_project(project_id=project_id, project_name=project_name)
        if not project:
            return {"success": False, "error": err or "项目不存在"}

        pid = str(project.get("id") or "")
        safe_limit = max(1, min(int(limit or 10), 50))
        records = list_history(project_id=pid, limit=max(safe_limit * 3, 20), include_archived=False).get("records") or []
        clean_type = str(record_type or "").strip().upper()
        if clean_type:
            records = [item for item in records if str(item.get("type") or "").upper() == clean_type]
        records = records[:safe_limit]
        return {
            "success": True,
            "project": {"id": project.get("id"), "name": project.get("name")},
            "record_type": clean_type or None,
            "returned_count": len(records),
            "records": [_simplify_v6_history_record(item) for item in records],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_get_current_compare_selection(
    project_id: str = None,
    project_name: str = None,
    sample_names: Optional[List[str]] = None,
    limit: int = 5,
) -> Dict:
    try:
        from electrochem_v6.core import get_latest_project_lsv_compare_plot
        from electrochem_v6.store.projects import get_lsv_summary

        project, err = _resolve_v6_project(project_id=project_id, project_name=project_name)
        if not project:
            return {"success": False, "error": err or "项目不存在"}

        pid = str(project.get("id") or "")
        safe_limit = max(1, min(int(limit or 5), 20))
        summary = get_lsv_summary(project_id=pid, page=1, page_size=100, sort_by="eta").get("lsv_summary") or {}
        samples = summary.get("samples") or []
        requested = [str(item).strip() for item in (sample_names or []) if str(item).strip()]
        if requested:
            requested_set = set(requested)
            rows = [item for item in samples if str(item.get("sample_name") or "").strip() in requested_set]
            selection_mode = "explicit_samples"
        else:
            rows = samples[:safe_limit]
            selection_mode = "project_top_samples"

        latest_overlay = get_latest_project_lsv_compare_plot(project_id=pid, chart_type="overlay")
        latest_overlay_plot = latest_overlay.get("plot") if latest_overlay.get("status") == "success" else None
        latest_overlay_meta = None
        if isinstance(latest_overlay_plot, dict):
            latest_overlay_meta = {
                "file_name": latest_overlay_plot.get("file_name"),
                "plot_path": latest_overlay_plot.get("plot_path"),
                "generated_at": latest_overlay_plot.get("generated_at"),
                "selected_samples": latest_overlay_plot.get("selected_samples"),
            }

        return {
            "success": True,
            "project": {"id": project.get("id"), "name": project.get("name")},
            "selection_mode": selection_mode,
            "note": "当前 UI 选中的样品不会持久化到后端；未提供 sample_names 时返回项目内可对比的顶部样品。",
            "compare_rows": [_simplify_v6_compare_row(item) for item in rows[:safe_limit]],
            "latest_overlay_plot": latest_overlay_meta,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============== 增强工具实现(让AI??数据?=============

def tool_scan_data_folder(folder_path: str) -> Dict:
    """Docstring"""
    try:
        # Path traversal protection: resolve and validate
        resolved = os.path.realpath(folder_path)
        if not os.path.isdir(resolved):
            return {"success": False, "error": f"文件夹不存在: {folder_path}"}
        folder_path = resolved
        if not os.path.exists(folder_path):
            return {"success": False, "error": f"文件夹不存在: {folder_path}"}
        
        files_info = []
        
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if file.endswith(('.txt', '.csv')):
                    file_path = os.path.join(root, file)
                    
                    # 检测文件类?
                    file_upper = file.upper()
                    if "LSV" in file_upper or "TAFEL" in file_upper:
                        detected_type = "LSV"
                    elif "CV" in file_upper:
                        detected_type = "CV"
                    elif "EIS" in file_upper:
                        detected_type = "EIS"
                    elif "ECSA" in file_upper:
                        detected_type = "ECSA"
                    else:
                        detected_type = "Unknown"
                    
                    files_info.append({
                        "file_name": file,
                        "file_path": file_path,
                        "detected_type": detected_type,
                        "folder": os.path.basename(root),
                        "size_kb": round(os.path.getsize(file_path) / 1024, 2)
                    })
        
        # 统计
        by_type = {}
        for f in files_info:
            ftype = f['detected_type']
            by_type[ftype] = by_type.get(ftype, 0) + 1
        
        return {
            "success": True,
            "folder_path": folder_path,
            "total_files": len(files_info),
            "files": files_info[:30],  # 返回?0个避免太?
            "statistics": {
                "total": len(files_info),
                "by_type": by_type,
                "folders": len(set(f['folder'] for f in files_info))
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_preview_data_file(file_path: str, lines: int = 20) -> Dict:
    """预览数据文件"""
    try:
        # Path traversal protection: only allow data file extensions
        resolved = os.path.realpath(file_path)
        ext = os.path.splitext(resolved)[1].lower()
        if ext not in ('.txt', '.csv', '.xlsx', '.xls', '.json'):
            return {"success": False, "error": f"不支持的文件类型: {ext}"}
        file_path = resolved
        if not os.path.exists(file_path):
            return {"success": False, "error": f"文件不存在: {file_path}"}
        
        # 尝试多种编码
        encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1']
        preview_lines = None
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    preview_lines = [f.readline().strip() for _ in range(lines)]
                break
            except Exception:
                continue
        
        if preview_lines is None:
            return {"success": False, "error": "无法读取文件(编码问题)"}
        
        # 分析内容
        content_str = '\n'.join(preview_lines)
        has_potential = 'potential' in content_str.lower()
        has_current = 'current' in content_str.lower()
        has_freq = 'freq' in content_str.lower()
        
        # 推断类型
        if has_freq:
            detected_type = "EIS"
        elif has_potential and has_current:
            detected_type = "LSV/CV"
        else:
            detected_type = "Unknown"
        
        return {
            "success": True,
            "file_path": file_path,
            "preview_lines": preview_lines,
            "detected_type": detected_type,
            "has_header": has_potential or has_current,
            "line_count_preview": len(preview_lines)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_analyze_data_characteristics(file_path: str, data_type: str) -> Dict:
    """分析数据特征(用于智能决定参数)"""
    try:
        # 自动检测数据起始行
        from electrochem_v6.core.processing_compat import auto_detect_data_start
        
        start_line = auto_detect_data_start(file_path)
        
        # ?修复:更健壮的数据读取,处理各种格式
        try:
            # 尝试1:智能分隔符
            df = pd.read_csv(file_path, sep=r'\s+|,', skiprows=start_line-1, engine='python', nrows=1000, on_bad_lines='skip')
        except Exception:
            try:
                # 尝试2:仅空格
                df = pd.read_csv(file_path, delim_whitespace=True, skiprows=start_line-1, nrows=1000, on_bad_lines='skip')
            except Exception:
                # 尝试3:仅逗号
                df = pd.read_csv(file_path, sep=',', skiprows=start_line-1, nrows=1000, on_bad_lines='skip')
        
        characteristics = {
            "data_start_line": start_line,
            "data_points": len(df)
        }
        
        if data_type == "LSV":
            # 查找电流?
            current_col = next((col for col in df.columns if 'current' in col.lower()), None)
            if current_col:
                currents_mA = df[current_col].abs() * 1000  # 转为mA
                
                characteristics.update({
                    "current_range_mA": {
                        "min": float(currents_mA.min()),
                        "max": float(currents_mA.max())
                    },
                    "suggested_tafel_range": "1-10"  # 默认
                })
                
                # 智能推荐Tafel范围
                max_current = currents_mA.max()
                if max_current > 50:
                    characteristics["suggested_tafel_range"] = "5-50"
                    characteristics["reasoning"] = "电流较大,推荐使?-50 mA/cm²范围"
                elif max_current < 5:
                    characteristics["suggested_tafel_range"] = "0.5-5"
                    characteristics["reasoning"] = "电流较小,推荐使?.5-5 mA/cm²范围"
                else:
                    characteristics["reasoning"] = "电流范围正常,使用标?-10 mA/cm²范围"
        
        return {
            "success": True,
            "file_path": file_path,
            "data_type": data_type,
            "characteristics": characteristics
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_auto_process_with_smart_params(
    folder_path: str,
    data_type: str,
    project_name: str = None,
    potential_offset: float = None,
    electrode_area: float = None,
    target_current: str = None,
    tafel_range: str = None,
    extra_gui_params: Optional[Dict[str, Any]] = None,
) -> Dict:
    """AI自主处理数据(核心功能)"""
    try:
        # Step 1: 扫描文件?
        scan_result = tool_scan_data_folder(folder_path)
        if not scan_result['success']:
            return scan_result
        
        if scan_result['total_files'] == 0:
            return {"success": False, "error": "文件夹中没有找到数据文件"}
        
        # Step 2: 使用用户指定或默认参?
        print("Using default parameters for data processing")
        
        # ?支持用户自定义参?
        if potential_offset is not None:
            print("Processing...")
        if electrode_area is not None:
            print(f"📏 用户指定电极面积: {electrode_area} cm²")
        if target_current is not None:
            print(f"User-specified target current: {target_current} mA/cm^2")
        if tafel_range is not None:
            print("Processing...")
        
        # Step 3: 构建处理参数
        gui_vars = {
            'area': electrode_area if electrode_area is not None else 1.0,
            'potential_offset': potential_offset if potential_offset is not None else 0.0,  # ?支持电位偏移
            'auto_detect_start': True
        }
        
        if data_type == "LSV":
            final_target_current = target_current if target_current else '10,100'
            enable_tafel = tafel_range is not None
            final_tafel_range = tafel_range if tafel_range else '1-10'
            gui_vars.update({
                'lsv_enabled': True,
                'lsv_target_current': final_target_current,
                'tafel_enabled': enable_tafel,
                'tafel_range': final_tafel_range
            })
            if not enable_tafel:
                print("Processing LSV data only (Tafel analysis not enabled)")
        elif data_type == "CV":
            gui_vars.update({
                'cv_enabled': True,
                'cv_match': 'prefix',
                'cv_prefix': 'CV',
                'cv_peaks_enabled': True,
                'cv_peaks_smooth': 5,
                'cv_peaks_min_height': 1.0,
                'cv_peaks_min_dist': 5,
                'cv_peaks_max': 3,
            })
            print("Processing CV data with peak detection enabled")
        elif data_type == "EIS":
            gui_vars.update({
                'eis_enabled': True,
                'eis_match': 'prefix',
                'eis_prefix': 'EIS',
                'plot_nyquist': True,
                'plot_bode': False,
                'eis_xlabel': "Z' (Ohm)",
                'eis_ylabel': "-Z'' (Ohm)",
            })
            print("Processing EIS data (Nyquist plot enabled)")
        elif data_type == "ECSA":
            gui_vars.update({
                'ecsa_enabled': True,
                'ecsa_match': 'prefix',
                'ecsa_prefix': 'ECSA',
                'ecsa_ev': 0.10,
                'ecsa_last_n': 1,
                'ecsa_avg_last_n': False,
                'ecsa_cs_value': 40.0,
                'ecsa_cs_unit': 'uF/cm^2',
                'ecsa_use_abs_delta': True,
            })
            print("Processing ECSA dataset for double-layer analysis")
        else:
            return {"success": False, "error": f"Unsupported data_type: {data_type}"}

        if extra_gui_params:
            gui_vars.update(extra_gui_params)
        # Step 4: 创建或使用项?
        if project_name:
            from electrochem_v6.store.legacy_runtime import get_project_manager_v6
            proj_mgr = get_project_manager_v6()
            
            # 检查项目是否已存在
            existing = proj_mgr.get_all_projects()
            project_id = None
            for proj in existing:
                if proj['name'] == project_name:
                    project_id = proj['id']
                    break
            
            # 不存在则创建
            if not project_id:
                project_id = proj_mgr.create_project(
                    name=project_name,
                    description=f"AI自动创建:{data_type}数据分析"
                )
            
            gui_vars['project_id'] = project_id
        
        # Step 5: 执行处理
        from electrochem_v6.core.processing_compat import run_pipeline
        
        result = run_pipeline(folder_path, gui_vars)
        
        # ?修复:正确统计处理文件数
        # 从scan_result的statistics中获取完整统计(不是files列表,那只有?0个)
        messages = result.get('messages', [])
        
        # 使用完整的统计信?
        by_type_stats = scan_result.get('statistics', {}).get('by_type', {})
        actual_processed = by_type_stats.get(data_type, 0)  # ?从统计中获取真实数量
        
        # Step 7: 汇总结果(包含质量分析?
        quality_summary = result.get('quality_summary', {})
        vision_findings = []
        if isinstance(quality_summary, dict):
            for report in (quality_summary.get('files', []) or []):
                stats = (report or {}).get('stats') or {}
                noise = stats.get('noise_analysis') or {}
                vision = noise.get('vision_analysis')
                if isinstance(vision, dict):
                    vision_findings.append({
                        "file": report.get('filename') or report.get('file') or "unknown",
                        "success": bool(vision.get('success')),
                        "result": vision.get('result') or vision.get('error'),
                        "model": vision.get('model'),
                        "image_path": vision.get('image_path'),
                    })
        base_suggestion = "建议:处理完成后,可以问\"分析质量报告\"获取详细分析,或\"找出最优催化剂\"查看性能排名"
        if vision_findings:
            highlight = []
            for finding in vision_findings[:3]:
                icon = "✅" if finding["success"] else "⚠️"
                highlight.append(f"{icon} {finding['file']}: {finding.get('result','无视觉结论')}")
            if len(vision_findings) > 3:
                highlight.append(f"... 还有 {len(vision_findings) - 3} 个文件完成视觉诊断")
            vision_block = "\n".join(highlight)
            ai_suggestion = f"{base_suggestion}\n\n📷 视觉诊断:\n{vision_block}"
        else:
            ai_suggestion = base_suggestion

        return {
            "success": True,
            "message": "AI??????",
            "summary": f"????{actual_processed}?{data_type}??",
            "processing": {
                "scanned_total": scan_result['total_files'],
                "processed_count": actual_processed,
                "data_type": data_type,
                "output_files": messages  # LSV_results.csv, quality_report.json?
            },
            "parameters": {
                "potential_offset": potential_offset if potential_offset else 0.0,
                "electrode_area": electrode_area if electrode_area else 1.0,
                "target_current": target_current if target_current else "10,100",
                "tafel_enabled": gui_vars.get('tafel_enabled', False)
            },
            "project_id": gui_vars.get('project_id'),
            "ai_suggestion": ai_suggestion,
            "vision_findings": vision_findings,
            "quality_summary": quality_summary,
        }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def tool_create_project(name: str, description: str = "") -> Dict:
    """创建项目"""
    try:
        from electrochem_v6.store.legacy_runtime import get_project_manager_v6

        proj_mgr = get_project_manager_v6()
        project_id = proj_mgr.create_project(name=name, description=description)
        
        return {
            "success": True,
            "project_id": project_id,
            "message": f"项目'{name}'创建成功"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_get_processing_history(project_id: str = None, record_type: str = None, limit: int = 20) -> Dict:
    """获取处理历史"""
    try:
        from electrochem_v6.store.legacy_runtime import get_history_manager_v6

        hist_mgr = get_history_manager_v6()
        
        if project_id:
            records = hist_mgr.get_records_by_project(project_id)
        else:
            records = hist_mgr.get_all_records()
        
        if record_type:
            records = [r for r in records if r.get('type', '').upper() == record_type.upper()]
        
        # 最新的在前
        records = sorted(records, key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return {
            "success": True,
            "total_records": len(records),
            "records": records[:limit]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============== 视觉分析工具 ==============

_vision_client_cache: VisionClient | None = None


def _get_vision_client() -> VisionClient | None:
    global _vision_client_cache
    if _vision_client_cache:
        return _vision_client_cache
    cfg = LLMConfig()
    if not cfg.is_vision_enabled():
        return None
    vision_cfg = cfg.get_vision_config()
    api_key = cfg.get_vision_api_key()
    if not api_key:
        return None
    client = VisionClient(
        api_key=api_key,
        model=vision_cfg.get("model", "gpt-4o-mini"),
        base_url=vision_cfg.get("base_url", "https://api.openai.com/v1"),
        timeout=int(vision_cfg.get("timeout", 60)),
    )
    _vision_client_cache = client
    return client


def tool_analyze_waveform_image(image_path: str, context: str = "", max_tokens: int | None = None) -> Dict:
    client = _get_vision_client()
    if client is None:
        return {"success": False, "error": "视觉模型未启用或未配置"}
    prompt = context or "请检查这条波形是否存在异常波动，并说明原因。"
    cfg = LLMConfig().get_vision_config()
    max_tokens = max_tokens or int(cfg.get("max_tokens", 800))
    return client.analyze_image(image_path=image_path, prompt=prompt, max_tokens=max_tokens)


# ============== 辅助函数 ==============

def _detect_type_from_content(content: str) -> str:
    """Function docstring"""
    content_lower = content.lower()
    if 'freq' in content_lower:
        return "EIS"
    elif 'potential' in content_lower and 'current' in content_lower:
        return "LSV/CV"
    else:
        return "Unknown"


__all__ = ["execute_tool"]
