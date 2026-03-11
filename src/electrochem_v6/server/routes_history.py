"""History route helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from electrochem_v6.store.history import (
    archive_history_record as _archive_history_record,
)
from electrochem_v6.store.history import (
    delete_history_record as _delete_history_record,
)
from electrochem_v6.store.history import (
    get_stats as _get_stats,
)
from electrochem_v6.store.history import (
    list_history as _list_history,
)


def list_history(project_id: Optional[str] = None, limit: int = 100, include_archived: bool = False) -> Dict[str, Any]:
    return _list_history(project_id=project_id, limit=limit, include_archived=include_archived)


def get_stats(project_id: Optional[str] = None, include_archived: bool = False) -> Dict[str, Any]:
    return _get_stats(project_id=project_id, include_archived=include_archived)


def archive_history_record(history_key: str) -> Dict[str, Any]:
    return _archive_history_record(history_key)


def delete_history_record(history_key: str) -> Dict[str, Any]:
    return _delete_history_record(history_key)
