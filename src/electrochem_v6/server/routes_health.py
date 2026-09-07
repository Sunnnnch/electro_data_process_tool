"""Health route helpers for the local HTTP server."""

from __future__ import annotations

from typing import Any, Dict

from electrochem_v6.config import APP_VERSION


def get_health() -> Dict[str, Any]:
    return {"status": "ok", "version": APP_VERSION}
