"""Finder entry point; diagnostic commands do not start a window or service."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def main() -> int:
    if sys.platform != "darwin":
        raise SystemExit("The macOS launcher must run on macOS.")
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(runtime_root() / "src"))
    parser = argparse.ArgumentParser(description="ElectroChem macOS desktop")
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--version", action="store_true")
    commands.add_argument("--environment-check", action="store_true")
    commands.add_argument("--desktop-smoke", action="store_true", help="Run isolated native desktop acceptance; --output must be a new directory")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.desktop_smoke:
        if not args.output or args.json:
            parser.error("--desktop-smoke requires --output <new directory>; --json is not supported")
        from smoke_macos_desktop import run_smoke
        return run_smoke(args.output, runtime_root())
    if args.version:
        from electrochem_v6.config import APP_VERSION
        print(APP_VERSION)
        return 0
    if args.environment_check:
        from electrochem_v6.desktop.environment import run_environment_check
        return run_environment_check(runtime_root(), json_output=args.json, output_path=args.output, windowed=False)
    if args.json or args.output:
        parser.error("--json and --output require --environment-check or --desktop-smoke")
    from electrochem_v6.desktop.shell import run_desktop
    return run_desktop(runtime_root())


if __name__ == "__main__":
    raise SystemExit(main())
