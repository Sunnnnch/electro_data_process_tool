"""Desktop UI with the real HTTP/UI pipeline and a deterministic native bridge."""

from __future__ import annotations

import copy
import json

import pytest

from conftest import _write_tsv, make_cv_rows
from electrochem_v6.config import APP_VERSION
from electrochem_v6.server import V6ServerManager
from electrochem_v6.store.conversations import append_message
from electrochem_v6.store.projects import create_project
from electrochem_v6.store.runtime import reset_runtime
from test_v6_ui_playwright import _get_free_port, _launch_chromium, _sync_playwright_factory


@pytest.fixture
def desktop_browser(monkeypatch, tmp_path):
    data = tmp_path / "runtime"
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(data))
    for key, name in {
        "ELECTROCHEM_V6_HISTORY_FILE": "history.json",
        "ELECTROCHEM_V6_PROJECTS_FILE": "projects.json",
        "ELECTROCHEM_V6_CONVERSATION_FILE": "conversations.json",
        "ELECTROCHEM_V6_TEMPLATE_FILE": "templates.json",
        "ELECTROCHEM_V6_QUALITY_REPORT_FILE": "quality.json",
    }.items():
        monkeypatch.setenv(key, str(data / name))
    reset_runtime()
    project = create_project("Desktop restored project")["project"]
    conversation_id = append_message(None, "assistant", "Saved desktop conversation")
    folder = tmp_path / "inputs"
    folder.mkdir()
    source = _write_tsv(folder / "CV_selected.txt", make_cv_rows(n_half=20))
    _write_tsv(folder / "CV_unselected.txt", make_cv_rows(n_half=20))
    managers = []

    def start_manager():
        manager = V6ServerManager(port=_get_free_port())
        ok, message = manager.start()
        assert ok, message
        managers.append(manager)
        return manager

    manager = start_manager()
    native = {
        "status": "success", "version": APP_VERSION, "tray_available": True,
        "preferences": {
            "local_storage": {
                "electrochem_v6_lang": "en",
                "electrochem_v6_appearance": json.dumps({
                    "version": 1, "theme": "dark", "fontSize": "large",
                    "density": "compact", "grid": False, "chartBackground": "paper",
                }),
            },
            "workspace": {"tab": "project", "project_id": project["id"], "conversation_id": conversation_id, "assistant_open": False},
        },
        "closing": {"waiting": False, "tasks": [], "active_count": 0},
        "environment_report": {
            "status": "success", "report_text": "ElectroChem environment check\nWindows 11 x64\nWebView2: update recommended\nData: C:/Users/Example/ElectroChem",
            "report": {
                "schema_version": 1, "can_start": True, "summary": "环境检查完成，有一项需留意。", "summary_en": "Environment check complete. One item needs attention.",
                "checks": [
                    {"id": "system", "label": "操作系统", "label_en": "Operating system", "status": "pass", "detail": "Windows 11，64 位", "detail_en": "Windows 11, 64-bit"},
                    {"id": "webview2", "label": "WebView2 运行库", "label_en": "WebView2 Runtime", "status": "warn", "detail": "建议更新运行库。", "detail_en": "A runtime update is recommended.", "remedy": "请使用离线完整安装包。", "remedy_en": "Use the complete offline installer."},
                    {"id": "data_directory", "label": "数据目录", "label_en": "Data folder", "status": "pass", "detail": "可以读写。", "detail_en": "Readable and writable."},
                ],
            },
        },
    }
    calls = []

    def bridge(method, args):
        calls.append((method, copy.deepcopy(args)))
        if method == "get_state":
            return copy.deepcopy(native)
        if method == "save_preferences":
            native["preferences"] = copy.deepcopy(args[0])
        if method == "set_window_appearance":
            native["window_appearance"] = copy.deepcopy(args[0])
        if method == "choose_import_files":
            return {"status": "success", "file_paths": [str(source)]}
        if method == "resolve_close":
            choice = args[0]
            if native["closing"].get("waiting"):
                return {"status": "success", "closing": copy.deepcopy(native["closing"])}
            native["closing"]["waiting"] = choice in ("wait", "cancel")
            native["closing"]["mode"] = choice if choice in ("wait", "cancel") else None
            return {"status": "success", "closing": copy.deepcopy(native["closing"])}
        if method == "get_migration_plan":
            return {"status": "success", "candidates": [
                {"source_id": "legacy-user", "label": "Legacy data", "source_dir": "C:/old/data", "target_dir": "C:/new/data", "can_migrate": True, "files_count": 4},
                {"source_id": "blocked", "label": "Existing data", "can_migrate": False, "reason": "Target already contains data"},
            ]}
        if method == "check_updates":
            return {"status": "success", "state": "update_available", "update_available": True, "current_version": APP_VERSION, "latest_version": "7.0.2", "release_notes": "<img src=x onerror=alert('unsafe')>"}
        if method == "get_environment_report":
            return copy.deepcopy(native["environment_report"])
        return {"status": "success"}

    try:
        with _sync_playwright_factory()() as playwright:
            browser = _launch_chromium(playwright)
            errors = []

            def open_page(*, width=1440, native_bridge=True, new_port=False, fail_bridge=False, late_bridge=False, color_scheme="light", forced_colors="none"):
                target = start_manager() if new_port else manager
                page = browser.new_page(viewport={"width": width, "height": 1050}, color_scheme=color_scheme, forced_colors=forced_colors)
                page.on("pageerror", lambda error: errors.append(str(error)))
                # Include the page origin so failures across two local ports can
                # be distinguished in captured CI output.
                page.on("requestfailed", lambda request: print(f"[browser:{page.url}] requestfailed {request.url}: {request.failure}"))
                page.on("response", lambda response: print(f"[browser:{page.url}] HTTP {response.status}: {response.url}") if response.status >= 400 else None)
                page.on("console", lambda message: print(f"[browser:{page.url}] console error: {message.text}") if message.type == "error" else None)
                if native_bridge:
                    page.expose_function("desktop_test_bridge", bridge)
                    page.add_init_script("""(() => {
                      const methods = ['get_state','save_preferences','set_window_appearance','choose_import_files','save_download','save_export','save_result','open_external','open_data_dir','get_migration_plan','migrate_legacy','check_updates','get_environment_report','hide_to_tray','request_exit','resolve_close'];
                      function connect() {
                        window.pywebview = {api:Object.fromEntries(methods.map(method => [method, (...args) => window.desktop_test_bridge(method,args)]))};
                        if (%s) window.pywebview.api.get_state = async () => { throw new Error('Bridge not available'); };
                        window.dispatchEvent(new Event('pywebviewready'));
                      }
                      if (%s) window.addEventListener('DOMContentLoaded', () => setTimeout(connect, 80)); else connect();
                    })();""" % (json.dumps(fail_bridge), json.dumps(late_bridge)))
                suffix = "?desktop=1" if native_bridge else ""
                page.goto(f"http://127.0.0.1:{target.port}/ui{suffix}", wait_until="networkidle")
                if native_bridge and not fail_bridge:
                    page.wait_for_selector("#desktop-menu-open")
                    page.wait_for_function("() => ElectrochemDesktop.isReady()")
                return page

            yield open_page, native, calls, source, project, conversation_id
            assert not errors
            browser.close()
    finally:
        for current in managers:
            current.stop()
        reset_runtime()


