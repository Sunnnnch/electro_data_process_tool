"""Windowed entry point for both source and packaged desktop clients."""
from __future__ import annotations

import sys
from pathlib import Path


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(_runtime_root() / "src"))

from electrochem_v6.config import APP_NAME
from electrochem_v6.desktop.shell import run_desktop

APP_TITLE = f"ElectroChem｜{APP_NAME}"


def main() -> int:
    return run_desktop(_runtime_root())


if __name__ == "__main__":
    raise SystemExit(main())
