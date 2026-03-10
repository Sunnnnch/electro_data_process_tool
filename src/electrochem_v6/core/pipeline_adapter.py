"""Runtime check helpers for the internal v6 processing pipeline."""

from __future__ import annotations

from typing import Any, Dict


def check_v5_pipeline_bridge() -> Dict[str, Any]:
    try:
        from electrochem_v6.core import processing_core_v6 as processing_core  # type: ignore

        has_run_pipeline = hasattr(processing_core, "run_pipeline")
        return {
            "ok": bool(has_run_pipeline),
            "repo_root": str(processing_core.__file__),
            "target_module": "processing_core_v6",
            "run_pipeline_found": bool(has_run_pipeline),
        }
    except Exception as exc:  # pragma: no cover
        return {
            "ok": False,
            "repo_root": "",
            "target_module": "processing_core_v6",
            "error": str(exc),
        }
