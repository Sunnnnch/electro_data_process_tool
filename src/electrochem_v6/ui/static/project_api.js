(function () {
  "use strict";

  const API = window.ElectrochemApi || { fetch: (...args) => window.fetch(...args) };

  function buildQuery(params) {
    if (API.buildQuery) return API.buildQuery(params);
    const query = new URLSearchParams();
    Object.entries(params || {}).forEach(([key, value]) => {
      if (value === undefined || value === null || value === "") return;
      if (Array.isArray(value)) {
        value.forEach((item) => query.append(key, String(item)));
        return;
      }
      query.set(key, String(value));
    });
    return query.toString();
  }

  function withQuery(path, params) {
    const query = buildQuery(params);
    return query ? `${path}?${query}` : path;
  }

  function jsonRequest(payload) {
    if (API.jsonRequest) return API.jsonRequest(payload, { method: "POST" });
    return {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    };
  }

  function archivedFlag(includeArchived) {
    return includeArchived ? "1" : "0";
  }

  function projectPath(projectId, suffix) {
    return `/api/v1/projects/${encodeURIComponent(projectId)}${suffix || ""}`;
  }

  function stats(options) {
    const opts = options || {};
    return API.fetch(
      withQuery("/api/v1/stats", {
        project: opts.projectId,
        include_archived: opts.includeArchived === undefined ? undefined : archivedFlag(opts.includeArchived),
      })
    );
  }

  function history(options) {
    const opts = options || {};
    return API.fetch(
      withQuery("/api/v1/history", {
        project: opts.projectId,
        limit: opts.limit,
        cursor: opts.cursor,
        q: opts.q,
        type: opts.type,
        date_from: opts.dateFrom,
        date_to: opts.dateTo,
        include_archived: opts.includeArchived === undefined ? undefined : archivedFlag(opts.includeArchived),
      })
    );
  }

  function historyDetail(historyKey) {
    return API.fetch(`/api/v1/history/${encodeURIComponent(historyKey)}`);
  }

  function listProjects(options) {
    const opts = options || {};
    return API.fetch(withQuery("/api/v1/projects", { status: opts.status || "active" }));
  }

  function createProject(payload) {
    return API.fetch("/api/v1/projects", jsonRequest(payload));
  }

  function deleteProject(projectId) {
    return API.fetch(projectPath(projectId, "/delete"), jsonRequest({}));
  }

  function restoreProject(projectId) {
    return API.fetch(projectPath(projectId, "/restore"), jsonRequest({}));
  }

  function permanentlyDeleteProject(projectId, options) {
    const opts = options || {};
    return API.fetch(
      projectPath(projectId, "/delete-permanent"),
      jsonRequest({ delete_artifacts: opts.deleteArtifacts !== false }),
    );
  }

  function storageSummary() {
    return API.fetch("/api/v1/storage");
  }

  function cleanupStorage() {
    return API.fetch("/api/v1/storage/cleanup", jsonRequest({}));
  }

  function updateProject(projectId, payload) {
    return API.fetch(projectPath(projectId, "/update"), jsonRequest(payload));
  }

  function updateSample(projectId, sampleId, payload) {
    return API.fetch(
      projectPath(projectId, `/samples/${encodeURIComponent(sampleId)}/update`),
      jsonRequest(payload),
    );
  }

  function archiveHistory(historyKey) {
    return API.fetch("/api/v1/history/archive", jsonRequest({ history_key: historyKey }));
  }

  function deleteHistory(historyKey, options) {
    const opts = options || {};
    return API.fetch(
      "/api/v1/history/delete",
      jsonRequest({ history_key: historyKey, delete_artifacts: opts.deleteArtifacts !== false }),
    );
  }

  function lsvSummary(projectId, options) {
    const opts = options || {};
    return API.fetch(
      withQuery(projectPath(projectId, "/lsv-summary"), {
        page: opts.page || 1,
        page_size: opts.pageSize || 15,
        sort: opts.sort || "eta",
      })
    );
  }

  function lsvTargetCurrents(projectId, options) {
    const opts = options || {};
    return API.fetch(
      withQuery(projectPath(projectId, "/lsv-target-currents"), {
        include_archived: archivedFlag(Boolean(opts.includeArchived)),
      })
    );
  }

  function lsvComparePlot(projectId, options) {
    const opts = options || {};
    return API.fetch(
      withQuery(projectPath(projectId, "/lsv-compare-plot"), {
        include_archived: archivedFlag(Boolean(opts.includeArchived)),
        chart_type: opts.chartType,
        metric: opts.metric,
        target_current: opts.targetCurrent,
        sample: Array.isArray(opts.samples) ? opts.samples : [],
      })
    );
  }

  function latestLsvComparePlot(projectId, options) {
    const opts = options || {};
    return API.fetch(
      withQuery(projectPath(projectId, "/lsv-compare-plot/latest"), {
        chart_type: opts.chartType,
        metric: opts.metric,
        target_current: opts.targetCurrent,
      })
    );
  }

  function exportReport(projectId, options) {
    const opts = options || {};
    return API.fetch(
      withQuery(projectPath(projectId, "/report"), {
        include_archived: archivedFlag(Boolean(opts.includeArchived)),
      })
    );
  }

  window.ElectrochemProjectApi = {
    recoveryList: (projectId) => API.fetch(withQuery("/api/v1/process/recovery", { project_id: projectId })),
    recoveryPlan: (payload) => API.fetch("/api/v1/process/recovery/plan", jsonRequest(payload)),
    recoveryResume: (payload) => API.fetch("/api/v1/process/recovery/resume", jsonRequest(payload)),
    compareRecords: (payload) => API.fetch("/api/v1/history/compare", jsonRequest(payload)),
    listRuns: (projectId, options = {}) => API.fetch(withQuery("/api/v1/runs", { project_id: projectId, offset: options.offset || 0, limit: options.limit || 100 })),
    getRun: (runId) => API.fetch(`/api/v1/runs/${encodeURIComponent(runId)}`),
    replayPlan: (runId, payload) => API.fetch(`/api/v1/runs/${encodeURIComponent(runId)}/replay-plan`, jsonRequest(payload)),
    replayRun: (runId, payload) => API.fetch(`/api/v1/runs/${encodeURIComponent(runId)}/replay`, jsonRequest(payload)),
    exportScopedReport: (projectId, payload) => API.fetch(projectPath(projectId, "/report"), jsonRequest(payload)),
    exportRunReport: (runId, payload) => API.fetch(`/api/v1/runs/${encodeURIComponent(runId)}/report`, jsonRequest(payload)),
    archiveHistory,
    cleanupStorage,
    createProject,
    deleteHistory,
    deleteProject,
    exportReport,
    history,
    historyDetail,
    latestLsvComparePlot,
    listProjects,
    lsvComparePlot,
    lsvSummary,
    lsvTargetCurrents,
    permanentlyDeleteProject,
    restoreProject,
    stats,
    storageSummary,
    updateProject,
    updateSample,
  };
})();
