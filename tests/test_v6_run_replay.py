from pathlib import Path

import pytest

from conftest import _write_tsv, make_ecsa_rows, make_lsv_rows
from electrochem_v6.core.process_service import process_folder
from electrochem_v6.core.run_replay import build_replay_plan
from electrochem_v6.store.run_recipes import get_run_recipe, list_run_recipes_page
from electrochem_v6.store.runtime import get_database, reset_runtime


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    folder = tmp_path / "data"
    folder.mkdir()
    yield folder
    reset_runtime()


def make_cv(folder, name="CV_demo.txt"):
    path = folder / name
    path.write_text("Potential Current\n0 0\n0.2 0.0004\n0.4 0.001\n0.6 0.0003\n0.8 -0.0002\n", encoding="utf-8")
    return path


def run(folder, data_types=None, params=None):
    result = process_folder({"folder_path": str(folder), "data_types": data_types or ["CV"], "project_name": "Replay", "params": params or {}})
    assert result["status"] == "success", result
    run_id = result["result"]["manifest"]["run"]["run_id"]
    return get_run_recipe(run_id)


def test_recipe_survives_deleted_outputs_and_replays_one_record_in_new_run(data):
    make_cv(data)
    make_cv(data, "CV_second.txt")
    old = run(data)
    old_id = old["run_id"]
    key = old["record_keys"][0]
    assert old["params"] and not any(key.startswith("_") for key in old["params"])
    assert len(old["inputs"]) == 2
    assert all(item.get("sha256") for item in old["inputs"])
    Path(old["output_dir"], "run_manifest.json").unlink()
    reset_runtime()
    plan = build_replay_plan(old_id, {"record_key": key, "params": {"area": 2}})
    assert plan["can_replay"], plan
    assert len(plan["input_files"]) == 1
    assert {item["key"] for item in plan["parameter_changes"]} == {"area"}
    result = process_folder(plan["payload"])
    assert result["status"] == "success", result
    new = get_run_recipe(result["result"]["manifest"]["run"]["run_id"])
    assert new["run_id"] != old_id
    assert new["parent_run_id"] == old_id
    assert new["parent_record_key"] == key
    assert new["output_dir"] != old["output_dir"]
    assert new["project_id"] == old["project_id"]
    assert len(new["record_keys"]) == 1
    assert get_database().get_history_record(key) is not None


def test_replay_changed_missing_and_relocated_source_are_explicit(data):
    source = make_cv(data)
    recipe = run(data)
    source.write_text(source.read_text() + "1.0 -0.0003\n")
    blocked = build_replay_plan(recipe["run_id"])
    assert not blocked["can_replay"] and blocked["requires_changed_confirmation"]
    assert blocked["source_checks"][0]["state"] == "changed"
    assert build_replay_plan(recipe["run_id"], {"allow_changed_sources": True})["can_replay"]
    new_location = data / "CV_relocated.txt"
    source.rename(new_location)
    missing = build_replay_plan(recipe["run_id"], {"allow_changed_sources": True})
    assert not missing["can_replay"] and missing["source_checks"][0]["state"] == "missing"
    relocated = build_replay_plan(recipe["run_id"], {"source_paths": {str(source): str(new_location)}, "allow_changed_sources": True})
    assert relocated["can_replay"], relocated
    assert relocated["input_files"][0]["path"] == str(new_location)


def test_queue_delay_cannot_silently_use_new_inputs(data):
    source = make_cv(data)
    recipe = run(data)
    plan = build_replay_plan(recipe["run_id"])
    assert plan["can_replay"]
    source.write_text(source.read_text() + "1.0 -0.0003\n")
    result = process_folder(plan["payload"])
    assert result["status"] == "error"
    assert "预检后发生变化" in result["message"]