def test_desktop_restores_preferences_and_navigation_across_ports_without_inputs(desktop_browser):
    open_page, native, calls, _source, project, conversation_id = desktop_browser
    page = open_page(late_bridge=True)
    assert page.locator("body").get_attribute("data-theme") == "dark"
    assert page.locator("#lang-select").input_value() == "en"
    assert page.locator("#tab-project").evaluate("node => node.classList.contains('active')")
    assert page.evaluate("selectedProjectId") == project["id"]
    assert page.evaluate("currentConversationId") == conversation_id
    assert page.locator("#proc-folder").input_value() == ""
    assert page.evaluate("processSourceItems.length") == 0
    assert page.locator("#sys-status-text").inner_text() == "Desktop app ready"
    page.click("#appearance-open")
    page.select_option("#appearance-font-size", "extra-large")
    page.keyboard.press("Escape")
    page.select_option("#lang-select", "zh")
    page.click("#tab-btn-pro")
    page.click("#assistant-fab")
    page.evaluate("() => ElectrochemDesktop.persist()")
    assert native["preferences"]["workspace"]["assistant_open"] is True
    assert set(native["preferences"]) == {"workspace", "local_storage"}
    assert set(native["preferences"]["local_storage"]) <= {"electrochem_v6_appearance", "electrochem_v6_theme", "electrochem_v6_lang"}
    page2 = open_page(new_port=True)
    assert page2.url != page.url
    assert page2.locator("#lang-select").input_value() == "zh"
    assert page2.locator("body").get_attribute("data-font-size") == "extra-large"
    assert page2.locator("#assistant-drawer").is_visible()
    assert page2.evaluate("currentConversationId") == conversation_id
    assert page2.locator("#proc-folder").input_value() == ""
    assert not [item for item in calls if item[0] == "save_result"]


