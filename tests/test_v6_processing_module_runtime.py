from __future__ import annotations

import pytest

from conftest import _write_tsv, make_ecsa_rows, make_lsv_rows
from electrochem_v6.core.processing_module_contract import ModuleRunContext, ModuleRunResult
from electrochem_v6.core.processing_module_orchestrator import run_module_pipeline
from electrochem_v6.core.processing_module_runtime import (
    ModuleRegistrationError,
    ModuleRunError,
    ModuleValidationError,
    ProcessingModuleRegistry,
    build_default_module_registry,
)
from electrochem_v6.core.processing_registry import ProcessingModuleSpec
from electrochem_v6.core.processing_result_models import MetricValue, ProcessingResult


class DemoModule:
    spec = ProcessingModuleSpec(
        "DEMO",
        "demo_enabled",
        "demo_match",
        "demo_prefix",
        "prefix",
        "DEMO",
        display_name="Demo",
        summary="Demo extension module",
        capabilities=("demo_metric",),
        result_kinds=("history_record",),
        aliases=("D",),
        parameter_keys=("ok",),
    )

    def detect_files(self, context):
        return [f"{context.folder_path}/DEMO_sample.txt"]

    def validate_params(self, context):
        return [] if context.params.get("ok") else ["ok is required"]

    def run(self, context, files):
        return ModuleRunResult(
            data_type="DEMO",
            results=(
                ProcessingResult(
                    data_type="DEMO",
                    sample_name="sample",
                    metrics=(MetricValue(key="demo_metric", value=len(files)),),
                ),
            ),
            artifacts=("demo.png",),
            messages=("processed",),
        )


def test_default_registry_exposes_builtin_direct_modules():
    registry = build_default_module_registry()
    catalog = registry.catalog()

    assert catalog["schema_version"] == "1.2"
    assert catalog["execution"] == "registry_orchestrated"
    assert catalog["supported_data_types"] == ["LSV", "CV", "EIS", "ECSA", "COUPLED"]
    modules = {item["key"]: item for item in catalog["modules"]}
    assert modules["LSV"]["origin"] == "builtin"
    assert modules["LSV"]["runner"] == {"kind": "module", "available": True}
    assert modules["LSV"]["parameter_keys"] == []
    assert modules["EIS"]["runner"] == {"kind": "module", "available": True}
    assert modules["ECSA"]["runner"] == {"kind": "module", "available": True}
    assert modules["COUPLED"]["runner"] == {"kind": "module", "available": True}
    assert modules["COUPLED"]["aliases"] == ["FE", "FARADAIC", "FARADAIC_EFFICIENCY", "SELECTIVITY"]


def test_registry_registers_extension_module_and_runs_contract():
    registry = ProcessingModuleRegistry()
    entry = registry.register_module(DemoModule())

    assert entry.key == "DEMO"
    assert registry.normalize_type("d") == "DEMO"
    assert registry.validate_data_types(["D", "DEMO"]) == ["DEMO"]
    assert entry.to_descriptor()["parameter_keys"] == ["ok"]

    context = ModuleRunContext(folder_path="D:/data", params={"ok": True}, run_id="run-1")
    preflight = registry.preflight_module("D", context)
    assert preflight["status"] == "pass"
    assert preflight["matched"] == 1

    result = registry.run_module("DEMO", context)
    payload = result.to_dict()
    assert payload["data_type"] == "DEMO"
    assert payload["results"][0]["metrics"][0]["value"] == 1
    assert payload["artifacts"] == ["demo.png"]


def test_orchestrator_uses_explicit_files_without_running_detection(tmp_path):
    captured: list[str] = []

    class ExplicitDemoModule(DemoModule):
        def detect_files(self, context):
            raise AssertionError("automatic detection must not run for explicit input files")

        def run(self, context, files):
            captured.extend(str(item) for item in files)
            return super().run(context, files)

    selected = tmp_path / "chosen.txt"
    selected.write_text("0 0\n", encoding="utf-8")
    registry = ProcessingModuleRegistry()
    registry.register_module(ExplicitDemoModule())

    result = run_module_pipeline(
        str(tmp_path),
        {
            "ok": True,
            "output_dir": str(tmp_path / "out"),
            "_selected_files_by_type": {"DEMO": [str(selected)]},
        },
        data_types=["DEMO"],
        registry=registry,
    )

    assert captured == [str(selected)]
    assert result.get("matched_counts", {}).get("DEMO") == 1


