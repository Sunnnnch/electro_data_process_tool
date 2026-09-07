from pathlib import Path

from electrochem_v6.core.processing_response import (
    build_process_error_result,
    build_process_success_result,
    collect_output_files,
    has_data_output_file,
    processing_stats,
)


def test_collect_output_files_prefers_known_artifacts_and_dedupes(tmp_path):
    summary = tmp_path / "summary.json"
    result_csv = tmp_path / "processing_results.csv"
    plot = tmp_path / "sample_LSV.png"
    for path in (summary, result_csv, plot):
        path.write_text("", encoding="utf-8")

    output_files = collect_output_files(
        {
            "summary_path": str(summary),
            "processing_results_csv": str(result_csv),
            "run_report_html_path": str(tmp_path / "run_report.html"),
            "artifact_paths": [str(result_csv), str(plot)],
            "messages": [str(plot), "not-a-path"],
        }
    )

    assert output_files == [str(summary), str(result_csv), str(tmp_path / "run_report.html"), str(plot)]


def test_has_data_output_file_ignores_report_only_outputs():
    assert not has_data_output_file(
        [
            "summary.json",
            "quality_report.json",
            "run_summary.json",
            "run_manifest.json",
            "run_report.md",
            "run_report.html",
        ]
    )
    assert has_data_output_file(["summary.json", str(Path("plots") / "sample_EIS_Nyquist.png")])


def test_processing_stats_counts_matched_generated_and_skipped_files():
    stats = processing_stats(
        {"matched_counts": {"LSV": 2, "EIS": 1}, "skipped_errors": [{"file": "bad.txt"}]},
        ["summary.json", "sample_LSV.png", "quality_report.json", "run_report.md", "run_report.html", "EIS_results.csv"],
    )

    assert stats["matched_files"] == 3
    assert stats["generated_files"] == 2
    assert stats["skipped_files"] == 1
    assert stats["result_state"] == "partial_success"


def test_build_process_success_result_keeps_legacy_and_structured_fields(tmp_path):
    plot = tmp_path / "sample.png"
    plot.write_text("", encoding="utf-8")

    payload = build_process_success_result(
        summary="ok",
        data_types=["LSV", "EIS"],
        project_id="project-1",
        summary_path=str(tmp_path / "summary.json"),
        output_files=[str(plot)],
        output_dir=str(tmp_path),
        preflight={"runnable": True},
        quality_summary={"level": "normal"},
        skipped_errors=[],
        summary_json={"version": "test"},
        raw={"matched_counts": {"LSV": 1}},
        manifest={"manifest_schema_version": "1.0"},
    )

    result = payload["result"]
    assert payload["status"] == "success"
    assert result["data_type"] == "LSV"
    assert result["data_types"] == ["LSV", "EIS"]
    assert result["processing"]["generated_files"] == 1
    assert result["preflight"]["runnable"] is True
    assert result["quality_summary"] == {"level": "normal"}
    assert result["raw"] == {"matched_counts": {"LSV": 1}}
    assert result["manifest"] == {"manifest_schema_version": "1.0"}


def test_build_process_error_result_can_include_partial_result():
    payload = build_process_error_result("failed", result={"processing": {"output_files": []}})

    assert payload == {
        "status": "error",
        "message": "failed",
        "result": {"processing": {"output_files": []}},
    }
