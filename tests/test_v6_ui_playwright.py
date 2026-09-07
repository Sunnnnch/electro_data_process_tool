import os
import socket
import time
from threading import Event

import pytest

import electrochem_v6.server.routes_post as routes_post
from electrochem_v6.server import V6ServerManager
from electrochem_v6.store.conversations import append_message, get_conversation
from electrochem_v6.store.runtime import reset_runtime


def _playwright_is_required() -> bool:
    return str(os.environ.get("ELECTROCHEM_REQUIRE_PLAYWRIGHT") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _sync_playwright_factory():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        if _playwright_is_required():
            pytest.fail(f"playwright is required but unavailable: {exc}")
        pytest.skip(f"could not import playwright.sync_api: {exc}")
    return sync_playwright


def _launch_chromium(playwright):
    try:
        return playwright.chromium.launch(headless=True)
    except Exception as exc:
        if _playwright_is_required():
            pytest.fail(f"playwright browser is required but unavailable: {exc}")
        pytest.skip(f"playwright browser not available: {exc}")


def _get_free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


class _DummyAgentService:
    def chat(
        self,
        *,
        message,
        conversation_id=None,
        provider=None,
        model=None,
        project_name=None,
        data_type=None,
        processing_result=None,
        attachments=None,
        prompt_prefix=None,
        professional_context=None,
        approval_id=None,
        approval_action=None,
        progress_callback=None,
        cancel_check=None,
    ):
        self.last_prompt_prefix = prompt_prefix
        self.last_professional_context = professional_context
        self.last_approval_id = approval_id
        self.last_approval_action = approval_action
        if progress_callback:
            progress_callback("generating test response")
        if approval_id and approval_action == "approve":
            time.sleep(0.35)
        cid = conversation_id or f"ui_conv_{_get_free_port()}"
        meta = {
            "provider": provider or "mock",
            "model": model or "mock-model",
            "project_name": project_name,
            "data_type": data_type,
        }
        cid = append_message(cid, "user", message, metadata=meta)
        md_reply = "## 测试结果\n- **关键点**\n- `code_snippet`"
        reply_meta = dict(meta)
        if approval_id:
            reply_meta["resolved_approval_ids"] = [approval_id]
            md_reply = "已取消该操作" if approval_action == "decline" else "已执行确认操作"
        elif "触发确认测试" in str(message or ""):
            approval_index = int(getattr(self, "approval_index", 0)) + 1
            self.approval_index = approval_index
            self.last_pending_approval_id = f"ui-approval-test-{approval_index}"
            reply_meta["pending_approvals"] = [
                {
                    "approval_id": self.last_pending_approval_id,
                    "tool_name": "create_project",
                    "summary": "创建项目“界面确认测试”",
                    "details": {"project_name": "界面确认测试", "description": ""},
                }
            ]
        append_message(cid, "agent", md_reply, metadata=reply_meta)
        conv = get_conversation(cid)
        return {
            "status": "success",
            "conversation_id": cid,
            "provider": meta["provider"],
            "model": meta["model"],
            "agent_reply": md_reply,
            "processing_result": processing_result,
            "attachments": attachments or [],
            "messages": conv.get("messages", []) if conv else [],
            "conversation": conv,
        }

    def delete_session(self, conversation_id):
        return None


def test_v6_ui_chat_rename_and_ai_settings(monkeypatch, tmp_path):
    sync_playwright = _sync_playwright_factory()

    mapping = {
        "ELECTROCHEM_V6_PROJECTS_FILE": str(tmp_path / "projects.json"),
        "ELECTROCHEM_V6_HISTORY_FILE": str(tmp_path / "processing_history.json"),
        "ELECTROCHEM_V6_CONVERSATION_FILE": str(tmp_path / "conversation_history.json"),
        "ELECTROCHEM_V6_TEMPLATE_FILE": str(tmp_path / "process_templates.json"),
        "ELECTROCHEM_V6_QUALITY_REPORT_FILE": str(tmp_path / "latest_quality_report.json"),
    }
    for key, value in mapping.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        routes_post,
        "check_provider_connection",
        lambda payload: {"status": "success", "provider": payload.get("provider"), "model": payload.get("model")},
    )

    port = _get_free_port()
    manager = V6ServerManager(port=port)
    agent_service = _DummyAgentService()
    manager._agent_service = agent_service
    ok, _msg = manager.start()
    assert ok

    try:
        with sync_playwright() as p:
            browser = _launch_chromium(p)

            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/ui", wait_until="networkidle")

            assert page.locator("#tab-btn-ai").count() == 0
            page.click("#assistant-fab")
            page.wait_for_selector("#assistant-drawer:not(.hidden)", timeout=10000)
            assert page.locator("#project-name").count() == 0
            assert page.locator("#data-type").count() == 0
            assert page.locator("#zip-file").count() == 0
            assert "AI 自动选择上下文" in page.locator(".assistant-context-card").inner_text()
            assert "未选择文件" in page.locator("#assistant-context-summary").inner_text()
            page.click("#assistant-suggest-btn")
            assert "当前专业模式" in page.locator("#msg-input").input_value()
            page.click("#assistant-database-suggest")
            assert "数据库" in page.locator("#msg-input").input_value()
            page.fill("#msg-input", "请输出 markdown 测试")
            page.click("#send-btn")

            page.wait_for_selector(".msg.agent .content strong", timeout=10000)
            page.wait_for_selector(".msg.agent .content code", timeout=10000)
            assert agent_service.last_professional_context["context_type"] == "professional_mode_summary"
            assert agent_service.last_professional_context["data_source"]["raw_file_content_included"] is False
            assert "professional_mode_summary" not in (agent_service.last_prompt_prefix or "")

            page.fill("#msg-input", "触发确认测试")
            page.click("#send-btn")
            page.wait_for_selector(".msg-approval .assistant-approval-btn.decline", timeout=10000)
            assert "写入阶段不可取消" in page.locator(".msg-approval").inner_text()
            assert "项目名称" in page.locator(".msg-approval").inner_text()
            page.click(".msg-approval .assistant-approval-btn.decline")
            page.wait_for_function(
                "() => !document.querySelector('.msg-approval')",
                timeout=10000,
            )
            assert agent_service.last_approval_id == "ui-approval-test-1"
            assert agent_service.last_approval_action == "decline"

            page.fill("#msg-input", "触发确认测试")
            page.click("#send-btn")
            page.wait_for_selector(".msg-approval .assistant-approval-btn.approve", timeout=10000)
            page.click(".msg-approval .assistant-approval-btn.approve")
            page.wait_for_function(
                "() => { const button = document.querySelector('#send-btn'); return button && button.disabled && button.textContent.includes('不可取消'); }",
                timeout=10000,
            )
            page.wait_for_function(
                "() => { const button = document.querySelector('#send-btn'); return button && !button.disabled && button.textContent.includes('发送'); }",
                timeout=10000,
            )
            assert agent_service.last_approval_id == "ui-approval-test-2"
            assert agent_service.last_approval_action == "approve"

            page.click("#assistant-history-toggle")
            page.wait_for_selector("#assistant-conversation-panel:not(.hidden)", timeout=10000)
            page.wait_for_selector(".conv-rename", timeout=10000)
            page.click(".conv-rename")
            page.fill(".conv-title-input", "重命名E2E")
            page.click(".conv-save")
            page.wait_for_function(
                "() => { const el = document.querySelector('.conv-item .title'); return !!el && el.textContent.includes('重命名E2E'); }",
                timeout=10000,
            )

            page.click("#ai-settings-open")
            page.wait_for_selector("#ai-settings-panel:not(.hidden)", timeout=10000)
            page.fill("#prompt-prefix", "这是E2E测试提示词")
            page.click("#prompt-save")
            page.wait_for_function(
                "() => { const el = document.querySelector('#llm-status'); return !!el && el.textContent.includes('提示词设置已保存'); }",
                timeout=10000,
            )
            page.click("#llm-test")
            page.wait_for_function(
                "() => { const el = document.querySelector('#llm-status'); return !!el && el.textContent.includes('模型连接可用'); }",
                timeout=10000,
            )
            page.click("#ai-settings-close")

            page.fill("#msg-input", "第一行")
            page.press("#msg-input", "Shift+Enter")
            page.keyboard.type("第二行")
            assert page.locator("#msg-input").input_value() == "第一行\n第二行"
            page.press("#msg-input", "Enter")
            page.wait_for_function(
                """
                () => {
                  const users = Array.from(document.querySelectorAll('.msg.user .content')).map((el) => el.textContent || '');
                  return users.some((text) => text.includes('第一行') && text.includes('第二行') && !text.includes('这是E2E测试提示词'));
                }
                """,
                timeout=10000,
            )
            browser.close()
    finally:
        manager.stop()


