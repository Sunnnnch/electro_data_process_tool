"""Agent service for v6 unified message endpoint."""

from __future__ import annotations

import json
import threading
import time
import uuid
import weakref
from collections import OrderedDict
from copy import deepcopy
from typing import Any, Callable, Dict, Optional

from electrochem_v6.agent.actions import completed_result_card, finish_action_collection, start_action_collection
from electrochem_v6.agent.agent_controller import AgentController
from electrochem_v6.agent.client_settings import resolve_client_settings
from electrochem_v6.agent.request_context import (
    get_pending_mutations,
    reset_pending_mutation_collection,
    reset_professional_mode_context,
    set_professional_mode_context,
    start_pending_mutation_collection,
)
from electrochem_v6.agent.tool_executor import execute_tool
from electrochem_v6.core.job_control import (
    NON_CANCELLABLE_PROGRESS_PREFIX,
    ProcessingCancelledError,
)
from electrochem_v6.llm.config import LLMConfig
from electrochem_v6.llm.error_utils import sanitize_llm_error
from electrochem_v6.llm.factory import create_llm_client
from electrochem_v6.store.conversations import append_message, get_conversation

_DATABASE_QUERY_TOOLS = {
    "analyze_processing_results",
    "compare_catalysts",
    "find_best_catalysts",
    "get_catalyst_info",
    "get_current_compare_selection",
    "get_current_project_history",
    "get_current_project_summary",
    "get_processing_history",
    "query_lsv_summary",
    "read_quality_report",
    "prepare_record_comparison",
    "prepare_run_replay",
    "prepare_result_report",
}
_LOCAL_DATA_TOOLS = {
    "analyze_data_characteristics",
    "preview_data_file",
    "scan_data_folder",
}
_MAX_DELETED_CONVERSATION_TOMBSTONES = 2048
_APPROVAL_TTL_SECONDS = 15 * 60


