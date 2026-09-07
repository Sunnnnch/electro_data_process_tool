"""Archive boundaries captured only after the processing service validates paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

RUN_ARCHIVE_ROOTS_PREFIX = "run_archive_roots:"


def register_run_archive_roots(
    run_id: str, *, input_root: str, input_roots: Iterable[str], output_root: str,
) -> None:
    from .runtime import get_database

    roots = {
        "input_root": str(Path(input_root).resolve()),
        "input_roots": list(dict.fromkeys(str(Path(path).resolve()) for path in input_roots)),
        "output_root": str(Path(output_root).resolve()),
    }
    with get_database().transaction() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (RUN_ARCHIVE_ROOTS_PREFIX + run_id, json.dumps(roots)),
        )


def discard_unused_run_archive_roots(run_id: str) -> None:
    from .runtime import get_database

    with get_database().transaction() as connection:
        connection.execute(
            "DELETE FROM meta WHERE key=? AND NOT EXISTS "
            "(SELECT 1 FROM history_records WHERE run_id=?)",
            (RUN_ARCHIVE_ROOTS_PREFIX + run_id, run_id),
        )
