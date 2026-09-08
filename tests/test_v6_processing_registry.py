from electrochem_v6.core.processing_registry import (
    SUPPORTED_DATA_TYPES,
    default_matched_counts,
    enabled_by_gui_vars,
    enabled_flags_for_data_types,
    get_match_config,
    gui_param_specs_for,
    merge_parameter_defaults,
    module_parameter_defaults,
    normalize_data_type,
    numeric_param_specs_for,
    parameter_defaults_for,
    parameter_group_descriptors,
    processing_module_descriptors,
    processing_parameter_schema,
)


def test_registry_exports_stable_type_order_and_aliases():
    assert SUPPORTED_DATA_TYPES == ("LSV", "CV", "EIS", "ECSA", "COUPLED")
    assert normalize_data_type("fe") == "COUPLED"
    assert normalize_data_type("selectivity") == "COUPLED"
    assert normalize_data_type("LSV") == "LSV"


def test_registry_describes_module_capabilities_and_inputs():
    descriptors = {item["key"]: item for item in processing_module_descriptors(["LSV", "FE"])}

    assert descriptors["LSV"]["display_name"] == "LSV"
    assert descriptors["LSV"]["input_kind"] == "data_files"
    assert descriptors["LSV"]["capabilities"] == [
        "polarization_curve",
        "tafel",
        "target_current",
        "quality_check",
    ]
    assert descriptors["LSV"]["file_match"]["default_value"] == "LSV"

    assert descriptors["COUPLED"]["display_name"] == "COUPLED/FE"
    assert descriptors["COUPLED"]["input_kind"] == "product_table"
    assert descriptors["COUPLED"]["has_file_match"] is False
    assert descriptors["COUPLED"]["aliases"] == [
        "FE",
        "FARADAIC",
        "FARADAIC_EFFICIENCY",
        "SELECTIVITY",
    ]


def test_registry_builds_enabled_flags_and_match_config():
    flags = enabled_flags_for_data_types(["LSV", "FE"])
    assert flags == {
        "lsv_enabled": True,
        "cv_enabled": False,
        "eis_enabled": False,
        "ecsa_enabled": False,
        "coupled_enabled": True,
    }

    gui_vars = {
        **flags,
        "lsv_match": "contains",
        "lsv_prefix": "HER",
    }
    assert enabled_by_gui_vars(gui_vars)["LSV"] is True
    assert enabled_by_gui_vars(gui_vars)["COUPLED"] is True
    assert enabled_by_gui_vars(gui_vars, matchable_only=True) == {
        "LSV": True,
        "CV": False,
        "EIS": False,
        "ECSA": False,
    }
    assert get_match_config(gui_vars, "LSV") == ("contains", "HER")
    assert get_match_config({}, "EIS") == ("prefix", "EIS")


def test_default_matched_counts_cover_all_supported_types():
    assert default_matched_counts() == {
        "LSV": 0,
        "CV": 0,
        "EIS": 0,
        "ECSA": 0,
        "COUPLED": 0,
    }


def test_numeric_param_specs_follow_selected_modules():
    cv_keys = {spec.key for spec in numeric_param_specs_for(["CV"])}
    assert {"font_size", "area", "potential_offset", "cv_line_width", "cv_peaks_max"} <= cv_keys
    assert "lsv_line_width" not in cv_keys
    assert "ecsa_cs_value" not in cv_keys

    lsv_coupled_keys = {spec.key for spec in numeric_param_specs_for(["LSV", "FE"])}
    assert "lsv_line_width" in lsv_coupled_keys
    assert "ir_linear_points" in lsv_coupled_keys
    assert "cv_peaks_max" not in lsv_coupled_keys


def test_gui_param_specs_follow_selected_modules():
    lsv_keys = {spec.key for spec in gui_param_specs_for(["LSV"])}
    assert {
        "plot_grid",
        "use_abs_current",
        "lsv_target_current",
        "lsv_potential_column",
        "lsv_current_unit",
        "ir_eis_match",
        "ir_eis_zimag_convention",
    } <= lsv_keys
    assert "eis_match" not in lsv_keys
    assert "cv_match" not in lsv_keys
    assert "ecsa_ev" not in lsv_keys

    ecsa_coupled_keys = {spec.key for spec in gui_param_specs_for(["ECSA", "FE"])}
    assert "ecsa_ev" in ecsa_coupled_keys
    assert "coupled_results_csv_filename" in ecsa_coupled_keys
    assert "lsv_target_current" not in ecsa_coupled_keys


def test_parameter_defaults_follow_selected_modules():
    defaults = parameter_defaults_for(["LSV", "FE"])

    assert defaults["area"] == 1.0
    assert defaults["font_size"] == 12
    assert defaults["lsv_target_current"] == "10,100"
    assert defaults["coupled_results_csv_filename"] == "coupled_results.csv"
    assert "cv_prefix" not in defaults

    cv_defaults = module_parameter_defaults("CV", include_common=False)
    assert cv_defaults["cv_prefix"] == "CV"
    assert "area" not in cv_defaults

    merged = merge_parameter_defaults(["LSV"], {"lsv_target_current": "5", "area": 2.5})
    assert merged["lsv_target_current"] == "5"
    assert merged["area"] == 2.5