def test_registry_rejects_duplicate_keys_and_alias_conflicts():
    registry = ProcessingModuleRegistry()
    registry.register_module(DemoModule())

    with pytest.raises(ModuleRegistrationError):
        registry.register_module(DemoModule())

    conflict = ProcessingModuleSpec("OTHER", "other_enabled", aliases=("DEMO",))
    with pytest.raises(ModuleRegistrationError):
        registry.register_spec(conflict)

    with pytest.raises(ModuleRegistrationError, match="parameter_keys"):
        registry.register_spec(
            ProcessingModuleSpec("BAD_PARAM", "bad_param_enabled", parameter_keys=("_private",))
        )


def test_registry_reports_validation_errors_before_running():
    registry = ProcessingModuleRegistry()
    registry.register_module(DemoModule())
    context = ModuleRunContext(folder_path="D:/data", params={"ok": False})

    preflight = registry.preflight_module("DEMO", context)
    assert preflight["status"] == "check"
    assert preflight["param_errors"] == ["ok is required"]

    with pytest.raises(ModuleValidationError) as exc:
        registry.run_module("DEMO", context)
    assert exc.value.errors == ("ok is required",)


def test_metadata_only_spec_is_discoverable_but_not_directly_runnable():
    registry = ProcessingModuleRegistry()
    registry.register_spec(ProcessingModuleSpec("META", "meta_enabled"), origin="test", runner="metadata")

    descriptor = registry.catalog()["modules"][0]
    assert descriptor["key"] == "META"
    assert descriptor["runner"] == {"kind": "metadata", "available": False}

    with pytest.raises(ModuleRunError):
        registry.get_module("META")


def test_default_registry_runs_real_coupled_fe_module(tmp_path):
    products = tmp_path / "products.csv"
    products.write_text(
        "sample,product,product_moles,n,charge\n"
        "sample-a,H2,0.000002,2,1.0\n"
        "sample-a,CO,0.000001,2,1.0\n",
        encoding="utf-8",
    )
    context = ModuleRunContext(
        folder_path=str(tmp_path),
        params={"coupled_products_file": str(products)},
        project_id="project-1",
        run_id="run-1",
        output_dir=str(tmp_path / "out"),
    )
    registry = build_default_module_registry()

    preflight = registry.preflight_module("FE", context)
    assert preflight["status"] == "pass"
    assert preflight["matched"] == 1

    result = registry.run_module("COUPLED", context)
    payload = result.to_dict()
    assert payload["data_type"] == "COUPLED"
    assert payload["metadata"]["rows"] == 2
    assert "coupled.faradaic_efficiency" in payload["metadata"]["formula_keys"]
    assert payload["artifacts"][0].endswith("coupled_results.csv")
    metric_keys = {metric["key"] for item in payload["results"] for metric in item["metrics"]}
    assert "faradaic_efficiency_pct" in metric_keys


def test_default_registry_runs_direct_cv_module(tmp_path):
    data_file = tmp_path / "CV_demo.txt"
    data_file.write_text(
        "Potential Current\n"
        "0.0 0.0000\n"
        "0.2 0.0004\n"
        "0.4 0.0010\n"
        "0.6 0.0003\n"
        "0.8 -0.0002\n"
        "1.0 -0.0005\n",
        encoding="utf-8",
    )
    context = ModuleRunContext(
        folder_path=str(tmp_path),
        params={
            "cv_match": "prefix",
            "cv_prefix": "CV",
            "cv_quality_check": False,
            "cv_scan_rate_v_s": 0.05,
        },
        run_id="run-1",
        output_dir=str(tmp_path / "out"),
    )
    registry = build_default_module_registry()

    preflight = registry.preflight_module("CV", context)
    assert preflight["status"] == "pass"
    assert preflight["matched"] == 1

    result = registry.run_module("CV", context)
    payload = result.to_dict()

    assert payload["data_type"] == "CV"
    assert payload["metadata"]["module"] == "direct_cv"
    assert payload["metadata"]["processed_files"] == 1
    assert any(str(item).endswith("_CV.png") for item in payload["artifacts"])
    metric_keys = {metric["key"] for item in payload["results"] for metric in item["metrics"]}
    assert {"data_points", "potential_min_v", "current_max_mA", "charge_mC"}.issubset(metric_keys)


