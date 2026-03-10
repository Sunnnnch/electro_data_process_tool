"""Smoke tests for v6 server skeleton."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Tuple
from urllib import error, request

from .server import V6ServerManager


def _read_json(url: str, method: str = "GET", payload: Dict[str, Any] | None = None) -> Tuple[int, Dict[str, Any]]:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, method=method, data=data, headers=headers)
    with request.urlopen(req, timeout=3) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body)


def _read_json_allow_error(
    url: str,
    method: str = "GET",
    payload: Dict[str, Any] | None = None,
) -> Tuple[int, Dict[str, Any]]:
    try:
        return _read_json(url=url, method=method, payload=payload)
    except json.JSONDecodeError:
        return 200, {"status": "non_json"}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(body or "{}")
        except Exception:
            parsed = {"status": "error", "message": body}
        return exc.code, parsed


def _wait_health(base_url: str, timeout_s: float = 5.0) -> None:
    end = time.time() + timeout_s
    while time.time() < end:
        try:
            status, payload = _read_json(f"{base_url}/health")
            if status == 200 and payload.get("status") == "ok":
                return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("v6 health check timeout")


def run_smoke(port: int = 8011) -> Dict[str, Any]:
    manager = V6ServerManager(port=port)
    ok, msg = manager.start()
    if not ok:
        return {"ok": False, "stage": "start", "message": msg}
    base = f"http://127.0.0.1:{port}"
    checks: list[Dict[str, Any]] = []
    try:
        _wait_health(base)
        status, payload = _read_json(f"{base}/api/v1/projects")
        checks.append({"name": "projects_get", "status": status, "ok": status == 200 and payload.get("status") == "success"})

        status, payload = _read_json(
            f"{base}/api/v1/projects",
            method="POST",
            payload={"name": "v6_smoke_project", "description": "smoke"},
        )
        checks.append({"name": "projects_post", "status": status, "ok": status == 200 and payload.get("status") == "success"})

        status, payload = _read_json(f"{base}/api/v1/llm/config")
        checks.append({"name": "llm_config_get", "status": status, "ok": status == 200 and payload.get("status") == "success"})

        status, payload = _read_json(f"{base}/api/v1/history")
        checks.append({"name": "history_get", "status": status, "ok": status == 200 and payload.get("status") == "success"})

        status, payload = _read_json_allow_error(f"{base}/api/v1/quality-report/latest")
        checks.append({"name": "quality_latest", "status": status, "ok": status in {200, 404}})

        status, payload = _read_json_allow_error(
            f"{base}/api/v1/process",
            method="POST",
            payload={"folder_path": "__not_exists__", "data_type": "LSV"},
        )
        checks.append({"name": "process_json_route", "status": status, "ok": status == 400})

        status, payload = _read_json_allow_error(
            f"{base}/api/v1/process-zip",
            method="POST",
            payload={"bad": "request"},
        )
        checks.append({"name": "process_zip_route", "status": status, "ok": status == 400})

        status, payload = _read_json_allow_error(f"{base}/ui")
        checks.append({"name": "ui_entry", "status": status, "ok": status == 200 and payload.get("status") in {"non_json", "success"}})

        return {"ok": all(c["ok"] for c in checks), "checks": checks}
    except error.HTTPError as exc:
        return {"ok": False, "stage": "http", "code": exc.code, "message": exc.read().decode("utf-8", errors="ignore")}
    except Exception as exc:
        return {"ok": False, "stage": "exception", "message": str(exc)}
    finally:
        manager.stop()
