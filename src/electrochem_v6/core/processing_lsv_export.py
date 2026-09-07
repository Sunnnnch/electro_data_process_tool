"""Result export helpers for LSV processing."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Mapping, Sequence

import pandas as pd

from .processing_common import ensure_output_dir


def build_lsv_detail_records(
    *,
    potential: Sequence[float],
    current: Sequence[float],
    current_signed: Sequence[float],
    target_potentials_original: Mapping[float, float],
    target_potentials_compensated: Mapping[float, float] | None = None,
    potential_compensated: Sequence[float] | None = None,
    ir_compensation: float | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build raw and target detail rows for per-file LSV exports."""
    raw_records: list[dict[str, Any]] = []
    for idx, (pot, cur, cur_sig) in enumerate(zip(potential, current, current_signed)):
        row: dict[str, Any] = {
            "Potential(V)": pot,
            "Current(mA/cm2)": cur,
            "CurrentSigned(mA/cm2)": cur_sig,
            "IR_Ohm": ir_compensation,
        }
        if potential_compensated is not None:
            row["Potential_IRComp(V)"] = potential_compensated[idx]
        raw_records.append(row)

    target_records: list[dict[str, Any]] = []
    compensated_targets = target_potentials_compensated or {}
    for target_current, original_potential in target_potentials_original.items():
        target_records.append(
            {
                "Target_Current(mA/cm2)": target_current,
                "Potential_Orig(V)": original_potential,
                "Potential_IRComp(V)": compensated_targets.get(target_current),
                "IR_Ohm": ir_compensation,
            }
        )
    return raw_records, target_records


def export_lsv_detail(
    *,
    output_dir: str,
    file_stem: str,
    sample_name: str,
    source_file: str,
    params: Mapping[str, Any],
    target_currents: Sequence[float],
    potential: Sequence[float],
    current: Sequence[float],
    current_signed: Sequence[float],
    target_potentials_original: Mapping[float, float],
    target_potentials_compensated: Mapping[float, float] | None = None,
    potential_compensated: Sequence[float] | None = None,
    ir_compensation: float | None = None,
    software_version: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Export per-file LSV details to XLSX, falling back to CSV if needed."""
    raw_records, target_records = build_lsv_detail_records(
        potential=potential,
        current=current,
        current_signed=current_signed,
        target_potentials_original=target_potentials_original,
        target_potentials_compensated=target_potentials_compensated,
        potential_compensated=potential_compensated,
        ir_compensation=ir_compensation,
    )

    output_dir = ensure_output_dir(output_dir, output_dir)
    out_xlsx = os.path.join(output_dir, f"{file_stem}.xlsx")
    try:
        with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
            pd.DataFrame(raw_records).to_excel(writer, sheet_name="raw", index=False)
            pd.DataFrame(target_records).to_excel(writer, sheet_name="targets", index=False)
            info_rows = [
                {"Key": "SoftwareVersion", "Value": software_version},
                {"Key": "GeneratedAt", "Value": datetime.now().isoformat(timespec="seconds")},
                {"Key": "Sample", "Value": sample_name},
                {"Key": "SourceFile", "Value": source_file},
                {"Key": "Area_cm2", "Value": params.get("area")},
                {"Key": "IR_Source", "Value": params.get("ir_source_resolved") or params.get("ir_source")},
                {"Key": "IR_Method", "Value": params.get("ir_extraction_method_resolved") or params.get("ir_method")},
                {"Key": "IR_SearchScope", "Value": params.get("ir_eis_search_scope_resolved") or params.get("ir_eis_search_scope")},
                {"Key": "IR_EISFile", "Value": params.get("ir_eis_file_resolved")},
                {"Key": "IR_EISStartLine", "Value": params.get("ir_eis_start_line_resolved")},
                {"Key": "IR_Formula", "Value": params.get("ir_compensation_formula")},
                {"Key": "IR_Ohm", "Value": ir_compensation},
                {"Key": "Targets(mA/cm2)", "Value": ",".join(str(t) for t in target_currents)},
            ]
            pd.DataFrame(info_rows).to_excel(writer, sheet_name="info", index=False)
    except Exception:
        pd.DataFrame(raw_records).to_csv(
            os.path.join(output_dir, f"{file_stem}_raw.csv"),
            index=False,
            encoding="utf-8-sig",
        )
        pd.DataFrame(target_records).to_csv(
            os.path.join(output_dir, f"{file_stem}_targets.csv"),
            index=False,
            encoding="utf-8-sig",
        )
    return raw_records, target_records


__all__ = ["build_lsv_detail_records", "export_lsv_detail"]
