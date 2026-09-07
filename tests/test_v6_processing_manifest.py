import hashlib
import json

from electrochem_v6.core.processing_manifest import (
    MANIFEST_SCHEMA_VERSION,
    build_run_manifest,
    input_file_refs_from_preflight,
    write_run_manifest,
)


def test_input_file_refs_from_preflight_keeps_module_context():
    refs = input_file_refs_from_preflight(
        {
            "by_type": {
                "LSV": {"match": "prefix", "examples": ["D:/data/LSV_a.txt"]},
                "COUPLED": {"match": "product_table", "examples": ["D:/data/products.csv"]},
            }
        }
    )

    assert refs[0]["data_type"] == "LSV"
    assert refs[0]["file_name"] == "LSV_a.txt"
    assert refs[0]["match"] == "prefix"
    assert refs[0]["exists"] is False
    assert refs[1]["data_type"] == "COUPLED"
    assert refs[1]["file_name"] == "products.csv"
    assert refs[1]["match"] == "product_table"
    assert refs[1]["exists"] is False


def test_input_file_refs_include_sha256_for_existing_files(tmp_path):
    source = tmp_path / "products.csv"
    source.write_text("sample,product\nA,H2\n", encoding="utf-8")
    refs = input_file_refs_from_preflight(
        {"by_type": {"COUPLED": {"match": "product_table", "files": [str(source)]}}}
    )

    expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    assert refs[0]["exists"] is True
    assert refs[0]["size_bytes"] == source.stat().st_size
    assert refs[0]["sha256"] == expected_hash


def test_input_file_refs_from_preflight_prefers_complete_file_list():
    refs = input_file_refs_from_preflight(
        {
            "by_type": {
                "LSV": {
                    "match": "prefix",
                    "examples": ["D:/data/LSV_1.txt"],
                    "files": ["D:/data/LSV_1.txt", "D:/data/LSV_2.txt", "D:/data/LSV_3.txt"],
                },
            }
        }
    )

    assert [item["file_name"] for item in refs] == ["LSV_1.txt", "LSV_2.txt", "LSV_3.txt"]


def test_build_run_manifest_redacts_sensitive_params_and_summarizes_results():
    manifest = build_run_manifest(
        app_name="ElectroChem",
        app_version="1.0",
        run_id="run-1",
        project_id="project-1",
        data_types=["lsv", "coupled"],
        params={"area": 1.0, "openai_api_key": "secret", "nested": {"token": "abc"}},
        preflight={"matched_counts": {"LSV": 1}, "matched_files": 1, "by_type": {}},
        output_files=["LSV_results.csv"],
        output_dir="D:/out",
        summary_path="D:/out/summary.json",
        processing={"generated_files": 1},
        quality_summary={"passed": 1},
        skipped_errors=[],
        raw_result={
            "processing_results": [
                {"data_type": "LSV", "metrics": [{"key": "potential_at_10"}]},
                {"data_type": "COUPLED", "metrics": [{"key": "faradaic_efficiency_pct"}]},
            ]
        },
        generated_at="2026-06-02 12:00:00",
    )

    assert manifest["manifest_schema_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest["run"]["data_types"] == ["LSV", "COUPLED"]
    assert manifest["parameters"]["openai_api_key"] == "***REDACTED***"
    assert manifest["parameters"]["nested"]["token"] == "***REDACTED***"
    formulas = {item["key"]: item for item in manifest["calculation"]["formulas"]}
    assert "coupled.faradaic_efficiency" in formulas
    assert formulas["coupled.faradaic_efficiency"]["expression"] == "FE_i = z_i * F * n_i / Q_total * 100%"
    assert manifest["results"]["normalized_results"] == 2
    assert manifest["results"]["normalized_metrics"] == 2
    assert manifest["results"]["by_type"] == {"LSV": 1, "COUPLED": 1}


def test_write_run_manifest_creates_json_file(tmp_path):
    path = write_run_manifest({"manifest_schema_version": "1.0"}, output_dir=str(tmp_path))

    payload = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    assert path == str(tmp_path / "run_manifest.json")
    assert payload == {"manifest_schema_version": "1.0"}
