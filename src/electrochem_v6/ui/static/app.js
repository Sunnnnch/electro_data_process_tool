let currentConversationId = null;
let activeAgentJobId = null;
let activeAgentRequest = null;
let conversationViewRevision = 0;
let conversationLoadRequestId = 0;
let conversationListRequestId = 0;
let conversationAutoSelect = true;
let conversationItems = [];
let hasProcessResult = false;
let templateItems = [];
let historyRecords = [];
let selectedHistoryKey = "";
let historyNextCursor = "";
let historyHasMore = false;
let historyTotal = 0;
let currentConversationKeyword = "";
let llmModelsByProvider = {};
let renamingConversationId = null;
let projectItems = [];
let activeProjectItems = [];
let selectedProjectId = "";
let projectDetailState = null;
let selectedProjectHistoryKey = "";
let projectIncludeArchived = false;
let projectListStatus = "active";
let projectFilterTimer = null;
let projectOutputTypeFilter = "";
let projectCompareSort = "eta";
let projectCompareOnlyEta = false;
let projectCompareOnlyTafel = false;
let projectCompareSelectedSamples = [];
let projectComparePlotData = null;
let projectComparePlotLoading = false;
let projectCompareChartType = "overlay";
let projectCompareMetric = "potential_at_target";
let projectCompareTargetCurrent = "10";
let projectCompareTargetCurrents = {
  target_currents: [],
  potential_target_currents: [],
  overpotential_target_currents: [],
};
let helpDocCache = {};
let activeHelpHeadingId = "";
let processPreflightState = "pending";
let activeProcessJobId = "";
let processRunState = "pending";
let expandedProcessModules = new Set(["LSV"]);
let activeResultTab = "current";
let preflightFileDetailOpen = false;
let latestPreflightScan = null;
let processSourceItems = [];
let processSourceFolders = [];
let appliedProcessTemplateName = "";
let processParameterSchema = null;
let activeProcessStepKey = "";
let processScrollSpyTicking = false;
let latestProcessResult = null;
let assistantContextSnapshot = null;
let pendingAssistantApprovalDecision = null;
let projectNavigationRevision = 0;
const assistantSourceTokens = new Map();

