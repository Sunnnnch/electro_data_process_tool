"""Real-browser coverage of appearance migration, persistence and interaction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from electrochem_v6.config import APP_VERSION
from electrochem_v6.server import V6ServerManager
from electrochem_v6.store.runtime import reset_runtime
from test_v6_assistant_appearance_ui import _contrast
from test_v6_ui_playwright import _get_free_port, _launch_chromium, _sync_playwright_factory

DEFAULTS = {
    "version": 2,
    "style": "modern",
    "fontSize": "standard",
    "density": "comfortable",
    "grid": False,
    "chartBackground": "theme",
    "paletteByStyle": {"modern": {"id": "lab"}, "paper": {"id": "cream"}, "soft": {"id": "mist"}, "pixel": {"id": "cream"}},
}
LEGACY_DEFAULTS = {"version": 1, "theme": "lab", "fontSize": "standard", "density": "comfortable", "grid": False, "chartBackground": "theme"}


@pytest.fixture
def appearance_browser(monkeypatch, tmp_path):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    for key, name in {
        "ELECTROCHEM_V6_HISTORY_FILE": "history.json",
        "ELECTROCHEM_V6_PROJECTS_FILE": "projects.json",
        "ELECTROCHEM_V6_CONVERSATION_FILE": "conversations.json",
        "ELECTROCHEM_V6_TEMPLATE_FILE": "templates.json",
        "ELECTROCHEM_V6_QUALITY_REPORT_FILE": "quality.json",
    }.items():
        monkeypatch.setenv(key, str(tmp_path / name))
    reset_runtime()
    manager = V6ServerManager(port=_get_free_port())
    ok, message = manager.start()
    assert ok, message
    try:
        with _sync_playwright_factory()() as playwright:
            browser = _launch_chromium(playwright)
            errors = []

            def open_page(*, storage=None, color_scheme="light", width=1400, block_storage=False, route_setup=None, wait_for_app=True, navigation_wait="networkidle"):
                context = browser.new_context(viewport={"width": width, "height": 1000}, color_scheme=color_scheme)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                # Resource failures do not emit pageerror; retain them in pytest's
                # captured output to diagnose a failed startup without hiding it.
                page.on("requestfailed", lambda request: print(f"[browser:{page.url}] requestfailed {request.url}: {request.failure}"))
                page.on("response", lambda response: print(f"[browser:{page.url}] HTTP {response.status}: {response.url}") if response.status >= 400 else None)
                page.on("console", lambda message: print(f"[browser:{page.url}] console error: {message.text}") if message.type == "error" else None)
                page.add_init_script("""
                  window.__appearanceEvents = [];
                  window.__appearanceFrames = [];
                  window.addEventListener('electrochem:appearance-changed', event => {
                    window.__appearanceEvents.push({detail: event.detail, body: document.body?.dataset.theme});
                  });
                  function frame() {
                    if (document.body) window.__appearanceFrames.push(document.body.dataset.theme);
                    if (window.__appearanceFrames.length < 3) requestAnimationFrame(frame);
                  }
                  requestAnimationFrame(frame);
                """)
                if storage:
                    page.add_init_script("""
                      if (!sessionStorage.getItem('appearance-test-seeded')) {
                        Object.entries(%s).forEach(([key,value]) => localStorage.setItem(key,value));
                        sessionStorage.setItem('appearance-test-seeded','1');
                      }
                    """ % json.dumps(storage))
                if block_storage:
                    page.add_init_script("""
                      const get = Storage.prototype.getItem, set = Storage.prototype.setItem;
                      Storage.prototype.getItem = function(key) {
                        if (key.startsWith('electrochem_v6_appearance')) throw new DOMException('Blocked', 'SecurityError');
                        return get.call(this,key);
                      };
                      Storage.prototype.setItem = function(key,value) {
                        if (key === 'electrochem_v6_appearance') throw new DOMException('Full', 'QuotaExceededError');
                        return set.call(this,key,value);
                      };
                    """)
                if route_setup:
                    route_setup(page)
                page.goto(f"http://127.0.0.1:{manager.port}/ui", wait_until=navigation_wait)
                if wait_for_app:
                    page.wait_for_function("() => Boolean(window.ElectrochemAppearance && document.querySelector('#appearance-dialog'))")
                return page

            yield open_page
            assert errors == []
            browser.close()
    finally:
        manager.stop()
        reset_runtime()


def _prefs(page):
    return page.evaluate("ElectrochemTheme.getPreferences()")


def _choose_style(page, style):
    page.locator(f'input[name="appearance-style"][value="{style}"]').check()


def _choose_palette(page, palette):
    page.locator(f'input[name="appearance-palette"][value="{palette}"]').check()


def test_appearance_first_visit_is_lab_before_first_paint(appearance_browser):
    page = appearance_browser(color_scheme="dark")
    assert _prefs(page) == DEFAULTS
    assert page.locator("body").get_attribute("data-theme") == "lab"
    assert page.evaluate("window.__appearanceFrames") == ["lab"] * 3
    assert page.evaluate("JSON.parse(localStorage.getItem('electrochem_v6_appearance'))") == DEFAULTS
    page.click("#appearance-open")
    assert page.locator('[data-appearance-style="modern"]').evaluate("node => node.classList.contains('selected')")
    assert page.locator("#appearance-grid").is_checked() is False


@pytest.mark.parametrize("saved_theme", ["lab", "ocean", "dark", "pixel"])
def test_appearance_migrates_each_saved_theme_and_new_preferences_win(appearance_browser, saved_theme):
    page = appearance_browser(storage={"electrochem_v6_theme": saved_theme})
    expected = {**DEFAULTS, "style": "pixel" if saved_theme == "pixel" else "modern",
                "paletteByStyle": {**DEFAULTS["paletteByStyle"], "modern": {"id": saved_theme if saved_theme != "pixel" else "lab"}}}
    assert _prefs(page) == expected
    assert page.evaluate("window.__appearanceFrames") == [saved_theme] * 3
    page.click("#appearance-open")
    page.select_option("#appearance-font-size", "large")
    _choose_style(page, "modern" if saved_theme == "pixel" else "pixel")
    chosen = _prefs(page)
    page.reload(wait_until="networkidle")
    assert _prefs(page) == chosen
    assert page.evaluate("localStorage.getItem('electrochem_v6_theme')") == saved_theme


@pytest.mark.parametrize("stored", [
    "not-json", "null", "[]", '{"version":3,"style":"pixel"}',
    '{"version":1,"theme":"<bad>","fontSize":"huge","density":false,"grid":"false","chartBackground":"black"}',
])
def test_appearance_validates_broken_storage_without_stopping_the_page(appearance_browser, stored):
    page = appearance_browser(storage={"electrochem_v6_appearance": stored})
    assert _prefs(page) == DEFAULTS
    page.click("#appearance-open")
    assert page.locator("#appearance-title").inner_text() == "外观设置"


def test_startup_recovers_missing_result_module_before_binding_ui(appearance_browser):
    attempts = []
    during_retry = []

    def intercept(route):
        attempts.append(route.request.url)
        if len(attempts) == 1:
            route.abort()
            return
        # Hold the retry across two browser frames: the appearance controls must
        # not become interactive while a required result renderer is unavailable.
        during_retry.append(route.request.frame.evaluate("""() => new Promise(resolve => {
          requestAnimationFrame(() => requestAnimationFrame(() => resolve({
            appearanceBound: Boolean(document.querySelector('#appearance-dialog')),
            resultModuleReady: Boolean(window.ElectrochemProcessResultPage),
          })));
        })"""))
        route.continue_()

    page = appearance_browser(
        storage={"electrochem_v6_appearance": '{"version":1,"theme":"<bad>","fontSize":"huge","density":false,"grid":"false","chartBackground":"black"}'},
        route_setup=lambda page: page.route("**/process_result_page.js*", intercept),
    )
    assert len(attempts) == 2
    assert during_retry == [{"appearanceBound": False, "resultModuleReady": False}]
    assert _prefs(page) == DEFAULTS
    assert page.locator("#proc-result-summary").inner_text() == "暂无结果"
    page.click("#appearance-open")
    assert page.locator("#appearance-title").inner_text() == "外观设置"
    page.click("#appearance-close")
    page.select_option("#lang-select", "en")
    assert page.locator("#proc-result-summary").inner_text() == "No result yet"
    assert page.locator("#app-startup-error").count() == 0


def test_startup_module_failure_is_visible_and_reload_can_recover(appearance_browser):
    attempts = []
    blocked = True

    def intercept(route):
        attempts.append(route.request.url)
        if blocked:
            route.abort()
        else:
            route.continue_()

    page = appearance_browser(
        route_setup=lambda page: page.route("**/process_result_page.js*", intercept),
        wait_for_app=False,
    )
    page.locator("#app-startup-error").wait_for(state="visible", timeout=3000)
    assert len(attempts) == 2
    assert "界面模块加载失败" in page.locator("#app-startup-error").inner_text()
    assert "process_result_page.js" in page.locator("#app-startup-error").inner_text()
    assert page.locator("#app-startup-error").get_attribute("role") == "alert"
    assert page.locator("#appearance-dialog").count() == 0
    blocked = False
    page.click("#app-startup-reload")
    page.wait_for_function("() => Boolean(document.querySelector('#appearance-dialog'))")
    assert len(attempts) == 3
    assert page.locator("#app-startup-error").count() == 0
    assert page.locator("#proc-result-summary").inner_text() == "暂无结果"
    page.click("#appearance-open")
    assert page.locator("#appearance-title").inner_text() == "外观设置"


def test_appearance_system_follows_changes_and_manual_choice_stays_fixed(appearance_browser):
    page = appearance_browser(color_scheme="light")
    page.click("#appearance-open")
    _choose_palette(page, "system")
    page.emulate_media(color_scheme="dark")
    page.wait_for_function("() => document.body.dataset.theme === 'dark'")
    assert _prefs(page)["paletteByStyle"]["modern"] == {"id": "system"}
    page.emulate_media(color_scheme="light")
    page.wait_for_function("() => document.body.dataset.theme === 'lab'")
    page.emulate_media(color_scheme="dark")
    page.wait_for_function("() => document.body.dataset.theme === 'dark'")
    page.reload(wait_until="networkidle")
    assert _prefs(page)["paletteByStyle"]["modern"] == {"id": "system"}
    assert page.evaluate("window.__appearanceFrames") == ["dark"] * 3
    page.click("#appearance-open")
    assert page.locator('input[name="appearance-palette"][value="system"]').is_checked()
    _choose_palette(page, "ocean")
    page.emulate_media(color_scheme="light")
    page.emulate_media(color_scheme="dark")
    assert page.locator("body").get_attribute("data-theme") == "ocean"
    assert _prefs(page)["paletteByStyle"]["modern"] == {"id": "ocean"}
    assert page.evaluate("window.__appearanceEvents.filter(e => e.body).every(e => e.detail.theme === e.body)")


def test_appearance_controls_are_independent_persist_and_reset_visibly(appearance_browser):
    page = appearance_browser()
    page.fill("#pro-area", "2.5")
    page.click("#appearance-open")
    page.select_option("#appearance-font-size", "large")
    page.select_option("#appearance-density", "compact")
    page.check("#appearance-grid")
    page.select_option("#appearance-chart-background", "paper")
    _choose_style(page, "pixel")
    expected = {**DEFAULTS, "style": "pixel", "fontSize": "large", "density": "compact", "grid": True, "chartBackground": "paper"}
    assert _prefs(page) == expected
    assert page.evaluate("getComputedStyle(document.body).getPropertyValue('--ui-font-size').trim()") == "16px"
    assert page.evaluate("getComputedStyle(document.body).getPropertyValue('--font-space').trim()") == "4px"
    assert page.locator("body").get_attribute("data-density") == "compact"
    assert page.locator("body").get_attribute("data-grid") == "true"
    assert page.locator("#appearance-status").inner_text() == "已应用并保存。"
    page.select_option("#appearance-font-size", "extra-large")
    assert _prefs(page)["density"] == "compact"
    assert page.evaluate("getComputedStyle(document.body).getPropertyValue('--ui-font-scale').trim()") == "1.285714"
    assert page.evaluate("getComputedStyle(document.body).getPropertyValue('--font-space').trim()") == "8px"
    page.click("#appearance-close")
    assert page.locator("#pro-area").input_value() == "2.5"
    page.reload(wait_until="networkidle")
    assert _prefs(page) == {**expected, "fontSize": "extra-large"}
    page.click("#appearance-open")
    page.click("#appearance-reset")
    assert _prefs(page) == DEFAULTS
    assert "已恢复默认" in page.locator("#appearance-status").inner_text()
    assert page.locator('input[name="appearance-style"][value="modern"]').is_checked()
    assert page.locator("#appearance-font-size").input_value() == "standard"
    assert page.locator("#appearance-density").input_value() == "comfortable"
    assert page.locator("#appearance-chart-background").input_value() == "theme"
    assert page.locator("#appearance-grid").is_checked() is False


def test_appearance_storage_denied_keeps_changes_in_memory(appearance_browser):
    page = appearance_browser(block_storage=True)
    page.click("#appearance-open")
    _choose_palette(page, "dark")
    page.select_option("#appearance-font-size", "large")
    assert _prefs(page)["paletteByStyle"]["modern"] == {"id": "dark"}
    assert _prefs(page)["fontSize"] == "large"
    assert "仅在本次页面" in page.locator("#appearance-status").inner_text()
    page.evaluate("ElectrochemTheme.init()")
    assert _prefs(page)["fontSize"] == "large"
    page.click("#appearance-close")
    page.click("#appearance-open")
    assert page.locator('input[name="appearance-palette"][value="dark"]').is_checked()


def test_appearance_keyboard_language_and_600px_layout(appearance_browser):
    page = appearance_browser(width=600)
    page.select_option("#lang-select", "en")
    page.locator("#appearance-open").focus()
    page.keyboard.press("Enter")
    assert page.locator("#appearance-title").inner_text() == "Appearance settings"
    assert page.evaluate("document.activeElement.id") == "appearance-close"
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.name") == "appearance-style"
    page.keyboard.press("ArrowRight")
    assert _prefs(page)["style"] == "paper"
    page.select_option("#appearance-font-size", "extra-large")
    page.select_option("#appearance-density", "compact")
    dimensions = page.locator("#appearance-dialog").evaluate("node => ({width: node.getBoundingClientRect().width, client: node.clientWidth, scroll: node.scrollWidth, viewport: innerWidth})")
    assert dimensions["width"] <= dimensions["viewport"]
    assert dimensions["scroll"] <= dimensions["client"] + 1
    for selector in ("#appearance-font-size", "#appearance-density", "#appearance-chart-background", "#appearance-grid", "#appearance-reset", "#appearance-close"):
        page.locator(selector).focus()
        assert page.locator(selector).evaluate("node => document.activeElement === node")
    page.keyboard.press("Escape")
    assert page.locator("#appearance-dialog").is_visible() is False
    assert page.evaluate("document.activeElement.id") == "appearance-open"
    page.keyboard.press("Enter")
    assert _prefs(page)["style"] == "paper"
    assert page.locator("#appearance-dialog").is_visible()


def test_dark_settings_and_rendered_ir_pairings_keep_readable_surfaces(appearance_browser):
    page = appearance_browser(storage={"electrochem_v6_appearance": json.dumps({**DEFAULTS, "paletteByStyle": {"modern": {"id": "dark"}, "pixel": {"id": "cream"}}})})

    def assert_contrast(selector):
        node = page.locator(selector).first
        assert node.is_visible(), selector
        colors = node.evaluate("""node => {
          const foreground = getComputedStyle(node).color;
          const images = [];
          while (node) {
            const style = getComputedStyle(node);
            images.push(style.backgroundImage);
            if (style.backgroundColor !== 'rgba(0, 0, 0, 0)') {
              return {foreground, background:style.backgroundColor, images};
            }
            node = node.parentElement;
          }
          return {foreground, background:'rgb(255, 255, 255)', images};
        }""")
        # These reading panels use solid semantic surfaces. A surviving white
        # gradient must not be skipped in favor of its dark ancestor's color.
        assert all(image == "none" for image in colors["images"]), (selector, colors)
        assert not colors["background"].startswith("rgba"), (selector, colors)
        assert _contrast(colors["foreground"], colors["background"]) >= 4.5, (selector, colors)

    page.click("#assistant-fab")
    page.click("#ai-settings-open")
    page.fill("#prompt-prefix", "保留单位并说明分析条件。")
    page.click("#prompt-save")
    assert page.locator("#llm-status").inner_text()
    for selector in (
        "#ai-settings-panel .sys-panel-head h3", ".ai-section-config h4", ".ai-section-config .section-sub",
        'label[for="llm-provider"]', "#llm-key-hint", "#llm-source-hint", ".toggle-row label",
        ".ai-section-prompt > .hint", "#llm-status",
    ):
        assert_contrast(selector)
    page.click("#ai-settings-close")
    page.keyboard.press("Escape")
    # Exercise the original preflight renderer and model with the API scan shape.
    page.evaluate("""() => {
      latestPreflightScan = {
        text_files:3, work_units:2,
        by_type:{LSV:{matched:2, examples:['LSV_A.txt','LSV_B.txt']}},
        ir_compensation:{items:[
          {status:'matched', lsv_file:'LSV_A.txt', eis_file:'EIS_A.txt', scope:'sample', extraction_method:'intercept'},
          {status:'missing', lsv_file:'LSV_B.txt', eis_file:'', message:'No matching EIS source', scope:'sample'}
        ]}
      };
      preflightFileDetailOpen = true;
      renderPreflightFileDetail();
    }""")
    assert page.locator(".preflight-ir-pair").count() == 2
    for selector in (
        ".preflight-ir-pair.ok .preflight-ir-files span", ".preflight-ir-pair.ok .preflight-ir-meta strong",
        ".preflight-ir-pair.ok .preflight-ir-meta span", ".preflight-ir-pair.issue .preflight-ir-files span",
        ".preflight-ir-pair.issue .preflight-ir-message",
    ):
        assert_contrast(selector)


@pytest.mark.parametrize("delay_health", [False, True], ids=["normal-health", "delayed-health"])
def test_product_name_language_and_manual_assets_fit_desktop_and_narrow_screens(appearance_browser, delay_health):
    def configure_health_delay(page):
        if delay_health:
            # Keep the real server response, but deliver it after the language
            # change handler returns. A synchronous route handler would hide
            # this race by blocking the Playwright action itself.
            page.add_init_script("""(() => {
              const fetch = window.fetch.bind(window);
              window.fetch = async (input, init) => {
                const response = await fetch(input, init);
                const url = input instanceof Request ? input.url : String(input);
                if (new URL(url, location.href).pathname === '/health') {
                  await new Promise(resolve => setTimeout(resolve, 500));
                }
                return response;
              };
            })();""")

    page = appearance_browser(width=1440, route_setup=configure_health_delay)
    screenshot_dir = Path(__file__).resolve().parents[1] / ".test_runtime" / "rename"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    expected_names = {
        "zh": "ElectroChem｜智能电化学数据处理软件",
        "en": "ElectroChem | Intelligent Electrochemical Data Processing Software",
    }
    for width in (1440, 600):
        page.set_viewport_size({"width": width, "height": 1000})
        for language, name in expected_names.items():
            page.select_option("#lang-select", language)
            assert page.title() == name
            assert page.locator(".hero .badge").inner_text() == name
            assert APP_VERSION not in name
            # Language changes start a new health request and reset the version
            # to "-" until its response has been rendered.
            page.wait_for_function(
                "version => document.querySelector('#sys-panel-version').textContent === version",
                arg=APP_VERSION,
                timeout=5000,
            )
            assert page.locator("#sys-panel-version").inner_text() == APP_VERSION
            assert page.locator('label[for="pro-ecsa-ev"]').inner_text() == ("评价电位 Ev (V)" if language == "zh" else "Evaluation potential Ev (V)")
            bounds = page.locator(".hero").evaluate("""hero => {
              const badge = hero.querySelector('.badge'), rect = badge.getBoundingClientRect();
              return {viewport:innerWidth, right:rect.right, left:rect.left, badgeWidth:badge.clientWidth,
                badgeScroll:badge.scrollWidth, headerWidth:hero.clientWidth, headerScroll:hero.scrollWidth};
            }""")
            assert bounds["left"] >= 0 and bounds["right"] <= bounds["viewport"], bounds
            assert bounds["badgeScroll"] <= bounds["badgeWidth"] + 1, bounds
            assert bounds["headerScroll"] <= bounds["headerWidth"] + 1, bounds
            for font_size in ("standard", "extra-large"):
                page.evaluate("fontSize => ElectrochemTheme.update({fontSize})", font_size)
                text_bounds = page.locator(".hero .badge").evaluate("""badge => {
                  const range = document.createRange(); range.selectNodeContents(badge);
                  const box = badge.getBoundingClientRect();
                  return {box:{left:box.left,right:box.right,top:box.top,bottom:box.bottom},
                    lines:Array.from(range.getClientRects(), rect => ({left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom}))};
                }""")
                assert text_bounds["lines"], text_bounds
                for line in text_bounds["lines"]:
                    assert line["left"] >= text_bounds["box"]["left"] - 1, text_bounds
                    assert line["right"] <= text_bounds["box"]["right"] + 1, text_bounds
                    assert line["top"] >= text_bounds["box"]["top"] - 1, text_bounds
                    assert line["bottom"] <= text_bounds["box"]["bottom"] + 1, text_bounds
            page.evaluate("ElectrochemTheme.update({fontSize:'standard'})")
            page.locator(".hero").screenshot(path=str(screenshot_dir / f"brand-{language}-{width}.png"))
            page.click("#help-docs-btn")
            page.wait_for_function("() => document.querySelectorAll('#help-doc-body .help-guide-figure img').length === 2")
            images = page.locator("#help-doc-body .help-guide-figure img")
            for image in images.all():
                image.scroll_into_view_if_needed()
                image.evaluate("image => image.decode()")
                assert image.evaluate("image => image.naturalWidth > 0 && image.getBoundingClientRect().width <= image.parentElement.clientWidth + 1")
                assert image.get_attribute("src").endswith(f".{language}.png")
            original_link = page.locator("#help-doc-body .help-guide-figure a").first
            with page.expect_popup() as opening:
                original_link.click()
            original = opening.value
            original.wait_for_load_state("domcontentloaded")
            assert original.url.endswith(f"/ui/static/guide-professional.{language}.png")
            original.close()
            page.evaluate("ElectrochemTheme.update({fontSize:'extra-large'})")
            assert page.locator("#help-doc-body").evaluate("node => parseFloat(getComputedStyle(node).fontSize)") == 19
            assert page.locator("#help-doc-scroll").evaluate("node => node.scrollWidth <= node.clientWidth + 1")
            download_link = page.locator('#help-doc-body a[download="CV_demo.csv"]')
            assert download_link.count() >= 1
            with page.expect_download() as downloading:
                download_link.first.click()
            download = downloading.value
            assert download.suggested_filename == "CV_demo.csv"
            downloaded_bytes = Path(download.path()).read_bytes()
            source = Path(__file__).resolve().parents[1] / "src/electrochem_v6/ui/static/guide-cv-demo.csv"
            assert downloaded_bytes == source.read_bytes()
            assert downloaded_bytes
            page.keyboard.press("Escape")
            page.evaluate("ElectrochemTheme.update({fontSize:'standard'})")

    restricted = page.evaluate("""() => {
      const raw = '![bad](../guide-project.zh.png)\\n\\n![bad](file:///private.png)\\n\\n![bad](/ui/static/arbitrary.png)\\n\\n[bad](../config.json)\\n\\n`[code](guide-cv-demo.csv)`';
      const manual = new DOMParser().parseFromString(renderMarkdownDocument(raw).html, 'text/html');
      const assistant = new DOMParser().parseFromString(renderMarkdownContent('![guide](guide-project.zh.png)\\n\\n[demo](guide-cv-demo.csv)'), 'text/html');
      return {manualImages:manual.images.length, manualLinks:manual.querySelectorAll('a').length,
        assistantImages:assistant.images.length, assistantLinks:assistant.querySelectorAll('a').length};
    }""")
    assert restricted == {"manualImages": 0, "manualLinks": 0, "assistantImages": 0, "assistantLinks": 0}
