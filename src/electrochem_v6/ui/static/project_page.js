(function () {
  "use strict";

  function textOrEmpty(value) {
    return String(value || "");
  }

  function safeData(data) {
    return data && typeof data === "object" ? data : {};
  }

  function setText(byId, id, value) {
    const el = typeof byId === "function" ? byId(id) : null;
    if (el) el.textContent = String(value);
  }

  function renderStats(options) {
    const opts = options || {};
    const data = safeData(opts.data);
    const prefix = opts.prefix || "stat";
    const byId = opts.byId;
    setText(byId, `${prefix}-total`, data.total_files || 0);
    setText(byId, `${prefix}-lsv`, data.lsv_count || 0);
    setText(byId, `${prefix}-cv`, data.cv_count || 0);
    setText(byId, `${prefix}-eis`, data.eis_count || 0);
    setText(byId, `${prefix}-ecsa`, data.ecsa_count || 0);
    setText(byId, `${prefix}-coupled`, data.coupled_count || 0);
  }

  function setProjectEditForm(options) {
    const opts = options || {};
    const byId = opts.byId;
    const project = opts.project && typeof opts.project === "object" ? opts.project : null;
    const nameEl = typeof byId === "function" ? byId("project-edit-name") : null;
    const colorEl = typeof byId === "function" ? byId("project-edit-color") : null;
    const tagsEl = typeof byId === "function" ? byId("project-edit-tags") : null;
    const descEl = typeof byId === "function" ? byId("project-edit-desc") : null;
    const saveBtn = typeof byId === "function" ? byId("project-save-btn") : null;
    if (nameEl) nameEl.value = project ? String(project.name || "") : "";
    if (colorEl) colorEl.value = project ? String(project.color || "") : "";
    if (tagsEl) tagsEl.value = project && Array.isArray(project.tags) ? project.tags.join(", ") : "";
    if (descEl) descEl.value = project ? String(project.description || "") : "";
    if (saveBtn) saveBtn.disabled = !project;
  }

  function renderProjectHeader(options) {
    const opts = options || {};
    const byId = opts.byId;
    const translate = typeof opts.t === "function" ? opts.t : textOrEmpty;
    const project = opts.project && typeof opts.project === "object" ? opts.project : null;
    const titleEl = typeof byId === "function" ? byId("project-detail-title") : null;
    const metaEl = typeof byId === "function" ? byId("project-detail-meta") : null;
    const useBtn = typeof byId === "function" ? byId("project-use-btn") : null;
    const delBtn = typeof byId === "function" ? byId("project-delete-btn") : null;
    const exportBtn = typeof byId === "function" ? byId("project-export-report-btn") : null;
    if (!project) {
      if (titleEl) titleEl.textContent = translate("project_none");
      if (metaEl) metaEl.textContent = translate("project_pick_hint");
      if (useBtn) useBtn.disabled = true;
      if (delBtn) delBtn.disabled = true;
      if (exportBtn) exportBtn.disabled = true;
      return false;
    }
    if (useBtn) useBtn.disabled = false;
    if (delBtn) delBtn.disabled = false;
    if (exportBtn) exportBtn.disabled = false;
    if (titleEl) titleEl.textContent = String(project.name || translate("project_none"));
    if (metaEl) {
      const parts = [
        `${translate("project_label_created")}: ${project.created_at || "-"}`,
        `${translate("project_label_updated")}: ${project.updated_at || "-"}`,
        `${translate("project_label_files")}: ${project.file_count ?? 0}`,
      ];
      const desc = String(project.description || "").trim();
      if (desc) parts.push(`${translate("project_label_desc")}: ${desc}`);
      metaEl.textContent = parts.join(" | ");
    }
    return true;
  }

  function relatedFilesForRecord(record) {
    const related = [];
    if (!record || typeof record !== "object") return related;
    if (record.file_path) related.push(String(record.file_path));
    if (record.file_name && record.file_name !== record.file_path) related.push(String(record.file_name));
    if (record.summary_path) related.push(String(record.summary_path));
    if (Array.isArray(record.output_files)) {
      record.output_files.forEach((item) => {
        const text = String(item || "").trim();
        if (text) related.push(text);
      });
    }
    return Array.from(new Set(related));
  }

  function rawFilesForRecord(record) {
    const related = [];
    if (!record || typeof record !== "object") return related;
    if (record.file_path) related.push(String(record.file_path));
    else if (record.file_name) related.push(String(record.file_name));
    if (record.source_archive_path) related.push(String(record.source_archive_path));
    return Array.from(new Set(related));
  }

  function renderProjectHistoryDetail(options) {
    const opts = options || {};
    const byId = opts.byId;
    const escapeHtml = opts.escapeHtml || textOrEmpty;
    const translate = typeof opts.t === "function" ? opts.t : textOrEmpty;
    const wrap = typeof byId === "function" ? byId("project-history-detail") : null;
    const openBtn = typeof byId === "function" ? byId("project-open-result-btn") : null;
    const archiveBtn = typeof byId === "function" ? byId("project-archive-history-btn") : null;
    const deleteBtn = typeof byId === "function" ? byId("project-delete-history-btn") : null;
    const record = opts.record && typeof opts.record === "object" ? opts.record : null;
    if (!wrap) return;
    if (!record) {
      const detailPanel = typeof byId === "function" ? byId("project-history-detail-panel") : null;
      if (detailPanel) detailPanel.hidden = true;
      wrap.innerHTML = `<div class="placeholder">${translate("project_select_history")}</div>`;
      if (openBtn) openBtn.disabled = true;
      if (archiveBtn) archiveBtn.disabled = true;
      if (deleteBtn) deleteBtn.disabled = true;
      return;
    }
    if (openBtn) openBtn.disabled = false;
    if (archiveBtn) archiveBtn.disabled = false;
    if (deleteBtn) deleteBtn.disabled = false;
    const metrics = resultMetricEntries(record);
    const resultItems = metrics.length
      ? metrics
          .map((metric) => `<li><strong>${escapeHtml(metric.label)}</strong>: ${escapeHtml(metric.formatted)}</li>`)
          .join("")
      : "<li>-</li>";
    const related = relatedFilesForRecord(record);
    const sampleRecords = Array.isArray(opts.sampleRecords) && opts.sampleRecords.length ? opts.sampleRecords : [record];
    const rawFiles = Array.from(new Set(sampleRecords.flatMap((item) => rawFilesForRecord(item))));
    const sampleTags = Array.isArray(record.sample_tags) ? record.sample_tags : [];
    const sampleNote = String(record.sample_note || "");
    const canEditSample = Boolean(record.sample_id && record.project_id);
    const detailPanel = typeof byId === "function" ? byId("project-history-detail-panel") : null;
    if (detailPanel) detailPanel.hidden = false;
    wrap.innerHTML = `
      <div class="project-history-meta">
        <div><strong>${escapeHtml(String(record.sample_name || "-"))}</strong> · ${escapeHtml(recordFileName(record))}</div>
        <div>${escapeHtml(String(record.type || "-"))} | ${escapeHtml(String(record.timestamp || "-"))} | ${escapeHtml(
          String(record.status || "-")
        )}</div>
      </div>
      <section class="project-result-metrics"><div class="proc-block-title">${escapeHtml(translate("project_result_metrics"))}</div><ul class="proc-list">${resultItems}</ul></section>
      <div class="project-history-sections">
        <details class="project-history-subblock project-sample-editor">
          <summary>${escapeHtml(translate("project_sample_info"))}</summary>
          <label class="input-label" for="project-sample-tags">${escapeHtml(translate("project_sample_tags"))}</label>
          <input id="project-sample-tags" type="text" value="${escapeHtml(sampleTags.join(", "))}"
            placeholder="${escapeHtml(translate("project_sample_tags_placeholder"))}" ${canEditSample ? "" : "disabled"}>
          <label class="input-label" for="project-sample-note">${escapeHtml(translate("project_sample_note"))}</label>
          <textarea id="project-sample-note" rows="4"
            placeholder="${escapeHtml(translate("project_sample_note_placeholder"))}" ${canEditSample ? "" : "disabled"}>${escapeHtml(sampleNote)}</textarea>
          <div class="source-setting-hint">${escapeHtml(translate("project_sample_note_hint"))}</div>
          <button id="project-sample-save-btn" class="btn mini primary" type="button" ${canEditSample ? "" : "disabled"}>${escapeHtml(
            translate("btn_project_sample_save")
          )}</button>
        </details>
        <details class="project-history-subblock">
          <summary>${escapeHtml(translate("project_sample_raw_files"))}</summary>
          <ul class="proc-list">
            ${rawFiles.length ? rawFiles.map((item) => `<li>${escapeHtml(item)}</li>`).join("") : "<li>-</li>"}
          </ul>
        </details>
        <details class="project-history-subblock">
          <summary>${escapeHtml(translate("project_related_files"))}</summary>
          <ul class="proc-list">
            ${related.length ? related.map((item) => `<li>${escapeHtml(item)}</li>`).join("") : "<li>-</li>"}
          </ul>
        </details>
      </div>
    `;
    const saveSampleBtn = typeof byId === "function" ? byId("project-sample-save-btn") : null;
    if (saveSampleBtn && typeof opts.onSaveSample === "function") {
      saveSampleBtn.addEventListener("click", opts.onSaveSample);
    }
  }

  function groupHistoryByRun(records, keyOf) {
    const groups = new Map();
    (Array.isArray(records) ? records : []).forEach((record, index) => {
      const key = String(record.run_id || keyOf(record));
      if (!groups.has(key)) groups.set(key, { key, runId: record.run_id || "", timestamp: record.timestamp || "", records: [], types: [] });
      const group = groups.get(key);
      group.records.push({ record, index });
      const type = String(record.type || "");
      if (type && !group.types.includes(type)) group.types.push(type);
    });
    return Array.from(groups.values());
  }

  function recordFileName(record) {
    return String(record.file_name || record.file_path || "").split(/[\\/]/).pop() || "";
  }

  function resultMetricEntries(record) {
    const results = record && record.results && typeof record.results === "object" ? record.results : {};
    const known = { tafel_slope: ["Tafel", "mV/dec"], Rs: ["Rs", "Ω"], Rct: ["Rct", "Ω"], ir_compensation: ["iR", "Ω"], equilibrium_potential: ["Eeq", "V"], Cdl: ["Cdl", record.type === "ECSA" ? "mF/cm²" : "F"], ECSA: ["ECSA", "cm²"], RF: ["RF", ""], cdl_mFcm2: ["Cdl", "mF/cm²"], ecsa_cm2: ["ECSA", "cm²"], delta_ep_mV: ["ΔEp", "mV"], charge_mC: ["Q", "mC"], CPE_Q: ["CPE Q", "S·sⁿ"], CPE_n: ["CPE n", ""], randles_r2: ["R²", ""], R2: ["R²", ""], fit_rmse_ohm: ["RMSE", "Ω"], Cs_mFcm2: ["Cs", "mF/cm²"], geometric_area_cm2: ["Ageo", "cm²"] };
    const metrics = new Map();
    Object.entries(results).forEach(([key, value]) => {
      const target = /^(potential|overpotential)_(?:at_)?([0-9]+(?:\.[0-9]+)?)$/.exec(key);
      const canonical = target ? `${target[1]}_${Number(target[2])}` : key;
      if (metrics.has(canonical) && !key.includes("_at_")) return;
      const [label, unit] = target ? [`${target[1] === "potential" ? "E" : "η"}@${Number(target[2])}`, target[1] === "potential" ? "V" : "mV"] : known[key] || [key.replaceAll("_", " "), ""];
      const formatted = value === null || value === undefined ? "—" : `${typeof value === "number" ? Number.isFinite(value) ? Number(value.toPrecision(6)) : "—" : typeof value === "object" ? JSON.stringify(value) : String(value)}${unit ? ` ${unit}` : ""}`;
      metrics.set(canonical, { key: canonical, label, unit, value, formatted });
    });
    return [...metrics.values()];
  }

  function recordMetricPreview(record) {
    const preferred = ["overpotential_10", "potential_10", "tafel_slope", "Rs", "Rct", "Cdl", "ECSA", "cdl_mFcm2", "ecsa_cm2", "delta_ep_mV", "charge_mC"];
    return resultMetricEntries(record).filter((metric) => typeof metric.value === "number" && Number.isFinite(metric.value))
      .sort((a, b) => (preferred.indexOf(a.key) < 0 ? 999 : preferred.indexOf(a.key)) - (preferred.indexOf(b.key) < 0 ? 999 : preferred.indexOf(b.key)))
      .slice(0, 2).map((metric) => `${metric.label}: ${metric.formatted}`).join(" · ");
  }

  function renderProjectHistory(options) {
    const opts = options || {};
    const listEl = opts.listEl;
    const escapeHtml = opts.escapeHtml || textOrEmpty;
    const translate = typeof opts.t === "function" ? opts.t : textOrEmpty;
    const historyRecordKey = typeof opts.historyRecordKey === "function" ? opts.historyRecordKey : () => "";
    const items = Array.isArray(opts.records) ? opts.records : [];
    let selectedKey = String(opts.selectedKey || "");
    if (!listEl) return { selectedKey, selectedRecord: null };
    const detailPanel = opts.detailPanel;
    if (detailPanel && listEl.contains && listEl.contains(detailPanel)) listEl.parentNode.appendChild(detailPanel);
    if (!items.length) {
      listEl.innerHTML = `<div class="placeholder">${translate("project_no_history")}</div>`;
      return { selectedKey: "", selectedRecord: null };
    }
    if (!items.some((record) => historyRecordKey(record) === selectedKey)) {
      selectedKey = opts.autoSelect === false ? "" : historyRecordKey(items[0]);
    }
    const selectedKeys = Array.isArray(opts.selectedKeys) ? opts.selectedKeys : [];
    listEl.innerHTML = groupHistoryByRun(items, historyRecordKey).map((group) => `
      <section class="project-run-group" data-run-id="${escapeHtml(group.runId)}">
        <div class="project-run-head"><div><strong>${escapeHtml(group.timestamp || "-")}</strong><span class="muted">${escapeHtml(group.types.join(" / "))} · ${group.records.length} ${escapeHtml(translate("project_records_unit"))}</span></div><button class="btn mini project-run-detail" type="button" data-project-history-index="${group.records[0].index}">${escapeHtml(translate("project_run_details"))}</button></div>
        ${group.records.map(({ record, index }) => {
        const name = record.sample_name || record.file_name || record.file_path || "unknown";
        const type = record.type || "-";
        const time = record.timestamp || "-";
        const subtitle = [type, recordFileName(record), record.status].filter(Boolean).join(" · ");
        const key = historyRecordKey(record);
        const active = key === selectedKey ? "active" : "";
        return `
          <div class="history-item project-result-row ${active}" data-project-history-index="${index}" data-key="${escapeHtml(key)}">
            <input class="project-record-check" type="checkbox" data-record-key="${escapeHtml(key)}" aria-label="${escapeHtml(`${translate("project_select_result")} ${name} ${type} ${time}`)}" ${selectedKeys.includes(key) ? "checked" : ""}>
            <button type="button" class="project-record-open" data-project-history-index="${index}"><span class="name">${escapeHtml(name)}</span><span class="meta">${escapeHtml(subtitle)}</span></button>
            <span class="project-record-metric">${escapeHtml(recordMetricPreview(record) || "-")}</span>
          </div>
        `;
      }).join("")}</section>`).join("");
    listEl.querySelectorAll(".project-record-open, .project-run-detail").forEach((el) => {
      el.addEventListener("click", () => {
        if (typeof opts.onSelect === "function") opts.onSelect(el.getAttribute("data-project-history-index"));
      });
    });
    listEl.querySelectorAll(".project-record-check").forEach((input) => {
      input.addEventListener("change", () => {
        if (typeof opts.onToggleRecord === "function") opts.onToggleRecord(input.getAttribute("data-record-key"), input.checked);
      });
    });
    if (detailPanel && selectedKey && listEl.querySelector) {
      const row = Array.from(listEl.querySelectorAll(".history-item")).find((item) => item.getAttribute("data-key") === selectedKey);
      if (row && typeof row.after === "function") row.after(detailPanel);
    }
    return {
      selectedKey,
      selectedRecord: items.find((record) => historyRecordKey(record) === selectedKey) || (opts.autoSelect === false ? null : items[0]),
    };
  }

  function renderProjectLSVSummary(options) {
    const opts = options || {};
    const wrap = opts.wrap;
    const escapeHtml = opts.escapeHtml || textOrEmpty;
    const translate = typeof opts.t === "function" ? opts.t : textOrEmpty;
    const formatMetric = typeof opts.formatMetric === "function" ? opts.formatMetric : textOrEmpty;
    const payload = safeData(opts.summary);
    const samples = Array.isArray(payload.samples) ? payload.samples : [];
    if (!wrap) return;
    if (!samples.length) {
      wrap.innerHTML = `<div class="placeholder">${translate("project_no_lsv")}</div>`;
      return;
    }
    wrap.innerHTML = `
      <table class="lsv-summary-table">
        <thead>
          <tr>
            <th>${escapeHtml(translate("project_lsv_col_sample"))}</th>
            <th>${escapeHtml(translate("project_lsv_col_eta"))}</th>
            <th>${escapeHtml(translate("project_lsv_col_tafel"))}</th>
            <th>${escapeHtml(translate("project_lsv_col_count"))}</th>
            <th>${escapeHtml(translate("project_lsv_col_time"))}</th>
          </tr>
        </thead>
        <tbody>
          ${samples
            .slice(0, 15)
            .map((item) => {
              const eta = item.overpotential_10 !== undefined && item.overpotential_10 !== null
                ? `${formatMetric(item.overpotential_10, 3)} mV`
                : item.potential_10 !== undefined && item.potential_10 !== null
                  ? `${formatMetric(item.potential_10, 3)} V`
                  : "-";
              const tafel = formatMetric(item.tafel_slope, 3);
              const count = item.record_count === undefined || item.record_count === null ? "-" : String(item.record_count);
              const latest = item.latest_time || "-";
              return `
                <tr>
                  <td>${escapeHtml(String(item.sample_name || "-"))}</td>
                  <td>${escapeHtml(eta)}</td>
                  <td>${escapeHtml(tafel)}</td>
                  <td>${escapeHtml(count)}</td>
                  <td>${escapeHtml(String(latest))}</td>
                </tr>
              `;
            })
            .join("")}
        </tbody>
      </table>
    `;
  }

  function collectProjectOutputFiles(history, historyRecordKey) {
    const groups = [];
    const seenGroup = new Map();
    const keyFn = typeof historyRecordKey === "function" ? historyRecordKey : () => "";
    (Array.isArray(history) ? history : []).forEach((record) => {
      const groupKey = String(record.run_id || keyFn(record));
      let group = seenGroup.get(groupKey);
      if (!group) {
        group = {
          key: groupKey,
          title: record.timestamp || groupKey,
          sub: `${record.type || "-"} | ${record.sample_name || record.file_name || "-"}`,
          type: String(record.type || "").toUpperCase(),
          files: [],
        };
        seenGroup.set(groupKey, group);
        groups.push(group);
      }
      if (Array.isArray(record.output_files)) {
        record.output_files.forEach((item) => {
          const text = String(item || "").trim();
          if (text && !group.files.includes(text)) group.files.push(text);
        });
      }
      if (record.summary_path) {
        const text = String(record.summary_path || "").trim();
        if (text && !group.files.includes(text)) group.files.push(text);
      }
    });
    return groups.filter((group) => group.files.length > 0);
  }

  function fileNameOnly(pathText) {
    const safe = String(pathText || "");
    const parts = safe.split(/[/\\]/);
    return parts.length ? parts[parts.length - 1] : safe;
  }

  function renderProjectOutputFiles(options) {
    const opts = options || {};
    const wrap = opts.wrap;
    const escapeHtml = opts.escapeHtml || textOrEmpty;
    const translate = typeof opts.t === "function" ? opts.t : textOrEmpty;
    const outputTypeFilter = String(opts.outputTypeFilter || "").toUpperCase();
    const groups = collectProjectOutputFiles(opts.history, opts.historyRecordKey).filter((group) => {
      if (!outputTypeFilter) return true;
      return String(group.type || "").toUpperCase() === outputTypeFilter;
    });
    if (!wrap) return [];
    if (!groups.length) {
      wrap.innerHTML = `<div class="placeholder">${translate("project_no_output_files")}</div>`;
      return groups;
    }
    wrap.innerHTML = groups
      .map((group, index) => {
        const title = `${translate("project_output_group_prefix")} ${index + 1}`;
        return `
          <div class="output-group">
            <div class="output-group-head">
              <div class="name">${escapeHtml(title)}</div>
              <div class="meta">${escapeHtml(String(group.title || "-"))} | ${escapeHtml(String(group.sub || "-"))}</div>
            </div>
            <div class="output-group-files">
              ${group.files
                .map((filePath) => {
                  const pathText = String(filePath || "");
                  return `
                    <div class="output-file-item">
                      <div class="name">${escapeHtml(fileNameOnly(pathText) || pathText)}</div>
                      <div class="path">${escapeHtml(pathText)}</div>
                      <div class="file-actions">
                        <button class="btn mini" type="button" data-copy-path="${escapeHtml(pathText)}">${escapeHtml(translate("btn_copy_path"))}</button>
                        <button class="btn mini" type="button" data-open-path="${escapeHtml(pathText)}">${escapeHtml(translate("btn_open_file"))}</button>
                        <button class="btn mini" type="button" data-open-dir="${escapeHtml(pathText)}">${escapeHtml(translate("btn_open_dir"))}</button>
                      </div>
                    </div>
                  `;
                })
                .join("")}
            </div>
          </div>
        `;
      })
      .join("");
    if (typeof opts.bindFileActions === "function") opts.bindFileActions(wrap);
    return groups;
  }

  function renderProjectList(options) {
    const opts = options || {};
    const listEl = opts.listEl;
    const escapeHtml = opts.escapeHtml || textOrEmpty;
    const translate = typeof opts.t === "function" ? opts.t : textOrEmpty;
    const items = Array.isArray(opts.items) ? opts.items : [];
    if (!listEl) return;
    if (!items.length) {
      listEl.innerHTML = `<div class="placeholder">${translate("project_empty")}</div>`;
      return;
    }
    listEl.innerHTML = items
      .map((item) => {
        const active = item.id === opts.selectedProjectId ? "active" : "";
        const rawColor = typeof item.color === "string" ? item.color.trim() : "";
        const color = /^#[0-9a-fA-F]{3,8}$/.test(rawColor) ? rawColor : "#155e45";
        const tags = Array.isArray(item.tags) ? item.tags.filter((tag) => String(tag || "").trim()).slice(0, 3) : [];
        const tagsHtml = tags.length
          ? `<div class="project-tags">${tags.map((tag) => `<span>${escapeHtml(String(tag))}</span>`).join("")}</div>`
          : "";
        return `
          <div class="project-item ${active}" data-project-id="${String(item.id || "")}">
            <div class="name"><span class="project-dot" style="background:${escapeHtml(color)}"></span>${escapeHtml(
              String(item.name || "-")
            )}</div>
            <div class="meta">${escapeHtml(translate("project_label_updated"))}: ${escapeHtml(
              String(item.updated_at || "-")
            )} | ${escapeHtml(translate("project_label_files"))}: ${escapeHtml(String(item.file_count ?? 0))}</div>
            ${tagsHtml}
          </div>
        `;
      })
      .join("");
    listEl.querySelectorAll(".project-item").forEach((el) => {
      el.addEventListener("click", () => {
        if (typeof opts.onSelect === "function") opts.onSelect(el.getAttribute("data-project-id") || "");
      });
    });
  }

  window.ElectrochemProjectPage = {
    groupHistoryByRun,
    recordMetricPreview,
    resultMetricEntries,
    recordFileName,
    collectProjectOutputFiles,
    fileNameOnly,
    rawFilesForRecord,
    relatedFilesForRecord,
    renderProjectHeader,
    renderProjectHistory,
    renderProjectHistoryDetail,
    renderProjectLSVSummary,
    renderProjectList,
    renderProjectOutputFiles,
    renderStats,
    setProjectEditForm,
  };
})();
