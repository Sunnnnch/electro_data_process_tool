import io
import os
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from electrochem_v6.core.artifact_lifecycle import (
    create_active_upload_root,
    finish_uploaded_run,
)
from electrochem_v6.core.job_service import ProcessingJobManager
from electrochem_v6.core.storage_service import cleanup_orphaned_runs, storage_summary
from electrochem_v6.server.routes_post import (
    _prepare_uploaded_zip_job,
    _process_prepared_uploaded_zip,
)
from electrochem_v6.store.runtime import get_database, reset_runtime


class UploadHandler:
    MAX_UPLOAD_FILE_BYTES = 100000
    MAX_ZIP_FILES = 10
    MAX_ZIP_UNCOMPRESSED_BYTES = 100000


class UploadItem:
    def get_filename(self):
        return "data.zip"

    def get_payload(self, decode=False):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("CV_demo.txt", "Potential Current\n0 0\n0.2 0.0004\n0.4 0.001\n0.6 0.0003\n0.8 -0.0002\n")
        return buffer.getvalue()


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(root))
    reset_runtime()
    yield root
    reset_runtime()


def prepare():
    return _prepare_uploaded_zip_job(UploadHandler(), {"data_type": "CV"}, {"file": UploadItem()})


@pytest.mark.parametrize("stop_action", ["cancel", "shutdown"])
def test_prepared_and_queued_upload_survive_cleanup_and_cancel_removes_lease(isolated_runtime, stop_action):
    started = threading.Event()
    release = threading.Event()

    def blocker(payload):
        started.set()
        assert release.wait(5)
        return {"status": "success"}

    manager = ProcessingJobManager(max_workers=1, process_runner=blocker, agent_runner=lambda *a, **k: {})
    prepared = prepare()
    try:
        assert storage_summary()["active_runs"] == 1
        assert cleanup_orphaned_runs()["removed"] == []
        manager.submit_process({})
        assert started.wait(2)
        job = manager.submit_agent({"_prepared_upload": prepared})
        assert get_database().get_processing_job(job["job_id"])["status"] == "queued"
        assert cleanup_orphaned_runs()["removed"] == []
        assert Path(prepared["zip_path"]).is_file()
        if stop_action == "cancel":
            assert manager.cancel(job["job_id"])
        else:
            manager.shutdown()
        assert get_database().get_processing_job(job["job_id"])["status"] == "cancelled"
        assert not Path(prepared["run_root"]).exists()
    finally:
        release.set()
        manager.shutdown()
        manager._executor.shutdown(wait=True)
        finish_uploaded_run(prepared["run_root"])


def test_running_upload_is_protected_until_history_reference_is_attached(isolated_runtime, monkeypatch):
    import electrochem_v6.server.routes_post as routes

    entered = threading.Event()
    release = threading.Event()
    real_process = routes.process_folder

    def process(payload):
        entered.set()
        assert release.wait(5)
        return real_process(payload)

    monkeypatch.setattr(routes, "process_folder", process)
    prepared = prepare()
    result = {}
    worker = threading.Thread(target=lambda: result.update(_process_prepared_uploaded_zip(prepared)))
    worker.start()
    try:
        assert entered.wait(2)
        assert cleanup_orphaned_runs()["removed"] == []
        release.set()
        worker.join(10)
        assert not worker.is_alive()
        assert result["status"] == "success"
        assert storage_summary()["active_runs"] == 0
        assert storage_summary()["referenced_runs"] == 1
        assert cleanup_orphaned_runs()["removed"] == []
        assert Path(prepared["zip_path"]).is_file()
    finally:
        release.set()
        worker.join(10)
        finish_uploaded_run(prepared["run_root"])


def test_failed_upload_releases_and_removes_reservation(isolated_runtime):
    prepared = prepare()
    Path(prepared["zip_path"]).write_bytes(b"invalid zip")
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        _process_prepared_uploaded_zip(prepared)
    assert not Path(prepared["run_root"]).exists()
    assert storage_summary()["active_runs"] == 0


