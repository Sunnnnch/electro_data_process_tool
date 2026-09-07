"""Direct LSV processing module for the runtime module registry."""

from __future__ import annotations

import math
import os
from typing import Any, Mapping, Sequence

from electrochem_v6.core.job_control import progress_work_items
from electrochem_v6.core.processing_common import build_file_context
from electrochem_v6.core.processing_lsv import process_lsv
from electrochem_v6.core.processing_lsv_metrics import build_lsv_result_columns
from electrochem_v6.core.processing_lsv_plot import plot_combined_lsv
from electrochem_v6.core.processing_metric_registry import resolve_metric
from electrochem_v6.core.processing_module_contract import ModuleRunContext, ModuleRunResult
from electrochem_v6.core.processing_registry import (
    PROCESSING_MODULES,
    get_module_spec,
    merge_parameter_defaults,
)
from electrochem_v6.core.processing_result_collect import make_metric_key
from electrochem_v6.core.processing_result_models import MetricValue, ProcessingResult, SourceFileRef
from electrochem_v6.core.processing_scan import resolve_data_start_line, scan_process_inputs
from electrochem_v6.core.utils import as_bool, as_float, as_int


class LsvDirectModule:
    """Run LSV files directly and return normalized processing results."""

    spec = get_module_spec("LSV")

    def _scan_params(self, context: ModuleRunContext) -> dict[str, Any]:
        params = merge_parameter_defaults(self.spec.key, context.params)
        raw_params = dict(context.params or {})
        if not raw_params.get("ir_source") and str(raw_params.get("ir_method") or "").lower() == "manual":
            params["ir_source"] = "manual"
            params["ir_method"] = "auto"
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
        raw_params = dict(context.params or {})
        if not raw_params.get("ir_source") and str(raw_params.get("ir_method") or "").lower() == "manual":
            params["ir_source"] = "manual"
            params["ir_method"] = "auto"
        start_line = params.get("start_line") or str(resolve_data_start_line(file_path, params))
        params["start_line"] = str(start_line)
        params["offset"] = params.get("potential_offset", params.get("offset", 0.0))
        params["area"] = params.get("area", 1.0)
        params["output_dir"] = self._output_dir_for(context, file_path)
        if context.project_id and not params.get("project_id"):
            params["project_id"] = context.project_id
        if context.run_id and not params.get("run_id"):
            params["run_id"] = context.run_id

        params["xlabel"] = params.get("lsv_xlabel", params.get("xlabel", "Potential (V)"))
        params["ylabel"] = params.get("lsv_ylabel", params.get("ylabel", "Current Density (mA/cm2)"))
        params["title"] = params.get("lsv_title", params.get("title", "LSV of {sample}"))
        params["font"] = params.get("font_family") or params.get("font") or ""
        params["fontsize"] = as_int(params.get("font_size", params.get("fontsize", 12)), 12)
        params["target_current"] = params.get("lsv_target_current", params.get("target_current", "10"))
        params["line_color"] = params.get("lsv_line_color", params.get("line_color", "blue"))
        params["line_width"] = as_float(params.get("lsv_line_width", params.get("line_width", 2.0)), 2.0)
        params["mark_targets"] = as_bool(params.get("lsv_mark_targets", params.get("mark_targets", True)), True)
        params["use_abs_current"] = as_bool(params.get("use_abs_current", True), True)
        params["ir_compensation_enabled"] = as_bool(params.get("ir_compensation_enabled", False), False)
        params["input_root"] = os.path.abspath(context.folder_path)
        params["ir_source"] = params.get("ir_source", "eis")
        params["ir_eis_search_scope"] = params.get("ir_eis_search_scope", "same_dir")
        params["ir_eis_file"] = params.get("ir_eis_file", "")
        params["ir_eis_match"] = params.get("ir_eis_match", params.get("eis_match", "prefix"))
        params["ir_eis_pattern"] = params.get("ir_eis_pattern", params.get("eis_prefix", "EIS"))
        params["eis_match"] = params.get("eis_match", "prefix")
        params["eis_prefix"] = params.get("eis_prefix", "EIS")
        params["eis_start_line"] = params.get("eis_start_line", start_line)
        params["tafel_enabled"] = as_bool(params.get("tafel_enabled", False), False)
        params["tafel_range"] = params.get("tafel_range", "1-10")
        params["export_tafel_plot"] = as_bool(params.get("export_tafel_plot", False), False)
        params["ir_method"] = params.get("ir_method", "auto")
        params["ir_validation_mode"] = params.get("ir_validation_mode", "strict")
        params["ir_linear_points"] = params.get("ir_linear_points", 10)
        params["overpotential_enabled"] = as_bool(params.get("overpotential_enabled", False), False)
        params["onset_enabled"] = as_bool(params.get("onset_enabled", False), False)
        params["onset_current"] = params.get("onset_current", "1.0")
        params["eq_potential"] = params.get("eq_potential", 0.0)
        params["halfwave_enabled"] = as_bool(params.get("halfwave_enabled", False), False)
        params["halfwave_current"] = params.get("halfwave_current", "")
        params["label_mode"] = params.get("lsv_label_mode", params.get("label_mode", "subfolder"))
        params["plot_grid"] = as_bool(params.get("plot_grid", True), True)
        params["export_detail"] = as_bool(params.get("lsv_export_data", params.get("export_detail", False)), False)
        params["ir_manual_ohm"] = params.get("ir_manual_ohm", 0.0)
        params.setdefault(
            "quality_config",
            {
                "min_points_issue": params.get("lsv_quality_min_points_issue"),
                "min_points_warning": params.get("lsv_quality_min_points_warning"),
                "outlier_ratio_warning_pct": params.get("lsv_quality_outlier_warning_pct"),
                "min_potential_span_warning": params.get("lsv_quality_min_potential_span"),
                "noise_warning": params.get("lsv_quality_noise_warning"),
                "noise_critical": params.get("lsv_quality_noise_critical"),
                "jump_ratio_warning": params.get("lsv_quality_jump_warning"),
                "jump_ratio_critical": params.get("lsv_quality_jump_critical"),
                "local_variation_factor": params.get("lsv_quality_local_variation_factor"),
            },
        )
        return params

    @staticmethod
    def _is_missing(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, float):
            return math.isnan(value)
        try:
            return bool(value != value)
        except Exception:
            return False

    @staticmethod
    def _dedupe_key(key: str, used: set[str]) -> str:
        if key not in used:
            used.add(key)
            return key
        suffix = 2
        while f"{key}_{suffix}" in used:
            suffix += 1
        final_key = f"{key}_{suffix}"
        used.add(final_key)
        return final_key

    @staticmethod
    def _collect_artifacts(subfolder: str, filename: str, params: Mapping[str, Any]) -> tuple[str, ...]:
        ctx = build_file_context(subfolder, filename, params)
        expected = [
            os.path.join(ctx.output_dir, f"{ctx.sample_name}_{ctx.file_stem}_LSV.png"),
            os.path.join(ctx.output_dir, f"{ctx.sample_name}_{ctx.file_stem}_LSV_IR_compensated.png"),
            os.path.join(ctx.output_dir, f"{ctx.sample_name}_{ctx.file_stem}_Tafel_fit.png"),
            os.path.join(ctx.output_dir, f"{ctx.sample_name}_{ctx.file_stem}_Tafel_fit_IR.png"),
            os.path.join(ctx.output_dir, f"{ctx.file_stem}.xlsx"),
            os.path.join(ctx.output_dir, f"{ctx.file_stem}_raw.csv"),
            os.path.join(ctx.output_dir, f"{ctx.file_stem}_targets.csv"),
        ]
        return tuple(path for path in expected if os.path.isfile(path))

    def _processing_result_from_row(
        self,
        row: Sequence[Any],
        columns: Sequence[str],
        *,
        file_path: str,
        artifacts: Sequence[str],
        context: ModuleRunContext,
        params: Mapping[str, Any],
        ir_provenance: Mapping[str, Any] | None = None,
        source_profile: Mapping[str, Any] | None = None,
    ) -> ProcessingResult:
        record = dict(zip(columns, row))
        sample_name = str(record.get("Sample_Name") or os.path.basename(os.path.dirname(file_path)) or "unknown_sample")
        file_name = str(record.get("File_Name") or os.path.basename(file_path))
        used_keys: set[str] = set()
        metrics: list[MetricValue] = []
        for column, value in record.items():
            if column in {"Sample_Name", "File_Name"} or self._is_missing(value):
                continue
            base_key = self._dedupe_key(make_metric_key(str(column)), used_keys)
            resolved = resolve_metric(self.spec.key, str(column), fallback_key=base_key)
            metrics.append(
                MetricValue(
                    key=resolved.key,
                    label=resolved.label,
                    value=value,
                    unit=resolved.unit,
                    method=resolved.method,
                    metadata=resolved.metadata,
                )
            )

        return ProcessingResult(
            data_type=self.spec.key,
            sample_name=sample_name,
            source=SourceFileRef(
                sample_name=sample_name,
                file_name=file_name,
                path=os.path.abspath(file_path),
                data_type=self.spec.key,
            ),
            metrics=tuple(metrics),
            artifacts=tuple(str(item) for item in artifacts if str(item).strip()),
            project_id=context.project_id or params.get("project_id"),
            run_id=context.run_id or params.get("run_id"),
            metadata={
                "module": "direct_lsv",
                "row_columns": len(columns),
                "row_values": len(row),
                "ir_provenance": dict(ir_provenance or {}),
                "source_profile": dict(source_profile or {}),
            },
        )

    @staticmethod
    def _fallback_quality_report(file_path: str) -> dict[str, Any]:
        return {
            "filename": os.path.basename(file_path),
            "is_valid": True,
            "warnings": [],
            "issues": [],
            "quality_level": "normal",
            "recommendation": "none",
        }

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
        collect_series: list[dict[str, Any]] = []
        ir_records: list[dict[str, Any]] = []
        run_params = merge_parameter_defaults(self.spec.key, context.params)
        enable_quality = as_bool(run_params.get("lsv_quality_check", True), True)

        for raw_file in progress_work_items(context.params, files):
            file_path = os.path.abspath(str(raw_file))
            subfolder = os.path.dirname(file_path)
            filename = os.path.basename(file_path)
            params = self._file_params(context, file_path)
            params["collect_series"] = collect_series
            try:
                payload = process_lsv(
                    subfolder,
                    filename,
                    params,
                    project_id=context.project_id or params.get("project_id"),
                    enable_quality_check=enable_quality,
                )
            except Exception as exc:
                skipped += 1
                messages.append(f"LSV skipped {filename}: {exc}")
                continue

            if isinstance(payload, Mapping):
                row = payload.get("result_row") or []
                quality = payload.get("quality_report")
                ir_provenance = payload.get("ir_provenance")
                source_profile = payload.get("source_profile")
            else:
                row = payload or []
                quality = None
                ir_provenance = None
                source_profile = None
            if not row:
                skipped += 1
                messages.append(f"LSV produced no valid data: {filename}")
                continue

            file_artifacts = self._collect_artifacts(subfolder, filename, params)
            result = self._processing_result_from_row(
                row,
                build_lsv_result_columns(params),
                file_path=file_path,
                artifacts=file_artifacts,
                context=context,
                params=params,
                ir_provenance=ir_provenance if isinstance(ir_provenance, Mapping) else None,
                source_profile=source_profile if isinstance(source_profile, Mapping) else None,
            )
            results.append(result)
            if isinstance(ir_provenance, Mapping) and ir_provenance.get("enabled"):
                ir_records.append(dict(ir_provenance))
            for artifact in file_artifacts:
                if artifact and artifact not in artifacts:
                    artifacts.append(artifact)
            quality_reports.append(quality if isinstance(quality, Mapping) else self._fallback_quality_report(file_path))

        combined_lsv_png = None
        if as_bool(run_params.get("lsv_combine_all", False), False) and collect_series:
            output_dir = str(context.output_dir or run_params.get("output_dir") or context.folder_path)
            os.makedirs(output_dir, exist_ok=True)
            combined_lsv_png = plot_combined_lsv(
                collect_series,
                output_path=os.path.join(output_dir, "LSV_combined.png"),
                params=run_params,
                font_name=str(run_params.get("font_family") or run_params.get("font") or ""),
            )
            if combined_lsv_png and combined_lsv_png not in artifacts:
                artifacts.append(combined_lsv_png)

        return ModuleRunResult(
            data_type=self.spec.key,
            results=tuple(results),
            artifacts=tuple(artifacts),
            quality_reports=tuple(quality_reports),
            messages=tuple(messages),
            metadata={
                "module": "direct_lsv",
                "input_files": len(files),
                "processed_files": len(results),
                "skipped_files": skipped,
                "ir_compensation": ir_records,
                "combined_lsv_png": combined_lsv_png,
            },
        )


__all__ = ["LsvDirectModule"]
