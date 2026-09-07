"""Persisted task summaries, filters and browser navigation/cancellation."""

from threading import Event

import pytest

from electrochem_v6.core.task_service import list_tasks
from electrochem_v6.store.runtime import get_database, reset_runtime
from test_v6_project_recovery_ui import recovery_browser as recovery_browser


@pytest.fixture
def task_data(monkeypatch, tmp_path):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    reset_runtime()
    yield get_database()
    reset_runtime()


def test_task_list_prioritizes_all_active_work_and_filters_before_pagination(task_data):
    task_data.create_processing_job("old-active", kind="process", payload={})
    for index in range(45):
        identifier = f"done-{index:02d}"
        task_data.create_processing_job(identifier, kind="agent", payload={})
        task_data.update_processing_job(identifier, status="succeeded")
    first = list_tasks(limit=10)
    assert first["items"][0]["job_id"] == "old-active"
    assert first["active_count"] == 1 and first["total"] == 46
    filtered = list_tasks(kind="agent", status="succeeded", limit=10, offset=40)
    assert filtered["total"] == 45 and len(filtered["items"]) == 5 and not filtered["has_more"]
    assert all(item["kind"] == "agent" for item in filtered["items"])
    assert list_tasks(status="failed")["items"] == []


def test_task_summary_does_not_duplicate_chat_credentials_or_result_bodies(task_data):
    task_data.create_processing_job("agent-private", kind="agent", payload={"message": "private prompt", "api_key": "test-secret", "professional_context": {"parameters": {"private": "test-value"}}})
    task_data.update_processing_job("agent-private", result={"reply": "private answer", "messages": ["private history"]})
    result = list_tasks()
    serialized = str(result)
    assert not any(value in serialized for value in ("private prompt", "test-secret", "private answer", "private history", "test-value"))
    assert "payload" not in result["items"][0] and "result" not in result["items"][0]
    assert result["items"][0]["can_cancel"] is False


@pytest.mark.parametrize("options", [{"kind": "bad"}, {"status": "unknown"}, {"offset": -1}, {"limit": 0}, {"limit": 101}])
def test_task_filters_reject_invalid_ranges(task_data, options):
    with pytest.raises(ValueError):
        list_tasks(**options)


def test_task_center_survives_reload_and_opens_exact_completed_results(recovery_browser):
    page, manager, payload, _source, _errors = recovery_browser
    from electrochem_v6.core.process_service import process_folder

    result = process_folder(payload)
    assert result["status"] == "success"
    database = get_database()
    database.create_processing_job("saved-process-task", kind="process", payload=payload)
    database.update_processing_job("saved-process-task", status="succeeded", result=result)
    page.goto(f"http://127.0.0.1:{manager.port}/ui", wait_until="networkidle")
    page.click("#task-center-btn")
    page.wait_for_selector('[data-task-id="saved-process-task"]')
    assert page.locator('[data-task-id="saved-process-task"] .task-status').inner_text() == "已完成"
    page.reload(wait_until="networkidle")
    page.click("#task-center-btn")
    page.click('[data-task-open="saved-process-task"]')
    page.wait_for_function("() => !document.querySelector('#task-center-dialog').open")
    assert page.locator("#tab-project").get_attribute("class").endswith("active")
    page.wait_for_selector("#project-history-detail-panel:not([hidden])")
    assert "CV_original" in page.locator("#project-history-detail-panel").inner_text()