def test_v6_ui_process_type_cards_use_schema(monkeypatch, tmp_path):
    sync_playwright = _sync_playwright_factory()

    source_dir = tmp_path / "source_picker"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "LSV_sample.txt").write_text("Potential Current\n0 0\n1 0.1\n", encoding="utf-8")
    (source_dir / "notes.csv").write_text("note,value\na,1\n", encoding="utf-8")
    monkeypatch.setattr(
        routes_post,
        "select_folder_dialog",
        lambda initial_dir=None: {"status": "success", "folder_path": str(source_dir)},
    )

    mapping = {
        "ELECTROCHEM_V6_PROJECTS_FILE": str(tmp_path / "projects.json"),
        "ELECTROCHEM_V6_HISTORY_FILE": str(tmp_path / "processing_history.json"),
        "ELECTROCHEM_V6_CONVERSATION_FILE": str(tmp_path / "conversation_history.json"),
        "ELECTROCHEM_V6_TEMPLATE_FILE": str(tmp_path / "process_templates.json"),
        "ELECTROCHEM_V6_QUALITY_REPORT_FILE": str(tmp_path / "latest_quality_report.json"),
    }
    for key, value in mapping.items():
        monkeypatch.setenv(key, value)

    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _msg = manager.start()
    assert ok

    try:
        with sync_playwright() as p:
            browser = _launch_chromium(p)

            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/ui", wait_until="networkidle")
            page.wait_for_function(
                """
                () => {
                  const schema = window.ElectrochemProcessingSchema && window.ElectrochemProcessingSchema.getCached();
                  return !!schema && document.querySelectorAll('#process-type-checks .proc-type-check').length === 5;
                }
                """,
                timeout=10000,
            )

            assert page.locator('label[for="proc-folder"]').is_visible()
            assert page.locator("#proc-data-pick").is_visible()
            page.click("#proc-data-pick")
            assert page.locator("#proc-pick-files").is_visible()
            assert page.locator("#proc-pick-folder").is_visible()
            page.click("#proc-data-pick")
            assert page.locator('label[for="proc-project"]').is_visible()
            assert page.locator("#project-archive-hint").is_visible()
            assert page.locator("#pro-output-run-dir").is_checked()
            assert page.locator('label:has(#pro-recursive-scan)').get_attribute("title")
            assert page.locator('label:has(#pro-output-run-dir)').get_attribute("title")
            assert page.locator("#proc-sticky-preflight").count() == 0
            assert page.locator("#proc-sticky-run").count() == 0
            assert page.locator("#proc-sticky-diagnostics").count() == 0
            assert page.locator("#proc-preflight-btn").count() == 1
            assert page.locator("#proc-run").count() == 1
            assert page.locator("#proc-diagnostics").count() == 1

            initial_step_classes = {
                key: page.locator(f'.process-step[data-step-key="{key}"]').get_attribute("class")
                for key in ("source", "template", "type", "basic", "modules")
            }
            assert "issue" in initial_step_classes["source"]
            assert "optional" in initial_step_classes["template"]
            assert "pending" in initial_step_classes["type"]
            assert "pending" in initial_step_classes["basic"]
            assert "pending" in initial_step_classes["modules"]

            titles = page.locator("#process-type-checks .mode-card-title").evaluate_all(
                "(items) => items.map((item) => item.textContent.trim())"
            )
            assert titles == ["LSV", "CV", "EIS", "ECSA", "COUPLED/FE"]

            checked = page.locator("#process-type-checks .proc-type-check:checked").evaluate_all(
                "(items) => items.map((item) => item.value)"
            )
            assert checked == ["LSV"]

            page.click("#proc-data-pick")
            page.click("#proc-pick-folder")
            page.wait_for_function(
                "() => document.querySelectorAll('#proc-source-list .source-file-item').length === 2",
                timeout=10000,
            )
            assert page.locator("#proc-folder").input_value() == str(source_dir)
            source_types = page.locator("#proc-source-list .source-file-type").evaluate_all(
                "(items) => items.map((item) => item.value)"
            )
            assert source_types == ["LSV", ""]
            assert "已加入 2 个文件" in page.locator("#proc-source-summary").text_content()
            assert "complete" in page.locator('.process-step[data-step-key="source"]').get_attribute("class")
            assert "complete" in page.locator('.process-step[data-step-key="type"]').get_attribute("class")
            assert "complete" in page.locator('.process-step[data-step-key="basic"]').get_attribute("class")
            assert "complete" in page.locator('.process-step[data-step-key="modules"]').get_attribute("class")
            assert "optional" in page.locator('.process-step[data-step-key="template"]').get_attribute("class")

            page.locator("#process-step-template").evaluate("(el) => { el.open = true; }")
            page.click("#tmpl-load")
            assert "complete" in page.locator('.process-step[data-step-key="template"]').get_attribute("class")

            page.check('#process-type-checks .proc-type-check[value="CV"]')
            page.wait_for_selector('.dtype-panel[data-dtype="CV"]:not(.hidden)', timeout=10000)
            checked = page.locator("#process-type-checks .proc-type-check:checked").evaluate_all(
                "(items) => items.map((item) => item.value)"
            )
            assert checked == ["LSV", "CV"]

            page.locator("#process-step-modules").scroll_into_view_if_needed()
            page.wait_for_function(
                "() => document.querySelector('.process-step.active')?.dataset.stepKey === 'modules'",
                timeout=10000,
            )

            page.check("#pro-lsv-advanced-mode")
            page.check("#pro-lsv-ir-enabled")
            page.wait_for_selector("#ir-eis-options:not(.hidden)", timeout=10000)

            page.select_option("#pro-lsv-ir-source", "manual")
            page.wait_for_selector("#ir-manual-options:not(.hidden)", timeout=10000)
            assert page.locator("#ir-eis-options").evaluate("(el) => el.classList.contains('hidden')") is True

            page.select_option("#pro-lsv-ir-source", "eis")
            page.select_option("#pro-lsv-ir-scope", "specified_file")
            page.wait_for_selector("#ir-specified-file-options:not(.hidden)", timeout=10000)
            assert page.locator("#ir-eis-options").evaluate(
                "(el) => el.scrollWidth <= el.clientWidth + 1"
            ) is True

            page.check('#process-type-checks .proc-type-check[value="COUPLED"]')
            page.wait_for_selector('.dtype-panel[data-dtype="COUPLED"]:not(.hidden)', timeout=10000)
            page.select_option("#pro-coupled-input-mode", "peak_analysis")
            page.wait_for_selector("#coupled-peak-source-options:not(.hidden)", timeout=10000)
            page.wait_for_selector("#coupled-peak-calc-options:not(.hidden)", timeout=10000)
            assert page.locator("#coupled-product-table-options").evaluate(
                "(el) => el.classList.contains('hidden')"
            ) is True
            assert page.locator("#pro-fe-peak-auto-locate").is_checked()
            assert page.locator("#pro-fe-peak-reference-align").is_checked()
            assert page.locator('.dtype-panel[data-dtype="COUPLED"]').evaluate(
                "(el) => el.scrollWidth <= el.clientWidth + 1"
            ) is True

            page.select_option("#pro-coupled-input-mode", "product_table")
            page.wait_for_selector("#coupled-product-table-options:not(.hidden)", timeout=10000)
            assert page.locator("#coupled-peak-source-options").evaluate(
                "(el) => el.classList.contains('hidden')"
            ) is True

            page.click('.process-step[data-step-key="preflight"]')
            page.wait_for_function(
                "() => document.querySelector('.process-step.active')?.dataset.stepKey === 'preflight'",
                timeout=10000,
            )
            browser.close()
    finally:
        manager.stop()