def test_processing_parameter_schema_describes_selected_modules_and_bounds():
    schema = processing_parameter_schema(["LSV", "FE"])

    assert schema["schema_version"] == "1.9"
    assert schema["data_types"] == ["LSV", "COUPLED"]
    modules = {item["key"]: item for item in schema["modules"]}
    assert modules["LSV"]["file_match"]["default_value"] == "LSV"
    assert modules["LSV"]["input_kind"] == "data_files"
    assert "target_current" in modules["LSV"]["capabilities"]
    assert modules["COUPLED"]["has_file_match"] is False
    assert modules["COUPLED"]["input_kind"] == "product_table"
    assert "faradaic_efficiency" in modules["COUPLED"]["capabilities"]
    assert "peak_quantification" in modules["COUPLED"]["capabilities"]

    params = {item["key"]: item for item in schema["parameters"]}
    assert params["lsv_target_current"]["default"] == "10,100"
    assert all("payload_key" not in item for item in params.values())
    assert params["ir_linear_points"]["value_type"] == "integer"
    assert params["ir_linear_points"]["min_value"] == 2.0
    assert params["ir_source"]["options"] == ["eis", "manual"]
    assert params["lsv_current_unit"]["options"] == ["a", "ma", "ua"]
    assert params["ir_eis_zimag_convention"]["options"] == ["z_imaginary", "negative_z_imaginary"]
    assert params["ir_eis_search_scope"]["options"] == [
        "same_dir",
        "same_then_root",
        "recursive_root",
        "specified_file",
    ]
    assert params["coupled_input_mode"]["options"] == ["product_table", "peak_analysis"]
    assert params["coupled_peak_method_source"]["default"] is None
    assert params["coupled_peak_method_source"]["ui_default"] == "panel"
    assert params["fe_peak_min_quantification_snr"]["default"] == 10.0
    assert params["potential_mode"]["options"] == ["manual", "formula_rhe"]
    assert params["rhe_ph"]["min_value"] == 0.0
    assert params["rhe_ph"]["max_value"] == 14.0
    assert params["rhe_temperature_c"]["default"] == 25.0
    assert params["reference_electrode_preset"]["default"] == "agcl_sat_kcl"
    assert params["tafel_enabled"]["default"] is False
    assert params["lsv_title"]["default"] == "LSV of {sample}"
    assert "cv_peaks_max" not in params

    presets = schema["presets"]
    assert presets["ecsa_material_default"] == "IrO2"
    reference_presets = {item["key"]: item for item in presets["reference_electrodes"]}
    assert reference_presets["agcl_sat_kcl"]["potential_v"] == 0.197
    assert reference_presets["custom"]["potential_v"] is None

    cv_params = {item["key"]: item for item in processing_parameter_schema(["CV"])["parameters"]}
    assert cv_params["cv_cycle_min_segment_points"]["default"] == 3
    assert cv_params["cv_cycle_reversal_tolerance"]["default"] is None


def test_parameter_schema_groups_common_and_module_parameters():
    schema = processing_parameter_schema(["LSV", "CV", "FE"])

    assert [item["key"] for item in parameter_group_descriptors()] == [
        "source",
        "basic",
        "calculation",
        "quality",
        "plot_export",
        "advanced",
    ]
    assert [item["key"] for item in schema["parameter_groups"]] == [
        "source",
        "basic",
        "calculation",
        "quality",
        "plot_export",
        "advanced",
    ]

    common = schema["common_parameters"]
    common_keys = {item["key"] for item in common["parameters"]}
    assert {"area", "potential_offset", "font_size", "plot_grid"} <= common_keys

    lsv_groups = {item["key"]: item for item in schema["module_parameters"]["LSV"]["groups"]}
    assert {"source", "basic", "calculation", "quality", "plot_export", "advanced"} <= set(lsv_groups)
    lsv_quality_keys = {item["key"] for item in lsv_groups["quality"]["parameters"]}
    assert {"lsv_quality_check", "lsv_quality_min_points_issue", "lsv_quality_noise_critical"} <= lsv_quality_keys

    cv_calculation_keys = {
        item["key"]
        for item in {group["key"]: group for group in schema["module_parameters"]["CV"]["groups"]}["calculation"]["parameters"]
    }
    assert {"cv_scan_rate_v_s", "cv_peaks_enabled", "cv_peaks_smooth", "cv_peaks_max"} <= cv_calculation_keys

    coupled_source_keys = {
        item["key"]
        for item in {group["key"]: group for group in schema["module_parameters"]["COUPLED"]["groups"]}["source"]["parameters"]
    }
    assert "coupled_products_file" in coupled_source_keys


def test_parameter_schema_exposes_ui_metadata_and_quality_thresholds():
    schema = processing_parameter_schema(["LSV", "ECSA", "FE"])
    params = {item["key"]: item for item in schema["parameters"]}

    assert params["lsv_match"]["group"] == "source"
    assert params["lsv_match"]["ui_control"] == "select"
    assert params["lsv_match"]["options"] == ["prefix", "suffix", "contains", "regex"]
    assert params["lsv_target_current"]["group"] == "basic"
    assert params["lsv_target_current"]["label"] == "Target current density"
    assert params["lsv_quality_min_points_issue"]["group"] == "quality"
    assert params["lsv_quality_min_points_issue"]["default"] == 20
    assert params["lsv_quality_min_points_issue"]["value_type"] == "integer"
    assert params["ecsa_cs_unit"]["options"] == ["uF/cm2", "mF/cm2"]
    assert params["coupled_products_file"]["required"] is True
