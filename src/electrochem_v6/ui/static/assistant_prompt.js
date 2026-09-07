(function () {
  "use strict";

  const STORAGE_KEY = "electrochem_v6_prompt_settings";
  const TEMPLATES = {
    analyst:
      "你是电化学数据分析助手。回答时请先给结论，再给证据；明确指出可能误差来源，并给下一步实验建议。",
    summary:
      "请用结构化方式总结本次结果：1) 核心结论 2) 关键指标 3) 异常/风险 4) 建议动作。每项不超过 3 条。",
    paper:
      "请用学术写作风格输出：背景一句、方法一句、结果三句、讨论两句，并保持术语严谨。",
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function translate(t, key) {
    return typeof t === "function" ? t(key) : key;
  }

  function getTemplate(key) {
    return TEMPLATES[key] || TEMPLATES.analyst;
  }

  function readSaved() {
    try {
      return JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null");
    } catch (_err) {
      return null;
    }
  }

  function load() {
    const saved = readSaved();
    const enabled = saved && typeof saved.enabled === "boolean" ? saved.enabled : true;
    const template = saved && typeof saved.template === "string" ? saved.template : "analyst";
    const prefix =
      saved && typeof saved.prefix === "string" && saved.prefix.trim()
        ? saved.prefix
        : getTemplate(template);
    if (byId("prompt-enabled")) byId("prompt-enabled").checked = enabled;
    if (byId("prompt-template")) byId("prompt-template").value = template;
    if (byId("prompt-prefix")) byId("prompt-prefix").value = prefix;
  }

  function renderTemplateOptions(t) {
    const select = byId("prompt-template");
    if (!select) return;
    const current = select.value || "analyst";
    select.innerHTML = "";
    const options = [
      { key: "analyst", label: translate(t, "prompt_tpl_analyst") },
      { key: "summary", label: translate(t, "prompt_tpl_summary") },
      { key: "paper", label: translate(t, "prompt_tpl_paper") },
    ];
    options.forEach((it) => {
      const op = document.createElement("option");
      op.value = it.key;
      op.textContent = it.label;
      select.appendChild(op);
    });
    select.value = options.some((it) => it.key === current) ? current : "analyst";
  }

  function save(options) {
    const onStatus = options && typeof options.onStatus === "function" ? options.onStatus : () => {};
    const t = options && options.translate;
    const enabled = Boolean(byId("prompt-enabled") && byId("prompt-enabled").checked);
    const template = String((byId("prompt-template") && byId("prompt-template").value) || "analyst").trim() || "analyst";
    const prefix = String((byId("prompt-prefix") && byId("prompt-prefix").value) || "").trim();
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        enabled,
        template,
        prefix,
      }),
    );
    if (!prefix && enabled) {
      if (byId("prompt-enabled")) byId("prompt-enabled").checked = false;
      onStatus(translate(t, "status_prompt_empty"));
      return;
    }
    onStatus(translate(t, "status_prompt_saved"));
  }

  function applyTemplate(options) {
    const onStatus = options && typeof options.onStatus === "function" ? options.onStatus : () => {};
    const t = options && options.translate;
    const template = String((byId("prompt-template") && byId("prompt-template").value) || "analyst").trim() || "analyst";
    if (byId("prompt-prefix")) byId("prompt-prefix").value = getTemplate(template);
    onStatus(translate(t, "status_prompt_applied"));
  }

  function getActivePrefix() {
    const enabled = Boolean(byId("prompt-enabled") && byId("prompt-enabled").checked);
    const prefix = String((byId("prompt-prefix") && byId("prompt-prefix").value) || "").trim();
    return enabled ? prefix : "";
  }

  function buildMessage(message) {
    const raw = String(message || "").trim();
    const prefix = getActivePrefix();
    if (!prefix) return raw;
    if (!raw) return prefix;
    return `${prefix}\n\n${raw}`;
  }

  window.ElectrochemAssistantPrompt = {
    applyTemplate,
    buildMessage,
    getActivePrefix,
    load,
    renderTemplateOptions,
    save,
    storageKey: STORAGE_KEY,
    templates: TEMPLATES,
  };
})();
