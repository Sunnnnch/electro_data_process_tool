#!/usr/bin/env python
"""Run and persist v6 stress-smoke report."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import datetime
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
V6_ROOT = SCRIPT_PATH.parents[1]
SRC = V6_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from electrochem_v6.stress import run_stress_smoke  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_report(payload: dict) -> Path:
    report_dir = V6_ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    latest = report_dir / "stress_smoke_latest.json"
    stamped = report_dir / f"stress_smoke_{ts}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    latest.write_text(text, encoding="utf-8")
    stamped.write_text(text, encoding="utf-8")
    return latest


def main() -> int:
    parser = argparse.ArgumentParser(description="Run v6 stress smoke test")
    parser.add_argument("--port", type=int, default=0, help="Server port; 0 means auto-free port")
    parser.add_argument("--upload-workers", type=int, default=4)
    parser.add_argument("--upload-requests", type=int, default=8)
    parser.add_argument("--conversation-turns", type=int, default=40)
    parser.add_argument("--timeout-sec", type=float, default=10.0)
    args = parser.parse_args()

    port = args.port or _free_port()
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "stress_smoke",
        "params": {
            "port": port,
            "upload_workers": args.upload_workers,
            "upload_requests": args.upload_requests,
            "conversation_turns": args.conversation_turns,
            "timeout_sec": args.timeout_sec,
        },
    }
    result = run_stress_smoke(
        port=port,
        upload_workers=args.upload_workers,
        upload_requests=args.upload_requests,
        conversation_turns=args.conversation_turns,
        timeout_sec=args.timeout_sec,
    )
    payload["result"] = result
    report_path = _write_report(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"[REPORT] {report_path}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
