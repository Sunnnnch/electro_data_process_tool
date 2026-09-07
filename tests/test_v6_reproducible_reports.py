from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from PIL import Image

from electrochem_v6.core import reproducible_report_service as reports
from electrochem_v6.core.project_report import export_project_report
from electrochem_v6.store import history, run_recipes
from electrochem_v6.store.database import Database


@pytest.fixture
def report_db(tmp_path, monkeypatch):
    database = Database(str(tmp_path / "reports.sqlite3"))
    monkeypatch.setattr(history, "get_database", lambda: database)
    monkeypatch.setattr(run_recipes, "get_database", lambda: database)
    return database


def add_record(database, index=0, *, project="project-a", run_id=None, archived=False, **extra):
    record = {
        "timestamp": "2026-09-01 12:00:00", "type": "LSV", "project_id": project,
        "run_id": run_id or f"run-{index}", "file_path": f"/data/LSV_{index}.txt",
        "file_name": f"LSV_{index}.txt", "sample_name": f"sample-{index}",
        "results": {"overpotential_at_10": index + 0.125}, "archived": archived,
        **extra,
    }
    database.add_history_record(record)
    return next(item for item in database.filter_history(project_id=project, include_archived=True, limit=None)
                if item["file_path"] == record["file_path"])


def recipe(run_id="fe-run", *, project="project-a", record_keys=None, sample="FE-sample"):
    return {
        "run_id": run_id, "project_id": project, "created_at": "2026-09-01 12:00:00",
        "status": "success", "data_types": ["COUPLED"], "record_keys": record_keys or [],
        "params": {"area": 2, "coupled_input_mode": "product_table", "ir_compensation_enabled": False},
        "app_version": "saved-2.3", "formula_schema_version": "saved-formula-1",
        "inputs": [{"path": "/data/products.csv", "file_name": "products.csv", "sha256": "saved-sha256"}],
        "manifest": {
            "processing_results": [{
                "data_type": "COUPLED", "sample_name": sample,
                "metrics": [{"key": "FE_H2", "value": 85.25, "unit": "%", "method": "saved-method"}],
                "source": {"path": "/data/products.csv"},
            }],
            "calculation": {"formula_schema_version": "saved-formula-1", "formulas": [
                {"name": "FE", "key": "FE_H2", "expression": "FE = z F n / Q * 100%", "result_unit": "%"}
            ]},
            "engine": {"python": "saved-python-version"},
            "quality_reports": [{"issues": [{"message": "recorded FE quality finding"}]}],
        },
    }


def test_project_report_includes_more_than_500_history_records(report_db, tmp_path):
    # Batch public upserts through one transaction to keep the large-scope
    # regression fast while exercising the real unlimited SQLite query.
    with report_db.transaction() as connection:
        for index in range(505):
            report_db._upsert_history_record(connection, {
                "timestamp": f"2026-09-{1 + index % 28:02d} 12:00:00", "type": "LSV", "project_id": "project-a",
                "run_id": "old-run", "file_path": f"/data/{index}.txt", "sample_name": f"all-samples-{index}",
                "results": {"last_metric": index},
            })
    result = history.build_project_report("project-a")
    assert result["status"] == "success"
    data = result["report"]
    assert data["scope"]["record_count"] == len(data["records"]) == 505
    assert data["scope"]["truncated"] is False
    exported = export_project_report(project={"id": "project-a", "name": "Complete"}, report_data=data, output_dir=str(tmp_path))
    text = Path(exported["markdown_path"]).read_text(encoding="utf-8")
    assert "all-samples-504" in text and "| last_metric | 504 |" in text
    assert "all-samples-0" in text and "| last_metric | 0 |" in text


def test_all_project_run_scope_reads_every_recipe_page_without_history(report_db):
    with report_db.transaction() as connection:
        connection.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", [
            (f"run_recipe:fe-{index}", json.dumps(recipe(f"fe-{index}"))) for index in range(503)
        ])
    data = history.build_project_report("project-a")["report"]
    assert data["scope"]["run_count"] == 503
    assert data["scope"]["record_count"] == 0
    assert data["scope"]["normalized_result_count"] == 503
    assert {item["run_id"] for item in data["runs"]} == {f"fe-{index}" for index in range(503)}


