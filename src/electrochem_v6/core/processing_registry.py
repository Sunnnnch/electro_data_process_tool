"""Central registry for supported processing modules.

This module is intentionally small: it records stable metadata that used to be
duplicated across the service layer and pipeline scanner.  Calculation logic
stays in the individual processing modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from electrochem_v6.core.utils import as_bool

PARAM_SCHEMA_VERSION = "1.9"

FILE_MATCH_MODES = ("prefix", "suffix", "contains", "regex")
POTENTIAL_MODES = ("manual", "formula_rhe")
IR_SOURCE_EIS = "eis"
IR_SOURCE_MANUAL = "manual"
IR_SOURCE_OPTIONS = (IR_SOURCE_EIS, IR_SOURCE_MANUAL)
IR_SEARCH_SCOPES = ("same_dir", "same_then_root", "recursive_root", "specified_file")
IR_EXTRACTION_METHODS = ("auto", "hf_intercept", "hf_mean", "linear_fit")
IR_VALIDATION_MODES = ("strict", "lenient")
COUPLED_INPUT_MODES = ("product_table", "peak_analysis")
COUPLED_PEAK_METHOD_SOURCES = ("file", "panel")


@dataclass(frozen=True)
class ParameterGroupSpec:
    key: str
    label: str
    description: str = ""
    order: int = 0


@dataclass(frozen=True)
class ProcessingModuleSpec:
    key: str
    enabled_key: str
    match_mode_key: str | None = None
    match_value_key: str | None = None
    default_match_mode: str = "prefix"
    default_match_value: str = ""
    display_name: str | None = None
    summary: str = ""
    capabilities: tuple[str, ...] = ()
    result_kinds: tuple[str, ...] = ()
    input_kind: str = "data_files"
    aliases: tuple[str, ...] = ()
    parameter_keys: tuple[str, ...] = ()

    @property
    def has_file_match(self) -> bool:
        return bool(self.match_mode_key and self.match_value_key)

    @property
    def title(self) -> str:
        return self.display_name or self.key


@dataclass(frozen=True)
class NumericParamSpec:
    key: str
    label: str
    min_value: float | None = None
    max_value: float | None = None
    integer_only: bool = False
    data_type: str | None = None
    default: Any = None
    group: str = "basic"
    required: bool = False
    help_text: str = ""
    ui_control: str = "number"


@dataclass(frozen=True)
class GuiParamSpec:
    key: str
    default: Any
    value_type: str = "raw"
    data_types: tuple[str, ...] | None = None
    empty_as_default: bool = False
    group: str = "basic"
    label: str | None = None
    required: bool = False
    help_text: str = ""
    ui_control: str | None = None
    options: tuple[Any, ...] = ()
    ui_default: Any = None


@dataclass(frozen=True)
class ReferenceElectrodePresetSpec:
    key: str
    label: str
    potential_v: float | None


@dataclass(frozen=True)
class EcsaMaterialPresetSpec:
    key: str
    label: str
    specific_capacitance_uf_cm2: float | None


REFERENCE_ELECTRODE_PRESETS: tuple[ReferenceElectrodePresetSpec, ...] = (
    ReferenceElectrodePresetSpec("agcl_sat_kcl", "Ag/AgCl (sat. KCl, +0.197 V)", 0.197),
    ReferenceElectrodePresetSpec("agcl_3m_kcl", "Ag/AgCl (3 M KCl, +0.210 V)", 0.210),
    ReferenceElectrodePresetSpec("sce", "SCE (+0.241 V)", 0.241),
    ReferenceElectrodePresetSpec("hg_hgo_1m_koh", "Hg/HgO (1 M KOH, +0.098 V)", 0.098),
    ReferenceElectrodePresetSpec("hg_hg2so4_sat", "Hg/Hg2SO4 (sat. K2SO4, +0.640 V)", 0.640),
    ReferenceElectrodePresetSpec("mse", "MSE (Hg/Hg2SO4 sat., +0.640 V)", 0.640),
    ReferenceElectrodePresetSpec("rhe", "RHE (+0.000 V)", 0.000),
    ReferenceElectrodePresetSpec("custom", "Custom", None),
)
REFERENCE_ELECTRODE_PRESET_VALUES: dict[str, float] = {
    spec.key: spec.potential_v for spec in REFERENCE_ELECTRODE_PRESETS if spec.potential_v is not None
}

ECSA_MATERIAL_PRESETS: tuple[EcsaMaterialPresetSpec, ...] = (
    EcsaMaterialPresetSpec("Pt", "Pt (20 uF/cm2)", 20.0),
    EcsaMaterialPresetSpec("Carbon", "Carbon (20 uF/cm2)", 20.0),
    EcsaMaterialPresetSpec("IrO2", "IrO2 (40 uF/cm2)", 40.0),
    EcsaMaterialPresetSpec("RuO2", "RuO2 (35 uF/cm2)", 35.0),
    EcsaMaterialPresetSpec("NiFeOOH", "NiFeOOH (60 uF/cm2)", 60.0),
    EcsaMaterialPresetSpec("MnO2", "MnO2 (40 uF/cm2)", 40.0),
    EcsaMaterialPresetSpec("CoOx", "CoOx (50 uF/cm2)", 50.0),
    EcsaMaterialPresetSpec("custom", "Custom", None),
)


PARAMETER_GROUPS: tuple[ParameterGroupSpec, ...] = (
    ParameterGroupSpec("source", "Data source", "File matching, input table, and data identification settings.", 10),
    ParameterGroupSpec("basic", "Basic parameters", "Frequently adjusted experiment parameters.", 20),
    ParameterGroupSpec("calculation", "Calculation", "Analysis options that affect reported metrics.", 30),
    ParameterGroupSpec("quality", "Quality control", "Thresholds and checks used to judge result reliability.", 40),
    ParameterGroupSpec("plot_export", "Plot and export", "Figure appearance and output file options.", 50),
    ParameterGroupSpec("advanced", "Advanced", "Less common parameters for specialized workflows.", 60),
)
PARAMETER_GROUP_BY_KEY: dict[str, ParameterGroupSpec] = {spec.key: spec for spec in PARAMETER_GROUPS}


PROCESSING_MODULES: tuple[ProcessingModuleSpec, ...] = (
    ProcessingModuleSpec(
        "LSV",
        "lsv_enabled",
        "lsv_match",
        "lsv_prefix",
        "prefix",
        "LSV",
        display_name="LSV",
        summary="Polarization curve, Tafel fitting, and target-current metrics",
        capabilities=("polarization_curve", "tafel", "target_current", "quality_check"),
        result_kinds=("plot", "summary_table", "history_record"),
    ),
    ProcessingModuleSpec(
        "CV",
        "cv_enabled",
        "cv_match",
        "cv_prefix",
        "prefix",
        "CV",
        display_name="CV",
        summary="Cyclic voltammetry curves, peak detection, and quality checks",
        capabilities=("cyclic_voltammetry", "peak_detection", "quality_check"),
        result_kinds=("plot", "history_record"),
    ),
    ProcessingModuleSpec(
        "EIS",
        "eis_enabled",
        "eis_match",
        "eis_prefix",
        "prefix",
        "EIS",
        display_name="EIS",
        summary="Impedance spectra with Nyquist, Bode, and equivalent-circuit fitting",
        capabilities=("nyquist", "bode", "randles_fit"),
        result_kinds=("plot", "history_record"),
    ),
    ProcessingModuleSpec(
        "ECSA",
        "ecsa_enabled",
        "ecsa_match",
        "ecsa_prefix",
        "prefix",
        "ECSA",
        display_name="ECSA",
        summary="Double-layer capacitance and electrochemically active surface area",
        capabilities=("double_layer_capacitance", "scan_rate_fit", "active_area"),
        result_kinds=("plot", "history_record"),
    ),
    ProcessingModuleSpec(
        "COUPLED",
        "coupled_enabled",
        display_name="COUPLED/FE",
        summary="Product-table or peak-based quantification for Faradaic efficiency and selectivity",
        capabilities=("faradaic_efficiency", "product_selectivity", "charge_coupling", "peak_quantification"),
        result_kinds=("summary_table", "quality_diagnostics", "history_record"),
        input_kind="product_table",
        aliases=("FE", "FARADAIC", "FARADAIC_EFFICIENCY", "SELECTIVITY"),
    ),
)

PROCESSING_MODULE_BY_KEY: dict[str, ProcessingModuleSpec] = {spec.key: spec for spec in PROCESSING_MODULES}
FILE_MATCH_MODULE_SPECS: tuple[ProcessingModuleSpec, ...] = tuple(
    spec for spec in PROCESSING_MODULES if spec.has_file_match
)
SUPPORTED_DATA_TYPES: tuple[str, ...] = tuple(spec.key for spec in PROCESSING_MODULES)

DATA_TYPE_ALIASES: dict[str, str] = {alias: spec.key for spec in PROCESSING_MODULES for alias in spec.aliases}

NUMERIC_PARAM_SPECS: tuple[NumericParamSpec, ...] = (
    NumericParamSpec("font_size", "Font size", 6.0, 72.0, True, default=12, group="plot_export"),
    NumericParamSpec("area", "Electrode area", 0.000001, default=1.0, group="basic", required=True),
    NumericParamSpec("potential_offset", "Potential offset", -100.0, 100.0, default=0.0, group="basic"),
    NumericParamSpec("rhe_ph", "pH", 0.0, 14.0, default=None, group="basic"),
    NumericParamSpec(
        "rhe_temperature_c",
        "RHE conversion temperature",
        -20.0,
        100.0,
        default=25.0,
        group="basic",
    ),
    NumericParamSpec(
        "reference_electrode_potential", "Reference electrode potential", -2.0, 2.0, default=None, group="basic"
    ),
    NumericParamSpec("lsv_line_width", "LSV line width", 0.1, 10.0, data_type="LSV", default=2.0, group="plot_export"),
    NumericParamSpec(
        "lsv_potential_column",
        "LSV potential column",
        1.0,
        100.0,
        integer_only=True,
        data_type="LSV",
        default=1,
        group="source",
    ),
    NumericParamSpec(
        "lsv_current_column",
        "LSV current column",
        1.0,
        100.0,
        integer_only=True,
        data_type="LSV",
        default=2,
        group="source",
    ),
    NumericParamSpec("cv_line_width", "CV line width", 0.1, 10.0, data_type="CV", default=2.0, group="plot_export"),
    NumericParamSpec(
        "cv_potential_column",
        "CV potential column",
        1.0,
        100.0,
        integer_only=True,
        data_type="CV",
        default=1,
        group="source",
    ),
    NumericParamSpec(
        "cv_current_column",
        "CV current column",
        1.0,
        100.0,
        integer_only=True,
        data_type="CV",
        default=2,
        group="source",
    ),
    NumericParamSpec(
        "cv_scan_rate_v_s", "CV scan rate", 0.000000001, data_type="CV", default=None, group="calculation"
    ),
    NumericParamSpec(
        "cv_cycle_reversal_tolerance",
        "CV cycle reversal tolerance",
        0.000000001,
        data_type="CV",
        default=None,
        group="plot_export",
    ),
    NumericParamSpec(
        "cv_cycle_min_segment_points",
        "CV cycle minimum segment points",
        2.0,
        100000.0,
        integer_only=True,
        data_type="CV",
        default=3,
        group="plot_export",
    ),
    NumericParamSpec("eis_line_width", "EIS line width", 0.1, 10.0, data_type="EIS", default=2.0, group="plot_export"),
    NumericParamSpec(
        "eis_fit_min_r2",
        "EIS fit minimum R2",
        0.0,
        1.0,
        data_type="EIS",
        default=0.5,
        group="calculation",
    ),
    NumericParamSpec("eis_fit_frequency_min_hz", "EIS minimum frequency (Hz)", min_value=0.0, data_type="EIS", group="calculation", help_text="Optional, strictly positive; inclusive lower bound in Hz. Empty means no lower limit."),
    NumericParamSpec("eis_fit_frequency_max_hz", "EIS maximum frequency (Hz)", min_value=0.0, data_type="EIS", group="calculation", help_text="Optional, strictly positive; inclusive upper bound in Hz. Empty means no upper limit."),
    NumericParamSpec(
        "eis_frequency_column",
        "EIS frequency column",
        1.0,
        100.0,
        integer_only=True,
        data_type="EIS",
        default=1,
        group="source",
    ),
    NumericParamSpec(
        "eis_zreal_column",
        "EIS real impedance column",
        1.0,
        100.0,
        integer_only=True,
        data_type="EIS",
        default=2,
        group="source",
    ),
    NumericParamSpec(
        "eis_zimag_column",
        "EIS imaginary impedance column",
        1.0,
        100.0,
        integer_only=True,
        data_type="EIS",
        default=3,
        group="source",
    ),
    NumericParamSpec(
        "ecsa_line_width", "ECSA line width", 0.1, 10.0, data_type="ECSA", default=2.0, group="plot_export"
    ),
    NumericParamSpec(
        "ecsa_potential_column",
        "ECSA potential column",
        1.0,
        100.0,
        integer_only=True,
        data_type="ECSA",
        default=1,
        group="source",
    ),
    NumericParamSpec(
        "ecsa_current_column",
        "ECSA current column",
        1.0,
        100.0,
        integer_only=True,
        data_type="ECSA",
        default=2,
        group="source",
    ),
    NumericParamSpec("ir_manual_ohm", "Manual Rs", 0.0, data_type="LSV", default=0.0, group="calculation"),
    NumericParamSpec(
        "ir_linear_points", "IR high-frequency points", 2.0, 1000.0, True, "LSV", default=10, group="advanced"
    ),
    NumericParamSpec(
        "ir_eis_frequency_column",
        "iR EIS frequency column",
        1.0,
        100.0,
        integer_only=True,
        data_type="LSV",
        default=1,
        group="source",
    ),
    NumericParamSpec(
        "ir_eis_zreal_column",
        "iR EIS real impedance column",
        1.0,
        100.0,
        integer_only=True,
        data_type="LSV",
        default=2,
        group="source",
    ),
    NumericParamSpec(
        "ir_eis_zimag_column",
        "iR EIS imaginary impedance column",
        1.0,
        100.0,
        integer_only=True,
        data_type="LSV",
        default=3,
        group="source",
    ),
    NumericParamSpec(
        "cv_peaks_smooth", "CV peak smoothing window", 1.0, 999.0, True, "CV", default=5, group="calculation"
    ),
    NumericParamSpec(
        "cv_peaks_min_height", "CV peak minimum height", 0.0, data_type="CV", default=1.0, group="calculation"
    ),
    NumericParamSpec(
        "cv_peaks_min_dist", "CV peak minimum distance", 1.0, 10000.0, True, "CV", default=5, group="calculation"
    ),
    NumericParamSpec("cv_peaks_max", "CV maximum peaks", 1.0, 1000.0, True, "CV", default=2, group="calculation"),
    NumericParamSpec(
        "ecsa_ev", "ECSA evaluation potential", 0.000001, data_type="ECSA", default=0.10, group="calculation"
    ),
    NumericParamSpec("ecsa_last_n", "ECSA last cycles", 1.0, 10000.0, True, "ECSA", default=1, group="calculation"),
    NumericParamSpec(
        "ecsa_cs_value", "Specific capacitance", 0.000001, data_type="ECSA", default=40.0, group="calculation"
    ),
    NumericParamSpec(
        "lsv_quality_min_points_issue",
        "LSV minimum points for failure",
        1.0,
        100000.0,
        data_type="LSV",
        default=20,
        integer_only=True,
        group="quality",
    ),
    NumericParamSpec(
        "lsv_quality_min_points_warning",
        "LSV minimum points for warning",
        1.0,
        100000.0,
        data_type="LSV",
        default=50,
        integer_only=True,
        group="quality",
    ),
    NumericParamSpec(
        "lsv_quality_outlier_warning_pct",
        "LSV outlier warning percent",
        0.0,
        100.0,
        data_type="LSV",
        default=10.0,
        group="quality",
    ),
    NumericParamSpec(
        "lsv_quality_min_potential_span",
        "LSV minimum potential span",
        0.0,
        100.0,
        data_type="LSV",
        default=0.1,
        group="quality",
    ),
    NumericParamSpec(
        "lsv_quality_noise_warning",
        "LSV noise warning threshold",
        0.0,
        100000.0,
        data_type="LSV",
        default=3.0,
        group="quality",
    ),
    NumericParamSpec(
        "lsv_quality_noise_critical",
        "LSV noise critical threshold",
        0.0,
        100000.0,
        data_type="LSV",
        default=7.0,
        group="quality",
    ),
    NumericParamSpec(
        "lsv_quality_jump_warning", "LSV jump warning ratio", 0.0, 1.0, data_type="LSV", default=0.10, group="quality"
    ),
    NumericParamSpec(
        "lsv_quality_jump_critical", "LSV jump critical ratio", 0.0, 1.0, data_type="LSV", default=0.20, group="quality"
    ),
    NumericParamSpec(
        "lsv_quality_local_variation_factor",
        "LSV local variation factor",
        1.0,
        100000.0,
        data_type="LSV",
        default=8.0,
        group="quality",
    ),
    NumericParamSpec(
        "cv_quality_min_points_warning",
        "CV minimum points for warning",
        1.0,
        100000.0,
        data_type="CV",
        default=100,
        integer_only=True,
        group="quality",
    ),
    NumericParamSpec(
        "cv_quality_cycle_tolerance",
        "CV cycle closure tolerance",
        0.0,
        100.0,
        data_type="CV",
        default=0.1,
        group="quality",
    ),
    NumericParamSpec(
        "fe_peak_search_tolerance",
        "FE peak search tolerance",
        0.000001,
        data_type="COUPLED",
        default=0.08,
        group="calculation",
    ),
    NumericParamSpec(
        "fe_peak_window_left", "FE peak left window", 0.000001, data_type="COUPLED", default=0.05, group="calculation"
    ),
    NumericParamSpec(
        "fe_peak_window_right", "FE peak right window", 0.000001, data_type="COUPLED", default=0.05, group="calculation"
    ),
    NumericParamSpec(
        "fe_peak_min_detection_snr",
        "FE peak minimum detection SNR",
        0.000001,
        data_type="COUPLED",
        default=3.0,
        group="quality",
    ),
    NumericParamSpec(
        "fe_peak_min_quantification_snr",
        "FE peak minimum quantification SNR",
        0.000001,
        data_type="COUPLED",
        default=10.0,
        group="quality",
    ),
)

GUI_PARAM_SPECS: tuple[GuiParamSpec, ...] = (
    GuiParamSpec(
        "recursive_scan", False, "bool", group="source", label="Scan deeper subdirectories", ui_control="checkbox"
    ),
    GuiParamSpec(
        "output_run_dir_enabled",
        True,
        "bool",
        group="source",
        label="Save results in a new run directory",
        ui_control="checkbox",
    ),
    GuiParamSpec("plot_grid", True, "bool", group="plot_export", label="Show grid", ui_control="checkbox"),
    GuiParamSpec("use_abs_current", True, "bool", group="basic", label="Use absolute current", ui_control="checkbox"),
    GuiParamSpec("font_family", "", "str", group="plot_export", label="Font family", ui_control="select"),
    GuiParamSpec(
        "potential_mode",
        "manual",
        "str",
        group="basic",
        label="Potential conversion mode",
        ui_control="select",
        options=POTENTIAL_MODES,
    ),
    GuiParamSpec("rhe_ph", None, "float", group="basic", label="pH"),
    GuiParamSpec("rhe_temperature_c", 25.0, "float", group="basic", label="Temperature (degC)"),
    GuiParamSpec(
        "reference_electrode_preset",
        "agcl_sat_kcl",
        "str",
        group="basic",
        label="Reference electrode",
        ui_control="select",
        options=tuple(spec.key for spec in REFERENCE_ELECTRODE_PRESETS),
    ),
    GuiParamSpec(
        "reference_electrode_potential", None, "float", group="basic", label="Custom reference electrode potential"
    ),
    GuiParamSpec(
        "lsv_target_current",
        "10,100",
        "str",
        ("LSV",),
        empty_as_default=True,
        group="basic",
        label="Target current density",
    ),
    GuiParamSpec(
        "tafel_range", "1-10", "str", ("LSV",), empty_as_default=True, group="calculation", label="Tafel current range"
    ),
    GuiParamSpec(
        "tafel_enabled",
        False,
        "bool",
        ("LSV",),
        group="calculation",
        label="Enable Tafel fitting",
        ui_control="checkbox",
    ),
    GuiParamSpec(
        "lsv_match",
        "prefix",
        "str",
        ("LSV",),
        group="source",
        label="LSV match mode",
        ui_control="select",
        options=FILE_MATCH_MODES,
    ),
    GuiParamSpec("lsv_prefix", "LSV", "str", ("LSV",), group="source", label="LSV match pattern"),
    GuiParamSpec("lsv_potential_column", 1, "int", ("LSV",), group="source", label="LSV potential column"),
    GuiParamSpec("lsv_current_column", 2, "int", ("LSV",), group="source", label="LSV current column"),
    GuiParamSpec(
        "lsv_potential_unit",
        "v",
        "str",
        ("LSV",),
        group="source",
        label="LSV potential unit",
        ui_control="select",
        options=("v", "mv"),
    ),
    GuiParamSpec(
        "lsv_current_unit",
        "a",
        "str",
        ("LSV",),
        group="source",
        label="LSV current unit",
        ui_control="select",
        options=("a", "ma", "ua"),
    ),
    GuiParamSpec("lsv_title", "LSV of {sample}", "str", ("LSV",), group="plot_export", label="LSV plot title"),
    GuiParamSpec("lsv_xlabel", "Potential (V)", "str", ("LSV",), group="plot_export", label="LSV X-axis label"),
    GuiParamSpec(
        "lsv_ylabel", "Current Density (mA/cm2)", "str", ("LSV",), group="plot_export", label="LSV Y-axis label"
    ),
    GuiParamSpec(
        "eis_match",
        "prefix",
        "str",
        ("EIS",),
        group="source",
        label="EIS match mode",
        ui_control="select",
        options=FILE_MATCH_MODES,
    ),
    GuiParamSpec("eis_prefix", "EIS", "str", ("EIS",), group="source", label="EIS match pattern"),
    GuiParamSpec("eis_frequency_column", 1, "int", ("EIS",), group="source", label="EIS frequency column"),
    GuiParamSpec("eis_zreal_column", 2, "int", ("EIS",), group="source", label="EIS real impedance column"),
    GuiParamSpec("eis_zimag_column", 3, "int", ("EIS",), group="source", label="EIS imaginary impedance column"),
    GuiParamSpec(
        "eis_frequency_unit",
        "hz",
        "str",
        ("EIS",),
        group="source",
        label="EIS frequency unit",
        ui_control="select",
        options=("hz", "khz"),
    ),
    GuiParamSpec(
        "eis_impedance_unit",
        "ohm",
        "str",
        ("EIS",),
        group="source",
        label="EIS impedance unit",
        ui_control="select",
        options=("ohm", "kohm"),
    ),
    GuiParamSpec(
        "eis_zimag_convention",
        "z_imaginary",
        "str",
        ("EIS",),
        group="source",
        label="EIS imaginary column convention",
        ui_control="select",
        options=("z_imaginary", "negative_z_imaginary"),
    ),
    GuiParamSpec("eis_title", "EIS of {sample}", "str", ("EIS",), group="plot_export", label="EIS plot title"),
    GuiParamSpec("eis_xlabel", "Z' (Ohm)", "str", ("EIS",), group="plot_export", label="EIS X-axis label"),
    GuiParamSpec("eis_ylabel", "-Z'' (Ohm)", "str", ("EIS",), group="plot_export", label="EIS Y-axis label"),
    GuiParamSpec(
        "lsv_mark_targets",
        True,
        "bool",
        ("LSV",),
        group="plot_export",
        label="Mark target current points",
        ui_control="checkbox",
    ),
    GuiParamSpec(
        "lsv_export_data",
        False,
        "bool",
        ("LSV",),
        group="plot_export",
        label="Export LSV detail tables",
        ui_control="checkbox",
    ),
    GuiParamSpec(
        "lsv_combine_all",
        False,
        "bool",
        ("LSV",),
        group="plot_export",
        label="Export combined LSV plot",
        ui_control="checkbox",
    ),
    GuiParamSpec(
        "export_tafel_plot",
        False,
        "bool",
        ("LSV",),
        group="plot_export",
        label="Export Tafel plot",
        ui_control="checkbox",
    ),
    GuiParamSpec(
        "ir_compensation_enabled",
        False,
        "bool",
        ("LSV",),
        group="calculation",
        label="Enable iR compensation",
        ui_control="checkbox",
    ),
    GuiParamSpec(
        "ir_source",
        "eis",
        "str",
        ("LSV",),
        group="calculation",
        label="Rs source",
        ui_control="select",
        options=IR_SOURCE_OPTIONS,
    ),
    GuiParamSpec(
        "ir_eis_search_scope",
        "same_dir",
        "str",
        ("LSV",),
        group="source",
        label="EIS search scope",
        ui_control="select",
        options=IR_SEARCH_SCOPES,
    ),
    GuiParamSpec("ir_eis_file", "", "str", ("LSV",), empty_as_default=True, group="source", label="Specified EIS file"),
    GuiParamSpec(
        "ir_eis_match",
        "prefix",
        "str",
        ("LSV",),
        group="source",
        label="iR EIS match mode",
        ui_control="select",
        options=FILE_MATCH_MODES,
    ),
    GuiParamSpec("ir_eis_pattern", "EIS", "str", ("LSV",), group="source", label="iR EIS match pattern"),
    GuiParamSpec("ir_eis_frequency_column", 1, "int", ("LSV",), group="source", label="iR EIS frequency column"),
    GuiParamSpec("ir_eis_zreal_column", 2, "int", ("LSV",), group="source", label="iR EIS real impedance column"),
    GuiParamSpec("ir_eis_zimag_column", 3, "int", ("LSV",), group="source", label="iR EIS imaginary impedance column"),
    GuiParamSpec(
        "ir_eis_frequency_unit",
        "hz",
        "str",
        ("LSV",),
        group="source",
        label="iR EIS frequency unit",
        ui_control="select",
        options=("hz", "khz"),
    ),
    GuiParamSpec(
        "ir_eis_impedance_unit",
        "ohm",
        "str",
        ("LSV",),
        group="source",
        label="iR EIS impedance unit",
        ui_control="select",
        options=("ohm", "kohm"),
    ),
    GuiParamSpec(
        "ir_eis_zimag_convention",
        "z_imaginary",
        "str",
        ("LSV",),
        group="source",
        label="iR EIS imaginary column convention",
        ui_control="select",
        options=("z_imaginary", "negative_z_imaginary"),
    ),
    GuiParamSpec(
        "ir_method",
        "auto",
        "str",
        ("LSV",),
        group="advanced",
        label="iR extraction method",
        ui_control="select",
        options=IR_EXTRACTION_METHODS,
    ),
    GuiParamSpec(
        "ir_validation_mode",
        "strict",
        "str",
        ("LSV",),
        group="advanced",
        label="iR validation mode",
        ui_control="select",
        options=IR_VALIDATION_MODES,
    ),
    GuiParamSpec("ir_manual_ohm", 0.0, "float", ("LSV",), group="calculation", label="Manual Rs"),
    GuiParamSpec("ir_linear_points", 10, "int", ("LSV",), group="advanced", label="iR high-frequency points"),
    GuiParamSpec(
        "overpotential_enabled",
        False,
        "bool",
        ("LSV",),
        group="calculation",
        label="Calculate overpotential",
        ui_control="checkbox",
    ),
    GuiParamSpec(
        "onset_enabled",
        False,
        "bool",
        ("LSV",),
        group="calculation",
        label="Calculate onset potential",
        ui_control="checkbox",
    ),
    GuiParamSpec("onset_current", "1.0", "str", ("LSV",), group="calculation", label="Onset current density"),
    GuiParamSpec("eq_potential", 0.0, "float", ("LSV",), group="calculation", label="Equilibrium potential"),
    GuiParamSpec(
        "halfwave_enabled",
        False,
        "bool",
        ("LSV",),
        group="calculation",
        label="Calculate half-wave potential",
        ui_control="checkbox",
    ),
    GuiParamSpec("halfwave_current", "", "str", ("LSV",), group="calculation", label="Half-wave current density"),
    GuiParamSpec(
        "lsv_quality_check",
        True,
        "bool",
        ("LSV",),
        group="quality",
        label="Enable LSV quality check",
        ui_control="checkbox",
    ),
    GuiParamSpec(
        "cv_match",
        "prefix",
        "str",
        ("CV",),
        group="source",
        label="CV match mode",
        ui_control="select",
        options=FILE_MATCH_MODES,
    ),
    GuiParamSpec("cv_prefix", "CV", "str", ("CV",), group="source", label="CV match pattern"),
    GuiParamSpec("cv_potential_column", 1, "int", ("CV",), group="source", label="CV potential column"),
    GuiParamSpec("cv_current_column", 2, "int", ("CV",), group="source", label="CV current column"),
    GuiParamSpec(
        "cv_potential_unit",
        "v",
        "str",
        ("CV",),
        group="source",
        label="CV potential unit",
        ui_control="select",
        options=("v", "mv"),
    ),
    GuiParamSpec(
        "cv_current_unit",
        "a",
        "str",
        ("CV",),
        group="source",
        label="CV current unit",
        ui_control="select",
        options=("a", "ma", "ua"),
    ),
    GuiParamSpec("cv_title", "CV of {sample}", "str", ("CV",), group="plot_export", label="CV plot title"),
    GuiParamSpec("cv_xlabel", "Potential (V)", "str", ("CV",), group="plot_export", label="CV X-axis label"),
    GuiParamSpec("cv_ylabel", "Current (mA)", "str", ("CV",), group="plot_export", label="CV Y-axis label"),
    GuiParamSpec("cv_scan_rate_v_s", None, "float", ("CV",), group="calculation", label="CV scan rate (V/s)"),
    GuiParamSpec(
        "cv_peaks_enabled",
        False,
        "bool",
        ("CV",),
        group="calculation",
        label="Enable peak detection",
        ui_control="checkbox",
    ),
    GuiParamSpec("cv_peaks_smooth", 5, "int", ("CV",), group="calculation", label="Peak smoothing window"),
    GuiParamSpec("cv_peaks_min_height", 1.0, "float", ("CV",), group="calculation", label="Peak minimum height"),
    GuiParamSpec("cv_peaks_min_dist", 5, "int", ("CV",), group="calculation", label="Peak minimum distance"),
    GuiParamSpec("cv_peaks_max", 2, "int", ("CV",), group="calculation", label="Maximum peaks"),
    GuiParamSpec(
        "cv_cycle_plot_enabled",
        False,
        "bool",
        ("CV",),
        group="plot_export",
        label="Export selected CV cycles",
        ui_control="checkbox",
    ),
    GuiParamSpec(
        "cv_cycle_numbers",
        "",
        "str",
        ("CV",),
        empty_as_default=True,
        group="plot_export",
        label="Selected CV cycle numbers",
    ),
    GuiParamSpec(
        "cv_cycle_reversal_tolerance",
        None,
        "float",
        ("CV",),
        empty_as_default=True,
        group="plot_export",
        label="CV cycle reversal tolerance",
    ),
    GuiParamSpec(
        "cv_cycle_min_segment_points", 3, "int", ("CV",), group="plot_export", label="CV cycle minimum segment points"
    ),
    GuiParamSpec(
        "cv_quality_check",
        True,
        "bool",
        ("CV",),
        group="quality",
        label="Enable CV quality check",
        ui_control="checkbox",
    ),
    GuiParamSpec(
        "plot_nyquist", True, "bool", ("EIS",), group="plot_export", label="Export Nyquist plot", ui_control="checkbox"
    ),
    GuiParamSpec(
        "plot_bode", False, "bool", ("EIS",), group="plot_export", label="Export Bode plot", ui_control="checkbox"
    ),
    GuiParamSpec(
        "eis_randles_fit",
        False,
        "bool",
        ("EIS",),
        group="calculation",
        label="Enable equivalent circuit fitting",
        ui_control="checkbox",
    ),
    GuiParamSpec(
        "eis_circuit_model",
        "randles_rc",
        "str",
        ("EIS",),
        group="calculation",
        label="Equivalent circuit model",
        ui_control="select",
        options=("randles_rc", "randles_cpe", "randles_warburg_rc", "randles_warburg_cpe", "two_time_constants_rc", "two_time_constants_cpe"),
    ),
    GuiParamSpec(
        "eis_fit_min_r2",
        0.5,
        "float",
        ("EIS",),
        group="calculation",
        label="Minimum accepted fit R2",
    ),
    GuiParamSpec("eis_fit_frequency_min_hz", None, "float", ("EIS",), empty_as_default=True, group="calculation", label="Minimum frequency (Hz)", help_text="Strictly positive inclusive bound; empty uses all available lower frequencies."),
    GuiParamSpec("eis_fit_frequency_max_hz", None, "float", ("EIS",), empty_as_default=True, group="calculation", label="Maximum frequency (Hz)", help_text="Strictly positive inclusive bound; empty uses all available higher frequencies."),
    GuiParamSpec("eis_fit_weighting", "uniform", "str", ("EIS",), group="calculation", label="Fit weighting", ui_control="select", options=("uniform", "modulus")),
    GuiParamSpec("eis_kk_check", False, "bool", ("EIS",), group="quality", label="Enable KK consistency check", ui_control="checkbox"),
    GuiParamSpec("plot_eis_residuals", True, "bool", ("EIS",), group="plot_export", label="Export EIS residuals when fitting or KK is enabled", ui_control="checkbox"),
    GuiParamSpec(
        "ecsa_match",
        "prefix",
        "str",
        ("ECSA",),
        group="source",
        label="ECSA match mode",
        ui_control="select",
        options=FILE_MATCH_MODES,
    ),
    GuiParamSpec("ecsa_prefix", "ECSA", "str", ("ECSA",), group="source", label="ECSA match pattern"),
    GuiParamSpec("ecsa_potential_column", 1, "int", ("ECSA",), group="source", label="ECSA potential column"),
    GuiParamSpec("ecsa_current_column", 2, "int", ("ECSA",), group="source", label="ECSA current column"),
    GuiParamSpec(
        "ecsa_potential_unit",
        "v",
        "str",
        ("ECSA",),
        group="source",
        label="ECSA potential unit",
        ui_control="select",
        options=("v", "mv"),
    ),
    GuiParamSpec(
        "ecsa_current_unit",
        "a",
        "str",
        ("ECSA",),
        group="source",
        label="ECSA current unit",
        ui_control="select",
        options=("a", "ma", "ua"),
    ),
    GuiParamSpec("ecsa_title", "ECSA of {sample}", "str", ("ECSA",), group="plot_export", label="ECSA plot title"),
    GuiParamSpec("ecsa_xlabel", "Scan rate v (V/s)", "str", ("ECSA",), group="plot_export", label="ECSA X-axis label"),
    GuiParamSpec("ecsa_ylabel", "Delta J (mA/cm2)", "str", ("ECSA",), group="plot_export", label="ECSA Y-axis label"),
    GuiParamSpec("ecsa_ev", 0.10, "float", ("ECSA",), group="calculation", label="Evaluation potential"),
    GuiParamSpec("ecsa_last_n", 1, "int", ("ECSA",), group="calculation", label="Last cycles used"),
    GuiParamSpec(
        "ecsa_avg_last_n",
        False,
        "bool",
        ("ECSA",),
        group="calculation",
        label="Average last cycles",
        ui_control="checkbox",
    ),
    GuiParamSpec("ecsa_cs_value", 40.0, "float", ("ECSA",), group="calculation", label="Specific capacitance value"),
    GuiParamSpec(
        "ecsa_cs_unit",
        "uF/cm2",
        "str",
        ("ECSA",),
        group="calculation",
        label="Specific capacitance unit",
        ui_control="select",
        options=("uF/cm2", "mF/cm2"),
    ),
    GuiParamSpec(
        "ecsa_use_abs_delta",
        True,
        "bool",
        ("ECSA",),
        group="calculation",
        label="Use absolute delta current",
        ui_control="checkbox",
    ),
    GuiParamSpec(
        "coupled_input_mode",
        "product_table",
        "str",
        ("COUPLED",),
        group="source",
        label="COUPLED input mode",
        ui_control="select",
        options=COUPLED_INPUT_MODES,
    ),
    GuiParamSpec(
        "coupled_products_file",
        "",
        "str",
        ("COUPLED",),
        empty_as_default=True,
        group="source",
        label="Product quantification table",
        required=True,
    ),
    GuiParamSpec(
        "coupled_products_sheet",
        0,
        "raw",
        ("COUPLED",),
        empty_as_default=True,
        group="source",
        label="Product table sheet",
    ),
    GuiParamSpec(
        "coupled_peak_method_source",
        None,
        "str",
        ("COUPLED",),
        group="source",
        label="FE peak method source",
        ui_control="select",
        options=COUPLED_PEAK_METHOD_SOURCES,
        ui_default="panel",
    ),
    GuiParamSpec(
        "coupled_peak_method_file",
        "",
        "str",
        ("COUPLED",),
        empty_as_default=True,
        group="source",
        label="FE peak method file",
    ),
    GuiParamSpec(
        "coupled_peak_method", None, "raw", ("COUPLED",), group="source", label="FE peak method configuration"
    ),
    GuiParamSpec(
        "fe_peak_auto_locate",
        True,
        "bool",
        ("COUPLED",),
        group="calculation",
        label="Automatically locate peaks",
        ui_control="checkbox",
    ),
    GuiParamSpec(
        "fe_peak_reference_align",
        True,
        "bool",
        ("COUPLED",),
        group="calculation",
        label="Align peaks using internal standard",
        ui_control="checkbox",
    ),
    GuiParamSpec(
        "fe_peak_fit_enabled",
        False,
        "bool",
        ("COUPLED",),
        group="calculation",
        label="Use constrained peak fitting",
        ui_control="checkbox",
    ),
    GuiParamSpec(
        "fe_peak_search_tolerance", 0.08, "float", ("COUPLED",), group="calculation", label="Peak search tolerance"
    ),
    GuiParamSpec(
        "fe_peak_window_left", 0.05, "float", ("COUPLED",), group="calculation", label="Peak window left width"
    ),
    GuiParamSpec(
        "fe_peak_window_right", 0.05, "float", ("COUPLED",), group="calculation", label="Peak window right width"
    ),
    GuiParamSpec(
        "fe_peak_min_detection_snr", 3.0, "float", ("COUPLED",), group="quality", label="Minimum detection SNR"
    ),
    GuiParamSpec(
        "fe_peak_min_quantification_snr",
        10.0,
        "float",
        ("COUPLED",),
        group="quality",
        label="Minimum quantification SNR",
    ),
    GuiParamSpec(
        "coupled_results_csv_filename",
        "coupled_results.csv",
        "str",
        ("COUPLED",),
        empty_as_default=True,
        group="plot_export",
        label="COUPLED result CSV filename",
    ),
)


def normalize_data_type(value: Any) -> str:
    key = str(value or "").strip().upper()
    return DATA_TYPE_ALIASES.get(key, key)


def get_module_spec(data_type: str | ProcessingModuleSpec) -> ProcessingModuleSpec:
    if isinstance(data_type, ProcessingModuleSpec):
        return data_type
    key = normalize_data_type(data_type)
    try:
        return PROCESSING_MODULE_BY_KEY[key]
    except KeyError as exc:
        raise KeyError(f"Unsupported processing module: {data_type}") from exc


def enabled_flags_for_data_types(data_types: Sequence[str]) -> dict[str, bool]:
    selected = {normalize_data_type(item) for item in data_types}
    return {spec.enabled_key: spec.key in selected for spec in PROCESSING_MODULES}


def numeric_param_specs_for(data_types: Sequence[str]) -> tuple[NumericParamSpec, ...]:
    selected = {normalize_data_type(item) for item in data_types}
    return tuple(spec for spec in NUMERIC_PARAM_SPECS if spec.data_type is None or spec.data_type in selected)


def gui_param_specs_for(data_types: Sequence[str]) -> tuple[GuiParamSpec, ...]:
    selected = {normalize_data_type(item) for item in data_types}
    return tuple(
        spec for spec in GUI_PARAM_SPECS if spec.data_types is None or any(item in selected for item in spec.data_types)
    )


def enabled_by_gui_vars(
    gui_vars: Mapping[str, Any],
    *,
    matchable_only: bool = False,
) -> dict[str, bool]:
    specs = FILE_MATCH_MODULE_SPECS if matchable_only else PROCESSING_MODULES
    return {spec.key: as_bool(gui_vars.get(spec.enabled_key, False), False) for spec in specs}


def get_match_config(
    gui_vars: Mapping[str, Any],
    data_type: str | ProcessingModuleSpec,
) -> tuple[str, str]:
    spec = get_module_spec(data_type)
    if not spec.has_file_match:
        raise ValueError(f"{spec.key} does not use filename matching")
    match_mode_key = spec.match_mode_key
    match_value_key = spec.match_value_key
    if match_mode_key is None or match_value_key is None:
        raise ValueError(f"{spec.key} does not use filename matching")
    mode = str(gui_vars.get(match_mode_key, spec.default_match_mode) or spec.default_match_mode)
    pattern = str(gui_vars.get(match_value_key, spec.default_match_value) or spec.default_match_value)
    return mode.strip().lower(), pattern.strip()


def default_matched_counts() -> dict[str, int]:
    return {spec.key: 0 for spec in PROCESSING_MODULES}


def _schema_value_type(gui_spec: GuiParamSpec | None, numeric_spec: NumericParamSpec | None) -> str:
    if numeric_spec and numeric_spec.integer_only:
        return "integer"
    if numeric_spec:
        return "number"
    if not gui_spec:
        return "any"
    return {
        "bool": "boolean",
        "int": "integer",
        "float": "number",
        "str": "string",
        "raw": "any",
    }.get(gui_spec.value_type, "any")


def _default_ui_control(value_type: str, options: Sequence[Any] = ()) -> str:
    if options:
        return "select"
    if value_type == "boolean":
        return "checkbox"
    if value_type in {"integer", "number"}:
        return "number"
    return "text"


def _group_descriptor(group_key: str) -> dict[str, Any]:
    spec = PARAMETER_GROUP_BY_KEY.get(group_key) or ParameterGroupSpec(group_key, group_key, order=999)
    return {
        "key": spec.key,
        "label": spec.label,
        "description": spec.description,
        "order": spec.order,
    }


def parameter_group_descriptors() -> list[dict[str, Any]]:
    return [_group_descriptor(spec.key) for spec in sorted(PARAMETER_GROUPS, key=lambda item: item.order)]


def _selected_data_types(data_types: Sequence[str] | None) -> list[str]:
    if data_types is None:
        return list(SUPPORTED_DATA_TYPES)
    selected: list[str] = []
    for item in data_types:
        key = normalize_data_type(item)
        if key not in PROCESSING_MODULE_BY_KEY:
            raise KeyError(f"Unsupported processing module: {item}")
        if key not in selected:
            selected.append(key)
    return selected


def processing_module_descriptors(data_types: Sequence[str] | None = None) -> list[dict[str, Any]]:
    selected = set(_selected_data_types(data_types))
    descriptors: list[dict[str, Any]] = []
    for spec in PROCESSING_MODULES:
        if spec.key not in selected:
            continue
        entry: dict[str, Any] = {
            "key": spec.key,
            "display_name": spec.title,
            "enabled_key": spec.enabled_key,
            "summary": spec.summary,
            "capabilities": list(spec.capabilities),
            "result_kinds": list(spec.result_kinds),
            "input_kind": spec.input_kind,
            "has_file_match": spec.has_file_match,
            "aliases": list(spec.aliases),
        }
        if spec.has_file_match:
            entry["file_match"] = {
                "mode_key": spec.match_mode_key,
                "value_key": spec.match_value_key,
                "default_mode": spec.default_match_mode,
                "default_value": spec.default_match_value,
            }
        descriptors.append(entry)
    return descriptors


def processing_parameter_schema(data_types: Sequence[str] | None = None) -> dict[str, Any]:
    selected = _selected_data_types(data_types)
    numeric_by_key = {spec.key: spec for spec in numeric_param_specs_for(selected)}
    gui_by_key = {spec.key: spec for spec in gui_param_specs_for(selected)}
    ordered_keys: list[str] = []
    for spec in gui_param_specs_for(selected):
        if spec.key not in ordered_keys:
            ordered_keys.append(spec.key)
    for spec in numeric_param_specs_for(selected):
        if spec.key not in ordered_keys:
            ordered_keys.append(spec.key)

    parameters: list[dict[str, Any]] = []
    for key in ordered_keys:
        gui_spec = gui_by_key.get(key)
        numeric_spec = numeric_by_key.get(key)
        value_type = _schema_value_type(gui_spec, numeric_spec)
        data_type_values = list(gui_spec.data_types or ()) if gui_spec else []
        if not data_type_values and numeric_spec and numeric_spec.data_type:
            data_type_values = [numeric_spec.data_type]
        group_key = (
            gui_spec.group
            if gui_spec and gui_spec.group
            else numeric_spec.group
            if numeric_spec and numeric_spec.group
            else "basic"
        )
        group = _group_descriptor(group_key)
        default = gui_spec.default if gui_spec else numeric_spec.default if numeric_spec else None
        label = (
            gui_spec.label
            if gui_spec and gui_spec.label
            else numeric_spec.label
            if numeric_spec and numeric_spec.label
            else key
        )
        options = list(gui_spec.options or ()) if gui_spec else []
        ui_control = (
            gui_spec.ui_control
            if gui_spec and gui_spec.ui_control
            else numeric_spec.ui_control
            if numeric_spec and numeric_spec.ui_control
            else _default_ui_control(value_type, options)
        )
        parameters.append(
            {
                "key": key,
                "value_type": value_type,
                "default": default,
                "ui_default": (gui_spec.ui_default if gui_spec and gui_spec.ui_default is not None else default),
                "data_types": data_type_values,
                "scope": "module" if data_type_values else "common",
                "empty_as_default": bool(gui_spec.empty_as_default) if gui_spec else False,
                "min_value": numeric_spec.min_value if numeric_spec else None,
                "max_value": numeric_spec.max_value if numeric_spec else None,
                "group": group["key"],
                "group_label": group["label"],
                "label": label,
                "required": bool(
                    (gui_spec.required if gui_spec else False) or (numeric_spec.required if numeric_spec else False)
                ),
                "help_text": (
                    gui_spec.help_text
                    if gui_spec and gui_spec.help_text
                    else numeric_spec.help_text
                    if numeric_spec and numeric_spec.help_text
                    else ""
                ),
                "ui_control": ui_control,
                "options": options,
            }
        )

    def grouped(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        known = sorted(PARAMETER_GROUPS, key=lambda item: item.order)
        for group_spec in known:
            group_items = [item for item in items if item.get("group") == group_spec.key]
            if group_items:
                descriptor = _group_descriptor(group_spec.key)
                descriptor["parameters"] = group_items
                output.append(descriptor)
        unknown_keys = sorted({str(item.get("group")) for item in items} - {item.key for item in known})
        for group_key in unknown_keys:
            group_items = [item for item in items if item.get("group") == group_key]
            descriptor = _group_descriptor(group_key)
            descriptor["parameters"] = group_items
            output.append(descriptor)
        return output

    common_parameters = [item for item in parameters if item.get("scope") == "common"]
    module_parameters: dict[str, Any] = {}
    for module_key in selected:
        module_items = [item for item in parameters if module_key in item.get("data_types", [])]
        module_parameters[module_key] = {
            "parameters": module_items,
            "groups": grouped(module_items),
        }

    return {
        "schema_version": PARAM_SCHEMA_VERSION,
        "supported_data_types": list(SUPPORTED_DATA_TYPES),
        "data_types": selected,
        "modules": processing_module_descriptors(selected),
        "parameter_groups": parameter_group_descriptors(),
        "common_parameters": {
            "parameters": common_parameters,
            "groups": grouped(common_parameters),
        },
        "module_parameters": module_parameters,
        "parameters": parameters,
        "presets": {
            "ecsa_material_default": "IrO2",
            "reference_electrodes": [
                {
                    "key": spec.key,
                    "label": spec.label,
                    "potential_v": spec.potential_v,
                }
                for spec in REFERENCE_ELECTRODE_PRESETS
            ],
            "ecsa_materials": [
                {
                    "key": spec.key,
                    "label": spec.label,
                    "specific_capacitance_uf_cm2": spec.specific_capacitance_uf_cm2,
                }
                for spec in ECSA_MATERIAL_PRESETS
            ],
        },
    }


def parameter_defaults_for(
    data_types: Sequence[str] | None = None,
    *,
    include_common: bool = True,
) -> dict[str, Any]:
    """Return schema defaults for the selected processing modules."""
    defaults: dict[str, Any] = {}
    for parameter in processing_parameter_schema(data_types)["parameters"]:
        if not include_common and parameter.get("scope") == "common":
            continue
        default = parameter.get("default")
        if default is None:
            continue
        key = str(parameter.get("key"))
        if key:
            defaults[key] = default
    return defaults


def module_parameter_defaults(data_type: str, *, include_common: bool = True) -> dict[str, Any]:
    return parameter_defaults_for([data_type], include_common=include_common)


def merge_parameter_defaults(
    data_types: Sequence[str] | str,
    params: Mapping[str, Any] | None,
    *,
    include_common: bool = True,
) -> dict[str, Any]:
    selected = [data_types] if isinstance(data_types, str) else list(data_types)
    merged = parameter_defaults_for(selected, include_common=include_common)
    if params:
        merged.update(dict(params))
    return merged
