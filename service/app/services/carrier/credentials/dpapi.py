"""Windows DPAPI seal/unseal via ctypes — no third-party crypto deps.

Uses CRYPTPROTECT_LOCAL_MACHINE so NSSM PZService (non-interactive) can decrypt.
Never log plaintext. Fail closed on non-Windows.
"""
from __future__ import annotations

import sys
from typing import Optional

from .exceptions import CarrierCredentialError

CRYPTPROTECT_LOCAL_MACHINE = 0x4
CRYPTPROTECT_UI_FORBIDDEN = 0x1


def dpapi_available() -> bool:
    return sys.platform == "win32"


def _protect_unprotect(plaintext: Optional[bytes], ciphertext: Optional[bytes], *, description: Optional[str]) -> bytes:
    from ctypes import (  # noqa: WPS433 — Windows-only
        POINTER,
        Structure,
        byref,
        c_char,
        cast,
        create_string_buffer,
        windll,
        wintypes,
        c_void_p,
    )

    class DATA_BLOB(Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", POINTER(c_char))]

    def blob_from_bytes(data: bytes) -> DATA_BLOB:
        buf = create_string_buffer(data, len(data))
        return DATA_BLOB(len(data), cast(buf, POINTER(c_char)))

    def bytes_from_blob(blob: DATA_BLOB) -> bytes:
        if not blob.pbData or blob.cbData == 0:
            return b""
        return bytes(bytearray(blob.pbData[: blob.cbData]))

    def local_free(blob: DATA_BLOB) -> None:
        if blob.pbData:
            windll.kernel32.LocalFree(cast(blob.pbData, c_void_p))

    crypt32 = windll.crypt32
    out_blob = DATA_BLOB()
    flags = CRYPTPROTECT_UI_FORBIDDEN

    if plaintext is not None:
        in_blob = blob_from_bytes(plaintext)
        flags |= CRYPTPROTECT_LOCAL_MACHINE
        ok = crypt32.CryptProtectData(
            byref(in_blob),
            description,
            None,
            None,
            None,
            flags,
            byref(out_blob),
        )
        if not ok:
            raise CarrierCredentialError("CryptProtectData failed")
    else:
        assert ciphertext is not None
        in_blob = blob_from_bytes(ciphertext)
        ok = crypt32.CryptUnprotectData(
            byref(in_blob),
            None,
            None,
            None,
            None,
            flags,
            byref(out_blob),
        )
        if not ok:
            raise CarrierCredentialError("CryptUnprotectData failed")

    try:
        return bytes_from_blob(out_blob)
    finally:
        local_free(out_blob)


def protect(plaintext: bytes, *, description: Optional[str] = None) -> bytes:
    if not dpapi_available():
        raise CarrierCredentialError("DPAPI available only on Windows")
    if not plaintext:
        raise CarrierCredentialError("refuse to seal empty payload")
    return _protect_unprotect(plaintext, None, description=description)


def unprotect(ciphertext: bytes) -> bytes:
    if not dpapi_available():
        raise CarrierCredentialError("DPAPI available only on Windows")
    if not ciphertext:
        raise CarrierCredentialError("refuse to unseal empty ciphertext")
    return _protect_unprotect(None, ciphertext, description=None)
