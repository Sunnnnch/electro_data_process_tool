"""Direct CV processing module for the runtime module registry."""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from electrochem_v6.core.job_control import progress_work_items
from electrochem_v6.core.processing_cv import process_cv
from electrochem_v6.core.processing_module_contract import ModuleRunContext, ModuleRunResult
from electrochem_v6.core.processing_registry import (
    PROCESSING_MODULES,
    get_module_spec,
    merge_parameter_defaults,
)
from electrochem_v6.core.processing_result_models import ProcessingResult
from electrochem_v6.core.processing_scan import resolve_data_start_line, scan_process_inputs
from electrochem_v6.core.utils import as_bool, as_float, as_int


class CvDirectModule:
    """Run CV files directly and return normalized processing results."""

    spec = get_module_spec("CV")

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
        params.setdefault("xlabel", params.get("cv_xlabel", "Potential (V)"))
        params.setdefault("ylabel", params.get("cv_ylabel", "Current (mA)"))
        params.setdefault("title", params.get("cv_title", "CV of {sample}"))
        params.setdefault("font", params.get("font_family") or params.get("font") or "")
        params.setdefault("fontsize", as_int(params.get("font_size", params.get("fontsize", 12)), 12))
        params.setdefault("line_color", params.get("cv_line_color", "blue"))
        params.setdefault("line_width", as_float(params.get("cv_line_width", params.get("line_width", 2.0)), 2.0))
        params.setdefault("plot_grid", as_bool(params.get("plot_grid", True), True))
        params.setdefault("peaks_enabled", as_bool(params.get("cv_peaks_enabled", params.get("peaks_enabled", False)), False))
        params.setdefault("peaks_smooth", as_int(params.get("cv_peaks_smooth", params.get("peaks_smooth", 5)), 5))
        params.setdefault("peaks_min_height", as_float(params.get("cv_peaks_min_height", params.get("peaks_min_height", 1.0)), 1.0))
        params.setdefault("peaks_min_dist", as_int(params.get("cv_peaks_min_dist", params.get("peaks_min_dist", 5)), 5))
        params.setdefault("peaks_max", as_int(params.get("cv_peaks_max", params.get("peaks_max", 2)), 2))
        params.setdefault(
            "cycle_plot_enabled",
            as_bool(params.get("cv_cycle_plot_enabled", params.get("cycle_plot_enabled", False)), False),
        )
        params.setdefault("cycle_numbers", params.get("cv_cycle_numbers", params.get("cycle_numbers", "")))
        params.setdefault("cv_cycle_reversal_tolerance", params.get("cycle_reversal_tolerance"))
        params.setdefault("cv_cycle_min_segment_points", params.get("cycle_min_segment_points", 3))
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
        run_params = merge_parameter_defaults(self.spec.key, context.params)
        enable_quality = as_bool(run_params.get("cv_quality_check", True), True)

        for raw_file in progress_work_items(context.params, files):
            file_path = os.path.abspath(str(raw_file))
            try:
                payload = process_cv(
                    os.path.dirname(file_path),
                    os.path.basename(file_path),
                    self._file_params(context, file_path),
                    enable_quality_check=enable_quality,
                )
            except Exception as exc:
                skipped += 1
                messages.append(f"CV skipped {os.path.basename(file_path)}: {exc}")
                continue
            if not isinstance(payload, Mapping):
                skipped += 1
                messages.append(f"CV produced no valid data: {os.path.basename(file_path)}")
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
                "module": "direct_cv",
                "input_files": len(files),
                "processed_files": len(results),
                "skipped_files": skipped,
            },
        )


__all__ = ["CvDirectModule"]
