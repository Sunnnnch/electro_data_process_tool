(function () {
  "use strict";

  const STANDARD_QUALITY_KEYS = ["total_files", "passed", "failed", "warnings"];
  const QUALITY_LABEL_KEYS = {
    failed: "result_quality_failed",
    passed: "result_quality_passed",
    total_files: "result_quality_total",
    warnings: "result_quality_warnings",
  };

  function safeObject(value) {
    return value && typeof value === "object" ? value : {};
  }

  function fileNameOnly(pathText) {
    const text = String(pathText || "").trim();
    return text.split(/[\\/]/).pop() || text;
  }

  function dataTypesFromResult(result) {
    if (Array.isArray(result && result.data_types)) {
      return result.data_types.map((item) => String(item || "")).filter(Boolean);
    }
    if (result && result.data_type) return [String(result.data_type)];
    return [];
  }

  function outputFilesFromResult(result) {
    const files = (safeObject(result && result.processing).output_files) || [];
    if (!Array.isArray(files) || !files.length) return [];
    return files.map((item) => {
      const path = String(item || "").trim();
      return { fileName: fileNameOnly(path), path };
    });
  }

  function qualityItemsFromResult(result) {
    const quality = safeObject(result && result.quality_summary);
    const processing = safeObject(result && result.processing);
    const items = [];
    const consumed = new Set();

    if (processing.matched_files !== undefined) {
      items.push({ labelKey: "result_matched_files", value: processing.matched_files });
    }
    if (processing.generated_files !== undefined) {
      items.push({ labelKey: "result_generated_files", value: processing.generated_files });
    }
    if (processing.skipped_files !== undefined) {
      items.push({ labelKey: "result_skipped_count", value: processing.skipped_files });
    }
    if (processing.output_dir) {
      items.push({ labelKey: "result_output_dir", value: processing.output_dir });
    }

    STANDARD_QUALITY_KEYS.forEach((key) => {
      if (quality[key] === undefined) return;
      items.push({ labelKey: QUALITY_LABEL_KEYS[key], value: quality[key] });
      consumed.add(key);
    });

    const skippedCount = Array.isArray(result && result.skipped_errors)
      ? result.skipped_errors.length
      : (quality.skipped || 0);
    if (skippedCount > 0) {
      items.push({ labelKey: "result_skipped_count", value: skippedCount });
      consumed.add("skipped");
    }

    Object.keys(quality).forEach((key) => {
      if (consumed.has(key)) return;
      const value = quality[key];
      if (value === undefined || value === null) return;
      items.push({
        label: key,
        value: typeof value === "object" ? JSON.stringify(value) : String(value),
      });
    });
    return items;
  }

  function skippedErrorsFromResult(result) {
    const skipped = (result && result.skipped_errors) || [];
    if (!Array.isArray(skipped) || !skipped.length) return [];
    return skipped.map((item) => {
      const file = String(item && item.file ? item.file : "");
      return {
        error: String(item && item.error ? item.error : ""),
        fileName: fileNameOnly(file),
        type: String(item && item.type ? item.type : ""),
      };
    });
  }

  function buildResultView(result) {
    const safe = safeObject(result);
    return {
      dataTypes: dataTypesFromResult(safe),
      outputFiles: outputFilesFromResult(safe),
      qualityItems: qualityItemsFromResult(safe),
      skippedErrors: skippedErrorsFromResult(safe),
      summary: safe.summary || "",
    };
  }

  function historyRecordFiles(record) {
    if (Array.isArray(record && record.output_files) && record.output_files.length) {
      return record.output_files.map((item) => String(item));
    }
    if (record && record.summary_path) return [String(record.summary_path)];
    if (record && (record.file_path || record.file_name)) return [String(record.file_path || record.file_name)];
    return [];
  }

  function buildResultFromHistoryRecord(record, historyLabel) {
    const safe = safeObject(record);
    const type = String(safe.type || "").toUpperCase();
    const sample = safe.sample_name || safe.file_name || safe.file_path || "-";
    const results = safeObject(safe.results);
    const quality = {
      status: safe.status || "-",
      project: safe.project_name || "-",
      timestamp: safe.timestamp || "-",
    };
    let count = 0;
    Object.keys(results).forEach((key) => {
      if (count >= 8) return;
      const value = results[key];
      if (typeof value === "object") return;
      quality[key] = value;
      count += 1;
    });
    return {
      data_type: type || undefined,
      data_types: type ? [type] : [],
      processing: { output_files: historyRecordFiles(safe) },
      quality_summary: quality,
      summary: `${historyLabel || "History record"}: ${sample}`,
    };
  }

  window.ElectrochemProcessResultModel = {
    buildResultFromHistoryRecord,
    buildResultView,
    dataTypesFromResult,
    fileNameOnly,
    outputFilesFromResult,
    qualityItemsFromResult,
    skippedErrorsFromResult,
  };
})();
