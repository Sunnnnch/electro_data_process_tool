"""Console companion for MCP hosts; stdio belongs exclusively to the protocol."""

from __future__ import annotations

import sys
from pathlib import Path


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(_runtime_root() / "src"))

from electrochem_v6.mcp_cli import main

if __name__ == "__main__":
    raise SystemExit(main(runtime_root=_runtime_root()))