def test_original_source_changes_during_processing_are_recorded(data, monkeypatch):
    import electrochem_v6.core.process_service as service

    source = make_cv(data)
    real_run = service._run_selected_modules

    def change_after_read(*args, **kwargs):
        result = real_run(*args, **kwargs)
        source.write_text(source.read_text() + "1.0 -0.0003\n")
        return result

    monkeypatch.setattr(service, "_run_selected_modules", change_after_read)
    recipe = run(data)
    assert recipe["source_integrity"] == "changed_during_processing"
    assert recipe["manifest"]["inputs"]["integrity"] == "changed_during_processing"


@pytest.mark.parametrize("dtype", ["LSV", "EIS", "ECSA"])
def test_other_primary_modules_have_complete_record_replay_inputs(data, dtype):
    if dtype == "LSV":
        _write_tsv(data / "LSV_demo.txt", make_lsv_rows())
        params = {}
        expected_files = 1
    elif dtype == "EIS":
        (data / "EIS_demo.txt").write_text("Freq Zreal Zimag\n100000 2 -0.5\n10000 3 -1\n1000 4 -2\n100 5 -1\n10 6 -.5\n")
        params = {}
        expected_files = 1
    else:
        for rate in (10, 20, 30):
            _write_tsv(data / f"ECSA{rate}.txt", make_ecsa_rows(rate / 1000))
        params = {"ecsa_ev": .1}
        expected_files = 3
    recipe = run(data, [dtype], params)
    assert recipe["record_keys"]
    plan = build_replay_plan(recipe["run_id"], {"record_key": recipe["record_keys"][0]})
    assert plan["can_replay"], plan
    assert len(plan["input_files"]) == expected_files
    replay = process_folder(plan["payload"])
    assert replay["status"] == "success", replay


@pytest.mark.parametrize("peak", [False, True])
def test_coupled_whole_run_retains_all_external_dependencies(data, peak):
    from test_v6_processing_coupled_pipeline import _write_peak_method, _write_peak_signal, _write_products_csv

    products = data / "products.csv"
    params = {"coupled_products_file": str(products)}
    expected_roles = {"product_table"}
    if peak:
        method = data / "method.json"
        signal = data / "signal.csv"
        _write_peak_method(method)
        _write_peak_signal(signal)
        products.write_text("sample_name,signal_file,charge_C\nsample-a,signal.csv,385.94132848\n")
        params.update(coupled_input_mode="peak_analysis", coupled_peak_method_source="file", coupled_peak_method_file=str(method))
        expected_roles |= {"peak_method", "signal"}
    else:
        _write_products_csv(products)
    recipe = run(data, ["COUPLED"], params)
    assert {item["role"] for item in recipe["inputs"]} == expected_roles
    assert recipe["manifest"]["processing_results"]
    plan = build_replay_plan(recipe["run_id"])
    assert plan["can_replay"], plan
    assert process_folder(plan["payload"])["status"] == "success"
    if peak:
        signal.unlink()
        blocked = build_replay_plan(recipe["run_id"])
        assert not blocked["can_replay"]
        assert any(item["role"] == "signal" and item["state"] == "missing" for item in blocked["source_checks"])


def test_old_history_and_foreign_record_cannot_claim_complete_recipe(data):
    with pytest.raises(LookupError, match="未保存完整配方"):
        build_replay_plan("old-unknown-run")
    make_cv(data)
    recipe = run(data)
    foreign = build_replay_plan(recipe["run_id"], {"record_key": "another-run-record"})
    assert not foreign["can_replay"]
    assert any("不属于" in item for item in foreign["issues"])


def test_runs_page_exposes_total_and_more(data):
    make_cv(data)
    recipe = run(data)
    run(data)
    page = list_run_recipes_page(recipe["project_id"], limit=1)
    assert page["total"] == 2 and page["has_more"] is True and page["next_offset"] == 1
    assert len(list_run_recipes_page(recipe["project_id"], limit=1, offset=1)["runs"]) == 1


