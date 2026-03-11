"""Structured logging policy with sensitive-data masking for v6."""

from __future__ import annotations

import json
import logging
import os
import re
from logging.handlers import RotatingFileHandler
from typing import Any

from electrochem_v6.config import ensure_parent_dir, get_log_file

_LOGGER_CACHE: dict[str, logging.Logger] = {}
_MAX_DEPTH = 8
_MAX_TEXT = 400
_MASK = "***"
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "secret",
    "password",
    "cookie",
    "set-cookie",
    "x-api-key",
}
_RE_BEARER = re.compile(r"(?i)\b(bearer)\s+([a-z0-9._\-]+)")
_RE_SK = re.compile(r"\b(sk-[a-z0-9_\-]{10,})\b", flags=re.IGNORECASE)


def _mask_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return text
    if len(text) <= 6:
        return _MASK
    return f"{text[:3]}{_MASK}{text[-2:]}"


def _redact_text(text: str) -> str:
    if not text:
        return text
    text = _RE_BEARER.sub(lambda m: f"{m.group(1)} {_mask_secret(m.group(2))}", text)
    text = _RE_SK.sub(lambda m: _mask_secret(m.group(1)), text)
    if len(text) > _MAX_TEXT:
        return f"{text[:_MAX_TEXT]}...(truncated)"
    return text


def _is_sensitive_key(key: str) -> bool:
    key_l = str(key or "").strip().lower()
    if key_l in _SENSITIVE_KEYS:
        return True
    return any(x in key_l for x in ("secret", "token", "password", "api_key", "authorization"))


def sanitize_for_log(value: Any, *, key: str | None = None, _depth: int = 0) -> Any:
    """Recursively sanitize payload for safe logging."""
    if _depth >= _MAX_DEPTH:
        return "...(max_depth)"

    if key and _is_sensitive_key(key):
        return _mask_secret(str(value))

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out[str(k)] = sanitize_for_log(v, key=str(k), _depth=_depth + 1)
        return out

    if isinstance(value, (list, tuple, set)):
        return [sanitize_for_log(v, _depth=_depth + 1) for v in value]

    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"

    if isinstance(value, str):
        return _redact_text(value)

    return value


def summarize_payload(payload: Any) -> dict[str, Any]:
    """Create a compact, low-risk summary for routine request/response logs."""
    if isinstance(payload, dict):
        out: dict[str, Any] = {"keys": sorted(payload.keys())[:40]}
        if "status" in payload:
            out["status"] = payload.get("status")
        if "message" in payload:
            out["message"] = _redact_text(str(payload.get("message")))
        return sanitize_for_log(out)
    if isinstance(payload, list):
        return {"type": "list", "size": len(payload)}
    if payload is None:
        return {"type": "none"}
    return {"type": type(payload).__name__}


def get_v6_logger(name: str = "electrochem_v6") -> logging.Logger:
    if name in _LOGGER_CACHE:
        return _LOGGER_CACHE[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        path = ensure_parent_dir(get_log_file())
        handler = RotatingFileHandler(
            filename=str(path),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    _LOGGER_CACHE[name] = logger
    return logger


def log_event(logger: logging.Logger, event: str, payload: Any = None, *, level: int = logging.INFO) -> None:
    """Log a structured, sanitized event."""
    try:
        include_payload = str(os.environ.get("ELECTROCHEM_V6_LOG_INCLUDE_PAYLOAD", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        content = sanitize_for_log(payload) if include_payload else summarize_payload(payload)
        line = json.dumps({"event": event, "payload": content}, ensure_ascii=False, default=str)
        logger.log(level, line)
    except Exception:
        # Logging must never break main request flow.
        pass

