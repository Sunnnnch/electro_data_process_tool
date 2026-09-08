(function () {
  "use strict";

  const labels = {
    appearance_open: ["外观", "Appearance"],
    appearance_title: ["外观设置", "Appearance settings"],
    appearance_hint: ["更改即时生效，不影响数据与计算参数。", "Changes apply immediately and leave data and analysis settings unchanged."],
    appearance_style: ["界面风格", "Interface style"],
    appearance_style_hint: ["选择边角与阴影样式，再搭配喜欢的颜色。", "Choose corners and shadows, then pair them with your preferred colors."],
    appearance_style_modern: ["现代简洁", "Modern"],
    appearance_style_modern_hint: ["柔和圆角、轻阴影，清晰舒展", "Soft corners and subtle shadows"],
    appearance_style_paper: ["纸感编辑", "Paper Editorial"],
    appearance_style_paper_hint: ["细线分隔、轻量纸面，专注内容阅读", "Fine dividers and understated paper surfaces for focused reading"],
    appearance_style_soft: ["柔和模块", "Soft Modules"],
    appearance_style_soft_hint: ["舒展圆角、柔和层次，模块清晰可辨", "Generous corners and soft depth with clearly defined modules"],
    appearance_style_pixel: ["像素复古", "Pixel Retro"],
    appearance_style_pixel_hint: ["直角控件、硬边阴影，复古有序", "Square controls and crisp offset shadows"],
    appearance_theme_lab: ["实验室浅色", "Lab Light"],
    appearance_theme_lab_hint: ["明亮清晰，适合日常分析", "A clear, light workspace for everyday analysis"],
    appearance_theme_ocean: ["专业深海", "Professional Ocean"],
    appearance_theme_ocean_hint: ["深色背景搭配浅色工作区", "A deep backdrop with light working panels"],
    appearance_theme_dark: ["高对比暗色", "High-Contrast Dark"],
    appearance_theme_dark_hint: ["适合较暗环境中的分析", "For analysis in dim surroundings"],
    appearance_theme_pixel: ["像素复古", "Pixel Retro"],
    appearance_theme_pixel_hint: ["直角边界与轻量像素阴影", "Square borders with subtle pixel shadows"],
    appearance_theme_system: ["跟随系统", "Follow system"],
    appearance_theme_system_hint: ["自动切换实验室浅色与高对比暗色", "Switch automatically between Lab Light and High-Contrast Dark"],
    appearance_palette: ["配色", "Color palette"],
    appearance_palette_hint: ["所有配色均可搭配四种风格；每种风格单独记住选择。", "All palettes work with all four styles. Each style remembers its selection."],
    appearance_palette_system_hint: ["按系统明暗自动切换浅色与暗色，保持当前界面风格。", "Switch between light and dark with the system while keeping your interface style."],
    appearance_palette_lab: ["实验室浅色", "Lab Light"],
    appearance_palette_ocean: ["专业深海", "Professional Ocean"],
    appearance_palette_dark: ["高对比暗色", "High-Contrast Dark"],
    appearance_palette_system: ["跟随系统", "Follow system"],
    appearance_palette_cream: ["复古米白", "Retro Cream"],
    appearance_palette_slate: ["石板蓝", "Slate Blue"],
    appearance_palette_amber: ["暖黑琥珀", "Warm Amber"],
    appearance_palette_mist: ["雾灰蓝", "Misty Blue"],
    appearance_palette_handheld: ["掌机黄绿", "Handheld Olive"],
    appearance_palette_violet: ["灰紫", "Muted Violet"],
    appearance_palette_custom: ["自选颜色", "Custom colors"],
    appearance_palette_reset: ["恢复当前风格配色", "Reset this style's colors"],
    appearance_palette_reset_done: ["已恢复当前风格的默认配色。", "This style's default colors have been restored."],
    appearance_palette_recovered: ["此前保存的配色", "Previously saved palettes"],
    appearance_palette_recovered_hint: ["旧主题与已移除风格的配色已保留，点击即可应用到当前风格。", "Palettes from earlier themes and removed styles are preserved. Select one to apply it to this style."],
    appearance_palette_recovered_lab: ["原实验室浅色 · 自选", "From Lab Light · Custom"],
    appearance_palette_recovered_ocean: ["原专业深海 · 自选", "From Professional Ocean · Custom"],
    appearance_palette_recovered_dark: ["原高对比暗色 · 自选", "From High-Contrast Dark · Custom"],
    appearance_palette_recovered_pixel: ["原像素复古 · 自选", "From Pixel Retro · Custom"],
    appearance_palette_recovered_classic: ["原经典桌面配色", "From Classic Desktop"],
    appearance_color_background: ["页面背景", "Page background"],
    appearance_color_surface: ["面板背景", "Panel background"],
    appearance_color_primary: ["强调色", "Accent color"],
    appearance_color_text: ["正文文字", "Body text"],
    appearance_color_titlebar: ["窗口标题栏", "Window title bar"],
    appearance_color_auto_text: ["自动匹配文字颜色", "Match text color automatically"],
    appearance_color_invalid: ["请输入有效的六位颜色值，例如 #31539A。", "Enter a valid six-digit color, such as #31539A."],
    appearance_palette_low_contrast: ["文字与背景的对比偏低，可调整文字或背景，也可自动匹配文字颜色。", "Text contrast is low. Adjust the text or background, or match text color automatically."],
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
    appearance_reset_done: ["已恢复默认：现代简洁、实验室浅色、标准字号、舒适密度、关闭网格、图表跟随主题。", "Defaults restored: Modern, Lab Light, standard text, comfortable density, no grid, charts follow theme."],
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

  function styleCard(name) {
    return `<label class="appearance-style-card" data-appearance-style="${name}">
      <input type="radio" name="appearance-style" value="${name}" aria-labelledby="appearance-style-${name}">
      <span class="appearance-style-preview" data-preview-style="${name}" aria-hidden="true">
        <span class="appearance-preview-bar"></span><span class="appearance-preview-layout"><span class="appearance-preview-side"></span><span class="appearance-preview-main"><span class="appearance-preview-line"></span><span class="appearance-preview-line"></span><span class="appearance-preview-chart"></span></span></span>
      </span><strong id="appearance-style-${name}" data-i18n="appearance_style_${name}"></strong>${caption(`appearance_style_${name}_hint`, "small")}</label>`;
  }

  function paletteCard(name) {
    return `<label class="appearance-palette-card" data-appearance-palette="${name}">
      <input type="radio" name="appearance-palette" value="${name}" aria-labelledby="appearance-palette-${name}">
      <span class="appearance-palette-colors" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
      <span id="appearance-palette-${name}" data-i18n="appearance_palette_${name}"></span></label>`;
  }

  function colorControl(name) {
    return `<div class="appearance-color-control"><label for="appearance-color-${name}" id="appearance-color-${name}-label" data-i18n="appearance_color_${name}"></label>
      <div class="appearance-color-inputs"><input type="color" id="appearance-color-${name}" data-color-key="${name}">
      <input type="text" id="appearance-color-${name}-hex" data-color-hex="${name}" aria-labelledby="appearance-color-${name}-label" spellcheck="false" autocomplete="off" maxlength="7" pattern="#[0-9a-fA-F]{6}"></div></div>`;
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
      <fieldset class="appearance-styles">${caption("appearance_style", "legend")}${caption("appearance_style_hint", "p")}<div class="appearance-style-grid">${theme().styles.map(styleCard).join("")}</div>
      <select id="theme-select" class="theme-select" hidden aria-hidden="true" tabindex="-1">${["lab", "ocean", "dark", "pixel", "system"].map((name) => `<option value="${name}" data-i18n="appearance_theme_${name}"></option>`).join("")}</select></fieldset>
      <fieldset class="appearance-palettes">${caption("appearance_palette", "legend")}${caption("appearance_palette_hint", "p")}<p id="appearance-palette-system-hint" data-i18n="appearance_palette_system_hint" hidden></p>
      <div class="appearance-palette-grid">${[...window.ElectrochemPalette.presets.map((item) => item.id), "system", "custom"].map(paletteCard).join("")}</div>
      <details id="appearance-recovered-palettes" hidden><summary data-i18n="appearance_palette_recovered"></summary>${caption("appearance_palette_recovered_hint", "p")}<div class="appearance-recovered-grid"></div></details>
      <div id="appearance-custom-colors" hidden><div class="appearance-colors-grid">${window.ElectrochemPalette.colorKeys.map(colorControl).join("")}</div>
      <button type="button" id="appearance-color-auto-text" class="btn secondary" data-i18n="appearance_color_auto_text"></button></div>
      <p id="appearance-palette-contrast" role="status" data-i18n="appearance_palette_low_contrast" hidden></p>
      <button type="button" id="appearance-palette-reset" class="btn secondary" data-i18n="appearance_palette_reset"></button></fieldset>
      <div class="appearance-controls-grid"><label class="appearance-control" for="appearance-font-size">${caption("appearance_font_size")}<select id="appearance-font-size"><option value="standard" data-i18n="appearance_font_standard"></option><option value="large" data-i18n="appearance_font_large"></option><option value="extra-large" data-i18n="appearance_font_extra_large"></option></select></label>
      <label class="appearance-control" for="appearance-density">${caption("appearance_density")}<select id="appearance-density"><option value="comfortable" data-i18n="appearance_density_comfortable"></option><option value="compact" data-i18n="appearance_density_compact"></option></select></label>
      <label class="appearance-control" for="appearance-chart-background">${caption("appearance_chart_background")}<select id="appearance-chart-background"><option value="theme" data-i18n="appearance_chart_theme"></option><option value="paper" data-i18n="appearance_chart_paper"></option></select></label>
      <label class="appearance-grid-control" for="appearance-grid"><input id="appearance-grid" type="checkbox">${caption("appearance_grid")}</label></div></div>
      <footer class="appearance-footer"><button id="appearance-reset" class="btn secondary" type="button" data-i18n="appearance_reset"></button><p id="appearance-status" role="status" aria-live="polite"></p></footer>`;
    document.body.appendChild(dialog);
    dialog.addEventListener("change", (event) => {
      const control = event.target;
      const key = { "theme-select": "theme", "appearance-font-size": "fontSize", "appearance-density": "density", "appearance-grid": "grid", "appearance-chart-background": "chartBackground" }[control.id];
      if (control.name === "appearance-palette") {
        statusKey = "appearance_saved";
        theme().setPalette(control.value === "custom" ? { id: "custom", colors: theme().getPalette().colors } : control.value);
      } else if (control.dataset.colorKey || control.dataset.colorHex) {
        const colorKey = control.dataset.colorKey || control.dataset.colorHex;
        const value = control.value.trim();
        if (!/^#[0-9a-f]{6}$/i.test(value)) {
          control.setAttribute("aria-invalid", "true");
          byId("appearance-status").textContent = text("appearance_color_invalid");
          return;
        }
        statusKey = "appearance_saved";
        theme().setPalette({ id: "custom", colors: { ...theme().getPalette().colors, [colorKey]: value } });
      } else if (control.name === "appearance-style") change({ style: control.value });
      else if (key) change({ [key]: control.type === "checkbox" ? control.checked : control.value });
    });
    byId("appearance-close").addEventListener("click", close);
    byId("appearance-reset").addEventListener("click", () => { statusKey = "appearance_reset_done"; theme().reset(); });
    byId("appearance-palette-reset").addEventListener("click", () => { statusKey = "appearance_palette_reset_done"; theme().resetPalette(); });
    byId("appearance-recovered-palettes").addEventListener("click", (event) => {
      const button = event.target.closest("[data-recovered-palette]");
      if (!button) return;
      const saved = theme().getRecoveredPalettes().find((item) => item.id === button.dataset.recoveredPalette);
      if (saved) {
        statusKey = "appearance_saved";
        theme().setPalette(saved.selection || { id: "custom", colors: saved.colors });
      }
    });
    byId("appearance-color-auto-text").addEventListener("click", () => {
      const colors = theme().getPalette().colors;
      const contrast = window.ElectrochemPalette.contrast;
      const candidates = ["#20242B", "#F7F8FA", "#000000", "#FFFFFF"];
      const score = (color) => contrast(color, colors.surface);
      candidates.sort((a, b) => score(b) - score(a));
      statusKey = "appearance_saved";
      theme().setPalette({ id: "custom", colors: { ...colors, text: candidates[0] } });
    });
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
    dialog.querySelectorAll('[name="appearance-style"]').forEach((radio) => {
      radio.checked = radio.value === prefs.style;
      radio.closest("label").classList.toggle("selected", radio.checked);
    });
    const selection = theme().getPaletteSelection();
    byId("theme-select").value = selection.id === "system" ? "system" : theme().getStyle() === "pixel" ? "pixel" : theme().getTheme();
    byId("appearance-font-size").value = prefs.fontSize;
    byId("appearance-density").value = prefs.density;
    byId("appearance-grid").checked = prefs.grid;
    byId("appearance-chart-background").value = prefs.chartBackground;
    const palette = theme().getPalette();
    dialog.querySelectorAll('[name="appearance-palette"]').forEach((radio) => {
      radio.checked = radio.value === selection.id;
      radio.closest("label").classList.toggle("selected", radio.checked);
      const presetId = radio.value === "system" ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "lab") : radio.value;
      const colors = radio.value === "custom" ? palette.colors : window.ElectrochemPalette.presets.find((item) => item.id === presetId).colors;
      radio.closest("label").querySelectorAll("i").forEach((swatch, index) => { swatch.style.backgroundColor = colors[["background", "titlebar", "surface", "primary"][index]]; });
    });
    // All thumbnails use the active palette, making their structural differences visible.
    dialog.querySelectorAll(".appearance-style-preview").forEach((preview) => {
      preview.style.setProperty("--preview-background", palette.colors.background);
      preview.style.setProperty("--preview-paper", palette.colors.surface);
      preview.style.setProperty("--preview-ink", palette.colors.primary);
    });
    const recovered = theme().getRecoveredPalettes();
    const recovery = byId("appearance-recovered-palettes");
    recovery.hidden = recovered.length === 0;
    const grid = recovery.querySelector(".appearance-recovered-grid");
    // Keep buttons stable so applying a saved palette does not lose keyboard focus.
    if (grid.dataset.ids !== recovered.map((item) => item.id).join(",")) {
      grid.replaceChildren(...recovered.map((item) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn secondary";
        button.dataset.recoveredPalette = item.id;
        return button;
      }));
      grid.dataset.ids = recovered.map((item) => item.id).join(",");
    }
    recovered.forEach((item, index) => { grid.children[index].textContent = text(item.labelKey); });
    byId("appearance-custom-colors").hidden = selection.id !== "custom";
    byId("appearance-palette-system-hint").hidden = selection.id !== "system";
    window.ElectrochemPalette.colorKeys.forEach((key) => {
      byId(`appearance-color-${key}`).value = palette.colors[key];
      byId(`appearance-color-${key}-hex`).value = palette.colors[key].toUpperCase();
      byId(`appearance-color-${key}-hex`).removeAttribute("aria-invalid");
    });
    byId("appearance-palette-contrast").hidden = window.ElectrochemPalette.contrast(palette.colors.text, palette.colors.surface) >= 4.5;
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
