(function () {
  "use strict";

  // A palette changes semantic colors only. The selected theme continues to own
  // its geometry, shadows, spacing, font size and optional background grid.
  const COLOR_KEYS = Object.freeze(["background", "surface", "primary", "text", "titlebar"]);
  const presetData = [
    ["lab", "#EEF2F5", "#FFFFFF", "#086959", "#1D2D3B", "#C6D6E3"],
    ["ocean", "#102A3A", "#F8FBFD", "#135C7E", "#152D40", "#244F63"],
    ["dark", "#10191E", "#1A282E", "#67D5B0", "#EDF4F6", "#334C59"],
    ["cream", "#E7E0D4", "#FAF7EF", "#31539A", "#282B33", "#D6C8AE"],
    ["slate", "#1B2432", "#29364A", "#9BBBE7", "#E9EFF7", "#425877"],
    ["amber", "#1C1915", "#2A241C", "#EDBB66", "#F4E9D4", "#5A452B"],
    ["mist", "#DEE5ED", "#F5F7FA", "#365C88", "#27374A", "#B4C5D9"],
    ["handheld", "#CED39A", "#E8EAC8", "#3F5631", "#303A24", "#A5B16C"],
    ["violet", "#25212F", "#352F43", "#CDB2EE", "#F0EAF7", "#574969"],
  ];
  const presets = Object.freeze(presetData.map(([id, ...values]) => Object.freeze({
    id, colors: Object.freeze(Object.fromEntries(COLOR_KEYS.map((key, index) => [key, values[index]]))),
  })));
  const presetById = new Map(presets.map((preset) => [preset.id, preset]));
  const defaults = {
    lab: { background: "#EEF2F5", surface: "#FFFFFF", primary: "#086959", text: "#1D2D3B", titlebar: "#C6D6E3" },
    ocean: { background: "#102A3A", surface: "#F8FBFD", primary: "#135C7E", text: "#152D40", titlebar: "#244F63" },
    dark: { background: "#10191E", surface: "#1A282E", primary: "#67D5B0", text: "#EDF4F6", titlebar: "#334C59" },
    pixel: { ...presetById.get("cream").colors },
  };

  function hex(value) {
    return typeof value === "string" && /^#[\da-f]{6}$/i.test(value) ? value.toUpperCase() : null;
  }

  function defaultsFor(theme) { return { ...(Object.hasOwn(defaults, theme) ? defaults[theme] : defaults.lab) }; }

  function normalize(value, theme) {
    const raw = typeof value === "string" ? { id: value } : value;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
    if (raw.id === "system") return { id: "system" };
    if (raw.id === "default") return { id: "default", colors: defaultsFor(theme) };
    if (presetById.has(raw.id)) {
      const preset = presetById.get(raw.id);
      return { id: preset.id, colors: { ...preset.colors } };
    }
    if (raw.id !== "custom" || !raw.colors || typeof raw.colors !== "object" || Array.isArray(raw.colors)) return null;
    const colors = {};
    for (const key of COLOR_KEYS) {
      const color = hex(raw.colors[key]);
      if (!color) return null;
      colors[key] = color;
    }
    return { id: "custom", colors };
  }

  function rgb(color) { return [1, 3, 5].map((offset) => parseInt(color.slice(offset, offset + 2), 16)); }

  function luminance(color) {
    const channels = rgb(color).map((value) => {
      const channel = value / 255;
      return channel <= .04045 ? channel / 12.92 : Math.pow((channel + .055) / 1.055, 2.4);
    });
    return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
  }

  function contrast(a, b) {
    if (!hex(a) || !hex(b)) return 0;
    const first = luminance(a), second = luminance(b);
    return (Math.max(first, second) + .05) / (Math.min(first, second) + .05);
  }

  function mix(a, b, weight) {
    const first = rgb(a), second = rgb(b);
    return "#" + first.map((value, index) => Math.round(value + (second[index] - value) * weight).toString(16).padStart(2, "0")).join("").toUpperCase();
  }

  function bestText(background) {
    return contrast("#FFFFFF", background) >= contrast("#000000", background) ? "#FFFFFF" : "#000000";
  }

  // Keep a candidate's hue where possible, then move toward a readable endpoint.
  function readable(candidate, background, minimum) {
    const target = minimum || 4.5;
    const backgrounds = Array.isArray(background) ? background : [background];
    const minimumContrast = (color) => Math.min(...backgrounds.map((base) => contrast(color, base)));
    if (minimumContrast(candidate) >= target) return candidate;
    const endpoint = minimumContrast("#FFFFFF") >= minimumContrast("#000000") ? "#FFFFFF" : "#000000";
    for (let step = 1; step <= 100; step += 1) {
      const adjusted = mix(candidate, endpoint, step / 100);
      if (minimumContrast(adjusted) >= target) return adjusted;
    }
    return endpoint;
  }

  function derive(colors, chartBackground) {
    const { background, surface, primary, text, titlebar } = colors;
    const dark = luminance(surface) < .18;
    const onSurface = readable(text, surface);
    const panelSoft = mix(surface, background, .35);
    const chrome = mix(surface, background, .5);
    const chromeStrong = mix(surface, background, .7);
    const selected = mix(surface, primary, dark ? .15 : .09);
    const code = mix(surface, background, .6);
    const control = surface;
    const readingSurfaces = [surface, panelSoft, selected];
    const chromeSurfaces = [chrome, chromeStrong, surface];
    const onPrimary = bestText(primary);
    const primaryHover = mix(primary, onPrimary === "#FFFFFF" ? "#000000" : "#FFFFFF", .14);
    const muted = readable(mix(surface, onSurface, .66), readingSurfaces);
    const border = readable(mix(surface, onSurface, .46), surface, 3);
    const notice = mix(surface, dark ? "#DFAA45" : "#EFBD68", dark ? .12 : .2);
    const ok = readable(dark ? "#80D5A6" : "#12683F", readingSurfaces);
    const warn = readable(dark ? "#F2CB83" : "#83530C", readingSurfaces);
    const danger = readable(dark ? "#FFACA5" : "#B1282D", readingSurfaces);
    const chatUser = mix(surface, primary, dark ? .12 : .07);
    // A quiet, neutral entrance inherits just a little of the palette's accent.
    const assistantBg = mix(surface, primary, dark ? .10 : .035);
    const assistantText = readable(mix(text, primary, .16), assistantBg);
    // Mid-grey custom surfaces can straddle the white/black contrast boundary.
    // Keep the text stable and adjust the hover surface to that same text.
    const assistantHover = readable(mix(surface, primary, dark ? .18 : .085), assistantText);
    const chart = chartBackground === "paper" ? "#FFFFFF" : surface;
    const chartText = chartBackground === "paper" ? "#163444" : readable(text, chart);
    return {
      "--body-bg": background,
      "--bg-a": background,
      "--bg-b": background,
      "--app-chrome": chrome,
      "--app-chrome-strong": chromeStrong,
      "--chrome-text": readable(text, chromeSurfaces),
      "--chrome-muted": readable(mix(chromeStrong, readable(text, chromeStrong), .75), chromeSurfaces),
      "--chrome-control": surface,
      "--chrome-border": readable(border, chromeStrong, 3),
      "--titlebar-bg": titlebar,
      "--titlebar-text": readable(text, titlebar),
      "--titlebar-divider": readable(primary, titlebar, 3),
      "--scrollbar-thumb": border,
      "--scrollbar-thumb-hover": readable(mix(border, onSurface, .3), panelSoft, 3),
      "--scrollbar-track": panelSoft,
      "--scrollbar-page-track": background,
      "--panel": surface,
      "--panel-solid": surface,
      "--panel-soft": panelSoft,
      "--control-bg": control,
      "--text": text,
      "--muted": muted,
      "--line": mix(surface, onSurface, .22),
      "--line-strong": border,
      "--control-border": border,
      "--primary": primary,
      "--primary-dark": primaryHover,
      "--primary-text": readable(primary, readingSurfaces),
      "--on-primary": onPrimary,
      "--accent-blue": readable(primary, readingSurfaces),
      "--ok": ok,
      "--on-ok": bestText(ok),
      "--warn": warn,
      "--on-warn": bestText(warn),
      "--danger": danger,
      "--on-danger": bestText(danger),
      "--focus": readable(primary, surface, 3),
      "--selected-bg": selected,
      "--disabled-bg": mix(surface, background, .6),
      "--disabled-text": readable(muted, mix(surface, background, .6)),
      "--notice-bg": notice,
      "--notice-text": readable(warn, notice),
      "--notice-border": readable(warn, notice, 3),
      "--chat-user-bg": chatUser,
      "--chat-agent-bg": surface,
      "--chat-text": readable(text, [surface, chatUser]),
      "--assistant-fab-bg": assistantBg,
      "--assistant-fab-hover": assistantHover,
      "--assistant-fab-text": assistantText,
      "--assistant-fab-border": mix(surface, onSurface, dark ? .4 : .22),
      "--code-bg": code,
      "--code-text": readable(text, code),
      "--chart-preview-bg": chart,
      "--chart-preview-text": chartText,
      "--chart-preview-axis": chartBackground === "paper" ? "#476779" : readable(muted, chart),
      "--grid-line": mix(background, bestText(background), .35),
      "--ink": text,
      "--accent": primary,
      "color-scheme": dark ? "dark" : "light",
    };
  }

  const overrideKeys = Object.freeze(Object.keys(derive(defaults.lab)));
  const BASE_THEMES = Object.freeze({ lab: "lab", ocean: "ocean", dark: "dark", cream: "pixel" });

  function baseTheme(palette, style) {
    if (palette && Object.hasOwn(BASE_THEMES, palette.id)) return BASE_THEMES[palette.id];
    if (style === "pixel") return "pixel";
    return palette && palette.colors && luminance(palette.colors.surface) < .18 ? "dark" : "lab";
  }

  function apply(element, palette, chartBackground) {
    if (!element || !element.style) return;
    // Preserve each original CSS colorway, including Ocean's mixed dark/light surfaces.
    const active = palette && palette.colors && palette.id !== "default" && !Object.hasOwn(BASE_THEMES, palette.id);
    const values = active ? derive(palette.colors, chartBackground) : null;
    for (const key of overrideKeys) {
      if (active) element.style.setProperty(key, values[key]);
      else element.style.removeProperty(key);
    }
    if (active) element.dataset.palette = palette.id;
    else delete element.dataset.palette;
    if (palette) element.dataset.paletteId = palette.id;
    else delete element.dataset.paletteId;
  }

  window.ElectrochemPalette = Object.freeze({ presets, colorKeys: COLOR_KEYS, defaultsFor, normalize, derive, apply, contrast, baseTheme });
})();