def test_task_center_cancels_owned_task_and_shows_failure_details(recovery_browser):
    page, manager, payload, _source, _errors = recovery_browser
    started, release = Event(), Event()

    def runner(_payload):
        started.set()
        assert release.wait(20)
        return {"status": "success"}

    manager._job_manager._process_runner = runner
    job = manager._job_manager.submit_process(payload)
    assert started.wait(5)
    database = get_database()
    database.create_processing_job("saved-failure", kind="process", payload=payload)
    database.update_processing_job("saved-failure", status="failed", error="示例：原始文件列格式错误")
    try:
        page.goto(f"http://127.0.0.1:{manager.port}/ui", wait_until="networkidle")
        page.click("#task-center-btn")
        page.wait_for_selector(f'[data-task-cancel="{job["job_id"]}"]')
        with page.expect_response(lambda response: response.url.endswith(f'/tasks/{job["job_id"]}/cancel')) as cancellation:
            page.click(f'[data-task-cancel="{job["job_id"]}"]')
        assert cancellation.value.status == 200
        assert database.get_processing_job(job["job_id"])["cancel_requested"]
        release.set()
        page.select_option("#task-status", "cancelled")
        page.wait_for_selector(f'[data-task-id="{job["job_id"]}"] .task-status.cancelled')
        page.select_option("#task-status", "failed")
        page.wait_for_selector('[data-task-id="saved-failure"]')
        page.click('[data-task-id="saved-failure"] .task-error summary')
        assert "列格式错误" in page.locator('[data-task-id="saved-failure"] .task-error').inner_text()
        page.set_viewport_size({"width": 600, "height": 900})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for theme in ("pixel", "lab", "dark"):
            page.evaluate("value => document.body.dataset.theme = value", theme)
            assert page.locator("#task-center-dialog").evaluate("node => node.scrollWidth <= node.clientWidth")
    finally:
        release.set()


def test_task_api_refuses_foreign_owner_and_committed_agent_cancellation(recovery_browser):
    from electrochem_v6.core.job_control import NON_CANCELLABLE_PROGRESS_PREFIX

    page, manager, payload, _source, _errors = recovery_browser
    entered, release = Event(), Event()

    def agent_runner(_payload, *, progress_callback, cancel_check):
        progress_callback(NON_CANCELLABLE_PROGRESS_PREFIX + "正在保存已确认的结果")
        entered.set()
        assert release.wait(20)
        assert not cancel_check()
        return {"status": "success", "write_action_started": True}

    manager._job_manager._agent_runner = agent_runner
    job = manager._job_manager.submit_agent({"message": "test approved write"})
    assert entered.wait(5)
    database = get_database()
    database.create_processing_job("other-owner", kind="process", payload=payload)
    try:
        page.goto(f"http://127.0.0.1:{manager.port}/ui", wait_until="networkidle")
        for job_id in (job["job_id"], "other-owner"):
            result = page.evaluate("async id => { const r = await ElectrochemApi.fetch(`/api/v1/tasks/${id}/cancel`, {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}); return {code:r.status,body:await r.json()}; }", job_id)
            assert result["code"] == 409
            assert not database.get_processing_job(job_id)["cancel_requested"]
        page.click("#task-center-btn")
        page.wait_for_selector(f'[data-task-id="{job["job_id"]}"]')
        assert page.locator("[data-task-cancel]").count() == 0
        assert page.locator(f'[data-task-id="{job["job_id"]}"] progress').get_attribute("value") is None
    finally:
        release.set()


def test_assistant_input_identity_covers_all_selected_files_and_distinguishes_same_names(recovery_browser):
    import hashlib

    from electrochem_v6.agent.actions import input_path_signature

    page, manager, _payload, _source, _errors = recovery_browser
    page.goto(f"http://127.0.0.1:{manager.port}/ui", wait_until="networkidle")
    paths = [f"C:/Inputs/{index}/LSV_same.txt" for index in range(25)]
    paths.extend(["C:\\Inputs\\A\\..\\B\\LSV.txt", "//SERVER/Share/A/../LSV.txt", "/data/A/../B/LSV.txt"])
    normalized = page.evaluate("paths => paths.map(ElectrochemAssistantContext.canonicalInputPath)", paths)
    assert [hashlib.sha256(value.encode()).hexdigest() for value in normalized] == [input_path_signature(value) for value in paths]
    page.evaluate("paths => { processSourceItems = paths.map(path => ({path,data_type:'LSV',enabled:true})); }", paths)
    before = page.evaluate("() => buildAssistantActionContext()")
    assert len(before["action_context"]["input_path_signatures"]) == len(paths)
    assert before["data_source"]["truncated"] is True
    page.evaluate("() => { processSourceItems[24].path = 'C:/Different/24/LSV_same.txt'; }")
    after = page.evaluate("() => buildAssistantActionContext()")
    assert before["data_source"] == after["data_source"]
    assert before["action_context"]["parameter_signature"] != after["action_context"]["parameter_signature"]
    assert before["action_context"]["input_path_signatures"] != after["action_context"]["input_path_signatures"]
