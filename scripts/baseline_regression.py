#!/usr/bin/env python
"""Run quick/full baseline regression checks for v5/v6."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List


SCRIPT_PATH = Path(__file__).resolve()
V6_ROOT = SCRIPT_PATH.parents[1]
REPORT_DIR = V6_ROOT / "reports"


@dataclass
class CheckResult:
    name: str
    command: List[str]
    returncode: int
    ok: bool
    duration_sec: float
    stdout_tail: str
    stderr_tail: str


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _tail(text: str, max_lines: int = 40) -> str:
    lines = (text or "").splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[-max_lines:])


def run_check(name: str, command: List[str], timeout_sec: int = 300) -> CheckResult:
    started = datetime.now()
    proc = subprocess.run(
        command,
        cwd=str(V6_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
    )
    ended = datetime.now()
    duration = (ended - started).total_seconds()
    return CheckResult(
        name=name,
        command=command,
        returncode=proc.returncode,
        ok=(proc.returncode == 0),
        duration_sec=duration,
        stdout_tail=_tail(proc.stdout),
        stderr_tail=_tail(proc.stderr),
    )


def build_commands(py: str, full: bool) -> List[tuple[str, List[str]]]:
    smoke_port = _free_port()
    commands: List[tuple[str, List[str]]] = [
        ("v6_help", [py, "run_v6.py", "--help"]),
        ("v6_check", [py, "run_v6.py", "check"]),
        ("v6_smoke", [py, "run_v6.py", "smoke", "--port", str(smoke_port)]),
        (
            "v6_server_tests",
            [py, "-m", "pytest", "-q", "tests/test_v6_server.py"],
        ),
    ]
    if full:
        commands.append(("repo_pytest", [py, "-m", "pytest", "-q"]))
    return commands


def write_report(payload: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    latest = REPORT_DIR / "baseline_regression_latest.json"
    stamped = REPORT_DIR / f"baseline_regression_{ts}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    latest.write_text(text, encoding="utf-8")
    stamped.write_text(text, encoding="utf-8")
    return latest


def main() -> int:
    parser = argparse.ArgumentParser(description="Run v5/v6 baseline regression checks")
    parser.add_argument("--full", action="store_true", help="Include full repository pytest run")
    args = parser.parse_args()

    py = sys.executable
    commands = build_commands(py=py, full=args.full)
    results: List[CheckResult] = []

    for name, command in commands:
        print(f"[RUN] {name}: {' '.join(command)}")
        try:
            result = run_check(name, command)
        except subprocess.TimeoutExpired:
            result = CheckResult(
                name=name,
                command=command,
                returncode=124,
                ok=False,
                duration_sec=0.0,
                stdout_tail="",
                stderr_tail="Timeout expired",
            )
        results.append(result)
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {name} ({result.duration_sec:.1f}s)")

    all_ok = all(item.ok for item in results)
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "full" if args.full else "quick",
        "python": py,
        "repo_root": str(V6_ROOT),
        "all_ok": all_ok,
        "checks": [
            {
                "name": item.name,
                "command": item.command,
                "returncode": item.returncode,
                "ok": item.ok,
                "duration_sec": round(item.duration_sec, 3),
                "stdout_tail": item.stdout_tail,
                "stderr_tail": item.stderr_tail,
            }
            for item in results
        ],
    }

    report_path = write_report(report)
    print(f"[REPORT] {report_path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
