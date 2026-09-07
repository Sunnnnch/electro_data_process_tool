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

  function health() {
    return API.fetch("/health");
  }

  function openPath(pathValue, revealOnly) {
    return API.fetch(
      "/api/v1/system/open-path",
      jsonRequest({
        path: pathValue,
        reveal_only: Boolean(revealOnly),
      })
    );
  }

  function selectFolder(initialDir) {
    return API.fetch("/api/v1/system/select-folder", jsonRequest({ initial_dir: initialDir }));
  }

  function selectFile(initialPath, extensions) {
    return API.fetch(
      "/api/v1/system/select-file",
      jsonRequest({ initial_path: initialPath, extensions: extensions || [".txt", ".csv"] })
    );
  }

  function selectFiles(initialPath, extensions) {
    return API.fetch(
      "/api/v1/system/select-files",
      jsonRequest({ initial_path: initialPath, extensions: extensions || [".txt", ".csv"] })
    );
  }

  window.ElectrochemSystemApi = {
    health,
    openPath,
    selectFile,
    selectFiles,
    selectFolder,
  };
})();
