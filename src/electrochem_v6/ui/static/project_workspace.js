(function () {
  "use strict";

  let projectCreatePending = false;
  let detailRevision = 0;

  function invalidateDetail() { detailRevision += 1; }

  function emptyTargetCurrents() {
    return {
      target_currents: [],
      potential_target_currents: [],
      overpotential_target_currents: [],
    };
  }

  function translate(ctx, key) {
    return typeof ctx.t === "function" ? ctx.t(key) : String(key || "");
  }

  function setStatus(ctx, text) {
    if (typeof ctx.setProjectStatus === "function") ctx.setProjectStatus(text || "");
  }

  function normalizeProjectItems(items) {
    return Array.isArray(items) ? items : [];
  }

  function getProjectItems(ctx) {
    return normalizeProjectItems(typeof ctx.getProjectItems === "function" ? ctx.getProjectItems() : []);
  }

  function setProjectItems(ctx, items) {
    if (typeof ctx.setProjectItems === "function") ctx.setProjectItems(normalizeProjectItems(items));
  }

  function getSelectedProjectId(ctx) {
    return String(typeof ctx.getSelectedProjectId === "function" ? ctx.getSelectedProjectId() || "" : "");
  }

  function setSelectedProjectId(ctx, projectId) {
    if (typeof ctx.setSelectedProjectId === "function") ctx.setSelectedProjectId(String(projectId || ""));
  }

  function setProjectDetailState(ctx, state) {
    if (typeof ctx.setProjectDetailState === "function") ctx.setProjectDetailState(state);
  }

  function resetProjectCompare(ctx) {
    if (typeof ctx.resetProjectCompareState === "function") {
      ctx.resetProjectCompareState();
      return;
    }
    if (typeof ctx.setProjectCompareSelectedSamples === "function") ctx.setProjectCompareSelectedSamples([]);
    if (typeof ctx.setProjectComparePlotData === "function") ctx.setProjectComparePlotData(null);
    if (typeof ctx.setProjectComparePlotLoading === "function") ctx.setProjectComparePlotLoading(false);
    if (typeof ctx.setProjectCompareTargetCurrents === "function") ctx.setProjectCompareTargetCurrents(emptyTargetCurrents());
  }

  function setSelectedProjectHistoryKey(ctx, value) {
    if (typeof ctx.setSelectedProjectHistoryKey === "function") ctx.setSelectedProjectHistoryKey(String(value || ""));
  }

  function renderProjectList(ctx, items) {
    if (typeof ctx.renderProjectList === "function") ctx.renderProjectList(normalizeProjectItems(items));
  }

  function renderSelectedProjectDetail(ctx) {
    if (typeof ctx.renderSelectedProjectDetail === "function") ctx.renderSelectedProjectDetail();
  }

  async function loadSelectedProjectDetail(ctx) {
    const revision = ++detailRevision;
    const projectId = getSelectedProjectId(ctx);
    if (!projectId) return null;
    const isCurrent = () => projectId === getSelectedProjectId(ctx) && revision === detailRevision;
    if (typeof ctx.setProjectComparePlotData === "function") ctx.setProjectComparePlotData(null);
    if (typeof ctx.setProjectComparePlotLoading === "function") ctx.setProjectComparePlotLoading(false);
    setStatus(ctx, translate(ctx, "project_status_detail_loading"));
    try {
      const [statsResp, historyResp, lsvResp] = await Promise.all([
        ctx.projectApi.stats({ projectId, includeArchived: Boolean(ctx.getProjectIncludeArchived && ctx.getProjectIncludeArchived()) }),
        ctx.projectApi.history({ projectId, limit: 30, includeArchived: Boolean(ctx.getProjectIncludeArchived && ctx.getProjectIncludeArchived()), ...(ctx.getHistoryFilters ? ctx.getHistoryFilters() : {}) }),
        ctx.projectApi.lsvSummary(projectId, { page: 1, pageSize: 15, sort: "eta" }),
      ]);
      const [statsData, historyData, lsvData] = await Promise.all([
        statsResp.json().catch(() => ({})),
        historyResp.json().catch(() => ({})),
        lsvResp.json().catch(() => ({})),
      ]);
      if (projectId !== getSelectedProjectId(ctx) || revision !== detailRevision) return null;
      const detailState = {
        stats: statsResp.ok && statsData.status === "success" ? statsData.data || {} : {},
        history: historyResp.ok && historyData.status === "success" ? historyData.records || [] : [],
        historyNextCursor: historyResp.ok && historyData.status === "success" ? historyData.next_cursor || "" : "",
        historyHasMore: Boolean(historyResp.ok && historyData.status === "success" && historyData.has_more),
        historyTotal: historyResp.ok && historyData.status === "success" ? Number(historyData.total || 0) : 0,
        lsv: lsvResp.ok && lsvData.status === "success" ? lsvData.lsv_summary || {} : null,
      };
      setProjectDetailState(ctx, detailState);
      if (typeof ctx.loadProjectCompareTargetCurrents === "function") {
        await ctx.loadProjectCompareTargetCurrents(projectId, isCurrent);
      }
      if (projectId !== getSelectedProjectId(ctx) || revision !== detailRevision) return null;
      renderSelectedProjectDetail(ctx);
      if (typeof ctx.loadLatestProjectComparePlot === "function") {
        await ctx.loadLatestProjectComparePlot(true, isCurrent);
      }
      if (projectId !== getSelectedProjectId(ctx) || revision !== detailRevision) return null;
      setStatus(ctx, historyResp.ok && historyData.status === "success" ? "" : historyData.message || translate(ctx, "project_status_detail_failed"));
      return detailState;
    } catch (err) {
      if (projectId !== getSelectedProjectId(ctx) || revision !== detailRevision) return null;
      if (typeof ctx.setProjectCompareTargetCurrents === "function") {
        ctx.setProjectCompareTargetCurrents(emptyTargetCurrents());
      }
      const emptyDetail = {
        stats: {}, history: [], historyNextCursor: "", historyHasMore: false, historyTotal: 0, lsv: null,
      };
      setProjectDetailState(ctx, emptyDetail);
      renderSelectedProjectDetail(ctx);
      setStatus(ctx, `${translate(ctx, "project_status_detail_failed")}: ${err.message}`);
      return null;
    }
  }

  async function selectProject(ctx, projectId) {
    const targetId = String(projectId || "").trim();
    if (targetId !== getSelectedProjectId(ctx) && ctx.resetHistoryFilters) ctx.resetHistoryFilters();
    setSelectedProjectId(ctx, targetId);
    setProjectDetailState(ctx, null);
    setSelectedProjectHistoryKey(ctx, "");
    resetProjectCompare(ctx);
    renderProjectList(ctx, getProjectItems(ctx));
    renderSelectedProjectDetail(ctx);
    if (!targetId) return null;
    return loadSelectedProjectDetail(ctx);
  }

  async function loadProjects(ctx, preferredProjectId = "") {
    setStatus(ctx, translate(ctx, "project_status_loading"));
    try {
      const listStatus = typeof ctx.getProjectListStatus === "function" ? ctx.getProjectListStatus() : "active";
      const resp = await ctx.projectApi.listProjects({ status: listStatus || "active" });
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || translate(ctx, "project_status_load_failed"));
      }
      const items = normalizeProjectItems(data.projects);
      setProjectItems(ctx, items);
      if (typeof ctx.syncProcessProjectOptions === "function") ctx.syncProcessProjectOptions();
      renderProjectList(ctx, items);
      if (!items.length) {
        setSelectedProjectId(ctx, "");
        setProjectDetailState(ctx, null);
        renderSelectedProjectDetail(ctx);
        setStatus(ctx, "");
        return [];
      }
      const preferred = String(preferredProjectId || getSelectedProjectId(ctx) || "").trim();
      const picked = preferred && items.some((item) => item.id === preferred) ? preferred : String(items[0].id || "");
      await selectProject(ctx, picked);
      return items;
    } catch (err) {
      setProjectItems(ctx, []);
      setSelectedProjectId(ctx, "");
      setProjectDetailState(ctx, null);
      if (typeof ctx.syncProcessProjectOptions === "function") ctx.syncProcessProjectOptions();
      renderProjectList(ctx, []);
      renderSelectedProjectDetail(ctx);
      setStatus(ctx, `${translate(ctx, "project_status_load_failed")}: ${err.message}`);
      return [];
    }
  }

  function setProjectCreateError(ctx, message, fieldId = "") {
    const error = ctx.byId("project-create-error");
    if (error) {
      error.textContent = message;
      error.hidden = !message;
    }
    for (const id of ["project-create-name", "project-create-color"]) {
      const field = ctx.byId(id);
      if (field && field.removeAttribute) {
        field.removeAttribute("aria-invalid");
        field.removeAttribute("aria-describedby");
        if (id === fieldId) {
          field.setAttribute("aria-invalid", "true");
          field.setAttribute("aria-describedby", "project-create-error");
          if (id === "project-create-color") ctx.byId("project-create-more").open = true;
          field.focus();
        }
      }
    }
  }

  function openProjectCreateDialog(ctx) {
    const dialog = ctx.byId("project-create-dialog");
    if (!dialog || dialog.open || projectCreatePending) return;
    ctx.byId("project-create-form").reset();
    ctx.byId("project-create-more").open = false;
    setProjectCreateError(ctx, "");
    dialog.showModal();
    ctx.byId("project-create-name").focus();
  }

  function closeProjectCreateDialog(ctx) {
    if (projectCreatePending) return;
    const dialog = ctx.byId("project-create-dialog");
    if (dialog && dialog.open) dialog.close();
  }

  function setProjectCreatePending(ctx, pending) {
    projectCreatePending = pending;
    for (const id of ["project-create-fields", "project-create-submit", "project-create-close", "project-create-cancel", "project-create-btn"]) {
      const control = ctx.byId(id);
      if (control) control.disabled = pending;
    }
    const submit = ctx.byId("project-create-submit");
    if (submit) submit.textContent = translate(ctx, pending ? "project_status_create_running" : "project_create_submit");
  }

  async function createProject(ctx) {
    if (projectCreatePending) return null;
    const name = ctx.textValue("project-create-name");
    const description = ctx.textValue("project-create-desc");
    const color = ctx.textValue("project-create-color");
    const tags = [...new Set(ctx.textValue("project-create-tags").split(/[,，]/).map((tag) => tag.trim()).filter(Boolean))];
    setProjectCreateError(ctx, "");
    if (!name || (color && !/^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(color))) {
      const message = translate(ctx, !name ? "project_name_required" : "project_color_invalid");
      setProjectCreateError(ctx, message, !name ? "project-create-name" : "project-create-color");
      setStatus(ctx, message);
      return null;
    }
    setProjectCreatePending(ctx, true);
    setStatus(ctx, translate(ctx, "project_status_create_running"));
    try {
      const resp = await ctx.projectApi.createProject({ name, description, tags, color: color || undefined, default_template_name: ctx.textValue("project-create-template") });
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || translate(ctx, "project_status_create_failed"));
      }
      const input = ctx.byId("project-create-name");
      if (input) input.value = "";
      const dialog = ctx.byId("project-create-dialog");
      if (dialog && dialog.open) dialog.close();
      if (typeof ctx.setProjectListStatus === "function") ctx.setProjectListStatus("active");
      const search = ctx.byId("project-list-search");
      if (search) search.value = "";
      const projectId = String(data.project_id || (data.project && data.project.id) || "");
      await loadProjects(ctx, projectId);
      setStatus(ctx, translate(ctx, "project_status_create_success"));
      return data;
    } catch (err) {
      const message = `${translate(ctx, "project_status_create_failed")}: ${err.message}`;
      setProjectCreateError(ctx, message);
      setStatus(ctx, message);
      return null;
    } finally {
      setProjectCreatePending(ctx, false);
    }
  }

  async function deleteCurrentProject(ctx) {
    const projectId = getSelectedProjectId(ctx);
    if (!projectId) return null;
    if (typeof ctx.confirm === "function" && !ctx.confirm(translate(ctx, "project_confirm_delete"))) return null;
    setStatus(ctx, translate(ctx, "project_status_delete_running"));
    try {
      const resp = await ctx.projectApi.deleteProject(projectId);
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || translate(ctx, "project_status_delete_failed"));
      }
      setSelectedProjectId(ctx, "");
      setProjectDetailState(ctx, null);
      await loadProjects(ctx, "");
      setStatus(ctx, translate(ctx, "project_status_delete_success"));
      return data;
    } catch (err) {
      setStatus(ctx, `${translate(ctx, "project_status_delete_failed")}: ${err.message}`);
      return null;
    }
  }

  async function restoreCurrentProject(ctx) {
    const projectId = getSelectedProjectId(ctx);
    if (!projectId) return null;
    if (typeof ctx.confirm === "function" && !ctx.confirm(translate(ctx, "project_confirm_restore"))) return null;
    setStatus(ctx, translate(ctx, "project_status_restore_running"));
    try {
      const resp = await ctx.projectApi.restoreProject(projectId);
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || translate(ctx, "project_status_restore_failed"));
      }
      setSelectedProjectId(ctx, "");
      setProjectDetailState(ctx, null);
      if (typeof ctx.setProjectListStatus === "function") ctx.setProjectListStatus("active");
      await loadProjects(ctx, projectId);
      setStatus(ctx, translate(ctx, "project_status_restore_success"));
      return data;
    } catch (err) {
      setStatus(ctx, `${translate(ctx, "project_status_restore_failed")}: ${err.message}`);
      return null;
    }
  }

  async function permanentlyDeleteCurrentProject(ctx) {
    const projectId = getSelectedProjectId(ctx);
    if (!projectId) return null;
    if (typeof ctx.confirm === "function" && !ctx.confirm(translate(ctx, "project_confirm_delete_permanent"))) return null;
    setStatus(ctx, translate(ctx, "project_status_permanent_delete_running"));
    try {
      const resp = await ctx.projectApi.permanentlyDeleteProject(projectId, { deleteArtifacts: true });
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || translate(ctx, "project_status_permanent_delete_failed"));
      }
      setSelectedProjectId(ctx, "");
      setProjectDetailState(ctx, null);
      await loadProjects(ctx, "");
      const skipped = data.artifact_cleanup && Array.isArray(data.artifact_cleanup.skipped)
        ? data.artifact_cleanup.skipped
        : [];
      setStatus(
        ctx,
        skipped.length
          ? translate(ctx, "project_status_permanent_delete_partial").replace("{count}", String(skipped.length))
          : translate(ctx, "project_status_permanent_delete_success")
      );
      return data;
    } catch (err) {
      setStatus(ctx, `${translate(ctx, "project_status_permanent_delete_failed")}: ${err.message}`);
      return null;
    }
  }

  function applyCurrentProjectToForms(ctx) {
    const project = getProjectItems(ctx).find((item) => item.id === getSelectedProjectId(ctx));
    if (!project || !project.name) return null;
    const name = String(project.name);
    const procProject = ctx.byId("proc-project");
    if (procProject) procProject.value = name;
    if (typeof ctx.switchTab === "function") ctx.switchTab("pro");
    setStatus(ctx, translate(ctx, "project_status_applied"));
    return project;
  }

  function readProjectEditPayload(ctx) {
    const name = ctx.textValue("project-edit-name");
    const description = ctx.textValue("project-edit-desc");
    const color = ctx.textValue("project-edit-color");
    const tags = ctx.textValue("project-edit-tags")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (!name) return { error: translate(ctx, "project_name_required") };
    if (color && !/^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(color)) {
      return { error: translate(ctx, "project_color_invalid") };
    }
    return { payload: { name, description, tags, color: color || undefined, ...(ctx.byId("project-edit-template") ? { default_template_name: ctx.textValue("project-edit-template") } : {}) } };
  }

  async function saveCurrentProject(ctx) {
    const projectId = getSelectedProjectId(ctx);
    if (!projectId) return null;
    const built = readProjectEditPayload(ctx);
    if (built.error) {
      setStatus(ctx, built.error);
      return null;
    }
    setStatus(ctx, translate(ctx, "project_status_save_running"));
    try {
      const resp = await ctx.projectApi.updateProject(projectId, built.payload);
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || translate(ctx, "project_status_save_failed"));
      }
      await loadProjects(ctx, projectId);
      if (typeof ctx.onProjectSaved === "function") ctx.onProjectSaved();
      setStatus(ctx, translate(ctx, "project_status_save_success"));
      return data;
    } catch (err) {
      setStatus(ctx, `${translate(ctx, "project_status_save_failed")}: ${err.message}`);
      return null;
    }
  }

  async function exportCurrentProjectReport(ctx) {
    const projectId = getSelectedProjectId(ctx);
    if (!projectId) return null;
    setStatus(ctx, translate(ctx, "project_status_detail_loading"));
    try {
      const resp = await ctx.projectApi.exportReport(projectId, { includeArchived: Boolean(ctx.getProjectIncludeArchived && ctx.getProjectIncludeArchived()) });
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || translate(ctx, "project_export_report_failed"));
      }
      setStatus(ctx, `${translate(ctx, "project_export_report_success")}: ${data.path || data.file_name || ""}`);
      return data;
    } catch (err) {
      setStatus(ctx, `${translate(ctx, "project_export_report_failed")}: ${err.message}`);
      return null;
    }
  }

  window.ElectrochemProjectWorkspace = {
    applyCurrentProjectToForms,
    closeProjectCreateDialog,
    createProject,
    deleteCurrentProject,
    emptyTargetCurrents,
    exportCurrentProjectReport,
    loadProjects,
    invalidateDetail,
    loadSelectedProjectDetail,
    openProjectCreateDialog,
    permanentlyDeleteCurrentProject,
    readProjectEditPayload,
    saveCurrentProject,
    selectProject,
    restoreCurrentProject,
  };
})();
