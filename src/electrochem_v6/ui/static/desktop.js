(function () {
  "use strict";

  const STORAGE_KEYS = ["electrochem_v6_appearance", "electrochem_v6_theme", "electrochem_v6_lang"];
  const SUBMISSIONS = "#proc-run, #send-btn, #project-replay-execute, #recovery-execute, #assistant-action-confirm";
  const labels = {
    zh: {
      menu: "客户端", local: "本机版", settings: "设置", appearance: "外观设置", ai: "AI 设置", system: "系统与存储", mcp: "AI 连接（MCP）",
      data: "打开数据目录", migrate: "迁移旧数据", updates: "检查更新", tray: "后台继续", exit: "退出软件", close: "关闭",
      import: "选择数据文件", save: "另存为", saved: "已保存", cancelled: "已取消", failed: "操作失败", busy: "正在处理…",
      privacy: "自动记住外观、语言及上次浏览的项目和会话；不会恢复输入文件或实验参数。",
      bridge: "正在连接桌面客户端…", bridgeError: "桌面连接失败，尚未载入工作区。请重试。", retry: "重试连接",
      preferencesError: "客户端偏好保存失败；本次界面设置仍然有效。", waiting: "等待任务结束后退出，新任务已暂停提交。",
      cancelling: "正在取消可取消任务，待安全结束后退出。", closeTitle: "退出前处理运行中的任务", taskCount: "进行中的任务：{count}",
      protected: "{count} 个任务正在保存结果，需等待安全完成。", stay: "继续使用", wait: "等待完成后退出", cancel: "取消任务后退出",
      noTasks: "没有正在运行的任务。", process: "数据处理", agent: "助手", queued: "排队中", running: "运行中", saving: "保存结果",
      succeeded: "已完成", failedTask: "失败", cancelledTask: "已取消", preflight: "预检", processing: "计算中", finalizing: "保存结果", committing: "写入结果",
      migrationHint: "迁移会保留原数据；本次仅安排迁移，任务安全结束后退出，下次启动再次确认。已有目标数据时不合并。",
      noMigration: "未找到可迁移的旧数据。", migrationSchedule: "安排迁移并退出", migrationQueued: "已安排迁移。下次启动时再次确认；原数据将保留。",
      source: "来源", destination: "目标", files: "文件", checking: "检查中…", release: "打开官方下载页面",
      update_available: "有新版本可下载。", up_to_date: "当前已是最新版本。", no_release: "暂未发布新版本。",
      offline: "无法连接更新服务，请稍后重试。", timeout: "检查更新超时，请稍后重试。", rate_limited: "更新检查频率受限，请稍后重试。",
      invalid_response: "更新服务返回无效信息。", invalid_version: "无法比较版本信息。", currentVersion: "当前版本", latestVersion: "最新版本",
      dropped: "文件已加入输入列表，请核对类型、参数并预检。", dropBusy: "任务运行或退出等待期间不能添加输入文件。", exportTooLarge: "导出内容超过 32 MB，请从结果文件使用另存为。",
      diagnostics: "环境自检", diagnosticsHint: "仅检查本机环境，不会上传数据或安装组件。诊断文本可先查看再复制。",
      diagnosticsRefresh: "重新检查", diagnosticsCopy: "复制诊断信息", diagnosticsText: "查看诊断文本", diagnosticsTextLabel: "诊断信息（只读）",
      diagnosticsCopied: "诊断信息已复制。", diagnosticsCopyFailed: "未能自动复制。请选中下方诊断文本，按 Ctrl+C 复制。",
      diagnosticsLoadFailed: "未能完成环境检查，请重新检查。", diagnosticsInvalid: "客户端返回的诊断信息不完整。",
      diagnosticsPass: "通过", diagnosticsWarn: "需留意", diagnosticsFail: "需处理", diagnosticsRemedy: "处理方法",
    },
    en: {
      menu: "Desktop", local: "Desktop app", settings: "Settings", appearance: "Appearance", ai: "AI settings", system: "System and storage", mcp: "AI connection (MCP)",
      data: "Open data folder", migrate: "Migrate old data", updates: "Check for updates", tray: "Continue in background", exit: "Exit application", close: "Close",
      import: "Choose data files", save: "Save as", saved: "Saved", cancelled: "Cancelled", failed: "Operation failed", busy: "Working…",
      privacy: "Remembers appearance, language, project and conversation. Input files and experiment parameters are not restored.",
      bridge: "Connecting to the desktop app…", bridgeError: "Desktop connection failed. The workspace has not loaded. Please retry.", retry: "Retry connection",
      preferencesError: "Could not save desktop preferences. Current interface settings remain active.", waiting: "Waiting for tasks to finish before exiting. New submissions are paused.",
      cancelling: "Cancelling eligible tasks and waiting for a safe exit.", closeTitle: "Running tasks before exit", taskCount: "Active tasks: {count}",
      protected: "{count} task(s) are saving results and must finish safely.", stay: "Keep using", wait: "Exit after tasks finish", cancel: "Cancel tasks and exit",
      noTasks: "No tasks are running.", process: "Data processing", agent: "Assistant", queued: "Queued", running: "Running", saving: "Saving results",
      succeeded: "Completed", failedTask: "Failed", cancelledTask: "Cancelled", preflight: "Preflight", processing: "Processing", finalizing: "Saving results", committing: "Writing results",
      migrationHint: "Original data is retained. This schedules migration after a safe exit; confirm again on the next launch. Existing target data is never merged.",
      noMigration: "No old data is available to migrate.", migrationSchedule: "Schedule migration and exit", migrationQueued: "Migration scheduled. Confirm again at the next launch. Original data is retained.",
      source: "Source", destination: "Destination", files: "Files", checking: "Checking…", release: "Open official download page",
      update_available: "A new version is available.", up_to_date: "You are up to date.", no_release: "No release is available yet.",
      offline: "Cannot reach the update service. Try again later.", timeout: "Update check timed out. Try again later.", rate_limited: "Update checks are rate limited. Try again later.",
      invalid_response: "The update service returned invalid information.", invalid_version: "Version information could not be compared.", currentVersion: "Current version", latestVersion: "Latest version",
      dropped: "Files added to the input list. Check types and parameters, then run preflight.", dropBusy: "Cannot add input files while a task is running or exit is pending.", exportTooLarge: "Export exceeds 32 MB. Use Save as on the result file instead.",
      diagnostics: "Environment check", diagnosticsHint: "Checks this computer only. No data is uploaded and no components are installed. Review the diagnostic text before copying it.",
      diagnosticsRefresh: "Check again", diagnosticsCopy: "Copy diagnostics", diagnosticsText: "View diagnostic text", diagnosticsTextLabel: "Diagnostic information (read only)",
      diagnosticsCopied: "Diagnostic information copied.", diagnosticsCopyFailed: "Automatic copying failed. Select the diagnostic text below and press Ctrl+C to copy it.",
      diagnosticsLoadFailed: "The environment check could not finish. Please check again.", diagnosticsInvalid: "The desktop app returned an incomplete diagnostic report.",
      diagnosticsPass: "Passed", diagnosticsWarn: "Note", diagnosticsFail: "Action needed", diagnosticsRemedy: "What to do",
    },
  };
  let enabled = false;
  let hooks = {};
  let state = {};
  let ready = false;
  let saveTimer = null;
  let saveChain = Promise.resolve();
  let lastSaved = "";
  let pollTimer = null;
  let busy = false;
  let queuedPaths = [];
  let observer = null;
  let importing = false;
  let contrastQuery = null;
  let systemColorProbe = null;
  let pendingWindowAppearance = null;
  let windowAppearanceRequest = null;
  let lastWindowAppearance = "";
  let diagnosticsRequest = 0;

  const byId = (id) => document.getElementById(id);
  const api = () => window.pywebview && window.pywebview.api;
  const requested = () => Boolean(api() || window.__ELECTROCHEM_DESKTOP__ || new URLSearchParams(location.search).get("desktop") === "1");
  const lang = () => document.documentElement.lang.startsWith("en") ? "en" : "zh";
  const text = (key) => labels[lang()][key] || key;
  const locked = () => Boolean(enabled && state.closing && (state.closing.waiting || ["wait", "cancel"].includes(state.closing.mode)));
  const basename = (value) => String(value || "").split(/[\\/]/).pop();

  function element(tag, content, className) {
    const node = document.createElement(tag);
    if (content != null) node.textContent = content;
    if (className) node.className = className;
    return node;
  }

  function button(key, callback, id) {
    const node = element("button", text(key), "btn");
    node.type = "button";
    node.dataset.desktopLabel = key;
    if (id) node.id = id;
    node.addEventListener("click", callback);
    return node;
  }

  function status(message) {
    const node = byId("desktop-status");
    if (node) { node.textContent = message || ""; node.hidden = !message; }
  }

  async function call(method, ...args) {
    if (!api() || typeof api()[method] !== "function") throw new Error(text("bridgeError"));
    const result = await api()[method](...args);
    if (result && (result.status === "error" || result.status === "failed")) throw new Error(result.message || text("failed"));
    return result || {};
  }

  function opaqueHexColor(value) {
    const color = String(value || "").trim();
    if (/^#[\da-f]{6}$/i.test(color)) return color.toUpperCase();
    if (/^#[\da-f]{3}$/i.test(color)) return `#${color.slice(1).split("").map((digit) => digit + digit).join("")}`.toUpperCase();
    const rgb = color.match(/^rgba?\(\s*(\d+(?:\.\d+)?)\s*[, ]\s*(\d+(?:\.\d+)?)\s*[, ]\s*(\d+(?:\.\d+)?)(?:\s*[,/]\s*(\d+(?:\.\d+)?))?\s*\)$/i);
    if (!rgb || (rgb[4] != null && Number(rgb[4]) !== 1)) return null;
    const channels = rgb.slice(1, 4).map(Number);
    if (channels.some((channel) => !Number.isFinite(channel) || channel < 0 || channel > 255)) return null;
    return `#${channels.map((channel) => Math.round(channel).toString(16).padStart(2, "0")).join("")}`.toUpperCase();
  }

  function windowAppearance() {
    if (!document.body || typeof window.getComputedStyle !== "function") return null;
    const bodyStyle = window.getComputedStyle(document.body);
    const highContrast = Boolean(contrastQuery && contrastQuery.matches);
    let systemStyle = null;
    if (highContrast) {
      // A gradient body can have a transparent computed background, including in forced colors.
      // Resolve the OS palette explicitly instead of inventing a light/dark replacement.
      if (!systemColorProbe) {
        systemColorProbe = document.createElement("span");
        systemColorProbe.hidden = true;
        systemColorProbe.setAttribute("aria-hidden", "true");
        systemColorProbe.style.cssText = "background-color:Canvas;color:CanvasText";
        document.body.appendChild(systemColorProbe);
      }
      systemStyle = window.getComputedStyle(systemColorProbe);
    }
    // Native caption colors deliberately differ from the page and application header.
    const caption = opaqueHexColor(systemStyle ? systemStyle.backgroundColor : bodyStyle.getPropertyValue("--titlebar-bg"));
    const foreground = opaqueHexColor(systemStyle ? systemStyle.color : bodyStyle.getPropertyValue("--titlebar-text"));
    if (!caption || !foreground) return null;
    const channels = [1, 3, 5].map((index) => {
      const channel = parseInt(caption.slice(index, index + 2), 16) / 255;
      return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
    });
    const luminance = channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
    return { dark: luminance < .179, caption_color: caption, text_color: foreground, high_contrast: highContrast };
  }

  function syncWindowAppearance() {
    if (!enabled || !api() || typeof api().set_window_appearance !== "function") return Promise.resolve();
    const appearance = windowAppearance();
    if (!appearance) return Promise.resolve();
    pendingWindowAppearance = appearance;
    if (windowAppearanceRequest) return windowAppearanceRequest;
    // This channel is independent from preference storage. Only one native update is in flight;
    // rapid changes replace the pending value instead of allowing an old response to win.
    windowAppearanceRequest = (async () => {
      while (pendingWindowAppearance) {
        const current = pendingWindowAppearance;
        pendingWindowAppearance = null;
        const signature = JSON.stringify(current);
        if (signature === lastWindowAppearance) continue;
        try {
          await call("set_window_appearance", current);
          lastWindowAppearance = signature;
        } catch (_error) {
          // Unsupported window managers or a closing window must not interrupt the workspace.
        }
      }
    })().finally(() => {
      windowAppearanceRequest = null;
      if (pendingWindowAppearance) return syncWindowAppearance();
    });
    return windowAppearanceRequest;
  }

  function watchWindowAppearance() {
    if (typeof window.matchMedia === "function") {
      contrastQuery = window.matchMedia("(forced-colors: active)");
      if (typeof contrastQuery.addEventListener === "function") contrastQuery.addEventListener("change", syncWindowAppearance);
      else if (typeof contrastQuery.addListener === "function") contrastQuery.addListener(syncWindowAppearance);
    }
    window.addEventListener("electrochem:appearance-changed", syncWindowAppearance);
    syncWindowAppearance();
  }

  async function action(callback, target) {
    if (busy) return;
    busy = true;
    if (target) target.disabled = true;
    status(text("busy"));
    try {
      const result = await callback();
      status(result && (result.cancelled || result.status === "cancelled") ? text("cancelled") : "");
      return result;
    } catch (error) { status(`${text("failed")}: ${error.message}`); }
    finally { busy = false; if (target) target.disabled = false; }
  }

  function workspace(value) {
    const input = value && typeof value === "object" ? value : {};
    return {
      tab: input.tab === "project" ? "project" : "pro",
      project_id: typeof input.project_id === "string" ? input.project_id.slice(0, 200) : "",
      conversation_id: typeof input.conversation_id === "string" ? input.conversation_id.slice(0, 200) : "",
      assistant_open: input.assistant_open === true,
    };
  }

  function hydrate(preferences) {
    const saved = preferences && preferences.local_storage || {};
    for (const key of STORAGE_KEYS) {
      if (typeof saved[key] !== "string" || saved[key].length > 4096) continue;
      if (key.endsWith("_lang") && !["zh", "en"].includes(saved[key])) continue;
      try { localStorage.setItem(key, saved[key]); } catch (_error) { /* Current session can still open. */ }
    }
    if (window.ElectrochemTheme) window.ElectrochemTheme.init();
  }

  async function bootstrap() {
    if (!requested()) return;
    document.documentElement.dataset.desktop = "connecting";
    const loading = element("div", text("bridge"), "desktop-startup");
    loading.id = "desktop-startup";
    loading.setAttribute("role", "status");
    document.body.appendChild(loading);
    try {
      if (!api()) await new Promise((resolve, reject) => {
        const onReady = () => { clearTimeout(timer); resolve(); };
        const timer = setTimeout(() => { window.removeEventListener("pywebviewready", onReady); reject(new Error(text("bridgeError"))); }, 15000);
        window.addEventListener("pywebviewready", onReady, { once: true });
      });
      state = await call("get_state");
      enabled = true;
      hydrate(state.preferences);
      document.documentElement.dataset.desktop = "ready";
      loading.remove();
    } catch (error) {
      loading.textContent = error.message || text("bridgeError");
      loading.appendChild(button("retry", () => location.reload(), "desktop-retry"));
      throw error;
    }
  }

  function snapshot() {
    const local = {};
    for (const key of STORAGE_KEYS) {
      try { const value = localStorage.getItem(key); if (value != null) local[key] = value; }
      catch (_error) { const saved = state.preferences && state.preferences.local_storage; if (saved && typeof saved[key] === "string") local[key] = saved[key]; }
    }
    return { local_storage: local, workspace: workspace(hooks.getWorkspace ? hooks.getWorkspace() : state.preferences && state.preferences.workspace) };
  }

  function persist() {
    clearTimeout(saveTimer);
    if (!enabled || !ready) return saveChain;
    const preferences = snapshot();
    const serialized = JSON.stringify(preferences);
    if (serialized === lastSaved) return saveChain;
    // Serialize bridge writes so a slower old write cannot replace the latest preference.
    saveChain = saveChain.then(async () => {
      if (serialized === lastSaved) return;
      await call("save_preferences", preferences);
      lastSaved = serialized;
    }).catch(() => status(text("preferencesError")));
    return saveChain;
  }

  function changed() {
    if (!enabled || !ready) return;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(persist, 220);
  }

  function dialog(id, titleKey) {
    let node = byId(id);
    if (!node) {
      node = element("dialog", null, "desktop-dialog");
      node.id = id;
      const head = element("div", null, "desktop-dialog-head");
      const title = element("h2", text(titleKey));
      title.id = `${id}-title`;
      title.dataset.desktopLabel = titleKey;
      node.setAttribute("aria-labelledby", title.id);
      head.append(title, button("close", () => node.close()));
      node.append(head, element("div", null, "desktop-dialog-content"));
      document.body.appendChild(node);
    }
    return node;
  }

  function show(node) { if (!node.open) node.showModal(); }

  function showSettings() {
    const node = dialog("desktop-settings-dialog", "settings");
    const body = node.querySelector(".desktop-dialog-content");
    body.replaceChildren(element("p", text("privacy"), "panel-sub"));
    const row = element("div", null, "desktop-actions");
    row.append(
      button("appearance", () => { node.close(); window.ElectrochemAppearance.open(); }),
      button("ai", () => { node.close(); if (hooks.openAISettings) hooks.openAISettings(); }),
      button("system", () => { node.close(); if (hooks.openSystem) hooks.openSystem(); }),
    );
    body.append(row);
    show(node);
  }

  async function showMigration() {
    const node = dialog("desktop-migration-dialog", "migrate");
    const body = node.querySelector(".desktop-dialog-content");
    body.replaceChildren(element("p", text("checking")));
    show(node);
    try {
      const plan = await call("get_migration_plan");
      body.replaceChildren(element("p", text("migrationHint"), "panel-sub"));
      if (!(plan.candidates || []).length) body.append(element("p", text("noMigration")));
      for (const candidate of plan.candidates || []) {
        const section = element("section", null, "desktop-candidate");
        section.append(element("h3", candidate.label || candidate.source_id));
        section.append(element("p", `${text("source")}: ${candidate.source_dir || ""}`));
        section.append(element("p", `${text("destination")}: ${candidate.target_dir || ""}`));
        section.append(element("p", `${text("files")}: ${candidate.files_count || 0}`));
        if (candidate.reason) section.append(element("p", candidate.reason));
        const migrate = button("migrationSchedule", async () => {
          await action(async () => {
            await persist();
            await call("migrate_legacy", candidate.source_id);
            body.replaceChildren(element("p", text("migrationQueued")));
          }, migrate);
        });
        migrate.disabled = !candidate.can_migrate;
        section.append(migrate);
        body.append(section);
      }
    } catch (error) { body.replaceChildren(element("p", `${text("failed")}: ${error.message}`)); }
  }

  async function showUpdates() {
    const node = dialog("desktop-updates-dialog", "updates");
    const body = node.querySelector(".desktop-dialog-content");
    body.replaceChildren(element("p", text("checking")));
    show(node);
    try {
      const result = await call("check_updates");
      body.replaceChildren(element("p", text(result.state || "invalid_response")));
      body.append(element("p", `${text("currentVersion")}: ${result.current_version || state.version || "-"}`));
      if (result.latest_version) body.append(element("p", `${text("latestVersion")}: ${result.latest_version}`));
      if (result.release_notes) body.append(element("pre", result.release_notes, "desktop-release-notes"));
      if (result.update_available) body.append(button("release", () => action(() => call("open_external", "https://github.com/Sunnnnch/electro_data_process_tool/releases"))));
    } catch (error) { body.replaceChildren(element("p", `${text("failed")}: ${error.message}`)); }
  }

  async function showDiagnostics() {
    const node = dialog("desktop-diagnostics-dialog", "diagnostics");
    const body = node.querySelector(".desktop-dialog-content");
    const request = ++diagnosticsRequest;
    const active = () => request === diagnosticsRequest && node.open;
    const hint = element("p", text("diagnosticsHint"), "panel-sub");
    const resultBody = element("div", null, "desktop-diagnostics-result");
    resultBody.setAttribute("aria-live", "polite");
    resultBody.setAttribute("aria-busy", "true");
    resultBody.append(element("p", text("checking")));
    const feedback = element("p", "", "desktop-diagnostics-feedback");
    feedback.id = "desktop-diagnostics-feedback";
    feedback.setAttribute("role", "status");
    feedback.hidden = true;
    const actions = element("div", null, "desktop-actions");
    const reload = button("diagnosticsRefresh", showDiagnostics, "desktop-diagnostics-refresh");
    const copy = button("diagnosticsCopy", async () => {
      if (!reportText || !active()) return;
      copy.disabled = true;
      feedback.hidden = true;
      try {
        if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(reportText);
        if (active()) { feedback.textContent = text("diagnosticsCopied"); feedback.hidden = false; }
      } catch (_error) {
        if (active()) {
          feedback.textContent = text("diagnosticsCopyFailed");
          feedback.hidden = false;
          disclosure.open = true;
          raw.focus();
          raw.select();
        }
      } finally { if (active()) copy.disabled = false; }
    }, "desktop-diagnostics-copy");
    reload.disabled = true;
    copy.disabled = true;
    actions.append(reload, copy);
    let reportText = "";
    const disclosure = element("details", null, "desktop-diagnostics-text");
    disclosure.hidden = true;
    disclosure.append(element("summary", text("diagnosticsText")));
    const raw = element("textarea");
    raw.id = "desktop-diagnostics-raw";
    raw.readOnly = true;
    raw.rows = 8;
    raw.setAttribute("aria-label", text("diagnosticsTextLabel"));
    raw.spellcheck = false;
    disclosure.append(raw);
    body.replaceChildren(hint, resultBody, actions, feedback, disclosure);
    show(node);
    try {
      const result = await call("get_environment_report");
      if (!active()) return;
      const report = result.report;
      if (!report || !Array.isArray(report.checks) || !report.checks.length || !report.checks.every((item) => item && ["pass", "warn", "fail"].includes(item.status)) || typeof result.report_text !== "string" || !result.report_text.trim()) {
        throw new Error(text("diagnosticsInvalid"));
      }
      const localized = (item, key) => String((lang() === "en" && item[`${key}_en`]) || item[key] || "");
      resultBody.replaceChildren(element("p", localized(report, "summary"), "desktop-diagnostics-summary"));
      const list = element("ul", null, "desktop-diagnostics-checks");
      for (const check of report.checks) {
        const row = element("li", null, "desktop-diagnostics-check");
        row.dataset.checkStatus = check.status;
        const head = element("div", null, "desktop-diagnostics-check-head");
        const badge = element("span", text({ pass: "diagnosticsPass", warn: "diagnosticsWarn", fail: "diagnosticsFail" }[check.status]), "desktop-diagnostics-badge");
        head.append(element("h3", localized(check, "label")), badge);
        row.append(head, element("p", localized(check, "detail")));
        const remedy = localized(check, "remedy");
        if (remedy) {
          const guidance = element("p", null, "desktop-diagnostics-remedy");
          guidance.append(element("strong", `${text("diagnosticsRemedy")}: `), document.createTextNode(remedy));
          row.append(guidance);
        }
        list.append(row);
      }
      resultBody.append(list);
      reportText = result.report_text;
      raw.value = reportText;
      disclosure.hidden = false;
      copy.disabled = false;
    } catch (error) {
      if (!active()) return;
      const message = element("p", `${text("diagnosticsLoadFailed")} ${error.message || ""}`, "desktop-diagnostics-error");
      message.setAttribute("role", "alert");
      resultBody.replaceChildren(message);
    } finally {
      if (active()) { reload.disabled = false; resultBody.setAttribute("aria-busy", "false"); }
    }
  }

  async function resolveClose(choice) {
    await persist();
    const result = await call("resolve_close", choice);
    if (result.closing) state.closing = result.closing;
    else if (choice === "stay" || choice === "background") state.closing = { waiting: false, mode: null };
    else state.closing = { ...state.closing, waiting: true, mode: choice };
    const node = byId("desktop-close-dialog");
    if (node && node.open) node.close();
    refresh();
    schedulePoll();
  }

  function showClose(closing) {
    state.closing = closing || {};
    const node = dialog("desktop-close-dialog", "closeTitle");
    node.querySelector(".desktop-dialog-head button").onclick = () => action(() => resolveClose("stay"));
    node.oncancel = (event) => { event.preventDefault(); action(() => resolveClose("stay")); };
    const body = node.querySelector(".desktop-dialog-content");
    const tasks = Array.isArray(closing.tasks) ? closing.tasks : [];
    body.replaceChildren(element("p", text("taskCount").replace("{count}", String(closing.active_count ?? tasks.length))));
    const list = element("ul", null, "desktop-task-list");
    for (const task of tasks) {
      const phase = task.stage || task.phase || task.status || "running";
      list.append(element("li", `${text(task.kind === "agent" ? "agent" : "process")} · ${text(phase)}`));
    }
    body.append(list);
    if (closing.protected_count) body.append(element("p", text("protected").replace("{count}", String(closing.protected_count))));
    const actions = element("div", null, "desktop-actions");
    for (const [key, choice] of [["stay", "stay"], ["tray", "background"], ["wait", "wait"], ["cancel", "cancel"]]) {
      const control = button(key, () => action(() => resolveClose(choice)), `desktop-close-${choice}`);
      if (choice === "background") control.disabled = state.tray_available === false;
      actions.append(control);
    }
    body.append(actions);
    refresh();
    show(node);
  }

  function schedulePoll() {
    clearTimeout(pollTimer);
    if (!locked()) return;
    pollTimer = setTimeout(async () => {
      try { state = { ...state, ...await call("get_state") }; refresh(); }
      catch (error) { status(error.message); }
      schedulePoll();
    }, 1200);
  }

  function refresh() {
    if (!enabled) return;
    document.querySelectorAll("[data-desktop-label]").forEach((node) => { const value = text(node.dataset.desktopLabel); if (node.textContent !== value) node.textContent = value; });
    for (const id of ["desktop-tray", "desktop-close-background"]) {
      const control = byId(id);
      if (control) control.disabled = state.tray_available === false;
    }
    const banner = byId("desktop-exit-status");
    if (banner) {
      banner.hidden = !locked();
      const value = text(state.closing && state.closing.mode === "cancel" ? "cancelling" : "waiting");
      if (banner.querySelector("span").textContent !== value) banner.querySelector("span").textContent = value;
    }
    document.body.dataset.desktopClosing = locked() ? "true" : "false";
    // aria-disabled and the capture guard preserve each control's existing processing state.
    document.querySelectorAll(SUBMISSIONS).forEach((node) => {
      if (locked()) {
        if (!node.hasAttribute("data-desktop-previous-disabled")) node.dataset.desktopPreviousDisabled = node.getAttribute("aria-disabled") || "";
        node.setAttribute("aria-disabled", "true");
      } else if (node.hasAttribute("data-desktop-previous-disabled")) {
        if (node.dataset.desktopPreviousDisabled) node.setAttribute("aria-disabled", node.dataset.desktopPreviousDisabled);
        else node.removeAttribute("aria-disabled");
        delete node.dataset.desktopPreviousDisabled;
      }
    });
  }

  async function importPaths(paths) {
    if (!enabled || !ready) { queuedPaths.push(...(Array.isArray(paths) ? paths : [])); return; }
    if (locked() || importing || (hooks.isProcessing && hooks.isProcessing())) { status(text("dropBusy")); return; }
    const valid = [...new Set((Array.isArray(paths) ? paths : []).filter((value) => typeof value === "string" && value.trim()))];
    if (!valid.length) return;
    importing = true;
    try { await action(async () => { if (hooks.importPaths) await hooks.importPaths(valid); }); }
    finally { importing = false; }
  }

  async function chooseFiles() {
    if (locked()) { status(text("dropBusy")); return; }
    try {
      const result = await call("choose_import_files");
      await importPaths(result.file_paths || result.paths || []);
    } catch (error) { status(error.message); }
  }

  async function saveDownload(url, filename) {
    const target = new URL(url, location.href);
    if (target.protocol === "blob:") {
      const response = await fetch(target.href);
      const blob = await response.blob();
      if (blob.size > 32 * 1024 * 1024) throw new Error(text("exportTooLarge"));
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
      return call("save_export", data, filename || "export", blob.type || "application/octet-stream");
    }
    return call("save_download", target.href, filename || basename(target.pathname));
  }

  function enhanceExports() {
    document.querySelectorAll("[data-open-path]").forEach((source) => {
      if (source.dataset.desktopExport === "true" || !source.dataset.openPath) return;
      source.dataset.desktopExport = "true";
      const save = button("save", () => action(() => call("save_result", source.dataset.openPath, basename(source.dataset.openPath))));
      save.classList.add("mini", "desktop-save-result");
      source.insertAdjacentElement("afterend", save);
    });
  }

  function intercept(event) {
    if (!enabled) return;
    if (locked() && event.target.closest(SUBMISSIONS)) {
      event.preventDefault(); event.stopImmediatePropagation(); status(text("waiting")); return;
    }
    const anchor = event.target.closest("a[href]");
    if (!anchor) return;
    const url = new URL(anchor.href, location.href);
    const download = anchor.hasAttribute("download") || url.protocol === "blob:";
    const external = /^https?:$/.test(url.protocol) && (url.origin !== location.origin || anchor.closest(".help-guide-figure"));
    if (!download && !external) return;
    event.preventDefault(); event.stopImmediatePropagation();
    action(() => download ? saveDownload(url.href, anchor.getAttribute("download") || basename(url.pathname)) : call("open_external", url.href));
  }

  function init(context) {
    if (!enabled || byId("desktop-menu-open")) return;
    hooks = context || {};
    document.body.dataset.desktop = "true";
    const host = element("details", null, "desktop-menu");
    host.id = "desktop-menu";
    const summary = element("summary", text("menu"), "hero-ghost-btn");
    summary.id = "desktop-menu-open";
    summary.dataset.desktopLabel = "menu";
    host.append(summary);
    const menu = element("div", null, "desktop-menu-items");
    const localLabel = element("strong", text("local"));
    localLabel.dataset.desktopLabel = "local";
    menu.append(localLabel);
    const entries = [
      ["settings", showSettings], ["mcp", () => window.ElectrochemMCP.show()], ["import", chooseFiles], ["data", () => action(() => call("open_data_dir"))],
      ["migrate", showMigration], ["diagnostics", showDiagnostics], ["updates", showUpdates], ["tray", () => action(async () => { await persist(); return call("hide_to_tray"); })],
      ["exit", () => action(async () => { await persist(); const result = await call("request_exit"); if (result.closing) showClose(result.closing); return result; })],
    ];
    for (const [key, callback] of entries) {
      const item = button(key, () => { host.open = false; callback(); }, `desktop-${key}`);
      if (key === "tray") item.disabled = state.tray_available === false;
      menu.append(item);
    }
    host.append(menu);
    document.querySelector(".hero-controls").prepend(host);
    const feedback = element("p", "", "desktop-feedback");
    feedback.id = "desktop-status";
    feedback.setAttribute("role", "status");
    feedback.hidden = true;
    const banner = element("div", null, "desktop-exit-status");
    banner.id = "desktop-exit-status";
    banner.setAttribute("role", "status");
    banner.append(element("span"));
    document.querySelector(".hero").append(feedback, banner);
    document.addEventListener("click", intercept, true);
    document.addEventListener("change", changed);
    document.addEventListener("click", changed);
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && host.open) { host.open = false; summary.focus(); } });
    document.addEventListener("dragover", (event) => { if (event.dataTransfer && Array.from(event.dataTransfer.types).includes("Files")) event.preventDefault(); });
    document.addEventListener("drop", (event) => { if (event.dataTransfer && Array.from(event.dataTransfer.types).includes("Files")) event.preventDefault(); });
    window.addEventListener("electrochem:appearance-changed", changed);
    watchWindowAppearance();
    window.addEventListener("pagehide", persist);
    observer = new MutationObserver(() => { enhanceExports(); if (locked()) refresh(); });
    observer.observe(document.body, { childList: true, subtree: true });
    enhanceExports();
    refresh();
    if (state.migration_notice) status(String(state.migration_notice));
    schedulePoll();
  }

  function markReady() {
    ready = true;
    changed();
    if (queuedPaths.length) { const paths = queuedPaths; queuedPaths = []; importPaths(paths); }
  }

  window.addEventListener("electrochem:desktop-files", (event) => importPaths(event.detail && event.detail.paths));
  window.addEventListener("electrochem:desktop-close", (event) => { if (enabled) showClose(event.detail || {}); });
  window.addEventListener("electrochem:desktop-state", (event) => { if (enabled) { state = { ...state, ...event.detail }; refresh(); schedulePoll(); } });
  window.ElectrochemDesktop = { bootstrap, requested, init, markReady, changed, persist, refresh, importPaths, chooseFiles, saveDownload, syncWindowAppearance, getPreferencesSnapshot: snapshot, isEnabled: () => enabled, isReady: () => ready, isLocked: locked, getWorkspace: () => workspace(state.preferences && state.preferences.workspace) };
})();
