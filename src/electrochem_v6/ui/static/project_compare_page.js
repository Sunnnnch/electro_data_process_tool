(function () {
  "use strict";

  function safeSummary(summary) {
    return summary && typeof summary === "object" ? summary : {};
  }

  function safeState(state) {
    return state && typeof state === "object" ? state : {};
  }

  function stateSelectedSamples(state) {
    const safe = safeState(state);
    return Array.isArray(safe.selectedSamples) ? safe.selectedSamples : [];
  }

  function filterSamples({ model, state, summary }) {
    const safe = safeState(state);
    const payload = safeSummary(summary);
    return model.filterSamples(payload.samples, {
      onlyEta: Boolean(safe.onlyEta),
      onlyTafel: Boolean(safe.onlyTafel),
      sort: safe.sort || "eta",
    });
  }

  function syncSelection({ maxDefault = 3, model, state, summary }) {
    const safe = safeState(state);
    const samples = filterSamples({ model, state: safe, summary });
    const selection = model.syncSelectedSamples(samples, stateSelectedSamples(safe), maxDefault);
    return {
      clearPlot: selection.clearPlot,
      plotData: selection.clearPlot ? null : safe.plotData,
      plotLoading: selection.visibleNames.length ? Boolean(safe.plotLoading) : false,
      samples,
      selectedSamples: selection.selectedSamples,
      visibleNames: selection.visibleNames,
    };
  }

  function renderSelectionCount({ byId, selectedSamples, t }) {
    const el = byId("project-compare-selected-count");
    if (!el) return;
    const count = Array.isArray(selectedSamples) ? selectedSamples.length : 0;
    el.textContent = count
      ? t("project_compare_selected_count").replace("{count}", String(count))
      : t("project_compare_selected_count_empty");
  }

  function needsTargetCurrent({ model, state }) {
    const safe = safeState(state);
    return model.needsTargetCurrent(safe.chartType, safe.metric);
  }

  function availableTargetCurrents({ model, state }) {
    const safe = safeState(state);
    return model.availableTargetCurrents(safe.targetCurrents, safe.metric);
  }

  function syncTargetOptions({ byId, escapeHtml, model, preferredValue = 10, state, t }) {
    const safe = safeState(state);
    const targetEl = byId("project-compare-target-current");
    if (!targetEl) return { targetCurrent: safe.targetCurrent || "" };

    const options = availableTargetCurrents({ model, state: safe });
    const targetState = model.selectTargetCurrent(options, safe.targetCurrent, preferredValue);
    const targetCurrent = targetState.value || "";
    if (!targetState.options.length) {
      targetEl.innerHTML = `<option value="">${escapeHtml(t("project_compare_target_current_empty"))}</option>`;
      targetEl.value = "";
      return { targetCurrent: "" };
    }
    targetEl.innerHTML = targetState.options
      .map((item) => {
        const text = model.formatTargetCurrent(item);
        return `<option value="${escapeHtml(text)}">${escapeHtml(text)}</option>`;
      })
      .join("");
    targetEl.value = targetCurrent;
    return { targetCurrent };
  }

  function syncControls({ byId, escapeHtml, model, state, t }) {
    const safe = safeState(state);
    const metricEl = byId("project-compare-metric");
    const targetEl = byId("project-compare-target-current");
    const targetWrap = byId("project-compare-target-wrap");
    if (metricEl) {
      metricEl.disabled = safe.chartType !== "bar";
      const control = typeof metricEl.closest === "function" ? metricEl.closest(".compare-control") : null;
      if (control) control.hidden = safe.chartType !== "bar";
    }
    const needsTarget = needsTargetCurrent({ model, state: safe });
    const targetState = syncTargetOptions({ byId, escapeHtml, model, state: safe, t });
    const nextState = { ...safe, targetCurrent: targetState.targetCurrent };
    if (targetEl) {
      targetEl.disabled = !needsTarget || !availableTargetCurrents({ model, state: nextState }).length;
    }
    if (targetWrap) {
      targetWrap.hidden = !needsTarget;
      targetWrap.style.opacity = needsTarget ? "1" : "0.55";
    }
    return targetState;
  }

  function bindSelection({ root, selectedSamples, onChange }) {
    const selected = Array.isArray(selectedSamples) ? selectedSamples : [];
    const targetRoot = root || document;
    targetRoot.querySelectorAll(".project-compare-sample").forEach((input) => {
      input.addEventListener("change", () => {
        const sampleName = decodeURIComponent(input.getAttribute("data-sample-name") || "");
        if (!sampleName) return;
        let nextSelected = selected;
        if (input.checked) {
          nextSelected = selected.includes(sampleName) ? selected : [...selected, sampleName];
        } else {
          nextSelected = selected.filter((item) => item !== sampleName);
        }
        onChange({ selectedSamples: nextSelected });
      });
    });
  }

  function renderSummary({ byId, escapeHtml, formatMetric, model, state, summary, t }) {
    const wrap = byId("project-compare-summary");
    if (!wrap) return;
    const samples = filterSamples({ model, state, summary });
    if (!samples.length) {
      wrap.innerHTML = `<div class="placeholder">${t("project_compare_empty")}</div>`;
      return;
    }
    const bestEta = [...samples]
      .filter((item) => item.overpotential_10 !== undefined && item.overpotential_10 !== null)
      .sort((a, b) => a.overpotential_10 - b.overpotential_10)[0];
    const bestPotential = [...samples]
      .filter((item) => item.potential_10 !== undefined && item.potential_10 !== null)
      .sort((a, b) => a.potential_10 - b.potential_10)[0];
    const bestTafel = [...samples]
      .filter((item) => item.tafel_slope !== undefined && item.tafel_slope !== null)
      .sort((a, b) => a.tafel_slope - b.tafel_slope)[0];
    const missingEta = samples
      .filter((item) => item.overpotential_10 === undefined || item.overpotential_10 === null)
      .map((item) => item.sample_name || "-");
    const missingTafel = samples
      .filter((item) => item.tafel_slope === undefined || item.tafel_slope === null)
      .map((item) => item.sample_name || "-");

    const cards = [];
    if (bestEta) {
      cards.push(`<div class="compare-chip"><strong>${escapeHtml(t("project_compare_best_eta"))}</strong><span>${escapeHtml(String(bestEta.sample_name || "-"))} | ${escapeHtml(formatMetric(bestEta.overpotential_10, 3))} mV</span></div>`);
    } else if (bestPotential) {
      cards.push(`<div class="compare-chip"><strong>${escapeHtml(t("project_compare_best_potential"))}</strong><span>${escapeHtml(String(bestPotential.sample_name || "-"))} | ${escapeHtml(formatMetric(bestPotential.potential_10, 3))} V</span></div>`);
    }
    if (bestTafel) {
      cards.push(`<div class="compare-chip"><strong>${escapeHtml(t("project_compare_best_tafel"))}</strong><span>${escapeHtml(String(bestTafel.sample_name || "-"))} | ${escapeHtml(formatMetric(bestTafel.tafel_slope, 3))}</span></div>`);
    }
    if (missingEta.length || missingTafel.length) {
      const missingParts = [];
      if (missingEta.length) missingParts.push(`${t("project_compare_missing_eta")}: ${missingEta.slice(0, 4).join(", ")}`);
      if (missingTafel.length) missingParts.push(`${t("project_compare_missing_tafel")}: ${missingTafel.slice(0, 4).join(", ")}`);
      cards.push(`<div class="compare-chip muted"><strong>${escapeHtml(t("project_compare_missing"))}</strong><span>${escapeHtml(missingParts.join(" | "))}</span></div>`);
    }
    wrap.innerHTML = cards.join("") || `<div class="placeholder">${t("project_compare_empty")}</div>`;
  }

  function renderTable({ byId, escapeHtml, formatMetric, model, onSelectionChange, state, summary, t }) {
    const wrap = byId("project-compare-table");
    if (!wrap) return [];
    const selectedSamples = stateSelectedSamples(state);
    const samples = filterSamples({ model, state, summary });
    if (!samples.length) {
      wrap.innerHTML = `<div class="placeholder">${t("project_compare_empty")}</div>`;
      renderSelectionCount({ byId, selectedSamples, t });
      return samples;
    }
    wrap.innerHTML = `
      <table class="lsv-summary-table compare-table">
        <thead>
          <tr>
            <th>${escapeHtml(t("project_compare_col_sample"))}</th>
            <th>${escapeHtml(t("project_compare_col_eta"))}</th>
            <th>${escapeHtml(t("project_compare_col_tafel"))}</th>
            <th>${escapeHtml(t("project_compare_col_count"))}</th>
            <th>${escapeHtml(t("project_compare_col_time"))}</th>
          </tr>
        </thead>
        <tbody>
          ${samples
            .map((item) => {
              const sampleName = String(item.sample_name || "-");
              const sampleToken = encodeURIComponent(sampleName);
              const checked = selectedSamples.includes(sampleName) ? "checked" : "";
              const etaText =
                item.overpotential_10 !== undefined && item.overpotential_10 !== null
                  ? `${formatMetric(item.overpotential_10, 3)} mV`
                  : item.potential_10 !== undefined && item.potential_10 !== null
                    ? `${formatMetric(item.potential_10, 3)} V`
                    : "-";
              const tafelText = item.tafel_slope !== undefined && item.tafel_slope !== null ? formatMetric(item.tafel_slope, 3) : "-";
              return `
                <tr>
                  <td>
                    <label class="compare-sample-cell compare-sample-check">
                      <input class="project-compare-sample" type="checkbox" data-sample-name="${sampleToken}" ${checked}>
                      <span>${escapeHtml(sampleName)}</span>
                    </label>
                  </td>
                  <td>${escapeHtml(etaText)}</td>
                  <td>${escapeHtml(tafelText)}</td>
                  <td>${escapeHtml(String(item.record_count ?? "-"))}</td>
                  <td>${escapeHtml(String(item.latest_time || "-"))}</td>
                </tr>
              `;
            })
            .join("")}
        </tbody>
      </table>
    `;
    renderSelectionCount({ byId, selectedSamples, t });
    bindSelection({ root: wrap, selectedSamples, onChange: onSelectionChange });
    return samples;
  }

  function renderPlot({ bindFileActions, byId, escapeHtml, model, state, t }) {
    const wrap = byId("project-compare-plot");
    if (!wrap) return {};
    const targetState = syncControls({ byId, escapeHtml, model, state, t });
    const safe = { ...safeState(state), ...targetState };
    const selectedSamples = stateSelectedSamples(safe);
    if (safe.plotLoading) {
      wrap.innerHTML = `<div class="placeholder">${t("project_compare_plot_loading")}</div>`;
      return targetState;
    }
    if (!selectedSamples.length) {
      wrap.innerHTML = `<div class="placeholder">${t("project_compare_plot_empty")}</div>`;
      return targetState;
    }
    if (!safe.plotData || !safe.plotData.image_data_url) {
      wrap.innerHTML = `<div class="placeholder">${t("project_compare_plot_empty")}</div>`;
      return targetState;
    }
    const plot = safe.plotData;
    const warnings = Array.isArray(plot.warnings) ? plot.warnings.filter((item) => String(item || "").trim()) : [];
    const image = window.ElectrochemChartPreview
      ? window.ElectrochemChartPreview.paperMarkup({ src: plot.image_data_url, alt: t("project_compare_plot_title"), t, escapeHtml })
      : `<img alt="${escapeHtml(t("project_compare_plot_title"))}" src="${escapeHtml(plot.image_data_url)}">`;
    wrap.innerHTML = `
      <div class="project-compare-plot-preview">
        ${image}
        <div class="project-compare-plot-meta">
          <span>${escapeHtml(t("project_compare_plot_traces"))}: ${escapeHtml(String(plot.trace_count || 0))}</span>
          ${plot.metric_label ? `<span>${escapeHtml(String(plot.metric_label))}</span>` : ""}
          <span>${escapeHtml(t("project_compare_plot_generated_at"))}: ${escapeHtml(String(plot.generated_at || "-"))}</span>
        </div>
        <div class="project-compare-plot-actions">
          <button class="btn mini" type="button" data-copy-path="${escapeHtml(String(plot.plot_path || ""))}">${escapeHtml(t("btn_copy_path"))}</button>
          <button class="btn mini" type="button" data-open-path="${escapeHtml(String(plot.plot_path || ""))}">${escapeHtml(t("btn_open_file"))}</button>
          <button class="btn mini" type="button" data-open-dir="${escapeHtml(String(plot.plot_path || ""))}">${escapeHtml(t("btn_open_dir"))}</button>
        </div>
        ${warnings.length ? `<ul class="project-compare-plot-warnings">${warnings.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul>` : ""}
      </div>
    `;
    bindFileActions(wrap);
    return targetState;
  }

  function selectAllSampleNames({ model, state, summary }) {
    return filterSamples({ model, state, summary })
      .map((item) => String(item.sample_name || "").trim())
      .filter(Boolean);
  }

  window.ElectrochemProjectComparePage = {
    availableTargetCurrents,
    filterSamples,
    needsTargetCurrent,
    renderPlot,
    renderSelectionCount,
    renderSummary,
    renderTable,
    selectAllSampleNames,
    syncControls,
    syncSelection,
    syncTargetOptions,
  };
})();
