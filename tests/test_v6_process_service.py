import io
import json
import os
import zipfile
from pathlib import Path

import electrochem_v6.core.process_service as process_service
import electrochem_v6.server.routes_post as routes_post
from electrochem_v6.config import APP_VERSION


def _write_eis_file(path):
    lines = ["Freq Zreal Zimag\n"]
    for idx, freq in enumerate([100000, 50000, 10000, 1000, 100, 10, 1]):
        z_real = 2.0 + idx * 0.5
        z_imag = -0.5 - idx * 0.2
        lines.append(f"{freq} {z_real:.6f} {z_imag:.6f}\n")
    path.write_text("".join(lines), encoding="utf-8")


def _write_cv_file(path):
    lines = ["Potential Current\n"]
    for potential, current in [(0.0, 0.0), (0.2, 0.0004), (0.4, 0.0010), (0.6, 0.0003), (0.8, -0.0002)]:
        lines.append(f"{potential:.6f} {current:.8f}\n")
    path.write_text("".join(lines), encoding="utf-8")


def _zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


class _UploadItem:
    def __init__(self, payload):
        self._payload = payload

    def get_payload(self, decode=False):
        return self._payload

    def get_filename(self):
        return "demo.zip"


class _UploadHandler:
    MAX_UPLOAD_FILE_BYTES = 100 * 1024 * 1024
    MAX_ZIP_FILES = 100
    MAX_ZIP_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


def test_build_gui_vars_uses_registry_defaults_and_conversions():
    gui_vars = process_service._build_gui_vars(
        ["LSV", "ECSA", "COUPLED"],
        {
            "params": {
                "lsv_target_current": "",
                "ecsa_last_n": "3",
                "ecsa_use_abs_delta": "false",
                "coupled_results_csv_filename": "",
            }
        },
    )

    assert gui_vars["lsv_target_current"] == "10,100"
    assert gui_vars["tafel_range"] == "1-10"
    assert gui_vars["tafel_enabled"] is False
    assert gui_vars["ir_eis_match"] == "prefix"
    assert gui_vars["font_size"] == 12
    assert gui_vars["lsv_quality_min_points_issue"] == 20
    assert gui_vars["ecsa_last_n"] == 3
    assert gui_vars["ecsa_use_abs_delta"] is False
    assert gui_vars["coupled_results_csv_filename"] == "coupled_results.csv"
    assert "cv_match" not in gui_vars
    assert "eis_match" not in gui_vars


def test_build_gui_vars_requires_explicit_tafel_enable_flag():
    disabled = process_service._build_gui_vars(["LSV"], {"params": {"tafel_range": "2-8"}})
    enabled = process_service._build_gui_vars(
        ["LSV"],
        {"params": {"tafel_range": "2-8", "tafel_enabled": True}},
    )

    assert disabled["tafel_range"] == "2-8"
    assert disabled["tafel_enabled"] is False
    assert enabled["tafel_enabled"] is True


def test_rhe_conversion_requires_ph_and_validates_temperature_bounds():
    missing_ph = process_service._validate_payload(
        {"params": {"potential_mode": "formula_rhe"}},
        ["LSV"],
    )
    too_hot = process_service._validate_payload(
        {
            "params": {
                "potential_mode": "formula_rhe",
                "rhe_ph": 7.0,
                "rhe_temperature_c": 101.0,
            }
        },
        ["LSV"],
    )

    assert missing_ph == "pH 不能为空 (rhe_ph)"
    assert too_hot is not None and "rhe_temperature_c" in too_hot


