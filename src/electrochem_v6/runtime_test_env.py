"""Temporary runtime-data isolation for smoke and stress checks."""

from __future__ import annotations

import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def _close_runtime_log_handlers(root: str) -> None:
    """Release Windows file handles opened below a temporary runtime root."""
    root_path = Path(root).resolve()
    logger_items = [logging.getLogger()]
    logger_items.extend(
        item
        for item in logging.Logger.manager.loggerDict.values()
        if isinstance(item, logging.Logger)
    )
    for logger in logger_items:
        for handler in list(logger.handlers):
            filename = getattr(handler, "baseFilename", None)
            if not filename:
                continue
            try:
                is_temporary = Path(filename).resolve().is_relative_to(root_path)
            except (OSError, ValueError):
                is_temporary = False
            if not is_temporary:
                continue
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    try:
        from electrochem_v6.core import processing_core_v6

        processing_core_v6._logger = None
    except Exception:
        pass
    try:
        from electrochem_v6.core import logging_policy

        logging_policy._LOGGER_CACHE.clear()
    except Exception:
        pass


@contextmanager
def isolated_data_env(*, prefix: str = "v6_check_env_") -> Iterator[dict[str, object]]:
    """Redirect every mutable runtime file to a disposable directory."""
    with tempfile.TemporaryDirectory(prefix=prefix) as root:
        mapping = {
            "ELECTROCHEM_V6_DATA_DIR": root,
            "ELECTROCHEM_V6_PROJECTS_FILE": os.path.join(root, "projects.json"),
            "ELECTROCHEM_V6_HISTORY_FILE": os.path.join(root, "processing_history.json"),
            "ELECTROCHEM_V6_CONVERSATION_FILE": os.path.join(root, "conversation_history.json"),
            "ELECTROCHEM_V6_TEMPLATE_FILE": os.path.join(root, "process_templates.json"),
            "ELECTROCHEM_V6_QUALITY_REPORT_FILE": os.path.join(root, "latest_quality_report.json"),
            "ELECTROCHEM_V6_LLM_CONFIG_FILE": os.path.join(root, "llm_config.json"),
            "ELECTROCHEM_V6_LOG_FILE": os.path.join(root, "logs", "v6_server.log"),
        }
        previous = {key: os.environ.get(key) for key in mapping}
        try:
            os.environ.update(mapping)
            yield {"root": root, "paths": mapping}
        finally:
            try:
                from electrochem_v6.store.runtime import reset_runtime

                reset_runtime()
            except Exception:
                pass
            _close_runtime_log_handlers(root)
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


__all__ = ["isolated_data_env"]
