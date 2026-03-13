import json

import electrochem_v6.core.process_service as process_service
from electrochem_v6.config import APP_VERSION


def test_process_folder_rewrites_summary_with_v6_version(tmp_path, monkeypatch):
    folder = tmp_path / "data"
    folder.mkdir(parents=True, exist_ok=True)
    summary_path = folder / "summary.json"
    summary_path.write_text(
        json.dumps({"version": "3.0.4", "timestamp": "2025-01-01 00:00:00"}, ensure_ascii=False),
        encoding="utf-8",
    )

    def _fake_run_pipeline(_folder_path, _gui_vars):
        return {
            "summary_path": str(summary_path),
            "quality_summary": {"total_files": 1, "passed": 1, "failed": 0, "warnings": 0},
            "messages": ["not_a_path"],
        }

    monkeypatch.setattr(process_service, "run_pipeline", _fake_run_pipeline)

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

