"""Desktop exit must drain this executor without losing or cancelling other work."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.client import HTTPConnection, HTTPResponse
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from electrochem_v6.core.job_control import (
    NON_CANCELLABLE_PROGRESS_PREFIX,
    ProcessingCancelledError,
)
from electrochem_v6.core.job_service import ProcessingJobManager
from electrochem_v6.store.runtime import get_database, reset_runtime


class _Lifecycle:
    def __init__(self) -> None:
        self.managers: list[ProcessingJobManager] = []
        self.events: list[threading.Event] = []

    def event(self) -> threading.Event:
        event = threading.Event()
        self.events.append(event)
        return event

    def manager(self, **kwargs: Any) -> ProcessingJobManager:
        manager = ProcessingJobManager(max_workers=1, **kwargs)
        self.managers.append(manager)
        return manager

    @staticmethod
    def drain(manager: ProcessingJobManager) -> None:
        # Wait for callbacks too, so resetting SQLite cannot race a worker cleanup.
        manager._executor.shutdown(wait=True)
        assert manager.active_jobs() == []

    def close(self) -> None:
        for event in self.events:
            event.set()
        for manager in self.managers:
            manager.shutdown()
            manager._executor.shutdown(wait=True)


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "data"))
    for name in ("HISTORY", "PROJECTS", "TEMPLATES", "CONVERSATION"):
        monkeypatch.delenv(f"ELECTROCHEM_V6_{name}_FILE", raising=False)
    reset_runtime()
    harness = _Lifecycle()
    try:
        yield harness
    finally:
        harness.close()
        reset_runtime()


def _job(job_id: str) -> dict[str, Any]:
    job = get_database().get_processing_job(job_id)
    assert job is not None
    return job


def test_wait_exit_preserves_running_and_queued_work_and_closes_both_submitters(lifecycle):
    started = lifecycle.event()
    release = lifecycle.event()
    observations = []

    def process(payload):
        started.set()
        assert release.wait(10)
        observations.append(("process", payload["_cancel_check"]()))
        return {"status": "success"}

    def agent(_payload, *, progress_callback, cancel_check):
        observations.append(("agent", cancel_check()))
        progress_callback("finished queued read")
        return {"status": "success", "agent_reply": "done"}

    manager = lifecycle.manager(process_runner=process, agent_runner=agent)
    first = manager.submit_process({})["job_id"]
    assert started.wait(5)
    second = manager.submit_agent({"message": "queued read"})["job_id"]
    active = {item["job_id"]: item for item in manager.begin_desktop_exit(cancel=False)}
    assert set(active) == {first, second}
    assert active[first]["status"] == "running"
    assert active[second]["status"] == "queued"
    assert all(not item["cancel_requested"] for item in active.values())
    for submit in (manager.submit_process, manager.submit_agent):
        with pytest.raises(RuntimeError, match="closed"):
            submit({})
    release.set()
    lifecycle.drain(manager)
    assert observations == [("process", False), ("agent", False)]
    for job_id in (first, second):
        assert _job(job_id)["status"] == "succeeded"
        assert _job(job_id)["cancel_requested"] is False


@pytest.mark.parametrize("kind", ["process", "agent"])
def test_cancel_exit_remains_active_until_cooperative_cancellation_is_applied(lifecycle, kind):
    started = lifecycle.event()
    observed_cancel = lifecycle.event()
    safe_boundary = lifecycle.event()
    called = []

    def run(cancel_check):
        called.append(kind)
        started.set()
        deadline = time.monotonic() + 10
        while not cancel_check():
            assert time.monotonic() < deadline
            observed_cancel.wait(0.005)
        observed_cancel.set()
        assert safe_boundary.wait(10)
        raise ProcessingCancelledError("stopped at a safe work-unit boundary")

    def process(payload):
        return run(payload["_cancel_check"])

    def agent(_payload, *, progress_callback, cancel_check):
        return run(cancel_check)

    manager = lifecycle.manager(process_runner=process, agent_runner=agent)
    submit = manager.submit_process if kind == "process" else manager.submit_agent
    first = submit({})["job_id"]
    assert started.wait(5)
    queued = submit({})["job_id"]
    remaining = manager.begin_desktop_exit(cancel=True)
    assert observed_cancel.wait(5)
    assert [item["job_id"] for item in remaining] == [first]
    assert remaining[0]["cancel_requested"] is True
    assert remaining[0]["cancellable"] is False
    assert _job(first)["status"] == "running"
    assert _job(queued)["status"] == "cancelled"
    assert _job(queued)["cancel_requested"] is True
    assert manager.active_jobs()
    safe_boundary.set()
    lifecycle.drain(manager)
    assert called == [kind]  # The cancelled queue entry never enters its runner.
    assert _job(first)["status"] == "cancelled"
    assert "safe work-unit boundary" in _job(first)["error"]


def test_cancel_exit_waits_for_confirmed_write_and_cancels_only_queued_work(lifecycle):
    writing = lifecycle.event()
    finish_write = lifecycle.event()
    committed = []

    def agent(_payload, *, progress_callback, cancel_check):
        progress_callback(NON_CANCELLABLE_PROGRESS_PREFIX + "saving confirmed report")
        writing.set()
        assert finish_write.wait(10)
        assert cancel_check() is False
        committed.append("report and metadata saved")
        return {"status": "success", "write_action_started": True, "write_action_succeeded": True}

    def must_not_start(_payload):
        pytest.fail("queued process should be cancelled before its runner starts")

    manager = lifecycle.manager(process_runner=must_not_start, agent_runner=agent)
    write_id = manager.submit_agent({"message": "confirm"})["job_id"]
    assert writing.wait(5)
    queued_id = manager.submit_process({})["job_id"]
    active = manager.begin_desktop_exit(cancel=True)
    assert active == [{"job_id": write_id, "kind": "agent", "status": "running",
                       "stage": "saving confirmed report", "cancellable": False,
                       "cancel_requested": False}]
    assert manager.cancel(write_id) is False
    assert _job(queued_id)["status"] == "cancelled"
    assert committed == []
    assert manager.active_jobs() == active
    finish_write.set()
    lifecycle.drain(manager)
    assert committed == ["report and metadata saved"]
    assert _job(write_id)["status"] == "succeeded"
    assert _job(write_id)["result"]["write_action_succeeded"] is True
    assert _job(write_id)["cancel_requested"] is False


@pytest.mark.parametrize("kind", ["process", "agent"])
@pytest.mark.parametrize("cancel", [False, True])
def test_exit_serializes_with_started_but_not_yet_registered_future(lifecycle, monkeypatch, kind, cancel):
    runner_started = lifecycle.event()
    release_runner = lifecycle.event()
    executor_submitted = lifecycle.event()
    register_future = lifecycle.event()
    exit_started = lifecycle.event()
    exit_finished = lifecycle.event()
    outcomes: dict[str, Any] = {}
    errors = []

    def process(_payload):
        runner_started.set()
        assert release_runner.wait(10)
        return {"status": "success"}

    def agent(payload, *, progress_callback, cancel_check):
        return process(payload)

    manager = lifecycle.manager(process_runner=process, agent_runner=agent)
    original_submit = manager._executor.submit

    def hold_after_executor_submit(*args, **kwargs):
        future = original_submit(*args, **kwargs)
        executor_submitted.set()
        assert register_future.wait(10)
        return future

    monkeypatch.setattr(manager._executor, "submit", hold_after_executor_submit)

    def submit():
        try:
            method = manager.submit_process if kind == "process" else manager.submit_agent
            outcomes["submitted"] = method({})
        except BaseException as exc:
            errors.append(exc)

    def exit_desktop():
        exit_started.set()
        try:
            outcomes["remaining"] = manager.begin_desktop_exit(cancel=cancel)
        except BaseException as exc:
            errors.append(exc)
        finally:
            exit_finished.set()

    submitter = threading.Thread(target=submit)
    exiter = threading.Thread(target=exit_desktop)
    submitter.start()
    try:
        assert executor_submitted.wait(5)
        assert runner_started.wait(5)
        exiter.start()
        assert exit_started.wait(5)
        # The worker exists, but admission still owns its registration transaction.
        assert not exit_finished.wait(0.1)
        register_future.set()
        submitter.join(5)
        exiter.join(5)
        assert not submitter.is_alive() and not exiter.is_alive()
        assert errors == []
        job_id = outcomes["submitted"]["job_id"]
        assert [item["job_id"] for item in outcomes["remaining"]] == [job_id]
        assert outcomes["remaining"][0]["cancel_requested"] is cancel
        with pytest.raises(RuntimeError, match="closed"):
            manager.submit_process({})
        release_runner.set()
        lifecycle.drain(manager)
        assert _job(job_id)["status"] == ("cancelled" if cancel else "succeeded")
    finally:
        register_future.set()
        release_runner.set()
        submitter.join(5)
        if exiter.ident is not None:
            exiter.join(5)


_OTHER_PROCESS = """
import json, sys, time
from pathlib import Path
from electrochem_v6.core.job_service import ProcessingJobManager
from electrochem_v6.store.runtime import get_database, reset_runtime
ready, release, completed = map(Path, sys.argv[1:])
def runner(payload):
    ready.write_text(json.dumps({'job_id': payload['_job_id']}), encoding='utf-8')
    deadline = time.monotonic() + 15
    while not release.exists():
        if time.monotonic() > deadline:
            raise RuntimeError('parent did not release worker')
        time.sleep(.01)
    return {'status': 'success'}
