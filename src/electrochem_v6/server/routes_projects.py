"""Projects route helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from electrochem_v6.store.projects import (
    create_project as _create_project,
)
from electrochem_v6.store.projects import (
    delete_project as _delete_project,
)
from electrochem_v6.store.projects import (
    get_lsv_summary as _get_lsv_summary,
)
from electrochem_v6.store.projects import (
    list_projects as _list_projects,
)
from electrochem_v6.store.projects import (
    update_project as _update_project,
)


def list_projects(status: str = "active") -> Dict[str, Any]:
    return _list_projects(status=status)


def create_project(
    name: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    color: Optional[str] = None,
) -> Dict[str, Any]:
    return _create_project(name=name, description=description, tags=tags, color=color)


def delete_project(project_id: str) -> Dict[str, Any]:
    return _delete_project(project_id=project_id)


def update_project(
    project_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    color: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    return _update_project(
        project_id=project_id,
        name=name,
        description=description,
        tags=tags,
        color=color,
        status=status,
    )


def get_lsv_summary(project_id: str, page: int = 1, page_size: int = 15, sort_by: str = "eta") -> Dict[str, Any]:
    return _get_lsv_summary(project_id=project_id, page=page, page_size=page_size, sort_by=sort_by)
