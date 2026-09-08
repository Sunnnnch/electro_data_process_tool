(function () {
  "use strict";

  const discoveries = new WeakMap();
  const discoveryErrors = new Set([
    "invalid_config", "invalid_url", "missing_key", "endpoint_changed", "unauthorized", "unsupported",
    "rate_limited", "unavailable", "redirect", "timeout", "network", "invalid_response",
  ]);

  function discoveryState(ctx) {
    const select = ctx.byId("llm-model-options");
    return select ? discoveries.get(select) : null;
  }

  function modelStatus(ctx, key, count) {
    const state = discoveryState(ctx);
    if (state) state.status = { key, count };
    const hint = ctx.byId("llm-model-status");
    if (hint) hint.textContent = translate(ctx, key).replace("{count}", String(count || 0));
  }

  function clearModelDiscovery(ctx) {
    const state = discoveryState(ctx);
    if (!state) return;
    state.generation += 1;
    clearTimeout(state.timer);
    if (state.controller) state.controller.abort();
    state.controller = null;
    state.signature = null;
    state.models = [];
    state.select.replaceChildren();
    state.select.hidden = true;
    state.select.disabled = true;
    const refresh = ctx.byId("llm-model-refresh");
    if (refresh) refresh.disabled = false;
  }

  function modelDiscoverySignature(ctx) {
    const provider = ctx.textValue("llm-provider");
    // In-memory only: never persist or log this draft credential fingerprint.
    return JSON.stringify([provider, ctx.textValue("llm-base-url"), ctx.textValue("llm-api-key"),
      Boolean((getModels(ctx)[provider] || {}).has_api_key)]);
  }

  function renderModelDiscovery(ctx) {
    const state = discoveryState(ctx);
    if (!state) return;
    state.select.setAttribute("aria-label", translate(ctx, "llm_models_choose"));
    if (state.models.length) {
      const selected = state.models.includes(ctx.textValue("llm-model"));
      modelStatus(ctx, selected ? "llm_models_loaded" : "llm_models_unlisted", state.models.length);
      state.select.value = selected ? ctx.textValue("llm-model") : "";
    } else if (state.status) {
      modelStatus(ctx, state.status.key, state.status.count);
    }
    const placeholder = state.select.options && state.select.options[0];
    if (placeholder) placeholder.textContent = translate(ctx, "llm_models_choose");
  }

  async function fetchModelDiscovery(ctx) {
    const state = discoveryState(ctx);
    if (!state || typeof ctx.llmApi.listModels !== "function") return;
    clearModelDiscovery(ctx);
    state.signature = modelDiscoverySignature(ctx);
    const provider = ctx.textValue("llm-provider");
    const apiKey = ctx.textValue("llm-api-key");
    if (!provider || (!apiKey && !(getModels(ctx)[provider] || {}).has_api_key)) {
      modelStatus(ctx, "llm_models_missing_key");
      return;
    }
    const generation = state.generation;
    state.controller = new AbortController();
    const refresh = ctx.byId("llm-model-refresh");
    if (refresh) refresh.disabled = true;
    modelStatus(ctx, "llm_models_loading");
    const payload = { provider, base_url: ctx.textValue("llm-base-url") };
    if (apiKey) payload.api_key = apiKey;
    try {
      const response = await ctx.llmApi.listModels(payload, { signal: state.controller.signal });
      const data = await response.json();
      if (generation !== state.generation) return;
      if (!response.ok || data.status !== "success") {
        const code = discoveryErrors.has(data.code) ? data.code : "unavailable";
        modelStatus(ctx, `llm_models_${code}`);
        return;
      }
      state.models = [...new Set((Array.isArray(data.models) ? data.models : [])
        .filter((item) => typeof item === "string" && item.length > 0 && item.length <= 256))];
      if (!state.models.length) {
        modelStatus(ctx, "llm_models_empty");
        return;
      }
      const doc = state.select.ownerDocument;
      const placeholder = doc.createElement("option");
      placeholder.value = "";
      placeholder.textContent = translate(ctx, "llm_models_choose");
      state.select.appendChild(placeholder);
      state.models.forEach((model) => {
        const option = doc.createElement("option");
        option.value = model;
        option.textContent = model;
        state.select.appendChild(option);
      });
      state.select.hidden = false;
      state.select.disabled = false;
      renderModelDiscovery(ctx);
    } catch (err) {
      if (generation === state.generation && err.name !== "AbortError") modelStatus(ctx, "llm_models_network");
    } finally {
      if (generation === state.generation) {
        state.controller = null;
        if (refresh) refresh.disabled = false;
      }
    }
  }

  function scheduleModelDiscovery(ctx, options = {}) {
    const state = discoveryState(ctx);
    if (!state) return;
    const signature = modelDiscoverySignature(ctx);
    if (state.signature === signature) return;
    clearModelDiscovery(ctx);
    const panel = ctx.byId("ai-settings-panel");
    if (options.onlyWhenOpen && (!panel || panel.classList.contains("hidden"))) {
      modelStatus(ctx, "llm_models_idle");
      return;
    }
    state.signature = signature;
    const provider = ctx.textValue("llm-provider");
    if (!ctx.textValue("llm-api-key") && !(getModels(ctx)[provider] || {}).has_api_key) {
      modelStatus(ctx, "llm_models_missing_key");
      return;
    }
    modelStatus(ctx, "llm_models_pending");
    state.timer = setTimeout(() => fetchModelDiscovery(ctx), 700);
  }

  function initModelDiscovery(ctx) {
    const select = ctx.byId("llm-model-options");
    if (!select || discoveries.has(select)) return;
    discoveries.set(select, { select, generation: 0, timer: null, controller: null, models: [] });
    ["llm-api-key", "llm-base-url"].forEach((id) => {
      const input = ctx.byId(id);
      input.addEventListener("input", (event) => {
        if (event.isComposing) { clearModelDiscovery(ctx); return; }
        scheduleModelDiscovery(ctx);
      });
      input.addEventListener("change", () => scheduleModelDiscovery(ctx));
      input.addEventListener("compositionend", () => scheduleModelDiscovery(ctx));
    });
    ctx.byId("llm-provider").addEventListener("change", () => {
      // A draft key belongs to the previous provider; never submit it to another provider.
      ctx.byId("llm-api-key").value = "";
      scheduleModelDiscovery(ctx);
    });
    ctx.byId("llm-model-refresh").addEventListener("click", () => fetchModelDiscovery(ctx));
    ctx.byId("llm-model").addEventListener("input", () => renderModelDiscovery(ctx));
    select.addEventListener("change", () => {
      if (select.value) ctx.byId("llm-model").value = select.value;
      renderModelDiscovery(ctx);
    });
    modelStatus(ctx, "llm_models_idle");
  }

  function getModels(ctx) {
    return typeof ctx.getModelsByProvider === "function" ? ctx.getModelsByProvider() : {};
  }

  function setModels(ctx, models) {
    if (typeof ctx.setModelsByProvider === "function") {
      ctx.setModelsByProvider(models && typeof models === "object" ? models : {});
    }
  }

  function translate(ctx, key) {
    return typeof ctx.t === "function" ? ctx.t(key) : String(key || "");
  }

  function setStatus(ctx, text) {
    if (typeof ctx.setLLMStatus === "function") ctx.setLLMStatus(text || "");
  }

  function assistantPage(ctx) {
    return ctx.assistantPage || {};
  }

  function assistantPrompt(ctx) {
    return ctx.assistantPrompt || {};
  }

  function listLLMProviders(ctx) {
    const page = assistantPage(ctx);
    return typeof page.listLLMProviders === "function" ? page.listLLMProviders(getModels(ctx)) : [];
  }

  function updateLLMKeyHint(ctx, provider) {
    const page = assistantPage(ctx);
    if (typeof page.updateLLMKeyHint !== "function") return;
    page.updateLLMKeyHint({
      byId: ctx.byId,
      modelsByProvider: getModels(ctx),
      provider,
      t: ctx.t,
    });
  }

  function applyLLMProviderPreset(ctx, provider) {
    const page = assistantPage(ctx);
    if (typeof page.applyLLMProviderPreset !== "function") return;
    page.applyLLMProviderPreset({
      byId: ctx.byId,
      modelsByProvider: getModels(ctx),
      provider,
      t: ctx.t,
    });
  }

  function renderLLMProviders(ctx, defaultProvider) {
    const page = assistantPage(ctx);
    if (typeof page.renderLLMProviders !== "function") return "";
    return page.renderLLMProviders({
      byId: ctx.byId,
      defaultProvider,
      modelsByProvider: getModels(ctx),
      t: ctx.t,
    });
  }

  async function loadLLMConfig(ctx) {
    clearModelDiscovery(ctx);
    setStatus(ctx, translate(ctx, "status_llm_loading"));
    try {
      const resp = await ctx.llmApi.getConfig();
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || translate(ctx, "status_llm_load_failed"));
      }
      setModels(ctx, data.models || {});
      renderLLMProviders(ctx, data.default_provider || "");
      scheduleModelDiscovery(ctx, { onlyWhenOpen: true });
      setStatus(ctx, translate(ctx, "status_llm_loaded"));
      return data;
    } catch (err) {
      setStatus(ctx, `${translate(ctx, "status_llm_load_failed")}: ${err.message}`);
      return null;
    }
  }

  function buildLLMConfigPayload(ctx, options = {}) {
    const requireChanges = Boolean(options.requireChanges);
    const provider = ctx.textValue("llm-provider");
    if (!provider) {
      return { error: translate(ctx, "status_llm_provider_required") };
    }
    const payload = { provider };
    let hasChanges = false;

    const model = ctx.textValue("llm-model");
    if (model) {
      payload.model = model;
      hasChanges = true;
    }

    const baseUrl = ctx.textValue("llm-base-url");
    if (baseUrl) {
      payload.base_url = baseUrl;
      hasChanges = true;
    }

    const timeoutRaw = ctx.textValue("llm-timeout");
    if (timeoutRaw) {
      const timeout = Number.parseInt(timeoutRaw, 10);
      if (!Number.isInteger(timeout) || timeout <= 0) {
        return { error: translate(ctx, "status_llm_timeout_invalid") };
      }
      payload.timeout = timeout;
      hasChanges = true;
    }

    const apiKey = ctx.textValue("llm-api-key");
    if (apiKey) {
      payload.api_key = apiKey;
      hasChanges = true;
    }

    if (requireChanges && !hasChanges) {
      return { error: translate(ctx, "status_llm_no_changes") };
    }
    return { apiKey, hasChanges, payload };
  }

  async function saveLLMConfig(ctx) {
    const built = buildLLMConfigPayload(ctx, { requireChanges: true });
    if (built.error) {
      setStatus(ctx, built.error);
      return null;
    }
    const { payload, apiKey } = built;
    const provider = payload.provider;
    clearModelDiscovery(ctx);

    setStatus(ctx, translate(ctx, "status_llm_save_running"));
    try {
      const resp = await ctx.llmApi.saveConfig(payload);
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || translate(ctx, "status_llm_save_failed"));
      }
      const models = getModels(ctx);
      const current = models[provider] || {};
      models[provider] = { ...current, ...(data.config || {}) };
      setModels(ctx, models);
      if (apiKey) {
        const keyEl = ctx.byId("llm-api-key");
        if (keyEl) keyEl.value = "";
      }
      renderLLMProviders(ctx, provider);
      scheduleModelDiscovery(ctx, { onlyWhenOpen: true });
      setStatus(ctx, translate(ctx, "status_llm_save_success"));
      return data;
    } catch (err) {
      setStatus(ctx, `${translate(ctx, "status_llm_save_failed")}: ${err.message}`);
      return null;
    }
  }

  async function testLLMConnection(ctx) {
    const built = buildLLMConfigPayload(ctx);
    if (built.error) {
      setStatus(ctx, built.error);
      return null;
    }
    const testBtn = ctx.byId("llm-test");
    if (testBtn && testBtn.disabled) return null;
    if (testBtn) testBtn.disabled = true;
    setStatus(ctx, translate(ctx, "status_llm_test_running"));
    try {
      const resp = await ctx.llmApi.testConfig(built.payload);
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || translate(ctx, "status_llm_test_failed"));
      }
      const modelText = data.model ? ` | ${data.model}` : "";
      setStatus(ctx, `${translate(ctx, "status_llm_test_success")}: ${data.provider || built.payload.provider}${modelText}`);
      return data;
    } catch (err) {
      setStatus(ctx, `${translate(ctx, "status_llm_test_failed")}: ${err.message}`);
      return null;
    } finally {
      if (testBtn) testBtn.disabled = false;
    }
  }

  function loadPromptSettings(ctx) {
    const prompt = assistantPrompt(ctx);
    if (typeof prompt.load === "function") prompt.load();
  }

  function renderPromptTemplateOptions(ctx) {
    const prompt = assistantPrompt(ctx);
    if (typeof prompt.renderTemplateOptions === "function") prompt.renderTemplateOptions(ctx.t);
  }

  function savePromptSettings(ctx) {
    const prompt = assistantPrompt(ctx);
    if (typeof prompt.save === "function") prompt.save({ translate: ctx.t, onStatus: ctx.setLLMStatus });
  }

  function applyPromptTemplate(ctx) {
    const prompt = assistantPrompt(ctx);
    if (typeof prompt.applyTemplate === "function") prompt.applyTemplate({ translate: ctx.t, onStatus: ctx.setLLMStatus });
  }

  function buildPromptedMessage(ctx, message) {
    const prompt = assistantPrompt(ctx);
    return typeof prompt.buildMessage === "function" ? prompt.buildMessage(message) : String(message || "").trim();
  }

  function getActivePromptPrefix(ctx) {
    const prompt = assistantPrompt(ctx);
    if (typeof prompt.getActivePrefix === "function") {
      return prompt.getActivePrefix();
    }
    return String(buildPromptedMessage(ctx, "") || "").trim();
  }

  window.ElectrochemAISettingsPage = {
    clearModelDiscovery,
    fetchModelDiscovery,
    initModelDiscovery,
    renderModelDiscovery,
    scheduleModelDiscovery,
    applyLLMProviderPreset,
    applyPromptTemplate,
    buildLLMConfigPayload,
    buildPromptedMessage,
    getActivePromptPrefix,
    listLLMProviders,
    loadLLMConfig,
    loadPromptSettings,
    renderLLMProviders,
    renderPromptTemplateOptions,
    saveLLMConfig,
    savePromptSettings,
    testLLMConnection,
    updateLLMKeyHint,
  };
})();
