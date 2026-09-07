"""Authenticated identity probe for local MCP service discovery."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlsplit

from electrochem_v6.config import APP_VERSION


def dispatch_mcp_get(handler: Any, manager: Any) -> bool:
    if urlsplit(handler.path).path.rstrip("/") != "/api/v1/mcp/status":
        return False
    supplied = str(handler.headers.get("X-Electrochem-Session") or "")
    if not manager or not supplied or not secrets.compare_digest(supplied.encode("utf-8"), manager.session_token.encode("utf-8")):
        handler._send_json(403, {"status": "error", "message": "Local MCP session authentication required"})
        return True
    handler._send_json(200, {"status": "success", "name": "electrochem-v6-api", "version": APP_VERSION,
                             "closing": manager.desktop_is_closing()})
    return True
