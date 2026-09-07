(function () {
  "use strict";

  // Context wrappers are recreated by app.js; the API object identifies the workspace.
  const activeRuns = new WeakMap();

  function resetState() {
    return {
      preflightState: "pending",
      runState: "pending",
    };
  }

  function formatPreflightSummary(options) {
    const opts = options || {};
    const preflightModel = opts.preflightModel;
    if (!preflightModel || typeof preflightModel.buildSummary !== "function") return "";
    const translate = typeof opts.t === "function" ? opts.t : (key) => String(key || "");
    const summary = preflightModel.buildSummary(
      opts.preflight || {},
      opts.selectedTypes || [],
      opts.moduleDescriptors && opts.moduleDescriptors.length ? opts.moduleDescriptors : undefined,
    );
    const parts = summary.counts.map((item) => `${item.label || item.dtype}: ${item.matched}`);
    const warnings = summary.warnings.length ? ` | ${summary.warnings.join("; ")}` : "";
    return `${translate("preflight_summary")}: ${parts.join(", ")} | ${translate("preflight_text_files")}: ${summary.textFiles} | ${translate("preflight_work_units")}: ${summary.workUnits}${warnings}`;
  }

  async function runPreflight(ctx, options = {}) {
    const silent = Boolean(options.silent);
    let payload;
    try {
      payload = ctx.collectProcessPayload();
    } catch (err) {
      ctx.setProcessPreflightState("issue");
      ctx.renderPreflightChecks(null, "issue", err.message);
      ctx.updateProcessStepState();
      if (!silent) ctx.setProcStatus(err.message);
      ctx.renderProcessError(err.message);
      return null;
    }

    const target = ctx.byId("proc-preflight");
    if (target && !silent) target.textContent = ctx.t("preflight_running");
    ctx.renderPreflightChecks(null, "running");
    ctx.setProcessPreflightState("running");
    ctx.updateProcessStepState();

    try {
      const resp = await ctx.processingApi.preflight(payload);
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || ctx.t("preflight_failed"));
      }
      const preflight = data.preflight || {};
      const text = ctx.formatPreflightSummary(preflight);
      if (target) target.textContent = text;
      if (!silent) ctx.setProcStatus(text);
      ctx.setProcessPreflightState("complete");
      ctx.renderPreflightChecks(preflight, "complete");
      ctx.updateProcessStepState();
      return preflight;
    } catch (err) {
      const msg = `${ctx.t("preflight_failed")}: ${err.message}`;
      if (target) target.textContent = msg;
      if (!silent) ctx.setProcStatus(msg);
      ctx.setProcessPreflightState("issue");
      ctx.renderPreflightChecks(null, "issue", err.message);
      ctx.updateProcessStepState();
      return null;
    }
  }

  function processSuccessStatus(ctx, result) {
    const safe = result && typeof result === "object" ? result : {};
    const processing = safe.processing && typeof safe.processing === "object" ? safe.processing : {};
    const files = (Array.isArray(processing.output_files) ? processing.output_files : []).slice(0, 5);
    const summary = safe.summary || "Done";
    return `${ctx.t("proc_success")}: ${summary}${files.length ? ` | output: ${files.join(", ")}` : ""}`;
  }

  async function runProcess(ctx) {
    const activeRun = activeRuns.get(ctx.processingApi);
    const activeJobId = activeRun ? activeRun.jobId : (
      typeof ctx.getActiveProcessJobId === "function" ? ctx.getActiveProcessJobId() : ""
    );
    if (activeJobId && typeof ctx.processingApi.cancelProcessJob === "function") {
      ctx.setProcStatus(ctx.t("process_job_cancelling"));
      try {
        await ctx.processingApi.cancelProcessJob(activeJobId);
      } catch (_err) {
        // Polling remains authoritative if the cancellation request races completion.
      }
      return null;
    }
    if (activeRun) return null;
    const run = { jobId: "" };
    activeRuns.set(ctx.processingApi, run);
    const ownsRun = () => activeRuns.get(ctx.processingApi) === run;
    const setSubmitting = (value) => {
      if (ownsRun() && typeof ctx.setProcessSubmitting === "function") ctx.setProcessSubmitting(value);
    };

    try {
      setSubmitting(true);
      const payload = ctx.collectProcessPayload();
      ctx.setProcStatus(ctx.t("proc_running"));
      ctx.setProcessRunState("running");
      ctx.updateProcessStepState();
      await ctx.runPreflight(true);
      let data;
      if (typeof ctx.processingApi.submitProcessJob === "function" && typeof ctx.processingApi.getProcessJob === "function") {
        const submitResp = await ctx.processingApi.submitProcessJob(payload);
        const submitted = await submitResp.json();
        if (!submitResp.ok || submitted.status !== "success" || !submitted.job_id) {
          throw new Error(submitted.message || ctx.t("proc_failed"));
        }
        const jobId = String(submitted.job_id);
        run.jobId = jobId;
        if (typeof ctx.setActiveProcessJob === "function") ctx.setActiveProcessJob(jobId);
        setSubmitting(false);
        let job = submitted.job || { job_id: jobId, status: "queued" };
        while (!["succeeded", "failed", "cancelled", "interrupted"].includes(String(job.status || ""))) {
          if (!ownsRun()) return null;
          if (typeof ctx.updateProcessJobProgress === "function") ctx.updateProcessJobProgress(job);
          await new Promise((resolve) => setTimeout(resolve, 500));
          const jobResp = await ctx.processingApi.getProcessJob(jobId);
          const jobPayload = await jobResp.json();
          if (!jobResp.ok || jobPayload.status !== "success" || !jobPayload.job) {
            throw new Error(jobPayload.message || ctx.t("proc_failed"));
          }
          job = jobPayload.job;
        }
        if (!ownsRun()) return null;
        if (typeof ctx.updateProcessJobProgress === "function") ctx.updateProcessJobProgress(job);
        setSubmitting(true);
        if (job.status === "cancelled") {
          ctx.setProcStatus(ctx.t("process_job_cancelled"));
          ctx.setProcessRunState("pending");
          ctx.updateProcessStepState();
          return null;
        }
        if (job.status !== "succeeded") throw new Error(job.error || ctx.t("proc_failed"));
        data = job.result || {};
      } else {
        const resp = await ctx.processingApi.runProcess(payload);
        data = await resp.json();
        if (!resp.ok || data.status !== "success") {
          throw new Error(data.message || ctx.t("proc_failed"));
        }
      }
      if (data.status !== "success") {
        throw new Error(data.message || ctx.t("proc_failed"));
      }
      const result = data.result || {};
      ctx.setProcStatus(processSuccessStatus(ctx, result));
      ctx.renderProcessResult(result);
      ctx.setProcessRunState("complete");
      ctx.updateProcessStepState();
      await ctx.loadStatsAndHistory();
      await ctx.loadProjects();
      return result;
    } catch (err) {
      if (!ownsRun()) return null;
      ctx.setProcStatus(`${ctx.t("proc_failed")}: ${err.message}`);
      ctx.renderProcessError(err.message);
      ctx.setProcessRunState("issue");
      ctx.updateProcessStepState();
      return null;
    } finally {
      if (ownsRun()) {
        const currentJobId = typeof ctx.getActiveProcessJobId === "function" ? ctx.getActiveProcessJobId() : run.jobId;
        if (currentJobId === run.jobId && typeof ctx.setActiveProcessJob === "function") ctx.setActiveProcessJob("");
        setSubmitting(false);
        activeRuns.delete(ctx.processingApi);
      }
    }
  }

  function diagnosticsResult(data, translate) {
    const safe = data && typeof data === "object" ? data : {};
    return {
      summary: translate("diagnostics_done"),
      data_types: [],
      processing: { output_files: safe.path ? [safe.path] : [] },
      quality_summary: { included_files: Array.isArray(safe.included_files) ? safe.included_files.length : 0 },
    };
  }

  async function exportDiagnostics(ctx) {
    ctx.setProcStatus(ctx.t("diagnostics_running"));
    try {
      const resp = await ctx.processingApi.exportDiagnostics();
      const data = await resp.json();
      if (!resp.ok || data.status !== "success") {
        throw new Error(data.message || ctx.t("diagnostics_failed"));
      }
      ctx.setProcStatus(`${ctx.t("diagnostics_done")}: ${data.path || data.file_name || "-"}`);
      if (data.path) {
        ctx.renderProcessResult(diagnosticsResult(data, ctx.t));
      }
      return data;
    } catch (err) {
      ctx.setProcStatus(`${ctx.t("diagnostics_failed")}: ${err.message}`);
      return null;
    }
  }

  window.ElectrochemProcessRuntime = {
    diagnosticsResult,
    exportDiagnostics,
    formatPreflightSummary,
    processSuccessStatus,
    resetState,
    runPreflight,
    runProcess,
  };
})();
