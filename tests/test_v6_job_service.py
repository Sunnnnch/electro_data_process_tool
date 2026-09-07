import threading
import time

from electrochem_v6.core.job_control import (
    NON_CANCELLABLE_PROGRESS_PREFIX,
    ProcessingCancelledError,
)
from electrochem_v6.core.job_service import ProcessingJobManager
from electrochem_v6.store.database import Database
from electrochem_v6.store.runtime import get_database, reset_runtime


def _wait_for_job(job_id, terminal=("succeeded", "failed", "cancelled"), timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = get_database().get_processing_job(job_id)
        if job and job.get("status") in terminal:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def test_processing_job_manager_persists_progress_and_result(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()

    def runner(payload):
        payload["_progress_callback"](1, 2, "first.txt")
        payload["_progress_callback"](2, 2, "second.txt")
        return {"status": "success", "result": {"summary": "done"}}

    manager = ProcessingJobManager(max_workers=1, process_runner=runner)
    try:
        submitted = manager.submit_process({"folder_path": str(tmp_path)})
        job = _wait_for_job(submitted["job_id"])
        assert job["status"] == "succeeded"
        assert job["progress_current"] == 2
        assert job["progress_total"] == 2
        assert job["result"]["result"]["summary"] == "done"
    finally:
        manager.shutdown()
        reset_runtime()


def test_processing_job_manager_cooperatively_cancels_running_job(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    started = threading.Event()

    def runner(payload):
        started.set()
        while not payload["_cancel_check"]():
            time.sleep(0.01)
        raise ProcessingCancelledError("cancelled in test work unit")

    manager = ProcessingJobManager(max_workers=1, process_runner=runner)
    try:
        submitted = manager.submit_process({"folder_path": str(tmp_path)})
        assert started.wait(timeout=2)
        assert manager.cancel(submitted["job_id"]) is True
        job = _wait_for_job(submitted["job_id"])
        assert job["status"] == "cancelled"
        assert job["cancel_requested"] is True
        assert "cancelled" in job["error"]
    finally:
        manager.shutdown()
        reset_runtime()


def test_processing_job_recovery_marks_active_rows_interrupted(tmp_path):
    db = Database(str(tmp_path / "jobs.db"))
    db.create_processing_job("queued-job", kind="process", payload={})
    db.create_processing_job("running-job", kind="process", payload={})
    db.update_processing_job("running-job", status="running")

    assert db.interrupt_active_processing_jobs() == 2
    assert db.get_processing_job("queued-job")["status"] == "interrupted"
    assert db.get_processing_job("running-job")["status"] == "interrupted"


def test_agent_job_manager_persists_progress_and_reply(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()

    def agent_runner(payload, *, progress_callback, cancel_check):
        assert payload["message"] == "hello"
        assert cancel_check() is False
        progress_callback("thinking")
        return {
            "status": "success",
            "conversation_id": "c1",
            "agent_reply": "world",
            "messages": [{"role": "user", "content": "hello"}],
            "conversation": {"conversation_id": "c1", "messages": []},
            "processing_result": {"large": "snapshot"},
        }

    manager = ProcessingJobManager(max_workers=1, agent_runner=agent_runner)
    try:
        submitted = manager.submit_agent({"message": "hello"})
        job = _wait_for_job(submitted["job_id"])
        assert job["kind"] == "agent"
        assert job["status"] == "succeeded"
        assert job["progress_current"] == 10
        assert job["result"]["agent_reply"] == "world"
        assert job["payload"] == {"conversation_id": "c1"}
        assert "messages" not in job["result"]
        assert "conversation" not in job["result"]
        assert job["result"]["processing_result"] == {"large": "snapshot"}
    finally:
        manager.shutdown()
        reset_runtime()


def test_agent_job_manager_cooperatively_cancels_stream(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    started = threading.Event()

    def agent_runner(_payload, *, progress_callback, cancel_check):
        started.set()
        while not cancel_check():
            progress_callback("streaming")
            time.sleep(0.01)
        raise ProcessingCancelledError("AI request was cancelled")

    manager = ProcessingJobManager(max_workers=1, agent_runner=agent_runner)
    try:
        submitted = manager.submit_agent({"message": "hello"})
        assert started.wait(timeout=2)
        assert manager.cancel(submitted["job_id"]) is True
        job = _wait_for_job(submitted["job_id"])
        assert job["status"] == "cancelled"
        assert job["cancel_requested"] is True
    finally:
        manager.shutdown()
        reset_runtime()


def test_confirmed_write_phase_rejects_cancel_and_finishes_successfully(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    write_started = threading.Event()
    allow_finish = threading.Event()

    def agent_runner(_payload, *, progress_callback, cancel_check):
        assert cancel_check() is False
        progress_callback(f"{NON_CANCELLABLE_PROGRESS_PREFIX}writing confirmed output")
        assert cancel_check() is False
        write_started.set()
        assert allow_finish.wait(timeout=2)
        return {
            "status": "success",
            "write_action_started": True,
            "write_action_succeeded": True,
        }

    manager = ProcessingJobManager(max_workers=1, agent_runner=agent_runner)
    try:
        submitted = manager.submit_agent({"message": "confirm"})
        assert write_started.wait(timeout=2)
        assert manager.cancel(submitted["job_id"]) is False
        allow_finish.set()
        job = _wait_for_job(submitted["job_id"])
        assert job["status"] == "succeeded"
        assert job["cancel_requested"] is False
        assert job["result"]["write_action_succeeded"] is True
    finally:
        allow_finish.set()
        manager.shutdown()
        reset_runtime()
