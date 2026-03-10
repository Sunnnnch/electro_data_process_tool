"""Health route placeholder."""

from __future__ import annotations

from typing import Dict, Any

from electrochem_v6.config import APP_VERSION


def get_health() -> Dict[str, Any]:
    return {"status": "ok", "version": APP_VERSION}