const uiCore = window.ElectrochemUiCore || {
  boolValue: (id) => Boolean(byId(id) && byId(id).checked),
  byId: (id) => document.getElementById(id),
  escapeHtml: (text) =>
    String(text || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;"),
  fileNameOnly: (pathText) => {
    const safe = String(pathText || "").trim();
    return safe.split(/[\\/]/).pop() || safe;
  },
  numberValue: (id) => {
    const raw = textValue(id);
    if (!raw) return undefined;
    const value = Number(raw);
    return Number.isFinite(value) ? value : undefined;
  },
  textValue: (id) => String((byId(id) && byId(id).value) || "").trim(),
};
const byId = uiCore.byId;
const textValue = uiCore.textValue;
const boolValue = uiCore.boolValue;
const numberValue = uiCore.numberValue;
const escapeHtml = uiCore.escapeHtml;
const fileNameOnly = uiCore.fileNameOnly;

const themeManager = window.ElectrochemTheme || {
  apply: (themeName) => themeName || "",
  getTheme: () => "",
  init: () => "",
  save: (themeName) => themeName || "",
};
const processSchemaClient = window.ElectrochemProcessingSchema || {
  applyToControls: () => {},
  buildModuleCards: () => [],
  controlIds: () => [],
  getCached: () => null,
  getDefault: (_schema, _key, fallback) => fallback,
  getModule: () => null,
  load: async () => null,
  moduleList: () => [],
  moduleMap: () => new Map(),
  validateControls: () => [],
};
const processPayloadBuilder = window.ElectrochemProcessPayload || {};
const processSourceSelection = window.ElectrochemProcessSourceSelection || {
  PRIMARY_TYPES: ["LSV", "CV", "EIS", "ECSA"],
  merge: (current, incoming) => (current || []).concat(incoming || []),
  preferredFolder: (_items, fallback) => fallback || "",
  toInputFiles: () => [],
};
const processRuntime = window.ElectrochemProcessRuntime || {};
const processTemplates = window.ElectrochemProcessTemplates || {};
const preflightModel = window.ElectrochemPreflightModel || {
  buildCheckItems: () => ({
    scan: null,
    items: {
      files: { state: "pending", labelKey: "preflight_status_pending" },
      params: { state: "pending", labelKey: "preflight_status_pending" },
      output: { state: "pending", labelKey: "preflight_status_pending" },
      runnable: { state: "pending", labelKey: "preflight_status_pending" },
    },
  }),
  buildFileDetailCards: () => [],
  buildSummary: () => ({
    counts: ["LSV", "CV", "EIS", "ECSA", "COUPLED"].map((dtype) => ({ dtype, matched: 0 })),
    textFiles: 0,
    warnings: [],
    workUnits: 0,
  }),
  buildFileDetailView: () => ({
    cards: [],
    metrics: [
      { labelKey: "preflight_detail_matched_files", value: 0 },
      { labelKey: "preflight_text_files", value: 0 },
      { labelKey: "preflight_work_units", value: 0 },
    ],
    warnings: [],
  }),
  checkKeys: ["files", "params", "output", "runnable"],
  defaultTypes: ["LSV", "CV", "EIS", "ECSA", "COUPLED"],
};
const projectCompareModel = window.ElectrochemProjectCompareModel || {
  availableTargetCurrents: (state, metric) => {
    const safe = state && typeof state === "object" ? state : {};
    if (metric === "overpotential_at_target") return safe.overpotential_target_currents || [];
    if (metric === "potential_at_target") return safe.potential_target_currents || [];
    return safe.target_currents || [];
  },
  filterSamples: (samples) => (Array.isArray(samples) ? [...samples] : []),
  formatTargetCurrent: (value) => String(value || ""),
  needsTargetCurrent: (chartType, metric) => chartType === "bar" && metric !== "tafel_slope",
  selectTargetCurrent: (options, currentValue, preferredValue) => {
    const normalized = (Array.isArray(options) ? options : []).map(Number).filter((item) => Number.isFinite(item) && item > 0);
    const preferred = normalized.includes(preferredValue) ? preferredValue : normalized[0];
    const current = Number(currentValue);
    const value = normalized.includes(current) ? current : preferred;
    return { options: [...new Set(normalized)], value: value !== undefined ? String(value) : "" };
  },
  syncSelectedSamples: (samples, selectedSamples, maxDefault) => {
    const names = (Array.isArray(samples) ? samples : []).map((item) => String(item.sample_name || "").trim()).filter(Boolean);
    const selected = names.filter((name) => (selectedSamples || []).includes(name));
    return {
      clearPlot: !selected.length || selected.length !== (selectedSamples || []).length,
      selectedSamples: selected.length ? selected : names.slice(0, Math.min(maxDefault || 3, names.length)),
      visibleNames: names,
    };
  },
};
const projectComparePage = window.ElectrochemProjectComparePage || {};
const processResultModel = window.ElectrochemProcessResultModel || {
  buildResultFromHistoryRecord: (record, historyLabel) => {
    const safe = record && typeof record === "object" ? record : {};
    const type = String(safe.type || "").toUpperCase();
    const files = Array.isArray(safe.output_files) && safe.output_files.length
      ? safe.output_files.map((item) => String(item))
      : safe.summary_path
        ? [String(safe.summary_path)]
        : safe.file_path || safe.file_name
          ? [String(safe.file_path || safe.file_name)]
          : [];
    return {
      data_type: type || undefined,
      data_types: type ? [type] : [],
      processing: { output_files: files },
      quality_summary: {
        status: safe.status || "-",
        project: safe.project_name || "-",
        timestamp: safe.timestamp || "-",
      },
      summary: `${historyLabel || "History record"}: ${safe.sample_name || safe.file_name || safe.file_path || "-"}`,
    };
  },
  buildResultView: (result) => {
    const safe = result && typeof result === "object" ? result : {};
    const processing = safe.processing && typeof safe.processing === "object" ? safe.processing : {};
    const outputFiles = Array.isArray(processing.output_files)
      ? processing.output_files.map((item) => {
          const path = String(item || "").trim();
          return { fileName: fileNameOnly(path), path };
        })
      : [];
    return {
      dataTypes: Array.isArray(safe.data_types) ? safe.data_types : safe.data_type ? [String(safe.data_type)] : [],
      outputFiles,
      qualityItems: [],
      skippedErrors: [],
      summary: safe.summary || "",
    };
  },
};
let processResultPage = window.ElectrochemProcessResultPage || {};
let processResultPageRetryStarted = false;
const processPage = window.ElectrochemProcessPage || {};
const assistantPage = window.ElectrochemAssistantPage || {};
const assistantContext = window.ElectrochemAssistantContext || {
  build: () => null,
  summary: () => "",
};
const aiSettingsPage = window.ElectrochemAISettingsPage || {};
const projectPage = window.ElectrochemProjectPage || {};
const projectWorkspace = window.ElectrochemProjectWorkspace || {};
const projectWorkbench = window.ElectrochemProjectWorkbench || null;
const projectPreferences = window.ElectrochemProjectPreferences || null;
const projectRecovery = window.ElectrochemProjectRecovery || null;
const projectReplay = window.ElectrochemProjectReplay || null;
const projectReplicates = window.ElectrochemProjectReplicates || null;
const assistantActions = window.ElectrochemAssistantActions || null;
const taskCenter = window.ElectrochemTaskCenter || null;
const projectHistoryWorkspace = window.ElectrochemProjectHistoryWorkspace || {};
const assistantPrompt = window.ElectrochemAssistantPrompt || {
  applyTemplate: () => {},
  buildMessage: (message) => String(message || "").trim(),
  getActivePrefix: () => "",
  load: () => {},
  renderTemplateOptions: () => {},
  save: () => {},
};
const assistantApi = window.ElectrochemAssistantApi || {
  conversationListUrl: (options) => {
    const opts = options || {};
    const query = new URLSearchParams();
    query.set("page", String(opts.page || 1));
    query.set("page_size", String(opts.pageSize || 30));
    if (opts.keyword) query.set("keyword", String(opts.keyword));
    return `/api/v1/agent/conversations?${query.toString()}`;
  },
  deleteConversation: (conversationId) =>
    apiFetch(`/api/v1/agent/conversations/${encodeURIComponent(conversationId)}/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }),
  getConversation: (conversationId) => apiFetch(`/api/v1/agent/conversations/${encodeURIComponent(conversationId)}`),
  listConversations: (options) => apiFetch(assistantApi.conversationListUrl(options)),
  renameConversation: (conversationId, title) =>
    apiFetch(`/api/v1/agent/conversations/${encodeURIComponent(conversationId)}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  sendMessageForm: (formData) => apiFetch("/api/v1/agent/messages", { method: "POST", body: formData }),
  submitMessageJobForm: (formData) => apiFetch("/api/v1/agent/jobs", { method: "POST", body: formData }),
  sendMessageJson: (payload) =>
    apiFetch("/api/v1/agent/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  submitMessageJob: (payload) =>
    apiFetch("/api/v1/agent/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  getMessageJob: (jobId) => apiFetch(`/api/v1/agent/jobs/${encodeURIComponent(jobId)}`),
  cancelMessageJob: (jobId) =>
    apiFetch(`/api/v1/agent/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }),
};
const llmApi = window.ElectrochemLLMApi || {
  getConfig: () => apiFetch("/api/v1/llm/config"),
  listModels: (payload, options = {}) => apiFetch("/api/v1/llm/models", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}), signal: options.signal,
  }),
  saveConfig: (payload) =>
    apiFetch("/api/v1/llm/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    }),
  testConfig: (payload) =>
    apiFetch("/api/v1/llm/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    }),
};
const systemApi = window.ElectrochemSystemApi || {
  health: () => apiFetch("/health"),
  openPath: (pathValue, revealOnly) =>
    apiFetch("/api/v1/system/open-path", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: pathValue, reveal_only: Boolean(revealOnly) }),
    }),
  selectFolder: (initialDir) =>
    apiFetch("/api/v1/system/select-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initial_dir: initialDir }),
    }),
  selectFile: (initialPath, extensions) =>
    apiFetch("/api/v1/system/select-file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initial_path: initialPath, extensions: extensions || [".txt", ".csv"] }),
    }),
  selectFiles: (initialPath, extensions) =>
    apiFetch("/api/v1/system/select-files", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initial_path: initialPath, extensions: extensions || [".txt", ".csv"] }),
    }),
};
const projectApi =
  window.ElectrochemProjectApi ||
  (() => {
    const buildQuery = (params) => {
      const query = new URLSearchParams();
      Object.entries(params || {}).forEach(([key, value]) => {
        if (value === undefined || value === null || value === "") return;
        if (Array.isArray(value)) {
          value.forEach((item) => query.append(key, String(item)));
          return;
        }
        query.set(key, String(value));
      });
      return query.toString();
    };
    const withQuery = (path, params) => {
      const query = buildQuery(params);
      return query ? `${path}?${query}` : path;
    };
    const postJson = (payload) => ({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    const archivedFlag = (includeArchived) => (includeArchived ? "1" : "0");
    const projectPath = (projectId, suffix = "") => `/api/v1/projects/${encodeURIComponent(projectId)}${suffix}`;
    return {
      archiveHistory: (historyKey) =>
        apiFetch("/api/v1/history/archive", postJson({ history_key: historyKey })),
      createProject: (payload) => apiFetch("/api/v1/projects", postJson(payload)),
      cleanupStorage: () => apiFetch("/api/v1/storage/cleanup", postJson({})),
      deleteHistory: (historyKey, options = {}) => apiFetch("/api/v1/history/delete", postJson({
        history_key: historyKey,
        delete_artifacts: options.deleteArtifacts !== false,
      })),
      deleteProject: (projectId) => apiFetch(projectPath(projectId, "/delete"), postJson({})),
      permanentlyDeleteProject: (projectId, options = {}) => apiFetch(
        projectPath(projectId, "/delete-permanent"),
        postJson({ delete_artifacts: options.deleteArtifacts !== false }),
      ),
      restoreProject: (projectId) => apiFetch(projectPath(projectId, "/restore"), postJson({})),
      exportReport: (projectId, options = {}) =>
        apiFetch(withQuery(projectPath(projectId, "/report"), { include_archived: archivedFlag(options.includeArchived) })),
      history: (options = {}) =>
        apiFetch(
          withQuery("/api/v1/history", {
            project: options.projectId,
            limit: options.limit,
            cursor: options.cursor,
            include_archived:
              options.includeArchived === undefined ? undefined : archivedFlag(options.includeArchived),
          })
        ),
      historyDetail: (historyKey) => apiFetch(`/api/v1/history/${encodeURIComponent(historyKey)}`),
      latestLsvComparePlot: (projectId, options = {}) =>
        apiFetch(
          withQuery(projectPath(projectId, "/lsv-compare-plot/latest"), {
            chart_type: options.chartType,
            metric: options.metric,
            target_current: options.targetCurrent,
          })
        ),
      listProjects: (options = {}) => apiFetch(withQuery("/api/v1/projects", { status: options.status || "active" })),
      lsvComparePlot: (projectId, options = {}) =>
        apiFetch(
          withQuery(projectPath(projectId, "/lsv-compare-plot"), {
            include_archived: archivedFlag(options.includeArchived),
            chart_type: options.chartType,
            metric: options.metric,
            target_current: options.targetCurrent,
            sample: Array.isArray(options.samples) ? options.samples : [],
          })
        ),
      lsvSummary: (projectId, options = {}) =>
        apiFetch(
          withQuery(projectPath(projectId, "/lsv-summary"), {
            page: options.page || 1,
            page_size: options.pageSize || 15,
            sort: options.sort || "eta",
          })
        ),
      lsvTargetCurrents: (projectId, options = {}) =>
        apiFetch(
          withQuery(projectPath(projectId, "/lsv-target-currents"), {
            include_archived: archivedFlag(options.includeArchived),
          })
        ),
      stats: (options = {}) =>
        apiFetch(
          withQuery("/api/v1/stats", {
            project: options.projectId,
            include_archived:
              options.includeArchived === undefined ? undefined : archivedFlag(options.includeArchived),
          })
        ),
      storageSummary: () => apiFetch("/api/v1/storage"),
      updateProject: (projectId, payload) => apiFetch(projectPath(projectId, "/update"), postJson(payload)),
    };
  })();
const processingApi =
  window.ElectrochemProcessingApi ||
  (() => {
    const postJson = (payload) => ({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    return {
      deleteTemplate: (name) => apiFetch(`/api/v1/process/templates/${encodeURIComponent(name)}/delete`, postJson({})),
      discoverInputs: (payload) => apiFetch("/api/v1/process/discover-inputs", postJson(payload)),
      exportDiagnostics: () => apiFetch("/api/v1/diagnostics/export", { method: "POST" }),
      listTemplates: () => apiFetch("/api/v1/process/templates"),
      preflight: (payload) => apiFetch("/api/v1/process/preflight", postJson(payload)),
      cancelProcessJob: (jobId) => apiFetch(`/api/v1/process/jobs/${encodeURIComponent(jobId)}/cancel`, postJson({})),
      getProcessJob: (jobId) => apiFetch(`/api/v1/process/jobs/${encodeURIComponent(jobId)}`),
      runProcess: (payload) => apiFetch("/api/v1/process", postJson(payload)),
      saveTemplate: (payload) => apiFetch("/api/v1/process/templates", postJson(payload)),
      submitProcessJob: (payload) => apiFetch("/api/v1/process/jobs", postJson(payload)),
    };
  })();
/* I18N translations are loaded from i18n.js (see index.html <script> order). */
const I18N = window.I18N || { zh: {}, en: {} };
const electrochemApi = window.ElectrochemApi || { fetch: (...args) => window.fetch(...args) };
const apiFetch = (...args) => electrochemApi.fetch(...args);

let currentLang = "zh";

function t(key) {
  return (I18N[currentLang] && I18N[currentLang][key]) || I18N.zh[key] || key;
}

function getPotentialMode() {
  return schemaControlValue("pro-potential-mode", "potential_mode");
}

function schemaControlValue(elementId, parameterKey) {
  const value = textValue(elementId);
  if (value !== "") return value;
  const fallback = processSchemaClient.getDefault(processParameterSchema, parameterKey, "");
  return fallback === undefined || fallback === null ? "" : String(fallback);
}

function schemaNumberDefault(parameterKey) {
  const value = processSchemaClient.getDefault(processParameterSchema, parameterKey, undefined);
  const number = Number(value);
  return Number.isFinite(number) ? number : undefined;
}

function getReferenceElectrodePotential() {
  const presetEl = byId("pro-ref-preset");
  if (!presetEl) return undefined;
  const preset = String(presetEl.value || "").trim();
  if (preset === "custom") {
    return numberValue("pro-ref-custom");
  }
  const option = presetEl.selectedOptions && presetEl.selectedOptions[0] ? presetEl.selectedOptions[0] : null;
  if (!option) return undefined;
  const raw = option.getAttribute("data-potential");
  if (!raw) return undefined;
  const value = Number(raw);
  return Number.isFinite(value) ? value : undefined;
}

function renderPotentialOffsetPreview() {
  const el = byId("potential-offset-preview");
  if (!el) return;
  const mode = getPotentialMode();
  if (mode === "formula_rhe") {
    const ph = numberValue("pro-rhe-ph");
    const temperature = numberValue("pro-rhe-temperature");
    const ref = getReferenceElectrodePotential();
    if (!Number.isFinite(ph) || !Number.isFinite(ref) || !Number.isFinite(temperature)) {
      el.textContent = t("potential_offset_preview_empty");
      return;
    }
    const slope = 2.303 * 8.31446261815324 * (temperature + 273.15) / 96485.33212;
    const value = ref + slope * ph;
    el.textContent = t("potential_offset_preview_rhe")
      .replace("{value}", value.toFixed(4))
      .replace("{ref}", ref.toFixed(4))
      .replace("{ph}", String(ph))
      .replace("{temperature}", String(temperature))
      .replace("{slope}", slope.toFixed(5));
    return;
  }
  const offset = numberValue("pro-offset");
  if (!Number.isFinite(offset)) {
    el.textContent = t("potential_offset_preview_empty");
    return;
  }
  el.textContent = t("potential_offset_preview_manual").replace("{value}", offset.toFixed(4));
}

function syncPotentialConversionUI() {
  const mode = getPotentialMode();
  const manualPanel = byId("potential-manual-panel");
  const rhePanel = byId("potential-rhe-panel");
  const manualActive = mode !== "formula_rhe";
  if (manualPanel) {
    manualPanel.classList.toggle("hidden", !manualActive);
    manualPanel.querySelectorAll("input, select, textarea").forEach((el) => {
      el.disabled = !manualActive;
    });
  }
  if (rhePanel) {
    rhePanel.classList.toggle("hidden", manualActive);
    rhePanel.querySelectorAll("input, select, textarea").forEach((el) => {
      el.disabled = manualActive;
    });
  }
  const customWrap = byId("pro-ref-custom-wrap");
  const customInput = byId("pro-ref-custom");
  const showCustom = mode === "formula_rhe" && textValue("pro-ref-preset") === "custom";
  if (customWrap) customWrap.classList.toggle("hidden", !showCustom);
  if (customInput) customInput.disabled = !showCustom;
  renderPotentialOffsetPreview();
}

function syncIrCompensationUI() {
  const enabled = boolValue("pro-lsv-ir-enabled");
  const source = schemaControlValue("pro-lsv-ir-source", "ir_source");
  const scope = schemaControlValue("pro-lsv-ir-scope", "ir_eis_search_scope");
  const groups = [
    ["ir-manual-options", enabled && source === "manual"],
    ["ir-eis-options", enabled && source !== "manual"],
    ["ir-specified-file-options", enabled && source !== "manual" && scope === "specified_file"],
  ];
  groups.forEach(([id, visible]) => {
    const group = byId(id);
    if (!group) return;
    group.classList.toggle("hidden", !visible);
    group.querySelectorAll("input, select, textarea, button").forEach((el) => {
      el.disabled = !visible;
    });
  });
}

function syncCoupledInputUI() {
  const peakMode = schemaControlValue("pro-coupled-input-mode", "coupled_input_mode") === "peak_analysis";
  const groups = [
    ["coupled-product-table-options", !peakMode],
    ["coupled-product-table-hint", !peakMode],
    ["coupled-peak-source-options", peakMode],
    ["coupled-peak-calc-options", peakMode],
  ];
  groups.forEach(([id, visible]) => {
    const group = byId(id);
    if (!group) return;
    group.classList.toggle("hidden", !visible);
    group.querySelectorAll("input, select, textarea, button").forEach((el) => {
      el.disabled = !visible;
    });
  });
  syncCoupledPeakMethodSourceUI();
}

function syncCoupledPeakMethodSourceUI() {
  const peakMode = schemaControlValue("pro-coupled-input-mode", "coupled_input_mode") === "peak_analysis";
  const methodSource = schemaControlValue("pro-coupled-peak-method-source", "coupled_peak_method_source");
  const groups = [
    ["coupled-peak-method-file-options", peakMode && methodSource === "file"],
    ["coupled-peak-method-panel-options", peakMode && methodSource === "panel"],
  ];
  groups.forEach(([id, visible]) => {
    const group = byId(id);
    if (!group) return;
    group.classList.toggle("hidden", !visible);
    group.querySelectorAll("input, select, textarea, button").forEach((el) => {
      el.disabled = !visible;
    });
  });
}

function feProductField(row, name) {
  return row ? row.querySelector(`[data-fe-product-field="${name}"]`) : null;
}

function feProductNumber(row, name) {
  const input = feProductField(row, name);
  const raw = String((input && input.value) || "").trim();
  if (!raw) return undefined;
  const value = Number(raw);
  return Number.isFinite(value) ? value : undefined;
}

function setFeProductRowValues(row, product, index) {
  const defaults = {
    name: `product_${index}`,
    expected_position: 1.9,
    polarity: "positive",
    nuclei_count: 1,
    electron_count: 2,
    response_factor: 1,
    reaction_id: "",
  };
  const values = { ...defaults, ...(product || {}) };
  Object.keys(defaults).forEach((name) => {
    const input = feProductField(row, name);
    if (input) input.value = values[name] == null ? "" : String(values[name]);
  });
}

function renumberFeProductRows() {
  const rows = Array.from(document.querySelectorAll("#fe-product-list [data-fe-product-row]"));
  rows.forEach((row, index) => {
    const number = row.querySelector("[data-fe-product-index]");
    if (number) number.textContent = String(index + 1);
    const remove = row.querySelector("[data-fe-product-remove]");
    if (remove) remove.disabled = rows.length === 1;
  });
}

function addFeProductRow(product) {
  const list = byId("fe-product-list");
  const template = list && list.querySelector("[data-fe-product-row]");
  if (!list || !template) return null;
  const row = template.cloneNode(true);
  setFeProductRowValues(row, product, list.querySelectorAll("[data-fe-product-row]").length + 1);
  list.appendChild(row);
  renumberFeProductRows();
  return row;
}

function getCoupledPeakMethodFromPanel() {
  const searchTolerance = numberValue("pro-fe-peak-search-tolerance")
    ?? schemaNumberDefault("fe_peak_search_tolerance");
  const windowLeft = numberValue("pro-fe-peak-window-left")
    ?? schemaNumberDefault("fe_peak_window_left");
  const windowRight = numberValue("pro-fe-peak-window-right")
    ?? schemaNumberDefault("fe_peak_window_right");
  const products = Array.from(document.querySelectorAll("#fe-product-list [data-fe-product-row]")).map((row) => ({
    name: String((feProductField(row, "name") && feProductField(row, "name").value) || "").trim(),
    reaction_id: String((feProductField(row, "reaction_id") && feProductField(row, "reaction_id").value) || "").trim(),
    electron_count: feProductNumber(row, "electron_count"),
    expected_position: feProductNumber(row, "expected_position"),
    nuclei_count: feProductNumber(row, "nuclei_count"),
    response_factor: feProductNumber(row, "response_factor"),
    polarity: String((feProductField(row, "polarity") && feProductField(row, "polarity").value) || "positive"),
    search_tolerance: searchTolerance,
    window_left: windowLeft,
    window_right: windowRight,
  }));
  return {
    schema_version: "1.0",
    method_id: textValue("pro-fe-method-id") || "qnmr_panel_method",
    analysis_method: "qnmr_internal_standard",
    axis_unit: textValue("pro-fe-axis-unit") || "ppm",
    internal_standard: {
      name: textValue("pro-fe-standard-name") || "internal_standard",
      expected_position: numberValue("pro-fe-standard-position"),
      nuclei_count: numberValue("pro-fe-standard-nuclei"),
      concentration_mM: numberValue("pro-fe-standard-concentration"),
      volume_uL: numberValue("pro-fe-standard-volume"),
      search_tolerance: searchTolerance,
      window_left: windowLeft,
      window_right: windowRight,
      polarity: textValue("pro-fe-standard-polarity") || "positive",
    },
    products,
    sample_defaults: {
      electrolyte_volume_mL: numberValue("pro-fe-electrolyte-volume"),
      sample_aliquot_volume_uL: numberValue("pro-fe-aliquot-volume"),
    },
  };
}

function applyCoupledPeakMethodToPanel(method) {
  if (!method || typeof method !== "object") return;
  const setValue = (id, value) => {
    const input = byId(id);
    if (input && value !== undefined && value !== null) input.value = String(value);
  };
  const standard = method.internal_standard && typeof method.internal_standard === "object"
    ? method.internal_standard
    : {};
  const defaults = method.sample_defaults && typeof method.sample_defaults === "object"
    ? method.sample_defaults
    : {};
  setValue("pro-fe-method-id", method.method_id);
  setValue("pro-fe-axis-unit", method.axis_unit);
  setValue("pro-fe-standard-name", standard.name);
  setValue("pro-fe-standard-position", standard.expected_position);
  setValue("pro-fe-standard-nuclei", standard.nuclei_count);
  setValue("pro-fe-standard-concentration", standard.concentration_mM);
  setValue("pro-fe-standard-volume", standard.volume_uL);
  setValue("pro-fe-standard-polarity", standard.polarity);
  setValue("pro-fe-electrolyte-volume", defaults.electrolyte_volume_mL);
  setValue("pro-fe-aliquot-volume", defaults.sample_aliquot_volume_uL);

  const list = byId("fe-product-list");
  const template = list && list.querySelector("[data-fe-product-row]");
  const products = Array.isArray(method.products) && method.products.length ? method.products : [{}];
  if (list && template) {
    list.replaceChildren();
    products.forEach((product, index) => {
      const row = template.cloneNode(true);
      setFeProductRowValues(row, product, index + 1);
      list.appendChild(row);
    });
  }
  renumberFeProductRows();
}

function processPayloadContext() {
  return {
    boolValue,
    currentLang,
    getSelectedInputFiles: (dataTypes) => processSourceSelection.toInputFiles(processSourceItems, dataTypes),
    getPotentialMode,
    getReferenceElectrodePotential,
    getSelectedProcessTypes,
    getCoupledPeakMethod: getCoupledPeakMethodFromPanel,
    numberValue,
    processParameterSchema,
    processSchemaClient,
    hasExplicitInputSelection: () => processSourceItems.length > 0,
    t,
    textValue,
  };
}

function collectProcessValidationErrors(dataTypes) {
  return processPayloadBuilder.collectValidationErrors(processPayloadContext(), dataTypes);
}

function formatLocalTimestamp() {
  try {
    return new Date().toLocaleTimeString(currentLang === "zh" ? "zh-CN" : "en-US", {
      hour12: false,
    });
  } catch (_err) {
    return new Date().toISOString();
  }
}

function formatMetric(value, digits = 3) {
  if (value === undefined || value === null || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  return String(num.toFixed(digits));
}

function formatTemplateString(template, values) {
  let out = String(template || "");
  Object.keys(values || {}).forEach((key) => {
    out = out.replaceAll(`{${key}}`, String(values[key] ?? ""));
  });
  return out;
}

function renderPlainText(text) {
  return escapeHtml(text).replaceAll("\n", "<br>");
}

function renderInlineMarkdown(escapedText) {
  const codeTokens = [];
  let out = String(escapedText || "");
  out = out.replace(/`([^`\n]+)`/g, (_m, code) => {
    const token = `@@INLINE_CODE_${codeTokens.length}@@`;
    codeTokens.push(`<code>${code}</code>`);
    return token;
  });

  out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_m, label, url) => {
    const safeUrl = String(url || "").replaceAll('"', "%22");
    return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });
  out = out.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");

  codeTokens.forEach((html, idx) => {
    out = out.replaceAll(`@@INLINE_CODE_${idx}@@`, html);
  });
  return out;
}

function renderMarkdownContent(text) {
  const raw = String(text || "").replaceAll("\r\n", "\n");
  const codeBlocks = [];
  const withTokens = raw.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (_m, lang, code) => {
    const token = `@@CODE_BLOCK_${codeBlocks.length}@@`;
    codeBlocks.push({
      lang: escapeHtml(lang || ""),
      code: escapeHtml(String(code || "").replace(/\n$/, "")),
    });
    return token;
  });

  const escaped = escapeHtml(withTokens);
  const lines = escaped.split("\n");
  const html = [];
  let paragraph = [];
  let listMode = null;
  let listItems = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${paragraph.map((line) => renderInlineMarkdown(line)).join("<br>")}</p>`);
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length || !listMode) return;
    const tag = listMode === "ol" ? "ol" : "ul";
    html.push(`<${tag}>${listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</${tag}>`);
    listMode = null;
    listItems = [];
  };

  lines.forEach((line) => {
    const trimmed = line.trim();
    const codeMatch = trimmed.match(/^@@CODE_BLOCK_(\d+)@@$/);
    if (!trimmed) {
      flushParagraph();
      flushList();
      return;
    }

    if (codeMatch) {
      flushParagraph();
      flushList();
      const idx = Number.parseInt(codeMatch[1], 10);
      const block = codeBlocks[idx];
      if (!block) return;
      const langCls = block.lang ? ` class="language-${block.lang}"` : "";
      html.push(`<pre><code${langCls}>${block.code}</code></pre>`);
      return;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      const level = headingMatch[1].length;
      html.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
      return;
    }

    const unorderedMatch = trimmed.match(/^[-*+]\s+(.+)$/);
    if (unorderedMatch) {
      flushParagraph();
      if (listMode && listMode !== "ul") flushList();
      listMode = "ul";
      listItems.push(unorderedMatch[1]);
      return;
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      if (listMode && listMode !== "ol") flushList();
      listMode = "ol";
      listItems.push(orderedMatch[1]);
      return;
    }

    if (trimmed.startsWith("&gt;")) {
      flushParagraph();
      flushList();
      html.push(`<blockquote>${renderInlineMarkdown(trimmed.replace(/^&gt;\s?/, ""))}</blockquote>`);
      return;
    }

    flushList();
    paragraph.push(line);
  });

  flushParagraph();
  flushList();
  const rawHtml = html.join("") || renderPlainText(raw);
  return typeof DOMPurify !== "undefined" ? DOMPurify.sanitize(rawHtml) : rawHtml;
}

function stripInlineMarkdown(text) {
  return String(text || "")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
    .replace(/[`*_#>~-]/g, "")
    .trim();
}

function slugifyHeading(text, seen) {
  const base =
    stripInlineMarkdown(text)
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^\w\u4e00-\u9fff]+/g, "-")
      .replace(/^-+|-+$/g, "") || "section";
  let id = base;
  let idx = 2;
  while (seen.has(id)) {
    id = `${base}-${idx}`;
    idx += 1;
  }
  seen.add(id);
  return id;
}

function renderMarkdownDocument(text) {
  const raw = String(text || "").replaceAll("\r\n", "\n");
  const codeBlocks = [];
  const withTokens = raw.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (_m, lang, code) => {
    const token = `@@CODE_BLOCK_${codeBlocks.length}@@`;
    codeBlocks.push({
      lang: escapeHtml(lang || ""),
      code: escapeHtml(String(code || "").replace(/\n$/, "")),
    });
    return token;
  });

  const rawLines = withTokens.split("\n");
  const escapedLines = escapeHtml(withTokens).split("\n");
  const html = [];
  const toc = [];
  const seenIds = new Set();
  let paragraph = [];
  let listMode = null;
  let listItems = [];

  // Only the bundled manual can link its fixed demonstration download.
  // Keep inline code and the assistant's Markdown renderer unchanged.
  const renderDocumentInline = (line) => String(line).split(/(`[^`\n]+`)/g).map((part) => {
    if (part.startsWith("`") && part.endsWith("`")) return renderInlineMarkdown(part);
    return part.split(/(\[[^\]\n]+\]\(guide-cv-demo\.csv\))/g).map((segment) => {
      const link = segment.match(/^\[([^\]\n]+)\]\(guide-cv-demo\.csv\)$/);
      return link ? `<a href="/ui/static/guide-cv-demo.csv" download="CV_demo.csv">${renderInlineMarkdown(link[1])}</a>` : renderInlineMarkdown(segment);
    }).join("");
  }).join("");

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${paragraph.map((line) => renderDocumentInline(line)).join("<br>")}</p>`);
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length || !listMode) return;
    const tag = listMode === "ol" ? "ol" : "ul";
    html.push(`<${tag}>${listItems.map((item) => `<li>${renderDocumentInline(item)}</li>`).join("")}</${tag}>`);
    listMode = null;
    listItems = [];
  };

  rawLines.forEach((rawLine, idx) => {
    const line = escapedLines[idx] || "";
    const trimmed = line.trim();
    const trimmedRaw = String(rawLine || "").trim();
    const codeMatch = trimmed.match(/^@@CODE_BLOCK_(\d+)@@$/);
    if (!trimmedRaw) {
      flushParagraph();
      flushList();
      return;
    }

    if (codeMatch) {
      flushParagraph();
      flushList();
      const block = codeBlocks[Number.parseInt(codeMatch[1], 10)];
      if (!block) return;
      const langCls = block.lang ? ` class="language-${block.lang}"` : "";
      html.push(`<pre><code${langCls}>${block.code}</code></pre>`);
      return;
    }

    const imageMatch = trimmedRaw.match(/^!\[([^\]]*)\]\((guide-(?:professional|project)\.(?:zh|en)\.png)\)$/);
    if (imageMatch) {
      flushParagraph();
      flushList();
      const alt = escapeHtml(imageMatch[1]);
      html.push(`<figure class="help-guide-figure"><a href="/ui/static/${imageMatch[2]}" target="_blank" rel="noopener noreferrer"><img src="/ui/static/${imageMatch[2]}" alt="${alt}" loading="lazy"></a><figcaption>${alt}</figcaption></figure>`);
      return;
    }

    const headingMatch = trimmedRaw.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      const level = headingMatch[1].length;
      const titleRaw = headingMatch[2];
      const titleEscaped = escapeHtml(titleRaw);
      const id = slugifyHeading(titleRaw, seenIds);
      html.push(`<h${level} id="${id}" class="doc-heading level-${level}">${renderDocumentInline(titleEscaped)}</h${level}>`);
      if (level >= 2 && level <= 4) {
        toc.push({ id, level, text: stripInlineMarkdown(titleRaw) });
      }
      return;
    }

    const unorderedMatch = trimmed.match(/^[-*+]\s+(.+)$/);
    if (unorderedMatch) {
      flushParagraph();
      if (listMode && listMode !== "ul") flushList();
      listMode = "ul";
      listItems.push(unorderedMatch[1]);
      return;
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      if (listMode && listMode !== "ol") flushList();
      listMode = "ol";
      listItems.push(orderedMatch[1]);
      return;
    }

    if (trimmed.startsWith("&gt;")) {
      flushParagraph();
      flushList();
      html.push(`<blockquote>${renderDocumentInline(trimmed.replace(/^&gt;\s?/, ""))}</blockquote>`);
      return;
    }

    flushList();
    paragraph.push(line);
  });

  flushParagraph();
  flushList();
  const rawHtml = html.join("") || renderPlainText(raw);
  const safeHtml = typeof DOMPurify !== "undefined" ? DOMPurify.sanitize(rawHtml, { ADD_ATTR: ["target"] }) : rawHtml;
  return {
    html: safeHtml,
    toc,
  };
}

