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

import fcntl
import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from ..core.config import settings

log = logging.getLogger(__name__)


def _lock_path(batch_id: str) -> Path:
    return settings.storage_root / "outputs" / batch_id / ".audit.lock"


@contextmanager
def batch_write_lock(
    batch_id: str,
    timeout_seconds: int = 30,
) -> Generator[None, None, None]:
    """
    Acquire an exclusive per-batch lock before writing to audit.json.

    Uses fcntl.flock(LOCK_EX) with a polling timeout.  The lock file is
    automatically released when the context exits (normal return, exception,
    or process crash — the OS closes the fd and releases the flock).

    Raises TimeoutError if the lock cannot be acquired within *timeout_seconds*.
    """
    lp = _lock_path(batch_id)
    lp.parent.mkdir(parents=True, exist_ok=True)

    fd = open(lp, "w")
    try:
        # Try non-blocking first
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            # Lock held by another process — poll until timeout
            deadline = time.monotonic() + timeout_seconds
            acquired = False
            while time.monotonic() < deadline:
                time.sleep(0.05)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
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
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        fd.close()
        log.debug("[batch_lock] Released lock for %s", batch_id)
