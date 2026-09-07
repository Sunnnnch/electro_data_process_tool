from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from electrochem_v6.core.processing_registry import processing_parameter_schema

ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "src" / "electrochem_v6" / "ui" / "static"


def _node_json(module_name: str, script: str, *, dependencies: tuple[str, ...] = ()) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node executable is required for static UI model tests")
    module_path = (STATIC_ROOT / module_name).as_posix()
    dependency_requires = "\n".join(
        f"require({(STATIC_ROOT / dependency).as_posix()!r});"
        for dependency in dependencies
    )
    code = textwrap.dedent(
        f"""
        global.window = {{}};
        {dependency_requires}
        require({module_path!r});
        const result = (async () => {{
        {textwrap.indent(script, "  ")}
        }})();
        Promise.resolve(result)
          .then((resolved) => console.log(JSON.stringify(resolved)))
          .catch((err) => {{
            console.error(err && err.stack ? err.stack : String(err));
            process.exit(1);
          }});
        """
    )
    proc = subprocess.run(
        [node, "-e", code],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.fail(f"node model test failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout)


def test_preflight_model_maps_check_states_and_legacy_scan() -> None:
    payload = _node_json(
        "preflight_model.js",
        """
        const model = window.ElectrochemPreflightModel;
        const withChecks = model.buildCheckItems({
          checks: {
            file_recognition: { ok: true, status: "pass" },
            param_completeness: { ok: false, status: "check" },
            output_dir: { ok: true, status: "normal" },
            runnable: { ok: false, status: "no" },
          },
        }, "complete");
        const legacyClean = model.buildCheckItems({ selected_matched: 2, warnings: [] }, "complete");
        const legacyWarning = model.buildCheckItems({ selected_matched: 2, warnings: ["narrow match"] }, "complete");
        const issue = model.buildCheckItems(null, "issue", "missing folder");
        return {
          issue: issue.items,
          legacyClean: legacyClean.items,
          legacyWarning: legacyWarning.items,
          scanKept: withChecks.scan.checks.runnable.status,
          withChecks: withChecks.items,
        };
        """,
    )

    assert payload["withChecks"]["files"] == {"state": "ok", "labelKey": "preflight_status_pass"}
    assert payload["withChecks"]["params"] == {"state": "issue", "labelKey": "preflight_status_check"}
    assert payload["withChecks"]["output"] == {"state": "ok", "labelKey": "preflight_status_normal"}
    assert payload["withChecks"]["runnable"] == {"state": "issue", "labelKey": "preflight_status_no"}
    assert payload["scanKept"] == "no"

    assert payload["legacyClean"]["files"] == {"state": "ok", "labelKey": "preflight_status_pass"}
    assert payload["legacyClean"]["runnable"] == {"state": "ok", "labelKey": "preflight_status_yes"}
    assert payload["legacyWarning"]["files"] == {"state": "issue", "labelKey": "preflight_status_check"}
    assert payload["legacyWarning"]["runnable"] == {"state": "ok", "labelKey": "preflight_status_yes"}
    assert payload["issue"]["params"] == {"state": "issue", "labelKey": "preflight_status_check"}


def test_assistant_context_builds_reviewable_professional_mode_summary() -> None:
    payload = _node_json(
        "assistant_context.js",
        r"""
        const model = window.ElectrochemAssistantContext;
        const context = model.build({
          projectName: "Catalyst screening",
          dataTypes: ["LSV", "EIS"],
          templateName: "acid-standard",
          folderName: "D:/private/experiment-07",
          sourceItems: [
            { path: "D:/private/experiment-07/LSV_sample_A.txt", data_type: "LSV", enabled: true },
            { path: "D:/private/experiment-07/EIS_sample_A.csv", data_type: "EIS", enabled: true },
          ],
          processPayload: {
            params: {
              potential_offset: 0.197,
              ir_eis_file: "D:/private/experiment-07/EIS_sample_A.csv",
            },
          },
          preflightState: "complete",
          preflight: {
            counts: [{ dtype: "LSV", matched: 1 }, { dtype: "EIS", matched: 1 }],
            textFiles: 2,
            workUnits: 2,
            warnings: [],
          },
          resultState: "complete",
          result: {
            summary: "Processing completed",
            dataTypes: ["LSV", "EIS"],
            qualityItems: [{ label: "R squared", value: 0.998 }],
            outputFiles: [{ path: "D:/private/outputs/summary.json", fileName: "summary.json" }],
          },
        });
        const labels = {
          assistant_context_project: "Project",
          assistant_context_files: "{count} files",
          assistant_context_no_files: "No files",
          assistant_context_preflight_complete: "Preflight complete",
          assistant_context_has_result: "Has result",
        };
        const summary = model.summary(context, (key) => labels[key] || key);
        return { context, summary };
        """,
    )

    context = payload["context"]
    assert context["context_type"] == "professional_mode_summary"
    assert context["data_source"]["raw_file_content_included"] is False
    assert context["data_source"]["folder"] == "experiment-07"
    assert [item["file"] for item in context["data_source"]["files"]] == [
        "LSV_sample_A.txt",
        "EIS_sample_A.csv",
    ]
    assert context["parameters"]["ir_eis_file"] == "EIS_sample_A.csv"
    assert context["result"]["output_files"] == ["summary.json"]
    assert "D:/private" not in json.dumps(context)
    assert "Project: Catalyst screening" in payload["summary"]
    assert "LSV / EIS" in payload["summary"]
    assert "2 files" in payload["summary"]
    assert "Preflight complete" in payload["summary"]
    assert payload["summary"].endswith("Has result")


def test_ui_core_exposes_shared_dom_and_format_helpers() -> None:
    payload = _node_json(
        "ui_core.js",
        """
        const store = {
          checked: { checked: true, value: "" },
          empty: { checked: false, value: "   " },
          number: { checked: false, value: " 42.5 " },
          text: { checked: false, value: " demo " },
        };
        global.document = {
          getElementById: (id) => store[id] || null,
        };
        const core = window.ElectrochemUiCore;
        return {
          boolValue: core.boolValue("checked"),
          emptyNumber: core.numberValue("empty") ?? null,
          escaped: core.escapeHtml("<a&b>"),
          fileName: core.fileNameOnly("D:/data/sample.txt"),
          missing: core.byId("missing"),
          numberValue: core.numberValue("number"),
          textValue: core.textValue("text"),
        };
        """,
    )

    assert payload == {
        "boolValue": True,
        "emptyNumber": None,
        "escaped": "&lt;a&amp;b&gt;",
        "fileName": "sample.txt",
        "missing": None,
        "numberValue": 42.5,
        "textValue": "demo",
    }


def test_process_source_selection_merges_deduplicates_and_builds_payload() -> None:
    payload = _node_json(
        "process_source_selection.js",
        """
        const model = window.ElectrochemProcessSourceSelection;
        let items = model.merge([], [
          { path: "D:/data/LSV_A.txt", suggested_type: "LSV", status: "recognized" },
          { path: "D:/data/CV_A.txt", suggested_type: "CV", status: "recognized" },
        ], { origin: "folder:D:/data" });
        items = model.merge(items, [
          { path: "d:/data/lsv_a.txt", suggested_type: "EIS" },
          { path: "D:/other/EIS_A.csv", suggested_type: "EIS" },
        ], { origin: "manual" });
        items[1].enabled = false;
        return {
          count: items.length,
          folder: model.preferredFolder(items, ""),
          payload: model.toInputFiles(items, ["LSV", "CV", "EIS"]),
          types: items.map((item) => item.data_type),
        };
        """,
    )

    assert payload["count"] == 3
    assert payload["folder"] == "D:/data"
    assert payload["types"] == ["LSV", "CV", "EIS"]
    assert payload["payload"] == [
        {"path": "D:/data/LSV_A.txt", "data_type": "LSV", "enabled": True},
        {"path": "D:/other/EIS_A.csv", "data_type": "EIS", "enabled": True},
    ]


def test_theme_defaults_to_lab_and_preserves_saved_choice() -> None:
    payload = _node_json(
        "theme.js",
        """
        const values = new Map();
        const select = { value: "" };
        global.document = {
          body: { dataset: {} },
          getElementById: (id) => id === "theme-select" ? select : null,
        };
        window.localStorage = {
          getItem: (key) => values.has(key) ? values.get(key) : null,
          setItem: (key, value) => values.set(key, value),
        };

        const theme = window.ElectrochemTheme;
        const initial = theme.init();
        const initialBodyTheme = document.body.dataset.theme;
        const initialSelectTheme = select.value;
        theme.save("dark");
        const saved = theme.init();
        values.set(theme.storageKey, "invalid-theme");
        const invalidFallback = theme.init();

        return {
          defaultTheme: theme.defaultTheme,
          initial,
          initialBodyTheme,
          initialSelectTheme,
          invalidFallback,
          saved,
        };
        """,
    )

    assert payload == {
        "defaultTheme": "lab",
        "initial": "lab",
        "initialBodyTheme": "lab",
        "initialSelectTheme": "lab",
        "invalidFallback": "lab",
        "saved": "dark",
    }


def test_process_templates_collects_applies_and_renders_options() -> None:
    payload = _node_json(
        "process_templates.js",
        """
        const templates = window.ElectrochemProcessTemplates;
        window.ElectrochemProcessingSchema.getVersion = () => "1.7";
        const elements = {
          "plot-font-size": { type: "text", value: "12", checked: false },
          "pro-area": { type: "text", value: "1.2", checked: false },
          "pro-lsv-prefix": { type: "text", value: "LSV", checked: false },
          "pro-plot-grid": { type: "checkbox", value: "", checked: true },
        };
        const processChecks = [
          { checked: false, value: "LSV" },
          { checked: true, value: "CV" },
        ];
        const select = { value: "old", options: [], appendChild: function (opt) { this.options.push(opt); } };
        Object.defineProperty(select, "innerHTML", {
          get: function () { return ""; },
          set: function () { this.options = []; },
        });
        elements["tmpl-select"] = select;
        global.document = {
          createElement: () => ({ value: "", textContent: "" }),
          querySelector: (selector) => selector === '.proc-type-check[value="LSV"]' ? processChecks[0] : null,
          querySelectorAll: (selector) => selector === ".proc-type-check" ? processChecks : [],
        };
        let applied = 0;
        const items = [
          { builtin: true, name: "LSV_default", state: {} },
          { builtin: false, name: "custom", state: {} },
        ];
        const ctx = {
          byId: (id) => elements[id] || null,
          getSelectedProcessTypes: () => processChecks.filter((item) => item.checked).map((item) => item.value),
          getTemplateItems: () => items,
          onTemplateApplied: () => { applied += 1; },
          t: (key) => ({ template_builtin_tag: "built-in", template_none: "No templates" }[key] || key),
        };

        const before = templates.getCurrentState(ctx);
        const appliedOk = templates.applyState(ctx, {
          schema_version: "1.6",
          checks: { "pro-plot-grid": false },
          selected_types: [],
          values: {
            "plot-font-size": "16",
            "pro-lsv-prefix": "LSV_NEW",
            "retired-control": "ignored",
          },
        });
        const warnings = templates.getLastApplyWarnings();
        templates.renderOptions(ctx);
        const optionLabels = select.options.map((opt) => opt.textContent);
        const emptyItemsCtx = { ...ctx, getTemplateItems: () => [] };
        templates.renderOptions(emptyItemsCtx);
        return {
          applied,
          appliedOk,
          before,
          emptyLabel: select.options[0].textContent,
          gridAfter: elements["pro-plot-grid"].checked,
          options: optionLabels,
          selectedAfter: processChecks.map((item) => [item.value, item.checked]),
          valuesAfter: [elements["plot-font-size"].value, elements["pro-lsv-prefix"].value],
          warnings,
        };
        """,
        dependencies=("process_schema.js",),
    )

    assert payload["before"]["selected_types"] == ["CV"]
    assert payload["before"]["values"]["plot-font-size"] == "12"
    assert payload["before"]["checks"]["pro-plot-grid"] is True
    assert payload["appliedOk"] is True
    assert payload["applied"] == 1
    assert payload["selectedAfter"] == [["LSV", True], ["CV", False]]
    assert payload["valuesAfter"] == ["16", "LSV_NEW"]
    assert payload["gridAfter"] is False
    assert payload["warnings"] == ["schema_version", "value:retired-control"]
    assert payload["options"] == ["LSV_default [built-in]", "custom"]
    assert payload["emptyLabel"] == "No templates"


def test_process_templates_calls_template_api_and_protects_builtin_delete() -> None:
    payload = _node_json(
        "process_templates.js",
        """
        const templates = window.ElectrochemProcessTemplates;
        window.ElectrochemProcessingSchema.getVersion = () => "1.7";
        let templateItems = [];
        const statuses = [];
        const confirmations = [];
        const saveCalls = [];
        const deleteCalls = [];
        const processChecks = [{ checked: true, value: "LSV" }];
        const elements = {
          "plot-font-size": { type: "text", value: "12", checked: false },
          "tmpl-name": { type: "text", value: "custom", checked: false },
        };
        const select = { value: "", options: [], appendChild: function (opt) { this.options.push(opt); } };
        Object.defineProperty(select, "innerHTML", {
          get: function () { return ""; },
          set: function () { this.options = []; },
        });
        elements["tmpl-select"] = select;
        global.document = {
          createElement: () => ({ value: "", textContent: "" }),
          querySelector: () => processChecks[0],
          querySelectorAll: () => processChecks,
        };
        const t = (key) => ({
          template_builtin_immutable: "builtin locked",
          template_builtin_tag: "built-in",
          template_confirm_delete: "delete?",
          template_confirm_overwrite: "overwrite?",
          template_deleted: "deleted",
          template_delete_failed: "delete failed",
          template_load_failed: "load failed",
          template_loaded: "loaded",
          template_loaded_with_warnings: "loaded with warnings",
          template_name_required: "name required",
          template_none: "No templates",
          template_restart_hint: "restart",
          template_saved: "saved",
          template_save_failed: "save failed",
        }[key] || key);
        const listPayload = () => ({
          status: "success",
          templates: [
            {
              builtin: true,
              name: "builtin",
              state: { schema_version: "1.7", selected_types: ["LSV"] },
            },
            {
              builtin: false,
              name: "custom",
              state: { schema_version: "1.7", values: { "plot-font-size": "18" } },
            },
          ],
        });
        const ctx = {
          byId: (id) => elements[id] || null,
          confirm: (message) => { confirmations.push(message); return true; },
          getSelectedProcessTypes: () => processChecks.filter((item) => item.checked).map((item) => item.value),
          getTemplateItems: () => templateItems,
          onTemplateApplied: () => {},
          processingApi: {
            deleteTemplate: async (name) => {
              deleteCalls.push(name);
              return { ok: true, json: async () => ({ status: "success" }) };
            },
            listTemplates: async () => ({ ok: true, json: async () => listPayload() }),
            saveTemplate: async (payload) => {
              saveCalls.push({ name: payload.name, overwrite: payload.overwrite, font: payload.state.values["plot-font-size"] });
              if (!payload.overwrite) {
                return { ok: false, json: async () => ({ code: "already_exists", message: "exists", status: "error" }) };
              }
              return { ok: true, json: async () => ({ status: "success" }) };
            },
          },
          setTemplateItems: (items) => { templateItems = items; },
          setTemplateStatus: (message) => statuses.push(message),
          t,
          textValue: (id) => (elements[id] && elements[id].value || "").trim(),
        };

        const loaded = await templates.loadTemplates(ctx);
        await templates.saveTemplate(ctx, false);
        select.value = "custom";
        const selected = templates.loadSelectedTemplate(ctx);
        select.value = "builtin";
        const builtinDelete = await templates.deleteSelectedTemplate(ctx);
        select.value = "custom";
        const deleted = await templates.deleteSelectedTemplate(ctx);
        return {
          builtinDelete,
          confirmations,
          deletedStatus: deleted.status,
          deleteCalls,
          fontAfterLoad: elements["plot-font-size"].value,
          loadedNames: loaded.map((item) => item.name),
          saveCalls,
          selectedName: selected.name,
          selectValue: select.value,
          statuses,
          templateCount: templateItems.length,
        };
        """,
        dependencies=("process_schema.js",),
    )

    assert payload["loadedNames"] == ["builtin", "custom"]
    assert payload["saveCalls"] == [
        {"font": "12", "name": "custom", "overwrite": False},
        {"font": "12", "name": "custom", "overwrite": True},
    ]
    assert payload["confirmations"] == ["overwrite?", "delete?"]
    assert payload["selectedName"] == "custom"
    assert payload["fontAfterLoad"] == "18"
    assert payload["builtinDelete"] is None
    assert payload["deleteCalls"] == ["custom"]
    assert payload["deletedStatus"] == "success"
    assert payload["templateCount"] == 2
    assert "saved" in payload["statuses"]
    assert "loaded" in payload["statuses"]
    assert "builtin locked" in payload["statuses"]
    assert "deleted" in payload["statuses"]


def test_process_payload_collects_multi_module_payload_and_validation_errors() -> None:
    payload = _node_json(
        "process_payload.js",
        """
        const builder = window.ElectrochemProcessPayload;
        const processSchemaClient = window.ElectrochemProcessingSchema;
        const processParameterSchema = {
          modules: [
            { key: "LSV", aliases: [] },
            { key: "CV", aliases: [] },
            { key: "COUPLED", aliases: ["FE"] },
          ],
          parameters: [
            {
              key: "area", label: "Electrode area", value_type: "number",
              min_value: 0.000001, max_value: null, data_types: [],
              options: [], required: true, default: 1.0,
            },
            {
              key: "coupled_products_file", label: "COUPLED quantification/measurement table path",
              value_type: "string", min_value: null, max_value: null,
              data_types: ["COUPLED"], options: [], required: true, default: "",
            },
          ],
        };
        const values = {
          "plot-font-family": "Arial",
          "plot-font-size": "12",
          "proc-folder": "D:/data",
          "proc-project": "demo project",
          "pro-area": "1.5",
          "pro-offset": "0.25",
          "pro-lsv-target": "10,100",
          "pro-lsv-tafel": "1-10",
          "pro-lsv-match": "prefix",
          "pro-lsv-prefix": "LSV",
          "pro-lsv-title": "LSV of {sample}",
          "pro-lsv-xlabel": "Potential",
          "pro-lsv-ylabel": "Current",
          "pro-lsv-line-width": "2",
          "pro-lsv-quality-min-points-issue": "5",
          "pro-lsv-quality-min-points-warning": "10",
          "pro-lsv-quality-outlier-warning-pct": "8",
          "pro-lsv-quality-min-potential-span": "0.1",
          "pro-lsv-quality-noise-warning": "1",
          "pro-lsv-quality-noise-critical": "2",
          "pro-lsv-quality-jump-warning": "0.2",
          "pro-lsv-quality-jump-critical": "0.5",
          "pro-lsv-quality-local-factor": "3",
          "pro-lsv-ir-source": "manual",
          "pro-lsv-ir-method": "auto",
          "pro-lsv-ir-manual": "4",
          "pro-lsv-ir-points": "8",
          "pro-lsv-eq-potential": "1.23",
          "pro-lsv-onset-current": "1",
          "pro-lsv-halfwave-current": "50",
          "pro-cv-match": "suffix",
          "pro-cv-prefix": "_CV",
          "pro-cv-title": "CV of {sample}",
          "pro-cv-xlabel": "Potential",
          "pro-cv-ylabel": "Current",
          "pro-cv-line-width": "1.5",
          "pro-cv-peaks-smooth": "7",
          "pro-cv-peaks-height": "0.1",
          "pro-cv-peaks-dist": "3",
          "pro-cv-peaks-max": "4",
          "pro-cv-cycle-numbers": "1,3",
          "pro-cv-quality-min-points-warning": "20",
          "pro-cv-quality-cycle-tolerance": "5",
          "pro-coupled-products-file": "products.csv",
          "pro-coupled-products-sheet": "Sheet1",
          "pro-coupled-results-csv": "fe.csv",
        };
        const checked = new Set([
          "pro-recursive-scan",
          "pro-output-run-dir",
          "pro-plot-grid",
          "pro-lsv-tafel-enabled",
          "pro-lsv-quality-check",
          "pro-lsv-ir-enabled",
          "pro-lsv-overpotential-enabled",
          "pro-lsv-onset-enabled",
          "pro-lsv-halfwave-enabled",
          "pro-cv-peaks-enabled",
          "pro-cv-cycle-plot-enabled",
          "pro-cv-quality-check",
        ]);
        const t = (key) => ({
          label_area: "Electrode area",
          label_cv_peaks_dist: "CV peak distance",
          label_cv_peaks_height: "CV peak height",
          label_cv_peaks_max: "CV peak max",
          label_cv_peaks_smooth: "CV peak smooth",
          label_cv_quality_cycle_tolerance: "CV cycle tolerance",
          label_cv_quality_min_points_warning: "CV min points",
          label_ecsa_cs_value: "ECSA Cs",
          label_ecsa_ev: "ECSA Ev",
          label_ecsa_last_n: "ECSA last N",
          label_eq_potential: "Equilibrium potential",
          label_font_size: "Font size",
          label_ir_manual: "Manual resistance",
          label_ir_points: "IR points",
          label_line_width: "Line width",
          label_offset: "Potential offset",
          label_quality_jump_critical: "Jump critical",
          label_quality_jump_warning: "Jump warning",
          label_quality_local_factor: "Local factor",
          label_quality_min_points_issue: "Min points issue",
          label_quality_min_points_warning: "Min points warning",
          label_quality_min_potential_span: "Potential span",
          label_quality_noise_critical: "Noise critical",
          label_quality_noise_warning: "Noise warning",
          label_quality_outlier_warning_pct: "Outlier pct",
          label_ref_custom: "Reference potential",
          label_rhe_ph: "pH",
          proc_folder_required: "folder required",
          proc_param_invalid: "Invalid parameter",
          proc_type_required: "type required",
        }[key] || key);
        const makeCtx = (overrides = {}) => ({
          boolValue: (id) => checked.has(id),
          currentLang: "en",
          getPotentialMode: () => "manual",
          getReferenceElectrodePotential: () => undefined,
          getSelectedProcessTypes: () => ["LSV", "CV", "COUPLED"],
          numberValue: (id) => {
            const raw = values[id] || "";
            const value = Number(raw);
            return Number.isFinite(value) ? value : undefined;
          },
          processParameterSchema,
          processSchemaClient,
          t,
          textValue: (id) => values[id] || "",
          ...overrides,
        });
        const result = builder.collectPayload(makeCtx());
        const invalid = builder.collectValidationErrors(makeCtx({
          boolValue: (id) => id === "pro-lsv-quality-check",
          textValue: (id) => id === "pro-area" ? "-1" : "",
          numberValue: (id) => id === "pro-area" ? -1 : undefined,
        }), ["LSV", "COUPLED"]);
        return {
          cvCycle: result.params.cv_cycle_numbers,
          cvPeaksMax: result.params.cv_peaks_max,
          dataTypes: result.data_types,
          invalid,
          lsvIr: result.params.ir_manual_ohm,
          lsvIrSource: [result.params.ir_source, result.params.ir_method],
          lsvQuality: result.params.lsv_quality_local_variation_factor,
          payloadTargets: [result.params.lsv_target_current, result.params.tafel_range],
          project: result.project_name,
          recursive: [result.params.recursive_scan, result.params.output_run_dir_enabled],
          table: [result.params.coupled_products_file, result.params.coupled_results_csv_filename],
        };
        """,
        dependencies=("process_schema.js",),
    )

    assert payload["cvCycle"] == "1,3"
    assert payload["cvPeaksMax"] == 4
    assert payload["dataTypes"] == ["LSV", "CV", "COUPLED"]
    assert payload["invalid"] == [
        "Electrode area must be >= 0.000001",
        "COUPLED quantification/measurement table path is required",
    ]
    assert payload["lsvIr"] == 4
    assert payload["lsvIrSource"] == ["manual", "auto"]
    assert payload["lsvQuality"] == 3
    assert payload["payloadTargets"] == ["10,100", "1-10"]
    assert payload["project"] == "demo project"
    assert payload["recursive"] == [True, True]
    assert payload["table"] == ["products.csv", "fe.csv"]


def test_process_payload_collects_temperature_dependent_rhe_and_eis_model() -> None:
    payload = _node_json(
        "process_payload.js",
        """
        const values = {
          "proc-folder": "D:/data",
          "pro-area": "1",
          "pro-rhe-ph": "13.5",
          "pro-rhe-temperature": "35",
          "pro-ref-preset": "agcl_sat_kcl",
          "pro-eis-circuit-model": "randles_cpe",
          "pro-eis-fit-min-r2": "0.95",
        };
        const ctx = {
          boolValue: (id) => id === "pro-eis-randles-fit",
          currentLang: "en",
          getPotentialMode: () => "formula_rhe",
          getReferenceElectrodePotential: () => 0.197,
          getSelectedProcessTypes: () => ["EIS"],
          numberValue: (id) => {
            const number = Number(values[id]);
            return Number.isFinite(number) ? number : undefined;
          },
          processParameterSchema: null,
          processSchemaClient: null,
          t: (key) => key,
          textValue: (id) => values[id] || "",
        };
        const result = window.ElectrochemProcessPayload.collectPayload(ctx);
        return {
          ph: result.params.rhe_ph,
          temperature: result.params.rhe_temperature_c,
          model: result.params.eis_circuit_model,
          minR2: result.params.eis_fit_min_r2,
          enabled: result.params.eis_randles_fit,
        };
        """,
    )

    assert payload == {
        "ph": 13.5,
        "temperature": 35,
        "model": "randles_cpe",
        "minR2": 0.95,
        "enabled": True,
    }


def test_process_payload_collects_peak_based_fe_options() -> None:
    payload = _node_json(
        "process_payload.js",
        """
        const builder = window.ElectrochemProcessPayload;
        const values = {
          "proc-folder": "D:/data/fe",
          "pro-coupled-input-mode": "peak_analysis",
          "pro-coupled-products-file": "measurements.csv",
          "pro-coupled-products-sheet": "0",
          "pro-coupled-peak-method-source": "file",
          "pro-coupled-peak-method-file": "method.json",
          "pro-fe-peak-search-tolerance": "0.08",
          "pro-fe-peak-window-left": "0.05",
          "pro-fe-peak-window-right": "0.06",
          "pro-fe-peak-min-detection-snr": "3",
          "pro-fe-peak-min-quantification-snr": "10",
          "pro-coupled-results-csv": "fe_results.csv",
        };
        const checked = new Set(["pro-fe-peak-auto-locate", "pro-fe-peak-reference-align"]);
        const ctx = {
          boolValue: (id) => checked.has(id),
          currentLang: "en",
          getPotentialMode: () => "manual",
          getReferenceElectrodePotential: () => undefined,
          getSelectedProcessTypes: () => ["COUPLED"],
          numberValue: (id) => {
            const value = Number(values[id]);
            return Number.isFinite(value) ? value : undefined;
          },
          t: (key) => key,
          textValue: (id) => values[id] || "",
        };
        const result = builder.collectPayload(ctx);
        values["pro-fe-peak-min-quantification-snr"] = "2";
        return {
          mode: result.params.coupled_input_mode,
          methodSource: result.params.coupled_peak_method_source,
          files: [result.params.coupled_products_file, result.params.coupled_peak_method_file],
          booleans: [result.params.fe_peak_auto_locate, result.params.fe_peak_reference_align, result.params.fe_peak_fit_enabled],
          windows: [result.params.fe_peak_search_tolerance, result.params.fe_peak_window_left, result.params.fe_peak_window_right],
          invalid: builder.collectValidationErrors(ctx, ["COUPLED"]),
        };
        """,
    )

    assert payload["mode"] == "peak_analysis"
    assert payload["methodSource"] == "file"
    assert payload["files"] == ["measurements.csv", "method.json"]
    assert payload["booleans"] == [True, True, False]
    assert payload["windows"] == [0.08, 0.05, 0.06]
    assert payload["invalid"] == ["Quantification SNR must not be lower than detection SNR"]


def test_process_payload_collects_panel_peak_method() -> None:
    payload = _node_json(
        "process_payload.js",
        """
        const builder = window.ElectrochemProcessPayload;
        const values = {
          "proc-folder": "D:/data/fe",
          "pro-coupled-input-mode": "peak_analysis",
          "pro-coupled-products-file": "measurements.csv",
          "pro-coupled-products-sheet": "0",
          "pro-coupled-peak-method-source": "panel",
          "pro-fe-peak-search-tolerance": "0.08",
          "pro-fe-peak-window-left": "0.05",
          "pro-fe-peak-window-right": "0.05",
          "pro-fe-peak-min-detection-snr": "3",
          "pro-fe-peak-min-quantification-snr": "10",
          "pro-coupled-results-csv": "fe_results.csv",
        };
        const method = {
          schema_version: "1.0",
          method_id: "panel-method",
          analysis_method: "qnmr_internal_standard",
          axis_unit: "ppm",
          internal_standard: {
            name: "standard",
            expected_position: 0,
            nuclei_count: 2,
            concentration_mM: 10,
            volume_uL: 100,
            search_tolerance: 0.08,
            window_left: 0.05,
            window_right: 0.05,
          },
          products: [{
            name: "acetate",
            expected_position: 1.9,
            nuclei_count: 3,
            electron_count: 4,
            response_factor: 1,
            search_tolerance: 0.08,
            window_left: 0.05,
            window_right: 0.05,
          }],
          sample_defaults: {
            electrolyte_volume_mL: 20,
            sample_aliquot_volume_uL: 500,
          },
        };
        const ctx = {
          boolValue: () => false,
          currentLang: "en",
          getCoupledPeakMethod: () => method,
          getPotentialMode: () => "manual",
          getReferenceElectrodePotential: () => undefined,
          getSelectedProcessTypes: () => ["COUPLED"],
          numberValue: (id) => {
            const value = Number(values[id]);
            return Number.isFinite(value) ? value : undefined;
          },
          t: (key) => key,
          textValue: (id) => values[id] || "",
        };
        const result = builder.collectPayload(ctx);
        return {
          method: result.params.coupled_peak_method,
          source: result.params.coupled_peak_method_source,
          errors: builder.collectValidationErrors(ctx, ["COUPLED"]),
        };
        """,
    )

    assert payload["source"] == "panel"
    assert payload["method"]["method_id"] == "panel-method"
    assert payload["method"]["products"][0]["electron_count"] == 4
    assert payload["errors"] == []


def test_process_runtime_drives_preflight_process_and_diagnostics() -> None:
    payload = _node_json(
        "process_runtime.js",
        """
        const runtime = window.ElectrochemProcessRuntime;
        const events = [];
        const statuses = [];
        const states = { preflight: "pending", run: "pending" };
        const target = { textContent: "" };
        let preflightCalls = 0;
        const t = (key) => ({
          diagnostics_done: "Diagnostics done",
          diagnostics_failed: "Diagnostics failed",
          diagnostics_running: "Diagnostics running",
          preflight_failed: "Preflight failed",
          preflight_running: "Preflight running",
          preflight_summary: "Preflight summary",
          preflight_text_files: "Text files",
          preflight_work_units: "Work units",
          proc_failed: "Process failed",
          proc_running: "Process running",
          proc_success: "Process success",
        }[key] || key);
        const preflightModel = {
          buildSummary: () => ({
            counts: [{ dtype: "LSV", label: "LSV", matched: 2 }],
            textFiles: 5,
            warnings: ["narrow"],
            workUnits: 2,
          }),
        };
        const ctx = {
          byId: (id) => id === "proc-preflight" ? target : null,
          collectProcessPayload: () => ({ folder_path: "D:/data", data_types: ["LSV"] }),
          formatPreflightSummary: (preflight) => runtime.formatPreflightSummary({
            moduleDescriptors: [],
            preflight,
            preflightModel,
            selectedTypes: ["LSV"],
            t,
          }),
          loadProjects: async () => events.push("load-projects"),
          loadStatsAndHistory: async () => events.push("load-stats"),
          processingApi: {
            exportDiagnostics: async () => ({
              ok: true,
              json: async () => ({ included_files: ["a", "b"], path: "D:/diag.zip", status: "success" }),
            }),
            preflight: async () => {
              preflightCalls += 1;
              return { ok: true, json: async () => ({ preflight: { selected_matched: 2 }, status: "success" }) };
            },
            runProcess: async () => ({
              ok: true,
              json: async () => ({
                result: { processing: { output_files: ["D:/out/a.png", "D:/out/b.csv"] }, summary: "Done" },
                status: "success",
              }),
            }),
          },
          renderPreflightChecks: (scan, state) => events.push(`preflight:${state}:${scan ? "scan" : "none"}`),
          renderProcessError: (message) => events.push(`error:${message}`),
          renderProcessResult: (result) => events.push(`result:${result.summary || result.processing.output_files[0]}`),
          runPreflight: (silent) => runtime.runPreflight(ctx, { silent }),
          setProcStatus: (text) => statuses.push(text),
          setProcessPreflightState: (state) => { states.preflight = state; },
          setProcessRunState: (state) => { states.run = state; },
          t,
          updateProcessStepState: () => events.push(`steps:${states.preflight}/${states.run}`),
        };
        const reset = runtime.resetState();
        const preflight = await runtime.runPreflight(ctx, { silent: false });
        const result = await runtime.runProcess(ctx);
        const diag = await runtime.exportDiagnostics(ctx);
        return {
          diagPath: diag.path,
          events,
          preflightCalls,
          preflightMatched: preflight.selected_matched,
          reset,
          resultSummary: result.summary,
          states,
          statuses,
          targetText: target.textContent,
        };
        """,
    )

    assert payload["reset"] == {"preflightState": "pending", "runState": "pending"}
    assert payload["preflightMatched"] == 2
    assert payload["resultSummary"] == "Done"
    assert payload["diagPath"] == "D:/diag.zip"
    assert payload["preflightCalls"] == 2
    assert payload["states"] == {"preflight": "complete", "run": "complete"}
    assert "Preflight summary: LSV: 2 | Text files: 5 | Work units: 2 | narrow" in payload["statuses"]
    assert "Process success: Done | output: D:/out/a.png, D:/out/b.csv" in payload["statuses"]
    assert "Diagnostics done: D:/diag.zip" in payload["statuses"]
    assert "result:Done" in payload["events"]
    assert "result:Diagnostics done" in payload["events"]
    assert payload["targetText"] == "Preflight summary: LSV: 2 | Text files: 5 | Work units: 2 | narrow"


def test_process_page_renders_module_cards_with_schema_defaults() -> None:
    payload = _node_json(
        "process_page.js",
        """
        const page = window.ElectrochemProcessPage;
        const container = { innerHTML: "" };
        const schemaClient = {
          buildModuleCards: () => [
            { key: "CV", cssClass: "mode-cv", descriptionKey: "mode_cv_desc", displayName: "CV", inputKind: "data_files", selected: false, summary: "CV summary" },
            { key: "LSV", cssClass: "mode-lsv", descriptionKey: "mode_lsv_desc", displayName: "LSV", inputKind: "data_files", selected: false, summary: "LSV summary" },
          ],
        };
        const cards = page.renderProcessTypeCards({
          container,
          escapeHtml: (value) => String(value || "").replaceAll("<", "&lt;"),
          processSchemaClient: schemaClient,
          schema: { modules: [] },
          selectedTypes: [],
          t: (key) => key === "mode_lsv_desc" ? "translated LSV" : key,
        });
        return {
          fallbackDesc: page.processTypeCardDescription({ descriptionKey: "unknown_key", summary: "fallback" }, (key) => key),
          htmlHasInput: container.innerHTML.includes('class="proc-type-check"'),
          htmlUsesTranslation: container.innerHTML.includes("translated LSV"),
          selected: cards.filter((card) => card.selected).map((card) => card.key),
        };
        """,
    )

    assert payload == {
        "fallbackDesc": "fallback",
        "htmlHasInput": True,
        "htmlUsesTranslation": True,
        "selected": ["LSV"],
    }


def test_assistant_page_renders_messages_conversations_and_llm_options() -> None:
    payload = _node_json(
        "assistant_page.js",
        """
        const page = window.ElectrochemAssistantPage;
        const listEl = {
          innerHTML: "",
          querySelectorAll: () => [],
        };
        const select = {
          innerHTML: "",
          value: "openai",
          appendChild: (option) => {
            select.innerHTML += `<option value="${option.value}">${option.textContent}</option>`;
          },
        };
        const fields = {
          "llm-provider": select,
          "llm-model": { value: "" },
          "llm-base-url": { value: "" },
          "llm-timeout": { value: "" },
          "llm-key-hint": { textContent: "" },
          "llm-source-hint": { textContent: "" },
        };
        global.document = {
          createElement: () => ({ textContent: "", value: "" }),
        };
        const models = {
          custom: { api_key_source: "saved", base_url: "https://api.example/v1", has_api_key: true, model: "gpt-x", timeout: 90 },
          bad: null,
        };
        const picked = page.renderLLMProviders({
          byId: (id) => fields[id] || null,
          defaultProvider: "custom",
          modelsByProvider: models,
          t: (key) => ({
            llm_key_configured: "configured",
            llm_key_missing: "missing",
            llm_key_source_saved: "saved key",
          }[key] || key),
        });
        page.renderConversations({
          currentConversationId: "c1",
          escapeHtml: (value) => String(value || "").replaceAll("<", "&lt;"),
          items: [{ conversation_id: "c1", provider: "mock", title: "Demo <A>", updated_at: "2026-06-05" }],
          listEl,
          renamingConversationId: "",
          t: (key) => ({ conv_delete_action: "Delete", conv_rename_action: "Rename" }[key] || key),
        });
        return {
          approvalHtml: page.renderPendingApprovals({
            escapeHtml: (value) => String(value || "").replaceAll("<", "&lt;"),
            metadata: { pending_approvals: [{
              approval_id: "approve-1",
              details: { folder_path: "D:/data/<batch>", tafel_enabled: true },
              summary: "Create <project>",
            }] },
            role: "agent",
            t: (key) => ({
              assistant_approval_cancel: "Cancel",
              assistant_approval_confirm: "Confirm",
              assistant_approval_detail_folder_path: "Data folder",
              assistant_approval_detail_tafel_enabled: "Tafel",
              assistant_approval_title: "Confirmation required",
              assistant_approval_value_yes: "Yes",
              assistant_approval_warning: "No changes yet",
            }[key] || key),
          }),
          conversationEscaped: listEl.innerHTML.includes("Demo &lt;A>"),
          conversationHasActions: listEl.innerHTML.includes("data-rename"),
          html: page.renderMessageItem({
            content: "**ok**",
            escapeHtml: (value) => String(value || ""),
            lang: "en",
            renderAgentContent: (value) => `<strong>${value}</strong>`,
            renderUserContent: (value) => value,
            metadata: { context_usage: { professional_mode: true, database: true } },
            role: "agent",
            timestamp: "now",
            t: (key) => ({
              assistant_source_database: "Database",
              assistant_source_label: "Sources",
              assistant_source_professional: "Professional",
            }[key] || key),
          }),
          keyHint: fields["llm-key-hint"].textContent,
          model: fields["llm-model"].value,
          picked,
          providers: page.listLLMProviders(models),
          roleEn: page.roleTextByRole("user", "en"),
          roleZhCodes: [...page.roleTextByRole("user", "zh")].map((ch) => ch.charCodeAt(0).toString(16)),
          resolvedApprovalHtml: page.renderPendingApprovals({
            metadata: { pending_approvals: [{ approval_id: "approve-1", summary: "Create project" }] },
            resolvedApprovalIds: new Set(["approve-1"]),
            role: "agent",
          }),
          expiredApprovalHtml: page.renderPendingApprovals({
            escapeHtml: (value) => String(value || ""),
            metadata: { pending_approvals: [{ approval_id: "expired-1", status: "expired", summary: "Old action" }] },
            role: "agent",
            t: (key) => ({
              assistant_approval_expired_title: "Expired",
              assistant_approval_expired_warning: "Ask again",
            }[key] || key),
          }),
          sourceHint: fields["llm-source-hint"].textContent,
        };
        """,
    )

    assert payload["conversationEscaped"] is True
    assert payload["conversationHasActions"] is True
    assert "data-approval-action=\"approve\"" in payload["approvalHtml"]
    assert "Create &lt;project>" in payload["approvalHtml"]
    assert "No changes yet" in payload["approvalHtml"]
    assert "Data folder" in payload["approvalHtml"]
    assert "D:/data/&lt;batch>" in payload["approvalHtml"]
    assert "Tafel" in payload["approvalHtml"]
    assert "Yes" in payload["approvalHtml"]
    assert payload["resolvedApprovalHtml"] == ""
    assert "Expired" in payload["expiredApprovalHtml"]
    assert "Ask again" in payload["expiredApprovalHtml"]
    assert "data-approval-action" not in payload["expiredApprovalHtml"]
    assert "AI | now" in payload["html"]
    assert "<strong>**ok**</strong>" in payload["html"]
    assert "Sources" in payload["html"]
    assert "Professional" in payload["html"]
    assert "Database" in payload["html"]
    assert payload["keyHint"] == "configured"
    assert payload["model"] == "gpt-x"
    assert payload["picked"] == "custom"
    assert payload["providers"] == ["custom"]
    assert payload["roleEn"] == "User"
    assert payload["roleZhCodes"] == ["7528", "6237"]
    assert payload["sourceHint"] == "saved key"


def test_ai_settings_page_loads_saves_tests_and_wraps_prompt_settings() -> None:
    payload = _node_json(
        "ai_settings_page.js",
        """
        const page = window.ElectrochemAISettingsPage;
        const statuses = [];
        const renderCalls = [];
        const presetCalls = [];
        const savedPayloads = [];
        const testedPayloads = [];
        let modelsByProvider = {};
        const fields = {
          "llm-api-key": { disabled: false, value: "sk-demo" },
          "llm-base-url": { disabled: false, value: "https://api.example/v1" },
          "llm-model": { disabled: false, value: "gpt-demo" },
          "llm-provider": { disabled: false, value: "custom" },
          "llm-test": { disabled: false, value: "" },
          "llm-timeout": { disabled: false, value: "60" },
        };
        const t = (key) => ({
          status_llm_loaded: "loaded",
          status_llm_loading: "loading",
          status_llm_no_changes: "no changes",
          status_llm_provider_required: "provider required",
          status_llm_save_running: "saving",
          status_llm_save_success: "saved",
          status_llm_test_running: "testing",
          status_llm_test_success: "test ok",
          status_llm_timeout_invalid: "bad timeout",
          status_prompt_applied: "prompt applied",
          status_prompt_saved: "prompt saved",
        }[key] || key);
        const ctx = {
          assistantPage: {
            applyLLMProviderPreset: (opts) => presetCalls.push(opts.provider),
            listLLMProviders: (models) => Object.keys(models).filter((key) => models[key]),
            renderLLMProviders: (opts) => { renderCalls.push(opts.defaultProvider); return opts.defaultProvider || "custom"; },
            updateLLMKeyHint: (opts) => presetCalls.push(`hint:${opts.provider}`),
          },
          assistantPrompt: {
            applyTemplate: (opts) => opts.onStatus(opts.translate("status_prompt_applied")),
            buildMessage: (message) => `PREFIX\\n\\n${message}`,
            getActivePrefix: () => "PREFIX",
            load: () => statuses.push("prompt loaded"),
            renderTemplateOptions: (translate) => statuses.push(translate("prompt_tpl_analyst")),
            save: (opts) => opts.onStatus(opts.translate("status_prompt_saved")),
          },
          byId: (id) => fields[id] || null,
          getModelsByProvider: () => modelsByProvider,
          llmApi: {
            getConfig: async () => ({
              ok: true,
              json: async () => ({
                default_provider: "custom",
                models: { custom: { model: "gpt-old" } },
                status: "success",
              }),
            }),
            saveConfig: async (payload) => {
              savedPayloads.push(payload);
              return { ok: true, json: async () => ({ config: { model: payload.model }, status: "success" }) };
            },
            testConfig: async (payload) => {
              testedPayloads.push(payload);
              return { ok: true, json: async () => ({ model: payload.model, provider: payload.provider, status: "success" }) };
            },
          },
          setLLMStatus: (text) => statuses.push(text),
          setModelsByProvider: (models) => { modelsByProvider = models; },
          t,
          textValue: (id) => String((fields[id] && fields[id].value) || "").trim(),
        };

        const invalid = page.buildLLMConfigPayload({ ...ctx, textValue: (id) => id === "llm-provider" ? "custom" : id === "llm-timeout" ? "0" : "" });
        const loaded = await page.loadLLMConfig(ctx);
        const built = page.buildLLMConfigPayload(ctx, { requireChanges: true });
        const saved = await page.saveLLMConfig(ctx);
        const tested = await page.testLLMConnection(ctx);
        page.loadPromptSettings(ctx);
        page.renderPromptTemplateOptions(ctx);
        page.applyPromptTemplate(ctx);
        page.savePromptSettings(ctx);
        return {
          activePrefix: page.getActivePromptPrefix(ctx),
          built,
          invalid,
          keyAfterSave: fields["llm-api-key"].value,
          list: page.listLLMProviders(ctx),
          loadedDefault: loaded.default_provider,
          modelsByProvider,
          prompted: page.buildPromptedMessage(ctx, "hello"),
          renderCalls,
          savedPayloads,
          savedStatus: saved.status,
          statuses,
          testDisabled: fields["llm-test"].disabled,
          testedModel: tested.model,
          testedPayloads,
        };
        """,
    )

    assert payload["invalid"] == {"error": "bad timeout"}
    assert payload["loadedDefault"] == "custom"
    assert payload["built"]["payload"] == {
        "api_key": "sk-demo",
        "base_url": "https://api.example/v1",
        "model": "gpt-demo",
        "provider": "custom",
        "timeout": 60,
    }
    assert payload["keyAfterSave"] == ""
    assert payload["modelsByProvider"]["custom"]["model"] == "gpt-demo"
    assert payload["savedPayloads"][0]["api_key"] == "sk-demo"
    assert payload["savedStatus"] == "success"
    assert payload["testedPayloads"][0]["provider"] == "custom"
    assert payload["testedModel"] == "gpt-demo"
    assert payload["testDisabled"] is False
    assert payload["list"] == ["custom"]
    assert payload["renderCalls"] == ["custom", "custom"]
    assert payload["activePrefix"] == "PREFIX"
    assert payload["prompted"] == "PREFIX\n\nhello"
    assert "loading" in payload["statuses"]
    assert "loaded" in payload["statuses"]
    assert "saved" in payload["statuses"]
    assert "test ok: custom | gpt-demo" in payload["statuses"]
    assert "prompt loaded" in payload["statuses"]
    assert "prompt applied" in payload["statuses"]
    assert "prompt saved" in payload["statuses"]


def test_project_page_renders_project_widgets_and_output_groups() -> None:
    payload = _node_json(
        "project_page.js",
        """
        const page = window.ElectrochemProjectPage;
        const fields = {
          "project-stat-total": { textContent: "" },
          "project-stat-lsv": { textContent: "" },
          "project-stat-cv": { textContent: "" },
          "project-stat-eis": { textContent: "" },
          "project-stat-ecsa": { textContent: "" },
          "project-stat-coupled": { textContent: "" },
          "project-edit-name": { value: "" },
          "project-edit-color": { value: "" },
          "project-edit-tags": { value: "" },
          "project-edit-desc": { value: "" },
          "project-save-btn": { disabled: false },
        };
        const listEl = { innerHTML: "", querySelectorAll: () => [] };
        const lsvWrap = { innerHTML: "" };
        const outWrap = { innerHTML: "" };
        const t = (key) => ({
          btn_copy_path: "Copy",
          btn_open_dir: "Open dir",
          btn_open_file: "Open",
          project_empty: "No projects",
          project_label_files: "Files",
          project_label_updated: "Updated",
          project_lsv_col_count: "Count",
          project_lsv_col_eta: "Eta",
          project_lsv_col_sample: "Sample",
          project_lsv_col_tafel: "Tafel",
          project_lsv_col_time: "Time",
          project_no_lsv: "No LSV",
          project_no_output_files: "No files",
          project_output_group_prefix: "Run",
        }[key] || key);
        page.renderStats({ byId: (id) => fields[id] || null, data: { total_files: 7, lsv_count: 3 }, prefix: "project-stat" });
        page.setProjectEditForm({
          byId: (id) => fields[id] || null,
          project: { color: "#00BCD4", description: "demo", name: "P1", tags: ["alpha", "beta"] },
        });
        page.renderProjectList({
          escapeHtml: (value) => String(value || "").replaceAll("<", "&lt;"),
          items: [{ color: "#123456", file_count: 2, id: "p1", name: "Project <1>", tags: ["a"], updated_at: "2026-06-05" }],
          listEl,
          selectedProjectId: "p1",
          t,
        });
        page.renderProjectLSVSummary({
          escapeHtml: (value) => String(value || ""),
          formatMetric: (value) => Number(value).toFixed(1),
          summary: { samples: [{ latest_time: "now", overpotential_10: 123.456, record_count: 2, sample_name: "S1", tafel_slope: 44.4 }] },
          t,
          wrap: lsvWrap,
        });
        const groups = page.renderProjectOutputFiles({
          escapeHtml: (value) => String(value || "").replaceAll("<", "&lt;"),
          history: [
            { output_files: ["D:/out/a.png", "D:/out/a.png"], run_id: "r1", sample_name: "S1", timestamp: "now", type: "LSV" },
            { summary_path: "D:/out/b.json", run_id: "r1", sample_name: "S1", timestamp: "now", type: "LSV" },
          ],
          historyRecordKey: (record) => record.run_id || "",
          outputTypeFilter: "LSV",
          t,
          wrap: outWrap,
        });
        return {
          editName: fields["project-edit-name"].value,
          editTags: fields["project-edit-tags"].value,
          listActive: listEl.innerHTML.includes("project-item active"),
          listEscaped: listEl.innerHTML.includes("Project &lt;1>"),
          lsvEta: lsvWrap.innerHTML.includes("123.5 mV"),
          outputFiles: groups[0].files,
          outputHtml: outWrap.innerHTML.includes("a.png") && outWrap.innerHTML.includes("b.json"),
          saveDisabled: fields["project-save-btn"].disabled,
          total: fields["project-stat-total"].textContent,
        };
        """,
    )

    assert payload == {
        "editName": "P1",
        "editTags": "alpha, beta",
        "listActive": True,
        "listEscaped": True,
        "lsvEta": True,
        "outputFiles": ["D:/out/a.png", "D:/out/b.json"],
        "outputHtml": True,
        "saveDisabled": False,
        "total": "7",
    }


def test_project_history_detail_renders_sample_note_and_linked_raw_files() -> None:
    payload = _node_json(
        "project_page.js",
        """
        const page = window.ElectrochemProjectPage;
        let saved = 0;
        const wrap = { innerHTML: "" };
        const saveButton = { addEventListener: (name, callback) => { if (name === "click") { saved += 1; callback(); } } };
        const elements = {
          "project-history-detail": wrap,
          "project-open-result-btn": { disabled: true },
          "project-archive-history-btn": { disabled: true },
          "project-delete-history-btn": { disabled: true },
          "project-sample-save-btn": saveButton,
        };
        const escapeHtml = (value) => String(value || "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;");
        page.renderProjectHistoryDetail({
          byId: (id) => elements[id] || null,
          escapeHtml,
          onSaveSample: () => { saved += 10; },
          record: {
            project_id: "p1",
            sample_id: "s1",
            sample_name: "Sample A",
            sample_note: "0.5 M KOH",
            sample_tags: ["control", "repeat"],
            file_path: "D:/raw/a_lsv.txt",
            type: "LSV",
          },
          sampleRecords: [
            { file_path: "D:/raw/a_lsv.txt" },
            { file_path: "D:/raw/a_cv.txt", source_archive_path: "D:/managed/source.zip" },
          ],
          t: (key) => key,
        });
        return {
          hasNote: wrap.innerHTML.includes("0.5 M KOH"),
          hasTags: wrap.innerHTML.includes("control, repeat"),
          hasRawLsv: wrap.innerHTML.includes("D:/raw/a_lsv.txt"),
          hasRawCv: wrap.innerHTML.includes("D:/raw/a_cv.txt"),
          hasArchive: wrap.innerHTML.includes("D:/managed/source.zip"),
          saved,
        };
        """,
    )

    assert payload == {
        "hasNote": True,
        "hasTags": True,
        "hasRawLsv": True,
        "hasRawCv": True,
        "hasArchive": True,
        "saved": 11,
    }


def test_project_history_renders_every_loaded_record() -> None:
    payload = _node_json(
        "project_page.js",
        """
        const page = window.ElectrochemProjectPage;
        const listEl = { innerHTML: "", querySelectorAll: () => [] };
        const records = Array.from({ length: 35 }, (_, index) => ({
          run_id: `run-${index}`,
          sample_name: `Sample ${index}`,
          status: "success",
          timestamp: `2026-08-27 10:${String(index).padStart(2, "0")}:00`,
          type: "LSV",
        }));
        page.renderProjectHistory({
          escapeHtml: (value) => String(value || ""),
          historyRecordKey: (record) => record.run_id,
          listEl,
          records,
          selectedKey: "run-0",
          t: (key) => key,
        });
        return { rendered: (listEl.innerHTML.match(/class="history-item/g) || []).length };
        """,
    )

    assert payload["rendered"] == 35


def test_project_workspace_runs_project_lifecycle_flows() -> None:
    payload = _node_json(
        "project_workspace.js",
        """
        const workspace = window.ElectrochemProjectWorkspace;
        const statuses = [];
        const renders = [];
        const apiCalls = [];
        const fields = {
          "proc-project": { value: "" },
          "project-create-name": { value: "Created project" },
          "project-edit-color": { value: "#00BCD4" },
          "project-edit-desc": { value: "updated desc" },
          "project-edit-name": { value: "Project One Updated" },
          "project-edit-tags": { value: "alpha, beta" },
        };
        let projectItems = [];
        let selectedProjectId = "";
        let projectDetailState = null;
        let selectedProjectHistoryKey = "old";
        let compareResetCount = 0;
        let targetCurrents = null;
        let latestPlotLoads = 0;
        const projects = [
          { id: "p1", name: "Project One" },
          { id: "p2", name: "Project Two" },
        ];
        function response(payload, ok = true) {
          return { ok, json: async () => payload };
        }
        const t = (key) => ({
          project_color_invalid: "bad color",
          project_confirm_delete: "delete?",
          project_confirm_delete_permanent: "delete forever?",
          project_export_report_success: "report ok",
          project_name_required: "name required",
          project_status_applied: "applied",
          project_status_create_running: "creating",
          project_status_create_success: "created",
          project_status_delete_running: "deleting",
          project_status_delete_success: "deleted",
          project_status_detail_loading: "detail loading",
          project_status_loading: "loading",
          project_status_permanent_delete_partial: "partial {count}",
          project_status_permanent_delete_running: "permanent deleting",
          project_status_save_running: "saving",
          project_status_save_success: "saved",
        }[key] || key);
        const ctx = {
          byId: (id) => fields[id] || null,
          confirm: (message) => { apiCalls.push(`confirm:${message}`); return true; },
          getProjectIncludeArchived: () => true,
          getProjectItems: () => projectItems,
          getSelectedProjectId: () => selectedProjectId,
          loadLatestProjectComparePlot: async (silent) => { latestPlotLoads += silent ? 1 : 10; },
          loadProjectCompareTargetCurrents: async (projectId) => { targetCurrents = projectId; },
          projectApi: {
            createProject: async (payload) => { apiCalls.push(`create:${payload.name}`); return response({ project_id: "p2", status: "success" }); },
            deleteProject: async (projectId) => { apiCalls.push(`delete:${projectId}`); return response({ status: "success" }); },
            permanentlyDeleteProject: async (projectId) => {
              apiCalls.push(`permanent:${projectId}`);
              return response({ artifact_cleanup: { skipped: ["locked"] }, status: "success" });
            },
            exportReport: async (projectId, options) => {
              apiCalls.push(`export:${projectId}:${options.includeArchived}`);
              return response({ path: "D:/report.md", status: "success" });
            },
            history: async (options) => {
              apiCalls.push(`history:${options.projectId}:${options.includeArchived}`);
              return response({ records: [{ sample_name: "S1" }], status: "success" });
            },
            listProjects: async () => { apiCalls.push("list"); return response({ projects, status: "success" }); },
            lsvSummary: async (projectId) => { apiCalls.push(`lsv:${projectId}`); return response({ lsv_summary: { samples: [{ sample_name: "S1" }] }, status: "success" }); },
            stats: async (options) => { apiCalls.push(`stats:${options.projectId || "all"}:${options.includeArchived}`); return response({ data: { total_files: 3 }, status: "success" }); },
            updateProject: async (projectId, payload) => {
              apiCalls.push(`update:${projectId}:${payload.name}:${payload.tags.join("+")}:${payload.color}`);
              const index = projects.findIndex((item) => item.id === projectId);
              if (index >= 0) projects[index] = { ...projects[index], name: payload.name };
              return response({ status: "success" });
            },
          },
          renderProjectList: (items) => renders.push(`list:${items.length}:${selectedProjectId}`),
          renderSelectedProjectDetail: () => renders.push(`detail:${selectedProjectId}:${projectDetailState ? "loaded" : "empty"}`),
          resetProjectCompareState: () => { compareResetCount += 1; },
          setProjectCompareTargetCurrents: (value) => { targetCurrents = value; },
          setProjectDetailState: (value) => { projectDetailState = value; },
          setProjectItems: (items) => { projectItems = items; },
          setProjectStatus: (text) => statuses.push(text),
          setSelectedProjectHistoryKey: (value) => { selectedProjectHistoryKey = value; },
          setSelectedProjectId: (value) => { selectedProjectId = value; },
          syncProcessProjectOptions: () => renders.push("sync-options"),
          t,
          textValue: (id) => String((fields[id] && fields[id].value) || "").trim(),
        };

        const editPayload = workspace.readProjectEditPayload(ctx);
        await workspace.loadProjects(ctx, "p2");
        const afterLoad = { selectedProjectId, detail: projectDetailState, selectedProjectHistoryKey, targetCurrents };
        workspace.applyCurrentProjectToForms(ctx);
        await workspace.saveCurrentProject(ctx);
        const afterSave = { procProject: fields["proc-project"].value, selectedProjectId };
        await workspace.createProject(ctx);
        await workspace.exportCurrentProjectReport(ctx);
        await workspace.deleteCurrentProject(ctx);
        selectedProjectId = "p2";
        await workspace.permanentlyDeleteCurrentProject(ctx);
        return {
          afterLoad,
          afterSave,
          apiCalls,
          compareResetCount,
          editPayload,
          emptyTargetCurrents: workspace.emptyTargetCurrents(),
          latestPlotLoads,
          projectItems,
          renders,
          selectedProjectId,
          statuses,
        };
        """,
    )

    assert payload["editPayload"] == {
        "payload": {
            "color": "#00BCD4",
            "description": "updated desc",
            "name": "Project One Updated",
            "tags": ["alpha", "beta"],
        }
    }
    assert payload["afterLoad"]["selectedProjectId"] == "p2"
    assert payload["afterLoad"]["selectedProjectHistoryKey"] == ""
    assert payload["afterLoad"]["detail"]["stats"] == {"total_files": 3}
    assert payload["afterLoad"]["targetCurrents"] == "p2"
    assert payload["afterSave"] == {
        "procProject": "Project Two",
        "selectedProjectId": "p2",
    }
    assert payload["emptyTargetCurrents"] == {
        "overpotential_target_currents": [],
        "potential_target_currents": [],
        "target_currents": [],
    }
    assert payload["compareResetCount"] >= 3
    assert payload["latestPlotLoads"] >= 3
    assert "create:Created project" in payload["apiCalls"]
    assert "update:p2:Project One Updated:alpha+beta:#00BCD4" in payload["apiCalls"]
    assert "export:p2:true" in payload["apiCalls"]
    assert "confirm:delete?" in payload["apiCalls"]
    assert "delete:p2" in payload["apiCalls"]
    assert "permanent:p2" in payload["apiCalls"]
    assert payload["selectedProjectId"] == "p1"
    assert "created" in payload["statuses"]
    assert "saved" in payload["statuses"]
    assert "report ok: D:/report.md" in payload["statuses"]
    assert "deleted" in payload["statuses"]
    assert "partial 1" in payload["statuses"]
    assert any(item.startswith("detail:p2:loaded") for item in payload["renders"])


def test_project_history_workspace_handles_selection_and_mutations() -> None:
    payload = _node_json(
        "project_history_workspace.js",
        """
        const workspace = window.ElectrochemProjectHistoryWorkspace;
        const statuses = [];
        const procStatuses = [];
        const tabs = [];
        const renders = [];
        const confirms = [];
        const apiCalls = [];
        const reloads = [];
        const processResults = [];
        let selectedKey = "r2";
        const projectDetailState = {
          history: [
            { run_id: "r1", sample_name: "S1", type: "LSV" },
            { run_id: "r2", sample_name: "S2", type: "CV" },
          ],
        };
        function response(payload, ok = true) {
          return { ok, json: async () => payload };
        }
        const t = (key) => ({
          project_history_archive_failed: "archive failed",
          project_history_archive_running: "archiving",
          project_history_archive_success: "archived",
          project_history_confirm_archive: "archive?",
          project_history_confirm_delete: "delete?",
          project_history_delete_failed: "delete failed",
          project_history_delete_running: "deleting",
          project_history_delete_success: "deleted",
          project_open_result_done: "opened",
          project_open_result_empty: "empty",
          status_history_loaded: "history loaded",
        }[key] || key);
        const ctx = {
          byId: () => ({ innerHTML: "" }),
          buildResultFromHistoryRecord: (record) => ({ sample: record.sample_name, type: record.type }),
          confirm: (message) => { confirms.push(message); return true; },
          escapeHtml: (value) => String(value || ""),
          getProjectDetailState: () => projectDetailState,
          getSelectedProjectHistoryKey: () => selectedKey,
          historyRecordKey: (record) => record.run_id || "",
          loadSelectedProjectDetail: async () => { reloads.push("detail"); },
          loadStatsAndHistory: async () => { reloads.push("stats"); },
          projectApi: {
            archiveHistory: async (key) => { apiCalls.push(`archive:${key}`); return response({ status: "success" }); },
            deleteHistory: async (key) => { apiCalls.push(`delete:${key}`); return response({ status: "success" }); },
          },
          projectPage: {
            renderProjectHistory: (opts) => {
              const records = Array.isArray(opts.records) ? opts.records : [];
              let picked = String(opts.selectedKey || "");
              if (!records.some((record) => opts.historyRecordKey(record) === picked)) {
                picked = records.length ? opts.historyRecordKey(records[0]) : "";
              }
              const selectedRecord = records.find((record) => opts.historyRecordKey(record) === picked) || null;
              renders.push(`list:${records.length}:${picked}`);
              return { selectedKey: picked, selectedRecord };
            },
            renderProjectHistoryDetail: (opts) => {
              renders.push(`detail:${opts.record ? opts.record.run_id : "none"}`);
            },
          },
          renderProcessResult: (result) => { processResults.push(result); },
          setProcStatus: (text) => { procStatuses.push(text); },
          setProjectStatus: (text) => { statuses.push(text); },
          setSelectedProjectHistoryKey: (value) => { selectedKey = String(value || ""); },
          switchTab: (tab) => { tabs.push(tab); },
          t,
        };

        const initial = workspace.getSelectedProjectHistoryRecord(ctx);
        workspace.renderProjectHistory(ctx, projectDetailState.history);
        const picked = workspace.selectProjectHistory(ctx, 0);
        const opened = workspace.openSelectedProjectHistoryResult(ctx);
        await workspace.archiveSelectedProjectHistory(ctx);
        selectedKey = "r2";
        await workspace.deleteSelectedProjectHistory(ctx);
        selectedKey = "";
        const missing = workspace.openSelectedProjectHistoryResult(ctx);
        return {
          apiCalls,
          confirms,
          initial: initial && initial.sample_name,
          missing,
          opened: opened && opened.sample_name,
          picked: picked && picked.sample_name,
          processResults,
          procStatuses,
          reloads,
          renders,
          selectedKey,
          statuses,
          tabs,
        };
        """,
    )

    assert payload["initial"] == "S2"
    assert payload["picked"] == "S1"
    assert payload["opened"] == "S1"
    assert payload["processResults"] == [{"sample": "S1", "type": "LSV"}]
    assert payload["procStatuses"] == ["history loaded"]
    assert payload["tabs"] == ["pro"]
    assert payload["confirms"] == ["archive?", "delete?"]
    assert payload["apiCalls"] == ["archive:r1", "delete:r2"]
    assert payload["reloads"] == ["detail", "stats", "detail", "stats"]
    assert payload["missing"] is None
    assert payload["selectedKey"] == ""
    assert "opened" in payload["statuses"]
    assert "archived" in payload["statuses"]
    assert "deleted" in payload["statuses"]
    assert "empty" in payload["statuses"]
    assert "list:2:r2" in payload["renders"]
    assert "detail:r1" in payload["renders"]


def test_project_compare_page_renders_summary_table_controls_and_plot() -> None:
    payload = _node_json(
        "project_compare_page.js",
        """
        const page = window.ElectrochemProjectComparePage;
        const fields = {
          "project-compare-summary": { innerHTML: "" },
          "project-compare-table": { innerHTML: "", querySelectorAll: () => [] },
          "project-compare-selected-count": { textContent: "" },
          "project-compare-plot": { innerHTML: "" },
          "project-compare-metric": { disabled: false },
          "project-compare-target-current": { disabled: false, innerHTML: "", value: "" },
          "project-compare-target-wrap": { style: {} },
        };
        const model = {
          availableTargetCurrents: (state, metric) => metric === "potential_at_target" ? state.potential_target_currents : state.target_currents,
          filterSamples: (samples, options) => [...samples].sort((a, b) => (a.overpotential_10 ?? 999) - (b.overpotential_10 ?? 999)),
          formatTargetCurrent: (value) => String(value),
          needsTargetCurrent: (chartType, metric) => chartType === "bar" && metric !== "tafel_slope",
          selectTargetCurrent: (options, currentValue) => ({ options, value: options.includes(Number(currentValue)) ? String(currentValue) : String(options[0] || "") }),
          syncSelectedSamples: (samples, selectedSamples, maxDefault) => ({
            clearPlot: !selectedSamples.length,
            selectedSamples: selectedSamples.length ? selectedSamples : samples.slice(0, maxDefault).map((item) => item.sample_name),
            visibleNames: samples.map((item) => item.sample_name),
          }),
        };
        const t = (key) => ({
          btn_copy_path: "Copy",
          btn_open_dir: "Open dir",
          btn_open_file: "Open",
          project_compare_best_eta: "Best eta",
          project_compare_best_tafel: "Best tafel",
          project_compare_col_count: "Count",
          project_compare_col_eta: "Eta",
          project_compare_col_sample: "Sample",
          project_compare_col_tafel: "Tafel",
          project_compare_col_time: "Time",
          project_compare_empty: "No compare",
          project_compare_missing: "Missing",
          project_compare_missing_eta: "Missing eta",
          project_compare_missing_tafel: "Missing tafel",
          project_compare_plot_empty: "No plot",
          project_compare_plot_generated_at: "Generated",
          project_compare_plot_loading: "Loading",
          project_compare_plot_title: "Compare plot",
          project_compare_plot_traces: "Traces",
          project_compare_selected_count: "Selected {count}",
          project_compare_selected_count_empty: "No selected",
          project_compare_target_current_empty: "No targets",
        }[key] || key);
        const summary = {
          samples: [
            { latest_time: "t1", overpotential_10: 120, record_count: 1, sample_name: "S1", tafel_slope: null },
            { latest_time: "t2", overpotential_10: 90, record_count: 2, sample_name: "S2", tafel_slope: 33.3 },
            { latest_time: "t3", potential_10: 1.5, record_count: 3, sample_name: "S3" },
          ],
        };
        const synced = page.syncSelection({
          model,
          state: { selectedSamples: [], sort: "eta" },
          summary,
          maxDefault: 2,
        });
        const state = {
          chartType: "bar",
          metric: "potential_at_target",
          plotData: {
            generated_at: "now",
            image_data_url: "data:image/png;base64,abc",
            metric_label: "E@10",
            plot_path: "D:/plot.png",
            trace_count: 2,
            warnings: ["narrow set"],
          },
          selectedSamples: synced.selectedSamples,
          targetCurrent: "10",
          targetCurrents: {
            potential_target_currents: [5, 10],
            target_currents: [10],
          },
        };
        const common = {
          byId: (id) => fields[id] || null,
          escapeHtml: (value) => String(value || "").replaceAll("<", "&lt;"),
          model,
          state,
          t,
        };
        page.renderSummary({ ...common, formatMetric: (value) => Number(value).toFixed(1), summary });
        page.renderTable({
          ...common,
          formatMetric: (value) => Number(value).toFixed(1),
          onSelectionChange: () => {},
          summary,
        });
        const target = page.renderPlot({ ...common, bindFileActions: () => { fields.bound = true; } });
        return {
          count: fields["project-compare-selected-count"].textContent,
          metricDisabled: fields["project-compare-metric"].disabled,
          plotHasImage: fields["project-compare-plot"].innerHTML.includes("data:image/png"),
          plotWarning: fields["project-compare-plot"].innerHTML.includes("narrow set"),
          selected: synced.selectedSamples,
          summaryBest: fields["project-compare-summary"].innerHTML.includes("S2 | 90.0 mV"),
          tableHasCheckbox: fields["project-compare-table"].innerHTML.includes("project-compare-sample"),
          targetCurrent: target.targetCurrent,
          targetOptions: fields["project-compare-target-current"].innerHTML,
          targetOpacity: fields["project-compare-target-wrap"].style.opacity,
          targetValue: fields["project-compare-target-current"].value,
        };
        """,
    )

    assert payload["count"] == "Selected 2"
    assert payload["metricDisabled"] is False
    assert payload["plotHasImage"] is True
    assert payload["plotWarning"] is True
    assert payload["selected"] == ["S2", "S1"]
    assert payload["summaryBest"] is True
    assert payload["tableHasCheckbox"] is True
    assert payload["targetCurrent"] == "10"
    assert 'value="10"' in payload["targetOptions"]
    assert payload["targetOpacity"] == "1"
    assert payload["targetValue"] == "10"


def test_process_schema_maps_module_descriptors_and_aliases() -> None:
    payload = _node_json(
        "process_schema.js",
        """
        const schemaClient = window.ElectrochemProcessingSchema;
        const schema = {
          parameters: [
            { key: "runtime_default", default: "runtime", ui_default: "ui" },
            { key: "plain_default", default: 12, ui_default: 12 },
          ],
          modules: [
            { key: "LSV", display_name: "LSV", aliases: [], input_kind: "data_files" },
            { key: "COUPLED", display_name: "COUPLED/FE", aliases: ["FE"], input_kind: "product_table" },
          ],
        };
        return {
          cards: schemaClient.buildModuleCards(schema, ["FE", "LSV"]),
          coupled: schemaClient.getModule(schema, "FE"),
          defaults: [
            schemaClient.getDefault(schema, "runtime_default", null),
            schemaClient.getDefault(schema, "plain_default", null),
          ],
          keys: Array.from(schemaClient.moduleMap(schema).keys()),
          modules: schemaClient.moduleList(schema).map((item) => item.key),
        };
        """,
    )

    assert payload["modules"] == ["LSV", "COUPLED"]
    assert payload["keys"] == ["LSV", "COUPLED", "FE"]
    assert payload["coupled"]["display_name"] == "COUPLED/FE"
    assert payload["coupled"]["input_kind"] == "product_table"
    assert payload["defaults"] == ["ui", 12]
    assert payload["cards"] == [
        {
            "key": "LSV",
            "cssClass": "mode-lsv",
            "descriptionKey": "mode_lsv_desc",
            "displayName": "LSV",
            "inputKind": "data_files",
            "selected": True,
            "summary": "",
        },
        {
            "key": "COUPLED",
            "cssClass": "mode-coupled",
            "descriptionKey": "mode_coupled_desc",
            "displayName": "COUPLED/FE",
            "inputKind": "product_table",
            "selected": True,
            "summary": "",
        },
    ]


def test_process_schema_frontend_bindings_cover_backend_parameters() -> None:
    payload = _node_json(
        "process_schema.js",
        """
        const schemaClient = window.ElectrochemProcessingSchema;
        return {
          bindingKeys: Object.keys(schemaClient.CONTROL_BINDINGS).sort(),
          uniqueControlCount: schemaClient.controlIds().length,
        };
        """,
    )

    backend_keys = {
        item["key"]
        for item in processing_parameter_schema()["parameters"]
        if item["key"] != "coupled_peak_method"
    }
    assert set(payload["bindingKeys"]) == backend_keys
    assert payload["uniqueControlCount"] == len(backend_keys)


def test_preflight_model_builds_file_cards_and_summary() -> None:
    payload = _node_json(
        "preflight_model.js",
        """
        const model = window.ElectrochemPreflightModel;
        const scan = {
          by_type: {
            LSV: {
              examples: ["D:/data/one.txt", "D:/data/two.txt", "D:/data/three.txt", "D:/data/four.txt"],
              match: "prefix",
              matched: 2,
              prefix: "LSV",
            },
            CV: { examples: [], match: "regex", matched: 0, pattern: "^CV" },
          },
          ir_compensation: {
            items: [{
              eis_file: "D:/data/EIS_one.txt",
              extraction_method: "auto",
              lsv_file: "D:/data/LSV_one.txt",
              message: "matched",
              scope: "same_dir",
              source: "eis",
              status: "matched",
            }],
          },
          text_files: 9,
          warnings: ["one warning"],
          work_units: 3,
        };
        return {
          cards: model.buildFileDetailCards(scan, ["LSV", "CV"]),
          detailView: model.buildFileDetailView(scan, ["LSV", "CV"]),
          summary: model.buildSummary(scan, ["LSV", "CV"]),
        };
        """,
    )

    assert payload["cards"][0]["dtype"] == "LSV"
    assert payload["cards"][0]["matched"] == 2
    assert payload["cards"][0]["ok"] is True
    assert payload["cards"][0]["rule"] == "prefix / LSV"
    assert payload["cards"][0]["examples"] == ["D:/data/one.txt", "D:/data/two.txt", "D:/data/three.txt"]
    assert payload["cards"][1]["ok"] is False
    assert payload["cards"][1]["rule"] == "regex / ^CV"

    assert payload["detailView"]["metrics"] == [
        {"labelKey": "preflight_detail_matched_files", "value": 2},
        {"labelKey": "preflight_text_files", "value": 9},
        {"labelKey": "preflight_work_units", "value": 3},
    ]
    assert payload["detailView"]["warnings"] == ["one warning"]
    assert payload["detailView"]["irPairings"] == [
        {
            "candidates": [],
            "eisFile": "D:/data/EIS_one.txt",
            "lsvFile": "D:/data/LSV_one.txt",
            "message": "matched",
            "method": "auto",
            "ok": True,
            "scope": "same_dir",
            "source": "eis",
            "status": "matched",
            "statusLabelKey": "preflight_ir_matched",
        }
    ]

    assert payload["summary"]["counts"] == [
        {"dtype": "LSV", "label": "LSV", "matched": 2},
        {"dtype": "CV", "label": "CV", "matched": 0},
    ]
    assert payload["summary"]["textFiles"] == 9
    assert payload["summary"]["warnings"] == ["one warning"]
    assert payload["summary"]["workUnits"] == 3


def test_preflight_model_uses_schema_module_labels_and_order() -> None:
    payload = _node_json(
        "preflight_model.js",
        """
        const model = window.ElectrochemPreflightModel;
        const scan = {
          by_type: {
            COUPLED: { match: "product_table", matched: 1 },
            LSV: { examples: ["D:/data/LSV_1.txt"], match: "prefix", matched: 2, prefix: "LSV" },
          },
          text_files: 4,
          work_units: 1,
        };
        const modules = [
          { key: "COUPLED", display_name: "COUPLED/FE", input_kind: "product_table", aliases: ["FE"] },
          { key: "LSV", display_name: "LSV", input_kind: "data_files" },
        ];
        return {
          detail: model.buildFileDetailView(scan, ["FE", "LSV"], model.defaultTypes, modules),
          summary: model.buildSummary(scan, ["FE", "LSV"], modules),
        };
        """,
    )

    assert [(card["dtype"], card["label"], card["inputKind"], card["matched"]) for card in payload["detail"]["cards"]] == [
        ("COUPLED", "COUPLED/FE", "product_table", 1),
        ("LSV", "LSV", "data_files", 2),
    ]
    assert payload["summary"]["counts"] == [
        {"dtype": "COUPLED", "label": "COUPLED/FE", "matched": 1},
        {"dtype": "LSV", "label": "LSV", "matched": 2},
    ]


def test_project_compare_model_filters_and_sorts_samples() -> None:
    payload = _node_json(
        "project_compare_model.js",
        """
        const model = window.ElectrochemProjectCompareModel;
        const samples = [
          { sample_name: "beta", latest_time: "2026-01-01 10:00:00", overpotential_10: 200, potential_10: 0.5, tafel_slope: 70 },
          { sample_name: "alpha", latest_time: "2026-01-03 10:00:00", overpotential_10: 100, potential_10: 0.4 },
          { sample_name: "gamma", latest_time: "2026-01-02 10:00:00", potential_10: 0.3, tafel_slope: 60 },
        ];
        const names = (items) => items.map((item) => item.sample_name);
        return {
          etaDefault: names(model.filterSamples(samples, { onlyEta: true, sort: "eta" })),
          latest: names(model.filterSamples(samples, { sort: "latest" })),
          sample: names(model.filterSamples(samples, { sort: "sample" })),
          tafelOnly: names(model.filterSamples(samples, { onlyTafel: true, sort: "tafel" })),
        };
        """,
    )

    assert payload["etaDefault"] == ["alpha", "beta"]
    assert payload["latest"] == ["alpha", "gamma", "beta"]
    assert payload["sample"] == ["alpha", "beta", "gamma"]
    assert payload["tafelOnly"] == ["gamma", "beta"]


def test_project_compare_model_syncs_selected_samples() -> None:
    payload = _node_json(
        "project_compare_model.js",
        """
        const model = window.ElectrochemProjectCompareModel;
        const samples = [
          { sample_name: "A" },
          { sample_name: "B" },
          { sample_name: "C" },
        ];
        return {
          defaulted: model.syncSelectedSamples(samples, ["stale"], 2),
          empty: model.syncSelectedSamples([], ["A"], 2),
          kept: model.syncSelectedSamples(samples, ["B"], 2),
        };
        """,
    )

    assert payload["defaulted"]["clearPlot"] is True
    assert payload["defaulted"]["selectedSamples"] == ["A", "B"]
    assert payload["empty"] == {"clearPlot": True, "selectedSamples": [], "visibleNames": []}
    assert payload["kept"]["clearPlot"] is False
    assert payload["kept"]["selectedSamples"] == ["B"]


def test_project_compare_model_selects_target_current_by_metric() -> None:
    payload = _node_json(
        "project_compare_model.js",
        """
        const model = window.ElectrochemProjectCompareModel;
        const state = {
          overpotential_target_currents: [20],
          potential_target_currents: [5, 10],
          target_currents: [1],
        };
        return {
          none: model.selectTargetCurrent([], "10", 10),
          potential: model.availableTargetCurrents(state, "potential_at_target"),
          preferred: model.selectTargetCurrent([5, "10", 10, 0, "bad"], "7", 10),
          preserved: model.selectTargetCurrent([5, 10], "5", 10),
          target: model.availableTargetCurrents(state, "tafel_slope"),
        };
        """,
    )

    assert payload["potential"] == [5, 10]
    assert payload["target"] == [1]
    assert payload["preferred"] == {"options": [5, 10], "value": "10"}
    assert payload["preserved"] == {"options": [5, 10], "value": "5"}
    assert payload["none"] == {"options": [], "value": ""}


def test_process_result_model_builds_result_view() -> None:
    payload = _node_json(
        "process_result_model.js",
        """
        const model = window.ElectrochemProcessResultModel;
        return model.buildResultView({
          data_types: ["LSV", "CV"],
          processing: {
            generated_files: 2,
            matched_files: 3,
            output_dir: "D:/out",
            output_files: ["D:/out/summary.json", "D:/out/plot.png"],
            skipped_files: 1,
          },
          quality_summary: {
            failed: 0,
            nested: { a: 1 },
            passed: 3,
            skipped: 2,
            total_files: 3,
            warnings: 1,
          },
          skipped_errors: [
            { error: "bad columns", file: "D:/raw/bad.txt", type: "LSV" },
            { error: "empty", file: "D:/raw/empty.txt", type: "CV" },
          ],
          summary: "Done",
        });
        """,
    )

    assert payload["summary"] == "Done"
    assert payload["dataTypes"] == ["LSV", "CV"]
    assert payload["outputFiles"] == [
        {"fileName": "summary.json", "path": "D:/out/summary.json"},
        {"fileName": "plot.png", "path": "D:/out/plot.png"},
    ]
    assert payload["qualityItems"][:8] == [
        {"labelKey": "result_matched_files", "value": 3},
        {"labelKey": "result_generated_files", "value": 2},
        {"labelKey": "result_skipped_count", "value": 1},
        {"labelKey": "result_output_dir", "value": "D:/out"},
        {"labelKey": "result_quality_total", "value": 3},
        {"labelKey": "result_quality_passed", "value": 3},
        {"labelKey": "result_quality_failed", "value": 0},
        {"labelKey": "result_quality_warnings", "value": 1},
    ]
    assert payload["qualityItems"][8] == {"labelKey": "result_skipped_count", "value": 2}
    assert payload["qualityItems"][9] == {"label": "nested", "value": '{"a":1}'}
    assert payload["skippedErrors"] == [
        {"error": "bad columns", "fileName": "bad.txt", "type": "LSV"},
        {"error": "empty", "fileName": "empty.txt", "type": "CV"},
    ]


def test_process_result_model_builds_history_result_with_metric_limit() -> None:
    payload = _node_json(
        "process_result_model.js",
        """
        const model = window.ElectrochemProcessResultModel;
        const record = {
          file_name: "sample.txt",
          output_files: [],
          project_name: "demo",
          results: {
            a: 1,
            b: 2,
            c: 3,
            d: 4,
            e: 5,
            f: 6,
            g: 7,
            h: 8,
            i: 9,
            nested: { ignored: true },
          },
          status: "success",
          summary_path: "D:/out/summary.json",
          timestamp: "2026-06-02 10:00:00",
          type: "lsv",
        };
        return model.buildResultFromHistoryRecord(record, "History record");
        """,
    )

    assert payload["summary"] == "History record: sample.txt"
    assert payload["data_type"] == "LSV"
    assert payload["data_types"] == ["LSV"]
    assert payload["processing"] == {"output_files": ["D:/out/summary.json"]}
    assert payload["quality_summary"]["project"] == "demo"
    assert payload["quality_summary"]["status"] == "success"
    assert payload["quality_summary"]["timestamp"] == "2026-06-02 10:00:00"
    assert list(payload["quality_summary"].keys()) == [
        "status",
        "project",
        "timestamp",
        "a",
        "b",
        "c",
        "d",
        "e",
        "f",
        "g",
        "h",
    ]


def test_process_result_page_renders_result_error_and_history_list() -> None:
    payload = _node_json(
        "process_result_page.js",
        """
        const page = window.ElectrochemProcessResultPage;
        function makeClassList(initial = []) {
          const values = new Set(initial);
          return {
            add: (...items) => items.forEach((item) => values.add(item)),
            contains: (item) => values.has(item),
            remove: (...items) => items.forEach((item) => values.delete(item)),
            toggle: (item, force) => {
              if (force === undefined ? !values.has(item) : force) values.add(item);
              else values.delete(item);
            },
            values,
          };
        }
        function makeEl(initialClasses = []) {
          return {
            classList: makeClassList(initialClasses),
            dataset: {},
            innerHTML: "",
            querySelectorAll: () => [],
            textContent: "",
          };
        }
        let historyItems = [];
        const historyList = makeEl();
        Object.defineProperty(historyList, "innerHTML", {
          get: function () { return this._innerHTML || ""; },
          set: function (value) {
            this._innerHTML = value;
            historyItems = Array.from(value.matchAll(/data-index="([^"]+)" data-key="([^"]*)"/g)).map((match) => {
              const item = makeEl();
              item.dataset = { index: match[1], key: match[2] };
              item.addEventListener = (_name, fn) => { item.click = fn; };
              return item;
            });
          },
        });
        historyList.querySelectorAll = (selector) => selector === ".history-item" ? historyItems : [];
        const elements = {
          "history-list": historyList,
          "proc-result-error": makeEl(),
          "proc-result-error-wrap": makeEl(["hidden"]),
          "proc-result-files": makeEl(),
          "proc-result-panel": makeEl(["hidden"]),
          "proc-result-quality": makeEl(),
          "proc-result-skipped": makeEl(),
          "proc-result-skipped-wrap": makeEl(["hidden"]),
          "proc-result-summary": makeEl(),
          "proc-result-types": makeEl(),
        };
        const tabs = [];
        const steps = [];
        const boundTargets = [];
        let selectedIndex = "";
        const ctx = {
          bindFileActions: (target) => boundTargets.push(target.innerHTML),
          byId: (id) => elements[id] || null,
          escapeHtml: (text) => String(text || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;"),
          onSelect: (index) => { selectedIndex = index; },
          processResultModel: {
            buildResultFromHistoryRecord: (record, label) => ({ summary: `${label}: ${record.sample_name}` }),
            buildResultView: () => ({
              dataTypes: ["LSV", "CV"],
              outputFiles: [{ fileName: "plot.png", path: "D:/out/plot.png" }],
              qualityItems: [{ labelKey: "result_quality_total", value: 2 }],
              skippedErrors: [{ error: "bad columns", fileName: "bad.txt", type: "LSV" }],
              summary: "Done",
            }),
          },
          setResultTab: (tab) => tabs.push(tab),
          t: (key) => ({
            btn_copy_path: "Copy",
            btn_open_dir: "Open dir",
            btn_open_file: "Open",
            no_history: "No history",
            proc_failed: "Failed",
            result_empty: "No result",
            result_from_history: "History",
            result_quality_total: "Total",
          }[key] || key),
          updateProcessStepState: () => steps.push("updated"),
        };

        const resultState = page.renderResult(ctx, {});
        const resultSnapshot = {
          filesAction: elements["proc-result-files"].classList.contains("action-list"),
          filesHtml: elements["proc-result-files"].innerHTML,
          panelHidden: elements["proc-result-panel"].classList.contains("hidden"),
          qualityHtml: elements["proc-result-quality"].innerHTML,
          skippedHidden: elements["proc-result-skipped-wrap"].classList.contains("hidden"),
          summary: elements["proc-result-summary"].textContent,
          types: elements["proc-result-types"].textContent,
        };
        const historyKey = page.historyRecordKey({ file_name: "sample.txt", timestamp: "2026-06-02", type: "lsv" });
        const exactHistoryKey = page.historyRecordKey({
          file_name: "sample.txt",
          record_key: "2026-06-02|lsv|sample.txt|run-1",
          timestamp: "2026-06-02",
          type: "lsv",
        });
        const historyResult = page.buildResultFromHistoryRecord(ctx, { sample_name: "sample-a" });
        const historyView = page.renderHistory({ ...ctx, selectedKey: historyKey }, [
          { file_name: "sample.txt", timestamp: "2026-06-02", type: "lsv" },
          { file_name: "cv.txt", timestamp: "2026-06-03", type: "cv" },
        ]);
        historyItems[1].click();
        page.setActiveHistoryItem(ctx, historyItems[1].dataset.key);
        const errorState = page.renderError(ctx, "bad input");
        const errorSnapshot = {
          errorHidden: elements["proc-result-error-wrap"].classList.contains("hidden"),
          errorText: elements["proc-result-error"].textContent,
          summary: elements["proc-result-summary"].textContent,
        };
        const placeholderState = page.renderPlaceholder(ctx);
        return {
          activeAfterSet: historyItems.map((item) => item.classList.contains("active")),
          boundTargets: boundTargets.length,
          errorSnapshot,
          errorState,
          exactHistoryKey,
          historyCount: historyView.records.length,
          historyHtml: historyList.innerHTML,
          historyKey,
          historyResult,
          placeholderState,
          resultSnapshot,
          resultState,
          selectedIndex,
          tabs,
          updateCount: steps.length,
        };
        """,
    )

    assert payload["resultState"]["hasProcessResult"] is True
    assert payload["resultState"]["processRunState"] == "complete"
    assert payload["resultSnapshot"]["summary"] == "Done"
    assert payload["resultSnapshot"]["types"] == "LSV, CV"
    assert payload["resultSnapshot"]["filesAction"] is True
    assert "plot.png" in payload["resultSnapshot"]["filesHtml"]
    assert payload["resultSnapshot"]["panelHidden"] is False
    assert payload["resultSnapshot"]["qualityHtml"] == "<li>Total: 2</li>"
    assert payload["resultSnapshot"]["skippedHidden"] is False
    assert payload["boundTargets"] == 1
    assert payload["historyKey"] == "2026-06-02|lsv|sample.txt"
    assert payload["exactHistoryKey"] == "2026-06-02|lsv|sample.txt|run-1"
    assert payload["historyResult"] == {"summary": "History: sample-a"}
    assert payload["historyCount"] == 2
    assert "sample.txt" in payload["historyHtml"]
    assert payload["selectedIndex"] == "1"
    assert payload["activeAfterSet"] == [False, True]
    assert payload["errorState"] == {"hasProcessResult": True, "processRunState": "issue"}
    assert payload["errorSnapshot"] == {
        "errorHidden": False,
        "errorText": "bad input",
        "summary": "Failed",
    }
    assert payload["placeholderState"] == {"hasProcessResult": False, "processRunState": "pending"}
    assert payload["tabs"] == ["current", "current"]
    assert payload["updateCount"] == 3


def test_assistant_api_exposes_background_job_submit_poll_and_cancel() -> None:
    payload = _node_json(
        "assistant_api.js",
        """
        const calls = [];
        window.fetch = async (url, options) => {
          calls.push({ url, method: options && options.method || "GET", body: options && options.body || null });
          return { ok: true };
        };
        const api = window.ElectrochemAssistantApi;
        await api.submitMessageJob({ message: "hello" });
        await api.getMessageJob("job/a");
        await api.cancelMessageJob("job/a");
        const form = { marker: "form" };
        await api.submitMessageJobForm(form);
        return { calls, hasForm: calls[3].body === form };
        """,
    )

    assert payload["calls"][0]["url"] == "/api/v1/agent/jobs"
    assert payload["calls"][0]["method"] == "POST"
    assert payload["calls"][1]["url"] == "/api/v1/agent/jobs/job%2Fa"
    assert payload["calls"][2]["url"] == "/api/v1/agent/jobs/job%2Fa/cancel"
    assert payload["calls"][2]["method"] == "POST"
    assert payload["calls"][3]["url"] == "/api/v1/agent/jobs"
    assert payload["hasForm"] is True


def test_project_api_exposes_storage_summary_cleanup_and_safe_delete_defaults() -> None:
    payload = _node_json(
        "project_api.js",
        """
        const calls = [];
        window.fetch = async (url, options) => {
          calls.push({ url, method: options && options.method || "GET", body: options && options.body || null });
          return { ok: true };
        };
        const api = window.ElectrochemProjectApi;
        await api.storageSummary();
        await api.cleanupStorage();
        await api.deleteHistory("history/a");
        await api.permanentlyDeleteProject("project/a");
        await api.updateSample("project/a", "sample/a", { note: "KOH", tags: ["control"] });
        return { calls };
        """,
    )

    calls = payload["calls"]
    assert calls[0] == {"url": "/api/v1/storage", "method": "GET", "body": None}
    assert calls[1]["url"] == "/api/v1/storage/cleanup"
    assert calls[1]["method"] == "POST"
    assert calls[2]["url"] == "/api/v1/history/delete"
    assert '"delete_artifacts":true' in calls[2]["body"]
    assert calls[3]["url"] == "/api/v1/projects/project%2Fa/delete-permanent"
    assert '"delete_artifacts":true' in calls[3]["body"]
    assert calls[4]["url"] == "/api/v1/projects/project%2Fa/samples/sample%2Fa/update"
    assert calls[4]["method"] == "POST"
    assert '"note":"KOH"' in calls[4]["body"]
