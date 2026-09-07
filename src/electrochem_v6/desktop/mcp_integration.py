"""Discover the running desktop service and produce local MCP client settings."""

from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
from pathlib import Path
from typing import Any

SERVICE_FILE = "desktop-service.json"


class DesktopServiceDiscovery:
    """Publish only while this shell owns its data-directory instance lease."""

    def __init__(self, data_dir: Path, port: int, session_token: str) -> None:
        self.path = Path(data_dir) / SERVICE_FILE
        self.token = session_token
        self.payload = {"version": 1, "pid": os.getpid(), "url": f"http://127.0.0.1:{port}",
                        "session_token": session_token}

    def publish(self) -> None:
        # A private temporary file and atomic replacement prevent partially read
        # connection details. On Windows the file inherits the data folder ACL.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".desktop-service-", suffix=".tmp", delete=False) as stream:
                temporary = stream.name
                json.dump(self.payload, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)

    def close(self) -> None:
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(current, dict) and secrets.compare_digest(str(current.get("session_token", "")), self.token):
                self.path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            pass


def client_configuration(runtime_root: Path, data_dir: Path, *, allow_write: bool = False,
                         frozen: bool | None = None, executable: str | None = None) -> dict[str, Any]:
    """Return a launch configuration, never the service's authentication token."""
    if type(allow_write) is not bool:
        raise ValueError("allow_write must be a boolean")
    runtime_root = Path(runtime_root).resolve()
    data_dir = Path(data_dir).resolve()
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if frozen:
        command = runtime_root / "ElectroChem-MCP.exe"
        args: list[str] = []
        available = command.is_file()
    else:
        command = Path(executable or sys.executable).resolve()
        if command.name.lower() == "pythonw.exe":
            command = command.with_name("python.exe")
        runner = runtime_root / "run_v6.py"
        args = [str(runner), "mcp"]
        available = command.is_file() and runner.is_file()
    args.extend(["--data-dir", str(data_dir)])
    if allow_write:
        args.append("--allow-write")
    config = {"mcpServers": {"electrochem": {"command": str(command), "args": args}}}
    return {"status": "success", "transport": "stdio", "read_only": not allow_write,
            "available": available, "data_dir": str(data_dir), "client_config": config}
