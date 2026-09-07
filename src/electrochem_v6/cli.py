"""Small CLI metadata helpers for ElectroChem V6."""

from __future__ import annotations

from typing import Any, Dict

from .config import APP_NAME


def cli_info() -> Dict[str, Any]:
    return {"status": "ok", "message": f"ElectroChem — {APP_NAME}: CLI entry points are available"}