@pytest.mark.parametrize("creation_delay", [0, 2.25], ids=["normal-creation", "delayed-creation"])
def test_cleanup_cannot_interleave_directory_creation_and_lease_acquisition(isolated_runtime, monkeypatch, creation_delay):
    import electrochem_v6.core.storage_service as storage

    target = (isolated_runtime / "runs" / "uploads" / "creating").resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    timeout = 10
    created = threading.Event()
    finish_creation = threading.Event()
    cleaner_started = threading.Event()
    cleaner_entered = threading.Event()
    cleaner_finished = threading.Event()
    errors = []
    original = Path.mkdir
    original_summary = storage._storage_summary

    def mkdir(path, *args, **kwargs):
        if path == target:
            time.sleep(creation_delay)
        result = original(path, *args, **kwargs)
        if path == target:
            created.set()
            assert finish_creation.wait(timeout), "creation was not released"
        return result

    def observed_summary():
        # Called inside the real storage lock. Cleanup must not reach this read
        # while mkdir has published the directory but not yet acquired its lease.
        cleaner_entered.set()
        return original_summary()

    def create():
        try:
            create_active_upload_root(target)
        except BaseException as error:
            errors.append(error)

    def clean():
        cleaner_started.set()
        try:
            clean_result.update(cleanup_orphaned_runs())
        except BaseException as error:
            errors.append(error)
        finally:
            cleaner_finished.set()

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(storage, "_storage_summary", observed_summary)
    creator = threading.Thread(target=create, name="upload-creator")
    clean_result = {}
    cleaner = threading.Thread(target=clean, name="upload-cleaner")
    creator.start()
    try:
        assert created.wait(timeout), f"directory was not created: {errors!r}"
        cleaner.start()
        assert cleaner_started.wait(timeout), "cleanup worker did not start"
        assert not cleaner_entered.wait(0.2), "cleanup entered before the upload lease was acquired"
        assert not cleaner_finished.is_set()
        finish_creation.set()
        creator.join(timeout)
        cleaner.join(timeout)
        assert not creator.is_alive() and not cleaner.is_alive()
        assert not errors, errors
        assert cleaner_entered.is_set() and cleaner_finished.is_set()
        assert clean_result["removed"] == []
        assert target.is_dir()
        assert clean_result["summary"]["active_runs"] == 1
        assert (target / ".active-upload.lock").is_file()
    finally:
        finish_creation.set()
        creator.join(timeout)
        if cleaner.ident:
            cleaner.join(timeout)
        finish_uploaded_run(target)


def test_other_process_lease_is_protected_and_crash_leftovers_are_reclaimable(isolated_runtime):
    target = isolated_runtime / "runs" / "uploads" / "other-process"
    ready = isolated_runtime / "ready"
    script = """
import os, sys
from pathlib import Path
from electrochem_v6.core.artifact_lifecycle import create_active_upload_root
create_active_upload_root(Path(sys.argv[1]))
Path(sys.argv[2]).write_text('ready')
sys.stdin.read(1)
os._exit(0)
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    child = subprocess.Popen([sys.executable, "-c", script, str(target), str(ready)], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        assert cleanup_orphaned_runs()["removed"] == []
        child.communicate(b"x", timeout=5)
        assert child.returncode == 0
        assert cleanup_orphaned_runs()["removed"] == [str(target.resolve())]
        assert not target.exists()
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)


def test_storage_lock_timeout_returns_retryable_error(tmp_path, monkeypatch):
    import electrochem_v6.core.artifact_lifecycle as lifecycle

    def busy(*args):
        raise OSError("lock held by another process")

    if os.name == "nt":
        import msvcrt

        monkeypatch.setattr(msvcrt, "locking", busy)
    else:
        import fcntl

        monkeypatch.setattr(fcntl, "flock", busy)
    times = iter([0.0, 11.0])
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: next(times))
    with (tmp_path / "busy.lock").open("w+b") as handle:
        handle.write(b"0")
        with pytest.raises(ValueError, match="稍后重试"):
            lifecycle._lock_file(handle, blocking=True)