function roleTextByRole(role) {
  if (role === "agent") return "AI";
  return assistantPage.roleTextByRole(role, currentLang);
}

function renderMessageBody(role, content) {
  return assistantPage.renderMessageBody({
    content,
    renderAgentContent: renderMarkdownContent,
    renderUserContent: renderPlainText,
    role,
  });
}

function renderMessageItem(role, content, timestamp) {
  return assistantPage.renderMessageItem({
    content,
    escapeHtml,
    lang: currentLang,
    renderAgentContent: renderMarkdownContent,
    renderUserContent: renderPlainText,
    role,
    timestamp,
  });
}

function ensureChatLogReady() {
  return assistantPage.ensureChatLogReady({ byId });
}

function appendLocalMessage(role, content) {
  assistantPage.appendLocalMessage({
    byId,
    content,
    escapeHtml,
    lang: currentLang,
    renderAgentContent: renderMarkdownContent,
    renderUserContent: renderPlainText,
    role,
    timestamp: formatLocalTimestamp(),
  });
}

function removeTypingIndicator() {
  assistantPage.removeTypingIndicator({ byId });
}

function showTypingIndicator() {
  assistantPage.showTypingIndicator({ byId, escapeHtml, t });
}

function closeInlineHelpPopovers(except = null) {
  document.querySelectorAll(".inline-help[open]").forEach((el) => {
    if (el !== except) el.open = false;
  });
}

function createInlineHelp(label, lines) {
  const details = document.createElement("details");
  details.className = "inline-help";

  const summary = document.createElement("summary");
  summary.textContent = "i";
  summary.setAttribute("aria-label", label);
  summary.setAttribute("title", label);

  const popover = document.createElement("div");
  popover.className = "inline-help-popover";

  const safeLines = lines.map((line) => String(line || "").trim()).filter(Boolean);
  if (safeLines.length > 1) {
    const list = document.createElement("ul");
    safeLines.forEach((line) => {
      const item = document.createElement("li");
      item.textContent = line;
      list.appendChild(item);
    });
    popover.appendChild(list);
  } else {
    popover.textContent = safeLines[0] || label;
  }

  details.appendChild(summary);
  details.appendChild(popover);
  details.addEventListener("toggle", () => {
    if (details.open) closeInlineHelpPopovers(details);
  });
  return details;
}

function attachInlineHelp(target, label, lines) {
  if (!target) return;
  target.querySelectorAll(".inline-help").forEach((el) => el.remove());
  const safeLines = lines.map((line) => String(line || "").trim()).filter(Boolean);
  if (!safeLines.length) return;
  target.appendChild(createInlineHelp(label, safeLines));
}

function renderInlineHelpPopovers() {
  attachInlineHelp(document.querySelector(".common-params-section .process-section-head h4"), t("inline_help_common_label"), [
    t("inline_help_common_line1"),
    t("inline_help_common_line2"),
    t("inline_help_common_line3"),
  ]);
  attachInlineHelp(document.querySelector(".module-params-section > .process-section-head h4"), t("inline_help_modules_label"), [
    t("inline_help_modules_line1"),
    t("inline_help_modules_line2"),
  ]);

  document.querySelectorAll(".module-group-title .inline-help").forEach((el) => {
    el.remove();
  });

  document.querySelectorAll(".module-advanced-control").forEach((control) => {
    const title = control.querySelector("label > span");
    const note = control.querySelector(":scope > span[data-i18n='module_advanced_hint']");
    if (!title || !note) return;
    attachInlineHelp(title, t("inline_help_advanced_label"), [note.textContent]);
  });
}

function applyI18n() {
  document.documentElement.lang = currentLang === "zh" ? "zh-CN" : "en";
  document.title = t("hero_title");
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    el.textContent = t(key);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    el.setAttribute("placeholder", t(key));
  });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    const key = el.getAttribute("data-i18n-title");
    el.setAttribute("title", t(key));
  });
  const langSelect = byId("lang-select");
  if (langSelect) langSelect.value = currentLang;
  if (byId("project-include-archived")) byId("project-include-archived").checked = projectIncludeArchived;
  if (byId("project-output-type-filter")) byId("project-output-type-filter").value = projectOutputTypeFilter;
  if (byId("project-compare-sort")) byId("project-compare-sort").value = projectCompareSort;
  if (byId("project-compare-only-eta")) byId("project-compare-only-eta").checked = projectCompareOnlyEta;
  if (byId("project-compare-only-tafel")) byId("project-compare-only-tafel").checked = projectCompareOnlyTafel;
  if (byId("project-compare-chart-type")) byId("project-compare-chart-type").value = projectCompareChartType;
  if (byId("project-compare-metric")) byId("project-compare-metric").value = projectCompareMetric;
  if (byId("project-compare-target-current")) byId("project-compare-target-current").value = projectCompareTargetCurrent;
  if (byId("help-panel") && !byId("help-panel").classList.contains("hidden")) loadHelpDocument(true);
  syncAllMatchFieldMeta();
  syncPotentialConversionUI();
  syncProcessModulePanels();
  setResultTab(activeResultTab);
  syncProjectCompareControls();
  renderPromptTemplateOptions();
  syncProcessProjectOptions();
  renderPreflightFileDetail();
  renderProjectList(projectItems);
  renderSelectedProjectDetail();
  renderInlineHelpPopovers();
  if (projectPreferences) {
    projectPreferences.refresh(projectPreferencesContext());
    ["project-create", "project-edit"].forEach((prefix) => projectPreferences.renderColors(projectPreferencesContext(), prefix));
  }
  renderProcessTypeCards(processParameterSchema);
  updateProcessStepState();
  setActiveProcessJob(activeProcessJobId);
  if (activeAgentJobId && byId("send-btn")) byId("send-btn").textContent = t("btn_cancel_ai");
  if (window.ElectrochemAppearance) window.ElectrochemAppearance.refresh();
  if (window.ElectrochemDesktop) window.ElectrochemDesktop.refresh();
}

function setSendStatus(text) {
  byId("send-status").textContent = text || "";
}

function setLLMStatus(text) {
  const el = byId("llm-status");
  if (el) el.textContent = text || "";
}

function setProcStatus(text) {
  byId("proc-status").textContent = text || "";
}

function setActiveProcessJob(jobId) {
  activeProcessJobId = String(jobId || "");
  const label = activeProcessJobId ? t("process_job_cancel") : t("btn_run");
  ["proc-run"].forEach((id) => {
    const button = byId(id);
    if (button) button.textContent = label;
  });
  const panel = byId("process-job-panel");
  if (panel) panel.classList.toggle("hidden", !activeProcessJobId);
}

function setProcessSubmitting(submitting) {
  const button = byId("proc-run");
  if (button) button.disabled = Boolean(submitting);
}

function updateProcessJobProgress(job) {
  const safe = job && typeof job === "object" ? job : {};
  const current = Math.max(0, Number(safe.progress_current || 0));
  const total = Math.max(0, Number(safe.progress_total || 0));
  const progress = byId("process-job-progress");
  if (progress) {
    progress.max = total || 1;
    progress.value = Math.min(current, total || 1);
  }
  const text = byId("process-job-progress-text");
  if (text) {
    text.textContent = t("process_job_progress")
      .replace("{current}", String(current))
      .replace("{total}", String(total || "?"))
      .replace("{item}", String(safe.current_item || ""));
  }
}

async function loadProcessingParameterSchema() {
  try {
    processParameterSchema = await processSchemaClient.load();
    renderProcessTypeCards(processParameterSchema);
    processSchemaClient.applyToControls(processParameterSchema);
    syncAllMatchFieldMeta();
    syncPotentialConversionUI();
    syncFeatureBlocks();
    toggleDataTypePanels();
  } catch (err) {
    processParameterSchema = null;
    setProcStatus(`${t("proc_schema_unavailable")}: ${err.message}`);
  }
}

function setProjectStatus(text) {
  const el = byId("project-status");
  if (el) el.textContent = text || "";
}

function setFileActionStatus(text) {
  setProcStatus(text);
  setProjectStatus(text);
}

function setTemplateStatus(text) {
  const el = byId("tmpl-status");
  if (el) el.textContent = text || "";
}

function syncProcessProjectOptions() {
  const select = byId("proc-project");
  if (!select) return;
  const previous = String(select.value || "").trim();
  const options = [
    `<option value="">${escapeHtml(t("proc_project_optional"))}</option>`,
    ...(projectListStatus === "archived" ? activeProjectItems : projectItems)
      .map((item) => {
        const name = String(item && item.name ? item.name : "").trim();
        if (!name) return "";
        return `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`;
      })
      .filter(Boolean),
  ];
  select.innerHTML = options.join("");
  const hasPrevious = (projectListStatus === "archived" ? activeProjectItems : projectItems).some(
    (item) => String(item && item.name ? item.name : "").trim() === previous
  );
  select.value = hasPrevious ? previous : "";
}

function matchDefaultValue(baseId) {
  const module = processSchemaClient.getModule(processParameterSchema, baseId);
  return String(module && module.file_match && module.file_match.default_value || "");
}

function matchDefaultMode(baseId) {
  const module = processSchemaClient.getModule(processParameterSchema, baseId);
  return String(module && module.file_match && module.file_match.default_mode || "");
}

function syncMatchFieldMeta(baseId) {
  const matchEl = byId(`pro-${baseId}-match`);
  const valueEl = byId(`pro-${baseId}-prefix`);
  const labelEl = byId(`pro-${baseId}-prefix-label`);
  if (!matchEl || !valueEl || !labelEl) return;
  const mode = String(matchEl.value || matchDefaultMode(baseId)).toLowerCase();
  let labelKey = "match_value_prefix";
  let titleKey = "match_title_prefix";
  let placeholderKey = "match_placeholder_prefix";
  if (mode === "contains") {
    labelKey = "match_value_contains";
    titleKey = "match_title_contains";
    placeholderKey = "match_placeholder_contains";
  } else if (mode === "regex") {
    labelKey = "match_value_regex";
    titleKey = "match_title_regex";
    placeholderKey = "match_placeholder_regex";
  }
  labelEl.textContent = t(labelKey);
  valueEl.title = t(titleKey);
  valueEl.placeholder = formatTemplateString(t(placeholderKey), {
    key: baseId,
    default: matchDefaultValue(baseId),
  });
}

function syncAllMatchFieldMeta() {
  document.querySelectorAll("[data-match-label]").forEach((label) => {
    const baseId = String(label.dataset.matchLabel || "").trim().toLowerCase();
    if (baseId) syncMatchFieldMeta(baseId);
  });
}

function setActiveHelpToc(targetId) {
  activeHelpHeadingId = targetId || "";
  document.querySelectorAll(".help-toc-link").forEach((el) => {
    el.classList.toggle("active", el.dataset.target === activeHelpHeadingId);
  });
}

function renderHelpToc(items) {
  const tocEl = byId("help-doc-toc-items");
  if (!tocEl) return;
  const entries = Array.isArray(items) ? items : [];
  if (!entries.length) {
    tocEl.innerHTML = `<div class="placeholder">${escapeHtml(t("help_docs_toc_empty"))}</div>`;
    setActiveHelpToc("");
    return;
  }
  tocEl.innerHTML = entries
    .map(
      (item) =>
        `<button class="help-toc-link level-${item.level}" type="button" data-target="${escapeHtml(item.id)}">${escapeHtml(item.text)}</button>`
    )
    .join("");
  setActiveHelpToc(entries[0].id);
}

function refreshHelpTocActive() {
  const scrollEl = byId("help-doc-scroll");
  if (!scrollEl) return;
  const headings = [...scrollEl.querySelectorAll(".doc-heading[id]")];
  if (!headings.length) {
    setActiveHelpToc("");
    return;
  }
  const currentTop = scrollEl.scrollTop + 36;
  let activeId = headings[0].id;
  headings.forEach((heading) => {
    if (heading.offsetTop <= currentTop) activeId = heading.id;
  });
  setActiveHelpToc(activeId);
}

function jumpToHelpHeading(targetId) {
  const target = byId(targetId);
  if (!target) return;
  target.scrollIntoView({
    behavior: "smooth",
    block: "start",
    inline: "nearest",
  });
  setActiveHelpToc(targetId);
}

function templateContext() {
  return {
    byId,
    confirm: (message) => window.confirm(message),
    applyCoupledPeakMethodState: applyCoupledPeakMethodToPanel,
    getCoupledPeakMethodState: getCoupledPeakMethodFromPanel,
    getSelectedProcessTypes,
    getTemplateItems: () => templateItems,
    onTemplateApplied: () => {
      appliedProcessTemplateName = textValue("tmpl-select");
      const state = processRuntime.resetState();
      processPreflightState = state.preflightState;
      processRunState = state.runState;
      toggleDataTypePanels();
      syncFeatureBlocks();
      syncPotentialConversionUI();
      renderProcessSourceList();
    },
    processingApi,
    setTemplateItems: (items) => {
      templateItems = Array.isArray(items) ? items : [];
      if (appliedProcessTemplateName && !templateItems.some((item) => item.name === appliedProcessTemplateName)) {
        appliedProcessTemplateName = "";
      }
      if (projectPreferences) projectPreferences.refresh(projectPreferencesContext());
    },
    setTemplateStatus,
    t,
    textValue,
  };
}

function getCurrentTemplateState() {
  return processTemplates.getCurrentState(templateContext());
}

function applyTemplateState(state) {
  processTemplates.applyState(templateContext(), state);
}

function renderTemplateOptions() {
  processTemplates.renderOptions(templateContext());
}

async function loadTemplates() {
  await processTemplates.loadTemplates(templateContext());
}

async function saveTemplate(overwrite = false) {
  await processTemplates.saveTemplate(templateContext(), overwrite);
}

function loadSelectedTemplate() {
  processTemplates.loadSelectedTemplate(templateContext());
}

async function deleteSelectedTemplate() {
  const selectedName = textValue("tmpl-select");
  const result = await processTemplates.deleteSelectedTemplate(templateContext());
  if (result && selectedName === appliedProcessTemplateName) {
    appliedProcessTemplateName = "";
    updateProcessStepState();
  }
}

function processResultContext() {
  return {
    bindFileActions: bindProjectFileActions,
    byId,
    escapeHtml,
    processResultModel,
    setResultTab,
    t,
    updateProcessStepState,
  };
}

function applyProcessResultState(state) {
  if (!state || typeof state !== "object") return;
  hasProcessResult = Boolean(state.hasProcessResult);
  processRunState = state.processRunState || processRunState;
}

function renderResultPlaceholder() {
  latestProcessResult = null;
  applyProcessResultState(processResultPage.renderPlaceholder(processResultContext()));
}

function renderProcessResult(result) {
  latestProcessResult = result && typeof result === "object" ? result : null;
  applyProcessResultState(processResultPage.renderResult(processResultContext(), result));
}

function renderProcessError(message) {
  latestProcessResult = { summary: String(message || ""), error: String(message || "") };
  applyProcessResultState(processResultPage.renderError(processResultContext(), message));
}

function setSystemStatus(state, text, version) {
  if (state === "ok" && window.ElectrochemDesktop && window.ElectrochemDesktop.isEnabled()) text = currentLang === "en" ? "Desktop app ready" : "本机版就绪";
  const btn = byId("sys-status-btn");
  const textEl = byId("sys-status-text");
  const panelHealth = byId("sys-panel-health");
  const panelVersion = byId("sys-panel-version");

  if (btn) {
    btn.classList.remove("pending", "ok", "error");
    btn.classList.add(state);
  }
  if (textEl) textEl.textContent = text || "-";
  if (panelHealth) panelHealth.textContent = text || "-";
  if (panelVersion) panelVersion.textContent = version || "-";
}

function openSystemPanel() {
  loadStorageSummary();
  byId("sys-panel-mask").classList.remove("hidden");
  byId("sys-panel").classList.remove("hidden");
}

function closeSystemPanel() {
  byId("sys-panel-mask").classList.add("hidden");
  byId("sys-panel").classList.add("hidden");
}

function getHelpDocUrls() {
  if (currentLang === "en") {
    return ["/ui/static/help_manual.en.md", "/ui/static/help_manual.zh.md"];
  }
  return ["/ui/static/help_manual.zh.md"];
}

async function loadHelpDocument(force = false) {
  const body = byId("help-doc-body");
  const tocEl = byId("help-doc-toc-items");
  const scrollEl = byId("help-doc-scroll");
  if (!body || !tocEl || !scrollEl) return;
  const cacheKey = currentLang;
  if (!force && helpDocCache[cacheKey]) {
    const rendered = renderMarkdownDocument(helpDocCache[cacheKey]);
    body.innerHTML = rendered.html || `<div class="placeholder">${escapeHtml(t("help_docs_empty"))}</div>`;
    renderHelpToc(rendered.toc);
    scrollEl.scrollTop = 0;
    refreshHelpTocActive();
    return;
  }
  body.innerHTML = `<div class="placeholder">${escapeHtml(t("help_docs_loading"))}</div>`;
  tocEl.innerHTML = `<div class="placeholder">${escapeHtml(t("help_docs_loading"))}</div>`;
  let loaded = "";
  let lastError = null;
  for (const url of getHelpDocUrls()) {
    try {
      const resp = await apiFetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const text = await resp.text();
      if (text.trim()) {
        loaded = text;
        break;
      }
    } catch (err) {
      lastError = err;
    }
  }
  if (!loaded.trim()) {
    body.innerHTML = `<div class="placeholder">${escapeHtml(t("help_docs_failed"))}${lastError ? `: ${escapeHtml(lastError.message || "")}` : ""}</div>`;
    tocEl.innerHTML = `<div class="placeholder">${escapeHtml(t("help_docs_toc_empty"))}</div>`;
    return;
  }
  helpDocCache[cacheKey] = loaded;
  const rendered = renderMarkdownDocument(loaded);
  body.innerHTML = rendered.html || `<div class="placeholder">${escapeHtml(t("help_docs_empty"))}</div>`;
  renderHelpToc(rendered.toc);
  scrollEl.scrollTop = 0;
  refreshHelpTocActive();
}

function openHelpPanel() {
  byId("help-panel-mask").classList.remove("hidden");
  byId("help-panel").classList.remove("hidden");
  loadHelpDocument();
}

function closeHelpPanel() {
  byId("help-panel-mask").classList.add("hidden");
  byId("help-panel").classList.add("hidden");
}

function openAISettingsPanel() {
  assistantPage.setPanelOpen({ byId, maskId: "ai-settings-mask", open: true, panelId: "ai-settings-panel" });
  aiSettingsPage.scheduleModelDiscovery(aiSettingsContext());
}

