(function () {
  "use strict";

  let provider;
  let revision = 0;
  let timer;
  let page = 0;
  let focusedId = "";
  let lastSignature = "";
  const busy = new Set();
  const PAGE_SIZE = 20;
  const el = (id) => document.getElementById(id);
  const dialog = () => el("task-center-dialog");
  const read = async (response) => {
    const data = await response.json();
    if (!response.ok || data.status !== "success") throw new Error(data.message || `HTTP ${response.status}`);
    return data;
  };

  function stageText(task, t) {
    const raw = String(task.current_item || "");
    const stages = { preflight: "task_stage_preflight", complete: "task_status_succeeded", failed: "task_status_failed", cancelled: "task_status_cancelled", "preparing AI request": "task_stage_preparing" };
    return stages[raw] ? t(stages[raw]) : raw;
  }

  function renderTask(ctx, task) {
    const t = ctx.t;
    const esc = ctx.escapeHtml;
    const ref = task.reference || {};
    const active = ["queued", "running"].includes(task.status);
    const title = ref.project_name || ref.conversation_title || t(task.kind === "agent" ? "task_kind_agent" : "task_kind_process");
    const canOpen = ref.project_id || ref.conversation_id;
    const current = Math.max(0, Number(task.progress_current) || 0);
    const total = Math.max(0, Number(task.progress_total) || 0);
    const measurable = task.kind === "process" && task.status === "running" && total > 0;
    const progress = active ? `<div class="task-progress"><progress ${measurable ? `value="${Math.min(current, total)}" max="${total}"` : ""} aria-label="${esc(t("task_progress"))}"></progress>${measurable ? `<span>${current} / ${total}</span>` : ""}</div>` : "";
    const time = task.started_at || task.created_at || "";
    const status = t(`task_status_${task.status}`);
    return `<article class="task-card${task.job_id === focusedId ? " selected" : ""}" data-task-id="${esc(task.job_id)}"><div class="task-card-head"><strong>${esc(title)}</strong><span class="task-status ${esc(task.status)}">${esc(status)}</span></div><div class="task-meta">${esc(t(task.kind === "agent" ? "task_kind_agent" : "task_kind_process"))} · ${esc(time.replace("T", " ").slice(0, 19))} · ${esc(task.job_id.slice(0, 8))}</div>${progress}<p class="task-stage">${esc(task.cancel_requested && active ? t("task_cancelling") : stageText(task, t))}</p>${task.error ? `<details class="task-error"><summary>${esc(t("task_error_details"))}</summary><p>${esc(task.error)}</p></details>` : ""}<div class="mini-actions">${canOpen ? `<button class="btn mini" type="button" data-task-open="${esc(task.job_id)}">${esc(t(ref.conversation_id ? "task_open_conversation" : "task_open_results"))}</button>` : ""}${task.can_cancel ? `<button class="btn mini" type="button" data-task-cancel="${esc(task.job_id)}" ${busy.has(task.job_id) ? "disabled" : ""}>${esc(t("task_cancel"))}</button>` : ""}${task.status === "interrupted" && task.kind === "process" ? `<button class="btn mini" type="button" data-task-recover="${esc(task.job_id)}">${esc(t("task_open_recovery"))}</button>` : ""}</div></article>`;
  }

  function schedule() {
    clearTimeout(timer);
    if (!provider || document.hidden) return;
    timer = setTimeout(() => refresh(), dialog().open ? 2000 : 15000);
  }

  async function refresh() {
    if (!provider) return;
    const ctx = provider();
    const ticket = ++revision;
    const visible = dialog().open;
    const query = new URLSearchParams({ kind: el("task-kind").value || "all", status: el("task-status").value || "all", limit: String(visible ? PAGE_SIZE : 1), offset: String(visible ? page * PAGE_SIZE : 0) });
    try {
      const data = await read(await ctx.apiFetch(`/api/v1/tasks?${query}`));
      if (ticket !== revision) return;
      el("task-center-label").textContent = ctx.t("task_entry").replace("{count}", String(data.active_count));
      if (visible) {
        if (page && !data.items.length) { page = Math.max(0, Math.ceil(data.total / PAGE_SIZE) - 1); return refresh(); }
        const signature = JSON.stringify([data.items, ctx.t("task_title"), focusedId, [...busy]]);
        if (signature !== lastSignature) {
          const activeElement = document.activeElement;
          const activeCard = activeElement && activeElement.closest(".task-card");
          const focus = activeCard ? { id: activeCard.dataset.taskId, index: [...activeCard.querySelectorAll("button, summary")].indexOf(activeElement) } : null;
          const opened = new Set([...el("task-list").querySelectorAll(".task-card:has(details[open])")].map((node) => node.dataset.taskId));
          el("task-list").innerHTML = data.items.length ? data.items.map((task) => renderTask(ctx, task)).join("") : `<p class="placeholder">${ctx.escapeHtml(ctx.t("task_empty"))}</p>`;
          el("task-list").querySelectorAll(".task-card").forEach((node) => { if (opened.has(node.dataset.taskId)) { const details = node.querySelector("details"); if (details) details.open = true; } });
          lastSignature = signature;
          bindItems(ctx, data.items);
          if (focus) {
            const card = [...el("task-list").querySelectorAll(".task-card")].find((node) => node.dataset.taskId === focus.id);
            const target = card && card.querySelectorAll("button, summary")[focus.index];
            if (target && !target.disabled) target.focus({ preventScroll: true });
          }
        }
        el("task-page-summary").textContent = ctx.t("task_page").replace("{page}", String(page + 1)).replace("{total}", String(data.total));
        el("task-prev").disabled = page === 0;
        el("task-next").disabled = !data.has_more;
        el("task-panel-status").textContent = "";
      }
    } catch (error) {
      if (ticket === revision) {
        if (visible) el("task-panel-status").textContent = `${ctx.t("task_load_failed")}: ${error.message}`;
        else el("task-center-label").textContent = ctx.t("task_title");
      }
    } finally { if (ticket === revision) schedule(); }
  }

  function bindItems(ctx, tasks) {
    const lookup = new Map(tasks.map((task) => [task.job_id, task]));
    el("task-list").querySelectorAll("[data-task-open]").forEach((button) => {
      button.onclick = async () => {
        button.disabled = true;
        try { await ctx.openTask(lookup.get(button.dataset.taskOpen)); dialog().close(); }
        catch (error) { el("task-panel-status").textContent = error.message; }
        finally { button.disabled = false; }
      };
    });
    el("task-list").querySelectorAll("[data-task-cancel]").forEach((button) => {
      button.onclick = async () => {
        const id = button.dataset.taskCancel;
        if (busy.has(id)) return;
        busy.add(id); button.disabled = true;
        try {
          await read(await ctx.apiFetch(`/api/v1/tasks/${encodeURIComponent(id)}/cancel`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }));
          await refresh();
        } catch (error) { el("task-panel-status").textContent = error.message; }
        finally { busy.delete(id); button.disabled = false; lastSignature = ""; }
      };
    });
    el("task-list").querySelectorAll("[data-task-recover]").forEach((button) => {
      button.onclick = () => { dialog().close(); ctx.openRecovery(); };
    });
  }

  async function open(jobId = "") {
    focusedId = String(jobId || "");
    page = 0; lastSignature = "";
    if (jobId) { el("task-kind").value = "all"; el("task-status").value = "all"; }
    if (!dialog().open) dialog().showModal();
    await refresh();
  }

  function init(contextProvider) {
    provider = contextProvider;
    el("task-center-btn").onclick = () => open();
    el("task-center-close").onclick = () => dialog().close();
    el("task-refresh").onclick = () => refresh();
    ["task-kind", "task-status"].forEach((id) => { el(id).onchange = () => { page = 0; lastSignature = ""; refresh(); }; });
    el("task-prev").onclick = () => { page = Math.max(0, page - 1); refresh(); };
    el("task-next").onclick = () => { page += 1; refresh(); };
    dialog().addEventListener("close", () => { revision += 1; schedule(); });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); else clearTimeout(timer); });
    window.addEventListener("electrochem:tasks-changed", () => refresh());
    window.addEventListener("pagehide", () => clearTimeout(timer));
    refresh();
  }

  window.ElectrochemTaskCenter = { init, open, refresh, renderTask, stageText };
})();
