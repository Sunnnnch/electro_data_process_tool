(function () {
  "use strict";

  const VALID_STEP_STATUSES = new Set(["complete", "issue", "running", "optional", "pending"]);

  function textOrEmpty(value) {
    return String(value || "");
  }

  function processTypeCardDescription(card, translate) {
    const key = String(card && card.descriptionKey ? card.descriptionKey : "");
    const translated = key && typeof translate === "function" ? translate(key) : "";
    if (translated && translated !== key) return translated;
    return String(card && card.summary ? card.summary : "");
  }

  function renderProcessTypeCards(options) {
    const opts = options || {};
    const container = opts.container;
    const schema = opts.schema;
    const schemaClient = opts.processSchemaClient;
    const escapeHtml = opts.escapeHtml || textOrEmpty;
    const selectedTypes = Array.isArray(opts.selectedTypes)
      ? opts.selectedTypes.map((item) => String(item || "").toUpperCase())
      : [];
    if (!container || !schema || !schemaClient || typeof schemaClient.buildModuleCards !== "function") return [];

    let cards = schemaClient.buildModuleCards(schema, selectedTypes);
    if (!Array.isArray(cards) || !cards.length) return [];
    if (!cards.some((card) => card.selected)) {
      const lsvIndex = cards.findIndex((card) => card.key === "LSV");
      const defaultIndex = lsvIndex >= 0 ? lsvIndex : 0;
      cards = cards.map((card, index) => ({ ...card, selected: index === defaultIndex }));
    }

    container.innerHTML = cards
      .map((card) => {
        const title = card.displayName || card.key;
        const desc = processTypeCardDescription(card, opts.t);
        return `
          <label class="mode-card ${escapeHtml(card.cssClass || "")}" data-module-key="${escapeHtml(card.key)}" data-module-input="${escapeHtml(card.inputKind || "")}">
            <input type="checkbox" class="proc-type-check" value="${escapeHtml(card.key)}" ${card.selected ? "checked" : ""} aria-label="${escapeHtml(title)}">
            <span class="mode-card-main">
              <span class="mode-card-title">${escapeHtml(title)}</span>
              <span class="mode-card-desc">${escapeHtml(desc)}</span>
            </span>
          </label>
        `;
      })
      .join("");
    return cards;
  }

  function setResultTab(tabName) {
    const normalized = tabName === "history" ? "history" : "current";
    const card = document.querySelector(".results-card");
    if (card) card.classList.toggle("show-history", normalized === "history");
    document.querySelectorAll(".result-tab").forEach((btn) => {
      const active = btn.dataset.resultTab === normalized;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    return normalized;
  }

  function setPreflightItem(options) {
    const opts = options || {};
    const key = String(opts.key || "");
    const byId = opts.byId;
    const item = document.querySelector(`[data-preflight-item="${key}"]`);
    const valueEl = typeof byId === "function" ? byId(`preflight-${key === "files" ? "files" : key}-state`) : null;
    if (item) {
      item.classList.remove("pending", "running", "ok", "issue");
      item.classList.add(opts.state || "pending");
    }
    if (valueEl) {
      valueEl.removeAttribute("data-i18n");
      valueEl.textContent = opts.label || "";
    }
  }

  function renderPreflightFileDetail(options) {
    const opts = options || {};
    const escapeHtml = opts.escapeHtml || textOrEmpty;
    const fileNameOnly = opts.fileNameOnly || textOrEmpty;
    const translate = typeof opts.t === "function" ? opts.t : textOrEmpty;
    const detail = opts.detail;
    const toggleLabel = opts.toggleLabel;
    const open = Boolean(opts.open);

    if (toggleLabel) {
      toggleLabel.setAttribute("data-detail-label", open ? translate("preflight_detail_hide") : translate("preflight_detail_show"));
    }
    if (!detail) return;
    detail.classList.toggle("hidden", !open);
    if (!open) return;

    const scan = opts.scan && typeof opts.scan === "object" ? opts.scan : null;
    if (!scan) {
      detail.innerHTML = `<div class="placeholder">${escapeHtml(translate("preflight_detail_empty"))}</div>`;
      return;
    }
    const preflightModel = opts.preflightModel;
    if (!preflightModel || typeof preflightModel.buildFileDetailView !== "function") return;
    const view = preflightModel.buildFileDetailView(
      scan,
      opts.selectedTypes || [],
      preflightModel.defaultTypes,
      opts.moduleDescriptors || [],
    );
    detail.innerHTML = `
      <div class="preflight-detail-summary">
        ${view.metrics
          .map(
            (metric) => `
              <div class="preflight-detail-stat">
                <span>${escapeHtml(translate(metric.labelKey))}</span>
                <strong>${escapeHtml(String(metric.value ?? ""))}</strong>
              </div>
            `,
          )
          .join("")}
      </div>
      <div class="preflight-detail-grid">
        ${view.cards
          .map((card) => {
            return `
              <section class="preflight-type-card ${card.ok ? "ok" : "issue"}">
                <div class="preflight-type-head"><span>${escapeHtml(card.label || card.dtype)}</span><strong>${card.matched}</strong></div>
                <div class="preflight-type-rule">${escapeHtml(translate("preflight_detail_rule"))}: ${escapeHtml(card.rule)}</div>
                ${
                  card.examples.length
                    ? `<ul class="preflight-examples">${card.examples
                        .map((file) => `<li title="${escapeHtml(String(file || ""))}">${escapeHtml(fileNameOnly(file))}</li>`)
                        .join("")}</ul>`
                    : `<div class="preflight-type-rule">${escapeHtml(translate("preflight_detail_no_examples"))}</div>`
                }
              </section>
            `;
          })
          .join("")}
      </div>
      ${
        view.irPairings.length
          ? `
            <section class="preflight-ir-section">
              <strong>${escapeHtml(translate("preflight_ir_pairings"))}</strong>
              <div class="preflight-ir-grid">
                ${view.irPairings
                  .map((pairing) => {
                    const target = pairing.status === "manual"
                      ? translate("preflight_ir_manual")
                      : pairing.eisFile
                        ? fileNameOnly(pairing.eisFile)
                        : "-";
                    const candidates = pairing.candidates.length > 1
                      ? `<div class="preflight-ir-candidates">${pairing.candidates
                          .map((file) => escapeHtml(fileNameOnly(file)))
                          .join(", ")}</div>`
                      : "";
                    return `
                      <article class="preflight-ir-pair ${pairing.ok ? "ok" : "issue"}">
                        <div class="preflight-ir-files">
                          <span title="${escapeHtml(pairing.lsvFile)}">${escapeHtml(fileNameOnly(pairing.lsvFile))}</span>
                          <b>&rarr;</b>
                          <span title="${escapeHtml(pairing.eisFile)}">${escapeHtml(target)}</span>
                        </div>
                        <div class="preflight-ir-meta">
                          <strong>${escapeHtml(translate(pairing.statusLabelKey))}</strong>
                          <span>${escapeHtml([pairing.scope, pairing.method].filter(Boolean).join(" / "))}</span>
                        </div>
                        ${pairing.ok ? "" : `<div class="preflight-ir-message">${escapeHtml(pairing.message)}</div>`}
                        ${candidates}
                      </article>
                    `;
                  })
                  .join("")}
              </div>
            </section>
          `
          : ""
      }
      ${
        view.warnings.length
          ? `
            <section class="preflight-warnings">
              <strong>${escapeHtml(translate("preflight_detail_warnings"))}</strong>
              <ul>
                ${view.warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}
              </ul>
            </section>
          `
          : ""
      }
    `;
  }

  function renderPreflightChecks(options) {
    const opts = options || {};
    const preflightModel = opts.preflightModel;
    if (!preflightModel || typeof preflightModel.buildCheckItems !== "function") return null;
    const model = preflightModel.buildCheckItems(opts.preflight, opts.state || "pending", opts.message || "");
    const translate = typeof opts.t === "function" ? opts.t : textOrEmpty;
    (preflightModel.checkKeys || []).forEach((key) => {
      const item = (model.items && model.items[key]) || { state: "pending", labelKey: "preflight_status_pending" };
      setPreflightItem({
        byId: opts.byId,
        key,
        label: translate(item.labelKey || "preflight_status_pending"),
        state: item.state,
      });
    });
    return model.scan || null;
  }

  function syncProcessModulePanels(options) {
    const opts = options || {};
    const selected = Array.isArray(opts.selectedTypes) ? opts.selectedTypes.map((item) => String(item || "").toUpperCase()) : [];
    const selectedSet = new Set(selected);
    const currentExpanded = opts.expandedModules instanceof Set ? opts.expandedModules : new Set();
    const expanded = new Set(Array.from(currentExpanded).filter((dtype) => selectedSet.has(dtype)));
    const translate = typeof opts.t === "function" ? opts.t : textOrEmpty;
    if (selected.length && !selected.some((dtype) => expanded.has(dtype))) {
      expanded.add(selected[0]);
    }
    document.querySelectorAll(".dtype-panel").forEach((panel) => {
      const dtype = String(panel.dataset.dtype || "").toUpperCase();
      const visible = selected.includes(dtype);
      const isExpanded = visible && expanded.has(dtype);
      panel.classList.toggle("module-collapsed", visible && !isExpanded);
      const head = panel.querySelector(".mode-panel-head");
      if (head) {
        head.setAttribute("role", "button");
        head.setAttribute("tabindex", visible ? "0" : "-1");
        head.setAttribute("aria-expanded", isExpanded ? "true" : "false");
        head.setAttribute("data-toggle-label", isExpanded ? translate("module_collapse") : translate("module_expand"));
      }
    });
    return expanded;
  }

  function toggleModuleExpansion(dtype, expandedModules) {
    const target = String(dtype || "").toUpperCase();
    const expanded = expandedModules instanceof Set ? new Set(expandedModules) : new Set();
    if (!target) return expanded;
    if (expanded.has(target)) {
      expanded.delete(target);
    } else {
      expanded.add(target);
    }
    return expanded;
  }

  function keepActiveProcessStepVisible(btn) {
    if (!btn) return;
    const scroller = btn.closest(".process-stepper");
    if (!scroller) return;
    const top = btn.offsetTop;
    const bottom = top + btn.offsetHeight;
    const viewTop = scroller.scrollTop;
    const viewBottom = viewTop + scroller.clientHeight;
    if (top < viewTop) {
      scroller.scrollTop = top;
    } else if (bottom > viewBottom) {
      scroller.scrollTop = bottom - scroller.clientHeight;
    }
  }

  function setActiveProcessStep(options) {
    const opts = options || {};
    const normalized = String(opts.stepKey || "");
    if (normalized && normalized === opts.currentStepKey && !opts.keepVisible) return opts.currentStepKey || "";
    let activeBtn = null;
    document.querySelectorAll(".process-step").forEach((btn) => {
      const active = btn.dataset.stepKey === normalized;
      btn.classList.toggle("active", active);
      if (active) activeBtn = btn;
    });
    if (opts.keepVisible !== false) {
      keepActiveProcessStepVisible(activeBtn);
    }
    return normalized;
  }

  function getProcessStepEntries(options) {
    const opts = options || {};
    const byId = opts.byId;
    return [...document.querySelectorAll(".process-step")]
      .map((btn) => {
        if (btn.dataset.stepKey === "result") return null;
        const target = typeof byId === "function" ? byId(btn.dataset.stepTarget || "") : null;
        if (!target || !target.getClientRects().length) return null;
        const rect = target.getBoundingClientRect();
        return {
          key: btn.dataset.stepKey || "",
          top: rect.top + window.scrollY,
        };
      })
      .filter(Boolean)
      .sort((a, b) => a.top - b.top);
  }

  function setProcessStepStatus(options) {
    const opts = options || {};
    const btn = document.querySelector(`.process-step[data-step-key="${opts.stepKey}"]`);
    if (!btn) return;
    const normalized = VALID_STEP_STATUSES.has(opts.status) ? opts.status : "pending";
    btn.classList.remove("complete", "issue", "running", "optional", "pending");
    btn.classList.add(normalized);
    const statusEl = btn.querySelector("[data-step-status]");
    if (statusEl) {
      const labelKey = `step_status_${normalized}`;
      statusEl.textContent = typeof opts.t === "function" ? opts.t(labelKey) : labelKey;
      statusEl.setAttribute("data-i18n", labelKey);
    }
  }

  window.ElectrochemProcessPage = {
    getProcessStepEntries,
    keepActiveProcessStepVisible,
    processTypeCardDescription,
    renderPreflightChecks,
    renderPreflightFileDetail,
    renderProcessTypeCards,
    setActiveProcessStep,
    setPreflightItem,
    setProcessStepStatus,
    setResultTab,
    syncProcessModulePanels,
    toggleModuleExpansion,
  };
})();
