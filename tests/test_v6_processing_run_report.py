from electrochem_v6.core.processing_run_report import build_run_report_html, build_run_report_markdown


def test_run_report_includes_formulas_quality_and_file_fingerprints():
    manifest = {
        "app_name": "ElectroChem",
        "app_version": "1.0",
        "run": {
            "run_id": "run-1",
            "project_id": "project-1",
            "data_types": ["LSV", "COUPLED"],
            "generated_at": "2026-06-02 12:00:00",
        },
        "processing": {
            "matched_files": 2,
            "generated_files": 3,
            "skipped_files": 0,
            "result_state": "success",
        },
        "quality": {"total_files": 1, "passed": 1, "failed": 0, "warnings": 0, "skipped": 0},
        "calculation": {
            "formula_schema_version": "1.0",
            "formulas": [
                {
                    "key": "coupled.faradaic_efficiency",
                    "name": "Faradaic efficiency",
                    "expression": "FE_i = z_i * F * n_i / Q_total * 100%",
                    "variables": [{"symbol": "Q_total", "description": "Total charge", "unit": "C"}],
                    "result_unit": "%",
                    "assumptions": ["Product amount and charge refer to the same interval."],
                }
            ],
            "ir_compensation": {
                "source": "eis",
                "scope": "same_then_root",
                "formula": "E_iR = E_measured - (j_mA_cm2 / 1000) * A_cm2 * Rs_ohm",
                "results": [
                    {
                        "lsv_file": "D:/data/LSV_sample.txt",
                        "eis_file": "D:/data/EIS_sample.txt",
                        "source": "eis",
                        "method": "auto",
                        "scope": "same_then_root",
                        "rs_ohm": 2.4,
                    }
                ],
            },
        },
        "inputs": {
            "files": [
                {
                    "data_type": "COUPLED",
                    "file_name": "products.csv",
                    "match": "product_table",
                    "exists": True,
                    "size_bytes": 128,
                    "sha256": "abc123",
                }
            ]
        },
        "outputs": {"output_dir": "D:/out", "output_files": ["D:/out/coupled_results.csv"]},
    }
    markdown = build_run_report_markdown(
        manifest,
        generated_at="2026-06-02 12:00:01",
    )

    assert "# ElectroChem Run Report" in markdown
    assert "FE_i = z_i * F * n_i / Q_total * 100%" in markdown
    assert "products.csv" in markdown
    assert "abc123" in markdown
    assert "Quality Summary" in markdown
    assert "iR Compensation Provenance" in markdown
    assert "EIS_sample.txt" in markdown
    assert "2.4" in markdown

    html = build_run_report_html(manifest, generated_at="2026-06-02 12:00:01")
    assert "<!doctype html>" in html
    assert "ElectroChem Run Report" in html
    assert "FE_i = z_i * F * n_i / Q_total * 100%" in html
    assert "products.csv" in html
    assert "abc123" in html
    assert "iR Compensation Provenance" in html
    assert "EIS_sample.txt" in html
