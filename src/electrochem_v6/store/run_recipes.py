"""Durable, versioned processing recipes independent of job retention and output files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._json_utils import to_json_safe
from .runtime import get_database

_PREFIX = "run_recipe:"


def get_run_recipe(run_id: str) -> dict[str, Any] | None:
    with get_database().read() as connection:
        row = connection.execute("SELECT value FROM meta WHERE key=?", (_PREFIX + str(run_id),)).fetchone()
    if row is None:
        return None
    value = json.loads(row["value"])
    return value if isinstance(value, dict) else None


def save_run_recipe(recipe: dict[str, Any]) -> None:
    run_id = str(recipe.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("运行配方缺少 run_id")
    with get_database().transaction() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (_PREFIX + run_id, json.dumps(to_json_safe(recipe), ensure_ascii=False, allow_nan=False)),
        )


def update_run_recipe(run_id: str, **updates: Any) -> dict[str, Any] | None:
    with get_database().transaction() as connection:
        row = connection.execute("SELECT value FROM meta WHERE key=?", (_PREFIX + str(run_id),)).fetchone()
        if row is None:
            return None
        recipe = json.loads(row["value"])
        recipe.update(to_json_safe(updates))
        connection.execute(
            "UPDATE meta SET value=? WHERE key=?",
            (json.dumps(recipe, ensure_ascii=False, allow_nan=False), _PREFIX + str(run_id)),
        )
    return recipe


def list_run_recipes_page(project_id: str | None = None, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    with get_database().read() as connection:
        rows = connection.execute("SELECT value FROM meta WHERE key LIKE ?", (_PREFIX + "%",)).fetchall()
    recipes = [json.loads(row["value"]) for row in rows]
    recipes = [item for item in recipes if isinstance(item, dict) and (project_id is None or item.get("project_id") == project_id)]
    recipes.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    keys = (
        "run_id", "project_id", "data_types", "created_at", "finished_at", "status",
        "parent_run_id", "parent_record_key", "app_version", "formula_schema_version",
        "record_keys", "source_integrity", "error", "output_dir",
        "history_partially_deleted", "deleted_record_keys",
    )
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), 500))
    selected = recipes[offset:offset + limit]
    runs = [{**{key: item.get(key) for key in keys}, "input_count": len(item.get("inputs") or [])} for item in selected]
    has_more = offset + len(selected) < len(recipes)
    return {"runs": runs, "total": len(recipes), "has_more": has_more, "next_offset": offset + len(selected) if has_more else None}


def list_run_recipes(project_id: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
    return list_run_recipes_page(project_id, limit=limit)["runs"]


def attach_run_upload_source(run_id: str, *, source_archive_path: str, source_archive_sha256: str, artifact_root: str) -> None:
    recipe = get_run_recipe(run_id)
    if recipe is None:
        return
    root = Path(recipe["folder_path"]).resolve()
    inputs = []
    for item in recipe.get("inputs") or []:
        item = dict(item)
        try:
            item["archive_member"] = Path(item["path"]).resolve().relative_to(root).as_posix()
        except ValueError:
            # Auxiliary files outside the uploaded tree retain their external identity.
            pass
        inputs.append(item)
    update_run_recipe(run_id, inputs=inputs, source_archive_path=source_archive_path,
                      source_archive_sha256=source_archive_sha256, artifact_root=artifact_root)
