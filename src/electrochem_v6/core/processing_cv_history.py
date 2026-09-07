"""History-record helpers for CV processing."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence


def build_cv_history_record(
    *,
    sample_name: str,
    file_stem: str,
    file_path: str,
    params: Mapping[str, Any],
    potential: Sequence[float],
    current: Sequence[float],
    delta_ep_mV: float | None = None,
    charge_mC: float | None = None,
    project_manager: Any | None = None,
) -> dict[str, Any]:
    """Build a CV history record in the legacy-compatible shape."""
    record: dict[str, Any] = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sample_name": sample_name,
        "file_name": file_stem,
        "file_path": file_path,
        "type": "CV",
        "status": "success",
        "results": {
            "data_points": len(potential),
            "potential_range": f"{min(potential):.3f} - {max(potential):.3f} V",
            "current_range": f"{min(current):.2f} - {max(current):.2f} mA",
            "delta_ep_mV": delta_ep_mV,
            "charge_mC": charge_mC,
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


def add_cv_history_record(
    history_manager: Any,
    record: Mapping[str, Any],
    *,
    log_func: Any | None = None,
    sample_name: str = "",
    file_stem: str = "",
) -> None:
    """Persist a CV history record through the configured history manager."""
    history_manager.add_record(dict(record))
    if log_func is not None:
        log_func(f"CV历史记录已保存: {sample_name}/{file_stem}")


__all__ = ["add_cv_history_record", "build_cv_history_record"]