manager = ProcessingJobManager(max_workers=1, process_runner=runner)
try:
    submitted = manager.submit_process({})
    manager.begin_desktop_exit(cancel=False)
    manager._executor.shutdown(wait=True)
    completed.write_text(json.dumps(get_database().get_processing_job(submitted['job_id'])), encoding='utf-8')
finally:
    manager.shutdown()
    reset_runtime()
"""


def test_exit_excludes_history_and_another_live_process(lifecycle, tmp_path):
    ready, release, completed = (tmp_path / name for name in ("ready.json", "release", "completed.json"))
    environ = dict(os.environ)
    source = str(Path(__file__).resolve().parents[1] / "src")
    environ["PYTHONPATH"] = os.pathsep.join(filter(None, (source, environ.get("PYTHONPATH"))))
    child = subprocess.Popen(
        [sys.executable, "-c", _OTHER_PROCESS, str(ready), str(release), str(completed)],
        env=environ, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )
    try:
        deadline = time.monotonic() + 8
        while not ready.exists() and time.monotonic() < deadline and child.poll() is None:
            time.sleep(0.01)
        assert ready.exists(), "other process did not start its actual worker"
        foreign_id = json.loads(ready.read_text(encoding="utf-8"))["job_id"]
        database = get_database()
        for status in ("queued", "succeeded", "failed", "cancelled", "interrupted"):
            database.create_processing_job("old-" + status, kind="process", payload={})
            database.update_processing_job("old-" + status, status=status)
        started = lifecycle.event()
        finish = lifecycle.event()

        def local_runner(_payload):
            started.set()
            assert finish.wait(10)
            return {"status": "success"}

        manager = lifecycle.manager(process_runner=local_runner)
        own_id = manager.submit_process({})["job_id"]
        assert started.wait(5)
        assert [item["job_id"] for item in manager.active_jobs()] == [own_id]
        assert [item["job_id"] for item in manager.begin_desktop_exit(cancel=True)] == [own_id]
        assert _job(foreign_id)["status"] == "running"
        assert _job(foreign_id)["cancel_requested"] is False
        for status in ("queued", "succeeded", "failed", "cancelled", "interrupted"):
            assert _job("old-" + status)["status"] == status
            assert _job("old-" + status)["cancel_requested"] is False
        finish.set()
        lifecycle.drain(manager)
        assert _job(own_id)["status"] == "cancelled"
        assert _job(foreign_id)["status"] == "running"
        release.touch()
        stdout, stderr = child.communicate(timeout=10)
        assert child.returncode == 0, stdout + stderr
        foreign = json.loads(completed.read_text(encoding="utf-8"))
        assert foreign["status"] == "succeeded"
        assert foreign["cancel_requested"] is False
    finally:
        release.touch()
        try:
            child.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate(timeout=5)


@pytest.mark.parametrize("kind", ["process", "agent"])
@pytest.mark.parametrize("action", ["wait", "cancel"])
def test_shell_exit_drains_admitted_http_submission_before_closing_executor(lifecycle, tmp_path, monkeypatch, kind, action):
    from electrochem_v6.desktop.shell import DesktopShellApp
    from electrochem_v6.server.http_server import V6ServerManager

    started = lifecycle.event()
    finish_work_unit = lifecycle.event()
    destroyed = threading.Event()
    cancellation_at_boundary = []

    def run(cancel_check):
        started.set()
        assert finish_work_unit.wait(10)
        cancelled = cancel_check()
        cancellation_at_boundary.append(cancelled)
        if cancelled:
            raise ProcessingCancelledError("safe boundary after admitted HTTP request")
        return {"status": "success"}

    def process(payload):
        return run(payload["_cancel_check"])

    def agent(_payload, *, progress_callback, cancel_check):
        return run(cancel_check)

    runner = lifecycle.manager(process_runner=process, agent_runner=agent)
    original_submit = runner._executor.submit

    def start_worker_before_returning_future(*args, **kwargs):
        future = original_submit(*args, **kwargs)
        assert started.wait(5)
        return future

    monkeypatch.setattr(runner._executor, "submit", start_worker_before_returning_future)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    manager = V6ServerManager(port=port)
    manager._job_manager = runner
    assert manager.start()[0]
    app = DesktopShellApp(tmp_path, {"path": str(tmp_path / "data"), "mode": "environment"})
    app.manager = manager
    app.window = SimpleNamespace(evaluate_js=lambda _script: None, destroy=destroyed.set)
    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    path = f"/api/v1/{kind}/jobs"
    payload = {"message": "read existing results"} if kind == "agent" else {"folder_path": str(tmp_path)}
    body = json.dumps(payload).encode("utf-8")
    try:
        # A real accepted POST is paused by its sender while read_json waits for
        # the body. No mock replaces the handler, router, submitter or exit loop.
        headers = (f"POST {path} HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n"
                   f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n")
        client.sendall(headers.encode("ascii"))
        deadline = time.monotonic() + 5
        while manager.desktop_active_writes() != 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert manager.desktop_active_writes() == 1
        assert runner.active_jobs() == []
        app.resolve_close(action)
        assert not destroyed.is_set()

        late_client = HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            late_client.request("POST", path, body=body, headers={"Content-Type": "application/json"})
            late_response = late_client.getresponse()
            assert late_response.status == 503
            late_response.read()
        finally:
            late_client.close()

        client.sendall(body)
        response = HTTPResponse(client)
        response.begin()
        accepted = json.loads(response.read())
        assert response.status == 202, accepted
        job_id = accepted["job_id"]
        assert started.is_set()
        if action == "cancel":
            deadline = time.monotonic() + 5
            while not _job(job_id)["cancel_requested"] and time.monotonic() < deadline:
                time.sleep(0.01)
            assert _job(job_id)["cancel_requested"] is True
        else:
            assert _job(job_id)["cancel_requested"] is False
        assert _job(job_id)["status"] == "running"
        assert not destroyed.is_set()  # Drained HTTP is not yet drained work.
        finish_work_unit.set()
        assert destroyed.wait(5)
        lifecycle.drain(runner)
        assert cancellation_at_boundary == [action == "cancel"]
        assert _job(job_id)["status"] == ("cancelled" if action == "cancel" else "succeeded")
        assert manager.desktop_active_writes() == 0
    finally:
        finish_work_unit.set()
        client.close()
        app._closed.set()
        manager.stop()
