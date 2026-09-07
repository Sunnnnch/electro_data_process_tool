(function () {
  "use strict";

  let provider;
  let active = null;
  let revision = 0;
  const labels = {
    replicate_title: "重复实验统计", replicate_close: "关闭", replicate_empty: "尚未保存重复组。请在项目结果中勾选独立实验后创建。",
    replicate_name: "重复组名称", replicate_members: "实验成员", replicate_include: "纳入", replicate_reason: "排除原因",
    replicate_confirm: "我确认这条记录来自独立实验，且不是其他成员的复算版本", replicate_source_verified: "已记录原始来源指纹",
    replicate_source_unverified: "缺少完整来源证据", replicate_deleted: "原记录已删除，不计入统计", replicate_review: "更新统计",
    replicate_save: "保存重复组", replicate_saved: "重复组已保存", replicate_changed: "成员或设置已改变，请更新统计后保存。",
    replicate_csv: "导出测量点与统计 CSV", replicate_svg: "导出误差条 SVG", replicate_metric: "指标", replicate_n: "有效 n",
    replicate_mean: "均值", replicate_sd: "样本标准差", replicate_value: "测量值", replicate_unit: "单位", replicate_status: "状态",
    replicate_undefined: "未定义", replicate_missing: "缺值", replicate_single: "仅 1 项，标准差未定义", replicate_unit_mismatch: "量纲不一致，不汇总",
    replicate_unit_unknown: "单位未知，不汇总", replicate_blocked: "请先解决来源问题", replicate_ok: "可汇总", replicate_nonfinite: "数值超出范围，不汇总",
    replicate_excluded: "已排除", replicate_included: "已纳入", replicate_unverified: "请确认独立性", replicate_same_source: "同源版本冲突",
    replicate_method: "蓝色圆点为独立实验测量值，绿色菱形及误差条为均值 ± 样本标准差（n−1）。标准差不是标准误或置信区间；同源复算版本不能增加 n。",
    replicate_select_first: "请先在项目结果中勾选独立实验。", replicate_loading: "正在核对实验来源与统计…",
    replicate_open_saved: "打开已保存的重复组", replicate_saved_only: "保存后可导出当前统计。", replicate_source: "实验来源与版本",
    replicate_conditions_title: "计算口径核对", replicate_conditions_confirm: "我已核对计算口径与实验记录，确认纳入实验的指标可比较",
  };
  const t = (ctx, key) => { const value = ctx.t(key); return value === key ? (labels[key] || key) : value; };
  const esc = (ctx, value) => ctx.escapeHtml(String(value ?? ""));
  const number = (value) => value === null || value === undefined ? "—" : String(Number(Number(value).toPrecision(7)));
  const dialog = (ctx) => ctx.byId("project-replicates-dialog");
  const endpoint = (projectId) => `/api/v1/projects/${encodeURIComponent(projectId)}`;
  const groupEndpoint = (id) => `/api/v1/replicate-groups/${encodeURIComponent(id)}`;

  async function request(ctx, url, payload) {
    const response = await ctx.apiFetch(url, payload === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok || result.status !== "success") throw new Error(result.message || String(response.status));
    return result;
  }

  function shell(ctx) {
    const el = dialog(ctx);
    el.innerHTML = `<div class="section-head"><h3>${esc(ctx, t(ctx, "replicate_title"))}</h3><button id="replicate-close" class="btn mini" type="button">${esc(ctx, t(ctx, "replicate_close"))}</button></div><div id="replicate-body"></div><p id="replicate-status" class="send-status" aria-live="polite"></p>`;
    ctx.byId("replicate-close").onclick = () => el.close();
    const menu = ctx.byId("project-more-menu");
    if (menu) menu.open = false;
    if (!el.open) el.showModal();
  }

  function message(ctx, value) { const node = ctx.byId("replicate-status"); if (node) node.textContent = value; }
  function busy(ctx, value) {
    if (active) active.busy = value;
    const fields = ctx.byId("replicate-fields");
    if (fields) fields.disabled = value;
    const save = ctx.byId("replicate-save");
    if (save) save.disabled = value || !active || active.dirty || !active.group.can_save;
  }

  function readDraft(ctx) {
    const group = active.group;
    const exclusions = [], confirmations = [];
    group.members.forEach((member, index) => {
      if (member.status === "deleted") return;
      const include = ctx.byId(`replicate-include-${index}`);
      if (include && !include.checked) exclusions.push({ record_key: member.record_key, reason: ctx.byId(`replicate-reason-${index}`).value });
      const confirm = ctx.byId(`replicate-confirm-${index}`);
      if (confirm && confirm.checked) confirmations.push(member.record_key);
    });
    const conditions = ctx.byId("replicate-conditions-confirm");
    return { name: ctx.byId("replicate-name").value, record_keys: group.record_keys.slice(), exclusions,
      analysis_conditions_confirmation: conditions && conditions.checked ? group.analysis_conditions.signature : "",
      independence_confirmed_keys: confirmations, ...(group.group_id ? { group_id: group.group_id, revision: group.revision } : {}) };
  }

  function markChanged(ctx) {
    if (!active) return;
    active.dirty = true;
    busy(ctx, false);
    ctx.byId("replicate-chart").replaceChildren();
    const statistics = ctx.byId("replicate-chart").previousElementSibling;
    if (statistics) statistics.hidden = true;
    for (const id of ["replicate-csv", "replicate-svg"]) { const node = ctx.byId(id); if (node) node.hidden = true; }
    message(ctx, t(ctx, "replicate_changed"));
  }

  function plot(ctx, metric) {
    if (!metric || !["ok", "single"].includes(metric.status)) return "";
    const points = metric.points.filter((point) => point.included && point.value !== null);
    const mean = metric.mean, sd = metric.sample_sd;
    const limits = points.map((point) => point.value).concat([mean - (sd || 0), mean + (sd || 0)]);
    const minimum = Math.min(...limits), maximum = Math.max(...limits);
    if (!limits.every(Number.isFinite)) return "";
    const scale = Math.max(Math.abs(minimum), Math.abs(maximum), 1);
    const span = maximum / scale - minimum / scale || Math.max(Math.abs(minimum / scale) * .1, 1 / scale);
    const low = minimum / scale - span * .15, high = maximum / scale + span * .15;
    const y = (value) => 240 - (value / scale - low) / (high - low) * 190;
    const items = points.map((point, index) => {
      const x = 135 + index * 350 / Math.max(1, points.length - 1);
      return `<circle data-chart-series="measurement" data-chart-part="halo" cx="${x}" cy="${y(point.value)}" r="5" fill="#236db4" stroke="#163444" stroke-width="1.5"><title>${esc(ctx, point.name)}: ${number(point.value)}</title></circle><text x="${x}" y="260" text-anchor="middle">${index + 1}</text>`;
    }).join("");
    const errorPath = sd === null ? "" : `M610 ${y(mean + sd)} V${y(mean - sd)} M599 ${y(mean + sd)} H621 M599 ${y(mean - sd)} H621`;
    const error = sd === null ? "" : `<path data-chart-part="halo" d="${errorPath}" stroke="#163444" stroke-width="4"/><path data-chart-series="sample-sd" d="${errorPath}" stroke="#087856" stroke-width="2"/>`;
    const ticks = Array.from({ length: 5 }, (_, index) => {
      const value = (low + (high - low) * index / 4) * scale;
      return `<text x="85" y="${y(value) + 4}" text-anchor="end">${number(value)}</text>`;
    }).join("");
    return `<svg class="replicate-plot" data-chart-preview="vector" viewBox="0 0 720 290" width="720" role="img" aria-label="${esc(ctx, metric.label)}"><rect data-chart-part="background" width="720" height="290" fill="white"/><g data-chart-part="text" font-family="Arial, Microsoft YaHei, sans-serif" font-size="12" fill="#163444"><text x="30" y="24">${esc(ctx, metric.label)} (${esc(ctx, metric.unit)}) · n=${metric.n}</text><path data-chart-part="axis" d="M95 45 V240 H675" stroke="#476779" fill="none"/>${ticks}${items}${error}<polygon data-chart-series="mean" data-chart-marker="diamond" data-chart-part="halo" points="610,${y(mean) - 7} 617,${y(mean)} 610,${y(mean) + 7} 603,${y(mean)}" fill="#087856" stroke="#163444" stroke-width="1.5"/><text x="610" y="260" text-anchor="middle">${esc(ctx, t(ctx, "replicate_mean"))} ± SD</text></g></svg>`;
  }

  function renderMetric(ctx) {
    if (!active) return;
    const select = ctx.byId("replicate-metric");
    const metric = active.group.metrics.find((item) => item.key === select.value);
    active.metric = metric && metric.key;
    ctx.byId("replicate-chart").innerHTML = !active.dirty ? plot(ctx, metric) : "";
    if (window.ElectrochemChartPreview) window.ElectrochemChartPreview.refresh(ctx.byId("replicate-chart"));
    active.group.members.forEach((member, index) => {
      const measurement = member.metrics[select.value];
      ctx.byId(`replicate-value-${index}`).textContent = measurement ? `${number(measurement.value)} ${measurement.unit}` : t(ctx, "replicate_missing");
    });
    const svg = ctx.byId("replicate-svg");
    svg.hidden = active.dirty || !active.group.group_id || !metric || !["ok", "single"].includes(metric.status);
    if (!svg.hidden) svg.href = `${groupEndpoint(active.group.group_id)}/export?format=svg&metric=${encodeURIComponent(metric.key)}`;
  }

  function render(ctx, group) {
    const oldMetric = active && active.metric;
    active = { group, projectId: group.project_id, metric: oldMetric, dirty: false, busy: false };
    const rows = group.members.map((member, index) => {
      const deleted = member.status === "deleted";
      const source = member.source || {};
      const files = (source.files || []).map((file) => `${file.file_name}: ${file.sha256 || "—"}`).join("\n");
      return `<tr><td><input class="replicate-include" id="replicate-include-${index}" type="checkbox" ${member.included ? "checked" : ""} ${deleted ? "disabled" : ""} aria-label="${esc(ctx, t(ctx, "replicate_include") + " " + member.name)}"></td><td><strong>${index + 1}. ${esc(ctx, member.name)}</strong><div class="panel-sub">${esc(ctx, member.timestamp || "")} · ${esc(ctx, member.run_id || "—")}</div><div>${esc(ctx, t(ctx, `replicate_${member.status}`))}</div>${deleted ? "" : `<details><summary>${esc(ctx, t(ctx, "replicate_source"))}</summary><p>${esc(ctx, t(ctx, source.state === "verified" ? "replicate_source_verified" : "replicate_source_unverified"))}</p><pre>${esc(ctx, files)}</pre></details>`}${!deleted && source.state !== "verified" ? `<label class="compact-check"><input class="replicate-confirm" id="replicate-confirm-${index}" type="checkbox" ${member.independence_confirmed ? "checked" : ""}><span>${esc(ctx, t(ctx, "replicate_confirm"))}</span></label>` : ""}</td><td id="replicate-value-${index}"></td><td>${deleted ? esc(ctx, member.reason) : `<textarea class="replicate-reason" id="replicate-reason-${index}" maxlength="500" rows="2" aria-label="${esc(ctx, t(ctx, "replicate_reason") + " " + member.name)}">${esc(ctx, member.reason)}</textarea>`}</td></tr>`;
    }).join("");
    const metrics = group.metrics.map((metric) => `<tr><th>${esc(ctx, metric.label)} (${esc(ctx, metric.units.join(" / "))})</th><td>${metric.n}</td><td>${number(metric.mean)}</td><td>${metric.sample_sd === null ? esc(ctx, t(ctx, "replicate_undefined")) : number(metric.sample_sd)}</td><td>${esc(ctx, t(ctx, `replicate_${metric.status}`))}</td></tr>`).join("");
    ctx.byId("replicate-body").innerHTML = `<fieldset id="replicate-fields" class="replicate-fields"><label for="replicate-name">${esc(ctx, t(ctx, "replicate_name"))}</label><input id="replicate-name" maxlength="128" value="${esc(ctx, group.name)}"><p class="panel-sub">${esc(ctx, t(ctx, "replicate_method"))}</p><ul class="project-notices">${[...(group.issues || []), ...(group.warnings || [])].map((issue) => `<li>${esc(ctx, issue)}</li>`).join("")}</ul><label for="replicate-metric">${esc(ctx, t(ctx, "replicate_metric"))}</label><select id="replicate-metric">${group.metrics.map((metric) => `<option value="${esc(ctx, metric.key)}">${esc(ctx, metric.label)} (${esc(ctx, metric.unit)})</option>`).join("")}</select><div class="project-table-scroll"><table class="project-data-table replicate-members"><thead><tr><th>${esc(ctx, t(ctx, "replicate_include"))}</th><th>${esc(ctx, t(ctx, "replicate_members"))}</th><th>${esc(ctx, t(ctx, "replicate_value"))}</th><th>${esc(ctx, t(ctx, "replicate_reason"))}</th></tr></thead><tbody>${rows}</tbody></table></div><div class="mini-actions"><button id="replicate-review" class="btn mini" type="button">${esc(ctx, t(ctx, "replicate_review"))}</button><button id="replicate-save" class="btn primary" type="button" ${group.can_save ? "" : "disabled"}>${esc(ctx, t(ctx, "replicate_save"))}</button></div><div class="project-table-scroll"><table class="project-data-table"><thead><tr><th>${esc(ctx, t(ctx, "replicate_metric"))}</th><th>${esc(ctx, t(ctx, "replicate_n"))}</th><th>${esc(ctx, t(ctx, "replicate_mean"))}</th><th>${esc(ctx, t(ctx, "replicate_sd"))}</th><th>${esc(ctx, t(ctx, "replicate_status"))}</th></tr></thead><tbody>${metrics}</tbody></table></div><div id="replicate-chart"></div><div class="mini-actions"><a id="replicate-csv" class="btn mini" ${group.group_id ? `href="${groupEndpoint(group.group_id)}/export?format=csv"` : "hidden"}>${esc(ctx, t(ctx, "replicate_csv"))}</a><a id="replicate-svg" class="btn mini" hidden>${esc(ctx, t(ctx, "replicate_svg"))}</a></div></fieldset>`;
    const select = ctx.byId("replicate-metric");
    if (group.analysis_conditions && group.analysis_conditions.requires_confirmation) {
      const conditions = group.analysis_conditions;
      const conditionRows = conditions.members.map((member) => `<tr><th>${esc(ctx, member.name)}</th><td>${Object.entries(member.values).map(([key, value]) => `${esc(ctx, window.ElectrochemProjectWorkbench.parameterLabel(ctx, key))}: ${esc(ctx, value === null || value === undefined ? "—" : JSON.stringify(value))}`).join("<br>")}</td></tr>`).join("");
      select.insertAdjacentHTML("beforebegin", `<details><summary>${esc(ctx, t(ctx, "replicate_conditions_title"))}</summary><div class="project-table-scroll"><table class="project-data-table"><tbody>${conditionRows}</tbody></table></div></details><label class="compact-check"><input id="replicate-conditions-confirm" type="checkbox" ${conditions.confirmed ? "checked" : ""}><span>${esc(ctx, t(ctx, "replicate_conditions_confirm"))}</span></label>`);
    }
    if (group.metrics.some((item) => item.key === oldMetric)) select.value = oldMetric;
    select.onchange = () => renderMetric(ctx);
    ctx.byId("replicate-fields").addEventListener("input", (event) => { if (event.target !== select) markChanged(ctx); });
    ctx.byId("replicate-review").onclick = () => review(ctx);
    ctx.byId("replicate-save").onclick = () => save(ctx);
    renderMetric(ctx);
  }

  async function review(ctx) {
    if (!active || active.busy) return;
    const payload = readDraft(ctx), projectId = active.projectId, token = ++revision;
    busy(ctx, true);
    message(ctx, t(ctx, "replicate_loading"));
    try {
      const result = await request(ctx, `${endpoint(projectId)}/replicate-preview`, payload);
      if (token !== revision || !dialog(ctx).open) return;
      render(ctx, result.group);
      message(ctx, "");
    } catch (error) { if (token === revision) message(ctx, error.message); }
    finally { if (token === revision) busy(ctx, false); }
  }

  async function save(ctx) {
    if (!active || active.busy || active.dirty) return;
    const group = active.group, payload = readDraft(ctx), token = ++revision;
    busy(ctx, true);
    try {
      const url = group.group_id ? `${groupEndpoint(group.group_id)}/update` : `${endpoint(active.projectId)}/replicate-groups`;
      const result = await request(ctx, url, payload);
      if (token !== revision || !dialog(ctx).open) return;
      render(ctx, result.group);
      message(ctx, t(ctx, "replicate_saved"));
    } catch (error) { if (token === revision) message(ctx, error.message); }
    finally { if (token === revision) busy(ctx, false); }
  }

  async function openSelected(ctx) {
    const projectId = ctx.getSelectedProjectId(), keys = ctx.getSelectedRecordKeys();
    const token = ++revision;
    active = null;
    shell(ctx);
    if (!projectId || !keys.length) { message(ctx, t(ctx, "replicate_select_first")); return; }
    message(ctx, t(ctx, "replicate_loading"));
    try {
      const result = await request(ctx, `${endpoint(projectId)}/replicate-preview`, { name: "", record_keys: keys, exclusions: [], independence_confirmed_keys: [] });
      if (token !== revision || !dialog(ctx).open) return;
      render(ctx, result.group);
      message(ctx, "");
    } catch (error) { if (token === revision) message(ctx, error.message); }
  }

  async function openGroups(ctx) {
    const projectId = ctx.getSelectedProjectId(), token = ++revision;
    active = null;
    shell(ctx);
    if (!projectId) { message(ctx, t(ctx, "replicate_select_first")); return; }
    message(ctx, t(ctx, "replicate_loading"));
    try {
      const result = await request(ctx, `${endpoint(projectId)}/replicate-groups`);
      if (token !== revision || !dialog(ctx).open) return;
      ctx.byId("replicate-body").innerHTML = result.groups.length ? result.groups.map((group, index) => `<button class="btn mini replicate-open" type="button" data-group-index="${index}">${esc(ctx, group.name)} · ${esc(ctx, group.updated_at || "")}</button>`).join("") : `<p>${esc(ctx, t(ctx, "replicate_empty"))}</p>`;
      message(ctx, "");
      ctx.byId("replicate-body").querySelectorAll(".replicate-open").forEach((button) => { button.onclick = async () => {
        const selectionToken = ++revision;
        message(ctx, t(ctx, "replicate_loading"));
        try {
          const selected = await request(ctx, groupEndpoint(result.groups[Number(button.dataset.groupIndex)].group_id));
          if (selectionToken !== revision || !dialog(ctx).open) return;
          render(ctx, selected.group);
          message(ctx, "");
        } catch (error) { if (selectionToken === revision) message(ctx, error.message); }
      }; });
    } catch (error) { if (token === revision) message(ctx, error.message); }
  }

  function init(contextProvider) {
    provider = contextProvider;
    const ctx = provider();
    const create = ctx.byId("project-replicates-create"), open = ctx.byId("project-replicates-open");
    if (create) create.addEventListener("click", () => openSelected(provider()));
    if (open) open.addEventListener("click", () => openGroups(provider()));
    if (dialog(ctx)) dialog(ctx).addEventListener("close", () => { revision += 1; active = null; });
  }

  window.ElectrochemProjectReplicates = { init, openSelected, openGroups, labels };
})();
