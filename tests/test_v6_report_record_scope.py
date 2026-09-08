"""Selected-result reports must not include another sample's run-wide metadata."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image

from electrochem_v6.core import reproducible_report_service as reports
from electrochem_v6.core.project_report import export_project_report
from electrochem_v6.store import history, run_recipes
from test_v6_reproducible_reports import add_record, report_db  # noqa: F401


@pytest.fixture
def shared_run(report_db, tmp_path):  # noqa: F811
    folder = tmp_path / "inputs"
    folder.mkdir()
    output = tmp_path / "outputs"
    output.mkdir()
    sources = [folder / "CV_selected.txt", folder / "CV_unselected.txt"]
    charts = [output / "CV_selected.png", output / "CV_unselected.png"]
    shared = output / "run_report.html"
    shared.write_text("Contains both samples' full run results", encoding="utf-8")
    for index, (source, chart) in enumerate(zip(sources, charts, strict=True)):
        source.write_text(f"0\t{index + 1}\n1\t{index + 2}\n", encoding="utf-8")
        Image.new("RGB", (3, 3), "blue" if index == 0 else "red").save(chart)
    quality = {
        "total_files": 2, "passed": 1, "failed": 1, "warnings": 1, "skipped": 0,
        "quality_levels": {"warning": 1, "error": 1},
        "recommendations": {"review": 1, "reject": 1},
        "files": [
            {"is_valid": True, "issues": [], "warnings": ["selected-only-quality-warning"],
             "stats": {"file_name": "inputs/CV_selected.txt", "data_points": 80},
             "suggestions": [], "quality_level": "warning", "recommendation": "review"},
            {"is_valid": False, "issues": ["unselected-only-quality-error"], "warnings": [],
             "stats": {"file_name": "inputs/CV_unselected.txt", "data_points": 98765},
             "suggestions": ["unselected-only-recommendation"], "quality_level": "error", "recommendation": "reject"},
        ],
    }
    records = [add_record(report_db, index, run_id="scope-shared-run", type="CV",
                          sample_name="inputs", file_name=source.stem, file_path=str(source),
                          results={"data_points": 80 if index == 0 else 98765},
                          output_files=[str(path) for path in [*charts, shared]],
                          quality_summary=quality)
               for index, source in enumerate(sources)]
    saved = {
        "run_id": "scope-shared-run", "project_id": "project-a", "status": "succeeded",
        "data_types": ["CV"], "created_at": "2026-09-01 12:00:00", "folder_path": str(folder),
        "output_dir": str(output), "params": {"area": 1}, "record_keys": [record["record_key"] for record in records],
        "records": [{"record_key": record["record_key"], "input_paths": [record["file_path"]]} for record in records],
        "inputs": [{"path": str(source), "file_name": source.name, "role": "primary", "data_type": "CV"} for source in sources],
        "manifest": {
            "run": {"run_id": "scope-shared-run", "data_types": ["CV"]},
            "quality": quality,
            "processing_results": [
                {"sample_name": "inputs", "data_type": "CV", "source": {"path": str(source)},
                 "metrics": [{"key": "data_points", "value": 80 if index == 0 else 98765, "unit": "count"}],
                 "artifacts": [str(charts[index])]}
                for index, source in enumerate(sources)
            ],
            "outputs": {"output_dir": str(output), "output_files": [str(path) for path in [*charts, shared]]},
        },
    }
    run_recipes.save_run_recipe(saved)
    return {"records": records, "recipe": saved, "quality": quality, "charts": charts, "shared": shared}


def test_selected_record_export_filters_quality_counts_details_and_artifact_list(shared_run, tmp_path):
    selected = shared_run["records"][0]
    data = history.build_project_report("project-a", record_keys=[selected["record_key"]])["report"]
    result = export_project_report(project={"id": "project-a", "name": "Selected scope"},
                                   report_data=data, output_dir=str(tmp_path / "selected-report"))
    assert result["scope"]["record_count"] == result["scope"]["run_count"] == 1
    for key in ("markdown_path", "html_path"):
        text = Path(result[key]).read_text(encoding="utf-8")
        assert "selected-only-quality-warning" in text and "CV_selected.png" in text
        assert "unselected-only-quality-error" not in text
        assert "unselected-only-recommendation" not in text
        assert "CV_unselected" not in text and "98765" not in text
    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
    quality_section = markdown.split("## 质量摘要", 1)[1].split("##", 1)[0]
    assert "检查文件: 1" in quality_section
    assert "通过: 1" in quality_section and "失败: 0" in quality_section
    assert "有警告: 1" in quality_section
    # Export filtering is a view: the durable run/history evidence stays complete.
    stored = history.get_history_detail(selected["record_key"])["record"]
    assert stored["quality_summary"] == shared_run["quality"]
    assert run_recipes.get_run_recipe("scope-shared-run")["manifest"]["quality"] == shared_run["quality"]


def test_whole_run_report_still_preserves_both_samples_and_quality(shared_run, tmp_path):
    result = reports.export_run_report("scope-shared-run", output_dir=str(tmp_path / "run-report"))
    assert result["status"] == "success"
    for key in ("markdown_path", "html_path"):
        text = Path(result[key]).read_text(encoding="utf-8")
        assert "selected-only-quality-warning" in text and "unselected-only-quality-error" in text
        assert "CV_selected.png" in text and "CV_unselected.png" in text
        assert "98765" in text
    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "检查文件: 2" in markdown and "失败: 1" in markdown


def test_old_unattributed_run_quality_is_not_presented_as_selected_sample_quality(shared_run):
    selected = deepcopy(shared_run["records"][0])
    selected["quality_summary"] = {
        "total_files": 99, "passed": 55, "failed": 44,
        "files": [{"issues": ["unknown-batch-only-error"], "stats": {"data_points": 76543}}],
    }
    document = reports.build_project_report_document(
        project={"id": "project-a"}, report_data={
            "records": [selected], "runs": [],
            "scope": {"mode": "record_keys", "project_id": "project-a", "record_keys": [selected["record_key"]],
                      "run_ids": ["scope-shared-run"], "run_count": 1, "record_count": 1, "truncated": False},
        })
    markdown = reports.render_report_markdown(document)
    assert "检查文件: 99" not in markdown and "失败: 44" not in markdown
    assert "unknown-batch-only-error" not in markdown and "76543" not in markdown
    assert any(word in markdown for word in ("未记录", "无法", "不能", "归属"))


@pytest.mark.parametrize("same_basename", [False, True], ids=["unique-group-sources", "ambiguous-group-label"])
def test_ecsa_group_quality_uses_saved_group_source_and_rejects_ambiguous_basename(report_db, tmp_path, same_basename):  # noqa: F811
    groups = [tmp_path / "branch-a" / ("same" if same_basename else "selected"),
              tmp_path / "branch-b" / ("same" if same_basename else "unselected")]
    members = []
    for group in groups:
        group.mkdir(parents=True)
        group_members = [group / "ECSA_20.txt", group / "ECSA_40.txt"]
        for path in group_members:
            path.write_text("0\t1\n1\t2\n", encoding="utf-8")
        members.append(group_members)
    checks = [
        {"filename": group.name + "/ECSA", "is_valid": True, "issues": [],
         "warnings": ["selected-group-quality" if index == 0 else "unselected-group-quality"],
         "stats": {"slope": 0.25 if index == 0 else 98765},
         "quality_level": "warning", "recommendation": "review"}
        for index, group in enumerate(groups)
    ]
    quality = {"total_files": 2, "passed": 2, "warnings": 2, "failed": 0, "files": checks}
    records = [add_record(report_db, index, run_id="ecsa-group-scope", type="ECSA",
                          file_path=str(group), file_name=group.name, sample_name=group.name,
                          results={"cdl_mF_cm2": 0.25 if index == 0 else 98765}, quality_summary=quality)
               for index, group in enumerate(groups)]
    run_recipes.save_run_recipe({
        "run_id": "ecsa-group-scope", "project_id": "project-a", "data_types": ["ECSA"],
        "params": {"area": 1}, "record_keys": [record["record_key"] for record in records],
        "inputs": [{"path": str(path), "role": "primary", "data_type": "ECSA"} for paths in members for path in paths],
        "records": [{"record_key": record["record_key"], "input_paths": [str(path) for path in members[index]]}
                    for index, record in enumerate(records)],
        "manifest": {"quality_reports": checks, "processing_results": [
            {"data_type": "ECSA", "sample_name": group.name, "source": {"path": str(group)},
             "metadata": {"source_files": [path.name for path in members[index]]}}
            for index, group in enumerate(groups)
        ]},
    })
    selected_data = history.build_project_report("project-a", record_keys=[records[0]["record_key"]])["report"]
    document = reports.build_project_report_document(project={"id": "project-a"}, report_data=selected_data)
    markdown = reports.render_report_markdown(document)
    assert "unselected-group-quality" not in markdown and "98765" not in markdown
    if same_basename:
        assert "selected-group-quality" not in markdown
        assert "检查文件:" not in markdown
        assert '"status": "unavailable"' in markdown
    else:
        assert "selected-group-quality" in markdown
        assert "检查文件: 1" in markdown and "有警告: 1" in markdown


@pytest.mark.parametrize("case", ["missing-input-inventory", "duplicate-relative-label", "conflicting-absolute-source"])
def test_uncertain_quality_identity_never_falls_back_to_selected_filename(shared_run, case):
    selected = deepcopy(shared_run["records"][0])
    saved = deepcopy(shared_run["recipe"])
    check = {"filename": "inputs/CV_selected.txt", "is_valid": True,
             "warnings": ["ambiguous-evidence-must-not-appear"], "issues": []}
    checks = [check]
    if case == "missing-input-inventory":
        saved["inputs"] = []
    elif case == "duplicate-relative-label":
        checks.append({**check, "warnings": ["foreign-duplicate-evidence-must-not-appear"]})
    else:
        check["file_path"] = shared_run["records"][1]["file_path"]
    selected["quality_summary"] = {"total_files": len(checks), "passed": len(checks), "files": checks}
    run_recipes.save_run_recipe(saved)
    document = reports.build_project_report_document(project={"id": "project-a"}, report_data={
        "records": [selected], "runs": [],
        "scope": {"mode": "record_keys", "record_keys": [selected["record_key"]],
                  "run_count": 1, "record_count": 1},
    })
    markdown = reports.render_report_markdown(document)
    assert "ambiguous-evidence-must-not-appear" not in markdown
    assert "foreign-duplicate-evidence-must-not-appear" not in markdown
    assert "检查文件:" not in markdown
    assert '"status": "unavailable"' in markdown
