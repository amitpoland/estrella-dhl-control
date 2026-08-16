"""Filesystem ACL helpers for the carrier DPAPI store (Windows).

LOCAL_MACHINE DPAPI ciphertext is decryptable by any process on the machine
that can *read* the files. ACLs are therefore part of the security boundary.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from .exceptions import CarrierCredentialError

log = logging.getLogger(__name__)

# Principals allowed full control on the store root when enforcing ACLs.
_ALLOWED_GRANT = (
    "NT AUTHORITY\\SYSTEM",
    "BUILTIN\\Administrators",
)


def _run_icacls(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["icacls", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def harden_directory_acls(path: Path) -> None:
    """Break inheritance; grant SYSTEM + Administrators only (F)."""
    if sys.platform != "win32":
        return
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    r1 = _run_icacls([str(path), "/inheritance:r"])
    if r1.returncode != 0:
        raise CarrierCredentialError(
            "failed to break ACL inheritance on credential store root"
        )
    for principal in _ALLOWED_GRANT:
        r = _run_icacls([str(path), "/grant:r", f"{principal}:(OI)(CI)(F)"])
        if r.returncode != 0:
            raise CarrierCredentialError(
                f"failed to grant ACL to {principal} on credential store root"
            )
    # Remove other explicit ACEs that survive inheritance break on some hosts.
    # /remove fails harmlessly when ACE absent.
    for principal in (
        "BUILTIN\\Users",
        "NT AUTHORITY\\Authenticated Users",
        "Everyone",
    ):
        _run_icacls([str(path), "/remove:g", principal])


def assert_store_root_secure(path: Path) -> None:
    """Fail closed if store root is readable by Users / Everyone / Authenticated Users."""
    if sys.platform != "win32":
        return
    path = Path(path)
    if not path.is_dir():
        raise CarrierCredentialError("credential store root does not exist")
    proc = _run_icacls([str(path)])
    if proc.returncode != 0:
        raise CarrierCredentialError("unable to inspect credential store ACLs")
    text = (proc.stdout or "").upper()
    forbidden_markers = (
        "BUILTIN\\USERS:",
        "NT AUTHORITY\\AUTHENTICATED USERS:",
        "EVERYONE:",
        "\\USERS:(",
    )
    for marker in forbidden_markers:
        if marker in text:
            raise CarrierCredentialError(
                "credential store root ACL is too open for LOCAL_MACHINE DPAPI "
                "(Users/Everyone/Authenticated Users can read ciphertext)"
            )


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via unique temp sibling then os.replace (never Path.with_suffix)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise
