"""Embedded HTTP server host for the ElectroChem V6 local API.

Security design notes
---------------------
* The server only binds to 127.0.0.1 and validates Host/Origin headers.
* Browser writes require a per-launch session token injected into the bundled
  UI. Non-browser local clients remain supported when they send no Origin or
  Fetch Metadata headers.
* ``Content-Security-Policy`` uses ``'unsafe-inline'`` because the bundled
  single-page UI injects small inline scripts during hydration.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from electrochem_v6.agent import AgentService
from electrochem_v6.core.job_service import ProcessingJobManager
from electrochem_v6.core.logging_policy import get_v6_logger, log_event
from electrochem_v6.server.routes_get import dispatch_get
from electrochem_v6.server.routes_post import dispatch_post
from electrochem_v6.store._json_utils import to_json_safe as _to_json_safe


def _encode_json_payload(payload: Dict[str, Any]) -> bytes:
    safe = _to_json_safe(payload)
    return json.dumps(safe, ensure_ascii=False, allow_nan=False).encode("utf-8")


class _ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """Keep one local service per address, including beside older Windows builds."""

    # On Windows SO_REUSEADDR can bind an already listening address and send
    # requests to either process. POSIX address reuse only aids closed sockets.
    allow_reuse_address = os.name != "nt"
    allow_reuse_port = False

    def server_bind(self) -> None:
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class V6ServerManager:
    """Embedded HTTP server manager for ElectroChem V6."""

    def __init__(self, port: int = 8010):
        self.port = int(port)
        self.is_running = False
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._agent_service = AgentService()
        self._job_manager: Optional[ProcessingJobManager] = None
        self.session_token = secrets.token_urlsafe(32)
        self._desktop_request_lock = threading.RLock()
        self._desktop_draining = False
        self._active_writes = 0

    def close_desktop_admission(self) -> None:
        """Block new writes while already admitted native-client requests finish."""
        with self._desktop_request_lock:
            self._desktop_draining = True

    def desktop_active_writes(self) -> int:
        with self._desktop_request_lock:
            return self._active_writes

    def desktop_is_closing(self) -> bool:
        with self._desktop_request_lock:
            return self._desktop_draining

    def _admit_write(self) -> bool:
        with self._desktop_request_lock:
            if self._desktop_draining:
                return False
            self._active_writes += 1
            return True

    def _finish_write(self) -> None:
        with self._desktop_request_lock:
            self._active_writes -= 1

    def _run_agent_job(
        self,
        payload: Dict[str, Any],
        *,
        progress_callback,
        cancel_check,
    ) -> Dict[str, Any]:
        prepared_upload = payload.get("_prepared_upload")
        processing_result = payload.get("processing_result")
        attachments = list(payload.get("attachments") or []) if isinstance(payload.get("attachments"), list) else []
        if isinstance(prepared_upload, dict):
            from electrochem_v6.server.routes_post import _process_prepared_uploaded_zip

            processed = _process_prepared_uploaded_zip(
                prepared_upload,
                cancel_check=cancel_check,
                progress_callback=lambda current, total, item: progress_callback(
                    f"processing {current}/{total}: {item or ''}".strip()
                ),
            )
            if processed.get("status") != "success":
                return processed
            processing_result = processed.get("result")
            attachments.append(
                {
                    "type": "processing_result",
                    "file_name": prepared_upload.get("original_filename") or "upload.zip",
                    "project_name": prepared_upload.get("project_name"),
                    "data_type": prepared_upload.get("data_type"),
                    "summary": (processing_result or {}).get("summary"),
                    "output_files": ((processing_result or {}).get("processing") or {}).get("output_files"),
                }
            )
        return self._agent_service.chat(
            message=payload.get("message", ""),
            conversation_id=payload.get("conversation_id"),
            provider=payload.get("provider"),
            model=payload.get("model"),
            project_name=payload.get("project_name"),
            data_type=payload.get("data_type"),
            processing_result=processing_result,
            attachments=attachments or None,
            prompt_prefix=payload.get("prompt_prefix"),
            professional_context=(
                payload.get("professional_context")
                if isinstance(payload.get("professional_context"), dict)
                else None
            ),
            approval_id=payload.get("approval_id"),
            approval_action=payload.get("approval_action"),
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

    def start(self) -> tuple[bool, str]:
        if self.is_running:
            return False, "v6 服务器已在运行中"
        with self._desktop_request_lock:
            self._desktop_draining = False
        try:
            if self._job_manager is None:
                self._job_manager = ProcessingJobManager(agent_runner=self._run_agent_job)
            self.session_token = secrets.token_urlsafe(32)
            handler_cls = self._make_handler()
            self._server = _ExclusiveThreadingHTTPServer(("127.0.0.1", self.port), handler_cls)
            self.port = int(self._server.server_address[1])
        except OSError as exc:
            if self._job_manager is not None:
                self._job_manager.shutdown()
                self._job_manager = None
            self._server = None
            return False, f"启动失败: {exc}"

        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.is_running = True
        return True, f"v6 服务器启动成功: http://127.0.0.1:{self.port}"

    def stop(self) -> tuple[bool, str]:
        if not self.is_running or self._server is None:
            return False, "v6 服务器未运行"
        try:
            self._server.shutdown()
            self._server.server_close()
        finally:
            if self._job_manager is not None:
                self._job_manager.shutdown()
                self._job_manager = None
            self._server = None
            self.is_running = False
        return True, "v6 服务器已停止"

    def _make_handler(self):
        manager = self
        static_root = Path(__file__).resolve().parents[1] / "ui" / "static"
        logger = get_v6_logger("electrochem_v6.http")

        def _env_int(key: str, default: int) -> int:
            raw = os.environ.get(key)
            if raw:
                try:
                    return int(raw)
                except ValueError:
                    pass
            return default

        class Handler(BaseHTTPRequestHandler):
            MAX_JSON_BODY_BYTES = _env_int("ELECTROCHEM_V6_MAX_JSON_BYTES", 2 * 1024 * 1024)
            MAX_UPLOAD_BODY_BYTES = _env_int("ELECTROCHEM_V6_MAX_UPLOAD_BYTES", 200 * 1024 * 1024)
            MAX_UPLOAD_FILE_BYTES = _env_int("ELECTROCHEM_V6_MAX_UPLOAD_FILE_BYTES", 100 * 1024 * 1024)
            MAX_ZIP_FILES = _env_int("ELECTROCHEM_V6_MAX_ZIP_FILES", 5000)
            MAX_ZIP_UNCOMPRESSED_BYTES = _env_int("ELECTROCHEM_V6_MAX_ZIP_UNCOMP_BYTES", 500 * 1024 * 1024)
            _logger = logger

            def log_message(self, format: str, *args: Any) -> None:
                # Keep default server logs quiet in this phase.
                return

            def _log_request(self) -> None:
                log_event(
                    self._logger,
                    "http.request",
                    {
                        "method": self.command,
                        "path": (self.path.split("?", 1)[0] if self.path else "/"),
                        "content_type": self.headers.get("Content-Type"),
                        "content_length": self.headers.get("Content-Length"),
                        "client": self.client_address[0] if self.client_address else None,
                    },
                )

            def _host_is_allowed(self) -> bool:
                raw_host = str(self.headers.get("Host") or "").strip()
                if not raw_host:
                    return False
                try:
                    parsed = urlsplit(f"//{raw_host}")
                    host = str(parsed.hostname or "").lower()
                    port = parsed.port
                except ValueError:
                    return False
                if host not in {"127.0.0.1", "localhost", "::1"}:
                    return False
                return port in {None, manager.port}

            def _browser_write_is_allowed(self) -> bool:
                token = str(self.headers.get("X-Electrochem-Session") or "")
                if token:
                    return secrets.compare_digest(token, manager.session_token)
                origin = str(self.headers.get("Origin") or "").strip()
                fetch_site = str(self.headers.get("Sec-Fetch-Site") or "").strip().lower()
                return not origin and fetch_site in {"", "none"}

            def _request_context_is_allowed(self, *, write: bool = False) -> bool:
                if not self._host_is_allowed():
                    return False
                origin = str(self.headers.get("Origin") or "").strip()
                if origin:
                    try:
                        parsed = urlsplit(origin)
                        origin_host = str(parsed.hostname or "").lower()
                        origin_port = parsed.port
                    except ValueError:
                        return False
                    if parsed.scheme != "http" or origin_host not in {"127.0.0.1", "localhost", "::1"}:
                        return False
                    if origin_port not in {None, manager.port}:
                        return False
                fetch_site = str(self.headers.get("Sec-Fetch-Site") or "").strip().lower()
                if fetch_site == "cross-site":
                    return False
                return not write or self._browser_write_is_allowed()

            def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
                response_status = int(status_code)
                response_payload: Dict[str, Any] = payload
                try:
                    response_body = _encode_json_payload(payload)
                except Exception:
                    response_status = 500
                    response_payload = {"status": "error", "message": "Response serialization failed"}
                    response_body = _encode_json_payload(response_payload)

                self.send_response(response_status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(response_body)
                log_event(
                    self._logger,
                    "http.response",
                    {
                        "method": self.command,
                        "path": (self.path.split("?", 1)[0] if self.path else "/"),
                        "status_code": response_status,
                        "payload_keys": list(response_payload.keys()) if isinstance(response_payload, dict) else "<non-dict>",
                    },
                    level=logging.WARNING if response_status >= 400 else logging.INFO,
                )

            def _send_static_file(self, file_path: Path) -> bool:
                try:
                    resolved = file_path.resolve()
                except Exception:
                    return False
                try:
                    if static_root.resolve() not in resolved.parents and resolved != static_root.resolve():
                        return False
                except Exception:
                    return False
                if not resolved.exists() or not resolved.is_file():
                    return False
                try:
                    if resolved.stat().st_size > 10 * 1024 * 1024:  # 10 MB
                        return False
                except OSError:
                    return False
                content_type, _ = mimetypes.guess_type(str(resolved))
                if not content_type:
                    content_type = "application/octet-stream"
                content = resolved.read_bytes()
                if content_type == "text/html":
                    content = content.replace(
                        b"__ELECTROCHEM_SESSION_TOKEN__",
                        manager.session_token.encode("ascii"),
                    )
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("X-Content-Type-Options", "nosniff")
                if content_type == "text/html":
                    self.send_header("Cache-Control", "no-store")
                    self.send_header(
                        "Content-Security-Policy",
                        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' blob:;",
                    )
                self.end_headers()
                self.wfile.write(content)
                log_event(
                    self._logger,
                    "http.response.static",
                    {
                        "method": self.command,
                        "path": (self.path.split("?", 1)[0] if self.path else "/"),
                        "status_code": 200,
                        "content_type": content_type,
                        "file": str(resolved),
                    },
                )
                return True

            def do_GET(self):
                self._log_request()
                try:
                    if not self._request_context_is_allowed():
                        self._send_json(403, {"status": "error", "message": "Request origin is not allowed"})
                        return
                    if self.path.split("?", 1)[0] in {"/ui", "/ui/"}:
                        if self._send_static_file(static_root / "index.html"):
                            return
                    if self.path.startswith("/ui/static/"):
                        from urllib.parse import unquote
                        rel = unquote(self.path[len("/ui/static/") :].split("?", 1)[0])
                        if self._send_static_file(static_root / rel):
                            return
                        self._send_json(404, {"status": "error", "message": "Static file not found"})
                        return
                    handled = dispatch_get(self, manager)
                    if not handled:
                        self._send_json(404, {"status": "error", "message": "Not Found"})
                except Exception as exc:  # pragma: no cover - defensive boundary
                    log_event(
                        self._logger,
                        "http.error",
                        {
                            "method": "GET",
                            "path": (self.path.split("?", 1)[0] if self.path else "/"),
                            "error": str(exc),
                        },
                        level=logging.ERROR,
                    )
                    if not getattr(self, "wfile", None):
                        return
                    self._send_json(500, {"status": "error", "message": "Internal Server Error"})

            def do_POST(self):
                self._log_request()
                admitted = False
                try:
                    if not self._request_context_is_allowed(write=True):
                        self._send_json(
                            403,
                            {"status": "error", "message": "Request origin or session is not allowed"},
                        )
                        return
                    admitted = manager._admit_write()
                    if not admitted:
                        self._send_json(503, {"status": "error", "message": "客户端正在安全退出，已暂停接收新操作。 / The desktop client is exiting."})
                        return
                    handled = dispatch_post(self, manager)
                    if not handled:
                        self._send_json(404, {"status": "error", "message": "Not Found"})
                except Exception as exc:  # pragma: no cover - defensive boundary
                    log_event(
                        self._logger,
                        "http.error",
                        {
                            "method": "POST",
                            "path": (self.path.split("?", 1)[0] if self.path else "/"),
                            "error": str(exc),
                        },
                        level=logging.ERROR,
                    )
                    if not getattr(self, "wfile", None):
                        return
                    self._send_json(500, {"status": "error", "message": "Internal Server Error"})
                finally:
                    if admitted:
                        manager._finish_write()

        return Handler
