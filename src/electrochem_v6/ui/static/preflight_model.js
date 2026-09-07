(function () {
  "use strict";

  const DEFAULT_TYPES = ["LSV", "CV", "EIS", "ECSA", "COUPLED"];
  const CHECK_KEYS = ["files", "params", "output", "runnable"];
  const STATUS_LABEL_KEYS = {
    pass: "preflight_status_pass",
    check: "preflight_status_check",
    normal: "preflight_status_normal",
    abnormal: "preflight_status_abnormal",
    yes: "preflight_status_yes",
    no: "preflight_status_no",
  };

  function safeScan(preflight) {
    return preflight && typeof preflight === "object" ? preflight : {};
  }

  function statusLabelKey(status, fallbackKey) {
    return STATUS_LABEL_KEYS[String(status || "")] || fallbackKey;
  }

  function item(state, labelKey) {
    return { state, labelKey };
  }

  function normalizeType(value) {
    return String(value || "").trim().toUpperCase();
  }

  function moduleMap(moduleDescriptors) {
    const map = new Map();
    (Array.isArray(moduleDescriptors) ? moduleDescriptors : []).forEach((module) => {
      const key = normalizeType(module && module.key);
      if (!key) return;
      map.set(key, module);
      (Array.isArray(module.aliases) ? module.aliases : []).forEach((alias) => {
        const aliasKey = normalizeType(alias);
        if (aliasKey && !map.has(aliasKey)) map.set(aliasKey, module);
      });
    });
    return map;
  }

  function resolveTypes(selectedTypes, defaultTypes, moduleDescriptors) {
    const modules = Array.isArray(moduleDescriptors) ? moduleDescriptors : [];
    const selectedItems = Array.isArray(selectedTypes) ? selectedTypes.filter(Boolean) : [];
    if (selectedItems.length && selectedItems.every((item) => item && typeof item === "object" && item.key)) {
      return selectedItems;
    }
    const selected = selectedItems.map(normalizeType).filter(Boolean);
    if (modules.length) {
      const modulesByKey = moduleMap(modules);
      const selectedKeys = new Set(
        selected.map((item) => {
          const module = modulesByKey.get(item);
          return module ? normalizeType(module.key) : item;
        })
      );
      const filtered = modules
        .filter((module) => {
          const key = normalizeType(module && module.key);
          return key && (!selectedKeys.size || selectedKeys.has(key));
        })
        .map((module) => ({
          key: normalizeType(module.key),
          inputKind: module.input_kind || "data_files",
          label: module.display_name || normalizeType(module.key),
        }));
      if (filtered.length) return filtered;
    }
    return selected.length ? selected : defaultTypes || DEFAULT_TYPES;
  }

  function runningItems() {
    return {
      files: item("running", "preflight_status_running"),
      params: item("running", "preflight_status_running"),
      output: item("running", "preflight_status_running"),
      runnable: item("running", "preflight_status_running"),
    };
  }

  function pendingItems() {
    return {
      files: item("pending", "preflight_status_pending"),
      params: item("pending", "preflight_status_pending"),
      output: item("pending", "preflight_status_pending"),
      runnable: item("pending", "preflight_status_pending"),
    };
  }

  function issueItems(hasMessage) {
    return {
      files: item("issue", "preflight_status_check"),
      params: item("issue", hasMessage ? "preflight_status_check" : "preflight_status_pending"),
      output: item("issue", "preflight_status_abnormal"),
      runnable: item("issue", "preflight_status_no"),
    };
  }

  function completeItems(scan) {
    const checks = scan.checks && typeof scan.checks === "object" ? scan.checks : null;
    if (checks) {
      const files = checks.file_recognition || {};
      const params = checks.param_completeness || {};
      const output = checks.output_dir || {};
      const runnable = checks.runnable || {};
      return {
        files: item(files.ok ? "ok" : "issue", statusLabelKey(files.status, "preflight_status_check")),
        params: item(params.ok ? "ok" : "issue", statusLabelKey(params.status, "preflight_status_check")),
        output: item(output.ok ? "ok" : "issue", statusLabelKey(output.status, "preflight_status_abnormal")),
        runnable: item(runnable.ok ? "ok" : "issue", statusLabelKey(runnable.status, "preflight_status_no")),
      };
    }

    const selectedMatched = Number(scan.selected_matched || 0);
    const warnings = Array.isArray(scan.warnings) ? scan.warnings : [];
    const filesOk = selectedMatched > 0 && warnings.length === 0;
    const runnable = selectedMatched > 0;
    return {
      files: item(filesOk ? "ok" : "issue", filesOk ? "preflight_status_pass" : "preflight_status_check"),
      params: item("ok", "preflight_status_pass"),
      output: item("ok", "preflight_status_normal"),
      runnable: item(runnable ? "ok" : "issue", runnable ? "preflight_status_yes" : "preflight_status_no"),
    };
  }

  function buildCheckItems(preflight, state, message) {
    if (state === "running") return { scan: null, items: runningItems() };
    if (state === "issue") return { scan: null, items: issueItems(Boolean(message)) };
    if (state !== "complete" || !preflight) return { scan: null, items: pendingItems() };

    const scan = safeScan(preflight);
    return { scan, items: completeItems(scan) };
  }

  function normalizeResolvedType(typeItem) {
    if (typeItem && typeof typeItem === "object") {
      const key = normalizeType(typeItem.key);
      return {
        dtype: key,
        inputKind: typeItem.inputKind || "data_files",
        label: typeItem.label || key,
      };
    }
    const key = normalizeType(typeItem);
    return { dtype: key, inputKind: "data_files", label: key };
  }

  function buildFileDetailCards(preflight, selectedTypes, defaultTypes, moduleDescriptors) {
    const scan = safeScan(preflight);
    const byType = scan.by_type && typeof scan.by_type === "object" ? scan.by_type : {};
    const types = resolveTypes(selectedTypes, defaultTypes, moduleDescriptors);
    return types.map((typeItem) => {
      const meta = normalizeResolvedType(typeItem);
      const dtype = meta.dtype;
      const itemData = byType[dtype] || {};
      const matched = Number(itemData.matched || 0);
      return {
        dtype,
        examples: Array.isArray(itemData.examples) ? itemData.examples.slice(0, 3) : [],
        inputKind: meta.inputKind,
        label: meta.label,
        matched,
        ok: matched > 0,
        rule: [itemData.match, itemData.pattern || itemData.prefix].filter(Boolean).join(" / ") || "-",
      };
    });
  }

  function buildSummary(preflight, dataTypes, moduleDescriptors) {
    const scan = safeScan(preflight);
    const byType = scan.by_type && typeof scan.by_type === "object" ? scan.by_type : {};
    const types = resolveTypes(dataTypes, DEFAULT_TYPES, moduleDescriptors);
    return {
      counts: types.map((typeItem) => {
        const meta = normalizeResolvedType(typeItem);
        return {
          dtype: meta.dtype,
          label: meta.label,
          matched: Number((byType[meta.dtype] || {}).matched || 0),
        };
      }),
      textFiles: Number(scan.text_files || 0),
      warnings: Array.isArray(scan.warnings) ? scan.warnings : [],
      workUnits: Number(scan.work_units || 0),
    };
  }

  function buildFileDetailView(preflight, selectedTypes, defaultTypes, moduleDescriptors) {
    const scan = safeScan(preflight);
    const types = resolveTypes(selectedTypes, defaultTypes, moduleDescriptors);
    const cards = buildFileDetailCards(preflight, types, defaultTypes, moduleDescriptors);
    const summary = buildSummary(preflight, types, moduleDescriptors);
    const matchedFiles = cards.reduce((total, card) => total + Number(card.matched || 0), 0);
    const irData = scan.ir_compensation && typeof scan.ir_compensation === "object" ? scan.ir_compensation : {};
    const irPairings = (Array.isArray(irData.items) ? irData.items : []).map((entry) => {
      const status = String((entry && entry.status) || "missing");
      return {
        candidates: Array.isArray(entry && entry.candidates) ? entry.candidates.slice(0, 5) : [],
        eisFile: String((entry && entry.eis_file) || ""),
        lsvFile: String((entry && entry.lsv_file) || ""),
        message: String((entry && entry.message) || ""),
        method: String((entry && (entry.extraction_method || entry.method)) || ""),
        ok: status === "matched" || status === "manual",
        scope: String((entry && entry.scope) || ""),
        source: String((entry && entry.source) || ""),
        status,
        statusLabelKey: `preflight_ir_${status}`,
      };
    });
    return {
      cards,
      irPairings,
      metrics: [
        { labelKey: "preflight_detail_matched_files", value: matchedFiles },
        { labelKey: "preflight_text_files", value: summary.textFiles },
        { labelKey: "preflight_work_units", value: summary.workUnits },
      ],
      warnings: summary.warnings.map((warning) => String(warning || "")).filter(Boolean),
    };
  }

  window.ElectrochemPreflightModel = {
    buildCheckItems,
    buildFileDetailView,
    buildFileDetailCards,
    buildSummary,
    checkKeys: CHECK_KEYS.slice(),
    defaultTypes: DEFAULT_TYPES.slice(),
    statusLabelKey,
  };
})();
