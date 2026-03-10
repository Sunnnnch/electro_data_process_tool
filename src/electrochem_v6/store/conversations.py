"""Conversation store adapter for v6."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .legacy_runtime import get_conversation_manager_v6


def list_conversations(
    page: int = 1,
    page_size: int = 20,
    filters: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    conv_mgr = get_conversation_manager_v6()
    return conv_mgr.list_conversations(page=page, page_size=page_size, filters=filters or {})


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    conv_mgr = get_conversation_manager_v6()
    return conv_mgr.get_conversation(conversation_id)


def delete_conversation(conversation_id: str) -> bool:
    conv_mgr = get_conversation_manager_v6()
    return conv_mgr.delete_conversation(conversation_id)


def rename_conversation(conversation_id: str, title: str) -> bool:
    conv_mgr = get_conversation_manager_v6()
    return conv_mgr.rename_conversation(conversation_id, title)


def append_message(
    conversation_id: Optional[str],
    role: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
    attachments: Optional[list[Dict[str, Any]]] = None,
) -> str:
    conv_mgr = get_conversation_manager_v6()
    return conv_mgr.append_message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        metadata=metadata,
        attachments=attachments,
    )