def test_process_folder_rewrites_summary_with_v6_version(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    folder = tmp_path / "data"
    folder.mkdir(parents=True, exist_ok=True)
    summary_path = folder / "summary.json"
    lsv_csv = folder / "LSV_results.csv"
    lsv_csv.write_text("Sample_Name,File_Name\n", encoding="utf-8")
    (folder / "LSV_demo.txt").write_text("Potential Current\n0 0\n1 0.001\n2 0.002\n", encoding="utf-8")
    summary_path.write_text(
        json.dumps({"version": "3.0.4", "timestamp": "2025-01-01 00:00:00"}, ensure_ascii=False),
        encoding="utf-8",
    )

    def _fake_run_modules(_folder_path, _gui_vars):
        return {
            "summary_path": str(summary_path),
            "lsv_csv": str(lsv_csv),
            "quality_summary": {"total_files": 1, "passed": 1, "failed": 0, "warnings": 0},
            "messages": ["not_a_path"],
        }

    monkeypatch.setattr(process_service, "_run_selected_modules", _fake_run_modules)
    monkeypatch.setattr(process_service, "attach_run_outputs", lambda **_kwargs: {"status": "success", "updated": 0})

    payload = {"folder_path": str(folder), "data_types": ["LSV"], "params": {"font_size": 12}}
    result = process_service.process_folder(payload)

    assert result.get("status") == "success"
    body = result.get("result", {})
    assert body.get("app_version") == APP_VERSION
    assert body.get("summary_path") == str(summary_path)
    assert isinstance(body.get("summary_json"), dict)
    manifest = body.get("manifest") or {}
    assert manifest.get("manifest_schema_version") == "1.1"
    assert manifest.get("run", {}).get("data_types") == ["LSV"]
    assert manifest.get("parameters", {}).get("font_size") == 12
    manifest_path = manifest.get("outputs", {}).get("run_manifest_path")
    assert manifest_path
    assert os.path.exists(manifest_path)
    assert manifest_path in body.get("processing", {}).get("output_files", [])
    run_report_path = manifest.get("outputs", {}).get("run_report_path")
    assert run_report_path
    assert os.path.exists(run_report_path)
    assert run_report_path in body.get("processing", {}).get("output_files", [])
    assert "ElectroChem Run Report" in open(run_report_path, encoding="utf-8").read()
    run_report_html_path = manifest.get("outputs", {}).get("run_report_html_path")
    assert run_report_html_path
    assert os.path.exists(run_report_html_path)
    assert run_report_html_path in body.get("processing", {}).get("output_files", [])
    assert "ElectroChem Run Report" in open(run_report_html_path, encoding="utf-8").read()

    saved = json.loads(summary_path.read_text(encoding="utf-8"))
    assert saved.get("version") == APP_VERSION
    assert saved.get("pipeline_version") == "3.0.4"
    assert saved.get("summary_schema_version") == "1.0"
    assert saved.get("data_types") == ["LSV"]
    assert isinstance(saved.get("history"), dict)
    assert isinstance(saved.get("processing", {}).get("output_files"), list)


def test_collect_output_files_includes_unified_processing_results(tmp_path):
    result_csv = tmp_path / "processing_results.csv"
    result_csv.write_text("sample_name,data_type\n", encoding="utf-8")

    output_files = process_service._collect_output_files({"processing_results_csv": str(result_csv)})

    assert output_files == [str(result_csv)]


def test_process_folder_reports_eis_png_output(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    folder = tmp_path / "eis_only"
    folder.mkdir(parents=True, exist_ok=True)
    _write_eis_file(folder / "EIS_demo.txt")
    monkeypatch.setattr(process_service, "attach_run_outputs", lambda **_kwargs: {"status": "success", "updated": 0})

    result = process_service.process_folder({
        "folder_path": str(folder),
        "data_types": ["EIS"],
        "params": {
            "eis_match": "prefix",
            "eis_prefix": "EIS",
            "plot_nyquist": True,
            "plot_bode": False,
        },
    })

    assert result.get("status") == "success"
    output_files = result.get("result", {}).get("processing", {}).get("output_files", [])
    assert any(str(item).endswith("_EIS_Nyquist.png") for item in output_files)
    assert any(str(item).endswith("processing_results.csv") for item in output_files)
    assert any(str(item).endswith("summary.json") for item in output_files)

    summary_path = Path(result["result"]["summary_path"])
    assert summary_path.parent.parent.name == "electrochem_outputs"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary.get("runtime") == "module_registry"
    assert summary.get("module_runs", [{}])[0].get("data_type") == "EIS"
    summary_outputs = summary.get("processing", {}).get("output_files", [])
    assert any(str(item).endswith("_EIS_Nyquist.png") for item in summary_outputs)
    assert summary.get("processing_results", {}).get("results") == 1


def test_process_folder_reports_cv_normalized_output(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    folder = tmp_path / "cv_only"
    folder.mkdir(parents=True, exist_ok=True)
    _write_cv_file(folder / "CV_demo.txt")
    monkeypatch.setattr(process_service, "attach_run_outputs", lambda **_kwargs: {"status": "success", "updated": 0})

    result = process_service.process_folder({
        "folder_path": str(folder),
        "data_types": ["CV"],
        "params": {"cv_match": "prefix", "cv_prefix": "CV", "cv_quality_check": False},
    })

    assert result.get("status") == "success"
    output_files = result.get("result", {}).get("processing", {}).get("output_files", [])
    assert any(str(item).endswith("_CV.png") for item in output_files)
    assert any(str(item).endswith("processing_results.csv") for item in output_files)

    summary_path = Path(result["result"]["summary_path"])
    assert summary_path.parent.parent.name == "electrochem_outputs"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary.get("runtime") == "module_registry"
    assert summary.get("processing_results", {}).get("results") == 1


def test_process_service_preflights_and_runs_runtime_extension(tmp_path, monkeypatch):
    from electrochem_v6.core.processing_module_contract import ModuleRunResult
    from electrochem_v6.core.processing_module_runtime import get_processing_module_registry
    from electrochem_v6.core.processing_registry import ProcessingModuleSpec
    from electrochem_v6.core.processing_result_models import MetricValue, ProcessingResult

    class RuntimeDemoModule:
        spec = ProcessingModuleSpec(
            "RUNTIME_DEMO",
            "runtime_demo_enabled",
            display_name="Runtime demo",
            aliases=("RDEMO",),
            parameter_keys=("runtime_demo_scale",),
        )

        def detect_files(self, context):
            return tuple(str(item) for item in Path(context.folder_path).glob("RUNTIME_*.txt"))

        def validate_params(self, context):
            return [] if context.params.get("runtime_demo_scale") == 2 else ["scale must be 2"]

        def run(self, context, files):
            output_dir = Path(context.output_dir or context.folder_path)
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / "runtime_demo_results.csv"
            output_file.write_text("sample,demo_metric\nsample,1\n", encoding="utf-8")
            return ModuleRunResult(
                data_type="RUNTIME_DEMO",
                results=(
                    ProcessingResult(
                        data_type="RUNTIME_DEMO",
                        sample_name="sample",
                        metrics=(MetricValue(key="demo_metric", value=len(files)),),
                    ),
                ),
                artifacts=(str(output_file),),
            )

    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(process_service, "attach_run_outputs", lambda **_kwargs: {"status": "success"})
    folder = tmp_path / "extension"
    folder.mkdir()
    (folder / "RUNTIME_sample.txt").write_text("demo\n", encoding="utf-8")
    registry = get_processing_module_registry()
    registry.register_module(RuntimeDemoModule(), origin="test")
    try:
        undeclared = process_service.preflight_process_folder(
            {
                "folder_path": str(folder),
                "data_types": ["RDEMO"],
                "params": {"runtime_demo_typo": 2},
            }
        )
        assert undeclared.get("status") == "error"
        assert undeclared.get("message") == "不支持的处理参数: runtime_demo_typo"

        preflight = process_service.preflight_process_folder(
            {
                "folder_path": str(folder),
                "data_types": ["RDEMO"],
                "params": {"runtime_demo_scale": 2},
            }
        )
        assert preflight.get("status") == "success"
        assert preflight.get("data_types") == ["RUNTIME_DEMO"]
        assert preflight.get("preflight", {}).get("matched_counts", {}).get("RUNTIME_DEMO") == 1
        assert preflight.get("preflight", {}).get("runnable") is True

        result = process_service.process_folder(
            {
                "folder_path": str(folder),
                "data_types": ["RDEMO"],
                "params": {"runtime_demo_scale": 2},
            }
        )
        assert result.get("status") == "success"
        raw = result.get("result", {}).get("raw", {})
        assert raw.get("module_runs", [{}])[0].get("data_type") == "RUNTIME_DEMO"
        assert any(
            str(item).endswith("runtime_demo_results.csv")
            for item in result.get("result", {}).get("processing", {}).get("output_files", [])
        )
    finally:
        registry.unregister("RUNTIME_DEMO")


def test_process_service_rejects_unknown_parameter_in_preflight_and_run(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    folder = tmp_path / "unknown_parameter"
    folder.mkdir()
    payload = {
        "folder_path": str(folder),
        "data_types": ["LSV"],
        "params": {"lsv_prefx": "LSV"},
    }

    preflight = process_service.preflight_process_folder(payload)
    result = process_service.process_folder(payload)

    assert preflight.get("status") == "error"
    assert preflight.get("message") == "不支持的处理参数: lsv_prefx"
    assert result.get("status") == "error"
    assert result.get("message") == "不支持的处理参数: lsv_prefx"


def test_process_preflight_counts_recursive_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    folder = tmp_path / "nested"
    deep = folder / "a" / "b"
    deep.mkdir(parents=True, exist_ok=True)
    _write_eis_file(deep / "EIS_deep.txt")

    flat = process_service.preflight_process_folder({
        "folder_path": str(folder),
        "data_types": ["EIS"],
        "params": {"eis_match": "prefix", "eis_prefix": "EIS"},
    })
    assert flat.get("status") == "error" or flat.get("preflight", {}).get("selected_matched") == 0

    recursive = process_service.preflight_process_folder({
        "folder_path": str(folder),
        "data_types": ["EIS"],
        "recursive_scan": True,
        "params": {"eis_match": "prefix", "eis_prefix": "EIS"},
    })
    assert recursive.get("status") == "success"
    preflight = recursive.get("preflight", {})
    assert preflight.get("selected_matched") == 1
    assert preflight.get("matched_counts", {}).get("EIS") == 1
    assert preflight.get("runnable") is True
    assert preflight.get("checks", {}).get("runnable", {}).get("status") == "yes"


def test_process_folder_can_write_isolated_run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    folder = tmp_path / "isolated"
    folder.mkdir(parents=True, exist_ok=True)
    _write_eis_file(folder / "EIS_demo.txt")
    monkeypatch.setattr(process_service, "attach_run_outputs", lambda **_kwargs: {"status": "success", "updated": 0})

    result = process_service.process_folder({
        "folder_path": str(folder),
        "data_types": ["EIS"],
        "output_run_dir_enabled": True,
        "params": {"eis_match": "prefix", "eis_prefix": "EIS"},
    })

    assert result.get("status") == "success"
    processing = result.get("result", {}).get("processing", {})
    output_dir = processing.get("output_dir")
    assert output_dir
    assert "electrochem_outputs" in output_dir
    assert result.get("result", {}).get("summary_path", "").startswith(output_dir)
    assert any(str(item).startswith(output_dir) and str(item).endswith("_EIS_Nyquist.png") for item in processing.get("output_files", []))


def test_uploaded_zip_outputs_survive_temp_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(process_service, "attach_run_outputs", lambda **_kwargs: {"status": "success", "updated": 0})
    payload = _zip_bytes({"EIS_demo.txt": "Freq Zreal Zimag\n1000 2 -1\n100 3 -2\n10 4 -3\n1 5 -4\n"})

    result = routes_post._process_uploaded_zip(
        _UploadHandler(),
        {"data_type": "EIS", "params": json.dumps({"eis_match": "prefix", "eis_prefix": "EIS"})},
        {"file": _UploadItem(payload)},
    )

    assert result.get("status") == "success"
    processing = result.get("result", {}).get("processing", {})
    output_dir = processing.get("output_dir")
    assert output_dir
    assert output_dir.startswith(str(tmp_path / "runtime" / "runs" / "uploads"))
    output_files = processing.get("output_files", [])
    assert any(str(item).startswith(output_dir) and str(item).endswith("_EIS_Nyquist.png") for item in output_files)
    assert any(str(item).endswith("_EIS_Nyquist.png") and os.path.exists(str(item)) for item in output_files)
    provenance = result.get("result", {}).get("provenance", {})
    source_archive = provenance.get("source_archive_path")
    assert source_archive and os.path.isfile(source_archive)
    assert str(source_archive).startswith(str(tmp_path / "runtime" / "runs" / "uploads"))
    assert provenance.get("source_archive_sha256")
    assert os.path.isfile(provenance.get("metadata_path"))
    assert provenance.get("artifact_root") == str(Path(output_dir).parent)


def test_preflight_does_not_filter_user_raw_csv(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    folder = tmp_path / "raw_input"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "LSV_raw.csv").write_text("Potential Current\n0 0\n1 0.001\n2 0.002\n", encoding="utf-8")

    result = process_service.preflight_process_folder({
        "folder_path": str(folder),
        "data_types": ["LSV"],
        "params": {"lsv_match": "prefix", "lsv_prefix": "LSV"},
    })

    assert result.get("status") == "success"
    preflight = result.get("preflight", {})
    assert preflight.get("selected_matched") == 1
    assert preflight.get("matched_counts", {}).get("LSV") == 1
    assert preflight.get("checks", {}).get("file_recognition", {}).get("status") == "pass"


def test_preflight_uses_exact_explicit_file_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    folder = tmp_path / "explicit_inputs"
    folder.mkdir(parents=True, exist_ok=True)
    selected = folder / "LSV_selected.txt"
    ignored = folder / "LSV_ignored.txt"
    selected.write_text("Potential Current\n0 0\n1 0.001\n2 0.002\n", encoding="utf-8")
    ignored.write_text("Potential Current\n0 0\n1 0.003\n2 0.004\n", encoding="utf-8")

    result = process_service.preflight_process_folder({
        "folder_path": str(folder),
        "data_types": ["LSV"],
        "input_files": [{"path": str(selected), "data_type": "LSV", "enabled": True}],
        "params": {"lsv_match": "prefix", "lsv_prefix": "LSV"},
    })

    assert result.get("status") == "success"
    preflight = result.get("preflight", {})
    assert preflight.get("selection_mode") == "explicit"
    assert preflight.get("selected_matched") == 1
    assert preflight.get("all_files") == [str(selected)]
    assert preflight.get("by_type", {}).get("LSV", {}).get("files") == [str(selected)]
    assert str(ignored) not in preflight.get("all_files", [])


def test_discover_process_inputs_lists_recognized_and_unrecognized_files(tmp_path):
    folder = tmp_path / "discover_inputs"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "LSV_sample.txt").write_text("0 0\n", encoding="utf-8")
    (folder / "notes.csv").write_text("a,b\n", encoding="utf-8")
    (folder / "LSV_results.csv").write_text("result\n", encoding="utf-8")

    result = process_service.discover_process_inputs({
        "folder_path": str(folder),
        "params": {"lsv_match": "prefix", "lsv_prefix": "LSV"},
    })

    assert result.get("status") == "success"
    files = {item["name"]: item for item in result.get("files", [])}
    assert set(files) == {"LSV_sample.txt", "notes.csv"}
    assert files["LSV_sample.txt"]["suggested_type"] == "LSV"
    assert files["notes.csv"]["status"] == "unrecognized"


def test_stale_artifact_is_not_counted_as_new_output(tmp_path, monkeypatch):
    import electrochem_v6.core.processing_cv_module as processing_cv_module

    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    folder = tmp_path / "stale"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "CV_demo.txt").write_text("Potential Current\n0 0\n1 0.1\n2 0.2\n", encoding="utf-8")
    stale_png = folder / f"{folder.name}_CV_demo_CV.png"
    stale_png.write_text("old image placeholder", encoding="utf-8")
    monkeypatch.setattr(process_service, "attach_run_outputs", lambda **_kwargs: {"status": "success", "updated": 0})

    def _fake_cv(_subfolder, _file, _params, enable_quality_check=True):
        return {
            "quality_report": {
                "filename": "CV_demo.txt",
                "is_valid": True,
                "warnings": [],
                "issues": [],
                "quality_level": "normal",
                "recommendation": "none",
            }
        }

    monkeypatch.setattr(processing_cv_module, "process_cv", _fake_cv)

    result = process_service.process_folder({
        "folder_path": str(folder),
        "data_types": ["CV"],
        "params": {"cv_match": "prefix", "cv_prefix": "CV"},
    })

    assert result.get("status") == "error"
    output_files = result.get("result", {}).get("processing", {}).get("output_files", [])
    assert str(stale_png) not in output_files


def test_process_folder_errors_when_no_data_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    folder = tmp_path / "no_match"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "CV_demo.txt").write_text("Potential Current\n0 0\n1 0.1\n2 0.2\n", encoding="utf-8")

    result = process_service.process_folder({
        "folder_path": str(folder),
        "data_types": ["LSV"],
        "params": {
            "lsv_match": "prefix",
            "lsv_prefix": "LSV",
        },
    })

    assert result.get("status") == "error"
    assert "没有生成任何" in result.get("message", "")
    assert "没有匹配" in result.get("message", "")


def test_export_diagnostics_creates_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    result = process_service.export_diagnostics()

    assert result.get("status") == "success"
    assert result.get("path", "").endswith(".zip")


def test_export_diagnostics_falls_back_to_temp_dir(tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    fallback_temp = tmp_path / "temp"
    monkeypatch.setattr(process_service, "user_config_dir", lambda: blocked)
    monkeypatch.setattr(process_service.tempfile, "gettempdir", lambda: str(fallback_temp))

    result = process_service.export_diagnostics()

    assert result.get("status") == "success"
    assert str(fallback_temp / "electrochem_v6" / "diagnostics") in result.get("path", "")


def test_get_latest_quality_report_includes_app_version(tmp_path, monkeypatch):
    report_path = tmp_path / "latest_quality_report.json"
    report_path.write_text(
        json.dumps({"generated_at": "2026-02-27 20:00:00", "data": {"total_files": 2}}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(process_service, "get_quality_report_file", lambda: report_path)

    payload = process_service.get_latest_quality_report()
    assert payload.get("status") == "success"
    assert payload.get("app_version") == APP_VERSION
    assert payload.get("data", {}).get("total_files") == 2
