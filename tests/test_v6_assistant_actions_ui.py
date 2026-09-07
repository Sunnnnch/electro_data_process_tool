"""Real API, persisted model-generated cards, and actual app button actions."""

from __future__ import annotations

from copy import deepcopy

import pytest

from electrochem_v6.server import V6ServerManager
from electrochem_v6.store.conversations import get_conversation
from test_v6_assistant_actions import action_data, model_service  # noqa: F401
from test_v6_ui_playwright import _get_free_port, _launch_chromium, _sync_playwright_factory


@pytest.fixture
def action_browser(action_data, monkeypatch):  # noqa: F811 - imported shared pytest fixture
    keys = action_data["context"]["action_context"]["record_keys"]
    service, controller = model_service(monkeypatch, [
        ("propose_parameter_changes", {"changes": [{"key": "area", "value": 2, "reason": "使用用户确认的电极面积"}]}),
        ("prepare_record_comparison", {"record_keys": keys}),
        ("prepare_run_replay", {"run_id": action_data["runs"][0]["run_id"], "params": {"area": 2}}),
        ("prepare_result_report", {"record_keys": keys}),
    ])
    manager = V6ServerManager(port=_get_free_port())
    manager._agent_service = service
    ok, message = manager.start()
    assert ok, message
    try:
        with _sync_playwright_factory()() as playwright:
            browser = _launch_chromium(playwright)
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/api/v1/system/select-folder", lambda route: route.fulfill(json={"status": "success", "folder_path": str(action_data["source"].parent)}))
            page.goto(f"http://127.0.0.1:{manager.port}/ui", wait_until="networkidle")
            yield page, action_data, controller
            assert errors == []
            browser.close()
    finally:
        manager.stop()


def configure(page, data):
    page.click("#tab-btn-pro")
    page.locator('.proc-type-check[value="CV"]').check()
    page.locator('.proc-type-check[value="LSV"]').uncheck()
    page.fill("#pro-area", "1")
    page.select_option("#proc-project", label="alpha")
    page.click("#proc-data-pick")
    page.click("#proc-pick-folder")
    page.wait_for_function("() => document.querySelector('#proc-source-list').textContent.includes('CV_demo.txt')")
    page.click("#proc-preflight-btn")
    page.wait_for_function("() => latestPreflightScan !== null")
    page.click("#tab-btn-project")
    page.click('[data-project-id="alpha"]')
    page.wait_for_function("() => document.querySelectorAll('.project-record-check').length === 2")
    page.locator(".project-record-check").nth(0).check()
    page.locator(".project-record-check").nth(1).check()
    # The replay scope is explicitly the old run, independently of row sorting.
    old_key = data["runs"][0]["record_keys"][0]
    old_index = page.locator(".project-result-row").evaluate_all("(rows, key) => rows.findIndex(row => row.dataset.key === key)", old_key)
    assert old_index >= 0
    page.locator(".project-result-row").nth(old_index).click()


def send_cards(page):
    page.click("#assistant-fab")
    page.fill("#msg-input", "准备参数、精确比较、复算和所选结果报告卡")
    page.click("#send-btn")
    page.wait_for_function("() => document.querySelectorAll('#chat-log .assistant-action-card').length === 4", timeout=15000)
    cid = page.evaluate("() => currentConversationId")
    return cid


def open_card(page, kind):
    page.locator(f'.assistant-action-card[data-action-kind="{kind}"] button').click()
    page.wait_for_function("() => !document.querySelector('#assistant-action-confirm').disabled")


def test_restored_cards_apply_params_compare_exact_records_and_preview_replay_report(action_browser):
    page, data, _controller = action_browser
    configure(page, data)
    cid = send_cards(page)
    persisted = get_conversation(cid)["messages"][-1]["metadata"]["action_cards"]
    assert len(persisted) == 4
    page.reload(wait_until="networkidle")
    configure(page, data)
    page.evaluate("cid => openConversation(cid, true)", cid)
    page.evaluate("() => openAssistantDrawer()")
    page.wait_for_function("() => document.querySelectorAll('#chat-log .assistant-action-card').length === 4")
    before = page.evaluate("() => collectProcessPayload()")
    open_card(page, "parameter_changes")
    assert "使用用户确认的电极面积" in page.locator("#assistant-action-content").inner_text()
    page.locator("#assistant-action-confirm").evaluate("button => { button.click(); button.click(); }")
    page.wait_for_function("() => document.querySelector('#pro-area').value === '2'")
    after = page.evaluate("() => collectProcessPayload()")
    assert after["input_files"] == before["input_files"]
    assert after.get("folder_path") == before.get("folder_path")
    assert after["params"]["area"] == 2
    assert page.evaluate("() => latestPreflightScan") is None

    open_card(page, "compare_records")
    with page.expect_request("**/api/v1/history/compare") as comparison:
        page.click("#assistant-action-confirm")
    assert comparison.value.post_data_json["left_record_key"] == data["context"]["action_context"]["record_keys"][0]
    assert comparison.value.post_data_json["right_record_key"] == data["context"]["action_context"]["record_keys"][1]
    page.wait_for_selector("#project-view-compare:not([hidden])")

    open_card(page, "replay_run")
    page.click("#assistant-action-confirm")
    page.wait_for_function("() => document.querySelector('#project-replay-dialog').open && document.querySelector('#project-replay-mode')?.value === 'modified'")
    assert page.locator('.project-replay-parameter[data-param-key="area"]').input_value() == "2"
    assert page.locator("#project-replay-execute").is_disabled()
    page.evaluate("() => document.querySelector('#project-replay-dialog').close()")

    open_card(page, "report_records")
    page.click("#assistant-action-confirm")
    page.wait_for_selector("#project-view-reports:not([hidden])")
    assert page.locator("#project-report-scope").input_value() == "selected"
    with page.expect_request("**/api/v1/projects/alpha/report") as report:
        page.click("#project-export-report-btn")
    assert set(report.value.post_data_json["record_keys"]) == set(data["context"]["action_context"]["record_keys"])
    assert "run_ids" not in report.value.post_data_json


def test_stale_parameter_card_and_foreign_project_card_cannot_execute(action_browser):
    page, data, _controller = action_browser
    configure(page, data)
    cid = send_cards(page)
    original = get_conversation(cid)["messages"][-1]["metadata"]["action_cards"]
    page.evaluate("() => { document.querySelector('#pro-area').value = '3'; }")
    page.locator('.assistant-action-card[data-action-kind="parameter_changes"] button').click()
    page.wait_for_function("() => document.querySelector('#assistant-action-status').textContent.includes('改变')")
    assert page.locator("#assistant-action-confirm").is_disabled()
    assert page.locator("#pro-area").input_value() == "3"
    page.click("#assistant-action-close")

    bad = deepcopy(next(card for card in original if card["kind"] == "report_records"))
    bad["id"] = "foreign-card"
    bad["record_keys"] = data["runs"][2]["record_keys"]
    page.evaluate("card => { const log = document.querySelector('#chat-log'); log.innerHTML = ElectrochemAssistantActions.renderCards({role:'agent',metadata:{action_cards:[card]}}); ElectrochemAssistantActions.bind(log); }", bad)
    page.locator(".assistant-action-card button").click()
    page.wait_for_function("() => document.querySelector('#assistant-action-status').textContent.includes('项目')")
    assert page.locator("#assistant-action-confirm").is_disabled()
