"""Recover interrupted work through the browser and the real processing pipeline."""

from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Event

import pytest

from conftest import _write_tsv, make_cv_rows
from electrochem_v6.core.process_owner import current_process_owner, inspect_process_owner
from electrochem_v6.core.process_service import process_folder
from electrochem_v6.server import V6ServerManager
from electrochem_v6.store.job_recovery import associate_job_run, register_owned_job
from electrochem_v6.store.projects import create_project
from electrochem_v6.store.run_recipes import get_run_recipe, update_run_recipe
from electrochem_v6.store.runtime import get_database, reset_runtime
from test_v6_ui_playwright import _get_free_port, _launch_chromium, _sync_playwright_factory


@pytest.fixture
def recovery_browser(monkeypatch, tmp_path):
    sync_playwright = _sync_playwright_factory()
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    for key, filename in (
        ("ELECTROCHEM_V6_PROJECTS_FILE", "projects.json"),
        ("ELECTROCHEM_V6_HISTORY_FILE", "history.json"),
        ("ELECTROCHEM_V6_TEMPLATE_FILE", "templates.json"),
        ("ELECTROCHEM_V6_CONVERSATION_FILE", "conversations.json"),
    ):
        monkeypatch.setenv(key, str(tmp_path / "runtime" / filename))
    reset_runtime()
    folder = tmp_path / "inputs"
    folder.mkdir()
    source = _write_tsv(folder / "CV_original.txt", make_cv_rows(n_half=20))
    project = create_project("恢复任务浏览器验证")["project"]
    payload = {
        "folder_path": str(folder), "input_files": [{"path": str(source), "data_type": "CV"}],
        "data_types": ["CV"], "project_id": project["id"], "project_name": project["name"],
        "params": {"area": 1, "potential_offset": 0},
    }
    manager = V6ServerManager(port=_get_free_port())
    assert manager.start()[0]
    try:
        with sync_playwright() as playwright:
            browser = _launch_chromium(playwright)
            page = browser.new_page(viewport={"width": 1400, "height": 1050})
            errors = []
            page.on("pageerror", lambda error: errors.append(error.stack or str(error)))
            yield page, manager, payload, source, errors
            assert errors == []
            browser.close()
    finally:
        manager.stop()
        reset_runtime()


def _open_recovery(page, manager, errors):
    page.goto(f"http://127.0.0.1:{manager.port}/ui", wait_until="networkidle")
    assert errors == []
    page.click("#tab-btn-project")
    page.click("#project-recovery-btn")
    page.wait_for_selector("#project-recovery-dialog .recovery-select")
    page.locator(".recovery-select").first.click()


def _wait_recovered(page, manager, job_id):
    page.wait_for_function(
        "() => document.querySelector('#project-recovery-status').textContent.includes('恢复完成')",
        timeout=45000,
    )
    response = page.request.get(f"http://127.0.0.1:{manager.port}/api/v1/process/jobs/{job_id}")
    assert response.ok
    job = response.json()["job"]
    assert job["status"] == "succeeded", job
    run_id = job["result"]["result"]["manifest"]["run"]["run_id"]
    recipe = get_run_recipe(run_id)
    assert recipe and recipe["status"] == "succeeded"
    return job, recipe


