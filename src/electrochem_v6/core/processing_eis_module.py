"""Direct EIS processing module for the runtime module registry."""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from electrochem_v6.core.job_control import progress_work_items
from electrochem_v6.core.processing_eis import process_eis
from electrochem_v6.core.processing_module_contract import ModuleRunContext, ModuleRunResult
from electrochem_v6.core.processing_registry import (
    PROCESSING_MODULES,
    get_module_spec,
    merge_parameter_defaults,
)
from electrochem_v6.core.processing_result_models import ProcessingResult
from electrochem_v6.core.processing_scan import resolve_data_start_line, scan_process_inputs
from electrochem_v6.core.utils import as_bool, as_float, as_int


class EisDirectModule:
    """Run EIS files directly and return normalized processing results."""

    spec = get_module_spec("EIS")

    def _scan_params(self, context: ModuleRunContext) -> dict[str, Any]:
        params = merge_parameter_defaults(self.spec.key, context.params)
        for spec in PROCESSING_MODULES:
            params[spec.enabled_key] = spec.key == self.spec.key
        if context.output_dir and not params.get("output_dir"):
            params["output_dir"] = context.output_dir
        if context.project_id and not params.get("project_id"):
            params["project_id"] = context.project_id
        if context.run_id and not params.get("run_id"):
            params["run_id"] = context.run_id
        return params

    @staticmethod
    def _output_dir_for(context: ModuleRunContext, file_path: str) -> str:
        params = dict(context.params or {})
        root = os.path.abspath(context.folder_path)
        file_dir = os.path.abspath(os.path.dirname(file_path))
        output_root = str(context.output_dir or params.get("output_dir") or "").strip()
        if not output_root:
            return file_dir
        output_root = os.path.abspath(output_root)
        try:
            rel = os.path.relpath(file_dir, root)
        except ValueError:
            rel = "."
        target = output_root if rel in (".", "") else os.path.join(output_root, rel)
        os.makedirs(target, exist_ok=True)
        return target

    def _file_params(self, context: ModuleRunContext, file_path: str) -> dict[str, Any]:
        params = merge_parameter_defaults(self.spec.key, context.params)
        if not params.get("start_line"):
            params["start_line"] = str(resolve_data_start_line(file_path, params))
        params["output_dir"] = self._output_dir_for(context, file_path)
        if context.project_id and not params.get("project_id"):
            params["project_id"] = context.project_id
        if context.run_id and not params.get("run_id"):
            params["run_id"] = context.run_id
        params.setdefault("xlabel", params.get("eis_xlabel", "Z' (Ohm)"))
        params.setdefault("ylabel", params.get("eis_ylabel", "-Z'' (Ohm)"))
        params.setdefault("title", params.get("eis_title", "EIS of {sample}"))
        params.setdefault("font", params.get("font_family") or params.get("font") or "")
        params.setdefault("fontsize", as_int(params.get("font_size", params.get("fontsize", 12)), 12))
        params.setdefault("line_color", params.get("eis_line_color", "blue"))
        params.setdefault("line_width", as_float(params.get("eis_line_width", params.get("line_width", 2.0)), 2.0))
        params.setdefault("plot_grid", as_bool(params.get("plot_grid", True), True))
        params.setdefault("plot_nyquist", as_bool(params.get("plot_nyquist", True), True))
        params.setdefault("plot_bode", as_bool(params.get("plot_bode", False), False))
        params.setdefault("randles_fit", as_bool(params.get("eis_randles_fit", params.get("randles_fit", False)), False))
        params.setdefault("eis_circuit_model", params.get("eis_circuit_model", "randles_rc"))
        params.setdefault("eis_fit_min_r2", as_float(params.get("eis_fit_min_r2", 0.5), 0.5))
        return params

    def detect_files(self, context: ModuleRunContext) -> Sequence[str]:
        scan = scan_process_inputs(context.folder_path, self._scan_params(context))
        by_type = scan.get("by_type") if isinstance(scan, Mapping) else {}
        entry = by_type.get(self.spec.key) if isinstance(by_type, Mapping) else {}
        values = entry.get("files") if isinstance(entry, Mapping) else []
        if not isinstance(values, list):
            values = []
        return tuple(str(item) for item in values if str(item).strip())

    def validate_params(self, context: ModuleRunContext) -> list[str]:
        if not os.path.isdir(context.folder_path):
            return [f"folder_path not found: {context.folder_path}"]
        return []

    def run(self, context: ModuleRunContext, files: Sequence[str]) -> ModuleRunResult:
        results: list[ProcessingResult] = []
        artifacts: list[str] = []
        quality_reports: list[Mapping[str, Any]] = []
        messages: list[str] = []
        skipped = 0

        for raw_file in progress_work_items(context.params, files):
            file_path = os.path.abspath(str(raw_file))
            try:
                payload = process_eis(
                    os.path.dirname(file_path),
                    os.path.basename(file_path),
                    self._file_params(context, file_path),
                )
            except Exception as exc:
                skipped += 1
                messages.append(f"EIS skipped {os.path.basename(file_path)}: {exc}")
                continue
            if not isinstance(payload, Mapping):
                skipped += 1
                messages.append(f"EIS produced no valid data: {os.path.basename(file_path)}")
                continue

            result = payload.get("processing_result")
            if isinstance(result, ProcessingResult):
                results.append(result)

            for artifact in payload.get("artifacts", []) or []:
                artifact_text = str(artifact).strip()
                if artifact_text and artifact_text not in artifacts:
                    artifacts.append(artifact_text)

            quality = payload.get("quality_report")
            if isinstance(quality, Mapping):
                quality_reports.append(quality)

        return ModuleRunResult(
            data_type=self.spec.key,
            results=tuple(results),
            artifacts=tuple(artifacts),
            quality_reports=tuple(quality_reports),
            messages=tuple(messages),
            metadata={
                "module": "direct_eis",
                "input_files": len(files),
                "processed_files": len(results),
                "skipped_files": skipped,
            },
        )


__all__ = ["EisDirectModule"]
