"""Agent service for v6 unified message endpoint."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional

from electrochem_v6.agent.agent_controller import AgentController
from electrochem_v6.llm.config import LLMConfig
from electrochem_v6.llm.factory import create_llm_client

from electrochem_v6.store.conversations import append_message, get_conversation


class AgentService:
    """Session-based chat service without license gating."""

    def __init__(self):
        self._sessions: Dict[str, AgentController] = {}

    def _create_agent(
        self,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> tuple[AgentController, str, str]:
        cfg = LLMConfig()
        provider_key = cfg.normalize_provider(provider or cfg.config.get("default_model", "openai"))
        model_cfg = cfg.get_model_config(provider_key) or {}
        resolved_model = model_name or model_cfg.get("model") or "gpt-4o"
        client = create_llm_client(cfg, provider=provider_key, model_override=resolved_model)
        controller = AgentController(client)
        return controller, provider_key, resolved_model

    def delete_session(self, conversation_id: str) -> None:
        self._sessions.pop(conversation_id, None)

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
    ) -> Dict[str, Any]:
        clean_message = str(message or "").strip()
        if not clean_message and not processing_result:
            return {"status": "error", "message": "message 字段不能为空"}
        if not clean_message and processing_result:
            clean_message = "请总结本次处理结果并给出下一步建议。"

        agent = None
        provider_key = provider or "openai"
        resolved_model = model
        cid = conversation_id or ""
        if cid and cid in self._sessions:
            agent = self._sessions[cid]
            provider_key = getattr(agent, "provider", provider_key)
            resolved_model = getattr(agent, "model_name", resolved_model)
        else:
            try:
                agent, provider_key, resolved_model = self._create_agent(provider, model)
            except Exception as exc:
                return {"status": "error", "message": str(exc)}
            cid = cid or uuid.uuid4().hex
            self._sessions[cid] = agent
            setattr(agent, "provider", provider_key)
            setattr(agent, "model_name", resolved_model)

        try:
            prompt_text = clean_message
            if processing_result is not None:
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
            reply = agent.chat(prompt_text)
        except Exception as exc:
            return {"status": "error", "message": f"Agent 调用失败: {exc}"}

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
        append_message(cid, "agent", reply or "", metadata={**meta, "message_type": "agent_reply"})
        conversation = get_conversation(cid)
        return {
            "status": "success",
            "conversation_id": cid,
            "provider": provider_key,
            "model": resolved_model,
            "agent_reply": reply,
            "processing_result": processing_result,
            "attachments": attachments or [],
            "messages": conversation.get("messages", []) if conversation else [],
            "conversation": conversation,
        }