function closeAISettingsPanel() {
  aiSettingsPage.clearModelDiscovery(aiSettingsContext());
  assistantPage.setPanelOpen({ byId, maskId: "ai-settings-mask", open: false, panelId: "ai-settings-panel" });
}

function aiSettingsContext() {
  return {
    assistantPage,
    assistantPrompt,
    byId,
    getModelsByProvider: () => llmModelsByProvider,
    llmApi,
    setLLMStatus,
    setModelsByProvider: (models) => {
      llmModelsByProvider = models && typeof models === "object" ? models : {};
    },
    t,
    textValue,
  };
}

function loadPromptSettings() {
  aiSettingsPage.loadPromptSettings(aiSettingsContext());
}

function renderPromptTemplateOptions() {
  aiSettingsPage.renderPromptTemplateOptions(aiSettingsContext());
}

function savePromptSettings() {
  aiSettingsPage.savePromptSettings(aiSettingsContext());
}

function applyPromptTemplate() {
  aiSettingsPage.applyPromptTemplate(aiSettingsContext());
}

function buildPromptedMessage(message) {
  return aiSettingsPage.buildPromptedMessage(aiSettingsContext(), message);
}

function getActivePromptPrefix() {
  return aiSettingsPage.getActivePromptPrefix(aiSettingsContext());
}

function buildProfessionalModeContext() {
  const dataTypes = getSelectedProcessTypes();
  let processPayload = { params: {} };
  let payloadError = "";
  try {
    processPayload = collectProcessPayload();
  } catch (err) {
    payloadError = err && err.message ? err.message : String(err || "");
  }
  const moduleDescriptors = processSchemaClient.moduleList(processParameterSchema);
  const preflight = latestPreflightScan
    ? preflightModel.buildSummary(latestPreflightScan, dataTypes, moduleDescriptors)
    : null;
  const result = latestProcessResult
    ? processResultModel.buildResultView(latestProcessResult)
    : null;
  const context = assistantContext.build({
    dataTypes,
    folderName: textValue("proc-folder"),
    payloadError,
    preflight,
    preflightState: processPreflightState,
    processPayload,
    projectName: textValue("proc-project"),
    result,
    resultState: processRunState,
    sourceItems: processSourceItems,
    templateName: appliedProcessTemplateName,
  });
  const inProjects = byId("tab-project").classList.contains("active");
  const selectedKeys = inProjects && projectWorkbench ? projectWorkbench.selectedKeys() : [];
  const detailKey = inProjects ? selectedProjectHistoryKey : selectedHistoryKey;
  const keys = selectedKeys.length ? selectedKeys : detailKey ? [detailKey] : [];
  const selectedRecord = inProjects && projectDetailState ? (projectDetailState.history || []).find((item) => historyRecordKey(item) === detailKey) : historyRecords.find((item) => historyRecordKey(item) === detailKey);
  const lastRun = latestProcessResult && latestProcessResult.manifest && latestProcessResult.manifest.run;
  const processProject = projectItems.concat(activeProjectItems).find((item) => item.name === textValue("proc-project"));
  context.action_context = {
    project_id: inProjects ? selectedProjectId || null : processPayload.project_id || (processProject && processProject.id) || (selectedRecord && selectedRecord.project_id) || null,
    record_keys: keys,
    run_id: selectedRecord && selectedRecord.run_id || (!inProjects && lastRun && lastRun.run_id) || null,
  };
  return context;
}

async function buildAssistantActionContext() {
  const context = buildProfessionalModeContext();
  let payload;
  try { payload = collectProcessPayload(); }
  catch (_error) { payload = { folder_path: textValue("proc-folder"), input_files: processSourceItems, parameters: context.parameters }; }
  const source = JSON.stringify({ folder_path: payload.folder_path, input_files: payload.input_files, params: payload.params || payload.parameters, data_types: context.data_types, project_id: context.action_context.project_id });
  if (window.crypto && window.crypto.subtle) {
    const sha256 = async (value) => {
      const digest = await window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
      return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
    };
    const inputs = Array.isArray(payload.input_files) ? payload.input_files : processSourceItems;
    const paths = inputs.filter((item) => item && item.enabled !== false && (!item.data_type || context.data_types.includes(item.data_type)))
      .map((item) => assistantContext.canonicalInputPath(typeof item === "string" ? item : item.path)).filter(Boolean);
    const [signature, pathSignatures] = await Promise.all([sha256(source), Promise.all([...new Set(paths)].map(sha256))]);
    context.action_context.parameter_signature = signature;
    context.action_context.input_path_signatures = pathSignatures.sort();
  } else {
    // A page-local opaque token fails closed after reload in older webviews.
    if (!assistantSourceTokens.has(source)) assistantSourceTokens.set(source, `${Date.now()}-${Math.random()}-${assistantSourceTokens.size}`);
    context.action_context.parameter_signature = assistantSourceTokens.get(source);
    context.action_context.input_path_signatures = [];
  }
  return context;
}

function refreshAssistantContextPreview() {
  const summaryEl = byId("assistant-context-summary");
  const previewEl = byId("assistant-context-preview");
  assistantContextSnapshot = buildProfessionalModeContext();
  if (summaryEl) summaryEl.textContent = assistantContext.summary(assistantContextSnapshot, t);
  if (previewEl) previewEl.textContent = JSON.stringify(assistantContextSnapshot, null, 2);
  return assistantContextSnapshot;
}

function setAssistantDrawerOpen(open) {
  const drawer = byId("assistant-drawer");
  const fab = byId("assistant-fab");
  if (!drawer) return;
  drawer.classList.toggle("hidden", !open);
  drawer.setAttribute("aria-hidden", open ? "false" : "true");
  if (fab) fab.setAttribute("aria-expanded", open ? "true" : "false");
  if (window.ElectrochemDesktop) window.ElectrochemDesktop.changed();
  if (open) {
    refreshAssistantContextPreview();
    window.setTimeout(() => {
      const input = byId("msg-input");
      if (input) input.focus();
    }, 0);
  }
}

function openAssistantDrawer() {
  setAssistantDrawerOpen(true);
}

function closeAssistantDrawer() {
  setAssistantDrawerOpen(false);
}

function toggleAssistantHistory() {
  const panel = byId("assistant-conversation-panel");
  const button = byId("assistant-history-toggle");
  if (!panel) return;
  const open = panel.classList.contains("hidden");
  panel.classList.toggle("hidden", !open);
  if (button) button.setAttribute("aria-expanded", open ? "true" : "false");
}

function prepareProfessionalAdvicePrompt() {
  openAssistantDrawer();
  refreshAssistantContextPreview();
  const input = byId("msg-input");
  if (!input) return;
  input.value = t("assistant_context_suggest_prompt");
  input.focus();
  setSendStatus(t("assistant_context_prompt_ready"));
}

function prepareDatabaseAdvicePrompt() {
  openAssistantDrawer();
  const input = byId("msg-input");
  if (!input) return;
  input.value = t("assistant_database_suggest_prompt");
  input.focus();
  setSendStatus(t("assistant_context_prompt_ready"));
}

function switchTab(tabName) {
  if (tabName === "ai") {
    openAssistantDrawer();
    return;
  }
  const tabs = ["pro", "project"];
  tabs.forEach((name) => {
    const active = tabName === name;
    const btn = byId(`tab-btn-${name}`);
    const panel = byId(`tab-${name}`);
    if (btn) btn.classList.toggle("active", active);
    if (panel) panel.classList.toggle("active", active);
  });
  document.querySelectorAll(".side-mode-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.sideTab === tabName);
  });
  if (tabName === "pro") {
    requestProcessScrollSpyUpdate();
  }
  if (window.ElectrochemDesktop) window.ElectrochemDesktop.changed();
}

function renderMessages(messages) {
  assistantPage.renderMessages({
    byId,
    escapeHtml,
    lang: currentLang,
    messages,
    renderAgentContent: renderMarkdownContent,
    renderUserContent: renderPlainText,
    t,
  });
}

function startNewConversation() {
  currentConversationId = null;
  conversationViewRevision += 1;
  conversationLoadRequestId += 1;
  conversationAutoSelect = false;
  byId("conv-title").textContent = t("conv_new");
  byId("conv-meta").textContent = t("conv_new_hint");
  renderMessages([]);
  renderConversations(conversationItems);
  setSendStatus(t("conv_new"));
}

function isAgentRequestVisible(request) {
  return conversationViewRevision === request.viewRevision
    || Boolean(request.conversationId && currentConversationId === request.conversationId);
}

async function deleteConversation(conversationId) {
  if (!conversationId) return;
  setSendStatus(t("status_delete_running"));
  try {
    const resp = await assistantApi.deleteConversation(conversationId);
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("status_delete_failed"));
    }
    if (conversationId === currentConversationId) {
      startNewConversation();
    }
    await loadConversations();
    setSendStatus(t("status_delete_success"));
  } catch (err) {
    setSendStatus(`${t("status_delete_failed")}: ${err.message}`);
  }
}

async function renameConversation(conversationId, nextTitleInput) {
  if (!conversationId) return;
  const target = (conversationItems || []).find((it) => it.conversation_id === conversationId);
  const oldTitle = (target && target.title) || t("conv_rename_default");
  const title = String(nextTitleInput || "").trim();
  if (!title) {
    setSendStatus(t("status_rename_empty"));
    return;
  }
  setSendStatus(t("status_rename_running"));
  try {
    const resp = await assistantApi.renameConversation(conversationId, title);
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("status_rename_failed"));
    }
    if (conversationId === currentConversationId) {
      byId("conv-title").textContent = title;
    }
    renamingConversationId = null;
    await loadConversations();
    setSendStatus(t("status_rename_success"));
  } catch (err) {
    setSendStatus(`${t("status_rename_failed")}: ${err.message}`);
  }
}

function renderConversations(items) {
  const listEl = byId("conv-list");
  conversationItems = Array.isArray(items) ? items : [];
  if (renamingConversationId && !conversationItems.some((it) => it.conversation_id === renamingConversationId)) {
    renamingConversationId = null;
  }
  assistantPage.renderConversations({
    callbacks: {
      cancelRename: () => {
        renamingConversationId = null;
        renderConversations(conversationItems);
      },
      delete: deleteConversation,
      open: openConversation,
      saveRename: renameConversation,
      startRename: (conversationId) => {
        renamingConversationId = conversationId;
        renderConversations(conversationItems);
        assistantPage.focusRenameInput(listEl, renamingConversationId);
      },
    },
    currentConversationId,
    escapeHtml,
    items: conversationItems,
    listEl,
    renamingConversationId,
    t,
  });
}

async function fetchHealth() {
  setSystemStatus("pending", t("health_checking"), "-");
  try {
    const resp = await systemApi.health();
    const data = await resp.json();
    if (resp.ok && data.status === "ok") {
      setSystemStatus("ok", t("health_online"), data.version || "unknown");
      return;
    }
    setSystemStatus("error", t("health_error"), "-");
  } catch (_err) {
    setSystemStatus("error", t("health_offline"), "-");
  }
}

function listLLMProviders() {
  return aiSettingsPage.listLLMProviders(aiSettingsContext());
}

function updateLLMKeyHint(provider) {
  aiSettingsPage.updateLLMKeyHint(aiSettingsContext(), provider);
}

function applyLLMProviderPreset(provider) {
  aiSettingsPage.applyLLMProviderPreset(aiSettingsContext(), provider);
}

function renderLLMProviders(defaultProvider) {
  aiSettingsPage.renderLLMProviders(aiSettingsContext(), defaultProvider);
}

async function loadLLMConfig() {
  await aiSettingsPage.loadLLMConfig(aiSettingsContext());
}

function buildLLMConfigPayload(options = {}) {
  return aiSettingsPage.buildLLMConfigPayload(aiSettingsContext(), options);
}

async function saveLLMConfig() {
  await aiSettingsPage.saveLLMConfig(aiSettingsContext());
}

async function testLLMConnection() {
  await aiSettingsPage.testLLMConnection(aiSettingsContext());
}

function buildConversationListUrl() {
  return assistantApi.conversationListUrl({ keyword: currentConversationKeyword, page: 1, pageSize: 30 });
}

function applyConversationFilter() {
  currentConversationKeyword = textValue("conv-search");
  loadConversations();
}

function clearConversationFilter() {
  currentConversationKeyword = "";
  byId("conv-search").value = "";
  loadConversations();
}

async function loadConversations(options = {}) {
  const silent = Boolean(options.silent);
  const requestId = ++conversationListRequestId;
  const viewRevision = conversationViewRevision;
  if (!silent) setSendStatus(t("status_loading_conversations"));
  try {
    const resp = await assistantApi.listConversations({ keyword: currentConversationKeyword, page: 1, pageSize: 30 });
    const data = await resp.json();
    if (requestId !== conversationListRequestId) return;
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("status_load_failed"));
    }
    const items = data.items || [];
    renderConversations(items);
    if (conversationAutoSelect && conversationViewRevision === viewRevision && !currentConversationId && items.length > 0) {
      await openConversation(items[0].conversation_id, true);
    }
    if (!silent && requestId === conversationListRequestId) setSendStatus("");
  } catch (err) {
    if (!silent && requestId === conversationListRequestId) setSendStatus(`${t("status_load_failed")}: ${err.message}`);
  }
}

async function openConversation(conversationId, skipListReload = false) {
  if (!conversationId) return;
  const requestId = ++conversationLoadRequestId;
  conversationAutoSelect = false;
  if (currentConversationId !== conversationId) {
    conversationViewRevision += 1;
    byId("conv-title").textContent = t("status_loading_conversations");
    byId("conv-meta").textContent = `ID: ${conversationId}`;
    renderMessages([]);
  }
  currentConversationId = conversationId;
  if (window.ElectrochemDesktop) window.ElectrochemDesktop.changed();
  renderConversations(conversationItems);
  try {
    const resp = await assistantApi.getConversation(conversationId);
    const data = await resp.json();
    if (requestId !== conversationLoadRequestId || currentConversationId !== conversationId) return;
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("status_load_failed"));
    }
    const conv = data.conversation || {};
    byId("conv-title").textContent = conv.title || conv.project_name || t("conv_rename_default");
    byId("conv-meta").textContent = `ID: ${conv.conversation_id || "-"} | ${conv.provider || "-"}`;
    renderMessages(conv.messages || []);

    if (!skipListReload) {
      await loadConversations({ silent: true });
    }
    return true;
  } catch (err) {
    if (requestId === conversationLoadRequestId && currentConversationId === conversationId) {
      setSendStatus(`${t("status_load_failed")}: ${err.message}`);
    }
    return false;
  }
}

async function waitForAgentJob(jobId, sendBtn, options = {}) {
  activeAgentJobId = jobId;
  const cancellable = options.cancellable !== false;
  if (sendBtn) {
    sendBtn.disabled = !cancellable;
    sendBtn.dataset.agentCancellable = cancellable ? "true" : "false";
    sendBtn.textContent = t(cancellable ? "btn_cancel_ai" : "btn_confirmed_action_running");
  }
  while (activeAgentJobId === jobId) {
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    if (activeAgentJobId !== jobId) break;
    const jobResp = await assistantApi.getMessageJob(jobId);
    const jobData = await jobResp.json();
    if (activeAgentJobId !== jobId) break;
    if (!jobResp.ok || jobData.status !== "success") {
      throw new Error(jobData.message || t("status_send_failed"));
    }
    const job = jobData.job || {};
    if (["queued", "running"].includes(job.status)) {
      const progressText = job.current_item ? `: ${job.current_item}` : "";
      setSendStatus(`${t("status_waiting_reply")}${progressText}`);
      continue;
    }
    activeAgentJobId = null;
    if (job.status === "cancelled") throw new Error(t("status_ai_cancelled"));
    if (job.status !== "succeeded") throw new Error(job.error || t("status_send_failed"));
    return job.result || {};
  }
  throw new Error(t("status_ai_cancelled"));
}

async function sendMessage() {
  if (window.ElectrochemDesktop && window.ElectrochemDesktop.isLocked()) return;
  const msgEl = byId("msg-input");
  const sendBtn = byId("send-btn");
  const provider = textValue("llm-provider");
  const model = textValue("llm-model");

  if (activeAgentJobId) {
    const cancellingJobId = activeAgentJobId;
    if (sendBtn && sendBtn.dataset.agentCancellable === "false") {
      setSendStatus(t("status_confirmed_action_not_cancellable"));
      return;
    }
    try {
      const cancelResponse = await assistantApi.cancelMessageJob(cancellingJobId);
      const cancelData = await cancelResponse.json();
      if (activeAgentJobId !== cancellingJobId) return;
      if (!cancelResponse.ok || cancelData.status !== "success") {
        throw new Error(cancelData.message || t("status_send_failed"));
      }
      setSendStatus(t("status_ai_cancelling"));
    } catch (err) {
      if (activeAgentJobId === cancellingJobId) setSendStatus(`${t("status_send_failed")}: ${err.message}`);
    }
    return;
  }
  if (activeAgentRequest || (sendBtn && sendBtn.disabled)) return;

  const approvalDecision = pendingAssistantApprovalDecision;
  const message = (msgEl.value || "").trim();
  const promptPrefix = getActivePromptPrefix();
  refreshAssistantContextPreview();

  if (!message && !approvalDecision) {
    setSendStatus(t("status_send_empty"));
    return;
  }

  const request = {
    conversationId: currentConversationId,
    viewRevision: conversationViewRevision,
  };
  activeAgentRequest = request;
  conversationAutoSelect = false;
  appendLocalMessage("user", message);
  showTypingIndicator();
  setSendStatus(t("status_waiting_reply"));
  if (sendBtn) sendBtn.disabled = true;
  msgEl.value = "";

  try {
    const professionalContext = await buildAssistantActionContext();
    const submitResp = await assistantApi.submitMessageJob({
      message,
      prompt_prefix: promptPrefix || undefined,
      professional_context: professionalContext || undefined,
      approval_id: approvalDecision ? approvalDecision.approvalId : undefined,
      approval_action: approvalDecision ? approvalDecision.action : undefined,
      conversation_id: request.conversationId,
      provider: provider || undefined,
      model: model || undefined,
    });
    const submitData = await submitResp.json();
    if (!submitResp.ok || submitData.status !== "success" || !submitData.job_id) {
      throw new Error(submitData.message || t("status_send_failed"));
    }
    const data = await waitForAgentJob(submitData.job_id, sendBtn, {
      cancellable: !(approvalDecision && approvalDecision.action === "approve"),
    });
    if (data.status !== "success") {
      throw new Error(data.message || t("status_send_failed"));
    }

    const conv = data.conversation || null;
    if (isAgentRequestVisible(request)) {
      const resultConversationId = data.conversation_id || request.conversationId;
      if (currentConversationId !== resultConversationId) conversationViewRevision += 1;
      currentConversationId = resultConversationId;
      conversationLoadRequestId += 1;
      if (conv) {
        byId("conv-title").textContent = conv.title || conv.project_name || t("conv_rename_default");
        byId("conv-meta").textContent = `ID: ${conv.conversation_id || "-"} | ${conv.provider || "-"}`;
        renderMessages(conv.messages || []);
      } else if (Array.isArray(data.messages)) {
        renderMessages(data.messages);
      } else if (currentConversationId) {
        await openConversation(currentConversationId, true);
      } else {
        removeTypingIndicator();
      }
    }

    setSendStatus(t("status_send_success"));
    await loadConversations();
  } catch (err) {
    removeTypingIndicator();
    try {
      if (isAgentRequestVisible(request)) {
        if (request.conversationId) await openConversation(request.conversationId, true);
        else renderMessages([]);
      }
    } catch (_syncError) {
      // Preserve the original send/cancel error below if the resync also fails.
    }
    if (approvalDecision) {
      document.querySelectorAll(`.assistant-approval-btn[data-approval-id="${approvalDecision.approvalId}"]`).forEach((button) => {
        button.disabled = false;
      });
    }
    setSendStatus(`${t("status_send_failed")}: ${err.message}`);
  } finally {
    if (pendingAssistantApprovalDecision === approvalDecision) pendingAssistantApprovalDecision = null;
    if (activeAgentRequest === request) {
      activeAgentRequest = null;
      activeAgentJobId = null;
      if (sendBtn) {
        sendBtn.disabled = false;
        delete sendBtn.dataset.agentCancellable;
        sendBtn.textContent = t("btn_send");
      }
    }
  }
}