def test_desktop_native_file_event_uses_discovery_exact_list_and_invalidates_preflight(desktop_browser):
    open_page, _native, _calls, source, _project, _conversation = desktop_browser
    page = open_page()
    requests = []
    page.on("request", lambda request: requests.append((request.url, request.post_data_json)) if request.method == "POST" else None)
    page.evaluate("processPreflightState = 'passed'")
    with page.expect_response(lambda response: response.url.endswith("/api/v1/process/discover-inputs")) as discovery:
        page.evaluate("paths => window.dispatchEvent(new CustomEvent('electrochem:desktop-files', {detail:{paths}}))", [str(source)])
    assert discovery.value.ok
    page.wait_for_function("() => processSourceItems.length === 1")
    assert page.evaluate("processSourceItems.map(item => item.path)") == [str(source)]
    assert page.evaluate("processPreflightState") == "pending"
    assert page.locator("#proc-source-list").inner_text().count("CV_selected.txt") >= 1
    assert "CV_unselected.txt" not in page.locator("#proc-source-list").inner_text()
    assert page.evaluate("collectProcessPayload().input_files.map(item => item.path)") == [str(source)]
    assert not [url for url, _body in requests if url.endswith("/process/jobs")]
    page.click("#proc-preflight-btn")
    page.wait_for_function("() => processPreflightState === 'complete'")
    assert any(url.endswith("/preflight") for url, _body in requests)
    page.click("#desktop-menu-open")
    page.click("#desktop-import")
    page.wait_for_function("() => processSourceItems.length === 1")


def test_desktop_exports_and_manual_links_use_native_dialogs(desktop_browser):
    open_page, _native, calls, _source, _project, _conversation = desktop_browser
    page = open_page()
    page.click("#help-docs-btn")
    page.wait_for_selector("#help-doc-body .help-guide-figure a")
    page.locator("#help-doc-body a[download]").click()
    page.wait_for_function("() => document.querySelector('#desktop-status').textContent !== 'Working…'")
    assert any(method == "save_download" and args[0].endswith("/ui/static/guide-cv-demo.csv") and args[1] == "CV_demo.csv" for method, args in calls)
    page.locator("#help-doc-body .help-guide-figure a").first.click()
    page.wait_for_timeout(100)
    assert any(method == "open_external" and args[0].endswith("guide-professional.en.png") for method, args in calls)
    page.keyboard.press("Escape")
    page.locator(".github-link").click()
    page.wait_for_timeout(100)
    assert any(method == "open_external" and args[0].startswith("https://github.com/") for method, args in calls)
    page.evaluate("""() => {
      const node = document.createElement('button'); node.dataset.openPath = 'C:/results/report.html';
      node.textContent = 'Open report'; document.querySelector('.hero').append(node);
    }""")
    page.wait_for_selector(".desktop-save-result")
    assert page.locator("[data-open-path='C:/results/report.html']").inner_text() == "Open report"
    page.locator(".desktop-save-result").click()
    page.wait_for_timeout(100)
    assert ("save_result", ["C:/results/report.html", "report.html"]) in calls
    page.evaluate("""async () => {
      const url = URL.createObjectURL(new Blob(['a,b\\n1,2'], {type:'text/csv'}));
      await ElectrochemDesktop.saveDownload(url, 'table.csv'); URL.revokeObjectURL(url);
    }""")
    assert any(method == "save_export" and args[1:] == ["table.csv", "text/csv"] for method, args in calls)


