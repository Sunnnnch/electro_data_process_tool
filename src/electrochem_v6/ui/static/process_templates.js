(function () {
  "use strict";

  const EXTRA_VALUE_IDS = [
    "pro-fe-method-id",
    "pro-fe-axis-unit",
    "pro-fe-standard-name",
    "pro-fe-standard-position",
    "pro-fe-standard-nuclei",
    "pro-fe-standard-polarity",
    "pro-fe-standard-concentration",
    "pro-fe-standard-volume",
    "pro-fe-electrolyte-volume",
    "pro-fe-aliquot-volume",
  ];
  let lastApplyWarnings = [];

  function currentSchemaVersion() {
    const schemaClient = window.ElectrochemProcessingSchema;
    if (!schemaClient) return "";
    if (typeof schemaClient.getVersion === "function") {
      return String(schemaClient.getVersion() || "");
    }
    const schema = typeof schemaClient.getCached === "function" ? schemaClient.getCached() : null;
    return String(schema && schema.schema_version || "");
  }

  function templateControlIds() {
    const schemaClient = window.ElectrochemProcessingSchema;
    const schemaIds = schemaClient && typeof schemaClient.controlIds === "function"
      ? schemaClient.controlIds()
      : [];
    return Array.from(new Set([...schemaIds, ...EXTRA_VALUE_IDS]));
  }

  function getItems(ctx) {
    return typeof ctx.getTemplateItems === "function" ? ctx.getTemplateItems() : [];
  }

  function getCurrentState(ctx) {
    const state = {
      schema_version: currentSchemaVersion(),
      selected_types: ctx.getSelectedProcessTypes(),
      values: {},
      checks: {},
    };
    templateControlIds().forEach((id) => {
      const el = ctx.byId(id);
      if (!el) return;
      if (el.type === "checkbox") state.checks[id] = Boolean(el.checked);
      else state.values[id] = el.value;
    });
    if (typeof ctx.getCoupledPeakMethodState === "function") {
      state.coupled_peak_method = ctx.getCoupledPeakMethodState();
    }
    return state;
  }

  function canApplyValue(el, value) {
    const raw = String(value ?? "");
    if (el.tagName === "SELECT") {
      return Array.from(el.options || []).some((option) => String(option.value) === raw);
    }
    if (raw && el.dataset && el.dataset.schemaParam) {
      const min = el.getAttribute("min");
      const max = el.getAttribute("max");
      if (min !== null || max !== null) {
        const numeric = Number(raw);
        if (!Number.isFinite(numeric)) return false;
        if (min !== null && numeric < Number(min)) return false;
        if (max !== null && numeric > Number(max)) return false;
      }
    }
    return true;
  }

  function applyState(ctx, state) {
    if (!state || typeof state !== "object") return false;
    lastApplyWarnings = [];
    const currentVersion = currentSchemaVersion();
    const savedVersion = String(state.schema_version || "");
    if (!savedVersion || (currentVersion && savedVersion !== currentVersion)) {
      lastApplyWarnings.push("schema_version");
    }
    const knownIds = new Set(templateControlIds());
    const availableTypes = new Set(
      Array.from(document.querySelectorAll(".proc-type-check"))
        .map((el) => String(el.value || "").toUpperCase())
        .filter(Boolean)
    );
    const selected = Array.isArray(state.selected_types) ? state.selected_types.map((item) => String(item).toUpperCase()) : [];
    if (selected.some((item) => !availableTypes.has(item))) {
      lastApplyWarnings.push("selected_types");
    }
    document.querySelectorAll(".proc-type-check").forEach((el) => {
      el.checked = selected.includes(String(el.value || "").toUpperCase());
    });
    if (!ctx.getSelectedProcessTypes().length) {
      const defaultType = document.querySelector('.proc-type-check[value="LSV"]');
      if (defaultType) defaultType.checked = true;
    }
    const values = state.values && typeof state.values === "object" ? { ...state.values } : {};
    Object.keys(values).forEach((id) => {
      if (!knownIds.has(id)) {
        lastApplyWarnings.push(`value:${id}`);
        return;
      }
      const el = ctx.byId(id);
      if (el && typeof values[id] !== "undefined") {
        if (!canApplyValue(el, values[id])) {
          lastApplyWarnings.push(`value:${id}`);
          return;
        }
        el.value = String(values[id]);
      }
    });
    const checks = state.checks && typeof state.checks === "object" ? state.checks : {};
    Object.keys(checks).forEach((id) => {
      if (!knownIds.has(id)) {
        lastApplyWarnings.push(`check:${id}`);
        return;
      }
      const el = ctx.byId(id);
      if (el && el.type === "checkbox") el.checked = Boolean(checks[id]);
      else if (el) lastApplyWarnings.push(`check:${id}`);
    });
    if (state.coupled_peak_method && typeof ctx.applyCoupledPeakMethodState === "function") {
      ctx.applyCoupledPeakMethodState(state.coupled_peak_method);
    }
    if (typeof ctx.onTemplateApplied === "function") {
      ctx.onTemplateApplied();
    }
    lastApplyWarnings = Array.from(new Set(lastApplyWarnings));
    return true;
  }

  function getLastApplyWarnings() {
    return [...lastApplyWarnings];
  }

  function renderOptions(ctx) {
    const select = ctx.byId("tmpl-select");
    if (!select) return "";
    const prev = select.value;
    const items = getItems(ctx);
    select.innerHTML = "";
    if (!Array.isArray(items) || !items.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = ctx.t("template_none");
      select.appendChild(opt);
      select.value = "";
      return "";
    }
    items.forEach((item) => {
      const opt = document.createElement("option");
      opt.value = String(item.name || "");
      const suffix = item.builtin ? ` [${ctx.t("template_builtin_tag")}]` : "";
      opt.textContent = `${item.name || ""}${suffix}`;
      select.appendChild(opt);
    });
    if (prev && items.some((item) => item.name === prev)) {
      select.value = prev;
    }
    return select.value;
  }

  async function loadTemplates(ctx) {
    try {
      const resp = await ctx.processingApi.listTemplates();
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || ctx.t("template_load_failed"));
      }
      const items = Array.isArray(data.templates) ? data.templates : [];
      ctx.setTemplateItems(items);
      renderOptions(ctx);
      ctx.setTemplateStatus("");
      return items;
    } catch (err) {
      ctx.setTemplateItems([]);
      renderOptions(ctx);
      ctx.setTemplateStatus(`${ctx.t("template_load_failed")}: ${err.message}`);
      return [];
    }
  }

  async function saveTemplate(ctx, overwrite = false) {
    const select = ctx.byId("tmpl-select");
    const name = ctx.textValue("tmpl-name") || (select ? select.value : "");
    if (!name) {
      ctx.setTemplateStatus(ctx.t("template_name_required"));
      return null;
    }
    try {
      const resp = await ctx.processingApi.saveTemplate({
        name,
        state: getCurrentState(ctx),
        overwrite,
      });
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        if (data.code === "already_exists" && !overwrite && ctx.confirm(ctx.t("template_confirm_overwrite"))) {
          return saveTemplate(ctx, true);
        }
        throw new Error(data.message || ctx.t("template_save_failed"));
      }
      await loadTemplates(ctx);
      const nameEl = ctx.byId("tmpl-name");
      if (nameEl) nameEl.value = name;
      if (select) select.value = name;
      ctx.setTemplateStatus(ctx.t("template_saved"));
      return data;
    } catch (err) {
      const msg = String(err && err.message ? err.message : "");
      if (msg.toLowerCase().includes("not found")) {
        ctx.setTemplateStatus(`${ctx.t("template_save_failed")}: ${msg}. ${ctx.t("template_restart_hint")}`);
      } else {
        ctx.setTemplateStatus(`${ctx.t("template_save_failed")}: ${msg}`);
      }
      return null;
    }
  }

  function loadSelectedTemplate(ctx) {
    const select = ctx.byId("tmpl-select");
    const name = select ? select.value : "";
    if (!name) return null;
    const found = getItems(ctx).find((item) => item.name === name);
    if (!found) {
      ctx.setTemplateStatus(ctx.t("template_load_failed"));
      return null;
    }
    applyState(ctx, found.state || {});
    const nameEl = ctx.byId("tmpl-name");
    if (nameEl) nameEl.value = name;
    const warnings = getLastApplyWarnings();
    ctx.setTemplateStatus(
      warnings.length
        ? `${ctx.t("template_loaded_with_warnings")} (${warnings.length})`
        : ctx.t("template_loaded")
    );
    return found;
  }

  async function deleteSelectedTemplate(ctx) {
    const select = ctx.byId("tmpl-select");
    const name = select ? select.value : "";
    if (!name) return null;
    const found = getItems(ctx).find((item) => item.name === name);
    if (found && found.builtin) {
      ctx.setTemplateStatus(ctx.t("template_builtin_immutable"));
      return null;
    }
    if (!ctx.confirm(ctx.t("template_confirm_delete"))) return null;
    try {
      const resp = await ctx.processingApi.deleteTemplate(name);
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || ctx.t("template_delete_failed"));
      }
      await loadTemplates(ctx);
      const nameEl = ctx.byId("tmpl-name");
      if (nameEl) nameEl.value = "";
      ctx.setTemplateStatus(ctx.t("template_deleted"));
      return data;
    } catch (err) {
      ctx.setTemplateStatus(`${ctx.t("template_delete_failed")}: ${err.message}`);
      return null;
    }
  }

  window.ElectrochemProcessTemplates = {
    applyState,
    deleteSelectedTemplate,
    getCurrentState,
    getLastApplyWarnings,
    loadSelectedTemplate,
    loadTemplates,
    renderOptions,
    saveTemplate,
    templateControlIds,
  };
})();
