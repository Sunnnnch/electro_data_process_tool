"""Data models for coupled electrochemical calculations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ProductQuantification:
    """Quantified product amount linked to one electrochemical sample."""

    sample_name: str
    product_name: str
    product_moles: float
    electron_count: float
    charge_coulomb: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CoupledProductResult:
    """Calculated FE and selectivity for one sample/product pair."""

    sample_name: str
    product_name: str
    product_moles: float
    electron_count: float
    charge_coulomb: float
    faradaic_efficiency_pct: float
    product_selectivity_pct: float | None = None
    fe_selectivity_pct: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_name": self.sample_name,
            "product_name": self.product_name,
            "product_moles": self.product_moles,
            "electron_count": self.electron_count,
            "charge_coulomb": self.charge_coulomb,
            "faradaic_efficiency_pct": self.faradaic_efficiency_pct,
            "product_selectivity_pct": self.product_selectivity_pct,
            "fe_selectivity_pct": self.fe_selectivity_pct,
            "metadata": dict(self.metadata),
        }


class CoupledCalculationError(ValueError):
    """Raised when coupled calculation inputs are physically invalid."""


__all__ = ["CoupledCalculationError", "CoupledProductResult", "ProductQuantification"]
