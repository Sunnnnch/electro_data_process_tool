(function () {
  "use strict";

  const STORAGE_KEY = "electrochem_v6_appearance";
  const LEGACY_STORAGE_KEY = "electrochem_v6_theme";
  const DEFAULTS = Object.freeze({ version: 1, theme: "lab", fontSize: "standard", density: "comfortable", grid: false, chartBackground: "theme" });
  const THEMES = new Set(["ocean", "lab", "dark", "pixel", "system"]);
  const FONT_SIZES = { standard: ["14px", "1", "0px"], large: ["16px", "1.142857", "4px"], "extra-large": ["18px", "1.285714", "8px"] };
  let preferences = { ...DEFAULTS };
  let currentTheme = DEFAULTS.theme;
  let initialized = false;
  let persistent = true;
  let mediaQuery;
  let bodyObserver;

  function normalize(value) {
    const raw = value && typeof value === "object" && !Array.isArray(value) ? value : {};
    return {
      version: 1,
      theme: THEMES.has(raw.theme) ? raw.theme : DEFAULTS.theme,
      fontSize: Object.hasOwn(FONT_SIZES, raw.fontSize) ? raw.fontSize : DEFAULTS.fontSize,
      density: ["comfortable", "compact"].includes(raw.density) ? raw.density : DEFAULTS.density,
      grid: typeof raw.grid === "boolean" ? raw.grid : DEFAULTS.grid,
      chartBackground: ["theme", "paper"].includes(raw.chartBackground) ? raw.chartBackground : DEFAULTS.chartBackground,
    };
  }

  function getPreferences() { return { ...preferences }; }

  function ensureMediaQuery() {
    if (mediaQuery || typeof window.matchMedia !== "function") return;
    mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const changed = () => { if (preferences.theme === "system") render(); };
    if (typeof mediaQuery.addEventListener === "function") mediaQuery.addEventListener("change", changed);
    else if (typeof mediaQuery.addListener === "function") mediaQuery.addListener(changed);
  }

  function applyToElement(element) {
    if (!element) return;
    Object.assign(element.dataset, { theme: currentTheme, density: preferences.density, fontSize: preferences.fontSize, grid: String(preferences.grid), chartBackground: preferences.chartBackground });
    if (element.style) {
      const [size, scale, space] = FONT_SIZES[preferences.fontSize];
      element.style.setProperty("--ui-font-size", size);
      element.style.setProperty("--ui-font-scale", scale);
      element.style.setProperty("--font-space", space);
    }
  }

  function render() {
    ensureMediaQuery();
    currentTheme = preferences.theme === "system" ? (mediaQuery && mediaQuery.matches ? "dark" : "lab") : preferences.theme;
    applyToElement(document.documentElement);
    applyToElement(document.body);
    const select = document.getElementById("theme-select");
    if (select) select.value = preferences.theme;
    if (typeof window.dispatchEvent === "function" && typeof window.CustomEvent === "function") {
      window.dispatchEvent(new CustomEvent("electrochem:appearance-changed", { detail: { theme: currentTheme, prefs: getPreferences(), persisted: persistent } }));
    }
    return currentTheme;
  }

  function persist() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
      persistent = true;
    } catch (_error) { persistent = false; }
  }

  function apply(themeName) {
    preferences = normalize({ ...preferences, theme: themeName });
    return render();
  }

  function update(patch) {
    const safe = patch && typeof patch === "object" && !Array.isArray(patch) ? patch : {};
    preferences = normalize({ ...preferences, ...safe });
    persist();
    render();
    return getPreferences();
  }

  function save(themeName) {
    update({ theme: themeName });
    return currentTheme;
  }

  function reset() { return update(DEFAULTS); }

  function init(defaultTheme) {
    let stored;
    let legacy;
    try {
      stored = window.localStorage.getItem(STORAGE_KEY);
      legacy = window.localStorage.getItem(LEGACY_STORAGE_KEY);
      persistent = true;
    } catch (_error) {
      persistent = false;
      if (!initialized) preferences = normalize({ theme: defaultTheme || DEFAULTS.theme });
      initialized = true;
      return render();
    }
    let parsed;
    try { parsed = stored ? JSON.parse(stored) : null; } catch (_error) { parsed = null; }
    preferences = parsed && parsed.version === 1 ? normalize(parsed) : normalize({ theme: THEMES.has(legacy) ? legacy : defaultTheme || DEFAULTS.theme });
    initialized = true;
    persist();
    return render();
  }

  window.ElectrochemTheme = {
    apply,
    defaultTheme: DEFAULTS.theme,
    defaults: DEFAULTS,
    getTheme: () => currentTheme,
    getPreferences,
    init,
    isPersistent: () => persistent,
    legacyStorageKey: LEGACY_STORAGE_KEY,
    reset,
    save,
    storageKey: STORAGE_KEY,
    update,
  };

  // Load before the stylesheet: resolve stored appearance before the first paint.
  if (typeof document !== "undefined" && document.documentElement) {
    init();
    if (!document.body && typeof MutationObserver === "function") {
      bodyObserver = new MutationObserver(() => {
        if (!document.body) return;
        applyToElement(document.body);
        bodyObserver.disconnect();
      });
      bodyObserver.observe(document.documentElement, { childList: true });
    }
  }
})();
