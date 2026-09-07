#!/usr/bin/env python
"""
Command runner for ElectroChem.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

from electrochem_v6.config import APP_NAME, APP_VERSION  # noqa: E402
from electrochem_v6.mcp_cli import add_arguments as add_mcp_arguments  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=f"ElectroChem — {APP_NAME} (v{APP_VERSION}) command runner")
    sub = parser.add_subparsers(dest="cmd", required=False)

    sub.add_parser("check", help="Run ElectroChem health checks")
    sub.add_parser("version", help="Show application version")
    sub.add_parser("desktop", help="Open the native desktop client")
    p_mcp = sub.add_parser("mcp", help="Connect an MCP host to the open desktop over stdio (read-only by default)")
    add_mcp_arguments(p_mcp)
    p_server = sub.add_parser("server", help="Start ElectroChem embedded HTTP server")
    p_server.add_argument("--port", type=int, default=8010, help="Port to bind (default: 8010)")
    p_smoke = sub.add_parser("smoke", help="Run ElectroChem API smoke test")
    p_smoke.add_argument("--port", type=int, default=8011, help="Temporary port (default: 8011)")
    p_stress = sub.add_parser("stress", help="Run ElectroChem stress smoke (concurrent upload + long conversation)")
    p_stress.add_argument("--port", type=int, default=8012, help="Temporary port (default: 8012)")
    p_stress.add_argument("--upload-workers", type=int, default=4, help="Upload concurrency workers (default: 4)")
    p_stress.add_argument("--upload-requests", type=int, default=8, help="Total upload requests (default: 8)")
    p_stress.add_argument("--conversation-turns", type=int, default=40, help="Long conversation turns (default: 40)")
    p_stress.add_argument("--timeout-sec", type=float, default=10.0, help="Per-request timeout seconds (default: 10)")
    p_db_check = sub.add_parser("db-check", help="Check SQLite integrity and storage health")
    p_db_check.add_argument("--path", help="Optional database path")
    p_db_backup = sub.add_parser("db-backup", help="Create a verified SQLite backup")
    p_db_backup.add_argument("--path", help="Optional database path")
    p_db_backup.add_argument("--backup-dir", help="Optional backup directory")
    p_db_backup.add_argument("--keep", type=int, default=5, help="Number of rolling backups to keep")
    p_db_restore = sub.add_parser("db-restore", help="Restore a verified SQLite backup")
    p_db_restore.add_argument("backup", help="Backup database file")
    p_db_restore.add_argument("--path", help="Optional target database path")
    p_db_restore.add_argument(
        "--yes",
        action="store_true",
        help="Confirm replacement of the target database after making a safety backup",
    )
    p_db_cleanup = sub.add_parser(
        "db-cleanup-preview",
        help="Preview likely test-generated projects without changing data",
    )
    p_db_cleanup.add_argument("--path", help="Optional database path")

    argv = sys.argv[1:]
    command_names = {
        "check",
        "version",
        "desktop",
        "mcp",
        "server",
        "smoke",
        "stress",
        "db-check",
        "db-backup",
        "db-restore",
        "db-cleanup-preview",
    }
    if not argv:
        argv = ["server"]
    elif argv[0] not in command_names and argv[0] not in {"-h", "--help"}:
        argv = ["server", *argv]

    args = parser.parse_args(argv)
    if not args.cmd:
        args.cmd = "server"

    if args.cmd == "version":
        print(APP_VERSION)
        return 0

    if args.cmd == "desktop":
        from electrochem_v6.desktop.shell import run_desktop
        return run_desktop(ROOT)

    if args.cmd == "mcp":
        from electrochem_v6.mcp_cli import run
        return run(args, runtime_root=ROOT)

    if args.cmd == "check":
        from electrochem_v6.app import run_check
        result = run_check()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    if args.cmd == "smoke":
        from electrochem_v6.smoke import run_smoke
        result = run_smoke(port=args.port)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    if args.cmd == "stress":
        from electrochem_v6.stress import run_stress_smoke
        result = run_stress_smoke(
            port=args.port,
            upload_workers=args.upload_workers,
            upload_requests=args.upload_requests,
            conversation_turns=args.conversation_turns,
            timeout_sec=args.timeout_sec,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    if args.cmd in {"db-check", "db-backup", "db-restore", "db-cleanup-preview"}:
        from electrochem_v6.store.database_maintenance import (
            backup_database,
            cleanup_preview,
            database_health,
            restore_database,
        )
        try:
            if args.cmd == "db-check":
                result = database_health(args.path)
            elif args.cmd == "db-backup":
                result = backup_database(
                    args.path,
                    backup_dir=args.backup_dir,
                    keep=args.keep,
                )
            elif args.cmd == "db-restore":
                result = restore_database(args.backup, args.path, confirmed=args.yes)
            else:
                result = cleanup_preview(args.path)
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    if args.cmd == "server":
        from electrochem_v6.server import V6ServerManager
        manager = V6ServerManager(port=args.port)
        ok, message = manager.start()
        print(message)
        if not ok:
            return 1
        print(f"ElectroChem {APP_VERSION} server running at http://127.0.0.1:{args.port} (Ctrl+C to stop)")
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
