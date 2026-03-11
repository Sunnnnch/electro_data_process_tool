"""Concurrent upload + long-conversation stress smoke for v6 server."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from typing import Any, Dict, Tuple
from urllib import error, request

from electrochem_v6.server import V6ServerManager
from electrochem_v6.store.conversations import append_message, get_conversation


def _ensure_utf8_console() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


@contextmanager
def _isolated_data_env():
    with tempfile.TemporaryDirectory(prefix="v6_stress_env_") as td:
        root = td
        mapping = {
            "ELECTROCHEM_V6_PROJECTS_FILE": os.path.join(root, "projects.json"),
            "ELECTROCHEM_V6_HISTORY_FILE": os.path.join(root, "processing_history.json"),
            "ELECTROCHEM_V6_CONVERSATION_FILE": os.path.join(root, "conversation_history.json"),
            "ELECTROCHEM_V6_TEMPLATE_FILE": os.path.join(root, "process_templates.json"),
            "ELECTROCHEM_V6_QUALITY_REPORT_FILE": os.path.join(root, "latest_quality_report.json"),
        }
        old = {k: os.environ.get(k) for k in mapping}
        try:
            for k, v in mapping.items():
                os.environ[k] = v
            yield {"root": root, "paths": mapping}
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def _read_json_allow_error(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: Dict[str, str] | None = None,
    timeout: float = 8.0,
) -> Tuple[int, Dict[str, Any]]:
    req = request.Request(url, method=method, data=data, headers=headers or {})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            try:
                return resp.status, json.loads(body)
            except Exception:
                return resp.status, {"status": "non_json", "raw": body}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        try:
            return exc.code, json.loads(body or "{}")
        except Exception:
            return exc.code, {"status": "non_json", "raw": body}


def _wait_health(base_url: str, timeout_s: float = 8.0) -> None:
    end = time.time() + timeout_s
    while time.time() < end:
        try:
            status, payload = _read_json_allow_error(f"{base_url}/health")
            if status == 200 and payload.get("status") == "ok":
                return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("health check timeout")


def _build_demo_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Minimal demo text file for upload-route stress (result may be success or validation error).
        zf.writestr("demo/LSV_1.txt", "Potential Current\n0 0\n0.1 0.2\n0.2 0.3\n")
    return buf.getvalue()


def _build_multipart(fields: Dict[str, str], file_name: str, file_bytes: bytes, file_field: str = "file") -> tuple[bytes, Dict[str, str]]:
    boundary = f"----v6stress{uuid.uuid4().hex[:12]}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
        chunks.append(f"{value}\r\n".encode("utf-8"))
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        (
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(file_bytes)
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    return body, headers


class _DummyAgentService:
    """Deterministic local agent to make stress smoke fully offline."""

    def chat(
        self,
        *,
        message: str,
        conversation_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        project_name: str | None = None,
        data_type: str | None = None,
        processing_result: Dict[str, Any] | None = None,
        attachments: list[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        cid = conversation_id or f"stress_conv_{uuid.uuid4().hex[:8]}"
        meta = {
            "provider": provider or "dummy",
            "model": model or "dummy-model",
            "project_name": project_name,
            "data_type": data_type,
        }
        append_message(cid, "user", message or "", metadata=meta, attachments=attachments or [])
        append_message(cid, "agent", f"echo:{(message or '')[:60]}", metadata=meta)
        conv = get_conversation(cid)
        return {
            "status": "success",
            "conversation_id": cid,
            "provider": meta["provider"],
            "model": meta["model"],
            "agent_reply": f"echo:{(message or '')[:60]}",
            "processing_result": processing_result,
            "attachments": attachments or [],
            "messages": conv.get("messages", []) if conv else [],
            "conversation": conv,
        }

    def delete_session(self, conversation_id: str) -> None:
        return None


def _run_upload_phase(
    base_url: str,
    *,
    upload_workers: int,
    upload_requests: int,
    timeout_sec: float,
) -> Dict[str, Any]:
    zip_bytes = _build_demo_zip_bytes()

    def _single_upload(index: int) -> Dict[str, Any]:
        started = time.perf_counter()
        fields = {"data_type": "LSV", "project_name": f"stress_u_{index}"}
        body, headers = _build_multipart(fields, file_name=f"demo_{index}.zip", file_bytes=zip_bytes)
        status, payload = _read_json_allow_error(
            f"{base_url}/api/v1/process-zip",
            method="POST",
            data=body,
            headers=headers,
            timeout=timeout_sec,
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        ok = status in {200, 400} and payload.get("status") in {"success", "error"}
        return {"ok": ok, "status_code": status, "duration_ms": duration_ms, "result_status": payload.get("status")}

    started = time.perf_counter()
    rows: list[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, int(upload_workers))) as pool:
        futures = [pool.submit(_single_upload, i + 1) for i in range(max(1, int(upload_requests)))]
        for fu in as_completed(futures):
            try:
                rows.append(fu.result())
            except Exception as exc:
                rows.append({"ok": False, "status_code": None, "duration_ms": 0.0, "error": str(exc)})

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    ok_count = sum(1 for r in rows if r.get("ok"))
    fail_count = len(rows) - ok_count
    has_5xx = any((r.get("status_code") or 0) >= 500 for r in rows if isinstance(r.get("status_code"), int))
    return {
        "name": "concurrent_upload",
        "workers": upload_workers,
        "requests": upload_requests,
        "elapsed_ms": elapsed_ms,
        "ok_count": ok_count,
        "fail_count": fail_count,
        "has_5xx": has_5xx,
        "sample": rows[:10],
        "ok": fail_count == 0 and not has_5xx,
    }


def _run_long_conversation_phase(base_url: str, *, conversation_turns: int, timeout_sec: float) -> Dict[str, Any]:
    turns = max(1, int(conversation_turns))
    conversation_id: str | None = None
    started = time.perf_counter()
    failed: list[Dict[str, Any]] = []
    for i in range(turns):
        payload = {
            "conversation_id": conversation_id,
            "message": f"[stress turn {i + 1}/{turns}] please summarize this turn",
            "provider": "dummy",
            "model": "dummy-model",
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        status, body = _read_json_allow_error(
            f"{base_url}/api/v1/agent/messages",
            method="POST",
            data=data,
            headers={"Content-Type": "application/json"},
            timeout=timeout_sec,
        )
        if status != 200 or body.get("status") != "success":
            failed.append({"turn": i + 1, "status_code": status, "status": body.get("status"), "message": body.get("message")})
            break
        conversation_id = body.get("conversation_id") or conversation_id

    stored_messages = 0
    if conversation_id:
        status, body = _read_json_allow_error(
            f"{base_url}/api/v1/agent/conversations/{conversation_id}",
            timeout=timeout_sec,
        )
        if status == 200 and body.get("status") == "success":
            stored_messages = len(((body.get("conversation") or {}).get("messages") or []))
        else:
            failed.append({"turn": "fetch_conversation", "status_code": status, "status": body.get("status")})

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    min_expected = turns * 2
    return {
        "name": "long_conversation",
        "turns": turns,
        "elapsed_ms": elapsed_ms,
        "conversation_id": conversation_id,
        "stored_messages": stored_messages,
        "min_expected_messages": min_expected,
        "failures": failed,
        "ok": (not failed) and stored_messages >= min_expected,
    }


def run_stress_smoke(
    *,
    port: int = 8012,
    upload_workers: int = 4,
    upload_requests: int = 8,
    conversation_turns: int = 40,
    timeout_sec: float = 10.0,
) -> Dict[str, Any]:
    _ensure_utf8_console()
    with _isolated_data_env() as env_info:
        manager = V6ServerManager(port=port)
        manager._agent_service = _DummyAgentService()
        ok, msg = manager.start()
        if not ok:
            return {"ok": False, "stage": "start", "message": msg}

        base = f"http://127.0.0.1:{port}"
        phases: list[Dict[str, Any]] = []
        try:
            _wait_health(base)
            phases.append(
                _run_upload_phase(
                    base,
                    upload_workers=upload_workers,
                    upload_requests=upload_requests,
                    timeout_sec=timeout_sec,
                )
            )
            phases.append(
                _run_long_conversation_phase(
                    base,
                    conversation_turns=conversation_turns,
                    timeout_sec=timeout_sec,
                )
            )
            return {
                "ok": all(p.get("ok") for p in phases),
                "env_root": env_info.get("root"),
                "phases": phases,
            }
        except Exception as exc:
            return {
                "ok": False,
                "stage": "exception",
                "message": str(exc),
                "env_root": env_info.get("root"),
                "phases": phases,
            }
        finally:
            manager.stop()