def test_v6_ui_async_navigation_and_submission_buttons(monkeypatch, tmp_path):
    sync_playwright = _sync_playwright_factory()
    for key, filename in {
        "ELECTROCHEM_V6_PROJECTS_FILE": "projects.json",
        "ELECTROCHEM_V6_HISTORY_FILE": "processing_history.json",
        "ELECTROCHEM_V6_CONVERSATION_FILE": "conversation_history.json",
        "ELECTROCHEM_V6_TEMPLATE_FILE": "process_templates.json",
        "ELECTROCHEM_V6_QUALITY_REPORT_FILE": "latest_quality_report.json",
    }.items():
        monkeypatch.setenv(key, str(tmp_path / filename))
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "LSV_sample.txt").write_text("Potential Current\n0 0\n1 0.1\n", encoding="utf-8")
    monkeypatch.setattr(
        routes_post,
        "select_folder_dialog",
        lambda initial_dir=None: {"status": "success", "folder_path": str(source_dir)},
    )
    port = _get_free_port()
    manager = V6ServerManager(port=port)
    ok, _msg = manager.start()
    assert ok

    try:
        with sync_playwright() as playwright:
            browser = _launch_chromium(playwright)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/ui", wait_until="networkidle")
            page.evaluate("""async () => {
              const state = window.asyncUiTest = { holdA: false, submissions: 0, preflights: 0 };
              const response = data => ({ ok: true, json: async () => data });
              const detail = id => response({ status: 'success', conversation: {
                conversation_id: id, title: id, messages: [{ role: 'user', content: id + ' history' }],
              } });
              assistantApi.getConversation = id => state.holdA && id === 'A'
                ? new Promise(resolve => { state.resolveA = () => resolve(detail(id)); })
                : Promise.resolve(detail(id));
              assistantApi.listConversations = async options => response({ status: 'success', items:
                (options.keyword ? ['A'] : ['A', 'B']).map(id => ({ conversation_id: id, title: id })),
              });
              assistantApi.submitMessageJob = async payload => {
                state.sentTo = payload.conversation_id;
                return response({ status: 'success', job_id: 'held-job' });
              };
              assistantApi.getMessageJob = () => new Promise(resolve => {
                state.resolveJob = () => resolve(response({ status: 'success', job: {
                  status: 'succeeded', result: { status: 'success', conversation_id: 'B' },
                } }));
              });
              await loadConversations();
              await openConversation('A', true);
              state.holdA = true;
              processingApi.preflight = () => new Promise(resolve => {
                state.preflights += 1;
                state.resolvePreflight = () => resolve(response({ status: 'success', preflight: { selected_matched: 1 } }));
              });
              processingApi.submitProcessJob = async () => {
                state.submissions += 1;
                return response({ status: 'success', job_id: 'one-process-job', job: {
                  status: 'succeeded', result: { status: 'success', result: { summary: 'UI regression result' } },
                } });
              };
            }""")
            page.click("#assistant-fab")
            page.click("#assistant-history-toggle")
            page.click('.conv-item[data-id="A"] .title')
            page.wait_for_function("() => !!window.asyncUiTest.resolveA")
            page.click('.conv-item[data-id="B"] .title')
            page.wait_for_function("() => document.querySelector('#conv-title').textContent === 'B'")
            page.evaluate("async () => { asyncUiTest.resolveA(); await new Promise(requestAnimationFrame); }")
            assert page.evaluate("currentConversationId") == "B"
            assert page.locator("#conv-title").text_content() == "B"
            assert "B history" in page.locator("#chat-log").inner_text()

            page.fill("#conv-search", "A")
            page.click("#conv-search-btn")
            page.wait_for_function("() => document.querySelectorAll('.conv-item').length === 1")
            assert page.evaluate("currentConversationId") == "B"
            assert page.locator("#conv-title").text_content() == "B"
            page.fill("#msg-input", "Message for B")
            page.click("#send-btn")
            page.wait_for_function("() => !!window.asyncUiTest.resolveJob")
            assert page.evaluate("asyncUiTest.sentTo") == "B"
            page.click("#conv-new")
            page.fill("#msg-input", "Draft for new conversation")
            page.evaluate("asyncUiTest.resolveJob()")
            page.wait_for_function("() => activeAgentRequest === null")
            assert page.evaluate("currentConversationId") is None
            assert page.locator("#chat-log .msg").count() == 0
            assert page.locator("#msg-input").input_value() == "Draft for new conversation"

            page.click("#assistant-close")
            page.click("#proc-data-pick")
            page.click("#proc-pick-folder")
            page.wait_for_function("() => document.querySelectorAll('#proc-source-list .source-file-item').length === 1")
            page.click("#proc-run")
            page.wait_for_function("() => !!window.asyncUiTest.resolvePreflight")
            assert page.locator("#proc-run").is_disabled()
            page.evaluate("runProcess()")
            assert page.evaluate("asyncUiTest.preflights") == 1
            page.evaluate("asyncUiTest.resolvePreflight()")
            page.wait_for_function("() => !document.querySelector('#proc-run').disabled")
            assert page.evaluate("asyncUiTest.submissions") == 1
            browser.close()
    finally:
        manager.stop()


