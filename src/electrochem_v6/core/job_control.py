"""Cooperative progress and cancellation helpers for processing jobs."""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator, Mapping
from typing import Any, TypeVar

T = TypeVar("T")

NON_CANCELLABLE_PROGRESS_PREFIX = "__electrochem_commit__:"


class ProcessingCancelledError(RuntimeError):
    """Raised at a safe work-unit boundary after cancellation is requested."""


def check_cancelled(params: Mapping[str, Any]) -> None:
    callback = params.get("_cancel_check")
    if callable(callback) and bool(callback()):
        raise ProcessingCancelledError("processing job was cancelled")


def report_progress(
    params: Mapping[str, Any],
    *,
    current: int | None = None,
    total: int | None = None,
    item: Any = None,
    advance: bool = False,
) -> None:
    state = params.get("_progress_state")
    if not isinstance(state, dict):
        state = {"current": 0, "total": max(0, int(total or 0))}
        if isinstance(params, dict):
            params["_progress_state"] = state
    if total is not None:
        state["total"] = max(0, int(total))
    if current is not None:
        state["current"] = max(0, int(current))
    if advance:
        state["current"] = max(0, int(state.get("current") or 0) + 1)
    callback = params.get("_progress_callback")
    if callable(callback):
        label = os.path.basename(str(item)) if item not in (None, "") else None
        callback(
            int(state.get("current") or 0),
            int(state.get("total") or 0),
            label,
        )


def progress_work_items(params: Mapping[str, Any], items: Iterable[T]) -> Iterator[T]:
    """Yield work items while checking cancellation and reporting completion."""

    for item in items:
        check_cancelled(params)
        report_progress(params, item=item)
        try:
            yield item
        finally:
            report_progress(params, item=item, advance=True)


__all__ = [
    "NON_CANCELLABLE_PROGRESS_PREFIX",
    "ProcessingCancelledError",
    "check_cancelled",
    "progress_work_items",
    "report_progress",
]
