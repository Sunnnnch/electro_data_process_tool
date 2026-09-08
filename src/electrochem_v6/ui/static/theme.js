(function () {
  "use strict";

  const STORAGE_KEY = "electrochem_v6_appearance";
  const LEGACY_STORAGE_KEY = "electrochem_v6_theme";
  const STYLES = Object.freeze(["modern", "paper", "soft", "pixel"]);
  const LEGACY_THEMES = ["lab", "ocean", "dark", "pixel"];
  const DEFAULT_PALETTES = Object.freeze({ modern: "lab", paper: "cream", soft: "mist", pixel: "cream" });
  const DEFAULTS = Object.freeze({
    version: 2, style: "modern", fontSize: "standard", density: "comfortable", grid: false, chartBackground: "theme",
    paletteByStyle: Object.freeze(Object.fromEntries(STYLES.map((style) => [style, Object.freeze({ id: DEFAULT_PALETTES[style] })]))),
  });
  const FONT_SIZES = { standard: ["14px", "1", "0px"], large: ["16px", "1.142857", "4px"], "extra-large": ["18px", "1.285714", "8px"] };
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const object = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
  const paletteEngine = () => window.ElectrochemPalette;
  let preferences = clone(DEFAULTS);
  let currentTheme = "lab";
  let initialized = false;
  let persistent = true;
  let mediaQuery;
  let bodyObserver;

  function selection(value, style) {
    const engine = paletteEngine();
    const normalized = engine && engine.normalize(value, style);
    if (!normalized || normalized.id === "default") return { id: DEFAULT_PALETTES[style] };
    return normalized.id === "custom" ? normalized : { id: normalized.id };
  }

  function normalizeRecovered(value) {
    if (!Array.isArray(value) || !paletteEngine()) return [];
    const seen = new Set();
    const ids = new Set();
    const recovered = [];
    for (const entry of value) {
      const raw = object(entry);
      if (!/^legacy-(lab|ocean|dark|pixel|classic)$/.test(raw.id) || ids.has(raw.id)) continue;
      const saved = raw.id === "legacy-classic" && Object.hasOwn(raw, "selection")
        ? paletteEngine().normalize(raw.selection, "modern") : null;
      if (raw.id === "legacy-classic" && Object.hasOwn(raw, "selection") && !saved) continue;
      const restored = saved ? selection(saved, "modern") : null;
      const colors = saved
        ? paletteEngine().normalize(saved.id === "system" ? "lab" : restored, "modern")
        : paletteEngine().normalize({ id: "custom", colors: raw.colors });
      if (!colors) continue;
      const key = restored && restored.id !== "custom" ? restored.id : JSON.stringify(colors.colors);
      if (seen.has(key)) continue;
      seen.add(key);
      ids.add(raw.id);
      const record = { id: raw.id, labelKey: `appearance_palette_recovered_${raw.id.slice(7)}`, colors: colors.colors };
      if (restored) record.selection = restored;
      recovered.push(record);
    }
    return recovered;
  }

  function normalize(value) {
    const raw = object(value);
    const savedPalettes = object(raw.paletteByStyle);
    const normalized = {
      version: 2,
      style: raw.style === "classic" ? "pixel" : STYLES.includes(raw.style) ? raw.style : DEFAULTS.style,
      fontSize: Object.hasOwn(FONT_SIZES, raw.fontSize) ? raw.fontSize : DEFAULTS.fontSize,
      density: ["comfortable", "compact"].includes(raw.density) ? raw.density : DEFAULTS.density,
      grid: typeof raw.grid === "boolean" ? raw.grid : DEFAULTS.grid,
      chartBackground: ["theme", "paper"].includes(raw.chartBackground) ? raw.chartBackground : DEFAULTS.chartBackground,
      paletteByStyle: Object.fromEntries(STYLES.map((style) => [style, selection(savedPalettes[style], style)])),
    };
    let recovery = Array.isArray(raw.recoveredPalettes) ? raw.recoveredPalettes : [];
    const engine = paletteEngine();
    const classic = engine && engine.normalize(savedPalettes.classic, "modern");
    if (classic || raw.style === "classic") {
      const former = selection(classic, "modern");
      // The existing Pixel palette always wins. Only an absent/invalid choice
      // receives Classic's palette when its active style migrates to Pixel.
      if (raw.style === "classic" && engine && !engine.normalize(savedPalettes.pixel, "pixel")) {
        normalized.paletteByStyle.pixel = former;
      }
      // Inactive Classic's default Lab choice was populated for every user.
      // Keep meaningful saved choices, without adding a default recovery card.
      const alreadyRecovered = recovery.some((entry) => object(entry).id === "legacy-classic");
      if ((raw.style === "classic" || former.id !== "lab") && (classic || !alreadyRecovered)) {
        recovery = recovery.filter((entry) => object(entry).id !== "legacy-classic");
        recovery.push({ id: "legacy-classic", selection: former });
      }
    }
    const recovered = normalizeRecovered(recovery);
    if (recovered.length) normalized.recoveredPalettes = recovered;
    return normalized;
  }

  function migrateLegacy(value) {
    const raw = object(value);
    const theme = [...LEGACY_THEMES, "system"].includes(raw.theme) ? raw.theme : "lab";
    const engine = paletteEngine();
    const oldPalettes = object(raw.paletteByTheme);
    const validPalettes = {};
    if (engine) {
      for (const name of LEGACY_THEMES) {
        const candidate = engine.normalize(oldPalettes[name], name);
        // System was not a palette in v1 and cannot be read from an old map.
        if (candidate && !["default", "system"].includes(candidate.id)) validPalettes[name] = candidate;
      }
    }
    let modern;
    if (theme === "system") modern = { id: "system" };
    else if (theme !== "pixel") modern = validPalettes[theme] || { id: theme };
    else {
      // v1 had no last-inactive-modern-theme field. Use a stable Lab/Ocean/Dark
      // preference order and recover all other saved custom colors below.
      const savedModern = ["lab", "ocean", "dark"].find((name) => validPalettes[name]);
      modern = savedModern ? validPalettes[savedModern] : { id: "lab" };
    }
    const paletteByStyle = { modern, pixel: validPalettes.pixel || { id: "cream" } };
    const selectedColors = new Set();
    if (engine) {
      for (const [style, saved] of Object.entries(paletteByStyle)) {
        const resolved = engine.normalize(saved, style);
        if (resolved && resolved.colors) selectedColors.add(JSON.stringify(resolved.colors));
      }
    }
    const recoveredPalettes = [];
    for (const name of LEGACY_THEMES) {
      const saved = validPalettes[name];
      if (!saved || saved.id !== "custom" || selectedColors.has(JSON.stringify(saved.colors))) continue;
      recoveredPalettes.push({ id: `legacy-${name}`, colors: saved.colors });
    }
    return normalize({ ...raw, style: theme === "pixel" ? "pixel" : "modern", paletteByStyle, recoveredPalettes });
  }

  function getPreferences() { return clone(preferences); }
  function getStyle() { return preferences.style; }
  function getRecoveredPalettes() { return clone(preferences.recoveredPalettes || []); }
  function getPaletteSelection() { return clone(preferences.paletteByStyle[preferences.style]); }

  function getPalette() {
    const saved = getPaletteSelection();
    const engine = paletteEngine();
    if (saved.id === "system") saved.id = mediaQuery && mediaQuery.matches ? "dark" : "lab";
    return engine ? engine.normalize(saved, preferences.style) : { id: saved.id, colors: {} };
  }

  function setPalette(value) {
    const paletteByStyle = { ...preferences.paletteByStyle, [preferences.style]: selection(value, preferences.style) };
    update({ paletteByStyle });
    return getPalette();
  }

  function resetPalette() { return setPalette(DEFAULT_PALETTES[preferences.style]); }
  function setStyle(style) { update({ style }); return getStyle(); }

  function ensureMediaQuery() {
    if (mediaQuery || typeof window.matchMedia !== "function") return;
    mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const changed = () => { if (getPaletteSelection().id === "system") render(); };
    if (typeof mediaQuery.addEventListener === "function") mediaQuery.addEventListener("change", changed);
    else if (typeof mediaQuery.addListener === "function") mediaQuery.addListener(changed);
  }

  function applyToElement(element) {
    if (!element) return;
    Object.assign(element.dataset, {
      theme: currentTheme, style: preferences.style, density: preferences.density,
      fontSize: preferences.fontSize, grid: String(preferences.grid), chartBackground: preferences.chartBackground,
      paletteSelection: getPaletteSelection().id,
    });
    if (element.style) {
      const [size, scale, space] = FONT_SIZES[preferences.fontSize];
      element.style.setProperty("--ui-font-size", size);
      element.style.setProperty("--ui-font-scale", scale);
      element.style.setProperty("--font-space", space);
      if (paletteEngine()) paletteEngine().apply(element, getPalette(), preferences.chartBackground);
    }
  }

  function legacySelection() {
    const saved = getPaletteSelection();
    if (saved.id === "system") return "system";
    return preferences.style === "pixel" ? "pixel" : currentTheme === "pixel" ? "lab" : currentTheme;
  }

  function render() {
    ensureMediaQuery();
    const engine = paletteEngine();
    currentTheme = engine ? engine.baseTheme(getPalette(), preferences.style) : "lab";
    applyToElement(document.documentElement);
    applyToElement(document.body);
    const select = document.getElementById("theme-select");
    if (select) select.value = legacySelection();
    if (typeof window.dispatchEvent === "function" && typeof window.CustomEvent === "function") {
      window.dispatchEvent(new CustomEvent("electrochem:appearance-changed", {
        detail: { theme: currentTheme, style: preferences.style, palette: getPalette(), prefs: getPreferences(), persisted: persistent },
      }));
    }
    return currentTheme;
  }

  function persist() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
      persistent = true;
    } catch (_error) { persistent = false; }
  }

  function legacyPatch(themeName, base) {
    const theme = [...LEGACY_THEMES, "system"].includes(themeName) ? themeName : "lab";
    const style = theme === "pixel" ? "pixel" : "modern";
    return {
      style,
      paletteByStyle: { ...base.paletteByStyle, [style]: { id: theme === "pixel" ? "cream" : theme } },
    };
  }

  function apply(themeName) {
    preferences = normalize({ ...preferences, ...legacyPatch(themeName, preferences) });
    return render();
  }

  function update(patch) {
    const safe = object(patch);
    const base = Object.hasOwn(safe, "theme") ? { ...preferences, ...legacyPatch(safe.theme, preferences) } : preferences;
    preferences = normalize({ ...base, ...safe });
    persist();
    render();
    return getPreferences();
  }

  function save(themeName) { update({ theme: themeName }); return currentTheme; }
  function reset() { return update({ ...clone(DEFAULTS), recoveredPalettes: [] }); }

  function init(defaultTheme) {
    let stored;
    let legacy;
    try {
      stored = window.localStorage.getItem(STORAGE_KEY);
      legacy = window.localStorage.getItem(LEGACY_STORAGE_KEY);
      persistent = true;
    } catch (_error) {
      persistent = false;
      if (!initialized) preferences = migrateLegacy({ theme: defaultTheme || "lab" });
      initialized = true;
      return render();
    }
    let parsed;
    try { parsed = stored ? JSON.parse(stored) : null; } catch (_error) { parsed = null; }
    if (parsed && parsed.version === 2) preferences = normalize(parsed);
    else if (parsed && parsed.version === 1) preferences = migrateLegacy(parsed);
    else preferences = migrateLegacy({ theme: [...LEGACY_THEMES, "system"].includes(legacy) ? legacy : defaultTheme || "lab" });
    initialized = true;
    persist();
    return render();
  }

  window.ElectrochemTheme = {
    apply, defaultTheme: "lab", defaultStyle: "modern", defaults: DEFAULTS, styles: STYLES,
    getTheme: () => currentTheme, getStyle, getPreferences, getPalette, getPaletteSelection, getRecoveredPalettes,
    init, isPersistent: () => persistent, legacyStorageKey: LEGACY_STORAGE_KEY,
    reset, resetPalette, save, setPalette, setStyle, storageKey: STORAGE_KEY, update,
  };

  // Migrate and resolve saved appearance before the stylesheet and first paint.
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