@pytest.mark.parametrize("choice", ["stay", "background", "wait", "cancel"])
def test_desktop_close_choices_show_tasks_and_block_new_submissions_at_600px(desktop_browser, choice):
    open_page, native, calls, _source, _project, _conversation = desktop_browser
    page = open_page(width=600)
    closing = {"waiting": False, "active_count": 2, "protected_count": 1, "tasks": [{"kind": "process", "status": "running", "stage": "committing"}, {"kind": "agent", "status": "queued"}]}
    native["closing"] = copy.deepcopy(closing)
    page.evaluate("detail => window.dispatchEvent(new CustomEvent('electrochem:desktop-close', {detail}))", closing)
    assert "Active tasks: 2" in page.locator("#desktop-close-dialog").inner_text()
    assert "Writing results" in page.locator(".desktop-task-list").inner_text()
    assert not page.locator("#desktop-close-dialog").evaluate("node => node.scrollWidth > node.clientWidth + 1")
    page.click(f"#desktop-close-{choice}")
    page.wait_for_function("() => !document.querySelector('#desktop-close-dialog').open")
    assert ("resolve_close", [choice]) in calls
    if choice in ("stay", "background"):
        assert not page.evaluate("ElectrochemDesktop.isLocked()")
        assert page.locator("#proc-run").get_attribute("aria-disabled") is None
        page.evaluate("detail => window.dispatchEvent(new CustomEvent('electrochem:desktop-close', {detail}))", closing)
        page.keyboard.press("Escape")
        page.wait_for_function("() => !document.querySelector('#desktop-close-dialog').open")
        return
    page.wait_for_function("() => ElectrochemDesktop.isLocked()")
    assert page.locator("#desktop-exit-status").is_visible()
    assert page.locator("#proc-run").get_attribute("aria-disabled") == "true"
    submissions = []
    page.on("request", lambda request: submissions.append(request.url) if request.method == "POST" and "/jobs" in request.url else None)
    page.evaluate("() => { runProcess(); sendMessage(); }")
    assert submissions == []
    assert page.locator("#desktop-exit-status button").count() == 0
    if choice == "cancel":
        assert "Cancelling" in page.locator("#desktop-exit-status").inner_text()


def test_desktop_settings_migration_update_text_and_keyboard_menu(desktop_browser):
    open_page, native, calls, _source, _project, _conversation = desktop_browser
    native["tray_available"] = False
    page = open_page(width=600)
    page.focus("#desktop-menu-open")
    page.keyboard.press("Enter")
    assert page.locator("#desktop-menu").get_attribute("open") is not None
    assert page.locator("#desktop-tray").is_disabled()
    native["tray_available"] = True
    page.evaluate("() => window.dispatchEvent(new CustomEvent('electrochem:desktop-state', {detail:{tray_available:true}}))")
    assert page.locator("#desktop-tray").is_enabled()
    page.click("#desktop-settings")
    assert "experiment parameters are not restored" in page.locator("#desktop-settings-dialog").inner_text()
    page.keyboard.press("Escape")
    page.click("#desktop-menu-open")
    page.click("#desktop-migrate")
    page.wait_for_selector(".desktop-candidate")
    assert page.locator(".desktop-candidate").nth(1).locator("button").is_disabled()
    page.locator(".desktop-candidate").first.locator("button").click()
    page.wait_for_function("() => document.querySelector('#desktop-migration-dialog').textContent.includes('Migration scheduled')")
    assert ("migrate_legacy", ["legacy-user"]) in calls
    page.keyboard.press("Escape")
    page.click("#desktop-menu-open")
    page.click("#desktop-updates")
    page.wait_for_selector(".desktop-release-notes")
    assert page.locator(".desktop-release-notes img").count() == 0
    assert "<img" in page.locator(".desktop-release-notes").inner_text()
    assert not page.locator("#desktop-updates-dialog").evaluate("node => node.scrollWidth > node.clientWidth + 1")
    page.keyboard.press("Escape")
    page.select_option("#lang-select", "zh")
    page.click("#desktop-menu-open")
    assert page.locator("#desktop-migrate").inner_text() == "迁移旧数据"
    page.keyboard.press("Escape")
    assert page.locator("#desktop-menu").get_attribute("open") is None


