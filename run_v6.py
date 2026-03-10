#!/usr/bin/env python
"""
v6 refactor entrypoint (no license mode).
"""

from __future__ import annotations

import argparse
import json
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from electrochem_v6.app import run_check  # noqa: E402
from electrochem_v6.config import APP_VERSION  # noqa: E402
from electrochem_v6.server import V6ServerManager  # noqa: E402
from electrochem_v6.smoke import run_smoke  # noqa: E402
from electrochem_v6.stress import run_stress_smoke  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="ElectroChem v6 refactor runner")
    sub = parser.add_subparsers(dest="cmd", required=False)

    sub.add_parser("check", help="Run v6 skeleton health checks")
    sub.add_parser("version", help="Show v6 version")
    p_server = sub.add_parser("server", help="Start v6 embedded HTTP server")
    p_server.add_argument("--port", type=int, default=8010, help="Port to bind (default: 8010)")
    p_smoke = sub.add_parser("smoke", help="Run v6 API smoke test")
    p_smoke.add_argument("--port", type=int, default=8011, help="Temporary port (default: 8011)")
    p_stress = sub.add_parser("stress", help="Run v6 stress smoke (concurrent upload + long conversation)")
    p_stress.add_argument("--port", type=int, default=8012, help="Temporary port (default: 8012)")
    p_stress.add_argument("--upload-workers", type=int, default=4, help="Upload concurrency workers (default: 4)")
    p_stress.add_argument("--upload-requests", type=int, default=8, help="Total upload requests (default: 8)")
    p_stress.add_argument("--conversation-turns", type=int, default=40, help="Long conversation turns (default: 40)")
    p_stress.add_argument("--timeout-sec", type=float, default=10.0, help="Per-request timeout seconds (default: 10)")

    argv = sys.argv[1:]
    command_names = {"check", "version", "server", "smoke", "stress"}
    if not argv:
        argv = ["server"]
    elif argv[0] not in command_names:
        argv = ["server", *argv]

    args = parser.parse_args(argv)
    if not args.cmd:
        args.cmd = "server"

    if args.cmd == "version":
        print(APP_VERSION)
        return 0

    if args.cmd == "check":
        result = run_check()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    if args.cmd == "smoke":
        result = run_smoke(port=args.port)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    if args.cmd == "stress":
        result = run_stress_smoke(
            port=args.port,
            upload_workers=args.upload_workers,
            upload_requests=args.upload_requests,
            conversation_turns=args.conversation_turns,
            timeout_sec=args.timeout_sec,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    if args.cmd == "server":
        manager = V6ServerManager(port=args.port)
        ok, message = manager.start()
        print(message)
        if not ok:
            return 1
        print(f"v6 server running at http://127.0.0.1:{args.port} (Ctrl+C to stop)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            manager.stop()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
