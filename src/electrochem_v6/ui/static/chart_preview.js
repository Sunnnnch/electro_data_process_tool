(function () {
  "use strict";

  const paperColors = { background: "#ffffff", text: "#163444", axis: "#476779", halo: "#163444" };

  function backgroundMode() {
    const theme = window.ElectrochemTheme;
    const preferences = theme && typeof theme.getPreferences === "function" ? theme.getPreferences() : {};
    return preferences.chartBackground === "paper" ? "paper" : "theme";
  }

  function applyVector(svg) {
    const mode = backgroundMode();
    const colors = mode === "paper" ? paperColors : {
      background: "var(--chart-preview-bg, #ffffff)",
      text: "var(--chart-preview-text, #163444)",
      axis: "var(--chart-preview-axis, #476779)",
      halo: "var(--chart-preview-text, #163444)",
    };
    svg.dataset.chartBackground = mode;
    svg.querySelectorAll("[data-chart-part]").forEach((node) => {
      const part = node.dataset.chartPart;
      if (part === "background" || part === "text") node.setAttribute("fill", colors[part]);
      if (part === "axis" || part === "halo") node.setAttribute("stroke", colors[part]);
    });
  }

  function refresh(root) {
    const target = root || document;
    if (target.matches && target.matches('[data-chart-preview="vector"]')) applyVector(target);
    target.querySelectorAll('[data-chart-preview="vector"]').forEach(applyVector);
  }

  function paperMarkup({ src, alt, t, escapeHtml }) {
    const key = "chart_original_paper_note";
    const translated = typeof t === "function" ? t(key) : key;
    const note = translated === key ? "原始图表以白底图纸显示；主题不会修改图像或导出文件。" : translated;
    return `<figure class="chart-preview-shell" data-chart-preview="paper"><div class="chart-paper"><img alt="${escapeHtml(String(alt || ""))}" src="${escapeHtml(String(src || ""))}"></div><figcaption class="chart-preview-note">${escapeHtml(note)}</figcaption></figure>`;
  }

  window.addEventListener("electrochem:appearance-changed", () => refresh());
  window.ElectrochemChartPreview = { applyVector, backgroundMode, paperMarkup, refresh };
})();
