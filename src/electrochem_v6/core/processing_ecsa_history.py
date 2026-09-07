"""History-record helpers for ECSA processing."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from .processing_ecsa_calc import EcsaFitResult


def build_ecsa_history_record(
    *,
    sample_name: str,
    subfolder: str,
    params: Mapping[str, Any],
    fit: EcsaFitResult,
    scan_rates: Sequence[float],
    project_manager: Any | None = None,
) -> dict[str, Any]:
    """Build an ECSA history record in the legacy-compatible shape."""
    record: dict[str, Any] = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sample_name": sample_name,
        "file_name": "ECSA",
        "file_path": subfolder,
        "type": "ECSA",
        "status": "success",
        "results": {
            "Cdl": float(fit.cdl_mFcm2),
            "ECSA": float(fit.ecsa_cm2),
            "RF": float(fit.rf),
            "R2": float(fit.r2),
            "scan_rates": len(scan_rates),
            "Cs_input": float(fit.cs_input),
            "Cs_unit": fit.cs_unit,
            "Cs_mFcm2": float(fit.cs_mFcm2),
            "geometric_area_cm2": float(params.get("area", 1.0)),
            "method": "double_layer_capacitance_scan_rate_fit",
        },
    }
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


def add_ecsa_history_record(
    history_manager: Any,
    record: Mapping[str, Any],
    *,
    log_func: Any | None = None,
    sample_name: str = "",
) -> None:
    """Persist an ECSA history record through the configured history manager."""
    history_manager.add_record(dict(record))
    if log_func is not None:
        log_func(f"ECSA历史记录已保存: {sample_name}")


__all__ = ["add_ecsa_history_record", "build_ecsa_history_record"]
