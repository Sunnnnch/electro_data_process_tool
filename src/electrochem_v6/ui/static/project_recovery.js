(function () {
  "use strict";

  let active = null;
  let listRevision = 0;
  const wb = () => window.ElectrochemProjectWorkbench;
  const text = (ctx, key, values) => wb().text(ctx, key, values);
  const escape = (ctx, value) => wb().escape(ctx, value);
  const read = (response) => wb().readResponse(response);
  const short = (value) => String(value || "").slice(0, 8);

  function setBusy(ctx, busy) {
    ctx.byId("project-recovery-content").querySelectorAll("input, select, button").forEach((node) => { node.disabled = busy; });
    ctx.byId("project-recovery-list").querySelectorAll("button").forEach((node) => { node.disabled = busy; });
    const executeButton = ctx.byId("recovery-execute");
    if (executeButton) executeButton.disabled = busy || !active || !active.plan.can_recover || active.completed;
  }

  function parameterTable(ctx, params) {
    const valueText = (value) => {
      if (value === null || value === undefined) return "—";
      if (typeof value === "boolean") return text(ctx, value ? "preflight_status_yes" : "preflight_status_no");
      if (Array.isArray(value)) return value.map(valueText).join(", ");
      if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${key}: ${valueText(item)}`).join("; ");
      return String(value);
    };
    const rows = Object.entries(params || {}).filter(([key]) => !key.startsWith("_") && !["run_id", "output_dir"].includes(key));
    return `<div class="project-table-scroll"><table class="project-data-table"><tbody>${rows.map(([key, value]) => `<tr><th>${escape(ctx, wb().parameterLabel(ctx, key))}</th><td>${escape(ctx, valueText(value))}</td></tr>`).join("")}</tbody></table></div>`;
  }

  async function refresh(ctx) {
    const revision = ++listRevision;
    try {
      // Recovery is global: queued requests may not have created a project yet.
      const result = await read(await ctx.recoveryApi.list());
      if (revision !== listRevision) return;
      const items = result.items || [];
      const button = ctx.byId("project-recovery-btn");
      button.textContent = text(ctx, "recovery_entry", { count: items.length });
      const list = ctx.byId("project-recovery-list");
      list.innerHTML = items.length ? items.map((item, index) => `<div class="project-source-check"><strong>${escape(ctx, item.project_name || item.project_id || text(ctx, "recovery_no_project"))}</strong><span>${escape(ctx, item.created_at || "")} · ${escape(ctx, short(item.run_id || item.job_id))}</span><span class="panel-sub">${escape(ctx, text(ctx, item.requires_owner_confirmation ? "recovery_owner_unknown" : "recovery_interrupted"))}</span><button class="btn mini recovery-select" data-recovery-index="${index}" type="button">${escape(ctx, text(ctx, "recovery_review"))}</button></div>`).join("") : `<p class="panel-sub">${escape(ctx, text(ctx, "recovery_empty"))}</p>`;
      list.querySelectorAll(".recovery-select").forEach((button) => {
        button.disabled = Boolean(active && (active.submitting || active.jobId));
        button.onclick = () => select(ctx, items[Number(button.dataset.recoveryIndex)]);
      });
    } catch (error) {
      if (revision === listRevision) ctx.byId("project-recovery-status").textContent = error.message;
    }
  }

  async function open(ctx) {
    wb().showDialog(ctx, "project-recovery-dialog");
    await refresh(ctx);
  }

  function payloadFor(ctx, state) {
    const payload = { recovery_id: state.item.recovery_id };
    if (state.plan.preflight_token) payload.preflight_token = state.plan.preflight_token;
    const confirm = ctx.byId("recovery-owner-confirm");
    if (confirm && confirm.checked) payload.confirm_owner_stopped = true;
    const changed = ctx.byId("recovery-changed-confirm");
    if (changed && changed.checked) payload.allow_changed_sources = true;
    const paths = { ...(state.sourcePaths || {}) };
    ctx.byId("project-recovery-content").querySelectorAll(".recovery-source-path").forEach((input) => {
      const source = state.plan.source_checks[Number(input.dataset.sourceIndex)];
      const value = input.value.trim();
      if (value && value !== source.path) paths[source.path] = value;
      else delete paths[source.path];
    });
    if (Object.keys(paths).length) payload.source_paths = paths;
    return payload;
  }

  function renderPlan(ctx, state, plan, payload = {}) {
    state.plan = plan;
    state.sourcePaths = payload.source_paths || {};
    const notes = [...(plan.issues || []), ...(plan.warnings || [])];
    const sources = (plan.source_checks || []).map((source, index) => {
      const key = ["missing", "changed", "unchanged", "current", "unverified"].includes(source.state) ? source.state : "unverified";
      return `<label class="project-source-check"><strong>${escape(ctx, source.file_name || source.path)}</strong><span class="panel-sub">${escape(ctx, text(ctx, `recovery_source_${key}`))}</span><span>${escape(ctx, text(ctx, "recovery_source_path"))}</span><input class="recovery-source-path" data-source-index="${index}" value="${escape(ctx, state.sourcePaths[source.path] || source.resolved_path || source.path)}"></label>`;
    }).join("");
    ctx.byId("project-recovery-content").innerHTML = `<p>${escape(ctx, text(ctx, "recovery_preserve"))}</p>${state.item.requires_owner_confirmation ? `<label class="compact-check"><input id="recovery-owner-confirm" type="checkbox" ${payload.confirm_owner_stopped ? "checked" : ""}><span>${escape(ctx, text(ctx, "recovery_owner_confirm"))}</span></label>` : ""}${notes.length ? `<ul class="project-notices">${notes.map((note) => `<li>${escape(ctx, note)}</li>`).join("")}</ul>` : ""}${sources ? `<details open><summary>${escape(ctx, text(ctx, "recovery_sources"))} (${(plan.source_checks || []).length})</summary>${sources}</details>` : ""}${plan.params ? `<details><summary>${escape(ctx, text(ctx, "recovery_parameters"))}</summary>${parameterTable(ctx, plan.params)}</details>` : ""}${plan.requires_changed_confirmation || payload.allow_changed_sources ? `<label class="compact-check"><input id="recovery-changed-confirm" type="checkbox" ${payload.allow_changed_sources ? "checked" : ""}><span>${escape(ctx, text(ctx, "recovery_changed_confirm"))}</span></label>` : ""}<div class="mini-actions"><button id="recovery-check" class="btn mini" type="button">${escape(ctx, text(ctx, "recovery_check"))}</button><button id="recovery-execute" class="btn primary" type="button" ${plan.can_recover ? "" : "disabled"}>${escape(ctx, text(ctx, "recovery_execute"))}</button></div>`;
    const content = ctx.byId("project-recovery-content");
    const invalidate = () => {
      if (active !== state || state.submitting || state.jobId) return;
      state.revision += 1;
      ctx.byId("recovery-execute").disabled = true;
    };
    content.oninput = invalidate;
    content.onchange = invalidate;
    ctx.byId("recovery-check").onclick = () => check(ctx);
    ctx.byId("recovery-execute").onclick = () => execute(ctx);
    state.plannedPayload = JSON.stringify(payloadFor(ctx, state));
  }

  async function select(ctx, item) {
    if (active && (active.submitting || active.jobId)) return;
    const state = { item, plan: {}, sourcePaths: {}, revision: 0, jobId: "", submitting: false };
    active = state;
    renderPlan(ctx, state, { can_recover: false, issues: [], warnings: [], source_checks: [] });
    await check(ctx);
  }

  async function check(ctx) {
    const state = active;
    if (!state || state.submitting || state.jobId) return;
    const revision = ++state.revision;
    const status = ctx.byId("project-recovery-status");
    ctx.byId("recovery-execute").disabled = true;
    try {
      const payload = payloadFor(ctx, state);
      status.textContent = text(ctx, "recovery_checking");
      const result = await read(await ctx.recoveryApi.plan(payload));
      if (active !== state || revision !== state.revision) return;
      renderPlan(ctx, state, result.plan, payload);
      status.textContent = text(ctx, result.plan.can_recover ? "recovery_ready" : "recovery_needs_review");
    } catch (error) {
      if (active === state && revision === state.revision) status.textContent = error.message;
    }
  }

  async function execute(ctx) {
    const state = active;
    if (!state || state.submitting || state.jobId || ctx.byId("recovery-execute").disabled) return;
    const status = ctx.byId("project-recovery-status");
    const payload = payloadFor(ctx, state);
    if (JSON.stringify(payload) !== state.plannedPayload) {
      status.textContent = text(ctx, "recovery_recheck");
      ctx.byId("recovery-execute").disabled = true;
      return;
    }
    state.submitting = true;
    ctx.byId("recovery-execute").disabled = true;
    setBusy(ctx, true);
    try {
      const result = await read(await ctx.recoveryApi.resume(payload));
      if (!result.job_id) throw new Error(text(ctx, "recovery_failed"));
      state.jobId = result.job_id;
      let job = result.job || { status: "queued" };
      while (["queued", "running"].includes(job.status)) {
        status.textContent = `${text(ctx, "recovery_running")} ${job.current_item || ""}`;
        await new Promise((resolve) => setTimeout(resolve, 500));
        job = (await read(await ctx.processingApi.getProcessJob(state.jobId))).job;
      }
      if (job.status !== "succeeded") throw new Error(job.error || text(ctx, "recovery_failed"));
      state.completed = true;
      status.textContent = text(ctx, "recovery_done");
      if (typeof ctx.onRecoveryCompleted === "function") await ctx.onRecoveryCompleted(job);
      else {
        await ctx.loadStatsAndHistory();
        if (ctx.getSelectedProjectId()) await ctx.loadSelectedProjectDetail();
      }
    } catch (error) {
      status.textContent = error.message;
      if (error.plan) renderPlan(ctx, state, error.plan, payload);
    } finally {
      state.jobId = "";
      state.submitting = false;
      if (active === state) setBusy(ctx, false);
      await refresh(ctx);
    }
  }

  function init(provider) {
    const ctx = provider();
    ctx.byId("project-recovery-btn").addEventListener("click", () => open(provider()));
    ctx.byId("project-recovery-close").addEventListener("click", () => wb().closeDialog(provider(), "project-recovery-dialog"));
    // Startup only discovers recoverable work; it never launches it or opens a modal.
    refresh(ctx);
  }

  window.ElectrochemProjectRecovery = { init, refresh, open, select, check, execute, payloadFor };
})();
