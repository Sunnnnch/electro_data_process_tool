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
    from electrochem_v6.config import APP_VERSION

    parser = argparse.ArgumentParser(description="ElectroChem macOS desktop")
    parser.add_argument("--version", action="version", version=APP_VERSION)
    parser.add_argument("--environment-check", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.environment_check:
        from electrochem_v6.desktop.environment import run_environment_check
        return run_environment_check(runtime_root(), json_output=args.json, output_path=args.output, windowed=False)
    if args.json or args.output:
        parser.error("--json and --output require --environment-check")
    from electrochem_v6.desktop.shell import run_desktop
    return run_desktop(runtime_root())


if __name__ == "__main__":
    raise SystemExit(main())
