from electrochem_v6.core.project_report import (
    build_project_report_markdown,
    export_project_report,
    safe_project_report_name,
)


def test_safe_project_report_name_replaces_windows_reserved_characters():
    assert safe_project_report_name('HER:LSV/2026*?"<>|') == "HER_LSV_2026______"
    assert safe_project_report_name("") == "project"


def test_build_project_report_markdown_includes_stats_outputs_and_metrics():
    markdown = build_project_report_markdown(
        project={"id": "p1", "name": "HER 项目", "description": "demo", "tags": ["LSV", "EIS"]},
        report_data={
            "stats": {
                "total_files": 2,
                "lsv_count": 1,
                "cv_count": 0,
                "eis_count": 1,
                "ecsa_count": 0,
                "coupled_count": 0,
            },
            "recent_records": [
                {
                    "sample_name": "sample-a",
                    "type": "LSV",
                    "timestamp": "2026-03-01 10:00:00",
                    "status": "success",
                    "file_path": "LSV_sample-a.txt",
                    "output_files": ["LSV_results.csv"],
                    "results": {"overpotential_10": 0.21},
                }
            ],
        },
        generated_at="2026-03-01 12:00:00",
    )

    assert "# HER 项目 项目报告" in markdown
    assert "- 总记录: 2" in markdown
    assert "### sample-a" in markdown
    assert "- 结果文件:" in markdown
    assert "  - LSV_results.csv" in markdown
    assert "| η@10 mA/cm² | 0.21 | mV |" in markdown
    assert '"overpotential_10": 0.21' in markdown


def test_export_project_report_writes_markdown_with_safe_name(tmp_path):
    result = export_project_report(
        project={"id": "p1", "name": "HER:LSV"},
        report_data={"stats": {"total_files": 0}, "recent_records": []},
        output_dir=str(tmp_path),
    )

    assert result["status"] == "success"
    assert result["file_name"].startswith("HER_LSV_project_report_")
    text = (tmp_path / result["file_name"]).read_text(encoding="utf-8")
    assert "# HER:LSV 项目报告" in text
    assert "- 暂无历史记录" in text
