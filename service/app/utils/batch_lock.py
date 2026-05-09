"""
batch_lock.py — Per-batch advisory file lock for audit.json write safety.

Prevents concurrent modification of the same batch's audit.json by
serialising all write operations through an exclusive fcntl.flock() lock.

Usage:
    from app.utils.batch_lock import batch_write_lock

    with batch_write_lock(batch_id):
        audit = load_audit(batch_id)
        # ... modify audit ...
        write_json_atomic(audit_path, audit)

Lock properties:
  - Per-batch: each batch has its own `.audit.lock` file
  - Exclusive: only one holder at a time
  - Auto-released on context exit, exception, or process crash
  - POSIX advisory lock via fcntl.flock()
"""
from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from ..core.config import settings

log = logging.getLogger(__name__)

if sys.platform != "win32":
    import fcntl
    _USE_FCNTL = True
else:
    import msvcrt
    _USE_FCNTL = False


def _lock_path(batch_id: str) -> Path:
    return settings.storage_root / "outputs" / batch_id / ".audit.lock"


@contextmanager
def batch_write_lock(
    batch_id: str,
    timeout_seconds: int = 30,
) -> Generator[None, None, None]:
    """
    Acquire an exclusive per-batch lock before writing to audit.json.

    Uses fcntl.flock on POSIX, msvcrt.locking on Windows.
    Auto-released on context exit, exception, or process crash.

    Raises TimeoutError if the lock cannot be acquired within *timeout_seconds*.
    """
    lp = _lock_path(batch_id)
    lp.parent.mkdir(parents=True, exist_ok=True)

    if _USE_FCNTL:
        fd = open(lp, "w")
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[name-defined]
            except (BlockingIOError, OSError):
                deadline = time.monotonic() + timeout_seconds
                acquired = False
                while time.monotonic() < deadline:
                    time.sleep(0.05)
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[name-defined]
                        acquired = True
                        break
                    except (BlockingIOError, OSError):
                        continue
                if not acquired:
                    fd.close()
                    raise TimeoutError(
                        f"Could not acquire batch lock for {batch_id} "
                        f"within {timeout_seconds}s"
                    )
            log.debug("[batch_lock] Acquired lock for %s", batch_id)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)  # type: ignore[name-defined]
            except Exception:
                pass
            fd.close()
            log.debug("[batch_lock] Released lock for %s", batch_id)
    else:
        # Windows: use msvcrt byte-range lock on the lock file
        fd = open(lp, "w")
        deadline = time.monotonic() + timeout_seconds
        acquired = False
        while time.monotonic() < deadline:
            try:
                msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[name-defined]
                acquired = True
                break
            except OSError:
                time.sleep(0.05)
        if not acquired:
            fd.close()
            raise TimeoutError(
                f"Could not acquire batch lock for {batch_id} "
                f"within {timeout_seconds}s"
            )
        log.debug("[batch_lock] Acquired lock for %s (win32)", batch_id)
        try:
            yield
        finally:
            try:
                msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[name-defined]
            except Exception:
                pass
            fd.close()
            log.debug("[batch_lock] Released lock for %s (win32)", batch_id)