def test_recipe_only_fe_is_in_run_and_selected_project_reports(report_db, tmp_path):
    run_recipes.save_run_recipe(recipe())
    selected = history.build_project_report("project-a", run_ids=["fe-run"])
    assert selected["status"] == "success"
    data = selected["report"]
    assert data["scope"]["record_count"] == 0
    assert data["scope"]["run_count"] == data["scope"]["normalized_result_count"] == 1
    outputs = [
        reports.export_run_report("fe-run", output_dir=str(tmp_path / "run")),
        export_project_report(project={"id": "project-a", "name": "FE"}, report_data=data,
                              output_dir=str(tmp_path / "project"), format="html"),
    ]
    for output in outputs:
        text = Path(output["markdown_path"]).read_text(encoding="utf-8")
        html = Path(output["html_path"]).read_text(encoding="utf-8")
        assert "85.25" in text and "FE_H2" in text and "saved-method" in text
        assert "saved-sha256" in text and "saved-2.3" in text and "saved-python-version" in text
        assert "recorded FE quality finding" in html
        assert text.index("85.25") < text.index("Reproducibility Appendix")
        assert output["path"] == output["html_path"]


def test_selected_record_excludes_other_results_and_shared_charts(report_db, tmp_path):
    selected = add_record(report_db, 1, run_id="shared")
    add_record(report_db, 2, run_id="shared", results={"unselected_only_metric": 91919})
    output = tmp_path / "plots"
    output.mkdir()
    chart = output / "shared.png"
    Image.new("RGB", (2, 2), "blue").save(chart)
    report_db.attach_run_outputs(run_id="shared", output_files=[str(chart)])
    saved = recipe("shared", sample="unselected-FE-result")
    saved["output_dir"] = str(output)
    run_recipes.save_run_recipe(saved)
    data = history.build_project_report("project-a", record_keys=[selected["record_key"]])["report"]
    document = reports.build_project_report_document(project={"id": "project-a"}, report_data=data)
    text = reports.render_report_markdown(document)
    assert data["scope"]["record_count"] == 1 and data["runs"] == []
    assert "sample-1" in text and "sample-2" not in text
    assert "unselected_only_metric" not in text and "unselected-FE-result" not in text
    assert not document["figures"]
    assert "未确认样品归属的图表不嵌入" in text


def test_selected_lsv_retains_its_auxiliary_eis_fingerprint_and_ir_provenance(report_db):
    selected = add_record(report_db, 1, run_id="with-eis")
    saved = recipe("with-eis")
    saved["records"] = [{"record_key": selected["record_key"], "input_paths": [selected["file_path"]]}]
    saved["inputs"] = [
        {"path": selected["file_path"], "role": "primary", "sha256": "selected-source-hash"},
        {"path": "/eis/matched.txt", "role": "ir_eis", "sha256": "matched-eis-hash", "for_paths": [selected["file_path"]]},
        {"path": "/eis/unrelated.txt", "role": "ir_eis", "sha256": "unrelated-eis-hash", "for_paths": ["/data/other.txt"]},
    ]
    saved["manifest"]["calculation"]["ir_compensation"] = {"source": "eis", "results": [
        {"lsv_file": selected["file_path"], "eis_file": "/eis/matched.txt", "rs_ohm": 4.125},
        {"lsv_file": "/data/other.txt", "eis_file": "/eis/unrelated.txt", "rs_ohm": 998.25},
    ]}
    run_recipes.save_run_recipe(saved)
    data = history.build_project_report("project-a", record_keys=[selected["record_key"]])["report"]
    text = reports.render_report_markdown(reports.build_project_report_document(project={"id": "project-a"}, report_data=data))
    assert "selected-source-hash" in text and "matched-eis-hash" in text and "4.125" in text
    assert "unrelated-eis-hash" not in text and "998.25" not in text


