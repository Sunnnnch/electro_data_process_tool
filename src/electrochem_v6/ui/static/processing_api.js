(function () {
  "use strict";

  const API = window.ElectrochemApi || { fetch: (...args) => window.fetch(...args) };

  function jsonRequest(payload) {
    if (API.jsonRequest) return API.jsonRequest(payload, { method: "POST" });
    return {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    };
  }

  function listTemplates() {
    return API.fetch("/api/v1/process/templates");
  }

  function saveTemplate(payload) {
    return API.fetch("/api/v1/process/templates", jsonRequest(payload));
  }

  function deleteTemplate(name) {
    return API.fetch(`/api/v1/process/templates/${encodeURIComponent(name)}/delete`, jsonRequest({}));
  }

  function preflight(payload) {
    return API.fetch("/api/v1/process/preflight", jsonRequest(payload));
  }

  function discoverInputs(payload) {
    return API.fetch("/api/v1/process/discover-inputs", jsonRequest(payload));
  }

  function exportDiagnostics() {
    return API.fetch("/api/v1/diagnostics/export", { method: "POST" });
  }

  function runProcess(payload) {
    return API.fetch("/api/v1/process", jsonRequest(payload));
  }

  function submitProcessJob(payload) {
    return API.fetch("/api/v1/process/jobs", jsonRequest(payload));
  }

  function getProcessJob(jobId) {
    return API.fetch(`/api/v1/process/jobs/${encodeURIComponent(jobId)}`);
  }

  function cancelProcessJob(jobId) {
    return API.fetch(`/api/v1/process/jobs/${encodeURIComponent(jobId)}/cancel`, jsonRequest({}));
  }

  window.ElectrochemProcessingApi = {
    deleteTemplate,
    discoverInputs,
    exportDiagnostics,
    listTemplates,
    preflight,
    cancelProcessJob,
    getProcessJob,
    runProcess,
    saveTemplate,
    submitProcessJob,
  };
})();
