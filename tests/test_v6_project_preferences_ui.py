"""Browser coverage of persisted project preferences and explicit template application."""

from __future__ import annotations

import pytest

import electrochem_v6.server.routes_post as routes_post
from electrochem_v6.server import V6ServerManager
from electrochem_v6.store.runtime import reset_runtime
from test_v6_ui_playwright import _get_free_port, _launch_chromium, _sync_playwright_factory

_AUXILIARY_SOURCE_IDS = (
    "pro-coupled-products-file", "pro-coupled-peak-method-file", "pro-lsv-ir-eis-file",
)


@pytest.fixture
def preferences_page(monkeypatch, tmp_path):
    sync_playwright = _sync_playwright_factory()
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    for key, filename in (
        ("ELECTROCHEM_V6_PROJECTS_FILE", "projects.json"),
        ("ELECTROCHEM_V6_HISTORY_FILE", "history.json"),
        ("ELECTROCHEM_V6_TEMPLATE_FILE", "templates.json"),
        ("ELECTROCHEM_V6_CONVERSATION_FILE", "conversations.json"),
    ):
        monkeypatch.setenv(key, str(tmp_path / "runtime" / filename))
    source = tmp_path / "source"
    source.mkdir()
    (source / "LSV_original.txt").write_text("Potential Current\n0 0\n0.2 0.001\n", encoding="utf-8")
    monkeypatch.setattr(
        routes_post, "select_folder_dialog",
        lambda initial_dir=None: {"status": "success", "folder_path": str(source)},
    )
    reset_runtime()
    manager = V6ServerManager(port=_get_free_port())
    assert manager.start()[0]
    try:
        with sync_playwright() as playwright:
            browser = _launch_chromium(playwright)
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(error.stack or str(error)))
            base_url = f"http://127.0.0.1:{manager.port}"
            response = page.request.post(f"{base_url}/api/v1/process/templates", data={
                "name": "project-area-template",
                "state": {
                    "selected_types": ["LSV"],
                    "values": {
                        "pro-area": "2.5", "pro-lsv-target": "25",
                        **{key: f"D:/previous-experiment/{key}.csv" for key in _AUXILIARY_SOURCE_IDS},
                    },
                    "checks": {"pro-plot-grid": False},
                },
            })
            assert response.ok
            page.goto(f"{base_url}/ui", wait_until="networkidle")
            assert errors == []
            page.wait_for_function(
                "() => window.ElectrochemProcessingSchema.getCached() && templateItems.some(item => item.name === 'project-area-template')"
            )
            page.click("#proc-data-pick")
            page.click("#proc-pick-folder")
            page.wait_for_selector("#proc-source-list .source-file-item")
            page.fill("#pro-area", "1.25")
            auxiliary = tmp_path / "auxiliary"
            auxiliary.mkdir()
            for source_id in _AUXILIARY_SOURCE_IDS:
                path = auxiliary / f"{source_id}.csv"
                path.write_text("current experiment input\n", encoding="utf-8")
                page.locator(f"#{source_id}").evaluate(
                    "(el, value) => { el.value = value; el.dispatchEvent(new Event('input', { bubbles: true })); }",
                    str(path),
                )
            assert page.locator("#proc-folder").input_value() == str(source)
            yield page, base_url
            assert errors == []
            browser.close()
    finally:
        manager.stop()
        reset_runtime()


def _processing_snapshot(page):
    return page.evaluate("""() => ({
      state: getCurrentTemplateState(), folder: document.querySelector('#proc-folder').value,
      sources: processSourceItems, folders: processSourceFolders,
    })""")


def _stored_project(page, base_url, project_id):
    response = page.request.get(f"{base_url}/api/v1/projects?status=all")
    assert response.ok
    return next(project for project in response.json()["projects"] if project["id"] == project_id)