@pytest.mark.parametrize("selectors", [
    {"run_ids": []}, {"record_keys": []}, {"run_ids": "fe-run"}, {"run_ids": [None]},
    {"run_ids": ["fe-run"], "record_keys": ["key"]}, {"run_ids": ["outside-project"]},
    {"record_keys": ["missing-key"]},
])
def test_invalid_or_outside_project_scope_is_not_widened(report_db, selectors):
    run_recipes.save_run_recipe(recipe())
    run_recipes.save_run_recipe(recipe("outside-project", project="project-b"))
    result = history.build_project_report("project-a", **selectors)
    assert result["status"] == "error"


def test_archived_scope_does_not_restore_archived_results_via_recipe(report_db):
    item = add_record(report_db, 1, run_id="archived-run", archived=True)
    run_recipes.save_run_recipe(recipe("archived-run", record_keys=[item["record_key"]]))
    default = history.build_project_report("project-a")["report"]
    assert not default["records"] and not default["runs"]
    assert default["scope"]["excluded_archived_run_ids"] == ["archived-run"]
    assert history.build_project_report("project-a", run_ids=["archived-run"])["status"] == "error"
    assert history.build_project_report("project-a", record_keys=[item["record_key"]])["status"] == "error"
    included = history.build_project_report("project-a", include_archived=True, run_ids=["archived-run"])["report"]
    assert included["scope"]["record_count"] == included["scope"]["normalized_result_count"] == 1


def test_legacy_missing_evidence_is_not_filled_with_current_defaults(report_db):
    item = add_record(report_db, 1, run_id="legacy")
    document = reports.build_project_report_document(project={"id": "project-a"}, report_data={"records": [item]})
    text = reports.render_report_markdown(document)
    assert "历史记录未保存参数" in text
    assert "未记录；不能确认可复算性" in text
    assert "Formula schema: 未记录" in text
    assert "area: 1" not in text and "cs_value: 40" not in text
    assert document["scope"]["truncated"] is None


def test_partially_deleted_run_never_restores_deleted_snapshot(report_db, tmp_path):
    remaining = add_record(report_db, 3, run_id="partial")
    saved = recipe("partial", record_keys=[remaining["record_key"]], sample="deleted-sample")
    saved["history_partially_deleted"] = True
    saved["deleted_record_keys"] = ["deleted-record-key"]
    run_recipes.save_run_recipe(saved)
    assert reports.export_run_report("partial", output_dir=str(tmp_path))["status"] == "error"
    assert history.build_project_report("project-a", run_ids=["partial"])["status"] == "error"
    for selectors in ({}, {"record_keys": [remaining["record_key"]]}):
        response = history.build_project_report("project-a", **selectors)
        assert response["status"] == "success"
        data = response["report"]
        assert data["scope"]["record_count"] == 1 and not data["runs"]
        document = reports.build_project_report_document(project={"id": "project-a"}, report_data=data)
        text = reports.render_report_markdown(document)
        assert "sample-3" in text and "3.125" in text
        assert "deleted-sample" not in text and "85.25" not in text
    assert history.build_project_report("project-a")["report"]["scope"]["excluded_partially_deleted_run_ids"] == ["partial"]


def test_older_recipe_can_restore_recorded_metrics_without_inventing_units(report_db, tmp_path):
    item = add_record(report_db, 11, run_id="older")
    run_recipes.save_run_recipe({"run_id": "older", "project_id": "project-a", "record_keys": [item["record_key"]], "params": {"area": 3}})
    result = reports.export_run_report("older", output_dir=str(tmp_path))
    text = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "11.125" in text and "overpotential_at_10" in text
    assert "由关联历史记录恢复" in text
    assert "未推断缺失单位或方法" in text
    assert result["scope"]["normalized_result_count"] == 1


