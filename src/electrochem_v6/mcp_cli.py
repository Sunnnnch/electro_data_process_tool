"""Quiet stdio entry point; never start a GUI, database, or processing engine."""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence


@contextmanager
def _installer_guard() -> Iterator[None]:
    """Keep setup from replacing this process; do not acquire the data lock."""
    if os.name != "nt":
        yield
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_bool
    handle = kernel.CreateMutexW(None, False, "Local\\ElectroChemV6.Desktop")
    if not handle:
        raise OSError(ctypes.get_last_error(), "Unable to register the running MCP companion")
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.description = (
        "Connect an MCP host to an already open ElectroChem desktop using stdio. "
        "Access is read-only unless --allow-write is set. This command does not start the desktop."
    )
    parser.add_argument(
        "--data-dir", type=Path,
        help="Desktop data directory; by default use ELECTROCHEM_V6_DATA_DIR, portable.marker, or the user directory",
    )
    parser.add_argument(
        "--url", help="Optional explicit loopback HTTP service URL (for example http://127.0.0.1:8010)",
    )
    parser.add_argument(
        "--allow-write", action="store_true",
        help="Expose processing/submission tools that can write results; omitted by default",
    )


def run(args: argparse.Namespace, *, runtime_root: Path | None = None) -> int:
    if sys.stdin is None or sys.stdout is None or sys.stderr is None:
        # A windowed executable cannot carry the MCP stdio transport.
        return 2
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    try:
        from electrochem_v6.desktop.data import resolve_desktop_data_dir
        from electrochem_v6.mcp.server import run_server

        root = runtime_root or (
            Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2]
        )
        data_dir = args.data_dir.expanduser().resolve() if args.data_dir is not None else Path(
            resolve_desktop_data_dir(root)["path"]
        )
        with _installer_guard():
            run_server(base_url=args.url, data_dir=data_dir, allow_write=args.allow_write)
        return 0
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == "mcp" or exc.name.startswith("mcp.")):
            print("MCP support is missing. Install the project requirements, including mcp>=1.30,<2.", file=sys.stderr)
            return 2
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ElectroChem MCP: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


def main(argv: Sequence[str] | None = None, *, runtime_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="electrochem-mcp")
    add_arguments(parser)
    return run(parser.parse_args(argv), runtime_root=runtime_root)


if __name__ == "__main__":
    raise SystemExit(main())
