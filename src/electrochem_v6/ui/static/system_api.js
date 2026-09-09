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
    const native = nativeSelection("select_folder", [initialDir || ""]);
    if (native) return native;
    return API.fetch("/api/v1/system/select-folder", jsonRequest({ initial_dir: initialDir }));
  }

  function selectFile(initialPath, extensions) {
    const native = nativeSelection("select_file", [initialPath || "", extensions || [".txt", ".csv"]]);
    if (native) return native;
    return API.fetch(
      "/api/v1/system/select-file",
      jsonRequest({ initial_path: initialPath, extensions: extensions || [".txt", ".csv"] })
    );
  }

  function selectFiles(initialPath, extensions) {
    const native = nativeSelection("select_files", [initialPath || "", extensions || [".txt", ".csv"]]);
    if (native) return native;
    return API.fetch(
      "/api/v1/system/select-files",
      jsonRequest({ initial_path: initialPath, extensions: extensions || [".txt", ".csv"] })
    );
  }

  function nativeSelection(method, args) {
    const native = window.pywebview && window.pywebview.api;
    if (!native || typeof native[method] !== "function") return null;
    // Native dialogs marshal onto Cocoa's main thread. Keep the same response
    // contract as the HTTP picker so all existing selection controls use it.
    return Promise.resolve().then(() => native[method](...args)).then((payload) =>
      new Response(JSON.stringify(payload), {
        status: payload && payload.status === "success" ? 200 : 400,
        headers: { "Content-Type": "application/json" },
      })
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
