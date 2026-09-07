(function () {
  "use strict";

  const MAX_SOURCES = 20;
  const MAX_PARAMETERS = 80;
  const MAX_TEXT_LENGTH = 500;

  function cleanText(value, maxLength = MAX_TEXT_LENGTH) {
    return String(value === undefined || value === null ? "" : value).trim().slice(0, maxLength);
  }

  function fileNameOnly(value) {
    const text = cleanText(value, 1000);
    const parts = text.split(/[/\\]/);
    return parts[parts.length - 1] || text;
  }

  function canonicalInputPath(value) {
    let path = String(value || "").replace(/\\/g, "/");
    const drive = /^[a-z]:\//i.test(path);
    const unc = path.startsWith("//");
    if (!drive && !path.startsWith("/")) return "";
    if (drive || unc) path = path.toLowerCase();
    const prefix = drive ? path.slice(0, 3) : unc ? "//" : "/";
    const segments = [];
    path.slice(prefix.length).split("/").forEach((part) => {
      if (!part || part === ".") return;
      if (part === "..") { if (segments.length > (unc ? 2 : 0)) segments.pop(); }
      else segments.push(part);
    });
    return prefix + segments.join("/");
  }

  function compactValue(value, key, depth = 0) {
    if (value === undefined || value === null || value === "") return undefined;
    if (typeof value === "boolean" || typeof value === "number") return value;
    if (typeof value === "string") {
      return /(file|folder|path)$/i.test(String(key || "")) ? fileNameOnly(value) : cleanText(value);
    }
    if (depth >= 2) return cleanText(JSON.stringify(value));
    if (Array.isArray(value)) {
      return value.slice(0, 12).map((item) => compactValue(item, key, depth + 1));
    }
    if (typeof value === "object") {
      const result = {};
      Object.entries(value)
        .slice(0, 30)
        .forEach(([childKey, childValue]) => {
          const compacted = compactValue(childValue, childKey, depth + 1);
          if (compacted !== undefined) result[childKey] = compacted;
        });
      return result;
    }
    return cleanText(value);
  }

  function compactParameters(parameters) {
    const source = parameters && typeof parameters === "object" ? parameters : {};
    const result = {};
    Object.entries(source)
      .slice(0, MAX_PARAMETERS)
      .forEach(([key, value]) => {
        const compacted = compactValue(value, key);
        if (compacted !== undefined) result[key] = compacted;
      });
    return result;
  }

  function normalizeSources(items) {
    return (Array.isArray(items) ? items : [])
      .filter((item) => item && item.enabled !== false)
      .slice(0, MAX_SOURCES)
      .map((item) => ({
        file: fileNameOnly(item.name || item.path),
        data_type: cleanText(item.data_type || "UNRECOGNIZED", 24),
      }));
  }

  function normalizePreflight(preflight, state) {
    const source = preflight && typeof preflight === "object" ? preflight : null;
    if (!source && !state) return null;
    return {
      state: cleanText(state || "pending", 32),
      matched: Array.isArray(source && source.counts)
        ? source.counts.map((item) => ({
            data_type: cleanText(item.dtype || item.label, 24),
            count: Number(item.matched || 0),
          }))
        : [],
      text_files: Number((source && source.textFiles) || 0),
      work_units: Number((source && source.workUnits) || 0),
      warnings: Array.isArray(source && source.warnings)
        ? source.warnings.slice(0, 10).map((item) => cleanText(item))
        : [],
    };
  }

  function normalizeResult(result, state) {
    const source = result && typeof result === "object" ? result : null;
    if (!source && !state) return null;
    return {
      state: cleanText(state || "pending", 32),
      summary: cleanText(source && source.summary, 1000),
      data_types: Array.isArray(source && source.dataTypes)
        ? source.dataTypes.slice(0, 8).map((item) => cleanText(item, 24))
        : [],
      quality: Array.isArray(source && source.qualityItems)
        ? source.qualityItems.slice(0, 20).map((item) => ({
            metric: cleanText(item.label || item.labelKey, 80),
            value: compactValue(item.value, "value"),
          }))
        : [],
      output_files: Array.isArray(source && source.outputFiles)
        ? source.outputFiles.slice(0, 20).map((item) => fileNameOnly(item.fileName || item.path))
        : [],
    };
  }

  function build(options) {
    const opts = options || {};
    const dataTypes = Array.from(
      new Set((Array.isArray(opts.dataTypes) ? opts.dataTypes : []).map((item) => cleanText(item, 24)).filter(Boolean))
    );
    const payload = opts.processPayload && typeof opts.processPayload === "object" ? opts.processPayload : {};
    const sources = normalizeSources(opts.sourceItems);
    return {
      context_type: "professional_mode_summary",
      project: cleanText(opts.projectName, 128) || null,
      data_types: dataTypes,
      template: cleanText(opts.templateName, 128) || null,
      data_source: {
        mode: sources.length ? "selected_files" : cleanText(opts.folderName) ? "folder" : "not_selected",
        folder: fileNameOnly(opts.folderName) || null,
        selected_count: sources.length,
        files: sources,
        truncated: Array.isArray(opts.sourceItems) && opts.sourceItems.filter((item) => item && item.enabled !== false).length > MAX_SOURCES,
        raw_file_content_included: false,
      },
      parameters: compactParameters(payload.params),
      configuration_warning: cleanText(opts.payloadError, 1000) || null,
      preflight: normalizePreflight(opts.preflight, opts.preflightState),
      result: normalizeResult(opts.result, opts.resultState),
    };
  }

  function summary(context, translate) {
    const ctx = context && typeof context === "object" ? context : {};
    const t = typeof translate === "function" ? translate : (key) => key;
    const parts = [];
    if (ctx.project) parts.push(`${t("assistant_context_project")}: ${ctx.project}`);
    if (Array.isArray(ctx.data_types) && ctx.data_types.length) parts.push(ctx.data_types.join(" / "));
    const count = Number(ctx.data_source && ctx.data_source.selected_count || 0);
    parts.push(count ? t("assistant_context_files").replace("{count}", String(count)) : t("assistant_context_no_files"));
    if (ctx.preflight) parts.push(t(`assistant_context_preflight_${ctx.preflight.state}`));
    if (ctx.result && ctx.result.state === "complete") parts.push(t("assistant_context_has_result"));
    return parts.filter(Boolean).join(" · ");
  }

  window.ElectrochemAssistantContext = {
    build,
    canonicalInputPath,
    compactParameters,
    normalizeSources,
    summary,
  };
})();