class AgentService:
    """Session-based chat service without license gating."""

    def __init__(self):
        self._sessions: Dict[str, AgentController] = {}
        self._session_config_keys: Dict[str, str] = {}
        self._sessions_lock = threading.Lock()
        self._pending_approvals: Dict[str, Dict[str, Any]] = {}
        self._approval_lock = threading.Lock()
        self._conversation_locks: weakref.WeakValueDictionary[str, Any] = (
            weakref.WeakValueDictionary()
        )
        self._conversation_locks_lock = threading.Lock()
        self._deleted_conversations: OrderedDict[str, None] = OrderedDict()

    def _create_agent(
        self,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        *,
        config: Optional[LLMConfig] = None,
    ) -> tuple[AgentController, str, str]:
        cfg = config if config is not None else LLMConfig()
        provider_key, resolved_model, _ = resolve_client_settings(cfg, provider, model_name)
        client = create_llm_client(cfg, provider=provider_key, model_override=resolved_model)
        controller = AgentController(client)
        return controller, provider_key, resolved_model

    def _agent_for_request(
        self, cid: str, provider: Optional[str], model: Optional[str],
    ) -> tuple[AgentController, str, str]:
        # The caller holds the conversation lock. Read once so the comparison
        # and newly constructed client use the same settings, including env keys.
        cfg = LLMConfig()
        _, _, signature = resolve_client_settings(cfg, provider, model)
        with self._sessions_lock:
            previous = self._sessions.get(cid)
            previous_signature = self._session_config_keys.get(cid)
        if previous is not None and previous_signature == signature:
            return previous, getattr(previous, "provider"), getattr(previous, "model_name")

        agent, provider_key, resolved_model = self._create_agent(provider, model, config=cfg)
        if previous is not None:
            # Preserve tool exchanges and enriched processing context as well as
            # visible messages when changing the provider/client configuration.
            agent.conversation_history = deepcopy(previous.conversation_history)
            agent.system_prompt = previous.system_prompt
            agent.max_iterations = previous.max_iterations
        else:
            self._hydrate_agent_history(agent, cid)
        setattr(agent, "provider", provider_key)
        setattr(agent, "model_name", resolved_model)
        with self._sessions_lock:
            self._sessions[cid] = agent
            self._session_config_keys[cid] = signature
        return agent, provider_key, resolved_model

    def delete_session(self, conversation_id: str) -> None:
        cid = str(conversation_id or "").strip()
        if not cid:
            return
        with self._sessions_lock:
            self._deleted_conversations[cid] = None
            self._deleted_conversations.move_to_end(cid)
            while len(self._deleted_conversations) > _MAX_DELETED_CONVERSATION_TOMBSTONES:
                self._deleted_conversations.popitem(last=False)
        conversation_lock = self._get_conversation_lock(cid)
        with conversation_lock:
            with self._sessions_lock:
                self._sessions.pop(cid, None)
                self._session_config_keys.pop(cid, None)
            with self._approval_lock:
                stale_ids = [
                    approval_id
                    for approval_id, item in self._pending_approvals.items()
                    if str(item.get("conversation_id") or "") == cid
                ]
                for approval_id in stale_ids:
                    self._pending_approvals.pop(approval_id, None)

    def _get_conversation_lock(self, conversation_id: str) -> threading.RLock:
        cid = str(conversation_id or "").strip()
        with self._conversation_locks_lock:
            lock = self._conversation_locks.get(cid)
            if lock is None:
                lock = threading.RLock()
                self._conversation_locks[cid] = lock
            return lock

    def _conversation_was_deleted(self, conversation_id: str) -> bool:
        with self._sessions_lock:
            return str(conversation_id or "") in self._deleted_conversations

    @staticmethod
    def _hydrate_agent_history(agent: AgentController, conversation_id: str) -> int:
        conversation = get_conversation(conversation_id)
        messages = conversation.get("messages") if isinstance(conversation, dict) else []
        history = []
        for item in messages if isinstance(messages, list) else []:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            if role == "agent":
                role = "assistant"
            if role not in {"user", "assistant"}:
                continue
            content = str(item.get("content") or "").strip()
            if content:
                history.append({"role": role, "content": content})
        max_messages = int(getattr(agent, "MAX_HISTORY_MESSAGES", 80) or 80)
        restored = history[-max_messages:]
        agent.conversation_history = restored
        return len(restored)

    @staticmethod
    def _approval_summary(tool_name: str, arguments: Dict[str, Any]) -> str:
        if tool_name == "create_project":
            name = str(arguments.get("name") or "未命名项目").strip()
            return f"创建项目“{name}”"
        if tool_name == "auto_process_with_smart_params":
            folder = str(arguments.get("folder_path") or "所选目录").strip().replace("\\", "/")
            folder_name = folder.rstrip("/").split("/")[-1] or "所选目录"
            data_type = str(arguments.get("data_type") or "数据").strip().upper()
            return f"处理“{folder_name}”中的 {data_type} 数据并生成结果文件"
        return f"执行写操作 {tool_name}"

    @staticmethod
    def _approval_details(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "create_project":
            return {
                "project_name": str(arguments.get("name") or "未命名项目").strip(),
                "description": str(arguments.get("description") or "").strip(),
            }
        if tool_name != "auto_process_with_smart_params":
            return {}

        folder_path = str(arguments.get("folder_path") or "").strip()
        normalized_folder = folder_path.replace("\\", "/").rstrip("/")
        folder_name = normalized_folder.split("/")[-1] if normalized_folder else "未命名项目"
        data_type = str(arguments.get("data_type") or "").strip().upper()
        details: Dict[str, Any] = {
            "folder_path": folder_path,
            "data_type": data_type,
            "project_name": str(arguments.get("project_name") or folder_name).strip(),
            "potential_offset_v": arguments.get("potential_offset")
            if arguments.get("potential_offset") is not None
            else 0.0,
            "electrode_area_cm2": arguments.get("electrode_area")
            if arguments.get("electrode_area") is not None
            else 1.0,
        }
        if data_type == "LSV":
            details["target_current_ma_cm2"] = str(arguments.get("target_current") or "10,100")
            details["tafel_enabled"] = arguments.get("tafel_range") is not None
            if arguments.get("tafel_range") is not None:
                details["tafel_range_ma_cm2"] = str(arguments.get("tafel_range"))
        if data_type == "COUPLED":
            details["coupled_products_file"] = str(arguments.get("coupled_products_file") or "")
            details["coupled_products_sheet"] = str(arguments.get("coupled_products_sheet") or "0")
            details["output_filename"] = str(
                arguments.get("coupled_results_csv_filename") or "coupled_results.csv"
            )
        extra_params = arguments.get("extra_gui_params")
        if isinstance(extra_params, dict) and extra_params:
            details["additional_parameters"] = deepcopy(extra_params)
        return details

    @staticmethod
    def _approval_is_expired(item: Dict[str, Any], now: float) -> bool:
        return now - float(item.get("created_at") or 0) > _APPROVAL_TTL_SECONDS

    def _prune_expired_approvals_locked(self, now: float) -> None:
        expired = [
            key
            for key, item in self._pending_approvals.items()
            if self._approval_is_expired(item, now)
        ]
        for key in expired:
            self._pending_approvals.pop(key, None)

    def annotate_conversation_approvals(
        self,
        conversation: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Mark persisted confirmation cards using the current live approval registry."""

        if not isinstance(conversation, dict):
            return conversation
        result: Dict[str, Any] = deepcopy(conversation)
        now = time.time()
        with self._approval_lock:
            self._prune_expired_approvals_locked(now)
            active = {
                approval_id: dict(item)
                for approval_id, item in self._pending_approvals.items()
            }
        conversation_id = str(result.get("conversation_id") or "")
        raw_messages = result.get("messages")
        messages: list[Any] = raw_messages if isinstance(raw_messages, list) else []
        for message in messages:
            if not isinstance(message, dict):
                continue
            raw_metadata = message.get("metadata")
            metadata: Dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
            raw_approvals = metadata.get("pending_approvals")
            approvals: list[Any] = raw_approvals if isinstance(raw_approvals, list) else []
            for approval in approvals:
                if not isinstance(approval, dict):
                    continue
                approval_id = str(approval.get("approval_id") or "")
                live = active.get(approval_id)
                same_conversation = bool(
                    live and str(live.get("conversation_id") or "") == conversation_id
                )
                approval["status"] = "pending" if same_conversation else "expired"
        return result

    def _store_pending_approvals(
        self,
        conversation_id: str,
        pending_items: list[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        now = time.time()
        result = []
        with self._approval_lock:
            self._prune_expired_approvals_locked(now)
            for item in pending_items:
                if not isinstance(item, dict):
                    continue
                tool_name = str(item.get("tool_name") or "").strip()
                raw_arguments = item.get("arguments")
                arguments: Dict[str, Any] = (
                    deepcopy(raw_arguments) if isinstance(raw_arguments, dict) else {}
                )
                if not tool_name:
                    continue
                approval_id = uuid.uuid4().hex
                summary = self._approval_summary(tool_name, arguments)
                details = self._approval_details(tool_name, arguments)
                expires_at_epoch_ms = int((now + _APPROVAL_TTL_SECONDS) * 1000)
                self._pending_approvals[approval_id] = {
                    "approval_id": approval_id,
                    "conversation_id": conversation_id,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "summary": summary,
                    "details": details,
                    "created_at": now,
                }
                result.append({
                    "approval_id": approval_id,
                    "tool_name": tool_name,
                    "summary": summary,
                    "details": details,
                    "expires_at_epoch_ms": expires_at_epoch_ms,
                    "status": "pending",
                })
        return result

    def _take_pending_approval(
        self,
        approval_id: str,
        conversation_id: str,
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        clean_id = str(approval_id or "").strip()
        if not clean_id:
            return None, "缺少确认操作 ID"
        with self._approval_lock:
            item = self._pending_approvals.get(clean_id)
            if not item:
                return None, "待确认操作不存在或已失效"
            if self._approval_is_expired(item, time.time()):
                self._pending_approvals.pop(clean_id, None)
                return None, "待确认操作已过期，请重新提出请求"
            expected_cid = str(item.get("conversation_id") or "")
            if conversation_id and expected_cid and conversation_id != expected_cid:
                return None, "待确认操作不属于当前会话"
            self._pending_approvals.pop(clean_id, None)
            return item, None

    def chat(
        self,
        *,
        message: str,
        conversation_id: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        project_name: Optional[str] = None,
        data_type: Optional[str] = None,
        processing_result: Optional[Dict[str, Any]] = None,
        attachments: Optional[list[Dict[str, Any]]] = None,
        prompt_prefix: Optional[str] = None,
        professional_context: Optional[Dict[str, Any]] = None,
        approval_id: Optional[str] = None,
        approval_action: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        cid = str(conversation_id or "").strip() or uuid.uuid4().hex
        conversation_lock = self._get_conversation_lock(cid)
        with conversation_lock:
            if self._conversation_was_deleted(cid):
                return {"status": "error", "message": "会话已删除，请新建会话后重试"}
            return self._chat_locked(
                message=message,
                conversation_id=cid,
                provider=provider,
                model=model,
                project_name=project_name,
                data_type=data_type,
                processing_result=processing_result,
                attachments=attachments,
                prompt_prefix=prompt_prefix,
                professional_context=professional_context,
                approval_id=approval_id,
                approval_action=approval_action,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )

    def _chat_locked(
        self,
        *,
        message: str,
        conversation_id: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        project_name: Optional[str] = None,
        data_type: Optional[str] = None,
        processing_result: Optional[Dict[str, Any]] = None,
        attachments: Optional[list[Dict[str, Any]]] = None,
        prompt_prefix: Optional[str] = None,
        professional_context: Optional[Dict[str, Any]] = None,
        approval_id: Optional[str] = None,
        approval_action: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        clean_message = str(message or "").strip()
        clean_approval_id = str(approval_id or "").strip()
        clean_approval_action = str(approval_action or "").strip().lower()
        if not clean_message and not processing_result and not clean_approval_id:
            return {"status": "error", "message": "message 字段不能为空"}
        if clean_approval_id and clean_approval_action not in {"approve", "decline"}:
            return {"status": "error", "message": "approval_action 必须是 approve 或 decline"}
        if not clean_message and processing_result:
            clean_message = "请总结本次处理结果并给出下一步建议。"
        clean_prompt_prefix = str(prompt_prefix or "").strip()

        cid = conversation_id or ""
        try:
            agent, provider_key, resolved_model = self._agent_for_request(cid, provider, model)
        except Exception as exc:
            return {"status": "error", "message": sanitize_llm_error(exc)}

        resolved_approval_ids: list[str] = []
        approved_item: Optional[Dict[str, Any]] = None
        approved_result: Optional[Dict[str, Any]] = None
        write_action_started = False
        approval_prompt = ""
        if clean_approval_id:
            approved_item, approval_error = self._take_pending_approval(clean_approval_id, cid)
            if approval_error or not approved_item:
                return {"status": "error", "message": approval_error or "待确认操作不可用"}
            resolved_approval_ids.append(clean_approval_id)
            summary = str(approved_item.get("summary") or "待确认操作")
            if clean_approval_action == "approve":
                if callable(cancel_check) and cancel_check():
                    raise ProcessingCancelledError("AI 写操作已取消")
                if callable(progress_callback):
                    progress_callback(
                        f"{NON_CANCELLABLE_PROGRESS_PREFIX}正在执行已确认操作：{summary}"
                    )
                if callable(cancel_check) and cancel_check():
                    raise ProcessingCancelledError("AI 写操作已取消")
                write_action_started = True
                approved_result = execute_tool(
                    str(approved_item.get("tool_name") or ""),
                    approved_item.get("arguments") or {},
                    approved=True,
                )
                if not clean_message:
                    clean_message = f"确认执行：{summary}"
                result_json = json.dumps(approved_result, ensure_ascii=False, indent=2, default=str)
                approval_prompt = (
                    "用户已通过界面确认以下具体操作，系统已按确认时绑定的参数执行。\n"
                    f"操作：{summary}\n"
                    "执行结果：\n```json\n"
                    f"{result_json}\n```\n"
                    "请解释执行是否成功、关键结果及必要的下一步建议。不要再次执行同一操作。"
                )
            else:
                if not clean_message:
                    clean_message = f"取消执行：{summary}"
                approval_prompt = (
                    f"用户已取消待执行操作：{summary}。"
                    "该操作没有执行。请简短确认取消结果，不要再次发起该操作。"
                )

        context_token = set_professional_mode_context(
            professional_context if isinstance(professional_context, dict) else None
        )
        pending_token = start_pending_mutation_collection()
        action_token = start_action_collection()
        action_cards: list[Dict[str, Any]] = []
        pending_mutations: list[Dict[str, Any]] = []
        try:
            prompt_text = approval_prompt or clean_message
            if not approval_prompt and processing_result is not None:
                summary_json = json.dumps(processing_result, ensure_ascii=False, indent=2, default=str)
                prompt_text = (
                    "以下是刚完成的一次电化学数据处理结果，请结合用户指令进行回答。\n"
                    f"数据类型：{data_type or '未指定'}\n"
                    f"项目：{project_name or '未命名'}\n"
                    "处理结果：\n```json\n"
                    f"{summary_json}\n```\n"
                    f"用户指令：{clean_message}"
                )
            elif project_name or data_type:
                prompt_text = (
                    f"当前项目：{project_name or '未命名'}\n"
                    f"当前数据类型：{data_type or '未指定'}\n"
                    f"用户指令：{clean_message}"
                )
            if clean_prompt_prefix:
                prompt_text = f"{clean_prompt_prefix}\n\n{prompt_text}"
            reply = agent.chat(
                prompt_text,
                callback=progress_callback,
                cancel_check=None if approval_prompt else cancel_check,
            )
        except ProcessingCancelledError:
            raise
        except Exception as exc:
            if not approval_prompt:
                return {"status": "error", "message": f"Agent 调用失败: {sanitize_llm_error(exc)}"}
            if clean_approval_action == "approve":
                succeeded = bool(isinstance(approved_result, dict) and approved_result.get("success"))
                reply = "已执行确认操作。" if succeeded else "确认操作已执行，但工具返回了失败结果。"
            else:
                reply = "已取消该操作，未修改项目或生成处理结果。"
        finally:
            action_cards = finish_action_collection(action_token)
            pending_mutations = get_pending_mutations()
            reset_pending_mutation_collection(pending_token)
            reset_professional_mode_context(context_token)

        tool_reader = getattr(agent, "get_last_tool_calls", None)
        raw_tools = tool_reader() if callable(tool_reader) else []
        used_tools = [str(item) for item in raw_tools if str(item).strip()] if isinstance(raw_tools, list) else []
        if approved_item and clean_approval_action == "approve":
            approved_tool = str(approved_item.get("tool_name") or "").strip()
            if approved_tool and approved_tool not in used_tools:
                used_tools.append(approved_tool)
        pending_approvals = self._store_pending_approvals(cid, pending_mutations)
        for completed in (processing_result, approved_result):
            card = completed_result_card(completed)
            if card and not any(item.get("kind") == "open_results" and item.get("run_id") == card["run_id"] for item in action_cards):
                action_cards.append(card)
        context_usage = {
            "professional_mode": any(item in {"get_professional_mode_context", "propose_parameter_changes"} for item in used_tools),
            "database": any(item in _DATABASE_QUERY_TOOLS for item in used_tools),
            "local_data": any(item in _LOCAL_DATA_TOOLS for item in used_tools),
            "tools": used_tools,
        }

        meta = {
            "source": "v6_agent_messages",
            "project_name": project_name,
            "data_type": data_type,
            "provider": provider_key,
            "model": resolved_model,
        }
        if processing_result is not None:
            meta["processing_snapshot"] = {
                "summary": processing_result.get("summary"),
                "quality_summary": processing_result.get("quality_summary"),
            }
        cid = append_message(
            cid,
            "user",
            clean_message,
            metadata={**meta, "message_type": "user_message"},
            attachments=attachments or [],
        )
        append_message(
            cid,
            "agent",
            reply or "",
            metadata={
                **meta,
                "message_type": "agent_reply",
                "context_usage": context_usage,
                "tools_used": used_tools,
                "pending_approvals": pending_approvals,
                "action_cards": action_cards,
                "resolved_approval_ids": resolved_approval_ids,
            },
        )
        conversation = get_conversation(cid)
        return {
            "status": "success",
            "conversation_id": cid,
            "provider": provider_key,
            "model": resolved_model,
            "agent_reply": reply,
            "processing_result": processing_result,
            "attachments": attachments or [],
            "context_usage": context_usage,
            "tools_used": used_tools,
            "pending_approvals": pending_approvals,
            "action_cards": action_cards,
            "resolved_approval_ids": resolved_approval_ids,
            "approved_action_result": approved_result,
            "write_action_started": write_action_started,
            "write_action_succeeded": bool(
                write_action_started
                and isinstance(approved_result, dict)
                and approved_result.get("success")
            ),
            "messages": conversation.get("messages", []) if conversation else [],
            "conversation": conversation,
        }
