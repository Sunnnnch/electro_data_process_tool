"""Recover fixed startup dependencies without partially initializing the UI."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from test_v6_appearance_ui import DEFAULTS
from test_v6_appearance_ui import appearance_browser as appearance_browser

API_CAPTURES = {"process_schema.js", "assistant_api.js", "llm_api.js", "project_api.js", "system_api.js", "processing_api.js"}


@pytest.mark.parametrize("missing", [
    ("project_page.js",),
    ("project_page.js", "process_result_page.js", "process_schema.js"),
    ("api.js",),
    ("i18n.js",),
    ("palette.js",),
])
def test_startup_recovers_dependencies_before_real_project_actions(appearance_browser, missing):
    attempts = Counter()
    recovered = []
    failed_initial = set()
    custom = {"id": "custom", "colors": {
        "background": "#E4E9F0", "surface": "#F8FAFD", "primary": "#355B8C",
        "text": "#25374B", "titlebar": "#B9CADF",
    }}
    preferences = {**DEFAULTS, "paletteByStyle": {**DEFAULTS["paletteByStyle"], "modern": custom}}

    def intercept(route):
        filename = urlsplit(route.request.url).path.rsplit("/", 1)[-1]
        attempts[filename] += 1
        if filename in missing and attempts[filename] == 1:
            route.abort()
        else:
            if attempts[filename] > 1:
                recovered.append(filename)
                assert not route.request.frame.evaluate("() => Boolean(document.querySelector('#appearance-dialog'))")
            route.continue_()

    def configure(page):
        def failed(request):
            url = urlsplit(request.url)
            if url.path.startswith("/ui/static/") and url.path.endswith(".js") and not url.query:
                failed_initial.add(url.path.rsplit("/", 1)[-1])

        page.on("requestfailed", failed)
        page.route("**/ui/static/*.js*", intercept)

    page = appearance_browser(
        storage={"electrochem_v6_appearance": json.dumps(preferences)},
        route_setup=configure,
    )
    # The host may also report a real initial network failure (for example
    # ERR_NO_BUFFER_SPACE). Only observed bundled failures justify extra recovery.
    expected = set(missing) | failed_initial
    if "api.js" in expected:
        expected |= API_CAPTURES
    if "i18n.js" in expected:
        expected |= {"workflow_i18n.js", "appearance.js"}
    assert set(recovered) == expected
    assert all(attempts[name] == (2 if name in expected else 1) for name in attempts)
    order = page.evaluate("startupModules.map(entry => entry.file)")
    assert recovered == [name for name in order if name in expected]
    assert page.locator("#app-startup-error").count() == 0
    assert page.locator("#proc-result-summary").inner_text() == "暂无结果"
    assert page.evaluate("ElectrochemTheme.getPreferences().paletteByStyle.modern") == custom
    assert page.evaluate("projectPage === ElectrochemProjectPage && processResultPage === ElectrochemProcessResultPage && processSchemaClient === ElectrochemProcessingSchema")

    if "api.js" in missing:
        # All six clients must have captured the recovered API object. Observe
        # real requests through it; do not replace their responses or outputs.
        calls = page.evaluate("""async () => {
          const calls = [], api = ElectrochemApi, fetch = api.fetch;
          api.fetch = (...args) => { calls.push(String(args[0])); return fetch(...args); };
          try {
            await ElectrochemProcessingSchema.load(['CV']);
            await ElectrochemAssistantApi.listConversations({});
            await ElectrochemLLMApi.getConfig();
            await ElectrochemProjectApi.listProjects({});
            await ElectrochemSystemApi.health();
            await ElectrochemProcessingApi.listTemplates();
          } finally { api.fetch = fetch; }
          return calls;
        }""")
        assert {urlsplit(url).path for url in calls} >= {
            "/api/v1/process/schema", "/api/v1/agent/conversations", "/api/v1/llm/config",
            "/api/v1/projects", "/health", "/api/v1/process/templates",
        }

    page.click("#appearance-open")
    assert page.locator("#appearance-title").inner_text() == "外观设置"
    page.click("#appearance-close")
    assert page.locator("#task-center-label").inner_text().startswith("任务")
    page.click("#tab-btn-project")
    page.click("#project-create-btn")
    page.fill("#project-create-name", "Startup recovery")
    with page.expect_response(lambda response: response.request.method == "POST" and "/projects" in response.url) as saved:
        page.click("#project-create-submit")
    assert saved.value.ok
    page.wait_for_function("() => document.querySelector('#project-list').textContent.includes('Startup recovery')")
    page.select_option("#lang-select", "en")
    page.click("#appearance-open")
    assert page.locator("#appearance-title").inner_text() == "Appearance settings"
    assert page.locator("#task-center-label").inner_text().startswith("Tasks")


def test_startup_normal_path_has_no_reloads_and_does_not_bind_twice(appearance_browser):
    requests = []
    static = Path(__file__).resolve().parents[1] / "src/electrochem_v6/ui/static"

    def configure(page):
        page.on("request", lambda request: requests.append(request.url))
        # Exercise the real bundled scripts with guaranteed successful transport,
        # so an unrelated host socket failure cannot turn this into recovery.
        page.route("**/ui/static/*.js*", lambda route: route.fulfill(
            status=200, content_type="text/javascript",
            body=(static / urlsplit(route.request.url).path.rsplit("/", 1)[-1]).read_text(encoding="utf-8"),
        ))

    page = appearance_browser(route_setup=configure)
    scripts = Counter(urlsplit(url).path.rsplit("/", 1)[-1] for url in requests if urlsplit(url).path.endswith(".js"))
    assert all("startup-recovery" not in urlsplit(url).query for url in requests)
    assert scripts and all(count == 1 for count in scripts.values())
    calls = page.evaluate("""() => {
      const original = ElectrochemTaskCenter.init; let count = 0;
      ElectrochemTaskCenter.init = (...args) => { count++; return original(...args); };
      try { init(); init(); } finally { ElectrochemTaskCenter.init = original; }
      return count;
    }""")
    assert calls == 0
    assert page.locator("#proc-result-summary").inner_text() == "暂无结果"


def test_startup_rejects_a_persistently_invalid_project_export(appearance_browser):
    attempts = []

    def intercept(route):
        attempts.append(route.request.url)
        route.fulfill(status=200, content_type="text/javascript", body="window.ElectrochemProjectPage = {};")

    page = appearance_browser(route_setup=lambda page: page.route("**/project_page.js*", intercept), wait_for_app=False)
    page.locator("#app-startup-error").wait_for(state="visible")
    assert len(attempts) == 2
    assert "project_page.js" in page.locator("#app-startup-error").inner_text()
    assert page.locator("#appearance-dialog").count() == 0


def test_startup_timeout_stops_batch_and_ignores_late_load(appearance_browser):
    attempts = Counter()
    held = []

    def configure(page):
        page.clock.install()

        def intercept(route):
            filename = urlsplit(route.request.url).path.rsplit("/", 1)[-1]
            attempts[filename] += 1
            if attempts[filename] == 1:
                route.abort()
            else:
                held.append(route)

        page.route("**/project_page.js*", intercept)
        page.route("**/process_result_page.js*", intercept)

    page = appearance_browser(route_setup=configure, wait_for_app=False, navigation_wait="domcontentloaded")
    page.wait_for_function("() => startupState === 'recovering'")
    page.evaluate("() => { window.__lateStartupLoad = [...document.scripts].find(script => script.onload && new URL(script.src).pathname.endsWith('process_result_page.js')).onload; }")
    page.clock.fast_forward(15001)
    assert page.locator("#app-startup-error").is_visible()
    assert attempts == {"process_result_page.js": 2, "project_page.js": 1}
    assert len(held) == 1
    source = Path(__file__).resolve().parents[1] / "src/electrochem_v6/ui/static/process_result_page.js"
    held[0].fulfill(status=200, content_type="text/javascript", body=source.read_text(encoding="utf-8"))
    page.evaluate("() => window.__lateStartupLoad()")
    assert page.locator("#appearance-dialog").count() == 0
    assert page.evaluate("startupState") == "failed"
    assert attempts["project_page.js"] == 1
