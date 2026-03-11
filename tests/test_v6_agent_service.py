"""Tests for agent/service.py — session management and chat entry."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from electrochem_v6.agent.service import AgentService


class TestAgentService:
    def _mock_create_agent(self):
        """Patch _create_agent to return a mock controller."""
        mock_ctrl = MagicMock()
        mock_ctrl.chat.return_value = "这是AI回复"
        return mock_ctrl

    def test_empty_message_error(self):
        svc = AgentService()
        result = svc.chat(message="")
        assert result["status"] == "error"
        assert "空" in result["message"]

    def test_empty_message_with_processing_result(self):
        svc = AgentService()
        with patch.object(svc, "_create_agent") as mock_create:
            mock_ctrl = self._mock_create_agent()
            mock_create.return_value = (mock_ctrl, "openai", "gpt-4")
            result = svc.chat(
                message="",
                processing_result={"summary": "处理完成", "files": 5},
            )
        assert result["status"] == "success"
        assert "conversation_id" in result

    def test_basic_chat(self):
        svc = AgentService()
        with patch.object(svc, "_create_agent") as mock_create:
            mock_ctrl = self._mock_create_agent()
            mock_create.return_value = (mock_ctrl, "openai", "gpt-4")
            result = svc.chat(message="你好")
        assert result["status"] == "success"
        assert result["agent_reply"] == "这是AI回复"

    def test_session_reuse(self):
        svc = AgentService()
        with patch.object(svc, "_create_agent") as mock_create:
            mock_ctrl = self._mock_create_agent()
            mock_create.return_value = (mock_ctrl, "openai", "gpt-4")
            r1 = svc.chat(message="第一条")
            cid = r1["conversation_id"]

        # Manually register the controller in sessions
        svc._sessions[cid] = mock_ctrl
        setattr(mock_ctrl, "provider", "openai")
        setattr(mock_ctrl, "model_name", "gpt-4")

        # Second chat reuses session
        mock_ctrl.chat.return_value = "第二条回复"
        r2 = svc.chat(message="第二条", conversation_id=cid)
        assert r2["status"] == "success"

    def test_delete_session(self):
        svc = AgentService()
        svc._sessions["test-cid"] = MagicMock()
        svc.delete_session("test-cid")
        assert "test-cid" not in svc._sessions

    def test_delete_nonexistent_session(self):
        svc = AgentService()
        svc.delete_session("no-such-id")  # should not raise

    def test_create_agent_failure(self):
        svc = AgentService()
        with patch.object(svc, "_create_agent", side_effect=ValueError("no API key")):
            result = svc.chat(message="你好")
        assert result["status"] == "error"
        assert "API key" in result["message"] or "no" in result["message"]

    def test_agent_chat_exception(self):
        svc = AgentService()
        with patch.object(svc, "_create_agent") as mock_create:
            mock_ctrl = MagicMock()
            mock_ctrl.chat.side_effect = RuntimeError("LLM crash")
            mock_create.return_value = (mock_ctrl, "openai", "gpt-4")
            result = svc.chat(message="test")
        assert result["status"] == "error"
        assert "失败" in result["message"] or "crash" in result["message"]

    def test_with_project_context(self):
        svc = AgentService()
        with patch.object(svc, "_create_agent") as mock_create:
            mock_ctrl = self._mock_create_agent()
            mock_create.return_value = (mock_ctrl, "openai", "gpt-4")
            result = svc.chat(
                message="分析结果",
                project_name="催化剂A",
                data_type="LSV",
            )
        assert result["status"] == "success"
        # Verify the prompt was enriched with context
        call_args = mock_ctrl.chat.call_args[0][0]
        assert "催化剂A" in call_args or "LSV" in call_args
