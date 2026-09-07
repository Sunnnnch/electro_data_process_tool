"""Upload recovery uses durable archive evidence before a run can finish."""

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from electrochem_v6.core.artifact_lifecycle import finish_uploaded_run
from electrochem_v6.core.process_service import preflight_process_folder
from electrochem_v6.core.replay_archive import restore_uploaded_sources
from electrochem_v6.core.storage_service import cleanup_orphaned_runs, storage_summary
from electrochem_v6.core.upload_recovery import PREPARED_UPLOAD_SNAPSHOT_KEYS, prepare_queued_upload_recovery
from electrochem_v6.server.routes_post import (
    _prepare_uploaded_zip_job,
    _process_prepared_uploaded_zip,
    _process_uploaded_zip,
)
from electrochem_v6.store.job_recovery import finish_owned_job, register_owned_job
from electrochem_v6.store.run_recipes import get_run_recipe, list_run_recipes_page
from electrochem_v6.store.runtime import get_database, reset_runtime

CV_TEXT = "Potential Current\n0 0\n0.2 0.0004\n0.4 0.001\n0.6 0.0003\n0.8 -0.0002\n"


class UploadHandler:
    MAX_UPLOAD_FILE_BYTES = 100000
    MAX_ZIP_FILES = 10
    MAX_ZIP_UNCOMPRESSED_BYTES = 100000


class UploadItem:
    def get_filename(self):
        return "original.zip"

    def get_payload(self, decode=False):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("CV_demo.txt", CV_TEXT)
            archive.writestr("auxiliary/calibration.json", '{"slope": 2}')
        return buffer.getvalue()


@pytest.fixture
def upload_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(root))
    reset_runtime()
    yield root
    reset_runtime()


def prepare():
    return _prepare_uploaded_zip_job(UploadHandler(), {"data_type": "CV"}, {"file": UploadItem()})


@pytest.mark.parametrize("queued", [False, True])
def test_interrupted_upload_recipe_retains_zip_and_restores_expired_inputs(upload_runtime, monkeypatch, queued):
    import electrochem_v6.core.process_service as service
    import electrochem_v6.server.routes_post as routes

    class InterruptedProcess(BaseException):
        pass

    payloads = []
    real_process = routes.process_folder

    def process(payload):
        payloads.append(payload)
        return real_process(payload)

    def interrupt(*args, **kwargs):
        raise InterruptedProcess("process terminated after recipe capture")

    monkeypatch.setattr(routes, "process_folder", process)
    monkeypatch.setattr(service, "_run_selected_modules", interrupt)
    with pytest.raises(InterruptedProcess):
        if queued:
            _process_prepared_uploaded_zip(prepare())
        else:
            _process_uploaded_zip(UploadHandler(), {"data_type": "CV"}, {"file": UploadItem()})
    source = payloads[0]["_upload_source"]
    assert set(source["archive_members"].values()) == {"CV_demo.txt", "auxiliary/calibration.json"}
    assert Path(source["source_archive_path"]).is_absolute()
    assert not Path(source["input_root"]).exists()
    recipe = get_run_recipe(list_run_recipes_page()["runs"][0]["run_id"])
    assert recipe["status"] == "running"
    assert recipe["source_archive_path"] == source["source_archive_path"]
    assert recipe["source_archive_sha256"] == hashlib.sha256(Path(source["source_archive_path"]).read_bytes()).hexdigest()
    assert recipe["inputs"][0]["archive_member"] == "CV_demo.txt"
    assert recipe["artifact_root"] == source["artifact_root"]
    assert storage_summary()["active_runs"] == 0
    assert storage_summary()["referenced_runs"] == 1
    assert cleanup_orphaned_runs()["removed"] == []
    assert get_database().count_artifact_root_references(source["artifact_root"]) >= 1
    restored = restore_uploaded_sources(recipe, recipe["inputs"])
    recovered = Path(restored["source_paths"][recipe["inputs"][0]["path"]])
    assert recovered.read_text() == CV_TEXT
    assert (recovered.parent / "auxiliary" / "calibration.json").is_file()
    assert Path(recipe["output_dir"]).is_dir()


