"""Per-request context exposed to agent tools without global state leakage."""

from __future__ import annotations

from contextvars import ContextVar, Token
from copy import deepcopy
from typing import Any, Dict, Optional

_PROFESSIONAL_MODE_CONTEXT: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "electrochem_professional_mode_context",
    default=None,
)
_PENDING_MUTATIONS: ContextVar[Optional[list[Dict[str, Any]]]] = ContextVar(
    "electrochem_pending_agent_mutations",
    default=None,
)


def set_professional_mode_context(context: Optional[Dict[str, Any]]) -> Token:
    safe = deepcopy(context) if isinstance(context, dict) else None
    return _PROFESSIONAL_MODE_CONTEXT.set(safe)


def reset_professional_mode_context(token: Token) -> None:
    _PROFESSIONAL_MODE_CONTEXT.reset(token)


def start_pending_mutation_collection() -> Token:
    return _PENDING_MUTATIONS.set([])


def reset_pending_mutation_collection(token: Token) -> None:
    _PENDING_MUTATIONS.reset(token)


def register_pending_mutation(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    pending = _PENDING_MUTATIONS.get()
    item = {
        "tool_name": str(tool_name or "").strip(),
        "arguments": deepcopy(arguments) if isinstance(arguments, dict) else {},
    }
    if isinstance(pending, list):
        pending.append(item)
    return {
        "success": False,
        "status": "confirmation_required",
        "confirmation_required": True,
        "tool_name": item["tool_name"],
        "message": "该操作会修改项目或生成处理结果，必须由用户确认后执行。",
    }


def get_pending_mutations() -> list[Dict[str, Any]]:
    pending = _PENDING_MUTATIONS.get()
    return deepcopy(pending) if isinstance(pending, list) else []


def tool_get_professional_mode_context() -> Dict[str, Any]:
    """Return the current UI summary only when the model explicitly asks for it."""

    context = _PROFESSIONAL_MODE_CONTEXT.get()
    if not isinstance(context, dict) or not context:
        return {
            "success": False,
            "available": False,
            "error": "当前请求没有可用的数据处理上下文",
        }
    return {
        "success": True,
        "available": True,
        "context": deepcopy(context),
    }


__all__ = [
    "reset_professional_mode_context",
    "get_pending_mutations",
    "register_pending_mutation",
    "reset_pending_mutation_collection",
    "set_professional_mode_context",
    "start_pending_mutation_collection",
    "tool_get_professional_mode_context",
]