def test_default_registry_runs_direct_lsv_module(tmp_path):
    data_file = _write_tsv(tmp_path / "LSV_demo.txt", make_lsv_rows(n=80))
    context = ModuleRunContext(
        folder_path=str(tmp_path),
        params={
            "lsv_match": "prefix",
            "lsv_prefix": "LSV",
            "lsv_target_current": "1.0",
            "lsv_quality_check": False,
            "plot_grid": False,
        },
        run_id="run-1",
        output_dir=str(tmp_path / "out"),
    )
    registry = build_default_module_registry()

    preflight = registry.preflight_module("LSV", context)
    assert preflight["status"] == "pass"
    assert preflight["matched"] == 1
    assert preflight["files"] == [str(data_file)]

    result = registry.run_module("LSV", context)
    payload = result.to_dict()

    assert payload["data_type"] == "LSV"
    assert payload["metadata"]["module"] == "direct_lsv"
    assert payload["metadata"]["processed_files"] == 1
    assert any(str(item).endswith("_LSV.png") for item in payload["artifacts"])
    metric_keys = {metric["key"] for item in payload["results"] for metric in item["metrics"]}
    assert "potential_at_1_0ma_cm2" in metric_keys


def test_default_registry_runs_direct_eis_module(tmp_path):
    data_file = tmp_path / "EIS_demo.txt"
    data_file.write_text(
        "Freq Zreal Zimag\n"
        "100000 2.0 -0.5\n"
        "10000 2.5 -0.8\n"
        "1000 3.0 -1.1\n"
        "100 3.5 -1.4\n"
        "10 4.0 -1.7\n"
        "1 4.5 -2.0\n",
        encoding="utf-8",
    )
    context = ModuleRunContext(
        folder_path=str(tmp_path),
        params={"eis_match": "prefix", "eis_prefix": "EIS", "plot_nyquist": True, "plot_bode": False},
        run_id="run-1",
        output_dir=str(tmp_path / "out"),
    )
    registry = build_default_module_registry()

    preflight = registry.preflight_module("EIS", context)
    assert preflight["status"] == "pass"
    assert preflight["matched"] == 1

    result = registry.run_module("EIS", context)
    payload = result.to_dict()

    assert payload["data_type"] == "EIS"
    assert payload["metadata"]["module"] == "direct_eis"
    assert payload["metadata"]["processed_files"] == 1
    assert any(str(item).endswith("_EIS_Nyquist.png") for item in payload["artifacts"])
    metric_keys = {metric["key"] for item in payload["results"] for metric in item["metrics"]}
    assert {"data_points", "frequency_min_hz", "frequency_max_hz"}.issubset(metric_keys)


def test_default_registry_runs_direct_ecsa_module(tmp_path):
    sample_dir = tmp_path / "sample_A"
    sample_dir.mkdir()
    for rate_mvs in (20, 40, 60):
        rows = make_ecsa_rows(scan_rate_Vs=rate_mvs / 1000.0, Ev=0.10)
        _write_tsv(sample_dir / f"ECSA{rate_mvs}.txt", rows)

    context = ModuleRunContext(
        folder_path=str(tmp_path),
        params={
            "ecsa_match": "prefix",
            "ecsa_prefix": "ECSA",
            "ecsa_ev": 0.10,
            "ecsa_cs_unit": "uF/cm2",
            "area": 1.0,
        },
        run_id="run-1",
        output_dir=str(tmp_path / "out"),
    )
    registry = build_default_module_registry()

    preflight = registry.preflight_module("ECSA", context)
    assert preflight["status"] == "pass"
    assert preflight["matched"] == 3

    result = registry.run_module("ECSA", context)
    payload = result.to_dict()

    assert payload["data_type"] == "ECSA"
    assert payload["metadata"]["module"] == "direct_ecsa"
    assert payload["metadata"]["processed_samples"] == 1
    assert any(str(item).endswith("_ECSA.png") for item in payload["artifacts"])
    metric_keys = {metric["key"] for item in payload["results"] for metric in item["metrics"]}
    assert {"n_points", "cdl_mfcm2", "ecsa_cm2", "rf"}.issubset(metric_keys)
