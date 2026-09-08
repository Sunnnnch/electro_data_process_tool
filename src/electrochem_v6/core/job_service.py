"""Bounded background execution for long-running processing requests."""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Dict

from electrochem_v6.core.artifact_lifecycle import finish_uploaded_run
from electrochem_v6.core.job_control import (
    NON_CANCELLABLE_PROGRESS_PREFIX,
    ProcessingCancelledError,
)
from electrochem_v6.core.process_owner import current_process_owner
from electrochem_v6.core.process_service import process_folder
from electrochem_v6.store.job_recovery import finish_owned_job, register_owned_job, start_owned_job
from electrochem_v6.store.runtime import get_database


def _serialized_submission(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        # Closing admission must be atomic with registration and executor submission.
        with self._submission_lock:
            return method(self, *args, **kwargs)
    return guarded


class ProcessingJobManager:
    def __init__(
        self,
        *,
        max_workers: int | None = None,
        process_runner: Callable[[Dict[str, Any]], Dict[str, Any]] = process_folder,
        agent_runner: Callable[..., Dict[str, Any]] | None = None,
    ) -> None:
        configured = max_workers or int(os.environ.get("ELECTROCHEM_V6_JOB_WORKERS", "2"))
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, min(int(configured), 4)),
            thread_name_prefix="electrochem-job",
        )
        self._process_runner = process_runner
        self._agent_runner = agent_runner
        self._futures: dict[str, Future[Any]] = {}
        self._non_cancellable_jobs: set[str] = set()
        self._lock = threading.RLock()
        self._submission_lock = threading.RLock()
        self._closed = False
        from electrochem_v6.core.job_recovery_service import reconcile_interrupted_work

        self._owner = current_process_owner()
        reconcile_interrupted_work()

    @_serialized_submission
    def submit_process(self, payload: Dict[str, Any], *, recovery_source: str | None = None, recovery_origin: dict[str, Any] | None = None) -> Dict[str, Any]:
        if self._closed:
            raise RuntimeError("processing job manager is closed")
        job_id = uuid.uuid4().hex
        database = get_database()
        database.prune_processing_jobs(kind="process")
        from electrochem_v6.core.job_recovery_service import snapshot_queued_request

        registered = register_owned_job(job_id, kind="process", owner=self._owner,
                                       payload=snapshot_queued_request(payload), recovery_source=recovery_source,
                                       recovery_origin=recovery_origin)
        if not registered["created"]:
            existing_id = registered["job_id"]
            return database.get_processing_job(existing_id) or {"job_id": existing_id, "status": "queued"}
        try:
            database.create_processing_job(job_id, kind="process", payload=dict(payload))
            future = self._executor.submit(self._run_process, job_id, dict(payload))
        except Exception:
            finish_owned_job(job_id, failed_submission=True)
            database.update_processing_job(job_id, status="failed", error="unable to schedule processing", finished_at=datetime.now().isoformat())
            raise
        with self._lock:
            self._futures[job_id] = future
        future.add_done_callback(lambda done: self._finish_process_future(job_id, done))
        return database.get_processing_job(job_id) or {"job_id": job_id, "status": "queued"}

    @_serialized_submission
    def submit_agent(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self._closed:
            raise RuntimeError("processing job manager is closed")
        if self._agent_runner is None:
            raise RuntimeError("agent job runner is unavailable")
        job_id = uuid.uuid4().hex
        database = get_database()
        database.prune_processing_jobs(kind="agent")
        prepared = payload.get("_prepared_upload")
        if isinstance(prepared, dict):
            from electrochem_v6.core.job_recovery_service import snapshot_uploaded_request

            register_owned_job(job_id, kind="process", owner=self._owner, payload=snapshot_uploaded_request(prepared))
        else:
            register_owned_job(job_id, kind="agent", owner=self._owner, payload={})
        try:
            database.create_processing_job(job_id, kind="agent", payload=dict(payload))
            future = self._executor.submit(self._run_agent, job_id, dict(payload))
        except Exception:
            finish_owned_job(job_id)
            raise
        with self._lock:
            self._futures[job_id] = future
        future.add_done_callback(lambda done: self._finish_agent_future(job_id, payload, done))
        return database.get_processing_job(job_id) or {"job_id": job_id, "status": "queued"}

    def _finish_process_future(self, job_id: str, future: Future[Any]) -> None:
        if future.cancelled():
            get_database().update_processing_job(job_id, status="cancelled", error="cancelled before processing started",
                                                 finished_at=datetime.now().isoformat())
        self._discard_future(job_id)

    def _finish_agent_future(self, job_id: str, payload: Dict[str, Any], future: Future[Any]) -> None:
        try:
            if future.cancelled():
                get_database().update_processing_job(
                    job_id,
                    status="cancelled",
                    payload=self._agent_payload_summary(payload),
                    error="cancelled before AI request started",
                    finished_at=datetime.now().isoformat(),
                )
            prepared = payload.get("_prepared_upload")
            if isinstance(prepared, dict) and prepared.get("run_root"):
                # Queued cancellation never enters the upload runner's finally block.
                # Completed runners have already released this lease, making this a no-op.
                finish_uploaded_run(str(prepared["run_root"]))
        finally:
            self._discard_future(job_id)

    def _discard_future(self, job_id: str) -> None:
        try:
            database = get_database()
            job = database.get_processing_job(job_id)
            if job:
                if job.get("status") not in {"queued", "running", "interrupted"}:
                    finish_owned_job(job_id)
                database.prune_processing_jobs(kind=str(job.get("kind") or ""))
        finally:
            with self._lock:
                self._futures.pop(job_id, None)
                self._non_cancellable_jobs.discard(job_id)

    @staticmethod
    def _agent_payload_summary(
        payload: Dict[str, Any],
        result: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        result = result if isinstance(result, dict) else {}
        return {
            "conversation_id": result.get("conversation_id") or payload.get("conversation_id")
        }

    @staticmethod
    def _compact_agent_result(result: Any) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {"value": result}
        compact = dict(result)
        # The canonical messages live in conversation tables. Keeping another complete
        # snapshot in every job makes long conversations grow quadratically.
        for key in ("conversation", "messages"):
            compact.pop(key, None)
        return compact

    @staticmethod
    def _is_cancel_requested(job_id: str) -> bool:
        job = get_database().get_processing_job(job_id)
        return bool(job and job.get("cancel_requested"))

    @staticmethod
    def _update_progress(job_id: str, current: int, total: int, item: str | None) -> None:
        get_database().update_processing_job(
            job_id,
            progress_current=max(0, int(current)),
            progress_total=max(0, int(total)),
            current_item=item,
        )

    def _run_process(self, job_id: str, payload: Dict[str, Any]) -> None:
        database = get_database()
        start_owned_job(job_id)
        if self._is_cancel_requested(job_id):
            database.update_processing_job(
                job_id,
                status="cancelled",
                error="cancelled before processing started",
                finished_at=datetime.now().isoformat(),
            )
            return
        database.update_processing_job(
            job_id,
            status="running",
            started_at=datetime.now().isoformat(),
            current_item="preflight",
        )
        runtime_payload = dict(payload)
        runtime_payload["_job_id"] = job_id
        runtime_payload["_job_owner"] = dict(self._owner)
        runtime_payload["_cancel_check"] = lambda: self._is_cancel_requested(job_id)
        runtime_payload["_progress_callback"] = (
            lambda current, total, item: self._update_progress(job_id, current, total, item)
        )
        try:
            result = self._process_runner(runtime_payload)
            if self._is_cancel_requested(job_id):
                raise ProcessingCancelledError("processing job was cancelled")
            succeeded = isinstance(result, dict) and result.get("status") == "success"
            database.update_processing_job(
                job_id,
                status="succeeded" if succeeded else "failed",
                result=result if isinstance(result, dict) else {"value": result},
                error=None
                if succeeded
                else str(result.get("message") if isinstance(result, dict) else "processing failed"),
                finished_at=datetime.now().isoformat(),
            )
        except ProcessingCancelledError as exc:
            database.update_processing_job(
                job_id,
                status="cancelled",
                error=str(exc),
                finished_at=datetime.now().isoformat(),
            )
        except Exception as exc:
            database.update_processing_job(
                job_id,
                status="failed",
                error=str(exc),
                finished_at=datetime.now().isoformat(),
            )

    def _run_agent(self, job_id: str, payload: Dict[str, Any]) -> None:
        database = get_database()
        start_owned_job(job_id)
        if self._is_cancel_requested(job_id):
            database.update_processing_job(
                job_id,
                status="cancelled",
                payload=self._agent_payload_summary(payload),
                error="cancelled before AI request started",
                finished_at=datetime.now().isoformat(),
            )
            return
        database.update_processing_job(
            job_id,
            status="running",
            started_at=datetime.now().isoformat(),
            progress_current=0,
            progress_total=10,
            current_item="preparing AI request",
        )
        progress_step = 0

        def report(message: str) -> None:
            nonlocal progress_step
            text = str(message)
            if text.startswith(NON_CANCELLABLE_PROGRESS_PREFIX):
                text = text[len(NON_CANCELLABLE_PROGRESS_PREFIX) :].lstrip()
                with self._lock:
                    self._non_cancellable_jobs.add(job_id)
            progress_step = min(progress_step + 1, 10)
            self._update_progress(job_id, progress_step, 10, text)

        try:
            if self._agent_runner is None:
                raise RuntimeError("agent job runner is unavailable")
            runtime_payload = dict(payload)
            if isinstance(payload.get("_prepared_upload"), dict):
                runtime_payload["_prepared_upload"] = {**payload["_prepared_upload"], "_job_id": job_id, "_job_owner": self._owner}
            result = self._agent_runner(
                runtime_payload,
                progress_callback=report,
                cancel_check=lambda: self._is_cancel_requested(job_id),
            )
            write_action_started = bool(
                isinstance(result, dict) and result.get("write_action_started")
            )
            if self._is_cancel_requested(job_id) and not write_action_started:
                raise ProcessingCancelledError("AI request was cancelled")
            if self._is_cancel_requested(job_id) and write_action_started and isinstance(result, dict):
                result = dict(result)
                result["cancel_ignored_after_write_started"] = True
            succeeded = isinstance(result, dict) and result.get("status") == "success"
            compact_result = self._compact_agent_result(result)
            database.update_processing_job(
                job_id,
                status="succeeded" if succeeded else "failed",
                payload=self._agent_payload_summary(
                    payload,
                    result if isinstance(result, dict) else None,
                ),
                progress_current=10 if succeeded else progress_step,
                progress_total=10,
                current_item="complete" if succeeded else "failed",
                result=compact_result,
                error=None
                if succeeded
                else str(result.get("message") if isinstance(result, dict) else "AI request failed"),
                finished_at=datetime.now().isoformat(),
            )
        except ProcessingCancelledError as exc:
            database.update_processing_job(
                job_id,
                status="cancelled",
                payload=self._agent_payload_summary(payload),
                current_item="cancelled",
                error=str(exc),
                finished_at=datetime.now().isoformat(),
            )
        except Exception as exc:
            database.update_processing_job(
                job_id,
                status="failed",
                payload=self._agent_payload_summary(payload),
                current_item="failed",
                error=str(exc),
                finished_at=datetime.now().isoformat(),
            )

    def can_cancel(self, job_id: str) -> bool:
        with self._lock:
            future = self._futures.get(str(job_id))
            if future is None or future.done() or str(job_id) in self._non_cancellable_jobs:
                return False
        job = get_database().get_processing_job(job_id)
        return bool(job and job.get("status") in {"queued", "running"} and not job.get("cancel_requested"))

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            if str(job_id) in self._non_cancellable_jobs:
                return False
        requested = get_database().request_processing_job_cancel(job_id)
        with self._lock:
            future = self._futures.get(str(job_id))
        if requested and future is not None and future.cancel():
            database = get_database()
            job = database.get_processing_job(job_id)
            updates: Dict[str, Any] = {
                "status": "cancelled",
                "error": "cancelled before processing started",
                "finished_at": datetime.now().isoformat(),
            }
            if job and job.get("kind") == "agent":
                updates["payload"] = self._agent_payload_summary(job.get("payload") or {})
            database.update_processing_job(
                job_id,
                **updates,
            )
        return requested

    def active_jobs(self) -> list[Dict[str, Any]]:
        """Only work owned by this executor; historical/other-process jobs are excluded."""
        with self._lock:
            # Done callbacks still finish durable ownership/artifact bookkeeping.
            active_ids = list(self._futures)
        jobs = []
        for job_id in active_ids:
            job = get_database().get_processing_job(job_id) or {}
            jobs.append({"job_id": job_id, "kind": job.get("kind", "process"),
                         "status": job.get("status", "running"), "stage": job.get("current_item", ""),
                         "cancellable": self.can_cancel(job_id),
                         "cancel_requested": bool(job.get("cancel_requested"))})
        return jobs

    def begin_desktop_exit(self, *, cancel: bool = False) -> list[Dict[str, Any]]:
        """Stop new submissions, optionally request cancellation, and let writes finish."""
        with self._submission_lock:
            self._closed = True
        if cancel:
            for job in self.active_jobs():
                if job["cancellable"]:
                    self.cancel(job["job_id"])
        return self.active_jobs()

    def shutdown(self, *, wait: bool = False) -> None:
        """Close submissions, request cancellation, and optionally drain callbacks."""
        with self._submission_lock:
            self._closed = True
        with self._lock:
            active_ids = [
                job_id for job_id in self._futures
                if job_id not in self._non_cancellable_jobs
            ]
        for job_id in active_ids:
            get_database().request_processing_job_cancel(job_id)
        self._executor.shutdown(wait=wait, cancel_futures=True)


__all__ = ["ProcessingJobManager"]
