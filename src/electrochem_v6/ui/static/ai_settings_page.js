(function () {
  "use strict";

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
    setStatus(ctx, translate(ctx, "status_llm_loading"));
    try {
      const resp = await ctx.llmApi.getConfig();
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || translate(ctx, "status_llm_load_failed"));
      }
      setModels(ctx, data.models || {});
      renderLLMProviders(ctx, data.default_provider || "");
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
