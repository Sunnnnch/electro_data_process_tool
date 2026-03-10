"""Top-level app helpers for v6 refactor."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict

from .config import APP_NAME, APP_VERSION, ENABLE_LICENSE
from .core.pipeline_adapter import check_v5_pipeline_bridge
from .server import get_health


def _check_no_license_refs() -> Dict[str, Any]:
    package_root = Path(__file__).resolve().parent
    hits = []
    for py_file in package_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name or ""
                    if "license" in name.lower():
                        hits.append({"file": str(py_file), "import": name})
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "license" in module.lower():
                    hits.append({"file": str(py_file), "import_from": module})
    return {"ok": len(hits) == 0, "hits": hits}


def run_check() -> Dict[str, Any]:
    bridge = check_v5_pipeline_bridge()
    no_license = _check_no_license_refs()
    return {
        "ok": bool(bridge.get("ok")) and bool(no_license.get("ok")),
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "license_enabled": ENABLE_LICENSE,
        "workspace": str(Path.cwd()),
        "bridge": bridge,
        "no_license_scan": no_license,
        "health_route": get_health(),
    }
