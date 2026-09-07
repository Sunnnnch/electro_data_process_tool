(function () {
  "use strict";

  function translate(ctx, key) {
    return typeof ctx.t === "function" ? ctx.t(key) : String(key || "");
  }

  function setProjectStatus(ctx, text) {
    if (typeof ctx.setProjectStatus === "function") ctx.setProjectStatus(text || "");
  }

  function historyRecordKey(ctx, record) {
    return typeof ctx.historyRecordKey === "function" ? ctx.historyRecordKey(record) : "";
  }

  function getProjectDetailState(ctx) {
    const state = typeof ctx.getProjectDetailState === "function" ? ctx.getProjectDetailState() : null;
    return state && typeof state === "object" ? state : {};
  }

  function getProjectHistory(ctx) {
    const state = getProjectDetailState(ctx);
    return Array.isArray(state.history) ? state.history : [];
  }

  function getSelectedProjectHistoryKey(ctx) {
    return String(typeof ctx.getSelectedProjectHistoryKey === "function" ? ctx.getSelectedProjectHistoryKey() || "" : "");
  }

  function setSelectedProjectHistoryKey(ctx, value) {
    if (typeof ctx.setSelectedProjectHistoryKey === "function") ctx.setSelectedProjectHistoryKey(String(value || ""));
  }

  function getSelectedProjectHistoryRecord(ctx) {
    const key = getSelectedProjectHistoryKey(ctx);
    return getProjectHistory(ctx).find((item) => historyRecordKey(ctx, item) === key) || null;
  }

  function renderProjectHistoryDetail(ctx, record) {
    if (ctx.projectPage && typeof ctx.projectPage.renderProjectHistoryDetail === "function") {
      const sampleRecords = record
        ? getProjectHistory(ctx).filter((item) => {
            if (record.sample_id && item.sample_id) return item.sample_id === record.sample_id;
            return item.project_id === record.project_id && item.sample_name === record.sample_name;
          })
        : [];
      ctx.projectPage.renderProjectHistoryDetail({
        byId: ctx.byId,
        escapeHtml: ctx.escapeHtml,
        onSaveSample: () => saveSelectedProjectSample(ctx),
        record,
        sampleRecords,
        t: ctx.t,
      });
    }
  }

  async function saveSelectedProjectSample(ctx) {
    const record = getSelectedProjectHistoryRecord(ctx);
    if (!record || !record.project_id || !record.sample_id) {
      setProjectStatus(ctx, translate(ctx, "project_sample_save_unavailable"));
      return null;
    }
    const noteEl = typeof ctx.byId === "function" ? ctx.byId("project-sample-note") : null;
    const tagsEl = typeof ctx.byId === "function" ? ctx.byId("project-sample-tags") : null;
    const note = noteEl ? String(noteEl.value || "").trim() : "";
    const tags = tagsEl
      ? String(tagsEl.value || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean)
      : [];
    setProjectStatus(ctx, translate(ctx, "project_sample_save_running"));
    try {
      const response = await ctx.projectApi.updateSample(record.project_id, record.sample_id, { note, tags });
      const payload = await response.json();
      if (!response.ok || payload.status !== "success" || !payload.sample) {
        throw new Error(payload.message || translate(ctx, "project_sample_save_failed"));
      }
      const sample = payload.sample;
      getProjectHistory(ctx).forEach((item) => {
        if (item.sample_id !== sample.id) return;
        item.sample_note = String(sample.note || "");
        item.sample_tags = Array.isArray(sample.tags) ? sample.tags.slice() : [];
      });
      renderProjectHistory(ctx, getProjectHistory(ctx));
      setProjectStatus(ctx, translate(ctx, "project_sample_save_success"));
      return sample;
    } catch (err) {
      setProjectStatus(ctx, `${translate(ctx, "project_sample_save_failed")}: ${err.message}`);
      return null;
    }
  }

  async function loadHistoryDetail(ctx, record) {
    if (!record || record.data !== undefined) return record;
    if (!ctx.projectApi || typeof ctx.projectApi.historyDetail !== "function") return record;
    const key = historyRecordKey(ctx, record);
    const response = await ctx.projectApi.historyDetail(key);
    const payload = await response.json();
    if (!response.ok || payload.status !== "success" || !payload.record) {
      throw new Error(payload.message || translate(ctx, "status_load_failed"));
    }
    Object.assign(record, payload.record);
    return record;
  }

  function renderProjectHistory(ctx, records) {
    const projectPage = ctx.projectPage || {};
    const listEl = typeof ctx.byId === "function" ? ctx.byId("project-history-list") : null;
    const view =
      typeof projectPage.renderProjectHistory === "function"
        ? projectPage.renderProjectHistory({
            escapeHtml: ctx.escapeHtml,
            historyRecordKey: (record) => historyRecordKey(ctx, record),
            listEl,
            onSelect: (index) => selectProjectHistory(ctx, index),
            records: Array.isArray(records) ? records : [],
            selectedKey: getSelectedProjectHistoryKey(ctx),
            autoSelect: ctx.autoSelectHistory !== false,
            detailPanel: typeof ctx.byId === "function" ? ctx.byId("project-history-detail-panel") : null,
            selectedKeys: typeof ctx.getComparedRecordKeys === "function" ? ctx.getComparedRecordKeys() : [],
            onToggleRecord: ctx.onToggleRecord,
            t: ctx.t,
          })
        : { selectedKey: "", selectedRecord: null };
    setSelectedProjectHistoryKey(ctx, view.selectedKey || "");
    renderProjectHistoryDetail(ctx, view.selectedRecord || null);
    if (typeof ctx.onHistoryRendered === "function") ctx.onHistoryRendered(view);
    return view;
  }

  function selectProjectHistory(ctx, index) {
    const history = getProjectHistory(ctx);
    const i = Number(index);
    if (!Number.isInteger(i) || i < 0 || i >= history.length) return null;
    const record = history[i];
    setSelectedProjectHistoryKey(ctx, historyRecordKey(ctx, record));
    renderProjectHistory(ctx, history);
    if (record.data === undefined && ctx.projectApi && typeof ctx.projectApi.historyDetail === "function") {
      loadHistoryDetail(ctx, record)
        .then((detail) => {
          if (getSelectedProjectHistoryKey(ctx) === historyRecordKey(ctx, detail)) {
            renderProjectHistoryDetail(ctx, detail);
          }
        })
        .catch((err) => setProjectStatus(ctx, `${translate(ctx, "status_load_failed")}: ${err.message}`));
    }
    return record;
  }

  function openSelectedProjectHistoryResult(ctx) {
    const record = getSelectedProjectHistoryRecord(ctx);
    if (!record) {
      setProjectStatus(ctx, translate(ctx, "project_open_result_empty"));
      return null;
    }
    const openRecord = (detail) => {
      if (typeof ctx.renderProcessResult === "function" && typeof ctx.buildResultFromHistoryRecord === "function") {
        ctx.renderProcessResult(ctx.buildResultFromHistoryRecord(detail));
      }
      if (typeof ctx.setProcStatus === "function") ctx.setProcStatus(translate(ctx, "status_history_loaded"));
      if (typeof ctx.switchTab === "function") ctx.switchTab("pro");
      setProjectStatus(ctx, translate(ctx, "project_open_result_done"));
      return detail;
    };
    if (record.data === undefined && ctx.projectApi && typeof ctx.projectApi.historyDetail === "function") {
      return loadHistoryDetail(ctx, record)
        .then(openRecord)
        .catch((err) => {
          setProjectStatus(ctx, `${translate(ctx, "status_load_failed")}: ${err.message}`);
          return null;
        });
    }
    return openRecord(record);
  }

  async function mutateSelectedProjectHistory(ctx, options) {
    const opts = options || {};
    const record = getSelectedProjectHistoryRecord(ctx);
    if (!record) {
      setProjectStatus(ctx, translate(ctx, "project_open_result_empty"));
      return null;
    }
    if (typeof ctx.confirm === "function" && !ctx.confirm(translate(ctx, opts.confirmKey))) return null;
    setProjectStatus(ctx, translate(ctx, opts.runningKey));
    try {
      const key = historyRecordKey(ctx, record);
      const resp = await opts.request(key);
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || translate(ctx, opts.failedKey));
      }
      setSelectedProjectHistoryKey(ctx, "");
      if (typeof ctx.loadSelectedProjectDetail === "function") await ctx.loadSelectedProjectDetail();
      if (typeof ctx.loadStatsAndHistory === "function") await ctx.loadStatsAndHistory();
      setProjectStatus(ctx, translate(ctx, opts.successKey));
      return data;
    } catch (err) {
      setProjectStatus(ctx, `${translate(ctx, opts.failedKey)}: ${err.message}`);
      return null;
    }
  }

  async function archiveSelectedProjectHistory(ctx) {
    return mutateSelectedProjectHistory(ctx, {
      confirmKey: "project_history_confirm_archive",
      failedKey: "project_history_archive_failed",
      request: (key) => ctx.projectApi.archiveHistory(key),
      runningKey: "project_history_archive_running",
      successKey: "project_history_archive_success",
    });
  }

  async function deleteSelectedProjectHistory(ctx) {
    return mutateSelectedProjectHistory(ctx, {
      confirmKey: "project_history_confirm_delete",
      failedKey: "project_history_delete_failed",
      request: (key) => ctx.projectApi.deleteHistory(key),
      runningKey: "project_history_delete_running",
      successKey: "project_history_delete_success",
    });
  }

  window.ElectrochemProjectHistoryWorkspace = {
    archiveSelectedProjectHistory,
    deleteSelectedProjectHistory,
    getProjectHistory,
    getSelectedProjectHistoryRecord,
    openSelectedProjectHistoryResult,
    renderProjectHistory,
    renderProjectHistoryDetail,
    saveSelectedProjectSample,
    selectProjectHistory,
  };
})();
