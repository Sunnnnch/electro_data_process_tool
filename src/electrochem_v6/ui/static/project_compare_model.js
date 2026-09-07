(function () {
  "use strict";

  function hasValue(value) {
    return value !== undefined && value !== null;
  }

  function filterSamples(samplesInput, options) {
    const opts = options || {};
    let samples = Array.isArray(samplesInput) ? [...samplesInput] : [];
    if (opts.onlyEta) {
      samples = samples.filter((item) => hasValue(item.overpotential_10));
    }
    if (opts.onlyTafel) {
      samples = samples.filter((item) => hasValue(item.tafel_slope));
    }
    if (opts.sort === "tafel") {
      samples.sort((a, b) => {
        const av = a.tafel_slope ?? Number.POSITIVE_INFINITY;
        const bv = b.tafel_slope ?? Number.POSITIVE_INFINITY;
        return av - bv;
      });
    } else if (opts.sort === "latest") {
      samples.sort((a, b) => String(b.latest_time || "").localeCompare(String(a.latest_time || "")));
    } else if (opts.sort === "sample") {
      samples.sort((a, b) => String(a.sample_name || "").localeCompare(String(b.sample_name || "")));
    } else {
      samples.sort((a, b) => {
        const aEta = a.overpotential_10;
        const bEta = b.overpotential_10;
        if (hasValue(aEta) && hasValue(bEta)) return aEta - bEta;
        if (hasValue(aEta)) return -1;
        if (hasValue(bEta)) return 1;
        const aPot = a.potential_10 ?? Number.POSITIVE_INFINITY;
        const bPot = b.potential_10 ?? Number.POSITIVE_INFINITY;
        return aPot - bPot;
      });
    }
    return samples;
  }

  function syncSelectedSamples(samples, selectedSamples, maxDefault) {
    const visibleNames = (Array.isArray(samples) ? samples : [])
      .map((item) => String(item.sample_name || "").trim())
      .filter(Boolean);
    if (!visibleNames.length) {
      return { clearPlot: true, selectedSamples: [], visibleNames };
    }

    const selected = Array.isArray(selectedSamples) ? selectedSamples : [];
    const visibleSet = new Set(visibleNames);
    const nextSelected = visibleNames.filter((name) => selected.includes(name));
    if (!nextSelected.length) {
      return {
        clearPlot: true,
        selectedSamples: visibleNames.slice(0, Math.min(maxDefault || 3, visibleNames.length)),
        visibleNames,
      };
    }

    const clearPlot = nextSelected.length !== selected.length || selected.some((name) => !visibleSet.has(name));
    return { clearPlot, selectedSamples: nextSelected, visibleNames };
  }

  function needsTargetCurrent(chartType, metric) {
    return chartType === "bar" && metric !== "tafel_slope";
  }

  function availableTargetCurrents(state, metric) {
    const safe = state && typeof state === "object" ? state : {};
    if (metric === "overpotential_at_target") {
      return Array.isArray(safe.overpotential_target_currents) ? safe.overpotential_target_currents : [];
    }
    if (metric === "potential_at_target") {
      return Array.isArray(safe.potential_target_currents) ? safe.potential_target_currents : [];
    }
    return Array.isArray(safe.target_currents) ? safe.target_currents : [];
  }

  function formatTargetCurrent(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 0) return "";
    return String(numeric);
  }

  function normalizeTargetOptions(options) {
    const normalized = (Array.isArray(options) ? options : [])
      .map((item) => {
        const numeric = Number(item);
        return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
      })
      .filter((item) => item !== null);
    return [...new Set(normalized)];
  }

  function selectTargetCurrent(options, currentValue, preferredValue) {
    const normalizedOptions = normalizeTargetOptions(options);
    const preferred = normalizedOptions.includes(preferredValue) ? preferredValue : normalizedOptions[0];
    const numericCurrent = Number(currentValue);
    const nextValue = normalizedOptions.includes(numericCurrent) ? numericCurrent : preferred;
    return {
      options: normalizedOptions,
      value: nextValue !== undefined ? formatTargetCurrent(nextValue) : "",
    };
  }

  window.ElectrochemProjectCompareModel = {
    availableTargetCurrents,
    filterSamples,
    formatTargetCurrent,
    needsTargetCurrent,
    normalizeTargetOptions,
    selectTargetCurrent,
    syncSelectedSamples,
  };
})();