def test_desktop_failed_bridge_does_not_initialize_or_save_defaults_and_browser_stays_unchanged(desktop_browser):
    open_page, _native, calls, _source, _project, _conversation = desktop_browser
    page = open_page(fail_bridge=True)
    assert page.locator("#desktop-retry").is_visible()
    assert page.locator("#desktop-menu-open").count() == 0
    assert not [item for item in calls if item[0] == "save_preferences"]
    browser_page = open_page(native_bridge=False)
    assert browser_page.locator("#desktop-menu-open").count() == 0
    assert browser_page.evaluate("ElectrochemDesktop.isEnabled()") is False
    assert browser_page.locator("#proc-run").is_visible()


def test_desktop_deleted_conversation_and_failed_preference_save_leave_a_usable_workspace(desktop_browser):
    open_page, native, _calls, _source, _project, _conversation = desktop_browser
    native["preferences"]["workspace"]["conversation_id"] = "deleted-conversation"
    page = open_page()
    assert page.evaluate("currentConversationId") is None
    assert page.locator("#proc-folder").input_value() == ""
    page.evaluate("""async () => {
      const save = pywebview.api.save_preferences;
      let writes = 0;
      pywebview.api.save_preferences = async preferences => {
        if (++writes === 1) await new Promise(resolve => setTimeout(resolve, 120));
        return save(preferences);
      };
      ElectrochemTheme.update({fontSize:'standard'});
      const first = ElectrochemDesktop.persist();
      ElectrochemTheme.update({fontSize:'extra-large'});
      await Promise.all([first, ElectrochemDesktop.persist()]);
    }""")
    assert json.loads(native["preferences"]["local_storage"]["electrochem_v6_appearance"])["fontSize"] == "extra-large"
    page.evaluate("""async () => {
      pywebview.api.save_preferences = async () => { throw new Error('Disk full'); };
      ElectrochemTheme.update({density:'comfortable'});
      await ElectrochemDesktop.persist();
    }""")
    assert "Could not save desktop preferences" in page.locator("#desktop-status").inner_text()
    assert page.locator("body").get_attribute("data-density") == "comfortable"
    assert page.locator("#desktop-menu-open").is_visible()


def test_native_caption_uses_distinct_hydrated_palette_without_preference_debounce(desktop_browser):
    open_page, native, calls, _source, _project, _conversation = desktop_browser
    page = open_page(late_bridge=True)
    page.evaluate("() => ElectrochemDesktop.syncWindowAppearance()")
    assert native["window_appearance"] == {"dark": True, "caption_color": "#334C59", "text_color": "#F0F7FB", "high_contrast": False}
    first_caption = next(index for index, item in enumerate(calls) if item[0] == "set_window_appearance")
    assert first_caption > next(index for index, item in enumerate(calls) if item[0] == "get_state")
    assert not any(method == "set_window_appearance" and not args[0]["dark"] for method, args in calls[:first_caption + 1])
    # A stalled persistence backend must not stall a native color change.
    page.evaluate("""() => {
      window.__captionSaves = [];
      pywebview.api.save_preferences = () => new Promise(resolve => window.__captionSaves.push(resolve));
    }""")
    for theme, dark, caption, foreground in [
        ("lab", False, "#C6D6E3", "#243443"),
        ("ocean", True, "#244F63", "#F2FAFF"),
        ("dark", True, "#334C59", "#F0F7FB"),
        ("pixel", False, "#D6C8AE", "#282B33"),
    ]:
        page.evaluate("theme => { ElectrochemTheme.update({theme}); ElectrochemDesktop.persist(); }", theme)
        page.evaluate("() => ElectrochemDesktop.syncWindowAppearance()")
        assert native["window_appearance"] == {"dark": dark, "caption_color": caption, "text_color": foreground, "high_contrast": False}
        frame = page.evaluate("""() => {
          const style = getComputedStyle(document.body), divider = getComputedStyle(document.documentElement, '::after');
          return {header:style.getPropertyValue('--app-chrome').trim().toUpperCase(),
            titlebar:style.getPropertyValue('--titlebar-bg').trim().toUpperCase(),
            dividerHeight:divider.height, dividerPosition:divider.position, dividerEvents:divider.pointerEvents};
        }""")
        assert caption == frame["titlebar"] and caption != frame["header"]
        assert (frame["dividerHeight"], frame["dividerPosition"], frame["dividerEvents"]) == ("2px", "fixed", "none")
    assert page.evaluate("window.__captionSaves.length") > 0
    assert page.locator("body").get_attribute("data-theme") == "pixel"


