"""Tests for agent/agent_controller.py — conversation logic with mocked LLM."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from electrochem_v6.agent.agent_controller import AgentController, _debug_log

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  _debug_log                                                             ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestDebugLog:
    def test_string_payload(self):
        # Should not raise
        _debug_log("TEST", "hello")

    def test_dict_payload(self):
        _debug_log("TEST", {"key": "value", "中文": "测试"})

    def test_non_serializable(self):
        _debug_log("TEST", object())  # falls back to str()


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  AgentController basics                                                 ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestAgentControllerBasics:
    def _make_controller(self, responses=None):
        """Create controller with a mock LLM client."""
        mock_llm = MagicMock()
        mock_llm.get_model_name.return_value = "test-model"
        if responses:
            mock_llm.chat.side_effect = responses
        else:
            mock_llm.chat.return_value = {"content": "我是AI助手"}
        return AgentController(mock_llm)

    def test_simple_chat(self):
        ctrl = self._make_controller()
        reply = ctrl.chat("你好")
        assert reply == "我是AI助手"
        assert len(ctrl.conversation_history) == 2  # user + assistant

    def test_reset(self):
        ctrl = self._make_controller()
        ctrl.chat("你好")
        assert len(ctrl.conversation_history) > 0
        ctrl.reset()
        assert len(ctrl.conversation_history) == 0

    def test_get_history_returns_copy(self):
        ctrl = self._make_controller()
        ctrl.chat("test")
        h = ctrl.get_history()
        h.clear()
        assert len(ctrl.conversation_history) == 2  # original untouched

    def test_export_conversation(self, tmp_path: Path):
        ctrl = self._make_controller()
        ctrl.chat("hello")
        out_file = tmp_path / "conversation.json"
        result = ctrl.export_conversation(str(out_file))
        assert result is True
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["model"] == "test-model"
        assert len(data["conversation"]) == 2

    def test_export_invalid_path(self):
        ctrl = self._make_controller()
        result = ctrl.export_conversation("/invalid/path/that/does/not/exist.json")
        assert result is False

    def test_llm_error_response(self):
        ctrl = self._make_controller()
        ctrl.llm.chat.return_value = {"error": "API key invalid"}  # type: ignore[attr-defined]
        reply = ctrl.chat("test")
        assert "失败" in reply or "error" in reply.lower() or "API" in reply

    def test_llm_exception(self):
        ctrl = self._make_controller()
        ctrl.llm.chat.side_effect = RuntimeError("network timeout")  # type: ignore[attr-defined]
        reply = ctrl.chat("test")
        assert "出错" in reply or "timeout" in reply.lower()

    def test_max_iterations_reached(self):
        """LLM always returns tool_calls → hits max iterations."""
        ctrl = self._make_controller()
        ctrl.max_iterations = 2
        ctrl.llm.chat.return_value = {  # type: ignore[attr-defined]
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "tool_list_history",
                        "arguments": "{}",
                    },
                }
            ],
        }
        reply = ctrl.chat("list history")
        assert "超时" in reply or "简化" in reply

    def test_callback_invoked(self):
        ctrl = self._make_controller()
        calls = []
        ctrl.chat("hi", callback=lambda msg: calls.append(msg))
        assert len(calls) >= 1
        assert "思考" in calls[0]

    def test_tool_call_and_final_reply(self):
        """LLM returns tool call first, then final reply."""
        tool_response = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "tool_list_history",
                        "arguments": "{}",
                    },
                }
            ],
        }
        final_response = {"content": "处理完成"}
        ctrl = self._make_controller(responses=[tool_response, final_response])
        reply = ctrl.chat("查看历史")
        assert reply == "处理完成"


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  AgentController system prompt                                          ║
# ╚═══════════════════════════════════════════════════════════════════════════╝

class TestAgentControllerPrompt:
    def test_default_prompt(self):
        mock_llm = MagicMock()
        mock_llm.chat.return_value = {"content": "ok"}
        ctrl = AgentController(mock_llm)
        assert "电化学" in ctrl.system_prompt or len(ctrl.system_prompt) > 50

    def test_custom_prompt(self):
        mock_llm = MagicMock()
        mock_llm.chat.return_value = {"content": "ok"}
        ctrl = AgentController(mock_llm, system_prompt="你是一个测试助手")
        assert ctrl.system_prompt == "你是一个测试助手"
