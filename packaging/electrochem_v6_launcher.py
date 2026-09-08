"""Windowed entry point for both source and packaged desktop clients."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(_runtime_root() / "src"))

from electrochem_v6.config import APP_NAME

APP_TITLE = f"ElectroChem｜{APP_NAME}"


def main() -> int:
    if "--environment-check" in sys.argv[1:]:
        from electrochem_v6.desktop.environment import run_environment_check
        parser = argparse.ArgumentParser(description="ElectroChem desktop environment diagnostics")
        parser.add_argument("--environment-check", action="store_true")
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--output", type=Path, help="Create a new report file; never overwrite an existing file")
        args = parser.parse_args()
        return run_environment_check(_runtime_root(), json_output=args.json, output_path=args.output,
                                     windowed=getattr(sys, "frozen", False) or sys.stdout is None)
    from electrochem_v6.desktop.shell import run_desktop
    return run_desktop(_runtime_root())


if __name__ == "__main__":
    raise SystemExit(main())
