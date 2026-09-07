(function () {
  "use strict";
  const kinds = new Set(["parameter_changes", "compare_records", "replay_run", "report_records", "open_results"]);
  const cards = new Map();
  let hooks = {}, active = null, revision = 0;
  const text = (key) => typeof hooks.t === "function" ? hooks.t(key) : key;
  const escape = (value) => typeof hooks.escapeHtml === "function" ? hooks.escapeHtml(String(value ?? "")) : String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const stable = (value) => JSON.stringify(value, (_key, item) => item && typeof item === "object" && !Array.isArray(item) ? Object.keys(item).sort().reduce((out, key) => { out[key] = item[key]; return out; }, {}) : item);
  const byId = (id) => document.getElementById(id);
  const valueText = (value) => value === null || value === undefined ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);

  function valid(card) {
    if (!card || card.schema_version !== 1 || typeof card.id !== "string" || !kinds.has(card.kind) || !Array.isArray(card.record_keys)) return false;
    if (card.kind === "parameter_changes") return card.context_guard && Array.isArray(card.changes) && card.changes.length > 0 && card.changes.every((change) => change && typeof change.key === "string" && !change.key.startsWith("_") && !/file|path|directory|folder|prefix|suffix|match/.test(change.key) && !["recursive_scan", "output_run_dir_enabled"].includes(change.key));
    if (typeof card.project_id !== "string" || !card.project_id) return false;
    if (card.record_keys.some((key) => typeof key !== "string" || !key) || new Set(card.record_keys).size !== card.record_keys.length) return false;
    if (card.kind === "compare_records" && card.record_keys.length !== 2) return false;
    if (card.kind === "report_records" && (!card.record_keys.length || card.record_keys.length > 200)) return false;
    if (["replay_run", "open_results"].includes(card.kind) && (typeof card.run_id !== "string" || !card.run_id)) return false;
    return card.kind !== "replay_run" || card.record_keys.length <= 1;
  }

  function renderCards(options) {
    const opts = options || {};
    if (opts.role !== "agent") return "";
    const values = opts.metadata && Array.isArray(opts.metadata.action_cards) ? opts.metadata.action_cards : [];
    return values.filter(valid).map((card) => {
      cards.set(card.id, clone(card));
      return `<section class="assistant-action-card" data-action-kind="${escape(card.kind)}"><strong>${escape(text(`assistant_action_${card.kind}`))}</strong>${card.project_name ? `<p>${escape(card.project_name)}</p>` : ""}${card.record_keys.length ? `<p>${escape(text("assistant_action_records"))}: ${card.record_keys.length}</p>` : ""}${card.kind === "parameter_changes" ? `<p>${card.changes.map((change) => escape(change.label || change.key)).join(" · ")}</p>` : ""}<button type="button" class="btn mini assistant-action-button" data-assistant-action-id="${escape(card.id)}">${escape(text("assistant_action_preview"))}</button></section>`;
    }).join("");
  }

  function ensureDialog() {
    if (!byId("assistant-action-dialog")) {
      const dialog = document.createElement("dialog");
      dialog.id = "assistant-action-dialog";
      dialog.className = "project-dialog";
      dialog.innerHTML = '<h3 id="assistant-action-title"></h3><div id="assistant-action-content"></div><p id="assistant-action-status" role="status"></p><div class="mini-actions"><button id="assistant-action-confirm" class="btn primary" type="button"></button><button id="assistant-action-close" class="btn" type="button"></button></div>';
      document.body.appendChild(dialog);
    }
    const dialog = byId("assistant-action-dialog");
    byId("assistant-action-close").textContent = text("assistant_action_close");
    byId("assistant-action-close").onclick = () => { if (!active || !active.busy) dialog.close(); };
    dialog.onclose = () => { revision += 1; active = null; };
    dialog.oncancel = (event) => { if (active && active.busy) event.preventDefault(); };
    byId("assistant-action-confirm").onclick = () => confirm();
    return dialog;
  }

  async function read(path) {
    const response = await fetch(path, { method: "GET", cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.status !== "success") throw new Error(data.message || text("assistant_action_invalid"));
    return data;
  }

  function guardMatches(card, context) {
    const guard = Object.fromEntries(["parameters", "data_types", "data_source", "action_context"].map((key) => [key, context && context[key] !== undefined ? context[key] : null]));
    return stable(guard) === stable(card.context_guard);
  }

  async function validateCurrent(card) {
    if (!valid(card)) throw new Error(text("assistant_action_invalid"));
    if (card.kind === "parameter_changes") {
      const current = await hooks.getContext();
      if (!guardMatches(card, current)) throw new Error(text("assistant_action_stale"));
      return;
    }
    if (card.run_id) {
      const data = await read(`/api/v1/runs/${encodeURIComponent(card.run_id)}`);
      if (!data.run || data.run.project_id !== card.project_id) throw new Error(text("assistant_action_project_mismatch"));
    }
    await Promise.all(card.record_keys.map(async (key) => {
      const data = await read(`/api/v1/history/${encodeURIComponent(key)}`);
      const record = data.record;
      if (!record || record.project_id !== card.project_id || card.run_id && record.run_id !== card.run_id) throw new Error(text("assistant_action_project_mismatch"));
    }));
  }

  function previewBody(card) {
    const rows = card.kind === "parameter_changes" ? `<div class="project-table-scroll"><table class="project-data-table"><thead><tr>${["parameter", "before", "after", "reason"].map((key) => `<th>${escape(text(`assistant_action_${key}`))}</th>`).join("")}</tr></thead><tbody>${card.changes.map((change) => `<tr><td>${escape(change.label || change.key)}</td><td>${escape(valueText(change.before))}</td><td>${escape(valueText(change.after))}</td><td>${escape(change.reason)}</td></tr>`).join("")}</tbody></table></div>` : `<p>${escape(card.project_name || card.project_id)}</p>${card.record_keys.length ? `<p>${escape(text("assistant_action_records"))}: ${card.record_keys.length}</p>` : ""}${card.run_id ? `<p>${escape(text("assistant_action_run"))}: ${escape(card.run_id)}</p>` : ""}${(card.records || []).map((record) => `<p>${escape(record.file_name || record.sample_name)} · ${escape(record.timestamp)}</p>`).join("")}`;
    const preview = card.preview || {};
    const notices = [...(preview.issues || []), ...(preview.warnings || [])];
    const changes = preview.parameter_changes || [];
    return `${rows}${changes.length ? `<ul>${changes.map((change) => `<li>${escape(change.key)}: ${escape(valueText(change.before))} → ${escape(valueText(change.after))}</li>`).join("")}</ul>` : ""}${notices.length ? `<ul>${notices.map((notice) => `<li>${escape(notice)}</li>`).join("")}</ul>` : ""}<p class="panel-sub">${escape(text(card.kind === "parameter_changes" ? "assistant_action_preflight" : "assistant_action_not_executed"))}</p>`;
  }

  async function preview(card) {
    if (active && active.busy) return;
    const dialog = ensureDialog();
    const attempt = { card: clone(card), revision: ++revision, busy: false };
    active = attempt;
    byId("assistant-action-title").textContent = text(`assistant_action_${card.kind}`);
    byId("assistant-action-content").innerHTML = previewBody(card);
    byId("assistant-action-status").textContent = text("assistant_action_loading");
    const button = byId("assistant-action-confirm");
    button.disabled = true;
    button.textContent = text(card.kind === "parameter_changes" ? "assistant_action_apply" : "assistant_action_continue");
    if (!dialog.open) dialog.showModal();
    try {
      await validateCurrent(card);
      if (active !== attempt || revision !== attempt.revision) return;
      byId("assistant-action-status").textContent = "";
      button.disabled = false;
    } catch (error) { if (active === attempt) byId("assistant-action-status").textContent = error.message; }
  }

  async function confirm() {
    const attempt = active;
    const button = byId("assistant-action-confirm");
    if (!attempt || attempt.busy || button.disabled) return;
    attempt.busy = true;
    button.disabled = true;
    byId("assistant-action-close").disabled = true;
    try {
      await validateCurrent(attempt.card);
      if (active !== attempt) return;
      const callback = { parameter_changes: "applyParameters", compare_records: "openComparison", replay_run: "openReplay", report_records: "openReport", open_results: "openResults" }[attempt.card.kind];
      if (typeof hooks[callback] !== "function") throw new Error(text("assistant_action_invalid"));
      await hooks[callback](clone(attempt.card));
      byId("assistant-action-status").textContent = text("assistant_action_ready");
      byId("assistant-action-dialog").close();
    } catch (error) { if (active === attempt) byId("assistant-action-status").textContent = error.message; }
    finally {
      attempt.busy = false;
      byId("assistant-action-close").disabled = false;
      // A failed proposal must be reviewed again; double clicks never retry writes.
    }
  }

  function bind(container) {
    if (!container) return;
    const visible = new Set(Array.from(container.querySelectorAll("[data-assistant-action-id]")).map((button) => button.dataset.assistantActionId));
    for (const id of cards.keys()) if (!visible.has(id)) cards.delete(id);
    if (container.dataset.assistantActionsBound === "true") return;
    container.dataset.assistantActionsBound = "true";
    container.addEventListener("click", (event) => {
      const button = event.target.closest("[data-assistant-action-id]");
      if (!button || !container.contains(button)) return;
      const card = cards.get(button.dataset.assistantActionId);
      if (card) preview(card);
    });
  }

  window.ElectrochemAssistantActions = { init: (options) => { hooks = options || {}; }, renderCards, bind, preview, guardMatches };
})();