def test_run_report_has_saved_parameters_metrics_fingerprints_and_safe_portable_figures(tmp_path):
    output = tmp_path / "original"
    output.mkdir()
    chart = output / "图 [1].png"
    Image.new("RGB", (4, 3), "blue").save(chart)
    outside = tmp_path / "outside.png"
    Image.new("RGB", (2, 2), "red").save(outside)
    svg = output / "unsafe.svg"
    svg.write_text('<svg><script>alert(1)</script></svg>', encoding="utf-8")
    attack = '<script>alert("x")</script><img src=x onerror=alert(1)>'
    manifest = {
        "run": {"run_id": attack, "data_types": ["LSV"]},
        "app": {"version": "recorded-version"}, "parameters": {
            "area": 7, "tafel_range": [0.1, 0.2], "offset": 0.17,
            "nested": [{"api_key": "do-not-export-token", "value": attack}],
            **{f"complete_parameter_{i}": i for i in range(20)},
        },
        "processing_results": [{"sample_name": attack, "data_type": "LSV",
            "metrics": [{"key": f"metric_{i}", "value": i} for i in range(14)],
            "metadata": {"effective_potential_offset": 0.17}, "artifacts": [str(chart)]}],
        "outputs": {"output_dir": str(output), "output_files": [str(chart), str(outside), str(svg)]},
        "inputs": {"files": [{"file_name": attack, "sha256": "recorded-hash", "path": str(tmp_path / "missing.txt")}],
                   "integrity": {"status": "changed"}},
    }
    document = reports.build_run_report_document(manifest)
    result = reports.export_report_document(document, output_dir=str(tmp_path / "export"), stem="unsafe_test")
    html = Path(result["html_path"]).read_text(encoding="utf-8")
    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert '<script>' not in html and '<img src=x' not in html and "&lt;script&gt;" in html
    assert "do-not-export-token" not in html and "do-not-export-token" not in markdown
    assert html.count('<img src="data:image/png;base64,') == 1
    assert "data:image/svg" not in html and "file:///" not in html
    assert "metric_13" in html and "complete_parameter_19" in html
    assert "recorded-hash" in html and "当前源文件缺失" in html
    assert "recorded-version" in html and "changed" in html
    assert markdown.index("几何面积 (cm²): 7") < markdown.index("Reproducibility Appendix")
    asset_paths = re.findall(r"\]\(<(report_[^>]+_assets/[^>]+)>\)", markdown)
    assert len(asset_paths) == 1
    assert (Path(result["markdown_path"]).parent / asset_paths[0]).read_bytes() == chart.read_bytes()


def test_pure_renderers_escape_text_and_reject_untrusted_links():
    document = {"title": "[click](javascript:alert(1))<script>bad</script>", "summary": [
        {"heading": "<img onerror=bad>", "fields": [["<x>", "<svg onload=bad>"]]},
    ], "figures": [{"caption": "bad", "data_uri": "data:image/svg+xml;base64,PHN2Zz4=", "href": "javascript:alert(1)"},
                    {"href": "http://[bad", "caption": "malformed"}]}
    html = reports.render_report_html(document)
    markdown = reports.render_report_markdown(document)
    assert '<script>' not in html and '<svg onload' not in html
    assert 'href="javascript:' not in html and '<img src=' not in html
    assert "\\[click\\]" in markdown


def test_run_report_rejects_missing_recipe_and_unsupported_format(report_db, tmp_path):
    assert reports.export_run_report("missing", output_dir=str(tmp_path))["status"] == "error"
    run_recipes.save_run_recipe(recipe())
    assert reports.export_run_report("fe-run", output_dir=str(tmp_path), format="pdf")["status"] == "error"
    assert not list(tmp_path.glob("run_report*"))