def test_native_caption_follows_system_only_in_system_mode_and_defers_to_high_contrast(desktop_browser):
    open_page, native, calls, _source, _project, _conversation = desktop_browser
    prefs = json.loads(native["preferences"]["local_storage"]["electrochem_v6_appearance"])
    prefs.pop("theme", None)
    prefs.update(version=2, style="modern", paletteByStyle={"modern": {"id": "system"}, "pixel": {"id": "cream"}})
    native["preferences"]["local_storage"]["electrochem_v6_appearance"] = json.dumps(prefs)
    page = open_page(color_scheme="light")
    page.evaluate("() => ElectrochemDesktop.syncWindowAppearance()")
    assert native["window_appearance"]["caption_color"] == "#C6D6E3"
    page.emulate_media(color_scheme="dark")
    page.wait_for_function("() => document.body.dataset.theme === 'dark'")
    page.evaluate("() => ElectrochemDesktop.syncWindowAppearance()")
    assert native["window_appearance"]["caption_color"] == "#334C59"
    page.evaluate("() => { ElectrochemTheme.update({theme:'ocean'}); return ElectrochemDesktop.syncWindowAppearance(); }")
    count = sum(method == "set_window_appearance" for method, _args in calls)
    page.emulate_media(color_scheme="light")
    page.evaluate("() => ElectrochemDesktop.syncWindowAppearance()")
    assert native["window_appearance"]["caption_color"] == "#244F63"
    assert sum(method == "set_window_appearance" for method, _args in calls) == count
    page.emulate_media(forced_colors="active")
    page.wait_for_function("() => matchMedia('(forced-colors: active)').matches")
    page.evaluate("() => ElectrochemDesktop.syncWindowAppearance()")
    forced = native["window_appearance"]
    assert forced["high_contrast"] is True
    assert forced["caption_color"] != "#244F63"
    assert forced["caption_color"] != forced["text_color"]
    page.emulate_media(forced_colors="none")
    page.evaluate("() => ElectrochemDesktop.syncWindowAppearance()")
    assert native["window_appearance"] == {"dark": True, "caption_color": "#244F63", "text_color": "#F2FAFF", "high_contrast": False}


def test_native_caption_serializes_quick_changes_and_recovers_after_bridge_error(desktop_browser):
    open_page, native, _calls, _source, _project, _conversation = desktop_browser
    page = open_page()
    page.evaluate("() => ElectrochemDesktop.syncWindowAppearance()")
    page.evaluate("""() => {
      const original = pywebview.api.set_window_appearance;
      window.__captionPending = [];
      window.__captionCalls = [];
      pywebview.api.set_window_appearance = payload => {
        window.__captionCalls.push(payload);
        return new Promise((resolve, reject) => window.__captionPending.push({payload, resolve:async () => resolve(await original(payload)), reject}));
      };
      ElectrochemTheme.update({theme:'lab'});
      ElectrochemTheme.update({theme:'pixel'});
      ElectrochemTheme.update({theme:'ocean'});
    }""")
    assert page.evaluate("window.__captionCalls.length") == 1
    assert page.evaluate("window.__captionCalls[0].caption_color") == "#C6D6E3"
    page.evaluate("() => window.__captionPending.shift().resolve()")
    page.wait_for_function("() => window.__captionCalls.length === 2")
    assert page.evaluate("window.__captionCalls[1].caption_color") == "#244F63"
    page.evaluate("() => window.__captionPending.shift().resolve()")
    page.evaluate("() => ElectrochemDesktop.syncWindowAppearance()")
    assert native["window_appearance"]["caption_color"] == "#244F63"
    page.evaluate("""() => {
      ElectrochemTheme.update({theme:'dark'});
      window.__captionPending.shift().reject(new Error('Window not ready'));
    }""")
    page.wait_for_function("() => window.__captionPending.length === 0")
    page.evaluate("() => { ElectrochemTheme.update({theme:'pixel'}); }")
    page.wait_for_function("() => window.__captionPending.length === 1")
    page.evaluate("() => window.__captionPending.shift().resolve()")
    page.evaluate("() => ElectrochemDesktop.syncWindowAppearance()")
    assert native["window_appearance"] == {"dark": False, "caption_color": "#D6C8AE", "text_color": "#282B33", "high_contrast": False}
    page.evaluate("delete pywebview.api.set_window_appearance")
    page.evaluate("() => { ElectrochemTheme.update({theme:'lab'}); return ElectrochemDesktop.syncWindowAppearance(); }")
    assert page.locator("#desktop-menu-open").is_visible()
    assert page.locator("body").get_attribute("data-theme") == "lab"


