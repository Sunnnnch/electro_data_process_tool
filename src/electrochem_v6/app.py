"""Top-level application checks for ElectroChem V6."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict

from .config import ACTIVATION_REQUIRED, APP_NAME, APP_VERSION
from .core.processing_module_runtime import get_processing_module_registry
from .server import get_health


def _check_activation_gate_refs() -> Dict[str, Any]:
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


def _check_processing_runtime() -> Dict[str, Any]:
    expected = {"LSV", "CV", "EIS", "ECSA", "COUPLED"}
    try:
        registry = get_processing_module_registry()
        supported = set(registry.supported_data_types())
        runnable = {key for key in supported if registry.get_module(key) is not None}
        missing = sorted(expected - runnable)
        return {
            "ok": not missing,
            "supported_data_types": sorted(supported),
            "runnable_data_types": sorted(runnable),
            "missing_data_types": missing,
        }
    except Exception as exc:  # pragma: no cover
        return {
            "ok": False,
            "supported_data_types": [],
            "runnable_data_types": [],
            "missing_data_types": sorted(expected),
            "error": str(exc),
        }


def run_check() -> Dict[str, Any]:
    processing_runtime = _check_processing_runtime()
    activation_gate = _check_activation_gate_refs()
    return {
        "ok": bool(processing_runtime.get("ok")) and bool(activation_gate.get("ok")),
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "activation_required": ACTIVATION_REQUIRED,
        "workspace": str(Path.cwd()),
        "processing_runtime": processing_runtime,
        "activation_gate_scan": activation_gate,
        "health_route": get_health(),
    }
