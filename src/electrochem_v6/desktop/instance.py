"""OS-held single-instance lease and authenticated loopback activation."""

from __future__ import annotations

import ctypes
import json
import os
import secrets
import socket
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO, Callable

APP_MUTEX = "Local\\ElectroChemV6.Desktop"


class SingleInstance:
    def __init__(self, data_dir: Path, activate: Callable[[], None]) -> None:
        self.data_dir = Path(data_dir)
        self._activate = activate
        self._handle: BinaryIO | None = None
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._mutex: Any = None
        self._token = secrets.token_urlsafe(32)

    @property
    def metadata_path(self) -> Path:
        return self.data_dir / "desktop-instance.json"

    def acquire(self) -> bool:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        handle = (self.data_dir / ".desktop-instance.lock").open("a+b")
        if handle.seek(0, 2) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        try:
            self._hold_installer_mutex()
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            listener.listen(5)
            listener.settimeout(0.3)
            self._socket = listener
            payload = {"pid": os.getpid(), "port": listener.getsockname()[1], "token": self._token}
            temporary = self.metadata_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(temporary, self.metadata_path)
            self._thread = threading.Thread(target=self._serve, daemon=True, name="electrochem-activation")
            self._thread.start()
        except Exception:
            self.close()
            raise
        return True

    def _hold_installer_mutex(self) -> None:
        if os.name != "nt":
            return
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        self._mutex = kernel.CreateMutexW(None, False, APP_MUTEX)
        if not self._mutex:
            raise OSError(ctypes.get_last_error(), "Unable to create application mutex")

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                assert self._socket is not None
                connection, _ = self._socket.accept()
            except (OSError, AssertionError):
                continue
            with connection:
                connection.settimeout(1)
                try:
                    raw = connection.recv(4096)
                    request = json.loads(raw.decode("utf-8"))
                    if not isinstance(request, dict) or request.get("action") != "activate":
                        continue
                    if not secrets.compare_digest(str(request.get("token", "")), self._token):
                        continue
                    self._activate()
                    connection.sendall(b'{"status":"success"}')
                except (ValueError, OSError):
                    pass

    def activate_existing(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                info = json.loads(self.metadata_path.read_text(encoding="utf-8"))
                if os.name == "nt":
                    ctypes.windll.user32.AllowSetForegroundWindow(int(info["pid"]))
                with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=1) as client:
                    client.sendall(json.dumps({"action": "activate", "token": info["token"]}).encode())
                    if json.loads(client.recv(4096)).get("status") == "success":
                        return True
            except (OSError, ValueError, KeyError, TypeError):
                time.sleep(0.1)
        return False

    def close(self) -> None:
        self._stop.set()
        if self._socket:
            self._socket.close()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        if self._handle:
            try:
                self.metadata_path.unlink(missing_ok=True)
                self._handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()
                self._handle = None
        if self._mutex:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(self._mutex)
            self._mutex = None