def test_environment_check_is_on_demand_localized_and_copies_exact_report(desktop_browser):
    open_page, native, calls, _source, _project, _conversation = desktop_browser
    page = open_page()
    assert not [method for method, _args in calls if method == "get_environment_report"]
    assert page.locator("#desktop-diagnostics-dialog").count() == 0
    page.focus("#desktop-menu-open")
    page.keyboard.press("Enter")
    page.focus("#desktop-diagnostics")
    page.keyboard.press("Enter")
    page.wait_for_selector(".desktop-diagnostics-check")
    dialog = page.locator("#desktop-diagnostics-dialog")
    assert "Environment check complete" in dialog.inner_text()
    assert "Operating system" in dialog.inner_text()
    assert "Use the complete offline installer" in dialog.inner_text()
    assert page.locator(".desktop-diagnostics-check[data-check-status='warn'] .desktop-diagnostics-badge").inner_text() == "Note"
    page.evaluate("""() => Object.defineProperty(navigator, 'clipboard', {configurable:true, value:{
      writeText:async value => { window.__diagnosticClipboard = value; }
    }})""")
    page.click("#desktop-diagnostics-copy")
    page.wait_for_function("() => document.querySelector('#desktop-diagnostics-feedback').textContent.includes('copied')")
    assert page.evaluate("window.__diagnosticClipboard") == native["environment_report"]["report_text"]
    assert not page.locator(".desktop-diagnostics-text").get_attribute("open")
    page.keyboard.press("Escape")
    assert not dialog.is_visible()
    page.select_option("#lang-select", "zh")
    page.click("#desktop-menu-open")
    assert page.locator("#desktop-diagnostics").inner_text() == "环境自检"
    page.click("#desktop-diagnostics")
    page.wait_for_selector(".desktop-diagnostics-check")
    assert "环境检查完成" in dialog.inner_text()
    assert "操作系统" in dialog.inner_text()
    assert "处理方法: 请使用离线完整安装包。" in dialog.inner_text()
    assert sum(method == "get_environment_report" for method, _args in calls) == 2
    assert not [method for method, _args in calls if method in {"open_external", "save_export", "save_result"}]


