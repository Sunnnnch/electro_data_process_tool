(function () {
  "use strict";

  async function apiFetch(input, init) {
    const options = { ...(init || {}) };
    const request = typeof Request !== "undefined" && input instanceof Request ? input : null;
    const requestHeaders = request ? request.headers : undefined;
    const method = String(options.method === undefined ? (request ? request.method : "GET") : options.method).toUpperCase();
    const signal = options.signal === undefined ? (request ? request.signal : null) : options.signal;
    const headers = new Headers(options.headers || requestHeaders || {});
    const tokenMeta = document.querySelector('meta[name="electrochem-session-token"]');
    const token = tokenMeta ? String(tokenMeta.content || "").trim() : "";
    const urlInput = typeof input === "string" || (typeof URL !== "undefined" && input instanceof URL);
    const targetValue = urlInput ? input : input.url;
    const target = new URL(targetValue, window.location.href);
    if (token && target.origin === window.location.origin && target.pathname.startsWith("/api/")) {
      headers.set("X-Electrochem-Session", token);
    }
    options.headers = headers;
    let response;
    try {
      response = await window.fetch(input, options);
    } catch (error) {
      // Fetch exposes transport failures as TypeError. Only local read APIs get
      // one bounded recovery; never repeat a write, HTTP error, or cancellation.
      // An unrecognized input (including another realm's Request) may carry a
      // write method that this wrapper cannot safely infer.
      const localRead = (urlInput || request !== null) && target.origin === window.location.origin
        && (target.pathname.startsWith("/api/") || target.pathname === "/health")
        && (method === "GET" || method === "HEAD");
      if (!localRead || error?.name !== "TypeError" || signal?.aborted) throw error;
      await new Promise((resolve) => window.setTimeout(resolve, 150));
      if (signal?.aborted) throw signal.reason === undefined ? new DOMException("The operation was aborted.", "AbortError") : signal.reason;
      response = await window.fetch(input, options);
    }
    if (response.ok && typeof window.dispatchEvent === "function" && typeof CustomEvent !== "undefined" && method === "POST"
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
