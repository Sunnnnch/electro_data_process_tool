"""Cross-thread/process leases for upload directories, released on process exit."""

from __future__ import annotations

import os
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

from electrochem_v6.config import user_config_dir

_LOCK = threading.RLock()
_LOCAL = threading.local()
_LEASES: dict[Path, BinaryIO] = {}
_LEASE_NAME = ".active-upload.lock"


def _lock_file(handle: BinaryIO, *, blocking: bool) -> bool:
    handle.seek(0)
    deadline = time.monotonic() + 10
    while True:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError as exc:
            if not blocking:
                return False
            if time.monotonic() >= deadline:
                # Upload endpoints already return ValueError details as a
                # retryable user-facing 400 instead of a generic server error.
                raise ValueError("存储维护正在进行，请稍后重试") from exc
            time.sleep(0.05)


def _open_lock(path: Path) -> BinaryIO:
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    return handle


@contextmanager
def artifact_storage_operation() -> Iterator[None]:
    """Serialize upload reservation and cleanup, including other app processes."""
    with _LOCK:
        if getattr(_LOCAL, "inside", False):
            yield
            return
        root = user_config_dir() / "runs"
        root.mkdir(parents=True, exist_ok=True)
        with _open_lock(root / ".artifact-storage.lock") as handle:
            _lock_file(handle, blocking=True)
            _LOCAL.inside = True
            try:
                yield
            finally:
                _LOCAL.inside = False


def create_active_upload_root(path: Path) -> None:
    """Publish a directory only while holding both its lease and the storage lock."""
    with artifact_storage_operation():
        path = path.resolve()
        path.mkdir(parents=True, exist_ok=False)
        handle = _open_lock(path / _LEASE_NAME)
        try:
            _lock_file(handle, blocking=True)
        except BaseException:
            handle.close()
            raise
        _LEASES[path] = handle


def upload_root_is_active(path: Path) -> bool:
    """Call under artifact_storage_operation; dead-process lease files are inactive."""
    path = path.resolve()
    if path in _LEASES:
        return True
    lease = path / _LEASE_NAME
    if not lease.is_file():
        return False
    try:
        with lease.open("r+b") as handle:
            return not _lock_file(handle, blocking=False)
    except OSError:
        # A busy/unreadable lease is never evidence that deletion is safe.
        return True


def release_upload_root(path: str | Path) -> bool:
    """Release only this process's reservation; repeat calls are harmless."""
    with artifact_storage_operation():
        handle = _LEASES.pop(Path(path).resolve(), None)
        if handle is None:
            return False
        handle.close()
        return True


def finish_uploaded_run(path: str | Path, *, keep: bool = False) -> None:
    """Release an owned upload and discard unsuccessful work before cleanup can race."""
    with artifact_storage_operation():
        owned = release_upload_root(path)
        if owned and not keep:
            shutil.rmtree(Path(path).resolve(), ignore_errors=True)