def test_replay_routes_use_real_background_pipeline(data):
    from electrochem_v6.server import V6ServerManager
    from test_v6_job_service import _wait_for_job
    from test_v6_server import _get_free_port, _read

    make_cv(data)
    recipe = run(data)
    manager = V6ServerManager(_get_free_port())
    assert manager.start()[0]
    base = f"http://127.0.0.1:{manager.port}/api/v1"
    try:
        status, detail = _read(f"{base}/runs/{recipe['run_id']}")
        assert status == 200 and detail["run"]["params"]
        status, planned = _read(f"{base}/runs/{recipe['run_id']}/replay-plan", method="POST", payload={})
        assert status == 200 and planned["plan"]["can_replay"], planned
        status, submitted = _read(f"{base}/runs/{recipe['run_id']}/replay", method="POST", payload={"params": {"area": 2}})
        assert status == 202, submitted
        job = _wait_for_job(submitted["job_id"], timeout=10)
        assert job["status"] == "succeeded", job
        new_id = job["result"]["result"]["manifest"]["run"]["run_id"]
        assert get_run_recipe(new_id)["parent_run_id"] == recipe["run_id"]
        status, listing = _read(f"{base}/runs?project_id={recipe['project_id']}&limit=1")
        assert status == 200 and listing["total"] == 2 and listing["has_more"]
    finally:
        manager.stop()


def test_uploaded_sources_restore_after_temporary_extraction_and_again_after_cache_removal(data):
    import shutil

    from electrochem_v6.server.routes_post import _process_prepared_uploaded_zip
    from test_v6_artifact_lifecycle import prepare

    prepared = prepare()
    result = _process_prepared_uploaded_zip(prepared)
    assert result["status"] == "success", result
    old = get_run_recipe(result["result"]["manifest"]["run"]["run_id"])
    assert old["inputs"][0]["archive_member"] == "CV_demo.txt"
    assert not Path(old["folder_path"]).exists()
    assert Path(old["source_archive_path"]).is_file()
    plan = build_replay_plan(old["run_id"])
    assert plan["can_replay"], plan
    assert any("恢复" in item for item in plan["warnings"])
    replay = process_folder(plan["payload"])
    assert replay["status"] == "success", replay
    new = get_run_recipe(replay["result"]["manifest"]["run"]["run_id"])
    assert new["source_archive_sha256"] == old["source_archive_sha256"]
    assert new["inputs"][0]["archive_member"] == old["inputs"][0]["archive_member"]
    cache = Path(new["folder_path"]).parent.resolve()
    assert cache.parent == (data.parent / "runtime" / "runs" / "replay_sources").resolve()
    shutil.rmtree(cache)
    second_plan = build_replay_plan(new["run_id"])
    assert second_plan["can_replay"], second_plan
    second = process_folder(second_plan["payload"])
    assert second["status"] == "success", second
    assert second["result"]["manifest"]["run"]["run_id"] not in {old["run_id"], new["run_id"]}


def test_default_and_explicit_project_are_captured_before_processing(data):
    from electrochem_v6.store.runtime import get_project_store

    make_cv(data)
    default = get_project_store().create_project("Default")
    other = get_project_store().create_project("Explicit")
    first = process_folder({"folder_path": str(data), "data_types": ["CV"]})
    assert first["status"] == "success", first
    recipe = get_run_recipe(first["result"]["manifest"]["run"]["run_id"])
    assert recipe["project_id"] == default
    assert get_database().get_history_record(recipe["record_keys"][0])["project_id"] == default
    get_database().set_default_project(other)
    replay = process_folder(build_replay_plan(recipe["run_id"])["payload"])
    assert replay["status"] == "success", replay
    assert get_run_recipe(replay["result"]["manifest"]["run"]["run_id"])["project_id"] == default
    explicit = process_folder({"folder_path": str(data), "data_types": ["CV"], "project_id": other})
    assert explicit["status"] == "success", explicit
    assert get_run_recipe(explicit["result"]["manifest"]["run"]["run_id"])["project_id"] == other


