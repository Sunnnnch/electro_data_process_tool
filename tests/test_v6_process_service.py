import io
import json
import os
import zipfile

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

    def _fake_run_pipeline(_folder_path, _gui_vars):
        return {
            "summary_path": str(summary_path),
            "lsv_csv": str(lsv_csv),
            "quality_summary": {"total_files": 1, "passed": 1, "failed": 0, "warnings": 0},
            "messages": ["not_a_path"],
        }

    monkeypatch.setattr(process_service, "run_pipeline", _fake_run_pipeline)
    monkeypatch.setattr(process_service, "attach_run_outputs", lambda **_kwargs: {"status": "success", "updated": 0})

    payload = {"folder_path": str(folder), "data_types": ["LSV"], "params": {"font_size": 12}}
    result = process_service.process_folder(payload)

    assert result.get("status") == "success"
    body = result.get("result", {})
    assert body.get("app_version") == APP_VERSION
    assert body.get("summary_path") == str(summary_path)
    assert isinstance(body.get("summary_json"), dict)

    saved = json.loads(summary_path.read_text(encoding="utf-8"))
    assert saved.get("version") == APP_VERSION
    assert saved.get("pipeline_version") == "3.0.4"
    assert saved.get("summary_schema_version") == "1.0"
    assert saved.get("data_types") == ["LSV"]
    assert isinstance(saved.get("history"), dict)
    assert isinstance(saved.get("processing", {}).get("output_files"), list)


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
    assert any(str(item).endswith("summary.json") for item in output_files)

    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    summary_outputs = summary.get("processing", {}).get("output_files", [])
    assert any(str(item).endswith("_EIS_Nyquist.png") for item in summary_outputs)


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
    assert recursive.get("preflight", {}).get("selected_matched") == 1


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
    assert result.get("preflight", {}).get("selected_matched") == 1


def test_stale_artifact_is_not_counted_as_new_output(tmp_path, monkeypatch):
    import electrochem_v6.core.processing_core_v6 as processing_core

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

    monkeypatch.setattr(processing_core, "process_cv", _fake_cv)

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