function handleAssistantApprovalClick(event) {
  const button = event.target.closest(".assistant-approval-btn");
  if (!button || activeAgentRequest || activeAgentJobId) return;
  const approvalId = String(button.dataset.approvalId || "").trim();
  const action = String(button.dataset.approvalAction || "").trim();
  const summary = String(button.dataset.approvalSummary || t("assistant_approval_unknown")).trim();
  if (!approvalId || !["approve", "decline"].includes(action)) return;
  document.querySelectorAll(`.assistant-approval-btn[data-approval-id="${approvalId}"]`).forEach((item) => {
    item.disabled = true;
  });
  pendingAssistantApprovalDecision = { approvalId, action };
  const key = action === "approve" ? "assistant_approval_approve_message" : "assistant_approval_decline_message";
  byId("msg-input").value = t(key).replace("{summary}", summary);
  sendMessage();
}

function historyRecordKey(record) {
  return processResultPage.historyRecordKey(record);
}

function buildResultFromHistoryRecord(record) {
  return processResultPage.buildResultFromHistoryRecord(processResultContext(), record);
}

async function viewHistoryRecord(index) {
  const i = Number(index);
  if (!Number.isInteger(i) || i < 0 || i >= historyRecords.length) return;
  let record = historyRecords[i];
  selectedHistoryKey = historyRecordKey(record);
  processResultPage.setActiveHistoryItem(processResultContext(), selectedHistoryKey);
  if (record.data === undefined && projectApi && typeof projectApi.historyDetail === "function") {
    try {
      const resp = await projectApi.historyDetail(selectedHistoryKey);
      const payload = await resp.json();
      if (!resp.ok || payload.status !== "success" || !payload.record) {
        throw new Error(payload.message || t("status_load_failed"));
      }
      record = payload.record;
      historyRecords[i] = record;
    } catch (err) {
      setProcStatus(`${t("status_load_failed")}: ${err.message}`);
      return;
    }
  }
  if (selectedHistoryKey !== historyRecordKey(record)) return;
  renderProcessResult(buildResultFromHistoryRecord(record));
  setProcStatus(t("status_history_loaded"));
}

function renderHistory(records) {
  const view = processResultPage.renderHistory(
    {
      ...processResultContext(),
      onSelect: viewHistoryRecord,
      selectedKey: selectedHistoryKey,
    },
    records,
  );
  historyRecords = view.records;
}

function renderHistoryPagination() {
  const status = byId("history-page-status");
  const button = byId("history-load-more");
  if (status) {
    status.textContent = t("history_page_status")
      .replace("{loaded}", String(historyRecords.length))
      .replace("{total}", String(historyTotal));
  }
  if (button) button.hidden = !historyHasMore;
}

function renderProjectHistoryPagination(state) {
  const detail = state && typeof state === "object" ? state : {};
  const records = Array.isArray(detail.history) ? detail.history : [];
  const status = byId("project-history-page-status");
  const button = byId("project-history-load-more");
  if (status) {
    status.textContent = t("history_page_status")
      .replace("{loaded}", String(records.length))
      .replace("{total}", String(Number(detail.historyTotal || 0)));
  }
  if (button) {
    button.hidden = !detail.historyHasMore;
    button.disabled = Boolean(detail.historyLoadingMore);
  }
}

function renderStats(data) {
  projectPage.renderStats({ byId, data, prefix: "stat" });
}

function renderProjectStats(data) {
  projectPage.renderStats({ byId, data, prefix: "project-stat" });
}

function setProjectEditForm(project) {
  projectPage.setProjectEditForm({ byId, project });
  if (projectPreferences) projectPreferences.setEditForm(projectPreferencesContext(), project);
}

function getSelectedProjectHistoryRecord() {
  return projectHistoryWorkspace.getSelectedProjectHistoryRecord(projectHistoryContext());
}

function renderProjectHistoryDetail(record) {
  projectHistoryWorkspace.renderProjectHistoryDetail(projectHistoryContext(), record);
}

function selectProjectHistory(index) {
  projectHistoryWorkspace.selectProjectHistory(projectHistoryContext(), index);
}

function renderProjectHistory(records) {
  projectHistoryWorkspace.renderProjectHistory(projectHistoryContext(), records);
}

function renderProjectLSVSummary(summary) {
  projectPage.renderProjectLSVSummary({
    escapeHtml,
    formatMetric,
    summary,
    t,
    wrap: byId("project-lsv-table"),
  });
}

function getProjectCompareViewState() {
  return {
    chartType: projectCompareChartType,
    metric: projectCompareMetric,
    onlyEta: projectCompareOnlyEta,
    onlyTafel: projectCompareOnlyTafel,
    plotData: projectComparePlotData,
    plotLoading: projectComparePlotLoading,
    selectedSamples: projectCompareSelectedSamples,
    sort: projectCompareSort,
    targetCurrent: projectCompareTargetCurrent,
    targetCurrents: projectCompareTargetCurrents,
  };
}

function applyProjectCompareViewState(view) {
  const safe = view && typeof view === "object" ? view : {};
  if (Array.isArray(safe.selectedSamples)) projectCompareSelectedSamples = safe.selectedSamples;
  if (Object.prototype.hasOwnProperty.call(safe, "plotData")) projectComparePlotData = safe.plotData;
  if (Object.prototype.hasOwnProperty.call(safe, "plotLoading")) projectComparePlotLoading = Boolean(safe.plotLoading);
  if (Object.prototype.hasOwnProperty.call(safe, "targetCurrent")) projectCompareTargetCurrent = String(safe.targetCurrent || "");
}

function getFilteredProjectCompareSamples(summary) {
  return projectComparePage.filterSamples({
    model: projectCompareModel,
    state: getProjectCompareViewState(),
    summary,
  });
}

function syncProjectCompareSelection(summary) {
  const view = projectComparePage.syncSelection({
    model: projectCompareModel,
    state: getProjectCompareViewState(),
    summary,
  });
  applyProjectCompareViewState(view);
  return view.samples || [];
}

function renderProjectCompareSelectionCount() {
  projectComparePage.renderSelectionCount({
    byId,
    selectedSamples: projectCompareSelectedSamples,
    t,
  });
}

function projectCompareNeedsTargetCurrent() {
  return projectComparePage.needsTargetCurrent({
    model: projectCompareModel,
    state: getProjectCompareViewState(),
  });
}

function getProjectCompareAvailableTargetCurrents(metric = projectCompareMetric) {
  return projectComparePage.availableTargetCurrents({
    model: projectCompareModel,
    state: {
      ...getProjectCompareViewState(),
      metric,
    },
  });
}

function syncProjectCompareControls() {
  const view = projectComparePage.syncControls({
    byId,
    escapeHtml,
    model: projectCompareModel,
    state: getProjectCompareViewState(),
    t,
  });
  applyProjectCompareViewState(view);
}

function renderProjectCompareSummary(summary) {
  projectComparePage.renderSummary({
    byId,
    escapeHtml,
    formatMetric,
    model: projectCompareModel,
    state: getProjectCompareViewState(),
    summary,
    t,
  });
}

function renderProjectCompareTable(summary) {
  projectComparePage.renderTable({
    byId,
    escapeHtml,
    formatMetric,
    model: projectCompareModel,
    onSelectionChange: (view) => {
      applyProjectCompareViewState(view);
      projectComparePlotData = null;
      renderProjectCompareSelectionCount();
      renderProjectComparePlot();
    },
    state: getProjectCompareViewState(),
    summary,
    t,
  });
}

function renderProjectComparePlot() {
  const view = projectComparePage.renderPlot({
    bindFileActions: bindProjectFileActions,
    byId,
    escapeHtml,
    model: projectCompareModel,
    state: getProjectCompareViewState(),
    t,
  });
  applyProjectCompareViewState(view);
}

async function generateProjectComparePlot() {
  if (!selectedProjectId) return;
  if (!projectCompareSelectedSamples.length) {
    setProjectStatus(t("project_compare_plot_empty"));
    renderProjectComparePlot();
    return;
  }
  if (projectCompareNeedsTargetCurrent()) {
    const availableTargets = getProjectCompareAvailableTargetCurrents(projectCompareMetric);
    if (!availableTargets.length || !projectCompareTargetCurrent) {
      setProjectStatus(t("project_compare_target_current_missing"));
      renderProjectComparePlot();
      return;
    }
  }
  projectComparePlotLoading = true;
  projectComparePlotData = null;
  renderProjectComparePlot();
  setProjectStatus(t("project_compare_plot_loading"));
  try {
    const resp = await projectApi.lsvComparePlot(selectedProjectId, {
      includeArchived: projectIncludeArchived,
      chartType: projectCompareChartType,
      metric: projectCompareMetric,
      targetCurrent: projectCompareNeedsTargetCurrent() ? projectCompareTargetCurrent : undefined,
      samples: projectCompareSelectedSamples,
    });
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("project_compare_plot_failed"));
    }
    projectComparePlotData = data.plot || null;
    if (projectComparePlotData && Array.isArray(projectComparePlotData.selected_samples) && projectComparePlotData.selected_samples.length) {
      projectCompareSelectedSamples = projectComparePlotData.selected_samples.map((item) => String(item || "")).filter(Boolean);
      renderProjectCompareSelectionCount();
    }
    if (projectComparePlotData && projectComparePlotData.target_current !== undefined && projectComparePlotData.target_current !== null) {
      projectCompareTargetCurrent = String(projectComparePlotData.target_current);
      syncProjectCompareControls();
    }
    setProjectStatus("");
  } catch (err) {
    projectComparePlotData = null;
    setProjectStatus(`${t("project_compare_plot_failed")}: ${err.message}`);
  } finally {
    projectComparePlotLoading = false;
    renderProjectComparePlot();
  }
}

async function loadLatestProjectComparePlot(silent = true, isCurrent = () => true) {
  if (!selectedProjectId) return;
  try {
    const resp = await projectApi.latestLsvComparePlot(selectedProjectId, {
      chartType: projectCompareChartType,
      metric: projectCompareMetric,
      targetCurrent: projectCompareNeedsTargetCurrent() && projectCompareTargetCurrent ? projectCompareTargetCurrent : undefined,
    });
    const data = await resp.json().catch(() => ({}));
    if (!isCurrent()) return;
    if (!resp.ok || data.status !== "success") {
      projectComparePlotData = null;
      renderProjectComparePlot();
      return;
    }
    projectComparePlotData = data.plot || null;
    if (projectComparePlotData && Array.isArray(projectComparePlotData.selected_samples) && projectComparePlotData.selected_samples.length) {
      projectCompareSelectedSamples = projectComparePlotData.selected_samples.map((item) => String(item || "")).filter(Boolean);
    }
    if (projectComparePlotData && projectComparePlotData.target_current !== undefined && projectComparePlotData.target_current !== null) {
      projectCompareTargetCurrent = String(projectComparePlotData.target_current);
      syncProjectCompareControls();
    }
    renderProjectCompareSelectionCount();
    renderProjectComparePlot();
  } catch (err) {
    if (!isCurrent()) return;
    projectComparePlotData = null;
    renderProjectComparePlot();
    if (!silent) {
      setProjectStatus(`${t("project_compare_plot_failed")}: ${err.message}`);
    }
  }
}

async function loadProjectCompareTargetCurrents(projectId, isCurrent = () => true) {
  const targetProjectId = String(projectId || "").trim();
  if (!targetProjectId) {
    projectCompareTargetCurrents = {
      target_currents: [],
      potential_target_currents: [],
      overpotential_target_currents: [],
    };
    syncProjectCompareControls();
    return;
  }
  try {
    const resp = await projectApi.lsvTargetCurrents(targetProjectId, { includeArchived: projectIncludeArchived });
    const data = await resp.json().catch(() => ({}));
    if (!isCurrent()) return;
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || "failed to load target currents");
    }
    projectCompareTargetCurrents = {
      target_currents: Array.isArray(data.target_currents) ? data.target_currents : [],
      potential_target_currents: Array.isArray(data.potential_target_currents) ? data.potential_target_currents : [],
      overpotential_target_currents: Array.isArray(data.overpotential_target_currents) ? data.overpotential_target_currents : [],
    };
  } catch (_err) {
    if (!isCurrent()) return;
    projectCompareTargetCurrents = {
      target_currents: [],
      potential_target_currents: [],
      overpotential_target_currents: [],
    };
  }
  syncProjectCompareControls();
}

function collectProjectOutputFiles(history) {
  return projectPage.collectProjectOutputFiles(history, historyRecordKey);
}

async function copyTextToClipboard(text) {
  const value = String(text || "").trim();
  if (!value) return false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch (_err) {}
  try {
    const el = document.createElement("textarea");
    el.value = value;
    el.setAttribute("readonly", "readonly");
    el.style.position = "fixed";
    el.style.opacity = "0";
    document.body.appendChild(el);
    el.select();
    document.execCommand("copy");
    el.remove();
    return true;
  } catch (_err) {
    return false;
  }
}

async function requestOpenPath(pathValue, revealOnly = false) {
  const target = String(pathValue || "").trim();
  if (!target) return;
  try {
    const resp = await systemApi.openPath(target, revealOnly);
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("project_open_dir_failed"));
    }
    setFileActionStatus(t("project_open_dir_done"));
  } catch (err) {
    setFileActionStatus(`${t("project_open_dir_failed")}: ${err.message}`);
  }
}

function bindProjectFileActions(root) {
  if (!root) return;
  root.querySelectorAll("[data-copy-path]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const ok = await copyTextToClipboard(btn.getAttribute("data-copy-path") || "");
      setFileActionStatus(ok ? t("project_copy_done") : t("project_copy_failed"));
    });
  });
  root.querySelectorAll("[data-open-path]").forEach((btn) => {
    btn.addEventListener("click", () => {
      requestOpenPath(btn.getAttribute("data-open-path") || "", false);
    });
  });
  root.querySelectorAll("[data-open-dir]").forEach((btn) => {
    btn.addEventListener("click", () => {
      requestOpenPath(btn.getAttribute("data-open-dir") || "", true);
    });
  });
}

function renderProjectOutputFiles(history) {
  projectPage.renderProjectOutputFiles({
    bindFileActions: bindProjectFileActions,
    escapeHtml,
    history,
    historyRecordKey,
    outputTypeFilter: projectOutputTypeFilter,
    t,
    wrap: byId("project-output-files"),
  });
}

function resetProjectCompareState() {
  projectCompareSelectedSamples = [];
  projectComparePlotData = null;
  projectComparePlotLoading = false;
  projectCompareTargetCurrents = projectWorkspace.emptyTargetCurrents();
}

function projectPreferencesContext() {
  return {
    byId, t, escapeHtml, processingApi, setProjectStatus,
    getTemplateItems: () => templateItems,
    setTemplateItems: (items) => { templateContext().setTemplateItems(items); renderTemplateOptions(); },
    getCurrentState: getCurrentTemplateState,
    isProcessing: () => Boolean(activeProcessJobId || (byId("proc-run") && byId("proc-run").disabled)),
    applyTemplate: (template) => {
      byId("tmpl-select").value = template.name;
      processTemplates.applyState(templateContext(), template.state || {});
      byId("tmpl-name").value = template.name;
      const warnings = processTemplates.getLastApplyWarnings();
      setTemplateStatus(t(warnings.length ? "template_loaded_with_warnings" : "template_loaded"));
    },
    enterProject: (project) => {
      byId("proc-project").value = project.name;
      switchTab("pro");
      setProjectStatus(t("project_status_applied"));
    },
  };
}

function getProjectHistoryFilters() {
  return { q: textValue("project-results-search"), type: textValue("project-results-type"), dateFrom: textValue("project-results-date-from"), dateTo: textValue("project-results-date-to") };
}

function projectHistoryFilterKey() {
  return JSON.stringify([selectedProjectId, projectIncludeArchived, getProjectHistoryFilters()]);
}

function resetProjectHistoryFilters() {
  clearTimeout(projectFilterTimer);
  ["project-results-search", "project-results-type", "project-results-date-from", "project-results-date-to"].forEach((id) => { const el = byId(id); if (el) el.value = ""; });
  const status = byId("project-results-filter-status");
  if (status) status.textContent = "";
}

function applyProjectHistoryFilters(debounce = false) {
  clearTimeout(projectFilterTimer);
  projectWorkspace.invalidateDetail();
  selectedProjectHistoryKey = "";
  if (projectWorkbench) projectWorkbench.clearSelection(projectWorkbenchContext());
  const filters = getProjectHistoryFilters();
  const invalid = filters.dateFrom && filters.dateTo && filters.dateFrom > filters.dateTo;
  const status = byId("project-results-filter-status");
  status.textContent = invalid ? t("project_filter_date_invalid") : Object.values(filters).some(Boolean) ? t("project_filters_scope") : "";
  if (projectDetailState) projectDetailState = { ...projectDetailState, history: [], historyHasMore: false, historyNextCursor: "", historyTotal: 0, historyLoading: !invalid };
  renderSelectedProjectDetail();
  if (invalid || !selectedProjectId) return;
  if (debounce) projectFilterTimer = setTimeout(loadSelectedProjectDetail, 300);
  else loadSelectedProjectDetail();
}

