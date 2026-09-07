"""History store adapter for v6."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterator, Optional, Sequence

from .runtime import get_database

__all__ = [
    "list_history",
    "list_history_page",
    "get_history_detail",
    "iter_project_archive_records",
    "get_stats",
    "archive_history_record",
    "delete_history_record",
    "build_project_report",
    "attach_run_outputs",
    "attach_run_provenance",
]


def list_history(
    project_id: Optional[str] = None,
    limit: Optional[int] = 100,
    include_archived: bool = False,
    metric_key: Optional[str] = None,
    metric_min: Optional[float] = None,
    metric_max: Optional[float] = None,
    data_type: Optional[str] = None,
    q: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    filters = {key: value for key, value in (("q", q), ("date_from", date_from), ("date_to", date_to)) if value is not None}
    try:
        records = get_database().filter_history(
            project_id=project_id,
            include_archived=include_archived,
            data_type=data_type,
            metric_key=metric_key,
            metric_min=metric_min,
            metric_max=metric_max,
            limit=limit,
            **filters,
        )
    except ValueError as exc:
        return {"status": "error", "message": str(exc), "records": []}
    return {"status": "success", "records": records}


def list_history_page(
    project_id: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
    include_archived: bool = False,
    metric_key: Optional[str] = None,
    metric_min: Optional[float] = None,
    metric_max: Optional[float] = None,
    data_type: Optional[str] = None,
    q: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    filters = {key: value for key, value in (("q", q), ("date_from", date_from), ("date_to", date_to)) if value is not None}
    try:
        page = get_database().filter_history_page(
            project_id=project_id,
            include_archived=include_archived,
            data_type=data_type,
            metric_key=metric_key,
            metric_min=metric_min,
            metric_max=metric_max,
            limit=limit,
            cursor=cursor,
            **filters,
        )
    except ValueError as exc:
        return {"status": "error", "message": str(exc), "records": []}
    return {"status": "success", **page}


def get_history_detail(record_key: str) -> Dict[str, Any]:
    safe_key = str(record_key or "").strip()
    if not safe_key:
        return {"status": "error", "message": "missing history key"}
    record = get_database().get_history_record(safe_key)
    if record is None:
        return {"status": "error", "message": "history record not found"}
    return {"status": "success", "record": record}


def iter_project_archive_records(
    project_id: str,
    *,
    include_archived: bool = False,
) -> Iterator[Dict[str, Any]]:
    return get_database().iter_history_archive_records(
        project_id=str(project_id),
        include_archived=include_archived,
    )


def get_stats(project_id: Optional[str] = None, include_archived: bool = False) -> Dict[str, Any]:
    stats = get_database().get_history_stats(
        project_id=project_id,
        include_archived=include_archived,
    )
    return {"status": "success", "data": stats}


def _update_history_records(*, match_key: str, action: str) -> Dict[str, Any]:
    safe_key = str(match_key or "").strip()
    if not safe_key:
        return {"status": "error", "message": "missing history key", "updated": 0}

    updated = get_database().update_history_by_key(safe_key, action)
    if updated == 0:
        return {"status": "error", "message": "history record not found", "updated": 0}
    return {"status": "success", "updated": updated, "action": action}


def archive_history_record(history_key: str) -> Dict[str, Any]:
    return _update_history_records(match_key=history_key, action="archive")


def delete_history_record(history_key: str, *, delete_artifacts: bool = False) -> Dict[str, Any]:
    safe_key = str(history_key or "").strip()
    record = get_database().get_history_record(safe_key) if safe_key and delete_artifacts else None
    result = _update_history_records(match_key=safe_key, action="delete")
    cleanup = {"removed": [], "skipped": [], "bytes_reclaimed": 0}
    if (
        result.get("status") == "success"
        and delete_artifacts
        and record
        and record.get("artifact_owner") == "application"
        and record.get("artifact_root")
    ):
        from electrochem_v6.core.storage_service import remove_managed_artifact_roots

        cleanup = remove_managed_artifact_roots([str(record["artifact_root"])])
    if delete_artifacts:
        result["artifact_cleanup"] = cleanup
    return result


def build_project_report(
    project_id: str,
    include_archived: bool = False,
    *,
    run_ids: Optional[Sequence[str]] = None,
    record_keys: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    safe_project_id = str(project_id or "").strip()
    if not safe_project_id:
        return {"status": "error", "message": "missing project id"}
    if run_ids is not None and record_keys is not None:
        return {"status": "error", "message": "select run_ids or record_keys, not both"}
    for name, values in (("run_ids", run_ids), ("record_keys", record_keys)):
        if values is not None and (
            not isinstance(values, (list, tuple)) or not values
            or any(not isinstance(item, str) or not item.strip() for item in values)
        ):
            return {"status": "error", "message": f"{name} must be a non-empty list of identifiers"}
    # None is the public database contract for an unlimited query. A report
    # must never silently inherit list-page limits or a 'recent 20' slice.
    records_resp = list_history(project_id=safe_project_id, limit=None, include_archived=include_archived)
    stats_resp = get_stats(project_id=safe_project_id, include_archived=include_archived)
    records = records_resp.get("records") or []
    stats = stats_resp.get("data") or {}
    requested_runs = list(dict.fromkeys(str(item).strip() for item in run_ids or []))
    requested_keys = list(dict.fromkeys(str(item).strip() for item in record_keys or []))
    available_count = len(records)
    # Runs are durable independently of history. In particular COUPLED runs
    # have normalized FE results even when no history row was produced.
    from .run_recipes import get_run_recipe, list_run_recipes_page

    recipe_summaries = []
    offset = 0
    while True:
        page = list_run_recipes_page(safe_project_id, limit=500, offset=offset)
        recipe_summaries.extend(page.get("runs") or [])
        if not page.get("has_more"):
            break
        next_offset = page.get("next_offset")
        if not isinstance(next_offset, int) or next_offset <= offset:
            return {"status": "error", "message": "run pagination did not advance; report scope cannot be verified"}
        offset = next_offset
    recipe_ids = {str(item.get("run_id") or "") for item in recipe_summaries}
    partially_deleted_runs = {str(item.get("run_id") or "") for item in recipe_summaries if item.get("history_partially_deleted")}
    archived_runs: set[str] = set()
    if not include_archived:
        all_records = list_history(project_id=safe_project_id, limit=None, include_archived=True).get("records") or []
        visible_keys = {str(item.get("record_key") or "") for item in records}
        archived_runs = {
            str(item["run_id"]) for item in all_records
            if item.get("run_id") and str(item.get("record_key") or "") not in visible_keys
        }
    if requested_runs or requested_keys:
        field, requested = ("run_id", requested_runs) if requested_runs else ("record_key", requested_keys)
        available = {str(item.get(field) or "") for item in records}
        if requested_runs:
            available.update(recipe_ids - archived_runs - partially_deleted_runs)
            deleted_selection = sorted(set(requested_runs) & partially_deleted_runs)
            if deleted_selection:
                return {"status": "error", "message": "selected runs have partially deleted history; select remaining record_keys to export", "missing_ids": deleted_selection}
            archived_selection = sorted(set(requested_runs) & archived_runs)
            if archived_selection:
                return {"status": "error", "message": "selected runs contain archived history; include_archived is required for a complete run report", "missing_ids": archived_selection}
        missing = [item for item in requested if item not in available]
        if missing:
            return {
                "status": "error", "message": "selected report items are missing, archived, or outside this project",
                "missing_ids": missing,
            }
        selected = set(requested)
        records = [item for item in records if str(item.get(field) or "") in selected]
        stats = {"total": len(records), "total_files": len(records)}
        for data_type in ("LSV", "CV", "EIS", "ECSA", "COUPLED"):
            stats[f"{data_type.lower()}_count"] = sum(str(item.get("type") or "").upper() == data_type for item in records)
    actual_runs = list(dict.fromkeys(str(item["run_id"]) for item in records if item.get("run_id")))
    selected_recipe_ids = [] if requested_keys else (
        requested_runs if requested_runs else [str(item.get("run_id")) for item in recipe_summaries if str(item.get("run_id")) not in archived_runs | partially_deleted_runs]
    )
    recipes = []
    for run_id in selected_recipe_ids:
        if run_id not in recipe_ids:
            continue  # Legacy history still reports its unavailable recipe.
        recipe = get_run_recipe(run_id)
        if not recipe or recipe.get("project_id") != safe_project_id:
            return {"status": "error", "message": "run scope changed while building report; retry export"}
        if recipe.get("history_partially_deleted"):
            return {"status": "error", "message": "run history changed while building report; select remaining record_keys to export"}
        recipes.append(recipe)
        if run_id not in actual_runs:
            actual_runs.append(run_id)
    normalized_count = sum(len((item.get("manifest") or {}).get("processing_results") or []) for item in recipes)
    scope = {
        "mode": "run_ids" if requested_runs else "record_keys" if requested_keys else "project",
        "project_id": safe_project_id,
        "include_archived": bool(include_archived),
        "requested_run_ids": requested_runs,
        "requested_record_keys": requested_keys,
        "record_keys": [str(item.get("record_key") or "") for item in records],
        "run_ids": actual_runs,
        "record_count": len(records), "run_count": len(actual_runs),
        "records_without_run_id": sum(not item.get("run_id") for item in records),
        "available_record_count": available_count,
        "available_run_count": len(recipe_ids | {str(item.get("run_id")) for item in (records_resp.get("records") or []) if item.get("run_id")}),
        "normalized_result_count": normalized_count,
        "excluded_archived_run_ids": sorted(archived_runs) if not requested_keys else [],
        "excluded_partially_deleted_run_ids": sorted(partially_deleted_runs) if not requested_keys else [],
        "run_result_scope": "selected_runs_complete" if requested_runs else "selected_history_only" if requested_keys else "all_unarchived_runs_and_visible_history",
        "truncated": False,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
    }
    report = {
        "project_id": safe_project_id,
        "generated_at": records[0].get("timestamp") if records else "",
        "include_archived": include_archived,
        "stats": stats,
        "scope": scope,
        "records": records,
        "recent_records": records,
        "runs": recipes,
    }
    return {"status": "success", "report": report}


def attach_run_outputs(
    *,
    run_id: str,
    output_files: list[str],
    summary_path: Optional[str] = None,
    quality_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    safe_run_id = str(run_id or "").strip()
    if not safe_run_id:
        return {"status": "error", "message": "missing run id", "updated": 0}
    safe_output_files = [str(item).strip() for item in output_files if str(item).strip()]

    updated = get_database().attach_run_outputs(
        run_id=safe_run_id,
        output_files=safe_output_files,
        summary_path=summary_path,
        quality_summary=quality_summary,
    )
    return {"status": "success", "updated": updated}


def attach_run_provenance(
    *,
    run_id: str,
    source_archive_path: Optional[str] = None,
    artifact_root: Optional[str] = None,
    artifact_owner: str = "application",
) -> Dict[str, Any]:
    safe_run_id = str(run_id or "").strip()
    if not safe_run_id:
        return {"status": "error", "message": "missing run id", "updated": 0}
    updated = get_database().attach_run_provenance(
        safe_run_id,
        source_archive_path=source_archive_path,
        artifact_root=artifact_root,
        artifact_owner=artifact_owner,
    )
    return {"status": "success", "updated": updated}