def test_environment_check_failure_retry_and_manual_copy_fallback_preserve_literal_text(desktop_browser):
    open_page, native, _calls, _source, _project, _conversation = desktop_browser
    good_report = copy.deepcopy(native["environment_report"])
    native["environment_report"] = {"status": "error", "message": "Diagnostics unavailable"}
    page = open_page()
    page.click("#desktop-menu-open")
    page.click("#desktop-diagnostics")
    page.wait_for_selector(".desktop-diagnostics-error")
    assert "Diagnostics unavailable" in page.locator(".desktop-diagnostics-error").inner_text()
    assert page.locator("#desktop-diagnostics-copy").is_disabled()
    assert page.locator("#desktop-diagnostics-refresh").is_enabled()
    # A malformed bridge response must not appear to be a successful check.
    native["environment_report"] = {"status": "success", "report": {"checks": [None]}, "report_text": "incomplete"}
    page.click("#desktop-diagnostics-refresh")
    page.wait_for_function("() => document.querySelector('.desktop-diagnostics-error').textContent.includes('incomplete')")
    assert page.locator("#desktop-diagnostics-copy").is_disabled()
    good_report["report"]["checks"][0].update(status="fail", detail_en="<img src=x onerror=alert('unsafe')>")
    native["environment_report"] = good_report
    page.click("#desktop-diagnostics-refresh")
    page.wait_for_selector(".desktop-diagnostics-check")
    assert page.locator("#desktop-diagnostics-dialog img").count() == 0
    assert "<img" in page.locator(".desktop-diagnostics-check").first.inner_text()
    assert "Action needed" in page.locator(".desktop-diagnostics-check").first.inner_text()
    page.evaluate("""() => Object.defineProperty(navigator, 'clipboard', {configurable:true, value:{
      writeText:async () => { throw new Error('Permission denied'); }
    }})""")
    page.click("#desktop-diagnostics-copy")
    page.wait_for_function("() => document.querySelector('.desktop-diagnostics-text').open")
    assert "Automatic copying failed" in page.locator("#desktop-diagnostics-feedback").inner_text()
    assert page.locator("#desktop-diagnostics-raw").input_value() == good_report["report_text"]
    assert page.locator("#desktop-diagnostics-raw").evaluate("node => node.readOnly && node.selectionStart === 0 && node.selectionEnd === node.value.length")
    assert page.locator("#desktop-diagnostics-copy").is_enabled()


def test_environment_check_ignores_closed_dialog_response(desktop_browser):
    open_page, native, _calls, _source, _project, _conversation = desktop_browser
    page = open_page()
    page.evaluate("""() => {
      window.__diagnosticNative = pywebview.api.get_environment_report;
      pywebview.api.get_environment_report = () => new Promise(resolve => window.__diagnosticPending = resolve);
    }""")
    page.click("#desktop-menu-open")
    page.click("#desktop-diagnostics")
    assert page.locator("#desktop-diagnostics-refresh").is_disabled()
    page.keyboard.press("Escape")
    page.evaluate("pywebview.api.get_environment_report = window.__diagnosticNative")
    page.click("#desktop-menu-open")
    page.click("#desktop-diagnostics")
    page.wait_for_selector(".desktop-diagnostics-check")
    stale = copy.deepcopy(native["environment_report"])
    stale["report"]["summary_en"] = "Stale report that must be ignored"
    page.evaluate("report => window.__diagnosticPending(report)", stale)
    assert "Stale report" not in page.locator("#desktop-diagnostics-dialog").inner_text()
    assert page.locator("#desktop-diagnostics-copy").is_enabled()


@pytest.mark.parametrize("style", ["modern", "paper", "soft", "pixel"])
def test_environment_check_uses_theme_and_fits_narrow_window(desktop_browser, style):
    open_page, _native, _calls, _source, _project, _conversation = desktop_browser
    page = open_page(width=360)
    page.evaluate("style => ElectrochemTheme.update({style, fontSize:'extra-large'})", style)
    page.click("#desktop-menu-open")
    page.click("#desktop-diagnostics")
    page.wait_for_selector(".desktop-diagnostics-check")
    page.locator(".desktop-diagnostics-text summary").click()
    layout = page.locator("#desktop-diagnostics-dialog").evaluate("""node => {
      const style = getComputedStyle(node), probe = document.createElement('span');
      probe.style.cssText = 'color:var(--ink);background-color:var(--panel-solid)'; node.append(probe);
      const expected = getComputedStyle(probe), rect = node.getBoundingClientRect();
      const result = {overflow:node.scrollWidth > node.clientWidth + 1, left:rect.left, right:rect.right,
        matchesTheme:style.color === expected.color && style.backgroundColor === expected.backgroundColor};
      probe.remove(); return result;
    }""")
    assert not layout["overflow"]
    assert 0 <= layout["left"] < layout["right"] <= 360
    assert layout["matchesTheme"]
    if style == "pixel":
        assert page.locator(".desktop-diagnostics-check").first.evaluate("node => getComputedStyle(node).borderRadius") == "0px"
    page.keyboard.press("Escape")
    assert not page.locator("#desktop-diagnostics-dialog").is_visible()
