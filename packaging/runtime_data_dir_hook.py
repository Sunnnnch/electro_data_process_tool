"""Runtime hook to force portable data paths for packaged builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _configure_portable_data_dir() -> None:
    if os.environ.get("ELECTROCHEM_V6_DATA_DIR"):
        return
    root = Path(sys.executable).resolve().parent
    data_dir = root / "user_data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception:
        return

    os.environ.setdefault("ELECTROCHEM_V6_DATA_DIR", str(data_dir))
    os.environ.setdefault("ELECTROCHEM_V6_PROJECTS_FILE", str(data_dir / "projects.json"))
    os.environ.setdefault("ELECTROCHEM_V6_HISTORY_FILE", str(data_dir / "processing_history.json"))
    os.environ.setdefault("ELECTROCHEM_V6_CONVERSATION_FILE", str(data_dir / "conversation_history.json"))
    os.environ.setdefault("ELECTROCHEM_V6_TEMPLATE_FILE", str(data_dir / "process_templates.json"))
    os.environ.setdefault("ELECTROCHEM_V6_QUALITY_REPORT_FILE", str(data_dir / "latest_quality_report.json"))
    os.environ.setdefault("ELECTROCHEM_V6_LOG_FILE", str(data_dir / "logs" / "v6_server.log"))
    os.environ.setdefault("ELECTROCHEM_V6_LLM_CONFIG_FILE", str(data_dir / "llm_config.json"))


_configure_portable_data_dir()
