"""Direct ECSA processing module for the runtime module registry."""

from __future__ import annotations

import math
import os
from typing import Any, Mapping, Sequence

from electrochem_v6.core.job_control import progress_work_items
from electrochem_v6.core.processing_ecsa import process_ecsa_for_subfolder
from electrochem_v6.core.processing_metric_registry import resolve_metric
from electrochem_v6.core.processing_module_contract import ModuleRunContext, ModuleRunResult
from electrochem_v6.core.processing_registry import (
    PROCESSING_MODULES,
    get_module_spec,
    merge_parameter_defaults,
)
from electrochem_v6.core.processing_result_collect import make_metric_key
from electrochem_v6.core.processing_result_models import MetricValue, ProcessingResult, SourceFileRef
from electrochem_v6.core.processing_scan import scan_process_inputs
from electrochem_v6.core.utils import as_bool, as_float, as_int


class EcsaDirectModule:
    """Run grouped ECSA CV files directly and return normalized results."""

    spec = get_module_spec("ECSA")

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
    def _output_dir_for(context: ModuleRunContext, folder_path: str) -> str:
        params = dict(context.params or {})
        root = os.path.abspath(context.folder_path)
        folder = os.path.abspath(folder_path)
        output_root = str(context.output_dir or params.get("output_dir") or "").strip()
        if not output_root:
            return folder
        output_root = os.path.abspath(output_root)
        try:
            rel = os.path.relpath(folder, root)
        except ValueError:
            rel = "."
        target = output_root if rel in (".", "") else os.path.join(output_root, rel)
        os.makedirs(target, exist_ok=True)
        return target

    @staticmethod
    def _group_by_folder(files: Sequence[str]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for raw_file in files:
            file_path = os.path.abspath(str(raw_file))
            folder = os.path.dirname(file_path)
            filename = os.path.basename(file_path)
            if filename:
                grouped.setdefault(folder, []).append(filename)
        return grouped

    def _ecsa_params(self, context: ModuleRunContext, folder_path: str) -> dict[str, Any]:
        params = merge_parameter_defaults(self.spec.key, context.params)
        params["match"] = params.get("ecsa_match", params.get("match", "prefix"))
        params["match_prefix"] = params.get("ecsa_prefix", params.get("match_prefix", "ECSA"))
        params["output_dir"] = self._output_dir_for(context, folder_path)
        if context.project_id and not params.get("project_id"):
            params["project_id"] = context.project_id
        if context.run_id and not params.get("run_id"):
            params["run_id"] = context.run_id
        params["ev"] = params.get("ecsa_ev", params.get("ev", 0.10))
        params["last_n"] = params.get("ecsa_last_n", params.get("last_n", 1))
        params["avg_last_n"] = as_bool(params.get("ecsa_avg_last_n", params.get("avg_last_n", False)), False)
        params["cs_value"] = params.get("ecsa_cs_value", params.get("cs_value", 40.0))
        params["cs_unit"] = params.get("ecsa_cs_unit", params.get("cs_unit", "uF/cm2"))
        params.setdefault("xlabel", params.get("ecsa_xlabel", "Scan rate v (V/s)"))
        params.setdefault("ylabel", params.get("ecsa_ylabel", "Delta J (mA/cm2)"))
        params.setdefault("title", params.get("ecsa_title", "ECSA of {sample} @ Ev={Ev:.3f} V"))
        params.setdefault("line_width", as_float(params.get("ecsa_line_width", params.get("line_width", 2.0)), 2.0))
        params.setdefault("use_abs_delta", as_bool(params.get("ecsa_use_abs_delta", params.get("use_abs_delta", True)), True))
        return params

    @staticmethod
    def _common_params(context: ModuleRunContext) -> dict[str, Any]:
        params = merge_parameter_defaults("ECSA", context.params)
        return {
            "area": params.get("area", 1.0),
            "font": params.get("font_family") or params.get("font") or "",
            "fontsize": as_int(params.get("font_size", params.get("fontsize", 12)), 12),
        }

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

    def _processing_result_from_ecsa(
        self,
        result: Mapping[str, Any],
        *,
        folder_path: str,
        input_files: Sequence[str],
        context: ModuleRunContext,
    ) -> ProcessingResult:
        sample_name = str(result.get("sample") or os.path.basename(folder_path) or "unknown_sample")
        metrics: list[MetricValue] = []
        used_keys: set[str] = set()
        for key, value in result.items():
            if key in {"sample", "png", "source_profile", "assumptions"} or self._is_missing(value):
                continue
            base_key = make_metric_key(str(key))
            metric_key = base_key
            suffix = 2
            while metric_key in used_keys:
                metric_key = f"{base_key}_{suffix}"
                suffix += 1
            used_keys.add(metric_key)
            resolved = resolve_metric(self.spec.key, str(key), fallback_key=metric_key)
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

        png_path = str(result.get("png") or "").strip()
        return ProcessingResult(
            data_type=self.spec.key,
            sample_name=sample_name,
            source=SourceFileRef(
                sample_name=sample_name,
                file_name=None,
                path=os.path.abspath(folder_path),
                data_type=self.spec.key,
            ),
            metrics=tuple(metrics),
            artifacts=(png_path,) if png_path else (),
            project_id=context.project_id,
            run_id=context.run_id,
            metadata={
                "module": "direct_ecsa",
                "input_files": len(input_files),
                "source_files": [str(item) for item in input_files],
                "source_profile": dict(result.get("source_profile") or {}),
                "ecsa_assumptions": dict(result.get("assumptions") or {}),
            },
        )

    @staticmethod
    def _quality_report(result: Mapping[str, Any], *, folder_path: str, input_files: Sequence[str]) -> dict[str, Any]:
        sample_name = str(result.get("sample") or os.path.basename(folder_path) or "unknown_sample")
        r2 = result.get("R2")
        warnings: list[str] = []
        if isinstance(r2, (int, float)) and r2 < 0.95:
            warnings.append("ECSA fit R2 is below 0.95; inspect scan-rate series and Ev setting.")
        raw_assumptions = result.get("assumptions")
        assumptions: Mapping[str, Any] = raw_assumptions if isinstance(raw_assumptions, Mapping) else {}
        if assumptions.get("specific_capacitance_input") == 40.0 and str(
            assumptions.get("specific_capacitance_unit") or ""
        ).lower() in {"uf/cm2", "µf/cm²", "μf/cm²"}:
            warnings.append(
                "ECSA uses the common 40 uF/cm2 specific-capacitance value; confirm that it is appropriate for the material and electrolyte."
            )
        return {
            "filename": f"{sample_name}/ECSA",
            "data_type": "ECSA",
            "is_valid": True,
            "quality_level": "warning" if warnings else "normal",
            "issues": [],
            "warnings": warnings,
            "recommendation": "inspect_fit" if warnings else "none",
            "stats": {
                "input_files": len(input_files),
                "fit_points": result.get("N_points"),
                "r2": r2,
                "ecsa_cm2": result.get("ECSA_cm2"),
                "rf": result.get("RF"),
                "specific_capacitance_mf_cm2": assumptions.get("specific_capacitance_normalized_mf_cm2"),
            },
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
        grouped = self._group_by_folder(files)
        common = self._common_params(context)

        for folder_path, filenames in progress_work_items(context.params, sorted(grouped.items())):
            try:
                payload = process_ecsa_for_subfolder(
                    folder_path,
                    sorted(filenames),
                    self._ecsa_params(context, folder_path),
                    common,
                )
            except Exception as exc:
                skipped += 1
                messages.append(f"ECSA skipped {os.path.basename(folder_path)}: {exc}")
                quality_reports.append({
                    "filename": f"{os.path.basename(folder_path)}/ECSA", "data_type": "ECSA",
                    "is_valid": False, "quality_level": "error", "issues": [str(exc)],
                    "warnings": [], "recommendation": "inspect_fit", "stats": {"input_files": len(filenames)},
                })
                continue
            if not isinstance(payload, Mapping):
                skipped += 1
                messages.append(f"ECSA produced no valid fit: {os.path.basename(folder_path)}")
                continue

            result = self._processing_result_from_ecsa(
                payload,
                folder_path=folder_path,
                input_files=filenames,
                context=context,
            )
            results.append(result)
            for artifact in result.artifacts:
                if artifact and artifact not in artifacts:
                    artifacts.append(artifact)
            quality_reports.append(self._quality_report(payload, folder_path=folder_path, input_files=filenames))

        return ModuleRunResult(
            data_type=self.spec.key,
            results=tuple(results),
            artifacts=tuple(artifacts),
            quality_reports=tuple(quality_reports),
            messages=tuple(messages),
            metadata={
                "module": "direct_ecsa",
                "input_files": len(files),
                "input_groups": len(grouped),
                "processed_samples": len(results),
                "skipped_groups": skipped,
            },
        )


__all__ = ["EcsaDirectModule"]
