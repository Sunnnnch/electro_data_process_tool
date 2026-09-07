(function () {
  "use strict";

  function textOrEmpty(value) {
    return String(value || "");
  }

  function prepareReadingContent(html, lang) {
    // The caller has already rendered/sanitized the content. Make overflowing
    // reading regions keyboard-accessible without changing the rendered text.
    if (typeof document === "undefined" || typeof document.createElement !== "function") return html;
    const template = document.createElement("template");
    template.innerHTML = html;
    if (!template.content || typeof template.content.querySelectorAll !== "function") return html;
    template.content.querySelectorAll("pre, .math-display, .katex-display, math[display='block']").forEach((region) => {
      if (!region.hasAttribute("tabindex")) region.tabIndex = 0;
    });
    template.content.querySelectorAll("table").forEach((table) => {
      const region = document.createElement("div");
      region.className = "assistant-table-scroll";
      region.tabIndex = 0;
      region.setAttribute("role", "region");
      region.setAttribute("aria-label", lang === "en" ? "Data table; scroll horizontally to read all columns" : "数据表，可横向滚动查看所有列");
      table.replaceWith(region);
      region.appendChild(table);
    });
    return template.innerHTML;
  }

  function roleTextByRole(role, lang) {
    if (role === "agent") return "AI";
    return lang === "zh" ? "用户" : "User";
  }

  function renderMessageBody(options) {
    const opts = options || {};
    if (opts.role === "agent" && typeof opts.renderAgentContent === "function") {
      return prepareReadingContent(opts.renderAgentContent(opts.content || ""), opts.lang);
    }
    if (typeof opts.renderUserContent === "function") {
      return opts.renderUserContent(opts.content || "");
    }
    return textOrEmpty(opts.content);
  }

  function renderSourceBadges(options) {
    const opts = options || {};
    if (opts.role !== "agent") return "";
    const metadata = opts.metadata && typeof opts.metadata === "object" ? opts.metadata : {};
    const usage = metadata.context_usage && typeof metadata.context_usage === "object"
      ? metadata.context_usage
      : {};
    const translate = typeof opts.t === "function" ? opts.t : textOrEmpty;
    const escapeHtml = opts.escapeHtml || textOrEmpty;
    const sources = [];
    if (usage.professional_mode) sources.push(translate("assistant_source_professional"));
    if (usage.database) sources.push(translate("assistant_source_database"));
    if (usage.local_data) sources.push(translate("assistant_source_local_data"));
    if (!sources.length) return "";
    return `
      <div class="msg-sources">
        <span class="msg-sources-label">${escapeHtml(translate("assistant_source_label"))}</span>
        ${sources.map((source) => `<span class="msg-source-badge">${escapeHtml(source)}</span>`).join("")}
      </div>
    `;
  }

  function renderPendingApprovals(options) {
    const opts = options || {};
    if (opts.role !== "agent") return "";
    const metadata = opts.metadata && typeof opts.metadata === "object" ? opts.metadata : {};
    const approvals = Array.isArray(metadata.pending_approvals) ? metadata.pending_approvals : [];
    const resolvedIds = opts.resolvedApprovalIds instanceof Set ? opts.resolvedApprovalIds : new Set();
    const translate = typeof opts.t === "function" ? opts.t : textOrEmpty;
    const escapeHtml = opts.escapeHtml || textOrEmpty;
    const pending = approvals.filter((item) => {
      const approvalId = String((item && item.approval_id) || "").trim();
      return approvalId && !resolvedIds.has(approvalId);
    });
    if (!pending.length) return "";
    return pending
      .map((item) => {
        const approvalId = String(item.approval_id || "").trim();
        const summary = String(item.summary || translate("assistant_approval_unknown")).trim();
        const expiresAt = Number(item.expires_at_epoch_ms || 0);
        const expired = item.status === "expired" || (expiresAt > 0 && expiresAt <= Date.now());
        const rawDetails = item.details && typeof item.details === "object" ? item.details : {};
        const detailRows = Object.entries(rawDetails).map(([key, value]) => {
          const labelKey = `assistant_approval_detail_${key}`;
          const translatedLabel = translate(labelKey);
          const label = translatedLabel === labelKey ? key : translatedLabel;
          let renderedValue = value;
          if (typeof value === "boolean") {
            renderedValue = translate(value ? "assistant_approval_value_yes" : "assistant_approval_value_no");
          } else if (value && typeof value === "object") {
            renderedValue = JSON.stringify(value);
          } else if (value === "" || value === null || value === undefined) {
            renderedValue = translate("assistant_approval_value_empty");
          }
          return `
            <div class="msg-approval-detail-row">
              <span>${escapeHtml(label)}</span>
              <strong>${escapeHtml(String(renderedValue))}</strong>
            </div>
          `;
        }).join("");
        return `
          <div class="msg-approval${expired ? " expired" : ""}" data-approval-id="${escapeHtml(approvalId)}">
            <div class="msg-approval-title">${escapeHtml(translate(expired ? "assistant_approval_expired_title" : "assistant_approval_title"))}</div>
            <div class="msg-approval-summary">${escapeHtml(summary)}</div>
            ${detailRows ? `<div class="msg-approval-details">${detailRows}</div>` : ""}
            <div class="msg-approval-warning">${escapeHtml(translate(expired ? "assistant_approval_expired_warning" : "assistant_approval_warning"))}</div>
            ${expired ? "" : `
              <div class="msg-approval-actions">
                <button class="assistant-approval-btn approve" type="button" data-approval-action="approve" data-approval-id="${escapeHtml(approvalId)}" data-approval-summary="${escapeHtml(summary)}">${escapeHtml(translate("assistant_approval_confirm"))}</button>
                <button class="assistant-approval-btn decline" type="button" data-approval-action="decline" data-approval-id="${escapeHtml(approvalId)}" data-approval-summary="${escapeHtml(summary)}">${escapeHtml(translate("assistant_approval_cancel"))}</button>
              </div>
            `}
          </div>
        `;
      })
      .join("");
  }

  function renderMessageItem(options) {
    const opts = options || {};
    const escapeHtml = opts.escapeHtml || textOrEmpty;
    const role = opts.role === "agent" ? "agent" : "user";
    return `
      <div class="msg ${role}">
        <div class="meta">${roleTextByRole(role, opts.lang)} | ${escapeHtml(opts.timestamp || "")}</div>
        <div class="content">${renderMessageBody({ ...opts, role })}</div>
        ${renderSourceBadges({ ...opts, role })}
        ${renderPendingApprovals({ ...opts, role })}
        ${window.ElectrochemAssistantActions ? window.ElectrochemAssistantActions.renderCards({ ...opts, role }) : ""}
      </div>
    `;
  }

  function ensureChatLogReady(options) {
    const byId = options && options.byId;
    const log = typeof byId === "function" ? byId("chat-log") : null;
    if (!log) return null;
    const placeholder = log.querySelector(".placeholder");
    if (placeholder) {
      log.innerHTML = "";
    }
    return log;
  }

  function appendLocalMessage(options) {
    const opts = options || {};
    const log = ensureChatLogReady(opts);
    if (!log) return;
    const body = String(opts.content || "").trim();
    if (!body) return;
    log.insertAdjacentHTML("beforeend", renderMessageItem({ ...opts, content: body }));
    if (window.ElectrochemAssistantActions) window.ElectrochemAssistantActions.bind(log);
    log.scrollTop = log.scrollHeight;
  }

  function removeTypingIndicator(options) {
    const byId = options && options.byId;
    const el = typeof byId === "function" ? byId("chat-typing") : null;
    if (el) el.remove();
  }

  function showTypingIndicator(options) {
    const opts = options || {};
    const escapeHtml = opts.escapeHtml || textOrEmpty;
    const translate = typeof opts.t === "function" ? opts.t : textOrEmpty;
    const log = ensureChatLogReady(opts);
    if (!log) return;
    removeTypingIndicator(opts);
    log.insertAdjacentHTML(
      "beforeend",
      `
        <div id="chat-typing" class="msg agent typing">
          <div class="meta">AI | ${escapeHtml(translate("status_ai_typing"))}</div>
          <div class="content">
            <span>${escapeHtml(translate("typing_reply"))}</span>
            <span class="typing-dots"><span></span><span></span><span></span></span>
          </div>
        </div>
      `
    );
    log.scrollTop = log.scrollHeight;
  }

  function renderMessages(options) {
    const opts = options || {};
    const byId = opts.byId;
    const translate = typeof opts.t === "function" ? opts.t : textOrEmpty;
    const log = typeof byId === "function" ? byId("chat-log") : null;
    if (!log) return;
    removeTypingIndicator(opts);
    const messages = Array.isArray(opts.messages) ? opts.messages : [];
    if (!messages.length) {
      log.innerHTML = `<div class="placeholder">${translate("chat_no_messages")}</div>`;
      return;
    }
    const resolvedApprovalIds = new Set();
    messages.forEach((message) => {
      const metadata = message && message.metadata && typeof message.metadata === "object" ? message.metadata : {};
      const ids = Array.isArray(metadata.resolved_approval_ids) ? metadata.resolved_approval_ids : [];
      ids.forEach((approvalId) => {
        const cleanId = String(approvalId || "").trim();
        if (cleanId) resolvedApprovalIds.add(cleanId);
      });
    });
    log.innerHTML = messages
      .map((message) => {
        const role = message.role === "agent" ? "agent" : "user";
        return renderMessageItem({
          ...opts,
          content: message.content || "",
          metadata: message.metadata || {},
          resolvedApprovalIds,
          role,
          timestamp: message.timestamp || "",
        });
      })
      .join("");
    if (window.ElectrochemAssistantActions) window.ElectrochemAssistantActions.bind(log);
    log.scrollTop = log.scrollHeight;
  }

  function setPanelOpen(options) {
    const opts = options || {};
    const byId = opts.byId;
    const mask = typeof byId === "function" ? byId(opts.maskId || "") : null;
    const panel = typeof byId === "function" ? byId(opts.panelId || "") : null;
    if (mask) mask.classList.toggle("hidden", !opts.open);
    if (panel) panel.classList.toggle("hidden", !opts.open);
  }

  function focusRenameInput(listEl, conversationId) {
    if (!listEl || !conversationId) return;
    const input = listEl.querySelector(`.conv-title-input[data-rename-input="${conversationId}"]`);
    if (!input) return;
    input.focus();
    try {
      input.setSelectionRange(0, input.value.length);
    } catch (_err) {}
  }

  function renderConversations(options) {
    const opts = options || {};
    const listEl = opts.listEl;
    const escapeHtml = opts.escapeHtml || textOrEmpty;
    const translate = typeof opts.t === "function" ? opts.t : textOrEmpty;
    const callbacks = opts.callbacks || {};
    const items = Array.isArray(opts.items) ? opts.items : [];
    if (!listEl) return;
    if (!items.length) {
      listEl.innerHTML = `<div class="placeholder">${translate("chat_no_conversations")}</div>`;
      return;
    }

    listEl.innerHTML = items
      .map((item) => {
        const active = item.conversation_id === opts.currentConversationId ? "active" : "";
        const title = item.title || translate("conv_rename_default");
        const editing = item.conversation_id === opts.renamingConversationId;
        return `
          <div class="conv-item ${active}" data-id="${item.conversation_id}">
            <div class="conv-actions">
              ${
                editing
                  ? `
                    <button class="conv-save" data-save="${item.conversation_id}" title="${escapeHtml(translate("btn_save"))}">${escapeHtml(translate("btn_save"))}</button>
                    <button class="conv-cancel" data-cancel="${item.conversation_id}" title="${escapeHtml(translate("btn_close"))}">${escapeHtml(translate("btn_close"))}</button>
                  `
                  : `
                    <button class="conv-rename" data-rename="${item.conversation_id}" title="${escapeHtml(translate("conv_rename_action"))}">${escapeHtml(translate("conv_rename_action"))}</button>
                    <button class="conv-del" data-del="${item.conversation_id}" title="${escapeHtml(translate("conv_delete_action"))}">${escapeHtml(translate("conv_delete_action"))}</button>
                  `
              }
            </div>
            ${
              editing
                ? `<input class="conv-title-input" data-rename-input="${item.conversation_id}" value="${escapeHtml(title)}" maxlength="80">`
                : `<div class="title">${escapeHtml(title)}</div>`
            }
            <div class="meta">${escapeHtml(item.provider || "-")} | ${escapeHtml(item.updated_at || "")}</div>
          </div>
        `;
      })
      .join("");

    listEl.querySelectorAll(".conv-item").forEach((el) => {
      el.addEventListener("click", (event) => {
        if (event.target.closest(".conv-actions") || event.target.closest(".conv-title-input")) return;
        if (typeof callbacks.open === "function") callbacks.open(el.dataset.id);
      });
    });

    listEl.querySelectorAll(".conv-del").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        if (typeof callbacks.delete === "function") callbacks.delete(btn.dataset.del);
      });
    });

    listEl.querySelectorAll(".conv-rename").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        if (typeof callbacks.startRename === "function") callbacks.startRename(btn.dataset.rename);
      });
    });

    listEl.querySelectorAll(".conv-save").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        const cid = btn.dataset.save;
        const input = listEl.querySelector(`.conv-title-input[data-rename-input="${cid}"]`);
        if (typeof callbacks.saveRename === "function") callbacks.saveRename(cid, input ? input.value : "");
      });
    });

    listEl.querySelectorAll(".conv-cancel").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        if (typeof callbacks.cancelRename === "function") callbacks.cancelRename(btn.dataset.cancel);
      });
    });

    listEl.querySelectorAll(".conv-title-input").forEach((input) => {
      input.addEventListener("click", (event) => event.stopPropagation());
      input.addEventListener("keydown", (event) => {
        const cid = input.getAttribute("data-rename-input") || "";
        if (event.key === "Enter") {
          event.preventDefault();
          if (typeof callbacks.saveRename === "function") callbacks.saveRename(cid, input.value);
        } else if (event.key === "Escape") {
          event.preventDefault();
          if (typeof callbacks.cancelRename === "function") callbacks.cancelRename(cid);
        }
      });
    });
  }

  function listLLMProviders(modelsByProvider) {
    return Object.keys(modelsByProvider || {}).filter((key) => {
      const value = modelsByProvider[key];
      return value && typeof value === "object";
    });
  }

  function updateLLMKeyHint(options) {
    const opts = options || {};
    const byId = opts.byId;
    const translate = typeof opts.t === "function" ? opts.t : textOrEmpty;
    const provider = opts.provider;
    const entry = (provider && opts.modelsByProvider && opts.modelsByProvider[provider]) || {};
    const hintEl = typeof byId === "function" ? byId("llm-key-hint") : null;
    const sourceEl = typeof byId === "function" ? byId("llm-source-hint") : null;
    if (hintEl) {
      hintEl.textContent = entry && entry.has_api_key ? translate("llm_key_configured") : translate("llm_key_missing");
    }
    if (!sourceEl) return;
    const envName = entry.api_key_env || `${String(provider || "").toUpperCase()}_API_KEY`;
    if (entry.api_key_source === "env") {
      sourceEl.textContent = translate("llm_key_source_env").replace("{env}", envName);
    } else if (entry.api_key_source === "env_empty") {
      sourceEl.textContent = translate("llm_key_source_env_empty").replace("{env}", envName);
    } else if (entry.api_key_source === "saved") {
      sourceEl.textContent = translate("llm_key_source_saved");
    } else {
      sourceEl.textContent = translate("llm_key_source_none");
    }
  }

  function applyLLMProviderPreset(options) {
    const opts = options || {};
    const byId = opts.byId;
    const provider = opts.provider;
    const entry = (provider && opts.modelsByProvider && opts.modelsByProvider[provider]) || {};
    if (Object.keys(entry).length > 0 && typeof byId === "function") {
      if (byId("llm-model")) byId("llm-model").value = String(entry.model || "");
      if (byId("llm-base-url")) byId("llm-base-url").value = String(entry.base_url || "");
      if (byId("llm-timeout")) byId("llm-timeout").value = entry.timeout !== undefined ? String(entry.timeout) : "";
    }
    updateLLMKeyHint(opts);
  }

  function renderLLMProviders(options) {
    const opts = options || {};
    const byId = opts.byId;
    const select = typeof byId === "function" ? byId("llm-provider") : null;
    if (!select) return "";
    const providers = listLLMProviders(opts.modelsByProvider);
    const previous = select.value;
    if (!providers.length) {
      select.innerHTML = '<option value="">-</option>';
      select.value = "";
      applyLLMProviderPreset({ ...opts, provider: "" });
      return "";
    }
    select.innerHTML = "";
    providers.forEach((provider) => {
      const option = document.createElement("option");
      option.value = provider;
      option.textContent = provider;
      select.appendChild(option);
    });
    const pick = providers.includes(previous)
      ? previous
      : providers.includes(opts.defaultProvider)
        ? opts.defaultProvider
        : providers[0];
    select.value = pick;
    applyLLMProviderPreset({ ...opts, provider: pick });
    return pick;
  }

  window.ElectrochemAssistantPage = {
    appendLocalMessage,
    applyLLMProviderPreset,
    ensureChatLogReady,
    focusRenameInput,
    listLLMProviders,
    removeTypingIndicator,
    renderConversations,
    renderLLMProviders,
    renderMessageBody,
    renderMessageItem,
    renderMessages,
    renderPendingApprovals,
    renderSourceBadges,
    roleTextByRole,
    setPanelOpen,
    showTypingIndicator,
    updateLLMKeyHint,
  };
})();
