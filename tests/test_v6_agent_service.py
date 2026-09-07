"""Tests for agent/service.py — session management and chat entry."""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from electrochem_v6.agent.request_context import tool_get_professional_mode_context
from electrochem_v6.agent.service import AgentService
from electrochem_v6.agent.tool_executor import execute_tool


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
        raw_key = "sk-proj-secretvalue1234567890"
        with patch.object(svc, "_create_agent", side_effect=ValueError(f"no API key: {raw_key}")):
            result = svc.chat(message="你好")
        assert result["status"] == "error"
        assert "API key" in result["message"] or "no" in result["message"]
        assert raw_key not in result["message"]

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

    def test_prompt_prefix_is_sent_but_not_stored(self):
        svc = AgentService()
        with patch.object(svc, "_create_agent") as mock_create:
            mock_ctrl = self._mock_create_agent()
            mock_create.return_value = (mock_ctrl, "openai", "gpt-4")
            result = svc.chat(
                message="请分析这组数据",
                prompt_prefix="你是电化学数据分析助手",
            )
        assert result["status"] == "success"
        assert "你是电化学数据分析助手" in mock_ctrl.chat.call_args[0][0]
        user_messages = [m for m in (result.get("messages") or []) if m.get("role") == "user"]
        assert user_messages
        assert user_messages[-1].get("content") == "请分析这组数据"

    def test_professional_context_is_available_only_when_agent_calls_tool(self):
        svc = AgentService()
        observed = {}
        professional_context = {
            "context_type": "professional_mode_summary",
            "data_types": ["LSV"],
            "parameters": {"potential_offset": 0.197},
            "data_source": {"raw_file_content_included": False},
        }

        with patch.object(svc, "_create_agent") as mock_create:
            mock_ctrl = MagicMock()

            def _chat(prompt, **_kwargs):
                observed["prompt"] = prompt
                observed["tool_result"] = tool_get_professional_mode_context()
                return "当前设置看起来正常"

            mock_ctrl.chat.side_effect = _chat
            mock_ctrl.get_last_tool_calls.return_value = ["get_professional_mode_context"]
            mock_create.return_value = (mock_ctrl, "openai", "gpt-4")
            result = svc.chat(
                message="检查当前设置",
                professional_context=professional_context,
            )

        assert result["status"] == "success"
        assert observed["tool_result"] == {
            "success": True,
            "available": True,
            "context": professional_context,
        }
        assert "professional_mode_summary" not in observed["prompt"]
        assert result["context_usage"]["professional_mode"] is True
        assert result["context_usage"]["database"] is False
        agent_messages = [item for item in result["messages"] if item.get("role") == "agent"]
        assert agent_messages[-1]["metadata"]["context_usage"]["professional_mode"] is True
        assert tool_get_professional_mode_context()["available"] is False

    def test_database_tool_usage_is_reported_separately(self):
        svc = AgentService()
        with patch.object(svc, "_create_agent") as mock_create:
            mock_ctrl = self._mock_create_agent()
            mock_ctrl.get_last_tool_calls.return_value = ["get_processing_history"]
            mock_create.return_value = (mock_ctrl, "openai", "gpt-4")
            result = svc.chat(message="总结最近实验")

        assert result["context_usage"] == {
            "professional_mode": False,
            "database": True,
            "local_data": False,
            "tools": ["get_processing_history"],
        }

    def test_mutating_tool_requires_bound_one_time_approval(self):
        svc = AgentService()
        mock_ctrl = self._mock_create_agent()
        calls = {"count": 0}

        def _chat(_prompt, **_kwargs):
            if calls["count"] == 0:
                gate_result = execute_tool("create_project", {"name": "确认测试项目", "description": "safe"})
                assert gate_result["confirmation_required"] is True
            calls["count"] += 1
            return "请确认创建项目" if calls["count"] == 1 else "已说明执行结果"

        mock_ctrl.chat.side_effect = _chat
        mock_ctrl.get_last_tool_calls.return_value = ["create_project"]
        with (
            patch.object(svc, "_create_agent", return_value=(mock_ctrl, "openai", "gpt-4")),
            patch("electrochem_v6.agent.tool_executor.tool_create_project") as create_project,
        ):
            create_project.return_value = {"success": True, "project_id": "p-confirmed"}
            pending = svc.chat(message="创建一个名为确认测试项目的项目")
            assert pending["status"] == "success"
            assert len(pending["pending_approvals"]) == 1
            approval = pending["pending_approvals"][0]
            assert approval["summary"] == "创建项目“确认测试项目”"
            assert "arguments" not in approval
            assert approval["details"] == {
                "project_name": "确认测试项目",
                "description": "safe",
            }
            create_project.assert_not_called()

            confirmed = svc.chat(
                message="",
                conversation_id=pending["conversation_id"],
                approval_id=approval["approval_id"],
                approval_action="approve",
            )
            assert confirmed["status"] == "success"
            assert confirmed["resolved_approval_ids"] == [approval["approval_id"]]
            assert confirmed["approved_action_result"]["project_id"] == "p-confirmed"
            assert confirmed["write_action_started"] is True
            assert confirmed["write_action_succeeded"] is True
            create_project.assert_called_once_with(name="确认测试项目", description="safe")

            reused = svc.chat(
                message="再次执行",
                conversation_id=pending["conversation_id"],
                approval_id=approval["approval_id"],
                approval_action="approve",
            )
            assert reused["status"] == "error"
            create_project.assert_called_once()

    def test_mutating_tool_can_be_declined_without_execution(self):
        svc = AgentService()
        mock_ctrl = self._mock_create_agent()
        first_call = True

        def _chat(_prompt, **_kwargs):
            nonlocal first_call
            if first_call:
                first_call = False
                execute_tool("create_project", {"name": "不要创建"})
                return "请确认"
            return "已取消"

        mock_ctrl.chat.side_effect = _chat
        with (
            patch.object(svc, "_create_agent", return_value=(mock_ctrl, "openai", "gpt-4")),
            patch("electrochem_v6.agent.tool_executor.tool_create_project") as create_project,
        ):
            pending = svc.chat(message="创建项目")
            approval = pending["pending_approvals"][0]
            declined = svc.chat(
                message="",
                conversation_id=pending["conversation_id"],
                approval_id=approval["approval_id"],
                approval_action="decline",
            )
        assert declined["status"] == "success"
        assert declined["approved_action_result"] is None
        create_project.assert_not_called()

    def test_existing_conversation_history_is_hydrated_after_service_restart(self):
        first_service = AgentService()
        first_ctrl = self._mock_create_agent()
        first_ctrl.MAX_HISTORY_MESSAGES = 80
        with patch.object(first_service, "_create_agent", return_value=(first_ctrl, "openai", "gpt-4")):
            first = first_service.chat(message="第一轮问题")

        restored = {}
        second_service = AgentService()
        second_ctrl = self._mock_create_agent()
        second_ctrl.MAX_HISTORY_MESSAGES = 80

        def _capture_history(_prompt, **_kwargs):
            restored["history"] = list(second_ctrl.conversation_history)
            return "理解了上一轮"

        second_ctrl.chat.side_effect = _capture_history
        with patch.object(second_service, "_create_agent", return_value=(second_ctrl, "openai", "gpt-4")):
            second = second_service.chat(message="继续分析", conversation_id=first["conversation_id"])

        assert second["status"] == "success"
        assert restored["history"][-2:] == [
            {"role": "user", "content": "第一轮问题"},
            {"role": "assistant", "content": "这是AI回复"},
        ]

    def test_auto_process_approval_exposes_scientific_parameters(self):
        svc = AgentService()
        details = svc._approval_details(
            "auto_process_with_smart_params",
            {
                "folder_path": "D:/experiments/batch-7",
                "data_type": "LSV",
                "project_name": "OER batch",
                "potential_offset": 0.197,
                "electrode_area": 0.25,
                "target_current": "10,50",
                "tafel_range": "2-12",
            },
        )
        assert details == {
            "folder_path": "D:/experiments/batch-7",
            "data_type": "LSV",
            "project_name": "OER batch",
            "potential_offset_v": 0.197,
            "electrode_area_cm2": 0.25,
            "target_current_ma_cm2": "10,50",
            "tafel_enabled": True,
            "tafel_range_ma_cm2": "2-12",
        }

    def test_restart_marks_persisted_pending_approval_expired(self):
        svc = AgentService()
        mock_ctrl = self._mock_create_agent()

        def _chat(_prompt, **_kwargs):
            execute_tool("create_project", {"name": "restart-test"})
            return "请确认"

        mock_ctrl.chat.side_effect = _chat
        with patch.object(svc, "_create_agent", return_value=(mock_ctrl, "openai", "gpt-4")):
            pending = svc.chat(message="创建项目")

        restarted_service = AgentService()
        annotated = restarted_service.annotate_conversation_approvals(pending["conversation"])
        agent_messages = [item for item in annotated["messages"] if item.get("role") == "agent"]
        approval = agent_messages[-1]["metadata"]["pending_approvals"][0]
        assert approval["status"] == "expired"

    def test_delete_session_revokes_pending_approval(self):
        svc = AgentService()
        mock_ctrl = self._mock_create_agent()

        def _chat(_prompt, **_kwargs):
            execute_tool("create_project", {"name": "deleted-chat-project"})
            return "请确认"

        mock_ctrl.chat.side_effect = _chat
        with (
            patch.object(svc, "_create_agent", return_value=(mock_ctrl, "openai", "gpt-4")),
            patch("electrochem_v6.agent.tool_executor.tool_create_project") as create_project,
        ):
            pending = svc.chat(message="创建项目")
            approval_id = pending["pending_approvals"][0]["approval_id"]
            cid = pending["conversation_id"]
            svc.delete_session(cid)
            result = svc.chat(
                message="确认",
                conversation_id=cid,
                approval_id=approval_id,
                approval_action="approve",
            )
        assert result["status"] == "error"
        assert "已删除" in result["message"]
        create_project.assert_not_called()

    def test_same_conversation_requests_are_serialized(self):
        svc = AgentService()
        cid = f"serialized-{uuid.uuid4().hex}"
        mock_ctrl = self._mock_create_agent()
        mock_ctrl.MAX_HISTORY_MESSAGES = 80
        setattr(mock_ctrl, "provider", "openai")
        setattr(mock_ctrl, "model_name", "gpt-4")
        state_lock = threading.Lock()
        state = {"active": 0, "max_active": 0}

        def _chat(prompt, **_kwargs):
            with state_lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            time.sleep(0.05)
            with state_lock:
                state["active"] -= 1
            return f"reply:{prompt}"

        mock_ctrl.chat.side_effect = _chat
        with (
            patch.object(svc, "_create_agent", return_value=(mock_ctrl, "openai", "gpt-4")),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            futures = [
                pool.submit(svc.chat, message=f"message-{index}", conversation_id=cid)
                for index in range(2)
            ]
            results = [future.result(timeout=3) for future in futures]
        assert all(result["status"] == "success" for result in results)
        assert state["max_active"] == 1