def test_v6_project_create_dialog_persists_settings_and_preserves_failed_draft(monkeypatch, tmp_path):
    sync_playwright = _sync_playwright_factory()
    monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "history.json"))
    reset_runtime()
    submitted = Event()
    release_submit = Event()
    real_create_project = routes_post.create_project
    created_names = []

    def create_with_pending_gate(**payload):
        created_names.append(payload["name"])
        if payload["name"] == "新建复核项目":
            submitted.set()
            if not release_submit.wait(timeout=15):
                return {"status": "error", "message": "test submission timed out"}
        return real_create_project(**payload)

    monkeypatch.setattr(routes_post, "create_project", create_with_pending_gate)
    manager = V6ServerManager(port=_get_free_port())
    ok, _message = manager.start()
    assert ok
    try:
        with sync_playwright() as playwright:
            browser = _launch_chromium(playwright)
            page = browser.new_page(viewport={"width": 1280, "height": 950})
            errors = []
            console_errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: console_errors.append((message.text, message.location.get("url", "")))
                if message.type == "error" else None,
            )
            base_url = f"http://127.0.0.1:{manager.port}"
            existing = page.request.post(f"{base_url}/api/v1/projects", data={"name": "既有项目"})
            assert existing.ok
            archived = page.request.post(f"{base_url}/api/v1/projects", data={"name": "已归档批次"})
            assert archived.ok
            archived_id = archived.json()["project_id"]
            assert page.request.post(f"{base_url}/api/v1/projects/{archived_id}/delete", data={}).ok
            page.goto(f"{base_url}/ui", wait_until="networkidle")
            page.click("#tab-btn-project")
            page.wait_for_selector("#project-list .project-item")
            page.click("#project-create-btn")
            dialog = page.locator("#project-create-dialog")
            assert dialog.is_visible()
            assert page.locator("#project-create-name").get_attribute("maxlength") == "128"
            assert page.locator("#project-create-desc").get_attribute("maxlength") == "1024"
            assert not page.locator("#project-create-more").evaluate("el => el.open")
            page.click("#project-create-submit")
            assert dialog.is_visible()
            assert created_names == ["既有项目", "已归档批次"]
            page.fill("#project-create-name", "取消的草稿")
            page.fill("#project-create-desc", "这段说明不应保存")
            page.click("#project-create-cancel")
            assert dialog.is_hidden()
            assert created_names == ["既有项目", "已归档批次"]

            page.check("#project-show-recycle")
            page.wait_for_selector(f'#project-list [data-project-id="{archived_id}"]')
            page.fill("#project-list-search", "已归档")
            page.click("#project-create-btn")
            page.fill("#project-create-name", "既有项目")
            description = "用于复核的项目\n第二批实验记录"
            page.fill("#project-create-desc", description)
            page.click("#project-create-more > summary")
            page.fill("#project-create-tags", "LSV， HER, 批次二")
            page.fill("#project-create-color-custom", "#2468ac")
            with page.expect_response(
                lambda response: response.url == f"{base_url}/api/v1/projects"
                and response.request.method == "POST"
            ) as rejected:
                page.click("#project-create-submit")
            assert rejected.value.status == 400
            page.wait_for_function(
                "() => document.querySelector('#project-create-error').textContent.includes('已存在')"
            )
            assert dialog.is_visible()
            assert page.locator("#project-create-name").input_value() == "既有项目"
            assert page.locator("#project-create-desc").input_value() == description
            assert page.locator("#project-create-tags").input_value() == "LSV， HER, 批次二"
            assert page.locator("#project-create-color").input_value() == "#2468ac"
            assert page.locator("#project-create-submit").is_enabled()

            page.fill("#project-create-name", "新建复核项目")
            page.click("#project-create-submit")
            assert submitted.wait(timeout=5)
            for element_id in (
                "project-create-name", "project-create-desc", "project-create-tags",
                "project-create-color", "project-create-submit", "project-create-cancel",
                "project-create-close",
            ):
                assert page.locator(f"#{element_id}").is_disabled()
            page.keyboard.press("Escape")
            assert dialog.is_visible()
            release_submit.set()
            page.wait_for_function("() => !document.querySelector('#project-create-dialog').open")
            page.wait_for_function(
                "() => document.querySelector('#project-detail-title').textContent === '新建复核项目'"
            )
            assert not page.locator("#project-show-recycle").is_checked()
            assert page.locator("#project-list-search").input_value() == ""
            stored_response = page.request.get(f"{base_url}/api/v1/projects?status=all")
            assert stored_response.ok
            stored = stored_response.json()["projects"]
            assert len(stored) == 3
            created = next(project for project in stored if project["name"] == "新建复核项目")
            assert created["description"] == description
            assert created["tags"] == ["LSV", "HER", "批次二"]
            assert created["color"] == "#2468ac"
            assert created["status"] == "active"
            assert page.locator(f'#project-list [data-project-id="{created["id"]}"]').is_visible()
            assert created_names == ["既有项目", "已归档批次", "既有项目", "新建复核项目"]
            assert errors == []
            # Existing optional font CSP failures and absent comparison plots are
            # unrelated to creation; every other console error remains a failure.
            assert [
                (message, url) for message, url in console_errors
                if not (
                    (url == f"{base_url}/api/v1/projects" and "400" in message)
                    or (url.startswith(f"{base_url}/api/v1/projects/")
                        and "/lsv-compare-plot/latest?" in url and "404" in message)
                    or (url == f"{base_url}/ui" and "fonts.googleapis.com/css2?" in message
                        and "Content Security Policy" in message)
                )
            ] == []
            browser.close()
    finally:
        release_submit.set()
        manager.stop()
        reset_runtime()


