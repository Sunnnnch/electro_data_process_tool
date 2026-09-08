(function () {
  "use strict";

  let active = null;
  const workbench = () => window.ElectrochemProjectWorkbench;
  const text = (ctx, key, values) => workbench().text(ctx, key, values);
  const escape = (ctx, value) => workbench().escape(ctx, value);
  const read = (response) => workbench().readResponse(response);

  function sourceFields(ctx, plan, payload) {
    return (plan.source_checks || []).map((source, index) => `<div class="project-source-check"><div><strong>${escape(ctx, source.file_name || source.path)}</strong><span class="project-source-state ${escape(ctx, source.state)}">${escape(ctx, text(ctx, `project_source_${source.state}`))}</span></div><span class="project-path">${escape(ctx, source.resolved_path || source.path)}</span>${["missing", "changed", "unverified"].includes(source.state) || payload.source_paths && payload.source_paths[source.path] ? `<label>${escape(ctx, text(ctx, "project_source_replace"))}<input class="project-source-override" data-source-index="${index}" value="${escape(ctx, payload.source_paths && payload.source_paths[source.path] || source.resolved_path || source.path)}"></label>` : ""}</div>`).join("");
  }

  function parameterFields(ctx, params, dataTypes = []) {
    const client = window.ElectrochemProcessingSchema;
    const schema = client && client.getCached();
    const common = ["area", "potential_mode", "potential_offset", "rhe_ph", "rhe_temperature_c", "reference_electrode_preset", "reference_electrode_potential"];
    const byType = { LSV: ["lsv_target_current", "tafel_enabled", "tafel_range", "ir_compensation_enabled", "ir_manual_ohm"], CV: ["cv_scan_rate_v_s", "cv_cycle_numbers"], EIS: ["eis_circuit_model", "eis_randles_fit", "eis_kk_check"], ECSA: ["ecsa_ev", "ecsa_last_n", "ecsa_avg_last_n", "ecsa_cs_value", "ecsa_cs_unit"], COUPLED: ["coupled_input_mode"] };
    (dataTypes.length ? dataTypes : Object.keys(byType)).forEach((type) => common.push(...(byType[type] || [])));
    const fields = Object.entries(params || {}).flatMap(([key, value]) => {
      if (key === "output_run_dir_enabled") return [];
      const definition = client && client.getParameter(schema, key) || {};
      const isNull = value === null;
      const nullable = isNull || definition.default === null;
      const type = isNull ? definition.value_type : typeof value;
      if (!["number", "integer", "string", "boolean"].includes(type)) return [];
      const numeric = type === "number" || type === "integer";
      const options = Array.isArray(definition.options) ? definition.options : [];
      const control = client && client.CONTROL_BINDINGS && ctx.byId(client.CONTROL_BINDINGS[key]);
      const optionLabel = (value) => Array.from(control && control.options || []).find((item) => String(item.value) === String(value))?.textContent || value;
      const token = escape(ctx, key);
      const attributes = `class="project-replay-parameter" data-param-key="${token}" data-param-type="${numeric ? "number" : type}" data-param-nullable="${nullable}"`;
      let input;
      if (type === "boolean" && nullable) input = `<select ${attributes}><option value="" ${isNull ? "selected" : ""}>—</option><option value="true" ${value === true ? "selected" : ""}>${escape(ctx, text(ctx, "preflight_status_yes"))}</option><option value="false" ${value === false ? "selected" : ""}>${escape(ctx, text(ctx, "preflight_status_no"))}</option></select>`;
      else if (type === "boolean") input = `<input ${attributes} type="checkbox" ${value ? "checked" : ""}>`;
      else if (options.length) input = `<select ${attributes}>${nullable ? `<option value="" ${isNull ? "selected" : ""}>—</option>` : ""}${options.map((option) => `<option value="${escape(ctx, option)}" ${!isNull && String(option) === String(value) ? "selected" : ""}>${escape(ctx, optionLabel(option))}</option>`).join("")}</select>`;
      else input = `<input ${attributes} type="${numeric ? "number" : "text"}" ${numeric ? 'step="any"' : ""} value="${escape(ctx, value ?? "")}">`;
      return [{ key, html: `<label class="project-replay-field"><span>${escape(ctx, workbench().parameterLabel(ctx, key))}</span>${input}</label>` }];
    });
    const primary = fields.filter((field) => common.includes(field.key)).sort((a, b) => common.indexOf(a.key) - common.indexOf(b.key));
    const secondary = fields.filter((field) => !common.includes(field.key));
    return `<div class="project-replay-fields">${primary.map((field) => field.html).join("")}</div>${secondary.length ? `<details class="project-replay-more"><summary>${escape(ctx, text(ctx, "project_replay_more_parameters"))} (${secondary.length})</summary><div class="project-replay-fields">${secondary.map((field) => field.html).join("")}</div></details>` : ""}`;
  }

  function payloadFor(ctx, replay) {
    const payload = replay.recordKey ? { record_key: replay.recordKey } : {};
    if (ctx.byId("project-replay-mode").value === "modified") {
      payload.params = {};
      ctx.byId("project-replay-content").querySelectorAll(".project-replay-parameter").forEach((input) => {
        const emptyNull = input.dataset.paramNullable === "true" && !input.value.trim();
        const value = emptyNull ? null : input.dataset.paramType === "boolean" ? input.type === "checkbox" ? input.checked : input.value === "true" : input.dataset.paramType === "number" ? Number(input.value) : input.value;
        if (!emptyNull && input.dataset.paramType === "number" && (!input.value.trim() || !Number.isFinite(value))) throw new Error(text(ctx, "project_replay_invalid_number", { name: workbench().parameterLabel(ctx, input.dataset.paramKey) }));
        if (JSON.stringify(value) !== JSON.stringify(replay.originalParams[input.dataset.paramKey])) payload.params[input.dataset.paramKey] = value;
      });
    }
    const paths = { ...(replay.sourcePaths || {}) };
    ctx.byId("project-replay-content").querySelectorAll(".project-source-override").forEach((input) => {
      const source = replay.plan.source_checks[Number(input.dataset.sourceIndex)];
      if (input.value.trim() && input.value.trim() !== source.path) paths[source.path] = input.value.trim();
      else delete paths[source.path];
    });
    if (Object.keys(paths).length) payload.source_paths = paths;
    const allowChanged = ctx.byId("project-replay-allow-changed");
    if (allowChanged && allowChanged.checked || replay.allowChanged && !allowChanged) payload.allow_changed_sources = true;
    return payload;
  }

  function renderPlan(ctx, replay, plan, payload = {}) {
    replay.plan = plan;
    replay.sourcePaths = payload.source_paths || {};
    replay.allowChanged = Boolean(payload.allow_changed_sources);
    const target = ctx.byId("project-replay-plan");
    const notices = [...(plan.issues || []), ...(plan.warnings || [])];
    target.innerHTML = `<p class="panel-sub">${escape(ctx, text(ctx, "project_replay_versions", { before: plan.source_app_version || "—", after: plan.current_app_version || "—" }))}</p>${notices.length ? `<ul class="project-notices">${notices.map((item) => `<li>${escape(ctx, item)}</li>`).join("")}</ul>` : ""}<details ${plan.can_replay ? "" : "open"}><summary>${escape(ctx, text(ctx, "project_source_checks"))}</summary>${sourceFields(ctx, plan, payload)}</details><details ${plan.parameter_changes && plan.parameter_changes.length ? "open" : ""}><summary>${escape(ctx, text(ctx, "project_parameter_changes"))}</summary>${workbench().changesTable(ctx, plan.parameter_changes)}</details>${plan.requires_changed_confirmation || replay.allowChanged ? `<label class="compact-check"><input id="project-replay-allow-changed" type="checkbox" ${replay.allowChanged ? "checked" : ""}><span>${escape(ctx, text(ctx, "project_replay_changed_confirm"))}</span></label>` : ""}`;
    ctx.byId("project-replay-execute").disabled = !plan.can_replay || Boolean(plan.requires_changed_confirmation && !replay.allowChanged);
    replay.plannedPayload = JSON.stringify(payloadFor(ctx, replay));
  }

  async function open(ctx, scope, runOverride, suggestedParams) {
    const record = runOverride || workbench().currentRecord(ctx);
    if (!record || !record.run_id) return;
    if (active && (active.jobId || active.submitting)) { workbench().showDialog(ctx, "project-replay-dialog"); return; }
    const replay = { runId: record.run_id, recordKey: scope === "record" ? ctx.historyRecordKey(record) : "", plan: null, originalParams: {}, sourcePaths: {}, jobId: "", revision: 0, projectId: ctx.getSelectedProjectId() };
    active = replay;
    workbench().showDialog(ctx, "project-replay-dialog");
    const target = ctx.byId("project-replay-content");
    target.textContent = text(ctx, "project_loading");
    ctx.byId("project-replay-status").textContent = "";
    try {
      const data = await read(await ctx.projectApi.replayPlan(replay.runId, replay.recordKey ? { record_key: replay.recordKey } : {}));
      if (active !== replay) return;
      replay.originalParams = data.plan.params || {};
      target.innerHTML = `<p><strong>${escape(ctx, record.sample_name || (record.data_types || []).join(" / ") || record.type)}</strong> · ${escape(ctx, text(ctx, scope === "record" ? "project_replay_record" : "project_replay_run"))}</p><p class="panel-sub">${escape(ctx, text(ctx, "project_replay_preserve"))}</p><label class="project-replay-mode-label" for="project-replay-mode">${escape(ctx, text(ctx, "project_replay_mode"))}</label><select id="project-replay-mode"><option value="original">${escape(ctx, text(ctx, "project_replay_original"))}</option><option value="modified">${escape(ctx, text(ctx, "project_replay_modified"))}</option></select><details id="project-replay-parameters" hidden><summary>${escape(ctx, text(ctx, "project_replay_edit_parameters"))}</summary>${parameterFields(ctx, data.plan.params, data.plan.data_types || (record.type ? [record.type] : record.data_types))}</details><div id="project-replay-plan"></div><div class="mini-actions"><button id="project-replay-check" class="btn mini" type="button">${escape(ctx, text(ctx, "project_replay_check"))}</button><button id="project-replay-execute" class="btn primary" type="button">${escape(ctx, text(ctx, "project_replay_execute"))}</button><button id="project-replay-cancel" class="btn mini" type="button" hidden>${escape(ctx, text(ctx, "process_job_cancel"))}</button></div>`;
      renderPlan(ctx, replay, data.plan);
      const invalidate = () => { if (active === replay && !replay.jobId && !replay.submitting) { replay.revision += 1; ctx.byId("project-replay-execute").disabled = true; } };
      target.oninput = invalidate;
      target.onchange = invalidate;
      ctx.byId("project-replay-mode").addEventListener("change", () => {
        const params = ctx.byId("project-replay-parameters");
        params.hidden = ctx.byId("project-replay-mode").value !== "modified";
        params.open = !params.hidden;
      });
      ctx.byId("project-replay-check").onclick = () => check(ctx);
      ctx.byId("project-replay-execute").onclick = () => execute(ctx);
      ctx.byId("project-replay-cancel").onclick = async () => {
        if (!replay.jobId) return;
        try { await read(await ctx.processingApi.cancelProcessJob(replay.jobId)); }
        catch (error) { ctx.byId("project-replay-status").textContent = error.message; }
      };
      if (suggestedParams && Object.keys(suggestedParams).length) {
        ctx.byId("project-replay-mode").value = "modified";
        const params = ctx.byId("project-replay-parameters");
        params.hidden = false;
        params.open = true;
        for (const [key, value] of Object.entries(suggestedParams)) {
          const input = Array.from(target.querySelectorAll(".project-replay-parameter")).find((item) => item.dataset.paramKey === key);
          if (!input) throw new Error(`${text(ctx, "project_replay_invalid_number", { name: key })}`);
          if (input.type === "checkbox") input.checked = Boolean(value);
          else input.value = value === null ? "" : String(value);
        }
        invalidate();
        ctx.byId("project-replay-status").textContent = text(ctx, "project_replay_needs_sources");
      }
    } catch (error) { if (active === replay) target.textContent = `${text(ctx, "project_replay_unavailable")}: ${error.message}`; }
  }

  async function check(ctx) {
    const replay = active;
    if (!replay || replay.jobId || replay.submitting) return;
    const revision = ++replay.revision;
    const target = ctx.byId("project-replay-status");
    ctx.byId("project-replay-execute").disabled = true;
    try {
      const payload = payloadFor(ctx, replay);
      target.textContent = text(ctx, "project_loading");
      const data = await read(await ctx.projectApi.replayPlan(replay.runId, payload));
      if (active !== replay || revision !== replay.revision) return;
      renderPlan(ctx, replay, data.plan, payload);
      target.textContent = data.plan.can_replay ? text(ctx, "project_replay_ready") : text(ctx, "project_replay_needs_sources");
    } catch (error) { if (active === replay && revision === replay.revision) target.textContent = error.message; }
  }

  async function execute(ctx) {
    const replay = active;
    if (!replay || replay.jobId || replay.submitting || ctx.byId("project-replay-execute").disabled) return;
    const status = ctx.byId("project-replay-status");
    try {
      const payload = payloadFor(ctx, replay);
      if (JSON.stringify(payload) !== replay.plannedPayload) { status.textContent = text(ctx, "project_replay_recheck"); return; }
      replay.submitting = true;
      ctx.byId("project-replay-execute").disabled = true;
      ctx.byId("project-replay-check").disabled = true;
      const data = await read(await ctx.projectApi.replayRun(replay.runId, payload));
      if (!data.job_id) throw new Error(text(ctx, "proc_failed"));
      replay.jobId = data.job_id;
      ctx.byId("project-replay-cancel").hidden = false;
      let job = data.job || { status: "queued" };
      while (["queued", "running"].includes(job.status)) {
        status.textContent = `${text(ctx, "proc_running")} ${job.current_item || ""}`;
        await new Promise((resolve) => setTimeout(resolve, 500));
        const response = await read(await ctx.processingApi.getProcessJob(replay.jobId));
        job = response.job;
      }
      if (job.status !== "succeeded") throw new Error(job.error || text(ctx, job.status === "cancelled" ? "process_job_cancelled" : "proc_failed"));
      status.textContent = text(ctx, "project_replay_done");
      if (ctx.getSelectedProjectId() === replay.projectId) await ctx.loadSelectedProjectDetail();
      if (ctx.getSelectedProjectId() === replay.projectId) await workbench().loadReportRuns(ctx);
      await ctx.loadStatsAndHistory();
    } catch (error) { status.textContent = error.message; if (error.plan) renderPlan(ctx, replay, error.plan); }
    finally {
      replay.submitting = false;
      replay.jobId = "";
      if (active === replay) {
        ctx.byId("project-replay-cancel").hidden = true;
        ctx.byId("project-replay-check").disabled = false;
      }
    }
  }

  function init(provider) {
    const ctx = provider();
    ctx.byId("project-replay-btn").addEventListener("click", () => open(provider(), "record"));
    ctx.byId("project-run-replay-btn").addEventListener("click", () => open(provider(), "run"));
    ctx.byId("project-replay-close").addEventListener("click", () => workbench().closeDialog(provider(), "project-replay-dialog"));
  }

  window.ElectrochemProjectReplay = { init, open, check, execute, payloadFor, parameterFields };
})();
