"""User-facing error helpers for LLM calls."""

from __future__ import annotations

from typing import Any

from electrochem_v6.core.logging_policy import sanitize_for_log


def sanitize_llm_error(error: Any) -> str:
    """Return an LLM error string safe to show in UI and store in history."""
    text = sanitize_for_log(str(error or ""))
    return str(text or "LLM 调用失败")


__all__ = ["sanitize_llm_error"]
