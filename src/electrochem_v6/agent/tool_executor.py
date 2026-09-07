"""Central tool dispatcher for the AI agent.

All tool implementations live in dedicated modules (tools_data, tools_projects,
tools_analysis, tools_catalyst). This module wires them into a single
``execute_tool()`` entry-point.
"""

import json
import logging
from typing import Any, Dict, Optional

from electrochem_v6.llm.config import LLMConfig
from electrochem_v6.llm.vision_client import VisionClient

from .actions import (
    prepare_record_comparison,
    prepare_result_report,
    prepare_run_replay,
    propose_parameter_changes,
    remember_recommendation,
)
from .request_context import register_pending_mutation, tool_get_professional_mode_context
from .tools_analysis import tool_analyze_processing_results, tool_read_quality_report
from .tools_catalyst import tool_get_catalyst_info
from .tools_data import (
    tool_analyze_data_characteristics,
    tool_preview_data_file,
    tool_scan_data_folder,
)
from .tools_projects import (
    tool_auto_process_with_smart_params,
    tool_create_project,
    tool_get_current_compare_selection,
    tool_get_current_project_history,
    tool_get_current_project_summary,
    tool_get_processing_history,
)

_logger = logging.getLogger(__name__)

MUTATING_AGENT_TOOLS = {
    "auto_process_with_smart_params",
    "create_project",
}


# ── LSV query tools (kept here – small, tightly coupled to history) ────────

def tool_query_lsv_summary(project_id: Optional[str] = None, sort_by: str = "eta", top_n: Optional[int] = None) -> Dict:
    """查询LSV数据汇总。"""
    try:
        from electrochem_v6.store.runtime import get_history_store

        hist_mgr = get_history_store()

        if project_id and project_id.lower() in ("all", "none", ""):
            project_id = None

        summary = hist_mgr.get_lsv_summary(project_id=project_id) if project_id else hist_mgr.get_lsv_summary()
        samples = summary.get("samples", [])

        _logger.debug("tool_query_lsv_summary: project_id=%s, 原始samples数量 = %d", project_id, len(samples))

        from electrochem_v6.core.agent_scientific import finite_number

        metric = "tafel_slope" if sort_by == "tafel" else "overpotential_10"
        samples = sorted(samples, key=lambda item: (
            finite_number(item.get(metric)) is None,
            finite_number(item.get(metric)) if finite_number(item.get(metric)) is not None else 0,
        ))

        if top_n:
            samples = samples[:top_n]

        return {
            "success": True,
            "total_samples": len(summary.get("samples", [])),
            "returned_samples": len(samples),
            "samples": samples,
            "ranking_metric": metric,
            "unranked_samples": sum(finite_number(item.get(metric)) is None for item in samples),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_find_best_catalysts(project_id: Optional[str] = None, count: int = 5) -> Dict:
    """找出最优催化剂。"""
    result = tool_query_lsv_summary(project_id=project_id, sort_by="eta", top_n=count)
    _logger.debug("tool_find_best_catalysts: result=%s", result)

    if result.get("success"):
        from electrochem_v6.core.agent_scientific import finite_number

        samples = [item for item in result.get("samples", []) if finite_number(item.get("overpotential_10")) is not None]
        if len(samples) == 0:
            return {
                "success": False,
                "message": "没有具有有效 η@10 指标的 LSV 记录，无法据此排名；请检查结果与过电位计算设置。",
                "suggestion": "Please check data processing tab for LSV data",
            }
        return {
            "success": True,
            "count": len(samples),
            "total_in_database": result.get("total_samples", len(samples)),
            "best_catalysts": samples,
        }
    return result


def tool_compare_catalysts(sample_names: list[str]) -> Dict:
    """对比催化剂性能。"""
    try:
        from electrochem_v6.store.runtime import get_history_store

        hist_mgr = get_history_store()
        all_records = hist_mgr.get_all_records()

        comparison = []
        for name in sample_names:
            for record in all_records:
                if record.get("sample_name") == name and record.get("type") == "LSV":
                    results = record.get("results", {})
                    comparison.append(
                        {
                            "sample_name": name,
                            "overpotential_10": results.get("overpotential_10"),
                            "tafel_slope": results.get("tafel_slope"),
                            "project": record.get("project_name", "Unknown"),
                        }
                    )
                    break

        if comparison:
            best_eta_sample = min(comparison, key=lambda x: x.get("overpotential_10", 999))
            return {
                "success": True,
                "comparison": comparison,
                "best_catalyst": best_eta_sample["sample_name"],
                "best_overpotential": best_eta_sample["overpotential_10"],
            }
        return {"success": False, "error": "未找到指定样品的数据"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Vision tool ────────────────────────────────────────────────────────────

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
    # Path boundary check: only allow images under user-accessible directories
    from electrochem_v6.agent.tools_data import _is_agent_path_allowed
    if not _is_agent_path_allowed(image_path):
        return {"success": False, "error": "图片路径不在允许范围内"}
    prompt = context or "请检查这条波形是否存在异常波动，并说明原因。"
    cfg = LLMConfig().get_vision_config()
    max_tokens = max_tokens or int(cfg.get("max_tokens", 800))
    return client.analyze_image(image_path=image_path, prompt=prompt, max_tokens=max_tokens)


# ── Main dispatcher ────────────────────────────────────────────────────────

def execute_tool(
    tool_name: str,
    arguments: str | Dict[str, Any],
    *,
    approved: bool = False,
) -> Dict:
    """Execute a named tool function with given arguments."""
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            return {"success": False, "error": "参数解析失败"}
    else:
        args = arguments
    if not isinstance(args, dict):
        return {"success": False, "error": "工具参数必须是对象"}

    if tool_name in MUTATING_AGENT_TOOLS and not approved:
        return register_pending_mutation(tool_name, args)

    tool_map = {
        "propose_parameter_changes": propose_parameter_changes,
        "prepare_record_comparison": prepare_record_comparison,
        "prepare_run_replay": prepare_run_replay,
        "prepare_result_report": prepare_result_report,
        # Request-scoped UI context
        "get_professional_mode_context": tool_get_professional_mode_context,
        # LSV query
        "query_lsv_summary": tool_query_lsv_summary,
        "find_best_catalysts": tool_find_best_catalysts,
        "compare_catalysts": tool_compare_catalysts,
        # Project / history
        "get_current_project_summary": tool_get_current_project_summary,
        "get_current_project_history": tool_get_current_project_history,
        "get_current_compare_selection": tool_get_current_compare_selection,
        "create_project": tool_create_project,
        "get_processing_history": tool_get_processing_history,
        # Data scanning
        "scan_data_folder": tool_scan_data_folder,
        "preview_data_file": tool_preview_data_file,
        "analyze_data_characteristics": tool_analyze_data_characteristics,
        "auto_process_with_smart_params": tool_auto_process_with_smart_params,
        # Analysis
        "read_quality_report": tool_read_quality_report,
        "analyze_processing_results": tool_analyze_processing_results,
        # Catalyst
        "get_catalyst_info": tool_get_catalyst_info,
        # Vision
        "analyze_waveform_image": tool_analyze_waveform_image,
    }

    if tool_name in tool_map:
        try:
            result = tool_map[tool_name](**args)
            if tool_name == "analyze_data_characteristics":
                remember_recommendation(result)
            return result
        except Exception as e:
            _logger.warning("工具 %s 执行失败: %s", tool_name, e, exc_info=True)
            return {"success": False, "error": f"工具执行失败: {str(e)}"}
    return {"success": False, "error": f"未知工具: {tool_name}"}


__all__ = ["MUTATING_AGENT_TOOLS", "execute_tool"]
