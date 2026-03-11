import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
REPO = ROOT.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from electrochem_v6.server import V6ServerManager  # noqa: E402
from electrochem_v6.store.conversations import append_message, get_conversation  # noqa: E402


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
    ):
        cid = conversation_id or f"ui_conv_{_get_free_port()}"
        meta = {
            "provider": provider or "mock",
            "model": model or "mock-model",
            "project_name": project_name,
            "data_type": data_type,
        }
        cid = append_message(cid, "user", message, metadata=meta)
        md_reply = "## 测试结果\n- **关键点**\n- `code_snippet`"
        append_message(cid, "agent", md_reply, metadata=meta)
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
    playwright_sync = pytest.importorskip("playwright.sync_api")
    sync_playwright = playwright_sync.sync_playwright

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
    manager._agent_service = _DummyAgentService()
    ok, _msg = manager.start()
    assert ok

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as exc:
                pytest.skip(f"playwright browser not available: {exc}")

            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/ui", wait_until="networkidle")

            page.click("#tab-btn-ai")
            page.fill("#msg-input", "请输出 markdown 测试")
            page.click("#send-btn")

            page.wait_for_selector(".msg.agent .content strong", timeout=10000)
            page.wait_for_selector(".msg.agent .content code", timeout=10000)

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
            browser.close()
    finally:
        manager.stop()
