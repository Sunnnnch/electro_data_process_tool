(function () {
  "use strict";

  const API = window.ElectrochemApi || { fetch: (...args) => window.fetch(...args) };
  let cachedSchema = null;

  // This map is presentation-only. Defaults, value types, bounds, and options
  // are supplied by the backend schema.
  const CONTROL_BINDINGS = Object.freeze({
    recursive_scan: "pro-recursive-scan",
    output_run_dir_enabled: "pro-output-run-dir",
    plot_grid: "pro-plot-grid",
    use_abs_current: "pro-use-abs-current",
    font_family: "plot-font-family",
    font_size: "plot-font-size",
    area: "pro-area",
    potential_mode: "pro-potential-mode",
    potential_offset: "pro-offset",
    rhe_ph: "pro-rhe-ph",
    rhe_temperature_c: "pro-rhe-temperature",
    reference_electrode_preset: "pro-ref-preset",
    reference_electrode_potential: "pro-ref-custom",

    lsv_target_current: "pro-lsv-target",
    tafel_range: "pro-lsv-tafel",
    tafel_enabled: "pro-lsv-tafel-enabled",
    lsv_match: "pro-lsv-match",
    lsv_prefix: "pro-lsv-prefix",
    lsv_potential_column: "pro-lsv-potential-column",
    lsv_current_column: "pro-lsv-current-column",
    lsv_potential_unit: "pro-lsv-potential-unit",
    lsv_current_unit: "pro-lsv-current-unit",
    lsv_title: "pro-lsv-title",
    lsv_xlabel: "pro-lsv-xlabel",
    lsv_ylabel: "pro-lsv-ylabel",
    lsv_line_width: "pro-lsv-line-width",
    lsv_mark_targets: "pro-lsv-mark-targets",
    lsv_export_data: "pro-lsv-export-data",
    lsv_combine_all: "pro-lsv-combine-all",
    export_tafel_plot: "pro-lsv-export-tafel",
    lsv_quality_check: "pro-lsv-quality-check",
    lsv_quality_min_points_issue: "pro-lsv-quality-min-points-issue",
    lsv_quality_min_points_warning: "pro-lsv-quality-min-points-warning",
    lsv_quality_outlier_warning_pct: "pro-lsv-quality-outlier-warning-pct",
    lsv_quality_min_potential_span: "pro-lsv-quality-min-potential-span",
    lsv_quality_noise_warning: "pro-lsv-quality-noise-warning",
    lsv_quality_noise_critical: "pro-lsv-quality-noise-critical",
    lsv_quality_jump_warning: "pro-lsv-quality-jump-warning",
    lsv_quality_jump_critical: "pro-lsv-quality-jump-critical",
    lsv_quality_local_variation_factor: "pro-lsv-quality-local-factor",
    ir_compensation_enabled: "pro-lsv-ir-enabled",
    ir_source: "pro-lsv-ir-source",
    ir_eis_search_scope: "pro-lsv-ir-scope",
    ir_eis_file: "pro-lsv-ir-eis-file",
    ir_eis_match: "pro-lsv-ir-eis-match",
    ir_eis_pattern: "pro-lsv-ir-eis-pattern",
    ir_method: "pro-lsv-ir-method",
    ir_validation_mode: "pro-lsv-ir-validation",
    ir_manual_ohm: "pro-lsv-ir-manual",
    ir_linear_points: "pro-lsv-ir-points",
    ir_eis_frequency_column: "pro-ir-eis-frequency-column",
    ir_eis_zreal_column: "pro-ir-eis-zreal-column",
    ir_eis_zimag_column: "pro-ir-eis-zimag-column",
    ir_eis_frequency_unit: "pro-ir-eis-frequency-unit",
    ir_eis_impedance_unit: "pro-ir-eis-impedance-unit",
    ir_eis_zimag_convention: "pro-ir-eis-zimag-convention",
    overpotential_enabled: "pro-lsv-overpotential-enabled",
    eq_potential: "pro-lsv-eq-potential",
    onset_enabled: "pro-lsv-onset-enabled",
    onset_current: "pro-lsv-onset-current",
    halfwave_enabled: "pro-lsv-halfwave-enabled",
    halfwave_current: "pro-lsv-halfwave-current",

    cv_match: "pro-cv-match",
    cv_prefix: "pro-cv-prefix",
    cv_potential_column: "pro-cv-potential-column",
    cv_current_column: "pro-cv-current-column",
    cv_potential_unit: "pro-cv-potential-unit",
    cv_current_unit: "pro-cv-current-unit",
    cv_title: "pro-cv-title",
    cv_xlabel: "pro-cv-xlabel",
    cv_ylabel: "pro-cv-ylabel",
    cv_line_width: "pro-cv-line-width",
    cv_scan_rate_v_s: "pro-cv-scan-rate",
    cv_peaks_enabled: "pro-cv-peaks-enabled",
    cv_peaks_smooth: "pro-cv-peaks-smooth",
    cv_peaks_min_height: "pro-cv-peaks-height",
    cv_peaks_min_dist: "pro-cv-peaks-dist",
    cv_peaks_max: "pro-cv-peaks-max",
    cv_cycle_plot_enabled: "pro-cv-cycle-plot-enabled",
    cv_cycle_numbers: "pro-cv-cycle-numbers",
    cv_cycle_reversal_tolerance: "pro-cv-cycle-reversal-tolerance",
    cv_cycle_min_segment_points: "pro-cv-cycle-min-segment-points",
    cv_quality_check: "pro-cv-quality-check",
    cv_quality_min_points_warning: "pro-cv-quality-min-points-warning",
    cv_quality_cycle_tolerance: "pro-cv-quality-cycle-tolerance",

    eis_match: "pro-eis-match",
    eis_prefix: "pro-eis-prefix",
    eis_frequency_column: "pro-eis-frequency-column",
    eis_zreal_column: "pro-eis-zreal-column",
    eis_zimag_column: "pro-eis-zimag-column",
    eis_frequency_unit: "pro-eis-frequency-unit",
    eis_impedance_unit: "pro-eis-impedance-unit",
    eis_zimag_convention: "pro-eis-zimag-convention",
    eis_title: "pro-eis-title",
    eis_xlabel: "pro-eis-xlabel",
    eis_ylabel: "pro-eis-ylabel",
    eis_line_width: "pro-eis-line-width",
    plot_nyquist: "pro-eis-plot-nyquist",
    plot_bode: "pro-eis-plot-bode",
    eis_randles_fit: "pro-eis-randles-fit",
    eis_circuit_model: "pro-eis-circuit-model",
    eis_fit_min_r2: "pro-eis-fit-min-r2",
    eis_fit_frequency_min_hz: "pro-eis-fit-frequency-min-hz",
    eis_fit_frequency_max_hz: "pro-eis-fit-frequency-max-hz",
    eis_fit_weighting: "pro-eis-fit-weighting",
    eis_kk_check: "pro-eis-kk-check",
    plot_eis_residuals: "pro-eis-plot-residuals",

    ecsa_match: "pro-ecsa-match",
    ecsa_prefix: "pro-ecsa-prefix",
    ecsa_potential_column: "pro-ecsa-potential-column",
    ecsa_current_column: "pro-ecsa-current-column",
    ecsa_potential_unit: "pro-ecsa-potential-unit",
    ecsa_current_unit: "pro-ecsa-current-unit",
    ecsa_title: "pro-ecsa-title",
    ecsa_xlabel: "pro-ecsa-xlabel",
    ecsa_ylabel: "pro-ecsa-ylabel",
    ecsa_line_width: "pro-ecsa-line-width",
    ecsa_ev: "pro-ecsa-ev",
    ecsa_last_n: "pro-ecsa-last-n",
    ecsa_avg_last_n: "pro-ecsa-avg-last-n",
    ecsa_cs_value: "pro-ecsa-cs-value",
    ecsa_cs_unit: "pro-ecsa-cs-unit",
    ecsa_use_abs_delta: "pro-ecsa-use-abs",

    coupled_input_mode: "pro-coupled-input-mode",
    coupled_products_file: "pro-coupled-products-file",
    coupled_products_sheet: "pro-coupled-products-sheet",
    coupled_peak_method_source: "pro-coupled-peak-method-source",
    coupled_peak_method_file: "pro-coupled-peak-method-file",
    fe_peak_auto_locate: "pro-fe-peak-auto-locate",
    fe_peak_reference_align: "pro-fe-peak-reference-align",
    fe_peak_fit_enabled: "pro-fe-peak-fit-enabled",
    fe_peak_search_tolerance: "pro-fe-peak-search-tolerance",
    fe_peak_window_left: "pro-fe-peak-window-left",
    fe_peak_window_right: "pro-fe-peak-window-right",
    fe_peak_min_detection_snr: "pro-fe-peak-min-detection-snr",
    fe_peak_min_quantification_snr: "pro-fe-peak-min-quantification-snr",
    coupled_results_csv_filename: "pro-coupled-results-csv",
  });

  async function load(dataTypes) {
    const query = new URLSearchParams();
    const selected = Array.isArray(dataTypes) ? dataTypes.filter(Boolean) : [];
    if (selected.length) query.set("data_types", selected.join(","));
    const url = `/api/v1/process/schema${query.toString() ? `?${query.toString()}` : ""}`;
    const resp = await API.fetch(url);
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || "Failed to load processing schema");
    }
    cachedSchema = data.schema || null;
    return cachedSchema;
  }

  function getCached() {
    return cachedSchema;
  }

  function getVersion(schema = cachedSchema) {
    return String(schema && schema.schema_version || "");
  }

  function paramMap(schema) {
    const params = schema && Array.isArray(schema.parameters) ? schema.parameters : [];
    return new Map(params.map((item) => [String(item.key || ""), item]));
  }

  function getParameter(schema, key) {
    return paramMap(schema).get(String(key || "")) || null;
  }

  function getDefault(schema, key, fallback) {
    const param = getParameter(schema, key);
    if (!param) return fallback;
    if (param.ui_default !== null && param.ui_default !== undefined) return param.ui_default;
    return param.default !== undefined ? param.default : fallback;
  }

  function moduleList(schema) {
    return schema && Array.isArray(schema.modules) ? schema.modules : [];
  }

  function moduleMap(schema) {
    const map = new Map();
    moduleList(schema).forEach((item) => {
      const key = String(item.key || "").trim().toUpperCase();
      if (!key) return;
      map.set(key, item);
      (Array.isArray(item.aliases) ? item.aliases : []).forEach((alias) => {
        const aliasKey = String(alias || "").trim().toUpperCase();
        if (aliasKey && !map.has(aliasKey)) map.set(aliasKey, item);
      });
    });
    return map;
  }

  function getModule(schema, dataType) {
    return moduleMap(schema).get(String(dataType || "").trim().toUpperCase()) || null;
  }

  function normalizeModuleKey(value) {
    return String(value || "").trim().toUpperCase();
  }

  function moduleDescriptionKey(key) {
    const normalized = normalizeModuleKey(key);
    return normalized ? `mode_${normalized.toLowerCase()}_desc` : "";
  }

  function buildModuleCards(schema, selectedTypes) {
    const modules = moduleMap(schema);
    const selected = new Set(
      (Array.isArray(selectedTypes) ? selectedTypes : []).map((item) => {
        const key = normalizeModuleKey(item);
        const module = modules.get(key);
        return module ? normalizeModuleKey(module.key) : key;
      })
    );
    return moduleList(schema).map((item) => {
      const key = normalizeModuleKey(item.key);
      return {
        key,
        cssClass: key ? `mode-${key.toLowerCase()}` : "",
        descriptionKey: moduleDescriptionKey(key),
        displayName: item.display_name || key,
        inputKind: item.input_kind || "data_files",
        selected: selected.has(key),
        summary: item.summary || "",
      };
    }).filter((item) => item.key);
  }

  function selectedModuleKeys(schema, selectedTypes) {
    const modules = moduleMap(schema);
    return new Set((Array.isArray(selectedTypes) ? selectedTypes : []).map((item) => {
      const key = normalizeModuleKey(item);
      const module = modules.get(key);
      return normalizeModuleKey(module ? module.key : key);
    }));
  }

  function isParameterSelected(param, selectedKeys) {
    const dataTypes = Array.isArray(param && param.data_types) ? param.data_types : [];
    return !dataTypes.length || dataTypes.some((item) => selectedKeys.has(normalizeModuleKey(item)));
  }

  function syncSelectOptions(el, options) {
    if (!el || String(el.tagName || "").toUpperCase() !== "SELECT" || !Array.isArray(options) || !options.length) return;
    const current = String(el.value || "");
    const existing = new Map(Array.from(el.options || []).map((option) => [String(option.value), option]));
    const fragment = document.createDocumentFragment();
    options.forEach((raw) => {
      const value = String(raw);
      const option = existing.get(value) || document.createElement("option");
      option.value = value;
      if (!option.textContent) option.textContent = value;
      fragment.appendChild(option);
    });
    el.replaceChildren(fragment);
    if (options.map(String).includes(current)) el.value = current;
  }

  function applyDefault(el, param, schemaVersion) {
    if (!el || !param) return;
    const defaultValue = param.ui_default !== null && param.ui_default !== undefined
      ? param.ui_default
      : param.default;
    if (defaultValue === null || defaultValue === undefined) return;
    const previousDefault = el.dataset.schemaDefault;
    const initialized = Boolean(el.dataset.schemaInitialized);
    const current = el.type === "checkbox" ? String(Boolean(el.checked)) : String(el.value || "");
    const shouldApply = !initialized || current === String(previousDefault ?? "");
    if (shouldApply) {
      if (el.type === "checkbox") el.checked = Boolean(defaultValue);
      else el.value = String(defaultValue);
    }
    el.dataset.schemaDefault = String(defaultValue);
    el.dataset.schemaInitialized = String(schemaVersion || "unknown");
  }

  function applyPresetSelect(el, entries, valueKey) {
    if (!el || !Array.isArray(entries) || !entries.length) return;
    const current = String(el.value || "");
    const existing = new Map(Array.from(el.options || []).map((option) => [String(option.value), option]));
    const fragment = document.createDocumentFragment();
    entries.forEach((entry) => {
      const key = String(entry && entry.key || "");
      if (!key) return;
      const option = existing.get(key) || document.createElement("option");
      option.value = key;
      if (!option.hasAttribute("data-i18n") || key !== "custom") {
        option.textContent = String(entry.label || key);
      }
      const value = entry[valueKey];
      if (value === null || value === undefined) option.removeAttribute("data-potential");
      else option.dataset.potential = String(value);
      fragment.appendChild(option);
    });
    el.replaceChildren(fragment);
    if (entries.some((entry) => String(entry.key) === current)) el.value = current;
  }

  function applyPresets(schema) {
    if (typeof document === "undefined") return;
    const presets = schema && schema.presets && typeof schema.presets === "object" ? schema.presets : {};
    applyPresetSelect(document.getElementById("pro-ref-preset"), presets.reference_electrodes, "potential_v");
    const materialSelect = document.getElementById("pro-ecsa-material");
    applyPresetSelect(materialSelect, presets.ecsa_materials, "specific_capacitance_uf_cm2");
    if (materialSelect && presets.ecsa_material_default) {
      materialSelect.value = String(presets.ecsa_material_default);
    }
  }

  function applyToControls(schema, elementMap = CONTROL_BINDINGS) {
    if (typeof document === "undefined") return;
    applyPresets(schema);
    const paramsByKey = paramMap(schema);
    Object.entries(elementMap || {}).forEach(([paramKey, elementId]) => {
      const param = paramsByKey.get(paramKey);
      const el = document.getElementById(elementId);
      if (!param || !el) return;
      el.dataset.schemaParam = paramKey;
      if (["integer", "number"].includes(param.value_type)) {
        el.setAttribute("inputmode", param.value_type === "integer" ? "numeric" : "decimal");
        if (param.min_value !== null && param.min_value !== undefined) el.setAttribute("min", String(param.min_value));
        else el.removeAttribute("min");
        if (param.max_value !== null && param.max_value !== undefined) el.setAttribute("max", String(param.max_value));
        else el.removeAttribute("max");
        if (!el.getAttribute("step")) el.setAttribute("step", param.value_type === "integer" ? "1" : "any");
      }
      syncSelectOptions(el, param.options);
      applyDefault(el, param, schema && schema.schema_version);
    });
    ["pro-eis-circuit-model", "pro-eis-randles-fit", "pro-eis-kk-check"].forEach((id) => {
      const control = document.getElementById(id);
      if (control && !control.dataset.eisBound) {
        control.addEventListener("change", syncEisControls);
        control.dataset.eisBound = "true";
      }
    });
    syncEisControls();
  }

  function syncEisControls() {
    if (typeof document === "undefined") return;
    const model = document.getElementById("pro-eis-circuit-model");
    document.querySelectorAll("[data-eis-model-hint]").forEach((hint) => {
      hint.hidden = hint.dataset.eisModelHint !== (model && model.value);
    });
    const residuals = document.getElementById("pro-eis-residual-options");
    if (residuals) {
      residuals.hidden = !["pro-eis-randles-fit", "pro-eis-kk-check"].some((id) => {
        const toggle = document.getElementById(id);
        return toggle && toggle.checked;
      });
      residuals.classList.toggle("hidden", residuals.hidden);
    }
  }

  function controlLabel(el, param) {
    if (typeof document !== "undefined" && el && el.id) {
      const label = document.querySelector(`label[for="${el.id}"]`);
      if (label && String(label.textContent || "").trim()) return String(label.textContent).trim();
    }
    return String(param && param.label || param && param.key || "Parameter");
  }

  function validationMessage(code, label, value, lang) {
    const zh = lang === "zh";
    if (code === "required") return zh ? `${label}不能为空` : `${label} is required`;
    if (code === "number") return zh ? `${label}必须是数字` : `${label} must be numeric`;
    if (code === "integer") return zh ? `${label}必须是整数` : `${label} must be an integer`;
    if (code === "min") return zh ? `${label}不能小于 ${value}` : `${label} must be >= ${value}`;
    if (code === "max") return zh ? `${label}不能大于 ${value}` : `${label} must be <= ${value}`;
    if (code === "option") return zh ? `${label}包含不支持的选项` : `${label} contains an unsupported option`;
    return zh ? `${label}无效` : `${label} is invalid`;
  }

  function validateControls(schema, selectedTypes, options = {}) {
    if (!schema) return [];
    const hasDocument = typeof document !== "undefined";
    const selected = selectedModuleKeys(schema, selectedTypes);
    const errors = [];
    (Array.isArray(schema.parameters) ? schema.parameters : []).forEach((param) => {
      if (!isParameterSelected(param, selected)) return;
      const elementId = (options.elementMap || CONTROL_BINDINGS)[param.key];
      const el = hasDocument && elementId ? document.getElementById(elementId) : null;
      if (!el && typeof options.readValue !== "function") return;
      if (el && el.disabled) return;
      const feature = el && el.closest && el.closest(".feature-body[data-feature-toggle]");
      if (feature) {
        const toggle = document.getElementById(feature.getAttribute("data-feature-toggle"));
        if (toggle && !toggle.checked) return;
      }
      const potentialPanel = el && el.closest && el.closest(".potential-panel.hidden");
      if (potentialPanel) return;
      const label = typeof options.labelFor === "function"
        ? String(options.labelFor(param, elementId) || controlLabel(el, param))
        : controlLabel(el, param);
      const supplied = typeof options.readValue === "function"
        ? options.readValue(param, elementId, el)
        : el.type === "checkbox"
          ? Boolean(el.checked)
          : el.value;
      const raw = param.value_type === "boolean"
        ? String(Boolean(supplied))
        : String(supplied ?? "").trim();
      if (!raw && param.required) {
        errors.push({ key: param.key, message: validationMessage("required", label, null, options.lang) });
        return;
      }
      if (!raw) return;
      if (["integer", "number"].includes(param.value_type)) {
        const value = Number(raw);
        if (!Number.isFinite(value)) {
          errors.push({ key: param.key, message: validationMessage("number", label, null, options.lang) });
          return;
        }
        if (param.value_type === "integer" && !Number.isInteger(value)) {
          errors.push({ key: param.key, message: validationMessage("integer", label, null, options.lang) });
          return;
        }
        if (param.min_value !== null && param.min_value !== undefined && value < Number(param.min_value)) {
          errors.push({ key: param.key, message: validationMessage("min", label, param.min_value, options.lang) });
          return;
        }
        if (param.max_value !== null && param.max_value !== undefined && value > Number(param.max_value)) {
          errors.push({ key: param.key, message: validationMessage("max", label, param.max_value, options.lang) });
          return;
        }
      }
      const allowed = Array.isArray(param.options) ? param.options.map(String) : [];
      if (allowed.length && !allowed.includes(raw)) {
        errors.push({ key: param.key, message: validationMessage("option", label, null, options.lang) });
      }
    });
    return errors;
  }

  function controlIds() {
    return Array.from(new Set(Object.values(CONTROL_BINDINGS)));
  }

  window.ElectrochemProcessingSchema = {
    CONTROL_BINDINGS,
    applyNumericConstraints: applyToControls,
    applyPresets,
    applyToControls,
    buildModuleCards,
    controlIds,
    getCached,
    getDefault,
    getModule,
    getParameter,
    getVersion,
    load,
    moduleList,
    moduleMap,
    paramMap,
    validateControls,
    syncEisControls,
  };
})();
