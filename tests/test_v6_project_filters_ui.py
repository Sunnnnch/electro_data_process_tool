"""Real-browser coverage for database-wide project result filters and races."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from electrochem_v6.server import V6ServerManager
from electrochem_v6.store.runtime import get_database, reset_runtime
from test_v6_ui_playwright import _get_free_port, _launch_chromium, _sync_playwright_factory


def _query(url):
    parsed = urlparse(url)
    return {key: values[0] for key, values in parse_qs(parsed.query).items()} if parsed.path == "/api/v1/history" else None


def _history_response(response, **filters):
    query = _query(response.url)
    return query is not None and all(query.get(key, "") == str(value) for key, value in filters.items())


@pytest.fixture
def project_browser(monkeypatch, tmp_path):
    for key, filename in {
        "ELECTROCHEM_V6_HISTORY_FILE": "history.json",
        "ELECTROCHEM_V6_PROJECTS_FILE": "projects.json",
        "ELECTROCHEM_V6_CONVERSATION_FILE": "conversations.json",
        "ELECTROCHEM_V6_TEMPLATE_FILE": "templates.json",
        "ELECTROCHEM_V6_QUALITY_REPORT_FILE": "quality.json",
    }.items():
        monkeypatch.setenv(key, str(tmp_path / filename))
    reset_runtime()
    database = get_database()
    for project_id, name in (("filters-alpha", "Alpha result filters"), ("filters-beta", "Beta result filters")):
        database.create_project({"id": project_id, "name": name, "status": "active", "created_at": "2026-09-01", "updated_at": "2026-09-01"})

    def add_record(key, *, sample="Routine", data_type="LSV", timestamp="2026-09-08 12:00:00", project="filters-alpha", archived=False):
        database.add_history_record({
            "timestamp": timestamp, "type": data_type, "sample_name": sample,
            "file_name": key + ".txt", "file_path": str(tmp_path / (key + ".txt")),
            "project_id": project, "run_id": "run-" + key, "archived": archived,
            "results": {"potential_10": 0.35} if data_type == "LSV" else {"delta_ep_mV": 75},
        })

    for index in range(45):
        add_record(f"recent-{index:02d}")
    for index in range(35):
        add_record(f"series-{index:02d}", sample="SeriesNi", timestamp="2026-09-07T12:00:00")
    add_record("unique_old_cv", sample="Old needle", data_type="CV", timestamp="2026-09-01 00:00:00")
    add_record("needle_%_literal", sample="CV end boundary", data_type="CV", timestamp="2026-09-02T23:59:59.999999")
    add_record("cv-outside", sample="CV next day", data_type="CV", timestamp="2026-09-03 00:00:00")
    add_record("cv-archived", sample="Archived needle", data_type="CV", timestamp="2026-09-02 12:00:00", archived=True)
    for sample in ("RaceA", "RaceB", "RaceSwitch"):
        add_record(sample, sample=sample, timestamp="2026-08-01 12:00:00")
    for index in range(2):
        add_record(f"beta-{index}", sample="BetaExclusive", project="filters-beta")

    manager = V6ServerManager(port=_get_free_port())
    ok, message = manager.start()
    assert ok, message
    try:
        with _sync_playwright_factory()() as playwright:
            browser = _launch_chromium(playwright)
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                page.goto(f"http://127.0.0.1:{manager.port}/ui", wait_until="networkidle")
                page.click("#tab-btn-project")
                page.click('[data-project-id="filters-alpha"]', timeout=5000)
                page.wait_for_function("() => document.querySelectorAll('.project-result-row').length === 30")
            except Exception as exc:
                diagnostics = page.evaluate("() => ({ projects: document.querySelector('#project-list')?.textContent, status: document.querySelector('#project-status')?.textContent, history: document.querySelector('#project-history-list')?.textContent })")
                raise AssertionError(f"Project fixture could not load: {diagnostics}; page errors: {errors}") from exc
            yield page
            assert errors == []
            browser.close()
    finally:
        manager.stop()
        reset_runtime()


def _search(page, value):
    with page.expect_response(lambda response: _history_response(response, project="filters-alpha", q=value, cursor="")) as result:
        page.fill("#project-results-search", value)
    return result.value.json()


def _wait_rows(page, count):
    page.wait_for_function("count => document.querySelectorAll('.project-result-row').length === count", arg=count)


def test_project_search_finds_unloaded_filename_and_clears_record_selection(project_browser):
    page = project_browser
    assert "unique_old_cv.txt" not in page.locator("#project-history-list").inner_text()
    page.locator(".project-record-check").first.check()
    assert page.locator("#project-record-selection").is_visible()
    result = _search(page, "unique_old_cv")
    assert result["total"] == 1
    assert result["records"][0]["file_name"] == "unique_old_cv.txt"
    _wait_rows(page, 1)
    assert "Old needle" in page.locator("#project-history-list").inner_text()
    assert page.locator(".project-record-check:checked").count() == 0
    assert page.locator("#project-record-selection").is_hidden()
    assert page.locator("#project-history-load-more").is_hidden()
    assert "1 / 1" in page.locator("#project-history-page-status").inner_text()
    literal = _search(page, "%_")
    assert literal["total"] == 1
    page.wait_for_function("() => document.querySelector('#project-history-list').textContent.includes('needle_%_literal.txt')")


def test_project_type_date_combination_and_clear_use_full_database(project_browser):
    page = project_browser
    page.click("#project-results-filter-more > summary")
    page.select_option("#project-results-type", "CV")
    page.fill("#project-results-date-from", "2026-09-01")
    with page.expect_response(lambda response: _history_response(response, project="filters-alpha", type="CV", date_from="2026-09-01", date_to="2026-09-02")) as result:
        page.fill("#project-results-date-to", "2026-09-02")
    assert result.value.json()["total"] == 2
    _wait_rows(page, 2)
    content = page.locator("#project-history-list").inner_text()
    assert "unique_old_cv.txt" in content and "needle_%_literal.txt" in content
    assert "cv-outside.txt" not in content
    with page.expect_response(lambda response: _history_response(response, project="filters-alpha", type="CV", date_from="2026-09-01", date_to="2026-09-02", include_archived=1)) as result:
        page.check("#project-include-archived")
    assert result.value.json()["total"] == 3
    _wait_rows(page, 3)
    with page.expect_response(lambda response: _history_response(response, project="filters-alpha", q="", type="", date_from="", date_to="", cursor="")):
        page.click("#project-results-filter-clear")
    _wait_rows(page, 30)
    assert page.locator("#project-results-search").input_value() == ""
    assert page.locator("#project-results-type").input_value() == ""
    assert page.locator("#project-results-date-from").input_value() == ""
    assert page.locator("#project-results-date-to").input_value() == ""
    assert page.locator("#project-history-load-more").is_visible()


def test_project_load_more_keeps_filters_and_late_page_cannot_append_after_search(project_browser):
    page = project_browser
    page.click("#project-results-filter-more > summary")
    page.select_option("#project-results-type", "LSV")
    page.fill("#project-results-date-from", "2026-09-07")
    page.fill("#project-results-date-to", "2026-09-07")
    result = _search(page, "SeriesNi")
    assert result["total"] == 35
    _wait_rows(page, 30)
    with page.expect_response(lambda response: _history_response(response, project="filters-alpha", q="SeriesNi", type="LSV", date_from="2026-09-07", date_to="2026-09-07", cursor=result["next_cursor"])) as more:
        page.click("#project-history-load-more")
    assert more.value.json()["total"] == 35
    _wait_rows(page, 35)
    keys = page.locator(".project-result-row").evaluate_all("rows => rows.map(row => row.dataset.key)")
    assert len(set(keys)) == 35
    assert page.locator("#project-history-load-more").is_hidden()

    # Capture a real second-page response, then release it after another search.
    page.click("#project-results-filter-clear")
    _wait_rows(page, 30)
    _search(page, "SeriesNi")
    held = []

    def hold_more(route):
        query = _query(route.request.url)
        if query and query.get("project") == "filters-alpha" and query.get("q") == "SeriesNi" and query.get("cursor"):
            held.append((route, route.fetch()))
        else:
            route.continue_()

    page.route("**/api/v1/history?*", hold_more)
    with page.expect_request(lambda request: bool((_query(request.url) or {}).get("cursor"))):
        page.click("#project-history-load-more")
    result = _search(page, "unique_old_cv")
    assert result["total"] == 1
    _wait_rows(page, 1)
    assert len(held) == 1
    route, response = held.pop()
    route.fulfill(response=response)
    page.wait_for_load_state("networkidle")
    assert page.locator(".project-result-row").count() == 1
    assert "unique_old_cv.txt" in page.locator("#project-history-list").inner_text()


def test_project_search_and_project_switch_ignore_older_responses(project_browser):
    page = project_browser
    held = {}

    def delay_selected(route):
        query = _query(route.request.url)
        if query and query.get("project") == "filters-alpha" and query.get("q") in {"RaceA", "RaceSwitch"}:
            held[query["q"]] = (route, route.fetch())
        else:
            route.continue_()

    page.route("**/api/v1/history?*", delay_selected)
    with page.expect_request(lambda request: (_query(request.url) or {}).get("q") == "RaceA"):
        page.fill("#project-results-search", "RaceA")
    result = _search(page, "RaceB")
    assert result["total"] == 1
    _wait_rows(page, 1)
    page.wait_for_function("() => document.querySelector('#project-history-list').textContent.includes('RaceB.txt')")
    route, response = held.pop("RaceA")
    route.fulfill(response=response)
    page.wait_for_load_state("networkidle")
    assert "RaceB.txt" in page.locator("#project-history-list").inner_text()
    assert "RaceA.txt" not in page.locator("#project-history-list").inner_text()

    with page.expect_request(lambda request: (_query(request.url) or {}).get("q") == "RaceSwitch"):
        page.fill("#project-results-search", "RaceSwitch")
    with page.expect_response(lambda response: _history_response(response, project="filters-beta", q="", cursor="")) as other:
        page.click('[data-project-id="filters-beta"]')
    assert other.value.json()["total"] == 2
    _wait_rows(page, 2)
    assert page.locator("#project-results-search").input_value() == ""
    route, response = held.pop("RaceSwitch")
    route.fulfill(response=response)
    page.wait_for_load_state("networkidle")
    assert "Beta result filters" in page.locator("#project-detail-title").inner_text()
    assert page.locator(".project-result-row").count() == 2
    assert "BetaExclusive" in page.locator("#project-history-list").inner_text()
    assert "RaceSwitch.txt" not in page.locator("#project-history-list").inner_text()
