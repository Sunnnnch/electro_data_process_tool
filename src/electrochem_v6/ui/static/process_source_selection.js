(function () {
  "use strict";

  const PRIMARY_TYPES = ["LSV", "CV", "EIS", "ECSA"];

  function pathKey(pathValue) {
    return String(pathValue || "").replaceAll("\\", "/").toLocaleLowerCase();
  }

  function folderOf(pathValue) {
    const value = String(pathValue || "");
    const splitAt = Math.max(value.lastIndexOf("/"), value.lastIndexOf("\\"));
    return splitAt > 0 ? value.slice(0, splitAt) : "";
  }

  function normalizeCandidate(raw, origin) {
    const item = raw && typeof raw === "object" ? raw : {};
    const path = String(item.path || "").trim();
    if (!path) return null;
    const suggested = String(item.data_type || item.suggested_type || "").toUpperCase();
    const dataType = PRIMARY_TYPES.includes(suggested) ? suggested : "";
    const matchedTypes = Array.isArray(item.matched_types)
      ? item.matched_types.map((value) => String(value || "").toUpperCase()).filter((value) => PRIMARY_TYPES.includes(value))
      : [];
    const status = String(item.status || (dataType ? "recognized" : "unrecognized"));
    const enabled = item.enabled === undefined
      ? Boolean(dataType) && status !== "conflict"
      : item.enabled !== false;
    return {
      path,
      name: String(item.name || path.split(/[\\/]/).pop() || path),
      folder: String(item.folder || folderOf(path)),
      data_type: dataType,
      matched_types: matchedTypes,
      status,
      enabled,
      origin: String(origin || item.origin || "manual"),
    };
  }

  function merge(currentItems, rawItems, options) {
    const opts = options || {};
    const origin = String(opts.origin || "manual");
    const replaceOrigin = Boolean(opts.replaceOrigin);
    const base = (Array.isArray(currentItems) ? currentItems : [])
      .filter((item) => !replaceOrigin || item.origin !== origin)
      .map((item) => ({ ...item }));
    const byPath = new Map(base.map((item, index) => [pathKey(item.path), index]));
    (Array.isArray(rawItems) ? rawItems : []).forEach((raw) => {
      const item = normalizeCandidate(raw, origin);
      if (!item) return;
      const key = pathKey(item.path);
      if (byPath.has(key)) {
        const existing = base[byPath.get(key)];
        if (!existing.data_type && item.data_type) existing.data_type = item.data_type;
        existing.matched_types = Array.from(new Set(existing.matched_types.concat(item.matched_types)));
        return;
      }
      byPath.set(key, base.length);
      base.push(item);
    });
    return base;
  }

  function toInputFiles(items, activeTypes) {
    const active = new Set((activeTypes || []).map((value) => String(value || "").toUpperCase()));
    return (Array.isArray(items) ? items : [])
      .filter((item) => item.enabled && item.data_type && active.has(item.data_type))
      .map((item) => ({ path: item.path, data_type: item.data_type, enabled: true }));
  }

  function preferredFolder(items, fallback) {
    const first = (Array.isArray(items) ? items : []).find((item) => item && item.path);
    return first ? String(first.folder || folderOf(first.path)) : String(fallback || "");
  }

  window.ElectrochemProcessSourceSelection = {
    PRIMARY_TYPES,
    folderOf,
    merge,
    normalizeCandidate,
    preferredFolder,
    toInputFiles,
  };
})();
