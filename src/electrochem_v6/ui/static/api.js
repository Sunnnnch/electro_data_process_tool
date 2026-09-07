(function () {
  "use strict";

  async function apiFetch(input, init) {
    const options = { ...(init || {}) };
    const requestHeaders = typeof Request !== "undefined" && input instanceof Request ? input.headers : undefined;
    const headers = new Headers(options.headers || requestHeaders || {});
    const tokenMeta = document.querySelector('meta[name="electrochem-session-token"]');
    const token = tokenMeta ? String(tokenMeta.content || "").trim() : "";
    const targetValue =
      typeof input === "string" || (typeof URL !== "undefined" && input instanceof URL)
        ? input
        : input.url;
    const target = new URL(targetValue, window.location.href);
    if (token && target.origin === window.location.origin && target.pathname.startsWith("/api/")) {
      headers.set("X-Electrochem-Session", token);
    }
    options.headers = headers;
    const response = await window.fetch(input, options);
    if (response.ok && typeof window.dispatchEvent === "function" && typeof CustomEvent !== "undefined" && String(options.method || "GET").toUpperCase() === "POST"
        && /\/api\/v1\/(?:process\/jobs|agent\/jobs|tasks\/[^/]+\/cancel|runs\/[^/]+\/replay|process\/recovery\/resume)(?:\/[^/]+\/cancel)?$/.test(target.pathname)) {
      window.dispatchEvent(new CustomEvent("electrochem:tasks-changed"));
    }
    return response;
  }

  function jsonHeaders(extraHeaders) {
    return {
      "Content-Type": "application/json",
      ...(extraHeaders || {}),
    };
  }

  function jsonRequest(payload, init) {
    const options = init || {};
    return {
      ...options,
      headers: jsonHeaders(options.headers),
      body: JSON.stringify(payload || {}),
    };
  }

  function buildQuery(params) {
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

  window.ElectrochemApi = {
    fetch: apiFetch,
    jsonRequest,
    buildQuery,
  };
})();
