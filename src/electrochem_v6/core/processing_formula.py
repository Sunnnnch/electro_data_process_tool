"""Calculation formula metadata for reproducible processing results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from electrochem_v6.core.utils import as_bool

FORMULA_SCHEMA_VERSION = "1.3"


@dataclass(frozen=True)
class FormulaVariable:
    symbol: str
    description: str
    unit: str | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "description": self.description,
            "unit": self.unit,
            "source": self.source,
        }


@dataclass(frozen=True)
class CalculationFormula:
    key: str
    name: str
    expression: str
    data_types: tuple[str, ...]
    variables: tuple[FormulaVariable, ...] = ()
    result_unit: str | None = None
    assumptions: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "expression": self.expression,
            "data_types": list(self.data_types),
            "variables": [item.to_dict() for item in self.variables],
            "result_unit": self.result_unit,
            "assumptions": list(self.assumptions),
            "references": list(self.references),
            "metadata": dict(self.metadata),
        }


FORMULA_CATALOG: tuple[CalculationFormula, ...] = (
    CalculationFormula(
        key="lsv.current_density",
        name="LSV current-density normalization",
        expression="j_signed = s_I * I_raw / A; j = abs(j_signed) if use_abs_current else j_signed",
        data_types=("LSV",),
        variables=(
            FormulaVariable("j_signed", "Signed current density retained for iR compensation", "mA/cm2", "calculated"),
            FormulaVariable("j", "Current density used for target potentials and Tafel fitting", "mA/cm2", "calculated"),
            FormulaVariable("I_raw", "Current column value in the configured source unit", "A, mA or uA", "input data"),
            FormulaVariable("s_I", "Current conversion factor: A=1000, mA=1, uA=0.001", "mA per source current unit", "lsv_current_unit"),
            FormulaVariable("A", "Electrode area", "cm2", "area"),
            FormulaVariable("use_abs_current", "Whether analysis uses absolute current density", None, "parameter"),
        ),
        result_unit="mA/cm2",
        assumptions=(
            "The configured current unit and electrode area apply to every selected input row.",
            "Absolute-current mode changes analysis current, while iR compensation retains the signed current.",
        ),
    ),
    CalculationFormula(
        key="lsv.manual_potential_offset",
        name="LSV manual potential offset",
        expression="E = s_E * E_raw + delta_E",
        data_types=("LSV",),
        variables=(
            FormulaVariable("E", "Potential before optional iR compensation", "V", "calculated"),
            FormulaVariable("E_raw", "Potential column value in the configured source unit", "V or mV", "input data"),
            FormulaVariable("s_E", "Potential conversion factor: V=1, mV=0.001", "V per source potential unit", "lsv_potential_unit"),
            FormulaVariable("delta_E", "Constant manual potential offset", "V", "potential_offset"),
        ),
        result_unit="V",
        assumptions=("Manual mode applies this offset, including a zero offset, instead of calculating an RHE conversion.",),
    ),
    CalculationFormula(
        key="lsv.target_potential",
        name="LSV target-current potential with guarded extrapolation",
        expression="E(j*) = E1 + (j* - j1) * (E2 - E1) / (j2 - j1) in range; outside range: E(j*) = a + b*log10(max(j*/j0, 1e-12)) or c + m*j*",
        data_types=("LSV",),
        variables=(
            FormulaVariable("E(j*)", "Potential at the requested current density", "V", "calculated"),
            FormulaVariable("j*", "Requested current density", "mA/cm2", "lsv_target_current"),
            FormulaVariable("j1,j2", "Current densities bracketing the target after sorting", "mA/cm2", "normalized input data"),
            FormulaVariable("E1,E2", "Potentials at the bracketing current densities", "V", "normalized or iR-compensated input data"),
            FormulaVariable("j0", "Reference current density for a dimensionless logarithm", "1 mA/cm2", "constant"),
            FormulaVariable("a,c", "Local least-squares intercepts for extrapolation", "V", "fit"),
            FormulaVariable("b", "Local logarithmic extrapolation slope", "V/dec", "fit"),
            FormulaVariable("m", "Local linear extrapolation slope", "V/(mA/cm2)", "fit"),
        ),
        result_unit="V",
        assumptions=(
            "Finite potential-current pairs are sorted by current; in-range targets use numpy.interp. At least two finite pairs and a positive maximum current are required.",
            "Out-of-range targets use edge points: j >= max(1, 0.7*j_max) above the range, or j <= 0.3*j_min below it; fewer than three selected points fall back to the nearest three available edge points.",
            "Extrapolation uses a logarithmic least-squares fit only with at least three positive selected currents spanning a ratio of at least three; otherwise it uses a linear fit.",
            "A target above twice the maximum current produces no estimate. Extrapolation also requires max(j*, j_max) / max(1e-12, min(j_selected_max, j*)) <= 2, with current densities expressed in mA/cm2. Accepted extrapolations are estimates outside the measured range.",
            "The logarithmic extrapolation branch is independent of the optional Tafel-slope setting. These are conditional calculation rules; not every branch is used by every result.",
        ),
    ),
    CalculationFormula(
        key="lsv.tafel_fit",
        name="LSV Tafel slope",
        expression="x = log10(max(j/j0, 1e-12)); E = a + b*x; TafelSlope = 1000*b",
        data_types=("LSV",),
        variables=(
            FormulaVariable("j", "Positive analysis current density inside the configured Tafel range", "mA/cm2", "normalized input data"),
            FormulaVariable("j0", "Reference current density for a dimensionless logarithm", "1 mA/cm2", "constant"),
            FormulaVariable("x", "Base-10 logarithm of the clipped dimensionless current ratio", None, "calculated"),
            FormulaVariable("E", "Converted potential, using iR-compensated potential when enabled", "V", "calculated input to fit"),
            FormulaVariable("a", "Least-squares intercept", "V", "fit"),
            FormulaVariable("b", "Signed least-squares slope of potential versus log10 current density", "V/dec", "fit"),
            FormulaVariable("TafelSlope", "Reported signed Tafel slope", "mV/dec", "calculated"),
        ),
        result_unit="mV/dec",
        assumptions=(
            "Only enabled Tafel fitting is described; a numeric result additionally requires at least three finite, positive-current pairs within the inclusive configured current range.",
            "The implementation uses an unweighted degree-one numpy.polyfit and retains the sign of the fitted slope.",
            "Potential is fitted directly; the implementation does not subtract equilibrium potential or filter points beyond the finite, positive-current and range checks.",
        ),
    ),
    CalculationFormula(
        key="common.rhe_conversion",
        name="RHE potential conversion",
        expression="E_RHE = E_measured + E_ref + (2.303 * R * T / F) * pH",
        data_types=("LSV", "CV"),
        variables=(
            FormulaVariable("E_RHE", "Potential converted to RHE", "V", "calculated"),
            FormulaVariable("E_measured", "Measured potential", "V", "input data"),
            FormulaVariable("E_ref", "Reference electrode potential", "V", "parameter"),
            FormulaVariable("pH", "Electrolyte pH", None, "parameter"),
        ),
        result_unit="V",
        assumptions=(
            "Nernst pH slope is calculated from the configured temperature.",
            "Reference-electrode preset potentials are nominal values versus SHE.",
        ),
    ),
    CalculationFormula(
        key="lsv.ir_compensation",
        name="LSV iR compensation",
        expression="E_iR = E_measured - (j_mA_cm2 / 1000) * A_cm2 * Rs_ohm",
        data_types=("LSV",),
        variables=(
            FormulaVariable("E_iR", "Potential after ohmic-drop compensation", "V", "calculated"),
            FormulaVariable("E_measured", "Measured potential", "V", "input data"),
            FormulaVariable("j_mA_cm2", "Signed current density", "mA/cm2", "input data"),
            FormulaVariable("A_cm2", "Electrode area", "cm2", "parameter"),
            FormulaVariable("Rs_ohm", "Solution resistance from EIS or manual input", "Ohm", "parameter or EIS"),
        ),
        result_unit="V",
        assumptions=(
            "Current density is converted from mA/cm2 to A/cm2 before multiplying by area and resistance.",
            "The signed current density is used, so correction direction follows the recorded current convention.",
        ),
    ),
    CalculationFormula(
        key="cv.absolute_charge",
        name="CV absolute charge from scan rate",
        expression="Q_abs = integral |I| dt, where dt = |dE| / v",
        data_types=("CV",),
        variables=(
            FormulaVariable("Q_abs", "Absolute charge passed during the selected CV trace", "mC", "calculated"),
            FormulaVariable("I", "Measured current", "mA", "input data"),
            FormulaVariable("E", "Measured potential", "V", "input data"),
            FormulaVariable("v", "Constant scan rate", "V/s", "parameter"),
        ),
        result_unit="mC",
        assumptions=("The scan rate is constant over the selected CV trace.",),
    ),
    CalculationFormula(
        key="coupled.faradaic_efficiency",
        name="Faradaic efficiency",
        expression="FE_i = z_i * F * n_i / Q_total * 100%",
        data_types=("COUPLED",),
        variables=(
            FormulaVariable("FE_i", "Faradaic efficiency of product i", "%", "calculated"),
            FormulaVariable("z_i", "Electron transfer number of product i", None, "product table"),
            FormulaVariable("F", "Faraday constant, 96485.33212 C/mol", "C/mol", "constant"),
            FormulaVariable("n_i", "Amount of product i", "mol", "product table"),
            FormulaVariable("Q_total", "Total charge passed during electrolysis", "C", "product table or current-time"),
        ),
        result_unit="%",
        assumptions=("Product amount and charge refer to the same electrolysis interval.",),
        references=("Faraday's law of electrolysis",),
    ),
    CalculationFormula(
        key="coupled.fixed_window_peak_area",
        name="Fixed-window baseline-corrected peak area",
        expression="A = integral[x_c-w_left, x_c+w_right] (y(x) - b_linear(x)) dx",
        data_types=("COUPLED",),
        variables=(
            FormulaVariable("A", "Baseline-corrected quantitative peak area", None, "calculated"),
            FormulaVariable("x_c", "Located peak center", None, "signal trace"),
            FormulaVariable("w_left", "Locked left window width", None, "parameter or method file"),
            FormulaVariable("w_right", "Locked right window width", None, "parameter or method file"),
            FormulaVariable("b_linear(x)", "Local linear baseline estimated from window edges", None, "calculated"),
        ),
        assumptions=("The same relative window rule is used for every sample in the batch.",),
    ),
    CalculationFormula(
        key="coupled.pseudo_voigt_peak_area",
        name="Constrained pseudo-Voigt peak area",
        expression="y(x) = A * [(1-eta) * G_norm(x; x_c,w) + eta * L_norm(x; x_c,w)] + b0 + b1*(x-x_c)",
        data_types=("COUPLED",),
        variables=(
            FormulaVariable("A", "Fitted peak area", None, "calculated"),
            FormulaVariable("eta", "Lorentzian mixing fraction constrained to 0..1", None, "fit"),
            FormulaVariable("x_c", "Peak center constrained to the quantification window", None, "fit"),
            FormulaVariable("w", "Positive peak width", None, "fit"),
            FormulaVariable("b0,b1", "Local linear baseline coefficients", None, "fit"),
        ),
        assumptions=("G_norm and L_norm are unit-area Gaussian and Lorentzian components.",),
    ),
    CalculationFormula(
        key="coupled.qnmr_product_amount",
        name="qNMR internal-standard product amount",
        expression="n_i = (A_i / N_i) / (A_IS / N_IS) * (C_IS * V_IS) * (V_electrolyte / V_aliquot) * R_i",
        data_types=("COUPLED",),
        variables=(
            FormulaVariable("n_i", "Total amount of product i in the electrolyte", "mol", "calculated"),
            FormulaVariable("A_i", "Integrated or fitted product peak area", None, "signal trace"),
            FormulaVariable("N_i", "Quantitative nuclei represented by the product peak", None, "method file"),
            FormulaVariable("A_IS", "Integrated or fitted internal-standard peak area", None, "signal trace"),
            FormulaVariable("N_IS", "Quantitative nuclei represented by the internal-standard peak", None, "method file"),
            FormulaVariable("C_IS", "Internal-standard concentration", "mol/L", "method or measurement table"),
            FormulaVariable("V_IS", "Internal-standard volume added", "L", "method or measurement table"),
            FormulaVariable("V_electrolyte", "Total electrolyte volume", "L", "method or measurement table"),
            FormulaVariable("V_aliquot", "Electrolyte aliquot volume analyzed", "L", "method or measurement table"),
            FormulaVariable("R_i", "Validated product response correction factor", None, "method file"),
        ),
        result_unit="mol",
        assumptions=(
            "Product and internal-standard areas are processed with one locked method.",
            "The analyzed aliquot is representative of the total electrolyte.",
        ),
    ),
    CalculationFormula(
        key="coupled.peak_reference_alignment",
        name="Reference-based peak alignment",
        expression="x_i,aligned = x_i,expected + (x_IS,found - x_IS,expected)",
        data_types=("COUPLED",),
        variables=(
            FormulaVariable("x_i,aligned", "Aligned expected product peak position", None, "calculated"),
            FormulaVariable("x_i,expected", "Method-defined product peak position", None, "method file"),
            FormulaVariable("x_IS,found", "Detected internal-standard peak position", None, "signal trace"),
            FormulaVariable("x_IS,expected", "Method-defined internal-standard position", None, "method file"),
        ),
        assumptions=("Reference and product peaks share the same local axis offset.",),
    ),
    CalculationFormula(
        key="coupled.product_selectivity",
        name="Product mole selectivity",
        expression="S_i = n_i / sum(n_j) * 100%",
        data_types=("COUPLED",),
        variables=(
            FormulaVariable("S_i", "Mole selectivity of product i", "%", "calculated"),
            FormulaVariable("n_i", "Amount of product i", "mol", "product table"),
            FormulaVariable("sum(n_j)", "Total quantified product amount for the same sample", "mol", "calculated"),
        ),
        result_unit="%",
        assumptions=("Only products present in the quantification table are included in the denominator.",),
    ),
    CalculationFormula(
        key="coupled.fe_selectivity",
        name="FE-share selectivity",
        expression="S_FE,i = FE_i / sum(FE_j) * 100%",
        data_types=("COUPLED",),
        variables=(
            FormulaVariable("S_FE,i", "Share of product i in total calculated FE", "%", "calculated"),
            FormulaVariable("FE_i", "Faradaic efficiency of product i", "%", "calculated"),
            FormulaVariable("sum(FE_j)", "Sum of calculated product FE values for the same sample", "%", "calculated"),
        ),
        result_unit="%",
        assumptions=("Only products present in the quantification table are included in the denominator.",),
    ),
    CalculationFormula(
        key="coupled.charge_from_current_time",
        name="Charge from current-time input",
        expression="Q_total = abs(I) * t",
        data_types=("COUPLED",),
        variables=(
            FormulaVariable("Q_total", "Total charge", "C", "calculated"),
            FormulaVariable("I", "Electrolysis current", "A", "product table"),
            FormulaVariable("t", "Electrolysis time", "s", "product table"),
        ),
        result_unit="C",
        assumptions=("Current is treated as constant over the provided time interval.",),
    ),
)

FORMULA_BY_KEY: dict[str, CalculationFormula] = {item.key: item for item in FORMULA_CATALOG}


def formula_catalog(keys: Sequence[str] | None = None) -> list[dict[str, Any]]:
    if keys is None:
        return [item.to_dict() for item in FORMULA_CATALOG]
    selected = {str(key) for key in keys}
    return [item.to_dict() for item in FORMULA_CATALOG if item.key in selected]


def formulas_for_data_types(data_types: Sequence[str]) -> list[dict[str, Any]]:
    selected = {str(item or "").strip().upper() for item in data_types}
    return [
        item.to_dict()
        for item in FORMULA_CATALOG
        if any(data_type in selected for data_type in item.data_types)
    ]


def formulas_for_run(data_types: Sequence[str], params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    formulas = formulas_for_data_types(data_types)
    values = params or {}
    potential_mode = str(values.get("potential_mode") or "").strip().lower()
    if potential_mode != "formula_rhe":
        formulas = [item for item in formulas if item.get("key") != "common.rhe_conversion"]
    else:
        formulas = [item for item in formulas if item.get("key") != "lsv.manual_potential_offset"]
    if not as_bool(values.get("tafel_enabled"), False):
        formulas = [item for item in formulas if item.get("key") != "lsv.tafel_fit"]
    if not as_bool(values.get("ir_compensation_enabled"), False):
        formulas = [item for item in formulas if item.get("key") != "lsv.ir_compensation"]
    try:
        cv_scan_rate = float(values.get("cv_scan_rate_v_s") or 0.0)
    except (TypeError, ValueError):
        cv_scan_rate = 0.0
    if cv_scan_rate <= 0:
        formulas = [item for item in formulas if item.get("key") != "cv.absolute_charge"]
    coupled_mode = str(values.get("coupled_input_mode") or "product_table").strip().lower()
    peak_mode = coupled_mode in {"peak_analysis", "peak", "peaks", "qnmr", "analytical_peaks"}
    peak_formula_keys = {
        "coupled.fixed_window_peak_area",
        "coupled.pseudo_voigt_peak_area",
        "coupled.qnmr_product_amount",
        "coupled.peak_reference_alignment",
    }
    if not peak_mode:
        formulas = [
            item
            for item in formulas
            if item.get("key") not in peak_formula_keys
        ]
    else:
        if as_bool(values.get("fe_peak_fit_enabled"), False):
            formulas = [item for item in formulas if item.get("key") != "coupled.fixed_window_peak_area"]
        else:
            formulas = [item for item in formulas if item.get("key") != "coupled.pseudo_voigt_peak_area"]
        if not as_bool(values.get("fe_peak_reference_align"), True):
            formulas = [item for item in formulas if item.get("key") != "coupled.peak_reference_alignment"]
    return formulas


__all__ = [
    "FORMULA_BY_KEY",
    "FORMULA_CATALOG",
    "FORMULA_SCHEMA_VERSION",
    "CalculationFormula",
    "FormulaVariable",
    "formula_catalog",
    "formulas_for_data_types",
    "formulas_for_run",
]
