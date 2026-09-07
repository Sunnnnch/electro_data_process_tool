"""Project & history query tools, and AI auto-processing tool.

These tools let the AI query project summaries, history records,
comparison selections, and run automated data processing.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_v6_project(
    project_id: Optional[str] = None, project_name: Optional[str] = None
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    from electrochem_v6.store.projects import list_projects

    # Archived projects retain their history and remain valid read-only analysis targets.
    projects = list_projects(status="all").get("projects") or []
    clean_id = str(project_id or "").strip()
    clean_name = str(project_name or "").strip()

    if clean_id:
        found = next(
            (item for item in projects if str(item.get("id") or "").strip() == clean_id),
            None,
        )
        return found, None if found else f"未找到项目ID: {clean_id}"

    if clean_name:
        found = next(
            (item for item in projects if str(item.get("name") or "").strip() == clean_name),
            None,
        )
        if found:
            return found, None
        lowered = clean_name.casefold()
        found = next(
            (item for item in projects if str(item.get("name") or "").strip().casefold() == lowered),
            None,
        )
        return found, None if found else f"未找到项目名称: {clean_name}"

    return None, "请提供 project_id 或 project_name"


def _simplify_v6_history_record(record: Dict[str, Any]) -> Dict[str, Any]:
    _raw_results = record.get("results")
    results = _raw_results if isinstance(_raw_results, dict) else {}
    _raw_output = record.get("output_files")
    output_files = _raw_output if isinstance(_raw_output, list) else []
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


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def tool_get_current_project_summary(
    project_id: Optional[str] = None, project_name: Optional[str] = None
) -> Dict:
    try:
        from electrochem_v6.store.history import get_stats, list_history
        from electrochem_v6.store.projects import get_lsv_summary

        project, err = _resolve_v6_project(project_id=project_id, project_name=project_name)
        if not project:
            return {"success": False, "error": err or "项目不存在"}

        pid = str(project.get("id") or "")
        stats = get_stats(project_id=pid, include_archived=False).get("data") or {}
        history = list_history(project_id=pid, limit=5, include_archived=False).get("records") or []
        lsv = get_lsv_summary(project_id=pid, page=1, page_size=5, sort_by="eta").get("lsv_summary") or {}
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
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
    record_type: Optional[str] = None,
    limit: int = 10,
) -> Dict:
    try:
        from electrochem_v6.store.history import list_history

        project, err = _resolve_v6_project(project_id=project_id, project_name=project_name)
        if not project:
            return {"success": False, "error": err or "项目不存在"}

        pid = str(project.get("id") or "")
        safe_limit = max(1, min(int(limit or 10), 50))
        records = (
            list_history(project_id=pid, limit=max(safe_limit * 3, 20), include_archived=False).get("records") or []
        )
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
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
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


def tool_create_project(name: str, description: str = "") -> Dict:
    """创建项目。"""
    try:
        from electrochem_v6.store.runtime import get_project_store

        proj_mgr = get_project_store()
        project_id = proj_mgr.create_project(name=name, description=description)

        return {"success": True, "project_id": project_id, "message": f"项目'{name}'创建成功"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_get_processing_history(
    project_id: Optional[str] = None, record_type: Optional[str] = None, limit: int = 20
) -> Dict:
    """获取处理历史。"""
    try:
        from electrochem_v6.store.runtime import get_history_store

        hist_mgr = get_history_store()

        all_records = hist_mgr.get_all_records()
        if project_id:
            records = [r for r in all_records if r.get("project_id") == project_id]
        else:
            records = all_records

        if record_type:
            records = [r for r in records if r.get("type", "").upper() == record_type.upper()]

        records = sorted(records, key=lambda x: x.get("timestamp", ""), reverse=True)

        return {"success": True, "total_records": len(records), "records": records[:limit]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_auto_process_with_smart_params(
    folder_path: str,
    data_type: str,
    project_name: Optional[str] = None,
    potential_offset: Optional[float] = None,
    electrode_area: Optional[float] = None,
    target_current: Optional[str] = None,
    tafel_range: Optional[str] = None,
    coupled_products_file: Optional[str] = None,
    coupled_products_sheet: Optional[str] = None,
    coupled_results_csv_filename: Optional[str] = None,
    extra_gui_params: Optional[Dict[str, Any]] = None,
) -> Dict:
    """AI自主处理数据(核心功能)。"""
    try:
        from .tools_data import tool_scan_data_folder

        data_type = str(data_type or "").strip().upper()
        if data_type in {"FE", "FARADAIC", "FARADAIC_EFFICIENCY", "SELECTIVITY"}:
            data_type = "COUPLED"
        if data_type not in {"LSV", "CV", "EIS", "ECSA", "COUPLED"}:
            return {"success": False, "error": f"Unsupported data_type: {data_type}"}

        from electrochem_v6.core.agent_scientific import scientific_parameter_requirements

        explicit_params: Dict[str, Any] = dict(extra_gui_params or {})
        if electrode_area is not None:
            explicit_params.setdefault("area", electrode_area)
        if potential_offset is not None:
            explicit_params.setdefault("potential_offset", potential_offset)
            explicit_params.setdefault("potential_mode", "manual")
        if coupled_products_file:
            explicit_params.setdefault("coupled_products_file", coupled_products_file)
        missing = scientific_parameter_requirements(data_type, explicit_params)
        if missing:
            return {"success": False, "status": "needs_parameters", "missing_parameters": missing,
                    "error": "必要科学参数未明确，请核对实验记录或当前界面参数后再处理。"}

        scan_result = tool_scan_data_folder(folder_path)
        if not scan_result["success"]:
            return scan_result

        if scan_result["total_files"] == 0 and data_type != "COUPLED":
            return {"success": False, "error": "文件夹中没有找到数据文件"}

        gui_vars: Dict[str, Any] = dict(explicit_params)

        if data_type == "LSV":
            final_target_current = target_current if target_current else "10,100"
            enable_tafel = tafel_range is not None
            final_tafel_range = tafel_range if tafel_range else "1-10"
            gui_vars.update(
                {
                    "lsv_target_current": final_target_current,
                    "tafel_enabled": enable_tafel,
                    "tafel_range": final_tafel_range,
                }
            )
        elif data_type == "CV":
            gui_vars.update(
                {
                    "cv_match": "prefix",
                    "cv_prefix": "CV",
                    "cv_peaks_enabled": True,
                    "cv_peaks_smooth": 5,
                    "cv_peaks_min_height": 1.0,
                    "cv_peaks_min_dist": 5,
                    "cv_peaks_max": 3,
                }
            )
        elif data_type == "EIS":
            gui_vars.update(
                {
                    "eis_match": "prefix",
                    "eis_prefix": "EIS",
                    "plot_nyquist": True,
                    "plot_bode": False,
                    "eis_xlabel": "Z' (Ohm)",
                    "eis_ylabel": "-Z'' (Ohm)",
                }
            )
        elif data_type == "ECSA":
            gui_vars.update(
                {
                    "ecsa_match": "prefix",
                    "ecsa_prefix": "ECSA",
                    "ecsa_ev": 0.10,
                    "ecsa_last_n": 1,
                    "ecsa_avg_last_n": False,
                    "ecsa_cs_value": 40.0,
                    "ecsa_cs_unit": "uF/cm^2",
                    "ecsa_use_abs_delta": True,
                }
            )
        elif data_type == "COUPLED":
            if not coupled_products_file:
                return {"success": False, "error": "COUPLED processing requires coupled_products_file"}
            gui_vars.update(
                {
                    "coupled_products_file": coupled_products_file,
                    "coupled_products_sheet": coupled_products_sheet or 0,
                    "coupled_results_csv_filename": coupled_results_csv_filename or "coupled_results.csv",
                }
            )
        else:
            return {"success": False, "error": f"Unsupported data_type: {data_type}"}

        if extra_gui_params:
            gui_vars.update(extra_gui_params)

        service_params = dict(gui_vars)
        service_payload: Dict[str, Any] = {
            "folder_path": folder_path,
            "data_types": [data_type],
            "params": service_params,
        }
        if project_name:
            service_payload["project_name"] = project_name

        from electrochem_v6.core.process_service import process_folder

        service_response = process_folder(service_payload)
        if service_response.get("status") != "success":
            return {
                "success": False,
                "error": str(service_response.get("message") or "数据处理失败"),
                "details": service_response.get("result"),
            }
        service_body = service_response.get("result")
        if not isinstance(service_body, dict):
            return {"success": False, "error": "处理服务返回了无效结果"}
        raw_result = service_body.get("raw")
        result = raw_result if isinstance(raw_result, dict) else {}
        processing = service_body.get("processing")
        processing_info = processing if isinstance(processing, dict) else {}
        output_files = [str(item) for item in processing_info.get("output_files") or []]

        scan_stats = scan_result.get("statistics")
        raw_by_type_stats = scan_stats.get("by_type") if isinstance(scan_stats, dict) else {}
        by_type_stats = raw_by_type_stats if isinstance(raw_by_type_stats, dict) else {}
        raw_matched_counts = processing_info.get("matched_counts") or result.get("matched_counts")
        matched_counts = raw_matched_counts if isinstance(raw_matched_counts, dict) else {}
        actual_processed = None
        for module_run in result.get("module_runs") or []:
            if not isinstance(module_run, dict):
                continue
            if str(module_run.get("data_type") or "").upper() == data_type:
                actual_processed = module_run.get("processed")
                break
        if actual_processed is None:
            actual_processed = matched_counts.get(data_type, by_type_stats.get(data_type, 0))

        quality_summary = service_body.get("quality_summary") or result.get("quality_summary", {})
        vision_findings = []
        if isinstance(quality_summary, dict):
            for report in quality_summary.get("files", []) or []:
                stats = (report or {}).get("stats") or {}
                noise = stats.get("noise_analysis") or {}
                vision = noise.get("vision_analysis")
                if isinstance(vision, dict):
                    vision_findings.append(
                        {
                            "file": report.get("filename") or report.get("file") or "unknown",
                            "success": bool(vision.get("success")),
                            "result": vision.get("result") or vision.get("error"),
                            "model": vision.get("model"),
                            "image_path": vision.get("image_path"),
                        }
                    )

        base_suggestion = "建议：查看本次质量报告，并在实验条件一致时比较明确记录的指标；数值排序不代表材料综合等级。"
        if vision_findings:
            highlight = []
            for finding in vision_findings[:3]:
                icon = "✅" if finding["success"] else "⚠️"
                highlight.append(f"{icon} {finding['file']}: {finding.get('result', '无视觉结论')}")
            if len(vision_findings) > 3:
                highlight.append(f"... 还有 {len(vision_findings) - 3} 个文件完成视觉诊断")
            vision_block = "\n".join(highlight)
            ai_suggestion = f"{base_suggestion}\n\n📷 视觉诊断:\n{vision_block}"
        else:
            ai_suggestion = base_suggestion

        manifest = service_body.get("manifest") or {}
        run_id = (manifest.get("run") or {}).get("run_id")
        effective_params = manifest.get("parameters") or service_params
        return {
            "success": True,
            "message": "AI自动处理完成",
            "summary": f"已处理{actual_processed}个{data_type}文件",
            "processing": {
                "scanned_total": scan_result["total_files"],
                "processed_count": actual_processed,
                "data_type": data_type,
                "output_files": output_files,
            },
            "parameters": {
                "potential_offset": effective_params.get("potential_offset"),
                "electrode_area": effective_params.get("area"),
                "target_current": effective_params.get("lsv_target_current"),
                "tafel_enabled": effective_params.get("tafel_enabled", False),
            },
            "effective_params": effective_params,
            "run_id": run_id,
            "project_id": service_body.get("project_id"),
            "ai_suggestion": ai_suggestion,
            "vision_findings": vision_findings,
            "quality_summary": quality_summary,
        }
    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
