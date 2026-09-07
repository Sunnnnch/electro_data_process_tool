(function () {
  "use strict";

  function fallbackEscape(text) {
    return String(text || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function htmlEscape(ctx, text) {
    return typeof ctx.escapeHtml === "function" ? ctx.escapeHtml(text) : fallbackEscape(text);
  }

  function translate(ctx, key) {
    return typeof ctx.t === "function" ? ctx.t(key) : String(key || "");
  }

  function element(ctx, id) {
    return typeof ctx.byId === "function" ? ctx.byId(id) : null;
  }

  function setText(ctx, id, text) {
    const target = element(ctx, id);
    if (target) target.textContent = text;
  }

  function setHtml(ctx, id, html) {
    const target = element(ctx, id);
    if (target) target.innerHTML = html;
  }

  function setHidden(ctx, id, hidden) {
    const target = element(ctx, id);
    if (target) target.classList.toggle("hidden", Boolean(hidden));
  }

  function setActionList(target, enabled) {
    if (!target) return;
    target.classList.toggle("action-list", Boolean(enabled));
  }

  function bindOutputActions(ctx, target) {
    if (target && typeof ctx.bindFileActions === "function") {
      ctx.bindFileActions(target);
    }
  }

  function updateStepState(ctx) {
    if (typeof ctx.updateProcessStepState === "function") {
      ctx.updateProcessStepState();
    }
  }

  function openCurrentResultTab(ctx) {
    if (typeof ctx.setResultTab === "function") {
      ctx.setResultTab("current");
    }
  }

  function renderOutputFiles(ctx, files) {
    const filesEl = element(ctx, "proc-result-files");
    if (!filesEl) return;
    if (!files.length) {
      setActionList(filesEl, false);
      filesEl.innerHTML = "<li>-</li>";
      return;
    }
    setActionList(filesEl, true);
    filesEl.innerHTML = files
      .map((file) => {
        const path = htmlEscape(ctx, file.path);
        return `
          <li class="output-file-item proc-output-file-item">
            <div class="name">${htmlEscape(ctx, file.fileName)}</div>
            <div class="path">${path}</div>
            <div class="file-actions">
              <button class="btn mini" type="button" data-copy-path="${path}">${htmlEscape(ctx, translate(ctx, "btn_copy_path"))}</button>
              <button class="btn mini" type="button" data-open-path="${path}">${htmlEscape(ctx, translate(ctx, "btn_open_file"))}</button>
              <button class="btn mini" type="button" data-open-dir="${path}">${htmlEscape(ctx, translate(ctx, "btn_open_dir"))}</button>
            </div>
          </li>
        `;
      })
      .join("");
    bindOutputActions(ctx, filesEl);
  }

  function renderQualityItems(ctx, items) {
    setHtml(
      ctx,
      "proc-result-quality",
      items.length
        ? items
            .map((item) => {
              const label = item.labelKey ? translate(ctx, item.labelKey) : item.label;
              return `<li>${htmlEscape(ctx, `${label}: ${item.value}`)}</li>`;
            })
            .join("")
        : "<li>-</li>",
    );
  }

  function renderSkippedErrors(ctx, items) {
    if (!items.length) {
      setHidden(ctx, "proc-result-skipped-wrap", true);
      setHtml(ctx, "proc-result-skipped", "");
      return;
    }
    setHidden(ctx, "proc-result-skipped-wrap", false);
    setHtml(
      ctx,
      "proc-result-skipped",
      items
        .map((item) => {
          const errType = htmlEscape(ctx, item.type || "");
          const errMsg = htmlEscape(ctx, item.error || "");
          return `<li class="skipped-item"><span class="skipped-type">[${errType}]</span> <strong>${htmlEscape(ctx, item.fileName)}</strong><span class="skipped-msg">${errMsg}</span></li>`;
        })
        .join(""),
    );
  }

  function renderPlaceholder(ctx) {
    setText(ctx, "proc-result-summary", translate(ctx, "result_empty"));
    setText(ctx, "proc-result-types", "-");
    const filesEl = element(ctx, "proc-result-files");
    setActionList(filesEl, false);
    if (filesEl) filesEl.innerHTML = "<li>-</li>";
    setHtml(ctx, "proc-result-quality", "<li>-</li>");
    setHidden(ctx, "proc-result-skipped-wrap", true);
    setHtml(ctx, "proc-result-skipped", "");
    setHidden(ctx, "proc-result-error-wrap", true);
    setText(ctx, "proc-result-error", "-");
    updateStepState(ctx);
    return { hasProcessResult: false, processRunState: "pending" };
  }

  function buildResultView(ctx, result) {
    if (!ctx.processResultModel || typeof ctx.processResultModel.buildResultView !== "function") {
      return {
        dataTypes: [],
        outputFiles: [],
        qualityItems: [],
        skippedErrors: [],
        summary: "",
      };
    }
    return ctx.processResultModel.buildResultView(result);
  }

  function renderResult(ctx, result) {
    openCurrentResultTab(ctx);
    const panel = element(ctx, "proc-result-panel");
    if (panel) panel.classList.remove("hidden");
    setHidden(ctx, "proc-result-error-wrap", true);
    setText(ctx, "proc-result-error", "-");

    const view = buildResultView(ctx, result);
    setText(ctx, "proc-result-summary", view.summary || translate(ctx, "result_empty"));
    setText(ctx, "proc-result-types", view.dataTypes.length ? view.dataTypes.join(", ") : "-");
    renderOutputFiles(ctx, view.outputFiles);
    renderQualityItems(ctx, view.qualityItems);
    renderSkippedErrors(ctx, view.skippedErrors);
    updateStepState(ctx);
    return { hasProcessResult: true, processRunState: "complete", view };
  }

  function renderError(ctx, message) {
    openCurrentResultTab(ctx);
    const panel = element(ctx, "proc-result-panel");
    if (panel) panel.classList.remove("hidden");
    setText(ctx, "proc-result-summary", translate(ctx, "proc_failed"));
    setText(ctx, "proc-result-types", "-");
    const filesEl = element(ctx, "proc-result-files");
    setActionList(filesEl, false);
    if (filesEl) filesEl.innerHTML = "<li>-</li>";
    setHtml(ctx, "proc-result-quality", "<li>-</li>");
    setHidden(ctx, "proc-result-skipped-wrap", true);
    setHtml(ctx, "proc-result-skipped", "");
    setHidden(ctx, "proc-result-error-wrap", false);
    setText(ctx, "proc-result-error", message || translate(ctx, "proc_failed"));
    updateStepState(ctx);
    return { hasProcessResult: true, processRunState: "issue" };
  }

  function historyRecordKey(record) {
    if (!record) return "";
    if (record.record_key) return String(record.record_key);
    const file = record.file_path || record.file_name || record.sample_name || "";
    return `${record.timestamp || ""}|${record.type || ""}|${file}`;
  }

  function buildResultFromHistoryRecord(ctx, record) {
    if (!ctx.processResultModel || typeof ctx.processResultModel.buildResultFromHistoryRecord !== "function") {
      return {};
    }
    return ctx.processResultModel.buildResultFromHistoryRecord(record, translate(ctx, "result_from_history"));
  }

  function setActiveHistoryItem(ctx, selectedKey) {
    const listEl = element(ctx, "history-list");
    if (!listEl) return;
    listEl.querySelectorAll(".history-item").forEach((item) => {
      item.classList.toggle("active", item.dataset.key === selectedKey);
    });
  }

  function renderHistory(ctx, records) {
    const listEl = element(ctx, "history-list");
    const normalized = Array.isArray(records) ? records : [];
    if (!listEl) return { records: normalized };
    if (!normalized.length) {
      listEl.innerHTML = `<div class="placeholder">${htmlEscape(ctx, translate(ctx, "no_history"))}</div>`;
      return { records: normalized };
    }
    const selectedKey = ctx.selectedKey || "";
    listEl.innerHTML = normalized
      .slice(0, 20)
      .map((record, index) => {
        const key = historyRecordKey(record);
        const active = key === selectedKey ? "active" : "";
        const name = record.sample_name || record.file_name || record.file_path || "unknown";
        return `
          <div class="history-item ${active}" data-index="${index}" data-key="${htmlEscape(ctx, key)}">
            <div class="name">${htmlEscape(ctx, name)}</div>
            <div class="meta">${htmlEscape(ctx, record.type || "-")} | ${htmlEscape(ctx, record.timestamp || "")}</div>
          </div>
        `;
      })
      .join("");
    listEl.querySelectorAll(".history-item").forEach((item) => {
      item.addEventListener("click", () => {
        if (typeof ctx.onSelect === "function") ctx.onSelect(item.dataset.index);
      });
    });
    return { records: normalized };
  }

  window.ElectrochemProcessResultPage = {
    buildResultFromHistoryRecord,
    historyRecordKey,
    renderError,
    renderHistory,
    renderPlaceholder,
    renderResult,
    setActiveHistoryItem,
  };
})();
