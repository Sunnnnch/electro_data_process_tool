(function () {
  "use strict";

  const labels = {
    appearance_open: ["外观", "Appearance"],
    appearance_title: ["外观设置", "Appearance settings"],
    appearance_hint: ["更改即时生效，不影响数据与计算参数。", "Changes apply immediately and leave data and analysis settings unchanged."],
    appearance_theme: ["主题", "Theme"],
    appearance_theme_lab: ["实验室浅色", "Lab Light"],
    appearance_theme_lab_hint: ["明亮清晰，适合日常分析", "A clear, light workspace for everyday analysis"],
    appearance_theme_ocean: ["专业深海", "Professional Ocean"],
    appearance_theme_ocean_hint: ["深色背景搭配浅色工作区", "A deep backdrop with light working panels"],
    appearance_theme_dark: ["高对比暗色", "High-Contrast Dark"],
    appearance_theme_dark_hint: ["适合较暗环境中的分析", "For analysis in dim surroundings"],
    appearance_theme_pixel: ["像素终端", "Pixel Terminal"],
    appearance_theme_pixel_hint: ["保留终端风格与清晰边界", "Terminal styling with distinct borders"],
    appearance_theme_system: ["跟随系统", "Follow system"],
    appearance_theme_system_hint: ["自动切换实验室浅色与高对比暗色", "Switch automatically between Lab Light and High-Contrast Dark"],
    appearance_font_size: ["界面字号", "Interface text size"],
    appearance_font_standard: ["标准 · 14 px", "Standard · 14 px"],
    appearance_font_large: ["较大 · 16 px", "Large · 16 px"],
    appearance_font_extra_large: ["最大 · 18 px", "Extra large · 18 px"],
    appearance_density: ["界面密度", "Interface density"],
    appearance_density_comfortable: ["舒适", "Comfortable"],
    appearance_density_compact: ["紧凑", "Compact"],
    appearance_grid: ["显示背景网格", "Show background grid"],
    appearance_chart_background: ["图表预览背景", "Chart preview background"],
    appearance_chart_theme: ["跟随主题", "Follow theme"],
    appearance_chart_paper: ["论文白底", "Paper white"],
    appearance_close: ["关闭", "Close"],
    appearance_reset: ["恢复默认", "Restore defaults"],
    appearance_saved: ["已应用并保存。", "Applied and saved."],
    appearance_reset_done: ["已恢复默认：实验室浅色、标准字号、舒适密度、关闭网格、图表跟随主题。", "Defaults restored: Lab Light, standard text, comfortable density, no grid, charts follow theme."],
    appearance_session_only: ["当前浏览器无法保存设置，更改仅在本次页面中生效。", "This browser cannot save preferences. Changes apply to this page only."],
  };
  Object.entries(labels).forEach(([key, values]) => {
    if (window.I18N && window.I18N.zh && window.I18N.en) {
      window.I18N.zh[key] = values[0];
      window.I18N.en[key] = values[1];
    }
  });

  let hooks = {};
  let initialized = false;
  let statusKey = "";
  let opener;
  const byId = (id) => (hooks.byId || document.getElementById.bind(document))(id);
  const theme = () => window.ElectrochemTheme;
  const text = (key) => {
    const translated = hooks.t && hooks.t(key);
    if (translated && translated !== key) return translated;
    const english = document.documentElement.lang.toLowerCase().startsWith("en");
    return labels[key] ? labels[key][english ? 1 : 0] : key;
  };
  const caption = (key, tag = "span") => `<${tag} data-i18n="${key}"></${tag}>`;

  function themeCard(name) {
    return `<label class="appearance-theme-card" data-appearance-theme="${name}">
      <input type="radio" name="appearance-theme" value="${name}" aria-labelledby="appearance-theme-${name}">
      <span class="appearance-theme-preview" data-preview-theme="${name}" aria-hidden="true">
        <span class="appearance-preview-bar"></span><span class="appearance-preview-layout"><span class="appearance-preview-side"></span><span class="appearance-preview-main"><span class="appearance-preview-line"></span><span class="appearance-preview-line"></span><span class="appearance-preview-chart"></span></span></span>
      </span><strong id="appearance-theme-${name}" data-i18n="appearance_theme_${name}"></strong>${caption(`appearance_theme_${name}_hint`, "small")}</label>`;
  }

  function ensureDialog() {
    if (byId("appearance-dialog")) return;
    const dialog = document.createElement("dialog");
    dialog.id = "appearance-dialog";
    dialog.className = "appearance-dialog";
    dialog.setAttribute("aria-labelledby", "appearance-title");
    dialog.setAttribute("aria-describedby", "appearance-hint");
    dialog.innerHTML = `<header class="appearance-header"><h2 id="appearance-title" data-i18n="appearance_title"></h2><button id="appearance-close" class="btn secondary" type="button" data-i18n="appearance_close" autofocus></button></header>
      <div class="appearance-content"><p id="appearance-hint" data-i18n="appearance_hint"></p>
      <fieldset class="appearance-themes">${caption("appearance_theme", "legend")}<div class="appearance-theme-grid">${["lab", "ocean", "dark", "pixel"].map(themeCard).join("")}</div>
      <label class="appearance-system"><input type="radio" name="appearance-theme" value="system"><span>${caption("appearance_theme_system", "strong")}${caption("appearance_theme_system_hint", "small")}</span></label>
      <select id="theme-select" class="theme-select" hidden aria-hidden="true" tabindex="-1">${["lab", "ocean", "dark", "pixel", "system"].map((name) => `<option value="${name}" data-i18n="appearance_theme_${name}"></option>`).join("")}</select></fieldset>
      <div class="appearance-controls-grid"><label class="appearance-control" for="appearance-font-size">${caption("appearance_font_size")}<select id="appearance-font-size"><option value="standard" data-i18n="appearance_font_standard"></option><option value="large" data-i18n="appearance_font_large"></option><option value="extra-large" data-i18n="appearance_font_extra_large"></option></select></label>
      <label class="appearance-control" for="appearance-density">${caption("appearance_density")}<select id="appearance-density"><option value="comfortable" data-i18n="appearance_density_comfortable"></option><option value="compact" data-i18n="appearance_density_compact"></option></select></label>
      <label class="appearance-control" for="appearance-chart-background">${caption("appearance_chart_background")}<select id="appearance-chart-background"><option value="theme" data-i18n="appearance_chart_theme"></option><option value="paper" data-i18n="appearance_chart_paper"></option></select></label>
      <label class="appearance-grid-control" for="appearance-grid"><input id="appearance-grid" type="checkbox">${caption("appearance_grid")}</label></div></div>
      <footer class="appearance-footer"><button id="appearance-reset" class="btn secondary" type="button" data-i18n="appearance_reset"></button><p id="appearance-status" role="status" aria-live="polite"></p></footer>`;
    document.body.appendChild(dialog);
    dialog.addEventListener("change", (event) => {
      const control = event.target;
      const key = { "theme-select": "theme", "appearance-font-size": "fontSize", "appearance-density": "density", "appearance-grid": "grid", "appearance-chart-background": "chartBackground" }[control.id];
      if (control.name === "appearance-theme") change({ theme: control.value });
      else if (key) change({ [key]: control.type === "checkbox" ? control.checked : control.value });
    });
    byId("appearance-close").addEventListener("click", close);
    byId("appearance-reset").addEventListener("click", () => { statusKey = "appearance_reset_done"; theme().reset(); });
    // Keep Escape local: the workbench has other independent drawers.
    dialog.addEventListener("keydown", (event) => { if (event.key === "Escape") event.stopPropagation(); });
    dialog.addEventListener("close", () => { if (opener && opener.isConnected) opener.focus({ preventScroll: true }); });
  }

  function change(patch) {
    statusKey = "appearance_saved";
    theme().update(patch);
  }

  function refresh() {
    const dialog = byId("appearance-dialog");
    if (!dialog) return;
    dialog.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = text(node.dataset.i18n); });
    const prefs = theme().getPreferences();
    dialog.querySelectorAll('[name="appearance-theme"]').forEach((radio) => {
      radio.checked = radio.value === prefs.theme;
      radio.closest("label").classList.toggle("selected", radio.checked);
    });
    byId("theme-select").value = prefs.theme;
    byId("appearance-font-size").value = prefs.fontSize;
    byId("appearance-density").value = prefs.density;
    byId("appearance-grid").checked = prefs.grid;
    byId("appearance-chart-background").value = prefs.chartBackground;
    byId("appearance-status").textContent = !theme().isPersistent() ? text("appearance_session_only") : statusKey ? text(statusKey) : "";
  }

  function open() {
    ensureDialog();
    refresh();
    const dialog = byId("appearance-dialog");
    if (!dialog.open) {
      opener = document.activeElement;
      dialog.showModal();
    }
  }

  function close() {
    const dialog = byId("appearance-dialog");
    if (dialog && dialog.open) dialog.close();
  }

  function init(context) {
    hooks = context || {};
    ensureDialog();
    if (!initialized) {
      const button = byId("appearance-open");
      if (button) button.addEventListener("click", open);
      window.addEventListener("electrochem:appearance-changed", refresh);
      initialized = true;
    }
    refresh();
  }

  window.ElectrochemAppearance = { init, open, close, refresh, labels };
})();
