(function () {
  "use strict";

  function byId(id) {
    if (!globalThis.document || typeof document.getElementById !== "function") return null;
    return document.getElementById(id);
  }

  function textValue(id) {
    const el = byId(id);
    return String((el && el.value) || "").trim();
  }

  function boolValue(id) {
    const el = byId(id);
    return Boolean(el && el.checked);
  }

  function numberValue(id) {
    const raw = textValue(id);
    if (!raw) return undefined;
    const value = Number(raw);
    return Number.isFinite(value) ? value : undefined;
  }

  function escapeHtml(text) {
    return String(text || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function fileNameOnly(pathText) {
    const safe = String(pathText || "").trim();
    return safe.split(/[\\/]/).pop() || safe;
  }

  window.ElectrochemUiCore = {
    boolValue,
    byId,
    escapeHtml,
    fileNameOnly,
    numberValue,
    textValue,
  };
})();