def test_lsv_record_replay_preserves_and_checks_ir_dependency(data):
    _write_tsv(data / "LSV_demo.txt", make_lsv_rows())
    eis = data / "EIS_demo.txt"
    eis.write_text("frequency zreal zimag\n100000 2.0 0.01\n10000 2.2 -0.1\n1000 2.8 -0.5\n")
    recipe = run(data, ["LSV"], {"ir_compensation_enabled": True, "ir_source": "eis", "ir_eis_search_scope": "specified_file", "ir_eis_file": str(eis)})
    assert {item["role"] for item in recipe["inputs"]} == {"primary", "ir_eis"}
    plan = build_replay_plan(recipe["run_id"], {"record_key": recipe["record_keys"][0]})
    assert plan["can_replay"], plan
    assert len(plan["source_checks"]) == 2
    assert process_folder(plan["payload"])["status"] == "success"
    eis.unlink()
    blocked = build_replay_plan(recipe["run_id"], {"record_key": recipe["record_keys"][0]})
    assert not blocked["can_replay"]
    assert any(item["role"] == "ir_eis" and item["state"] == "missing" for item in blocked["source_checks"])


def test_uploaded_peak_run_restores_relative_signal_dependencies(data):
    import io
    import json
    import zipfile

    from electrochem_v6.server.routes_post import _prepare_uploaded_zip_job, _process_prepared_uploaded_zip
    from test_v6_artifact_lifecycle import UploadHandler
    from test_v6_processing_coupled_pipeline import _write_peak_method, _write_peak_signal

    _write_peak_method(data / "method.json")
    _write_peak_signal(data / "signal.csv")
    (data / "products.csv").write_text("sample_name,signal_file,charge_C\nsample-a,signal.csv,385.94132848\n")
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        for name in ("method.json", "signal.csv", "products.csv"):
            archive.write(data / name, "analysis/" + name)

    class PeakUpload:
        def get_filename(self):
            return "peak.zip"

        def get_payload(self, decode=False):
            return content.getvalue()

    class PeakUploadHandler(UploadHandler):
        MAX_UPLOAD_FILE_BYTES = 1024 * 1024
        MAX_ZIP_UNCOMPRESSED_BYTES = 1024 * 1024

    fields = {"data_type": "COUPLED", "params": json.dumps({
        "coupled_input_mode": "peak_analysis", "coupled_products_file": "analysis/products.csv",
        "coupled_peak_method_source": "file", "coupled_peak_method_file": "analysis/method.json",
    })}
    prepared = _prepare_uploaded_zip_job(PeakUploadHandler(), fields, {"file": PeakUpload()})
    original = _process_prepared_uploaded_zip(prepared)
    assert original["status"] == "success", original
    recipe = get_run_recipe(original["result"]["manifest"]["run"]["run_id"])
    assert {item["archive_member"] for item in recipe["inputs"]} == {"analysis/products.csv", "analysis/method.json", "analysis/signal.csv"}
    assert not Path(recipe["folder_path"]).exists()
    plan = build_replay_plan(recipe["run_id"])
    assert plan["can_replay"], plan
    assert {item["role"] for item in plan["source_checks"]} == {"product_table", "peak_method", "signal"}
    replay = process_folder(plan["payload"])
    assert replay["status"] == "success", replay
    new = get_run_recipe(replay["result"]["manifest"]["run"]["run_id"])
    assert {item["archive_member"] for item in new["inputs"]} == {item["archive_member"] for item in recipe["inputs"]}


def test_partially_deleted_history_only_replays_retained_record(data):
    from electrochem_v6.store.run_recipes import update_run_recipe

    make_cv(data)
    make_cv(data, "CV_second.txt")
    recipe = run(data)
    retained, deleted = recipe["records"]
    update_run_recipe(recipe["run_id"], records=[retained], record_keys=[retained["record_key"]],
                      history_partially_deleted=True, deleted_record_keys=[deleted["record_key"]])
    whole = build_replay_plan(recipe["run_id"])
    assert not whole["can_replay"] and any("已有删除结果" in issue for issue in whole["issues"])
    assert not build_replay_plan(recipe["run_id"], {"record_key": deleted["record_key"]})["can_replay"]
    assert build_replay_plan(recipe["run_id"], {"record_key": retained["record_key"]})["can_replay"]