def test_v6_project_workbench_replay_comparison_reports_and_themes(monkeypatch, tmp_path):
    sync_playwright = _sync_playwright_factory()
    monkeypatch.setenv("ELECTROCHEM_V6_HISTORY_FILE", str(tmp_path / "history.json"))
    manager = V6ServerManager(port=_get_free_port())
    ok, _message = manager.start()
    assert ok
    try:
        with sync_playwright() as playwright:
            browser = _launch_chromium(playwright)
            page = browser.new_page(viewport={"width": 1400, "height": 950})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{manager.port}/ui", wait_until="networkidle")
            page.evaluate("""async () => {
              const state = window.projectUiTest = { compare: null, report: null, replay: [], runOffsets: [], sourceMode: 'unchanged' };
              const response = data => ({ ok: true, json: async () => ({ status: 'success', ...data }) });
              state.projects = [{ id: 'p1', name: 'NiFe project', status: 'active', file_count: 2 }, { id: 'p2', name: 'Other project', status: 'active', file_count: 0 }];
              state.records = [
                { record_key: 'key-A', project_id: 'p1', run_id: 'run-A', sample_name: 'NiFe-01', file_path: 'D:/sources/LSV-A.txt', type: 'LSV', timestamp: '2026-09-07 10:00:00', status: 'success', results: { potential_10: .31 }, output_files: ['D:/original-A.csv'], data: {} },
                { record_key: 'key-B', project_id: 'p1', run_id: 'run-B', sample_name: 'NiFe-01', file_name: 'LSV-B.txt', type: 'LSV', timestamp: '2026-09-06 09:00:00', status: 'success', results: { potential_10: .36 }, output_files: ['D:/original-B.csv'], data: {} },
              ];
              projectApi.listProjects = async () => response({ projects: state.projects });
              projectApi.stats = async () => response({ data: { total_files: 2, lsv_count: 2 } });
              projectApi.history = async () => response({ records: state.records, total: 2, has_more: false });
              projectApi.lsvSummary = async () => response({ lsv_summary: { samples: [{ sample_name: 'NiFe-01', potential_10: .31, record_count: 2 }] } });
              projectApi.lsvTargetCurrents = async () => response({ target_currents: [10], potential_target_currents: [10] });
              projectApi.latestLsvComparePlot = async () => response({ plot: null });
              state.records[0].results = { 'potential_at_10.0': .31, potential_10: .31, tafel_slope: 59.999999996 };
              projectApi.listRuns = async (_id, paging) => { state.runOffsets.push(paging.offset); return response({ runs: paging.offset === 0 ? [
                { run_id: 'run-A', record_keys: ['key-A'], data_types: ['LSV'], created_at: '2026-09-07 10:00:00' },
                { run_id: 'run-B', record_keys: ['key-B'], data_types: ['LSV'], created_at: '2026-09-06 09:00:00' },
              ] : [
                { run_id: 'run-empty', record_keys: [], data_types: ['COUPLED'], created_at: '2026-09-05 10:00:00', status: 'success' },
              ], has_more: paging.offset === 0, next_offset: 2 }); };
              projectApi.compareRecords = async payload => { state.compare = payload; return response({ comparison: {
                metrics: [{ key: 'potential_10', label: 'E@10', unit: 'V', left: .31, right: .36, delta: .05, relative_change_percent: 16.129 }, { key: 'Cdl', label: 'Cdl', unit: 'mF/cm²', left_unit: 'F', right_unit: 'mF/cm²', left: .01, right: 10, delta: null, status: 'unit_mismatch' }],
                parameter_changes: [{ key: 'area', before: 1, after: 2 }], warnings: ['Different electrode areas'],
                parameters_known: !state.unknownParameters, versions: { left_app: '6.0.20', right_app: '6.0.21' }, quality: { left: {}, right: {} },
              } }); };
              projectApi.exportScopedReport = async (_id, payload) => { state.report = payload; return response({ path: 'D:/report.html', html_path: 'D:/report.html', markdown_path: 'D:/report.md', scope: { run_count: 2, record_count: 2 } }); };
              projectApi.exportRunReport = async (id, payload) => { state.report = { run_id: id, ...payload }; return response({ path: 'D:/run.html', scope: { run_count: 1, record_count: 1 } }); };
              projectApi.replayPlan = async (runId, payload) => {
                state.lastPlan = payload;
                const changed = state.sourceMode === 'changed' && !payload.allow_changed_sources;
                if (state.sourceMode === 'legacy') return { ok: false, status: 404, json: async () => ({ status: 'error', message: 'Stored recipe unavailable' }) };
                return response({ plan: { run_id: runId, data_types: ['LSV'], params: { area: 1, potential_mode: 'manual', potential_offset: 0, rhe_ph: null, rhe_temperature_c: null, reference_electrode_preset: 'custom', reference_electrode_potential: null, tafel_enabled: true, lsv_line_width: 1, recursive_scan: true, output_run_dir_enabled: true, ...payload.params },
                  source_checks: [{ path: 'D:/source.txt', resolved_path: 'D:/source.txt', file_name: 'source.txt', state: state.sourceMode }],
                  parameter_changes: payload.params && payload.params.area !== undefined ? [{ key: 'area', before: 1, after: payload.params.area }] : [],
                  can_replay: !changed && state.sourceMode !== 'missing' && !(payload.params && payload.params.potential_mode === 'formula_rhe' && payload.params.rhe_ph == null), requires_changed_confirmation: changed, issues: [], warnings: [], source_app_version: '6.0.20', current_app_version: '6.0.21',
                } });
              };
              projectApi.replayRun = async (runId, payload) => { state.replay.push({ runId, ...payload }); return response({ job_id: 'replayed', job: { status: 'succeeded', result: { status: 'success' } } }); };
              projectApi.updateProject = async (id, payload) => { state.projects = state.projects.map(item => item.id === id ? { ...item, ...payload } : item); return response({}); };
              await loadProjects('p1');
              switchTab('project');
            }""")
            assert page.locator("#project-view-results").is_visible()
            assert page.locator("#project-view-compare").is_hidden()
            assert page.locator("#project-view-reports").is_hidden()
            assert page.locator("#project-history-list .project-run-group").count() == 2
            assert page.locator("#project-history-detail-panel").is_hidden()
            assert page.locator("#project-lsv-table").count() == 0
            assert page.locator("#tab-project #storage-cleanup-btn").count() == 0
            assert page.locator("#sys-panel #storage-cleanup-btn").count() == 1
            page.wait_for_selector("[data-replay-empty-run]")
            assert "COUPLED" in page.locator("#project-unrecorded-runs").inner_text()
            assert page.evaluate("projectUiTest.runOffsets.slice(0, 2)") == [0, 2]
            assert "LSV-A.txt" in page.locator(".project-record-open").first.inner_text()
            assert "LSV-B.txt" in page.locator(".project-record-open").nth(1).inner_text()
            assert page.locator(".project-record-metric").first.inner_text() == "E@10: 0.31 V · Tafel: 60 mV/dec"

            page.locator(".project-record-open").first.click()
            assert page.locator("#project-history-detail-panel").is_visible()
            assert page.locator("#project-history-detail-panel").evaluate("el => el.previousElementSibling.dataset.key") == "key-A"
            assert page.locator(".project-result-metrics li").count() == 2
            assert "Tafel: 60 mV/dec" in page.locator(".project-result-metrics").inner_text()
            page.locator(".project-record-check").nth(0).check()
            page.locator(".project-record-check").nth(1).check()
            page.click("#project-compare-records-btn")
            page.wait_for_function("() => !!window.projectUiTest.compare")
            assert page.evaluate("projectUiTest.compare") == {
                "left_record_key": "key-A", "right_record_key": "key-B", "project_id": "p1",
            }
            assert "0.05" in page.locator("#project-version-comparison").inner_text()
            assert "Different electrode areas" in page.locator("#project-version-comparison").inner_text()
            assert "0.01 F" in page.locator("#project-version-comparison").inner_text()
            assert "10 mF/cm²" in page.locator("#project-version-comparison").inner_text()
            assert "LSV-A.txt" in page.locator(".project-comparison-pair").inner_text()
            assert "LSV-B.txt" in page.locator(".project-comparison-pair").inner_text()
            page.evaluate("projectUiTest.unknownParameters = true")
            page.click("#project-version-compare-btn")
            page.wait_for_function("() => document.querySelector('#project-version-comparison').textContent.includes('无法确认参数')")
            page.click("#project-lsv-comparison > summary")
            assert page.locator("#project-compare-table").is_visible()

            page.click("#project-tab-results")
            page.click("#project-report-selected-btn")
            assert page.locator("#project-report-scope").input_value() == "selected"
            page.click("#project-export-report-btn")
            page.wait_for_function("() => !!window.projectUiTest.report")
            assert page.evaluate("projectUiTest.report") == {
                "format": "html", "include_archived": False, "record_keys": ["key-A", "key-B"],
            }
            page.click("#project-tab-results")
            page.locator('.project-record-check[data-record-key="key-B"]').uncheck()
            page.evaluate("async () => { projectUiTest.records[1].run_id = 'run-A'; await loadSelectedProjectDetail(); }")
            page.click("#project-report-selected-btn")
            assert "1 条结果" in page.locator("#project-report-range").inner_text()
            assert "同批次未勾选" in page.locator("#project-report-range").inner_text()
            page.click("#project-export-report-btn")
            page.wait_for_function("() => window.projectUiTest.report.record_keys.length === 1")
            assert page.evaluate("projectUiTest.report") == {
                "format": "html", "include_archived": False, "record_keys": ["key-A"],
            }
            page.click("#project-tab-results")
            page.click("#project-clear-records-btn")
            page.click("#project-tab-reports")
            page.evaluate("projectUiTest.report = null")
            page.click("#project-export-report-btn")
            assert page.evaluate("projectUiTest.report") is None
            assert "请先勾选" in page.locator("#project-report-result").inner_text()
            page.evaluate("async () => { projectUiTest.records[1].run_id = 'run-B'; await loadSelectedProjectDetail(); }")
            page.select_option("#project-report-scope", "project")
            page.click("#project-export-report-btn")
            page.wait_for_function("() => window.projectUiTest.report && !('record_keys' in window.projectUiTest.report)")
            assert page.evaluate("projectUiTest.report") == {"format": "html", "include_archived": False}
            page.select_option("#project-report-scope", "run")
            page.select_option("#project-report-run", "run-empty")
            page.click("#project-export-report-btn")
            page.wait_for_function("() => window.projectUiTest.report.run_id === 'run-empty'")

            page.click("#project-tab-results")
            page.click("#project-replay-btn")
            page.wait_for_selector("#project-replay-execute:not([disabled])")
            page.get_by_label("计算方式", exact=True).select_option("modified")
            assert page.locator('.project-replay-parameter[data-param-key="area"]').is_visible()
            assert page.locator('.project-replay-parameter[data-param-key="lsv_line_width"]').is_hidden()
            assert page.locator('.project-replay-parameter[data-param-key="output_run_dir_enabled"]').count() == 0
            assert page.locator("#project-replay-dialog").get_by_label("启用 Tafel 拟合", exact=True).is_visible()
            for key in ("rhe_ph", "rhe_temperature_c", "reference_electrode_potential"):
                field = page.locator(f'.project-replay-parameter[data-param-key="{key}"]')
                assert field.is_visible()
                assert field.input_value() == ""
            page.fill('.project-replay-parameter[data-param-key="area"]', "2")
            assert page.locator("#project-replay-execute").is_disabled()
            page.click("#project-replay-check")
            page.wait_for_selector("#project-replay-execute:not([disabled])")
            page.click("#project-replay-execute")
            page.wait_for_function("() => window.projectUiTest.replay.length === 1")
            assert page.evaluate("projectUiTest.replay[0]") == {"runId": "run-A", "record_key": "key-A", "params": {"area": 2}}
            page.wait_for_function("() => document.querySelector('#project-replay-status').textContent.includes('原记录')")
            page.click("#project-replay-close")
            assert page.locator("#project-history-list .project-result-row").count() == 2
            assert page.evaluate("projectUiTest.records[0].output_files[0]") == "D:/original-A.csv"

            page.click("#project-replay-btn")
            page.wait_for_selector("#project-replay-execute:not([disabled])")
            page.get_by_label("计算方式", exact=True).select_option("modified")
            page.select_option('.project-replay-parameter[data-param-key="potential_mode"]', "formula_rhe")
            page.fill('.project-replay-parameter[data-param-key="rhe_ph"]', "14")
            page.fill('.project-replay-parameter[data-param-key="rhe_temperature_c"]', "25")
            page.fill('.project-replay-parameter[data-param-key="reference_electrode_potential"]', "0.197")
            page.click("#project-replay-check")
            page.wait_for_selector("#project-replay-execute:not([disabled])")
            assert page.evaluate("projectUiTest.lastPlan.params") == {
                "potential_mode": "formula_rhe", "rhe_ph": 14, "rhe_temperature_c": 25,
                "reference_electrode_potential": 0.197,
            }
            page.fill('.project-replay-parameter[data-param-key="rhe_ph"]', "")
            page.click("#project-replay-check")
            page.wait_for_function("() => !('rhe_ph' in window.projectUiTest.lastPlan.params)")
            assert page.locator("#project-replay-execute").is_disabled()
            assert "rhe_ph" not in page.evaluate("projectUiTest.lastPlan.params")
            page.click("#project-replay-close")

            page.evaluate("projectUiTest.sourceMode = 'changed'")
            page.click("#project-run-replay-btn")
            page.wait_for_selector("#project-replay-allow-changed")
            assert page.locator("#project-replay-execute").is_disabled()
            page.check("#project-replay-allow-changed")
            assert page.locator("#project-replay-execute").is_disabled()
            page.click("#project-replay-check")
            page.wait_for_selector("#project-replay-execute:not([disabled])")
            assert page.evaluate("projectUiTest.lastPlan.allow_changed_sources") is True
            page.click("#project-replay-close")
            page.evaluate("projectUiTest.sourceMode = 'missing'")
            page.click("#project-replay-btn")
            page.wait_for_selector(".project-source-override")
            assert page.locator("#project-replay-execute").is_disabled()
            page.click("#project-replay-close")
            page.evaluate("projectUiTest.sourceMode = 'legacy'")
            page.click("#project-replay-btn")
            page.wait_for_function("() => document.querySelector('#project-replay-content').textContent.includes('Stored recipe unavailable')")
            assert page.locator("#project-replay-execute").count() == 0
            page.click("#project-replay-close")

            nullable = page.evaluate("""() => {
              const originalParams = { tafel_enabled: null, reference_electrode_preset: null, rhe_ph: null, unknown_parameter: null };
              const container = document.createElement('div');
              const base = window.ElectrochemProjectWorkbench.getContext();
              const ctx = { ...base, byId: id => id === 'project-replay-content' ? container : id === 'project-replay-mode' ? { value: 'modified' } : id === 'project-replay-allow-changed' ? null : base.byId(id) };
              container.innerHTML = window.ElectrochemProjectReplay.parameterFields(ctx, originalParams, ['LSV']);
              const replay = { originalParams, plan: { source_checks: [] } };
              const blank = window.ElectrochemProjectReplay.payloadFor(ctx, replay);
              container.querySelector('[data-param-key="tafel_enabled"]').value = 'false';
              container.querySelector('[data-param-key="reference_electrode_preset"]').value = 'custom';
              container.querySelector('[data-param-key="rhe_ph"]').value = '0';
              return { blank, filled: window.ElectrochemProjectReplay.payloadFor(ctx, replay), unknownCount: container.querySelectorAll('[data-param-key="unknown_parameter"]').length };
            }""")
            assert nullable == {
                "blank": {"params": {}},
                "filled": {"params": {"tafel_enabled": False, "reference_electrode_preset": "custom", "rhe_ph": 0}},
                "unknownCount": 0,
            }

            page.evaluate("document.querySelector('#proc-project').value = 'Other project'")
            page.click("#project-more-menu > summary")
            page.click("#project-settings-open")
            page.fill("#project-edit-desc", "updated in settings")
            page.click("#project-save-btn")
            page.wait_for_function("() => !document.querySelector('#project-settings-dialog').open")
            assert page.locator("#proc-project").input_value() == "Other project"
            page.click("#project-use-btn")
            assert page.locator("#tab-pro").is_visible()
            assert page.locator("#proc-project").input_value() == "NiFe project"
            page.click("#tab-btn-project")
            page.select_option("#lang-select", "en")
            page.wait_for_function("() => document.querySelector('#project-tab-results').textContent === 'Results'")
            assert page.locator('#project-report-scope option[value="selected"]').text_content() == "Selected results"
            for theme in ("lab", "dark", "pixel"):
                page.click("#appearance-open")
                page.check(f'input[name="appearance-theme"][value="{theme}"]')
                page.click("#appearance-close")
                assert page.locator("#project-view-results").is_visible()
                assert page.locator(".project-main").evaluate("el => el.scrollWidth <= el.clientWidth + 1")
            page.set_viewport_size({"width": 600, "height": 900})
            assert page.locator(".project-main").evaluate("el => el.scrollWidth <= el.clientWidth + 1")
            assert errors == []
            browser.close()
    finally:
        manager.stop()
