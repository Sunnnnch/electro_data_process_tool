"""Embedded HTTP server host for v6 API-first refactor.

Security design notes
---------------------
* The server only binds to 127.0.0.1 (localhost) — it is **not** reachable
  from the network.  This is intentional: the application is a local desktop
  tool, so CORS headers and authentication are deliberately omitted.
* If a future version needs network access, add:
  - ``Access-Control-Allow-Origin`` gating
  - Bearer-token or session-cookie authentication
  - TLS termination (or run behind a reverse proxy)
* ``Content-Security-Policy`` uses ``'unsafe-inline'`` because the bundled
  single-page UI injects small inline scripts during hydration.
"""

from __future__ import annotations

import json
import logging
import math
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

from electrochem_v6.agent import AgentService
from electrochem_v6.core.logging_policy import get_v6_logger, log_event
from electrochem_v6.server.routes_get import dispatch_get
from electrochem_v6.server.routes_post import dispatch_post


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_json_safe(v) for v in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _to_json_safe(item())
        except Exception:
            pass
    return str(value)


def _encode_json_payload(payload: Dict[str, Any]) -> bytes:
    safe = _to_json_safe(payload)
    return json.dumps(safe, ensure_ascii=False, allow_nan=False).encode("utf-8")


class V6ServerManager:
    """Minimal embedded HTTP server for v6 refactor stage."""

    def __init__(self, port: int = 8010):
        self.port = int(port)
        self.is_running = False
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._agent_service = AgentService()

    def start(self) -> tuple[bool, str]:
        if self.is_running:
            return False, "v6 服务器已在运行中"
        try:
            handler_cls = self._make_handler()
            self._server = ThreadingHTTPServer(("127.0.0.1", self.port), handler_cls)
        except OSError as exc:
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
                        "payload": response_payload,
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
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("X-Content-Type-Options", "nosniff")
                if content_type == "text/html":
                    self.send_header(
                        "Content-Security-Policy",
                        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;",
                    )
                self.end_headers()
                self.wfile.write(resolved.read_bytes())
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
                    if self.path == "/ui" or self.path == "/ui/":
                        if self._send_static_file(static_root / "index.html"):
                            return
                    if self.path.startswith("/ui/static/"):
                        rel = self.path[len("/ui/static/") :].split("?", 1)[0]
                        if self._send_static_file(static_root / rel):
                            return
                        self._send_json(404, {"status": "error", "message": "Static file not found"})
                        return
                    handled = dispatch_get(self)
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
                try:
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

        return Handler
