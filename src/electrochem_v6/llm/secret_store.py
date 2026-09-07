"""OS-backed protection for persisted LLM credentials."""

from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes

_DPAPI_PREFIX = "dpapi:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _windows_dpapi(value: bytes, *, decrypt: bool) -> bytes:
    buffer = ctypes.create_string_buffer(value)
    input_blob = _DataBlob(
        len(value),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if decrypt:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
    else:
        ok = crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            "ElectroChem V6 LLM credential",
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
    if not ok:
        raise OSError(ctypes.get_last_error(), "Windows DPAPI operation failed")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def protect_secret(value: str) -> str | None:
    """Protect a secret for the current Windows user, if supported."""
    text = str(value or "")
    if not text:
        return ""
    if os.name != "nt":
        return None
    encrypted = _windows_dpapi(text.encode("utf-8"), decrypt=False)
    return _DPAPI_PREFIX + base64.b64encode(encrypted).decode("ascii")


def secret_protection_available() -> bool:
    """Return whether this runtime can persist secrets without plaintext."""
    return os.name == "nt"


def unprotect_secret(value: str) -> str | None:
    """Decrypt a value produced by :func:`protect_secret`."""
    text = str(value or "")
    if not text:
        return ""
    if not text.startswith(_DPAPI_PREFIX) or os.name != "nt":
        return None
    encrypted = base64.b64decode(text[len(_DPAPI_PREFIX) :], validate=True)
    return _windows_dpapi(encrypted, decrypt=True).decode("utf-8")


__all__ = ["protect_secret", "secret_protection_available", "unprotect_secret"]
