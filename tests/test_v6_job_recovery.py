"""Recovery exercises process identity, actual preflight and durable claims."""

import hashlib
import json
import subprocess
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from electrochem_v6.config import user_config_dir
from electrochem_v6.core.job_recovery_service import (
    build_recovery_plan,
    list_recovery_items,
    reconcile_interrupted_work,
    resume_recovery,
    snapshot_queued_request,
    snapshot_uploaded_request,
)
from electrochem_v6.core.job_service import ProcessingJobManager
from electrochem_v6.core.process_owner import current_process_owner, inspect_process_owner
from electrochem_v6.core.process_service import process_folder
from electrochem_v6.store.database import Database
from electrochem_v6.store.job_recovery import associate_job_run, get_owned_job, recovery_claim, register_owned_job
from electrochem_v6.store.run_recipes import get_run_recipe, update_run_recipe
from electrochem_v6.store.runtime import get_database, reset_runtime


@pytest.fixture
def recovery_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    folder = tmp_path / "data"
    folder.mkdir()
    source = folder / "CV_demo.txt"
    source.write_text("Potential Current\n0 0\n0.2 0.0004\n0.4 0.001\n0.6 0.0003\n0.8 -0.0002\n", encoding="utf-8")
    yield source
    reset_runtime()


def dead_owner():
    return {**current_process_owner(), "start_token": "a-prior-process-creation-token"}


def seed(source, job_id="old", *, owner=None, files_only=False):
    payload = {"data_types": ["CV"], "params": {"area": 2}, "input_files": [str(source)]}
    if not files_only:
        payload["folder_path"] = str(source.parent)
    get_database().create_processing_job(job_id, kind="process", payload=payload)
    if owner is not None:
        register_owned_job(job_id, kind="process", owner=owner, payload=snapshot_queued_request(payload))
    return payload


def wait_job(job_id):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        item = get_database().get_processing_job(job_id)
        if item["status"] not in {"queued", "running"}:
            return item
        time.sleep(0.01)
    raise AssertionError("recovery job did not finish")


