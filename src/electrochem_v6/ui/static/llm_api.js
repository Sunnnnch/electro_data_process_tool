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

  function getConfig() {
    return API.fetch("/api/v1/llm/config");
  }

  function saveConfig(payload) {
    return API.fetch("/api/v1/llm/config", jsonRequest(payload));
  }

  function testConfig(payload) {
    return API.fetch("/api/v1/llm/test", jsonRequest(payload));
  }

  window.ElectrochemLLMApi = {
    getConfig,
    saveConfig,
    testConfig,
  };
})();