def test_summary_is_compact_without_raw_scope_repeated_history_or_float_noise(report_db):
    run_id = "abcdef1234567890abcdef1234567890"
    record = add_record(report_db, 1, run_id=run_id, results={"potential_10": 0.31, "potential_at_10.0": 0.31, "tafel_slope": 59.999999966})
    saved = recipe(run_id, record_keys=[record["record_key"]])
    saved["manifest"]["processing_results"] = [{"sample_name": "same-folder", "data_type": "LSV",
        "source": {"path": "/data/LSV_1.txt"}, "metrics": [
            {"key": "potential_at_10", "value": 0.31, "unit": "V"},
            {"key": "tafel_slope", "value": 59.999999966, "unit": "mV/dec"},
        ]}]
    saved["manifest"]["quality"] = {"passed": 1, "warnings": 1, "files": [{"warnings": ["Review fitted range"], "stats": {"large_internal_detail": 123}}]}
    run_recipes.save_run_recipe(saved)
    data = history.build_project_report("project-a", run_ids=[run_id])["report"]
    document = reports.build_project_report_document(project={"id": "project-a", "name": "Summary"}, report_data=data)
    summary = json.dumps(document["summary"], ensure_ascii=False)
    assert all("json" not in block for block in document["summary"])
    assert run_id not in summary and record["record_key"] not in summary and "/data/" not in summary
    assert "59.999999966" not in summary and '"60"' in summary
    assert "large_internal_detail" not in summary and "Review fitted range" in summary
    assert "potential_10" not in summary  # The history aliases are only in the appendix.
    assert "LSV_1.txt" in summary
    metric_tables = [item for item in document["summary"] if item.get("rows")]
    assert len(metric_tables) == 1 and len(metric_tables[0]["rows"]) == 2
    raw = json.dumps(document["appendix"], ensure_ascii=False)
    assert "59.999999966" in raw and record["record_key"] in raw and "large_internal_detail" in raw


def test_selected_history_table_deduplicates_aliases_and_keeps_known_units(report_db):
    record = add_record(report_db, 1, results={"potential_10": 0.3, "potential_at_10.0": 0.31, "tafel_slope": 59.999999966})
    data = history.build_project_report("project-a", record_keys=[record["record_key"]])["report"]
    document = reports.build_project_report_document(project={"id": "project-a"}, report_data=data)
    rows = next(item["rows"] for item in document["summary"] if item.get("columns") == ["指标", "数值", "单位"])
    assert rows == [["E@10 mA/cm²", "0.31", "V"], ["Tafel 斜率", "60", "mV/dec"]]
    assert '"potential_10": 0.3' in reports.render_report_markdown(document)


def test_record_chart_selection_uses_path_even_when_sample_names_match(report_db, tmp_path):
    selected = add_record(report_db, 1, run_id="shared-name", sample_name="same-folder")
    other = add_record(report_db, 2, run_id="shared-name", sample_name="same-folder")
    charts = []
    for index in range(2):
        path = tmp_path / f"chart-{index}.png"
        Image.new("RGB", (2, 2), "blue" if index == 0 else "red").save(path)
        charts.append(str(path))
    saved = recipe("shared-name")
    saved["output_dir"] = str(tmp_path)
    saved["manifest"]["processing_results"] = [
        {"sample_name": "same-folder", "data_type": "LSV", "source": {"path": record["file_path"]}, "artifacts": [chart]}
        for record, chart in zip((selected, other), charts)
    ]
    run_recipes.save_run_recipe(saved)
    data = history.build_project_report("project-a", record_keys=[selected["record_key"]])["report"]
    document = reports.build_project_report_document(project={"id": "project-a"}, report_data=data)
    assert [figure["path"] for figure in document["figures"]] == charts[:1]
    assert "LSV_1.txt" in json.dumps(document["summary"], ensure_ascii=False)
    assert "LSV_2.txt" not in json.dumps(document["summary"], ensure_ascii=False)


def test_true_manifest_builder_formulas_render_and_legacy_empty_list_keeps_known_version():
    from electrochem_v6.core.processing_manifest import build_run_manifest

    manifest = build_run_manifest(app_name="ElectroChem", app_version="recorded", run_id="formula-run", project_id="p",
        data_types=["LSV"], params={"tafel_enabled": True}, preflight={}, output_files=[], output_dir=None,
        summary_path=None, processing={}, quality_summary={}, skipped_errors=[], raw_result={})
    assert isinstance(manifest["calculation"]["formulas"], list)
    assert any(item["key"] == "lsv.tafel_fit" for item in manifest["calculation"]["formulas"])
    html = reports.render_report_html(reports.build_run_report_document(manifest))
    assert "lsv.tafel_fit" in html and "本次清单未保存公式条目" not in html
    manifest["calculation"] = {"formula_schema_version": "1.2", "formulas": []}
    html = reports.render_report_html(reports.build_run_report_document(manifest))
    assert "已记录公式版本 1.2" in html and "本次清单未保存公式条目" in html
    assert "公式版本和公式内容未记录" not in html and "lsv.tafel_fit" not in html
