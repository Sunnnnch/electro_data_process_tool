(function () {
  "use strict";

  const state = { projectId: "", view: "results", keys: [], runs: [], compareRevision: 0, reportRevision: 0, runRevision: 0, runSignature: "" };
  let contextProvider;
  const text = (ctx, key, values = {}) => Object.entries(values).reduce((value, [name, replacement]) => value.replaceAll(`{${name}}`, String(replacement)), ctx.t(key));
  const escape = (ctx, value) => ctx.escapeHtml(String(value ?? ""));
  const records = (ctx) => (ctx.getProjectDetailState() || {}).history || [];
  const selectedRecords = (ctx) => records(ctx).filter((record) => state.keys.includes(ctx.historyRecordKey(record)));
  const selectedRecordKeys = (ctx) => selectedRecords(ctx).map((record) => ctx.historyRecordKey(record));
  const formatValue = (value) => value === null || value === undefined ? "—" : typeof value === "number" ? String(Number(value.toPrecision(7))) : typeof value === "object" ? JSON.stringify(value) : String(value);

  async function readResponse(response) {
    const data = await response.json();
    if (!response.ok || data.status !== "success") {
      const error = new Error(data.message || String(response.status || "Request failed"));
      error.plan = data.plan;
      throw error;
    }
    return data;
  }

  function showDialog(ctx, id) {
    const menu = ctx.byId("project-more-menu");
    if (menu) menu.open = false;
    const dialog = ctx.byId(id);
    if (dialog && !dialog.open) dialog.showModal();
  }

  function closeDialog(ctx, id) {
    const dialog = ctx.byId(id);
    if (dialog && dialog.open) dialog.close();
  }

  function setView(ctx, view) {
    state.view = ["results", "compare", "reports"].includes(view) ? view : "results";
    document.querySelectorAll("[data-project-view]").forEach((button) => {
      const active = button.dataset.projectView === state.view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    });
    ["results", "compare", "reports"].forEach((name) => { const panel = ctx.byId(`project-view-${name}`); if (panel) panel.hidden = name !== state.view; });
    if (state.view === "reports") refreshReportOptions(ctx);
  }

  function currentRecord(ctx) {
    return records(ctx).find((record) => ctx.historyRecordKey(record) === ctx.getSelectedHistoryKey()) || null;
  }

  function toggleRecord(ctx, key, selected) {
    state.keys = selected ? [...new Set([...state.keys, key])] : state.keys.filter((item) => item !== key);
    state.compareRevision += 1;
    const target = ctx.byId("project-version-comparison");
    if (target) target.innerHTML = `<p class="placeholder">${escape(ctx, text(ctx, "project_compare_versions_hint"))}</p>`;
    refreshSelection(ctx);
  }

  function refreshSelection(ctx) {
    const selected = selectedRecords(ctx);
    const bar = ctx.byId("project-record-selection");
    if (bar) bar.hidden = !selected.length;
    const count = ctx.byId("project-record-selection-count");
    if (count) count.textContent = text(ctx, "project_selected_records", { count: selected.length });
    ["project-compare-records-btn", "project-version-compare-btn"].forEach((id) => { const button = ctx.byId(id); if (button) button.disabled = selected.length !== 2; });
    const report = ctx.byId("project-report-selected-btn");
    if (report) report.disabled = !selectedRecordKeys(ctx).length;
    refreshReportOptions(ctx);
  }

  function clearSelection(ctx) {
    state.keys = [];
    state.compareRevision += 1;
    state.reportRevision += 1;
    const comparison = ctx.byId("project-version-comparison");
    if (comparison) comparison.textContent = ctx.t("project_compare_versions_hint");
    const report = ctx.byId("project-report-result");
    if (report) report.textContent = "";
    refreshSelection(ctx);
  }

  function refresh(ctx) {
    const projectId = ctx.getSelectedProjectId() || "";
    if (state.projectId !== projectId) {
      state.projectId = projectId;
      state.keys = [];
      state.runs = [];
      state.compareRevision += 1;
      state.reportRevision += 1;
      state.runRevision += 1;
      state.runSignature = "";
      ["project-version-comparison", "project-report-result"].forEach((id) => { const element = ctx.byId(id); if (element) element.innerHTML = ""; });
      closeDialog(ctx, "project-settings-dialog");
      closeDialog(ctx, "project-files-dialog");
      setView(ctx, "results");
    }
    ["project-view-tabs", "project-stats-line", "project-results-filter-form"].forEach((id) => { const el = ctx.byId(id); if (el) el.hidden = !projectId; });
    ["project-settings-open", "project-files-open", "project-export-report-btn"].forEach((id) => { const el = ctx.byId(id); if (el) el.disabled = !projectId; });
    if (ctx.getProjectDetailState()) state.keys = state.keys.filter((key) => records(ctx).some((record) => ctx.historyRecordKey(record) === key));
    refreshSelection(ctx);
    const record = currentRecord(ctx);
    ["project-replay-btn", "project-run-replay-btn", "project-run-report-btn"].forEach((id) => { const el = ctx.byId(id); if (el) el.disabled = !record || !record.run_id; });
    if (projectId && ctx.getProjectDetailState()) {
      const signature = `${projectId}:${(ctx.getProjectDetailState() || {}).historyTotal}:${records(ctx)[0] && records(ctx)[0].timestamp}`;
      if (signature !== state.runSignature) { state.runSignature = signature; loadReportRuns(ctx); }
    }
    renderUnrecordedRuns(ctx);
  }

  function parameterLabel(ctx, key) {
    const schema = window.ElectrochemProcessingSchema;
    const id = schema && schema.CONTROL_BINDINGS && schema.CONTROL_BINDINGS[key];
    const control = id && ctx.byId(id);
    const label = id && (document.querySelector(`label[for="${id}"]`) || control && control.closest("label"));
    return label ? label.textContent.trim() : key.replaceAll("_", " ");
  }

  function changesTable(ctx, changes) {
    if (!changes || !changes.length) return `<p class="panel-sub">${escape(ctx, text(ctx, "project_no_parameter_changes"))}</p>`;
    return `<div class="project-table-scroll"><table class="project-data-table"><thead><tr><th>${escape(ctx, text(ctx, "project_parameter"))}</th><th>${escape(ctx, text(ctx, "project_before"))}</th><th>${escape(ctx, text(ctx, "project_after"))}</th></tr></thead><tbody>${changes.map((item) => `<tr><td>${escape(ctx, parameterLabel(ctx, item.key))}</td><td>${escape(ctx, formatValue(item.before))}</td><td>${escape(ctx, formatValue(item.after))}</td></tr>`).join("")}</tbody></table></div>`;
  }

  async function compareSelected(ctx) {
    const selected = selectedRecords(ctx);
    setView(ctx, "compare");
    const target = ctx.byId("project-version-comparison");
    if (selected.length !== 2) { target.textContent = text(ctx, "project_compare_choose_two"); return; }
    if (selected[0].type !== selected[1].type) { target.textContent = text(ctx, "project_compare_same_type"); return; }
    const revision = ++state.compareRevision;
    target.innerHTML = `<p class="placeholder">${escape(ctx, text(ctx, "project_loading"))}</p>`;
    try {
      const data = await readResponse(await ctx.projectApi.compareRecords({ left_record_key: ctx.historyRecordKey(selected[0]), right_record_key: ctx.historyRecordKey(selected[1]), project_id: state.projectId }));
      if (revision !== state.compareRevision) return;
      const comparison = data.comparison || {};
      const header = selected.map((record, index) => `<div><strong>${escape(ctx, text(ctx, index ? "project_after" : "project_before"))} · ${escape(ctx, record.sample_name || record.type)}</strong><span>${escape(ctx, String(record.file_name || record.file_path || "").split(/[\\/]/).pop())}</span><span>${escape(ctx, record.timestamp)} · ${escape(ctx, record.run_id || "-")}</span></div>`).join("");
      const metricValue = (value, unit) => `${formatValue(value)}${value !== null && value !== undefined && unit ? ` ${unit}` : ""}`;
      const metricRows = (comparison.metrics || []).map((metric) => `<tr><td>${escape(ctx, metric.label || metric.key)}</td><td>${escape(ctx, metricValue(metric.left, metric.left_unit ?? metric.unit))}</td><td>${escape(ctx, metricValue(metric.right, metric.right_unit ?? metric.unit))}</td><td>${escape(ctx, metricValue(metric.delta, metric.unit))}${metric.relative_change_percent === null || metric.relative_change_percent === undefined ? "" : ` (${escape(ctx, formatValue(metric.relative_change_percent))}%)`}</td></tr>`).join("");
      const versions = comparison.versions || {};
      const provenance = [[text(ctx, "project_software_version"), versions.left_app, versions.right_app], [text(ctx, "project_formula_version"), versions.left_formula, versions.right_formula], [text(ctx, "project_quality_summary"), comparison.quality && comparison.quality.left, comparison.quality && comparison.quality.right]];
      target.innerHTML = `<div class="project-comparison-pair">${header}</div><p class="panel-sub">${escape(ctx, text(ctx, "project_delta_direction"))}</p><div class="project-table-scroll"><table class="project-data-table"><thead><tr><th>${escape(ctx, text(ctx, "project_metric"))}</th><th>${escape(ctx, text(ctx, "project_before"))}</th><th>${escape(ctx, text(ctx, "project_after"))}</th><th>${escape(ctx, text(ctx, "project_delta"))}</th></tr></thead><tbody>${metricRows}</tbody></table></div><details open><summary>${escape(ctx, text(ctx, "project_parameter_changes"))}</summary>${comparison.parameters_known === false ? `<p class="panel-sub">${escape(ctx, text(ctx, "project_parameters_unknown"))}</p>` : changesTable(ctx, comparison.parameter_changes)}</details><details><summary>${escape(ctx, text(ctx, "project_versions_quality"))}</summary><div class="project-table-scroll"><table class="project-data-table"><tbody>${provenance.map(([label, before, after]) => `<tr><th>${escape(ctx, label)}</th><td>${escape(ctx, formatValue(before))}</td><td>${escape(ctx, formatValue(after))}</td></tr>`).join("")}</tbody></table></div></details>${(comparison.warnings || []).length ? `<ul class="project-notices">${comparison.warnings.map((item) => `<li>${escape(ctx, item)}</li>`).join("")}</ul>` : ""}`;
    } catch (error) { if (revision === state.compareRevision) target.textContent = error.message; }
  }

  function reportRuns(ctx) {
    const all = new Map(state.runs.map((run) => [String(run.run_id), run]));
    records(ctx).forEach((record) => { if (record.run_id && !all.has(String(record.run_id))) all.set(String(record.run_id), { run_id: record.run_id, created_at: record.timestamp, data_types: [record.type] }); });
    return [...all.values()];
  }

  function refreshReportOptions(ctx) {
    const select = ctx.byId("project-report-run");
    if (!select) return;
    const previous = select.value;
    select.innerHTML = reportRuns(ctx).map((run) => `<option value="${escape(ctx, run.run_id)}">${escape(ctx, run.created_at || run.run_id)} · ${escape(ctx, (run.data_types || []).join(" / "))} · ${escape(ctx, String(run.run_id).slice(0, 8))}</option>`).join("");
    if ([...select.options].some((option) => option.value === previous)) select.value = previous;
    const scope = ctx.byId("project-report-scope").value;
    select.hidden = scope !== "run";
    ctx.byId("project-report-run-label").hidden = scope !== "run";
    ctx.byId("project-report-range").textContent = scope === "project" ? text(ctx, "project_report_all_hint") : scope === "selected" ? text(ctx, "project_report_selected_hint", { count: selectedRecordKeys(ctx).length }) : text(ctx, "project_report_single_hint");
  }

  async function loadReportRuns(ctx) {
    const projectId = state.projectId;
    if (!projectId || !ctx.projectApi.listRuns) return;
    const revision = ++state.runRevision;
    try {
      const runs = [];
      let offset = 0;
      while (true) {
        const data = await readResponse(await ctx.projectApi.listRuns(projectId, { offset, limit: 100 }));
        if (state.projectId !== projectId || revision !== state.runRevision) return;
        runs.push(...(data.runs || []));
        if (!data.has_more || !(Number(data.next_offset) > offset)) break;
        offset = Number(data.next_offset);
      }
      state.runs = runs;
      refreshReportOptions(ctx);
      renderUnrecordedRuns(ctx);
    } catch (_error) { /* Existing history remains selectable without a stored recipe. */ }
  }

  function renderUnrecordedRuns(ctx) {
    const target = ctx.byId("project-unrecorded-runs");
    if (!target) return;
    if (ctx.hasHistoryFilters && ctx.hasHistoryFilters()) { target.innerHTML = ""; return; }
    const runs = state.runs.filter((run) => Array.isArray(run.record_keys) && !run.record_keys.length);
    target.innerHTML = runs.map((run, index) => `<section class="project-run-group"><div class="project-run-head"><div><strong>${escape(ctx, run.created_at || run.run_id)}</strong><span>${escape(ctx, (run.data_types || []).join(" / "))} · ${escape(ctx, run.status || "")}</span></div><div class="mini-actions"><button class="btn mini" type="button" data-replay-empty-run="${index}">${escape(ctx, text(ctx, "project_replay_run"))}</button><button class="btn mini" type="button" data-report-empty-run="${index}">${escape(ctx, text(ctx, "project_report_run"))}</button></div></div><p class="panel-sub">${escape(ctx, run.error || text(ctx, "project_run_without_records"))}</p></section>`).join("");
    target.querySelectorAll("[data-replay-empty-run]").forEach((button) => button.addEventListener("click", () => window.ElectrochemProjectReplay.open(ctx, "run", runs[Number(button.dataset.replayEmptyRun)])));
    target.querySelectorAll("[data-report-empty-run]").forEach((button) => button.addEventListener("click", () => {
      ctx.byId("project-report-scope").value = "run";
      setView(ctx, "reports");
      ctx.byId("project-report-run").value = runs[Number(button.dataset.reportEmptyRun)].run_id;
    }));
  }

  async function exportReport(ctx) {
    const target = ctx.byId("project-report-result");
    const scope = ctx.byId("project-report-scope").value;
    const runId = ctx.byId("project-report-run").value;
    const recordKeys = selectedRecordKeys(ctx);
    if ((scope === "selected" && !recordKeys.length) || (scope === "run" && !runId)) { target.textContent = text(ctx, "project_report_selection_required"); return; }
    const revision = ++state.reportRevision;
    const button = ctx.byId("project-export-report-btn");
    button.disabled = true;
    target.textContent = text(ctx, "project_report_generating");
    try {
      const response = scope === "run" ? await ctx.projectApi.exportRunReport(runId, { format: "html" }) : await ctx.projectApi.exportScopedReport(state.projectId, { format: "html", include_archived: Boolean(ctx.getIncludeArchived()), ...(scope === "selected" ? { record_keys: recordKeys } : {}) });
      const data = await readResponse(response);
      if (revision !== state.reportRevision) return;
      const range = data.scope || {};
      target.innerHTML = `<p>${escape(ctx, text(ctx, "project_report_created", { runs: range.run_count ?? "-", records: range.record_count ?? "-" }))}</p><div class="mini-actions"><button class="btn primary" type="button" data-open-path="${escape(ctx, data.html_path || data.path)}">${escape(ctx, text(ctx, "project_report_open"))}</button>${data.markdown_path ? `<button class="btn mini" type="button" data-open-path="${escape(ctx, data.markdown_path)}">Markdown</button>` : ""}<button class="btn mini" type="button" data-open-dir="${escape(ctx, data.path)}">${escape(ctx, text(ctx, "btn_open_dir"))}</button></div>`;
      ctx.bindFileActions(target);
    } catch (error) { if (revision === state.reportRevision) target.textContent = error.message; }
    finally { if (revision === state.reportRevision) button.disabled = false; }
  }

  function reportCurrentRun(ctx) {
    const record = currentRecord(ctx);
    if (!record || !record.run_id) return;
    ctx.byId("project-report-scope").value = "run";
    setView(ctx, "reports");
    ctx.byId("project-report-run").value = record.run_id;
    loadReportRuns(ctx);
  }

  function init(provider) {
    contextProvider = provider;
    const ctx = provider();
    const on = (id, action) => { const el = ctx.byId(id); if (el) el.addEventListener("click", () => action(provider())); };
    document.querySelectorAll("[data-project-view]").forEach((button) => button.addEventListener("click", () => { const live = provider(); setView(live, button.dataset.projectView); if (button.dataset.projectView === "reports") loadReportRuns(live); }));
    ctx.byId("project-view-tabs").addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      const tabs = [...document.querySelectorAll("[data-project-view]")];
      const current = tabs.indexOf(document.activeElement);
      if (current < 0) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].click();
      tabs[next].focus();
    });
    on("project-settings-open", (live) => { live.setProjectEditForm(live.getProject()); showDialog(live, "project-settings-dialog"); });
    on("project-settings-close", (live) => closeDialog(live, "project-settings-dialog"));
    on("project-files-open", (live) => showDialog(live, "project-files-dialog"));
    on("project-files-close", (live) => closeDialog(live, "project-files-dialog"));
    on("project-detail-close", (live) => { live.setSelectedHistoryKey(""); live.renderHistory(); });
    on("project-compare-records-btn", compareSelected);
    on("project-version-compare-btn", compareSelected);
    on("project-clear-records-btn", (live) => { state.keys = []; live.renderHistory(); refreshSelection(live); });
    on("project-report-selected-btn", (live) => { live.byId("project-report-scope").value = "selected"; setView(live, "reports"); loadReportRuns(live); });
    on("project-run-report-btn", reportCurrentRun);
    const scope = ctx.byId("project-report-scope");
    if (scope) scope.addEventListener("change", () => refreshReportOptions(provider()));
    const search = ctx.byId("project-list-search");
    if (search) search.addEventListener("input", () => provider().renderProjectList());
    setView(ctx, "results");
  }

  window.ElectrochemProjectWorkbench = { init, refresh, clearSelection, setView, selectedKeys: () => state.keys.slice(), toggleRecord, compareSelected, exportReport, refreshSelection, currentRecord, loadReportRuns, readResponse, parameterLabel, changesTable, text, escape, showDialog, closeDialog, getContext: () => contextProvider() };
})();
