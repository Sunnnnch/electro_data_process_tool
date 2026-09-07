"""History payload helpers for LSV processing."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence


def build_lsv_history_record(
    *,
    sample_name: str,
    file_stem: str,
    file_path: str,
    params: Mapping[str, Any],
    target_potentials_original: Mapping[float, float],
    target_overpotentials_original: Mapping[float, float],
    overpotential_enabled: bool,
    equilibrium_potential: float,
    slope_mVdec: float | None = None,
    ir_compensation: float | None = None,
) -> dict[str, Any]:
    """Build the compact LSV history record stored for searching and comparison."""
    record: dict[str, Any] = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sample_name": sample_name,
        "file_name": file_stem,
        "file_path": file_path,
        "type": "LSV",
        "status": "success",
        "results": {},
    }
    if params.get("run_id"):
        record["run_id"] = params.get("run_id")

    results = record["results"]
    for target_current, potential in target_potentials_original.items():
        results[f"potential_at_{target_current}"] = potential

    if overpotential_enabled:
        for target_current, overpotential in target_overpotentials_original.items():
            results[f"overpotential_at_{target_current}"] = overpotential

    if 10.0 in target_potentials_original:
        results["potential_10"] = target_potentials_original[10.0]
        if overpotential_enabled:
            results["overpotential_10"] = target_overpotentials_original.get(10.0)
            results["equilibrium_potential"] = equilibrium_potential
            results["overpotential_enabled"] = True

    if slope_mVdec is not None:
        results["tafel_slope"] = slope_mVdec
    if ir_compensation:
        results["ir_compensation"] = ir_compensation
        results["ir_source"] = params.get("ir_source_resolved") or params.get("ir_source")
        results["ir_method"] = params.get("ir_extraction_method_resolved") or params.get("ir_method")
        results["ir_search_scope"] = (
            params.get("ir_eis_search_scope_resolved") or params.get("ir_eis_search_scope")
        )
        results["ir_eis_file"] = params.get("ir_eis_file_resolved")
        results["ir_eis_start_line"] = params.get("ir_eis_start_line_resolved")
        results["ir_formula"] = params.get("ir_compensation_formula")
    return record


def build_lsv_history_data(
    *,
    potential: Sequence[float],
    current: Sequence[float],
    target_currents: Sequence[float],
    potential_compensated: Sequence[float] | None = None,
    ir_compensation: float | None = None,
    tafel_fit_original: Mapping[str, Any] | None = None,
    tafel_fit_ir: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the heavier numeric payload attached to an LSV history record."""
    return {
        "potential_compensated": list(potential_compensated) if potential_compensated is not None else None,
        "potential_original": list(potential),
        "current": list(current),
        "target_currents": list(target_currents),
        "ir_compensation": ir_compensation,
        "tafel_fit_original": tafel_fit_original,
        "tafel_fit_ir": tafel_fit_ir,
    }


def add_lsv_history_record(
    history_mgr: Any,
    record: Mapping[str, Any],
    *,
    data: Mapping[str, Any] | None = None,
    project_id: str | None = None,
) -> None:
    """Add an LSV history record across legacy manager API variants."""
    try:
        history_mgr.add_record(record, data=data, project_id=project_id)
    except TypeError:
        try:
            history_mgr.add_record(record, project_id=project_id)
        except TypeError:
            history_mgr.add_record(record)


__all__ = ["add_lsv_history_record", "build_lsv_history_data", "build_lsv_history_record"]
