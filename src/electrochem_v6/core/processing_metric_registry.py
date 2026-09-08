"""Metric naming registry for normalized processing results."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_TOKEN_RE = re.compile(r"[^0-9A-Za-z]+")
_NUMBER_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"


@dataclass(frozen=True)
class MetricDefinition:
    """Stable description of one metric family."""

    key: str
    data_type: str
    label: str
    unit: str | None
    category: str
    description: str
    aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "data_type": self.data_type,
            "label": self.label,
            "unit": self.unit,
            "category": self.category,
            "description": self.description,
            "aliases": list(self.aliases),
        }


@dataclass(frozen=True)
class ResolvedMetric:
    """Metric definition resolved for one concrete output column."""

    key: str
    label: str
    unit: str | None = None
    method: str | None = None
    definition_key: str | None = None
    category: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


METRIC_DEFINITIONS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        key="lsv.potential_at_current",
        data_type="LSV",
        label="Potential at target current density",
        unit="V",
        category="potential",
        description="Interpolated electrode potential at a selected current density.",
        aliases=("Potential@",),
    ),
    MetricDefinition(
        key="lsv.solution_resistance",
        data_type="LSV",
        label="Solution resistance",
        unit="ohm",
        category="resistance",
        description="Solution resistance used for iR compensation.",
        aliases=("R_solution",),
    ),
    MetricDefinition(
        key="lsv.overpotential_at_current",
        data_type="LSV",
        label="Overpotential at target current density",
        unit="mV",
        category="potential",
        description="Overpotential relative to the configured equilibrium potential.",
        aliases=("Overpotential@",),
    ),
    MetricDefinition(
        key="lsv.onset_potential",
        data_type="LSV",
        label="Onset potential",
        unit="V",
        category="potential",
        description="Interpolated onset potential at the configured onset current density.",
        aliases=("OnsetPotential@",),
    ),
    MetricDefinition(
        key="lsv.onset_overpotential",
        data_type="LSV",
        label="Onset overpotential",
        unit="mV",
        category="potential",
        description="Onset overpotential relative to the configured equilibrium potential.",
        aliases=("OnsetOverpotential",),
    ),
    MetricDefinition(
        key="lsv.half_wave_potential",
        data_type="LSV",
        label="Half-wave potential",
        unit="V",
        category="potential",
        description="Potential at the configured half-wave current.",
        aliases=("HalfWavePotential",),
    ),
    MetricDefinition(
        key="lsv.tafel_slope",
        data_type="LSV",
        label="Tafel slope",
        unit="mV/dec",
        category="kinetics",
        description="Tafel slope from the configured current-density window.",
        aliases=("TafelSlope",),
    ),
    MetricDefinition(
        key="cv.point_count",
        data_type="CV",
        label="CV point count",
        unit="count",
        category="input",
        description="Number of potential-current points parsed from the CV file.",
        aliases=("data_points",),
    ),
    MetricDefinition(
        key="cv.potential_min",
        data_type="CV",
        label="Minimum potential",
        unit="V",
        category="input",
        description="Minimum potential in the parsed CV curve.",
        aliases=("potential_min_v",),
    ),
    MetricDefinition(
        key="cv.potential_max",
        data_type="CV",
        label="Maximum potential",
        unit="V",
        category="input",
        description="Maximum potential in the parsed CV curve.",
        aliases=("potential_max_v",),
    ),
    MetricDefinition(
        key="cv.current_min",
        data_type="CV",
        label="Minimum current",
        unit="mA",
        category="input",
        description="Minimum current in the parsed CV curve.",
        aliases=("current_min_mA", "current_min_ma"),
    ),
    MetricDefinition(
        key="cv.current_max",
        data_type="CV",
        label="Maximum current",
        unit="mA",
        category="input",
        description="Maximum current in the parsed CV curve.",
        aliases=("current_max_mA", "current_max_ma"),
    ),
    MetricDefinition(
        key="cv.charge",
        data_type="CV",
        label="Integrated absolute charge",
        unit="mC",
        category="charge",
        description="Integral of absolute current over elapsed time reconstructed from potential and scan rate.",
        aliases=("charge_mC", "charge_mc"),
    ),
    MetricDefinition(
        key="cv.delta_ep",
        data_type="CV",
        label="Peak separation",
        unit="mV",
        category="peak",
        description="Potential separation between the selected anodic and cathodic peaks.",
        aliases=("delta_ep_mV", "delta_ep_mv"),
    ),
    MetricDefinition(
        key="cv.peak_count",
        data_type="CV",
        label="Detected peak count",
        unit="count",
        category="peak",
        description="Number of CV peaks accepted by the configured peak detector.",
        aliases=("peak_count",),
    ),
    MetricDefinition(
        key="ecsa.evaluation_potential",
        data_type="ECSA",
        label="Evaluation potential",
        unit="V",
        category="input",
        description="Potential used to extract current differences from CV curves.",
        aliases=("Ev",),
    ),
    MetricDefinition(
        key="ecsa.used_scan_count",
        data_type="ECSA",
        label="Used scan count",
        unit="count",
        category="input",
        description="Number of scans used from each CV file.",
        aliases=("n_used",),
    ),
    MetricDefinition(
        key="ecsa.fit_point_count",
        data_type="ECSA",
        label="Fit point count",
        unit="count",
        category="fit",
        description="Number of scan-rate points used for the ECSA linear fit.",
        aliases=("N_points",),
    ),
    MetricDefinition(
        key="ecsa.fit_slope",
        data_type="ECSA",
        label="ECSA fit slope",
        unit="mF/cm2",
        category="fit",
        description="Slope of delta current density versus scan rate.",
        aliases=("slope_mFcm2",),
    ),
    MetricDefinition(
        key="ecsa.fit_intercept",
        data_type="ECSA",
        label="ECSA fit intercept",
        unit="mA/cm2",
        category="fit",
        description="Intercept of the ECSA linear fit.",
        aliases=("intercept",),
    ),
    MetricDefinition(
        key="ecsa.fit_r2",
        data_type="ECSA",
        label="ECSA fit R2",
        unit=None,
        category="fit",
        description="Coefficient of determination for the ECSA linear fit.",
        aliases=("R2",),
    ),
    MetricDefinition(
        key="ecsa.double_layer_capacitance",
        data_type="ECSA",
        label="Double-layer capacitance",
        unit="mF/cm2",
        category="capacitance",
        description="Calculated double-layer capacitance normalized by geometric area.",
        aliases=("Cdl_mFcm2",),
    ),
    MetricDefinition(
        key="ecsa.specific_capacitance_input",
        data_type="ECSA",
        label="Specific capacitance input",
        unit=None,
        category="input",
        description="User-provided specific capacitance value before unit normalization.",
        aliases=("Cs_input",),
    ),
    MetricDefinition(
        key="ecsa.specific_capacitance_normalized",
        data_type="ECSA",
        label="Specific capacitance",
        unit="mF/cm2",
        category="input",
        description="Specific capacitance normalized to mF/cm2.",
        aliases=("Cs_mFcm2",),
    ),
    MetricDefinition(
        key="ecsa.surface_area",
        data_type="ECSA",
        label="Electrochemical surface area",
        unit="cm2",
        category="surface_area",
        description="Electrochemical surface area calculated from Cdl and Cs.",
        aliases=("ECSA_cm2",),
    ),
    MetricDefinition(
        key="ecsa.roughness_factor",
        data_type="ECSA",
        label="Roughness factor",
        unit=None,
        category="surface_area",
        description="Roughness factor calculated from ECSA and geometric area.",
        aliases=("RF",),
    ),
    MetricDefinition(
        key="eis.point_count",
        data_type="EIS",
        label="EIS point count",
        unit="count",
        category="input",
        description="Number of impedance points parsed from the EIS file.",
        aliases=("data_points",),
    ),
    MetricDefinition(
        key="eis.frequency_min",
        data_type="EIS",
        label="Minimum frequency",
        unit="Hz",
        category="input",
        description="Minimum frequency in the EIS file.",
        aliases=("frequency_min_hz",),
    ),
    MetricDefinition(
        key="eis.frequency_max",
        data_type="EIS",
        label="Maximum frequency",
        unit="Hz",
        category="input",
        description="Maximum frequency in the EIS file.",
        aliases=("frequency_max_hz",),
    ),
    MetricDefinition(
        key="eis.solution_resistance",
        data_type="EIS",
        label="Solution resistance",
        unit="ohm",
        category="fit",
        description="Solution resistance from the accepted Randles fit.",
        aliases=("Rs", "rs_ohm"),
    ),
    MetricDefinition(
        key="eis.charge_transfer_resistance",
        data_type="EIS",
        label="Charge-transfer resistance",
        unit="ohm",
        category="fit",
        description="Charge-transfer resistance from the accepted Randles fit.",
        aliases=("Rct", "rct_ohm"),
    ),
    MetricDefinition(
        key="eis.double_layer_capacitance",
        data_type="EIS",
        label="Double-layer capacitance",
        unit="F",
        category="fit",
        description="Double-layer capacitance from the accepted Randles fit.",
        aliases=("Cdl", "cdl_f"),
    ),
    MetricDefinition(
        key="eis.randles_r2",
        data_type="EIS",
        label="Circuit fit R2",
        unit=None,
        category="fit_quality",
        description="Complex coefficient of determination; a numerical criterion, not proof of physical validity.",
        aliases=("randles_r2",),
    ),
    *(MetricDefinition(key=f"eis.{key}", data_type="EIS", label=label, unit=unit,
                       category="fit", description=description, aliases=aliases)
      for key, label, unit, description, aliases in (
        ("cpe_q", "CPE Q", "S*s^n", "Q changes dimensions with n; it is not generally a capacitance.", ("CPE Q", "CPE_Q", "cpe_q")),
        ("cpe_n", "CPE exponent", None, "Constant-phase exponent.", ("CPE n", "CPE_n", "cpe_n")),
        ("warburg_sigma", "Warburg coefficient", "Ohm*s^-0.5", "Semi-infinite Warburg coefficient for sigma*(1-j)/sqrt(omega).", ("sigma", "Warburg sigma", "warburg_sigma")),
        ("r1", "Fast-branch resistance R1", "ohm", "Branch 1 has the shorter fitted time constant; mechanism is not inferred.", ("R1", "r1_ohm")),
        ("r2", "Slow-branch resistance R2", "ohm", "Branch 2 has the longer fitted time constant; mechanism is not inferred.", ("R2", "r2_ohm")),
        ("c1", "Fast-branch capacitance C1", "F", "Ideal capacitance of branch 1.", ("C1", "c1_f")),
        ("c2", "Slow-branch capacitance C2", "F", "Ideal capacitance of branch 2.", ("C2", "c2_f")),
        ("q1", "Fast-branch CPE Q1", "S*s^n1", "CPE Q of branch 1; dimensions depend on n1.", ("Q1",)),
        ("q2", "Slow-branch CPE Q2", "S*s^n2", "CPE Q of branch 2; dimensions depend on n2.", ("Q2",)),
        ("n1", "Fast-branch exponent n1", None, "CPE exponent of branch 1.", ("n1",)),
        ("n2", "Slow-branch exponent n2", None, "CPE exponent of branch 2.", ("n2",)),
        ("fit_rmse", "Circuit fit RMSE", "ohm", "Root mean squared complex residual in Ohms.", ("fit_rmse", "fit_rmse_ohm")),
      )),
    MetricDefinition(
        key="coupled.product_moles",
        data_type="COUPLED",
        label="Product amount",
        unit="mol",
        category="product",
        description="Amount of quantified product used for coupled electrochemical calculations.",
        aliases=("product_moles",),
    ),
    MetricDefinition(
        key="coupled.electron_count",
        data_type="COUPLED",
        label="Electron count",
        unit="count",
        category="reaction",
        description="Number of transferred electrons per molecule of product.",
        aliases=("electron_count",),
    ),
    MetricDefinition(
        key="coupled.charge_coulomb",
        data_type="COUPLED",
        label="Charge",
        unit="C",
        category="charge",
        description="Total charge passed during the product quantification window.",
        aliases=("charge_coulomb",),
    ),
    MetricDefinition(
        key="coupled.faradaic_efficiency",
        data_type="COUPLED",
        label="Faradaic efficiency",
        unit="%",
        category="efficiency",
        description="Faradaic efficiency calculated from product amount, electron count, and charge.",
        aliases=("faradaic_efficiency_pct",),
    ),
    MetricDefinition(
        key="coupled.product_selectivity",
        data_type="COUPLED",
        label="Product selectivity",
        unit="%",
        category="selectivity",
        description="Mole-based product selectivity among quantified products for one sample.",
        aliases=("product_selectivity_pct",),
    ),
    MetricDefinition(
        key="coupled.fe_selectivity",
        data_type="COUPLED",
        label="FE selectivity",
        unit="%",
        category="selectivity",
        description="Faradaic-efficiency share among quantified products for one sample.",
        aliases=("fe_selectivity_pct",),
    ),
)

_DEFINITIONS_BY_KEY = {item.key: item for item in METRIC_DEFINITIONS}
_DEFINITIONS_BY_ALIAS = {
    (item.data_type.upper(), alias): item
    for item in METRIC_DEFINITIONS
    for alias in item.aliases
}


def normalize_metric_key(label: str) -> str:
    """Convert an output label into the exported metric_key format."""
    text = str(label).strip()
    replacements = {
        "²": "2",
        "³": "3",
        "μ": "u",
        "µ": "u",
        "Ω": "ohm",
        "Ω": "ohm",
        # Legacy mojibake for squared units from old result headers: cm虏 -> cm2.
        "虏": "2",
        "@": "_at_",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = _TOKEN_RE.sub("_", text).strip("_").lower()
    return text or "value"


def get_metric_definition(key: str) -> MetricDefinition | None:
    return _DEFINITIONS_BY_KEY.get(str(key))


def list_metric_definitions(data_type: str | None = None) -> list[MetricDefinition]:
    if data_type is None:
        return list(METRIC_DEFINITIONS)
    normalized = str(data_type).upper()
    return [item for item in METRIC_DEFINITIONS if item.data_type.upper() == normalized]


def _metadata_from_definition(definition: MetricDefinition, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "definition_key": definition.key,
        "category": definition.category,
    }
    if extra:
        metadata.update(extra)
    return metadata


def _resolve_alias(data_type: str, column_label: str) -> MetricDefinition | None:
    normalized_type = str(data_type).upper()
    for (registered_type, alias), definition in _DEFINITIONS_BY_ALIAS.items():
        if registered_type == normalized_type and str(column_label).startswith(alias):
            return definition
    return None


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _resolve_lsv_metric(column_label: str, fallback_key: str) -> ResolvedMetric | None:
    text = str(column_label).strip()

    # Accept both current cm2/cm² headers and legacy mojibake cm虏 headers.
    potential_match = re.match(
        rf"^Potential@(?P<target>{_NUMBER_RE})mA/cm[2²虏](?:\((?P<method>Original|IR_compensated)\))?$",
        text,
    )
    if potential_match:
        definition = get_metric_definition("lsv.potential_at_current")
        if definition:
            method = potential_match.group("method")
            return ResolvedMetric(
                key=fallback_key,
                label=text,
                unit=definition.unit,
                method=method.replace("_", " ") if method else None,
                definition_key=definition.key,
                category=definition.category,
                metadata=_metadata_from_definition(
                    definition,
                    {"target_current_mA_cm2": _parse_float(potential_match.group("target"))},
                ),
            )

    overpotential_match = re.match(
        rf"^Overpotential@(?P<target>{_NUMBER_RE})mA/cm[2²虏]\(mV\)@Eq=(?P<eq>{_NUMBER_RE})V$",
        text,
    )
    if overpotential_match:
        definition = get_metric_definition("lsv.overpotential_at_current")
        if definition:
            return ResolvedMetric(
                key=fallback_key,
                label=text,
                unit=definition.unit,
                definition_key=definition.key,
                category=definition.category,
                metadata=_metadata_from_definition(
                    definition,
                    {
                        "target_current_mA_cm2": _parse_float(overpotential_match.group("target")),
                        "equilibrium_potential_V": _parse_float(overpotential_match.group("eq")),
                    },
                ),
            )

    onset_match = re.match(rf"^OnsetPotential@(?P<target>{_NUMBER_RE})mA/cm[2²虏]\(V\)$", text)
    if onset_match:
        definition = get_metric_definition("lsv.onset_potential")
        if definition:
            return ResolvedMetric(
                key=fallback_key,
                label=text,
                unit=definition.unit,
                definition_key=definition.key,
                category=definition.category,
                metadata=_metadata_from_definition(
                    definition,
                    {"onset_current_mA_cm2": _parse_float(onset_match.group("target"))},
                ),
            )

    onset_overpotential_match = re.match(rf"^OnsetOverpotential\(mV\)@Eq=(?P<eq>{_NUMBER_RE})V$", text)
    if onset_overpotential_match:
        definition = get_metric_definition("lsv.onset_overpotential")
        if definition:
            return ResolvedMetric(
                key=fallback_key,
                label=text,
                unit=definition.unit,
                definition_key=definition.key,
                category=definition.category,
                metadata=_metadata_from_definition(
                    definition,
                    {"equilibrium_potential_V": _parse_float(onset_overpotential_match.group("eq"))},
                ),
            )

    definition = _resolve_alias("LSV", text)
    if definition:
        return ResolvedMetric(
            key=fallback_key,
            label=text,
            unit=definition.unit,
            definition_key=definition.key,
            category=definition.category,
            metadata=_metadata_from_definition(definition),
        )
    return None


def resolve_metric(data_type: str, column_label: str, fallback_key: str | None = None) -> ResolvedMetric:
    """Resolve unit, category, and metadata for one result-table column."""
    resolved_key = fallback_key or normalize_metric_key(column_label)
    normalized_type = str(data_type).upper()
    if normalized_type == "LSV":
        lsv = _resolve_lsv_metric(column_label, resolved_key)
        if lsv:
            return lsv

    definition = _resolve_alias(normalized_type, str(column_label))
    if definition:
        return ResolvedMetric(
            key=resolved_key,
            label=str(column_label),
            unit=definition.unit,
            definition_key=definition.key,
            category=definition.category,
            metadata=_metadata_from_definition(definition),
        )

    return ResolvedMetric(key=resolved_key, label=str(column_label))


__all__ = [
    "METRIC_DEFINITIONS",
    "MetricDefinition",
    "ResolvedMetric",
    "get_metric_definition",
    "list_metric_definitions",
    "normalize_metric_key",
    "resolve_metric",
]
