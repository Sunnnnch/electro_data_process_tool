"""Pure calculations for coupled electrochemical metrics."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Mapping, Sequence

from electrochem_v6.core.processing_coupled_models import (
    CoupledCalculationError,
    CoupledProductResult,
    ProductQuantification,
)
from electrochem_v6.core.processing_formula import formulas_for_run
from electrochem_v6.core.processing_metric_registry import resolve_metric
from electrochem_v6.core.processing_result_models import MetricValue, ProcessingResult, SourceFileRef

FARADAY_CONSTANT_C_PER_MOL = 96485.33212
COUPLED_METRIC_FORMULA_KEYS = {
    "faradaic_efficiency_pct": "coupled.faradaic_efficiency",
    "product_selectivity_pct": "coupled.product_selectivity",
    "fe_selectivity_pct": "coupled.fe_selectivity",
}


def _positive_float(value: float, field_name: str) -> float:
    try:
        numeric = float(value)
    except Exception as exc:
        raise CoupledCalculationError(f"{field_name} must be numeric") from exc
    if numeric <= 0:
        raise CoupledCalculationError(f"{field_name} must be greater than 0")
    return numeric


def _non_negative_float(value: float, field_name: str) -> float:
    try:
        numeric = float(value)
    except Exception as exc:
        raise CoupledCalculationError(f"{field_name} must be numeric") from exc
    if numeric < 0:
        raise CoupledCalculationError(f"{field_name} must be greater than or equal to 0")
    return numeric


def calculate_faradaic_efficiency_pct(
    *,
    product_moles: float,
    electron_count: float,
    charge_coulomb: float,
    faraday_constant: float = FARADAY_CONSTANT_C_PER_MOL,
) -> float:
    """Calculate Faradaic efficiency percentage for one product."""
    moles = _non_negative_float(product_moles, "product_moles")
    electrons = _positive_float(electron_count, "electron_count")
    charge = _positive_float(charge_coulomb, "charge_coulomb")
    faraday = _positive_float(faraday_constant, "faraday_constant")
    return (electrons * faraday * moles / charge) * 100.0


def calculate_selectivity_pct(amounts_by_product: Mapping[str, float]) -> dict[str, float]:
    """Calculate mole-based selectivity percentage for products."""
    amounts = {
        str(product): _non_negative_float(amount, f"amount[{product}]")
        for product, amount in amounts_by_product.items()
    }
    total = sum(amounts.values())
    if total <= 0:
        raise CoupledCalculationError("selectivity total must be greater than 0")
    return {product: amount / total * 100.0 for product, amount in amounts.items()}


def calculate_fe_selectivity_pct(fe_by_product: Mapping[str, float]) -> dict[str, float]:
    """Calculate FE-share selectivity from product Faradaic efficiencies."""
    efficiencies = {
        str(product): _non_negative_float(fe, f"faradaic_efficiency[{product}]")
        for product, fe in fe_by_product.items()
    }
    total = sum(efficiencies.values())
    if total <= 0:
        raise CoupledCalculationError("FE selectivity total must be greater than 0")
    return {product: fe / total * 100.0 for product, fe in efficiencies.items()}


def calculate_coupled_product_results(
    inputs: Sequence[ProductQuantification],
) -> list[CoupledProductResult]:
    """Calculate FE and selectivity for quantified products grouped by sample."""
    by_sample: dict[str, list[ProductQuantification]] = defaultdict(list)
    for item in inputs:
        sample_name = str(item.sample_name).strip()
        product_name = str(item.product_name).strip()
        if not sample_name:
            raise CoupledCalculationError("sample_name is required")
        if not product_name:
            raise CoupledCalculationError("product_name is required")
        _non_negative_float(item.product_moles, "product_moles")
        _positive_float(item.electron_count, "electron_count")
        _positive_float(item.charge_coulomb, "charge_coulomb")
        by_sample[sample_name].append(item)

    results: list[CoupledProductResult] = []
    for sample_name, sample_items in by_sample.items():
        reference_charge = float(sample_items[0].charge_coulomb)
        inconsistent_charges = [
            float(item.charge_coulomb)
            for item in sample_items[1:]
            if not math.isclose(
                float(item.charge_coulomb),
                reference_charge,
                rel_tol=1e-6,
                abs_tol=1e-9,
            )
        ]
        if inconsistent_charges:
            values = ", ".join(f"{value:.12g}" for value in [reference_charge, *inconsistent_charges])
            raise CoupledCalculationError(
                f"inconsistent charge_coulomb for sample {sample_name}: {values}"
            )
        seen_products: set[str] = set()
        for item in sample_items:
            if item.product_name in seen_products:
                raise CoupledCalculationError(
                    f"duplicate product for sample {sample_name}: {item.product_name}"
                )
            seen_products.add(item.product_name)
        moles_by_product = {
            item.product_name: float(item.product_moles)
            for item in sample_items
        }
        selectivity_by_product = calculate_selectivity_pct(moles_by_product)
        fe_by_product = {
            item.product_name: calculate_faradaic_efficiency_pct(
                product_moles=item.product_moles,
                electron_count=item.electron_count,
                charge_coulomb=item.charge_coulomb,
            )
            for item in sample_items
        }
        fe_selectivity_by_product = calculate_fe_selectivity_pct(fe_by_product)
        for item in sample_items:
            results.append(
                CoupledProductResult(
                    sample_name=sample_name,
                    product_name=item.product_name,
                    product_moles=float(item.product_moles),
                    electron_count=float(item.electron_count),
                    charge_coulomb=float(item.charge_coulomb),
                    faradaic_efficiency_pct=fe_by_product[item.product_name],
                    product_selectivity_pct=selectivity_by_product[item.product_name],
                    fe_selectivity_pct=fe_selectivity_by_product[item.product_name],
                    metadata=item.metadata,
                )
            )
    return results


def _metric_from_registry(label: str, value: float, extra_metadata: Mapping[str, object]) -> MetricValue:
    resolved = resolve_metric("COUPLED", label)
    metadata = dict(resolved.metadata)
    metadata.update(extra_metadata)
    formula_key = COUPLED_METRIC_FORMULA_KEYS.get(label)
    if formula_key:
        metadata["formula_key"] = formula_key
    return MetricValue(
        key=resolved.key,
        label=resolved.label,
        value=value,
        unit=resolved.unit,
        metadata=metadata,
    )


def coupled_results_to_processing_results(
    results: Iterable[CoupledProductResult],
    *,
    project_id: str | None = None,
    run_id: str | None = None,
    formula_keys: Sequence[str] | None = None,
) -> list[ProcessingResult]:
    """Convert coupled calculation results into normalized ProcessingResult items."""
    output: list[ProcessingResult] = []
    resolved_formula_keys = list(formula_keys) if formula_keys is not None else [
        item["key"] for item in formulas_for_run(["COUPLED"], {})
    ]
    for item in results:
        product_metadata = {"product_name": item.product_name}
        charge_metadata = dict(product_metadata)
        if item.metadata.get("charge_source") == "current_time":
            charge_metadata["formula_key"] = "coupled.charge_from_current_time"
        metrics = [
            _metric_from_registry("product_moles", item.product_moles, product_metadata),
            _metric_from_registry("electron_count", item.electron_count, product_metadata),
            _metric_from_registry("charge_coulomb", item.charge_coulomb, charge_metadata),
            _metric_from_registry(
                "faradaic_efficiency_pct",
                item.faradaic_efficiency_pct,
                product_metadata,
            ),
        ]
        if item.product_selectivity_pct is not None:
            metrics.append(
                _metric_from_registry(
                    "product_selectivity_pct",
                    item.product_selectivity_pct,
                    product_metadata,
                )
            )
        if item.fe_selectivity_pct is not None:
            metrics.append(
                _metric_from_registry(
                    "fe_selectivity_pct",
                    item.fe_selectivity_pct,
                    product_metadata,
                )
            )
        output.append(
            ProcessingResult(
                data_type="COUPLED",
                sample_name=item.sample_name,
                source=SourceFileRef(
                    sample_name=item.sample_name,
                    file_name=item.product_name,
                    data_type="COUPLED",
                ),
                metrics=tuple(metrics),
                project_id=project_id,
                run_id=run_id,
                metadata={
                    "product_name": item.product_name,
                    "formula_keys": resolved_formula_keys,
                    **dict(item.metadata),
                },
            )
        )
    return output


__all__ = [
    "FARADAY_CONSTANT_C_PER_MOL",
    "calculate_coupled_product_results",
    "calculate_faradaic_efficiency_pct",
    "calculate_fe_selectivity_pct",
    "calculate_selectivity_pct",
    "coupled_results_to_processing_results",
]