def test_queued_snapshot_retains_zip_after_owner_exit_and_cache_reuse_preserves_outputs(upload_runtime):
    prepared = prepare()
    snapshot = {key: prepared[key] for key in PREPARED_UPLOAD_SNAPSHOT_KEYS}
    register_owned_job("queued-upload", kind="process", owner={}, payload={"_prepared_upload": snapshot})
    finish_uploaded_run(prepared["run_root"], keep=True)  # The process lease is now gone.
    assert not list_run_recipes_page()["runs"]
    assert storage_summary()["active_runs"] == 0
    assert storage_summary()["referenced_runs"] == 1
    assert cleanup_orphaned_runs()["removed"] == []
    first = prepare_queued_upload_recovery(snapshot)
    assert not first["issues"], first
    assert first["source_checks"][0]["state"] == "unchanged"
    payload = first["payload"]
    assert "output_dir" not in payload and "run_id" not in payload
    assert payload["params"]["output_run_dir_enabled"] is True
    preflight = preflight_process_folder(payload)
    assert preflight["status"] == "success"
    assert preflight["preflight"]["selected_matched"] == 1
    generated = Path(payload["folder_path"]) / "electrochem_outputs" / "previous-recovery" / "result.txt"
    generated.parent.mkdir(parents=True)
    generated.write_text("keep the previous output", encoding="utf-8")
    second = prepare_queued_upload_recovery(snapshot)
    assert not second["issues"], second
    assert second["payload"] == payload
    assert generated.read_text() == "keep the previous output"
    assert cleanup_orphaned_runs()["removed"] == []
    finish_owned_job("queued-upload")
    assert cleanup_orphaned_runs()["removed"] == [str(Path(prepared["run_root"]).resolve())]


@pytest.mark.parametrize("change", ["missing", "changed", "no_fingerprint"])
def test_queued_zip_source_failures_are_explicit_and_do_not_extract(upload_runtime, change):
    prepared = prepare()
    try:
        if change == "missing":
            Path(prepared["zip_path"]).unlink()
        elif change == "changed":
            Path(prepared["zip_path"]).write_bytes(b"replacement data")
        else:
            prepared.pop("source_archive_sha256")
        result = prepare_queued_upload_recovery(prepared)
        assert result["payload"] is None and result["issues"]
        assert result["source_checks"][0]["path"] == prepared["zip_path"]
        assert result["source_checks"][0]["state"] == {"no_fingerprint": "unverified"}.get(change, change)
        assert not (Path(prepared["run_root"]) / "recovery_sources").exists()
    finally:
        finish_uploaded_run(prepared["run_root"])


def test_relocated_identical_zip_retains_original_source_key(upload_runtime):
    prepared = prepare()
    try:
        moved = upload_runtime / "relocated.zip"
        Path(prepared["zip_path"]).rename(moved)
        result = prepare_queued_upload_recovery(prepared, {prepared["zip_path"]: str(moved)})
        assert not result["issues"], result
        check = result["source_checks"][0]
        assert check["path"] == prepared["zip_path"]
        assert check["resolved_path"] == str(moved)
        assert result["payload"]["_upload_source"]["source_archive_path"] == str(moved)
    finally:
        finish_uploaded_run(prepared["run_root"])


@pytest.mark.parametrize("change", ["modified", "missing", "extra"])
def test_cache_changes_block_without_overwriting_user_or_previous_run_files(upload_runtime, change):
    prepared = prepare()
    try:
        first = prepare_queued_upload_recovery(prepared)
        assert not first["issues"], first
        data = Path(first["payload"]["folder_path"])
        source = data / "CV_demo.txt"
        if change == "modified":
            source.write_text("changed", encoding="utf-8")
        elif change == "missing":
            source.unlink()
        else:
            (data / "CV_extra.txt").write_text(CV_TEXT)
        second = prepare_queued_upload_recovery(prepared)
        assert second["payload"] is None and second["issues"]
        assert "缓存" in second["issues"][0]
        if change == "modified":
            assert source.read_text() == "changed"
        if change == "missing":
            assert not source.exists()
        if change == "extra":
            assert (data / "CV_extra.txt").is_file()
    finally:
        finish_uploaded_run(prepared["run_root"])


@pytest.mark.parametrize("invalid", ["traversal", "entry_limit", "outside_root"])
def test_queued_recovery_enforces_extraction_limits_and_managed_root(upload_runtime, invalid):
    prepared = prepare()
    original_root = prepared["run_root"]
    try:
        if invalid == "traversal":
            with zipfile.ZipFile(prepared["zip_path"], "w") as archive:
                archive.writestr("../escape.txt", "bad")
            prepared["source_archive_sha256"] = hashlib.sha256(Path(prepared["zip_path"]).read_bytes()).hexdigest()
        elif invalid == "entry_limit":
            prepared["max_zip_files"] = 1
        else:
            prepared["run_root"] = str(upload_runtime.parent / "arbitrary")
        result = prepare_queued_upload_recovery(prepared)
        assert result["payload"] is None and result["issues"]
        assert not (upload_runtime.parent / "arbitrary").exists()
        assert not list(Path(original_root).rglob("escape.txt"))
        assert not list(Path(original_root).rglob("queued_*"))
    finally:
        finish_uploaded_run(original_root)


def test_invalid_snapshot_json_does_not_gain_archive_reference(upload_runtime):
    register_owned_job("non-upload", kind="process", owner={}, payload={"_prepared_upload": "invalid"})
    assert get_database().get_managed_artifact_roots() == []
    assert get_database().count_artifact_root_references(str(upload_runtime)) == 0