def test_actual_process_exit_and_pid_reuse_are_distinct_from_unknown_identity():
    code = "import sys,json,importlib.util;spec=importlib.util.spec_from_file_location('owner',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);print(json.dumps(m.current_process_owner()),flush=True);sys.stdin.read()"
    process = subprocess.Popen([sys.executable, "-c", code, str(Path(__file__).resolve().parents[1] / "src/electrochem_v6/core/process_owner.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        owner = json.loads(process.stdout.readline())
        assert inspect_process_owner(owner)["state"] == "alive"
        assert inspect_process_owner({**owner, "start_token": "old"})["state"] == "dead"
        assert inspect_process_owner({**owner, "host_id": "another-machine"})["state"] == "unknown"
        process.communicate(timeout=5)
        assert inspect_process_owner(owner)["state"] == "dead"
        assert inspect_process_owner(None)["state"] == "unknown"
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_second_manager_does_not_interrupt_other_live_work(recovery_data):
    started, release = threading.Event(), threading.Event()

    def runner(_payload):
        started.set()
        assert release.wait(5)
        return {"status": "success"}

    first = ProcessingJobManager(max_workers=1, process_runner=runner)
    second = None
    try:
        one = first.submit_process({"folder_path": str(recovery_data.parent), "data_types": ["CV"]})
        assert started.wait(3)
        queued = first.submit_process({"folder_path": str(recovery_data.parent), "data_types": ["CV"]})
        second = ProcessingJobManager(max_workers=1)
        assert get_database().get_processing_job(one["job_id"])["status"] == "running"
        assert get_database().get_processing_job(queued["job_id"])["status"] == "queued"
        assert list_recovery_items()["items"] == []
    finally:
        release.set()
        wait_job(one["job_id"])
        wait_job(queued["job_id"])
        first.shutdown()
        if second:
            second.shutdown()


def test_actual_abrupt_exit_leaves_running_and_queued_intents_recoverable(recovery_data):
    code = """
import json, os, sys, threading
sys.path.insert(0, sys.argv[1])
from electrochem_v6.core.job_service import ProcessingJobManager
started = threading.Event()
def runner(payload):
    started.set()
    threading.Event().wait(60)
manager = ProcessingJobManager(max_workers=1, process_runner=runner)
payload = {'folder_path': sys.argv[2], 'data_types': ['CV']}
one = manager.submit_process(payload)
assert started.wait(5)
two = manager.submit_process(payload)
print('RECOVERY_JOBS:' + json.dumps([one['job_id'], two['job_id']]), flush=True)
sys.stdin.readline()
os._exit(0)
"""
    process = subprocess.Popen([sys.executable, "-c", code, str(Path(__file__).resolve().parents[1] / "src"), str(recovery_data.parent)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    try:
        for line in process.stdout:
            if line.startswith("RECOVERY_JOBS:"):
                ids = json.loads(line.partition(":")[2])
                break
        else:
            raise AssertionError("child failed to persist jobs")
        assert all(inspect_process_owner(get_owned_job(identifier)["owner"])["state"] == "alive" for identifier in ids)
        assert reconcile_interrupted_work() == {"jobs": 0, "runs": 0}
        process.communicate(input="exit\n", timeout=5)
        assert reconcile_interrupted_work() == {"jobs": 2, "runs": 0}
        assert all(get_database().get_processing_job(identifier)["status"] == "interrupted" for identifier in ids)
        assert {item["job_id"] for item in list_recovery_items()["items"]} == set(ids)
        assert all(build_recovery_plan("job:" + identifier)["can_recover"] for identifier in ids)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_dead_queued_snapshot_survives_bounded_job_history_and_files_only_preflights(recovery_data):
    seed(recovery_data, owner=dead_owner(), files_only=True)
    assert reconcile_interrupted_work()["jobs"] == 1
    assert get_database().get_processing_job("old")["status"] == "interrupted"
    with get_database().transaction() as connection:
        connection.execute("DELETE FROM processing_jobs WHERE job_id='old'")
    plan = build_recovery_plan("job:old")
    assert plan["can_recover"], plan
    assert plan["params"]["area"] == 2
    assert plan["payload"]["folder_path"] == str(recovery_data.parent)
    assert plan["payload"]["params"]["output_run_dir_enabled"] is True


def test_legacy_unknown_requires_confirmation_and_preserves_original_status(recovery_data):
    seed(recovery_data)
    reconcile_interrupted_work()
    assert get_database().get_processing_job("old")["status"] == "queued"
    assert not build_recovery_plan("job:old")["can_recover"]
    assert build_recovery_plan("job:old", {"confirm_owner_stopped": True})["can_recover"]
    assert get_database().get_processing_job("old")["status"] == "queued"


def test_active_owner_cannot_be_bypassed_by_manual_confirmation(recovery_data):
    seed(recovery_data, owner=current_process_owner())
    with pytest.raises(ValueError):
        build_recovery_plan("job:old", {"confirm_owner_stopped": True})


def test_missing_queued_file_can_be_relocated_twice_with_stable_original_key(recovery_data):
    seed(recovery_data, owner=dead_owner())
    moved = recovery_data.with_name("CV_moved.txt")
    recovery_data.rename(moved)
    plan = build_recovery_plan("job:old")
    assert not plan["can_recover"]
    assert plan["source_checks"][0]["state"] == "missing"
    assert plan["source_checks"][0]["path"] == str(recovery_data)
    options = {"source_paths": {str(recovery_data): str(moved)}}
    plan = build_recovery_plan("job:old", options)
    assert plan["can_recover"], plan
    assert plan["source_checks"][0]["path"] == str(recovery_data)
    assert plan["source_checks"][0]["resolved_path"] == str(moved)
    second = moved.with_name("CV_twice.txt")
    moved.rename(second)
    assert build_recovery_plan("job:old", {"source_paths": {str(recovery_data): str(second)}})["can_recover"]


@pytest.mark.parametrize("run_status", ["success", "succeeded"])
def test_completed_recipe_with_unfinished_job_is_not_reprocessed(recovery_data, run_status):
    payload = seed(recovery_data, owner=dead_owner())
    result = process_folder(payload)
    run_id = result["result"]["manifest"]["run"]["run_id"]
    associate_job_run("old", run_id)
    update_run_recipe(run_id, status=run_status, owner=dead_owner(), job_id="old")
    plan = build_recovery_plan("job:old")
    assert not plan["can_recover"]
    assert "完成" in plan["issues"][0]


def test_terminal_change_during_preflight_prevents_submission(recovery_data, monkeypatch):
    import electrochem_v6.core.process_service as processing

    seed(recovery_data)
    actual = processing.preflight_process_folder

    def finishes_during_preflight(payload):
        result = actual(payload)
        get_database().update_processing_job("old", status="succeeded")
        return result

    monkeypatch.setattr(processing, "preflight_process_folder", finishes_during_preflight)
    manager = ProcessingJobManager(max_workers=1)
    try:
        with pytest.raises(ValueError):
            resume_recovery("job:old", {"confirm_owner_stopped": True}, manager)
        assert recovery_claim("job:old") is None
    finally:
        manager.shutdown()


def test_atomic_claim_checks_origin_status_again(recovery_data):
    seed(recovery_data)
    get_database().update_processing_job("old", status="succeeded")
    with pytest.raises(ValueError, match="已完成"):
        register_owned_job("new", kind="process", owner=current_process_owner(), payload={}, recovery_source="job:old", recovery_origin={"job_id": "old"})
    assert recovery_claim("job:old") is None
    assert get_owned_job("new") is None


def test_cross_instance_claims_are_atomic_and_idempotent(tmp_path, monkeypatch):
    import electrochem_v6.store.job_recovery as store

    db_path = str(tmp_path / "shared.db")
    first, second = Database(db_path), Database(db_path)
    first.create_processing_job("old", kind="process", payload={})
    local = threading.local()
    monkeypatch.setattr(store, "get_database", lambda: local.database)
    barrier = threading.Barrier(2)

    def submit(database, job_id):
        local.database = database
        store.ensure_recovery_schema()
        barrier.wait(timeout=5)
        return register_owned_job(job_id, kind="process", owner={}, payload={}, recovery_source="job:old", recovery_origin={"job_id": "old"})

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit, first, "one"), pool.submit(submit, second, "two")]
            results = [future.result(timeout=10) for future in futures]
        assert sum(item["created"] for item in results) == 1
        assert results[0]["job_id"] == results[1]["job_id"]
    finally:
        first.close_all()
        second.close_all()


def test_reviewed_sources_cannot_silently_change_before_resume(recovery_data):
    seed(recovery_data, owner=dead_owner())
    plan = build_recovery_plan("job:old")
    recovery_data.write_text(recovery_data.read_text() + "1.0 -0.0003\n")
    manager = ProcessingJobManager(max_workers=1)
    try:
        result = resume_recovery("job:old", {"preflight_token": plan["preflight_token"]}, manager)
        assert result["status"] == "error"
        assert recovery_claim("job:old") is None
    finally:
        manager.shutdown()


def test_captured_interrupted_run_recovers_into_new_output_and_preserves_original(recovery_data):
    result = process_folder({"folder_path": str(recovery_data.parent), "data_types": ["CV"]})
    old_id = result["result"]["manifest"]["run"]["run_id"]
    old = get_run_recipe(old_id)
    original_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in Path(old["output_dir"]).rglob("*") if path.is_file()}
    update_run_recipe(old_id, status="running", owner=dead_owner())
    manager = ProcessingJobManager(max_workers=1)
    try:
        submitted = resume_recovery("run:" + old_id, {}, manager)
        duplicate = resume_recovery("run:" + old_id, {}, manager)
        assert duplicate["job_id"] == submitted["job_id"]
        job = wait_job(submitted["job_id"])
        assert job["status"] == "succeeded", job
        new_id = job["result"]["result"]["manifest"]["run"]["run_id"]
        new = get_run_recipe(new_id)
        assert new_id != old_id and new["parent_run_id"] == old_id
        assert new["output_dir"] != old["output_dir"]
        assert all(get_database().get_history_record(key) for key in old["record_keys"])
        assert original_hashes == {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in original_hashes}
        assert get_run_recipe(old_id)["status"] == "interrupted"
    finally:
        manager.shutdown()


def prepared_zip(source):
    root = user_config_dir() / "runs" / "uploads" / "recovery-seed"
    root.mkdir(parents=True)
    archive = root / "input.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.write(source, "samples/CV_demo.txt")
    return {"run_root": str(root), "zip_path": str(archive),
            "source_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "data_type": "CV", "project_name": "Recovered upload", "params": {"area": 2},
            "max_zip_files": 10, "max_zip_uncompressed_bytes": 100000, "original_filename": "input.zip"}


def test_agent_upload_saves_only_process_request_and_injects_real_job_identity(recovery_data):
    entered, release = threading.Event(), threading.Event()
    observed = []

    def runner(payload, **_kwargs):
        observed.append(payload)
        entered.set()
        assert release.wait(5)
        return {"status": "success"}

    manager = ProcessingJobManager(max_workers=1, agent_runner=runner)
    try:
        submitted = manager.submit_agent({"_prepared_upload": prepared_zip(recovery_data), "api_key": "private-key", "message": "private-prompt"})
        assert entered.wait(3)
        owned = get_owned_job(submitted["job_id"])
        assert owned["kind"] == "process"
        serialized = json.dumps(owned)
        assert "private-key" not in serialized and "private-prompt" not in serialized
        assert observed[0]["_prepared_upload"]["_job_id"] == submitted["job_id"]
        assert observed[0]["_prepared_upload"]["_job_owner"] == current_process_owner()
    finally:
        release.set()
        wait_job(submitted["job_id"])
        manager.shutdown()


def test_dead_queued_zip_recovery_creates_a_provenance_complete_process_run(recovery_data):
    prepared = prepared_zip(recovery_data)
    get_database().create_processing_job("zip-old", kind="agent", payload={"_prepared_upload": prepared})
    register_owned_job("zip-old", kind="process", owner=dead_owner(), payload=snapshot_uploaded_request(prepared))
    plan = build_recovery_plan("job:zip-old")
    assert plan["can_recover"], plan
    assert plan["source_checks"][0]["role"] == "source_archive"
    assert plan["source_checks"][0]["state"] == "unchanged"
    manager = ProcessingJobManager(max_workers=1)
    try:
        result = resume_recovery("job:zip-old", {"preflight_token": plan["preflight_token"]}, manager)
        assert result["status"] == "success", result
        job = wait_job(result["job_id"])
        assert job["status"] == "succeeded", job
        recipe = get_run_recipe(job["result"]["result"]["manifest"]["run"]["run_id"])
        assert recipe["recovered_from_job_id"] == "zip-old"
        assert recipe["source_archive_sha256"] == prepared["source_archive_sha256"]
        assert recipe["source_archive_path"] == prepared["zip_path"]
        assert recipe["inputs"][0]["archive_member"] == "samples/CV_demo.txt"
        assert recipe["params"]["area"] == 2
        assert get_database().get_processing_job("zip-old")["status"] == "interrupted"
        assert hashlib.sha256(Path(prepared["zip_path"]).read_bytes()).hexdigest() == prepared["source_archive_sha256"]
    finally:
        manager.shutdown()