def test_project_color_and_template_settings_persist_without_applying(preferences_page):
    page, base_url = preferences_page
    original = _processing_snapshot(page)
    page.click("#tab-btn-project")
    page.click("#project-create-btn")
    page.fill("#project-create-name", "有常用模板的项目")
    page.click("#project-create-more > summary")
    assert page.locator('#project-create-colors button[data-color=""]').get_attribute("aria-pressed") == "true"
    page.locator('#project-create-colors button[data-color="#2563eb"]').click()
    page.select_option("#project-create-template", "LSV_常用模板")
    with page.expect_response(
        lambda response: response.url == f"{base_url}/api/v1/projects" and response.request.method == "POST"
    ) as created_response:
        page.click("#project-create-submit")
    assert created_response.value.ok
    project_id = created_response.value.json()["project_id"]
    page.wait_for_function("() => !document.querySelector('#project-create-dialog').open")
    stored = _stored_project(page, base_url, project_id)
    assert stored["color"] == "#2563eb"
    assert stored["default_template_name"] == "LSV_常用模板"
    assert _processing_snapshot(page) == original

    page.click("#project-more-menu > summary")
    page.click("#project-settings-open")
    assert page.locator('#project-edit-colors button[data-color="#2563eb"]').get_attribute("aria-pressed") == "true"
    assert page.locator("#project-edit-template").input_value() == "LSV_常用模板"
    page.fill("#project-edit-color-custom", "#123abc")
    page.select_option("#project-edit-template", "project-area-template")
    page.click("#project-save-btn")
    page.wait_for_function("() => !document.querySelector('#project-settings-dialog').open")
    stored = _stored_project(page, base_url, project_id)
    assert stored["color"] == "#123abc"
    assert stored["default_template_name"] == "project-area-template"
    assert _processing_snapshot(page) == original

    page.click("#project-use-btn")
    page.wait_for_selector("#project-template-apply:not([disabled])")
    assert "2.5" in page.locator("#project-template-diff").inner_text()
    assert "1.25" in page.locator("#project-template-diff").inner_text()
    assert _processing_snapshot(page) == original
    page.click("#project-template-cancel")
    assert page.locator("#tab-project").is_visible()
    assert _processing_snapshot(page) == original
    page.click("#project-use-btn")
    page.wait_for_selector("#project-template-apply:not([disabled])")
    page.click("#project-template-skip")
    assert page.locator("#tab-pro").is_visible()
    assert page.locator("#proc-project").input_value() == "有常用模板的项目"
    assert _processing_snapshot(page) == original
    assert page.evaluate("appliedProcessTemplateName") == ""


def test_project_template_apply_invalidates_preflight_and_missing_template_never_falls_back(preferences_page):
    page, base_url = preferences_page
    response = page.request.post(f"{base_url}/api/v1/projects", data={
        "name": "显式应用模板", "default_template_name": "project-area-template",
    })
    assert response.ok
    project_id = response.json()["project_id"]
    original = _processing_snapshot(page)
    page.click("#proc-preflight-btn")
    page.wait_for_function("() => processPreflightState === 'complete'")
    page.click("#tab-btn-project")
    page.click("#project-refresh")
    page.wait_for_selector(f'#project-list [data-project-id="{project_id}"]')
    page.locator(f'#project-list [data-project-id="{project_id}"]').click()
    page.click("#project-use-btn")
    page.wait_for_selector("#project-template-apply:not([disabled])")
    assert page.evaluate("processPreflightState") == "complete"
    page.click("#project-template-apply")
    assert page.locator("#tab-pro").is_visible()
    assert page.locator("#pro-area").input_value() == "2.5"
    assert page.locator("#pro-lsv-target").input_value() == "25"
    assert not page.locator("#pro-plot-grid").is_checked()
    assert page.locator("#tmpl-select").input_value() == "project-area-template"
    assert page.locator("#tmpl-name").input_value() == "project-area-template"
    assert page.evaluate("appliedProcessTemplateName") == "project-area-template"
    assert page.evaluate("processPreflightState") == "pending"
    applied = _processing_snapshot(page)
    for key in ("folder", "sources", "folders"):
        assert applied[key] == original[key]
    for source_id in _AUXILIARY_SOURCE_IDS:
        assert applied["state"]["values"][source_id] == original["state"]["values"][source_id]

    assert page.request.post(f"{base_url}/api/v1/process/templates/project-area-template/delete", data={}).ok
    page.fill("#pro-area", "7.5")
    before_missing = _processing_snapshot(page)
    page.click("#tab-btn-project")
    page.click("#project-use-btn")
    page.wait_for_function(
        "() => document.querySelector('#project-template-status').textContent.includes('已删除或不可用')"
    )
    assert page.locator("#project-template-apply").is_disabled()
    assert page.locator("#project-template-skip").is_enabled()
    assert _processing_snapshot(page) == before_missing
    assert _stored_project(page, base_url, project_id)["default_template_name"] == "project-area-template"
    page.click("#project-template-skip")
    assert page.locator("#tab-pro").is_visible()
    assert _processing_snapshot(page) == before_missing
    assert page.locator("#pro-area").input_value() == "7.5"
    assert page.evaluate("appliedProcessTemplateName") == ""
