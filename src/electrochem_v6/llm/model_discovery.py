"""Read an OpenAI-compatible model catalogue without saving keys or running inference."""

from __future__ import annotations

import ipaddress
import json
import time
import zlib
from collections.abc import Callable, Iterator
from urllib.parse import urlsplit

import requests
from urllib3.exceptions import HTTPError as UrllibHTTPError
from urllib3.exceptions import ReadTimeoutError

from electrochem_v6.llm.config import LLMConfig

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_MODELS = 2000
MAX_DISCOVERY_SECONDS = 10

_MESSAGES = {
    "invalid_config": "请检查服务商、API Key 和 Base URL。",
    "invalid_url": "Base URL 需为 HTTPS 地址；本机服务可使用 HTTP，不支持账号密码、查询参数或片段。",
    "missing_key": "请先输入 API Key，或保存该服务商的密钥。",
    "endpoint_changed": "Base URL 已切换到另一服务地址，请输入该地址对应的 API Key 后重试。",
    "unauthorized": "密钥无效或没有查询模型列表的权限，请检查密钥与服务地址。",
    "unsupported": "此地址未提供兼容的模型列表接口，可继续手动填写模型名称。",
    "rate_limited": "模型列表请求过于频繁，请稍后刷新；仍可手动填写模型。",
    "unavailable": "服务商暂时无法返回模型列表，请稍后刷新或手动填写。",
    "redirect": "模型列表地址发生重定向，未转发密钥；请核对 Base URL 或手动填写模型。",
    "timeout": "获取模型列表超时，请检查网络或稍后刷新；仍可手动填写。",
    "network": "无法连接模型列表接口，请检查网络、代理与 Base URL；仍可手动填写。",
    "invalid_response": "服务商返回的模型列表格式不兼容或内容过大，可继续手动填写模型。",
}


def _error(code: str) -> dict:
    # Never expose an upstream body, exception, URL or credential in responses/logs.
    return {"status": "error", "code": code, "message": _MESSAGES[code]}


class _DiscoveryFailure(Exception):
    def __init__(self, code: str):
        self.code = code


def _read_model_body(response: requests.Response, started: float) -> bytes:
    """Bound wire size, decoded size and elapsed time without waiting for full chunks."""
    length = response.headers.get("Content-Length")
    if length is not None:
        try:
            if int(length) < 0 or int(length) > MAX_RESPONSE_BYTES:
                raise _DiscoveryFailure("invalid_response")
        except ValueError:
            raise _DiscoveryFailure("invalid_response") from None
    encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
    if encoding in {"", "identity"}:
        decoder = None
    elif encoding in {"gzip", "x-gzip", "deflate"}:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS if encoding != "deflate" else zlib.MAX_WBITS)
    else:
        raise _DiscoveryFailure("invalid_response")
    # read1 returns available bytes after at most one underlying read. Disabling
    # urllib3 decoding prevents its decoder from doing hidden extra network reads.
    read1: Callable[..., bytes] | None = getattr(response.raw, "read1", None)
    legacy_stream: Iterator[bytes] = iter(()) if callable(read1) else response.raw.stream(amt=1, decode_content=False)
    body = bytearray()
    received = 0
    while True:
        if time.monotonic() - started > MAX_DISCOVERY_SECONDS:
            raise _DiscoveryFailure("timeout")
        chunk: bytes = read1(16384, decode_content=False) if callable(read1) else next(legacy_stream, b"")
        if time.monotonic() - started > MAX_DISCOVERY_SECONDS:
            raise _DiscoveryFailure("timeout")
        if not chunk:
            break
        received += len(chunk)
        if received > MAX_RESPONSE_BYTES:
            raise _DiscoveryFailure("invalid_response")
        if decoder:
            try:
                chunk = decoder.decompress(chunk, MAX_RESPONSE_BYTES + 1 - len(body))
            except zlib.error:
                raise _DiscoveryFailure("invalid_response") from None
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            raise _DiscoveryFailure("invalid_response")
    if decoder and (not decoder.eof or decoder.unused_data):
        raise _DiscoveryFailure("invalid_response")
    return bytes(body)


def _base_url(value: object) -> tuple[str, tuple]:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError
    value = value.strip().rstrip("/")
    if any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\" in value:
        raise ValueError
    parsed = urlsplit(value)
    if not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError
    if parsed.scheme not in {"https", "http"}:
        raise ValueError
    if parsed.scheme == "http":
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname.lower() == "localhost"
        if not loopback:
            raise ValueError
    origin = (parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80))
    return value, origin


def discover_provider_models(payload: dict) -> dict:
    """Only GET ``<base_url>/models``. An unsupported catalogue never blocks manual input."""
    if not isinstance(payload, dict) or not isinstance(payload.get("provider"), str) or not payload["provider"].strip():
        return _error("invalid_config")
    entered_key = payload.get("api_key", "")
    if not isinstance(entered_key, str) or len(entered_key) > 8192 or any(ord(c) < 32 or ord(c) > 126 for c in entered_key):
        return _error("invalid_config")
    entered_key = entered_key.strip()
    try:
        cfg = LLMConfig()
        provider = cfg.normalize_provider(payload["provider"].strip())
        entry = cfg.get_model_config(provider) or {}
    except Exception:
        return _error("invalid_config")
    try:
        base_url, origin = _base_url(payload.get("base_url", entry.get("base_url", "")))
        if not entered_key:
            _, saved_origin = _base_url(entry.get("base_url", ""))
            if origin != saved_origin:
                return _error("endpoint_changed")
    except (ValueError, TypeError):
        return _error("invalid_url")
    api_key = entered_key or str(cfg.get_api_key(provider) or "").strip()
    if not api_key:
        return _error("missing_key")
    try:
        started = time.monotonic()
        with requests.Session() as session:
            # Keep proxy support, but never let a user's .netrc override the supplied key.
            session.auth = lambda request: request
            # Redirects must never carry this credential to an unexpected destination.
            with session.get(
                base_url + "/models",
                headers={"Authorization": "Bearer " + api_key, "Accept": "application/json", "Accept-Encoding": "gzip, deflate"},
                timeout=(3.05, 5), allow_redirects=False, stream=True,
            ) as response:
                status = response.status_code
                if 300 <= status < 400:
                    return _error("redirect")
                if status in {401, 403}:
                    return _error("unauthorized")
                if status in {404, 405, 501}:
                    return _error("unsupported")
                if status == 429:
                    return _error("rate_limited")
                if not 200 <= status < 300:
                    return _error("unavailable")
                body = _read_model_body(response, started)
        result = json.loads(body)
        rows = result.get("data") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            return _error("invalid_response")
        models = set()
        for row in rows:
            model_id = row.get("id") if isinstance(row, dict) else None
            if not isinstance(model_id, str):
                continue
            model_id = model_id.strip()
            if not model_id or len(model_id) > 256 or not model_id.isprintable() or api_key in model_id:
                continue
            models.add(model_id)
            if len(models) >= MAX_MODELS:
                break
        return {"status": "success", "models": sorted(models), "truncated": len(rows) > MAX_MODELS}
    except _DiscoveryFailure as exc:
        return _error(exc.code)
    except (requests.Timeout, ReadTimeoutError):
        return _error("timeout")
    except (requests.RequestException, UrllibHTTPError):
        return _error("network")
    except (ValueError, TypeError, UnicodeError):
        return _error("invalid_response")
