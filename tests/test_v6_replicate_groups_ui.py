"""Persist replicate decisions and exports through the real browser/API."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from electrochem_v6.server import V6ServerManager
from electrochem_v6.store.projects import create_project
from electrochem_v6.store.runtime import reset_runtime
from test_v6_replicate_groups import seed
from test_v6_ui_playwright import _get_free_port, _launch_chromium, _sync_playwright_factory


@pytest.fixture
def browser_project(monkeypatch, tmp_path):
    factory = _sync_playwright_factory()
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    for variable, filename in (
        ("ELECTROCHEM_V6_PROJECTS_FILE", "projects.json"), ("ELECTROCHEM_V6_HISTORY_FILE", "history.json"),
        ("ELECTROCHEM_V6_CONVERSATION_FILE", "conversations.json"), ("ELECTROCHEM_V6_TEMPLATE_FILE", "templates.json"),
    ):
        monkeypatch.setenv(variable, str(tmp_path / "runtime" / filename))
    reset_runtime()
    project_id = create_project("重复统计浏览器验收")["project"]["id"]
    manager = V6ServerManager(port=_get_free_port())
    assert manager.start()[0]
    try:
        with factory() as playwright:
            browser = _launch_chromium(playwright)
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            errors = []
            page.on("pageerror", lambda error: errors.append(error.stack or str(error)))
            yield page, f"http://127.0.0.1:{manager.port}", project_id
            assert errors == []
            browser.close()
    finally:
        manager.stop()
        reset_runtime()


def open_selection(page, base_url):
    page.goto(base_url + "/ui", wait_until="networkidle")
    page.click("#tab-btn-project")
    page.wait_for_selector(".project-record-check")
    for checkbox in page.locator(".project-record-check").all():
        checkbox.check()
    with page.expect_response(lambda response: response.url.endswith("/replicate-preview")) as response:
        page.click("#project-replicates-create")
    assert response.value.ok
    page.wait_for_selector("#replicate-name")
    return response.value.json()["group"]


def review(page):
    with page.expect_response(lambda response: response.url.endswith("/replicate-preview")) as response:
        page.click("#replicate-review")
    return response.value


def test_replicate_ui_excludes_rerun_saves_points_and_downloads_exports(browser_project):
    import hashlib

    page, base_url, project_id = browser_project
    zero = seed(project_id, "zero", 0)
    seed(project_id, "two", 2)
    copied = seed(project_id, "copy", 99, sha=hashlib.sha256(b"zero").hexdigest())
    preview = open_selection(page, base_url)
    assert page.locator(".replicate-members tbody tr").first.locator("td").count() == 4
    assert page.locator(".replicate-members tbody strong").count() == 3
    assert preview["source_conflicts"] and not preview["can_save"]
    assert {zero, copied} == set(preview["source_conflicts"][0])
    copy_index = preview["record_keys"].index(copied)
    page.fill("#replicate-name", "催化剂复测组")
    page.uncheck(f"#replicate-include-{copy_index}")
    rejected = review(page)
    assert rejected.status == 400
    assert page.locator("#replicate-name").input_value() == "催化剂复测组"
    assert not page.locator(f"#replicate-include-{copy_index}").is_checked()
    page.fill(f"#replicate-reason-{copy_index}", "同一原始数据的复算版本，不增加独立样本数")
    checked = review(page)
    assert checked.ok and checked.json()["group"]["can_save"]
    page.wait_for_selector("#replicate-save:not([disabled])")
    with page.expect_response(lambda response: response.url.endswith("/replicate-groups") and response.request.method == "POST") as saved:
        page.click("#replicate-save")
    assert saved.value.ok
    group = saved.value.json()["group"]
    group_id = group["group_id"]
    metric = group["metrics"][0]
    assert metric["n"] == 2 and metric["mean"] == 1
    assert metric["sample_sd"] == pytest.approx(math.sqrt(2))
    page.wait_for_selector("#replicate-chart svg")
    assert page.locator('#replicate-chart circle[data-chart-series="measurement"]').count() == 2
    assert page.locator('#replicate-chart polygon[data-chart-marker="diamond"]').count() == 1
    for selector, expected in (("#replicate-csv", b"source_sha256"), ("#replicate-svg", b"ddof=1")):
        with page.expect_download() as downloaded:
            page.click(selector)
        assert expected in Path(downloaded.value.path()).read_bytes()
    page.click("#replicate-close")
    page.reload(wait_until="networkidle")
    page.click("#tab-btn-project")
    page.click("#project-more-menu > summary")
    page.click("#project-replicates-open")
    page.locator(".replicate-open").filter(has_text="催化剂复测组").click()
    page.wait_for_selector("#replicate-name")
    assert not page.locator(f"#replicate-include-{copy_index}").is_checked()
    assert "复算版本" in page.locator(f"#replicate-reason-{copy_index}").input_value()
    page.set_viewport_size({"width": 600, "height": 900})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator("#replicate-save").scroll_into_view_if_needed()
    assert page.locator("#replicate-save").is_visible()
    stored = page.request.get(base_url + "/api/v1/replicate-groups/" + group_id).json()["group"]
    assert stored["exclusions"] == group["exclusions"]


def test_replicate_ui_requires_each_unknown_experiment_confirmation(browser_project):
    page, base_url, project_id = browser_project
    keys = [seed(project_id, "legacy-one", 0, recipe=False), seed(project_id, "legacy-two", 8, recipe=False)]
    preview = open_selection(page, base_url)
    assert not preview["can_save"]
    assert page.locator(".replicate-confirm").count() == 2
    assert not page.locator("#replicate-confirm-0").is_checked()
    page.fill("#replicate-name", "旧实验独立性已人工核对")
    page.check("#replicate-confirm-0")
    checked = review(page)
    assert checked.ok and not checked.json()["group"]["can_save"]
    assert page.locator("#replicate-save").is_disabled()
    page.check("#replicate-confirm-1")
    page.check("#replicate-conditions-confirm")
    checked = review(page)
    assert checked.ok and checked.json()["group"]["can_save"]
    page.wait_for_selector("#replicate-save:not([disabled])")
    with page.expect_response(lambda response: response.url.endswith("/replicate-groups") and response.request.method == "POST") as saved:
        page.click("#replicate-save")
    assert saved.value.ok
    group = saved.value.json()["group"]
    assert set(group["independence_confirmed_keys"]) == set(keys)
    assert group["metrics"][0]["n"] == 2 and group["metrics"][0]["mean"] == 4
