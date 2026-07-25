"""
batch_lock.py — Per-batch advisory file lock for audit.json write safety.

Prevents concurrent modification of the same batch's audit.json by
serialising all write operations through an exclusive lock.

Usage:
    from app.utils.batch_lock import batch_write_lock

    with batch_write_lock(batch_id):
        audit = load_audit(batch_id)
        # ... modify audit ...
        write_json_atomic(audit_path, audit)

Lock properties:
  - Per-batch: each batch has its own lock
  - Exclusive: only one holder at a time
  - Auto-released on context exit or exception
  - POSIX: fcntl.flock() advisory lock
  - Windows: threading.Lock() per batch_id (single-process uvicorn)
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

# Batch ids whose lock the CURRENT thread already holds. batch_write_lock is
# non-reentrant on both platforms, so a second acquire on the same thread would
# deadlock. Code that must do a locked read-modify-write but may already be
# inside a batch_write_lock (e.g. timeline.log_event, called both inside and
# outside the lock across ~170 sites) checks holds_batch_lock() and only
# acquires when it is not already held. Thread-local: FastAPI runs sync
# endpoints in a threadpool, so each request is its own thread.
import threading as _threading_hold

_held = _threading_hold.local()


def _held_set() -> set:
    s = getattr(_held, "batches", None)
    if s is None:
        s = set()
        _held.batches = s
    return s


def holds_batch_lock(batch_id: str) -> bool:
    """True if the current thread already holds batch_write_lock(batch_id)."""
    return batch_id in _held_set()


def _lock_path(batch_id: str) -> Path:
    return settings.storage_root / "outputs" / batch_id / ".audit.lock"


if sys.platform == "win32":
    import threading as _threading

    _win_locks: dict[str, _threading.Lock] = {}
    _win_locks_guard = _threading.Lock()

    @contextmanager
    def batch_write_lock(
        batch_id: str,
        timeout_seconds: int = 30,
    ) -> Generator[None, None, None]:
        """Windows implementation using per-batch threading.Lock."""
        with _win_locks_guard:
            if batch_id not in _win_locks:
                _win_locks[batch_id] = _threading.Lock()
            lock = _win_locks[batch_id]
        if holds_batch_lock(batch_id):
            # Same thread already holds this batch's lock; re-acquiring the
            # non-reentrant Lock would deadlock. The existing hold already
            # serialises this critical section — proceed without a second lock.
            yield
            return
        acquired = lock.acquire(timeout=timeout_seconds)
        if not acquired:
            raise TimeoutError(
                f"Could not acquire batch lock for {batch_id} "
                f"within {timeout_seconds}s"
            )
        _held_set().add(batch_id)
        log.debug("[batch_lock] Acquired lock for %s", batch_id)
        try:
            yield
        finally:
            _held_set().discard(batch_id)
            lock.release()
            log.debug("[batch_lock] Released lock for %s", batch_id)

else:
    import fcntl as _fcntl

    @contextmanager
    def batch_write_lock(
        batch_id: str,
        timeout_seconds: int = 30,
    ) -> Generator[None, None, None]:
        """
        POSIX implementation using fcntl.flock().

        Uses LOCK_EX with a polling timeout.  The lock file is automatically
        released when the context exits (normal return, exception, or process
        crash — the OS closes the fd and releases the flock).

        Raises TimeoutError if the lock cannot be acquired within *timeout_seconds*.
        """
        if holds_batch_lock(batch_id):
            # Same thread already holds it. A second flock() from this process
            # on a fresh fd would block against its own lock — deadlock. The
            # outer hold already serialises this section.
            yield
            return

        lp = _lock_path(batch_id)
        lp.parent.mkdir(parents=True, exist_ok=True)

        fd = open(lp, "w")
        try:
            try:
                _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            except (BlockingIOError, OSError):
                deadline = time.monotonic() + timeout_seconds
                acquired = False
                while time.monotonic() < deadline:
                    time.sleep(0.05)
                    try:
                        _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
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

            _held_set().add(batch_id)
            log.debug("[batch_lock] Acquired lock for %s", batch_id)
            yield
        finally:
            _held_set().discard(batch_id)
            try:
                _fcntl.flock(fd, _fcntl.LOCK_UN)
            except Exception:
                pass
            fd.close()
            log.debug("[batch_lock] Released lock for %s", batch_id)