function projectWorkspaceContext() {
  return {
    byId,
    confirm: (message) => window.confirm(message),
    getProjectIncludeArchived: () => projectIncludeArchived,
    getProjectListStatus: () => projectListStatus,
    getHistoryFilters: getProjectHistoryFilters,
    resetHistoryFilters: resetProjectHistoryFilters,
    getProjectItems: () => projectItems,
    getSelectedProjectId: () => selectedProjectId,
    loadLatestProjectComparePlot,
    loadProjectCompareTargetCurrents,
    projectApi,
    renderProjectList,
    renderSelectedProjectDetail,
    resetProjectCompareState,
    setProjectComparePlotData: (value) => {
      projectComparePlotData = value || null;
    },
    setProjectComparePlotLoading: (value) => {
      projectComparePlotLoading = Boolean(value);
    },
    setProjectCompareTargetCurrents: (value) => {
      projectCompareTargetCurrents = value && typeof value === "object" ? value : projectWorkspace.emptyTargetCurrents();
    },
    setProjectDetailState: (value) => {
      projectDetailState = value;
    },
    setProjectItems: (items) => {
      projectItems = Array.isArray(items) ? items : [];
      if (projectListStatus === "active") activeProjectItems = projectItems.slice();
    },
    setProjectListStatus: (value) => {
      projectListStatus = value === "archived" ? "archived" : "active";
      const toggle = byId("project-show-recycle");
      if (toggle) toggle.checked = projectListStatus === "archived";
    },
    setProjectStatus,
    setSelectedProjectHistoryKey: (value) => {
      selectedProjectHistoryKey = String(value || "");
    },
    setSelectedProjectId: (value) => {
      projectNavigationRevision += 1;
      selectedProjectId = String(value || "");
      if (window.ElectrochemDesktop) window.ElectrochemDesktop.changed();
    },
    syncProcessProjectOptions,
    switchTab,
    onProjectSaved: () => {
      const dialog = byId("project-settings-dialog");
      if (dialog && dialog.open) dialog.close();
    },
    t,
    textValue,
  };
}

function projectHistoryContext() {
  return {
    autoSelectHistory: !projectWorkbench,
    getComparedRecordKeys: () => projectWorkbench ? projectWorkbench.selectedKeys() : [],
    onToggleRecord: (key, selected) => projectWorkbench && projectWorkbench.toggleRecord(projectWorkbenchContext(), key, selected),
    onHistoryRendered: () => projectWorkbench && projectWorkbench.refresh(projectWorkbenchContext()),
    buildResultFromHistoryRecord,
    byId,
    confirm: (message) => window.confirm(message),
    escapeHtml,
    getProjectDetailState: () => projectDetailState,
    getSelectedProjectHistoryKey: () => selectedProjectHistoryKey,
    historyRecordKey,
    loadSelectedProjectDetail,
    loadStatsAndHistory,
    projectApi,
    projectPage,
    renderProcessResult,
    setProcStatus,
    setProjectStatus,
    setSelectedProjectHistoryKey: (value) => {
      selectedProjectHistoryKey = String(value || "");
    },
    switchTab,
    t: (key) => key === "project_no_history" && projectDetailState && projectDetailState.historyLoading ? t("project_loading") : key === "project_no_history" && Object.values(getProjectHistoryFilters()).some(Boolean) ? t("project_results_no_matches") : t(key),
  };
}

function projectWorkbenchContext() {
  return {
    byId, escapeHtml, t, projectApi, processingApi, historyRecordKey,
    recoveryApi: { list: projectApi.recoveryList, plan: projectApi.recoveryPlan, resume: projectApi.recoveryResume },
    onRecoveryCompleted: async (job) => {
      await loadStatsAndHistory();
      await loadProjects(selectedProjectId || (job.result && job.result.project_id) || "");
    },
    bindFileActions: bindProjectFileActions,
    getProjectDetailState: () => projectDetailState,
    getSelectedProjectId: () => selectedProjectId,
    getSelectedHistoryKey: () => selectedProjectHistoryKey,
    setSelectedHistoryKey: (key) => { selectedProjectHistoryKey = String(key || ""); },
    getProject: () => projectItems.find((item) => item.id === selectedProjectId),
    getIncludeArchived: () => projectIncludeArchived,
    hasHistoryFilters: () => Object.values(getProjectHistoryFilters()).some(Boolean),
    setProjectEditForm,
    renderHistory: () => renderProjectHistory(projectDetailState && projectDetailState.history || []),
    renderProjectList: () => renderProjectList(projectItems),
    loadSelectedProjectDetail,
    loadStatsAndHistory,
  };
}

function projectReplicatesContext() {
  return { byId, t, escapeHtml, apiFetch: (...args) => window.ElectrochemApi.fetch(...args),
    getSelectedProjectId: () => selectedProjectId,
    getSelectedRecordKeys: () => projectWorkbench ? projectWorkbench.selectedKeys() : [],
  };
}

async function prepareActionProject(card) {
  const started = projectNavigationRevision;
  const keys = [...new Set(card.record_keys || [])];
  const requests = [projectApi.listProjects({ status: "all" }), ...keys.map((key) => projectApi.historyDetail(key))];
  const responses = await Promise.all(requests);
  const data = await Promise.all(responses.map((response) => projectWorkbench.readResponse(response)));
  if (started !== projectNavigationRevision) throw new Error(t("assistant_action_navigation_changed"));
  const project = (data[0].projects || []).find((item) => item.id === card.project_id);
  if (!project) throw new Error(t("task_target_missing"));
  const records = data.slice(1).map((item) => item.record);
  if (records.some((record) => !record || record.project_id !== project.id)) throw new Error(t("assistant_action_project_mismatch"));
  projectListStatus = project.status === "archived" ? "archived" : "active";
  byId("project-show-recycle").checked = projectListStatus === "archived";
  projectItems = data[0].projects.filter((item) => item.status === projectListStatus);
  activeProjectItems = data[0].projects.filter((item) => item.status !== "archived");
  resetProjectHistoryFilters();
  projectIncludeArchived = records.some((record) => record.archived);
  byId("project-include-archived").checked = projectIncludeArchived;
  switchTab("project");
  const navigation = selectProject(project.id);
  const owned = projectNavigationRevision;
  await navigation;
  if (owned !== projectNavigationRevision || selectedProjectId !== project.id) throw new Error(t("assistant_action_navigation_changed"));
  if (!projectDetailState) throw new Error(t("project_status_detail_failed"));
  const selected = new Set(keys);
  projectDetailState.history = [...records, ...(projectDetailState.history || []).filter((record) => !selected.has(historyRecordKey(record)))];
  projectWorkbench.clearSelection(projectWorkbenchContext());
  records.forEach((record) => projectWorkbench.toggleRecord(projectWorkbenchContext(), historyRecordKey(record), true));
  if (records.length) selectedProjectHistoryKey = historyRecordKey(records[0]);
  renderSelectedProjectDetail();
  return { records, isCurrent: () => owned === projectNavigationRevision && selectedProjectId === project.id };
}

async function applyAssistantParameters(card) {
  if (activeProcessJobId || byId("proc-run").disabled) throw new Error(t("assistant_action_busy"));
  const live = await buildAssistantActionContext();
  if (activeProcessJobId || byId("proc-run").disabled) throw new Error(t("assistant_action_busy"));
  if (!assistantActions.guardMatches(card, live)) throw new Error(t("assistant_action_stale"));
  const bindings = processSchemaClient.CONTROL_BINDINGS || {};
  const updates = (card.changes || []).map((change) => {
    const control = bindings[change.key] && byId(bindings[change.key]);
    if (!control || ["ir_eis_file", "coupled_products_file", "coupled_peak_method_file"].includes(change.key)) throw new Error(t("assistant_action_invalid"));
    return { control, value: change.after, previous: control.type === "checkbox" ? control.checked : control.value };
  });
  updates.forEach(({ control, value }) => { if (control.type === "checkbox") control.checked = Boolean(value); else control.value = value === null || value === undefined ? "" : String(value); });
  try { collectProcessPayload(); }
  catch (error) {
    updates.forEach(({ control, previous }) => { if (control.type === "checkbox") control.checked = previous; else control.value = previous; });
    throw error;
  }
  syncFeatureBlocks(); syncProcessModulePanels(); syncPotentialConversionUI(); syncAllMatchFieldMeta();
  markProcessChanged();
  appliedProcessTemplateName = "";
  switchTab("pro");
  setProcStatus(t("assistant_action_preflight"));
  refreshAssistantContextPreview();
}

async function openAssistantResults(card) {
  const state = await prepareActionProject(card);
  if (!state.isCurrent()) return;
  projectWorkbench.setView(projectWorkbenchContext(), "results");
  if (state.records.length) {
    selectedProjectHistoryKey = historyRecordKey(state.records[0]);
    renderProjectHistory(projectDetailState.history || []);
    byId("project-history-detail-panel").scrollIntoView({ block: "nearest" });
  }
}

function assistantActionsContext() {
  return {
    getContext: buildAssistantActionContext, applyParameters: applyAssistantParameters, t, escapeHtml,
    openComparison: async (card) => { const result = await prepareActionProject(card); if (result.isCurrent()) await projectWorkbench.compareSelected(projectWorkbenchContext()); },
    openReplay: async (card) => { const result = await prepareActionProject(card); if (result.isCurrent()) await projectReplay.open(projectWorkbenchContext(), card.record_keys.length ? "record" : "run", { run_id: card.run_id, record_key: card.record_keys[0] }, card.params); },
    openReport: async (card) => { const result = await prepareActionProject(card); if (!result.isCurrent()) return; byId("project-report-scope").value = "selected"; projectWorkbench.setView(projectWorkbenchContext(), "reports"); await projectWorkbench.loadReportRuns(projectWorkbenchContext()); },
    openResults: openAssistantResults,
  };
}

function taskCenterContext() {
  return { t, escapeHtml, apiFetch: (...args) => window.ElectrochemApi.fetch(...args),
    openRecovery: () => projectRecovery.open(projectWorkbenchContext()),
    openTask: async (task) => {
      const ref = task.reference || {};
      if (ref.conversation_id) { await openConversation(ref.conversation_id); openAssistantDrawer(); }
      else if (ref.project_id) await openAssistantResults(ref);
      else throw new Error(t("task_target_missing"));
    },
  };
}

function renderSelectedProjectDetail() {
  const project = projectItems.find((it) => it.id === selectedProjectId);
  const hasProject = projectPage.renderProjectHeader({ byId, project, t });
  const archivedProject = Boolean(project && project.status === "archived");
  const archiveButton = byId("project-delete-btn");
  const restoreButton = byId("project-restore-btn");
  const permanentButton = byId("project-delete-permanent-btn");
  if (archiveButton) archiveButton.hidden = archivedProject;
  if (restoreButton) restoreButton.hidden = !archivedProject;
  if (permanentButton) permanentButton.hidden = !archivedProject;
  if (projectWorkbench) projectWorkbench.refresh(projectWorkbenchContext());
  if (byId("project-replicates-open")) byId("project-replicates-open").disabled = !hasProject;

  if (!hasProject) {
    selectedProjectHistoryKey = "";
    projectCompareSelectedSamples = [];
    projectComparePlotData = null;
    projectComparePlotLoading = false;
    projectCompareTargetCurrents = {
      target_currents: [],
      potential_target_currents: [],
      overpotential_target_currents: [],
    };
    setProjectEditForm(null);
    renderProjectStats({});
    renderProjectHistory([]);
    renderProjectHistoryPagination(null);
    renderProjectLSVSummary(null);
    renderProjectCompareSummary(null);
    renderProjectCompareTable(null);
    renderProjectCompareSelectionCount();
    renderProjectComparePlot();
    renderProjectOutputFiles([]);
    return;
  }

  const state = projectDetailState && typeof projectDetailState === "object" ? projectDetailState : {};
  syncProjectCompareSelection(state.lsv || null);
  renderProjectStats(state.stats || {});
  renderProjectHistory(state.history || []);
  renderProjectHistoryPagination(state);
  renderProjectLSVSummary(state.lsv || null);
  renderProjectCompareSummary(state.lsv || null);
  renderProjectCompareTable(state.lsv || null);
  renderProjectComparePlot();
  renderProjectOutputFiles(state.history || []);
}

function renderProjectList(items) {
  const keyword = textValue("project-list-search").toLowerCase();
  const visibleItems = (Array.isArray(items) ? items : projectItems).filter((item) => !keyword || `${item.name || ""} ${(item.tags || []).join(" ")}`.toLowerCase().includes(keyword));
  projectPage.renderProjectList({
    escapeHtml,
    items: visibleItems,
    listEl: byId("project-list"),
    onSelect: selectProject,
    selectedProjectId,
    t,
  });
}

async function loadSelectedProjectDetail() {
  await projectWorkspace.loadSelectedProjectDetail(projectWorkspaceContext());
}

async function loadMoreProjectHistory() {
  const state = projectDetailState && typeof projectDetailState === "object" ? projectDetailState : null;
  if (!selectedProjectId || !state || !state.historyHasMore || !state.historyNextCursor) return;
  if (state.historyLoadingMore) return;
  state.historyLoadingMore = true;
  const filterKey = projectHistoryFilterKey();
  const button = byId("project-history-load-more");
  if (button) button.disabled = true;
  try {
    const resp = await projectApi.history({
      projectId: selectedProjectId,
      limit: 30,
      cursor: state.historyNextCursor,
      includeArchived: projectIncludeArchived,
      ...getProjectHistoryFilters(),
    });
    const payload = await resp.json();
    if (projectDetailState !== state || filterKey !== projectHistoryFilterKey()) return;
    if (!resp.ok || payload.status !== "success") throw new Error(payload.message || t("status_load_failed"));
    const existing = new Set((state.history || []).map((record) => historyRecordKey(record)));
    (payload.records || []).forEach((record) => {
      if (!existing.has(historyRecordKey(record))) state.history.push(record);
    });
    state.historyNextCursor = payload.next_cursor || "";
    state.historyHasMore = Boolean(payload.has_more);
    state.historyTotal = Number(payload.total || state.history.length);
    renderSelectedProjectDetail();
  } catch (err) {
    if (projectDetailState === state && filterKey === projectHistoryFilterKey()) setProjectStatus(`${t("status_load_failed")}: ${err.message}`);
  } finally {
    state.historyLoadingMore = false;
    if (button && projectDetailState === state) button.disabled = false;
  }
}

async function selectProject(projectId) {
  await projectWorkspace.selectProject(projectWorkspaceContext(), projectId);
}

async function loadProjects(preferredProjectId = "") {
  await projectWorkspace.loadProjects(projectWorkspaceContext(), preferredProjectId);
}