def test_unknown_queued_recovery_requires_recheck_and_keeps_running_state_when_reopened(recovery_browser):
    page, manager, payload, _source, errors = recovery_browser
    database = get_database()
    original_job_id = "legacy-queued-owner-unknown"
    original_job = database.create_processing_job(original_job_id, kind="process", payload=payload)
    entered = Event()
    release = Event()
    real_runner = manager._job_manager._process_runner

    def gated_runner(current_payload):
        entered.set()
        if not release.wait(timeout=20):
            return {"status": "error", "message": "test processing gate timed out"}
        return real_runner(current_payload)

    manager._job_manager._process_runner = gated_runner
    resume_requests = []
    page.on("request", lambda outgoing: resume_requests.append(outgoing.post_data_json)
            if outgoing.url.endswith("/api/v1/process/recovery/resume") else None)
    try:
        _open_recovery(page, manager, errors)
        page.wait_for_selector("#recovery-owner-confirm")
        assert page.locator("#recovery-execute").is_disabled()
        assert database.get_processing_job(original_job_id)["status"] == "queued"
        page.check("#recovery-owner-confirm")
        assert page.locator("#recovery-execute").is_disabled()
        with page.expect_response(lambda response: response.url.endswith("/api/v1/process/recovery/plan")) as checked:
            page.click("#recovery-check")
        assert checked.value.json()["plan"]["can_recover"] is True
        page.wait_for_selector("#recovery-execute:not([disabled])")
        with page.expect_response(lambda response: response.url.endswith("/api/v1/process/recovery/resume")) as resumed:
            page.locator("#recovery-execute").evaluate("el => { el.click(); el.click(); }")
        assert resumed.value.status == 202
        recovered_job_id = resumed.value.json()["job_id"]
        assert entered.wait(timeout=5)
        assert recovered_job_id != original_job_id
        assert len(resume_requests) == 1
        assert resume_requests[0]["confirm_owner_stopped"] is True
        page.wait_for_function(
            "() => document.querySelector('#project-recovery-status').textContent.includes('正在运行')"
        )
        assert page.locator("#recovery-check").is_disabled()
        assert page.locator(".recovery-source-path").first.is_disabled()
        page.click("#project-recovery-close")
        assert page.locator("#project-recovery-dialog").is_hidden()
        page.click("#project-recovery-btn")
        assert page.locator("#project-recovery-dialog").is_visible()
        assert page.locator("#recovery-execute").is_disabled()
        assert "正在运行" in page.locator("#project-recovery-status").inner_text()
        assert len(resume_requests) == 1
        release.set()
        _job, recipe = _wait_recovered(page, manager, recovered_job_id)
        assert recipe["project_id"] == payload["project_id"]
        assert recipe["recovered_from_job_id"] == original_job_id
        assert recipe["record_keys"]
        assert database.get_processing_job(original_job_id) == original_job
        assert len(database.get_all_history_records()) == 1
        assert len(resume_requests) == 1
    finally:
        release.set()


def test_dead_owner_recovery_relocates_missing_input_without_overwriting_original_run(recovery_browser):
    page, manager, payload, source, errors = recovery_browser
    original_result = process_folder(payload)
    assert original_result["status"] == "success", original_result
    original_run_id = original_result["result"]["manifest"]["run"]["run_id"]
    original = get_run_recipe(original_run_id)
    assert original
    fingerprints = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in Path(original["output_dir"]).rglob("*") if path.is_file()
    }
    assert fingerprints
    # Simulate a recorded process incarnation which no longer owns this PID.
    owner = current_process_owner()
    owner["start_token"] = "previous-process-incarnation"
    assert inspect_process_owner(owner)["state"] == "dead"
    original_job_id = "interrupted-run-owner-dead"
    database = get_database()
    database.create_processing_job(original_job_id, kind="process", payload=payload)
    database.update_processing_job(original_job_id, status="running")
    register_owned_job(original_job_id, kind="process", owner=owner, payload=payload)
    associate_job_run(original_job_id, original_run_id)
    update_run_recipe(original_run_id, status="running", owner=owner, job_id=original_job_id)
    moved = source.with_name("CV_relocated.txt")
    source.rename(moved)

    _open_recovery(page, manager, errors)
    page.wait_for_selector(".recovery-source-path")
    assert page.locator("#recovery-owner-confirm").count() == 0
    assert page.locator("#recovery-execute").is_disabled()
    assert "输入缺失" in page.locator("#project-recovery-content").inner_text()
    assert database.get_processing_job(original_job_id)["status"] == "interrupted"
    assert get_run_recipe(original_run_id)["status"] == "interrupted"
    page.locator(".recovery-source-path").first.fill(str(moved))
    assert page.locator("#recovery-execute").is_disabled()
    with page.expect_response(lambda response: response.url.endswith("/api/v1/process/recovery/plan")) as checked:
        page.click("#recovery-check")
    assert checked.value.json()["plan"]["can_recover"] is True
    assert checked.value.json()["plan"]["source_checks"][0]["state"] == "unchanged"
    page.wait_for_selector("#recovery-execute:not([disabled])")
    with page.expect_response(lambda response: response.url.endswith("/api/v1/process/recovery/resume")) as resumed:
        page.click("#recovery-execute")
    assert resumed.value.status == 202
    new_job_id = resumed.value.json()["job_id"]
    _job, recovered = _wait_recovered(page, manager, new_job_id)
    assert new_job_id != original_job_id
    assert recovered["run_id"] != original_run_id
    assert recovered["parent_run_id"] == original_run_id
    assert recovered["output_dir"] != original["output_dir"]
    assert str(moved) in {item["path"] for item in recovered["inputs"]}
    assert database.get_processing_job(original_job_id)["status"] == "interrupted"
    assert get_run_recipe(original_run_id)["status"] == "interrupted"
    assert database.get_history_record(original["record_keys"][0]) is not None
    assert len(database.get_all_history_records()) == 2
    assert {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in fingerprints} == fingerprints
