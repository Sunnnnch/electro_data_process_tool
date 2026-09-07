"""Bounded, authenticated access to a running ElectroChem loopback HTTP API."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from electrochem_v6.config import user_config_dir

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_REQUEST_BYTES = 512 * 1024
_SECRET_KEYS = {"session_token", "api_key", "apikey", "authorization", "access_token", "refresh_token", "password"}
_GET_PATHS = {"/", "/api/v1/mcp/status", "/api/v1/projects", "/api/v1/history", "/api/v1/tasks",
              "/api/v1/process/schema", "/api/v1/process/templates"}
_POST_PATHS = {"/api/v1/process/preflight", "/api/v1/process/jobs", "/api/v1/history/compare"}


class MCPClientError(ValueError):
    """An actionable tool failure containing no connection credentials."""

    def __init__(self, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {"status": "error", "code": self.code, "message": str(self)}
        if self.details is not None:
            result["details"] = self.details
        return result


def validate_base_url(value: str) -> str:
    """Accept only a literal HTTP loopback origin, never a URL to arbitrary data."""
    if not isinstance(value, str) or not re.fullmatch(r"http://(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?/?", value):
        raise MCPClientError("invalid_url", "Use an HTTP loopback origin such as http://127.0.0.1:8010, without a path, query or credentials.")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise MCPClientError("invalid_url", "The local service port is invalid.") from None
    if port is not None and not 1 <= port <= 65535:
        raise MCPClientError("invalid_url", "The local service port is invalid.")
    # Resolve localhost to the literal loopback address so proxy/DNS settings
    # cannot change the destination after validation.
    return "http://127.0.0.1" + (f":{port}" if port is not None else "")


def _safe_payload(value: Any, token: str | None = None) -> Any:
    if isinstance(value, dict):
        return {key: "[redacted]" if str(key).lower() in _SECRET_KEYS else _safe_payload(item, token)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_payload(item, token) for item in value]
    if isinstance(value, str) and token:
        return value.replace(token, "[redacted]")
    return value


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MCPClientError("redirect_refused", "The local service returned a redirect. Check the ElectroChem service address.")


def _allowed_route(method: str, path: str) -> bool:
    if method == "GET":
        return path in _GET_PATHS or bool(re.fullmatch(r"/api/v1/(?:history|runs|tasks)/[^/?#]+", path))
    if method == "POST":
        return path in _POST_PATHS or bool(re.fullmatch(r"/api/v1/(?:projects|runs)/[^/?#]+/report", path))
    return False


@dataclass(frozen=True)
class _Connection:
    base_url: str
    token: str | None = field(default=None, repr=False)
    timeout: float = 30
    closing: bool = False

    def request(self, method: str, path: str, *, query: dict[str, Any] | None = None,
                payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not _allowed_route(method, path):
            raise MCPClientError("unsupported_operation", "This HTTP operation is not available through MCP.")
        if self.closing and method == "POST":
            raise MCPClientError("desktop_closing", "ElectroChem is closing. Existing jobs can still be read; reopen the application before requesting a new operation.")
        data = None
        if payload is not None:
            try:
                data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (ValueError, TypeError):
                raise MCPClientError("invalid_input", "Parameters must contain finite JSON values.") from None
            if len(data) > MAX_REQUEST_BYTES:
                raise MCPClientError("request_too_large", "The request exceeds the MCP input limit; reduce the selected files or parameters.")
        parameters = {key: value for key, value in (query or {}).items() if value is not None}
        url = self.base_url + path + ("?" + urlencode(parameters, doseq=True) if parameters else "")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["X-Electrochem-Session"] = self.token
        request = Request(url, data=data, headers=headers, method=method)
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        try:
            try:
                response = opener.open(request, timeout=self.timeout)
            except HTTPError as exc:
                response = exc
            with response:
                status = response.code
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except MCPClientError:
            raise
        except (OSError, URLError, TimeoutError):
            raise MCPClientError("service_unavailable", "Cannot reach ElectroChem. Open the application and retry. A submitted job may still be running; check jobs before retrying a write.") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MCPClientError("response_too_large", "The result exceeds the MCP response limit; request a smaller page or narrower report scope.")
        try:
            parsed = json.loads(raw)
        except (ValueError, UnicodeError):
            raise MCPClientError("invalid_service_response", "The service did not return a valid JSON response.") from None
        if not isinstance(parsed, dict):
            raise MCPClientError("invalid_service_response", "The service response must be a JSON object.")
        result = _safe_payload(parsed, self.token)
        if not 200 <= status < 300 or result.get("status") == "error":
            message = {401: "Local service authentication failed. Restart ElectroChem and retry.",
                       403: "Local service authentication or path permission failed. Reopen ElectroChem or select the source folder in its workspace.",
                       404: "The requested record, run or operation is unavailable. Refresh the corresponding list.",
                       503: "ElectroChem is closing or temporarily unavailable. Reopen it before submitting new work."}.get(status)
            raise MCPClientError(f"http_{status}", message or "ElectroChem rejected the operation; review the returned details.",
                                 None if status in {401, 403} else result)
        return result


class ElectroChemClient:
    """Discover on every tool call; keep one verified connection for that call."""

    def __init__(self, *, base_url: str | None = None, data_dir: str | Path | None = None,
                 timeout: float = 30) -> None:
        self.base_url = validate_base_url(base_url) if base_url is not None else None
        self.data_dir = Path(data_dir).expanduser() if data_dir is not None else None
        if not 0 < timeout <= 120:
            raise ValueError("HTTP timeout must be between 0 and 120 seconds")
        self.timeout = timeout

    def connect(self) -> _Connection:
        if self.base_url is not None:
            connection = _Connection(self.base_url, timeout=self.timeout)
            identity = connection.request("GET", "/")
            if identity.get("name") != "electrochem-v6-api" or identity.get("status") != "running":
                raise MCPClientError("wrong_service", "The URL does not identify a running ElectroChem API.")
            return connection
        descriptor = (self.data_dir if self.data_dir is not None else user_config_dir()) / "desktop-service.json"
        try:
            with descriptor.open("rb") as stream:
                raw = stream.read(16385)
            if len(raw) > 16384:
                raise ValueError("oversized")
            record = json.loads(raw)
            if (not isinstance(record, dict) or type(record.get("version")) is not int or record["version"] != 1
                    or type(record.get("pid")) is not int or record["pid"] <= 0):
                raise ValueError("invalid descriptor")
            token = record.get("session_token")
            if not isinstance(token, str) or not 16 <= len(token) <= 1024 or any(ord(char) < 33 or ord(char) > 126 for char in token):
                raise ValueError("invalid session")
            url = record.get("url")
            if not isinstance(url, str):
                raise ValueError("missing address")
            address = validate_base_url(url)
        except FileNotFoundError:
            raise MCPClientError("desktop_not_running", "No desktop service was found. Open ElectroChem, or provide --url for an existing browser service.") from None
        except (OSError, ValueError, TypeError, MCPClientError):
            raise MCPClientError("invalid_discovery", "The desktop service descriptor is invalid. Restart ElectroChem to refresh it.") from None
        connection = _Connection(address, token=token, timeout=self.timeout)
        identity = connection.request("GET", "/api/v1/mcp/status")
        if identity.get("name") != "electrochem-v6-api" or identity.get("status") != "success" or not isinstance(identity.get("closing"), bool):
            raise MCPClientError("wrong_service", "The discovered endpoint is not the authenticated ElectroChem desktop API.")
        return _Connection(address, token=token, timeout=self.timeout, closing=identity["closing"])


__all__ = ["ElectroChemClient", "MCPClientError", "validate_base_url"]