function formatStorageBytes(value) {
  const bytes = Math.max(0, Number(value || 0));
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GiB`;
}

async function loadStorageSummary() {
  const summaryEl = byId("storage-summary");
  if (!summaryEl) return;
  summaryEl.textContent = t("storage_loading");
  try {
    const response = await projectApi.storageSummary();
    const data = await response.json();
    if (!response.ok || data.status !== "success") throw new Error(data.message || t("status_load_failed"));
    summaryEl.textContent = t("storage_summary")
      .replace("{referenced_runs}", String(data.referenced_runs || 0))
      .replace("{referenced_bytes}", formatStorageBytes(data.referenced_bytes))
      .replace("{orphaned_runs}", String(data.orphaned_runs || 0))
      .replace("{orphaned_bytes}", formatStorageBytes(data.orphaned_bytes));
    const cleanup = byId("storage-cleanup-btn");
    if (cleanup) cleanup.disabled = !Number(data.orphaned_runs || 0);
  } catch (err) {
    summaryEl.textContent = `${t("status_load_failed")}: ${err.message}`;
  }
}

async function cleanupManagedStorage() {
  if (!window.confirm(t("storage_cleanup_confirm"))) return;
  const cleanupButton = byId("storage-cleanup-btn");
  if (cleanupButton) cleanupButton.disabled = true;
  try {
    const response = await projectApi.cleanupStorage();
    const data = await response.json();
    if (!response.ok || data.status !== "success") {
      throw new Error(data.message || t("status_load_failed"));
    }
    setProjectStatus(
      t("storage_cleanup_done")
        .replace("{count}", String((data.removed || []).length))
        .replace("{bytes}", formatStorageBytes(data.bytes_reclaimed)),
    );
    await loadStorageSummary();
  } catch (err) {
    setProjectStatus(`${t("status_load_failed")}: ${err.message}`);
    if (cleanupButton) cleanupButton.disabled = false;
  }
}

async function createProject() {
  await projectWorkspace.createProject(projectWorkspaceContext());
}

async function deleteCurrentProject() {
  await projectWorkspace.deleteCurrentProject(projectWorkspaceContext());
}

async function restoreCurrentProject() {
  await projectWorkspace.restoreCurrentProject(projectWorkspaceContext());
}

async function permanentlyDeleteCurrentProject() {
  await projectWorkspace.permanentlyDeleteCurrentProject(projectWorkspaceContext());
}

function applyCurrentProjectToForms() {
  const project = projectItems.find((item) => item.id === selectedProjectId);
  if (projectPreferences) return projectPreferences.enterProject(projectPreferencesContext(), project);
  return projectWorkspace.applyCurrentProjectToForms(projectWorkspaceContext());
}

async function saveCurrentProject() {
  await projectWorkspace.saveCurrentProject(projectWorkspaceContext());
}

function openSelectedProjectHistoryResult() {
  projectHistoryWorkspace.openSelectedProjectHistoryResult(projectHistoryContext());
}

async function archiveSelectedProjectHistory() {
  await projectHistoryWorkspace.archiveSelectedProjectHistory(projectHistoryContext());
}

async function deleteSelectedProjectHistory() {
  await projectHistoryWorkspace.deleteSelectedProjectHistory(projectHistoryContext());
}

async function exportCurrentProjectReport() {
  if (projectWorkbench) return projectWorkbench.exportReport(projectWorkbenchContext());
  return projectWorkspace.exportCurrentProjectReport(projectWorkspaceContext());
}

async function loadStatsAndHistory(options = {}) {
  const append = Boolean(options && options.append === true);
  try {
    const cursor = append ? historyNextCursor : "";
    if (append && (!historyHasMore || !cursor)) return;
    const requests = [projectApi.history({ limit: 50, cursor })];
    if (!append) requests.unshift(projectApi.stats());
    const responses = await Promise.all(requests);
    const statsResp = append ? null : responses[0];
    const historyResp = append ? responses[0] : responses[1];
    const statsData = statsResp ? await statsResp.json() : null;
    const historyData = await historyResp.json();

    if (statsResp && statsResp.ok && statsData.status === "success") {
      renderStats(statsData.data || {});
    }
    if (historyResp.ok && historyData.status === "success") {
      const incoming = historyData.records || [];
      if (append) {
        const existing = new Set(historyRecords.map((record) => historyRecordKey(record)));
        renderHistory(historyRecords.concat(incoming.filter((record) => !existing.has(historyRecordKey(record)))));
      } else {
        renderHistory(incoming);
      }
      historyNextCursor = historyData.next_cursor || "";
      historyHasMore = Boolean(historyData.has_more);
      historyTotal = Number(historyData.total || historyRecords.length);
      renderHistoryPagination();
    }
  } catch (_err) {
    // silent refresh errors
  }
}

function getSelectedProcessTypes() {
  return Array.from(document.querySelectorAll(".proc-type-check:checked")).map((el) =>
    String(el.value || "").toUpperCase()
  );
}

function processTypeCardDescription(card) {
  return processPage.processTypeCardDescription(card, t);
}

function renderProcessTypeCards(schema) {
  const container = byId("process-type-checks") || document.querySelector(".dtype-checks");
  processPage.renderProcessTypeCards({
    container,
    escapeHtml,
    processSchemaClient,
    schema,
    selectedTypes: getSelectedProcessTypes(),
    t,
  });
}

function setResultTab(tabName) {
  activeResultTab = processPage.setResultTab(tabName);
}

function setPreflightItem(key, state, label) {
  processPage.setPreflightItem({ byId, key, label: label || t("preflight_status_pending"), state });
}

function setPreflightFileDetailOpen(open) {
  preflightFileDetailOpen = Boolean(open);
  const toggle = document.querySelector('[data-preflight-item="files"]');
  if (toggle) toggle.setAttribute("aria-expanded", preflightFileDetailOpen ? "true" : "false");
  renderPreflightFileDetail();
}

function renderPreflightFileDetail() {
  const moduleDescriptors = processSchemaClient.moduleList(processParameterSchema);
  processPage.renderPreflightFileDetail({
    detail: byId("preflight-file-detail"),
    escapeHtml,
    fileNameOnly,
    moduleDescriptors,
    open: preflightFileDetailOpen,
    preflightModel,
    scan: latestPreflightScan,
    selectedTypes: getSelectedProcessTypes(),
    t,
    toggleLabel: byId("preflight-files-state"),
  });
}

function renderPreflightChecks(preflight, state = "pending", message = "") {
  latestPreflightScan = processPage.renderPreflightChecks({
    byId,
    message,
    preflight,
    preflightModel,
    state,
    t,
  });
  renderPreflightFileDetail();
}

function syncProcessModulePanels() {
  expandedProcessModules = processPage.syncProcessModulePanels({
    expandedModules: expandedProcessModules,
    selectedTypes: getSelectedProcessTypes(),
    t,
  });
}

function toggleProcessModuleExpansion(dtype) {
  expandedProcessModules = processPage.toggleModuleExpansion(dtype, expandedProcessModules);
  syncProcessModulePanels();
}

function keepActiveProcessStepVisible(btn) {
  processPage.keepActiveProcessStepVisible(btn);
}

function setActiveProcessStep(stepKey, options = {}) {
  activeProcessStepKey = processPage.setActiveProcessStep({
    currentStepKey: activeProcessStepKey,
    keepVisible: options.keepVisible,
    stepKey,
  });
}

function getProcessStepEntries() {
  return processPage.getProcessStepEntries({ byId });
}

function refreshProcessScrollSpy() {
  processScrollSpyTicking = false;
  const panel = byId("tab-pro");
  if (!panel || !panel.classList.contains("active")) return;
  const entries = getProcessStepEntries();
  if (!entries.length) return;
  const probeY = window.scrollY + Math.min(260, Math.max(120, window.innerHeight * 0.32));
  let active = entries[0];
  entries.forEach((entry) => {
    if (entry.top <= probeY) active = entry;
  });
  setActiveProcessStep(active.key);
}

function requestProcessScrollSpyUpdate() {
  if (processScrollSpyTicking) return;
  processScrollSpyTicking = true;
  window.requestAnimationFrame(refreshProcessScrollSpy);
}

function setProcessStepStatus(stepKey, status) {
  processPage.setProcessStepStatus({ stepKey, status, t });
}

function updateProcessStepState() {
  const dataTypes = getSelectedProcessTypes();
  const hasFolder = Boolean(textValue("proc-folder"));
  const activeInputFiles = processSourceSelection.toInputFiles(processSourceItems, dataTypes);
  const primaryTypes = dataTypes.filter((dataType) => dataType !== "COUPLED");
  const hasSource = hasFolder && (!primaryTypes.length || activeInputFiles.length > 0);
  const hasTypes = dataTypes.length > 0;
  const hasTemplate = Boolean(appliedProcessTemplateName);
  const validationErrors = hasTypes ? collectProcessValidationErrors(dataTypes) : [];
  const coupledPeakMode = schemaControlValue("pro-coupled-input-mode", "coupled_input_mode") === "peak_analysis";
  const coupledMethodSource = schemaControlValue(
    "pro-coupled-peak-method-source",
    "coupled_peak_method_source"
  );
  const coupledMissing = dataTypes.includes("COUPLED") && (
    !textValue("pro-coupled-products-file")
    || (
      coupledPeakMode
      && coupledMethodSource === "file"
      && !textValue("pro-coupled-peak-method-file")
    )
  );

  setProcessStepStatus("source", hasSource ? "complete" : "issue");
  setProcessStepStatus("template", hasTemplate ? "complete" : "optional");
  setProcessStepStatus("type", !hasSource ? "pending" : (hasTypes ? "complete" : "issue"));
  setProcessStepStatus(
    "basic",
    !hasSource || !hasTypes ? "pending" : (validationErrors.length && !coupledMissing ? "issue" : "complete")
  );
  setProcessStepStatus(
    "modules",
    !hasSource || !hasTypes ? "pending" : (!coupledMissing ? "complete" : "issue")
  );
  setProcessStepStatus("preflight", !hasSource || !hasTypes ? "pending" : processPreflightState);
  setProcessStepStatus("result", !hasSource || !hasTypes ? "pending" : processRunState);
}

function markProcessChanged() {
  const state = processRuntime.resetState();
  processPreflightState = state.preflightState;
  processRunState = state.runState;
  renderPreflightChecks(null, "pending");
  updateProcessStepState();
}

function handleProcessStepClick(event) {
  const btn = event.target.closest(".process-step");
  if (!btn) return;
  const targetId = btn.dataset.stepTarget || "";
  const target = byId(targetId);
  setActiveProcessStep(btn.dataset.stepKey || "", { keepVisible: true });
  if (targetId === "proc-result-panel") {
    setResultTab("current");
  }
  if (target) {
    if (target.tagName === "DETAILS") {
      target.open = true;
    }
    target.scrollIntoView({ behavior: "smooth", block: "start", inline: "nearest" });
    requestProcessScrollSpyUpdate();
  }
}

function toggleDataTypePanels() {
  const selected = new Set(getSelectedProcessTypes());
  document.querySelectorAll(".dtype-panel").forEach((panel) => {
    panel.classList.toggle("hidden", !selected.has(panel.dataset.dtype));
  });
  syncFeatureBlocks();
  syncProcessModulePanels();
  updateProcessStepState();
  requestProcessScrollSpyUpdate();
}

function syncFeatureBlocks() {
  if (processSchemaClient.syncEisControls) processSchemaClient.syncEisControls();
  document.querySelectorAll(".dtype-panel").forEach((panel) => {
    const dtype = String(panel.dataset.dtype || "").toLowerCase();
    const advancedToggle = byId(`pro-${dtype}-advanced-mode`);
    const advancedEnabled = advancedToggle ? advancedToggle.checked : true;
    panel.querySelectorAll(".advanced-group").forEach((group) => {
      group.style.display = advancedEnabled ? "" : "none";
    });
  });
  document.querySelectorAll(".feature-body[data-feature-toggle]").forEach((body) => {
    const toggleId = body.getAttribute("data-feature-toggle");
    const toggle = byId(toggleId);
    const enabled = Boolean(toggle && toggle.checked);
    body.classList.toggle("hidden", !enabled);
    const featureBlock = body.closest(".feature-block");
    if (featureBlock) {
      featureBlock.classList.toggle("inactive", !enabled);
    }
    body.querySelectorAll("input, select, textarea").forEach((el) => {
      el.disabled = !enabled;
    });
  });
  syncIrCompensationUI();
  syncCoupledInputUI();
}

async function loadMoreHistory() {
  const button = byId("history-load-more");
  if (button) button.disabled = true;
  await loadStatsAndHistory({ append: true });
  if (button) button.disabled = false;
}

function closeProcessSourcePicker() {
  const picker = byId("proc-data-picker");
  if (picker) picker.open = false;
}

function sourceDiscoveryParams() {
  const params = { recursive_scan: boolValue("pro-recursive-scan") };
  processSourceSelection.PRIMARY_TYPES.forEach((dataType) => {
    const key = dataType.toLowerCase();
    const match = textValue(`pro-${key}-match`);
    const pattern = textValue(`pro-${key}-prefix`);
    if (match) params[`${key}_match`] = match;
    if (pattern) params[`${key}_prefix`] = pattern;
  });
  return params;
}

function renderProcessSourceList() {
  const container = byId("proc-source-list");
  const summary = byId("proc-source-summary");
  if (!container || !summary) return;
  const activeTypes = getSelectedProcessTypes();
  const activeFiles = processSourceSelection.toInputFiles(processSourceItems, activeTypes);
  if (!processSourceItems.length) {
    container.replaceChildren();
    summary.textContent = t("source_not_selected_hint");
    return;
  }
  const summaryTemplate = t("source_selected_summary");
  summary.textContent = summaryTemplate
    .replace("{total}", String(processSourceItems.length))
    .replace("{active}", String(activeFiles.length));
  container.innerHTML = processSourceItems.map((item, index) => {
    const options = [
      `<option value="">${escapeHtml(t("source_type_unassigned"))}</option>`,
      ...processSourceSelection.PRIMARY_TYPES.map((dataType) => (
        `<option value="${dataType}"${item.data_type === dataType ? " selected" : ""}>${dataType}</option>`
      )),
    ].join("");
    const conflict = item.status === "conflict" ? ` · ${escapeHtml(t("source_match_conflict"))}` : "";
    return `
      <div class="source-file-item" data-source-index="${index}">
        <input class="source-file-enabled" type="checkbox" ${item.enabled ? "checked" : ""} aria-label="${escapeHtml(item.name)}">
        <div class="source-file-copy" title="${escapeHtml(item.path)}">
          <span class="source-file-name">${escapeHtml(item.name)}${conflict}</span>
          <span class="source-file-path">${escapeHtml(item.folder)}</span>
        </div>
        <select class="source-file-type" aria-label="${escapeHtml(t("source_file_type"))}">${options}</select>
        <button class="source-file-remove" type="button">${escapeHtml(t("source_remove"))}</button>
      </div>`;
  }).join("");
}

function enableDiscoveredProcessTypes(items) {
  let changed = false;
  (items || []).forEach((item) => {
    if (!item.data_type) return;
    const checkbox = document.querySelector(`.proc-type-check[value="${item.data_type}"]`);
    if (checkbox && !checkbox.checked) {
      checkbox.checked = true;
      expandedProcessModules.add(item.data_type);
      changed = true;
    }
  });
  if (changed) toggleDataTypePanels();
}

function disableUnusedSourceType(dataType) {
  if (!processSourceSelection.PRIMARY_TYPES.includes(dataType)) return;
  if (processSourceItems.some((item) => item.data_type === dataType)) return;
  const checkbox = document.querySelector(`.proc-type-check[value="${dataType}"]`);
  if (checkbox && checkbox.checked) {
    checkbox.checked = false;
    expandedProcessModules.delete(dataType);
    toggleDataTypePanels();
  }
}

async function discoverAndMergeProcessSources(payload, origin, replaceOrigin = false) {
  setProcStatus(t("source_discovering"));
  const resp = await processingApi.discoverInputs({
    ...payload,
    data_types: getSelectedProcessTypes(),
    params: sourceDiscoveryParams(),
    recursive_scan: boolValue("pro-recursive-scan"),
  });
  const data = await resp.json();
  if (!resp.ok || data.status !== "success") {
    throw new Error(data.message || t("source_pick_failed"));
  }
  processSourceItems = processSourceSelection.merge(processSourceItems, data.files || [], {
    origin,
    replaceOrigin,
  });
  enableDiscoveredProcessTypes(processSourceItems);
  const folderInput = byId("proc-folder");
  if (folderInput && !folderInput.value) {
    folderInput.value = data.folder_path || processSourceSelection.preferredFolder(processSourceItems, "");
  }
  renderProcessSourceList();
  markProcessChanged();
  return data;
}

async function pickProcessFiles() {
  if (window.ElectrochemDesktop && window.ElectrochemDesktop.isEnabled()) {
    closeProcessSourcePicker();
    return window.ElectrochemDesktop.chooseFiles();
  }
  closeProcessSourcePicker();
  setProcStatus(t("source_pick_files_opening"));
  try {
    const resp = await systemApi.selectFiles(textValue("proc-folder") || undefined, [".txt", ".csv"]);
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("source_pick_failed"));
    }
    await discoverAndMergeProcessSources(
      { file_paths: data.file_paths || [] },
      `manual:${Date.now()}`,
      false
    );
    setProcStatus(t("source_pick_success"));
  } catch (err) {
    setProcStatus(`${t("source_pick_failed")}: ${err.message}`);
  }
}

async function pickProcessFolder() {
  closeProcessSourcePicker();
  setProcStatus(t("source_pick_folder_opening"));
  try {
    const resp = await systemApi.selectFolder(textValue("proc-folder") || undefined);
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("source_pick_failed"));
    }
    const folderPath = String(data.folder_path || "");
    const folderInput = byId("proc-folder");
    if (folderInput) folderInput.value = folderPath;
    if (!processSourceFolders.includes(folderPath)) processSourceFolders.push(folderPath);
    const discovered = await discoverAndMergeProcessSources(
      { folder_path: folderPath },
      `folder:${folderPath}`,
      true
    );
    setProcStatus(discovered.count ? t("source_pick_success") : t("source_empty_folder"));
  } catch (err) {
    setProcStatus(`${t("source_pick_failed")}: ${err.message}`);
  }
}

async function refreshProcessSourceFolders() {
  if (!processSourceFolders.length) return;
  try {
    for (const folderPath of processSourceFolders) {
      await discoverAndMergeProcessSources(
        { folder_path: folderPath },
        `folder:${folderPath}`,
        true
      );
    }
    setProcStatus(t("source_pick_success"));
  } catch (err) {
    setProcStatus(`${t("source_pick_failed")}: ${err.message}`);
  }
}

function clearProcessSources() {
  processSourceItems = [];
  processSourceFolders = [];
  const folderInput = byId("proc-folder");
  if (folderInput) folderInput.value = "";
  renderProcessSourceList();
  markProcessChanged();
}

async function pickIrEisFile() {
  const initial = textValue("pro-lsv-ir-eis-file") || textValue("proc-folder") || undefined;
  setProcStatus(t("ir_eis_picker_opening"));
  try {
    const resp = await systemApi.selectFile(initial, [".txt", ".csv"]);
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("ir_eis_picker_failed"));
    }
    const input = byId("pro-lsv-ir-eis-file");
    if (input) input.value = data.file_path || "";
    markProcessChanged();
    setProcStatus(t("ir_eis_picker_success"));
  } catch (err) {
    setProcStatus(`${t("ir_eis_picker_failed")}: ${err.message}`);
  }
}

function collectProcessPayload() {
  if (!processParameterSchema) {
    throw new Error(t("proc_schema_unavailable"));
  }
  return processPayloadBuilder.collectPayload(processPayloadContext());
}

function processRuntimeContext() {
  return {
    byId,
    collectProcessPayload,
    formatPreflightSummary,
    getActiveProcessJobId: () => activeProcessJobId,
    loadProjects: () => loadProjects(selectedProjectId),
    loadStatsAndHistory,
    processingApi,
    renderPreflightChecks,
    renderProcessError,
    renderProcessResult,
    runPreflight,
    setProcStatus,
    setActiveProcessJob,
    setProcessSubmitting,
    updateProcessJobProgress,
    setProcessPreflightState: (state) => {
      processPreflightState = state;
    },
    setProcessRunState: (state) => {
      processRunState = state;
    },
    t,
    updateProcessStepState,
  };
}

function formatPreflightSummary(preflight) {
  const moduleDescriptors = processSchemaClient.moduleList(processParameterSchema);
  return processRuntime.formatPreflightSummary({
    moduleDescriptors,
    preflight,
    preflightModel,
    selectedTypes: getSelectedProcessTypes(),
    t,
  });
}

async function runPreflight(silent = false) {
  return processRuntime.runPreflight(processRuntimeContext(), { silent });
}

async function exportDiagnostics() {
  return processRuntime.exportDiagnostics(processRuntimeContext());
}

async function runProcess() {
  if (window.ElectrochemDesktop && window.ElectrochemDesktop.isLocked()) return;
  return processRuntime.runProcess(processRuntimeContext());
}

function bindEvents() {
  byId("tab-btn-pro").addEventListener("click", () => switchTab("pro"));
  byId("tab-btn-project").addEventListener("click", () => switchTab("project"));
  document.querySelectorAll(".side-mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.sideTab || "pro"));
  });
  byId("assistant-fab").addEventListener("click", openAssistantDrawer);
  byId("assistant-close").addEventListener("click", closeAssistantDrawer);
  byId("assistant-history-toggle").addEventListener("click", toggleAssistantHistory);
  byId("assistant-suggest-btn").addEventListener("click", prepareProfessionalAdvicePrompt);
  byId("assistant-database-suggest").addEventListener("click", prepareDatabaseAdvicePrompt);
  const processStepper = document.querySelector(".process-stepper");
  if (processStepper) {
    processStepper.addEventListener("click", handleProcessStepClick);
  }
  window.addEventListener("scroll", requestProcessScrollSpyUpdate, { passive: true });
  window.addEventListener("resize", requestProcessScrollSpyUpdate);
  byId("help-docs-btn").addEventListener("click", openHelpPanel);
  byId("help-panel-close").addEventListener("click", closeHelpPanel);
  byId("help-panel-mask").addEventListener("click", closeHelpPanel);
  byId("help-doc-toc-items").addEventListener("click", (e) => {
    const btn = e.target.closest(".help-toc-link");
    if (!btn) return;
    jumpToHelpHeading(btn.dataset.target || "");
  });
  byId("help-doc-scroll").addEventListener("scroll", refreshHelpTocActive);
  byId("sys-status-btn").addEventListener("click", openSystemPanel);
  byId("sys-panel-close").addEventListener("click", closeSystemPanel);
  byId("sys-panel-mask").addEventListener("click", closeSystemPanel);
  byId("sys-panel-refresh").addEventListener("click", fetchHealth);
  byId("ai-settings-open").addEventListener("click", openAISettingsPanel);
  byId("ai-settings-close").addEventListener("click", closeAISettingsPanel);
  byId("ai-settings-mask").addEventListener("click", closeAISettingsPanel);

  byId("lang-select").addEventListener("change", (e) => {
    currentLang = e.target.value || "zh";
    localStorage.setItem("electrochem_v6_lang", currentLang);
    applyI18n();
    if (projectRecovery) projectRecovery.refresh(projectWorkbenchContext());
    if (taskCenter) taskCenter.refresh();
    if (!byId("assistant-drawer").classList.contains("hidden")) refreshAssistantContextPreview();
    renderProcessSourceList();
    fetchHealth();
    if (currentConversationId) {
      openConversation(currentConversationId, true);
    } else {
      renderMessages([]);
      byId("conv-title").textContent = t("conv_none");
      byId("conv-meta").textContent = t("conv_auto_create");
    }
    loadConversations();
    loadStatsAndHistory();
    loadProjects(selectedProjectId);
    renderTemplateOptions();
    updateLLMKeyHint(textValue("llm-provider"));
    aiSettingsPage.renderModelDiscovery(aiSettingsContext());
    if (!hasProcessResult) {
      renderResultPlaceholder();
    }
  });
  byId("conv-refresh").addEventListener("click", loadConversations);
  byId("conv-search-btn").addEventListener("click", applyConversationFilter);
  byId("conv-search-clear").addEventListener("click", clearConversationFilter);
  byId("conv-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      applyConversationFilter();
    }
  });
  byId("history-refresh").addEventListener("click", () => loadStatsAndHistory());
  byId("history-load-more").addEventListener("click", loadMoreHistory);
  byId("project-refresh").addEventListener("click", () => {
    loadProjects(selectedProjectId);
    loadStorageSummary();
  });
  byId("storage-refresh-btn").addEventListener("click", loadStorageSummary);
  byId("storage-cleanup-btn").addEventListener("click", cleanupManagedStorage);
  byId("project-include-archived").addEventListener("change", (e) => {
    projectIncludeArchived = Boolean(e.target.checked);
    applyProjectHistoryFilters();
  });
  byId("project-show-recycle").addEventListener("change", (e) => {
    projectListStatus = e.target.checked ? "archived" : "active";
    selectedProjectId = "";
    projectDetailState = null;
    loadProjects("");
  });
  byId("project-output-type-filter").addEventListener("change", (e) => {
    projectOutputTypeFilter = String(e.target.value || "").toUpperCase();
    renderSelectedProjectDetail();
  });
  byId("project-compare-sort").addEventListener("change", (e) => {
    projectCompareSort = String(e.target.value || "eta");
    renderSelectedProjectDetail();
  });
  byId("project-compare-only-eta").addEventListener("change", (e) => {
    projectCompareOnlyEta = Boolean(e.target.checked);
    renderSelectedProjectDetail();
  });
  byId("project-compare-only-tafel").addEventListener("change", (e) => {
    projectCompareOnlyTafel = Boolean(e.target.checked);
    renderSelectedProjectDetail();
  });
  byId("project-compare-chart-type").addEventListener("change", (e) => {
    projectCompareChartType = String(e.target.value || "overlay");
    projectComparePlotData = null;
    syncProjectCompareControls();
    renderProjectComparePlot();
    loadLatestProjectComparePlot(true);
  });
  byId("project-compare-metric").addEventListener("change", (e) => {
    projectCompareMetric = String(e.target.value || "potential_at_target");
    projectComparePlotData = null;
    syncProjectCompareControls();
    renderProjectComparePlot();
    loadLatestProjectComparePlot(true);
  });
  byId("project-compare-target-current").addEventListener("change", (e) => {
    projectCompareTargetCurrent = String(e.target.value || "10").trim() || "10";
    projectComparePlotData = null;
    renderProjectComparePlot();
    loadLatestProjectComparePlot(true);
  });
  byId("project-compare-select-all-btn").addEventListener("click", () => {
    const summary = projectDetailState && projectDetailState.lsv ? projectDetailState.lsv : null;
    const samples = getFilteredProjectCompareSamples(summary).map((it) => String(it.sample_name || "").trim()).filter(Boolean);
    projectCompareSelectedSamples = samples;
    projectComparePlotData = null;
    renderProjectCompareTable(summary);
    renderProjectComparePlot();
  });
  byId("project-compare-clear-btn").addEventListener("click", () => {
    projectCompareSelectedSamples = [];
    projectComparePlotData = null;
    renderProjectCompareSelectionCount();
    renderProjectCompareTable(projectDetailState && projectDetailState.lsv ? projectDetailState.lsv : null);
    renderProjectComparePlot();
  });
  byId("project-compare-generate-btn").addEventListener("click", generateProjectComparePlot);
  byId("project-create-btn").addEventListener("click", () => {
    projectWorkspace.openProjectCreateDialog(projectWorkspaceContext());
    if (projectPreferences) projectPreferences.prepareCreate(projectPreferencesContext());
  });
  byId("project-results-filter-form").addEventListener("submit", (event) => { event.preventDefault(); applyProjectHistoryFilters(); });
  byId("project-results-search").addEventListener("input", () => applyProjectHistoryFilters(true));
  ["project-results-type", "project-results-date-from", "project-results-date-to"].forEach((id) => byId(id).addEventListener("change", () => applyProjectHistoryFilters()));
  byId("project-results-filter-clear").addEventListener("click", () => { resetProjectHistoryFilters(); applyProjectHistoryFilters(); });
  byId("project-create-form").addEventListener("submit", (event) => {
    event.preventDefault();
    createProject();
  });
  for (const id of ["project-create-close", "project-create-cancel"]) {
    byId(id).addEventListener("click", () => projectWorkspace.closeProjectCreateDialog(projectWorkspaceContext()));
  }
  byId("project-create-dialog").addEventListener("cancel", (event) => {
    event.preventDefault();
    projectWorkspace.closeProjectCreateDialog(projectWorkspaceContext());
  });
  byId("project-export-report-btn").addEventListener("click", exportCurrentProjectReport);
  byId("project-use-btn").addEventListener("click", applyCurrentProjectToForms);
  byId("project-save-btn").addEventListener("click", saveCurrentProject);
  byId("project-delete-btn").addEventListener("click", deleteCurrentProject);
  byId("project-restore-btn").addEventListener("click", restoreCurrentProject);
  byId("project-delete-permanent-btn").addEventListener("click", permanentlyDeleteCurrentProject);
  byId("project-open-result-btn").addEventListener("click", openSelectedProjectHistoryResult);
  byId("project-archive-history-btn").addEventListener("click", archiveSelectedProjectHistory);
  byId("project-delete-history-btn").addEventListener("click", deleteSelectedProjectHistory);
  byId("project-history-load-more").addEventListener("click", loadMoreProjectHistory);
  byId("project-edit-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      saveCurrentProject();
    }
  });
  byId("llm-reload").addEventListener("click", loadLLMConfig);
  byId("llm-test").addEventListener("click", testLLMConnection);
  byId("llm-save").addEventListener("click", saveLLMConfig);
  byId("prompt-apply-template").addEventListener("click", applyPromptTemplate);
  byId("prompt-save").addEventListener("click", savePromptSettings);
  byId("llm-provider").addEventListener("change", () => {
    applyLLMProviderPreset(textValue("llm-provider"));
  });
  aiSettingsPage.initModelDiscovery(aiSettingsContext());

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".inline-help")) closeInlineHelpPopovers();
  });

  byId("conv-new").addEventListener("click", startNewConversation);

  byId("send-btn").addEventListener("click", sendMessage);
  byId("chat-log").addEventListener("click", handleAssistantApprovalClick);
  byId("msg-input").addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
    e.preventDefault();
    sendMessage();
  });
  byId("proc-run").addEventListener("click", runProcess);
  byId("proc-preflight-btn").addEventListener("click", () => runPreflight(false));
  byId("proc-diagnostics").addEventListener("click", exportDiagnostics);
  byId("proc-pick-files").addEventListener("click", pickProcessFiles);
  byId("proc-pick-folder").addEventListener("click", pickProcessFolder);
  byId("proc-source-clear").addEventListener("click", clearProcessSources);
  byId("proc-source-list").addEventListener("change", (event) => {
    const row = event.target.closest("[data-source-index]");
    if (!row) return;
    const index = Number(row.dataset.sourceIndex);
    const item = processSourceItems[index];
    if (!item) return;
    if (event.target.classList.contains("source-file-enabled")) {
      item.enabled = Boolean(event.target.checked);
    }
    if (event.target.classList.contains("source-file-type")) {
      const previousType = item.data_type;
      item.data_type = String(event.target.value || "").toUpperCase();
      if (item.data_type) {
        item.enabled = true;
        enableDiscoveredProcessTypes([item]);
      }
      if (previousType && previousType !== item.data_type) disableUnusedSourceType(previousType);
    }
    renderProcessSourceList();
    markProcessChanged();
  });
  byId("proc-source-list").addEventListener("click", (event) => {
    const button = event.target.closest(".source-file-remove");
    if (!button) return;
    const row = button.closest("[data-source-index]");
    const index = row ? Number(row.dataset.sourceIndex) : -1;
    if (index < 0 || !processSourceItems[index]) return;
    const removedType = processSourceItems[index].data_type;
    processSourceItems.splice(index, 1);
    disableUnusedSourceType(removedType);
    renderProcessSourceList();
    markProcessChanged();
  });
  byId("pro-recursive-scan").addEventListener("change", refreshProcessSourceFolders);
  byId("pro-lsv-ir-eis-file-btn").addEventListener("click", pickIrEisFile);
  byId("tmpl-load").addEventListener("click", loadSelectedTemplate);
  byId("tmpl-select").addEventListener("change", () => {
    if (textValue("tmpl-select") !== appliedProcessTemplateName) {
      appliedProcessTemplateName = "";
      updateProcessStepState();
    }
  });
  byId("tmpl-save").addEventListener("click", () => {
    saveTemplate(false);
  });
  byId("tmpl-delete").addEventListener("click", deleteSelectedTemplate);

  const processTypeChecks = byId("process-type-checks") || document.querySelector(".dtype-checks");
  if (processTypeChecks) {
    processTypeChecks.addEventListener("change", (event) => {
      const el = event.target.closest(".proc-type-check");
      if (!el) return;
      const dtype = String(el.value || "").toUpperCase();
      if (el.checked) {
        expandedProcessModules.add(dtype);
      } else {
        expandedProcessModules.delete(dtype);
      }
      markProcessChanged();
      toggleDataTypePanels();
      renderProcessSourceList();
    });
  }

  document.querySelectorAll(".dtype-panel .mode-panel-head").forEach((head) => {
    head.addEventListener("click", () => {
      const panel = head.closest(".dtype-panel");
      if (panel) toggleProcessModuleExpansion(panel.dataset.dtype || "");
    });
    head.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      const panel = head.closest(".dtype-panel");
      if (panel) toggleProcessModuleExpansion(panel.dataset.dtype || "");
    });
  });

  document.querySelectorAll(".result-tab").forEach((btn) => {
    btn.addEventListener("click", () => setResultTab(btn.dataset.resultTab || "current"));
  });

  const preflightFilesToggle = document.querySelector('[data-preflight-item="files"]');
  if (preflightFilesToggle) {
    preflightFilesToggle.addEventListener("click", () => setPreflightFileDetailOpen(!preflightFileDetailOpen));
  }

  document.querySelectorAll("#tab-pro input, #tab-pro select, #tab-pro textarea").forEach((el) => {
    el.addEventListener("input", markProcessChanged);
    el.addEventListener("change", markProcessChanged);
  });

  document.querySelectorAll(".feature-body[data-feature-toggle]").forEach((body) => {
    const toggleId = body.getAttribute("data-feature-toggle");
    const toggle = byId(toggleId);
    if (toggle) {
      toggle.addEventListener("change", syncFeatureBlocks);
    }
  });

  document.querySelectorAll(".module-advanced-check").forEach((el) => {
    el.addEventListener("change", syncFeatureBlocks);
  });

  ["pro-lsv-ir-source", "pro-lsv-ir-scope"].forEach((id) => {
    const el = byId(id);
    if (el) el.addEventListener("change", syncIrCompensationUI);
  });

  const coupledInputMode = byId("pro-coupled-input-mode");
  if (coupledInputMode) {
    coupledInputMode.addEventListener("change", syncCoupledInputUI);
  }
  const coupledPeakMethodSource = byId("pro-coupled-peak-method-source");
  if (coupledPeakMethodSource) {
    coupledPeakMethodSource.addEventListener("change", syncCoupledPeakMethodSourceUI);
  }
  const feProductAdd = byId("fe-product-add");
  if (feProductAdd) {
    feProductAdd.addEventListener("click", () => {
      addFeProductRow();
      markProcessChanged();
    });
  }
  const feProductList = byId("fe-product-list");
  if (feProductList) {
    feProductList.addEventListener("click", (event) => {
      const remove = event.target.closest("[data-fe-product-remove]");
      if (!remove || remove.disabled) return;
      const row = remove.closest("[data-fe-product-row]");
      if (row) row.remove();
      renumberFeProductRows();
      markProcessChanged();
    });
    feProductList.addEventListener("input", markProcessChanged);
    feProductList.addEventListener("change", markProcessChanged);
  }
  renumberFeProductRows();

  const potentialModeEl = byId("pro-potential-mode");
  if (potentialModeEl) {
    potentialModeEl.addEventListener("change", syncPotentialConversionUI);
  }
  const refPresetEl = byId("pro-ref-preset");
  if (refPresetEl) {
    refPresetEl.addEventListener("change", syncPotentialConversionUI);
  }
  ["pro-offset", "pro-rhe-ph", "pro-rhe-temperature", "pro-ref-custom"].forEach((id) => {
    const el = byId(id);
    if (el) el.addEventListener("input", renderPotentialOffsetPreview);
  });

  const ecsaMaterialEl = byId("pro-ecsa-material");
  if (ecsaMaterialEl) {
    ecsaMaterialEl.addEventListener("change", () => {
      const val = ecsaMaterialEl.value;
      const presets = processParameterSchema && processParameterSchema.presets;
      const materials = presets && Array.isArray(presets.ecsa_materials) ? presets.ecsa_materials : [];
      const selected = materials.find((item) => String(item.key) === val);
      if (selected && selected.specific_capacitance_uf_cm2 != null) {
        const csInput = byId("pro-ecsa-cs-value");
        if (csInput) csInput.value = selected.specific_capacitance_uf_cm2;
      }
    });
  }

  document.querySelectorAll("[data-match-label]").forEach((label) => {
    const baseId = String(label.dataset.matchLabel || "").trim().toLowerCase();
    const el = byId(`pro-${baseId}-match`);
    if (el) {
      el.addEventListener("change", () => syncMatchFieldMeta(baseId));
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    closeInlineHelpPopovers();
    closeHelpPanel();
    closeSystemPanel();
    closeAISettingsPanel();
    closeAssistantDrawer();
  });
}

function ensureProcessResultPage() {
  const required = ["buildResultFromHistoryRecord", "historyRecordKey", "renderError", "renderHistory", "renderPlaceholder", "renderResult", "setActiveHistoryItem"];
  const ready = () => required.every((name) => typeof window.ElectrochemProcessResultPage?.[name] === "function");
  if (ready()) {
    processResultPage = window.ElectrochemProcessResultPage;
    return true;
  }
  if (processResultPageRetryStarted) return false;
  processResultPageRetryStarted = true;
  // A failed classic-script request does not stop the parser from running app.js.
  // Retry this required renderer once, before binding any partially working UI.
  const script = document.createElement("script");
  let settled = false;
  const finish = () => {
    if (settled) return;
    settled = true;
    clearTimeout(timeout);
    script.onload = null;
    script.onerror = null;
    script.remove();
    if (ready()) {
      processResultPage = window.ElectrochemProcessResultPage;
      init();
      return;
    }
    const notice = document.createElement("section");
    notice.id = "app-startup-error";
    notice.className = "card";
    notice.setAttribute("role", "alert");
    notice.tabIndex = -1;
    const message = document.createElement("p");
    message.textContent = "结果界面加载失败，页面尚未启动。请重新加载；若仍失败，请重启软件。 / The results interface could not load. Reload the page; if this continues, restart the application.";
    const reload = document.createElement("button");
    reload.id = "app-startup-reload";
    reload.type = "button";
    reload.className = "btn primary";
    reload.textContent = "重新加载 / Reload";
    reload.addEventListener("click", () => window.location.reload());
    notice.append(message, reload);
    (document.querySelector(".shell") || document.body).prepend(notice);
    notice.focus();
  };
  const timeout = setTimeout(finish, 15000);
  script.onload = finish;
  script.onerror = finish;
  script.src = "/ui/static/process_result_page.js";
  document.head.appendChild(script);
  return false;
}

function init() {
  if (!ensureProcessResultPage()) return;
  const desktop = window.ElectrochemDesktop;
  if (desktop && desktop.requested() && !desktop.isEnabled()) {
    desktop.bootstrap().then(init).catch(() => {});
    return;
  }
  const restored = desktop && desktop.isEnabled() ? desktop.getWorkspace() : null;
  currentLang = localStorage.getItem("electrochem_v6_lang") || "zh";
  themeManager.init();
  if (window.ElectrochemAppearance) window.ElectrochemAppearance.init({ byId, t });
  applyI18n();
  bindEvents();
  if (projectWorkbench) projectWorkbench.init(projectWorkbenchContext);
  if (projectReplay) projectReplay.init(projectWorkbenchContext);
  if (projectPreferences) projectPreferences.init(projectPreferencesContext);
  if (projectRecovery) projectRecovery.init(projectWorkbenchContext);
  if (projectReplicates) projectReplicates.init(projectReplicatesContext);
  if (assistantActions) assistantActions.init(assistantActionsContext());
  if (taskCenter) taskCenter.init(taskCenterContext);
  if (desktop) desktop.init({
    getWorkspace: () => ({
      tab: byId("tab-project").classList.contains("active") ? "project" : "pro",
      project_id: selectedProjectId,
      conversation_id: currentConversationId || "",
      assistant_open: !byId("assistant-drawer").classList.contains("hidden"),
    }),
    openAISettings: openAISettingsPanel,
    openSystem: openSystemPanel,
    isProcessing: () => Boolean(activeProcessJobId || (byId("proc-run") && byId("proc-run").disabled)),
    importPaths: async (paths) => {
      switchTab("pro");
      await discoverAndMergeProcessSources({ file_paths: paths }, `desktop:${Date.now()}`, false);
      setProcStatus(t("source_pick_success"));
    },
  });
  switchTab(restored ? restored.tab : "pro");
  toggleDataTypePanels();
  syncFeatureBlocks();
  syncProcessModulePanels();
  setResultTab("current");
  renderPreflightChecks(null, "pending");
  renderProcessSourceList();
  syncAllMatchFieldMeta();
  syncPotentialConversionUI();
  renderResultPlaceholder();
  byId("conv-title").textContent = t("conv_none");
  byId("conv-meta").textContent = t("conv_auto_create");
  fetchHealth();
  if (restored && restored.conversation_id) conversationAutoSelect = false;
  const conversationsReady = loadConversations();
  loadStatsAndHistory();
  const projectsReady = loadProjects(restored ? restored.project_id : "");
  loadStorageSummary();
  loadPromptSettings();
  loadLLMConfig();
  loadTemplates();
  loadProcessingParameterSchema();
  requestProcessScrollSpyUpdate();
  const restoredConversation = restored && restored.conversation_id ? openConversation(restored.conversation_id, true).then((opened) => {
    if (opened === false && currentConversationId === restored.conversation_id) startNewConversation();
  }) : Promise.resolve();
  if (restored && restored.assistant_open) openAssistantDrawer();
  if (desktop && desktop.isEnabled()) Promise.allSettled([conversationsReady, projectsReady, restoredConversation]).then(() => desktop.markReady());
}

init();
