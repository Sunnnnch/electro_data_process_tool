(function () {
  "use strict";

  const labels = {
    zh: {
      title: "AI 连接（MCP）", close: "关闭", loading: "正在读取连接配置…",
      intro: "将下面的配置加入支持本地 MCP 的 AI 客户端，即可查询项目、搜索结果和预检数据。连接期间请保持本软件运行。",
      access: "允许新建处理任务和导出报告", scope: "默认只读。勾选后生成允许处理和导出的配置，复制到 AI 客户端并重新连接后生效；不会改变已有连接的权限。新任务会显示在本软件的任务中心。",
      config: "MCP 配置（JSON）", copy: "复制配置", copied: "配置已复制。", select: "无法自动复制，请选中配置后手动复制。",
      missing: "未找到 MCP 启动程序，请使用包含 ElectroChem-MCP.exe 的完整客户端目录。",
      closing: "软件正在退出，请重新打开后连接。", unavailable: "本地服务尚未就绪，请稍后重试。",
      failed: "无法读取 MCP 配置：", retry: "重试", example: "连接后可以对 AI 说：“列出我的电化学项目，找到最近的 CV 结果并解释质量提示。”",
      writeExample: "处理数据时，先让 AI 查询参数并预检，再提交任务。输入路径须位于运行本软件的电脑上。",
      hint: "如果 AI 客户端已有 mcpServers 配置，只合并 electrochem 这一项。此入口适用于支持本地 stdio 的客户端。",
    },
    en: {
      title: "AI connection (MCP)", close: "Close", loading: "Loading connection settings…",
      intro: "Add this configuration to an AI client that supports local MCP to query projects, search results and preflight data. Keep this application running while connected.",
      access: "Allow new processing jobs and report exports", scope: "Read-only by default. This changes the generated configuration; copy it into the AI client and reconnect to apply it. Existing connections keep their permissions. New jobs appear in this application's task center.",
      config: "MCP configuration (JSON)", copy: "Copy configuration", copied: "Configuration copied.", select: "Automatic copy is unavailable. Select the configuration and copy it manually.",
      missing: "The MCP launcher is missing. Use the complete application folder containing ElectroChem-MCP.exe.",
      closing: "The application is closing. Reopen it before connecting.", unavailable: "The local service is not ready. Please try again shortly.",
      failed: "Unable to load MCP settings: ", retry: "Retry", example: "After connecting, ask the AI: “List my electrochemistry projects, find the latest CV results and explain their quality warnings.”",
      writeExample: "Before processing, ask the AI to inspect the parameter schema and preflight the data. Input paths must be on the computer running this application.",
      hint: "If your AI client already has mcpServers settings, merge only the electrochem entry. This connection supports local stdio clients.",
    },
  };

  function node(tag, value, className) {
    const item = document.createElement(tag);
    if (value) item.textContent = value;
    if (className) item.className = className;
    return item;
  }

  async function show() {
    const existing = document.getElementById("mcp-settings-dialog");
    if (existing) { if (!existing.open) existing.showModal(); return; }
    const lang = document.getElementById("lang-select")?.value === "en" ? "en" : "zh";
    const text = labels[lang];
    const dialog = node("dialog", "", "desktop-dialog mcp-settings-dialog");
    dialog.id = "mcp-settings-dialog";
    dialog.setAttribute("aria-labelledby", "mcp-settings-title");
    const head = node("div", "", "desktop-dialog-head");
    const title = node("h2", text.title); title.id = "mcp-settings-title";
    const close = node("button", text.close, "btn"); close.type = "button";
    close.addEventListener("click", () => dialog.close());
    head.append(title, close);
    const intro = node("p", text.intro);
    const access = node("label", "", "mcp-settings-access");
    const allow = node("input"); allow.type = "checkbox"; allow.id = "mcp-allow-write";
    access.append(allow, node("span", text.access));
    const scope = node("p", text.scope, "panel-sub");
    const configLabel = node("label", text.config); configLabel.htmlFor = "mcp-client-config";
    const config = node("textarea", "", "mcp-client-config");
    config.id = "mcp-client-config"; config.readOnly = true; config.spellcheck = false;
    config.rows = 12; config.wrap = "off";
    const feedback = node("p", text.loading); feedback.id = "mcp-settings-status";
    feedback.setAttribute("role", "status");
    const actions = node("div", "", "desktop-actions");
    const copy = node("button", text.copy, "btn primary"); copy.id = "mcp-copy-config"; copy.type = "button"; copy.disabled = true;
    const retry = node("button", text.retry, "btn"); retry.type = "button";
    actions.append(copy, retry);
    dialog.append(head, intro, access, scope, configLabel, config, node("p", text.hint, "panel-sub"),
      feedback, actions, node("p", text.example, "panel-sub"), node("p", text.writeExample, "panel-sub"));
    dialog.addEventListener("close", () => dialog.remove(), { once: true });
    document.body.append(dialog);
    dialog.showModal();

    let request = 0;
    async function refresh() {
      const current = ++request;
      copy.disabled = true; config.value = ""; feedback.textContent = text.loading;
      try {
        const api = window.pywebview?.api;
        if (!api || typeof api.get_mcp_configuration !== "function") throw new Error(text.unavailable);
        const result = await api.get_mcp_configuration(allow.checked);
        if (current !== request || !dialog.isConnected) return;
        if (!result || result.status !== "success" || !result.client_config) throw new Error(result?.message || text.unavailable);
        config.value = JSON.stringify(result.client_config, null, 2);
        copy.disabled = !result.available;
        feedback.textContent = !result.available ? text.missing : result.closing ? text.closing : !result.server_running ? text.unavailable : "";
      } catch (error) {
        if (current === request && dialog.isConnected) feedback.textContent = text.failed + (error.message || String(error));
      }
    }
    allow.addEventListener("change", refresh);
    retry.addEventListener("click", refresh);
    copy.addEventListener("click", async () => {
      const value = config.value;
      if (!value || copy.disabled) return;
      try {
        await navigator.clipboard.writeText(value);
        feedback.textContent = text.copied;
      } catch (_error) {
        config.focus(); config.select(); feedback.textContent = text.select;
      }
    });
    await refresh();
  }

  window.ElectrochemMCP = { show };
})();
