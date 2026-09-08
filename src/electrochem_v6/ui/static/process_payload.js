(function () {
  "use strict";

  function addIfSet(obj, key, value) {
    if (value !== undefined && value !== null && value !== "") {
      obj[key] = value;
    }
  }

  function langOf(ctx) {
    return ctx && ctx.currentLang ? ctx.currentLang : "zh";
  }

  function localized(ctx, zh, en) {
    return langOf(ctx) === "zh" ? zh : en;
  }

  function schemaDefault(ctx, key) {
    const client = ctx && (ctx.processSchemaClient || window.ElectrochemProcessingSchema);
    const schema = ctx && ctx.processParameterSchema
      || (client && typeof client.getCached === "function" ? client.getCached() : null);
    return client && typeof client.getDefault === "function"
      ? client.getDefault(schema, key, undefined)
      : undefined;
  }

  function textOrSchemaDefault(ctx, elementId, key) {
    const value = ctx.textValue(elementId);
    return value === "" ? schemaDefault(ctx, key) : value;
  }

  function getCoupledPeakMethod(ctx) {
    if (!ctx || typeof ctx.getCoupledPeakMethod !== "function") return null;
    const method = ctx.getCoupledPeakMethod();
    return method && typeof method === "object" ? method : null;
  }

  function validatePositiveMethodValue(ctx, value, zhLabel, enLabel) {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) {
      return localized(ctx, `${zhLabel}必须大于 0`, `${enLabel} must be greater than 0`);
    }
    return null;
  }

  function validatePanelPeakMethod(ctx, method) {
    if (!method) {
      return [localized(ctx, "请填写峰分析面板参数", "Panel peak method is required")];
    }
    const errors = [];
    const standard = method.internal_standard && typeof method.internal_standard === "object"
      ? method.internal_standard
      : {};
    if (!Number.isFinite(Number(standard.expected_position))) {
      errors.push(localized(ctx, "内标预期峰位必须是数字", "Internal-standard peak position must be numeric"));
    }
    [
      [standard.nuclei_count, "内标定量核数", "Internal-standard nuclei count"],
      [standard.concentration_mM, "内标浓度", "Internal-standard concentration"],
      [standard.volume_uL, "内标加入体积", "Internal-standard volume"],
      [method.sample_defaults && method.sample_defaults.electrolyte_volume_mL, "电解液总体积", "Electrolyte volume"],
      [method.sample_defaults && method.sample_defaults.sample_aliquot_volume_uL, "取样体积", "Aliquot volume"],
    ].forEach(([value, zhLabel, enLabel]) => {
      const error = validatePositiveMethodValue(ctx, value, zhLabel, enLabel);
      if (error) errors.push(error);
    });

    const products = Array.isArray(method.products) ? method.products : [];
    if (!products.length) {
      errors.push(localized(ctx, "至少需要定义一个产物", "At least one product is required"));
      return errors;
    }
    const names = new Set();
    products.forEach((product, index) => {
      const number = index + 1;
      const name = String((product && product.name) || "").trim();
      if (!name) {
        errors.push(localized(ctx, `产物 ${number} 名称不能为空`, `Product ${number} name is required`));
      } else if (names.has(name.toLowerCase())) {
        errors.push(localized(ctx, `产物名称重复：${name}`, `Duplicate product name: ${name}`));
      } else {
        names.add(name.toLowerCase());
      }
      if (!Number.isFinite(Number(product && product.expected_position))) {
        errors.push(localized(ctx, `产物 ${number} 预期峰位必须是数字`, `Product ${number} peak position must be numeric`));
      }
      [
        [product && product.nuclei_count, "定量核数", "nuclei count"],
        [product && product.electron_count, "电子转移数", "electron count"],
        [product && product.response_factor, "响应修正因子", "response factor"],
      ].forEach(([value, zhLabel, enLabel]) => {
        const error = validatePositiveMethodValue(
          ctx,
          value,
          `产物 ${number} ${zhLabel}`,
          `Product ${number} ${enLabel}`,
        );
        if (error) errors.push(error);
      });
    });

    const peaks = [standard, ...products].filter((item) => Number.isFinite(Number(item.expected_position)));
    for (let leftIndex = 0; leftIndex < peaks.length; leftIndex += 1) {
      const left = peaks[leftIndex];
      const leftMin = Number(left.expected_position) - Number(left.window_left || 0);
      const leftMax = Number(left.expected_position) + Number(left.window_right || 0);
      for (let rightIndex = leftIndex + 1; rightIndex < peaks.length; rightIndex += 1) {
        const right = peaks[rightIndex];
        const rightMin = Number(right.expected_position) - Number(right.window_left || 0);
        const rightMax = Number(right.expected_position) + Number(right.window_right || 0);
        if (Math.min(leftMax, rightMax) > Math.max(leftMin, rightMin)) {
          const leftName = String(left.name || "internal_standard");
          const rightName = String(right.name || `product_${rightIndex}`);
          errors.push(localized(
            ctx,
            `定量窗口重叠：${leftName} 与 ${rightName}`,
            `Quantification windows overlap: ${leftName} and ${rightName}`,
          ));
        }
      }
    }
    return errors;
  }

  function collectValidationErrors(ctx, dataTypesInput) {
    const dataTypes = Array.isArray(dataTypesInput) ? dataTypesInput : [];
    const errors = [];
    const t = ctx.t;
    const addError = (err) => {
      if (err) errors.push(err);
    };
    const schemaClient = ctx.processSchemaClient || window.ElectrochemProcessingSchema;
    const schema = ctx.processParameterSchema
      || (schemaClient && typeof schemaClient.getCached === "function" ? schemaClient.getCached() : null);
    const usesSchemaValidation = Boolean(
      schemaClient && schema && typeof schemaClient.validateControls === "function"
    );
    if (usesSchemaValidation) {
      schemaClient.validateControls(schema, dataTypes, {
        lang: langOf(ctx),
        readValue: (param, elementId) => (
          param.value_type === "boolean" ? ctx.boolValue(elementId) : ctx.textValue(elementId)
        ),
      }).forEach((item) => addError(item && item.message));
    }

    if (dataTypes.includes("EIS")) {
      const lower = ctx.textValue("pro-eis-fit-frequency-min-hz");
      const upper = ctx.textValue("pro-eis-fit-frequency-max-hz");
      if ([lower, upper].some((value) => value && (!Number.isFinite(Number(value)) || Number(value) <= 0))) {
        addError(langOf(ctx) === "zh" ? "EIS 频率须为大于 0 的有限数字（Hz）；留空表示不限制" : "EIS frequency must be finite and > 0 Hz; leave blank for no limit");
      }
      if (lower && upper && Number(lower) > Number(upper)) {
        addError(langOf(ctx) === "zh" ? "EIS 最低频率不能高于最高频率" : "EIS minimum frequency must not exceed maximum frequency");
      }
    }

    if (ctx.getPotentialMode() === "formula_rhe") {
      if (!ctx.textValue("pro-rhe-ph")) {
        addError(langOf(ctx) === "zh" ? "pH 不能为空" : "pH is required");
      }
      if (!ctx.textValue("pro-rhe-temperature")) {
        addError(langOf(ctx) === "zh" ? "温度不能为空" : "Temperature is required");
      }
      const refPreset = ctx.textValue("pro-ref-preset");
      if (refPreset === "custom") {
        if (!ctx.textValue("pro-ref-custom")) {
          addError(langOf(ctx) === "zh" ? "请填写自定义参比电位" : "Custom reference potential is required");
        }
      } else if (ctx.getReferenceElectrodePotential() === undefined) {
        addError(langOf(ctx) === "zh" ? "参比电极电位无效" : "Reference electrode potential is invalid");
      }
    }

    if (dataTypes.includes("LSV")) {
      if (ctx.boolValue("pro-lsv-ir-enabled")) {
        const irSource = textOrSchemaDefault(ctx, "pro-lsv-ir-source", "ir_source");
        if (irSource === "manual") {
          if (!ctx.textValue("pro-lsv-ir-manual")) addError(t("ir_manual_required"));
          const manualRs = Number(ctx.textValue("pro-lsv-ir-manual"));
          if (Number.isFinite(manualRs) && manualRs <= 0) addError(t("ir_manual_required"));
        } else {
          const scope = ctx.textValue("pro-lsv-ir-scope");
          if (scope === "specified_file" && !ctx.textValue("pro-lsv-ir-eis-file")) {
            addError(t("ir_eis_file_required"));
          }
          const pattern = ctx.textValue("pro-lsv-ir-eis-pattern");
          if (scope !== "specified_file" && !pattern) addError(t("ir_eis_pattern_required"));
          if (ctx.textValue("pro-lsv-ir-eis-match") === "regex" && pattern) {
            try {
              new RegExp(pattern, "i");
            } catch (_err) {
              addError(t("ir_eis_regex_invalid"));
            }
          }
        }
      }
      if (ctx.boolValue("pro-lsv-overpotential-enabled")) {
        if (!ctx.textValue("pro-lsv-eq-potential")) {
          addError(langOf(ctx) === "zh" ? "平衡电位不能为空" : "Equilibrium potential is required");
        }
      }
    }

    if (dataTypes.includes("COUPLED")) {
      const coupledMode = textOrSchemaDefault(ctx, "pro-coupled-input-mode", "coupled_input_mode");
      if (!usesSchemaValidation && !ctx.textValue("pro-coupled-products-file")) {
        addError(langOf(ctx) === "zh" ? "COUPLED 定量/测量表路径不能为空" : "COUPLED quantification/measurement table path is required");
      }
      if (coupledMode === "peak_analysis") {
        const methodSource = textOrSchemaDefault(ctx, "pro-coupled-peak-method-source", "coupled_peak_method_source");
        if (methodSource === "file" && !ctx.textValue("pro-coupled-peak-method-file")) {
          addError(langOf(ctx) === "zh" ? "峰分析方法文件不能为空" : "Peak-analysis method file is required");
        }
        if (methodSource === "panel") {
          validatePanelPeakMethod(ctx, getCoupledPeakMethod(ctx)).forEach(addError);
        }
        const detectionSnr = Number(ctx.textValue("pro-fe-peak-min-detection-snr"));
        const quantificationSnr = Number(ctx.textValue("pro-fe-peak-min-quantification-snr"));
        if (Number.isFinite(detectionSnr) && Number.isFinite(quantificationSnr) && quantificationSnr < detectionSnr) {
          addError(langOf(ctx) === "zh" ? "最低定量 SNR 不能低于最低检出 SNR" : "Quantification SNR must not be lower than detection SNR");
        }
      }
    }

    return errors;
  }

  function collectPayload(ctx) {
    const folder = ctx.textValue("proc-folder");
    if (!folder) {
      throw new Error(ctx.t("proc_folder_required"));
    }

    const dataTypes = ctx.getSelectedProcessTypes();
    if (!dataTypes.length) {
      throw new Error(ctx.t("proc_type_required"));
    }
    const hasExplicitInputSelection = typeof ctx.hasExplicitInputSelection === "function"
      && ctx.hasExplicitInputSelection();
    const inputFiles = typeof ctx.getSelectedInputFiles === "function"
      ? ctx.getSelectedInputFiles(dataTypes)
      : [];
    const primaryTypes = dataTypes.filter((dataType) => dataType !== "COUPLED");
    if (hasExplicitInputSelection && primaryTypes.length && !inputFiles.length) {
      throw new Error(ctx.t("proc_input_files_required"));
    }
    const validationErrors = collectValidationErrors(ctx, dataTypes);
    if (validationErrors.length) {
      throw new Error(`${ctx.t("proc_param_invalid")}: ${validationErrors[0]}`);
    }

    const params = {
      plot_grid: ctx.boolValue("pro-plot-grid"),
      use_abs_current: ctx.boolValue("pro-use-abs-current"),
      recursive_scan: ctx.boolValue("pro-recursive-scan"),
      output_run_dir_enabled: ctx.boolValue("pro-output-run-dir"),
    };
    const payload = {
      folder_path: folder,
      data_types: dataTypes,
      params,
    };
    if (hasExplicitInputSelection) payload.input_files = inputFiles;

    const projectName = ctx.textValue("proc-project");
    if (projectName) payload.project_name = projectName;

    const potentialMode = ctx.getPotentialMode();
    params.potential_mode = potentialMode;
    addIfSet(params, "font_family", ctx.textValue("plot-font-family"));
    addIfSet(params, "font_size", ctx.numberValue("plot-font-size"));
    addIfSet(params, "area", ctx.numberValue("pro-area"));
    if (potentialMode === "formula_rhe") {
      addIfSet(params, "rhe_ph", ctx.numberValue("pro-rhe-ph"));
      addIfSet(params, "rhe_temperature_c", ctx.numberValue("pro-rhe-temperature"));
      addIfSet(params, "reference_electrode_preset", ctx.textValue("pro-ref-preset"));
      addIfSet(params, "reference_electrode_potential", ctx.getReferenceElectrodePotential());
    } else {
      addIfSet(params, "potential_offset", ctx.numberValue("pro-offset"));
    }

    if (dataTypes.includes("LSV")) {
      const target = ctx.textValue("pro-lsv-target");
      const tafel = ctx.textValue("pro-lsv-tafel");

      addIfSet(params, "lsv_target_current", target);
      addIfSet(params, "tafel_range", tafel);
      addIfSet(params, "lsv_match", textOrSchemaDefault(ctx, "pro-lsv-match", "lsv_match"));
      addIfSet(params, "lsv_prefix", textOrSchemaDefault(ctx, "pro-lsv-prefix", "lsv_prefix"));
      addIfSet(params, "lsv_potential_column", ctx.numberValue("pro-lsv-potential-column"));
      addIfSet(params, "lsv_current_column", ctx.numberValue("pro-lsv-current-column"));
      addIfSet(params, "lsv_potential_unit", textOrSchemaDefault(ctx, "pro-lsv-potential-unit", "lsv_potential_unit"));
      addIfSet(params, "lsv_current_unit", textOrSchemaDefault(ctx, "pro-lsv-current-unit", "lsv_current_unit"));
      addIfSet(params, "lsv_title", ctx.textValue("pro-lsv-title"));
      addIfSet(params, "lsv_xlabel", ctx.textValue("pro-lsv-xlabel"));
      addIfSet(params, "lsv_ylabel", ctx.textValue("pro-lsv-ylabel"));
      addIfSet(params, "lsv_line_width", ctx.numberValue("pro-lsv-line-width"));
      params.tafel_enabled = ctx.boolValue("pro-lsv-tafel-enabled");
      params.lsv_mark_targets = ctx.boolValue("pro-lsv-mark-targets");
      params.lsv_export_data = ctx.boolValue("pro-lsv-export-data");
      params.lsv_combine_all = ctx.boolValue("pro-lsv-combine-all");
      params.export_tafel_plot = ctx.boolValue("pro-lsv-export-tafel");
      params.lsv_quality_check = ctx.boolValue("pro-lsv-quality-check");
      if (params.lsv_quality_check) {
        addIfSet(params, "lsv_quality_min_points_issue", ctx.numberValue("pro-lsv-quality-min-points-issue"));
        addIfSet(params, "lsv_quality_min_points_warning", ctx.numberValue("pro-lsv-quality-min-points-warning"));
        addIfSet(params, "lsv_quality_outlier_warning_pct", ctx.numberValue("pro-lsv-quality-outlier-warning-pct"));
        addIfSet(params, "lsv_quality_min_potential_span", ctx.numberValue("pro-lsv-quality-min-potential-span"));
        addIfSet(params, "lsv_quality_noise_warning", ctx.numberValue("pro-lsv-quality-noise-warning"));
        addIfSet(params, "lsv_quality_noise_critical", ctx.numberValue("pro-lsv-quality-noise-critical"));
        addIfSet(params, "lsv_quality_jump_warning", ctx.numberValue("pro-lsv-quality-jump-warning"));
        addIfSet(params, "lsv_quality_jump_critical", ctx.numberValue("pro-lsv-quality-jump-critical"));
        addIfSet(params, "lsv_quality_local_variation_factor", ctx.numberValue("pro-lsv-quality-local-factor"));
      }

      const overpotentialEnabled = ctx.boolValue("pro-lsv-overpotential-enabled");
      params.overpotential_enabled = overpotentialEnabled;
      if (overpotentialEnabled) {
        addIfSet(params, "eq_potential", ctx.numberValue("pro-lsv-eq-potential"));
      }

      const irEnabled = ctx.boolValue("pro-lsv-ir-enabled");
      params.ir_compensation_enabled = irEnabled;
      if (irEnabled) {
        const irMethod = textOrSchemaDefault(ctx, "pro-lsv-ir-method", "ir_method");
        const irSource = textOrSchemaDefault(ctx, "pro-lsv-ir-source", "ir_source");
        addIfSet(params, "ir_source", irSource);
        addIfSet(params, "ir_method", irMethod);
        addIfSet(params, "ir_validation_mode", textOrSchemaDefault(ctx, "pro-lsv-ir-validation", "ir_validation_mode"));
        if (irSource === "manual") {
          addIfSet(params, "ir_manual_ohm", ctx.numberValue("pro-lsv-ir-manual"));
        } else {
          addIfSet(params, "ir_eis_search_scope", textOrSchemaDefault(ctx, "pro-lsv-ir-scope", "ir_eis_search_scope"));
          addIfSet(params, "ir_eis_file", ctx.textValue("pro-lsv-ir-eis-file"));
          addIfSet(params, "ir_eis_match", textOrSchemaDefault(ctx, "pro-lsv-ir-eis-match", "ir_eis_match"));
          addIfSet(params, "ir_eis_pattern", textOrSchemaDefault(ctx, "pro-lsv-ir-eis-pattern", "ir_eis_pattern"));
          addIfSet(params, "ir_linear_points", ctx.numberValue("pro-lsv-ir-points"));
          addIfSet(params, "ir_eis_frequency_column", ctx.numberValue("pro-ir-eis-frequency-column"));
          addIfSet(params, "ir_eis_zreal_column", ctx.numberValue("pro-ir-eis-zreal-column"));
          addIfSet(params, "ir_eis_zimag_column", ctx.numberValue("pro-ir-eis-zimag-column"));
          addIfSet(params, "ir_eis_frequency_unit", textOrSchemaDefault(ctx, "pro-ir-eis-frequency-unit", "ir_eis_frequency_unit"));
          addIfSet(params, "ir_eis_impedance_unit", textOrSchemaDefault(ctx, "pro-ir-eis-impedance-unit", "ir_eis_impedance_unit"));
          addIfSet(params, "ir_eis_zimag_convention", textOrSchemaDefault(ctx, "pro-ir-eis-zimag-convention", "ir_eis_zimag_convention"));
        }
      }

      const onsetEnabled = ctx.boolValue("pro-lsv-onset-enabled");
      params.onset_enabled = onsetEnabled;
      if (onsetEnabled) {
        addIfSet(params, "onset_current", ctx.textValue("pro-lsv-onset-current"));
      }

      const halfwaveEnabled = ctx.boolValue("pro-lsv-halfwave-enabled");
      params.halfwave_enabled = halfwaveEnabled;
      if (halfwaveEnabled) {
        addIfSet(params, "halfwave_current", ctx.textValue("pro-lsv-halfwave-current"));
      }
    }

    if (dataTypes.includes("CV")) {
      addIfSet(params, "cv_match", textOrSchemaDefault(ctx, "pro-cv-match", "cv_match"));
      addIfSet(params, "cv_prefix", textOrSchemaDefault(ctx, "pro-cv-prefix", "cv_prefix"));
      addIfSet(params, "cv_title", ctx.textValue("pro-cv-title"));
      addIfSet(params, "cv_xlabel", ctx.textValue("pro-cv-xlabel"));
      addIfSet(params, "cv_ylabel", ctx.textValue("pro-cv-ylabel"));
      addIfSet(params, "cv_line_width", ctx.numberValue("pro-cv-line-width"));
      addIfSet(params, "cv_scan_rate_v_s", ctx.numberValue("pro-cv-scan-rate"));
      addIfSet(params, "cv_potential_column", ctx.numberValue("pro-cv-potential-column"));
      addIfSet(params, "cv_current_column", ctx.numberValue("pro-cv-current-column"));
      addIfSet(params, "cv_potential_unit", textOrSchemaDefault(ctx, "pro-cv-potential-unit", "cv_potential_unit"));
      addIfSet(params, "cv_current_unit", textOrSchemaDefault(ctx, "pro-cv-current-unit", "cv_current_unit"));
      params.cv_quality_check = ctx.boolValue("pro-cv-quality-check");
      const cvPeaksEnabled = ctx.boolValue("pro-cv-peaks-enabled");
      params.cv_peaks_enabled = cvPeaksEnabled;
      if (cvPeaksEnabled) {
        addIfSet(params, "cv_peaks_smooth", ctx.numberValue("pro-cv-peaks-smooth"));
        addIfSet(params, "cv_peaks_min_height", ctx.numberValue("pro-cv-peaks-height"));
        addIfSet(params, "cv_peaks_min_dist", ctx.numberValue("pro-cv-peaks-dist"));
        addIfSet(params, "cv_peaks_max", ctx.numberValue("pro-cv-peaks-max"));
      }
      const cvCyclePlotEnabled = ctx.boolValue("pro-cv-cycle-plot-enabled");
      params.cv_cycle_plot_enabled = cvCyclePlotEnabled;
      if (cvCyclePlotEnabled) {
        addIfSet(params, "cv_cycle_numbers", ctx.textValue("pro-cv-cycle-numbers"));
        addIfSet(params, "cv_cycle_reversal_tolerance", ctx.numberValue("pro-cv-cycle-reversal-tolerance"));
        addIfSet(params, "cv_cycle_min_segment_points", ctx.numberValue("pro-cv-cycle-min-segment-points"));
      }
      if (params.cv_quality_check) {
        addIfSet(params, "cv_quality_min_points_warning", ctx.numberValue("pro-cv-quality-min-points-warning"));
        addIfSet(params, "cv_quality_cycle_tolerance", ctx.numberValue("pro-cv-quality-cycle-tolerance"));
      }
    }

    if (dataTypes.includes("EIS")) {
      addIfSet(params, "eis_match", textOrSchemaDefault(ctx, "pro-eis-match", "eis_match"));
      addIfSet(params, "eis_prefix", textOrSchemaDefault(ctx, "pro-eis-prefix", "eis_prefix"));
      addIfSet(params, "eis_title", ctx.textValue("pro-eis-title"));
      addIfSet(params, "eis_xlabel", ctx.textValue("pro-eis-xlabel"));
      addIfSet(params, "eis_ylabel", ctx.textValue("pro-eis-ylabel"));
      addIfSet(params, "eis_line_width", ctx.numberValue("pro-eis-line-width"));
      addIfSet(params, "eis_frequency_column", ctx.numberValue("pro-eis-frequency-column"));
      addIfSet(params, "eis_zreal_column", ctx.numberValue("pro-eis-zreal-column"));
      addIfSet(params, "eis_zimag_column", ctx.numberValue("pro-eis-zimag-column"));
      addIfSet(params, "eis_frequency_unit", textOrSchemaDefault(ctx, "pro-eis-frequency-unit", "eis_frequency_unit"));
      addIfSet(params, "eis_impedance_unit", textOrSchemaDefault(ctx, "pro-eis-impedance-unit", "eis_impedance_unit"));
      addIfSet(params, "eis_zimag_convention", textOrSchemaDefault(ctx, "pro-eis-zimag-convention", "eis_zimag_convention"));
      params.plot_nyquist = ctx.boolValue("pro-eis-plot-nyquist");
      params.plot_bode = ctx.boolValue("pro-eis-plot-bode");
      params.eis_randles_fit = ctx.boolValue("pro-eis-randles-fit");
      addIfSet(params, "eis_circuit_model", textOrSchemaDefault(ctx, "pro-eis-circuit-model", "eis_circuit_model"));
      addIfSet(params, "eis_fit_min_r2", ctx.numberValue("pro-eis-fit-min-r2"));
      params.eis_fit_frequency_min_hz = ctx.numberValue("pro-eis-fit-frequency-min-hz") ?? null;
      params.eis_fit_frequency_max_hz = ctx.numberValue("pro-eis-fit-frequency-max-hz") ?? null;
      addIfSet(params, "eis_fit_weighting", textOrSchemaDefault(ctx, "pro-eis-fit-weighting", "eis_fit_weighting"));
      params.eis_kk_check = ctx.boolValue("pro-eis-kk-check");
      params.plot_eis_residuals = ctx.boolValue("pro-eis-plot-residuals");
    }

    if (dataTypes.includes("ECSA")) {
      addIfSet(params, "ecsa_match", textOrSchemaDefault(ctx, "pro-ecsa-match", "ecsa_match"));
      addIfSet(params, "ecsa_prefix", textOrSchemaDefault(ctx, "pro-ecsa-prefix", "ecsa_prefix"));
      addIfSet(params, "ecsa_title", ctx.textValue("pro-ecsa-title"));
      addIfSet(params, "ecsa_xlabel", ctx.textValue("pro-ecsa-xlabel"));
      addIfSet(params, "ecsa_ylabel", ctx.textValue("pro-ecsa-ylabel"));
      addIfSet(params, "ecsa_line_width", ctx.numberValue("pro-ecsa-line-width"));
      addIfSet(params, "ecsa_potential_column", ctx.numberValue("pro-ecsa-potential-column"));
      addIfSet(params, "ecsa_current_column", ctx.numberValue("pro-ecsa-current-column"));
      addIfSet(params, "ecsa_potential_unit", textOrSchemaDefault(ctx, "pro-ecsa-potential-unit", "ecsa_potential_unit"));
      addIfSet(params, "ecsa_current_unit", textOrSchemaDefault(ctx, "pro-ecsa-current-unit", "ecsa_current_unit"));
      addIfSet(params, "ecsa_ev", ctx.numberValue("pro-ecsa-ev"));
      addIfSet(params, "ecsa_last_n", ctx.numberValue("pro-ecsa-last-n"));
      params.ecsa_avg_last_n = ctx.boolValue("pro-ecsa-avg-last-n");
      addIfSet(params, "ecsa_cs_value", ctx.numberValue("pro-ecsa-cs-value"));
      addIfSet(params, "ecsa_cs_unit", textOrSchemaDefault(ctx, "pro-ecsa-cs-unit", "ecsa_cs_unit"));
      params.ecsa_use_abs_delta = ctx.boolValue("pro-ecsa-use-abs");
    }

    if (dataTypes.includes("COUPLED")) {
      const coupledMode = textOrSchemaDefault(ctx, "pro-coupled-input-mode", "coupled_input_mode");
      const productsFile = ctx.textValue("pro-coupled-products-file");
      const productsSheet = textOrSchemaDefault(ctx, "pro-coupled-products-sheet", "coupled_products_sheet");
      const coupledCsv = textOrSchemaDefault(ctx, "pro-coupled-results-csv", "coupled_results_csv_filename");
      const peakMethodFile = ctx.textValue("pro-coupled-peak-method-file");
      const peakMethodSource = textOrSchemaDefault(ctx, "pro-coupled-peak-method-source", "coupled_peak_method_source");
      addIfSet(params, "coupled_input_mode", coupledMode);
      addIfSet(params, "coupled_products_file", productsFile);
      addIfSet(params, "coupled_products_sheet", productsSheet);
      addIfSet(params, "coupled_results_csv_filename", coupledCsv);
      if (coupledMode === "peak_analysis") {
        addIfSet(params, "coupled_peak_method_source", peakMethodSource);
        if (peakMethodSource === "file") {
          addIfSet(params, "coupled_peak_method_file", peakMethodFile);
        } else {
          addIfSet(params, "coupled_peak_method", getCoupledPeakMethod(ctx));
        }
        params.fe_peak_auto_locate = ctx.boolValue("pro-fe-peak-auto-locate");
        params.fe_peak_reference_align = ctx.boolValue("pro-fe-peak-reference-align");
        params.fe_peak_fit_enabled = ctx.boolValue("pro-fe-peak-fit-enabled");
        addIfSet(params, "fe_peak_search_tolerance", ctx.numberValue("pro-fe-peak-search-tolerance"));
        addIfSet(params, "fe_peak_window_left", ctx.numberValue("pro-fe-peak-window-left"));
        addIfSet(params, "fe_peak_window_right", ctx.numberValue("pro-fe-peak-window-right"));
        addIfSet(params, "fe_peak_min_detection_snr", ctx.numberValue("pro-fe-peak-min-detection-snr"));
        addIfSet(params, "fe_peak_min_quantification_snr", ctx.numberValue("pro-fe-peak-min-quantification-snr"));
      }
    }
    return payload;
  }

  window.ElectrochemProcessPayload = {
    addIfSet,
    collectPayload,
    collectValidationErrors,
  };
})();
