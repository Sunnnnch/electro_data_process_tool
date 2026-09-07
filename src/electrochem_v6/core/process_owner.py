"""Process identities for recovery; elapsed time is never evidence of death."""

from __future__ import annotations

import errno
import hashlib
import os
import platform
from pathlib import Path
from typing import Any


def _host_identity() -> str | None:
    try:
        if os.name == "nt":
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                identity = str(winreg.QueryValueEx(key, "MachineGuid")[0])
        else:
            identity = Path("/etc/machine-id").read_text(encoding="ascii").strip()
        return hashlib.sha256((platform.system() + ":" + identity).encode()).hexdigest() if identity else None
    except (OSError, ImportError):
        return None


def _probe_process(pid: int) -> dict[str, Any]:
    if pid <= 0:
        return {"state": "unknown", "reason": "invalid_pid"}
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
        kernel.GetProcessTimes.restype = wintypes.BOOL
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        handle = kernel.OpenProcess(0x00100000 | 0x1000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            return {"state": "dead", "reason": "pid_absent"} if error == 87 else {"state": "unknown", "reason": "process_access_unavailable"}
        try:
            if kernel.WaitForSingleObject(handle, 0) == 0:
                return {"state": "dead", "reason": "process_exited"}
            created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
                return {"state": "unknown", "reason": "creation_identity_unavailable"}
            token = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
            return {"state": "alive", "start_token": str(token), "reason": "process_present"}
        finally:
            kernel.CloseHandle(handle)
    if platform.system() == "Linux":
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            fields = stat[stat.rfind(")") + 2:].split()
            boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
            if fields[0] in {"Z", "X"}:
                return {"state": "dead", "reason": "process_exited"}
            return {"state": "alive", "start_token": boot + ":" + fields[19], "reason": "process_present"}
        except (OSError, IndexError):
            pass
    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return {"state": "dead", "reason": "pid_absent"}
    return {"state": "unknown", "reason": "creation_identity_unavailable"}


def current_process_owner() -> dict[str, Any]:
    observed = _probe_process(os.getpid())
    return {"schema_version": "1", "pid": os.getpid(), "host_id": _host_identity(),
            "start_token": observed.get("start_token")}


def inspect_process_owner(owner: Any) -> dict[str, str]:
    if not isinstance(owner, dict) or not owner.get("host_id") or not owner.get("start_token"):
        return {"state": "unknown", "reason": "owner_identity_missing"}
    if owner["host_id"] != _host_identity():
        return {"state": "unknown", "reason": "different_or_unavailable_host"}
    try:
        pid = int(owner["pid"])
    except (KeyError, TypeError, ValueError):
        return {"state": "unknown", "reason": "invalid_pid"}
    observed = _probe_process(pid)
    if observed["state"] == "alive" and observed.get("start_token") != owner["start_token"]:
        return {"state": "dead", "reason": "pid_reused_after_owner_exit"}
    return {"state": observed["state"], "reason": observed["reason"]}
