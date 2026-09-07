"""Runtime module adapter for coupled FE/selectivity calculations."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from electrochem_v6.core.job_control import check_cancelled, report_progress
from electrochem_v6.core.processing_coupled import (
    normalize_coupled_input_mode,
    normalize_coupled_peak_method_source,
    process_coupled_input,
)
from electrochem_v6.core.processing_coupled_io import read_product_quantification_table
from electrochem_v6.core.processing_coupled_models import CoupledCalculationError
from electrochem_v6.core.processing_fe_peak import inspect_fe_peak_inputs
from electrochem_v6.core.processing_formula import formulas_for_run
from electrochem_v6.core.processing_module_contract import ModuleRunContext, ModuleRunResult
from electrochem_v6.core.processing_registry import (
    get_module_spec,
    merge_parameter_defaults,
)


class CoupledFEModule:
    """Direct module runner for product-table FE and selectivity calculations."""

    spec = get_module_spec("COUPLED")

    @staticmethod
    def _products_file(context: ModuleRunContext) -> str:
        params = merge_parameter_defaults("COUPLED", context.params)
        return str(params.get("coupled_products_file") or params.get("products_file") or "").strip()

    @staticmethod
    def _input_mode(context: ModuleRunContext) -> str:
        params = merge_parameter_defaults("COUPLED", context.params)
        return normalize_coupled_input_mode(params.get("coupled_input_mode"))

    @staticmethod
    def _peak_method_file(context: ModuleRunContext) -> str:
        params = merge_parameter_defaults("COUPLED", context.params)
        return str(params.get("coupled_peak_method_file") or "").strip()

    @staticmethod
    def _peak_method_payload(context: ModuleRunContext) -> Mapping[str, Any] | None:
        params = merge_parameter_defaults("COUPLED", context.params)
        payload = params.get("coupled_peak_method")
        return payload if isinstance(payload, Mapping) else None

    @classmethod
    def _peak_method_source(cls, context: ModuleRunContext) -> str:
        params = merge_parameter_defaults("COUPLED", context.params)
        return normalize_coupled_peak_method_source(
            params.get("coupled_peak_method_source"),
            method_payload=cls._peak_method_payload(context),
        )

    @staticmethod
    def _sheet_name(context: ModuleRunContext) -> str | int:
        params = merge_parameter_defaults("COUPLED", context.params)
        return params.get("coupled_products_sheet", params.get("products_sheet", 0))

    @staticmethod
    def _output_dir(context: ModuleRunContext) -> str:
        params = merge_parameter_defaults("COUPLED", context.params)
        return str(context.output_dir or params.get("output_dir") or context.folder_path).strip()

    def detect_files(self, context: ModuleRunContext) -> Sequence[str]:
        products_file = self._products_file(context)
        files = [products_file] if products_file and os.path.isfile(products_file) else []
        if self._input_mode(context) == "peak_analysis" and self._peak_method_source(context) == "file":
            method_file = self._peak_method_file(context)
            if method_file and os.path.isfile(method_file):
                files.append(method_file)
        return files

    def validate_params(self, context: ModuleRunContext) -> list[str]:
        products_file = self._products_file(context)
        errors: list[str] = []
        if not products_file:
            errors.append("coupled_products_file is required")
            return errors
        if not os.path.isfile(products_file):
            errors.append(f"coupled_products_file not found: {products_file}")
            return errors
        try:
            input_mode = self._input_mode(context)
        except ValueError as exc:
            errors.append(str(exc))
            return errors
        if input_mode == "peak_analysis":
            method_source = self._peak_method_source(context)
            method_file = self._peak_method_file(context)
            method_payload = self._peak_method_payload(context)
            if method_source == "file":
                if not method_file:
                    errors.append("coupled_peak_method_file is required for file-based peak_analysis")
                    return errors
                if not os.path.isfile(method_file):
                    errors.append(f"coupled_peak_method_file not found: {method_file}")
                    return errors
            elif method_payload is None:
                errors.append("coupled_peak_method is required for panel-based peak_analysis")
                return errors
            inspection = inspect_fe_peak_inputs(
                products_file,
                method_file if method_source == "file" else None,
                method_payload=method_payload if method_source == "panel" else None,
                sheet_name=self._sheet_name(context),
                allowed_signal_roots=(context.folder_path,),
            )
            errors.extend(str(item) for item in inspection.get("errors") or [])
            return errors
        try:
            rows = read_product_quantification_table(products_file, sheet_name=self._sheet_name(context))
        except CoupledCalculationError as exc:
            errors.append(str(exc))
        except Exception as exc:
            errors.append(f"failed to read product quantification table: {exc}")
        else:
            if not rows:
                errors.append("product quantification table has no valid rows")
        return errors

    def run(self, context: ModuleRunContext, files: Sequence[str]) -> ModuleRunResult:
        check_cancelled(context.params)
        products_file = str(files[0] if files else self._products_file(context)).strip()
        output_dir = self._output_dir(context)
        params = merge_parameter_defaults(self.spec.key, context.params)
        input_mode = self._input_mode(context)
        csv_filename = str(params.get("coupled_results_csv_filename") or "coupled_results.csv")
        result = process_coupled_input(
            products_file,
            input_mode=input_mode,
            peak_method_file=self._peak_method_file(context),
            peak_method_source=self._peak_method_source(context),
            peak_method_payload=self._peak_method_payload(context),
            output_dir=output_dir,
            csv_filename=csv_filename,
            sheet_name=self._sheet_name(context),
            params=dict(params),
            project_id=context.project_id,
            run_id=context.run_id,
            allowed_signal_roots=(context.folder_path,),
        )
        report_progress(context.params, item=products_file, advance=True)
        artifacts = tuple(
            str(result.get(key) or "")
            for key in (
                "coupled_results_csv",
                "fe_peak_diagnostics_csv",
                "fe_peak_results_json",
            )
            if str(result.get(key) or "").strip()
        )
        return ModuleRunResult(
            data_type="COUPLED",
            results=tuple(result.get("processing_results") or ()),
            artifacts=artifacts,
            quality_reports=tuple(result.get("quality_reports") or ()),
            messages=(f"COUPLED/FE {input_mode} processed {Path(products_file).name}",),
            metadata={
                "input_mode": input_mode,
                "input_rows": result.get("input_rows"),
                "rows": result.get("rows"),
                "products_file": products_file,
                "peak_method_file": self._peak_method_file(context) if input_mode == "peak_analysis" else "",
                "peak_method_source": self._peak_method_source(context) if input_mode == "peak_analysis" else "",
                "method_id": result.get("method_id"),
                "products": result.get("products"),
                "formula_keys": [item["key"] for item in formulas_for_run(["COUPLED"], params)],
            },
        )


__all__ = ["CoupledFEModule"]
