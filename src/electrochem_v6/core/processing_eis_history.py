"""History-record helpers for EIS processing."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence


def build_eis_history_record(
    *,
    sample_name: str,
    file_stem: str,
    file_path: str,
    params: Mapping[str, Any],
    frequency: Sequence[float],
    z_real: Sequence[float],
    randles_result: Mapping[str, Any] | None = None,
    project_manager: Any | None = None,
    analysis: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an EIS history record in the legacy-compatible shape."""
    rs = None
    rct = None
    cdl = None
    q = None
    cpe_n = None
    if randles_result:
        rs = randles_result["Rs"]
        rct = randles_result.get("Rct")
        cdl = randles_result.get("Cdl")
        q = randles_result.get("Q")
        cpe_n = randles_result.get("n")
    elif params.get("ir_enabled") and z_real:
        rs = min(z_real)

    record: dict[str, Any] = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sample_name": sample_name,
        "file_name": file_stem,
        "file_path": file_path,
        "type": "EIS",
        "status": "success",
        "results": {
            "Rs": float(rs) if rs is not None else None,
            "Rct": float(rct) if rct is not None else None,
            "Cdl": float(cdl) if cdl is not None else None,
            "CPE_Q": float(q) if q is not None else None,
            "CPE_n": float(cpe_n) if cpe_n is not None else None,
            "circuit_model": randles_result.get("model") if randles_result else None,
            "equivalent_circuit": randles_result.get("equivalent_circuit") if randles_result else None,
            "randles_r2": float(randles_result["r2"]) if randles_result else None,
            "fit_rmse_ohm": float(randles_result["rmse_complex_ohm"])
            if randles_result and randles_result.get("rmse_complex_ohm") is not None
            else None,
            "frequency_range": f"{min(frequency):.2e} - {max(frequency):.2e} Hz",
            "data_points": len(frequency),
        },
    }
    if randles_result:
        for key in ("sigma", "R1", "R2", "C1", "C2", "Q1", "Q2", "n1", "n2"):
            if randles_result.get(key) is not None:
                record["results"][key] = float(randles_result[key])
    if analysis is not None:
        record["eis_analysis"] = dict(analysis)
        diagnostics = analysis.get("fit") or {}
        record["results"]["circuit_model"] = diagnostics.get("model")
        record["results"]["equivalent_circuit"] = diagnostics.get("equivalent_circuit")
        record["results"]["fit_status"] = diagnostics.get("status", "not_requested")
        record["results"]["kk_status"] = (analysis.get("kk") or {}).get("status", "not_requested")
    if params.get("run_id"):
        record["run_id"] = params.get("run_id")

    project_id = params.get("project_id")
    if project_id:
        record["project_id"] = project_id
        if project_manager is not None:
            try:
                project = project_manager.get_project(project_id)
                if project:
                    record["project_name"] = project["name"]
            except Exception:
                pass
    return record


def add_eis_history_record(
    history_manager: Any,
    record: Mapping[str, Any],
    *,
    log_func: Any | None = None,
    sample_name: str = "",
    file_stem: str = "",
) -> None:
    """Persist an EIS history record through the configured history manager."""
    history_manager.add_record(dict(record))
    if log_func is not None:
        log_func(f"EIS历史记录已保存: {sample_name}/{file_stem}")


__all__ = ["add_eis_history_record", "build_eis_history_record"]
