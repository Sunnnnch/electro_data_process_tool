(function () {
  "use strict";

  const palette = [
    ["#155e45", "project_color_green"], ["#2563eb", "project_color_blue"],
    ["#0891b2", "project_color_cyan"], ["#7c3aed", "project_color_purple"],
    ["#d97706", "project_color_orange"], ["#db2777", "project_color_pink"],
  ];
  let pendingApplication = null;
  let previewRevision = 0;

  function parameterState(template) {
    const state = JSON.parse(JSON.stringify(template.state || {}));
    // File selections belong to the current experiment, including auxiliary inputs.
    for (const id of ["pro-coupled-products-file", "pro-coupled-peak-method-file", "pro-lsv-ir-eis-file"]) {
      if (state.values) delete state.values[id];
    }
    return state;
  }

  function setColor(ctx, prefix, value) {
    const field = ctx.byId(`${prefix}-color`);
    const group = ctx.byId(`${prefix}-colors`);
    if (!field || !group) return;
    const raw = String(value || "");
    const normalized = /^#[0-9a-f]{3}$/i.test(raw) ? `#${[...raw.slice(1)].map((part) => part + part).join("")}` : raw;
    field.value = normalized;
    group.querySelectorAll("[data-color]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.color.toLowerCase() === normalized.toLowerCase()));
    });
    const custom = ctx.byId(`${prefix}-color-custom`);
    if (custom) {
      const pickerColor = /^#[0-9a-f]{4}$/i.test(normalized) ? `#${[...normalized.slice(1, 4)].map((part) => part + part).join("")}` : /^#[0-9a-f]{8}$/i.test(normalized) ? normalized.slice(0, 7) : normalized;
      custom.value = /^#[0-9a-f]{6}$/i.test(pickerColor) ? pickerColor : "#155e45";
      custom.classList.toggle("selected", Boolean(normalized) && !palette.some(([color]) => color.toLowerCase() === normalized.toLowerCase()));
    }
  }

  function renderColors(ctx, prefix) {
    const group = ctx.byId(`${prefix}-colors`);
    if (!group) return;
    const choices = prefix === "project-create" ? [["", "project_color_auto"], ...palette] : palette;
    group.innerHTML = choices.map(([color, label]) => `<button type="button" class="project-color-swatch ${color ? "" : "automatic"}" data-color="${color}" aria-pressed="false" aria-label="${ctx.escapeHtml(ctx.t(label))}" title="${ctx.escapeHtml(ctx.t(label))}" ${color ? `style="--swatch-color:${color}"` : ""}>${color ? "" : ctx.escapeHtml(ctx.t(label))}</button>`).join("") +
      `<label class="project-color-custom-label"><span>${ctx.escapeHtml(ctx.t("project_color_custom"))}</span><input id="${prefix}-color-custom" class="project-color-custom" type="color" aria-label="${ctx.escapeHtml(ctx.t("project_color_custom"))}"></label>`;
    group.querySelectorAll("[data-color]").forEach((button) => button.addEventListener("click", () => setColor(ctx, prefix, button.dataset.color)));
    ctx.byId(`${prefix}-color-custom`).addEventListener("input", (event) => setColor(ctx, prefix, event.target.value));
    setColor(ctx, prefix, ctx.byId(`${prefix}-color`).value);
  }

  function renderTemplateOptions(ctx, id, desired) {
    const select = ctx.byId(id);
    if (!select) return;
    const selected = desired === undefined ? select.value : String(desired || "");
    const items = ctx.getTemplateItems();
    select.replaceChildren();
    const add = (value, label) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      select.appendChild(option);
    };
    add("", ctx.t("project_template_none"));
    items.forEach((item) => add(item.name, item.name + (item.builtin ? ` [${ctx.t("template_builtin_tag")}]` : "")));
    if (selected && !items.some((item) => item.name === selected)) add(selected, `${selected} (${ctx.t("project_template_missing_short")})`);
    select.value = selected;
    renderTemplateHint(ctx, id);
  }

  function renderTemplateHint(ctx, id) {
    const select = ctx.byId(id);
    const hint = ctx.byId(`${id}-hint`);
    if (!select || !hint) return;
    const missing = select.value && !ctx.getTemplateItems().some((item) => item.name === select.value);
    hint.textContent = ctx.t(missing ? "project_template_missing" : "project_template_link_hint");
    hint.classList.toggle("project-create-error", Boolean(missing));
  }

  function refresh(ctx) {
    ["project-create-template", "project-edit-template"].forEach((id) => renderTemplateOptions(ctx, id));
  }

  function setEditForm(ctx, project) {
    setColor(ctx, "project-edit", project && project.color);
    renderTemplateOptions(ctx, "project-edit-template", project && project.default_template_name);
  }

  function prepareCreate(ctx) {
    setColor(ctx, "project-create", "");
    renderTemplateOptions(ctx, "project-create-template", "");
  }

  function valueLabel(ctx, id, value) {
    if (value === null || value === undefined || value === "") return ctx.t("project_template_unset");
    if (typeof value === "boolean") return ctx.t(value ? "project_template_enabled" : "project_template_disabled");
    const control = ctx.byId(id);
    if (control && control.tagName === "SELECT") {
      const option = [...control.options].find((item) => item.value === String(value));
      if (option) return option.textContent;
    }
    return typeof value === "object" ? JSON.stringify(value) : String(value);
  }

  function changes(ctx, before, after) {
    const rows = [];
    const labelFor = (id) => {
      const field = ctx.byId(id);
      const label = field && (document.querySelector(`label[for="${id}"]`) || field.closest("label"));
      return label ? label.textContent.trim() : id;
    };
    if (JSON.stringify(before.selected_types) !== JSON.stringify(after.selected_types)) rows.push([ctx.t("project_template_types"), (before.selected_types || []).join(" / "), (after.selected_types || []).join(" / ")]);
    for (const section of ["values", "checks"]) {
      Object.entries(after[section] || {}).forEach(([id, next]) => {
        const prev = (before[section] || {})[id];
        if (String(prev ?? "") !== String(next ?? "")) rows.push([labelFor(id), valueLabel(ctx, id, prev), valueLabel(ctx, id, next)]);
      });
    }
    if (after.coupled_peak_method && JSON.stringify(before.coupled_peak_method) !== JSON.stringify(after.coupled_peak_method)) rows.push([ctx.t("project_template_peak_method"), ctx.t("project_template_current"), ctx.t("project_template_replaced")]);
    return rows;
  }

  async function enterProject(ctx, project) {
    if (!project) return;
    if (!project.default_template_name) { ctx.enterProject(project); return; }
    if (ctx.isProcessing()) { ctx.setProjectStatus(ctx.t("project_template_busy")); return; }
    const revision = ++previewRevision;
    const dialog = ctx.byId("project-template-dialog");
    const content = ctx.byId("project-template-diff");
    const status = ctx.byId("project-template-status");
    const apply = ctx.byId("project-template-apply");
    pendingApplication = { project, template: null };
    ctx.byId("project-template-title").textContent = ctx.t("project_template_preview");
    ctx.byId("project-template-name").textContent = `${project.name} · ${project.default_template_name}`;
    content.replaceChildren();
    status.textContent = ctx.t("project_loading");
    apply.disabled = true;
    if (!dialog.open) dialog.showModal();
    try {
      const response = await ctx.processingApi.listTemplates();
      const data = await response.json();
      if (!response.ok || data.status !== "success") throw new Error(data.message || ctx.t("template_load_failed"));
      if (revision !== previewRevision || !dialog.open) return;
      const items = Array.isArray(data.templates) ? data.templates : [];
      ctx.setTemplateItems(items);
      const template = items.find((item) => item.name === project.default_template_name);
      if (!template) throw new Error(ctx.t("project_template_missing"));
      const before = ctx.getCurrentState();
      const state = parameterState(template);
      const rows = changes(ctx, before, state);
      const esc = ctx.escapeHtml;
      content.innerHTML = rows.length ? `<table class="project-data-table"><thead><tr><th>${esc(ctx.t("project_parameter"))}</th><th>${esc(ctx.t("project_template_current"))}</th><th>${esc(ctx.t("project_template_value"))}</th></tr></thead><tbody>${rows.map((row) => `<tr>${row.map((value) => `<td>${esc(value)}</td>`).join("")}</tr>`).join("")}</tbody></table>` : `<p>${esc(ctx.t("project_template_no_changes"))}</p>`;
      pendingApplication = { project, template: { ...template, state } };
      status.textContent = ctx.t("project_template_preview_hint");
      apply.disabled = false;
    } catch (error) {
      if (revision === previewRevision && dialog.open) status.textContent = error.message;
    }
  }

  function init(provider) {
    const ctx = provider();
    ["project-create", "project-edit"].forEach((prefix) => renderColors(ctx, prefix));
    ["project-create-template", "project-edit-template"].forEach((id) => ctx.byId(id).addEventListener("change", () => renderTemplateHint(provider(), id)));
    const dialog = ctx.byId("project-template-dialog");
    dialog.addEventListener("close", () => { previewRevision += 1; pendingApplication = null; });
    ctx.byId("project-template-cancel").addEventListener("click", () => dialog.close());
    ctx.byId("project-template-skip").addEventListener("click", () => {
      if (!pendingApplication) return;
      const project = pendingApplication.project;
      dialog.close();
      provider().enterProject(project);
    });
    ctx.byId("project-template-apply").addEventListener("click", () => {
      const live = provider();
      if (!pendingApplication || !pendingApplication.template) return;
      if (live.isProcessing()) { live.byId("project-template-status").textContent = live.t("project_template_busy"); return; }
      const { project, template } = pendingApplication;
      live.applyTemplate(template);
      dialog.close();
      live.enterProject(project);
    });
    refresh(ctx);
  }

  window.ElectrochemProjectPreferences = { init, refresh, setEditForm, prepareCreate, enterProject, renderColors, changes, setColor };
})();
